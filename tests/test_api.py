import json
import sqlite3

from fastapi.testclient import TestClient

from crossborder_api.agent import AgentManager, ProviderStore
from crossborder_api.main import app


def test_bootstrap_exposes_exact_four_primary_pages():
    with TestClient(app) as client:
        response = client.get("/api/v1/app/bootstrap")
    assert response.status_code == 200
    labels = [item["label"] for item in response.json()["data"]["navigation"]]
    assert labels == ["经营总览", "专题分析", "数据中心", "AI分析师"]


def test_overview_and_topic_use_dataset_and_scope_metadata():
    with TestClient(app) as client:
        overview = client.get("/api/v1/overview", params={"dataset_id": "demo-all"})
        topic = client.get("/api/v1/topics/market", params={"dataset_id": "demo-all", "page_size": 5})
    assert overview.status_code == 200
    assert overview.json()["meta"]["dataset_id"] == "demo-all"
    assert overview.json()["meta"]["scope_id"]
    assert {item["label"] for item in overview.json()["data"]["kpis"]} == {
        "GMV（成交总额）", "利润率", "订单数", "客单价",
    }
    assert topic.status_code == 200
    assert topic.json()["data"]["pagination"]["total"] >= 1


def test_overview_uses_real_comparison_series_and_complete_operating_modules():
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/overview",
            params={
                "dataset_id": "demo-all",
                "start": "2023-09-01",
                "end": "2025-08-31",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["current_period"] == {
        "start": "2025-08-01", "end": "2025-08-31", "type": "month",
    }
    assert data["comparison_period"] == {
        "start": "2025-07-01", "end": "2025-07-31", "type": "month",
    }
    assert set(data["trends"]) == {"day", "week"}
    assert data["trends"]["day"]["current_period"] == {"start": "2025-08-01", "end": "2025-08-31"}
    assert data["trends"]["day"]["comparison_period"] == {"start": "2025-07-01", "end": "2025-07-31"}
    assert len(data["trends"]["day"]["rows"]) == 31
    assert len(data["trends"]["week"]["rows"]) == 5
    assert all(
        {"current_date", "comparison_date", "current", "comparison"} <= set(row)
        for trend in data["trends"].values()
        for row in trend["rows"]
    )
    assert any(
        row["current"] != row["comparison"]
        for row in data["trends"]["day"]["rows"]
    )
    assert len(data["tasks"]) == 4
    assert all(
        task["object"]
        and task["anomaly"]
        and task["impact_amount"] is not None
        and task["target_threshold"]
        for task in data["tasks"]
    )
    assert [market["rank"] for market in data["markets"]] == [1, 2, 3, 4, 5]
    assert all(market["yoy"] is not None for market in data["markets"])
    assert abs(sum(item["share"] for item in data["categories"]) - 1.0) < 1e-9
    assert len(data["opportunities"]) == 2
    assert all(item["estimated_growth"] > 1000 and item["basis"] for item in data["opportunities"])
    assert set(data["methodology"]) == {"kpis", "trend", "tasks", "markets", "products", "opportunities", "insights"}
    assert all(
        item["basis"] and item["comparison"] and item["threshold"]
        for item in data["methodology"].values()
    )
    assert all(item["basis"] and item["threshold"] for item in data["kpis"])
    assert all(
        insight["sustainability"]["level"]
        and insight["sustainability"]["reason"]
        and insight["history"]["lookback_months"] <= 12
        and insight["evidence"]["formula"]
        and insight["recommendation"]["action"]
        and "task" not in insight
        for insight in data["insights"]
    )


def test_five_topic_views_have_independent_metrics_trends_rankings_and_details():
    topics = ["market", "product", "customer", "profit", "returns"]
    payloads = {}
    with TestClient(app) as client:
        for topic in topics:
            response = client.get(
                "/api/v1/topics/{}".format(topic),
                params={
                    "dataset_id": "demo-all", "start": "2023-09-01",
                    "end": "2025-08-31", "page": 1, "page_size": 10,
                },
            )
            assert response.status_code == 200
            payloads[topic] = response.json()["data"]

    metric_sets = {topic: tuple(item["id"] for item in data["metrics"]) for topic, data in payloads.items()}
    assert len(set(metric_sets.values())) == len(topics)
    assert len({data["trend"]["title"] for data in payloads.values()}) == len(topics)
    assert len({data["ranking"]["title"] for data in payloads.values()}) == len(topics)
    assert len({tuple(column["key"] for column in data["columns"]) for data in payloads.values()}) == len(topics)
    assert all(len(data["metrics"]) == 4 for data in payloads.values())
    assert all(data["trend"]["rows"] and data["ranking"]["rows"] for data in payloads.values())
    assert all(data["ai"]["findings"] and data["ai"]["evidence"] and data["ai"]["actions"] for data in payloads.values())
    assert all(data["report"]["summary"] == data["summary"] for data in payloads.values())
    assert len({data["decision_board"]["trend"]["title"] for data in payloads.values()}) == len(topics)
    assert all(data["decision_board"]["basis"] for data in payloads.values())
    assert all(data["decision_board"]["trend"]["rows"] for data in payloads.values())
    assert all(len(data["decision_board"]["anomalies"]) == 5 for data in payloads.values())
    assert all(len(data["decision_board"]["drivers"]) == 5 for data in payloads.values())
    assert all(
        0 <= item["impact_share"] <= 1
        for data in payloads.values()
        for group in ("anomalies", "drivers")
        for item in data["decision_board"][group]
    )
    assert all(
        len({item["finding"] for item in data["ai"]["findings"]}) == len(data["ai"]["findings"])
        for data in payloads.values()
    )


def test_topic_search_and_paging_only_change_details_while_analysis_filters_recalculate_all():
    common = {
        "dataset_id": "demo-all", "start": "2023-09-01", "end": "2025-08-31",
        "page": 1, "page_size": 10,
    }
    with TestClient(app) as client:
        base = client.get("/api/v1/topics/product", params=common).json()["data"]
        product_id = base["details"][0]["product_id"]
        searched = client.get(
            "/api/v1/topics/product", params={**common, "search": product_id, "page_size": 50},
        ).json()["data"]
        filtered = client.get(
            "/api/v1/topics/product", params={**common, "market": "West", "category": "Electronics"},
        ).json()["data"]

    assert searched["metrics"] == base["metrics"]
    assert searched["trend"] == base["trend"]
    assert searched["composition"] == base["composition"]
    assert searched["ranking"] == base["ranking"]
    assert searched["pagination"]["total"] >= 1
    assert all(product_id.lower() in str(row).lower() for row in searched["details"])
    assert filtered["metrics"] != base["metrics"]
    assert filtered["trend"] != base["trend"]
    assert filtered["composition"] != base["composition"]


def test_topic_csv_export_uses_current_filters_and_search():
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/topics/customer/export",
            params={
                "dataset_id": "demo-all", "start": "2023-09-01", "end": "2025-08-31",
                "market": "West", "category": "Electronics", "search": "VIP客户",
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "customer-details.csv" in response.headers["content-disposition"]
    text = response.content.decode("utf-8-sig")
    assert "客户,客户分群,最近购买间隔" in text
    assert "VIP客户" in text


def test_demo_mode_blocks_shared_task_mutation():
    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/work-items/example",
            json={"workflow_status": "IN_PROGRESS", "owner": "运营负责人"},
        )
    assert response.status_code == 403


def test_provider_status_never_returns_secret_fields():
    with TestClient(app) as client:
        payload = client.get("/api/v1/agent/status").json()["data"]
    assert "api_key" not in payload
    assert "token" not in payload


def test_agent_run_starts_inside_async_request_context():
    with TestClient(app) as client:
        session = client.post(
            "/api/v1/agent/sessions",
            json={"dataset_id": "demo-all"},
        ).json()["data"]
        response = client.post(
            f"/api/v1/agent/sessions/{session['session_id']}/runs",
            json={
                "dataset_id": "demo-all",
                "question": "给出当前经营问题、证据与建议",
            },
        )
    assert response.status_code == 200
    assert response.json()["data"]["run_id"].startswith("run_")


def test_agent_session_rejects_cross_dataset_run():
    with TestClient(app) as client:
        session = client.post(
            "/api/v1/agent/sessions",
            json={"dataset_id": "demo-all"},
        ).json()["data"]
        response = client.post(
            f"/api/v1/agent/sessions/{session['session_id']}/runs",
            json={"dataset_id": "demo-west", "question": "分析当前经营情况"},
        )
    assert response.status_code == 400
    assert "数据集" in response.json()["detail"]


def test_agent_answer_contract_uses_business_evidence_without_internal_ids():
    answer = AgentManager._apply_answer_contract(
        "结论：订单量下降。\n\n建议：检查主要市场。",
        {
            "dataset": {"dataset_id": "demo-all", "name": "全量经营演示数据"},
            "period": {"start": "2025-01-01", "end": "2025-01-31"},
            "scope_id": "scope_test",
            "decision_brief": {
                "cases": [{
                    "evidence": [{"metric": "GMV（成交总额）", "source": "SQL 注册指标聚合"}],
                    "limitations": ["缺少广告流量"],
                }],
            },
        },
    )
    assert "数据集：全量经营演示数据（demo-all）" in answer
    assert "周期：2025-01-01 至 2025-01-31" in answer
    assert "业务证据：GMV（成交总额）（SQL 注册指标聚合）" in answer
    assert "限制：缺少广告流量" in answer
    assert "scope_test" not in answer
    assert "ev_test" not in answer


def test_ccswitch_import_keeps_secret_server_side(tmp_path, monkeypatch):
    database = tmp_path / "cc-switch.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE providers (name TEXT, settings_config TEXT, app_type TEXT, is_current INTEGER)"
    )
    secret = "test-secret-must-not-leave-server"
    settings = {
        "config": (
            'model = "test-model"\n'
            'model_provider = "custom"\n'
            '[model_providers.custom]\n'
            'base_url = "https://provider.example/v1"\n'
            'wire_api = "responses"\n'
        ),
        "auth": {"OPENAI_API_KEY": secret},
    }
    connection.execute(
        "INSERT INTO providers VALUES (?, ?, 'codex', 1)",
        ("私有 Provider", json.dumps(settings)),
    )
    connection.commit()
    connection.close()

    monkeypatch.setattr(ProviderStore, "ccswitch_path", staticmethod(lambda: database))
    store = ProviderStore("private")
    payload = store.import_ccswitch()

    assert payload["configured"] is True
    assert payload["source"] == "ccswitch"
    assert store.config is not None and store.config.api_key == secret
    assert "api_key" not in payload
    assert "base_url" not in payload
    assert secret not in json.dumps(payload, ensure_ascii=False)
