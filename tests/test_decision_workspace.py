from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

from crossborder_analytics.decision import (
    apply_market_strategy,
    build_market_category_metrics,
    market_series,
    resolve_market_field,
)
from crossborder_analytics.service import AnalysisService


def _orders():
    return pd.DataFrame([
        {"order_id": "A1", "order_date": pd.Timestamp("2025-01-01"), "country": "US", "region": "North", "category": "Beauty", "product_id": "P1", "customer_id": "C1", "quantity": 1, "total_amount": 100.0, "profit_amount": 20.0, "returned": False},
        {"order_id": "A2", "order_date": pd.Timestamp("2025-01-02"), "country": None, "region": "West", "category": "Beauty", "product_id": "P1", "customer_id": "C2", "quantity": 2, "total_amount": 200.0, "profit_amount": 20.0, "returned": True},
        {"order_id": "A3", "order_date": pd.Timestamp("2025-01-03"), "country": "US", "region": "South", "category": "New Category", "product_id": "P2", "customer_id": "C1", "quantity": 1, "total_amount": 50.0, "profit_amount": -5.0, "returned": False},
    ])


def test_country_is_one_dataset_grain_and_partial_missing_is_labeled():
    frame = _orders()
    assert resolve_market_field(frame) == "region"
    assert market_series(frame).tolist() == ["North", "West", "South"]
    country_preferred = frame.assign(region=["North", None, None])
    assert resolve_market_field(country_preferred) == "country"
    assert market_series(country_preferred).tolist() == ["US", "未标注国家", "US"]
    blank_country = frame.assign(country="  ")
    assert resolve_market_field(blank_country) == "region"


def test_dynamic_market_categories_share_and_source_are_immutable():
    frame = _orders()
    before = frame.copy(deep=True)
    result = build_market_category_metrics(frame)
    assert_frame_equal(frame, before)
    assert set(result["category"]) == {"Beauty", "New Category"}
    assert result.groupby("market")["order_share"].sum().round(12).eq(1).all()
    assert result.groupby("market")["gmv_share"].sum().round(12).eq(1).all()


def test_market_strategy_rules_and_missing_evidence():
    missing = apply_market_strategy(pd.DataFrame([{"region": "A", "gmv": 10, "orders": 1}]))
    assert missing.iloc[0].strategy == "证据不足"
    negative = apply_market_strategy(pd.DataFrame([{"region": "A", "gmv": 10, "orders": 1, "profit": -1, "profit_rate": -.1}]))
    assert negative.iloc[0].strategy == "谨慎评估"

    risk = apply_market_strategy(pd.DataFrame([
        {"region": "A", "gmv": 100, "orders": 10, "profit": 20, "profit_rate": .2, "return_rate": .20},
        {"region": "B", "gmv": 100, "orders": 10, "profit": 20, "profit_rate": .2, "return_rate": .01},
    ]))
    assert risk.set_index("region").loc["A", "strategy"] == "先优化效率"

    scale = apply_market_strategy(pd.DataFrame([
        {"region": "A", "gmv": 80, "orders": 8, "profit": 16, "profit_rate": .2},
        {"region": "B", "gmv": 20, "orders": 2, "profit": 2, "profit_rate": .1},
    ]))
    assert scale.set_index("region").loc["A", "strategy"] == "优先评估投入"

    increment = apply_market_strategy(pd.DataFrame([
        {"region": "A", "gmv": 80, "orders": 8, "profit": 8, "profit_rate": .1},
        {"region": "B", "gmv": 20, "orders": 2, "profit": 4, "profit_rate": .2},
    ]))
    strategies = increment.set_index("region")["strategy"]
    assert strategies.loc["B"] == "小规模增量测试"
    assert strategies.loc["A"] == "改善利润后再扩量"
    assert increment.strategy_confidence.eq("LOW").all()


def test_product_category_conflict_and_parameterized_detail(tmp_path):
    source = tmp_path / "products.csv"
    source.write_text(
        "order_id,order_date,total_amount,profit_amount,product_id,product_name,category,quantity,customer_id,region,returned\n"
        "A1,2025-01-01,100,20,P1,One,Beauty,1,C1,West,false\n"
        "A2,2025-02-01,120,10,P1,One,Beauty,1,C2,West,false\n"
        "A3,2025-03-01,80,-5,P1,One,Home,1,C1,East,true\n",
        encoding="utf-8",
    )
    service = AnalysisService(cache_dir=tmp_path / "fx", database_path=tmp_path / "analysis.db")
    bundle = service.run(service.prepare(source, source_currency="CNY", target_currency="CNY"))
    product = bundle.results["product"].data["products"].iloc[0]
    assert product.primary_category == "Beauty"
    assert product.category_count == 2
    assert bool(product.category_conflict) is True

    detail = service.product_detail(bundle, "P1")
    assert detail["summary"]["product_id"] == "P1"
    assert detail["periods"] == 3
    assert detail["trend_available"] is False
    assert {run["name"] for run in detail["query_runs"]} == {
        "product_detail_summary", "product_detail_monthly",
        "product_detail_market", "product_detail_customers",
    }
