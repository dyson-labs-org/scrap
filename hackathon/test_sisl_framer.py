"""Unit + loopback tests for sisl_framer.py.

Run: python hackathon/test_sisl_framer.py
"""

from __future__ import annotations

import os

import numpy as np
import pytest

import sisl_crypto as sc
import sisl_framer as sf


# ── Basic sanity ────────────────────────────────────────────────────────────

def test_byte_bit_roundtrip():
    data = b"\x00\x01\xAB\xFF\x1A\xCF\xFC\x1D"
    bits = sf.bytes_to_bits(data)
    assert len(bits) == len(data) * 8
    out = sf.bits_to_bytes(bits)
    assert out == data


# ── Differential bit encoding ──────────────────────────────────────────────

def test_differential_encode_decode_roundtrip():
    """Hand-computed reference vector for the differential encoder.

    Bits:        [1, 0, 1, 1, 0, 0, 1, 0]    (input)
    seed = 0:
       e[-1] = 0
       e[0]  = 0 XOR 1 = 1
       e[1]  = 1 XOR 0 = 1
       e[2]  = 1 XOR 1 = 0
       e[3]  = 0 XOR 1 = 1
       e[4]  = 1 XOR 0 = 1
       e[5]  = 1 XOR 0 = 1
       e[6]  = 1 XOR 1 = 0
       e[7]  = 0 XOR 0 = 0
    Encoded:     [1, 1, 0, 1, 1, 1, 0, 0]
    """
    bits = np.array([1, 0, 1, 1, 0, 0, 1, 0], dtype=np.uint8)
    expected = np.array([1, 1, 0, 1, 1, 1, 0, 0], dtype=np.uint8)
    encoded = sf.differential_encode_bits(bits, seed=0)
    assert np.array_equal(encoded, expected), (encoded, expected)
    decoded = sf.differential_decode_bits(encoded, seed=0)
    assert np.array_equal(decoded, bits)


def test_differential_encode_with_seed_one():
    """Same input, seed = 1, every encoded bit is flipped vs seed=0."""
    bits = np.array([1, 0, 1, 1, 0, 0, 1, 0], dtype=np.uint8)
    encoded = sf.differential_encode_bits(bits, seed=1)
    # seed=1 flips e[-1], so all subsequent e_k flip
    expected = np.array([0, 0, 1, 0, 0, 0, 1, 1], dtype=np.uint8)
    assert np.array_equal(encoded, expected)
    decoded = sf.differential_decode_bits(encoded, seed=1)
    assert np.array_equal(decoded, bits)


def test_differential_encode_random_roundtrip():
    rng = np.random.default_rng(seed=42)
    bits = rng.integers(0, 2, 1000).astype(np.uint8)
    for seed in (0, 1):
        encoded = sf.differential_encode_bits(bits, seed=seed)
        decoded = sf.differential_decode_bits(encoded, seed=seed)
        assert np.array_equal(decoded, bits)


# ── DBPSK end-to-end deterministic test vector ─────────────────────────────
#
# This is the Q7 sign-of-life test mandated by the panel review. It traces
# every stage of the DBPSK pipeline with hand-computed expected values, so
# any sign-convention regression in the encoder, drift estimator, or
# differential decoder is caught at unit-test time before any RF.

