"""SISL framer / deframer — pure-numpy DSP for the hackathon demo.

Implements the TX and RX chip-rate DSP for the SISL DSSS hailing channel,
independent of GNU Radio. The same functions are reused by the Phase 1
hidden-signal demo (`sisl_dsss_demo.py`) and the Phase 2 handshake flowgraph
(`sisl_hail_flow.py`) via thin GR wrappers.

Signal chain:

    TX: bytes → MSB-first bit unpack → BPSK symbols (±1)
              → repeat each symbol 1023 times → multiply by spreading code
              → int8 chip stream

    RX: chip stream → reshape into (n_symbols, 1023) → row-dot with local
        code → sign decision → MSB-first bit pack → bytes

Acquisition (sliding correlator, matched-filter frame detection) is NOT
implemented here. Per Hackathon.md §1.3 and §Risks, the Phase 1 demo
assumes chip-aligned start on both ends. For production or a real receiver,
add a sliding correlator on top of this module.

The spreading code is the public hailing code from SISL v3 §4.6.1, generated
by `sisl_dsss.hail_code_seed()` + `sisl_dsss.generate_dsss_code()`. Callers
may supply a session-derived code for the Phase 3 P2P channel.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

# scipy is a HARD requirement — the matched-filter correlator must be
# FFT-based for real-time DSP. A numpy np.convolve fallback on multi-
# million-sample streams takes seconds per block and silently causes
# HackRF overflow in the live-RX path. Fail loudly at import.
try:
    from scipy.signal import fftconvolve as _fftconvolve
except ImportError as e:
    raise ImportError(
        "sisl_framer requires scipy for FFT-based DSP. "
        "Install with: pip install scipy  "
        "(or on Arch: sudo pacman -S python-scipy)"
    ) from e

import sisl_dsss as sd

CHIPS_PER_SYMBOL = 1023


# ── Spreading code helpers ──────────────────────────────────────────────────


def code_from_seed(seed: bytes, length: int = CHIPS_PER_SYMBOL) -> np.ndarray:
    return np.array(sd.generate_dsss_code(seed, length=length), dtype=np.int8)


DEFAULT_PUBLIC_CODE: np.ndarray = code_from_seed(sd.hail_code_seed())
DEFAULT_PUBLIC_CODE.flags.writeable = False


def public_hail_code() -> np.ndarray:
    """Return the public SISL hailing spreading code as int8 ±1 array."""
    return DEFAULT_PUBLIC_CODE


# ── Byte/bit packing ────────────────────────────────────────────────────────

def bytes_to_bits(data: bytes) -> np.ndarray:
    """MSB-first unpack. Returns uint8 array of 0/1."""
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def bits_to_bytes(bits: np.ndarray) -> bytes:
    """MSB-first pack. Bits must be a multiple of 8 in length."""
    if len(bits) % 8 != 0:
        raise ValueError(f"bit count {len(bits)} not a multiple of 8")
    return np.packbits(bits.astype(np.uint8)).tobytes()


# ── Differential bit encoding (for DBPSK) ───────────────────────────────────
#
# DBPSK eliminates the absolute-phase requirement by encoding each bit as
# a TRANSITION (or non-transition) of the previous symbol, rather than as
# an absolute symbol value. The receiver decodes via the differential dot
# product Re(y_k · conj(y_{k−1})), which depends only on the inter-symbol
# phase difference and is insensitive to a global phase rotation.
#
# Encoder:    e_{−1} = seed
#             e_k    = e_{k−1} XOR b_k
# Decoder:    b_k    = sign(Re(y_k · conj(y_{k−1}))) → 0 if positive, 1 if neg
#
# This file provides the bit-domain primitives. The DBPSK demodulator
# (dbpsk_decode_from_pilot, defined below) uses them to recover bits from
# complex peak values after V-V drift correction.
#
# Use case in SISL FEC: the 48-bit uncoded header stays coherent (the pilot
# fit needs un-encoded symbols to estimate θ₀), and the 2048-bit FEC body
# is differentially encoded with seed = the last header bit, so the first
# body bit's differential decode anchors on the receiver's coherent estimate
# of the last pilot symbol.

def differential_encode_bits(bits: np.ndarray, seed: int = 0) -> np.ndarray:
    """Differentially encode a uint8 0/1 bit array.

    e_{−1} = seed (0 or 1)
    e_k    = e_{k−1} XOR bits[k]   for k = 0 .. N−1

    Returns the encoded bit array with the same shape and dtype as `bits`.
    """
    bits = np.ascontiguousarray(bits, dtype=np.uint8)
    if bits.ndim != 1:
        raise ValueError(f"bits must be 1-D, got shape {bits.shape}")
    out = np.empty_like(bits)
    prev = int(seed) & 1
    for k in range(len(bits)):
        prev = prev ^ int(bits[k])
        out[k] = prev
    return out


def differential_decode_bits(bits: np.ndarray, seed: int = 0) -> np.ndarray:
    """Inverse of differential_encode_bits, on hard-decided bit values.

    b_k = bits[k] XOR bits[k−1]    for k = 1 .. N−1
    b_0 = bits[0] XOR seed

    This is the bit-domain inverse, used for testing and for paths that
    do not have soft LLR access. The DBPSK soft demodulator computes the
    LLRs directly via differential dot products and bypasses this.
    """
    bits = np.ascontiguousarray(bits, dtype=np.uint8)
    if bits.ndim != 1:
        raise ValueError(f"bits must be 1-D, got shape {bits.shape}")
    out = np.empty_like(bits)
    prev = int(seed) & 1
    for k in range(len(bits)):
        out[k] = int(bits[k]) ^ prev
        prev = int(bits[k])
    return out


# ── TX: bytes → chip stream ─────────────────────────────────────────────────

def tx_bytes_to_chips(data: bytes,
                      code: Optional[np.ndarray] = None) -> np.ndarray:
    """Spread `data` into an int8 bipolar chip stream.

    BPSK mapping: bit 0 → +1, bit 1 → -1. Each symbol is multiplied by the
    full spreading code, so one byte produces 8 * CHIPS_PER_SYMBOL chips.
    """
    if code is None:
        code = DEFAULT_PUBLIC_CODE
    if len(code) != CHIPS_PER_SYMBOL:
        raise ValueError(f"code length {len(code)} != {CHIPS_PER_SYMBOL}")

    return tx_bits_to_chips(bytes_to_bits(data), code)


def tx_bits_to_chips(bits: np.ndarray,
                     code: Optional[np.ndarray] = None) -> np.ndarray:
    """Spread an arbitrary-length bit array into an int8 bipolar chip stream.

    Bits must be a uint8 array of 0/1 values; length need NOT be a multiple
    of 8. Required for FEC-coded payloads whose codeword length isn't
    byte-aligned. BPSK mapping (matches tx_bytes_to_chips): bit 0 → +1,
    bit 1 → -1. Each bit produces CHIPS_PER_SYMBOL chips.
    """
    if code is None:
        code = DEFAULT_PUBLIC_CODE
    if len(code) != CHIPS_PER_SYMBOL:
        raise ValueError(f"code length {len(code)} != {CHIPS_PER_SYMBOL}")

    bits = np.asarray(bits)
    if bits.size == 0:
        return np.empty(0, dtype=np.int8)
    if bits.dtype != np.uint8:
        bits = bits.astype(np.uint8)
    if not np.all((bits == 0) | (bits == 1)):
        raise ValueError("bits array must contain only 0/1 values")

    symbols = (1 - 2 * bits.astype(np.int8))
    chips = (symbols[:, None] * code[None, :]).reshape(-1)
    return chips.astype(np.int8)


# ── RX: chip stream → bytes ─────────────────────────────────────────────────

def rx_chips_to_bytes(chips: np.ndarray, n_bytes: int,
                      code: Optional[np.ndarray] = None) -> bytes:
    """Despread a chip-aligned stream into bytes.

    `chips` must contain at least `n_bytes * 8 * CHIPS_PER_SYMBOL` samples
    starting at chip 0 of the first symbol. Accepts float or int input.
    """
    if code is None:
        code = DEFAULT_PUBLIC_CODE

    n_bits = n_bytes * 8
    return bits_to_bytes(rx_chips_to_bits(chips, n_bits, code))


def rx_chips_to_bits(chips: np.ndarray, n_bits: int,
                     code: Optional[np.ndarray] = None) -> np.ndarray:
    """Despread a chip-aligned stream into an arbitrary-length bit array.

    `chips` must contain at least `n_bits * CHIPS_PER_SYMBOL` samples
    starting at chip 0 of the first symbol. Returns uint8 array of 0/1
    values, length n_bits. Required for FEC-coded payloads whose decoded
    length isn't byte-aligned.
    """
    if code is None:
        code = DEFAULT_PUBLIC_CODE

    if n_bits == 0:
        return np.empty(0, dtype=np.uint8)

    needed = n_bits * CHIPS_PER_SYMBOL
    if len(chips) < needed:
        raise ValueError(f"need {needed} chips, got {len(chips)}")

    mat = np.asarray(chips[:needed], dtype=np.float32).reshape(
        n_bits, CHIPS_PER_SYMBOL
    )
    corr = mat @ code.astype(np.float32)
    return (corr < 0).astype(np.uint8)


# ── Sliding-correlator acquisition (Phase 2/3, optional) ────────────────────

def matched_filter_magnitude(chips: np.ndarray,
                              code: Optional[np.ndarray] = None) -> np.ndarray:
    """Return |correlation| of `chips` against one period of the spreading code.

    Chip-rate matched filter. `chips` is expected to already be decimated
    to one sample per chip, chip-aligned at the start. For sample-rate
    input (unknown sub-chip phase), use `matched_filter_magnitude_sample_rate`
    instead — it is phase-agnostic and runs in a single pass.

    Output length = len(chips) - len(code) + 1.
    """
    if code is None:
        code = DEFAULT_PUBLIC_CODE
    chips_f = np.asarray(chips, dtype=np.float32)
    code_f = code.astype(np.float32)
    if len(chips_f) < len(code_f):
        return np.zeros(0, dtype=np.float32)
    kernel = code_f[::-1]
    corr = _fftconvolve(chips_f, kernel, mode="valid")
    return np.abs(corr.astype(np.float32))


def _remove_dc(samples: np.ndarray) -> np.ndarray:
    """Subtract the block-mean (DC component) from a complex sample stream.

    RTL-SDR direct-conversion receivers have significant LO feedthrough
    that shows up as a large DC spike at the tuned frequency. For our
    BPSK-DSSS signal the modulated energy is mean-zero over any
    reasonable window, so subtracting the block mean removes the LO
    leakage without affecting the useful signal. This matters for R[1]
    autocorrelation — a DC component contributes a large real-valued
    (phase-zero) term that biases the phase estimate toward zero.
    """
    s = np.asarray(samples, dtype=np.complex64)
    if len(s) == 0:
        return s
    return (s - s.mean()).astype(np.complex64)


def _estimate_freq_offset_r1(samples: np.ndarray) -> float:
    """Single R[1] autocorrelation freq estimate (rad/sample).

    Assumes the input has already had its DC component removed.
    """
    s = np.asarray(samples, dtype=np.complex64)
    if len(s) < 2:
        return 0.0
    r1 = np.vdot(s[1:], s[:-1])     # ≡ Σ s[n]·conj(s[n+1])
    if abs(r1) < 1e-9:
        return 0.0
    return -float(np.angle(r1))


def _estimate_freq_fft_squared(samples: np.ndarray,
                               coarse_rad: float = 0.0) -> float:
    """FFT-based frequency estimator on the squared signal.

    For BPSK/DSSS: s(t) = A*d(t)*c(t)*exp(jωt). Squaring removes the
    data/code modulation: s²(t) = A²*exp(j2ωt). The FFT of s² has a
    spectral line at 2ω, giving an unambiguous carrier estimate.

    This works at much lower per-sample SNR than R[1] because the FFT
    integrates over the entire block with √N gain. For 12M samples at
    -17 dB per-sample SNR, the spectral line at 2ω has ~30 dB SNR.

    `coarse_rad`: optional coarse frequency estimate (from R[1]) used to
    center the FFT search window. If 0, searches the full band.

    Returns frequency estimate in rad/sample.
    """
    s = np.asarray(samples, dtype=np.complex64)
    N = len(s)
    if N < 1024:
        return coarse_rad

    # Apply coarse correction to bring the signal near baseband,
    # then square to remove BPSK modulation.
    if coarse_rad != 0.0:
        n_arr = np.arange(N, dtype=np.float64)
        s = s * np.exp(-1j * coarse_rad * n_arr).astype(np.complex64)

    sq = (s * s).astype(np.complex64)

    # FFT with zero-padding for interpolation accuracy
    nfft = min(N, 2**20)  # cap at 1M-point FFT for speed
    # Average over segments if block is much longer than nfft
    n_seg = max(1, N // nfft)
    seg_len = nfft
    accum = np.zeros(nfft, dtype=np.complex128)
    for i in range(n_seg):
        seg = sq[i * seg_len:(i + 1) * seg_len]
        if len(seg) < nfft:
            break
        accum += np.fft.fft(seg, n=nfft)

    mag = np.abs(accum)
    # The spectral line is at 2*residual_freq (after coarse correction).
    # Search the full spectrum for the peak.
    peak_bin = int(np.argmax(mag))
    # Convert bin to frequency
    if peak_bin > nfft // 2:
        peak_bin -= nfft
    freq_per_bin = 2 * np.pi / nfft  # rad/sample per bin
    delta_2x = peak_bin * freq_per_bin
    # The squared signal has frequency 2*offset, so divide by 2
    fine_rad = delta_2x / 2.0

    return coarse_rad + fine_rad


def estimate_freq_drift_rate(samples: np.ndarray,
                             n_segments: int = 6) -> tuple[float, float]:
    """Estimate both carrier offset and linear drift rate from sub-block R[1].

    Splits the block into `n_segments` sub-blocks, runs R[1] on each,
    fits a line through the per-segment frequency estimates. Returns
    (rad_per_sample_at_center, drift_rad_per_sample2).

    The drift rate captures RTL-SDR crystal warm-up drift (~1-3 kHz/s at
    433 MHz). Without this correction, a 6-second block can have ~5 kHz
    of in-block drift — enough to destroy the 1023-chip MF coherence.
    """
    N = len(samples)
    if N < n_segments * 1000:
        r = _estimate_freq_offset_r1(_remove_dc(samples))
        return r, 0.0

    seg_len = N // n_segments
    freqs = []
    centers = []
    for i in range(n_segments):
        seg = samples[i * seg_len:(i + 1) * seg_len]
        seg = _remove_dc(seg)
        f = _estimate_freq_offset_r1(seg)
        freqs.append(f)
        centers.append((i + 0.5) * seg_len)  # center sample of segment

    freqs = np.array(freqs)
    centers = np.array(centers)

    # Robust linear fit (use median of pairwise slopes to reject outliers)
    if n_segments >= 3:
        slopes = []
        for i in range(n_segments):
            for j in range(i + 1, n_segments):
                slopes.append((freqs[j] - freqs[i]) / (centers[j] - centers[i]))
        drift = float(np.median(slopes))
    else:
        drift = float((freqs[-1] - freqs[0]) / (centers[-1] - centers[0]))

    # Offset at center of block
    mid = N / 2.0
    offset_at_center = float(np.median(freqs - drift * (centers - mid)))

    # Convert to offset at sample 0
    offset_at_zero = offset_at_center - drift * mid

    return offset_at_zero, drift


def estimate_freq_offset_rad_per_sample(samples: np.ndarray,
                                         iterations: int = 2) -> float:
    """Estimate carrier frequency offset of a BPSK-DSSS baseband signal.

    Uses the 1-sample-lag autocorrelation R[1] = Σ s[n]·conj(s[n+1]).
    For a signal s[n] = x[n]·exp(j·2π·Δf·n·T + jφ), with x[n] ∈ {+1,-1},
    the autocorrelation has phase -2π·Δf·T. When samps_per_chip ≥ 2, many
    sample-pairs (n, n+1) fall inside the same chip (x[n] = x[n+1] = ±1)
    so they coherently contribute `exp(-j·2π·Δf·T)`; cross-chip pairs
    contribute random-sign products that average toward zero.

    To improve accuracy over long streams, this function iterates the
    R[1] estimator: after computing a coarse offset, it applies the
    correction and re-estimates on the corrected samples. Each iteration
    typically reduces the residual error by 1-2 orders of magnitude
    until numerical precision is reached. Two iterations are usually
    enough for ~0.01 Hz residual on multi-second streams, which keeps
    cumulative phase drift below 0.1 rad across a one-second frame.

    Returns the total phase advance per sample in radians (= 2π·Δf·T).
    Multiply by f_s / (2π) to convert to Hz.

    The input is implicitly DC-centered by subtracting the block mean.
    This is critical for direct-conversion receivers (notably RTL-SDR)
    whose LO feedthrough produces a large DC spike right on top of the
    signal; without DC removal, R[1] is pulled toward zero phase by
    that bias term and the estimate can be off by hundreds of Hz.
    """
    samples_ac = _remove_dc(samples)
    total = _estimate_freq_offset_r1(samples_ac)
    for _ in range(iterations - 1):
        # Apply the current correction and re-estimate the residual.
        # DC removal on the corrected stream too, in case the correction
        # itself introduces a residual DC term.
        corrected = _remove_dc(apply_freq_correction(samples_ac, total))
        delta = _estimate_freq_offset_r1(corrected)
        total += delta
        if abs(delta) < 1e-9:
            break
    return total


def apply_freq_correction(samples: np.ndarray,
                           rad_per_sample: float,
                           drift_rad_per_sample2: float = 0.0) -> np.ndarray:
    """Multiply samples by exp(-j·(δ·n + ½α·n²)) to remove freq offset + drift.

    rad_per_sample: constant frequency offset (rad/sample)
    drift_rad_per_sample2: linear drift rate (rad/sample², i.e. chirp rate).
        Compensates oscillator warm-up drift. Zero disables chirp correction.
    """
    if rad_per_sample == 0.0 and drift_rad_per_sample2 == 0.0:
        return samples
    n = np.arange(len(samples), dtype=np.float64)
    phase = rad_per_sample * n
    if drift_rad_per_sample2 != 0.0:
        phase += 0.5 * drift_rad_per_sample2 * n * n
    correction = np.exp(-1j * phase).astype(np.complex64)
    return (samples * correction).astype(np.complex64)


def matched_filter_complex_sample_rate(
    samples: np.ndarray,
    samps_per_chip: int,
    code: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Complex sample-rate matched filter.

    Returns a COMPLEX correlator output. |corr| at a symbol boundary is
    the symbol energy; angle(corr) is the (residual) carrier phase at
    that symbol. Use this when the input may have a non-trivial carrier
    phase offset — taking only `.real` (as in the simpler helpers above)
    loses up to half the signal energy when the phase is near π/2.
    """
    if code is None:
        code = DEFAULT_PUBLIC_CODE
    code_upsampled = np.repeat(
        code.astype(np.float32), samps_per_chip
    ).astype(np.float32)
    if len(samples) < len(code_upsampled):
        return np.zeros(0, dtype=np.complex64)
    kernel = code_upsampled[::-1]
    s = np.asarray(samples, dtype=np.complex64)
    corr_re = _fftconvolve(s.real.astype(np.float32), kernel, mode="valid")
    corr_im = _fftconvolve(s.imag.astype(np.float32), kernel, mode="valid")
    return (corr_re + 1j * corr_im).astype(np.complex64)


