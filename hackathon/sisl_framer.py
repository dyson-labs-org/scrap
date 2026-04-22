"""SISL framer / deframer — pure-numpy DSP for BPSK-DSSS TX/RX.

TX: bytes → BPSK symbols (±1) → spread by 1023-chip code → int8 chips
RX: chips → reshape → row-dot with code → sign decision → bytes

Assumes chip-aligned start; add a sliding correlator for acquisition.
"""

from __future__ import annotations

import os
import sys

import numpy as np
SISL_DEBUG = bool(os.environ.get("SISL_DEBUG"))
_DEBUG_SCHEMA_KEYS = (
    "status",
    "candidates",
    "asm_errs",
    "mean_abs_llr",
    "cos_sim",
    "freq_hz",
    "drift_rad",
)


def _format_debug_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (float, np.floating)):
        if np.isfinite(value):
            return f"{float(value):.6g}"
        return str(float(value))
    if isinstance(value, (np.integer, int)):
        return str(int(value))
    return str(value)


def debug_telemetry(component: str, /, stream=None, **fields) -> None:
    """Emit SISL_DEBUG telemetry in a stable key/value format."""
    if not SISL_DEBUG:
        return
    ordered: list[tuple[str, object]] = []
    for key in _DEBUG_SCHEMA_KEYS:
        value = fields.pop(key, None)
        if value is not None:
            ordered.append((key, value))
    for key, value in fields.items():
        if value is not None:
            ordered.append((key, value))
    if not ordered:
        return
    payload = " ".join(f"{k}={_format_debug_value(v)}" for k, v in ordered)
    print(f"  [DBG {component}] {payload}", file=(stream or sys.stdout), flush=True)

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
_MAX_ABS_RAD_PER_SAMPLE = float(np.pi)
_MAX_ABS_DRIFT_PER_SYMBOL = float(np.pi)
_MAX_ABS_DRIFT_RAD_PER_SAMPLE2 = 1.0


# ── Spreading code helpers ──────────────────────────────────────────────────


def code_from_seed(seed: bytes, length: int = CHIPS_PER_SYMBOL) -> np.ndarray:
    return sd.generate_dsss_code(seed, length=length)


DEFAULT_PUBLIC_CODE: np.ndarray = code_from_seed(sd.hail_code_seed())
DEFAULT_PUBLIC_CODE.flags.writeable = False


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
# Encoder: e_k = e_{k−1} XOR b_k
# Decoder: b_k = sign(Re(y_k · conj(y_{k−1})))
# Phase-insensitive; depends only on inter-symbol phase difference.

def differential_encode_bits(bits: np.ndarray, seed: int = 0) -> np.ndarray:
    """Differentially encode a uint8 0/1 bit array.

    e_{−1} = seed (0 or 1)
    e_k    = e_{k−1} XOR bits[k]   for k = 0 .. N−1

    Returns the encoded bit array with the same shape and dtype as `bits`.
    """
    bits = np.ascontiguousarray(bits, dtype=np.uint8)
    if bits.ndim != 1:
        raise ValueError(f"bits must be 1-D, got shape {bits.shape}")
    padded = np.empty(len(bits) + 1, dtype=np.uint8)
    padded[0] = seed & 1
    padded[1:] = bits
    return np.bitwise_xor.accumulate(padded)[1:]


def differential_decode_bits(bits: np.ndarray, seed: int = 0) -> np.ndarray:
    """Inverse of differential_encode_bits: b_k = bits[k] XOR bits[k−1]."""
    bits = np.ascontiguousarray(bits, dtype=np.uint8)
    if bits.ndim != 1:
        raise ValueError(f"bits must be 1-D, got shape {bits.shape}")
    padded = np.empty(len(bits) + 1, dtype=np.uint8)
    padded[0] = seed & 1
    padded[1:] = bits
    return np.diff(padded).astype(np.uint8) & 1


# ── TX: bytes → chip stream ─────────────────────────────────────────────────

