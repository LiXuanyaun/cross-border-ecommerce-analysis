"""CrossBorder AI Analytics Streamlit entrypoint."""
from pathlib import Path
from io import BytesIO

import pandas as pd
import plotly.express as px
import streamlit as st

from autoclean.analytics import DatasetContext, load_tabular
from crossborder_analytics.localization import (
    currency_label,
    localize_formula,
    localize_source_fields,
    value_for,
)
from crossborder_analytics.reporting import export_bundle
from crossborder_analytics.rfm import SEGMENT_ORDER
from crossborder_analytics.service import AnalysisService
from crossborder_analytics.ui import (
    COLORS, chart_layout, contribution_chart, customer_detail_frame, evidence_rail, inject_theme,
    localized_grid, money, monthly_chart, page_header, pct, result_or_notice,
    status_strip,
)


ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT / "data" / "ecommerce_sales_34500.csv"
CURRENCIES = ["CNY", "USD", "EUR", "GBP", "JPY", "HKD", "AUD", "CAD", "CHF", "INR", "BRL"]

st.set_page_config(page_title="CrossBorder AI Analytics", page_icon=":material/analytics:", layout="wide", initial_sidebar_state="auto")
inject_theme()


@st.cache_data(show_spinner=False)
def read_columns(payload: bytes, filename: str):
    loaded = load_tabular(payload, filename=filename)
    return loaded.data.columns.tolist(), loaded.metadata


@st.cache_data(show_spinner=False)
def prepare_cached(payload, filename, mapping_items, source_currency, target_currency, fx_payload):
    service = AnalysisService(cache_dir=ROOT / ".cache" / "fx")
    fx_rates = pd.read_csv(BytesIO(fx_payload)) if fx_payload else None
    return service.prepare(
        payload,
        filename=filename,
        mapping=dict(mapping_items),
        source_currency=source_currency,
        target_currency=target_currency,
        fx_rates=fx_rates,
    )


def _context_cache_key(context):
    return "{}:{}:{}:{}".format(
        context.metadata.get("sha256"),
        context.metadata.get("source_currency"),
        context.metadata.get("target_currency"),
        sorted(context.field_mapping.items()),
    )


@st.cache_data(show_spinner=False, hash_funcs={DatasetContext: _context_cache_key})
def run_cached(context, date_range, regions, categories):
    filters = {"order_date": date_range}
    if regions:
        filters["region"] = list(regions)
    if categories:
        filters["category"] = list(categories)
    return AnalysisService(cache_dir=ROOT / ".cache" / "fx").run(context, filters=filters)


def load_source():
    st.sidebar.markdown("### 数据")
    uploaded = st.sidebar.file_uploader("订单数据", type=["csv", "xlsx"], help="一行一订单；原始文件不会被修改")
    st.sidebar.caption("单个文件最大 200 MB · 支持 CSV/XLSX")
    use_sample = st.sidebar.toggle("使用内置示例", value=uploaded is None)
    if uploaded is not None:
        return uploaded.getvalue(), uploaded.name
    if use_sample:
        return SAMPLE, SAMPLE.name
    return None, None


source, filename = load_source()
source_currency = st.sidebar.selectbox(
    "源币种", CURRENCIES, index=0, format_func=currency_label,
    help="数据没有币种字段时，该币种将应用于整张表",
)
target_currency = st.sidebar.selectbox("基准币种", CURRENCIES, index=0, format_func=currency_label)
fx_upload = st.sidebar.file_uploader("汇率表（可选）", type=["csv"], help="date, source_currency, target_currency, rate")
st.sidebar.caption("单个文件最大 200 MB · 仅支持 CSV；字段为日期、源币种、目标币种、汇率")

if source is None:
    page_header("数据准备", "上传订单文件或载入内置示例")
    st.info("请选择数据文件。")
    st.stop()

