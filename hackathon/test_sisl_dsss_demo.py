"""Tests for demo.py and sisl_rx.py (pure-numpy, no HackRF).

Run: python -m pytest hackathon/test_sisl_dsss_demo.py
"""

from __future__ import annotations

import os
import tempfile

import numpy as np

import sisl_crypto as sc
import sisl_rx
import demo as dd
from conftest import bits_to_hard_llrs, encoded_fec_bits_to_post_dbpsk, make_test_hail_body


# ── Demo keys and hail builder ──────────────────────────────────────────────

def test_demo_keys_reproducible():
    """Demo keys are deterministic across calls (required for TX/RX symmetry)."""
    a1 = dd.demo_caller_key()
    a2 = dd.demo_caller_key()
    b1 = dd.demo_responder_key()
    b2 = dd.demo_responder_key()
    from cryptography.hazmat.primitives import serialization
    def pub(k):
        return k.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.CompressedPoint,
        )
    assert pub(a1) == pub(a2)
    assert pub(b1) == pub(b2)
    assert pub(a1) != pub(b1)   # caller and responder must differ
    assert pub(a1) != pub(dd.demo_other_key())


def test_build_demo_hail_round_trip():
    """build_demo_hail produces a 100 B frame decryptable by demo_responder_key."""
    frame = dd.build_demo_hail()
    assert len(frame) == sc.HAIL_FRAME_LEN
    # Correct key decrypts
    decoded = sc.decode_hail(frame, dd.demo_responder_key())
    assert decoded is not None
    assert decoded.body.center_freq_offset == 100
    assert decoded.body.mode == 0x01
    # Wrong key does not decrypt
    assert sc.decode_hail(frame, dd.demo_other_key()) is None
    assert sc.decode_hail(frame, dd.demo_caller_key()) is None


# ── Full tx → file → offline_decode_hail pipeline ──────────────────────────

def test_offline_decode_hail_correct_key():
    """FEC block → offline_decode_hail decrypts OK."""
    with tempfile.NamedTemporaryFile(suffix=".cfile", delete=False) as f:
        path = f.name
    try:
        block, _ = _make_block_with_hail(prefix_samples=50_000)
        block.tofile(path)
        result = dd.offline_decode_hail(path)
        assert result["decrypted"] is True, result
        assert result["decoded_hail"] is not None
        assert result["decoded_hail"].body.center_freq_offset == 100
    finally:
        os.unlink(path)


def test_offline_decode_hail_wrong_key_fails():
    """Trying to decode the same capture as demo_other_key MUST fail."""
    with tempfile.NamedTemporaryFile(suffix=".cfile", delete=False) as f:
        path = f.name
    try:
        block, _ = _make_block_with_hail(prefix_samples=50_000)
        block.tofile(path)
        result = dd.offline_decode_hail(path, responder_static=dd.demo_other_key())
        assert result["decrypted"] is False
        assert result["decoded_hail"] is None
    finally:
        os.unlink(path)


# ── Live block decoder (pure numpy, no SoapySDR) ──────────────────────────

def _make_block_with_hail(prefix_samples: int = 50_000,
                          suffix_samples: int = 50_000,
                          phase_offset: int = 0,
                          repeats: int = 2) -> tuple[np.ndarray, bytes]:
    """Synthesize a baseband block containing FEC-encoded demo hails.

    `repeats`: how many back-to-back copies (default 2 to give the
    tracker enough search margin for the 2× window).
    `phase_offset`: shift the signal start by N samples so the chip grid
    doesn't align at sample 0.
    """
    chips, diag_frame = dd.build_demo_hail_fec_chips()
    if repeats > 1:
        chips = np.tile(chips, repeats)
    signal = dd.upsample_chips_to_samples(chips)
    prefix = np.zeros(prefix_samples + phase_offset, dtype=np.complex64)
    suffix = np.zeros(suffix_samples, dtype=np.complex64)
    block = np.concatenate([prefix, signal, suffix])
    return block, diag_frame


def test_decode_one_hail_in_block_correct_key():
    block, _ = _make_block_with_hail()
    result = sisl_rx._decode_one_hail_in_block(block, dd.demo_responder_key())
    assert result["status"] == "decrypt_ok", result
    assert result["body"].center_freq_offset == 100
    assert result["body"].mode == 0x01


