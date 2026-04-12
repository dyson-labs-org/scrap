"""Unit tests for sisl_fec.py — rate-1/2 K=9 soft Viterbi.

Run: python hackathon/test_sisl_fec.py
"""

from __future__ import annotations

import time

import numpy as np

import sisl_fec as fec


# ── Basic length / constants ────────────────────────────────────────────────

def test_encode_length():
    """coded_length is 2*(n + TAIL_BITS).

    Note: the original task specified `coded_length(1000) == 2*1000 + 8
    = 2008`. That is a typo (operator-precedence error); the correct
    arithmetic for flushing TAIL_BITS=8 zero bits through a rate-1/2
    encoder is 2*(1000 + 8) = 2016. We assert the correct value.
    """
    assert fec.coded_length(1000) == 2 * (1000 + fec.TAIL_BITS)
    assert fec.coded_length(1000) == 2016
    # Spot checks
    assert fec.coded_length(0) == 2 * fec.TAIL_BITS
    assert fec.coded_length(1) == 2 * (1 + fec.TAIL_BITS)


def test_constants():
    """Public constants match the task spec."""
    assert fec.CODE_RATE_NUMERATOR == 1
    assert fec.CODE_RATE_DENOMINATOR == 2
    assert fec.CONSTRAINT_LENGTH == 9
    assert fec.TAIL_BITS == 8
    assert fec.CODED_BITS_PER_PAYLOAD_BIT == 2


# ── Noiseless round-trip ────────────────────────────────────────────────────

def test_encode_decode_noiseless():
    """Encode → convert coded bits to ±1 → pass as LLRs → perfect recovery."""
    rng = np.random.default_rng(seed=1)
    payload = rng.integers(0, 2, size=1000).astype(np.uint8)
    coded = fec.encode(payload)
    assert len(coded) == fec.coded_length(len(payload))
    # Bit c=0 → LLR +1; bit c=1 → LLR −1
    llrs = (1.0 - 2.0 * coded.astype(np.float32))
    recovered = fec.decode(llrs, n_payload_bits=len(payload))
    assert len(recovered) == len(payload)
    assert np.array_equal(recovered, payload), \
        f"noiseless round trip failed; diff count = {int(np.sum(recovered != payload))}"


# ── Noise tolerance ─────────────────────────────────────────────────────────

def _simulate_awgn_ber(n_payload: int, es_n0_db: float,
                       n_trials: int, seed: int) -> float:
    """Encode random bits, add AWGN at Es/N0, decode, measure BER."""
    rng = np.random.default_rng(seed)
    es_n0 = 10.0 ** (es_n0_db / 10.0)
    sigma = np.sqrt(1.0 / (2.0 * es_n0))    # per-symbol noise std for Es=1
    total_errors = 0
    total_bits = 0
    for _ in range(n_trials):
        payload = rng.integers(0, 2, size=n_payload).astype(np.uint8)
        coded = fec.encode(payload)
        symbols = (1.0 - 2.0 * coded.astype(np.float32))
        noise = rng.normal(0.0, sigma, size=symbols.shape).astype(np.float32)
        y = symbols + noise
        # Soft LLR proportional to matched-filter output: LLR = 2·y/σ².
        # We absorb the 2/σ² scale since it's a common factor across
        # all LLRs and Viterbi is scale-invariant.
        llrs = y
        recovered = fec.decode(llrs, n_payload_bits=n_payload)
        total_errors += int(np.sum(recovered != payload))
        total_bits += n_payload
    return total_errors / total_bits


def test_decode_corrects_low_noise():
    """BER < 1e-4 at Es/N0 = 3 dB over 100 trials of 1000 bits."""
    ber = _simulate_awgn_ber(n_payload=1000, es_n0_db=3.0,
                               n_trials=100, seed=2)
    assert ber < 1e-4, f"BER={ber} at Es/N0=3dB, expected <1e-4"


def test_decode_corrects_moderate_noise():
    """BER < 1e-2 at Es/N0 = 1 dB over 100 trials of 1000 bits."""
    ber = _simulate_awgn_ber(n_payload=1000, es_n0_db=1.0,
                               n_trials=100, seed=3)
    assert ber < 1e-2, f"BER={ber} at Es/N0=1dB, expected <1e-2"


# ── LLR sign convention ─────────────────────────────────────────────────────

def test_llr_sign_convention():
    """Positive LLR means bit 0. Flipping signs must produce ones."""
    n_payload = 500
    # All-positive LLRs → strongly indicates coded bits are all 0.
    # The all-zero coded sequence is a valid codeword (encode(zeros)),
    # so the decoder should recover an all-zero payload.
    n_coded = fec.coded_length(n_payload)
    pos_llrs = np.full(n_coded, 10.0, dtype=np.float32)
    recovered_pos = fec.decode(pos_llrs, n_payload_bits=n_payload)
    assert np.all(recovered_pos == 0), \
        f"all-positive LLRs decoded to non-zero: " \
        f"{int(np.sum(recovered_pos != 0))} ones"

    # All-negative LLRs → decoder picks whatever valid codeword maximizes
    # the sum of negative LLRs, which is the LEAST-LIKE-ALL-ZERO path.
    # The result must contain at least one bit 1 (and almost certainly
    # many).
    neg_llrs = -pos_llrs
    recovered_neg = fec.decode(neg_llrs, n_payload_bits=n_payload)
    assert np.any(recovered_neg == 1), \
        "all-negative LLRs decoded to all zeros"


# ── Output length ───────────────────────────────────────────────────────────

def test_decode_output_length():
    """decode() always returns exactly n_payload_bits, never the tail."""
    rng = np.random.default_rng(seed=4)
    for n in [1, 7, 8, 9, 100, 1001, 4097]:
        payload = rng.integers(0, 2, size=n).astype(np.uint8)
        coded = fec.encode(payload)
        llrs = (1.0 - 2.0 * coded.astype(np.float32))
        recovered = fec.decode(llrs, n_payload_bits=n)
        assert len(recovered) == n, \
            f"decode returned {len(recovered)} bits for n_payload={n}"
        assert np.array_equal(recovered, payload), \
            f"noiseless round trip at n={n} failed"


# ── Performance ─────────────────────────────────────────────────────────────

def test_vectorized_decode_perf():
    """10000 payload bits should decode in under 1 s (500 ms target, 2x slack)."""
    rng = np.random.default_rng(seed=5)
    n_payload = 10_000
    payload = rng.integers(0, 2, size=n_payload).astype(np.uint8)
    coded = fec.encode(payload)
    llrs = (1.0 - 2.0 * coded.astype(np.float32))
    t0 = time.perf_counter()
    recovered = fec.decode(llrs, n_payload_bits=n_payload)
    dt = time.perf_counter() - t0
    assert np.array_equal(recovered, payload), "10k-bit decode corrupted data"
    # Target 500 ms; allow 2x slack for CI / slower hardware.
    assert dt < 1.0, f"decode took {dt*1000:.0f} ms, expected <1000 ms"
    print(f"  perf: {n_payload} payload bits decoded in {dt*1000:.1f} ms")

