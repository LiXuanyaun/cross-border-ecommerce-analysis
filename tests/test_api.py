import json
import sqlite3
from types import SimpleNamespace
from io import BytesIO

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from crossborder_api.agent import AgentManager, ProviderStore
from crossborder_api.main import app, runtime


def test_bootstrap_exposes_primary_pages_without_implicit_dataset():
    with TestClient(app) as client:
        response = client.get("/api/v1/app/bootstrap")
    assert response.status_code == 200
    labels = [item["label"] for item in response.json()["data"]["navigation"]]
    assert labels == ["经营总览", "专题分析", "多业务分析", "数据中心", "AI分析师"]
    data = response.json()["data"]
    assert data["default_dataset_id"] is None
    assert data["period_source"] == "AUTO"
    assert data["capability_contract_version"] == "1.0.0"
    assert data["recommended_period"]["start"] >= data["date_bounds"]["start"]
    assert data["recommended_period"]["end"] <= data["date_bounds"]["end"]


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


def test_overview_topic_report_and_agent_share_one_scope_id():
    params = {"dataset_id": "demo-all", "start": "2023-09-01", "end": "2025-08-31"}
    with TestClient(app) as client:
        overview = client.get("/api/v1/overview", params=params)
        topic = client.get("/api/v1/topics/market", params={**params, "page_size": 5})
        report = client.get("/api/v1/reports/demo-all/manifest", params={k: v for k, v in params.items() if k != "dataset_id"})

    agent_context, bundle = runtime.agent_context(
        "demo-all", "请解释当前经营问题并给出建议", params["start"], params["end"],
    )
    overview_scope = overview.json()["meta"]["scope_id"]
    topic_scope = topic.json()["meta"]["scope_id"]
    assert report.status_code == 200
    report_scope = json.loads(report.content.decode("utf-8-sig"))["scope_id"]

    assert overview_scope == topic_scope == report_scope == agent_context["scope_id"] == bundle.metadata["scope_id"]


def test_report_export_rejects_mismatched_scope_id():
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/reports/demo-all/manifest",
            params={"start": "2023-09-01", "end": "2025-08-31", "scope_id": "scope_wrong"},
        )

    assert response.status_code == 409
    assert "scope_id" in response.json()["detail"]


def test_datahub_detail_exposes_catalogs_capacity_and_fx_lineage():
    with TestClient(app) as client:
        response = client.get("/api/v1/datasets/demo-all")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["metric_catalog"]
    assert data["rule_catalog"]
    assert data["capacity"]["database_bytes"] >= 0
    assert "metric_snapshots" in data["capacity"]["record_counts"]
    assert data["capacity"]["cleanup_recommendations"]
    assert data["fx_lineage"]["target_currency"] == "CNY"
    assert data["import_history"]


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