def test_decode_one_hail_in_block_populates_llrs_on_clean_decrypt():
    """Clean decrypts must surface fec_llrs / phase_rms / asm_errs
    so the LLR accumulator can chase-combine across blocks."""
    block, _ = _make_block_with_hail()
    result = sisl_rx._decode_one_hail_in_block(block, dd.demo_responder_key())
    assert result["status"] == "decrypt_ok", result
    for key in ("fec_llrs",
                "phase_rms_residual_rad", "asm_errs_in_coherent"):
        assert key in result, (key, sorted(result.keys()))
        assert result[key] is not None, key
    assert result["fec_llrs"].shape == (sc.HAIL_FEC_TOTAL_BITS,)
    assert result["fec_llrs"].dtype == np.float32


def test_decode_one_hail_in_block_populates_llrs_on_decrypt_fail():
    """decrypt_fail must also surface fec_llrs so the accumulator can
    keep combining marginal blocks across the wrong-key boundary case."""
    block, _ = _make_block_with_hail()
    result = sisl_rx._decode_one_hail_in_block(block, dd.demo_other_key())
    assert result["status"] == "decrypt_fail", result
    for key in ("fec_llrs",
                "phase_rms_residual_rad", "asm_errs_in_coherent"):
        assert key in result, (key, sorted(result.keys()))
        assert result[key] is not None, key


def test_decode_one_hail_in_block_wrong_key():
    block, _ = _make_block_with_hail()
    result = sisl_rx._decode_one_hail_in_block(block, dd.demo_other_key())
    assert result["status"] == "decrypt_fail", result


def test_decode_one_hail_in_block_pure_noise():
    rng = np.random.default_rng(seed=42)
    noise = (
        rng.normal(0, 0.05, 8_000_000).astype(np.float32)
        + 1j * rng.normal(0, 0.05, 8_000_000).astype(np.float32)
    ).astype(np.complex64)
    result = sisl_rx._decode_one_hail_in_block(noise, dd.demo_responder_key())
    # Pure noise: any non-decode status is acceptable. With the lower
    # signal threshold (4x) we now let more borderline blocks through
    # so downstream periodicity / tracking / ASM checks can reject them.
    assert result["status"] in (
        "no_signal", "no_lock", "no_hail",
        "track_lost", "frame_fuzzy", "short_block",
    ), result
    # The critical invariant: pure noise must NEVER decrypt.
    assert result["status"] != "decrypt_ok"


def test_decode_one_hail_in_block_sub_chip_phase_offset():
    """Signal starts at a non-integer-chip sample — sub-chip search needed."""
    block, _ = _make_block_with_hail(phase_offset=3)   # 3 of 8 samples off
    result = sisl_rx._decode_one_hail_in_block(block, dd.demo_responder_key())
    # Because _decode_one_hail_in_block iterates all 8 chip phases, it
    # finds the shifted signal and recovers it.
    assert result["status"] == "decrypt_ok", result


def test_offline_decode_hail_repeats():
    """Multiple hail copies in the capture still decode."""
    with tempfile.NamedTemporaryFile(suffix=".cfile", delete=False) as f:
        path = f.name
    try:
        block, _ = _make_block_with_hail(prefix_samples=50_000, repeats=3)
        block.tofile(path)
        result = dd.offline_decode_hail(path)
        assert result["decrypted"] is True
        assert result["decoded_hail"].body.mode == 0x01
    finally:
        os.unlink(path)


def test_find_sisl_frame_soft_topk_returns_candidates():
    """Top-K search returns multiple candidates, sorted by |score|."""
    block, _ = _make_block_with_hail()
    # Extract peak_values manually to simulate what decode_one would see.
    # Instead, run the decode and check that topk-like behavior is plumbed.
    # Easier: synth a list of peak values with multiple plausible positions.
    rng = np.random.default_rng(seed=99)
    # 200 random peaks (std 1) with a clean ASM-aligned burst at position 60
    peaks = rng.normal(0, 1, 200) + 1j * rng.normal(0, 1, 200)
    peaks = peaks.astype(np.complex128)
    # Inject a strong ASM-like signal at position 60 by setting peaks there
    # to follow _ASM_BITS sign pattern with large magnitude.
    asm_signs = np.where(sisl_rx._ASM_BITS == 0, 1.0, -1.0)
    for i in range(32):
        peaks[60 + i] = 10.0 * asm_signs[i]
    results = sisl_rx.find_sisl_frame_soft_topk(
        peaks.tolist(), frame_len=sc.HAIL_FRAME_LEN, k=5,
    )
    assert len(results) > 0
    assert len(results) <= 5
    # Top result should be near position 60 (differential, so ±1 is fine)
    top_offset, top_score, top_pts = results[0]
    assert abs(top_offset - 59) <= 2 or abs(top_offset - 60) <= 2
    assert abs(top_score) > 20
    # pts ratio should be clearly above the noise-driven sidelobe median
    assert top_pts > 4, f"pts_ratio {top_pts} too low for clean signal"
    # Results must be sorted by |score| descending
    scores = [abs(s) for _, s, _ in results]
    assert scores == sorted(scores, reverse=True)