def tx_bytes_to_chips(data: bytes,
                      code: np.ndarray | None = None) -> np.ndarray:
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
                     code: np.ndarray | None = None) -> np.ndarray:
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
                      code: np.ndarray | None = None) -> bytes:
    """Despread a chip-aligned stream into bytes.

    `chips` must contain at least `n_bytes * 8 * CHIPS_PER_SYMBOL` samples
    starting at chip 0 of the first symbol. Accepts float or int input.
    """
    if code is None:
        code = DEFAULT_PUBLIC_CODE

    n_bits = n_bytes * 8
    return bits_to_bytes(rx_chips_to_bits(chips, n_bits, code))


def rx_chips_to_bits(chips: np.ndarray, n_bits: int,
                     code: np.ndarray | None = None) -> np.ndarray:
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


# ── Sliding-correlator acquisition ─────────────────────────────────────────

def _remove_dc(samples: np.ndarray) -> np.ndarray:
    """Subtract block-mean DC from a complex sample stream."""
    s = np.asarray(samples, dtype=np.complex64)
    if len(s) == 0:
        return s
    return (s - s.mean()).astype(np.complex64)


def _require_finite_real(name: str, value: float) -> float:
    value_f = float(value)
    if not np.isfinite(value_f):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return value_f


def _require_rad_per_sample(name: str, value: float) -> float:
    value_f = _require_finite_real(name, value)
    if abs(value_f) > _MAX_ABS_RAD_PER_SAMPLE:
        raise ValueError(
            f"{name} must be in [-pi, +pi] rad/sample, got {value_f:.6g}"
        )
    return value_f


def _require_drift_per_symbol(name: str, value: float) -> float:
    value_f = _require_finite_real(name, value)
    if abs(value_f) > _MAX_ABS_DRIFT_PER_SYMBOL:
        raise ValueError(
            f"{name} must be in [-pi, +pi] rad/symbol, got {value_f:.6g}"
        )
    return value_f


def _wrap_phase_pi(value: float) -> float:
    """Wrap phase-like values to [-pi, +pi)."""
    value_f = _require_finite_real("phase", value)
    return float(((value_f + np.pi) % (2.0 * np.pi)) - np.pi)


