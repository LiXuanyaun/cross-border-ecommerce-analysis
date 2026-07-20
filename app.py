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
from crossborder_analytics.decision import composition_preview
from crossborder_analytics.phase2_ui import (
    insight_action_summary, insight_period_label, insight_title, latest_priority_insights,
    render_health_center, render_insight_center, render_market_growth,
    render_product_opportunities, render_risk_center,
)
from crossborder_analytics.phase2_models import AnalysisRequest
from crossborder_analytics.ui import (
    COLORS, chart_layout, composition_chart, contribution_chart, customer_detail_frame,
    evidence_rail, inject_theme, localized_grid, localized_selectable_grid,
    market_category_heatmap, market_strategy_heatmap, money, monthly_chart, page_header,
    pct, product_detail_frame, render_chart, result_or_notice, status_strip,
)


ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT / "data" / "ecommerce_sales_34500.csv"
CURRENCIES = ["CNY", "USD", "EUR", "GBP", "JPY", "HKD", "AUD", "CAD", "CHF", "INR", "BRL"]

st.set_page_config(page_title="CrossBorder AI Analytics", page_icon=":material/analytics:", layout="wide", initial_sidebar_state="auto")
inject_theme()

VIEWS = [
    "经营总览", "市场增长", "产品机会", "风险中心", "洞察中心", "数据健康中心", "销售分析", "商品分析",
    "客户分析", "区域市场", "退货与运营", "数据准备", "导出",
]
st.sidebar.markdown("### 页面")
view = st.sidebar.radio("页面", VIEWS, label_visibility="collapsed")


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
def run_cached(context, date_range, period_type, event_period=(), comparison_period=()):
    request = AnalysisRequest(
        filters={"order_date": date_range}, period_type=period_type,
        period_start=str(event_period[0]) if event_period else None,
        period_end=str(event_period[1]) if event_period else None,
        comparison_start=str(comparison_period[0]) if comparison_period else None,
        comparison_end=str(comparison_period[1]) if comparison_period else None,
    )
    return AnalysisService(cache_dir=ROOT / ".cache" / "fx").run(
        context, request=request,
    )


def load_source():
    uploaded = st.file_uploader("订单数据", type=["csv", "xlsx"], help="一行一订单；原始文件不会被修改")
    st.caption("单个文件最大 200 MB · 支持 CSV/XLSX")
    use_sample = st.toggle("使用内置示例", value=uploaded is None)
    if uploaded is not None:
        return uploaded.getvalue(), uploaded.name
    if use_sample:
        return SAMPLE, SAMPLE.name
    return None, None


with st.sidebar.expander("数据与口径", expanded=False):
    source, filename = load_source()
    source_currency = st.selectbox(
        "源币种", CURRENCIES, index=0, format_func=currency_label,
        help="数据没有币种字段时，该币种将应用于整张表",
    )
    target_currency = st.selectbox("基准币种", CURRENCIES, index=0, format_func=currency_label)
    fx_upload = st.file_uploader("汇率表（可选）", type=["csv"], help="date, source_currency, target_currency, rate")
    st.caption("单个文件最大 200 MB · 仅支持 CSV；字段为日期、源币种、目标币种、汇率")

if source is None:
    page_header("数据准备", "上传订单文件或载入内置示例")
    st.info("请选择数据文件。")
    st.stop()