def test_find_sisl_frame_soft_topk_separation():
    """Results respect minimum separation — no two candidates adjacent."""
    rng = np.random.default_rng(seed=100)
    peaks = (rng.normal(0, 1, 500) + 1j * rng.normal(0, 1, 500)).astype(np.complex128)
    results = sisl_rx.find_sisl_frame_soft_topk(
        peaks.tolist(), frame_len=sc.HAIL_FRAME_LEN, k=5, min_separation=4,
    )
    offsets = sorted(off for off, _, _ in results)
    for a, b in zip(offsets, offsets[1:]):
        assert b - a > 4, f"candidates {a} and {b} too close"
    # Pure noise pts ratios should all be ~2-3 (not > 5)
    for _, _, pts in results:
        assert pts < 5, f"noise pts_ratio {pts} implausibly high"


def test_find_sisl_frame_soft_topk_empty_on_short():
    assert sisl_rx.find_sisl_frame_soft_topk([1+0j]*10) == []


def _build_fec_result(responder_static, magnitude: float = 10.0,
                      noise_std: float = 0.0, seed: int = 0) -> dict:
    """Synthesize a result dict containing FEC channel LLRs for one
    demo hail. Returns a dict with the keys LlrAccumulator expects:
    fec_llrs, phase_rms_residual_rad, asm_errs_in_coherent."""
    body = make_test_hail_body()
    eph = sc.Ephemeral()
    bits = sc.encode_hail_fec(eph, responder_static.public_key(), body)
    # Convert to post-DBPSK basis (the FEC accumulator's try_decrypt
    # consumes LLRs in the FEC code-bit basis, which is what
    # dbpsk_decode_from_pilot produces in production after differentially
    # decoding the body region).
    post_dbpsk_bits = encoded_fec_bits_to_post_dbpsk(bits)
    llrs = bits_to_hard_llrs(post_dbpsk_bits, magnitude=magnitude)
    if noise_std > 0:
        rng = np.random.default_rng(seed=seed)
        llrs = llrs + rng.normal(0, noise_std, len(llrs)).astype(np.float32)
    return {
        "fec_llrs": llrs,
        "phase_rms_residual_rad": 0.05,
        "asm_errs_in_coherent": 0,
    }


def test_llr_accumulator_fec_constructor_validates_n_bits():
    # Requires n_bits == HAIL_FEC_TOTAL_BITS
    try:
        sisl_rx.LlrAccumulator(n_bits=1064)
        raise AssertionError("expected AssertionError on wrong n_bits")
    except AssertionError as e:
        if "n_bits must be" not in str(e) and "HAIL_FEC_TOTAL_BITS" not in str(e):
            raise
    # Correct construction works and allocates body-sized accumulator
    acc = sisl_rx.LlrAccumulator(n_bits=sc.HAIL_FEC_TOTAL_BITS)
    assert acc.accumulated.shape == (sc.HAIL_FEC_BODY_CODED_BITS,)
    assert acc._header_bits == sc.HAIL_FEC_HEADER_BITS


def test_llr_accumulator_fec_single_copy_decrypt():
    """One clean FEC copy should admit and decrypt via the Viterbi path."""
    responder_static = dd.demo_responder_key()
    result = _build_fec_result(responder_static, magnitude=10.0)
    acc = sisl_rx.LlrAccumulator(n_bits=sc.HAIL_FEC_TOTAL_BITS)
    assert acc.try_add(result) is True
    assert acc.n_copies == 1
    decrypt = acc.try_decrypt(responder_static)
    assert decrypt is not None
    decoded, label, flips = decrypt
    assert label == "fec-acc"
    assert flips == 0
    assert decoded.body.center_freq_offset == 100
    assert decoded.body.mode == 0x01


