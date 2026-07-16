"""Streamlit rendering helpers for the operating dashboard."""
from html import escape
from typing import Any, Dict, Iterable, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

from autoclean.analytics import AnalysisStatus
from crossborder_analytics.localization import (
    MODULE_LABELS,
    STATUS_LABELS,
    currency_label,
    label_for,
    localize_frame,
    value_for,
)
from crossborder_analytics.rfm import SEGMENT_ORDER


COLORS = {
    "ink": "#17212B",
    "paper": "#F7F8F6",
    "grid": "#DDE3E0",
    "teal": "#0D7C66",
    "coral": "#C84B31",
    "amber": "#B98213",
    "blue": "#3D6FA3",
}


AGGRID_ZH_CN = {
    "page": "页",
    "more": "更多",
    "to": "至",
    "of": "共",
    "next": "下一页",
    "last": "末页",
    "first": "首页",
    "previous": "上一页",
    "pageSizeSelectorLabel": "每页行数：",
    "loadingOoo": "正在加载...",
    "selectAll": "全选",
    "selectAllSearchResults": "选择全部搜索结果",
    "searchOoo": "搜索...",
    "blanks": "空值",
    "filterOoo": "筛选...",
    "applyFilter": "应用筛选",
    "resetFilter": "重置筛选",
    "clearFilter": "清除筛选",
    "cancelFilter": "取消",
    "equals": "等于",
    "notEqual": "不等于",
    "blank": "为空",
    "notBlank": "不为空",
    "empty": "请选择",
    "lessThan": "小于",
    "greaterThan": "大于",
    "lessThanOrEqual": "小于或等于",
    "greaterThanOrEqual": "大于或等于",
    "inRange": "介于",
    "inRangeStart": "起始值",
    "inRangeEnd": "结束值",
    "contains": "包含",
    "notContains": "不包含",
    "startsWith": "开头是",
    "endsWith": "结尾是",
    "andCondition": "并且",
    "orCondition": "或者",
    "noRowsToShow": "暂无数据",
    "pinColumn": "固定列",
    "pinLeft": "固定到左侧",
    "pinRight": "固定到右侧",
    "noPin": "取消固定",
    "autosizeThiscolumn": "自动调整此列",
    "autosizeAllColumns": "自动调整所有列",
    "resetColumns": "重置列",
    "copy": "复制",
    "copyWithHeaders": "复制（含表头）",
    "copyWithGroupHeaders": "复制（含分组表头）",
    "paste": "粘贴",
    "export": "导出",
    "csvExport": "导出为CSV",
    "excelExport": "导出为Excel",
    "sortAscending": "升序排列",
    "sortDescending": "降序排列",
    "sortUnSort": "清除排序",
    "columns": "列",
    "filters": "筛选",
    "chooseColumns": "选择列",
    "columnFilter": "列筛选",
    "columnChooser": "选择列",
}

PERCENT_FIELDS = {"profit_rate", "return_rate", "change_rate", "relative_change"}
AMOUNT_FIELDS = {
    "gmv", "profit", "profit_amount", "aov", "monetary", "returned_gmv_exposure",
    "baseline_value", "absolute_change", "change", "current", "previous",
}
INTEGER_FIELDS = {
    "orders", "customers", "units", "returned_orders", "frequency", "recency_days",
    "r_score", "f_score", "m_score", "sample_size", "evidence_count",
}


