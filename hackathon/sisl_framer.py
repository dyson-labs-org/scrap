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

import os
import sys
from typing import Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

    bits = bytes_to_bits(data)
    symbols = (1 - 2 * bits.astype(np.int8))          # 0→+1, 1→-1
    # Broadcast multiply: (n_symbols, 1) * (1, chips) → (n_symbols, chips)
    chips = (symbols[:, None] * code[None, :]).reshape(-1)
    return chips.astype(np.int8)


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
    needed = n_bits * CHIPS_PER_SYMBOL
    if len(chips) < needed:
        raise ValueError(f"need {needed} chips, got {len(chips)}")

    # Reshape, correlate each row against the local code
    mat = np.asarray(chips[:needed], dtype=np.float32).reshape(
        n_bits, CHIPS_PER_SYMBOL
    )
    corr = mat @ code.astype(np.float32)

    # BPSK decision: correlation > 0 → bit 0, < 0 → bit 1
    bits = (corr < 0).astype(np.uint8)
    return bits_to_bytes(bits)


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


def rx_chip_snr_db(chips: np.ndarray, n_bytes: int,
                   code: Optional[np.ndarray] = None) -> float:
    """Estimate post-despread SNR in dB from correlator output magnitude.

    Useful for sanity-checking the loopback with and without noise.
    """
    if code is None:
        code = DEFAULT_PUBLIC_CODE
    n_bits = n_bytes * 8
    needed = n_bits * CHIPS_PER_SYMBOL
    mat = np.asarray(chips[:needed], dtype=np.float32).reshape(
        n_bits, CHIPS_PER_SYMBOL
    )
    corr = mat @ code.astype(np.float32)
    # signal = magnitude of correlator output (assuming BPSK ±)
    # noise  = deviation from ±CHIPS_PER_SYMBOL
    signal = np.mean(np.abs(corr))
    noise = np.std(np.abs(corr) - signal) + 1e-12
    return float(20 * np.log10(signal / noise))


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
                           rad_per_sample: float) -> np.ndarray:
    """Multiply samples by exp(-j·δ·n) to remove a constant frequency offset."""
    if rad_per_sample == 0.0:
        return samples
    n = np.arange(len(samples), dtype=np.float64)
    correction = np.exp(-1j * rad_per_sample * n).astype(np.complex64)
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
            return None

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
    if incoherent_mag <= 0:
        return None
    ratio = coherent_mag / incoherent_mag
    # Convert ratio to an equivalent radian phase-spread:
    # For a Gaussian phase jitter σ, E[e^{jφ}] = e^{-σ²/2}, so
    #    σ² = -2 · ln(ratio), σ = sqrt(-2 · ln ratio).
    # Clamped below so a perfect match doesn't log(0).
    safe_ratio = max(min(ratio, 1.0 - 1e-9), 1e-9)
    rms_residual = float(np.sqrt(-2.0 * np.log(safe_ratio)))

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