def test_dbpsk_deterministic_vector_noiseless():
    """Hand-traced DBPSK pipeline, no noise, no drift.

    Stages (all hand-computed):
      1. Pilot bits (4): [0, 0, 1, 1] — KNOWN, transmitted coherently.
         BPSK: 0→+1, 1→−1, so pilot symbols = [+1, +1, −1, −1].
      2. Body bits (6): [0, 1, 1, 0, 0, 1] — INPUT.
         Differential encode with seed = 1 (last pilot bit):
            e[-1] = 1
            e[0]  = 1 XOR 0 = 1   → BPSK −1
            e[1]  = 1 XOR 1 = 0   → BPSK +1
            e[2]  = 0 XOR 1 = 1   → BPSK −1
            e[3]  = 1 XOR 0 = 1   → BPSK −1
            e[4]  = 1 XOR 0 = 1   → BPSK −1
            e[5]  = 1 XOR 1 = 0   → BPSK +1
         Encoded body symbols = [−1, +1, −1, −1, −1, +1].
      3. Full TX symbol stream (10): [+1, +1, −1, −1, −1, +1, −1, −1, −1, +1].
      4. Apply absolute phase rotation θ₀ = 0.5 rad (no drift):
         peak[k] = symbol[k] * exp(j * 0.5)
      5. RX recovers θ₀ = 0.5 from pilot fit, derotates.
      6. Body bits decoded via differential dot products on derotated peaks.

    The decoded body bits MUST equal the original input [0, 1, 1, 0, 0, 1].
    """
    pilot_bits = np.array([0, 0, 1, 1], dtype=np.uint8)
    body_input = np.array([0, 1, 1, 0, 0, 1], dtype=np.uint8)

    # Stage 1: pilot symbols (coherent BPSK)
    pilot_symbols = (1.0 - 2.0 * pilot_bits.astype(np.float64))
    assert np.array_equal(pilot_symbols, [+1.0, +1.0, -1.0, -1.0])

    # Stage 2: differential encode body with seed = last pilot bit
    seed = int(pilot_bits[-1])  # = 1
    body_encoded = sf.differential_encode_bits(body_input, seed=seed)
    assert np.array_equal(body_encoded, [1, 0, 1, 1, 1, 0]), body_encoded

    body_symbols = (1.0 - 2.0 * body_encoded.astype(np.float64))
    assert np.array_equal(body_symbols, [-1.0, +1.0, -1.0, -1.0, -1.0, +1.0])

    # Stage 3: full TX symbol stream
    tx_symbols = np.concatenate([pilot_symbols, body_symbols])
    expected_tx = np.array(
        [+1.0, +1.0, -1.0, -1.0, -1.0, +1.0, -1.0, -1.0, -1.0, +1.0])
    assert np.array_equal(tx_symbols, expected_tx)

    # Stage 4: apply absolute phase rotation
    theta0 = 0.5
    peaks = (tx_symbols * np.exp(1j * theta0)).astype(np.complex128)

    # Stage 5: pilot-fit θ₀ recovery
    # Coherent sum after derotating by known pilot signs:
    aligned = peaks[:len(pilot_bits)] * pilot_symbols
    recovered_theta0 = float(np.angle(np.sum(aligned)))
    assert abs(recovered_theta0 - theta0) < 1e-9

    # Stage 6: derotate and differential-decode the body
    derotated = peaks * np.exp(-1j * recovered_theta0)
    # All derotated values should be ≈ ±1 + 0j with no rotation
    assert np.allclose(derotated.imag, 0, atol=1e-9)

    # Differential decode body bits, anchoring on last pilot peak
    body_derotated = derotated[len(pilot_bits):]
    last_pilot = derotated[len(pilot_bits) - 1]
    prev_peaks = np.empty_like(body_derotated)
    prev_peaks[0] = last_pilot
    prev_peaks[1:] = body_derotated[:-1]
    body_llrs = (body_derotated * np.conj(prev_peaks)).real
    decoded_body = (body_llrs < 0).astype(np.uint8)
    assert np.array_equal(decoded_body, body_input), (
        f"decoded={decoded_body} expected={body_input}")


# ── DBPSK decoder via dbpsk_decode_from_pilot ──────────────────────────────

def _make_dbpsk_test_signal(pilot_bits, body_bits, theta0, delta_theta,
                            noise_std=0.0, rng=None):
    """Build a complex peak vector for the DBPSK pipeline:
    - body is differentially encoded with seed = pilot_bits[-1]
    - all symbols are BPSK ±1, then rotated by theta0 + k*delta_theta
    - optional complex AWGN with per-axis std noise_std added per peak
    Returns (peaks, body_input).
    """
    seed = int(pilot_bits[-1])
    body_encoded = sf.differential_encode_bits(body_bits, seed=seed)
    pilot_symbols = (1.0 - 2.0 * pilot_bits.astype(np.float64))
    body_symbols = (1.0 - 2.0 * body_encoded.astype(np.float64))
    tx = np.concatenate([pilot_symbols, body_symbols])
    n = len(tx)
    k_arr = np.arange(n, dtype=np.float64)
    rotated = tx * np.exp(1j * (theta0 + k_arr * delta_theta))
    peaks = rotated.astype(np.complex128)
    if noise_std > 0 and rng is not None:
        noise = (rng.normal(0, noise_std, n).astype(np.float64)
                 + 1j * rng.normal(0, noise_std, n).astype(np.float64))
        peaks = peaks + noise
    return peaks


