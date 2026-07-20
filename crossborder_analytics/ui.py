"""Streamlit rendering helpers for the operating dashboard."""
from html import escape
from math import ceil
from typing import Any, Dict, Iterable, Optional

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from st_aggrid import AgGrid, DataReturnMode, GridOptionsBuilder, JsCode

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

CHART_FONT_FAMILY = (
    "Microsoft YaHei, PingFang SC, Noto Sans CJK SC, Noto Sans SC, "
    "Source Han Sans SC, Segoe UI, sans-serif"
)
PLOTLY_RENDER_CONFIG = {
    "displayModeBar": False,
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": False,
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

PERCENT_FIELDS = {
    "profit_rate", "return_rate", "change_rate", "relative_change", "order_share",
    "gmv_share", "scale_benchmark", "portfolio_profit_rate", "portfolio_return_rate",
    "gmv_growth_rate", "order_growth_rate", "profit_margin_change", "return_rate_change",
    "sku_concentration", "market_growth_contribution", "customer_concentration",
    "high_value_customer_share",
}
AMOUNT_FIELDS = {
    "gmv", "profit", "profit_amount", "aov", "monetary", "returned_gmv_exposure",
    "baseline_value", "absolute_change", "change", "current", "previous", "current_gmv",
    "previous_gmv", "gmv_change", "impact_amount", "current_aov", "previous_aov",
}
INTEGER_FIELDS = {
    "orders", "customers", "units", "returned_orders", "frequency", "recency_days",
    "r_score", "f_score", "m_score", "sample_size", "evidence_count", "category_count",
    "current_orders", "previous_orders", "market_coverage",
}


def inject_theme() -> None:
    st.markdown(
        """
        <style>
        :root { --ink:#17212B; --paper:#F7F8F6; --grid:#DDE3E0; --teal:#0D7C66; --coral:#C84B31; --amber:#B98213; }
        html, body, [class*="css"] { font-family:"Noto Sans SC","Microsoft YaHei","Segoe UI",sans-serif; color:var(--ink); }
        .stApp { background:#F7F8F6; }
        [data-testid="stMain"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stMain"] label p,
        [data-testid="stSidebar"] label p,
        [data-testid="stMetricLabel"] p,
        [data-testid="stMetricValue"] p { color:var(--ink) !important; }
        [data-testid="stCaptionContainer"] p,
        [data-testid="stMain"] small,
        [data-testid="stSidebar"] small { color:#62706B !important; }
        button [data-testid="stMarkdownContainer"] p { color:inherit !important; }
        .block-container { max-width:1440px; padding-top:1.35rem; padding-bottom:3rem; }
        h1, h2, h3 { letter-spacing:0 !important; color:var(--ink) !important; }
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
        .audit-flow { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); background:#FFFFFF; border-top:1px solid var(--grid); border-bottom:1px solid var(--grid); margin:.6rem 0 1.2rem; }
        .audit-step { min-width:0; padding:13px 14px; border-right:1px solid var(--grid); }
        .audit-step:last-child { border-right:0; }
        .audit-label { color:#62706B; font-size:.68rem; margin-bottom:5px; }
        .audit-value { color:var(--ink); font-size:.82rem; font-weight:600; line-height:1.45; overflow-wrap:anywhere; }
        .audit-value.risk { color:#9D3823; }
        .audit-value.verify { color:#075E4C; }
        .decision-brief { background:#FFFFFF; border-top:3px solid var(--ink); border-bottom:1px solid var(--grid); padding:18px 20px; margin:.35rem 0 1rem; }
        .decision-brief-label { color:#62706B; font-size:.72rem; font-weight:700; margin-bottom:7px; }
        .decision-brief-text { color:var(--ink); font-size:1.05rem; font-weight:650; line-height:1.75; }
        .risk-list { background:#FFFFFF; border-top:1px solid var(--ink); border-bottom:1px solid var(--grid); margin:.75rem 0 .25rem; }
        .risk-list-header,.risk-list-row { display:grid; grid-template-columns:90px minmax(210px,1.3fr) 105px 125px 125px minmax(280px,1.55fr); }
        .risk-list-header { background:var(--paper); color:#62706B; font-size:.72rem; font-weight:700; }
        .risk-list-row { border-top:1px solid var(--grid); font-size:.78rem; line-height:1.55; }
        .risk-cell { min-width:0; padding:10px 12px; overflow-wrap:anywhere; }
        .priority-mark { display:inline-block; min-width:2rem; font-family:"Bahnschrift","Segoe UI",sans-serif; font-weight:700; }
        .page-kicker { color:#62706B; font-size:.78rem; margin-bottom:.15rem; }
        .page-subtitle { color:#62706B; font-size:.84rem; margin-bottom:1rem; }
        [data-testid="stPlotlyChart"],
        [data-testid="stPlotlyChart"] > div,
        [data-testid="stPlotlyChart"] .js-plotly-plot,
        [data-testid="stPlotlyChart"] .plot-container { width:100% !important; min-width:0 !important; }
        [data-testid="stPlotlyChart"] { overflow:visible !important; }
        [data-testid="stPlotlyChart"] .svg-container { overflow:visible !important; }
        iframe[title="st_aggrid.agGrid"] { border:1px solid var(--grid); border-radius:6px; background:#FFFFFF; }
        .stButton > button, .stDownloadButton > button { border-radius:5px; min-height:2.35rem; }
        .stButton > button:focus-visible, .stDownloadButton > button:focus-visible { outline:3px solid rgba(13,124,102,.28); outline-offset:2px; }
        @media (max-width: 720px) {
          .block-container { padding-left:.8rem; padding-right:.8rem; padding-top:3.75rem; }
          h1 { font-size:1.35rem !important; }
          [data-testid="stMetric"] { min-height:92px; }
          .evidence-meta { font-size:.68rem; }
          .audit-flow { grid-template-columns:1fr; }
          .audit-step { border-right:0; border-bottom:1px solid var(--grid); }
          .audit-step:last-child { border-bottom:0; }
          .decision-brief { padding:15px 14px; }
          .decision-brief-text { font-size:.94rem; }
          .risk-list-header { display:none; }
          .risk-list-row { display:block; padding:8px 12px; }
          .risk-cell { display:grid; grid-template-columns:78px minmax(0,1fr); gap:8px; padding:6px 0; }
          .risk-cell::before { content:attr(data-label); color:#62706B; font-size:.7rem; font-weight:600; }
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


def _visual_length(value: Any) -> int:
    return sum(2 if ord(character) > 127 else 1 for character in str(value))


def _wrap_axis_label(value: Any, width: int = 12, max_lines: int = 2) -> str:
    text = str(value)
    if not text:
        return text
    lines = []
    current = []
    current_width = 0
    for character in text:
        char_width = 2 if ord(character) > 127 else 1
        if current and current_width + char_width > width:
            lines.append("".join(current))
            current = []
            current_width = 0
            if len(lines) == max_lines:
                lines[-1] = lines[-1].rstrip("…") + "…"
                return "<br>".join(lines)
        current.append(character)
        current_width += char_width
    if current:
        lines.append("".join(current))
    return "<br>".join(lines)


def _sample_ticks(labels: list[str], maximum: int) -> tuple[list[str], list[str]]:
    if len(labels) <= maximum:
        return labels, labels
    indexes = sorted({round(index * (len(labels) - 1) / (maximum - 1)) for index in range(maximum)})
    return [labels[index] for index in indexes], [labels[index] for index in indexes]


def chart_layout_config(
    profile: str = "cartesian",
    x_labels: Optional[Iterable[Any]] = None,
    y_labels: Optional[Iterable[Any]] = None,
    series_names: Optional[Iterable[Any]] = None,
    item_count: Optional[int] = None,
    height: Optional[int] = None,
) -> Dict[str, Any]:
    """Return deterministic spacing and axis rules for one responsive chart."""
    profiles = {"cartesian", "time_series", "category_x", "category_y", "scatter", "heatmap"}
    if profile not in profiles:
        raise ValueError("Unknown chart profile: {}".format(profile))
    x_values = [str(value) for value in (list(x_labels) if x_labels is not None else [])]
    y_values = [str(value) for value in (list(y_labels) if y_labels is not None else [])]
    series = [
        str(value) for value in (list(series_names) if series_names is not None else [])
        if str(value)
    ]
    count = int(item_count if item_count is not None else max(len(x_values), len(y_values), 0))

    x_angle = 0
    x_tickvals = list(x_values)
    x_ticktext = list(x_values)
    bottom = 58
    if profile == "time_series":
        if len(x_values) > 24:
            x_angle, bottom = -45, 104
            x_tickvals, x_ticktext = _sample_ticks(x_values, 12)
        elif len(x_values) > 12:
            x_angle, bottom = -30, 88
    elif profile in {"category_x", "heatmap"} and x_values:
        maximum = max((_visual_length(value) for value in x_values), default=0)
        if len(x_values) <= 6 and maximum <= 16:
            x_angle, bottom = 0, 66
        elif len(x_values) <= 12:
            x_angle, bottom = -25, 88
        else:
            x_angle, bottom = -40, 108
        if profile != "heatmap" and len(x_values) > 18:
            x_tickvals, x_ticktext = _sample_ticks(x_values, 12)
        x_ticktext = [_wrap_axis_label(value, width=14, max_lines=2) for value in x_ticktext]

    y_tickvals = list(y_values)
    y_ticktext = [_wrap_axis_label(value, width=16, max_lines=2) for value in y_values]
    left = 72
    if profile in {"category_y", "heatmap"} and y_values:
        longest_line = max(
            (_visual_length(line) for value in y_ticktext for line in value.split("<br>")),
            default=0,
        )
        left = min(196, max(88, 42 + longest_line * 7))

    legend_units = sum(max(6, _visual_length(name)) + 3 for name in series)
    legend_rows = 0 if len(series) <= 1 else max(1, ceil(legend_units / 32))
    top = 72 + legend_rows * 24
    right = 30
    if profile == "heatmap":
        label_lines = max((text.count("<br>") + 1 for text in x_ticktext), default=1)
        top = max(top, 82 + label_lines * 18)
        right = 78

    if height is None:
        if profile == "category_y":
            resolved_height = max(360, min(900, 180 + max(count, 1) * 36))
        elif profile == "heatmap":
            resolved_height = max(430, min(920, 190 + max(count, 1) * 52))
        elif profile == "scatter":
            resolved_height = 500
        elif profile == "time_series":
            resolved_height = 410
        else:
            resolved_height = 380
    else:
        resolved_height = int(height)

    return {
        "profile": profile,
        "height": resolved_height,
        "margin": {"l": left, "r": right, "t": top, "b": bottom, "pad": 4},
        "x_tickangle": x_angle,
        "x_tickvals": x_tickvals,
        "x_ticktext": x_ticktext,
        "y_tickvals": y_tickvals,
        "y_ticktext": y_ticktext,
        "legend_rows": legend_rows,
    }


def chart_layout(
    fig,
    height: Optional[int] = None,
    *,
    profile: str = "cartesian",
    x_labels: Optional[Iterable[Any]] = None,
    y_labels: Optional[Iterable[Any]] = None,
    series_names: Optional[Iterable[Any]] = None,
    item_count: Optional[int] = None,
):
    if series_names is None:
        series_names = [
            trace.name for trace in fig.data
            if getattr(trace, "showlegend", None) is not False and getattr(trace, "name", None)
        ]
    config = chart_layout_config(
        profile=profile,
        x_labels=x_labels,
        y_labels=y_labels,
        series_names=series_names,
        item_count=item_count,
        height=height,
    )
    fig.update_layout(
        autosize=True,
        height=config["height"],
        margin=config["margin"],
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#FFFFFF",
        font=dict(family=CHART_FONT_FAMILY, color=COLORS["ink"], size=12),
        title=dict(x=.01, xanchor="left", y=.98, yanchor="top", font=dict(size=16, color=COLORS["ink"])),
        hoverlabel=dict(bgcolor="#FFFFFF", bordercolor=COLORS["grid"], font_size=12, font_family=CHART_FONT_FAMILY),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
            font=dict(family=CHART_FONT_FAMILY, color=COLORS["ink"], size=11),
        ),
        uniformtext=dict(minsize=10, mode="show"),
        coloraxis_colorbar=dict(
            thickness=12, len=.78,
            tickfont=dict(family=CHART_FONT_FAMILY, color=COLORS["ink"], size=10),
            title_font=dict(family=CHART_FONT_FAMILY, color=COLORS["ink"], size=11),
        ),
    )
    xaxis = dict(
        gridcolor=COLORS["grid"], zeroline=False, automargin=True,
        ticklabeloverflow="allow", tickangle=config["x_tickangle"],
        tickfont=dict(family=CHART_FONT_FAMILY, color=COLORS["ink"], size=11),
        title_font=dict(family=CHART_FONT_FAMILY, color=COLORS["ink"], size=12),
        title_standoff=14,
    )
    if config["x_tickvals"]:
        xaxis.update(tickmode="array", tickvals=config["x_tickvals"], ticktext=config["x_ticktext"])
    yaxis = dict(
        gridcolor=COLORS["grid"], zeroline=False, automargin=True,
        ticklabeloverflow="allow",
        tickfont=dict(family=CHART_FONT_FAMILY, color=COLORS["ink"], size=11),
        title_font=dict(family=CHART_FONT_FAMILY, color=COLORS["ink"], size=12),
        title_standoff=16,
    )
    if config["y_tickvals"]:
        yaxis.update(tickmode="array", tickvals=config["y_tickvals"], ticktext=config["y_ticktext"])
    fig.update_xaxes(**xaxis)
    fig.update_yaxes(**yaxis)
    for trace in fig.data:
        if isinstance(trace, go.Heatmap):
            trace.update(colorbar=dict(
                thickness=12,
                tickfont=dict(family=CHART_FONT_FAMILY, color=COLORS["ink"], size=10),
                title_font=dict(family=CHART_FONT_FAMILY, color=COLORS["ink"], size=11),
            ))
    return fig


def render_chart(fig, key: Optional[str] = None) -> None:
    """Render every Dashboard chart through one responsive Streamlit contract."""
    st.plotly_chart(
        fig,
        key=key,
        width="stretch",
        theme=None,
        config=PLOTLY_RENDER_CONFIG,
    )


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
        if source_name in {"发生了什么", "下一步"}:
            options.update({"minWidth": 280 if source_name == "发生了什么" else 360, "wrapText": True, "autoHeight": True})
        builder.configure_column(display_name, header_name=display_name, **options)

    options = builder.build()
    options.update({
        "localeText": AGGRID_ZH_CN,
        "animateRows": False,
        "paginationPageSizeSelector": [10, 20, 50, 100],
        "suppressCellFocus": True,
        "autoSizeStrategy": {"type": "fitGridWidth", "defaultMinWidth": 108},
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


def product_detail_frame(products: pd.DataFrame, classification: str = "全部商品") -> pd.DataFrame:
    """Filter a product action list without changing the fixed product matrix."""
    detail = products.copy(deep=True)
    if classification == "亏损商品":
        detail = detail.loc[detail["profit"].lt(0)].copy()
    elif classification != "全部商品":
        detail = detail.loc[detail["classification"].eq(classification)].copy()
    return detail.sort_values(["gmv", "orders"], ascending=[False, False]).reset_index(drop=True)


def localized_selectable_grid(
    data: pd.DataFrame,
    key: str,
    *,
    id_field: str,
    page_size: int = 20,
    height: Optional[int] = None,
) -> tuple[pd.DataFrame, Optional[str]]:
    """Render a searchable, filterable single-select grid and return its current preview."""
    source = data.copy(deep=True)
    display = localize_frame(source)
    query = st.text_input(
        "搜索商品",
        key="{}_search".format(key),
        placeholder="输入商品ID、名称、品类或分类",
        label_visibility="collapsed",
    ).strip()
    if query:
        matches = display.astype(str).apply(
            lambda column: column.str.contains(query, case=False, na=False, regex=False)
        ).any(axis=1)
        display = display.loc[matches].copy()

    builder = GridOptionsBuilder.from_dataframe(display)
    builder.configure_default_column(
        sortable=True, filter=True, resizable=True, wrapHeaderText=True,
        autoHeaderHeight=True, minWidth=108,
    )
    builder.configure_selection(
        selection_mode="single", use_checkbox=False, suppressRowClickSelection=False
    )
    builder.configure_pagination(enabled=True, paginationAutoPageSize=False, paginationPageSize=page_size)
    for index, source_name in enumerate(source.columns):
        display_name = label_for(source_name)
        options = {"pinned": "left"} if index == 0 else {}
        if source_name in PERCENT_FIELDS:
            options["valueFormatter"] = JsCode(
                "function(p){return p.value == null ? '不可用' : (p.value * 100).toFixed(2) + '%';}"
            )
        elif source_name in AMOUNT_FIELDS:
            options["valueFormatter"] = JsCode(
                "function(p){return p.value == null ? '不可用' : Number(p.value).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});}"
            )
        builder.configure_column(display_name, header_name=display_name, **options)
    options = builder.build()
    options.update({
        "localeText": AGGRID_ZH_CN,
        "animateRows": False,
        "paginationPageSizeSelector": [10, 20, 50, 100],
        "rowSelection": {"mode": "singleRow", "enableClickSelection": True, "checkboxes": False},
        "autoSizeStrategy": {"type": "fitGridWidth", "defaultMinWidth": 108},
    })
    response = AgGrid(
        display,
        gridOptions=options,
        height=height or max(260, min(620, 120 + min(max(len(display), 1), page_size) * 34)),
        key=key,
        theme="streamlit",
        allow_unsafe_jscode=True,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        update_on=["selectionChanged", "filterChanged", "sortChanged"],
        custom_css={
            ".ag-root-wrapper": {"border": "none", "border-radius": "5px"},
            ".ag-header": {"background-color": COLORS["paper"], "font-weight": "600"},
            ".ag-row-hover": {"background-color": "#EEF5F2 !important"},
            ".ag-row-selected": {"background-color": "#DCEDE8 !important"},
        },
    )
    visible = response.data if isinstance(response.data, pd.DataFrame) else display
    selected = response.selected_rows
    selected_id = None
    id_label = label_for(id_field)
    if isinstance(selected, pd.DataFrame) and not selected.empty and id_label in selected:
        selected_id = str(selected.iloc[0][id_label])
    elif isinstance(selected, list) and selected and id_label in selected[0]:
        selected_id = str(selected[0][id_label])
    return visible.copy(deep=True), selected_id


def _display_market(value: Any, source: Optional[str]) -> Any:
    return value_for(value, "region") if source == "region" else value


def market_category_heatmap(data: pd.DataFrame, mode: str):
    if data is None or data.empty:
        return None
    source = data.copy(deep=True)
    market_source = source["market_source"].dropna().iloc[0] if "market_source" in source and source["market_source"].notna().any() else None
    source["market_label"] = source["market"].map(lambda item: _display_market(item, market_source))
    source["category_label"] = source["category"].map(lambda item: value_for(item, "category"))
    market_order = source.groupby("market_label")["gmv"].sum().sort_values(ascending=False).index.tolist()
    category_order = source.groupby("category_label")["orders"].sum().sort_values(ascending=False).index.tolist()
    metric = "order_share" if mode == "订单偏好" else "profit"
    pivot = source.pivot(index="market_label", columns="category_label", values=metric).reindex(
        index=market_order, columns=category_order
    )
    lookup = source.set_index(["market_label", "category_label"])
    custom = []
    text_values = []
    for market in pivot.index:
        custom_row = []
        text_row = []
        for category in pivot.columns:
            row = lookup.loc[(market, category)] if (market, category) in lookup.index else None
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            if row is None:
                values = [None] * 8
            else:
                values = [
                    row.get("order_share"), row.get("orders"), row.get("units"), row.get("customers"),
                    row.get("gmv"), row.get("profit"), row.get("profit_rate"), row.get("return_rate"),
                ]
            custom_row.append(values)
            cell = pivot.loc[market, category]
            if pd.isna(cell):
                text_row.append("-")
            elif mode == "订单偏好":
                text_row.append("{:.1%}".format(cell))
            else:
                text_row.append("{:+,.0f}".format(cell))
        custom.append(custom_row)
        text_values.append(text_row)

    if mode == "收益贡献":
        finite = pd.to_numeric(source["profit"], errors="coerce").dropna()
        if finite.empty:
            return None
        bound = max(abs(float(finite.min())), abs(float(finite.max())), 1.0)
        colorscale = [[0, COLORS["coral"]], [.5, "#F2F3F1"], [1, COLORS["teal"]]]
        zmin, zmax, zmid = -bound, bound, 0
    else:
        colorscale = [[0, "#EEF3F0"], [1, COLORS["teal"]]]
        zmin, zmax, zmid = 0, max(float(source["order_share"].max()), .01), None
    trace = go.Heatmap(
        z=pivot.values,
        x=pivot.columns,
        y=pivot.index,
        text=text_values,
        texttemplate="%{text}",
        customdata=custom,
        colorscale=colorscale,
        zmin=zmin,
        zmax=zmax,
        zmid=zmid,
        colorbar=dict(title="订单占比" if mode == "订单偏好" else "利润额"),
        hovertemplate=(
            "市场 %{y}<br>品类 %{x}<br>订单占比 %{customdata[0]:.2%}"
            "<br>订单 %{customdata[1]:,.0f}<br>销量 %{customdata[2]:,.0f}"
            "<br>客户 %{customdata[3]:,.0f}<br>GMV（成交总额）%{customdata[4]:,.2f}"
            "<br>利润额 %{customdata[5]:,.2f}<br>利润率 %{customdata[6]:.2%}"
            "<br>退货率 %{customdata[7]:.2%}<extra></extra>"
        ),
    )
    fig = go.Figure(trace)
    fig.update_layout(title="市场×品类决策热力图", xaxis_title="品类", yaxis_title="市场")
    fig.update_xaxes(side="top")
    return chart_layout(
        fig,
        profile="heatmap",
        x_labels=pivot.columns,
        y_labels=pivot.index,
        item_count=len(pivot.index),
    )


def market_strategy_heatmap(data: pd.DataFrame):
    if data is None or data.empty:
        return None
    source = data.copy(deep=True)
    market_source = source["market_source"].dropna().iloc[0] if "market_source" in source and source["market_source"].notna().any() else None
    source["market_label"] = source["market"].map(lambda item: _display_market(item, market_source))
    source = source.sort_values("gmv", ascending=False)
    columns = ["规模", "利润质量", "退货健康度", "履约健康度"]
    health_fields = ["scale_health", "profit_health", "return_health", "delivery_health"]
    actual_fields = ["gmv_share", "profit_rate", "return_rate", "delivery_p90"]
    benchmark_fields = ["scale_benchmark", "portfolio_profit_rate", "portfolio_return_rate", "delivery_p90_benchmark"]
    z, text_values, custom = [], [], []
    for row in source.itertuples(index=False):
        z_row, text_row, custom_row = [], [], []
        for index, (health, actual, benchmark) in enumerate(zip(health_fields, actual_fields, benchmark_fields)):
            health_value = getattr(row, health, np.nan)
            actual_value = getattr(row, actual, np.nan)
            benchmark_value = getattr(row, benchmark, np.nan)
            z_row.append(health_value)
            if pd.isna(actual_value):
                actual_text = "证据缺失"
                benchmark_text = "不可用"
            elif index < 3:
                actual_text = "{:.2%}".format(actual_value)
                benchmark_text = "{:.2%}".format(benchmark_value) if pd.notna(benchmark_value) else "不可用"
            else:
                actual_text = "{:.1f}天".format(actual_value)
                benchmark_text = "{:.1f}天".format(benchmark_value) if pd.notna(benchmark_value) else "不可用"
            text_row.append(actual_text)
            custom_row.append([actual_text, benchmark_text, row.strategy, row.strategy_confidence])
        z.append(z_row)
        text_values.append(text_row)
        custom.append(custom_row)
    fig = go.Figure(go.Heatmap(
        z=z, x=columns, y=source["market_label"], text=text_values, texttemplate="%{text}",
        customdata=custom, zmin=0, zmax=1,
        colorscale=[[0, COLORS["coral"]], [.5, COLORS["amber"]], [1, COLORS["teal"]]],
        colorbar=dict(title="相对健康度"),
        hovertemplate=(
            "市场 %{y}<br>维度 %{x}<br>实际值 %{customdata[0]}<br>当前组合基准 %{customdata[1]}"
            "<br>策略 %{customdata[2]}<br>置信度 %{customdata[3]}<extra></extra>"
        ),
    ))
    fig.update_layout(title="市场策略矩阵", xaxis_title="", yaxis_title="市场")
    fig.update_xaxes(side="top")
    return chart_layout(
        fig,
        profile="heatmap",
        x_labels=columns,
        y_labels=source["market_label"],
        item_count=len(source),
    )


def composition_chart(data: pd.DataFrame, title: str, dimension_label: str):
    if data is None or data.empty:
        return None
    source = data.copy(deep=True)
    if dimension_label == "品类":
        source["dimension_value"] = source["dimension_value"].map(lambda item: value_for(item, "category"))
    fig = px.bar(
        source.sort_values("gmv", ascending=True),
        x="gmv", y="dimension_value", orientation="h", text="gmv_share", title=title,
        color="gmv_share", color_continuous_scale=[[0, "#DDE3E0"], [1, COLORS["blue"]]],
        labels={"gmv": "GMV（成交总额）", "dimension_value": dimension_label, "gmv_share": "GMV占比"},
        custom_data=["customers", "orders", "gmv_share"],
    )
    fig.update_traces(
        texttemplate="%{text:.1%}",
        hovertemplate=(
            "%{y}<br>客户 %{customdata[0]:,.0f}<br>订单 %{customdata[1]:,.0f}"
            "<br>GMV（成交总额）%{x:,.2f}<br>占比 %{customdata[2]:.2%}<extra></extra>"
        ),
    )
    fig.update_layout(coloraxis_showscale=False)
    return chart_layout(
        fig,
        profile="category_y",
        y_labels=source["dimension_value"],
        item_count=len(source),
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
    return chart_layout(
        fig,
        profile="time_series",
        x_labels=data["month"],
        series_names=["不完整月份"] if incomplete else [],
        item_count=len(data),
    )


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
    return chart_layout(
        fig,
        profile="category_y",
        y_labels=ordered[dimension],
        item_count=len(ordered),
    )


def result_or_notice(bundle, name):
    result = bundle.results.get(name)
    if not result or result.status != AnalysisStatus.SUCCESS:
        st.warning(result.message if result else "模块不可用")
        return None
    if result.message:
        st.info(result.message)
    return result