mapping = None
if not isinstance(source, Path):
    columns, source_meta = read_columns(source, filename)
    with st.sidebar.expander("字段映射", expanded=False):
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
st.sidebar.markdown("### 分析周期")
st.sidebar.caption("影响全部页面的固定分析范围")
date_min, date_max = frame.order_date.min().date(), frame.order_date.max().date()
date_range = st.sidebar.date_input(
    "订单日期", value=(date_min, date_max), min_value=date_min, max_value=date_max
)
period_label = st.sidebar.segmented_control("比较周期", ["月度", "周度", "活动"], default="月度")
period_type = {"月度": "month", "周度": "week", "活动": "event"}[period_label]
event_period = comparison_period = ()
if period_type == "event":
    event_end = date_max
    event_start = max(date_min, event_end - pd.Timedelta(days=6).to_pytimedelta())
    comparison_end = event_start - pd.Timedelta(days=1).to_pytimedelta()
    comparison_start = max(date_min, comparison_end - pd.Timedelta(days=6).to_pytimedelta())
    event_period = st.sidebar.date_input("活动期", value=(event_start, event_end), min_value=date_min, max_value=date_max)
    comparison_period = st.sidebar.date_input("对照期", value=(comparison_start, comparison_end), min_value=date_min, max_value=date_max)
    if len(event_period) != 2 or len(comparison_period) != 2:
        st.error("活动分析需要完整选择活动期和对照期。")
        st.stop()
    if (event_period[1] - event_period[0]).days != (comparison_period[1] - comparison_period[0]).days:
        st.error("活动期和对照期必须等长。")
        st.stop()
with st.spinner("正在保存规范化数据并执行SQL分析..."):
    bundle = run_cached(context, tuple(date_range), period_type, tuple(event_period), tuple(comparison_period))
dataset_failure = bundle.results.get("dataset")
if dataset_failure and dataset_failure.status.value == "FATAL":
    page_header("数据准备", "本地数据层尚未就绪")
    st.error(dataset_failure.message)
    st.stop()
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
        render_chart(monthly_chart(sales.data["monthly"], sales.data["incomplete_months"]))
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
    artifacts = getattr(bundle, "artifacts", None)
    if artifacts and artifacts.insights:
        priority_insights = latest_priority_insights(artifacts, limit=3)
        if not priority_insights:
            st.info("当前未发现达到高优先级阈值的异常。")
        for item in priority_insights:
            evidence_rail(
                "[{}] {}".format(item.priority, insight_title(item)),
                item.finding,
                "{} · 建议：{} · 依据 {}".format(
                    insight_period_label(item, artifacts), insight_action_summary(item, artifacts),
                    ", ".join(item.evidence_ids),
                ),
                item.severity,
            )
    else:
        for item in bundle.recommendations[:5]:
            evidence_rail(item["title"], item["action"], "依据 " + ", ".join(item["evidence_ids"]), item["level"])

elif view == "销售分析":
    page_header("销售分析", "完整周期趋势与品类、区域贡献")
    result = result_or_notice(bundle, "sales")
    if result:
        render_chart(monthly_chart(result.data["monthly"], result.data["incomplete_months"]))
        left, right = st.columns(2)
        with left:
            fig = contribution_chart(result.data["category_contribution"], "category")
            if fig: render_chart(fig)
        with right:
            fig = contribution_chart(result.data["region_contribution"], "region")
            if fig: render_chart(fig)
        localized_grid(result.data["monthly"].sort_values("month", ascending=False), "sales_monthly")

elif view == "市场增长":
    render_market_growth(bundle)

elif view == "产品机会":
    render_product_opportunities(bundle)

