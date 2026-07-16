import pandas as pd
from pandas.testing import assert_frame_equal

from crossborder_analytics.localization import (
    currency_label,
    label_for,
    localize_formula,
    localize_frame,
    raw_value,
    value_for,
)


def test_labels_values_and_unknown_fallback():
    assert label_for("gmv") == "GMV（成交总额）"
    assert currency_label("CNY") == "CNY（人民币）"
    assert value_for("Electronics", "category") == "电子产品"
    assert value_for("East", "region") == "东部"
    assert value_for("SUCCESS", "status") == "成功"
    assert label_for("future_metric") == "future_metric"
    assert value_for("Moon", "region") == "Moon"


def test_localized_value_round_trip():
    for field, raw in (("category", "Beauty"), ("region", "West"), ("currency", "USD"), ("status", "SKIPPED")):
        assert raw_value(value_for(raw, field), field) == raw


def test_localize_frame_is_immutable_and_translates_content():
    source = pd.DataFrame([{
        "month": "2025-08",
        "category": "Fashion",
        "region": "East",
        "profit_rate": 0.2,
        "status": "SUCCESS",
        "formula": "利润额 / GMV",
        "source_fields": "profit_amount, total_amount",
    }])
    before = source.copy(deep=True)
    localized = localize_frame(source)
    assert_frame_equal(source, before)
    assert list(localized.columns) == ["月份", "品类", "区域", "利润率", "状态", "计算口径", "数据字段"]
    assert localized.loc[0, "品类"] == "服饰"
    assert localized.loc[0, "区域"] == "东部"
    assert localized.loc[0, "状态"] == "成功"
    assert localized.loc[0, "数据字段"] == "利润额、订单金额"
    assert localize_formula("利润额 / GMV") == "利润率 = 利润额 / GMV（成交总额）"