mapping = None
if not isinstance(source, Path):
    columns, source_meta = read_columns(source, filename)
    with st.sidebar.expander("字段映射"):
        order_id = st.selectbox("订单ID", columns, index=columns.index("order_id") if "order_id" in columns else 0)
        order_date = st.selectbox("订单日期", columns, index=columns.index("order_date") if "order_date" in columns else 0)
        total_amount = st.selectbox("订单金额", columns, index=columns.index("total_amount") if "total_amount" in columns else 0)
        profit_default = columns.index("profit_margin") if "profit_margin" in columns else None
        profit_amount = st.selectbox("单笔利润额", [""] + columns, index=(profit_default + 1) if profit_default is not None else 0)
        mapping = {"order_id": order_id, "order_date": order_date, "total_amount": total_amount, "profit_amount": profit_amount}

fx_payload = fx_upload.getvalue() if fx_upload else None
source_payload = source.read_bytes() if isinstance(source, Path) else source
try:
    with st.spinner("正在校验数据并计算指标..."):
        context = prepare_cached(
            source_payload,
            filename,
            tuple(sorted((mapping or {}).items())),
            source_currency,
            target_currency,
            fx_payload,
        )
except Exception as exc:
    page_header("数据准备", "输入文件尚未通过校验")
    st.error("无法读取或准备数据：{}".format(exc))
    st.stop()

if context.fatal_issues:
    page_header("数据准备", "输入文件尚未通过核心契约")
    for issue in context.fatal_issues:
        st.error(issue.message)
    st.stop()

frame = context.analysis_data
st.sidebar.markdown("### 筛选")
date_min, date_max = frame.order_date.min().date(), frame.order_date.max().date()
date_range = st.sidebar.date_input("订单日期", value=(date_min, date_max), min_value=date_min, max_value=date_max)
regions = st.sidebar.pills(
    "区域",
    sorted(frame.region.dropna().unique()) if "region" in frame else [],
    selection_mode="multi",
    format_func=lambda item: value_for(item, "region"),
) or []
categories = st.sidebar.pills(
    "品类",
    sorted(frame.category.dropna().unique()) if "category" in frame else [],
    selection_mode="multi",
    format_func=lambda item: value_for(item, "category"),
) or []
bundle = run_cached(context, tuple(date_range), tuple(regions), tuple(categories))
views = ["经营总览", "销售分析", "商品分析", "客户分析", "区域市场", "退货与运营", "数据准备", "导出"]
view = st.sidebar.radio("视图", views, label_visibility="collapsed")

currency = context.metadata.get("target_currency", "")
with st.sidebar.expander("模块状态"):
    status_strip(bundle)

if view == "经营总览":
    page_header("经营总览", "当前经营规模、变化与需要关注的证据")
    overview = result_or_notice(bundle, "overview")
    sales = result_or_notice(bundle, "sales")
    if overview:
        data = overview.data
        cols = st.columns(4)
        cols[0].metric("GMV（成交总额）", money(data["gmv"], currency))
        cols[1].metric("订单", "{:,}".format(data["orders"]))
        cols[2].metric("利润", money(data.get("profit_amount"), currency))
        cols[3].metric("退货率", pct(data.get("return_rate")))
        cols = st.columns(4)
        cols[0].metric("客户", "{:,}".format(data.get("customers") or 0))
        cols[1].metric("销量", "{:,}".format(data.get("units") or 0))
        cols[2].metric("AOV（平均客单价）", money(data["aov"], currency))
        cols[3].metric("利润率", pct(data.get("profit_rate")))
    if sales:
        st.plotly_chart(monthly_chart(sales.data["monthly"], sales.data["incomplete_months"]), width="stretch", config={"displayModeBar": False})
        evidence = sales.evidence[0] if sales.evidence else None
        if evidence:
            evidence_rail(
                "最近完整月 {}".format(evidence.period),
                "GMV（成交总额）{}，相对 {} 变化 {}。".format(money(evidence.value, currency), evidence.comparison_period, pct(evidence.relative_change)),
                "证据 {} · {} · 数据字段 {} · 样本 {:,}".format(
                    evidence.id,
                    localize_formula(evidence.formula),
                    localize_source_fields(", ".join(evidence.source_fields)),
                    evidence.sample_size or 0,
                ),
                "WARNING" if evidence.relative_change is not None and evidence.relative_change < 0 else "normal",
            )
    st.subheader("运营建议")
    for item in bundle.recommendations:
        evidence_rail(item["title"], item["action"], "依据 " + ", ".join(item["evidence_ids"]), item["level"])

