import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from PIL import Image
from pandas.testing import assert_frame_equal
from streamlit.testing.v1 import AppTest

from crossborder_analytics.reporting import _save_charts
from crossborder_analytics.service import AnalysisService
from crossborder_analytics.ui import (
    CHART_FONT_FAMILY,
    PLOTLY_RENDER_CONFIG,
    chart_layout,
    chart_layout_config,
    composition_chart,
)


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "ecommerce_sales_34500.csv"


def test_time_axis_rotation_and_density_rules():
    short = chart_layout_config("time_series", ["2025-{:02d}".format(month) for month in range(1, 13)])
    medium = chart_layout_config("time_series", pd.period_range("2024-01", periods=18, freq="M").astype(str))
    long_labels = pd.period_range("2023-01", periods=36, freq="M").astype(str).tolist()
    long = chart_layout_config("time_series", long_labels)

    assert short["x_tickangle"] == 0
    assert medium["x_tickangle"] == -30
    assert long["x_tickangle"] == -45
    assert len(long["x_tickvals"]) <= 12
    assert long["x_tickvals"][0] == long_labels[0]
    assert long["x_tickvals"][-1] == long_labels[-1]
    assert long["margin"]["b"] > medium["margin"]["b"] > short["margin"]["b"]


def test_long_category_labels_wrap_and_heatmap_keeps_every_category():
    categories = ["跨境家居收纳用品超长分类名称{:02d}".format(index) for index in range(20)]
    markets = ["北美洲重点增长市场{:02d}".format(index) for index in range(8)]
    category = chart_layout_config("category_x", categories)
    heatmap = chart_layout_config("heatmap", categories, markets, item_count=len(markets))

    assert category["x_tickangle"] == -40
    assert len(category["x_tickvals"]) <= 12
    assert any("<br>" in label for label in category["x_ticktext"])
    assert len(heatmap["x_tickvals"]) == len(categories)
    assert len(heatmap["y_tickvals"]) == len(markets)
    assert heatmap["margin"]["l"] >= 88
    assert heatmap["margin"]["r"] >= 78
    assert heatmap["height"] >= 190 + len(markets) * 52


def test_category_y_height_legend_space_and_plotly_axis_contract():
    labels = ["需要完整显示的市场名称{:02d}".format(index) for index in range(12)]
    config = chart_layout_config(
        "category_y",
        y_labels=labels,
        series_names=["核心商品", "引流商品", "潜力商品", "淘汰观察"],
        item_count=len(labels),
    )
    assert config["height"] == 180 + len(labels) * 36
    assert config["legend_rows"] >= 1
    assert config["margin"]["t"] > 72

    figure = go.Figure(go.Bar(x=list(range(len(labels))), y=labels, orientation="h", name="市场"))
    chart_layout(
        figure,
        profile="category_y",
        y_labels=labels,
        series_names=["市场"],
        item_count=len(labels),
    )
    assert figure.layout.autosize is True
    assert figure.layout.xaxis.automargin is True
    assert figure.layout.yaxis.automargin is True
    assert figure.layout.xaxis.ticklabeloverflow == "allow"
    assert figure.layout.yaxis.ticklabeloverflow == "allow"
    assert figure.layout.font.family == CHART_FONT_FAMILY


def test_composition_chart_does_not_mutate_source():
    source = pd.DataFrame([
        {"dimension_value": "非常长的市场名称一", "gmv": 100.0, "gmv_share": .6, "customers": 5, "orders": 8},
        {"dimension_value": "非常长的市场名称二", "gmv": 70.0, "gmv_share": .4, "customers": 4, "orders": 6},
    ])
    before = source.copy(deep=True)
    figure = composition_chart(source, "市场构成", "市场")
    assert_frame_equal(source, before)
    assert figure.layout.height >= 360


def test_streamlit_charts_use_shared_responsive_contract():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not app.exception
    assert app.get("plotly_chart")
    for chart in app.get("plotly_chart"):
        spec = json.loads(chart.proto.spec)
        config = json.loads(chart.proto.config)
        layout = spec["layout"]
        assert layout["autosize"] is True
        assert layout["xaxis"]["automargin"] is True
        assert layout["yaxis"]["automargin"] is True
        assert CHART_FONT_FAMILY in layout["font"]["family"]
        assert config == PLOTLY_RENDER_CONFIG


def test_all_report_charts_render_nonblank_with_safe_canvas(tmp_path):
    service = AnalysisService(cache_dir=tmp_path / "fx", database_path=tmp_path / "charts.db")
    bundle = service.run(service.prepare(SAMPLE, source_currency="CNY", target_currency="CNY"))
    paths = _save_charts(bundle, tmp_path / "charts")
    assert set(paths) == {"sales", "product", "region", "customer"}
    for path in paths.values():
        assert path.exists() and path.stat().st_size > 10_000
        with Image.open(path) as image:
            assert image.width >= 900
            assert image.height >= 500
            extrema = image.convert("RGB").resize((64, 64)).getextrema()
        assert any(low != high for low, high in extrema)

