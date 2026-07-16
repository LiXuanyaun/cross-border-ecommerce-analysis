import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "browser_control.py"
SPEC = importlib.util.spec_from_file_location("browser_control", SCRIPT)
browser_control = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(browser_control)


def test_debug_endpoints_are_loopback_and_distinct():
    assert browser_control.ENDPOINTS == {
        "chrome": "http://127.0.0.1:9222",
        "edge": "http://127.0.0.1:9223",
    }


def test_status_reports_unavailable_endpoint_without_raising(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("not listening")

    monkeypatch.setattr(browser_control, "urlopen", unavailable)
    result = browser_control.debug_status("chrome")
    assert result["ready"] is False
    assert result["endpoint"] == "http://127.0.0.1:9222"