def test_unified_overview_uses_active_market_dimension_and_quality_scope():
    unified_id = next(
        item["dataset_id"] for item in runtime.datasets()
        if item["dataset_id"].startswith("unified-")
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/overview",
            params={
                "dataset_id": unified_id,
                "start": "2024-06-01",
                "end": "2025-08-31",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    data = payload["data"]
    assert len(data["markets"]) == 5
    assert data["markets"][0]["name"]
    assert data["markets"][0]["name"] != "未标注国家"
    assert data["tasks"]
    assert data["insights"]
    assert payload["meta"]["quality_rating"] in {"A", "B"}


def test_overview_falls_back_when_sales_result_is_missing(monkeypatch):
    actual_bundle = runtime.bundle(
        "demo-all", "2023-09-01", "2025-08-31",
    )
    fake_bundle = SimpleNamespace(
        artifacts=actual_bundle.artifacts,
        context=actual_bundle.context,
        generated_at=actual_bundle.generated_at,
        metadata=actual_bundle.metadata,
        results={
            name: result
            for name, result in actual_bundle.results.items()
            if name != "sales"
        },
    )
    monkeypatch.setattr(runtime, "bundle", lambda *args, **kwargs: fake_bundle)

    data, bundle = runtime.overview(
        "demo-all", "2023-09-01", "2025-08-31",
    )

    assert bundle is fake_bundle
    assert "sales" not in bundle.results
    assert len(data["trend"]) == 12
    assert {"month", "gmv", "orders"} <= set(data["trend"][0])


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
    assert all(data["ai"]["findings"] for data in payloads.values())
    assert all(data["report"]["summary"] == data["summary"] for data in payloads.values())
    assert len({data["decision_board"]["trend"]["title"] for data in payloads.values()}) == len(topics)
    assert all(data["decision_board"]["basis"] for data in payloads.values())
    assert all(data["decision_board"]["trend"]["rows"] for data in payloads.values())
    assert all(
        item["metric_id"] and item["metric_version"] and item["rule_id"]
        and item["rule_version"] and item["evidence_ids"]
        for data in payloads.values()
        for item in data["decision_board"]["anomalies"]
    )
    assert all(
        item["metric_id"] and item["rule_id"] and item["evidence_ids"]
        for topic, data in payloads.items()
        if topic != "customer"
        for item in data["ai"]["actions"]
    )
    assert all(
        item["metric_id"] and item["rule_id"] is None and item["evidence_ids"]
        for item in payloads["customer"]["ai"]["actions"]
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


def test_import_preview_maps_csv_fields_without_persisting_dataset():
    content = (
        "订单号,下单日期,订单金额,国家,商品ID\n"
        "A1,2025-01-01,10,US,P1\n"
        "A2,2025-01-02,20,US,P2\n"
    ).encode("utf-8-sig")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/imports/preview",
            files=[("files", ("orders.csv", content, "text/csv"))],
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "READY_FOR_MAPPING_CONFIRMATION"
    assert data["file_count"] == 1
    assert data["total_rows"] == 2
    file_preview = data["files"][0]
    assert file_preview["status"] == "READY_FOR_CONFIRMATION"
    assert file_preview["metadata"]["encoding"]
    mappings = {item["standard_field"]: item for item in file_preview["field_mappings"]}
    assert mappings["order_id"]["source_field"] == "订单号"
    assert mappings["order_date"]["source_field"] == "下单日期"
    assert mappings["total_amount"]["source_field"] == "订单金额"
    assert mappings["order_id"]["confidence"] >= 0.85
    assert any(item["id"] == "market" and item["status"] == "FULL" for item in file_preview["capabilities"])


def test_every_uploaded_file_uses_autoclean_preview_contract():
    content = (
        "return_id,sales_order_number,sales_order_line_number,return_quantity,original_order_quantity,refund_amount,original_line_sales_amount\n"
        "R1,SO1,1,1,1,10,10\n"
    ).encode("utf-8")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/imports/preview",
            files=[("files", ("fact_returns.csv", content, "text/csv"))],
        )

    assert response.status_code == 200
    file_preview = response.json()["data"]["files"][0]
    assert file_preview["status"] == "BLOCKED"
    assert file_preview["metadata"]["rows"] == 1
    assert "field_mappings" in file_preview
    assert any(issue["code"] == "MISSING_REQUIRED_FIELD" for issue in file_preview["issues"])


def test_import_preview_reads_xlsx_sheet_names():
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        pd.DataFrame([
            {"order_id": "A1", "order_date": "2025-01-01", "total_amount": 10},
        ]).to_excel(writer, index=False, sheet_name="Orders")
        pd.DataFrame([{"note": "ignored"}]).to_excel(writer, index=False, sheet_name="Notes")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/imports/preview",
            files=[("files", ("orders.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        )

    assert response.status_code == 200
    file_preview = response.json()["data"]["files"][0]
    assert file_preview["sheets"] == ["Orders", "Notes"]
    assert file_preview["selected_sheet"] == "Orders"
    assert file_preview["status"] == "READY_FOR_CONFIRMATION"


def test_import_preview_accepts_heterogeneous_files_for_individual_autoclean():
    first = "order_id,order_date,total_amount\nA1,2025-01-01,10\n".encode("utf-8")
    second = "order_id,order_date,total_amount,country\nA2,2025-01-02,20,US\n".encode("utf-8")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/imports/preview",
            files=[
                ("files", ("jan.csv", first, "text/csv")),
                ("files", ("feb.csv", second, "text/csv")),
            ],
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "READY_FOR_MAPPING_CONFIRMATION"
    assert all(item["status"] == "READY_FOR_CONFIRMATION" for item in data["files"])
    assert not any(issue["code"] == "FIELD_SET_MISMATCH" for issue in data["batch_issues"])


def test_mixed_batch_persists_qualified_files_and_reports_failed_files(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime._service, "database_path", tmp_path / "partial-import.db")
    runtime.bundle.cache_clear()
    valid = b"order_id,order_date,total_amount\nA1,2025-01-01,10\n"
    invalid = b"note,value\nignore,1\n"
    mapping = json.dumps({"order_id": "order_id", "order_date": "order_date", "total_amount": "total_amount"})
    with TestClient(app) as client:
        preview = client.post(
            "/api/v1/imports/preview",
            files=[("files", ("valid.csv", valid, "text/csv")), ("files", ("invalid.csv", invalid, "text/csv"))],
        )
        preview_data = preview.json()["data"]
        committed = client.post(
            "/api/v1/imports",
            data={
                "preview_id": preview_data["preview_id"], "mapping_json": mapping,
                "dataset_name": "部分合格批次", "data_grain": "order",
                "amount_semantic": "order_total", "source_currency": "CNY", "target_currency": "CNY",
            },
        )

    assert preview.status_code == 200
    assert preview_data["status"] == "READY_FOR_MAPPING_CONFIRMATION"
    assert committed.status_code == 200
    result = committed.json()["data"]
    assert result["status"] == "READY"
    assert result["row_count"] == 1
    assert len(result["failed_files"]) == 1
    assert result["failed_files"][0]["filename"] == "invalid.csv"


def test_import_preview_requires_grain_confirmation_for_cross_file_duplicate_order_ids():
    first = "order_id,order_date,total_amount\nA1,2025-01-01,10\n".encode("utf-8")
    second = "order_id,order_date,total_amount\nA1,2025-01-02,20\n".encode("utf-8")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/imports/preview",
            files=[
                ("files", ("jan.csv", first, "text/csv")),
                ("files", ("feb.csv", second, "text/csv")),
            ],
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "READY_FOR_MAPPING_CONFIRMATION"
    issue = next(issue for issue in data["batch_issues"] if issue["code"] == "CROSS_FILE_DUPLICATE_ORDER_ID")
    assert issue["severity"] == "WARNING"


def test_confirmed_single_file_import_is_persisted_and_idempotent(tmp_path, monkeypatch):
    database_path = tmp_path / "import.db"
    monkeypatch.setattr(runtime._service, "database_path", database_path)
    runtime.bundle.cache_clear()
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
        "dataset_name": "一月订单",
        "data_grain": "order",
        "amount_semantic": "order_total",
        "source_currency": "CNY",
        "target_currency": "CNY",
    }
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/imports", data=form,
            files={"file": ("orders.csv", content, "text/csv")},
        )
        second = client.post(
            "/api/v1/imports", data=form,
            files={"file": ("orders.csv", content, "text/csv")},
        )
        datasets_response = client.get("/api/v1/datasets")
        imported_id = first.json()["data"]["dataset_id"]
        detail_response = client.get("/api/v1/datasets/{}".format(imported_id))
        overview_response = client.get("/api/v1/overview", params={"dataset_id": imported_id})

    assert first.status_code == 200
    first_data = first.json()["data"]
    second_data = second.json()["data"]
    assert first_data["status"] == "READY"
    assert first_data["row_count"] == 2
    assert second_data["dataset_id"] == first_data["dataset_id"]
    assert second_data["reused"] is True
    assert any(
        item["dataset_id"] == first_data["dataset_id"] and item["name"] == "一月订单"
        for item in datasets_response.json()["data"]
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["dataset"]["is_demo"] is False
    assert overview_response.status_code == 200
    assert overview_response.json()["meta"]["dataset_id"] == first_data["dataset_id"]

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT source_file_id, source_row_number FROM orders WHERE dataset_id = ? ORDER BY source_row_number",
            (first_data["dataset_id"],),
        ).fetchall()
        dataset_count = connection.execute(
            "SELECT COUNT(*) FROM autoclean_datasets WHERE dataset_id = ?",
            (first_data["dataset_id"],),
        ).fetchone()[0]
    assert rows == [(first_data["source_file_id"], 2), (first_data["source_file_id"], 3)]
    assert dataset_count == 1


def test_single_month_topic_trends_use_daily_buckets_without_fake_comparison(tmp_path, monkeypatch):
    database_path = tmp_path / "single-month-topic.db"
    monkeypatch.setattr(runtime._service, "database_path", database_path)
    runtime.bundle.cache_clear()
    content = (
        "order_id,order_date,total_amount,country,product_id,product_name,quantity,customer_id,category\n"
        "A1,2025-08-01,10,US,P1,Widget,1,C1,Tools\n"
        "A2,2025-08-02,20,US,P1,Widget,2,C2,Tools\n"
        "A3,2025-08-03,30,CA,P2,Gadget,1,C3,Home\n"
    ).encode("utf-8-sig")
    form = {
        "mapping_json": json.dumps({
            "order_id": "order_id", "order_date": "order_date", "total_amount": "total_amount",
            "country": "country", "product_id": "product_id", "product_name": "product_name",
            "quantity": "quantity", "customer_id": "customer_id", "category": "category",
        }),
        "dataset_name": "单月专题趋势",
        "data_grain": "order",
        "amount_semantic": "order_total",
        "source_currency": "CNY",
        "target_currency": "CNY",
    }
    with TestClient(app) as client:
        imported = client.post(
            "/api/v1/imports", data=form,
            files={"file": ("august.csv", content, "text/csv")},
        )
        dataset_id = imported.json()["data"]["dataset_id"]
        market = client.get("/api/v1/topics/market", params={"dataset_id": dataset_id})
        product = client.get("/api/v1/topics/product", params={"dataset_id": dataset_id})

    assert imported.status_code == 200
    assert imported.json()["data"]["status"] == "READY"
    for response in (market, product):
        assert response.status_code == 200
        trend = response.json()["data"]["decision_board"]["trend"]
        assert trend["grain"] == "day"
        assert len(trend["rows"]) == 3
        assert trend["comparison_period"] == {"start": None, "end": None}
        assert all(row["comparison"] is None for row in trend["rows"])


def test_follow_up_import_appends_as_versioned_dataset(tmp_path, monkeypatch):
    database_path = tmp_path / "append.db"
    monkeypatch.setattr(runtime._service, "database_path", database_path)
    runtime.bundle.cache_clear()
    mapping = json.dumps({
        "order_id": "order_id", "order_date": "order_date",
        "total_amount": "total_amount", "country": "country",
    })
    form = {
        "mapping_json": mapping,
        "dataset_name": "持续订单",
        "data_grain": "order",
        "amount_semantic": "order_total",
        "source_currency": "CNY",
        "target_currency": "CNY",
    }
    first_content = b"order_id,order_date,total_amount,country\nA1,2025-01-01,10,US\nA2,2025-01-02,20,US\n"
    second_content = b"order_id,order_date,total_amount,country\nA3,2025-02-01,30,US\nA4,2025-02-02,40,US\n"
    with TestClient(app) as client:
        first = client.post("/api/v1/imports", data=form, files={"file": ("jan.csv", first_content, "text/csv")})
        first_id = first.json()["data"]["dataset_id"]
        appended = client.post(
            "/api/v1/imports",
            data={**form, "target_dataset_id": first_id},
            files={"file": ("feb.csv", second_content, "text/csv")},
        )
        new_data = appended.json()["data"]
        detail = client.get("/api/v1/datasets/{}".format(new_data["dataset_id"])).json()["data"]
        catalog = client.get("/api/v1/datasets").json()["data"]

    assert first.status_code == 200
    assert appended.status_code == 200
    assert new_data["status"] == "READY"
    assert new_data["merged"] is True
    assert new_data["parent_dataset_id"] == first_id
    assert new_data["dataset_id"] != first_id
    assert new_data["previous_row_count"] == 2
    assert new_data["appended_row_count"] == 2
    assert new_data["row_count"] == 4
    assert detail["lineage"]["parent_dataset_id"] == first_id
    assert detail["dataset"]["row_count"] == 4
    assert first_id in {item["dataset_id"] for item in catalog}
    assert new_data["dataset_id"] in {item["dataset_id"] for item in catalog}


def test_follow_up_import_blocks_duplicate_order_without_partial_write(tmp_path, monkeypatch):
    database_path = tmp_path / "append-conflict.db"
    monkeypatch.setattr(runtime._service, "database_path", database_path)
    runtime.bundle.cache_clear()
    mapping = json.dumps({
        "order_id": "order_id", "order_date": "order_date",
        "total_amount": "total_amount", "country": "country",
    })
    form = {
        "mapping_json": mapping,
        "dataset_name": "重复订单",
        "data_grain": "order",
        "amount_semantic": "order_total",
        "source_currency": "CNY",
        "target_currency": "CNY",
    }
    content = b"order_id,order_date,total_amount,country\nA1,2025-01-01,10,US\n"
    with TestClient(app) as client:
        first = client.post("/api/v1/imports", data=form, files={"file": ("jan.csv", content, "text/csv")}).json()["data"]
        blocked = client.post(
            "/api/v1/imports",
            data={**form, "target_dataset_id": first["dataset_id"]},
            files={"file": ("correction.csv", content.replace(b"10", b"99"), "text/csv")},
        )

    result = blocked.json()["data"]
    assert blocked.status_code == 200
    assert result["status"] == "BLOCKED"
    assert any(issue["code"] == "GRAIN_CONFLICT" for issue in result["issues"])
    with sqlite3.connect(database_path) as connection:
        row_count = connection.execute("SELECT COUNT(*) FROM orders WHERE dataset_id = ?", (first["dataset_id"],)).fetchone()[0]
    assert row_count == 1


def test_imported_dataset_can_be_archived_without_deleting_orders(tmp_path, monkeypatch):
    database_path = tmp_path / "archive.db"
    monkeypatch.setattr(runtime._service, "database_path", database_path)
    runtime.bundle.cache_clear()
    content = (
        "order_id,order_date,total_amount,country\n"
        "A1,2025-01-01,10,US\n"
        "A2,2025-01-02,20,US\n"
    ).encode("utf-8")
    form = {
        "mapping_json": json.dumps({
            "order_id": "order_id", "order_date": "order_date",
            "total_amount": "total_amount", "country": "country",
        }),
        "dataset_name": "归档测试",
        "data_grain": "order",
        "amount_semantic": "order_total",
        "source_currency": "CNY",
        "target_currency": "CNY",
    }
    with TestClient(app) as client:
        imported = client.post(
            "/api/v1/imports", data=form,
            files={"file": ("orders.csv", content, "text/csv")},
        ).json()["data"]
        archive_response = client.post("/api/v1/datasets/{}/archive".format(imported["dataset_id"]))
        datasets_response = client.get("/api/v1/datasets")
        detail_response = client.get("/api/v1/datasets/{}".format(imported["dataset_id"]))

    assert archive_response.status_code == 200
    assert archive_response.json()["data"]["status"] == "ARCHIVED"
    assert imported["dataset_id"] not in {
        item["dataset_id"] for item in datasets_response.json()["data"]
    }
    assert detail_response.status_code == 404
    with sqlite3.connect(database_path) as connection:
        status, order_count = connection.execute(
            "SELECT d.status, COUNT(o.record_id) FROM autoclean_datasets d "
            "JOIN orders o ON o.dataset_id = d.dataset_id WHERE d.dataset_id = ?",
            (imported["dataset_id"],),
        ).fetchone()
    assert status == "ARCHIVED"
    assert order_count == 2


def test_confirmed_import_blocks_before_writing_when_contract_is_invalid(tmp_path, monkeypatch):
    database_path = tmp_path / "blocked.db"
    monkeypatch.setattr(runtime._service, "database_path", database_path)
    runtime.bundle.cache_clear()
    content = "order_id,total_amount\nA1,10\n".encode("utf-8")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/imports",
            data={
                "mapping_json": json.dumps({"order_id": "order_id", "total_amount": "total_amount"}),
                "dataset_name": "缺日期数据",
                "data_grain": "order",
                "amount_semantic": "order_total",
                "source_currency": "CNY",
                "target_currency": "CNY",
            },
            files={"file": ("invalid.csv", content, "text/csv")},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "BLOCKED"
    assert data["dataset_id"] is None
    assert any(issue["severity"] == "FATAL" for issue in data["issues"])
    with sqlite3.connect(database_path) as connection:
        table_names = {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        dataset_count = (
            connection.execute("SELECT COUNT(*) FROM autoclean_datasets").fetchone()[0]
            if "autoclean_datasets" in table_names else 0
        )
    assert dataset_count == 0
    assert "orders" not in table_names


def test_confirmed_xlsx_import_uses_selected_sheet(tmp_path, monkeypatch):
    database_path = tmp_path / "sheet.db"
    monkeypatch.setattr(runtime._service, "database_path", database_path)
    runtime.bundle.cache_clear()
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        pd.DataFrame([{"note": "ignore"}]).to_excel(writer, index=False, sheet_name="Notes")
        pd.DataFrame([
            {"order_id": "A1", "order_date": "2025-02-01", "total_amount": 30},
        ]).to_excel(writer, index=False, sheet_name="Orders")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/imports",
            data={
                "mapping_json": json.dumps({
                    "order_id": "order_id", "order_date": "order_date", "total_amount": "total_amount",
                }),
                "dataset_name": "二月订单",
                "selected_sheet": "Orders",
                "data_grain": "order",
                "amount_semantic": "order_total",
                "source_currency": "CNY",
                "target_currency": "CNY",
            },
            files={"file": ("orders.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "READY"
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT order_id, source_row_number FROM orders WHERE dataset_id = ?",
            (data["dataset_id"],),
        ).fetchone()
    assert row == ("A1", 2)


def test_multi_file_order_import_commits_once_with_file_lineage(tmp_path, monkeypatch):
    database_path = tmp_path / "multi.db"
    monkeypatch.setattr(runtime._service, "database_path", database_path)
    runtime.bundle.cache_clear()
    first = "order_id,order_date,total_amount\nA1,2025-01-01,10\n".encode("utf-8")
    second = "order_id,order_date,total_amount\nA2,2025-01-02,20\n".encode("utf-8")
    form = {
        "mapping_json": json.dumps({
            "order_id": "order_id", "order_date": "order_date", "total_amount": "total_amount",
        }),
        "dataset_name": "一月合并订单",
        "data_grain": "order",
        "amount_semantic": "order_total",
        "source_currency": "CNY",
        "target_currency": "CNY",
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/imports", data=form,
            files=[
                ("files", ("jan-1.csv", first, "text/csv")),
                ("files", ("jan-2.csv", second, "text/csv")),
            ],
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "READY"
    assert data["row_count"] == 2
    assert len(data["source_file_ids"]) == 2
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT order_id, source_file_id, source_row_number FROM orders WHERE dataset_id = ? ORDER BY order_id",
            (data["dataset_id"],),
        ).fetchall()
        dataset_count = connection.execute("SELECT COUNT(*) FROM autoclean_datasets").fetchone()[0]
    assert [row[0] for row in rows] == ["A1", "A2"]
    assert {row[1] for row in rows} == set(data["source_file_ids"])
    assert [row[2] for row in rows] == [2, 2]
    assert dataset_count == 1


def test_multi_file_field_drift_is_cleaned_into_one_dataset(tmp_path, monkeypatch):
    database_path = tmp_path / "multi-cleaned.db"
    monkeypatch.setattr(runtime._service, "database_path", database_path)
    runtime.bundle.cache_clear()
    first = "order_id,order_date,total_amount\nA1,2025-01-01,10\n".encode("utf-8")
    second = "order_id,order_date,total_amount,country\nA2,2025-01-02,20,US\n".encode("utf-8")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/imports",
            data={
                "mapping_json": json.dumps({
                    "order_id": "order_id", "order_date": "order_date", "total_amount": "total_amount",
                }),
                "dataset_name": "结构不一致",
                "data_grain": "order",
                "amount_semantic": "order_total",
                "source_currency": "CNY",
                "target_currency": "CNY",
            },
            files=[
                ("files", ("jan.csv", first, "text/csv")),
                ("files", ("feb.csv", second, "text/csv")),
            ],
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "READY"
    assert data["row_count"] == 2
    assert not any(issue["code"] == "FIELD_SET_MISMATCH" for issue in data["issues"])
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM orders WHERE dataset_id = ?", (data["dataset_id"],)
        ).fetchone()[0] == 2


def test_order_item_line_amount_counts_unique_orders_and_sums_lines(tmp_path, monkeypatch):
    database_path = tmp_path / "item-lines.db"
    monkeypatch.setattr(runtime._service, "database_path", database_path)
    runtime.bundle.cache_clear()
    content = (
        "order_id,order_date,total_amount,product_id,quantity\n"
        "A1,2025-01-01,10,P1,1\n"
        "A1,2025-01-01,20,P2,2\n"
        "A2,2025-01-02,30,P1,1\n"
    ).encode("utf-8")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/imports",
            data={
                "mapping_json": json.dumps({
                    "order_id": "order_id", "order_date": "order_date", "total_amount": "total_amount",
                    "product_id": "product_id", "quantity": "quantity",
                }),
                "dataset_name": "商品行金额",
                "data_grain": "order_item",
                "amount_semantic": "line_amount",
                "source_currency": "CNY",
                "target_currency": "CNY",
            },
            files={"file": ("items.csv", content, "text/csv")},
        )

    data = response.json()["data"]
    assert data["status"] == "READY"
    with sqlite3.connect(database_path) as connection:
        gmv, orders, records = connection.execute(
            "SELECT SUM(gmv_amount_base), COUNT(DISTINCT order_id), COUNT(*) FROM orders WHERE dataset_id = ?",
            (data["dataset_id"],),
        ).fetchone()
    assert (gmv, orders, records) == (60.0, 2, 3)


def test_order_item_repeated_order_total_is_deduplicated(tmp_path, monkeypatch):
    database_path = tmp_path / "item-total.db"
    monkeypatch.setattr(runtime._service, "database_path", database_path)
    runtime.bundle.cache_clear()
    content = (
        "order_id,order_date,total_amount,product_id\n"
        "A1,2025-01-01,100,P1\n"
        "A1,2025-01-01,100,P2\n"
    ).encode("utf-8")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/imports",
            data={
                "mapping_json": json.dumps({
                    "order_id": "order_id", "order_date": "order_date", "total_amount": "total_amount",
                    "product_id": "product_id",
                }),
                "dataset_name": "订单总额商品行",
                "data_grain": "order_item",
                "amount_semantic": "order_total",
                "source_currency": "CNY",
                "target_currency": "CNY",
            },
            files={"file": ("items.csv", content, "text/csv")},
        )

    data = response.json()["data"]
    assert data["status"] == "READY"
    with sqlite3.connect(database_path) as connection:
        gmv, orders = connection.execute(
            "SELECT SUM(gmv_amount_base), COUNT(DISTINCT order_id) FROM orders WHERE dataset_id = ?",
            (data["dataset_id"],),
        ).fetchone()
    assert (gmv, orders) == (100.0, 1)


def test_demo_mode_blocks_shared_task_mutation():
    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/work-items/example",
            json={"workflow_status": "IN_PROGRESS", "owner": "运营负责人", "deadline": "2025-05-31"},
        )
    assert response.status_code == 403


def test_work_item_in_progress_requires_deadline():
    from crossborder_api.task_lifecycle import normalize_work_item_patch

    with pytest.raises(ValueError, match="截止日期"):
        normalize_work_item_patch({"workflow_status": "IN_PROGRESS", "owner": "运营负责人"})


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