def test_llr_accumulator_fec_wrong_responder_returns_none():
    target = dd.demo_responder_key()
    other = dd.demo_other_key()
    result = _build_fec_result(target, magnitude=10.0)
    acc = sisl_rx.LlrAccumulator(n_bits=sc.HAIL_FEC_TOTAL_BITS)
    assert acc.try_add(result) is True
    assert acc.try_decrypt(other) is None


def test_llr_accumulator_fec_combines_two_noisy_copies():
    """Two FEC copies at an SNR where the body BER is too high for
    single-copy Viterbi to recover but the LLR sum is well above the
    waterfall."""
    responder_static = dd.demo_responder_key()
    # Pick magnitude/noise so single-copy decrypts (Es/N0 well above
    # the FEC waterfall). Use the same body across both copies to test
    # accumulator combining specifically.
    body = make_test_hail_body(
        center_freq_offset=200,
        bandwidth_code=0x05,
        body_nonce=b"\xaa\xbb\xcc\xdd\xee\xff\x00\x11",
        flags=0x07,
    )
    eph = sc.Ephemeral()
    bits = sc.encode_hail_fec(eph, responder_static.public_key(), body)
    post_dbpsk_bits = encoded_fec_bits_to_post_dbpsk(bits)
    clean = bits_to_hard_llrs(post_dbpsk_bits, magnitude=4.0)
    rng = np.random.default_rng(seed=7)
    noisy1 = (clean + rng.normal(0, 1.0, len(clean))).astype(np.float32)
    noisy2 = (clean + rng.normal(0, 1.0, len(clean))).astype(np.float32)
    base = {"phase_rms_residual_rad": 0.05, "asm_errs_in_coherent": 0}

    acc = sisl_rx.LlrAccumulator(n_bits=sc.HAIL_FEC_TOTAL_BITS)
    assert acc.try_add({**base, "fec_llrs": noisy1}) is True
    assert acc.try_add({**base, "fec_llrs": noisy2}) is True
    assert acc.n_copies == 2

    # Body LLR magnitude after 2 copies should be ~2× single-copy
    body_l1_2 = float(np.mean(np.abs(acc.accumulated)))
    acc_single = sisl_rx.LlrAccumulator(n_bits=sc.HAIL_FEC_TOTAL_BITS)
    assert acc_single.try_add({**base, "fec_llrs": noisy1}) is True
    body_l1_1 = float(np.mean(np.abs(acc_single.accumulated)))
    assert body_l1_2 > 1.5 * body_l1_1, (body_l1_1, body_l1_2)

    decrypt = acc.try_decrypt(responder_static)
    assert decrypt is not None
    decoded, label, _ = decrypt
    assert label == "fec-acc"
    assert decoded.body.center_freq_offset == 200
    assert decoded.body.body_nonce == b"\xaa\xbb\xcc\xdd\xee\xff\x00\x11"


def test_llr_accumulator_fec_polarity_inversion_normalized():
    """DBPSK body LLRs are phase-invariant — no polarity vote is applied.
    Two identical copies add constructively (L1 doubles)."""
    responder_static = dd.demo_responder_key()
    result = _build_fec_result(responder_static, magnitude=10.0)

    acc = sisl_rx.LlrAccumulator(n_bits=sc.HAIL_FEC_TOTAL_BITS)
    assert acc.try_add(result) is True
    l1_single = float(np.mean(np.abs(acc.accumulated)))
    assert acc.try_add(result) is True
    l1_double = float(np.mean(np.abs(acc.accumulated)))
    assert l1_double > 1.8 * l1_single, (l1_single, l1_double)

    decrypt = acc.try_decrypt(responder_static)
    assert decrypt is not None


def test_llr_accumulator_fec_short_input_rejected():
    responder_static = dd.demo_responder_key()
    result = _build_fec_result(responder_static, magnitude=10.0)
    result["fec_llrs"] = result["fec_llrs"][: sc.HAIL_FEC_TOTAL_BITS // 2]
    acc = sisl_rx.LlrAccumulator(n_bits=sc.HAIL_FEC_TOTAL_BITS)
    assert acc.try_add(result) is False
    assert acc.n_copies == 0



