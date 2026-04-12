"""SISL DSSS receive-side DSP: acquisition, tracking, FEC decode, decrypt."""

from __future__ import annotations

import numpy as np
from cryptography.hazmat.primitives.asymmetric import ec

import sisl_crypto as sc
import sisl_fec
import sisl_framer as sf


# Initial signal-presence prefilter — a cheap peak/median ratio test
# that rejects the noisiest blocks before running the more expensive
# periodicity check. The periodicity check (16 symbol-spaced peaks
# median >= 30% of global max) is the authoritative test; this ratio
# is just a cheap first-pass filter.
#
# Pure Gaussian noise gives peak/median ~= 5-8 for block lengths of
# millions of samples. Weak-but-real bench signals can sit at ratio
# 4-10 when antennas are misaligned or path loss is large. Default
# of 4 admits most real signals and lets the periodicity check do
# the real rejection. Override with --signal-threshold.
_SIGNAL_FLOOR_RATIO = 4.0


# Bit-unpacked ASM for sliding-bit-offset search. MSB-first to match
# bytes_to_bits / rx_chips_to_bytes conventions.
_ASM_BITS = np.unpackbits(
    np.frombuffer(sc.ASM, dtype=np.uint8)
).astype(np.uint8)

# Extended pilot: ASM + deterministic version (0x03) and msg_type (0x01)
# bytes. Every valid SISL hail frame begins with ASM || 0x03 || 0x01,
# so these 48 bits are a free extended training sequence for phase and
# frequency estimation. Longer pilot = tighter slope variance = better
# coherent decode at marginal SNR.
_PILOT_BYTES = sc.ASM + bytes([sc.SISL_VERSION, sc.MSG_HAIL])
_PILOT_BITS = np.unpackbits(
    np.frombuffer(_PILOT_BYTES, dtype=np.uint8)
).astype(np.uint8)

_ACK_PILOT_BYTES = sc.ASM + bytes([sc.SISL_VERSION, sc.MSG_ACK])
_ACK_PILOT_BITS = np.unpackbits(
    np.frombuffer(_ACK_PILOT_BYTES, dtype=np.uint8)
).astype(np.uint8)


class LlrAccumulator:
    """Multi-copy FEC LLR accumulator for SISL hails.

    The TX loops the same FEC-encoded hail frame repeatedly. Each clean
    per-block detection yields a per-bit soft-value vector. Adding these
    vectors element-wise across copies gives +3 dB effective SNR per
    doubling (coherent addition of independent AWGN observations).

    The accumulator stores only the FEC body LLRs (2048 coded bits);
    the 48-bit uncoded header is used for polarity vote and ASM
    cheap-reject but is not summed. try_decrypt runs sisl_fec.decode
    (soft Viterbi) on the accumulated body LLRs.

    `max_copies` is the cap before exponential forgetting (halving).
    """

    def __init__(self, n_bits: int, pass_rms: float = 0.6,
                 max_copies: int = 64, max_asm_errs: int = 2):
        assert n_bits == sc.HAIL_FEC_TOTAL_BITS, (
            f"n_bits must be HAIL_FEC_TOTAL_BITS "
            f"({sc.HAIL_FEC_TOTAL_BITS}); got {n_bits}"
        )
        self.n_bits = n_bits
        self.pass_rms = pass_rms
        self.max_copies = max_copies
        self.max_asm_errs = max_asm_errs
        self._header_bits = sc.HAIL_FEC_HEADER_BITS
        self._accum_size = sc.HAIL_FEC_BODY_CODED_BITS
        self.accumulated = np.zeros(self._accum_size, dtype=np.float64)
        self.n_copies = 0
        self._asm_signs = np.where(_ASM_BITS == 0, 1.0, -1.0).astype(np.float64)

    def reset(self) -> None:
        self.accumulated.fill(0.0)
        self.n_copies = 0

    def try_add(self, result: dict) -> bool:
        """Try to add a block-decode result to the accumulator.

        Returns True if the result was accepted and added, False otherwise.
        """
        llrs = result.get("fec_llrs")
        if llrs is None:
            return False
        if len(llrs) < self.n_bits:
            return False
        # The soft-Viterbi + Poly1305 gate at try_decrypt is the real
        # quality oracle. Skip phase_rms and asm_errs gates -- the FEC +
        # crypto layer rejects bad copies after combining.
        # DBPSK body LLRs are phase-invariant: the differential dot
        # product Re(y_k * conj(y_{k-1})) has the correct sign regardless
        # of absolute phase theta_0. NO polarity vote -- applying one flips
        # correct body LLRs based on noisy pilot phase, causing ~half the
        # copies to cancel instead of add (sublinear L1 growth).
        llrs_f64 = llrs[:self.n_bits].astype(np.float64)
        body_llrs = llrs_f64[self._header_bits:]
        self.accumulated += body_llrs
        self.n_copies += 1
        return True

    def try_decrypt(
        self,
        responder_static,
    ) -> tuple[object, str, int | None]:
        """Soft-Viterbi-decode accumulated body LLRs and trial-decrypt.

        Returns (decoded_hail, polarity_label, chase_flips) or None.
        """
        if self.n_copies == 0:
            return None
        body_llrs_f32 = sc._deinterleave_llrs(
            self.accumulated.astype(np.float32))
        body_bits = sisl_fec.decode(
            body_llrs_f32, sc.HAIL_FEC_BODY_PAYLOAD_BITS,
        )
        body_bytes = np.packbits(body_bits).tobytes()
        assert len(body_bytes) == sc.HAIL_BODY_PAYLOAD_LEN
        header = sc.ASM + bytes([sc.SISL_VERSION, sc.MSG_HAIL])
        frame = header + body_bytes
        decoded = sc.decode_hail(frame, responder_static)
        if decoded is not None:
            return decoded, "fec-acc", 0
        return None


