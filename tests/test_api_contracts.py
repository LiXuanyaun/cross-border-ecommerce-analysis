import json

import pytest
from fastapi.testclient import TestClient

from crossborder_api.main import app, runtime


CONTRACT_PARAMS = {"dataset_id": "demo-all", "start": "2023-09-01", "end": "2025-08-31"}


def _data(response):
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"status", "data", "meta", "limitations"}
    assert payload["status"] == "SUCCESS"
    assert isinstance(payload["limitations"], list)
    return payload["data"], payload["meta"]


def test_overview_response_contract_locks_metrics_scope_and_evidence():
    with TestClient(app) as client:
        data, meta = _data(client.get("/api/v1/overview", params=CONTRACT_PARAMS))

    assert meta["dataset_id"] == "demo-all"
    assert meta["scope_id"] == "scope_21af142e36633be9331cf48a"
    assert meta["quality_rating"] == "A"
    assert set(data) == {
        "period", "selection_period", "current_period", "comparison_period",
        "market_comparison_period", "currency", "kpis", "trend", "trends",
        "tasks", "markets", "categories", "opportunities", "insights", "methodology",
        "data_state", "available_periods", "recommended_period", "requested_period",
    }
    assert data["current_period"] == {"start": "2025-08-01", "end": "2025-08-31", "type": "month"}
    assert data["comparison_period"] == {"start": "2025-07-01", "end": "2025-07-31", "type": "month"}

    kpis = {item["id"]: item for item in data["kpis"]}
    assert list(kpis) == ["gmv", "profit_rate", "orders", "aov"]
    expected = {
        "gmv": ("gmv", 243808.5, 249593.5, "currency"),
        "profit_rate": ("profit_margin", 0.170042, 0.171919, "percent"),
        "orders": ("orders", 1498.0, 1471.0, "integer"),
        "aov": ("aov", 162.756008, 169.676071, "currency"),
    }
    for public_id, (metric_id, value, previous, value_format) in expected.items():
        item = kpis[public_id]
        assert set(item) == {
            "id", "label", "value", "previous_value", "format", "change", "tone",
            "sparkline", "basis", "threshold", "metric_id", "metric_version", "evidence_id",
        }
        assert item["metric_id"] == metric_id
        assert item["value"] == pytest.approx(value)
        assert item["previous_value"] == pytest.approx(previous)
        assert item["format"] == value_format
        assert item["metric_version"] == "1.0.0"
        assert item["evidence_id"] == "ev_2d6fc924f071b5530b099b22"
        assert len(item["sparkline"]) <= 8

    assert set(data["trends"]) == {"day", "week"}
    assert len(data["trends"]["day"]["rows"]) == 31
    assert len(data["trends"]["week"]["rows"]) == 5
    assert set(data["tasks"][0]) >= {
        "id", "insight_id", "metric_id", "rule_id", "evidence", "diagnosis", "recommendation",
        "current_period", "comparison_period", "status", "owner", "deadline",
    }
    assert data["tasks"][0]["evidence"]["ids"] == ["ev_2d6fc924f071b5530b099b22"]
    assert data["insights"][0]["rule_id"].startswith("ANOM-")
    assert data["insights"][0]["evidence"]["ids"] == ["ev_2d6fc924f071b5530b099b22"]


def test_topic_response_contract_locks_market_payload_and_pagination():
    with TestClient(app) as client:
        data, meta = _data(client.get(
            "/api/v1/topics/market",
            params={**CONTRACT_PARAMS, "page": 1, "page_size": 5},
        ))

    assert meta["dataset_id"] == "demo-all"
    assert meta["scope_id"] == "scope_21af142e36633be9331cf48a"
    assert set(data) == {
        "topic", "summary", "metrics", "trend", "composition", "ranking", "columns",
        "details", "pagination", "filters", "decision_board", "ai", "report",
        "data_state", "available_periods", "recommended_period", "requested_period",
        "visualizations", "table",
    }
    assert data["topic"] == "market"
    assert data["pagination"] == {"page": 1, "page_size": 5, "total": 5, "pages": 1}
    assert [item["id"] for item in data["metrics"]] == [
        "market_gmv", "market_count", "top_market_share", "delivery_mean",
    ]
    assert data["metrics"][0]["value"] == pytest.approx(5773444.88)
    assert data["metrics"][0]["change"] == pytest.approx(-0.02317768691893018)
    assert set(data["trend"]) == {"title", "format", "rows", "secondary_label", "secondary_format"}
    assert set(data["composition"]) == {"title", "format", "rows"}
    assert set(data["ranking"]) == {"title", "format", "secondary_format", "rows"}
    assert [column["key"] for column in data["columns"]] == [
        "name", "gmv", "orders", "customers", "profit_rate", "return_rate", "delivery_p90", "strategy",
    ]
    assert set(data["details"][0]) >= {
        "market", "name", "gmv", "orders", "customers", "profit_rate", "return_rate",
        "strategy", "strategy_confidence", "strategy_evidence_id",
    }
    anomaly = data["decision_board"]["anomalies"][0]
    assert anomaly["metric_id"] == "gmv"
    assert anomaly["rule_id"] == "ANOM-GMV-DROP"
    assert anomaly["evidence_ids"] == ["ev_2d6fc924f071b5530b099b22"]
    assert set(data["ai"]) == {"findings", "evidence", "actions"}
    assert data["ai"]["actions"][0]["evidence_ids"] == ["ev_2d6fc924f071b5530b099b22"]
    topic_evidence = data["ai"]["evidence"][0]
    assert set(topic_evidence) == {
        "contract_version", "id", "metric", "value", "unit", "claim", "formula",
        "sample_size", "confidence", "source_fields", "period", "filters",
        "quality_state", "limitations",
    }
    assert topic_evidence["contract_version"] == "topic-evidence.v1"
    assert not {"query_name", "database_schema_version", "result_digest"} & set(topic_evidence)
    assert data["report"]["summary"] == data["summary"]


