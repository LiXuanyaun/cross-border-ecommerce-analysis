from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from crossborder_analytics.multibusiness_analysis import MultiBusinessAnalysisService
from crossborder_analytics.multibusiness_import import MultiBusinessImportService
from crossborder_analytics.service import AnalysisService
from crossborder_api.app_state import runtime
from crossborder_api.main import app


FIXTURE = Path(__file__).parent / "fixtures" / "adventureworks_v4"


@pytest.fixture()
def business_dataset(tmp_path, monkeypatch):
    database = tmp_path / "business.db"
    core = AnalysisService(database_path=database)
    result = MultiBusinessImportService(database, core).import_directory(FIXTURE)
    service = MultiBusinessAnalysisService(database)
    monkeypatch.setattr(runtime.multi_business_presenter, "analysis_service", service)
    return service, result["dataset_id"]


def test_three_planted_scenarios_produce_versioned_rules_and_evidence(business_dataset):
    service, dataset_id = business_dataset
    expected = {
        "advertising": "AD_SPEND_UP_CVR_DOWN",
        "returns": "RETURN_SIZE_RATE_SPIKE",
        "logistics": "LOGISTICS_CUSTOMS_DELAY_SPIKE",
    }

    for topic, rule_id in expected.items():
        payload = service.analyze(topic, dataset_id)
        anomalies = {item["rule_id"]: item for item in payload["anomalies"]}
        assert rule_id in anomalies
        anomaly = anomalies[rule_id]
        assert anomaly["rule_version"] == "1.0.0"
        assert anomaly["threshold"]
        assert anomaly["evidence_ids"]
        assert anomaly["limitations"]
        evidence = {item["evidence_id"]: item for item in payload["evidence"]}
        assert anomaly["evidence_ids"][0] in evidence
        assert evidence[anomaly["evidence_ids"][0]]["formula"]
        assert evidence[anomaly["evidence_ids"][0]]["record_keys"]
        assert payload["data_source"]["is_simulated"] is True
        assert payload["quality"]["status"] == "WARNING"


def test_advertising_metrics_use_usd_and_registered_formulas(business_dataset):
    service, dataset_id = business_dataset
    payload = service.analyze("advertising", dataset_id, country="DE", channel="Search")
    metrics = {item["id"]: item for item in payload["metrics"]}

    assert metrics["ad.spend_usd"]["value"] == pytest.approx(150.0)
    assert metrics["ad.roas"]["value"] == pytest.approx(220 / 150)
    assert metrics["ad.spend_usd"]["currency"] == "USD"
    assert "attributed_revenue_usd" in metrics["ad.roas"]["formula"]
    assert payload["filters"] == {"country": "DE", "channel": "Search"}


def test_business_api_contract_exposes_scope_filters_evidence_and_simulation(business_dataset):
    service, dataset_id = business_dataset
    client = TestClient(app)

    response = client.get(
        "/api/v1/business/returns",
        params={"dataset_id": dataset_id, "country": "Germany", "category": "Clothing"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["meta"]["dataset_id"] == dataset_id
    assert body["meta"]["scope_id"] == body["data"]["scope_id"]
    assert body["data"]["topic"] == "returns"
    assert body["data"]["filter_options"]["category"] == ["Clothing"]
    assert body["data"]["metrics"]
    assert body["data"]["evidence"]
    assert body["data"]["data_source"]["label"] == "模拟数据"
    assert any("模拟数据" in item for item in body["limitations"])


def test_business_api_rejects_unknown_topic(business_dataset):
    _, dataset_id = business_dataset
    response = TestClient(app).get("/api/v1/business/inventory", params={"dataset_id": dataset_id})
    assert response.status_code == 400