elif view == "销售分析":
    page_header("销售分析", "完整周期趋势与品类、区域贡献")
    result = result_or_notice(bundle, "sales")
    if result:
        st.plotly_chart(monthly_chart(result.data["monthly"], result.data["incomplete_months"]), width="stretch", config={"displayModeBar": False})
        left, right = st.columns(2)
        with left:
            fig = contribution_chart(result.data["category_contribution"], "category")
            if fig: st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        with right:
            fig = contribution_chart(result.data["region_contribution"], "region")
            if fig: st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        localized_grid(result.data["monthly"].sort_values("month", ascending=False), "sales_monthly")

elif view == "商品分析":
    page_header("商品分析", "销量、利润与样本充分度共同决定经营分类")
    result = result_or_notice(bundle, "product")
    if result:
        products = result.data["products"]
        eligible = products[products.classification.ne("样本不足")]
        if not eligible.empty:
            fig = px.scatter(
                eligible, x="units", y="profit_rate", size="gmv", color="classification",
                hover_name="product_id", title="商品经营矩阵",
                color_discrete_map={"核心商品": COLORS["teal"], "引流商品": COLORS["amber"], "潜力商品": COLORS["blue"], "淘汰观察": COLORS["coral"]},
                labels={"units": "销量", "profit_rate": "利润率", "gmv": "GMV（成交总额）", "classification": "商品分类"},
            )
            fig.add_vline(x=result.data["volume_threshold"], line_color=COLORS["grid"])
            fig.add_hline(y=result.data["portfolio_margin"], line_color=COLORS["grid"])
            st.plotly_chart(chart_layout(fig, 500), width="stretch", config={"displayModeBar": False})
        evidence_rail("商品分类门槛", "{:,}个商品进入四象限，其余商品继续积累样本。".format(result.data["eligible_products"]), "证据 product.matrix · 至少3笔订单 · 销量P75（75分位数）/ 组合利润率")
        localized_grid(products.head(500), "product_analysis")

elif view == "客户分析":
    page_header("客户分析", "RFM分群定位维护、唤回与增长人群")
    result = result_or_notice(bundle, "customer")
    if result:
        customers = result.data["customers"]
        segments = result.data["segments"]
        fig = px.bar(segments, x="segment", y="customers", color="segment", title="RFM（客户价值模型）分群规模", color_discrete_sequence=[COLORS["teal"], COLORS["blue"], COLORS["coral"], COLORS["amber"]], labels={"segment": "客户分群", "customers": "客户数"})
        st.plotly_chart(chart_layout(fig), width="stretch", config={"displayModeBar": False})
        evidence_rail(
            "RFM（客户价值模型）锚点 {}".format(result.data["anchor_date"]),
            "客户按照最近购买、购买频率和消费金额的百分位评分分群，统计图始终使用固定分析口径。",
            "证据 customer.rfm · R/F/M评分1-5 · 客户 {:,}".format(len(customers)),
        )
        st.subheader("客户明细")
        available_segments = [name for name in SEGMENT_ORDER if name in set(customers["segment"])]
        selected_segment = st.segmented_control(
            "客户类型",
            ["全部客户"] + available_segments,
            default="全部客户",
            selection_mode="single",
            key="customer_detail_segment",
        ) or "全部客户"
        table_customers = customer_detail_frame(customers, selected_segment)
        st.caption("当前显示：{:,} 位{}。可使用下方搜索进一步筛选。".format(
            len(table_customers),
            "客户" if selected_segment == "全部客户" else selected_segment,
        ))
        visible_customers = localized_grid(table_customers, "customer_analysis")
        if len(visible_customers) != len(table_customers):
            st.caption("关键词匹配：{:,} 位客户。".format(len(visible_customers)))
        csv_data = visible_customers.to_csv(index=False).encode("utf-8-sig")
        export_segment = selected_segment.replace("客户", "") or "全部"
        st.download_button(
            "下载当前客户清单（{:,}人）".format(len(visible_customers)),
            data=csv_data,
            file_name="客户清单_{}_{}.csv".format(export_segment, result.data["anchor_date"]),
            mime="text/csv",
            icon=":material/download:",
            key="download_customer_detail",
        )

