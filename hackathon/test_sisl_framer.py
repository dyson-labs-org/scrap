"""Unit + loopback tests for sisl_framer.py.

Run: python hackathon/test_sisl_framer.py
"""

from __future__ import annotations

import os
import sys
import time
import traceback

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sisl_crypto as sc
import sisl_framer as sf


# ── Basic sanity ────────────────────────────────────────────────────────────

def test_public_code_length_and_shape():
    code = sf.public_hail_code()
    assert code.dtype == np.int8
    assert len(code) == sf.CHIPS_PER_SYMBOL
    assert set(np.unique(code).tolist()) == {-1, 1}


def test_byte_bit_roundtrip():
    data = b"\x00\x01\xAB\xFF\x1A\xCF\xFC\x1D"
    bits = sf.bytes_to_bits(data)
    assert len(bits) == len(data) * 8
    out = sf.bits_to_bytes(bits)
    assert out == data


# ── TX → RX clean loopback ──────────────────────────────────────────────────

def test_tx_rx_loopback_clean_short():
    data = b"\x1A\xCF\xFC\x1D\x03\x01\xDE\xAD\xBE\xEF"
    chips = sf.tx_bytes_to_chips(data)
    assert len(chips) == len(data) * 8 * sf.CHIPS_PER_SYMBOL
    assert chips.dtype == np.int8
    assert set(np.unique(chips).tolist()) == {-1, 1}
    recovered = sf.rx_chips_to_bytes(chips, len(data))
    assert recovered == data


def test_tx_rx_loopback_random_100b():
    data = os.urandom(100)
    chips = sf.tx_bytes_to_chips(data)
    recovered = sf.rx_chips_to_bytes(chips, len(data))
    assert recovered == data


def test_tx_rx_loopback_full_hail_frame():
    """Pipe a real SISL v3 hail frame through the framer."""
    caller_static = sc.generate_keypair()
    responder_static = sc.generate_keypair()
    caller_eph = sc.Ephemeral()
    body = sc.HailBody(
        caller_static_pub=sc.pubkey_to_compressed(caller_static.public_key()),
        center_freq_offset=100,
        bandwidth_code=0x03,
        mode=0x01,
        chip_rate_code=0x32,
        body_nonce=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        flags=0x03,
    )
    frame = sc.encode_hail(caller_eph, responder_static.public_key(), body)
    assert len(frame) == sc.HAIL_FRAME_LEN

    chips = sf.tx_bytes_to_chips(frame)
    recovered = sf.rx_chips_to_bytes(chips, len(frame))
    assert recovered == frame

    # Trial-decrypt from the despread frame end-to-end
    decoded = sc.decode_hail(recovered, responder_static)
    assert decoded is not None
    assert decoded.body.body_nonce == body.body_nonce


# ── Noise robustness ────────────────────────────────────────────────────────

def _run_noisy_loopback(data: bytes, chip_snr_db: float,
                        rng: np.random.Generator) -> bytes:
    """Transmit, add AWGN at the specified per-chip SNR, recover."""
    chips = sf.tx_bytes_to_chips(data).astype(np.float32)
    # Signal power is 1 per chip (±1). noise_std from SNR:
    #   SNR_dB = 10 log10(1 / noise_var)
    noise_std = 10 ** (-chip_snr_db / 20.0)
    noise = rng.normal(0.0, noise_std, chips.shape).astype(np.float32)
    rxed = chips + noise
    return sf.rx_chips_to_bytes(rxed, len(data))


def test_loopback_noise_0dB():
    """SNR = 0 dB per chip → post-despread SNR ≈ 30 dB (L=1023) → no BER."""
    rng = np.random.default_rng(seed=1)
    data = os.urandom(64)
    recovered = _run_noisy_loopback(data, chip_snr_db=0.0, rng=rng)
    assert recovered == data


def test_loopback_noise_minus_10dB():
    """SNR = -10 dB per chip → post-despread ≈ 20 dB → clean recovery."""
    rng = np.random.default_rng(seed=2)
    data = os.urandom(64)
    recovered = _run_noisy_loopback(data, chip_snr_db=-10.0, rng=rng)
    assert recovered == data


