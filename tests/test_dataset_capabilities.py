import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient

from crossborder_api.dataset_capabilities import DatasetCapabilityService
from crossborder_api.main import app


class DatasetServiceStub:
    def __init__(self, database_path):
        self.database_path = database_path

    @staticmethod
    def scenario(dataset_id):
        if dataset_id != "dynamic-dataset":
            raise KeyError(dataset_id)
        return SimpleNamespace(is_demo=False)

    @staticmethod
    def context_for(_dataset_id):
        raise AssertionError("persisted orders should not load the dataframe context")


def _create_database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE orders (
                dataset_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                order_date TEXT NOT NULL,
                gmv_amount_base REAL,
                quantity REAL,
                product_id TEXT,
                customer_id TEXT,
                country TEXT
            );
            CREATE INDEX idx_test_orders_date ON orders(dataset_id, order_date);
            CREATE TABLE fact_ad_performance_daily (
                dataset_id TEXT NOT NULL,
                ad_date TEXT NOT NULL,
                campaign_id TEXT,
                spend_usd REAL,
                data_origin TEXT
            );
            CREATE INDEX idx_test_ads_date ON fact_ad_performance_daily(dataset_id, ad_date);
            """
        )


def _insert_orders(path, dates):
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("dynamic-dataset", "row-{}".format(index), value, 10.0, 1, "p", "c", "JP")
                for index, value in enumerate(dates)
            ],
        )


def test_orders_capability_splits_eras_and_recommends_latest_complete_month(tmp_path):
    database = tmp_path / "capabilities.db"
    _create_database(database)
    _insert_orders(database, [
        "2010-01-01", "2010-01-31",
        "2023-06-01", "2023-06-30",
        "2030-02-01", "2030-02-28", "2030-03-01", "2030-03-10",
    ])
    service = DatasetCapabilityService(DatasetServiceStub(database))

    result = service.discover("dynamic-dataset", fact="orders")
    capability = result["facts"]["orders"]

    assert result["contract_version"] == "1.0.0"
    assert [(item["start"], item["end"]) for item in capability["available_periods"]] == [
        ("2010-01-01", "2010-01-31"),
        ("2023-06-01", "2023-06-30"),
        ("2030-02-01", "2030-03-10"),
    ]
    assert capability["recommended_period"] == {"start": "2030-02-01", "end": "2030-02-28"}
    assert capability["state"] == "READY"


def test_requested_range_distinguishes_out_of_range_empty_and_incomplete(tmp_path):
    database = tmp_path / "states.db"
    _create_database(database)
    _insert_orders(database, ["2030-02-01", "2030-02-28", "2030-03-01", "2030-03-10"])
    service = DatasetCapabilityService(DatasetServiceStub(database))

    out_of_range = service.discover(
        "dynamic-dataset", fact="orders", start="2025-01-01", end="2025-01-31",
    )["facts"]["orders"]
    empty = service.discover(
        "dynamic-dataset", fact="orders", start="2030-02-10", end="2030-02-11",
    )["facts"]["orders"]
    incomplete = service.discover(
        "dynamic-dataset", fact="orders", start="2030-03-01", end="2030-03-31",
    )["facts"]["orders"]

    assert (out_of_range["state"], out_of_range["row_count"]) == ("OUT_OF_RANGE", 0)
    assert (empty["state"], empty["row_count"]) == ("EMPTY", 0)
    assert incomplete["state"] == "INCOMPLETE_PERIOD"
    assert incomplete["row_count"] == 2
    assert any("不完整月份" in item for item in incomplete["limitations"])


def test_advertising_recommendation_uses_latest_twelve_month_window(tmp_path):
    database = tmp_path / "advertising.db"
    _create_database(database)
    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO fact_ad_performance_daily VALUES (?, ?, ?, ?, ?)",
            [
                ("dynamic-dataset", value, "campaign", 10.0, "synthetic_extension")
                for value in (
                    "2010-12-29", "2013-02-01", "2013-03-01", "2013-04-01", "2013-05-01",
                    "2013-06-01", "2013-07-01", "2013-08-01", "2013-09-01", "2013-10-01",
                    "2013-11-01", "2013-12-01", "2014-01-01", "2014-01-28",
                )
            ],
        )
    service = DatasetCapabilityService(DatasetServiceStub(database))

    capability = service.discover("dynamic-dataset", fact="advertising")["facts"]["advertising"]

    assert capability["recommended_period"] == {"start": "2013-02-01", "end": "2014-01-28"}
    assert capability["simulation_state"] == "SIMULATED"


def test_capability_endpoint_returns_typed_contract_for_demo_dataset():
    with TestClient(app) as client:
        response = client.get("/api/v1/datasets/demo-all/capabilities", params={"fact": "orders"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["dataset_id"] == "demo-all"
    assert body["data"]["facts"]["orders"]["available_periods"]
    assert body["data"]["facts"]["orders"]["recommended_period"]


def test_capability_endpoint_rejects_partial_or_invalid_ranges():
    with TestClient(app) as client:
        partial = client.get(
            "/api/v1/datasets/demo-all/capabilities", params={"fact": "orders", "start": "2030-01-01"},
        )
        invalid = client.get(
            "/api/v1/datasets/demo-all/capabilities",
            params={"fact": "orders", "start": "2030-02-01", "end": "2030-01-01"},
        )

    assert partial.status_code == 400
    assert invalid.status_code == 400


def test_regular_topic_out_of_range_returns_formal_empty_contract():
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/topics/market",
            params={"dataset_id": "demo-all", "start": "2030-01-01", "end": "2030-12-31"},
        )

    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert data["data_state"] == "OUT_OF_RANGE"
    assert body["meta"]["scope_id"] == data["scope_id"]
    assert data["metrics"] == []
    assert data["trend"]["rows"] == []
    assert data["ranking"]["rows"] == []
    assert data["details"] == []
    assert data["available_periods"]
    assert len(data["visualizations"]) == 3
    assert all(item["rows"] == [] for item in data["visualizations"])
    assert data["table"]["rows"] == []
    assert data["table"]["pagination"] == data["pagination"]


def test_regular_topic_presentation_contract_matches_authoritative_payload():
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/topics/market",
            params={"dataset_id": "demo-all", "start": "2025-08-01", "end": "2025-08-31", "page_size": 5},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    contracts = {item["id"].rsplit("_", 1)[-1]: item for item in data["visualizations"]}
    assert contracts["trend"]["rows"] == data["trend"]["rows"]
    assert contracts["composition"]["rows"] == data["composition"]["rows"]
    assert contracts["ranking"]["rows"] == data["ranking"]["rows"]
    assert data["table"]["rows"] == data["details"]
    assert data["table"]["pagination"] == data["pagination"]
    assert [item["field"] for item in data["table"]["columns"]] == [item["key"] for item in data["columns"]]


def test_capability_cache_clear_rediscovers_persisted_periods(tmp_path):
    database = tmp_path / "cache-invalidation.db"
    _create_database(database)
    _insert_orders(database, ["2023-06-01", "2023-06-30"])
    service = DatasetCapabilityService(DatasetServiceStub(database))

    first = service.discover("dynamic-dataset", fact="orders")["facts"]["orders"]
    _insert_orders(database, ["2030-02-01", "2030-02-28"])
    cached = service.discover("dynamic-dataset", fact="orders")["facts"]["orders"]
    service.clear_cache()
    refreshed = service.discover("dynamic-dataset", fact="orders")["facts"]["orders"]

    assert cached["available_periods"] == first["available_periods"]
    assert refreshed["recommended_period"] == {"start": "2030-02-01", "end": "2030-02-28"}
    assert len(refreshed["available_periods"]) == 2


def test_overview_out_of_range_returns_formal_empty_contract():
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/overview",
            params={"dataset_id": "demo-all", "start": "2030-01-01", "end": "2030-12-31"},
        )

    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert data["data_state"] == "OUT_OF_RANGE"
    assert body["meta"]["scope_id"] == data["scope_id"]
    assert data["kpis"] == []
    assert data["trends"]["day"]["rows"] == []
    assert data["tasks"] == []
    assert data["available_periods"]