def decode_with_freq_tracking(
    samples: np.ndarray,
    samps_per_chip: int,
    n_bytes: int,
    code: Optional[np.ndarray] = None,
    search_half_samples: Optional[int] = None,
    lock_threshold_frac: float = 0.1,
    freq_offset_rad_per_sample: Optional[float] = None,
    precomputed_corr: Optional[np.ndarray] = None,
) -> Optional[dict]:
    """Full-stack decoder: carrier offset correction + complex MF + tracking.

    Handles both carrier frequency offset (via one-shot R[1] estimation
    and correction) AND symbol-timing drift (via per-symbol peak search
    within a local window). Works with any integer samps_per_chip ≥ 2.

    Returns a dict with:
        bytes           — decoded bytes (one bit polarity; caller should
                          try this and its complement for SISL framing)
        positions       — peak position (sample index) per decoded bit
        freq_offset_hz  — estimated frequency offset applied (needs the
                          caller to supply the original sample rate; we
                          return rad/sample and let the caller scale)
        freq_rad_per_sample
        peak_magnitude  — global matched-filter peak after correction
        ref_angle_rad   — reference carrier phase taken from first peak

    Returns None if:
        - Stream too short for one symbol
        - No matched-filter peak above lock threshold
        - Tracker lost lock before decoding n_bytes*8 bits
    """
    if code is None:
        code = DEFAULT_PUBLIC_CODE

    n_bits = n_bytes * 8
    samples_per_symbol = CHIPS_PER_SYMBOL * samps_per_chip
    if search_half_samples is None:
        search_half_samples = samples_per_symbol // 4

    if len(samples) < samples_per_symbol:
        return None

    # ── 1. Carrier offset estimation + correction ─────────────────────
    if freq_offset_rad_per_sample is None:
        rad_per_sample = estimate_freq_offset_rad_per_sample(samples)
    else:
        rad_per_sample = float(freq_offset_rad_per_sample)
    samples_corr = apply_freq_correction(samples, rad_per_sample)

    # ── 2. Complex matched filter ─────────────────────────────────────
    if precomputed_corr is not None:
        corr_c = precomputed_corr
    else:
        corr_c = matched_filter_complex_sample_rate(
            samples_corr, samps_per_chip, code
        )
    if len(corr_c) == 0:
        return None
    mag = np.abs(corr_c).astype(np.float32)

    global_peak = float(mag.max())
    if global_peak == 0.0:
        return None

    # ── 3. Find first peak and its reference phase ────────────────────
    high_threshold = 0.9 * global_peak
    first_candidate = int(np.argmax(mag >= high_threshold))
    if mag[first_candidate] < high_threshold:
        return None
    lo = max(0, first_candidate - search_half_samples)
    hi = min(len(mag), first_candidate + search_half_samples + 1)
    local_idx = int(np.argmax(mag[lo:hi]))
    pos = lo + local_idx
    # Bootstrap a conservative initial lock floor from the single
    # argmax peak. This is biased HIGH (argmax always wins the tail
    # of the peak distribution), so for long codewords we soften it
    # further; after BOOTSTRAP successful peaks we re-anchor on the
    # running median of the first block of peaks, which is outlier-
    # resistant and reflects the actual per-symbol energy.
    initial_peak = float(mag[pos])
    # Lock floor anchored to the GLOBAL noise floor (median of |MF|),
    # not just a fixed fraction of one possibly-lucky peak. The pure
    # `lock_threshold_frac * initial_peak` form fails on long codewords
    # because (a) the initial peak can be a noise-driven argmax, in
    # which case subsequent real peaks fall below the floor, and
    # (b) a single per-symbol noise dip can push local_peak under the
    # floor, aborting the entire tracker. Two combined gates here:
    #   1. peak must be >= 2× median(|MF|) — i.e. clearly above the
    #      noise floor, regardless of how the initial peak was chosen
    #   2. peak must be >= lock_threshold_frac * initial_peak softened
    #      by sqrt(n_bits / 256), so longer codewords get a more
    #      permissive threshold (more chances to hit a noise dip)
    median_mag = float(np.median(mag))
    length_softening = max(1.0, float(np.sqrt(n_bits / 256.0)))
    lock_floor = max(
        median_mag * 2.0,
        lock_threshold_frac * initial_peak / length_softening,
    )

    ref_angle = float(np.angle(corr_c[pos]))

    # ── 4. Per-symbol tracking loop with sub-sample peak refinement ───
    # At 2 samples/chip the MF mainlobe is only 2-3 samples wide, so a
    # bare argmax can lock on the wrong sample and put us on the sinc
    # sidelobe (wrong phase). Refine each peak via parabolic
    # interpolation of the magnitude and take a linearly interpolated
    # correlator value at the refined sample index.
    peak_values: list[complex] = []
    positions: list[int] = []

    def _refine_peak(lo: int, hi: int) -> tuple[Optional[float], Optional[complex]]:
        """Parabolic peak interpolation.

        Fits y(x) = a·(x-x0)² + b·x + c to the three magnitudes around
        the argmax. Returns (refined_pos, refined_complex_value). The
        complex value is linearly interpolated between the two bracket
        samples at the refined position.
        """
        if hi - lo < 3:
            idx = int(np.argmax(mag[lo:hi]))
            actual = lo + idx
            return float(actual), complex(corr_c[actual])
        window = mag[lo:hi]
        local_idx = int(np.argmax(window))
        if local_idx == 0 or local_idx == len(window) - 1:
            actual = lo + local_idx
            return float(actual), complex(corr_c[actual])
        y0 = float(window[local_idx - 1])
        y1 = float(window[local_idx])
        y2 = float(window[local_idx + 1])
        denom = (y0 - 2 * y1 + y2)
        if abs(denom) < 1e-12:
            actual = lo + local_idx
            return float(actual), complex(corr_c[actual])
        frac = 0.5 * (y0 - y2) / denom              # in [-0.5, 0.5]
        refined = lo + local_idx + frac
        # Linear-interpolate the complex correlator value at the refined
        # fractional position. Phase unwrapping isn't needed over 1 sample
        # because the mainlobe is smooth.
        i0 = int(np.floor(refined))
        i1 = i0 + 1
        if i1 >= len(corr_c):
            return float(refined), complex(corr_c[i0])
        t = refined - i0
        c_refined = (1 - t) * corr_c[i0] + t * corr_c[i1]
        return float(refined), complex(c_refined)

    BOOTSTRAP = 8
    # Maximum CONSECUTIVE peaks below lock_floor before aborting. The
    # original logic aborted on the first dip, which is too brittle for
    # long codewords (FEC mode walks 4× HAIL_FEC_TOTAL_BITS ≈ 8000+
    # symbols and even at high SNR there are isolated dips below the
    # 2×median floor). Allow up to ~3% of the walk in consecutive
    # misses; abort if a sustained run of misses suggests the tracker
    # really has fallen off the signal.
    max_consecutive_misses = max(8, n_bits // 32)
    consecutive_misses = 0
    for bit_idx in range(n_bits):
        lo = max(0, int(round(pos)) - search_half_samples)
        hi = min(len(mag), int(round(pos)) + search_half_samples + 1)
        if hi - lo < samps_per_chip:
            return None
        refined_pos, refined_c = _refine_peak(lo, hi)
        if refined_pos is None or refined_c is None:
            return None
        local_peak = abs(refined_c)
        if local_peak < lock_floor:
            consecutive_misses += 1
            if consecutive_misses > max_consecutive_misses:
                return None
            # Use the refined peak anyway — downstream consumers (FEC
            # decoder, soft correlator) will handle the noisy sample
            # statistically. Step the position forward by the nominal
            # symbol period rather than the noise-driven refined_pos.
            peak_values.append(refined_c)
            positions.append(int(round(refined_pos)))
            pos = pos + samples_per_symbol
            continue
        consecutive_misses = 0

        peak_values.append(refined_c)
        positions.append(int(round(refined_pos)))
        pos = refined_pos + samples_per_symbol

        # After BOOTSTRAP successful peaks, re-anchor the lock floor on
        # the median of the first BOOTSTRAP peak magnitudes. The median
        # is outlier-resistant and gives a much better estimate of the
        # typical per-symbol energy than the argmax-biased initial_peak.
        # This is the key fix for the long-codeword low-SNR tracker
        # failure: otherwise a single transient dip past bit_idx = 7
        # aborts the decode before FEC / accumulator can use the LLRs.
        if bit_idx == BOOTSTRAP - 1:
            bootstrap_mags = np.abs(
                np.asarray(peak_values, dtype=np.complex128)
            )
            lock_floor = (
                lock_threshold_frac * float(np.median(bootstrap_mags))
            )

    # ── 5. Carrier phase drift estimation + differential decoding ─────
    # With 2 samples/chip and bench-grade SDRs, residual frequency offset
    # after R[1] correction can be 50-500 Hz — right in the range where
    # per-symbol phase drift approaches or crosses ±π/2. We now track
    # the per-symbol phase drift and remove it before making each
    # differential decision.
    #
    # Drift is estimated via the Viterbi-Viterbi squared estimator: if
    # each peak value c_k has phase θ_0 + k·Δθ + b_k·π (where b_k is
    # the BPSK bit), then (c_k)² has phase 2·(θ_0 + k·Δθ) (the b_k·π
    # term vanishes because 2π ≡ 0). Squaring removes the BPSK ambiguity
    # and lets us estimate Δθ from the mean phase advance of squared
    # values.
    if len(peak_values) >= 4:
        squared = np.array(peak_values, dtype=np.complex128) ** 2
        # Phase difference between consecutive squared values = 2·Δθ
        diffs = squared[1:] * np.conjugate(squared[:-1])
        mean_diff = complex(np.sum(diffs))
        if abs(mean_diff) > 1e-12:
            drift_per_symbol_2x = float(np.angle(mean_diff))
            drift_per_symbol = drift_per_symbol_2x / 2.0
        else:
            drift_per_symbol = 0.0
    else:
        drift_per_symbol = 0.0

    bits = np.empty(n_bits, dtype=np.uint8)
    bits[0] = 0                          # caller tries both polarities
    # Pre-compute the drift rotator so we can cancel it before each
    # differential dot product
    drift_rotator = complex(np.cos(drift_per_symbol),
                             -np.sin(drift_per_symbol))
    for k in range(1, n_bits):
        # Remove the expected per-symbol drift before comparing
        c_prev_rotated = peak_values[k - 1] * np.conj(drift_rotator)
        dot = (peak_values[k] * np.conj(c_prev_rotated)).real
        bits[k] = bits[k - 1] if dot >= 0 else (1 - bits[k - 1])

    return {
        "bytes": bits_to_bytes(bits),
        "positions": positions,
        "rad_per_sample": rad_per_sample,
        "peak_magnitude": global_peak,
        "ref_angle_rad": ref_angle,
        "drift_per_symbol_rad": drift_per_symbol,
        # Full list of complex peak values — needed for soft-decision
        # ASM search downstream.
        "peak_values": peak_values,
        # Diagnostic: first few peak magnitudes/angles so callers can
        # inspect what the decoder is seeing
        "first_peak_magnitudes": [abs(c) for c in peak_values[:16]],
        "first_peak_angles_rad": [float(np.angle(c)) for c in peak_values[:16]],
    }


def _phase_spread_rms(coherent_mag: float, incoherent_mag: float) -> float:
    """Convert coherent/incoherent magnitude ratio to equivalent phase spread in radians."""
    if incoherent_mag <= 0:
        return float("inf")
    ratio = coherent_mag / incoherent_mag
    safe_ratio = max(min(ratio, 1.0 - 1e-9), 1e-9)
    return float(np.sqrt(-2.0 * np.log(safe_ratio)))


def fit_phase_from_known_bits(
    peak_values,
    start_bit_offset: int,
    known_bits: np.ndarray,
    delta_search_range: float = np.pi,
    delta_fine_steps: int = 8,
) -> Optional[tuple[float, float, float]]:
    """ML fit of absolute phase θ₀ and per-symbol drift Δθ from a known pilot.

    Maximum-likelihood estimator for the linear carrier-phase model
    θ(k) = θ₀ + k·Δθ, given that peak_values[start:start+N] carry bits
    with known signs. Robust at arbitrary residual frequency offsets up
    to ±symbol_rate/2 — does NOT use np.unwrap, which diverges when the
    true slope approaches π/symbol.

    Derivation. After derotating each peak by the known bit sign:
        d[k] = sign(known_bits[k]) · peak[k]
             ≈ |p| · exp(j·(θ₀ + k·Δθ))  +  noise

    The ML estimate of Δθ is:
        Δθ̂ = argmax_{δ}  | Σ_k d[k] · exp(-j·k·δ) |²

    This is exactly the peak of the FFT of d[k], zero-padded for fine
    resolution. Given Δθ̂, the ML estimate of θ₀ is the angle of the
    coherent sum:
        θ̂₀ = angle( Σ_k d[k] · exp(-j·k·Δθ̂) )

    The rms_residual diagnostic is computed as the ratio between the
    coherent-sum magnitude and the incoherent sum of magnitudes — a
    value near 0 means all peaks are phase-aligned after correction
    (clean), values near 1 mean they are randomly oriented (noise).
    For backward compatibility with existing callers expecting a radians
    value, we return the equivalent phase spread:
        rms_residual ≈ sqrt(-2 · ln(coherent_mag / incoherent_mag))

    So rms_residual < 0.3 rad → clean, > 0.9 rad → marginal, > 1.5 rad
    → essentially noise.

    `delta_search_range` is the half-width of the Δθ search interval in
    radians per symbol (default π, the full unambiguous range).

    `delta_fine_steps` is the number of fine-refinement FFT iterations
    around the coarse peak; default 8 gives ~0.001 rad resolution.

    Returns (theta0, delta_theta, rms_residual_rad) or None on failure.
    """
    n_known = len(known_bits)
    if n_known < 4:
        return None
    total = len(peak_values)
    if start_bit_offset < 0 or start_bit_offset + n_known > total:
        return None

    peaks = np.array(
        peak_values[start_bit_offset:start_bit_offset + n_known],
        dtype=np.complex128,
    )
    if np.any(np.abs(peaks) < 1e-12):
        return None

    # Derotate by known sign: bit 0 → +1, bit 1 → -1
    sign = np.where(known_bits == 0, 1.0, -1.0).astype(np.float64)
    derotated = peaks * sign

    # Coarse grid search via zero-padded FFT. With M = 16*n_known samples,
    # the DFT bin spacing corresponds to Δθ = 2π/M per bin, covering
    # [-π, π] around DC. For n_known=48 this gives ~768 bins at 8 mrad
    # spacing — sufficient to localize the peak to one bin.
    n_fft = max(256, 16 * n_known)
    spectrum = np.fft.fft(derotated, n=n_fft)
    mag_sq = (spectrum.real ** 2 + spectrum.imag ** 2)
    coarse_idx = int(np.argmax(mag_sq))
    # Map FFT bin index to Δθ in (-π, π]
    if coarse_idx > n_fft // 2:
        coarse_idx -= n_fft
    coarse_delta = 2.0 * np.pi * coarse_idx / n_fft
    # Restrict to user-provided range (in case caller has a tighter prior)
    if abs(coarse_delta) > delta_search_range:
        # Search was too wide; clamp by re-searching within the allowed band
        bin_lo = int(-delta_search_range * n_fft / (2.0 * np.pi))
        bin_hi = int(delta_search_range * n_fft / (2.0 * np.pi))
        # Build masked magnitudes allowing only [bin_lo, bin_hi]
        idx_wrapped = np.arange(n_fft)
        signed = np.where(idx_wrapped > n_fft // 2,
                           idx_wrapped - n_fft, idx_wrapped)
        mask = (signed >= bin_lo) & (signed <= bin_hi)
        masked = np.where(mask, mag_sq, -1.0)
        coarse_idx_raw = int(np.argmax(masked))
        coarse_delta = 2.0 * np.pi * signed[coarse_idx_raw] / n_fft

    # Fine refinement: iterative bisection around the coarse peak.
    # At each step, evaluate the likelihood at (δ - h, δ, δ + h), move
    # to the best, halve h. This converges quadratically to machine
    # precision in a handful of steps.
    k_arr = np.arange(n_known, dtype=np.float64)
    def _likelihood(delta_val: float) -> float:
        phasor = np.exp(-1j * k_arr * delta_val)
        s = float(np.abs(np.sum(derotated * phasor)))
        return s
    delta_hat = float(coarse_delta)
    h = 2.0 * np.pi / n_fft   # half the coarse bin width
    for _ in range(delta_fine_steps):
        left = _likelihood(delta_hat - h)
        center = _likelihood(delta_hat)
        right = _likelihood(delta_hat + h)
        if left > center and left >= right:
            delta_hat -= h
        elif right > center and right > left:
            delta_hat += h
        h *= 0.5

    # ML θ₀ is the angle of the coherent sum at the best Δθ,
    # translated from "at start_bit_offset" back to "at bit index 0".
    phasor = np.exp(-1j * k_arr * delta_hat)
    coherent_sum = np.sum(derotated * phasor)
    coherent_mag = float(np.abs(coherent_sum))
    theta0_local = float(np.angle(coherent_sum))
    theta0_at_zero = theta0_local - start_bit_offset * delta_hat

    # Phase-spread residual: how much are the derotated peaks scattered
    # around the fitted trajectory? Compute via the ratio of coherent to
    # incoherent sums. coherent/incoherent = 1 for a perfectly aligned
    # signal; → 1/sqrt(N) for random noise.
    incoherent_mag = float(np.sum(np.abs(derotated)))
    rms_residual = _phase_spread_rms(coherent_mag, incoherent_mag)
    if rms_residual == float("inf"):
        return None

    return theta0_at_zero, float(delta_hat), rms_residual


def refine_freq_from_pilot(
    peak_values,
    pilot_bit_offset: int,
    pilot_bits: np.ndarray,
    symbol_rate_hz: float,
) -> Optional[tuple[float, float, float]]:
    """Pilot-aided ML refinement of residual frequency offset.

    Wraps fit_phase_from_known_bits and converts the per-symbol phase
    slope Δθ to a frequency offset in Hz via
        f_residual = (Δθ · symbol_rate_hz) / (2π)

    Useful as a fine-refinement stage AFTER a coarse Doppler search
    (e.g., a 2-D time × frequency grid) has located a candidate peak.
    The coarse search pins the freq to ±bin_width/2; the pilot fit then
    reduces the residual by a factor ~N (pilot length in bits) because
    ML slope estimation has 1/N precision when the SNR is high enough.

    Returns (f_residual_hz, theta0, rms_residual_rad) or None on failure.
    """
    fit = fit_phase_from_known_bits(
        peak_values, pilot_bit_offset, pilot_bits,
    )
    if fit is None:
        return None
    theta0, delta_theta, rms_residual = fit
    f_residual_hz = delta_theta * symbol_rate_hz / (2.0 * np.pi)
    return f_residual_hz, theta0, rms_residual


def coherent_decode_from_pilot(
    peak_values,
    pilot_bit_offset: int,
    pilot_bits: np.ndarray,
    n_data_bits: int,
) -> Optional[tuple[bytes, np.ndarray, float, float, float]]:
    """Coherent BPSK decode using a known pilot for absolute phase recovery.

    1. Fit θ₀, Δθ, residual from the pilot bits (pilot_bits_offset = where
       the known pilot starts within peak_values, pilot_bits = the values).
    2. For each data-bit position k ∈ [0, n_data_bits), compute the
       expected phase θ₀+k·Δθ and derotate the corresponding peak.
    3. The sign of the real part of the derotated peak is the coherent
       BPSK decision; its magnitude is the soft LLR.

    Decodes bits starting at peak index 0 in peak_values (not at the
    pilot position — the caller is responsible for aligning peak_values
    so that bit 0 is the frame start). Typically called with
    pilot_bit_offset = 0 when the ASM begins at the start of the frame.

    Returns (frame_bytes, soft_bits, theta0, delta_theta, rms_residual)
    where soft_bits is a float array of signed correlator outputs
    (positive for bit 0, negative for bit 1) — caller can use these
    for FEC decoding or fuzzy frame search.

    Returns None on fit failure or insufficient peaks.
    """
    fit = fit_phase_from_known_bits(
        peak_values, pilot_bit_offset, pilot_bits,
    )
    if fit is None:
        return None
    theta0, delta_theta, rms_residual = fit

    total = len(peak_values)
    if n_data_bits < 8 or n_data_bits > total:
        n_data_bits = min(n_data_bits, total)
    if n_data_bits < 8:
        return None

    peaks_arr = np.array(peak_values[:n_data_bits], dtype=np.complex128)
    k_arr = np.arange(n_data_bits, dtype=np.float64)
    # Derotate each peak by -(θ₀ + k·Δθ)
    rot = np.exp(-1j * (theta0 + k_arr * delta_theta))
    derotated = peaks_arr * rot
    # Real part carries the bit info (positive → 0, negative → 1)
    soft = derotated.real.astype(np.float32)
    bits = (soft < 0).astype(np.uint8)

    # Pad to byte boundary if needed
    pad = (-n_data_bits) % 8
    if pad:
        bits = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
    frame_bytes = np.packbits(bits).tobytes()

    return frame_bytes, soft, theta0, delta_theta, rms_residual


def estimate_drift_per_symbol(
    peak_values,
    pilot_bits: Optional[np.ndarray] = None,
) -> float:
    """Estimate per-symbol phase drift Δθ in rad/symbol.

    Two estimators are computed and combined:

      • **V-V** (Viterbi-Viterbi squared estimator) on ALL peaks. This
        is the existing per-block-tracker drift estimator. It uses
        every peak so it is statistically efficient, but it operates
        on the squared signal y² so its unambiguous range is bounded
        to Δθ ∈ [−π/2, +π/2]. Beyond that range it aliases by π.

      • **Pilot** (BPSK-demodulated adjacent differentials over the
        known pilot region). Removes the BPSK modulation by multiplying
        each pilot peak by its known sign, then computes adjacent
        products whose phase is exactly Δθ (no squaring). Range is
        unambiguous over [−π, +π], but only N_pilot ≈ 48 samples are
        used so it is noisier than V-V.

    When pilot_bits is given, V-V's [−π/2, +π/2] estimate is **unwrapped**
    around the pilot-derived coarse estimate by adding the integer
    multiple of π that minimises |delta_VV + k·π − delta_pilot|. This
    gives the V-V accuracy AND the pilot's full unambiguous range.

    When pilot_bits is None, only V-V is available and the range is
    bounded to [−π/2, +π/2].

    Returns Δθ in rad/symbol. Returns 0.0 on degenerate input
    (too few peaks, all-zero signal).
    """
    peaks = np.asarray(peak_values, dtype=np.complex128)
    n = len(peaks)
    if n < 4:
        return 0.0

    # ── V-V over all peaks ──
    # Squared signal y² = A² · exp(j·2(θ₀ + k·Δθ)). Adjacent product
    # of squared peaks has phase 2·Δθ — independent of k for constant
    # drift, so the sum is the ML estimator.
    sq = peaks * peaks
    diffs_vv = sq[1:] * np.conjugate(sq[:-1])
    s_vv = complex(np.sum(diffs_vv))
    if abs(s_vv) > 1e-12:
        delta_vv: Optional[float] = float(np.angle(s_vv)) / 2.0
    else:
        delta_vv = None

    if pilot_bits is None or len(pilot_bits) < 2:
        # No pilot — V-V is all we have. Bounded to [−π/2, +π/2].
        return delta_vv if delta_vv is not None else 0.0

    # ── Pilot-aided unambiguous coarse estimate ──
    n_pilot = int(min(len(pilot_bits), n))
    if n_pilot < 2:
        return delta_vv if delta_vv is not None else 0.0
    pilot_signs = (1.0 - 2.0
                    * np.asarray(pilot_bits[:n_pilot], dtype=np.float64))
    pilot_peaks = peaks[:n_pilot]
    clean = pilot_peaks * pilot_signs
    adj_clean = clean[1:] * np.conjugate(clean[:-1])
    s_pilot = complex(np.sum(adj_clean))
    if abs(s_pilot) < 1e-12:
        return delta_vv if delta_vv is not None else 0.0
    delta_pilot = float(np.angle(s_pilot))

    if delta_vv is None:
        return delta_pilot

    # ── Unwrap V-V around pilot estimate ──
    # The true Δθ could be delta_vv, delta_vv + π, or delta_vv − π
    # (V-V wraps every π). Pick whichever is closest to the pilot's
    # unambiguous estimate.
    candidates = (delta_vv, delta_vv + np.pi, delta_vv - np.pi)
    best = min(candidates, key=lambda c: abs(c - delta_pilot))
    return float(best)


def dbpsk_decode_from_pilot(
    peak_values,
    pilot_bits: np.ndarray,
    n_data_bits: int,
) -> Optional[tuple[bytes, np.ndarray, float, float, float]]:
    """Hybrid coherent-pilot + differential-body decoder for DBPSK signals.

    Replaces `coherent_decode_from_pilot` for the FEC fast path. Solves
    the long-codeword phase-trajectory problem documented in the second
    reviewer's S4 critique and confirmed on real RF in today's live
    test (decrypt_fail on every block due to back-half BPSK flips).

    Pipeline:
      1. Δθ estimate via FFT coarse search + V-V refinement (full
         [−π, +π] range, bypasses V-V's π/2 cliff).
      2. Derotate every peak by exp(-j·k·Δθ) to remove drift.
      3. Pilot region (k = 0 .. len(pilot_bits)-1): coherent ML decode
         using the known pilot bits to estimate θ₀.
      4. Body region (k = len(pilot_bits) .. n_data_bits-1): differential
         decode. The first body bit anchors on the last pilot peak, which
         is known coherently — this matches the TX-side convention of
         differentially encoding the body with seed = last header bit.
      5. Pack hard decisions into bytes for backwards compatibility.

    Sign convention (matches coherent_decode_from_pilot and sisl_fec):
      llr > 0  ⇒  bit 0
      llr < 0  ⇒  bit 1

    Returns (frame_bytes, soft_llrs, θ₀, Δθ, rms_residual_rad)
    or None on degenerate input.

    The TX side MUST differentially encode the body with seed equal to
    the last header bit's value (sc.encode_hail_fec does this), or the
    body decode produces meaningless XOR-of-adjacent-bits LLRs.
    """
    n_pilot = len(pilot_bits)
    if n_pilot < 1 or n_data_bits < n_pilot:
        return None
    total = len(peak_values)
    if n_data_bits > total:
        n_data_bits = total
    if n_data_bits < n_pilot + 1:
        return None

    peaks_arr = np.array(peak_values[:n_data_bits], dtype=np.complex128)

    # ── 1. Pilot-aided drift estimate (unambiguous over [−π, +π]) ──
    delta_theta = estimate_drift_per_symbol(peaks_arr, pilot_bits=pilot_bits)

    # ── 2. Derotate to remove drift ──
    k_arr = np.arange(n_data_bits, dtype=np.float64)
    drift_correction = np.exp(-1j * k_arr * delta_theta)
    derotated = peaks_arr * drift_correction

    # ── 3. Pilot-aided θ₀ recovery ──
    # The known pilot signs break the 180° symmetry; angle of the sum
    # of (derotated_pilot · known_pilot_signs) is θ₀ unambiguously.
    pilot_signs = (1.0 - 2.0 * pilot_bits.astype(np.float64))   # 0→+1, 1→−1
    pilot_section = derotated[:n_pilot]
    aligned = pilot_section * pilot_signs
    coherent_sum = complex(np.sum(aligned))
    theta0 = float(np.angle(coherent_sum))

    # rms residual is the same metric coherent_decode_from_pilot reports
    # (Gaussian phase-jitter equivalent).
    coherent_mag = abs(coherent_sum)
    incoherent_mag = float(np.sum(np.abs(aligned)))
    rms_residual = _phase_spread_rms(coherent_mag, incoherent_mag)

    # Apply θ₀ derotation to the entire frame for consistency.
    theta_rotator = np.exp(-1j * theta0)
    fully_derotated = derotated * theta_rotator

    # ── 4. Pilot-region LLRs (coherent) ──
    pilot_llrs = fully_derotated[:n_pilot].real.astype(np.float32)

    # ── 5. Body-region LLRs (differential) ──
    # Use RAW (un-derotated) peaks for the differential product. DBPSK
    # is inherently drift-immune: Re(peak[k] * conj(peak[k-1])) cancels
    # any constant per-symbol phase drift. Derotating first requires an
    # accurate Δθ estimate, which fails at low SNR and DESTROYS the
    # otherwise-good differential LLRs (the derotation introduces a
    # spurious constant phase offset exp(-j*Δθ_error) into every
    # differential product, rotating them off the real axis).
    raw_body = peaks_arr[n_pilot:]
    n_body = n_data_bits - n_pilot
    if n_body > 0:
        prev_peaks = np.empty(n_body, dtype=np.complex128)
        prev_peaks[0] = peaks_arr[n_pilot - 1]
        prev_peaks[1:] = raw_body[:-1]
        body_llrs = (raw_body * np.conj(prev_peaks)).real.astype(np.float32)
    else:
        body_llrs = np.zeros(0, dtype=np.float32)

    soft = np.concatenate([pilot_llrs, body_llrs]).astype(np.float32)
    bits = (soft < 0).astype(np.uint8)
    pad = (-n_data_bits) % 8
    if pad:
        bits = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
    frame_bytes = np.packbits(bits).tobytes()

    return frame_bytes, soft, theta0, delta_theta, rms_residual




def find_frame_start(chips: np.ndarray, code: Optional[np.ndarray] = None,
                     max_search: Optional[int] = None,
                     peak_threshold: float = 4.0) -> Optional[int]:
    """Locate the chip offset of the first symbol via matched-filter peak.

    Returns the offset into `chips` at which the first symbol begins, or
    None if no peak is confidently above noise within `max_search` chips.

    `max_search=None` searches the entire input. `peak_threshold` is the
    ratio of peak magnitude to median magnitude required to declare a lock;
    4.0 is conservative and works well under AWGN with processing gain.

    Note: the matched filter also peaks at every symbol boundary (every
    1023 chips) because the code period matches the symbol period. We return
    the FIRST above-threshold peak, which corresponds to the first symbol
    edge in the stream.
    """
    if code is None:
        code = DEFAULT_PUBLIC_CODE
    mag = matched_filter_magnitude(chips, code)
    if len(mag) == 0:
        return None
    if max_search is not None:
        mag = mag[:max_search]
        if len(mag) == 0:
            return None

    peak_val = float(mag.max())
    median = float(np.median(mag))
    if median == 0.0 or peak_val < peak_threshold * median:
        return None

    # Note: the matched filter peaks at every symbol boundary (every 1023
    # chips) with magnitude ≈ CHIPS_PER_SYMBOL; FFT-based convolution
    # introduces ULP-level rounding across these near-identical peaks, so
    # a strict np.argmax may return a LATER peak than the first. Return
    # the first index that is within 10% of the global maximum — robust
    # to float32 rounding while still unambiguously above noise.
    near_peak = mag >= 0.9 * peak_val
    return int(np.argmax(near_peak))