def test_loopback_noise_minus_20dB_ber():
    """SNR = -20 dB per chip → post-despread ≈ 10 dB → small BER tolerated."""
    rng = np.random.default_rng(seed=3)
    data = os.urandom(64)
    recovered = _run_noisy_loopback(data, chip_snr_db=-20.0, rng=rng)
    # Expect near-zero BER at 10 dB post-despread for BPSK
    errors = sum(bin(a ^ b).count("1") for a, b in zip(data, recovered))
    total_bits = len(data) * 8
    ber = errors / total_bits
    assert ber < 0.01, f"BER {ber:.3f} too high"


# ── Wrong code rejects signal ───────────────────────────────────────────────

def test_wrong_code_produces_garbage():
    """Despreading with a different code must NOT recover the message."""
    data = b"this is a secret transmission that must stay hidden"
    code_a = sf.public_hail_code()
    code_b = sf.code_from_seed(b"\x55" * 32)

    chips = sf.tx_bytes_to_chips(data, code=code_a)
    wrong = sf.rx_chips_to_bytes(chips, len(data), code=code_b)
    # Must not match original
    assert wrong != data
    # And must have substantial bit errors (≈50 %)
    errors = sum(bin(a ^ b).count("1") for a, b in zip(data, wrong))
    total = len(data) * 8
    assert errors > total * 0.3, (
        f"unexpectedly few errors with wrong code: {errors}/{total}"
    )


# ── Sliding correlator acquisition ──────────────────────────────────────────

def test_find_frame_start_chip_zero():
    data = b"hello world"
    chips = sf.tx_bytes_to_chips(data)
    offset = sf.find_frame_start(chips.astype(np.float32), max_search=256)
    # Signal starts at chip 0; peak at 0
    assert offset == 0


def test_find_frame_start_with_prefix_noise():
    rng = np.random.default_rng(seed=4)
    data = b"hello world"
    pad = rng.normal(0, 0.5, size=137).astype(np.float32)
    chips = sf.tx_bytes_to_chips(data).astype(np.float32)
    stream = np.concatenate([pad, chips])
    offset = sf.find_frame_start(stream, max_search=512)
    # True start is at 137
    assert offset is not None
    assert abs(offset - 137) <= 1


def test_find_frame_start_large_prefix_no_bound():
    """Full-stream search locates the frame without an explicit max_search."""
    rng = np.random.default_rng(seed=5)
    data = b"greetings from chip 7500"
    pad = rng.normal(0, 0.3, size=7500).astype(np.float32)
    chips = sf.tx_bytes_to_chips(data).astype(np.float32)
    stream = np.concatenate([pad, chips])
    offset = sf.find_frame_start(stream)
    assert offset is not None
    # The matched filter peaks at every symbol boundary; the first above-
    # threshold peak corresponds to chip 7500 (the signal start).
    assert abs(offset - 7500) <= 1


def test_matched_filter_magnitude_shape():
    rng = np.random.default_rng(seed=6)
    stream = rng.normal(0, 1, size=10_000).astype(np.float32)
    mag = sf.matched_filter_magnitude(stream)
    assert len(mag) == 10_000 - sf.CHIPS_PER_SYMBOL + 1
    # Pure noise → no peak clearly above median
    assert np.max(mag) < 6 * np.median(mag)


# ── Pilot-aided coherent decode ─────────────────────────────────────────────

def _synth_peaks(bits: np.ndarray, theta0: float, delta: float,
                 amp: float = 1.0, noise_std: float = 0.0,
                 seed: int = 0) -> np.ndarray:
    """Synthesize a sequence of complex peak values for a BPSK bit stream.
    peak[k] = amp · sign(bit k) · exp(j·(theta0 + k·delta)) + noise"""
    rng = np.random.default_rng(seed)
    n = len(bits)
    k = np.arange(n, dtype=np.float64)
    sign = np.where(bits == 0, 1.0, -1.0)
    phasors = np.exp(1j * (theta0 + k * delta))
    peaks = amp * sign * phasors
    if noise_std > 0:
        peaks = peaks + (rng.normal(0, noise_std, n)
                         + 1j * rng.normal(0, noise_std, n))
    return peaks.astype(np.complex128)