def inject_theme() -> None:
    st.markdown(
        """
        <style>
        :root { --ink:#17212B; --paper:#F7F8F6; --grid:#DDE3E0; --teal:#0D7C66; --coral:#C84B31; --amber:#B98213; }
        html, body, [class*="css"] { font-family:"Noto Sans SC","Microsoft YaHei","Segoe UI",sans-serif; color:var(--ink); }
        .stApp { background:#F7F8F6; }
        .block-container { max-width:1440px; padding-top:1.35rem; padding-bottom:3rem; }
        h1, h2, h3 { letter-spacing:0 !important; color:var(--ink); }
        h1 { font-size:1.65rem !important; margin:0 0 .2rem 0 !important; }
        h2 { font-size:1.15rem !important; margin-top:1.5rem !important; }
        h3 { font-size:1rem !important; }
        [data-testid="stSidebar"] { background:#FFFFFF; border-right:1px solid var(--grid); }
        [data-testid="stToolbar"] {
          display:flex !important;
          align-items:center !important;
          justify-content:space-between !important;
          width:100% !important;
          min-height:60px !important;
          padding:0 .75rem !important;
        }
        [data-testid="stAppDeployButton"],
        [data-testid="stDeployButton"],
        [data-testid="stMainMenuButton"],
        [data-testid="stMainMenu"] { display:none !important; }
        [data-testid="stSidebarCollapseButton"] {
          visibility:visible !important;
          opacity:1 !important;
        }
        [data-testid="stExpandSidebarButton"],
        [data-testid="stSidebarCollapsedControl"] {
          position:fixed !important;
          top:.75rem !important;
          left:.75rem !important;
          z-index:2147483647 !important;
          display:flex !important;
          visibility:visible !important;
          opacity:1 !important;
          width:2.25rem !important;
          height:2.25rem !important;
          align-items:center !important;
          justify-content:center !important;
        }
        [data-testid="stSidebarCollapseButton"] button,
        [data-testid="stExpandSidebarButton"],
        [data-testid="stSidebarCollapsedControl"] button,
        button[aria-label*="sidebar" i] {
          background:#FFFFFF !important;
          border:1px solid var(--grid) !important;
          border-radius:6px !important;
          color:var(--ink) !important;
          box-shadow:0 4px 14px rgba(23,33,43,.10) !important;
          width:2.25rem !important;
          height:2.25rem !important;
          min-width:2.25rem !important;
          padding:0 !important;
        }
        [data-testid="stExpandSidebarButton"]:hover::after,
        [data-testid="stExpandSidebarButton"]:focus-visible::after {
          content:"展开侧栏";
          position:absolute;
          left:calc(100% + .45rem);
          top:50%;
          transform:translateY(-50%);
          padding:.3rem .5rem;
          border-radius:4px;
          background:var(--ink);
          color:#FFFFFF;
          font-size:.72rem;
          line-height:1;
          white-space:nowrap;
          pointer-events:none;
        }
        [data-testid="stFileUploaderDropzoneInstructions"] { display:none; }
        [data-testid="stFileUploaderDropzone"] { min-height:3rem; padding:.55rem; }
        [data-testid="stFileUploaderDropzone"] button [data-testid="stMarkdownContainer"],
        [data-testid="stFileUploaderDropzone"] button [data-testid="stIconMaterial"] { display:none !important; }
        [data-testid="stFileUploaderDropzone"] button { font-size:0 !important; }
        [data-testid="stFileUploaderDropzone"] button::after { content:"选择文件"; font-size:.875rem; }
        [data-testid="stMetric"] { background:#FFFFFF; border:1px solid var(--grid); border-radius:6px; padding:14px 16px; min-height:112px; }
        [data-testid="stMetricValue"] { font-family:"Bahnschrift","Segoe UI",sans-serif; font-size:1.3rem; line-height:1.2; white-space:normal !important; overflow:visible !important; text-overflow:clip !important; overflow-wrap:anywhere; }
        [data-testid="stMetricValue"] p { white-space:normal !important; overflow:visible !important; text-overflow:clip !important; overflow-wrap:normal; word-break:keep-all; }
        [data-testid="stMetricDelta"] { font-size:.78rem; }
        .evidence-rail { background:#FFFFFF; border:1px solid var(--grid); border-left:4px solid var(--teal); border-radius:0 6px 6px 0; padding:12px 14px; margin:.45rem 0 .8rem; }
        .evidence-rail.warn { border-left-color:var(--amber); }
        .evidence-rail.risk { border-left-color:var(--coral); }
        .evidence-title { font-weight:700; font-size:.92rem; margin-bottom:4px; }
        .evidence-claim { font-size:.84rem; line-height:1.55; }
        .evidence-meta { color:#62706B; font-size:.72rem; margin-top:7px; overflow-wrap:anywhere; }
        .status-strip { display:flex; flex-wrap:wrap; gap:6px; margin:.3rem 0 1rem; }
        .status-item { background:#FFFFFF; border:1px solid var(--grid); border-radius:4px; padding:4px 8px; font-size:.72rem; }
        .status-item.success { border-color:#80BDAE; color:#075E4C; }
        .status-item.skipped { border-color:#D8B86C; color:#785900; }
        .status-item.failed,.status-item.fatal { border-color:#D59586; color:#8E2F1B; }
        .page-kicker { color:#62706B; font-size:.78rem; margin-bottom:.15rem; }
        .page-subtitle { color:#62706B; font-size:.84rem; margin-bottom:1rem; }
        iframe[title="st_aggrid.agGrid"] { border:1px solid var(--grid); border-radius:6px; background:#FFFFFF; }
        .stButton > button, .stDownloadButton > button { border-radius:5px; min-height:2.35rem; }
        .stButton > button:focus-visible, .stDownloadButton > button:focus-visible { outline:3px solid rgba(13,124,102,.28); outline-offset:2px; }
        @media (max-width: 720px) {
          .block-container { padding-left:.8rem; padding-right:.8rem; padding-top:3.75rem; }
          h1 { font-size:1.35rem !important; }
          [data-testid="stMetric"] { min-height:92px; }
          .evidence-meta { font-size:.68rem; }
        }
        @media (prefers-reduced-motion: reduce) { * { scroll-behavior:auto !important; transition:none !important; animation:none !important; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str, kicker: str = "经营控制台") -> None:
    st.markdown('<div class="page-kicker">{}</div>'.format(escape(kicker)), unsafe_allow_html=True)
    st.title(title)
    st.markdown('<div class="page-subtitle">{}</div>'.format(escape(subtitle)), unsafe_allow_html=True)


def status_strip(bundle) -> None:
    items = []
    for result in bundle.results.values():
        css = result.status.value.lower()
        items.append('<span class="status-item {}">{} · {}</span>'.format(
            css,
            escape(MODULE_LABELS.get(result.name, result.name)),
            escape(STATUS_LABELS.get(result.status.value, result.status.value)),
        ))
    st.markdown('<div class="status-strip">{}</div>'.format("".join(items)), unsafe_allow_html=True)


def evidence_rail(title: str, claim: str, metadata: str, level: str = "normal") -> None:
    css = "risk" if level == "HIGH" else "warn" if level in ("MONITOR", "WARNING") else ""
    st.markdown(
        '<div class="evidence-rail {}"><div class="evidence-title">{}</div><div class="evidence-claim">{}</div><div class="evidence-meta">{}</div></div>'.format(
            css, escape(title), escape(claim), escape(metadata)
        ),
        unsafe_allow_html=True,
    )


def money(value, currency: str) -> str:
    if value is None or pd.isna(value):
        return "不可用"
    magnitude = abs(float(value))
    if magnitude >= 100_000_000:
        text = "{:.2f}亿".format(value / 100_000_000)
    elif magnitude >= 10_000:
        text = "{:.2f}万".format(value / 10_000)
    else:
        text = "{:,.2f}".format(value)
    return "{} {}".format(text, currency_label(currency)).strip()


def pct(value) -> str:
    return "不可用" if value is None or pd.isna(value) else "{:.2%}".format(value)


def chart_layout(fig, height=380):
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=46, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Noto Sans SC, Microsoft YaHei, Segoe UI", color=COLORS["ink"]),
        hoverlabel=dict(bgcolor="#FFFFFF", font_size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
    )
    fig.update_xaxes(gridcolor=COLORS["grid"], zeroline=False)
    fig.update_yaxes(gridcolor=COLORS["grid"], zeroline=False)
    return fig


def localized_grid(
    data: pd.DataFrame,
    key: str,
    *,
    height: Optional[int] = None,
    page_size: int = 20,
    search: bool = True,
    value_maps: Optional[Dict[str, Dict[str, str]]] = None,
) -> pd.DataFrame:
    """Render an immutable localized grid and return its searched display copy."""
    if not isinstance(data, pd.DataFrame):
        data = pd.DataFrame(data)
    source_columns = list(data.columns)
    display = localize_frame(data, value_maps=value_maps)
    if search:
        query = st.text_input(
            "搜索表格",
            key="{}_search".format(key),
            placeholder="输入关键词搜索当前表格",
            label_visibility="collapsed",
        ).strip()
        if query:
            matches = display.astype(str).apply(
                lambda column: column.str.contains(query, case=False, na=False, regex=False)
            ).any(axis=1)
            display = display.loc[matches].copy()

    builder = GridOptionsBuilder.from_dataframe(display)
    builder.configure_default_column(
        sortable=True,
        filter=True,
        resizable=True,
        wrapHeaderText=True,
        autoHeaderHeight=True,
        minWidth=108,
        suppressHeaderMenuButton=False,
        suppressHeaderFilterButton=False,
        menuTabs=["generalMenuTab", "filterMenuTab", "columnsMenuTab"],
    )
    builder.configure_pagination(enabled=True, paginationAutoPageSize=False, paginationPageSize=page_size)
    for index, source_name in enumerate(source_columns):
        display_name = label_for(source_name)
        options = {"pinned": "left"} if index == 0 else {}
        if source_name in PERCENT_FIELDS:
            options.update({
                "type": ["numericColumn", "rightAligned"],
                "valueFormatter": JsCode("function(p){return p.value == null ? '不可用' : (p.value * 100).toFixed(2) + '%';}"),
            })
        elif source_name in AMOUNT_FIELDS:
            options.update({
                "type": ["numericColumn", "rightAligned"],
                "valueFormatter": JsCode("function(p){return p.value == null ? '不可用' : Number(p.value).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});}"),
            })
        elif source_name in INTEGER_FIELDS:
            options.update({
                "type": ["numericColumn", "rightAligned"],
                "valueFormatter": JsCode("function(p){return p.value == null ? '不可用' : Number(p.value).toLocaleString('zh-CN',{maximumFractionDigits:2});}"),
            })
        builder.configure_column(display_name, header_name=display_name, **options)

    options = builder.build()
    options.update({
        "localeText": AGGRID_ZH_CN,
        "animateRows": False,
        "paginationPageSizeSelector": [10, 20, 50, 100],
        "suppressCellFocus": True,
        "autoSizeStrategy": {"type": "fitGridWidth", "defaultMinWidth": 108},
        "columnMenu": "legacy",
    })
    grid_height = height or max(190, min(560, 112 + min(max(len(display), 1), page_size) * 34))
    AgGrid(
        display,
        gridOptions=options,
        height=grid_height,
        key=key,
        theme="streamlit",
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        show_toolbar=False,
        show_search=False,
        show_download_button=False,
        custom_css={
            ".ag-root-wrapper": {"border": "none", "border-radius": "5px"},
            ".ag-header": {"background-color": COLORS["paper"], "font-weight": "600"},
            ".ag-row-hover": {"background-color": "#EEF5F2 !important"},
        },
    )
    return display.copy(deep=True)


def customer_detail_frame(customers: pd.DataFrame, segment: str = "全部客户") -> pd.DataFrame:
    """Return an immutable, operationally ordered customer-detail view."""
    detail = customers.copy(deep=True)
    if segment != "全部客户":
        detail = detail.loc[detail["segment"].eq(segment)].copy()
    order = {name: index for index, name in enumerate(SEGMENT_ORDER)}
    detail["_segment_order"] = detail["segment"].map(order).fillna(len(order))
    return (
        detail.sort_values(["_segment_order", "monetary"], ascending=[True, False])
        .drop(columns="_segment_order")
        .reset_index(drop=True)
    )


def monthly_chart(data: pd.DataFrame, incomplete: Iterable[str]):
    fig = px.line(data, x="month", y="gmv", markers=True, title="月度GMV（成交总额）", labels={"month": "月份", "gmv": "GMV（成交总额）"})
    fig.update_traces(line_color=COLORS["teal"], line_width=2.4, marker_size=6, hovertemplate="%{x}<br>GMV（成交总额）%{y:,.2f}<extra></extra>")
    incomplete = set(incomplete)
    if incomplete:
        partial = data[data.month.isin(incomplete)]
        fig.add_trace(go.Scatter(
            x=partial.month, y=partial.gmv, mode="markers", name="不完整月份",
            marker=dict(color=COLORS["amber"], size=10, symbol="diamond"),
            hovertemplate="%{x}<br>不完整周期 %{y:,.2f}<extra></extra>",
        ))
    fig.update_xaxes(type="category")
    return chart_layout(fig, 390)


def contribution_chart(data: pd.DataFrame, dimension: str):
    if data is None or data.empty:
        return None
    ordered = data.sort_values("change").copy()
    if dimension in ordered:
        ordered[dimension] = ordered[dimension].map(lambda item: value_for(item, dimension))
    fig = px.bar(
        ordered, x="change", y=dimension, orientation="h", title="环比贡献",
        color="change", color_continuous_scale=[[0, COLORS["coral"]], [.5, "#DDE3E0"], [1, COLORS["teal"]]],
        labels={"change": "GMV（成交总额）变化", "category": "品类", "region": "区域"},
    )
    fig.update_layout(coloraxis_showscale=False)
    fig.update_traces(hovertemplate="%{y}<br>GMV（成交总额）变化 %{x:,.2f}<extra></extra>")
    return chart_layout(fig, 360)


def result_or_notice(bundle, name):
    result = bundle.results.get(name)
    if not result or result.status != AnalysisStatus.SUCCESS:
        st.warning(result.message if result else "模块不可用")
        return None
    if result.message:
        st.info(result.message)
    return result