def test_dbpsk_decode_noiseless_zero_drift():
    """The minimal sanity check: noiseless, no drift, exact recovery."""
    pilot_bits = np.array([0, 0, 1, 1], dtype=np.uint8)
    body_bits = np.array([0, 1, 1, 0, 0, 1], dtype=np.uint8)
    peaks = _make_dbpsk_test_signal(pilot_bits, body_bits, theta0=0.0,
                                     delta_theta=0.0)
    result = sf.dbpsk_decode_from_pilot(peaks, pilot_bits, len(peaks))
    assert result is not None
    frame, soft, theta0_est, delta_est, rms = result
    assert abs(theta0_est) < 1e-6
    assert abs(delta_est) < 1e-6
    decoded_bits = (soft < 0).astype(np.uint8)
    expected = np.concatenate([pilot_bits, body_bits])
    assert np.array_equal(decoded_bits, expected), (decoded_bits, expected)


def test_dbpsk_decode_with_theta0_only():
    """Pilot fit recovers a non-zero θ₀."""
    pilot_bits = np.array([0, 0, 1, 1], dtype=np.uint8)
    body_bits = np.array([0, 1, 1, 0, 0, 1], dtype=np.uint8)
    theta0 = 0.7
    peaks = _make_dbpsk_test_signal(pilot_bits, body_bits, theta0=theta0,
                                     delta_theta=0.0)
    result = sf.dbpsk_decode_from_pilot(peaks, pilot_bits, len(peaks))
    assert result is not None
    _, soft, theta0_est, delta_est, _ = result
    assert abs(theta0_est - theta0) < 1e-6, (theta0_est, theta0)
    assert abs(delta_est) < 1e-6
    decoded_bits = (soft < 0).astype(np.uint8)
    expected = np.concatenate([pilot_bits, body_bits])
    assert np.array_equal(decoded_bits, expected)


def test_dbpsk_decode_with_small_drift():
    """Small drift Δθ = 0.1 rad/sym, well within V-V's range, exact recovery."""
    pilot_bits = np.array([0, 0, 1, 1, 0, 1, 0, 1] * 6, dtype=np.uint8)  # 48
    body_bits = np.tile([0, 1, 1, 0, 0, 1, 1, 0], 32)                     # 256
    delta_theta = 0.1
    peaks = _make_dbpsk_test_signal(pilot_bits, body_bits, theta0=0.3,
                                     delta_theta=delta_theta)
    result = sf.dbpsk_decode_from_pilot(peaks, pilot_bits, len(peaks))
    assert result is not None
    _, soft, _, delta_est, _ = result
    assert abs(delta_est - delta_theta) < 0.01, (delta_est, delta_theta)
    decoded_bits = (soft < 0).astype(np.uint8)
    expected = np.concatenate([pilot_bits, body_bits])
    assert np.array_equal(decoded_bits, expected)


def test_dbpsk_decode_at_v_v_cliff():
    """Δθ = 1.5 rad/sym — exactly the live-test value where V-V alone
    sits on the squaring branch cut. The FFT coarse search MUST cover
    this range. This is the panel-mandated regression test for Q3."""
    pilot_bits = np.array([0, 0, 1, 1, 0, 1, 0, 1] * 6, dtype=np.uint8)
    body_bits = np.tile([0, 1, 1, 0, 0, 1, 1, 0], 32)
    delta_theta = 1.5
    peaks = _make_dbpsk_test_signal(pilot_bits, body_bits, theta0=-0.4,
                                     delta_theta=delta_theta)
    result = sf.dbpsk_decode_from_pilot(peaks, pilot_bits, len(peaks))
    assert result is not None
    _, soft, _, delta_est, _ = result
    # FFT coarse search has bin width ~2π/nfft. With 304 squared
    # samples, nfft ≈ 512, so bin width ≈ 0.012 rad. V-V refines
    # within the bin. Expect delta_est within ~0.005 rad of truth.
    assert abs(delta_est - delta_theta) < 0.05, (delta_est, delta_theta)
    decoded_bits = (soft < 0).astype(np.uint8)
    expected = np.concatenate([pilot_bits, body_bits])
    assert np.array_equal(decoded_bits, expected)


