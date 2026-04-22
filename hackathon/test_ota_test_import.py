import importlib.util
from pathlib import Path


def test_importing_ota_test_does_not_launch_subprocesses(monkeypatch):
    popen_calls = []

    def _fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        raise AssertionError("ota_test import should not launch subprocesses")

    monkeypatch.setattr("subprocess.Popen", _fake_popen)
    module_path = Path(__file__).resolve().parent / "ota_test.py"
    spec = importlib.util.spec_from_file_location("ota_test_import_safety", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)

    assert popen_calls == []
