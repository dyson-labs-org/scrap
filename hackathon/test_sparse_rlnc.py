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


def test_robust_soliton_rejects_invalid_params():
    import pytest
    with pytest.raises(ValueError):
        sr.robust_soliton_cdf(0)
    with pytest.raises(ValueError):
        sr.robust_soliton_cdf(16, c=0.0)
    with pytest.raises(ValueError):
        sr.robust_soliton_cdf(16, delta=1.0)


def test_coefficients_unique():
    for K in (16, 32):
        for comb_id in range(5):
            indices, coeffs = sr.sample_coefficients(comb_id, K, PRK)
            assert len(indices) == len(set(indices)), "duplicate indices"
            assert all(0 <= i < K for i in indices), "index out of range"
            assert indices == sorted(indices), "not sorted"
            assert all(1 <= c <= 255 for c in coeffs), "coefficient out of GF(2^8) nonzero range"
            assert len(indices) == len(coeffs), "indices/coeffs length mismatch"


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


def test_encode_gf_linear():
    """Verify GF(2^8) linear combination: encoded = XOR of c_i * frag_i."""
    import numpy as np
    payload = bytes(range(256)) * 2
    K = 16
    enc = sr.RLNCEncoder(payload, K, PRK)
    frags = [np.frombuffer(f, dtype=np.uint8) for f in sr.fragment_payload(payload, K)]

    for comb_id in range(40):
        _, sym, indices = enc.encode_symbol(comb_id)
        idx_list, coeff_list = sr.sample_coefficients(comb_id, K, PRK)
        sym_arr = np.frombuffer(sym, dtype=np.uint8)
        expected = np.zeros(len(sym_arr), dtype=np.uint8)
        for idx, coeff in zip(idx_list, coeff_list):
            expected ^= sr._gf_mul_vec(coeff, frags[idx])
        assert (sym_arr == expected).all(), f"comb_id={comb_id} GF linear combination mismatch"
        return  # one check suffices


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


def test_decoder_exact_K():
    K = 16
    payload = bytes(range(256))
    enc = sr.RLNCEncoder(payload, K, PRK)
    dec = sr.RLNCDecoder(K, PRK)
    for comb_id in range(K * 3):
        _, sym, _ = enc.encode_symbol(comb_id)
        if dec.add_symbol(comb_id, sym):
            break
    result = dec.decode()
    assert result is not None
    frags = sr.fragment_payload(payload, K)
    expected = b''.join(frags)
    assert result == expected


def test_decoder_overhead():
    K = 16
    payload = bytes(range(256))
    enc = sr.RLNCEncoder(payload, K, PRK)
    dec = sr.RLNCDecoder(K, PRK)
    for comb_id in range(K * 4):
        _, sym, _ = enc.encode_symbol(comb_id)
        if dec.add_symbol(comb_id, sym):
            break
    assert dec.decode() is not None


def test_decoder_insufficient():
    K = 16
    payload = bytes(range(256))
    enc = sr.RLNCEncoder(payload, K, PRK)
    dec = sr.RLNCDecoder(K, PRK)
    for comb_id in range(K // 2):
        _, sym, _ = enc.encode_symbol(comb_id)
        dec.add_symbol(comb_id, sym)
    assert dec.decode() is None


def test_decoder_roundtrip_various_payloads():
    K = 16
    for payload in (b'X', b'B' * 512, b'C' * 100):
        enc = sr.RLNCEncoder(payload, K, PRK)
        dec = sr.RLNCDecoder(K, PRK)
        for comb_id in range(K * 3):
            _, sym, _ = enc.encode_symbol(comb_id)
            if dec.add_symbol(comb_id, sym):
                break
        result = dec.decode()
        assert result is not None
        frags = sr.fragment_payload(payload, K)
        expected = b''.join(frags)
        assert result == expected


def test_decoder_add_symbol_returns_complete():
    K = 16
    payload = bytes(range(256))
    enc = sr.RLNCEncoder(payload, K, PRK)
    dec = sr.RLNCDecoder(K, PRK)
    completed = False
    for comb_id in range(K * 3):
        _, sym, _ = enc.encode_symbol(comb_id)
        if dec.add_symbol(comb_id, sym):
            completed = True
            break
    assert completed


def test_decoder_k_minus_one_insufficient():
    K = 16
    payload = bytes(range(128))
    enc = sr.RLNCEncoder(payload, K, PRK)
    dec = sr.RLNCDecoder(K, PRK)
    for comb_id in range(K - 1):
        _, sym, _ = enc.encode_symbol(comb_id)
        dec.add_symbol(comb_id, sym)
    assert dec.decode() is None


def test_decoder_default_symbol_budget_is_4k():
    K = 16
    dec = sr.RLNCDecoder(K, PRK)
    assert dec.max_symbols == 4 * K


def test_decoder_budget_exhaustion_sets_status_and_bounds_seen_ids():
    K = 16
    payload = bytes(range(128))
    enc = sr.RLNCEncoder(payload, K, PRK)
    dec = sr.RLNCDecoder(K, PRK)
    _, sym0, _ = enc.encode_symbol(0)

    for _ in range(dec.max_symbols):
        dec.add_symbol(0, sym0)

    assert dec.is_budget_exhausted
    assert dec.status == "budget_exhausted"
    assert dec.failure_reason is not None
    assert "budget exhausted" in dec.failure_reason
    assert dec.received_symbols == dec.max_symbols
    assert dec.unique_symbol_ids == 1
    assert dec.decode() is None


def test_decoder_completes_before_budget_exhaustion():
    K = 16
    payload = bytes(range(256))
    enc = sr.RLNCEncoder(payload, K, PRK)
    dec = sr.RLNCDecoder(K, PRK)
    for comb_id in range(K * 3):
        _, sym, _ = enc.encode_symbol(comb_id)
        if dec.add_symbol(comb_id, sym):
            break
    assert dec.is_complete
    assert not dec.is_budget_exhausted
    assert dec.status == "complete"
