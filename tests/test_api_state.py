import time

from crossborder_api.agent import AgentManager
from crossborder_api.runtime import AnalyticsRuntime


def test_private_work_items_and_agent_sessions_persist(tmp_path, monkeypatch):
    database = tmp_path / "crossborder-state.db"
    monkeypatch.setenv("CROSSBORDER_APP_MODE", "private")
    monkeypatch.setenv("CROSSBORDER_STATE_DB", str(database))

    first_runtime = AnalyticsRuntime()
    first_runtime.update_work_item(
        "task-1",
        {"workflow_status": "IN_PROGRESS", "owner": "运营负责人"},
    )
    first_agent = AgentManager(first_runtime)
    session = first_agent.create_session("demo-all")

    second_runtime = AnalyticsRuntime()
    second_agent = AgentManager(second_runtime)

    assert second_runtime._work_items["task-1"]["workflow_status"] == "IN_PROGRESS"
    assert second_agent.sessions[session["session_id"]]["dataset_id"] == "demo-all"


def test_demo_sessions_are_removed_after_ttl():
    runtime = type("DemoRuntime", (), {"app_mode": "demo", "state_store": None})()
    manager = AgentManager(runtime)
    session = manager.create_session("demo-all")
    session_id = session["session_id"]
    manager.runs["run-expired"] = []
    manager._run_sessions["run-expired"] = session_id
    manager._session_deadlines[session_id] = time.monotonic() - 1

    manager._cleanup_expired()

    assert session_id not in manager.sessions
    assert "run-expired" not in manager.runs
