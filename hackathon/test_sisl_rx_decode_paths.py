from __future__ import annotations

from types import SimpleNamespace

import numpy as np

import sisl_rx


def test_try_decode_llrs_polarities_prefers_positive():
    llrs = np.array([1.0, -2.0], dtype=np.float32)

    seen = []

    def _decode(arr: np.ndarray):
        seen.append(arr.copy())
        return "ok" if np.array_equal(arr, llrs) else None

    decoded, polarity = sisl_rx._try_decode_llrs_polarities(
        llrs,
        _decode,
        polarity_pos="pos",
        polarity_inv="inv",
    )

    assert decoded == "ok"
    assert polarity == "pos"
    assert len(seen) == 1


def test_try_fec_decrypt_hail_reports_inverted_polarity(monkeypatch):
    monkeypatch.setattr(
        sisl_rx,
        "find_sisl_frame_soft_topk",
        lambda *args, **kwargs: [(0, 20.0, 5.0)],
    )
    monkeypatch.setattr(
        sisl_rx,
        "_extract_llrs_at_position",
        lambda *args, **kwargs: {
            "fec_llrs": np.array([1.0, -3.0], dtype=np.float32),
            "phase_rms_residual_rad": 0.05,
            "asm_errs_in_coherent": 0,
        },
    )

    decoded_hail = SimpleNamespace(body=b"payload", caller_eph_pub_canonical=b"epk")

    def _decode_hail(llrs: np.ndarray, _responder_static):
        if np.array_equal(llrs, np.array([-1.0, 3.0], dtype=np.float32)):
            return decoded_hail
        return None

    monkeypatch.setattr(sisl_rx.sc, "decode_hail_fec_from_llrs", _decode_hail)

    result = sisl_rx._try_fec_decrypt(
        peak_values=[0j] * sisl_rx.sc.HAIL_FEC_TOTAL_BITS,
        positions=[7],
        top_k_soft=1,
        freq_hz=10.0,
        peak_mag=4.0,
        median_mag=1.0,
        rad_per_sample=0.0,
        responder_static=object(),
    )

    assert result["status"] == "decrypt_ok"
    assert result["polarity"] == "fec-inv"
    assert result["decoded_hail"] is decoded_hail


def test_decode_payload_candidates_accepts_inverted_llrs(monkeypatch):
    monkeypatch.setattr(
        sisl_rx,
        "find_sisl_frame_soft_topk",
        lambda *args, **kwargs: [(0, 6.5, 2.0)],
    )
    monkeypatch.setattr(
        sisl_rx.sf,
        "dbpsk_decode_from_pilot",
        lambda *args, **kwargs: (
            np.zeros(2, dtype=np.uint8),
            np.array([1.0, -1.0], dtype=np.float32),
            np.zeros(2, dtype=np.float32),
            0.0,
            0.0,
        ),
    )

    def _decode_payload(llrs: np.ndarray, n_payload_bytes: int):
        if n_payload_bytes == 2 and np.array_equal(llrs, np.array([-1.0, 1.0], dtype=np.float32)):
            return b"ok"
        return None

    monkeypatch.setattr(sisl_rx.sc, "decode_payload_symbol_fec_from_llrs", _decode_payload)

    results = sisl_rx._decode_payload_candidates(
        peak_values=[0j] * 4,
        n_payload_bytes=2,
        n_fec_bits=2,
        base={"freq_offset_hz": 0.0},
        max_candidates=1,
        return_first=True,
    )

    assert len(results) == 1
    assert results[0]["status"] == "decrypt_ok"
    assert results[0]["payload_frame_bytes"] == b"ok"


def test_extract_llrs_out_of_range_returns_contract_shape():
    result = sisl_rx._extract_llrs_at_position(
        peak_values=[0j] * 8,
        peak_offset=99,
        n_fec_bits=16,
        pilot_bits=np.array([0, 1], dtype=np.uint8),
    )

    assert set(result.keys()) == {
        "fec_llrs",
        "phase_rms_residual_rad",
        "asm_errs_in_coherent",
    }
    assert result["fec_llrs"] is None
    assert result["phase_rms_residual_rad"] is None
    assert result["asm_errs_in_coherent"] is None