elif view == "商品分析":
    page_header("商品分析", "固定经营矩阵定位组合，页面内清单与详情支持下一步投入判断")
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
            render_chart(chart_layout(
                fig,
                profile="scatter",
                series_names=eligible["classification"].dropna().unique(),
                item_count=len(eligible),
            ))
        evidence_rail("商品分类门槛", "{:,}个商品进入四象限，其余商品继续积累样本。".format(result.data["eligible_products"]), "证据 product.matrix · 至少3笔订单 · 销量P75（75分位数）/ 组合利润率")
        st.subheader("商品行动清单")
        classes = [name for name in ["核心商品", "引流商品", "潜力商品", "淘汰观察", "样本不足"] if name in set(products.classification)]
        if products["profit"].lt(0).any():
            classes.append("亏损商品")
        selected_class = st.segmented_control(
            "商品分类",
            ["全部商品"] + classes,
            default="全部商品",
            selection_mode="single",
            key="product_detail_classification",
        ) or "全部商品"
        table_products = product_detail_frame(products, selected_class)
        st.caption("当前分类包含 {:,} 个商品；经营矩阵仍使用固定分析口径。点击表格行查看同页详情。".format(len(table_products)))
        visible_products, selected_product_id = localized_selectable_grid(
            table_products,
            "product_analysis",
            id_field="product_id",
            page_size=20,
        )
        st.download_button(
            "下载当前商品清单（{:,}项）".format(len(visible_products)),
            data=visible_products.to_csv(index=False).encode("utf-8-sig"),
            file_name="商品清单_{}.csv".format(selected_class),
            mime="text/csv",
            icon=":material/download:",
            key="download_product_detail",
        )
        if selected_product_id:
            st.subheader("商品详情")
            try:
                detail = AnalysisService(cache_dir=ROOT / ".cache" / "fx").product_detail(bundle, selected_product_id)
            except Exception as exc:
                st.error("商品详情查询失败：{}".format(exc))
            else:
                summary = detail["summary"]
                product_title = summary.get("product_name")
                title = "{} · {}".format(product_title, selected_product_id) if product_title and not pd.isna(product_title) else selected_product_id
                st.markdown("#### {}".format(title))
                st.caption("主品类：{} · 经营分类：{} · 建议动作：{}{}".format(
                    value_for(summary.get("primary_category"), "category") if pd.notna(summary.get("primary_category")) else "不可用",
                    summary.get("classification", "不可用"),
                    summary.get("recommended_action", "不可用"),
                    " · 存在跨品类冲突" if summary.get("category_conflict") else "",
                ))
                metrics = st.columns(4)
                metrics[0].metric("GMV（成交总额）", money(summary.get("gmv"), currency))
                metrics[1].metric("利润", money(summary.get("profit"), currency))
                metrics[2].metric("利润率", pct(summary.get("profit_rate")))
                metrics[3].metric("订单", "{:,}".format(int(summary.get("orders", 0) or 0)))
                metrics = st.columns(4)
                metrics[0].metric("销量", "{:,}".format(int(summary.get("units", 0) or 0)))
                metrics[1].metric("客户", "不可用" if pd.isna(summary.get("customers")) else "{:,}".format(int(summary.get("customers", 0))))
                metrics[2].metric("退货率", pct(summary.get("return_rate")))
                metrics[3].metric("最近销售", str(summary.get("last_order") or "不可用")[:10])
                if detail["trend_available"]:
                    monthly = detail["monthly"]
                    trend = px.line(
                        monthly, x="month", y="gmv", markers=True, title="商品月度表现",
                        labels={"month": "月份", "gmv": "GMV（成交总额）"},
                    )
                    trend.update_traces(line_color=COLORS["teal"], hovertemplate="%{x}<br>GMV（成交总额）%{y:,.2f}<extra></extra>")
                    render_chart(chart_layout(
                        trend,
                        profile="time_series",
                        x_labels=monthly["month"],
                        item_count=len(monthly),
                    ))
                else:
                    st.info("仅有 {} 个有效周期，少于8个周期；当前展示期间表，不形成趋势判断。".format(detail["periods"]))
                    localized_grid(detail["monthly"], "product_detail_periods", search=False)
                left, right = st.columns(2)
                with left:
                    market_mix = detail["market_mix"].rename(columns={"market": "dimension_value"})
                    chart = composition_chart(market_mix, "市场构成", "市场")
                    if chart:
                        render_chart(chart)
                    else:
                        st.info("缺少市场字段，市场构成不可用。")
                with right:
                    customer_mix = detail["customer_mix"].rename(columns={"segment": "dimension_value"})
                    chart = composition_chart(customer_mix, "客户分群构成", "客户分群")
                    if chart:
                        render_chart(chart)
                    else:
                        st.info("缺少客户字段，客户分群构成不可用。")
                evidence = detail["evidence"]
                evidence_rail(
                    "商品详情证据",
                    "详情只汇总当前固定分析周期内的商品订单；缺字段区域单独降级。",
                    "证据 {} · 样本 {:,} · 日期 {} 至 {} · 数据字段 {}".format(
                        evidence["id"], evidence["sample_size"],
                        str(evidence["date_range"][0] or "-")[:10], str(evidence["date_range"][1] or "-")[:10],
                        "、".join(evidence["source_fields"]),
                    ),
                )

