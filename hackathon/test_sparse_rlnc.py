from __future__ import annotations

import sisl_crypto as sc
import sparse_rlnc as sr


def _make_prk() -> bytes:
    caller_eph = sc.Ephemeral()
    caller_eph_priv = caller_eph.consume()
    responder_eph = sc.Ephemeral()
    responder_eph_priv = responder_eph.consume()
    caller_static = sc.generate_keypair()
    responder_static = sc.generate_keypair()

    caller_eph_canonical = sc.pubkey_to_compressed(caller_eph_priv.public_key())
    responder_eph_canonical = sc.pubkey_to_compressed(responder_eph_priv.public_key())

    dh1 = sc.ecdh(caller_eph_priv, responder_static.public_key())
    dh2 = sc.ecdh(caller_static, responder_eph_priv.public_key())
    dh3 = sc.ecdh(caller_eph_priv, responder_eph_priv.public_key())
    keys = sc.derive_session_keys(dh1, dh2, dh3, caller_eph_canonical, responder_eph_canonical)
    return sc.derive_session_prk(keys)


PRK = _make_prk()


def test_rsd_sums_to_one():
    for K in (16, 32):
        cdf = sr.robust_soliton_cdf(K)
        assert abs(cdf[-1] - 1.0) < 1e-9, f"K={K} CDF[-1]={cdf[-1]}"


def test_degree_range():
    for K in (16, 32):
        cdf = sr.robust_soliton_cdf(K)
        for u in [0.0, 0.25, 0.5, 0.75, 0.9999]:
            d = sr.sample_degree(cdf, u)
            assert 1 <= d <= K, f"K={K} u={u} d={d}"


def test_coefficients_unique():
    for K in (16, 32):
        for comb_id in range(5):
            indices = sr.sample_coefficients(comb_id, K, PRK)
            assert len(indices) == len(set(indices)), "duplicate indices"
            assert all(0 <= i < K for i in indices), "index out of range"
            assert indices == sorted(indices), "not sorted"


def test_coefficients_deterministic():
    for K in (16, 32):
        a = sr.sample_coefficients(0, K, PRK)
        b = sr.sample_coefficients(0, K, PRK)
        assert a == b


def test_coefficients_distinct_comb_ids():
    K = 16
    a = sr.sample_coefficients(0, K, PRK)
    b = sr.sample_coefficients(1, K, PRK)
    assert a != b


def test_encode_length():
    payload = b'A' * 400
    K = 16
    enc = sr.RLNCEncoder(payload, K, PRK)
    _, sym, _ = enc.encode_symbol(0)
    frags = sr.fragment_payload(payload, K)
    assert len(sym) == len(frags[0])


def test_encode_xor():
    payload = bytes(range(256)) * 2
    K = 16
    enc = sr.RLNCEncoder(payload, K, PRK)
    frags = sr.fragment_payload(payload, K)

    for comb_id in range(20):
        _, sym, indices = enc.encode_symbol(comb_id)
        if len(indices) == 2:
            expected = bytes(a ^ b for a, b in zip(frags[indices[0]], frags[indices[1]]))
            assert sym == expected, f"comb_id={comb_id} XOR mismatch"
            return
    # if no degree-2 found, just verify degree-1
    for comb_id in range(20):
        _, sym, indices = enc.encode_symbol(comb_id)
        if len(indices) == 1:
            assert sym == frags[indices[0]]
            return


def test_fragment_padding():
    for payload_len in (1, 15, 16, 100, 512):
        for K in (16, 32):
            frags = sr.fragment_payload(bytes(payload_len), K)
            assert len(frags) == K
            frag_size = len(frags[0])
            assert frag_size % 16 == 0
            for f in frags:
                assert len(f) == frag_size
            assert frag_size * K % 16 == 0
