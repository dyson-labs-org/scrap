"""Round-trip tests for sisl_dsss_demo.py (pure-numpy, no HackRF).

Validates that tx_to_file → offline_despread recovers the original bytes
at several prefix sizes, exercising the find_frame_start acquisition path.

Run: python hackathon/test_sisl_dsss_demo.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sisl_crypto as sc
import sisl_dsss_demo as dd
import sisl_framer as sf


# ── Constants used by the tests ─────────────────────────────────────────────

_SHORT_MSG = b"SISL HELLO"


# ── tx_to_file / offline_despread round-trips ───────────────────────────────

def test_tx_to_file_no_prefix_roundtrip():
    with tempfile.NamedTemporaryFile(suffix=".cfile", delete=False) as f:
        path = f.name
    try:
        n_samples = dd.tx_to_file(_SHORT_MSG, path, prefix_ms=0.0)
        expected = len(_SHORT_MSG) * 8 * sf.CHIPS_PER_SYMBOL * dd.SAMPS_PER_CHIP
        assert n_samples == expected, (n_samples, expected)

        recovered, offset = dd.offline_despread(path)
        assert recovered.startswith(_SHORT_MSG)
        assert len(recovered) == len(_SHORT_MSG)
        assert offset == 0
    finally:
        os.unlink(path)


def test_tx_to_file_1ms_prefix_acquires():
    """1 ms prefix = 8000 samples = 1000 chips of silence before signal."""
    with tempfile.NamedTemporaryFile(suffix=".cfile", delete=False) as f:
        path = f.name
    try:
        dd.tx_to_file(_SHORT_MSG, path, prefix_ms=1.0)
        recovered, offset = dd.offline_despread(path)
        assert recovered.startswith(_SHORT_MSG)
        assert offset is not None
        # 1 ms * 1 Mcps = 1000 chips prefix
        assert abs(offset - 1000) <= 1, offset
    finally:
        os.unlink(path)


def test_tx_to_file_10ms_prefix_acquires():
    """10 ms prefix = 10k chips before signal — larger search window test."""
    with tempfile.NamedTemporaryFile(suffix=".cfile", delete=False) as f:
        path = f.name
    try:
        dd.tx_to_file(_SHORT_MSG, path, prefix_ms=10.0)
        recovered, offset = dd.offline_despread(path)
        assert recovered.startswith(_SHORT_MSG)
        assert offset is not None
        assert abs(offset - 10_000) <= 1, offset
    finally:
        os.unlink(path)


def test_tx_to_file_bounded_search_finds_lock():
    """max_search_chips=2000 should still find a 1 ms (1000-chip) prefix."""
    with tempfile.NamedTemporaryFile(suffix=".cfile", delete=False) as f:
        path = f.name
    try:
        dd.tx_to_file(_SHORT_MSG, path, prefix_ms=1.0)
        recovered, offset = dd.offline_despread(path, max_search_chips=2000)
        assert recovered.startswith(_SHORT_MSG)
        assert offset is not None
    finally:
        os.unlink(path)


def test_tx_to_file_hail_frame_end_to_end():
    """TX a real SISL v3 hail frame via tx_to_file, offline decode, trial decrypt."""
    responder_static = sc.generate_keypair()
    caller_eph = sc.Ephemeral()
    body = sc.HailBody(
        center_freq_offset=100,
        bandwidth_code=0x03,
        mode=0x01,
        chip_rate_code=0x32,
        body_nonce=b"\xDE\xAD\xBE\xEF\xCA\xFE\xBA\xBE",
        flags=0x03,
    )
    frame = sc.encode_hail(caller_eph, responder_static.public_key(), body)
    assert len(frame) == sc.HAIL_FRAME_LEN

    with tempfile.NamedTemporaryFile(suffix=".cfile", delete=False) as f:
        path = f.name
    try:
        dd.tx_to_file(frame, path, prefix_ms=2.0)
        recovered, offset = dd.offline_despread(path)
        # Decoder returns all available bytes from the located offset;
        # for a pristine TX file, the decoded bytes are exactly the frame.
        assert recovered.startswith(frame)
        assert offset is not None

        # Auto-detect the SISL frame in the decoded bytes
        info = dd.identify_sisl_frame(recovered)
        assert info is not None
        assert info["frame_type"] == "hail"
        assert info["version"] == 0x03
        assert info["msg_type"] == 0x01
        assert info["frame_bytes"] == frame

        # Trial-decrypt the detected frame — validates the full stack
        decoded = sc.decode_hail(info["frame_bytes"], responder_static)
        assert decoded is not None
        assert decoded.body.body_nonce == body.body_nonce
    finally:
        os.unlink(path)


def test_identify_sisl_frame_finds_embedded_frame():
    """identify_sisl_frame scans for ASM within a larger byte stream."""
    responder_static = sc.generate_keypair()
    caller_eph = sc.Ephemeral()
    body = sc.HailBody(
        center_freq_offset=50, bandwidth_code=0x03, mode=0x01,
        chip_rate_code=0x32,
        body_nonce=b"\x11\x22\x33\x44\x55\x66\x77\x88",
        flags=0x03,
    )
    frame = sc.encode_hail(caller_eph, responder_static.public_key(), body)

    prefix = b"\x00" * 17 + b"garbage"
    suffix = b"more garbage"
    blob = prefix + frame + suffix

    info = dd.identify_sisl_frame(blob)
    assert info is not None
    assert info["asm_offset"] == len(prefix)
    assert info["frame_type"] == "hail"
    assert info["frame_bytes"] == frame


def test_identify_sisl_frame_none_on_noise():
    info = dd.identify_sisl_frame(b"\xAA" * 200)
    assert info is None


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
    """tx_to_file(build_demo_hail()) → offline_decode_hail decrypts OK."""
    with tempfile.NamedTemporaryFile(suffix=".cfile", delete=False) as f:
        path = f.name
    try:
        frame = dd.build_demo_hail()
        dd.tx_to_file(frame, path, prefix_ms=3.0)

        result = dd.offline_decode_hail(path)
        assert result["offset"] is not None
        assert result["frame"] is not None
        assert result["frame"]["frame_type"] == "hail"
        assert result["decrypted"] is True
        assert result["decoded_hail"] is not None
        assert result["decoded_hail"].body.center_freq_offset == 100
    finally:
        os.unlink(path)


def test_offline_decode_hail_wrong_key_fails():
    """Trying to decode the same capture as demo_other_key MUST fail."""
    with tempfile.NamedTemporaryFile(suffix=".cfile", delete=False) as f:
        path = f.name
    try:
        frame = dd.build_demo_hail()
        dd.tx_to_file(frame, path, prefix_ms=3.0)

        result = dd.offline_decode_hail(
            path, responder_static=dd.demo_other_key()
        )
        # The frame IS detected (ASM + msg_type), but decrypt fails
        assert result["frame"] is not None
        assert result["frame"]["frame_type"] == "hail"
        assert result["decrypted"] is False
        assert result["decoded_hail"] is None
    finally:
        os.unlink(path)


def test_offline_decode_hail_repeats():
    """Multiple hail copies in the capture still decode the first."""
    with tempfile.NamedTemporaryFile(suffix=".cfile", delete=False) as f:
        path = f.name
    try:
        frame = dd.build_demo_hail()
        dd.tx_to_file(frame, path, prefix_ms=2.0, repeats=3)
        result = dd.offline_decode_hail(path)
        assert result["decrypted"] is True
        assert result["decoded_hail"].body.mode == 0x01
    finally:
        os.unlink(path)


def test_decimate_to_chips_shape():
    # 16 samples at SAMPS_PER_CHIP=8 → 2 chips
    samples = np.ones(16, dtype=np.complex64) * (1 + 0j)
    chips = dd._decimate_to_chips(samples)
    assert len(chips) == 16 // dd.SAMPS_PER_CHIP
    assert np.allclose(chips, 1.0)


# ── Runner ──────────────────────────────────────────────────────────────────

def _run_all():
    tests = [(n, f) for n, f in globals().items()
             if n.startswith("test_") and callable(f)]
    passed = failed = 0
    t0 = time.time()
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception:
            print(f"  FAIL  {name}")
            traceback.print_exc()
            failed += 1
    dt = time.time() - t0
    print(f"\n{passed} passed, {failed} failed in {dt:.2f}s")
    return failed


if __name__ == "__main__":
    sys.exit(_run_all())
