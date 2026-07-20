import json
from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_default_view_renders_metrics_chart_and_navigation():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    assert not app.exception
    assert any(metric.label == "GMV（成交总额）" for metric in app.metric)
    assert any(metric.label == "订单" for metric in app.metric)
    assert len(app.get("plotly_chart")) >= 1
    assert len(app.radio) == 1
    assert app.radio[0].label == "页面"
    assert not any(pills.label in {"区域", "品类"} for pills in app.pills)


def _customer_chart_data(app):
    spec = json.loads(app.get("plotly_chart")[0].proto.spec)
    return [(trace.get("name"), trace.get("x"), trace.get("y")) for trace in spec["data"]]


def _assert_shared_chart_layout(app):
    for chart in app.get("plotly_chart"):
        spec = json.loads(chart.proto.spec)
        config = json.loads(chart.proto.config)
        assert spec["layout"]["autosize"] is True
        assert spec["layout"]["xaxis"]["automargin"] is True
        assert spec["layout"]["yaxis"]["automargin"] is True
        assert config["responsive"] is True


def test_streamlit_customer_view_filters_detail_without_changing_chart():
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    app = AppTest.from_file(app_path, default_timeout=60).run()
    app.radio[0].set_value("客户分析").run()

    assert not app.exception
    assert not any(toggle.label == "启用自定义分群规则" for toggle in app.toggle)
    assert not any("VIP最近购买" in slider.label for slider in app.slider)
    selector = app.segmented_control(key="customer_detail_segment")
    assert selector.options == ["全部客户", "VIP客户", "高价值客户", "流失风险客户", "普通客户"]
    assert selector.value == "全部客户"
    _assert_shared_chart_layout(app)
    chart_data = _customer_chart_data(app)

    expected = {
        "VIP客户": 1196,
        "高价值客户": 1012,
        "流失风险客户": 1954,
        "普通客户": 3741,
    }
    for segment, count in expected.items():
        app.segmented_control(key="customer_detail_segment").set_value(segment).run()
        assert not app.exception
        assert any("{:,} 位{}".format(count, segment) in caption.value for caption in app.caption)
        assert _customer_chart_data(app) == chart_data
        assert app.download_button[0].label == "下载当前客户清单（{:,}人）".format(count)

    app.segmented_control(key="customer_detail_segment").set_value("VIP客户").run()
    app.text_input(key="customer_analysis_search").set_value("C16655").run()
    assert app.download_button[0].label == "下载当前客户清单（1人）"


def test_market_and_product_pages_have_local_decision_controls():
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    app = AppTest.from_file(app_path, default_timeout=60).run()
    app.radio[0].set_value("区域市场").run()
    assert not app.exception
    _assert_shared_chart_layout(app)
    assert app.segmented_control(key="market_heatmap_mode").options == ["订单偏好", "收益贡献"]
    assert any(button.label.startswith("下载当前市场清单") for button in app.download_button)

    app.radio[0].set_value("商品分析").run()
    assert not app.exception
    _assert_shared_chart_layout(app)
    assert app.segmented_control(key="product_detail_classification").options[0] == "全部商品"
    assert any(button.label.startswith("下载当前商品清单") for button in app.download_button)

    app.radio[0].set_value("市场增长").run()
    assert not app.exception
    assert any(metric.label == "健康增长市场" for metric in app.metric)
    assert any(item.label == "市场状态" for item in app.multiselect)
    assert any(button.label.startswith("下载当前市场行动清单") for button in app.download_button)

    app.radio[0].set_value("产品机会").run()
    assert not app.exception
    assert app.segmented_control(key="product_opportunity_matrix").options == [
        "增长率 × 利润率", "市场覆盖 × 市场增长贡献", "GMV规模 × 退货风险",
    ]
    assert any(item.label == "机会类型" for item in app.multiselect)
    assert any(button.label.startswith("下载当前产品机会清单") for button in app.download_button)


def test_phase2_risk_insight_and_health_workspaces_render_from_shared_artifacts():
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    app = AppTest.from_file(app_path, default_timeout=60).run()

    app.radio[0].set_value("风险中心").run()
    assert not app.exception
    assert any(metric.label == "数据可信度" for metric in app.metric)
    assert {item.label for item in app.multiselect} >= {"优先级", "分析状态", "任务状态", "对象类型"}
    assert len(app.get("plotly_chart")) >= 1
    assert any(button.label.startswith("下载当前筛选") for button in app.download_button)
    assert any(button.label.startswith("下载全部记录") for button in app.download_button)
    assert any(select.label == "选择风险任务" for select in app.selectbox)
    assert any(button.label == "保存处理进度" for button in app.button)

    app.radio[0].set_value("洞察中心").run()
    assert not app.exception
    assert any(select.label == "选择经营问题" for select in app.selectbox)
    assert any(metric.label == "证据支持度" for metric in app.metric)
    assert any("经营结论" in item.value for item in app.markdown)
    assert any(expander.label.startswith("完整洞察清单（") for expander in app.expander)
    assert len(app.expander) >= 3
    assert len(app.table) >= 1
    assert any(button.label.startswith("下载全部洞察") for button in app.download_button)

    app.radio[0].set_value("数据健康中心").run()
    assert not app.exception
    assert any(metric.label == "质量评分" for metric in app.metric)
    assert any(metric.label == "可用能力" for metric in app.metric)
    assert len(app.get("plotly_chart")) >= 1
