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


def _customer_chart_data(app):
    spec = json.loads(app.get("plotly_chart")[0].proto.spec)
    return [(trace.get("name"), trace.get("x"), trace.get("y")) for trace in spec["data"]]


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