# Pre-computed differential polarity template for the 32-bit ASM.
# For each of 31 consecutive bit pairs in the ASM, the "expected" differential
# dot-product sign is +1 if the two bits are equal (same bit), -1 if they differ.
# Soft-decision ASM search correlates this template against the actual
# differential dot-product stream.
_ASM_DIFF_POLARITY = np.where(
    _ASM_BITS[1:] == _ASM_BITS[:-1],
    +1.0, -1.0,
).astype(np.float64)


def find_sisl_frame_soft_topk(
    peak_values: list,
    frame_len: int = sc.HAIL_FRAME_LEN,
    k: int = 5,
    min_separation: int = 4,
) -> list:
    """Return the top-K ASM candidate positions by |soft_score|.

    At marginal SNR, the argmax soft score may be a noise-driven winner
    while the true ASM sits at a lower-but-plausible position. Searching
    the top K candidates lets the downstream coherent+chase decode try
    each alternative before giving up.

    `min_separation` enforces that returned candidates are at least N
    bit positions apart, so adjacent samples in the same peak neighborhood
    don't all crowd the top-K list.

    Returns a list of (bit_offset, soft_score, pts_ratio) tuples,
    sorted by |soft_score| descending, at most K entries long.
    `pts_ratio` is the candidate's |score| divided by the median |score|
    across all positions -- a CFAR-style peak-to-sidelobe ratio usable
    as an additional cheap gate before feeding candidates to the
    expensive coherent decode + Chase pipeline. Clean signal has
    pts_ratio > 5; pure noise has pts_ratio ~= 2-3.
    Empty list if the buffer is too short.
    """
    n_bits = frame_len * 8
    n_peaks = len(peak_values)
    if n_peaks < 33:
        return []

    peaks = np.array(peak_values, dtype=np.complex128)
    diffs = (peaks[1:] * np.conj(peaks[:-1])).real
    mags = np.abs(peaks[1:]) * np.abs(peaks[:-1])
    soft = np.where(mags > 1e-12, diffs / mags, 0.0).astype(np.float64)

    template = _ASM_DIFF_POLARITY
    n_soft = len(soft)
    if n_soft < 31:
        return []

    n_positions = n_soft - 30
    windowed = np.lib.stride_tricks.sliding_window_view(
        soft, window_shape=31
    )[:n_positions]
    scores = windowed @ template
    abs_scores = np.abs(scores)

    sidelobe = float(np.median(abs_scores)) + 1e-9

    taken = np.zeros(n_positions, dtype=bool)
    results = []
    for _ in range(k):
        candidate_mask = ~taken
        if not candidate_mask.any():
            break
        masked = np.where(candidate_mask, abs_scores, -1.0)
        idx = int(np.argmax(masked))
        if masked[idx] <= 0:
            break
        score = float(scores[idx])
        pts_ratio = float(abs_scores[idx]) / sidelobe
        results.append((idx, score, pts_ratio))
        lo = max(0, idx - min_separation)
        hi = min(n_positions, idx + min_separation + 1)
        taken[lo:hi] = True
    return results