def test_dbpsk_decode_at_negative_drift():
    """Same cliff value but negative — covers the [−π, 0] half of the FFT range."""
    pilot_bits = np.array([0, 0, 1, 1, 0, 1, 0, 1] * 6, dtype=np.uint8)
    body_bits = np.tile([0, 1, 1, 0, 0, 1, 1, 0], 32)
    delta_theta = -1.5
    peaks = _make_dbpsk_test_signal(pilot_bits, body_bits, theta0=0.6,
                                     delta_theta=delta_theta)
    result = sf.dbpsk_decode_from_pilot(peaks, pilot_bits, len(peaks))
    assert result is not None
    _, soft, _, delta_est, _ = result
    assert abs(delta_est - delta_theta) < 0.05, (delta_est, delta_theta)
    decoded_bits = (soft < 0).astype(np.uint8)
    expected = np.concatenate([pilot_bits, body_bits])
    assert np.array_equal(decoded_bits, expected)


def test_dbpsk_decode_with_awgn():
    """AWGN at high SNR. Tests the LLR sign convention end-to-end with
    noise; threshold accounts for the DBPSK ~2 dB asymptotic loss vs
    coherent BPSK."""
    rng = np.random.default_rng(seed=7)
    pilot_bits = np.array([0, 0, 1, 1, 0, 1, 0, 1] * 6, dtype=np.uint8)
    body_bits = rng.integers(0, 2, 256).astype(np.uint8)
    # Per-axis noise std 0.15 → per-symbol Es/N0 ≈ 11 dB
    # Post-DBPSK SNR ≈ 9 dB → expected BER < 1e-3
    peaks = _make_dbpsk_test_signal(pilot_bits, body_bits, theta0=0.2,
                                     delta_theta=0.05, noise_std=0.15,
                                     rng=rng)
    result = sf.dbpsk_decode_from_pilot(peaks, pilot_bits, len(peaks))
    assert result is not None
    _, soft, _, _, _ = result
    decoded_bits = (soft < 0).astype(np.uint8)
    expected = np.concatenate([pilot_bits, body_bits])
    ber = float(np.mean(decoded_bits != expected))
    assert ber < 0.02, f"BER={ber} too high at ~11 dB Es/N0 DBPSK"


def test_estimate_drift_v_v_only_in_range():
    """Without pilot_bits, V-V alone is bounded to Δθ ∈ [−π/2, +π/2].
    Inside this range it must be accurate to ~0.01 rad."""
    pilot_bits = np.array([0, 0, 1, 1, 0, 1, 0, 1] * 6, dtype=np.uint8)
    body_bits = np.tile([0, 1, 1, 0, 0, 1, 1, 0], 32)
    # Inside the V-V cliff:
    test_deltas = [-1.4, -1.0, -0.5, 0.0, 0.3, 0.7, 1.0, 1.4]
    for dt in test_deltas:
        peaks = _make_dbpsk_test_signal(pilot_bits, body_bits, theta0=0.0,
                                         delta_theta=dt)
        delta_est = sf.estimate_drift_per_symbol(peaks)
        assert abs(delta_est - dt) < 0.02, (
            f"Δθ={dt} estimate={delta_est} error={delta_est-dt}")


def test_estimate_drift_with_pilot_full_range():
    """With pilot_bits, the estimator unwraps V-V around the pilot
    coarse estimate and covers the full Δθ ∈ [−π, +π] range. This is
    the panel-mandated regression test for Q3 (V-V cliff at ±π/2)."""
    pilot_bits = np.array([0, 0, 1, 1, 0, 1, 0, 1] * 6, dtype=np.uint8)
    body_bits = np.tile([0, 1, 1, 0, 0, 1, 1, 0], 32)
    test_deltas = [-2.8, -2.0, -1.5, -0.5, 0.0, 0.3, 0.7, 1.5, 2.0, 2.8]
    for dt in test_deltas:
        peaks = _make_dbpsk_test_signal(pilot_bits, body_bits, theta0=0.0,
                                         delta_theta=dt)
        delta_est = sf.estimate_drift_per_symbol(peaks, pilot_bits=pilot_bits)
        assert abs(delta_est - dt) < 0.02, (
            f"Δθ={dt} estimate={delta_est} error={delta_est-dt}")


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
        payload_len=20,
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


