from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo as dd


class _FakeDevice:
    def close(self) -> None:
        return None


def _patch_soapy_device_open(monkeypatch):
    sdr_mod = sys.modules[dd.SoapyDevice.__module__]
    monkeypatch.setitem(sys.modules, "SoapySDR", SimpleNamespace())
    monkeypatch.setattr(sdr_mod, "_open_soapy_with_retry", lambda *_a, **_k: _FakeDevice())
    monkeypatch.setattr(sdr_mod, "_read_device_serial", lambda *_a, **_k: "78d063dc2b6d2267")


def test_soapydevice_hides_ppm_cal_in_default_output(capsys, monkeypatch):
    _patch_soapy_device_open(monkeypatch)
    monkeypatch.setattr(dd.sf, "SISL_DEBUG", False, raising=False)
    sdr = dd.SoapyDevice(center_hz=2_437_000_000)
    sdr.close()
    out = capsys.readouterr().out
    assert "PPM cal: device" not in out


def test_soapydevice_shows_ppm_cal_in_debug_output(capsys, monkeypatch):
    _patch_soapy_device_open(monkeypatch)
    monkeypatch.setattr(dd.sf, "SISL_DEBUG", True, raising=False)
    sdr = dd.SoapyDevice(center_hz=2_437_000_000)
    sdr.close()
    out = capsys.readouterr().out
    assert "PPM cal: device" in out


def test_tx_mode_runs_on_soapy_path(monkeypatch):
    class _FakeSoapyCtx:
        def __init__(self, *_a, center_hz=None, **_k):
            self.center_hz = center_hz
            self.device = object()

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(dd, "SoapyDevice", _FakeSoapyCtx)
    monkeypatch.setattr(
        dd,
        "build_demo_hail_fec_chips",
        lambda: (dd.np.array([1, -1], dtype=dd.np.int8), b"\x1a\xcf\xfc\x1d\x03\x01"),
    )
    monkeypatch.setattr(dd, "soapy_tx_streaming", lambda _gen, *_a, **_k: 0)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(Path(__file__).resolve().parent / "demo.py"), "--mode", "tx", "--duration", "0", "--tx-vga", "0"],
    )
    assert dd.main() == 0


def test_tx_mode_runs_without_gnuradio(monkeypatch):
    """Compatibility shim for verify-local pinned test target."""
    test_tx_mode_runs_on_soapy_path(monkeypatch)


def test_legacy_mode_is_rejected(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [str(Path(__file__).resolve().parent / "demo.py"), "--mode", "tx-gr-legacy"],
    )
    try:
        dd.main()
        raise AssertionError("expected argparse to reject removed tx-gr-legacy mode")
    except SystemExit as exc:
        assert exc.code == 2


def test_compute_rlnc_rx_timeout_coord_path_uses_fixed_fallback():
    timeout_s = dd._compute_rlnc_rx_timeout(
        coord_active=True,
        k_symbols=16,
        symbol_bytes=64,
        chip_rate_hz=1_000_000,
    )
    assert timeout_s == 600.0


def test_compute_rlnc_rx_timeout_no_coord_uses_symbol_budget():
    timeout_s = dd._compute_rlnc_rx_timeout(
        coord_active=False,
        k_symbols=16,
        symbol_bytes=64,
        chip_rate_hz=1_000_000,
    )
    assert timeout_s >= 120.0
    assert timeout_s != 600.0


def test_finalize_call_payload_coord_early_path():
    class _FakeCoord:
        def __init__(self):
            self.wait_calls = 0
            self.send_calls = 0

        def wait_for_switch(self, timeout=300.0):  # noqa: ARG002
            self.wait_calls += 1
            return True

        def send_switch(self):
            self.send_calls += 1

    coord = _FakeCoord()
    assert dd._finalize_call_payload_coord(coord, payload_early=True)
    assert coord.wait_calls == 1
    assert coord.send_calls == 2