def _extract_llrs_at_position(
    peak_values: list,
    peak_offset: int,
) -> dict:
    """Run the DBPSK decoder at one ASM offset and return FEC LLRs.

    Returns a dict with fec_llrs (2096 float32), phase_rms_residual_rad,
    and asm_errs_in_coherent. All None if the offset is out of range or
    the decode fails.
    """
    out: dict = {
        "fec_llrs": None,
        "phase_rms_residual_rad": None,
        "asm_errs_in_coherent": None,
    }
    aligned_peaks = peak_values[peak_offset:]
    n_fec_bits = sc.HAIL_FEC_TOTAL_BITS
    if len(aligned_peaks) < n_fec_bits:
        return out

    dbpsk = sf.dbpsk_decode_from_pilot(
        aligned_peaks, _PILOT_BITS, n_fec_bits,
    )
    if dbpsk is None:
        return out
    fec_frame, fec_soft, theta0, delta_theta, rms = dbpsk
    out["fec_llrs"] = fec_soft
    out["phase_rms_residual_rad"] = rms
    c_bits_first32 = np.unpackbits(
        np.frombuffer(fec_frame[:4], dtype=np.uint8))
    out["asm_errs_in_coherent"] = int(np.sum(c_bits_first32 != _ASM_BITS))
    return out


