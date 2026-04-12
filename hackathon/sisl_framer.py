"""SISL framer / deframer — pure-numpy DSP for BPSK-DSSS TX/RX.

TX: bytes → BPSK symbols (±1) → spread by 1023-chip code → int8 chips
RX: chips → reshape → row-dot with code → sign decision → bytes

Assumes chip-aligned start; add a sliding correlator for acquisition.
"""

from __future__ import annotations


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
    out = np.empty_like(bits)
    prev = int(seed) & 1
    for k in range(len(bits)):
        prev = prev ^ int(bits[k])
        out[k] = prev
    return out


def differential_decode_bits(bits: np.ndarray, seed: int = 0) -> np.ndarray:
    """Inverse of differential_encode_bits: b_k = bits[k] XOR bits[k−1]."""
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
    nfft = min(N, 2**20)  # cap at 1M-point FFT for speed
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

    # Validate each candidate: apply correction, run a QUICK MF on a
    # short segment, pick the one with the best peak/median.
    seg_len = min(N, 2_000_000)  # 1 second at 2 Msps
    seg = np.asarray(samples[:seg_len], dtype=np.complex64)
    best_rad = candidates[0]
    best_ratio = 0.0
    for cand_rad in candidates:
        corrected = apply_freq_correction(seg, cand_rad)
        # Quick MF — assume 2 samples/chip (works for any samps_per_chip
        # since we just need relative peak/median, not absolute)
        spc = max(2, round(len(seg) / 1024 / 1023)) if len(seg) > 2046 else 2
        spc = min(spc, 8)  # cap at 8
        corr = matched_filter_complex_sample_rate(corrected, 2)
        if len(corr) < 100:
            continue
        m = np.abs(corr).astype(np.float32)
        ratio = float(m.max()) / max(float(np.median(m)), 1e-12)
        if ratio > best_ratio:
            best_ratio = ratio
            best_rad = cand_rad

    return best_rad


def estimate_freq_drift_rate(samples: np.ndarray,
                             n_segments: int = 6) -> tuple[float, float]:
    """Estimate carrier offset and linear drift rate from sub-block R[1].

    Splits into `n_segments` sub-blocks, fits a line through per-segment
    R[1] estimates. Returns (rad_per_sample_at_start, drift_rad_per_sample²).
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
    lock_threshold_frac: float = 0.1,
    freq_offset_rad_per_sample: float | None = None,
    precomputed_corr: np.ndarray | None = None,
) -> dict | None:
    """Full-stack decoder: R[1] freq correction → complex MF → symbol tracking.

    Returns dict with bytes, positions, rad_per_sample, peak_magnitude,
    ref_angle_rad, drift_per_symbol_rad, peak_values, etc. or None on failure.
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
    initial_peak = float(mag[pos])
    # Lock floor: max(2× median noise, softened fraction of initial peak).
    # Re-anchored on median of first BOOTSTRAP peaks below.
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


def fit_phase_from_known_bits(
    peak_values,
    start_bit_offset: int,
    known_bits: np.ndarray,
    delta_search_range: float = np.pi,
    delta_fine_steps: int = 8,
) -> tuple[float, float, float | None]:
    """ML fit of absolute phase θ₀ and per-symbol drift Δθ from a known pilot.

    Derotate by known bit sign: d[k] = sign[k] · peak[k] ≈ |p|·exp(j·(θ₀+k·Δθ))
        Δθ̂ = argmax_{δ} |Σ_k d[k]·exp(-j·k·δ)|²   (FFT peak, zero-padded)
        θ̂₀ = angle(Σ_k d[k]·exp(-j·k·Δθ̂))

    rms_residual ≈ sqrt(-2·ln(coherent/incoherent)): <0.3 clean, >1.5 noise.

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
) -> tuple[float, float, float | None]:
    """Convert pilot phase slope Δθ to residual freq offset in Hz.

    f_residual = (Δθ · symbol_rate_hz) / (2π).
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

    # ── 5. Body-region LLRs (differential, on raw peaks for drift immunity) ──
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