# ── Bit-level framer (for FEC-coded payloads) ───────────────────────────────

def test_tx_bits_to_chips_clean_loopback():
    rng = np.random.default_rng(seed=137)
    bits = rng.integers(0, 2, size=137, dtype=np.uint8)
    chips = sf.tx_bits_to_chips(bits)
    assert chips.dtype == np.int8
    assert len(chips) == 137 * sf.CHIPS_PER_SYMBOL
    recovered = sf.rx_chips_to_bits(chips, 137)
    assert recovered.shape == (137,)
    assert recovered.dtype == np.uint8
    assert np.array_equal(recovered, bits)


def test_tx_bits_to_chips_loopback_at_minus_10dB():
    rng = np.random.default_rng(seed=42)
    n = 1000
    bits = rng.integers(0, 2, size=n, dtype=np.uint8)
    chips = sf.tx_bits_to_chips(bits).astype(np.float32)
    chip_snr_db = -10.0
    noise_std = 10 ** (-chip_snr_db / 20.0)
    noise = rng.normal(0.0, noise_std, chips.shape).astype(np.float32)
    recovered = sf.rx_chips_to_bits(chips + noise, n)
    errors = int(np.sum(recovered != bits))
    assert errors <= n // 100, f"{errors} bit errors exceeds 1% of {n}"


def test_tx_bits_to_chips_byte_aligned_matches_bytes_path():
    rng = np.random.default_rng(seed=7)
    payload = bytes(rng.integers(0, 256, size=16, dtype=np.uint8))
    chips_bytes = sf.tx_bytes_to_chips(payload)
    chips_bits = sf.tx_bits_to_chips(sf.bytes_to_bits(payload))
    assert np.array_equal(chips_bytes, chips_bits)


def test_tx_bits_to_chips_empty():
    out = sf.tx_bits_to_chips(np.empty(0, dtype=np.uint8))
    assert out.dtype == np.int8
    assert out.size == 0