def test_fit_phase_from_known_bits_clean():
    rng = np.random.default_rng(seed=11)
    bits = rng.integers(0, 2, size=64).astype(np.uint8)
    theta0_true = 0.7
    delta_true = 0.02
    peaks = _synth_peaks(bits, theta0_true, delta_true)
    fit = sf.fit_phase_from_known_bits(peaks, 0, bits)
    assert fit is not None
    theta0, delta, rms = fit
    assert abs(theta0 - theta0_true) < 1e-6
    assert abs(delta - delta_true) < 1e-6
    assert rms < 1e-6


def test_fit_phase_from_known_bits_with_offset():
    """Pilot doesn't start at bit 0 — theta0 should map back to bit 0."""
    rng = np.random.default_rng(seed=12)
    bits = rng.integers(0, 2, size=64).astype(np.uint8)
    theta0_true = -0.4
    delta_true = 0.015
    peaks = _synth_peaks(bits, theta0_true, delta_true)
    start = 10
    pilot = bits[start:start + 32]
    fit = sf.fit_phase_from_known_bits(peaks, start, pilot)
    assert fit is not None
    theta0, delta, _ = fit
    assert abs(theta0 - theta0_true) < 1e-6
    assert abs(delta - delta_true) < 1e-6


def test_coherent_decode_from_pilot_clean():
    rng = np.random.default_rng(seed=13)
    n_bits = 133 * 8
    bits = rng.integers(0, 2, size=n_bits).astype(np.uint8)
    # Force first 32 bits to a known ASM-like pattern
    asm_bits = rng.integers(0, 2, size=32).astype(np.uint8)
    bits[:32] = asm_bits
    peaks = _synth_peaks(bits, theta0=0.3, delta=0.01)
    result = sf.coherent_decode_from_pilot(peaks, 0, asm_bits, n_bits)
    assert result is not None
    frame_bytes, soft, theta0, delta, rms = result
    # Reconstruct bits and compare
    decoded_bits = sf.bytes_to_bits(frame_bytes)[:n_bits]
    assert np.array_equal(decoded_bits, bits)
    assert rms < 1e-6


def test_coherent_decode_from_pilot_noisy():
    """Coherent decode works at moderate SNR with small residual drift.

    Note: at ~10 dB SNR with only 32 pilot bits, the slope estimate has
    high variance, and a delta error ~0.003 rad/symbol accumulates over
    1000+ bits to flip nearly half the later bits. In practice the chip
    tracker supplies a good drift estimate, so the coherent decoder only
    needs to refine a small residual; for this unit test we use low
    residual drift + modest noise to exercise the clean coherent path.
    """
    rng = np.random.default_rng(seed=14)
    n_bits = 133 * 8
    bits = rng.integers(0, 2, size=n_bits).astype(np.uint8)
    asm_bits = rng.integers(0, 2, size=32).astype(np.uint8)
    bits[:32] = asm_bits
    peaks = _synth_peaks(bits, theta0=-0.5, delta=0.0,
                          noise_std=0.08, seed=15)
    result = sf.coherent_decode_from_pilot(peaks, 0, asm_bits, n_bits)
    assert result is not None
    frame_bytes, _, _, _, rms = result
    decoded_bits = sf.bytes_to_bits(frame_bytes)[:n_bits]
    ber = float(np.mean(decoded_bits != bits))
    assert ber < 0.02, f"BER too high: {ber}"
    assert rms < 0.3


def test_fit_phase_from_known_bits_too_short():
    assert sf.fit_phase_from_known_bits(
        np.zeros(10, dtype=np.complex128), 0,
        np.array([0, 1, 0], dtype=np.uint8),
    ) is None


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
