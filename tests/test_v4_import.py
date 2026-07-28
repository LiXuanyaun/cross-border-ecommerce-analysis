from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from crossborder_analytics.adventureworks import AdventureWorksAdapter
from crossborder_analytics.multibusiness_import import (
    FILE_TYPES,
    MultiBusinessImportService,
    classify_business_file,
    preview_business_payload,
)
from crossborder_analytics.service import AnalysisService


FIXTURE = Path(__file__).parent / "fixtures" / "adventureworks_v4"


@pytest.fixture()
def importer(tmp_path):
    database = tmp_path / "v4.db"
    analysis = AnalysisService(database_path=database)
    return MultiBusinessImportService(database, analysis), database


def test_adventureworks_adapter_converts_headerless_pipe_sources_to_order_lines():
    result = AdventureWorksAdapter().load_orders(FIXTURE)
    row = result.loaded.data.iloc[0]

    assert row.record_id == "aw:SO1:1"
    assert row.order_id == "SO1"
    assert row.sales_order_number == "SO1"
    assert row.sales_order_line_number == 1
    assert row.category == "Clothing"
    assert row.country == "Germany"
    assert row.currency == "USD"
    assert row.total_amount == pytest.approx(20.0)
    assert row.cost_amount == pytest.approx(10.0)
    assert row.profit_amount == pytest.approx(10.0)
    assert row.source_product_key == "1"
    assert row.source_customer_key == "1"
    assert len(result.source_files) == 9


def test_business_file_preview_identifies_type_grain_fields_and_simulation_label():
    path = FIXTURE / "fact_returns.csv"
    preview = preview_business_payload(path.name, path.read_bytes())

    assert preview["file_type"] == "returns"
    assert preview["table"] == "fact_returns"
    assert preview["grain"] == "one row per returned order line"
    assert preview["business_key"] == ["return_id"]
    assert preview["is_simulated"] is True
    assert "refund_amount" in preview["columns"]
    assert preview["field_preview"][0]["sales_order_number"] == "SO1"
    assert classify_business_file("FactInternetSales.csv")["grain"] == "one row per order line"


def test_eight_business_tables_import_with_foreign_keys_and_reimport_is_idempotent(importer):
    service, database = importer
    first = service.import_directory(FIXTURE)
    second = service.import_directory(FIXTURE)

    assert first["status"] == "READY"
    assert first["order_row_count"] == 1
    assert first["inserted_rows"] == 10
    assert set(first["association_rates"].values()) == {1.0}
    assert second["status"] == "READY"
    assert second["reused"] is True
    assert second["inserted_rows"] == 0
    assert second["duplicate_rows"] == 10

    with sqlite3.connect(database) as connection:
        counts = {
            spec.table: connection.execute("SELECT COUNT(*) FROM {}".format(spec.table)).fetchone()[0]
            for spec in FILE_TYPES.values()
        }
        assert counts == {
            "dim_campaign": 1,
            "dim_carrier": 1,
            "dim_return_reason": 1,
            "fact_ad_performance_daily": 1,
            "bridge_order_attribution": 1,
            "fact_returns": 1,
            "fact_shipments": 1,
            "fact_tracking_events": 3,
        }
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT data_origin, scenario_id, generator_version FROM fact_returns"
        ).fetchone() == ("synthetic_extension", "SCN_RET_CLOTHING_SIZE_SPIKE", "1.0.0")


def test_validation_blocks_currency_amount_return_and_tracking_violations(importer):
    service, _ = importer
    orders = AdventureWorksAdapter().load_orders(FIXTURE).loaded.data
    frames = {name: pd.read_csv(FIXTURE / name) for name in FILE_TYPES}
    frames["fact_ad_performance_daily.csv"].loc[0, "clicks"] = 1001
    frames["fact_ad_performance_daily.csv"].loc[0, "billing_currency"] = "EUR"
    frames["fact_returns.csv"].loc[0, "return_quantity"] = 3
    frames["fact_returns.csv"].loc[0, "refund_amount"] = 21
    frames["fact_tracking_events.csv"].loc[1, "event_timestamp"] = frames["fact_tracking_events.csv"].loc[0, "event_timestamp"]

    codes = {item["code"] for item in service._validate(orders, frames)["issues"]}
    assert {
        "CLICKS_EXCEED_IMPRESSIONS",
        "AD_CURRENCY_NOT_USD",
        "RETURN_QUANTITY_EXCEEDED",
        "REFUND_AMOUNT_EXCEEDED",
        "TRACKING_TIME_NOT_STRICT",
    } <= codes
