"""SISL DSSS receive-side DSP: acquisition, tracking, FEC decode, decrypt."""

from __future__ import annotations

import os
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
_PERIODICITY_BYPASS_MF_SCORE = 3.0
_PERIODIC_RATIO_MIN = 0.15
_SOFT_SCORE_MIN_HAIL_ACK = 10.0
_SOFT_PTS_RATIO_MIN = 3.0
_SOFT_SCORE_MIN_PAYLOAD = 5.0
_RX_DEBUG = bool(os.environ.get("SISL_DEBUG"))


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
    """Multi-copy FEC LLR accumulator for SISL hails or ACK frames.

    The TX loops the same FEC-encoded frame repeatedly. Each clean
    per-block detection yields a per-bit soft-value vector. Adding these
    vectors element-wise across copies gives +3 dB effective SNR per
    doubling (coherent addition of independent AWGN observations).

    The accumulator stores only the FEC body LLRs; the uncoded header
    is used for polarity vote and ASM cheap-reject but is not summed.
    try_decrypt runs sisl_fec.decode (soft Viterbi) on accumulated body LLRs.

    `max_copies` is the cap before exponential forgetting (halving the
    accumulated LLRs before adding the new copy — sliding-window behaviour).

    Frequency-drift flush: if a new block's frequency estimate differs
    from the running estimate by more than `freq_flush_hz` (default 5×
    chip rate = 5000 Hz at 1 Mcps), the accumulator is flushed and
    restarted with the new block's LLRs only.  This prevents stale LLRs
    from a previous hail (different ephemeral key / carrier offset) from
    contaminating a new one.
    """

    def __init__(self, n_bits: int, pass_rms: float = 0.6,
                 max_copies: int = 64, max_asm_errs: int = 2,
                 freq_flush_hz: float = 5000.0):
        self.n_bits = n_bits
        self.pass_rms = pass_rms
        self.max_copies = max_copies
        self.max_asm_errs = max_asm_errs
        self.freq_flush_hz = freq_flush_hz
        # For hail frames the body starts after the header; for ACK frames
        # all bits are FEC body (no separate header field in sisl_crypto).
        if n_bits not in (sc.HAIL_FEC_TOTAL_BITS, sc.ACK_FEC_TOTAL_BITS):
            raise ValueError(
                f"n_bits must be HAIL_FEC_TOTAL_BITS ({sc.HAIL_FEC_TOTAL_BITS}) "
                f"or ACK_FEC_TOTAL_BITS ({sc.ACK_FEC_TOTAL_BITS}); got {n_bits}"
            )
        if n_bits == sc.HAIL_FEC_TOTAL_BITS:
            self._header_bits = sc.HAIL_FEC_HEADER_BITS
            self._accum_size = sc.HAIL_FEC_BODY_CODED_BITS
        else:
            # ACK frame: accumulate all FEC bits as body.
            self._header_bits = 0
            self._accum_size = n_bits
        self.accumulated = np.zeros(self._accum_size, dtype=np.float64)
        self.n_copies = 0
        self._running_freq_hz: float | None = None
        self._asm_signs = np.where(_ASM_BITS == 0, 1.0, -1.0).astype(np.float64)

    def reset(self) -> None:
        self.accumulated.fill(0.0)
        self.n_copies = 0
        self._running_freq_hz = None

    def try_add(self, result: dict) -> bool:
        """Try to add a block-decode result to the accumulator.

        Returns True if the result was accepted and added, False otherwise.

        Frequency-drift flush: if the incoming block's frequency estimate
        differs from the running estimate by more than freq_flush_hz, the
        accumulator is flushed before adding the new LLRs.

        Exponential forgetting: if n_copies >= max_copies, the accumulated
        LLRs are halved before the new copy is added (sliding-window
        behaviour that prevents stale copies from dominating).
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
        if _RX_DEBUG and self.n_copies > 0:
            prev_norm = float(np.linalg.norm(self.accumulated))
            body_norm = float(np.linalg.norm(body_llrs))
            if prev_norm > 1e-9 and body_norm > 1e-9:
                cos_sim = float(np.dot(self.accumulated, body_llrs) / (prev_norm * body_norm))
                print(f"       [DBG acc] cos_sim={cos_sim:+.3f} "
                      f"mean|llr|={float(np.mean(np.abs(body_llrs))):.3f}",
                      flush=True)

        # Frequency-drift flush: detect carrier shift > freq_flush_hz.
        incoming_freq = result.get("freq_offset_hz")
        if incoming_freq is not None:
            if (self._running_freq_hz is not None
                    and abs(incoming_freq - self._running_freq_hz) > self.freq_flush_hz):
                # New carrier offset — stale LLRs would cancel, not add.
                self.accumulated.fill(0.0)
                self.n_copies = 0
            # Update running estimate as exponential moving average.
            if self._running_freq_hz is None:
                self._running_freq_hz = float(incoming_freq)
            else:
                self._running_freq_hz = (
                    0.8 * self._running_freq_hz + 0.2 * float(incoming_freq)
                )

        # Exponential forgetting: halve before adding when saturated.
        if self.n_copies >= self.max_copies:
            self.accumulated *= 0.5

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
        body_llrs_f32 = sc.deinterleave_hail_body_llrs(
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


def make_ack_decode_fn(
    caller_static_priv,
    caller_eph_priv,
    dh1: bytes,
    expected_nonce_echo: bytes,
    samps_per_chip: int = 2,
    samp_hz: float = 2_000_000.0,
    signal_threshold: float = _SIGNAL_FLOOR_RATIO,
    top_k_soft: int = 5,
    max_copies: int = 64,
):
    """Return a stateful ACK decode function with LLR accumulation.

    The returned callable has the same signature as `decode_one_ack_in_block`
    (takes a block of samples, returns a status dict) but internally accumulates
    FEC LLRs across calls for multi-copy coherent combining.  When the
    accumulated LLRs yield a successful decrypt, the result dict contains
    ``status='decrypt_ok'`` and the accumulator is reset.  The accumulator
    is also reset on each new nonce (session).

    Use this instead of a bare `decode_one_ack_in_block` call when the
    responder retransmits the ACK continuously (e.g. for ACK_TX_WINDOW seconds).
    """
    accumulator = LlrAccumulator(
        n_bits=sc.ACK_FEC_TOTAL_BITS,
        max_copies=max_copies,
    )

    def _decode(block_data: "np.ndarray") -> dict:
        result = decode_one_ack_in_block(
            block_data,
            caller_static_priv=caller_static_priv,
            caller_eph_priv=caller_eph_priv,
            dh1=dh1,
            expected_nonce_echo=expected_nonce_echo,
            samps_per_chip=samps_per_chip,
            samp_hz=samp_hz,
            signal_threshold=signal_threshold,
            top_k_soft=top_k_soft,
        )
        if result["status"] == "decrypt_ok":
            accumulator.reset()
            return result

        # Try accumulating FEC LLRs from this block (present on decrypt_fail
        # and decrypt_ok paths from _try_fec_decrypt in ACK mode).
        fec_llrs = result.get("fec_llrs")
        if fec_llrs is not None and len(fec_llrs) >= sc.ACK_FEC_TOTAL_BITS:
            accumulator.try_add({
                "fec_llrs": fec_llrs,
                "freq_offset_hz": result.get("freq_offset_hz"),
            })
            if accumulator.n_copies >= 2:
                acc_llrs = accumulator.accumulated.astype(np.float32)
                for polarity in (1.0, -1.0):
                    attempt = sc.decode_ack_fec_from_llrs(
                        polarity * acc_llrs,
                        caller_static_priv, caller_eph_priv,
                        dh1, expected_nonce_echo,
                    )
                    if attempt is not None:
                        accumulator.reset()
                        return {
                            **result,
                            "status": "decrypt_ok",
                            "polarity": "ack-fec-acc",
                            "decoded_ack": attempt,
                            "body": attempt.body,
                        }
        return result

    return _decode


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

    peaks = np.array(peak_values, dtype=np.complex64)
    diffs = (peaks[1:] * np.conj(peaks[:-1])).real
    mags = np.abs(peaks[1:]) * np.abs(peaks[:-1])
    soft = np.where(mags > 1e-12, diffs / mags, 0.0).astype(np.float32)

    template = _ASM_DIFF_POLARITY.astype(np.float32)
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
    n_fec_bits: int | None = None,
    pilot_bits: np.ndarray | None = None,
) -> dict:
    """Run the DBPSK decoder at one ASM offset and return FEC LLRs.

    Handles both hail frames (default) and ACK frames via n_fec_bits /
    pilot_bits parameters.

    Returns a dict with fec_llrs, phase_rms_residual_rad, and
    asm_errs_in_coherent. All None if the offset is out of range or
    the decode fails.
    """
    if n_fec_bits is None:
        n_fec_bits = sc.HAIL_FEC_TOTAL_BITS
    if pilot_bits is None:
        pilot_bits = _PILOT_BITS
    out: dict = {
        "fec_llrs": None,
        "phase_rms_residual_rad": None,
        "asm_errs_in_coherent": None,
    }
    aligned_peaks = peak_values[peak_offset:]
    if len(aligned_peaks) < n_fec_bits:
        return out

    dbpsk = sf.dbpsk_decode_from_pilot(
        aligned_peaks, pilot_bits, n_fec_bits,
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


def _acquire_and_track(
    samples: np.ndarray,
    samps_per_chip: int,
    samp_hz: float,
    signal_threshold: float,
    fec_total_bits: int = sc.HAIL_FEC_TOTAL_BITS,
    freq_hint_rad: float | None = None,
    freq_offset_hz: float | None = None,
    skip_periodicity: bool = False,
    track_full_block: bool = False,
) -> dict:
    """Frequency estimation, correction, matched filter, periodicity test,
    and per-symbol tracking decode.

    freq_offset_hz: pre-seeded carrier offset (Hz).  When provided, uses this
    value directly instead of FFT-squared + post-MF estimation.

    skip_periodicity: bypass the 16-symbol periodicity gate.  The periodicity
    gate rejects continuous unique-symbol streams (RLNC payloads).

    track_full_block: track symbols over the entire block instead of limiting
    to 2x fec_total_bits.  Needed when extracting multiple symbols per block.

    Returns a dict with peak_values, positions, freq_hz, peak_mag,
    median_mag, rad_per_sample on success, or a status dict on failure.
    """
    min_symbols = 4 if skip_periodicity else 200
    if len(samples) < sf.CHIPS_PER_SYMBOL * samps_per_chip * min_symbols:
        return {"status": "short_block"}

    samples = (samples - samples.mean()).astype(np.complex64)

    _mf_score = 0.0
    if freq_offset_hz is not None:
        rad_per_sample = float(freq_offset_hz) * 2.0 * np.pi / samp_hz
    elif freq_hint_rad is not None:
        # Use the hint from a prior block's successful decode.
        # Validate it with post-MF scoring; if it still works, skip
        # the expensive FFT-squared + grid search entirely.
        rad_per_sample, _mf_score = sf.estimate_freq_post_mf(
            samples, freq_hint_rad,
            samps_per_chip=samps_per_chip,
            samp_hz=samp_hz,
        )
    else:
        # Two-stage frequency estimation:
        # Stage 1: FFT-squared picks top-K spectral peaks and validates each
        # via MF periodicity. Returns the best candidate.
        # Stage 2: Post-MF grid search validates the FFT-squared result and
        # falls back to a ±50 kHz grid if PLL spurs caused the estimator
        # to lock onto the wrong peak.
        fft_rad = sf._estimate_freq_fft_squared(samples)
        rad_per_sample, _mf_score = sf.estimate_freq_post_mf(
            samples, fft_rad,
            samps_per_chip=samps_per_chip,
            samp_hz=samp_hz,
        )
    freq_hz = rad_per_sample * samp_hz / (2 * np.pi)
    samples_corr = sf.apply_freq_correction(samples, rad_per_sample)

    corr_c = sf.matched_filter_complex_sample_rate(samples_corr, samps_per_chip)
    if len(corr_c) == 0:
        return {"status": "short_block"}
    mag = np.abs(corr_c).astype(np.float32)
    peak_mag = float(mag.max())
    median_mag = float(np.median(mag))

    # Clamp the prefilter threshold to 2.5× peak/median ratio.
    # The user-facing --signal-threshold (default 4.0) gates the main
    # signal-presence check, but the periodicity test downstream is the
    # real discriminator.  We clamp here because a threshold above ~2.5
    # rejects weak-but-real DSSS signals before they reach the periodicity
    # check.  Pure Gaussian noise gives peak/median ≈ 5-8 for million-
    # sample blocks; a real signal at marginal SNR can sit at 2-3×.
    # Clamping to 2.5 ensures the prefilter only rejects obvious noise
    # floors while letting marginal signals through to the periodicity gate.
    prefilter_threshold = min(signal_threshold, 2.5)
    if median_mag == 0.0 or peak_mag < prefilter_threshold * median_mag:
        return {
            "status": "no_signal",
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
        }

    samples_per_symbol = sf.CHIPS_PER_SYMBOL * samps_per_chip

    # Chip-phase estimation: average MF magnitude at each phase offset
    # across the whole block.  A WiFi/BT spike dominates argmax(mag) but
    # is non-periodic, so the column mean of the reshaped magnitude array
    # suppresses it and peaks at the true DSSS chip phase.
    n_full = (len(mag) // samples_per_symbol) * samples_per_symbol
    phase_avgs = mag[:n_full].reshape(-1, samples_per_symbol).mean(axis=0)
    chip_phase = int(np.argmax(phase_avgs))
    chip_phase_peak = float(phase_avgs[chip_phase])

    if not skip_periodicity:
        # Periodicity check using chip-phase aligned peaks (not spike-biased argmax).
        search_half = samples_per_symbol // 4
        test_peaks: list[float] = []
        for k in range(16):
            pos_k = chip_phase + k * samples_per_symbol
            if pos_k + search_half >= len(mag):
                break
            lo = max(0, pos_k - search_half)
            hi = min(len(mag), pos_k + search_half + 1)
            test_peaks.append(float(mag[lo:hi].max()))

        if len(test_peaks) < 4:
            return {"status": "short_block", "peak_mag": peak_mag, "median_mag": median_mag}

        periodic_ratio = float(np.median(test_peaks)) / peak_mag if peak_mag > 0 else 0.0
        # Periodicity gate: median of 16 symbol-spaced MF peaks / global peak.
        # A real DSSS signal produces periodic MF peaks at every symbol boundary
        # (every CHIPS_PER_SYMBOL x samps_per_chip samples), so the median of
        # symbol-spaced peaks should be a substantial fraction of the global peak.
        # 0.15 means the median periodic peak must be at least 15% of the global
        # peak magnitude — below this, the "peak" is likely a single non-periodic
        # spike (WiFi/BT interference) rather than a sustained DSSS signal.
        #
        # This gate is bypassed when _mf_score >= 3.0 (from estimate_freq_post_mf).
        # The MF score is median-of-periodic-peaks / median-noise, which is immune
        # to WiFi/BT spikes inflating peak_mag.  A score >= 3.0 means the periodic
        # structure is 3x above the noise floor — the signal is real even if a
        # single spike makes periodic_ratio look small.
        if (
            _mf_score < _PERIODICITY_BYPASS_MF_SCORE
            and periodic_ratio < _PERIODIC_RATIO_MIN
        ):
            return {
                "status": "no_signal",
                "peak_mag": peak_mag,
                "median_mag": median_mag,
                "rad_per_sample": rad_per_sample,
                "freq_offset_hz": freq_hz,
                "periodic_ratio": periodic_ratio,
                "note": "spurious spike, no periodic structure",
            }

    if track_full_block:
        # Track symbols over the entire block for multi-symbol extraction.
        # Leave one symbol of margin so the tracking loop does not overrun.
        n_block_symbols = max(1, (len(corr_c) - samples_per_symbol) // samples_per_symbol)
        target_bytes = n_block_symbols // 8
        if target_bytes < 1:
            return {"status": "short_block", "peak_mag": peak_mag, "median_mag": median_mag}
        # Frequency correction already applied to samples_corr; pass 0.0.
        track_rad = 0.0
        track_samples = samples_corr
    else:
        target_bytes = (2 * fec_total_bits + 7) // 8
        # Cap to what the block can actually track: the MF output has
        # len(samples) - samples_per_symbol + 1 elements, and each
        # tracked symbol steps by samples_per_symbol.
        max_trackable = max(1, (len(samples) - samples_per_symbol) // samples_per_symbol)
        max_bytes = max_trackable // 8
        if target_bytes > max_bytes:
            target_bytes = max_bytes
        track_rad = rad_per_sample
        track_samples = samples

    track_result = sf.decode_with_freq_tracking(
        track_samples,
        samps_per_chip=samps_per_chip,
        n_bytes=target_bytes,
        freq_offset_rad_per_sample=track_rad,
        precomputed_corr=corr_c,
        start_pos=chip_phase,
        peak_hint=chip_phase_peak,
    )
    if track_result is None:
        return {
            "status": "acquire_failed",
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
    top_k_soft: int,
    freq_hz: float,
    peak_mag: float,
    median_mag: float,
    rad_per_sample: float,
    # Hail-mode args (default):
    responder_static: ec.EllipticCurvePrivateKey | None = None,
    # ACK-mode args (pass all four to select ACK path):
    caller_static_priv: ec.EllipticCurvePrivateKey | None = None,
    caller_eph_priv: ec.EllipticCurvePrivateKey | None = None,
    dh1: bytes | None = None,
    expected_nonce_echo: bytes | None = None,
) -> dict:
    """FEC fast path: soft correlator search, DBPSK decode, Viterbi, decrypt.

    Handles both hail frames (pass responder_static) and ACK frames (pass
    caller_static_priv, caller_eph_priv, dh1, expected_nonce_echo).

    Returns a result dict with status decrypt_ok, decrypt_fail, or track_lost.
    """
    ack_mode = caller_static_priv is not None
    fec_total_bits = sc.ACK_FEC_TOTAL_BITS if ack_mode else sc.HAIL_FEC_TOTAL_BITS
    frame_len = sc.ACK_FRAME_LEN if ack_mode else sc.HAIL_FRAME_LEN
    pilot_bits = _ACK_PILOT_BITS if ack_mode else None
    polarity_pos = "ack-fec" if ack_mode else "fec"
    polarity_inv = "ack-fec-inv" if ack_mode else "fec-inv"

    if not peak_values or len(peak_values) < fec_total_bits:
        return {
            "status": "track_lost",
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
            "note": f"peak_values too short for {'ACK' if ack_mode else 'HAIL'}_FEC_TOTAL_BITS",
        }

    topk = find_sisl_frame_soft_topk(peak_values, frame_len, k=top_k_soft)
    if _RX_DEBUG:
        print(f"       [DBG rx] candidates={len(topk)} "
              f"peak_values={len(peak_values)} fec_bits={fec_total_bits} "
              f"Δf={freq_hz:+.0f}Hz", flush=True)

    best_attempt: dict | None = None
    best_offset = -1
    best_score = 0.0
    best_pts_ratio = 0.0
    decoded = None
    polarity_label = polarity_pos
    extra_fec_llrs: list[np.ndarray] = []

    for cand_offset, cand_score, cand_pts in topk:
        if cand_offset + fec_total_bits > len(peak_values):
            continue
        # Soft ASM score gate for hail/ACK frames: require |score| > 10.0.
        # The soft score is the 31-element differential ASM template correlated
        # against the normalized differential dot-products of consecutive MF
        # peaks.  Perfect alignment gives score = ±31 (all 31 differentials
        # match); pure noise gives score ~ N(0, sqrt(31)) ≈ std 5.6.
        # A threshold of 10.0 ≈ 1.8σ above noise mean — conservative enough
        # to admit marginal signals while rejecting most noise candidates.
        #
        # pts_ratio gate: |score| / median(|scores|), a CFAR-style
        # peak-to-sidelobe ratio.  Clean signal gives pts_ratio > 5; noise
        # gives ~2-3.  The 3.0 threshold rejects candidates that are not
        # meaningfully above the sidelobe floor — even if their absolute
        # score exceeds 10.0, a low pts_ratio means the candidate is not
        # distinctive relative to other positions in the block.
        if (
            abs(cand_score) <= _SOFT_SCORE_MIN_HAIL_ACK
            or cand_pts < _SOFT_PTS_RATIO_MIN
        ):
            continue

        llr_diag = _extract_llrs_at_position(
            peak_values, int(cand_offset),
            n_fec_bits=fec_total_bits if ack_mode else None,
            pilot_bits=pilot_bits,
        )
        fec_llrs_arr = llr_diag.get("fec_llrs")
        if fec_llrs_arr is None:
            continue
        if _RX_DEBUG:
            body = fec_llrs_arr[sc.ACK_FEC_HEADER_BITS if ack_mode else sc.HAIL_FEC_HEADER_BITS:]
            print(f"       [DBG rx] cand off={cand_offset} score={cand_score:+.1f} "
                  f"pts={cand_pts:.2f} mean|body|={float(np.mean(np.abs(body))):.3f} "
                  f"asm_errs={llr_diag.get('asm_errs_in_coherent')}",
                  flush=True)

        if ack_mode:
            assert caller_static_priv is not None and caller_eph_priv is not None
            assert dh1 is not None and expected_nonce_echo is not None
            attempt = sc.decode_ack_fec_from_llrs(
                fec_llrs_arr, caller_static_priv, caller_eph_priv,
                dh1, expected_nonce_echo)
            if attempt is None:
                attempt = sc.decode_ack_fec_from_llrs(
                    -fec_llrs_arr, caller_static_priv, caller_eph_priv,
                    dh1, expected_nonce_echo)
                if attempt is not None:
                    polarity_label = polarity_inv
            else:
                polarity_label = polarity_pos
        else:
            assert responder_static is not None
            attempt = sc.decode_hail_fec_from_llrs(fec_llrs_arr, responder_static)
            if attempt is None:
                attempt = sc.decode_hail_fec_from_llrs(-fec_llrs_arr, responder_static)
                if attempt is not None:
                    polarity_label = polarity_inv
            else:
                polarity_label = polarity_pos

        if attempt is not None:
            decoded = attempt
            best_offset = int(cand_offset)
            best_score = float(cand_score)
            best_pts_ratio = float(cand_pts)
            best_attempt = {"llr_diag": llr_diag, "fec_llrs": fec_llrs_arr}
            break

        if not ack_mode:
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

    # ── Extract additional frame copies at frame-length offsets ──────
    # The TX loops the same FEC-encoded hail frame continuously.  A
    # 5.36s block at 1 Mcps holds ~2.5 copies (each frame =
    # HAIL_FEC_TOTAL_BITS ≈ 2.18s).  The top-K search above finds
    # candidates near the BEST ASM position but misses copies one or
    # two frame-lengths away.  Search at ±N×frame_bits offsets from the
    # best candidate and extract LLRs for the accumulator.
    if not ack_mode and best_offset >= 0:
        frame_bits = sc.HAIL_FEC_TOTAL_BITS
        for mult in (-2, -1, 1, 2):
            copy_offset = best_offset + mult * frame_bits
            if copy_offset < 0:
                continue
            if copy_offset + fec_total_bits > len(peak_values):
                continue
            copy_llr = _extract_llrs_at_position(
                peak_values, copy_offset,
                n_fec_bits=fec_total_bits,
                pilot_bits=pilot_bits,
            )
            copy_fec = copy_llr.get("fec_llrs")
            if copy_fec is not None:
                extra_fec_llrs.append(copy_fec)

    llr_diag = best_attempt["llr_diag"]
    fec_llrs_arr = best_attempt["fec_llrs"]
    base: dict = {
        "start_sample": positions[0] if positions else 0,
        "asm_at_byte": f"soft-bit{best_offset}",
        "peak_mag": peak_mag,
        "median_mag": median_mag,
        "rad_per_sample": rad_per_sample,
        "freq_offset_hz": freq_hz,
        "soft_score": best_score,
        "pts_ratio": best_pts_ratio,
    }
    if ack_mode:
        # Expose FEC LLRs for ACK LLR accumulation (multi-copy combining).
        base["fec_llrs"] = fec_llrs_arr
    else:
        base["fec_llrs"] = fec_llrs_arr
        base["extra_fec_llrs"] = extra_fec_llrs
        base["phase_rms_residual_rad"] = llr_diag["phase_rms_residual_rad"]
        base["asm_errs_in_coherent"] = llr_diag["asm_errs_in_coherent"]

    if decoded is None:
        return {"status": "decrypt_fail", "polarity": polarity_label, **base}
    if ack_mode:
        return {
            "status": "decrypt_ok",
            "polarity": polarity_label,
            "decoded_ack": decoded,
            "body": decoded.body,
            **base,
        }
    decoded_hail: sc.DecodedHail = decoded  # type: ignore[assignment]
    return {
        "status": "decrypt_ok",
        "polarity": polarity_label,
        "body": decoded_hail.body,
        "caller_eph_pub_canonical": decoded_hail.caller_eph_pub_canonical,
        "decoded_hail": decoded_hail,
        **base,
    }


def _decode_one_hail_in_block(
    samples: np.ndarray,
    responder_static: ec.EllipticCurvePrivateKey,
    samps_per_chip: int = 2,
    samp_hz: float = 8_000_000.0,
    signal_threshold: float = _SIGNAL_FLOOR_RATIO,
    top_k_soft: int = 5,
    freq_hint_rad: float | None = None,
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
    # Track enough symbols for one full hail frame plus margin for the
    # frame-copy extraction loop in _try_fec_decrypt.  The target_bytes
    # formula in _acquire_and_track doubles fec_total_bits, so requesting
    # 1× gives ~2 frames worth of tracked symbols.  With 3.0s blocks at
    # 2 Msps this fits comfortably; the old 3× multiplier required 5.36s+
    # blocks that exceeded real-time decode budget.
    acq = _acquire_and_track(
        samples, samps_per_chip, samp_hz, signal_threshold,
        fec_total_bits=sc.HAIL_FEC_TOTAL_BITS,
        freq_hint_rad=freq_hint_rad,
    )
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

    return _try_fec_decrypt(
        peak_values=acq["peak_values"],
        positions=acq["positions"],
        top_k_soft=top_k_soft,
        freq_hz=acq["freq_hz"],
        peak_mag=acq["peak_mag"],
        median_mag=acq["median_mag"],
        rad_per_sample=acq["rad_per_sample"],
        caller_static_priv=caller_static_priv,
        caller_eph_priv=caller_eph_priv,
        dh1=dh1,
        expected_nonce_echo=expected_nonce_echo,
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
              f"asm@{result.get('asm_at_byte', '?')}  "
              f"peak={pk:.3g}  {snr_str}  "
              f"\u0394f={foff:+.0f}Hz  "
              f"pol={pol}  "
              f"{detail}{_RESET}", flush=True)
    elif s == "decrypt_fail":
        print(f"[{block_num:4d}] FRAME FOUND  "
              f"asm@{result.get('asm_at_byte', '?')}  "
              f"{snr_str}  "
              f"\u0394f={foff:+.0f}Hz  "
              f"pol={result.get('polarity', '?')}  "
              f"\u2014 DECRYPT FAILED", flush=True)
    elif s == "track_lost":
        p = result.get("peak_mag", 0)
        m = result.get("median_mag", 0)
        r = p / m if m > 0 else float("inf")
        print(f"[{block_num:4d}] TRACK LOST: "
              f"peak={p:.3g}, median={m:.3g}, ratio={r:.1f}, "
              f"\u0394f={foff:+.0f}Hz", flush=True)
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
              f"\u0394f={foff:+.0f}Hz{extra}", flush=True)
    elif s == "short_block":
        print(f"[{block_num:4d}] short block (processing gap)", flush=True)


_PAYLOAD_PILOT_BYTES = sc.ASM + bytes([sc.SISL_VERSION, sc.MSG_PAYLOAD])
_PAYLOAD_PILOT_BITS = np.unpackbits(
    np.frombuffer(_PAYLOAD_PILOT_BYTES, dtype=np.uint8)
).astype(np.uint8)


def _decode_payload_candidates(
    peak_values: list,
    n_payload_bytes: int,
    n_fec_bits: int,
    base: dict,
    max_candidates: int = 5,
    min_separation: int = 4,
    return_first: bool = False,
) -> list[dict]:
    """DBPSK decode + FEC decode for payload ASM candidates.

    Shared candidate-processing loop for both decode_one_payload_in_block
    and decode_all_payload_in_block.

    peak_values: symbol-rate MF peak complex values from tracking.
    return_first: if True, return after the first successful decode (for
    decode_one); if False, collect all successful decodes (for decode_all).

    Returns a list of result dicts with status decrypt_ok, or a single-element
    list with status decrypt_fail if no candidate succeeded.
    """
    frame_len_bytes = n_payload_bytes + sc.PAYLOAD_HEADER_LEN
    topk = find_sisl_frame_soft_topk(
        peak_values, frame_len_bytes,
        k=max_candidates,
        min_separation=min_separation,
    )

    results = []
    for cand_offset, cand_score, _cand_pts in topk:
        # Soft ASM score gate for payload frames: require |score| > 5.0.
        # Lower than the hail/ACK gate (10.0) because payload frames are
        # sent once each (unique RLNC symbols), so there is no multi-copy
        # LLR accumulation to recover from a missed frame.  The AEAD
        # (Authenticated Encryption with Associated Data) tag on each
        # payload symbol provides a hard cryptographic check, so false
        # positives from lowering the gate are rejected by Poly1305 —
        # the cost is only wasted FEC decode cycles, not false accepts.
        if abs(cand_score) <= _SOFT_SCORE_MIN_PAYLOAD:
            continue
        if cand_offset + n_fec_bits > len(peak_values):
            continue

        aligned = peak_values[int(cand_offset):]
        if len(aligned) < n_fec_bits:
            continue

        dbpsk = sf.dbpsk_decode_from_pilot(aligned, _PAYLOAD_PILOT_BITS, n_fec_bits)
        if dbpsk is None:
            continue

        _, fec_soft, _, _, _ = dbpsk
        for polarity in (1.0, -1.0):
            raw = sc.decode_payload_symbol_fec_from_llrs(
                polarity * fec_soft, n_payload_bytes,
            )
            if raw is not None and len(raw) == n_payload_bytes:
                results.append({
                    "status": "decrypt_ok",
                    "payload_frame_bytes": raw,
                    "asm_at_byte": f"soft-bit{int(cand_offset)}",
                    "soft_score": float(cand_score),
                    **base,
                })
                if return_first:
                    return results
                break

    if not results:
        return [{"status": "decrypt_fail", **base}]
    return results


def decode_one_payload_in_block(
    samples: np.ndarray,
    n_payload_bytes: int,
    samps_per_chip: int = 2,
    samp_hz: float = 2_000_000.0,
    signal_threshold: float = _SIGNAL_FLOOR_RATIO,
    top_k_soft: int = 5,
) -> dict:
    """Process one block, try to decode one RLNC payload symbol.

    n_payload_bytes — expected encode_payload_symbol() output length.
    Returns dict with status and payload_frame_bytes on decrypt_ok.
    Caller must call sisl_payload.decode_payload_symbol() to AEAD-verify.
    """
    n_fec_bits = sc.payload_fec_total_bits(n_payload_bytes)
    acq = _acquire_and_track(
        samples, samps_per_chip, samp_hz, signal_threshold,
        fec_total_bits=n_fec_bits,
    )
    if acq["status"] != "acquired":
        return acq

    peak_values = acq["peak_values"]
    positions = acq["positions"]
    base = {
        "peak_mag": acq["peak_mag"],
        "median_mag": acq["median_mag"],
        "rad_per_sample": acq["rad_per_sample"],
        "freq_offset_hz": acq["freq_hz"],
        "start_sample": positions[0] if positions else 0,
    }

    if len(peak_values) < n_fec_bits:
        return {"status": "track_lost", **base}

    results = _decode_payload_candidates(
        peak_values, n_payload_bytes, n_fec_bits, base,
        max_candidates=top_k_soft,
        return_first=True,
    )
    return results[0]


def decode_all_payload_in_block(
    samples: np.ndarray,
    n_payload_bytes: int,
    samps_per_chip: int = 2,
    samp_hz: float = 2_000_000.0,
    signal_threshold: float = _SIGNAL_FLOOR_RATIO,
    max_symbols_per_block: int = 8,
    freq_offset_hz: float | None = None,
) -> list[dict]:
    """Process one block and decode every RLNC payload symbol found in it.

    Unlike decode_one_payload_in_block, this function bypasses the
    _acquire_and_track periodicity gate (which was designed for repeated hail
    frames and rejects continuous unique-symbol streams).  Instead it uses
    _acquire_and_track with skip_periodicity=True and track_full_block=True
    to track symbols over the entire block.

    Each symbol boundary is identified by the fixed 48-bit header
    (ASM + SISL_VERSION + MSG_PAYLOAD) that encode_payload_symbol_fec
    prepends to every coded symbol — no additional sync markers required.

    freq_offset_hz: pre-seeded carrier offset (Hz) from the hail/ACK decode.
    When provided, frequency correction uses this value instead of estimating
    it from the block.  Recommended when disable_auto_ppm=True so the estimate
    matches the actual signal frequency.

    Returns a list of result dicts (one per found symbol).  Empty list if
    no signal or no ASM candidates pass the score gate.  Callers must call
    sisl_payload.decode_payload_symbol() to AEAD-verify each result.
    """
    n_fec_bits = sc.payload_fec_total_bits(n_payload_bytes)

    acq = _acquire_and_track(
        samples, samps_per_chip, samp_hz, signal_threshold,
        fec_total_bits=n_fec_bits,
        freq_offset_hz=freq_offset_hz,
        skip_periodicity=True,
        track_full_block=True,
    )
    if acq["status"] != "acquired":
        return [acq]

    peak_values = acq["peak_values"]
    base = {
        "peak_mag": acq["peak_mag"],
        "median_mag": acq["median_mag"],
        "rad_per_sample": acq["rad_per_sample"],
        "freq_offset_hz": acq["freq_hz"],
    }

    return _decode_payload_candidates(
        peak_values, n_payload_bytes, n_fec_bits, base,
        max_candidates=max_symbols_per_block,
        min_separation=n_fec_bits // 2,
        return_first=False,
    )
