from __future__ import annotations

from types import SimpleNamespace

import sisl_rx


def test_print_live_event_default_concise_decrypt_ok(capsys, monkeypatch):
    monkeypatch.setattr(sisl_rx.sf, "SISL_DEBUG", False, raising=False)
    result = {
        "status": "decrypt_ok",
        "peak_mag": 12.0,
        "median_mag": 1.2,
        "freq_offset_hz": 1234.0,
        "body": SimpleNamespace(
            body_nonce=b"\x00" * 16,
            center_freq_offset=2437,
            mode=1,
        ),
    }
    sisl_rx._print_live_event(7, result)
    out = capsys.readouterr().out.strip()
    assert out.startswith("[   7] ✅ HAIL decrypted")
    assert "SNR" not in out
    assert "Δf" not in out
    assert "asm@" not in out
    assert "nonce=" not in out


def test_print_live_event_default_concise_decrypt_fail(capsys, monkeypatch):
    monkeypatch.setattr(sisl_rx.sf, "SISL_DEBUG", False, raising=False)
    result = {
        "status": "decrypt_fail",
        "asm_at_byte": 4,
        "peak_mag": 6.0,
        "median_mag": 2.0,
        "freq_offset_hz": -88.0,
        "polarity": "-",
    }
    sisl_rx._print_live_event(2, result)
    out = capsys.readouterr().out.strip()
    assert out.startswith("[   2] ⚠️ Frame detected, but decrypt failed")
    assert "SNR" not in out
    assert "Δf" not in out
    assert "FRAME FOUND" not in out


def test_print_live_event_debug_preserves_engineering_detail(capsys, monkeypatch):
    monkeypatch.setattr(sisl_rx.sf, "SISL_DEBUG", True, raising=False)
    result = {
        "status": "decrypt_fail",
        "asm_at_byte": 4,
        "peak_mag": 6.0,
        "median_mag": 2.0,
        "freq_offset_hz": -88.0,
        "polarity": "-",
    }
    sisl_rx._print_live_event(2, result)
    out = capsys.readouterr().out.strip()
    assert out.startswith("[   2] FRAME FOUND")
    assert "asm@4" in out
    assert "SNR=+9.5dB" in out
    assert "Δf=-88Hz" in out
    assert "pol=-" in out
    assert "DECRYPT FAILED" in out


def test_print_live_event_quiet_suppresses_no_signal(capsys, monkeypatch):
    monkeypatch.setattr(sisl_rx.sf, "SISL_DEBUG", False, raising=False)
    result = {
        "status": "no_signal",
        "peak_mag": 3.0,
        "median_mag": 1.0,
        "freq_offset_hz": 0.0,
        "periodic_ratio": 0.12,
    }
    sisl_rx._print_live_event(3, result, quiet=True)
    out = capsys.readouterr().out
    assert out == ""


def test_print_live_event_default_no_signal_suppressed_after_block_two(capsys, monkeypatch):
    monkeypatch.setattr(sisl_rx.sf, "SISL_DEBUG", False, raising=False)
    result = {
        "status": "no_signal",
        "peak_mag": 3.0,
        "median_mag": 1.0,
        "freq_offset_hz": 0.0,
        "periodic_ratio": 0.12,
    }
    sisl_rx._print_live_event(2, result)
    out2 = capsys.readouterr().out
    assert "Listening: no usable signal yet" in out2

    sisl_rx._print_live_event(3, result)
    out3 = capsys.readouterr().out
    assert out3 == ""