def _acquire_and_track(
    samples: np.ndarray,
    samps_per_chip: int,
    samp_hz: float,
    signal_threshold: float,
    fec_total_bits: int = sc.HAIL_FEC_TOTAL_BITS,
) -> dict:
    """Frequency estimation, correction, matched filter, periodicity test,
    and per-symbol tracking decode.

    Returns a dict with peak_values, positions, freq_hz, peak_mag,
    median_mag, rad_per_sample on success, or a status dict on failure.
    """
    if len(samples) < sf.CHIPS_PER_SYMBOL * samps_per_chip * 200:
        return {"status": "short_block"}

    samples = (samples - samples.mean()).astype(np.complex64)
    # Two-stage frequency estimation:
    # 1. R[1] coarse (± tens of kHz — often wrong at low wideband SNR,
    # FFT-squared frequency estimation: square the signal to remove
    # BPSK modulation, FFT to find the spectral line at 2× carrier
    # offset. No R[1] coarse correction — R[1] is unreliable at DSSS
    # wideband SNR and applying it can shift the signal to the band
    # edge where it aliases.
    rad_per_sample = sf._estimate_freq_fft_squared(samples)
    freq_hz = rad_per_sample * samp_hz / (2 * np.pi)
    samples_corr = sf.apply_freq_correction(samples, rad_per_sample)

    corr_c = sf.matched_filter_complex_sample_rate(samples_corr, samps_per_chip)
    if len(corr_c) == 0:
        return {"status": "short_block"}
    mag = np.abs(corr_c).astype(np.float32)
    peak_mag = float(mag.max())
    median_mag = float(np.median(mag))

    prefilter_threshold = min(signal_threshold, 2.5)
    if median_mag == 0.0 or peak_mag < prefilter_threshold * median_mag:
        return {
            "status": "no_signal",
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
        }

    first_peak_pos = int(np.argmax(mag))
    samples_per_symbol = sf.CHIPS_PER_SYMBOL * samps_per_chip
    search_half = samples_per_symbol // 4
    test_peaks: list[float] = []
    for k in range(16):
        pos_k = first_peak_pos + k * samples_per_symbol
        if pos_k + search_half >= len(mag):
            break
        lo = max(0, pos_k - search_half)
        hi = min(len(mag), pos_k + search_half + 1)
        test_peaks.append(float(mag[lo:hi].max()))

    if len(test_peaks) < 4:
        return {"status": "short_block", "peak_mag": peak_mag, "median_mag": median_mag}

    periodic_ratio = float(np.median(test_peaks)) / peak_mag if peak_mag > 0 else 0.0
    # Lowered from 0.3 to 0.15: WiFi/BLE bursts at 2.4 GHz create
    # non-periodic MF spikes that suppress the periodic ratio even
    # when the DSSS signal is present underneath. The FEC + Poly1305
    # tag is the real integrity gate — this check just saves wasted
    # compute on pure-noise blocks.
    if periodic_ratio < 0.15:
        return {
            "status": "no_signal",
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
            "periodic_ratio": periodic_ratio,
            "note": "spurious spike, no periodic structure",
        }

    target_bytes = (2 * fec_total_bits + 7) // 8
    track_result = sf.decode_with_freq_tracking(
        samples,
        samps_per_chip=samps_per_chip,
        n_bytes=target_bytes,
        freq_offset_rad_per_sample=rad_per_sample,
        precomputed_corr=corr_c,
    )
    if track_result is None:
        fallback_bytes = (fec_total_bits + 7) // 8
        track_result = sf.decode_with_freq_tracking(
            samples,
            samps_per_chip=samps_per_chip,
            n_bytes=fallback_bytes,
            freq_offset_rad_per_sample=rad_per_sample,
            precomputed_corr=corr_c,
        )
        if track_result is None:
            return {
                "status": "track_lost",
                "peak_mag": peak_mag,
                "median_mag": median_mag,
                "rad_per_sample": rad_per_sample,
                "freq_offset_hz": freq_hz,
            }

    return {
        "status": "acquired",
        "peak_values": track_result.get("peak_values", []),
        "positions": track_result["positions"],
        "freq_hz": freq_hz,
        "peak_mag": peak_mag,
        "median_mag": median_mag,
        "rad_per_sample": rad_per_sample,
    }


def _try_fec_decrypt(
    peak_values: list,
    positions: list,
    responder_static: ec.EllipticCurvePrivateKey,
    top_k_soft: int,
    freq_hz: float,
    peak_mag: float,
    median_mag: float,
    rad_per_sample: float,
) -> dict:
    """FEC fast path: soft correlator search, DBPSK decode, Viterbi, decrypt.

    Returns a result dict with status decrypt_ok, decrypt_fail, or track_lost.
    """
    if not peak_values or len(peak_values) < sc.HAIL_FEC_TOTAL_BITS:
        return {
            "status": "track_lost",
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
            "note": "peak_values too short for HAIL_FEC_TOTAL_BITS",
        }

    topk = find_sisl_frame_soft_topk(
        peak_values, sc.HAIL_FRAME_LEN, k=top_k_soft,
    )

    best_attempt: dict | None = None
    best_offset = -1
    best_score = 0.0
    best_pts_ratio = 0.0
    decoded_hail: sc.DecodedHail | None = None
    polarity_label = "fec"
    extra_fec_llrs: list[np.ndarray] = []

    for cand_offset, cand_score, cand_pts in topk:
        if cand_offset + sc.HAIL_FEC_TOTAL_BITS > len(peak_values):
            continue
        if abs(cand_score) <= 10.0 or cand_pts < 3.0:
            continue

        llr_diag = _extract_llrs_at_position(peak_values, int(cand_offset))
        fec_llrs_arr = llr_diag.get("fec_llrs")
        if fec_llrs_arr is None:
            continue

        attempt = sc.decode_hail_fec_from_llrs(fec_llrs_arr, responder_static)
        if attempt is None:
            attempt = sc.decode_hail_fec_from_llrs(
                -fec_llrs_arr, responder_static,
            )
            if attempt is not None:
                polarity_label = "fec-inv"
        else:
            polarity_label = "fec"

        if attempt is not None:
            decoded_hail = attempt
            best_offset = int(cand_offset)
            best_score = float(cand_score)
            best_pts_ratio = float(cand_pts)
            best_attempt = {"llr_diag": llr_diag, "fec_llrs": fec_llrs_arr}
            break

        extra_fec_llrs.append(fec_llrs_arr)
        if best_attempt is None or abs(cand_score) > abs(best_score):
            best_attempt = {"llr_diag": llr_diag, "fec_llrs": fec_llrs_arr}
            best_offset = int(cand_offset)
            best_score = float(cand_score)
            best_pts_ratio = float(cand_pts)

    if best_attempt is None:
        return {
            "status": "track_lost",
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
            "note": "no soft-correlator candidate cleared the gate",
        }

    llr_diag = best_attempt["llr_diag"]
    fec_llrs_arr = best_attempt["fec_llrs"]
    base = {
        "start_sample": positions[0] if positions else 0,
        "asm_at_byte": f"soft-bit{best_offset}",
        "peak_mag": peak_mag,
        "median_mag": median_mag,
        "rad_per_sample": rad_per_sample,
        "freq_offset_hz": freq_hz,
        "soft_score": best_score,
        "pts_ratio": best_pts_ratio,
        "fec_llrs": fec_llrs_arr,
        "extra_fec_llrs": extra_fec_llrs,
        "phase_rms_residual_rad": llr_diag["phase_rms_residual_rad"],
        "asm_errs_in_coherent": llr_diag["asm_errs_in_coherent"],
    }
    if decoded_hail is None:
        return {"status": "decrypt_fail", "polarity": "fec", **base}
    return {
        "status": "decrypt_ok",
        "polarity": polarity_label,
        "body": decoded_hail.body,
        "caller_eph_pub_canonical": decoded_hail.caller_eph_pub_canonical,
        "decoded_hail": decoded_hail,  # full object for ACK construction
        **base,
    }


