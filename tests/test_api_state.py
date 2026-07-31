import asyncio
import time

import pandas as pd

import crossborder_api.runtime as runtime_module
from crossborder_api.agent import AgentManager, ProviderConfig
from crossborder_api.runtime import AnalyticsRuntime
from crossborder_api.services import DemoScenario


def test_dataset_catalog_is_cached_until_analysis_cache_clear(monkeypatch):
    scenario = DemoScenario("cached-demo", "缓存演示", "测试数据集", {}, "测试来源")
    context = type("Context", (), {"analysis_data": pd.DataFrame({"order_date": ["2025-01-01"]})})()
    quality_calls = {"count": 0}

    def fake_quality(*_args):
        quality_calls["count"] += 1
        return type("Quality", (), {"quality_score": 88.0})(), None, None, None, None, None

    monkeypatch.setattr(runtime_module, "SCENARIOS", (scenario,))
    monkeypatch.setattr(runtime_module, "assess_business_quality", fake_quality)
    monkeypatch.setattr(runtime_module, "replace", lambda obj, **_changes: obj)
    runtime = AnalyticsRuntime()
    monkeypatch.setattr(runtime, "_imported_scenarios", lambda: ())
    monkeypatch.setattr(runtime, "_context_for", lambda _dataset_id: context)
    monkeypatch.setattr(runtime, "date_bounds", lambda _dataset_id: ("2025-01-01", "2025-01-01"))
    first = runtime.datasets()
    second = runtime.datasets()

    assert first == second
    assert quality_calls["count"] == 1
    runtime.clear_analysis_cache()
    runtime.datasets()
    assert quality_calls["count"] == 2


def test_private_catalog_keeps_unified_default_and_exposes_ready_web_imports(monkeypatch):
    unified = DemoScenario(
        "unified-test", "统一数据", "统一数据", {}, "统一来源",
        metadata={"import_origin": "unified"},
    )
    uploaded = DemoScenario(
        "web-test", "我的导入", "用户导入", {}, "Web 上传", is_demo=False,
        metadata={"import_origin": "web"},
    )
    source = DemoScenario(
        "source-test", "合并来源", "内部来源", {}, "AdventureWorks",
        metadata={"import_origin": "adventureworks"},
    )
    context = type("Context", (), {"analysis_data": pd.DataFrame({"order_date": ["2025-01-01"]})})()

    monkeypatch.setattr(
        runtime_module,
        "assess_business_quality",
        lambda *_args: (type("Quality", (), {"quality_score": 88.0})(), None, None, None, None, None),
    )
    monkeypatch.setattr(runtime_module, "replace", lambda obj, **_changes: obj)
    runtime = AnalyticsRuntime()
    runtime.app_mode = "private"
    monkeypatch.setattr(runtime, "_imported_scenarios", lambda: (uploaded, source, unified))
    monkeypatch.setattr(runtime, "_context_for", lambda _dataset_id: context)
    monkeypatch.setattr(runtime, "date_bounds", lambda _dataset_id: ("2025-01-01", "2025-01-01"))

    assert [item["dataset_id"] for item in runtime.datasets()] == ["unified-test", "web-test"]


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
    assert result["payload"]["model"]["status"] == "USED"
    assert any(item["type"] == "model" and item["payload"]["status"] == "USED" for item in manager.runs[run_id])


def test_empty_provider_output_uses_partial_deterministic_fallback():
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
                        "limitations": [],
                    }],
                },
                "trace": [],
            }
            bundle = type("Bundle", (), {"metadata": {"scope_id": "scope-test"}})()
            return context, bundle

    async def synthesize(prompt):
        return "   "

    manager = AgentManager(DemoRuntime())
    manager.provider.config = ProviderConfig(
        source="test", provider_name="测试模型", base_url="https://provider.example/v1",
        api_key="secret", model="test-model", wire_api="responses",
    )
    manager.provider.synthesize = synthesize
    session = manager.create_session("demo-all")
    run_id = "run-empty-provider"
    manager.runs[run_id] = []

    asyncio.run(manager._execute(run_id, session["session_id"], "demo-all", "分析问题"))

    result = next(item for item in manager.runs[run_id] if item["type"] == "result")
    assert result["payload"]["status"] == "PARTIAL"
    assert "GMV 下降" in result["payload"]["answer"]
    assert result["payload"]["model"]["status"] == "FALLBACK"
    assert any(item["type"] == "warning" for item in manager.runs[run_id])


def test_provider_hallucinated_number_uses_partial_deterministic_fallback():
    class DemoRuntime:
        app_mode = "demo"
        state_store = None

        def agent_context(self, dataset_id, question, start=None, end=None, market=None, category=None):
            context = {
                "question": question,
                "dataset": {"dataset_id": dataset_id, "name": "测试数据集"},
                "period": {"start": "2025-01-01", "end": "2025-01-31"},
                "agent_plan": [], "tools": [], "tool_observations": [], "trace": [],
                "decision_brief": {"status": "SUCCESS", "cases": [{
                    "finding": {"summary": "GMV 下降 5%"},
                    "actions": [{"title": "复核", "action": "检查订单结构"}],
                    "evidence": [{"metric": "GMV", "source": "注册指标"}],
                    "limitations": [],
                }]},
            }
            return context, type("Bundle", (), {"metadata": {"scope_id": "scope-test"}})()

    async def synthesize(prompt):
        return "利润将增长 999999%。"

    manager = AgentManager(DemoRuntime())
    manager.provider.config = ProviderConfig(
        "test", "测试模型", "https://provider.example/v1", "secret", "test-model", "responses",
    )
    manager.provider.synthesize = synthesize
    session = manager.create_session("demo-all")
    run_id = "run-invalid-provider"
    manager.runs[run_id] = []

    asyncio.run(manager._execute(run_id, session["session_id"], "demo-all", "分析问题"))

    result = next(item for item in manager.runs[run_id] if item["type"] == "result")
    assert result["payload"]["status"] == "PARTIAL"
    assert "999999" not in result["payload"]["answer"]
    assert result["payload"]["model"]["status"] == "FALLBACK"
    assert any("校验失败" in item["payload"].get("message", "") for item in manager.runs[run_id])


def test_model_answer_accepts_equivalent_number_format():
    context = {"metric": 808.5, "rate": 36.5}

    assert AgentManager._model_answer_error("花费 808.50，增长 36.50%。", context) is None