def test_analysis_routes_require_explicit_dataset_identity():
    with TestClient(app) as client:
        assert client.get("/api/v1/overview").status_code == 422
        assert client.get("/api/v1/topics/market").status_code == 422
        assert client.get("/api/v1/topics/market/export").status_code == 422


def test_agent_context_contract_uses_same_scope_and_registered_tools():
    context, bundle = runtime.agent_context(
        "demo-all", "请解释当前经营问题并给出建议", "2023-09-01", "2025-08-31",
    )

    assert context["scope_id"] == bundle.metadata["scope_id"] == "scope_21af142e36633be9331cf48a"
    assert context["dataset"] == {"dataset_id": "demo-all", "name": "全量经营演示数据"}
    assert context["filters"] == {"start": "2023-09-01", "end": "2025-08-31", "market": None, "category": None}
    assert set(context) == {
        "question", "dataset", "period", "filters", "scope_id", "tools", "agent_plan",
        "overview", "quality", "insights", "evidence", "recommendations",
        "decision_brief", "trace", "tool_observations",
    }
    assert context["tools"] == [
        "get_dataset_profile", "get_data_quality", "query_metrics", "get_metric", "compare_periods",
        "list_anomalies", "get_diagnosis", "get_evidence", "create_task", "get_recommendations",
        "generate_report", "generate_review_report", "explain_limitation",
    ]
    assert [step["step_id"] for step in context["agent_plan"]] == [
        "plan-1", "plan-2", "plan-3", "plan-4", "plan-5",
    ]
    assert all(step["status"] == "COMPLETED" for step in context["agent_plan"])
    assert context["decision_brief"]["status"] == "SUCCESS"
    assert len(context["decision_brief"]["cases"]) >= 1
    assert context["trace"][0] == {
        "insight_id": "ins_903cccbd8765a24ee2d705fe",
        "anomaly_id": "anom_46ec2ebd7dffbed00117c615",
        "rule_id": "ANOM-GMV-DROP",
        "rule_version": "1.0.0",
        "metric_id": "gmv",
        "evidence_ids": ["ev_2d6fc924f071b5530b099b22"],
    }
    first_observation = context["tool_observations"][0]
    assert first_observation["tool"] == "get_dataset_profile"
    assert first_observation["status"] == "SUCCESS"
    assert first_observation["payload"]["scope_id"] == context["scope_id"]