def _decode_one_hail_in_block(
    samples: np.ndarray,
    responder_static: ec.EllipticCurvePrivateKey,
    samps_per_chip: int = 8,
    samp_hz: float = 8_000_000.0,
    signal_threshold: float = _SIGNAL_FLOOR_RATIO,
    top_k_soft: int = 5,
) -> dict:
    """Process one block of baseband samples, try to decode one FEC hail.

    Thin dispatcher: calls _acquire_and_track, then _try_fec_decrypt.

    Statuses:
      short_block   -- fewer than one code-period of samples
      no_signal     -- CORRECTED peak/median below threshold
      track_lost    -- tracker lost lock partway through the frame
      decrypt_fail  -- hail frame found but Poly1305 tag mismatch
      decrypt_ok    -- hail decoded and decrypted under responder_static
    """
    acq = _acquire_and_track(samples, samps_per_chip, samp_hz, signal_threshold)
    if acq["status"] != "acquired":
        return acq

    return _try_fec_decrypt(
        peak_values=acq["peak_values"],
        positions=acq["positions"],
        responder_static=responder_static,
        top_k_soft=top_k_soft,
        freq_hz=acq["freq_hz"],
        peak_mag=acq["peak_mag"],
        median_mag=acq["median_mag"],
        rad_per_sample=acq["rad_per_sample"],
    )


# ── ACK decode path (parallel to hail, different frame sizes) ────────────

def _extract_ack_llrs_at_position(
    peak_values: list,
    peak_offset: int,
) -> dict:
    """Run the DBPSK decoder at one ASM offset for an ACK frame."""
    out: dict = {
        "fec_llrs": None,
        "phase_rms_residual_rad": None,
        "asm_errs_in_coherent": None,
    }
    aligned_peaks = peak_values[peak_offset:]
    n_fec_bits = sc.ACK_FEC_TOTAL_BITS
    if len(aligned_peaks) < n_fec_bits:
        return out

    dbpsk = sf.dbpsk_decode_from_pilot(
        aligned_peaks, _ACK_PILOT_BITS, n_fec_bits,
    )
    if dbpsk is None:
        return out
    fec_frame, fec_soft, _, _, rms = dbpsk
    out["fec_llrs"] = fec_soft
    out["phase_rms_residual_rad"] = rms
    c_bits_first32 = np.unpackbits(
        np.frombuffer(fec_frame[:4], dtype=np.uint8))
    out["asm_errs_in_coherent"] = int(np.sum(c_bits_first32 != _ASM_BITS))
    return out