elif view == "区域市场":
    page_header("区域市场", "比较市场规模、利润质量、退货与配送效率")
    result = result_or_notice(bundle, "region")
    if result:
        region_chart = result.data.sort_values("gmv").copy()
        region_chart["region"] = region_chart["region"].map(lambda item: value_for(item, "region"))
        fig = px.bar(region_chart, x="gmv", y="region", orientation="h", color="profit_rate", title="区域GMV（成交总额）与利润率", color_continuous_scale=[COLORS["coral"], COLORS["amber"], COLORS["teal"]], labels={"gmv": "GMV（成交总额）", "region": "区域", "profit_rate": "利润率"})
        st.plotly_chart(chart_layout(fig, 430), width="stretch", config={"displayModeBar": False})
        localized_grid(result.data, "region_analysis")

elif view == "退货与运营":
    page_header("退货与运营", "退货风险暴露与配送关联，不将关联写成原因")
    result = result_or_notice(bundle, "returns")
    if result:
        cols = st.columns(3)
        cols[0].metric("退货率", pct(result.data["summary"]["return_rate"]))
        cols[1].metric("退货订单", "{:,}".format(result.data["summary"]["returned_orders"]))
        cols[2].metric("退货关联GMV（成交总额）", money(result.data["summary"]["returned_gmv_exposure"], currency))
        evidence_rail("退货关联GMV（成交总额）不是实际损失", "缺少退款额、成本和退款状态，当前只展示风险暴露。", "证据 returns.gmv_exposure · {}".format(localize_formula("sum(total_amount where returned=True)")), "WARNING")
        if not result.data["category"].empty:
            return_chart = result.data["category"].sort_values("return_rate").copy()
            return_chart["category"] = return_chart["category"].map(lambda item: value_for(item, "category"))
            fig = px.bar(return_chart, x="return_rate", y="category", orientation="h", title="品类退货率", color="returned_gmv_exposure", color_continuous_scale=[COLORS["grid"], COLORS["coral"]], labels={"return_rate": "退货率", "category": "品类", "returned_gmv_exposure": "退货关联GMV（成交总额）"})
            st.plotly_chart(chart_layout(fig), width="stretch", config={"displayModeBar": False})
        localized_grid(result.data["region"], "return_region")

elif view == "数据准备":
    page_header("数据准备", "字段、粒度、质量与汇率覆盖")
    cols = st.columns(4)
    cols[0].metric("原始记录", "{:,}".format(context.metadata["rows"]))
    cols[1].metric("分析记录", "{:,}".format(len(frame)))
    cols[2].metric("字段", context.metadata["columns"])
    cols[3].metric("汇率覆盖", "100%" if context.metadata.get("fx_complete") else "不完整")
    st.subheader("字段映射")
    localized_grid(pd.DataFrame([{"canonical_field": key, "source_field": value} for key, value in context.field_mapping.items()]), "field_mapping", search=False)
    st.subheader("质量问题")
    if context.issues:
        localized_grid(pd.DataFrame([issue.to_dict() for issue in context.issues]), "data_quality", search=False)
    else:
        st.success("核心契约、订单粒度和业务范围检查均通过。")

elif view == "导出":
    page_header("导出", "从当前筛选和同一证据包生成全部交付物")
    export_key = context.metadata["sha256"][:12]
    export_dir = ROOT / ".cache" / "exports" / export_key
    if st.button("生成分析文件", icon=":material/download:", type="primary"):
        with st.spinner("正在生成Excel、Markdown、DOCX和manifest..."):
            st.session_state["export_paths"] = export_bundle(bundle, export_dir)
    paths = st.session_state.get("export_paths")
    if paths:
        for name, path in paths.items():
            mime = {
                "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "markdown": "text/markdown",
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "manifest": "application/json",
            }[name]
            st.download_button("下载 {}".format(path.name), data=path.read_bytes(), file_name=path.name, mime=mime, icon=":material/download:")
