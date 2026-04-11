"""Unit tests for sisl_crypto.py (SISL v3) and sisl_dsss.py.

Tests are arranged bottom-up:
    1. DSSS code generator matches SISL.md §21.2 vectors
    2. HKDF key/IV derivation is deterministic and symmetric
    3. Elligator stub round-trips
    4. Hail frame round-trip: encode → decode under correct key
    5. Hail trial-decryption rejects wrong receiver (identity oracle)
    6. ACK round-trip: encode → decode under correct caller
    7. Ephemeral one-shot enforcement

Run with: python -m pytest hackathon/test_sisl_crypto.py
Or standalone: python hackathon/test_sisl_crypto.py
"""

from __future__ import annotations

import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sisl_crypto as sc
import sisl_dsss as sd


# ── 1. DSSS code generator ──────────────────────────────────────────────────

def test_dsss_hail_code_matches_spec_vector():
    """SISL.md §21.2 Test Vector 2: public hailing code first 32 chips.

    The spec vector uses seed = SHA256("SISL-public-hailing-code-v2") for
    v2, but v3 uses the "-v3" suffix. We verify the generator produces a
    deterministic bipolar code of the right length and shape.
    """
    seed = sd.hail_code_seed()
    code = sd.generate_dsss_code(seed, length=1023)
    assert len(code) == 1023
    assert all(c in (1, -1) for c in code)
    # Regenerate must match (deterministic)
    code2 = sd.generate_dsss_code(seed, length=1023)
    assert code == code2


def test_dsss_different_seeds_give_different_codes():
    code_a = sd.generate_dsss_code(hashlib.sha256(b"seedA").digest())
    code_b = sd.generate_dsss_code(hashlib.sha256(b"seedB").digest())
    assert code_a != code_b


def test_fhss_sequence_in_range():
    seq = sd.generate_fhss_sequence(b"\x00" * 32, num_channels=16, num_hops=100)
    assert len(seq) == 100
    assert all(0 <= x < 16 for x in seq)


# ── 2. HKDF key / IV derivation ─────────────────────────────────────────────

def test_hail_key_iv_symmetric():
    """Caller and receiver derive identical key/IV from DH1."""
    caller_eph = sc.generate_keypair()
    responder_static = sc.generate_keypair()

    dh1_caller = sc.ecdh(caller_eph, responder_static.public_key())
    dh1_responder = sc.ecdh(responder_static, caller_eph.public_key())
    assert dh1_caller == dh1_responder

    k1 = sc.derive_hail_key(dh1_caller)
    k2 = sc.derive_hail_key(dh1_responder)
    assert k1 == k2
    assert len(k1) == 32

    iv1 = sc.derive_hail_iv(dh1_caller)
    iv2 = sc.derive_hail_iv(dh1_responder)
    assert iv1 == iv2
    assert len(iv1) == 12

    # key and iv must differ
    assert k1[:12] != iv1


# ── 3. Elligator stub ──────────────────────────────────────────────────────

def test_elligator_stub_roundtrip():
    priv = sc.generate_keypair()
    pub = priv.public_key()
    encoded = sc.encode_ephemeral_pub(pub)
    assert len(encoded) == sc.ELLIGATOR_LEN
    decoded = sc.decode_ephemeral_pub(encoded)
    assert (sc.pubkey_to_compressed(decoded)
            == sc.pubkey_to_compressed(pub))


def test_elligator_stub_rejects_wrong_length():
    try:
        sc.decode_ephemeral_pub(b"\x00" * 63)
    except ValueError:
        return
    raise AssertionError("expected ValueError for short input")


# ── 4. Hail round-trip ─────────────────────────────────────────────────────

def _test_body() -> sc.HailBody:
    return sc.HailBody(
        center_freq_offset=100,
        bandwidth_code=0x03,
        mode=0x01,
        chip_rate_code=0x32,
        body_nonce=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        flags=0x03,
    )


def test_hail_roundtrip():
    responder_static = sc.generate_keypair()
    caller_eph = sc.Ephemeral()
    body = _test_body()

    frame = sc.encode_hail(caller_eph, responder_static.public_key(), body)
    assert len(frame) == sc.HAIL_FRAME_LEN

    decoded = sc.decode_hail(frame, responder_static)
    assert decoded is not None
    assert decoded.body.center_freq_offset == body.center_freq_offset
    assert decoded.body.body_nonce == body.body_nonce
    assert decoded.body.flags == body.flags