def _try_ack_fec_decrypt(
    peak_values: list,
    positions: list,
    caller_static_priv: ec.EllipticCurvePrivateKey,
    caller_eph_priv: ec.EllipticCurvePrivateKey,
    dh1: bytes,
    expected_nonce_echo: bytes,
    top_k_soft: int,
    freq_hz: float,
    peak_mag: float,
    median_mag: float,
    rad_per_sample: float,
) -> dict:
    """ACK-specific FEC decrypt path. Parallel to _try_fec_decrypt."""
    if not peak_values or len(peak_values) < sc.ACK_FEC_TOTAL_BITS:
        return {
            "status": "track_lost",
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
        }

    topk = find_sisl_frame_soft_topk(
        peak_values, sc.ACK_FRAME_LEN, k=top_k_soft,
    )

    best_attempt = None
    best_offset = -1
    best_score = 0.0
    best_pts_ratio = 0.0
    decoded_ack = None
    polarity_label = "ack-fec"

    for cand_offset, cand_score, cand_pts in topk:
        if cand_offset + sc.ACK_FEC_TOTAL_BITS > len(peak_values):
            continue
        if abs(cand_score) <= 10.0 or cand_pts < 3.0:
            continue

        llr_diag = _extract_ack_llrs_at_position(
            peak_values, int(cand_offset))
        fec_llrs_arr = llr_diag.get("fec_llrs")
        if fec_llrs_arr is None:
            continue

        attempt = sc.decode_ack_fec_from_llrs(
            fec_llrs_arr, caller_static_priv, caller_eph_priv,
            dh1, expected_nonce_echo)
        if attempt is None:
            attempt = sc.decode_ack_fec_from_llrs(
                -fec_llrs_arr, caller_static_priv, caller_eph_priv,
                dh1, expected_nonce_echo)
            if attempt is not None:
                polarity_label = "ack-fec-inv"
        else:
            polarity_label = "ack-fec"

        if attempt is not None:
            decoded_ack = attempt
            best_offset = int(cand_offset)
            best_score = float(cand_score)
            best_pts_ratio = float(cand_pts)
            best_attempt = {"llr_diag": llr_diag}
            break

        if best_attempt is None or abs(cand_score) > abs(best_score):
            best_attempt = {"llr_diag": llr_diag}
            best_offset = int(cand_offset)
            best_score = float(cand_score)
            best_pts_ratio = float(cand_pts)

    if best_attempt is None:
        return {
            "status": "track_lost",
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
        }

    base = {
        "start_sample": positions[0] if positions else 0,
        "asm_at_byte": f"soft-bit{best_offset}",
        "peak_mag": peak_mag,
        "median_mag": median_mag,
        "rad_per_sample": rad_per_sample,
        "freq_offset_hz": freq_hz,
        "soft_score": best_score,
        "pts_ratio": best_pts_ratio,
    }
    if decoded_ack is None:
        return {"status": "decrypt_fail", "polarity": polarity_label, **base}
    return {
        "status": "decrypt_ok",
        "polarity": polarity_label,
        "decoded_ack": decoded_ack,
        "body": decoded_ack.body,
        **base,
    }