def test_tx_bits_to_chips_wrong_dtype_or_value():
    bad = np.array([0, 1, 2, 1], dtype=np.uint8)
    try:
        sf.tx_bits_to_chips(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for non-0/1 input")

    # float64 array of clean 0.0/1.0 is accepted via astype(uint8)
    float_bits = np.array([0.0, 1.0, 1.0, 0.0, 1.0], dtype=np.float64)
    chips = sf.tx_bits_to_chips(float_bits)
    assert chips.dtype == np.int8
    assert len(chips) == 5 * sf.CHIPS_PER_SYMBOL


def test_rx_chips_to_bits_partial_recovery():
    rng = np.random.default_rng(seed=100)
    bits = rng.integers(0, 2, size=100, dtype=np.uint8)
    chips = sf.tx_bits_to_chips(bits)
    out = sf.rx_chips_to_bits(chips, 100)
    assert out.shape == (100,)
    assert out.dtype == np.uint8
    assert np.array_equal(out, bits)


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
    code_a = sf.DEFAULT_PUBLIC_CODE
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
    assert abs(theta0 - theta0_true) < 1e-3
    assert abs(delta - delta_true) < 1e-4
    assert rms < 1e-2


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
    assert abs(theta0 - theta0_true) < 5e-3
    assert abs(delta - delta_true) < 5e-4


def test_fit_phase_from_known_bits_large_slope_no_pi_ambiguity():
    """The old unwrap+polyfit estimator fails at slope ≈ π/symbol
    (the π ambiguity boundary). The new ML estimator must work here.
    """
    rng = np.random.default_rng(seed=21)
    bits = rng.integers(0, 2, size=48).astype(np.uint8)
    theta0_true = 0.2
    # Slope near the boundary that broke unwrap
    delta_true = np.pi * 0.9
    peaks = _synth_peaks(bits, theta0_true, delta_true, noise_std=0.05,
                          seed=22)
    fit = sf.fit_phase_from_known_bits(peaks, 0, bits)
    assert fit is not None
    theta0, delta, rms = fit
    # Must resolve the correct slope within ~0.02 rad/symbol
    assert abs(delta - delta_true) < 0.02, \
        f"delta recovered {delta} vs true {delta_true}"
    assert rms < 0.3


def test_fit_phase_from_known_bits_negative_slope():
    """Negative slopes should be recovered correctly too."""
    rng = np.random.default_rng(seed=23)
    bits = rng.integers(0, 2, size=48).astype(np.uint8)
    theta0_true = -1.1
    delta_true = -0.4
    peaks = _synth_peaks(bits, theta0_true, delta_true, noise_std=0.05,
                          seed=24)
    fit = sf.fit_phase_from_known_bits(peaks, 0, bits)
    assert fit is not None
    theta0, delta, _ = fit
    assert abs(delta - delta_true) < 0.02
    assert abs(theta0 - theta0_true) < 0.05


def test_fit_phase_noise_ratio_reflects_quality():
    """rms_residual should grow monotonically with noise level."""
    rng = np.random.default_rng(seed=25)
    bits = rng.integers(0, 2, size=64).astype(np.uint8)
    rmss = []
    for noise in [0.0, 0.1, 0.3, 0.6, 1.0]:
        peaks = _synth_peaks(bits, theta0=0.1, delta=0.001,
                              noise_std=noise, seed=26)
        fit = sf.fit_phase_from_known_bits(peaks, 0, bits)
        assert fit is not None
        rmss.append(fit[2])
    # Monotone nondecreasing
    for a, b in zip(rmss, rmss[1:]):
        assert b >= a - 0.05, f"non-monotone: {rmss}"
    # Clean case near zero, noisy case clearly larger
    assert rmss[0] < 0.1
    assert rmss[-1] > rmss[0]


def test_fit_phase_from_known_bits_too_short():
    assert sf.fit_phase_from_known_bits(
        np.zeros(10, dtype=np.complex128), 0,
        np.array([0, 1, 0], dtype=np.uint8),
    ) is None


# ── Tracker lock-floor regression (I3 fix) ─────────────────────────────────

def _synth_tracker_samples(n_bits: int, samps_per_chip: int,
                            attenuate_symbol: int = -1,
                            attenuate_factor: float = 1.0,
                            seed: int = 0) -> np.ndarray:
    """Build a clean BPSK DSSS sample stream with optional single-symbol
    magnitude attenuation. Used to reproduce the I3 failure mode.

    The byte-level loopback path only exposes byte-granular bits, but
    the tracker doesn't care what the bit values are — it just needs a
    frame-length worth of peaks. We construct an all-zero payload of
    the right byte count so the exact bit values don't matter for the
    lock-floor test, and attenuate one symbol's chip burst to simulate
    a transient dip.
    """
    n_bytes = (n_bits + 7) // 8
    # Random bytes chosen deterministically so the test is reproducible.
    rng = np.random.default_rng(seed)
    payload = rng.integers(0, 256, size=n_bytes, dtype=np.uint8).tobytes()
    chips = sf.tx_bytes_to_chips(payload).astype(np.float32)
    samples = np.repeat(chips, samps_per_chip).astype(np.complex64)

    # Optionally attenuate one symbol's worth of samples to simulate a
    # per-symbol noise dip. This is what the old lock_floor rejects.
    if attenuate_symbol >= 0 and attenuate_factor != 1.0:
        sps = sf.CHIPS_PER_SYMBOL * samps_per_chip
        start = attenuate_symbol * sps
        end = start + sps
        if end <= len(samples):
            samples[start:end] *= attenuate_factor

    return samples


@pytest.mark.parametrize(
    "n_bytes, attenuate_symbol, attenuate_factor, seed",
    [
        pytest.param(262, 3, 0.08, 271, id="long_frame_early_dip"),
        pytest.param(262, 20, 0.15, 271, id="post_bootstrap_dip"),
        pytest.param(133, -1, 1.0, 42, id="short_frame_unchanged"),
    ],
)
def test_decode_with_freq_tracking_lock_floor(
    n_bytes, attenuate_symbol, attenuate_factor, seed,
):
    samps_per_chip = 2
    n_bits = n_bytes * 8
    samples = _synth_tracker_samples(
        n_bits, samps_per_chip,
        attenuate_symbol=attenuate_symbol,
        attenuate_factor=attenuate_factor,
        seed=seed,
    )
    result = sf.decode_with_freq_tracking(
        samples, samps_per_chip=samps_per_chip,
        n_bytes=n_bytes,
    )
    assert result is not None
    assert len(result["peak_values"]) == n_bits

