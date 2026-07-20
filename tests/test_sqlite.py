from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from autoclean.analytics import AnalysisStatus
from crossborder_analytics.service import AnalysisService


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "ecommerce_sales_34500.csv"


def _bundle(backend, tmp_path, filters=None):
    service = AnalysisService(
        cache_dir=tmp_path / "fx",
        database_path=tmp_path / "ecommerce.db",
        backend=backend,
    )
    context = service.prepare(SAMPLE, source_currency="CNY", target_currency="CNY")
    return service.run(context, filters=filters)


def _assert_metrics_equal(actual, expected):
    assert actual.keys() == expected.keys()
    for key, value in expected.items():
        if isinstance(value, float):
            assert actual[key] == pytest.approx(value, rel=1e-10, abs=1e-10)
        else:
            assert actual[key] == value


def test_sql_backend_matches_pandas_business_results(tmp_path):
    pandas_bundle = _bundle("pandas", tmp_path)
    sql_bundle = _bundle("sql", tmp_path)

    _assert_metrics_equal(sql_bundle.results["overview"].data, pandas_bundle.results["overview"].data)
    pd.testing.assert_frame_equal(
        sql_bundle.results["sales"].data["monthly"].reset_index(drop=True),
        pandas_bundle.results["sales"].data["monthly"].reset_index(drop=True),
        check_dtype=False,
        check_exact=False,
        rtol=1e-10,
    )
    assert sql_bundle.results["customer"].data["segments"].set_index("segment")["customers"].to_dict() == (
        pandas_bundle.results["customer"].data["segments"].set_index("segment")["customers"].to_dict()
    )
    assert sql_bundle.results["product"].data["eligible_products"] == (
        pandas_bundle.results["product"].data["eligible_products"]
    )
    assert sql_bundle.results["returns"].data["summary"] == pandas_bundle.results["returns"].data["summary"]
    market_columns = [
        "market", "category", "orders", "units", "customers", "gmv", "profit",
        "returned_orders", "profit_rate", "return_rate", "order_share", "gmv_share",
    ]
    sql_market = sql_bundle.results["market_category"].data[market_columns].sort_values(["market", "category"]).reset_index(drop=True)
    pandas_market = pandas_bundle.results["market_category"].data[market_columns].sort_values(["market", "category"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(sql_market, pandas_market, check_dtype=False, check_exact=False, rtol=1e-10)
    pd.testing.assert_frame_equal(
        sql_bundle.results["customer"].data["composition"].sort_values(["segment", "dimension_type", "dimension_value"]).reset_index(drop=True),
        pandas_bundle.results["customer"].data["composition"].sort_values(["segment", "dimension_type", "dimension_value"]).reset_index(drop=True),
        check_dtype=False,
        check_exact=False,
        rtol=1e-10,
    )
    assert {item["name"] for item in sql_bundle.metadata["query_runs"]} >= {
        "overview", "monthly_sales", "product_analysis", "customer_rfm_base",
        "market_analysis", "return_analysis",
        "market_category_analysis",
    }


def test_sql_product_detail_matches_pandas(tmp_path):
    sql_service = AnalysisService(cache_dir=tmp_path / "sql-fx", database_path=tmp_path / "details.db", backend="sql")
    pandas_service = AnalysisService(cache_dir=tmp_path / "pandas-fx", database_path=None, backend="pandas")
    sql_bundle = sql_service.run(sql_service.prepare(SAMPLE, source_currency="CNY", target_currency="CNY"))
    pandas_bundle = pandas_service.run(pandas_service.prepare(SAMPLE, source_currency="CNY", target_currency="CNY"))
    product_id = str(sql_bundle.results["product"].data["products"].iloc[0].product_id)
    sql_detail = sql_service.product_detail(sql_bundle, product_id)
    pandas_detail = pandas_service.product_detail(pandas_bundle, product_id)
    for name, sort_columns in (("monthly", ["month"]), ("market_mix", ["market"]), ("customer_mix", ["segment"])):
        actual = sql_detail[name].sort_values(sort_columns).reset_index(drop=True)
        expected = pandas_detail[name].sort_values(sort_columns).reset_index(drop=True)
        common = [column for column in actual.columns if column in expected.columns]
        pd.testing.assert_frame_equal(
            actual[common], expected[common], check_dtype=False, check_exact=False, rtol=1e-10
        )


def test_sql_filters_match_pandas_and_versions_are_idempotent(tmp_path):
    filters = {
        "order_date": ("2025-01-01", "2025-06-30"),
        "region": ["West"],
        "category": ["Beauty", "Home"],
    }
    pandas_bundle = _bundle("pandas", tmp_path, filters=filters)
    sql_bundle = _bundle("sql", tmp_path, filters=filters)
    _assert_metrics_equal(sql_bundle.results["overview"].data, pandas_bundle.results["overview"].data)

    repeated = _bundle("sql", tmp_path, filters=filters)
    assert repeated.metadata["dataset_id"] == sql_bundle.metadata["dataset_id"]
    assert repeated.context.metadata["storage_reused"] is True
    with sqlite3.connect(tmp_path / "ecommerce.db") as connection:
        datasets = connection.execute("SELECT COUNT(*) FROM autoclean_datasets").fetchone()[0]
        rows = connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    assert datasets == 1
    assert rows == 34500


def test_fatal_grain_conflict_never_persists_orders(tmp_path):
    source = tmp_path / "duplicate.csv"
    source.write_text(
        "order_id,order_date,total_amount\nA1,2025-01-01,10\nA1,2025-01-02,20\n",
        encoding="utf-8",
    )
    database = tmp_path / "ecommerce.db"
    service = AnalysisService(cache_dir=tmp_path / "fx", database_path=database)
    bundle = service.run(service.prepare(source, source_currency="CNY", target_currency="CNY"))
    assert bundle.results["dataset"].status == AnalysisStatus.FATAL
    assert not database.exists()


def test_database_initialization_failure_is_explicit_fatal(tmp_path):
    service = AnalysisService(cache_dir=tmp_path / "fx", database_path=tmp_path)
    context = service.prepare(SAMPLE, source_currency="CNY", target_currency="CNY")
    bundle = service.run(context)
    assert bundle.results["dataset"].status == AnalysisStatus.FATAL
    assert "Database initialization failed" in bundle.results["dataset"].message


def test_empty_sql_filter_returns_zero_overview_instead_of_failing(tmp_path):
    bundle = _bundle("sql", tmp_path, filters={"region": ["不存在的区域"]})
    result = bundle.results["overview"]
    assert result.status == AnalysisStatus.SUCCESS
    assert result.data["orders"] == 0
    assert result.data["gmv"] == 0
    assert result.data["returned_orders"] == 0