def decode_one_ack_in_block(
    samples: np.ndarray,
    caller_static_priv: ec.EllipticCurvePrivateKey,
    caller_eph_priv: ec.EllipticCurvePrivateKey,
    dh1: bytes,
    expected_nonce_echo: bytes,
    samps_per_chip: int = 2,
    samp_hz: float = 2_000_000.0,
    signal_threshold: float = _SIGNAL_FLOOR_RATIO,
    top_k_soft: int = 5,
) -> dict:
    """Process one block, try to decode an ACK frame.

    Parallel to _decode_one_hail_in_block but for the 95-byte ACK.
    """
    # Use the hail tracker target (4192 bits) rather than the ACK target
    # (2976 bits). The hail target tracks more symbols, giving the soft
    # correlator more room to find the ACK's ASM. With HackRF spurs, the
    # tracker's first_candidate can land on a spur peak; a longer target
    # gives more opportunities for the real signal peaks to dominate.
    # The _try_ack_fec_decrypt extracts only the 1488 bits it needs.
    acq = _acquire_and_track(
        samples, samps_per_chip, samp_hz, signal_threshold,
        fec_total_bits=sc.HAIL_FEC_TOTAL_BITS,
    )
    if acq["status"] != "acquired":
        return acq

    return _try_ack_fec_decrypt(
        peak_values=acq["peak_values"],
        positions=acq["positions"],
        caller_static_priv=caller_static_priv,
        caller_eph_priv=caller_eph_priv,
        dh1=dh1,
        expected_nonce_echo=expected_nonce_echo,
        top_k_soft=top_k_soft,
        freq_hz=acq["freq_hz"],
        peak_mag=acq["peak_mag"],
        median_mag=acq["median_mag"],
        rad_per_sample=acq["rad_per_sample"],
    )


def _print_live_event(block_num: int, result: dict, quiet: bool = False) -> None:
    s = result["status"]
    foff = result.get("freq_offset_hz", 0.0)
    # Signal power estimate: peak/median of MF output in dB.
    # peak_mag = signal + noise at the symbol peak, median_mag ≈ noise.
    # SNR ≈ (peak/median)² in linear → 20*log10(peak/median) in dB.
    pk = result.get("peak_mag", 0)
    md = result.get("median_mag", 0)
    if md > 0 and pk > 0:
        snr_db = 20.0 * np.log10(pk / md)
        snr_str = f"SNR={snr_db:+.1f}dB"
    else:
        snr_str = ""
    _GREEN = "\033[32m"
    _RESET = "\033[0m"
    if s == "decrypt_ok":
        b = result.get("body")
        pol = result.get("polarity", "?")
        detail = ""
        if b is not None and hasattr(b, "body_nonce"):
            # HailBody
            detail = (f"nonce={b.body_nonce.hex()}  "
                      f"freq=+{b.center_freq_offset}MHz  "
                      f"mode=0x{b.mode:02x}")
        elif b is not None and hasattr(b, "nonce_echo"):
            # AckBody
            detail = (f"status={b.status}  "
                      f"nonce_echo={b.nonce_echo.hex()}")
        print(f"{_GREEN}[{block_num:4d}] DECRYPTED  "
              f"asm@{result['asm_at_byte']}  "
              f"peak={pk:.3g}  {snr_str}  "
              f"\u0394f={foff:+.0f}Hz  "
              f"pol={pol}  "
              f"{detail}{_RESET}")
    elif s == "decrypt_fail":
        print(f"[{block_num:4d}] FRAME FOUND  "
              f"asm@{result['asm_at_byte']}  "
              f"{snr_str}  "
              f"\u0394f={foff:+.0f}Hz  "
              f"pol={result.get('polarity', '?')}  "
              f"\u2014 DECRYPT FAILED")
    elif s == "track_lost":
        p = result.get("peak_mag", 0)
        m = result.get("median_mag", 0)
        r = p / m if m > 0 else float("inf")
        print(f"[{block_num:4d}] TRACK LOST: "
              f"peak={p:.3g}, median={m:.3g}, ratio={r:.1f}, "
              f"\u0394f={foff:+.0f}Hz")
    elif quiet:
        return
    elif s == "no_signal":
        p = result.get("peak_mag", 0)
        m = result.get("median_mag", 0)
        r = p / m if m > 0 else float("inf")
        periodic = result.get("periodic_ratio", None)
        note = result.get("note", "")
        extra = ""
        if periodic is not None:
            extra = f", periodic={periodic:.2f}"
            if note:
                extra += f" ({note})"
        print(f"[{block_num:4d}] no signal: "
              f"peak={p:.3g}, median={m:.3g}, ratio={r:.1f}, "
              f"\u0394f={foff:+.0f}Hz{extra}")
    elif s == "short_block":
        print(f"[{block_num:4d}] short block (processing gap)")