def test_import_preview_response_contract_preserves_mapping_and_capability_fields():
    content = (
        "订单号,下单日期,订单金额,国家,商品ID\n"
        "A1,2025-01-01,10,US,P1\n"
        "A2,2025-01-02,20,US,P2\n"
    ).encode("utf-8-sig")

    with TestClient(app) as client:
        data, meta = _data(client.post(
            "/api/v1/imports/preview",
            files=[("files", ("orders.csv", content, "text/csv"))],
        ))

    assert meta["app_mode"] == "demo"
    assert set(data) == {
        "status", "file_count", "total_rows", "files", "batch_issues", "next_step",
        "preview_id", "expires_at",
    }
    assert data["status"] == "READY_FOR_MAPPING_CONFIRMATION"
    assert data["file_count"] == 1
    assert data["total_rows"] == 2
    assert data["batch_issues"] == []
    assert data["preview_id"].startswith("preview_")
    preview = data["files"][0]
    assert set(preview) == {
        "filename", "source_file_id", "status", "metadata", "sheets", "selected_sheet",
        "columns", "field_mappings", "issues", "capabilities",
    }
    assert preview["filename"] == "orders.csv"
    assert preview["source_file_id"] == "src_da4569b39c01"
    assert preview["status"] == "READY_FOR_CONFIRMATION"
    assert preview["metadata"]["rows"] == 2
    assert preview["metadata"]["column_names"] == ["订单号", "下单日期", "订单金额", "国家", "商品ID"]
    mappings = {item["standard_field"]: item for item in preview["field_mappings"]}
    assert mappings["order_id"]["source_field"] == "订单号"
    assert mappings["order_date"]["source_field"] == "下单日期"
    assert mappings["total_amount"]["source_field"] == "订单金额"
    assert mappings["order_id"]["sample_values"] == ["A1", "A2"]
    assert mappings["order_id"]["status"] == "MAPPED"
    assert mappings["customer_id"]["status"] == "UNMAPPED"
    capabilities = {item["id"]: item["status"] for item in preview["capabilities"]}
    assert capabilities == {
        "overview": "FULL", "market": "FULL", "product": "FULL",
        "customer": "DISABLED", "profit": "DISABLED", "returns": "DISABLED",
    }


def test_import_preview_accepts_more_than_twenty_valid_files():
    files = [
        (
            "files",
            (
                f"orders-{index}.csv",
                f"order_id,order_date,total_amount\nA{index},2025-01-01,{index + 1}\n".encode(),
                "text/csv",
            ),
        )
        for index in range(21)
    ]

    with TestClient(app) as client:
        response = client.post("/api/v1/imports/preview", files=files)

    assert response.status_code == 200
    assert response.json()["data"]["file_count"] == 21


def test_agent_session_requires_explicit_dataset_identity():
    with TestClient(app) as client:
        response = client.post("/api/v1/agent/sessions", json={})

    assert response.status_code == 422


def test_committed_import_response_contract_uses_dataset_scope_and_lineage(tmp_path, monkeypatch):
    database_path = tmp_path / "contract-import.db"
    monkeypatch.setattr(runtime._service, "database_path", database_path)
    runtime.clear_analysis_cache()
    content = (
        "订单号,下单日期,订单金额,国家\n"
        "A1,2025-01-01,10,US\n"
        "A2,2025-01-02,20,US\n"
    ).encode("utf-8-sig")
    form = {
        "mapping_json": json.dumps({
            "order_id": "订单号", "order_date": "下单日期",
            "total_amount": "订单金额", "country": "国家",
        }),
        "dataset_name": "契约导入",
        "data_grain": "order",
        "amount_semantic": "order_total",
        "source_currency": "CNY",
        "target_currency": "CNY",
    }

    with TestClient(app) as client:
        data, meta = _data(client.post(
            "/api/v1/imports", data=form,
            files={"file": ("orders.csv", content, "text/csv")},
        ))
        overview, overview_meta = _data(client.get("/api/v1/overview", params={"dataset_id": data["dataset_id"]}))

    assert meta["app_mode"] == "demo"
    assert set(data) == {
        "status", "dataset_id", "source_file_id", "source_file_ids", "reused", "row_count", "issues",
    }
    assert data["status"] == "READY"
    assert data["row_count"] == 2
    assert data["source_file_id"].startswith("src_")
    assert data["source_file_ids"] == [data["source_file_id"]]
    assert data["issues"] == []
    assert overview_meta["dataset_id"] == data["dataset_id"]
    assert overview_meta["scope_id"].startswith("scope_")
    assert overview_meta["quality_rating"] in {"A", "B", "C", "D"}
    assert overview["kpis"][0]["metric_id"] == "gmv"


def test_commit_reuses_staged_preview_without_reupload(tmp_path, monkeypatch):
    database_path = tmp_path / "staged-import.db"
    monkeypatch.setattr(runtime._service, "database_path", database_path)
    runtime.clear_analysis_cache()
    content = (
        "order_id,order_date,total_amount,country\n"
        "A1,2025-01-01,10,US\n"
        "A2,2025-01-02,20,US\n"
    ).encode()

    with TestClient(app) as client:
        preview = _data(client.post(
            "/api/v1/imports/preview",
            files={"files": ("orders.csv", content, "text/csv")},
        ))[0]
        response = client.post("/api/v1/imports", data={
            "preview_id": preview["preview_id"],
            "mapping_json": json.dumps({
                "order_id": "order_id", "order_date": "order_date",
                "total_amount": "total_amount", "country": "country",
            }),
            "dataset_name": "暂存引用导入",
            "data_grain": "order",
            "amount_semantic": "order_total",
            "source_currency": "CNY",
            "target_currency": "CNY",
        })

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "READY"