elif view == "客户分析":
    page_header("客户分析", "RFM分群定位维护、唤回与增长人群")
    result = result_or_notice(bundle, "customer")
    if result:
        customers = result.data["customers"]
        segments = result.data["segments"]
        fig = px.bar(segments, x="segment", y="customers", color="segment", title="RFM（客户价值模型）分群规模", color_discrete_sequence=[COLORS["teal"], COLORS["blue"], COLORS["coral"], COLORS["amber"]], labels={"segment": "客户分群", "customers": "客户数"})
        render_chart(chart_layout(
            fig,
            profile="category_x",
            x_labels=segments["segment"],
            series_names=segments["segment"],
            item_count=len(segments),
        ))
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
        composition = result.data.get("composition", pd.DataFrame())
        if not composition.empty:
            left, right = st.columns(2)
            with left:
                market_preview = composition_preview(composition, selected_segment, "market")
                chart = composition_chart(market_preview, "市场构成", "市场")
                if chart:
                    render_chart(chart)
            with right:
                category_preview = composition_preview(composition, selected_segment, "category")
                chart = composition_chart(category_preview, "品类构成", "品类")
                if chart:
                    render_chart(chart)
            with st.expander("查看完整客户构成"):
                full_composition = composition if selected_segment == "全部客户" else composition.loc[composition.segment.eq(selected_segment)]
                localized_grid(full_composition, "customer_composition", search=False)
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
    page_header("区域市场", "先看市场×品类偏好，再结合利润、退货和履约证据判断投入方向")
    market_category = result_or_notice(bundle, "market_category")
    result = result_or_notice(bundle, "region")
    if market_category:
        mode = st.segmented_control(
            "热力图指标", ["订单偏好", "收益贡献"], default="订单偏好",
            selection_mode="single", key="market_heatmap_mode",
        ) or "订单偏好"
        heatmap = market_category_heatmap(market_category.data, mode)
        if heatmap:
            render_chart(heatmap)
        else:
            st.info("当前模式缺少可用字段；可切换订单偏好查看市场内订单构成。")
        st.caption("订单偏好按市场内订单占比计算；收益贡献使用以0为中心的利润正负色阶。页面切换不改变固定分析模型。")
    if result:
        strategy_chart = market_strategy_heatmap(result.data)
        if strategy_chart:
            render_chart(strategy_chart)
        evidence_rail(
            "市场投入策略规则",
            "策略使用当前数据集的规模、组合利润率、整体退货率和配送P90基准；缺少风险字段会降低置信度。",
            "证据 region.strategy · 负利润谨慎评估 · 风险弱于基准先优化效率 · 规模与利润达标优先评估投入",
        )
        st.subheader("市场行动清单")
        visible_markets = localized_grid(result.data, "region_analysis")
        st.download_button(
            "下载当前市场清单（{:,}项）".format(len(visible_markets)),
            data=visible_markets.to_csv(index=False).encode("utf-8-sig"),
            file_name="市场行动清单.csv",
            mime="text/csv",
            icon=":material/download:",
            key="download_market_preview",
        )

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
            render_chart(chart_layout(
                fig,
                profile="category_y",
                y_labels=return_chart["category"],
                item_count=len(return_chart),
            ))
        localized_grid(result.data["region"], "return_region")

elif view == "风险中心":
    render_risk_center(bundle)

elif view == "洞察中心":
    render_insight_center(bundle)

elif view == "数据健康中心":
    render_health_center(bundle)