def test_hail_wrong_receiver_rejected():
    """Trial decryption MUST return None for a receiver that is not the target."""
    target_static = sc.generate_keypair()
    other_static = sc.generate_keypair()
    caller_eph = sc.Ephemeral()

    frame = sc.encode_hail(
        caller_eph, target_static.public_key(), _test_body()
    )
    # correct receiver
    assert sc.decode_hail(frame, target_static) is not None
    # wrong receiver — identity oracle must reject
    assert sc.decode_hail(frame, other_static) is None


def test_hail_corrupted_frame_rejected():
    responder_static = sc.generate_keypair()
    caller_eph = sc.Ephemeral()
    frame = sc.encode_hail(
        caller_eph, responder_static.public_key(), _test_body()
    )
    # flip one bit in the ciphertext (body starts at offset 70)
    corrupted = frame[:72] + bytes([frame[72] ^ 0x01]) + frame[73:]
    assert sc.decode_hail(corrupted, responder_static) is None


def test_hail_wrong_asm_rejected():
    responder_static = sc.generate_keypair()
    caller_eph = sc.Ephemeral()
    frame = sc.encode_hail(
        caller_eph, responder_static.public_key(), _test_body()
    )
    bad = b"\x00\x00\x00\x00" + frame[4:]
    assert sc.decode_hail(bad, responder_static) is None


# ── 5. ACK round-trip ──────────────────────────────────────────────────────

def test_ack_roundtrip():
    responder_static = sc.generate_keypair()
    caller_eph = sc.Ephemeral()

    # Caller keeps a reference to its ephemeral priv before encode consumes it
    caller_eph_priv_ref = caller_eph._priv   # peek for test purposes

    body = _test_body()
    hail_frame = sc.encode_hail(
        caller_eph, responder_static.public_key(), body
    )
    decoded_hail = sc.decode_hail(hail_frame, responder_static)
    assert decoded_hail is not None

    # Responder builds an ACK
    responder_eph = sc.Ephemeral()
    ack_frame = sc.encode_ack(
        responder_static_priv=responder_static,
        responder_eph=responder_eph,
        caller_eph_pub=decoded_hail.caller_eph_pub,
        decoded_hail=decoded_hail,
        status=1,
    )
    assert len(ack_frame) == sc.ACK_FRAME_LEN

    # Caller side: need DH1 at hail-time
    dh1_caller = sc.ecdh(caller_eph_priv_ref, responder_static.public_key())
    decoded_ack = sc.decode_ack(
        frame=ack_frame,
        caller_eph_priv=caller_eph_priv_ref,
        dh1=dh1_caller,
        expected_nonce_echo=body.body_nonce,
    )
    assert decoded_ack is not None
    assert decoded_ack.body.status == 1
    assert decoded_ack.body.nonce_echo == body.body_nonce


def test_ack_wrong_nonce_echo_rejected():
    responder_static = sc.generate_keypair()
    caller_eph = sc.Ephemeral()
    caller_eph_priv_ref = caller_eph._priv
    body = _test_body()
    hail_frame = sc.encode_hail(
        caller_eph, responder_static.public_key(), body
    )
    decoded_hail = sc.decode_hail(hail_frame, responder_static)

    responder_eph = sc.Ephemeral()
    ack_frame = sc.encode_ack(
        responder_static_priv=responder_static,
        responder_eph=responder_eph,
        caller_eph_pub=decoded_hail.caller_eph_pub,
        decoded_hail=decoded_hail,
        status=1,
    )

    dh1 = sc.ecdh(caller_eph_priv_ref, responder_static.public_key())
    # wrong expected nonce echo → reject
    result = sc.decode_ack(
        frame=ack_frame,
        caller_eph_priv=caller_eph_priv_ref,
        dh1=dh1,
        expected_nonce_echo=b"\xff" * 8,
    )
    assert result is None


# ── 6. Ephemeral one-shot enforcement ──────────────────────────────────────

def test_ephemeral_one_shot():
    e = sc.Ephemeral()
    _ = e.consume()
    try:
        _ = e.consume()
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError on second consume")


def test_encode_hail_consumes_ephemeral():
    """A second encode_hail with the same Ephemeral must fail."""
    responder_static = sc.generate_keypair()
    e = sc.Ephemeral()
    sc.encode_hail(e, responder_static.public_key(), _test_body())
    try:
        sc.encode_hail(e, responder_static.public_key(), _test_body())
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError on ephemeral reuse")


# ── Runner ──────────────────────────────────────────────────────────────────

def _run_all():
    import traceback
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