def _require_drift_rad_per_sample2(name: str, value: float) -> float:
    value_f = _require_finite_real(name, value)
    if abs(value_f) > _MAX_ABS_DRIFT_RAD_PER_SAMPLE2:
        raise ValueError(
            f"{name} magnitude {value_f:.6g} rad/sample^2 exceeds limit "
            f"{_MAX_ABS_DRIFT_RAD_PER_SAMPLE2}"
        )
    return value_f


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
    """FFT-based frequency estimator on squared signal.

    s²(t) = A²·exp(j2ωt) removes BPSK modulation; FFT peak at 2ω / 2.
    `coarse_rad` is accepted for API compat but ignored — R[1] is too
    unreliable at DSSS wideband SNR to be useful as a coarse estimate.
    Returns frequency estimate in rad/sample.
    """
    s = np.asarray(samples, dtype=np.complex64)
    N = len(s)
    if N < 1024:
        return 0.0

    # Square to remove BPSK modulation. Do NOT apply R[1] coarse
    # correction — at -17 dB per-sample SNR, R[1] gives random angles
    # (often ±π = ±Nyquist), which shifts the real signal to the band
    # edge where it aliases or falls outside any search window.
    sq = (s * s).astype(np.complex64)

    # FFT with segment averaging for noise reduction
    nfft = min(N, 2**20)  # cap at 1M-point FFT (~0.5s at 2 Msps)
    # NOTE: 2^23 was tried for +10dB integration gain but took 20s per
    # block — unusable.  The post-MF grid search (estimate_freq_post_mf)
    # handles spur rejection at post-despread SNR instead.
    n_seg = max(1, N // nfft)
    seg_len = nfft
    accum = np.zeros(nfft, dtype=np.complex128)
    for i in range(n_seg):
        seg = sq[i * seg_len:(i + 1) * seg_len]
        if len(seg) < nfft:
            break
        accum += np.fft.fft(seg, n=nfft)

    mag = np.abs(accum)
    # Search the full band, excluding only DC and Nyquist bins.
    mask = np.ones(nfft, dtype=bool)
    mask[0] = False
    mask[nfft // 2] = False
    masked_mag = np.where(mask, mag, 0.0)

    # Return the top-K candidates (by magnitude) so the caller can
    # try each one and pick the one that produces the best MF output.
    # HackRF has PLL spurs at multiples of ~250/500 kHz that can be
    # stronger than the DSSS carrier; returning only the argmax would
    # lock onto the spur. With K candidates the caller validates each
    # against the MF and picks the real signal.
    K = 5
    candidates: list[float] = []
    freq_per_bin = 2 * np.pi / nfft
    working_mag = masked_mag.copy()
    for _ in range(K):
        peak_bin = int(np.argmax(working_mag))
        if working_mag[peak_bin] <= 0:
            break
        # Parabolic interpolation
        left = (peak_bin - 1) % nfft
        right = (peak_bin + 1) % nfft
        y0 = float(mag[left])
        y1 = float(mag[peak_bin])
        y2 = float(mag[right])
        frac = _parabolic_frac(y0, y1, y2)
        refined_bin = peak_bin + frac
        if refined_bin > nfft / 2:
            refined_bin -= nfft
        delta_2x = refined_bin * freq_per_bin
        candidates.append(delta_2x / 2.0)  # divide by 2 for squared
        # Suppress this peak and its neighbors for next iteration
        lo = max(0, peak_bin - nfft // 100)
        hi = min(nfft, peak_bin + nfft // 100 + 1)
        working_mag[lo:hi] = 0.0

    if not candidates:
        return 0.0

    # If only one candidate, return it directly (fast path for tests).
    if len(candidates) == 1:
        return candidates[0]

    # Validate each candidate with the canonical MF periodicity scorer.
    # Uses column-mean chip-phase (robust to WiFi/BT spikes) instead of
    # argmax. See _score_freq_candidate_mf for details.
    validator_seg_len = min(N, 200_000)  # ~100ms — fast screening only
    # Heavy validation is done by estimate_freq_post_mf (grid search)
    # AFTER the FFT-squared picks the best candidate.  Keep this cheap.
    spc = 2  # always validate at 2 samples/chip

    best_rad = candidates[0]
    best_score = -1.0
    for cand_rad in candidates:
        score = _score_freq_candidate_mf(
            samples, cand_rad, samps_per_chip=spc,
            seg_len=validator_seg_len, n_peaks=32,
        )
        if score > best_score:
            best_score = score
            best_rad = cand_rad

    return best_rad


def _score_freq_candidate_mf(
    samples: np.ndarray,
    rad_per_sample: float,
    samps_per_chip: int = 2,
    seg_len: int = 100_000,
    n_peaks: int = 16,
    code: np.ndarray | None = None,
) -> float:
    """Score a frequency candidate by MF periodicity strength.

    Apply freq correction, run the MF (matched filter) on a short segment,
    measure periodic peak structure at symbol spacing.  Returns a
    periodicity score (median of symbol-spaced peaks / median noise).
    Higher is better; real DSSS (Direct-Sequence Spread Spectrum) signal
    gives score >> 5, spurs give ~1-3.

    code: spreading code to correlate against.  Default is the full 1023-chip
    public code.  Pass a shorter code (e.g. first 128 chips) for a wider-
    bandwidth coarse frequency search at reduced processing gain.
    """
    if code is None:
        code = DEFAULT_PUBLIC_CODE
    seg = np.asarray(samples[:seg_len], dtype=np.complex64)
    sym_samples = len(code) * samps_per_chip

    if len(seg) < sym_samples * 10:
        return 0.0

    corrected = apply_freq_correction(seg, rad_per_sample)
    corr = matched_filter_complex_sample_rate(corrected, samps_per_chip, code=code)
    if len(corr) < sym_samples * 10:
        return 0.0

    m = np.abs(corr).astype(np.float32)
    median_noise = float(np.median(m))
    if median_noise < 1e-12:
        return 0.0

    # Use column-mean chip-phase (periodic average) to find true DSSS phase,
    # not argmax which can be a WiFi/BT spike.
    n_full = (len(m) // sym_samples) * sym_samples
    phase_avgs = m[:n_full].reshape(-1, sym_samples).mean(axis=0)
    chip_phase = int(np.argmax(phase_avgs))

    search_half = sym_samples // 4
    periodic_peaks: list[float] = []
    for k in range(n_peaks):
        pos = chip_phase + k * sym_samples
        if pos + search_half >= len(m):
            break
        lo = max(0, pos - search_half)
        hi = min(len(m), pos + search_half + 1)
        periodic_peaks.append(float(m[lo:hi].max()))

    if len(periodic_peaks) < 4:
        return 0.0

    return float(np.median(periodic_peaks)) / median_noise


def estimate_freq_post_mf(
    samples: np.ndarray,
    fft_squared_rad: float,
    samps_per_chip: int = 2,
    samp_hz: float = 2_000_000.0,
    grid_half_hz: float = 50_000.0,
    grid_step_hz: float = 5_000.0,
    min_score: float = 3.0,
    tracking_threshold: float = 5.0,
) -> tuple[float, float]:
    """Post-MF periodicity-based frequency acquisition/tracking for DSSS.

    Two modes, selected automatically:

    **Tracking** (fft_squared_rad scores >= tracking_threshold with full MF):
    The hint is a good frequency from a prior block.  Validate it with the
    full correlator; if it still scores well, refine via FFT-squared in the
    neighborhood.  Cost: 1 full-MF eval + 1 FFT-squared ≈ 40ms.

    **Acquisition** (hint absent, stale, or low-scoring):
    Hierarchical grid search — coarse stage with 128-chip partial correlator
    (wide mainlobe tolerates 5 kHz steps), fine stage with full correlator.
    Cost: ~30 coarse + ~20 fine MF evals ≈ 1.5s.

    Tracking mode prevents re-acquisition from locking onto spurs when the
    signal frequency is already known.  Falls back to acquisition if the
    hint is invalidated (e.g., carrier frequency changed between TX epochs).

    Returns (best_rad_per_sample, best_score).
    """
    seg_len = min(len(samples), 200_000)
    hz_to_rad = 2.0 * np.pi / samp_hz
    full_kernel_bw = samp_hz / (2.0 * CHIPS_PER_SYMBOL * samps_per_chip)
    fine_step_hz = max(100.0, full_kernel_bw)  # ~489 Hz

    # ── Tracking mode: validate hint with full MF ─────────────────────
    hint_score = _score_freq_candidate_mf(
        samples, fft_squared_rad, samps_per_chip, seg_len,
    )
    if hint_score >= tracking_threshold:
        # Hint is valid — refine in neighborhood, skip coarse grid.
        best_rad = fft_squared_rad
        best_score = hint_score
        # Fine grid: ±fine_step_hz×3 around hint
        hint_hz = best_rad / hz_to_rad
        for i in range(-3, 4):
            candidate_hz = hint_hz + i * fine_step_hz
            candidate_rad = candidate_hz * hz_to_rad
            score = _score_freq_candidate_mf(
                samples, candidate_rad, samps_per_chip, seg_len,
            )
            if score > best_score:
                best_score = score
                best_rad = candidate_rad
        # Sub-bin FFT-squared
        corrected = apply_freq_correction(samples[:seg_len], best_rad)
        residual_rad = _estimate_freq_fft_squared(corrected)
        residual_hz = abs(residual_rad * samp_hz / (2.0 * np.pi))
        if residual_hz < fine_step_hz:
            best_rad += residual_rad
        return best_rad, best_score

    # ── Acquisition mode: hierarchical grid search ────────────────────
    _COARSE_CHIPS = 128
    coarse_code = DEFAULT_PUBLIC_CODE[:_COARSE_CHIPS].copy()

    # Coarse grid with partial correlator
    best_rad = fft_squared_rad
    best_score = _score_freq_candidate_mf(
        samples, fft_squared_rad, samps_per_chip, seg_len,
        code=coarse_code,
    )
    n_coarse = int(grid_half_hz / grid_step_hz)
    for i in range(-n_coarse, n_coarse + 1):
        candidate_rad = i * grid_step_hz * hz_to_rad
        score = _score_freq_candidate_mf(
            samples, candidate_rad, samps_per_chip, seg_len,
            code=coarse_code,
        )
        if score > best_score:
            best_score = score
            best_rad = candidate_rad

    # Fine grid with full correlator around coarse winner
    coarse_hz = best_rad / hz_to_rad
    n_fine = int(grid_step_hz / fine_step_hz) + 1
    for i in range(-n_fine, n_fine + 1):
        candidate_hz = coarse_hz + i * fine_step_hz
        candidate_rad = candidate_hz * hz_to_rad
        score = _score_freq_candidate_mf(
            samples, candidate_rad, samps_per_chip, seg_len,
        )
        if score > best_score:
            best_score = score
            best_rad = candidate_rad

    # Sub-bin FFT-squared refinement
    if best_score >= min_score:
        corrected = apply_freq_correction(samples[:seg_len], best_rad)
        residual_rad = _estimate_freq_fft_squared(corrected)
        residual_hz = abs(residual_rad * samp_hz / (2.0 * np.pi))
        if residual_hz < fine_step_hz:
            best_rad += residual_rad

    return best_rad, best_score


def estimate_freq_offset_rad_per_sample(samples: np.ndarray,
                                         iterations: int = 2) -> float:
    """Iterative R[1] autocorrelation frequency offset estimator.

    R[1] phase = −2π·Δf·T; iterates correction + re-estimation for
    refinement. Returns phase advance per sample in rad (= 2π·Δf·T).
    DC is removed internally (critical for direct-conversion receivers).
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
    rad_per_sample = _require_rad_per_sample("rad_per_sample", rad_per_sample)
    drift_rad_per_sample2 = _require_drift_rad_per_sample2(
        "drift_rad_per_sample2",
        drift_rad_per_sample2,
    )
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
    code: np.ndarray | None = None,
) -> np.ndarray:
    """Complex sample-rate matched filter; preserves carrier phase information."""
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


def _refine_peak(
    mag: np.ndarray, corr_c: np.ndarray, lo: int, hi: int,
) -> tuple[float | None, complex | None]:
    """Parabolic interpolation around argmax; returns (pos, complex_value)."""
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
    frac = _parabolic_frac(y0, y1, y2)
    refined = lo + local_idx + frac
    i0 = int(np.floor(refined))
    i1 = i0 + 1
    if i1 >= len(corr_c):
        return float(refined), complex(corr_c[i0])
    t = refined - i0
    c_refined = (1 - t) * corr_c[i0] + t * corr_c[i1]
    return float(refined), complex(c_refined)


def decode_with_freq_tracking(
    samples: np.ndarray,
    samps_per_chip: int,
    n_bytes: int,
    code: np.ndarray | None = None,
    search_half_samples: int | None = None,
    # lock_threshold_frac: fraction of the initial (or bootstrap-median)
    # MF peak magnitude used as the lock floor for the per-symbol tracker.
    # If a symbol's MF peak falls below lock_threshold_frac × reference_peak,
    # it counts as a "miss" (tracker keeps stepping but flags the symbol).
    # 0.1 (10%) is empirical: DSSS symbol peaks vary by ≈ ±3 dB due to
    # fading and noise, but rarely drop below 10% of the median peak
    # unless the signal is truly gone.  Too high → false track-loss on
    # fading dips; too low → tracker follows noise after signal ends.
    lock_threshold_frac: float = 0.1,
    freq_offset_rad_per_sample: float | None = None,
    precomputed_corr: np.ndarray | None = None,
    start_pos: int | None = None,
    peak_hint: float | None = None,
) -> dict | None:
    """Full-stack decoder: R[1] freq correction → complex MF → symbol tracking.

    Returns dict with bytes, positions, rad_per_sample, peak_magnitude,
    ref_angle_rad, drift_per_symbol_rad, peak_values, etc. or None on failure.

    start_pos: optional sample index into the MF output to begin tracking.
    When provided, the tracker starts near this position rather than the global
    MF peak.  Useful when the global peak is a WiFi/BT spike that is not
    phase-aligned with the DSSS periodic peaks.

    peak_hint: optional expected DSSS peak magnitude.  When provided, used
    instead of mag[start_pos] to compute lock_floor.  Required when start_pos
    is the true DSSS phase but the MF amplitude there is spike-inflated.
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
    rad_per_sample = _require_rad_per_sample("freq_offset_rad_per_sample", rad_per_sample)
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
    if start_pos is not None:
        # Caller pre-computed the DSSS chip phase; find the highest peak
        # within one search window of start_pos.  Avoids being misled by a
        # WiFi/BT spike that happens to be the global max but is not
        # phase-aligned with the periodic DSSS peaks.
        first_candidate = int(np.clip(start_pos, 0, len(mag) - 1))
    else:
        high_threshold = 0.9 * global_peak
        first_candidate = int(np.argmax(mag >= high_threshold))
        if mag[first_candidate] < high_threshold:
            return None
    lo = max(0, first_candidate - search_half_samples)
    hi = min(len(mag), first_candidate + search_half_samples + 1)
    local_idx = int(np.argmax(mag[lo:hi]))
    pos = lo + local_idx
    initial_peak = float(peak_hint if peak_hint is not None else mag[pos])
    # Lock floor: max(2× median noise, softened fraction of initial peak).
    # Re-anchored on median of first BOOTSTRAP peaks below.
    # When peak_hint is supplied the caller has pre-computed the true DSSS
    # peak amplitude (e.g. from the periodic phase average), preventing a
    # WiFi/BT spike at mag[pos] from inflating lock_floor above the DSSS level.
    median_mag = float(np.median(mag))
    length_softening = max(1.0, float(np.sqrt(n_bits / 256.0)))
    lock_floor = max(
        median_mag * 2.0,
        lock_threshold_frac * initial_peak / length_softening,
    )

    ref_angle = float(np.angle(corr_c[pos]))

    # ── 4. Per-symbol tracking loop with parabolic peak refinement ────
    peak_values: list[complex] = []
    positions: list[int] = []

    # BOOTSTRAP: number of initial symbols used to re-anchor lock_floor.
    # The initial lock_floor is set from the first detected peak (or
    # peak_hint), which may be spike-inflated.  After 8 symbols the
    # tracker has enough samples for a robust median that reflects the
    # true DSSS peak level.  8 symbols ≈ 8 ms at 1 ksym/s — short enough
    # to re-anchor before fading or drift invalidates the initial estimate,
    # long enough for the median to suppress 1-2 outlier spikes.  This
    # also spans the 6-byte (48-bit) pilot header, ensuring the bootstrap
    # window includes the known-good pilot region.
    BOOTSTRAP = 8
    max_consecutive_misses = max(8, n_bits // 32)
    consecutive_misses = 0
    for bit_idx in range(n_bits):
        lo = max(0, int(round(pos)) - search_half_samples)
        hi = min(len(mag), int(round(pos)) + search_half_samples + 1)
        if hi - lo < samps_per_chip:
            return None
        refined_pos, refined_c = _refine_peak(mag, corr_c, lo, hi)
        if refined_pos is None or refined_c is None:
            return None
        local_peak = abs(refined_c)
        if local_peak < lock_floor:
            consecutive_misses += 1
            if consecutive_misses > max_consecutive_misses:
                return None
            # Keep noisy sample; step by nominal symbol period.
            peak_values.append(refined_c)
            positions.append(int(round(refined_pos)))
            pos = pos + samples_per_symbol
            continue
        consecutive_misses = 0

        peak_values.append(refined_c)
        positions.append(int(round(refined_pos)))
        pos = refined_pos + samples_per_symbol

        # Re-anchor lock floor on median of first BOOTSTRAP peaks.
        if bit_idx == BOOTSTRAP - 1:
            bootstrap_mags = np.abs(
                np.asarray(peak_values, dtype=np.complex128)
            )
            lock_floor = (
                lock_threshold_frac * float(np.median(bootstrap_mags))
            )

    # ── 5. V-V drift estimation + differential decoding ────────────────
    drift_per_symbol = estimate_drift_per_symbol(peak_values)
    drift_per_symbol = _require_drift_per_symbol("drift_per_symbol", drift_per_symbol)

    bits = np.empty(n_bits, dtype=np.uint8)
    bits[0] = 0                          # caller tries both polarities
    # Pre-compute the drift rotator (constant — same drift each symbol).
    # drift_rotator = exp(-j * drift_per_symbol)
    drift_rotator = complex(np.cos(drift_per_symbol),
                             -np.sin(drift_per_symbol))
    # Vectorized differential DBPSK decode (T1).
    # c_prev_rotated[k] = peaks[k-1] * conj(drift_rotator)
    # dot[k] = Re(peaks[k] * conj(c_prev_rotated[k]))
    #         = Re(peaks[k] * conj(peaks[k-1]) * drift_rotator)
    # bit flips when dot < 0; accumulate flips via XOR.
    peaks = np.asarray(peak_values, dtype=np.complex128)
    dots = (peaks[1:] * np.conj(peaks[:-1]) * drift_rotator).real
    flips = (dots < 0).astype(np.uint8)
    bits[1:] = np.bitwise_xor.accumulate(flips)

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


def _parabolic_frac(y0: float, y1: float, y2: float) -> float:
    """Fractional offset of the peak of a parabola through three samples."""
    denom = y0 - 2 * y1 + y2
    if abs(denom) < 1e-12:
        return 0.0
    return 0.5 * (y0 - y2) / denom


def _phase_spread_rms(coherent_mag: float, incoherent_mag: float) -> float:
    """Convert coherent/incoherent magnitude ratio to equivalent phase spread in radians."""
    if incoherent_mag <= 0:
        return float("inf")
    ratio = coherent_mag / incoherent_mag
    safe_ratio = max(min(ratio, 1.0 - 1e-9), 1e-9)
    return float(np.sqrt(-2.0 * np.log(safe_ratio)))


def estimate_drift_per_symbol(
    peak_values,
    pilot_bits: np.ndarray | None = None,
) -> float:
    """Estimate per-symbol phase drift Δθ in rad/symbol.

    Combines V-V squared estimator (all peaks, range [−π/2,+π/2]) with
    pilot-aided differentials (range [−π,+π], noisier). When pilot_bits
    is given, V-V is unwrapped around the pilot estimate (V-V accuracy
    + pilot's full unambiguous range). Returns 0.0 on degenerate input.
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
        delta_vv: float | None = float(np.angle(s_vv)) / 2.0
    else:
        delta_vv = None

    if pilot_bits is None or len(pilot_bits) < 2:
        # No pilot — V-V is all we have. Bounded to [−π/2, +π/2].
        return _wrap_phase_pi(delta_vv if delta_vv is not None else 0.0)

    # ── Pilot-aided unambiguous coarse estimate ──
    n_pilot = int(min(len(pilot_bits), n))
    if n_pilot < 2:
        return _wrap_phase_pi(delta_vv if delta_vv is not None else 0.0)
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
        return _wrap_phase_pi(delta_pilot)

    # ── Unwrap V-V around pilot estimate ──
    # The true Δθ could be delta_vv, delta_vv + π, or delta_vv − π
    # (V-V wraps every π). Pick whichever is closest to the pilot's
    # unambiguous estimate.
    candidates = (delta_vv, delta_vv + np.pi, delta_vv - np.pi)
    best = min(candidates, key=lambda c: abs(c - delta_pilot))
    return _wrap_phase_pi(float(best))


def dbpsk_decode_from_pilot(
    peak_values,
    pilot_bits: np.ndarray,
    n_data_bits: int,
) -> tuple[bytes, np.ndarray, float, float, float | None]:
    """Hybrid coherent-pilot + differential-body decoder for DBPSK signals.

    Pipeline: (1) Δθ estimate, (2) derotate peaks, (3) coherent pilot
    decode for θ₀, (4) differential body decode anchored on last pilot
    peak, (5) pack into bytes. llr > 0 ⇒ bit 0, llr < 0 ⇒ bit 1.

    Returns (frame_bytes, soft_llrs, θ₀, Δθ, rms_residual_rad) or None.
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
    delta_theta = _wrap_phase_pi(delta_theta)
    delta_theta = _require_drift_per_symbol("delta_theta", delta_theta)

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

    # rms residual: Gaussian phase-jitter equivalent
    coherent_mag = abs(coherent_sum)
    incoherent_mag = float(np.sum(np.abs(aligned)))
    rms_residual = _phase_spread_rms(coherent_mag, incoherent_mag)

    # Apply θ₀ derotation to the entire frame for consistency.
    theta_rotator = np.exp(-1j * theta0)
    fully_derotated = derotated * theta_rotator

    # ── 4. Pilot-region LLRs (coherent) ──
    pilot_llrs = fully_derotated[:n_pilot].real.astype(np.float32)

    # ── 5. Body-region LLRs (differential, drift-compensated) ──
    # The differential product y_k * conj(y_{k-1}) has residual phase
    # delta_theta per symbol from carrier frequency offset.  Without
    # compensation, the .real projection attenuates the LLR by cos(Δθ)
    # which is catastrophic when Δθ >> 0.1 rad (e.g. 15 kHz CFO at
    # 1 ksym/s gives Δθ ≈ 96 rad — essentially random projection).
    # Apply the same drift rotator as decode_with_freq_tracking.
    raw_body = peaks_arr[n_pilot:]
    n_body = n_data_bits - n_pilot
    if n_body > 0:
        prev_peaks = np.empty(n_body, dtype=np.complex128)
        prev_peaks[0] = peaks_arr[n_pilot - 1]
        prev_peaks[1:] = raw_body[:-1]
        drift_rotator = complex(np.cos(delta_theta), -np.sin(delta_theta))
        uncomp = (raw_body * np.conj(prev_peaks)).real.astype(np.float32)
        body_llrs = (raw_body * np.conj(prev_peaks) * drift_rotator).real.astype(np.float32)
        if SISL_DEBUG:
            sign_changes = float(np.mean(np.signbit(uncomp) != np.signbit(body_llrs)))
            debug_telemetry(
                "framer",
                status="dbpsk_comp",
                drift_rad=delta_theta,
                mean_abs_llr=float(np.mean(np.abs(body_llrs))),
                phase_rms=rms_residual,
                mean_abs_pilot=float(np.mean(np.abs(pilot_llrs))),
                mean_abs_body_unc=float(np.mean(np.abs(uncomp))),
                sign_flip=sign_changes,
            )
    else:
        body_llrs = np.zeros(0, dtype=np.float32)

    soft = np.concatenate([pilot_llrs, body_llrs]).astype(np.float32)
    bits = (soft < 0).astype(np.uint8)
    pad = (-n_data_bits) % 8
    if pad:
        bits = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
    frame_bytes = np.packbits(bits).tobytes()

    return frame_bytes, soft, theta0, delta_theta, rms_residual