elif view == "数据准备":
    page_header("数据准备", "字段、粒度、质量与汇率覆盖")
    cols = st.columns(4)
    cols[0].metric("原始记录", "{:,}".format(context.metadata["rows"]))
    cols[1].metric("分析记录", "{:,}".format(len(frame)))
    cols[2].metric("字段", context.metadata["columns"])
    cols[3].metric("汇率覆盖", "100%" if context.metadata.get("fx_complete") else "不完整")
    st.subheader("本地数据层")
    storage_cols = st.columns(4)
    storage_cols[0].metric("分析后端", str(bundle.metadata.get("analysis_backend", "")).upper())
    storage_cols[1].metric("入库记录", "{:,}".format(bundle.context.metadata.get("stored_rows", 0)))
    storage_cols[2].metric("数据库版本", bundle.metadata.get("database_schema_version") or "-")
    dataset_id = bundle.metadata.get("dataset_id") or ""
    storage_cols[3].metric("数据集版本", dataset_id[:12] if dataset_id else "-")
    st.caption("数据库：{} · 重复导入：{}".format(
        bundle.context.metadata.get("database_path", ""),
        "已复用" if bundle.context.metadata.get("storage_reused") else "新版本",
    ))
    st.subheader("字段映射")
    localized_grid(pd.DataFrame([{"canonical_field": key, "source_field": value} for key, value in context.field_mapping.items()]), "field_mapping", search=False)
    st.subheader("质量问题")
    if context.issues:
        localized_grid(pd.DataFrame([issue.to_dict() for issue in context.issues]), "data_quality", search=False)
    else:
        st.success("核心契约、订单粒度和业务范围检查均通过。")

elif view == "导出":
    page_header("导出", "从固定分析结果生成《跨境电商经营分析与行动报告》")
    report_version_label = st.segmented_control(
        "报告版本", ["摘要版", "完整版"], default="摘要版", key="report_version",
    ) or "摘要版"
    report_scope_label = st.segmented_control(
        "报告范围", ["整体", "指定市场", "指定品类"], default="整体", key="report_scope",
    ) or "整体"
    scope_map = {"整体": "overall", "指定市场": "market", "指定品类": "category"}
    report_scope = scope_map[report_scope_label]
    scope_value = None
    if report_scope == "market":
        market_values = [item.market for item in bundle.artifacts.market_opportunities]
        scope_value = st.selectbox("选择市场", market_values, key="report_market") if market_values else None
        if not market_values:
            st.info("当前没有可用于指定范围的市场对象。")
    elif report_scope == "category":
        category_values = sorted({item.category for item in bundle.artifacts.product_opportunities})
        scope_value = st.selectbox("选择品类", category_values, key="report_category") if category_values else None
        if not category_values:
            st.info("当前没有可用于指定范围的品类对象。")
    include_action_details = st.toggle("附带行动明细", value=True, key="report_actions")
    output_formats = st.multiselect("输出格式", ["DOCX", "Excel"], default=["DOCX", "Excel"], key="report_formats")
    st.caption("报告版本、范围和行动明细只改变交付内容；数据集、分析周期、指标公式和证据口径保持不变。")
    export_key = context.metadata["sha256"][:12]
    option_key = "{}_{}_{}".format(report_version_label, report_scope, scope_value or "all")
    export_dir = ROOT / ".cache" / "exports" / export_key / option_key
    can_export = bool(output_formats) and (report_scope == "overall" or scope_value is not None)
    if st.button("生成经营报告", icon=":material/download:", type="primary", disabled=not can_export):
        with st.spinner("正在生成Excel、Markdown、DOCX和manifest..."):
            st.session_state["export_paths"] = export_bundle(
                bundle, export_dir,
                report_version="summary" if report_version_label == "摘要版" else "full",
                report_scope=report_scope,
                scope_value=scope_value,
                include_action_details=include_action_details,
            )
            st.session_state["export_formats"] = list(output_formats)
    paths = st.session_state.get("export_paths")
    if paths:
        selected_names = {"DOCX": "docx", "Excel": "excel"}
        for label in st.session_state.get("export_formats", []):
            name = selected_names[label]
            path = paths[name]
            mime = {
                "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }[name]
            st.download_button("下载 {}".format(path.name), data=path.read_bytes(), file_name=path.name, mime=mime, icon=":material/download:")
