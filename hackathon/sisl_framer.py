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

_public_code_cache: Optional[np.ndarray] = None


def public_hail_code() -> np.ndarray:
    """Return the public SISL hailing spreading code as int8 ±1 array."""
    global _public_code_cache
    if _public_code_cache is None:
        seed = sd.hail_code_seed()
        code_list = sd.generate_dsss_code(seed, length=CHIPS_PER_SYMBOL)
        _public_code_cache = np.array(code_list, dtype=np.int8)
    return _public_code_cache


def code_from_seed(seed: bytes, length: int = CHIPS_PER_SYMBOL) -> np.ndarray:
    return np.array(sd.generate_dsss_code(seed, length=length), dtype=np.int8)


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
        code = public_hail_code()
    if len(code) != CHIPS_PER_SYMBOL:
        raise ValueError(f"code length {len(code)} != {CHIPS_PER_SYMBOL}")

    bits = bytes_to_bits(data)
    symbols = (1 - 2 * bits.astype(np.int8))          # 0→+1, 1→-1
    # Broadcast multiply: (n_symbols, 1) * (1, chips) → (n_symbols, chips)
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
        code = public_hail_code()

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


def rx_chip_snr_db(chips: np.ndarray, n_bytes: int,
                   code: Optional[np.ndarray] = None) -> float:
    """Estimate post-despread SNR in dB from correlator output magnitude.

    Useful for sanity-checking the loopback with and without noise.
    """
    if code is None:
        code = public_hail_code()
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
        code = public_hail_code()
    chips_f = np.asarray(chips, dtype=np.float32)
    code_f = code.astype(np.float32)
    if len(chips_f) < len(code_f):
        return np.zeros(0, dtype=np.float32)
    kernel = code_f[::-1]
    corr = _fftconvolve(chips_f, kernel, mode="valid")
    return np.abs(corr.astype(np.float32))


def _estimate_freq_offset_r1(samples: np.ndarray) -> float:
    """Single R[1] autocorrelation freq estimate (rad/sample)."""
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
    """
    total = _estimate_freq_offset_r1(samples)
    for _ in range(iterations - 1):
        # Apply the current correction and re-estimate the residual
        corrected = apply_freq_correction(samples, total)
        delta = _estimate_freq_offset_r1(corrected)
        total += delta
        # Early exit once the refinement drops below numerical floor
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
        code = public_hail_code()
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
    lock_threshold_frac: float = 0.3,
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
        code = public_hail_code()

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
    initial_peak = float(mag[pos])
    lock_floor = lock_threshold_frac * initial_peak

    ref_angle = float(np.angle(corr_c[pos]))

    # ── 4. Per-symbol tracking loop ───────────────────────────────────
    # Collect the complex correlator value at each symbol peak. We then
    # decode DIFFERENTIALLY: each bit is determined by the phase
    # relationship between CONSECUTIVE symbols, not against a fixed
    # reference. This is immune to slow carrier phase drift — the drift
    # per symbol only needs to stay below ±π/2, which allows residual
    # offsets up to ~250 Hz (≈ 0.25 rad/symbol at 1 ms symbols) even
    # without any phase tracking. Any residual drift the R[1] estimator
    # couldn't fully remove is absorbed.
    peak_values: list[complex] = []
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
            return None

        peak_values.append(complex(corr_c[actual_pos]))
        positions.append(actual_pos)
        pos = actual_pos + samples_per_symbol

    # ── 5. Differential bit decoding ───────────────────────────────────
    # For BPSK, consecutive symbols differ in phase by 0 (same bit) or π
    # (different bit), plus a small drift due to residual frequency
    # offset. We classify via the real part of (c_k · conj(c_{k-1})):
    #   dot > 0  →  phase difference in (-π/2, +π/2)  →  same bit
    #   dot < 0  →  phase difference near ±π          →  different bit
    # The absolute bit polarity (which value bit_0 represents) is
    # arbitrary and resolved by the caller trying both orientations.
    bits = np.empty(n_bits, dtype=np.uint8)
    bits[0] = 0                          # caller tries both polarities
    for k in range(1, n_bits):
        dot = (peak_values[k] * peak_values[k - 1].conjugate()).real
        bits[k] = bits[k - 1] if dot >= 0 else (1 - bits[k - 1])

    return {
        "bytes": bits_to_bytes(bits),
        "positions": positions,
        "rad_per_sample": rad_per_sample,
        "peak_magnitude": global_peak,
        "ref_angle_rad": ref_angle,
    }


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
        code = public_hail_code()
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
        code = public_hail_code()

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
        code = public_hail_code()
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
        code = public_hail_code()
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
            self._code = code if code is not None else public_hail_code()

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
            self._code = code if code is not None else public_hail_code()

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
