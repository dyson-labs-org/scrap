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

        recovered, offset = dd.offline_despread(path, n_bytes=len(_SHORT_MSG))
        assert recovered == _SHORT_MSG
        assert offset is not None
        assert offset == 0
    finally:
        os.unlink(path)


def test_tx_to_file_1ms_prefix_acquires():
    """1 ms prefix = 8000 samples = 1000 chips of silence before signal."""
    with tempfile.NamedTemporaryFile(suffix=".cfile", delete=False) as f:
        path = f.name
    try:
        dd.tx_to_file(_SHORT_MSG, path, prefix_ms=1.0)
        recovered, offset = dd.offline_despread(path, n_bytes=len(_SHORT_MSG))
        assert recovered == _SHORT_MSG
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
        recovered, offset = dd.offline_despread(path, n_bytes=len(_SHORT_MSG))
        assert recovered == _SHORT_MSG
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
        recovered, offset = dd.offline_despread(
            path, n_bytes=len(_SHORT_MSG), max_search_chips=2000
        )
        assert recovered == _SHORT_MSG
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
        recovered, offset = dd.offline_despread(path, n_bytes=len(frame))
        assert recovered == frame
        assert offset is not None
        # Trial-decrypt the recovered bytes — validates the full stack
        decoded = sc.decode_hail(recovered, responder_static)
        assert decoded is not None
        assert decoded.body.body_nonce == body.body_nonce
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
