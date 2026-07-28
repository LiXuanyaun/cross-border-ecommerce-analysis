import asyncio
import time

from crossborder_api.agent import AgentManager, ProviderConfig
from crossborder_api.runtime import AnalyticsRuntime


def test_private_work_items_and_agent_sessions_persist(tmp_path, monkeypatch):
    database = tmp_path / "crossborder-state.db"
    monkeypatch.setenv("CROSSBORDER_APP_MODE", "private")
    monkeypatch.setenv("CROSSBORDER_STATE_DB", str(database))

    first_runtime = AnalyticsRuntime()
    first_runtime.update_work_item(
        "task-1",
        {"workflow_status": "IN_PROGRESS", "owner": "运营负责人", "deadline": "2025-05-31"},
    )
    first_agent = AgentManager(first_runtime)
    session = first_agent.create_session("demo-all")

    second_runtime = AnalyticsRuntime()
    second_agent = AgentManager(second_runtime)

    assert second_runtime._work_items["task-1"]["workflow_status"] == "IN_PROGRESS"
    assert second_runtime._work_items["task-1"]["deadline"] == "2025-05-31"
    assert second_agent.sessions[session["session_id"]]["dataset_id"] == "demo-all"


def test_private_work_item_close_fields_persist(tmp_path, monkeypatch):
    database = tmp_path / "crossborder-state.db"
    monkeypatch.setenv("CROSSBORDER_APP_MODE", "private")
    monkeypatch.setenv("CROSSBORDER_STATE_DB", str(database))

    runtime = AnalyticsRuntime()
    runtime.update_work_item(
        "task-close",
        {
            "workflow_status": "CLOSED",
            "owner": "运营负责人",
            "deadline": "2025-05-31",
            "result_note": "已完成复盘",
            "review_result": "目标指标改善",
            "close_reason": "已验证完成",
            "closed_by": "总监",
            "closed_at": "2025-05-31T00:00:00+00:00",
        },
    )

    second_runtime = AnalyticsRuntime()
    saved = second_runtime._work_items["task-close"]

    assert saved["workflow_status"] == "CLOSED"
    assert saved["result_note"] == "已完成复盘"
    assert saved["review_result"] == "目标指标改善"
    assert saved["close_reason"] == "已验证完成"
    assert saved["closed_by"] == "总监"
    assert saved["closed_at"] == "2025-05-31T00:00:00+00:00"


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


def test_configured_provider_is_used_outside_private_mode():
    class DemoRuntime:
        app_mode = "demo"
        state_store = None

        def agent_context(self, dataset_id, question, start=None, end=None, market=None, category=None):
            context = {
                "question": question,
                "dataset": {"dataset_id": dataset_id, "name": "测试数据集"},
                "period": {"start": "2025-01-01", "end": "2025-01-31"},
                "agent_plan": [],
                "tools": [],
                "tool_observations": [],
                "decision_brief": {
                    "status": "SUCCESS",
                    "cases": [{
                        "finding": {"summary": "GMV 下降"},
                        "actions": [{"title": "调整投放", "action": "暂停低效组合"}],
                        "evidence": [{"metric": "GMV", "source": "注册指标"}],
                        "limitations": ["缺少广告成本"],
                    }],
                },
                "trace": [],
            }
            bundle = type("Bundle", (), {"metadata": {"scope_id": "scope-test"}})()
            return context, bundle

    async def synthesize(prompt):
        assert "请按问题回答" in prompt
        return "模型按问题生成的答案"

    manager = AgentManager(DemoRuntime())
    manager.provider.config = ProviderConfig(
        source="test",
        provider_name="测试模型",
        base_url="https://provider.example/v1",
        api_key="secret",
        model="test-model",
        wire_api="responses",
    )
    manager.provider.synthesize = synthesize
    session = manager.create_session("demo-all")
    run_id = "run-provider"
    manager.runs[run_id] = []

    asyncio.run(manager._execute(run_id, session["session_id"], "demo-all", "请按问题回答"))

    result = next(item for item in manager.runs[run_id] if item["type"] == "result")
    assert "模型按问题生成的答案" in result["payload"]["answer"]