def matched_filter_signed_sample_rate(
    samples: np.ndarray,
    samps_per_chip: int,
    code: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Sample-rate matched filter returning SIGNED correlation.

    Like `matched_filter_magnitude_sample_rate` but returns the raw real-
    valued correlation instead of its magnitude. The sign at a symbol-
    boundary peak is the BPSK bit value: positive → bit 0, negative →
    bit 1. Used by `decode_with_tracking` to extract bit decisions
    directly from correlator output without a second decimation pass.
    """
    if code is None:
        code = DEFAULT_PUBLIC_CODE
    if samps_per_chip < 1:
        raise ValueError("samps_per_chip must be >= 1")
    code_upsampled = np.repeat(
        code.astype(np.float32), samps_per_chip
    ).astype(np.float32)
    i = np.asarray(samples, dtype=np.complex64).real.astype(np.float32)
    if len(i) < len(code_upsampled):
        return np.zeros(0, dtype=np.float32)
    kernel = code_upsampled[::-1]
    corr = _fftconvolve(i, kernel, mode="valid")
    return corr.astype(np.float32)


def decode_with_tracking(
    samples: np.ndarray,
    samps_per_chip: int,
    n_bytes: int,
    code: Optional[np.ndarray] = None,
    search_half_samples: Optional[int] = None,
    lock_threshold_frac: float = 0.3,
) -> Optional[tuple[bytes, list[int]]]:
    """Decode `n_bytes` from a baseband sample stream with per-symbol
    peak tracking, robust to TX-RX clock drift.

    Algorithm:
      1. Compute signed matched filter at sample rate (phase-agnostic
         with respect to integer-sample sub-chip offset).
      2. Locate the first strong peak above threshold (0.5 × global max).
      3. For each subsequent symbol, search a local window
         (±search_half_samples, default = CHIPS_PER_SYMBOL*samps_per_chip/4)
         around the predicted next-peak position and take the peak as
         the decision point. Predicted position is updated from the
         last ACTUAL peak, so clock drift is absorbed continuously.
      4. Extract the sign at each peak → bit value → bytes.

    Returns (decoded_bytes, peak_positions) or None if tracking lost
    lock (a window's peak dropped below `lock_threshold_frac` × initial
    peak, or the stream ran out of samples).

    Note on BPSK phase ambiguity: this function returns ONE bit
    orientation. The caller should try both the returned bytes and
    their bitwise complement when searching for framing markers, since
    a 180° carrier phase offset flips every bit.
    """
    if code is None:
        code = DEFAULT_PUBLIC_CODE

    n_bits = n_bytes * 8
    samples_per_symbol = CHIPS_PER_SYMBOL * samps_per_chip
    if search_half_samples is None:
        search_half_samples = samples_per_symbol // 4

    corr = matched_filter_signed_sample_rate(samples, samps_per_chip, code)
    if len(corr) == 0:
        return None
    mag = np.abs(corr)

    global_peak = float(mag.max())
    if global_peak == 0.0:
        return None

    # Locate initial lock: first index within 90% of the global max
    high_threshold = 0.9 * global_peak
    first_candidate = int(np.argmax(mag >= high_threshold))
    if mag[first_candidate] < high_threshold:
        return None

    # Refine the initial position within a small local window
    lo = max(0, first_candidate - search_half_samples)
    hi = min(len(mag), first_candidate + search_half_samples + 1)
    local_idx = int(np.argmax(mag[lo:hi]))
    pos = lo + local_idx
    initial_peak = float(mag[pos])
    lock_floor = lock_threshold_frac * initial_peak

    bits = np.empty(n_bits, dtype=np.uint8)
    positions: list[int] = []

    for bit_idx in range(n_bits):
        lo = max(0, pos - search_half_samples)
        hi = min(len(mag), pos + search_half_samples + 1)
        if hi - lo < samps_per_chip:
            return None
        window_mag = mag[lo:hi]
        local_idx = int(np.argmax(window_mag))
        actual_pos = lo + local_idx
        local_peak = float(window_mag[local_idx])

        if local_peak < lock_floor:
            # Lost track: signal faded or we ran past the frame
            return None

        sign = float(corr[actual_pos])
        bits[bit_idx] = 0 if sign >= 0 else 1
        positions.append(actual_pos)

        # Next expected position — updated from the ACTUAL (not predicted)
        # peak so clock drift is absorbed continuously.
        pos = actual_pos + samples_per_symbol

    return bits_to_bytes(bits), positions


def matched_filter_magnitude_sample_rate(
    samples: np.ndarray,
    samps_per_chip: int,
    code: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Sample-rate matched filter. Phase-agnostic acquisition in one pass.

    Correlates `samples` (complex64 baseband) against the spreading code
    upsampled by `samps_per_chip` via zero-order hold. A peak at output
    index k means the first chip of a symbol starts at sample k. No
    sub-chip phase search is required — the kernel's ZOH upsampling
    absorbs any integer-sample phase offset of the TX chip grid relative
    to the RX sample grid.

    Only the real (I) component of `samples` is used — the demo TX is
    BPSK with zero Q. A full-complex version is a trivial extension.

    Output length = len(samples) - len(code)*samps_per_chip + 1.
    """
    if code is None:
        code = DEFAULT_PUBLIC_CODE
    if samps_per_chip < 1:
        raise ValueError("samps_per_chip must be >= 1")
    code_upsampled = np.repeat(
        code.astype(np.float32), samps_per_chip
    ).astype(np.float32)
    i = np.asarray(samples, dtype=np.complex64).real.astype(np.float32)
    if len(i) < len(code_upsampled):
        return np.zeros(0, dtype=np.float32)
    kernel = code_upsampled[::-1]
    corr = _fftconvolve(i, kernel, mode="valid")
    return np.abs(corr.astype(np.float32))


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


# ── GNU Radio wrappers (optional; only if gnuradio is importable) ───────────

try:
    from gnuradio import gr
    _HAVE_GR = True
except ImportError:
    gr = None                                          # type: ignore
    _HAVE_GR = False


if _HAVE_GR:
    class SISLFramerBlock(gr.basic_block):                                # type: ignore[misc]
        """GR basic_block wrapping `tx_bytes_to_chips`.

        Input: byte stream (uint8, one byte per item).
        Output: chip stream (int8, ±1, CHIPS_PER_SYMBOL * 8 chips per byte).
        """

        def __init__(self, code: Optional[np.ndarray] = None):
            gr.basic_block.__init__(
                self,
                name="sisl_framer",
                in_sig=[np.uint8],
                out_sig=[np.int8],
            )
            self._code = code if code is not None else DEFAULT_PUBLIC_CODE

        def general_work(self, input_items, output_items):
            in0 = input_items[0]
            out0 = output_items[0]
            chips_per_byte = 8 * CHIPS_PER_SYMBOL
            n_bytes_in = len(in0)
            n_bytes_out = len(out0) // chips_per_byte
            n = min(n_bytes_in, n_bytes_out)
            if n == 0:
                return 0
            chips = tx_bytes_to_chips(bytes(in0[:n].tolist()), self._code)
            out0[:n * chips_per_byte] = chips
            self.consume(0, n)
            return n * chips_per_byte

    class SISLDeframerBlock(gr.basic_block):                              # type: ignore[misc]
        """GR basic_block wrapping `rx_chips_to_bytes` (chip-aligned).

        Input: float32 chip stream (correlator input).
        Output: byte stream (uint8).

        Assumes chip-0 alignment at startup. A real receiver must prepend a
        sliding-correlator acquisition stage (see `find_frame_start`).
        """

        def __init__(self, code: Optional[np.ndarray] = None):
            gr.basic_block.__init__(
                self,
                name="sisl_deframer",
                in_sig=[np.float32],
                out_sig=[np.uint8],
            )
            self._code = code if code is not None else DEFAULT_PUBLIC_CODE

        def general_work(self, input_items, output_items):
            in0 = input_items[0]
            out0 = output_items[0]
            chips_per_byte = 8 * CHIPS_PER_SYMBOL
            n_bytes_possible = min(len(in0) // chips_per_byte, len(out0))
            if n_bytes_possible == 0:
                return 0
            chips = in0[:n_bytes_possible * chips_per_byte]
            data = rx_chips_to_bytes(chips, n_bytes_possible, self._code)
            out0[:n_bytes_possible] = np.frombuffer(data, dtype=np.uint8)
            self.consume(0, n_bytes_possible * chips_per_byte)
            return n_bytes_possible
