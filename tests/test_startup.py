from pathlib import Path

from fastapi.testclient import TestClient

from crossborder_api.build_identity import current_build_fingerprint
from crossborder_api.main import app


ROOT = Path(__file__).resolve().parents[1]


def test_build_fingerprint_changes_with_backend_or_frontend_content(tmp_path):
    backend = tmp_path / "crossborder_api"
    frontend = tmp_path / "frontend" / "src"
    backend.mkdir(parents=True)
    frontend.mkdir(parents=True)
    backend_file = backend / "sample.py"
    frontend_file = frontend / "sample.ts"
    backend_file.write_text("VALUE = 1\n", encoding="utf-8")
    frontend_file.write_text("export const value = 1;\n", encoding="utf-8")
    first = current_build_fingerprint(tmp_path)

    frontend_file.write_text("export const value = 2;\n", encoding="utf-8")

    assert current_build_fingerprint(tmp_path) != first


def test_health_exposes_process_build_identity():
    with TestClient(app) as client:
        health = client.get("/api/v1/health").json()

    assert health["status"] == "ok"
    assert health["workspace_root"] == str(ROOT)
    assert health["build_fingerprint"] == current_build_fingerprint(ROOT)
    assert "unified_dataset_id" in health


def test_startup_scripts_require_identity_match_and_unified_smoke_check():
    startup = (ROOT / "scripts" / "start_web.ps1").read_text(encoding="utf-8")
    readiness = (ROOT / "scripts" / "open_when_ready.ps1").read_text(encoding="utf-8")

    assert "$sameWorkspace -and $sameBuild -and $sameMode" in startup
    assert "It was not stopped" in startup
    assert "Restarting stale CrossBorder process" in startup
    assert "$datasetId -notin $catalogIds" in readiness
    assert "$datasetId -notin $businessIds" in readiness
