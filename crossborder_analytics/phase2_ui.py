"""Business-facing Phase 2 workspaces for the Streamlit dashboard."""
from __future__ import annotations

from datetime import date, timedelta
from html import escape
import json
from typing import Mapping

import pandas as pd
import plotly.express as px
import streamlit as st

from .localization import STATUS_LABELS, value_for
from .phase2_models import AnomalyStatus, WorkItemStatus
from .phase2_storage import ArtifactStore
from .ui import COLORS, chart_layout, localized_grid, money, page_header, pct, render_chart


METRIC_LABELS = {
    "gmv": "GMV（成交总额）",
    "orders": "订单数",
    "aov": "AOV（平均客单价）",
    "units": "销量",
    "customers": "客户数",
    "profit": "利润额",
    "profit_margin": "利润率",
    "return_rate": "退货率",
    "growth_rate": "增长率",
    "product_contribution": "商品贡献率",
    "market_contribution": "市场/品类贡献率",
    "market_quality_score": "市场质量评分",
}
ENTITY_LABELS = {"global": "整体", "market": "市场", "category": "品类", "sku": "商品"}
RULE_LABELS = {
    "ANOM-GMV-DROP": "GMV 明显下降",
    "ANOM-GMV-SPIKE": "GMV 异常增长",
    "ANOM-MARGIN-DROP": "利润率明显下降",
    "ANOM-HIGH-SALES-LOW-MARGIN": "高销售低利润",
    "ANOM-HIGH-RETURN": "退货率偏高",
    "ANOM-MARKET-UNHEALTHY-GROWTH": "增长伴随质量风险",
    "ANOM-MIX-SHIFT": "贡献结构明显变化",
    "ANOM-AOV-DROP": "客单价明显下降",
    "ANOM-HERO-GROWTH-RISK": "爆品增长伴随质量风险",
}
DIAGNOSIS_LABELS = {
    "VERIFIED_DRIVER": "数据拆解已验证",
    "LIKELY_DRIVER": "较可能驱动",
    "UNRESOLVED": "原因尚未确定",
    "DATA_ISSUE": "先修复数据",
}
ACTION_TYPE_LABELS = {
    "INVESTIGATE": "调查核实",
    "OPTIMIZE": "运营优化",
    "SCALE": "小范围增量",
    "LIMIT": "控制风险",
    "DATA_REQUEST": "补充数据",
}
WORKFLOW_LABELS = {
    "TODO": "待处理",
    "IN_PROGRESS": "处理中",
    "REVIEW": "待复盘",
    "COMPLETED": "已完成",
    "DISMISSED": "暂不处理",
    "WAITING_DATA": "等待数据或完整周期",
}
ANALYSIS_STATUS_LABELS = {
    "DETECTED": "已触发",
    "RECOVERED": "已恢复",
    "SUPPRESSED": "未参与判断",
}


def _artifacts(bundle):
    artifacts = getattr(bundle, "artifacts", None)
    if artifacts is None or artifacts.data_quality is None:
        page_header("分析基础设施", "本次运行没有可用的 Phase 2 对象")
        st.error("指标、质量或证据链未成功生成。请在模块状态中检查 Phase 2 错误。")
        return None
    return artifacts


def _display_frame(records) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    for column in frame.columns:
        if frame[column].map(lambda value: isinstance(value, (dict, list, tuple))).any():
            frame[column] = frame[column].map(
                lambda value: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list, tuple)) else value
            )
    return frame


MARKET_STATUS_COLORS = {
    "健康增长": COLORS["teal"],
    "风险增长": COLORS["coral"],
    "稳定经营": COLORS["blue"],
    "收缩待修复": COLORS["amber"],
    "低价值市场": "#77827D",
    "样本不足": "#AAB3AF",
    "数据不足": COLORS["ink"],
}
PRODUCT_OPPORTUNITY_COLORS = {
    "扩量机会": COLORS["teal"],
    "市场扩张机会": COLORS["blue"],
    "利润修复机会": COLORS["amber"],
    "高风险增长": COLORS["coral"],
    "观察机会": "#77827D",
    "样本不足": "#AAB3AF",
    "数据不足": COLORS["ink"],
}


def _records(items) -> pd.DataFrame:
    return _display_frame([item.to_dict() for item in items])


def render_market_growth(bundle) -> None:
    artifacts = _artifacts(bundle)
    if artifacts is None:
        return
    page_header("市场增长", "跨周期识别增长质量、主要贡献与可执行保护条件")
    items = artifacts.market_opportunities
    if not items:
        st.info("当前没有两个完整可比较周期，市场增长判断尚不可用。")
        return
    frame = _records(items)
    counts = frame.status.value_counts()
    healthy = int(counts.get("健康增长", 0))
    risky = int(counts.get("风险增长", 0))
    unknown = int(counts.get("样本不足", 0) + counts.get("数据不足", 0))
    top_growth = frame.sort_values("gmv_change", ascending=False).iloc[0]
    margin_rows = frame.dropna(subset=["profit_margin_change"])
    worst_margin = margin_rows.sort_values("profit_margin_change").iloc[0].market if not margin_rows.empty else "无法判断"
    cols = st.columns(5)
    cols[0].metric("健康增长市场", healthy)
    cols[1].metric("风险增长市场", risky)
    cols[2].metric("增长贡献最高", str(top_growth.market))
    cols[3].metric("利润恶化最明显", str(worst_margin))
    cols[4].metric("当前无法判断", unknown)

    st.subheader("市场增长矩阵")
    chart_data = frame.dropna(subset=["gmv_growth_rate", "quality_score"]).copy()
    if chart_data.empty:
        st.info("市场质量评分需要两期样本以及利润和退货字段；当前展示行动清单。")
    else:
        fig = px.scatter(
            chart_data, x="gmv_growth_rate", y="quality_score", size="current_gmv", color="status",
            hover_name="market", color_discrete_map=MARKET_STATUS_COLORS,
            labels={"gmv_growth_rate": "GMV（成交总额）增长率", "quality_score": "市场质量评分", "current_gmv": "当前GMV（成交总额）", "status": "市场状态"},
        )
        fig.add_vline(x=0.20, line_color=COLORS["grid"], line_dash="dot")
        render_chart(chart_layout(fig, profile="scatter", series_names=chart_data.status.unique(), item_count=len(chart_data)))
    st.caption("气泡大小表示当前GMV（成交总额）。矩阵仅改变预览，固定市场状态不随页面筛选变化。")

    st.subheader("市场行动清单")
    statuses = [name for name in MARKET_STATUS_COLORS if name in set(frame.status)]
    selected = st.multiselect("市场状态", statuses, default=statuses, key="market_growth_status")
    filtered = frame.loc[frame.status.isin(selected)] if selected else frame.iloc[0:0]
    visible_columns = [
        "market", "status", "current_gmv", "gmv_change", "gmv_growth_rate", "primary_driver",
        "recommended_action", "guardrail_metrics", "validation_period", "stop_condition", "evidence_ids",
    ]
    visible = localized_grid(filtered[visible_columns], "market_growth_actions", page_size=20)
    st.download_button(
        "下载当前市场行动清单（{:,}项）".format(len(visible)),
        data=visible.to_csv(index=False).encode("utf-8-sig"), file_name="市场增长行动清单.csv",
        mime="text/csv", icon=":material/download:", key="download_market_growth",
    )

    if not filtered.empty:
        selected_market = st.selectbox("选择市场查看详情", filtered.market.tolist(), key="market_growth_detail")
        item = next(value for value in items if value.market == selected_market)
        st.markdown("#### {} · {}".format(item.market, item.status.value))
        detail_cols = st.columns(4)
        detail_cols[0].metric("当前GMV（成交总额）", money(item.current_gmv, bundle.context.metadata.get("target_currency", "")), pct(item.gmv_growth_rate))
        detail_cols[1].metric("订单", "{:,}".format(item.current_orders), pct(item.order_growth_rate))
        detail_cols[2].metric("利润率", pct(item.profit_margin), "{} 个百分点".format("无法判断" if item.profit_margin_change is None else "{:+.1f}".format(item.profit_margin_change * 100)))
        detail_cols[3].metric("退货率", pct(item.return_rate), "{} 个百分点".format("无法判断" if item.return_rate_change is None else "{:+.1f}".format(item.return_rate_change * 100)))
        left, right = st.columns(2)
        with left:
            st.markdown("##### 主要增长品类")
            localized_grid(_display_frame(item.top_categories), "market_growth_categories", search=False, page_size=10)
        with right:
            st.markdown("##### 主要增长SKU")
            localized_grid(_display_frame(item.top_skus), "market_growth_skus", search=False, page_size=10)
        st.info("建议动作：{}\n\n验证周期：{}\n\n停止条件：{}".format(item.recommended_action, item.validation_period, item.stop_condition))
        st.caption("证据编号：{} · 限制：{}".format("、".join(item.evidence_ids), "；".join(item.limitations)))


def render_product_opportunities(bundle) -> None:
    artifacts = _artifacts(bundle)
    if artifacts is None:
        return
    page_header("产品机会", "在经营分类之外识别扩量、扩市场、修复与观察机会")
    items = artifacts.product_opportunities
    if not items:
        st.info("当前没有两个完整可比较周期或商品字段，产品机会判断尚不可用。")
        return
    frame = _records(items)
    counts = frame.opportunity_type.value_counts()
    cols = st.columns(5)
    cols[0].metric("扩量机会", int(counts.get("扩量机会", 0)))
    cols[1].metric("市场扩张机会", int(counts.get("市场扩张机会", 0)))
    cols[2].metric("利润修复商品", int(counts.get("利润修复机会", 0)))
    cols[3].metric("高风险增长商品", int(counts.get("高风险增长", 0)))
    excluded = int(artifacts.opportunity_summary.get("excluded_low_sample_products", 0))
    cols[4].metric("样本不足商品", int(counts.get("样本不足", 0)) + excluded)

    st.subheader("产品机会矩阵")
    mode = st.segmented_control(
        "矩阵视角", ["增长率 × 利润率", "市场覆盖 × 市场增长贡献", "GMV规模 × 退货风险"],
        default="增长率 × 利润率", key="product_opportunity_matrix",
    ) or "增长率 × 利润率"
    axes = {
        "增长率 × 利润率": ("gmv_growth_rate", "profit_margin", "GMV（成交总额）增长率", "利润率"),
        "市场覆盖 × 市场增长贡献": ("market_coverage", "market_growth_contribution", "市场覆盖数", "市场增长贡献"),
        "GMV规模 × 退货风险": ("current_gmv", "return_rate", "当前GMV（成交总额）", "退货率"),
    }
    x, y, x_label, y_label = axes[mode]
    chart_data = frame.dropna(subset=[x, y]).copy()
    if chart_data.empty:
        st.info("当前视角缺少可用字段，可切换矩阵视角或查看机会清单。")
    else:
        fig = px.scatter(
            chart_data, x=x, y=y, size="current_gmv", color="opportunity_type",
            hover_name="product_name", hover_data=["product_id", "operating_status"],
            color_discrete_map=PRODUCT_OPPORTUNITY_COLORS,
            labels={x: x_label, y: y_label, "current_gmv": "当前GMV（成交总额）", "opportunity_type": "机会类型"},
        )
        render_chart(chart_layout(fig, profile="scatter", series_names=chart_data.opportunity_type.unique(), item_count=len(chart_data)))
    st.caption(
        "视角切换只改变矩阵坐标；商品机会类型由固定跨周期规则生成。跨两期合计少于 {} 单的 {:,} 个商品只计入样本不足总数，不生成确定性机会或行动项。".format(
            artifacts.opportunity_summary.get("product_candidate_min_orders", 3), excluded,
        )
    )

    st.subheader("产品机会清单")
    types = [name for name in PRODUCT_OPPORTUNITY_COLORS if name in set(frame.opportunity_type)]
    selected_types = st.multiselect("机会类型", types, default=types, key="product_opportunity_type")
    filtered = frame.loc[frame.opportunity_type.isin(selected_types)] if selected_types else frame.iloc[0:0]
    visible_columns = [
        "product_id", "product_name", "category", "opportunity_type", "operating_status",
        "target_market", "primary_customer_group", "current_gmv", "gmv_growth_rate", "profit_margin", "return_rate",
        "rationale", "recommended_action", "guardrail_metrics", "stop_condition", "evidence_ids",
    ]
    visible = localized_grid(filtered[visible_columns], "product_opportunity_actions", page_size=20)
    st.download_button(
        "下载当前产品机会清单（{:,}项）".format(len(visible)),
        data=visible.to_csv(index=False).encode("utf-8-sig"), file_name="产品机会清单.csv",
        mime="text/csv", icon=":material/download:", key="download_product_opportunities",
    )
    if not filtered.empty:
        labels = {
            (str(row.product_id) if str(row.product_name) == str(row.product_id) else "{} · {}".format(row.product_name, row.product_id)): row.product_id
            for row in filtered.itertuples()
        }
        selected_label = st.selectbox("选择商品查看机会详情", list(labels), key="product_opportunity_detail")
        item = next(value for value in items if value.product_id == labels[selected_label])
        st.markdown("#### {} · {}".format(item.product_name, item.opportunity_type.value))
        st.caption("SKU：{} · 品类：{} · 当前经营状态：{}".format(item.product_id, item.category, item.operating_status))
        detail_cols = st.columns(4)
        detail_cols[0].metric("当前GMV（成交总额）", money(item.current_gmv, bundle.context.metadata.get("target_currency", "")), pct(item.gmv_growth_rate))
        detail_cols[1].metric("利润率", pct(item.profit_margin), "{} 个百分点".format("无法判断" if item.profit_margin_change is None else "{:+.1f}".format(item.profit_margin_change * 100)))
        detail_cols[2].metric("退货率", pct(item.return_rate), "{} 个百分点".format("无法判断" if item.return_rate_change is None else "{:+.1f}".format(item.return_rate_change * 100)))
        detail_cols[3].metric("市场覆盖", item.market_coverage)
        st.markdown("**判断依据**：{}".format(item.rationale))
        st.caption("主要客户群：{} · 高价值客户购买占比：{}".format(
            item.primary_customer_group, pct(item.high_value_customer_share),
        ))
        st.info("建议动作：{}\n\n主要市场：{} · 测试市场：{}\n\n验证周期：{}\n\n停止条件：{}".format(
            item.recommended_action, item.primary_market, item.target_market, item.validation_period, item.stop_condition,
        ))
        st.caption("证据编号：{} · 限制：{}".format("、".join(item.evidence_ids), "；".join(item.limitations)))


def _entity_name(entity_type: str, name: str) -> str:
    if entity_type == "market":
        return str(value_for(name, "region"))
    if entity_type == "category":
        return str(value_for(name, "category"))
    if entity_type == "global":
        return "整体业务"
    return str(name)


def _period_label(snapshot) -> str:
    if snapshot is None:
        return "周期未知"
    start, end = pd.Timestamp(snapshot.period_start), pd.Timestamp(snapshot.period_end)
    if snapshot.period_type == "month":
        return "{}年{}月".format(start.year, start.month)
    if snapshot.period_type == "week":
        return "{}月{}日-{}月{}日".format(start.month, start.day, end.month, end.day)
    return "{} 至 {}".format(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))


def _format_value(value, metric_id: str, currency: str = "") -> str:
    if value is None or pd.isna(value):
        return "不可用"
    if metric_id in {"profit_margin", "return_rate", "growth_rate", "product_contribution", "market_contribution"}:
        return "{:.1%}".format(float(value))
    if metric_id in {"gmv", "aov", "profit"}:
        return money(float(value), currency)
    if metric_id in {"orders", "units", "customers"}:
        return "{:,.0f}".format(float(value))
    return "{:,.2f}".format(float(value))


def _format_impact(anomaly, current) -> str:
    if anomaly.impact_amount is None:
        return _change_text(anomaly.change_rate)
    currency = current.currency if current else ""
    if anomaly.impact_type == "aov_change":
        return "{} / 单".format(money(anomaly.impact_amount, currency))
    if anomaly.impact_type in {"profit_margin_change_pp", "contribution_change_pp"}:
        return "{:+.1f} 个百分点".format(float(anomaly.impact_amount) * 100)
    return money(anomaly.impact_amount, currency)


def _format_insight_impact(insight, current) -> str:
    if insight.impact_amount is None:
        return _change_text(insight.change_rate)
    currency = current.currency if current else ""
    if insight.metric_id == "aov":
        return "{} / 单".format(money(insight.impact_amount, currency))
    if insight.metric_id in {"profit_margin", "market_contribution"}:
        return "{:+.1f} 个百分点".format(float(insight.impact_amount) * 100)
    return money(insight.impact_amount, currency)


def _change_text(rate) -> str:
    if rate is None or pd.isna(rate):
        return "变化不可用"
    return "{} {:.1%}".format("上升" if rate >= 0 else "下降", abs(float(rate)))


def _snapshot_maps(artifacts):
    by_id = {item.snapshot_id: item for item in artifacts.metric_snapshots}
    exact = {
        (item.metric_id, item.entity_type, item.entity_id, item.period_start): item
        for item in artifacts.metric_snapshots
    }
    return by_id, exact


def _work_item_store(bundle):
    path = bundle.metadata.get("artifact_store_path") if getattr(bundle, "metadata", None) else None
    return ArtifactStore(path) if path else None


def _work_item_map(bundle) -> dict:
    store = _work_item_store(bundle)
    scope_id = bundle.metadata.get("scope_id") if getattr(bundle, "metadata", None) else None
    if not store or not scope_id:
        return {}
    return {item.anomaly_id: item for item in store.work_items(scope_id)}


def _default_workflow_status(anomaly) -> str:
    if str(anomaly.status) == "SUPPRESSED":
        return "WAITING_DATA"
    if str(anomaly.status) == "RECOVERED":
        return "COMPLETED"
    return "TODO"


def _workflow_value(anomaly, work_item) -> str:
    return str(work_item.workflow_status) if work_item else _default_workflow_status(anomaly)


def _latest_period(insights, snapshot_by_id) -> str | None:
    periods = [
        snapshot_by_id[item.current_snapshot_id].period_start
        for item in insights
        if item.current_snapshot_id in snapshot_by_id
    ]
    return max(periods) if periods else None


def latest_priority_insights(artifacts, limit: int = 3):
    """Return latest-period P0/P1 insights without duplicate entity/metric cards."""
    snapshot_by_id, _ = _snapshot_maps(artifacts)
    candidates = [item for item in artifacts.insights if item.type == "ANOMALY"]
    latest = _latest_period(candidates, snapshot_by_id)
    if latest:
        candidates = [
            item for item in candidates
            if item.current_snapshot_id in snapshot_by_id
            and snapshot_by_id[item.current_snapshot_id].period_start == latest
        ]
    candidates = sorted(candidates, key=lambda item: (-item.priority_score, item.insight_id))
    output, seen = [], set()
    for item in candidates:
        if item.priority not in {"P0", "P1"}:
            continue
        key = (item.entity_type, item.entity_id, item.metric_id)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
        if len(output) == limit:
            break
    return output


def insight_period_label(insight, artifacts) -> str:
    snapshot_by_id, _ = _snapshot_maps(artifacts)
    return _period_label(snapshot_by_id.get(insight.current_snapshot_id))


def insight_title(insight) -> str:
    return "{} · {}".format(
        _entity_name(insight.entity_type, insight.entity_name),
        METRIC_LABELS.get(insight.metric_id, insight.metric_id),
    )


def _localized_action(action: str, entity_type: str, entity_name: str) -> str:
    localized = _entity_name(entity_type, entity_name)
    return str(action).replace(str(entity_name), localized) if entity_name else str(action)


def insight_action_summary(insight, artifacts) -> str:
    recommendation = next(
        (item for item in artifacts.recommendations if item.recommendation_id in insight.recommendation_ids),
        None,
    )
    action = recommendation.action if recommendation else insight.recommendation_summary
    return _localized_action(action, insight.entity_type, insight.entity_name)


def _workspace_metrics(artifacts):
    snapshot_by_id, _ = _snapshot_maps(artifacts)
    latest = _latest_period(artifacts.insights, snapshot_by_id)
    detected = [
        item for item in artifacts.anomalies
        if str(item.status) == "DETECTED"
        and item.current_snapshot_id in snapshot_by_id
        and (latest is None or snapshot_by_id[item.current_snapshot_id].period_start == latest)
    ]
    high = [
        item for item in artifacts.insights
        if item.priority in {"P0", "P1"}
        and item.current_snapshot_id in snapshot_by_id
        and (latest is None or snapshot_by_id[item.current_snapshot_id].period_start == latest)
    ]
    latest_label = "暂无完整周期"
    if latest:
        sample = next((item for item in artifacts.metric_snapshots if item.period_start == latest), None)
        latest_label = _period_label(sample)
    cols = st.columns(4)
    cols[0].metric("数据可信度", "{}级 · {:.0f}".format(artifacts.data_quality.quality_rating, artifacts.data_quality.quality_score))
    cols[1].metric("本期异常", "{:,}".format(len(detected)))
    cols[2].metric("本期优先处理", "{:,}".format(len(high)))
    cols[3].metric("最近完整周期", latest_label)


def _risk_finding(anomaly) -> str:
    entity = _entity_name(anomaly.entity_type, anomaly.entity_name)
    if str(anomaly.status) == "SUPPRESSED":
        reason = "；".join(anomaly.limitations) or "样本、质量或能力门槛不足"
        return "{} · 本周期未参与异常判断 · {}".format(entity, reason)
    if str(anomaly.status) == "RECOVERED":
        return "{} · 上一周期异常已恢复 · 当前不再达到规则门槛".format(entity)
    return "{} · {} · {}".format(
        entity,
        RULE_LABELS.get(anomaly.rule_id, "指标达到异常门槛"),
        _change_text(anomaly.change_rate),
    )


def _next_action(anomaly, recommendation) -> str:
    if str(anomaly.status) == "SUPPRESSED":
        return "等待完整周期或补齐门槛数据后自动重新评估"
    if str(anomaly.status) == "RECOVERED":
        return "确认保护指标稳定后关闭任务，继续周期监测"
    if recommendation:
        return _localized_action(recommendation.action, anomaly.entity_type, anomaly.entity_name)
    return "建立调查任务，补充证据后再决定经营动作"


def _risk_export_frame(items) -> pd.DataFrame:
    records = []
    for item in items:
        anomaly = item["anomaly"]
        insight = item.get("insight")
        diagnosis = item.get("diagnosis")
        recommendation = item.get("recommendation")
        current, baseline = item.get("current"), item.get("baseline")
        work_item = item.get("work_item")
        records.append({
            "priority": insight.priority if insight else None,
            "priority_score": insight.priority_score if insight else None,
            "analysis_status": str(anomaly.status),
            "analysis_status_label": ANALYSIS_STATUS_LABELS.get(str(anomaly.status), str(anomaly.status)),
            "workflow_status": _workflow_value(anomaly, work_item),
            "workflow_status_label": WORKFLOW_LABELS.get(_workflow_value(anomaly, work_item), _workflow_value(anomaly, work_item)),
            "owner": work_item.owner if work_item else "",
            "due_date": work_item.due_date if work_item else None,
            "resolution_note": work_item.resolution_note if work_item else "",
            "updated_at": work_item.updated_at if work_item else None,
            "period_start": current.period_start if current else None,
            "period_end": current.period_end if current else None,
            "is_complete_period": current.is_complete_period if current else None,
            "entity_type": anomaly.entity_type,
            "entity_id": anomaly.entity_id,
            "entity_name": _entity_name(anomaly.entity_type, anomaly.entity_name),
            "metric_id": anomaly.metric_id,
            "metric_name": METRIC_LABELS.get(anomaly.metric_id, anomaly.metric_id),
            "current_value": anomaly.current_value,
            "baseline_value": anomaly.baseline_value,
            "absolute_change": anomaly.absolute_change,
            "change_rate": anomaly.change_rate,
            "impact_amount": anomaly.impact_amount,
            "impact_type": anomaly.impact_type,
            "severity": str(anomaly.severity),
            "rule_id": anomaly.rule_id,
            "rule_name": RULE_LABELS.get(anomaly.rule_id, anomaly.rule_id),
            "diagnosis_status": str(diagnosis.status) if diagnosis else None,
            "diagnosis_finding": diagnosis.finding if diagnosis else None,
            "primary_driver": diagnosis.primary_driver if diagnosis else None,
            "driver_contributions": json.dumps(diagnosis.driver_contributions, ensure_ascii=False) if diagnosis else None,
            "explained_share": diagnosis.explained_share if diagnosis else None,
            "confidence_score": diagnosis.confidence_score if diagnosis else None,
            "recommended_action": _next_action(anomaly, recommendation),
            "owner_role": recommendation.owner_role if recommendation else None,
            "expected_metric": recommendation.expected_metric if recommendation else None,
            "guardrail_metrics": "、".join(recommendation.guardrail_metrics) if recommendation else None,
            "validation_period": recommendation.validation_period if recommendation else None,
            "stop_condition": recommendation.stop_condition if recommendation else None,
            "limitations": "；".join(anomaly.limitations),
            "evidence_ids": "、".join(anomaly.evidence_ids),
            "anomaly_id": anomaly.anomaly_id,
            "insight_id": insight.insight_id if insight else None,
        })
    return pd.DataFrame(records)


def _download_csv(frame: pd.DataFrame, file_name: str, label: str, key: str) -> None:
    st.download_button(
        label, data=frame.to_csv(index=False).encode("utf-8-sig"), file_name=file_name,
        mime="text/csv", icon=":material/download:", key=key,
    )


def _render_work_item_editor(bundle, anomaly, insight, recommendation, work_item, key_prefix: str) -> None:
    store = _work_item_store(bundle)
    scope_id = bundle.metadata.get("scope_id") if getattr(bundle, "metadata", None) else None
    if not store or not scope_id:
        st.info("当前分析后端未启用任务持久化，可先下载清单线下处理。")
        return
    default_status = _workflow_value(anomaly, work_item)
    options = [str(item) for item in WorkItemStatus]
    default_due = pd.Timestamp(work_item.due_date).date() if work_item and work_item.due_date else date.today() + timedelta(days=30)
    default_owner = work_item.owner if work_item else (recommendation.owner_role if recommendation else "")
    with st.form("{}_{}".format(key_prefix, anomaly.anomaly_id)):
        fields = st.columns((1, 1.2, 1))
        status = fields[0].selectbox(
            "任务状态", options, index=options.index(default_status),
            format_func=lambda value: WORKFLOW_LABELS.get(value, value),
        )
        owner = fields[1].text_input("负责人", value=default_owner, placeholder="填写具体负责人或团队")
        due_date = fields[2].date_input("计划完成日期", value=default_due)
        note = st.text_area(
            "处理记录与结论", value=work_item.resolution_note if work_item else "",
            placeholder="记录已核查内容、采取的动作、验证结果或暂不处理原因",
        )
        submitted = st.form_submit_button("保存处理进度", type="primary")
    if submitted:
        if status == "COMPLETED" and not note.strip():
            st.error("标记已完成前，请填写处理结论。")
        elif not owner.strip() and status not in {"DISMISSED", "WAITING_DATA"}:
            st.error("请填写负责人。")
        else:
            store.save_work_item(
                scope_id, anomaly.anomaly_id, insight.insight_id if insight else None,
                status, owner, due_date.isoformat() if due_date else None, note,
            )
            st.success("处理进度已保存。")
            st.rerun()


def build_risk_items(artifacts, work_items: Mapping[str, object] | None = None) -> list[dict]:
    """Join generated artifacts with mutable task state for display and export."""
    work_items = work_items or {}
    snapshot_by_id, _ = _snapshot_maps(artifacts)
    insight_by_anomaly = {item.anomaly_id: item for item in artifacts.insights if item.anomaly_id}
    diagnosis_by_id = {item.diagnosis_id: item for item in artifacts.diagnoses}
    recommendation_by_id = {item.recommendation_id: item for item in artifacts.recommendations}
    rows = []
    for anomaly in artifacts.anomalies:
        insight = insight_by_anomaly.get(anomaly.anomaly_id)
        recommendation = next(
            (recommendation_by_id.get(item_id) for item_id in insight.recommendation_ids if recommendation_by_id.get(item_id)),
            None,
        ) if insight else None
        diagnosis = diagnosis_by_id.get(insight.diagnosis_id) if insight and insight.diagnosis_id else None
        work_item = work_items.get(anomaly.anomaly_id)
        rows.append({
            "anomaly": anomaly,
            "insight": insight,
            "current": snapshot_by_id.get(anomaly.current_snapshot_id),
            "baseline": snapshot_by_id.get(anomaly.baseline_snapshot_id),
            "recommendation": recommendation,
            "diagnosis": diagnosis,
            "work_item": work_item,
            "priority": insight.priority if insight else "UNRANKED",
            "priority_score": insight.priority_score if insight else None,
            "workflow_status": _workflow_value(anomaly, work_item),
            "status": str(anomaly.status),
            "period_start": snapshot_by_id[anomaly.current_snapshot_id].period_start if anomaly.current_snapshot_id in snapshot_by_id else "",
        })
    return rows


def render_risk_center(bundle) -> None:
    page_header("风险中心", "先看本期发生了什么，再决定哪些问题需要立即核实", "可信经营审计")
    artifacts = _artifacts(bundle)
    if not artifacts:
        return
    _workspace_metrics(artifacts)
    work_items = _work_item_map(bundle)
    rows = build_risk_items(artifacts, work_items)
    if not rows:
        st.info("当前未发现达到规则阈值的异常。")
        return

    controls = st.columns((1.15, 1.15, 1.15, 1.15, .9))
    priorities = controls[0].multiselect(
        "优先级", ["P0", "P1", "P2", "P3", "UNRANKED"],
        default=["P0", "P1", "P2", "P3", "UNRANKED"],
        format_func=lambda value: "不参与排序" if value == "UNRANKED" else value,
    )
    statuses = controls[1].multiselect(
        "分析状态", ["DETECTED", "RECOVERED", "SUPPRESSED"], default=["DETECTED"],
        format_func=lambda value: ANALYSIS_STATUS_LABELS.get(value, value),
    )
    workflow_statuses = controls[2].multiselect(
        "任务状态", [str(item) for item in WorkItemStatus], default=[],
        format_func=lambda value: WORKFLOW_LABELS.get(value, value), placeholder="全部任务状态",
    )
    entity_types = controls[3].multiselect(
        "对象类型", sorted({item["anomaly"].entity_type for item in rows}), default=[],
        format_func=lambda value: ENTITY_LABELS.get(value, value), placeholder="全部对象",
    )
    latest_only = controls[4].toggle("仅最近周期", value=True)
    filtered = [
        item for item in rows
        if item["priority"] in priorities and item["status"] in statuses
        and (not workflow_statuses or item["workflow_status"] in workflow_statuses)
        and (not entity_types or item["anomaly"].entity_type in entity_types)
    ]
    if latest_only and filtered:
        latest = max(item["period_start"] for item in filtered)
        filtered = [item for item in filtered if item["period_start"] == latest]
    if not filtered:
        st.info("当前筛选条件下没有异常。调整优先级或状态可查看其他记录。")
        return

    chart_rows = []
    for item in filtered:
        anomaly = item["anomaly"]
        if anomaly.change_rate is None or str(anomaly.status) != "DETECTED":
            continue
        chart_rows.append({
            "对象": "{} · {}".format(_entity_name(anomaly.entity_type, anomaly.entity_name), METRIC_LABELS.get(anomaly.metric_id, anomaly.metric_id)),
            "变化率": anomaly.change_rate,
            "方向": "增长" if anomaly.change_rate >= 0 else "下降",
            "标注": "{:+.1%}".format(anomaly.change_rate),
        })
    if chart_rows:
        chart_frame = pd.DataFrame(chart_rows).sort_values("变化率")
        fig = px.bar(
            chart_frame, x="变化率", y="对象", orientation="h", color="方向", text="标注",
            color_discrete_map={"增长": COLORS["teal"], "下降": COLORS["coral"]},
            title="本期达到规则门槛的变化", labels={"变化率": "相对上一完整周期"},
        )
        fig.update_traces(textposition="inside", insidetextanchor="end", textfont_color="#FFFFFF")
        fig.update_xaxes(tickformat=".0%", zeroline=True, zerolinecolor=COLORS["ink"])
        fig.update_yaxes(title=None)
        render_chart(chart_layout(
            fig, profile="category_y", y_labels=chart_frame["对象"],
            item_count=len(chart_frame), height=max(300, 180 + len(chart_frame) * 42),
        ), key="risk_change")

    download_cols = st.columns((1, 1, 3))
    with download_cols[0]:
        _download_csv(
            _risk_export_frame(filtered), "风险清单_当前筛选.csv",
            "下载当前筛选（{}条）".format(len(filtered)), "risk_filtered_download",
        )
    with download_cols[1]:
        _download_csv(
            _risk_export_frame(rows), "风险清单_全部记录.csv",
            "下载全部记录（{}条）".format(len(rows)), "risk_all_download",
        )

    display_rows = []
    ordered = sorted(filtered, key=lambda value: (value["priority_score"] is None, -(value["priority_score"] or 0), value["anomaly"].anomaly_id))
    for item in ordered:
        anomaly, current = item["anomaly"], item["current"]
        display_rows.append({
            "优先级": "{} · {:.1f}".format(item["priority"], item["priority_score"]) if item["priority_score"] is not None else "不参与排序",
            "发生了什么": _risk_finding(anomaly),
            "分析周期": _period_label(current),
            "影响规模": _format_impact(anomaly, current) if str(anomaly.status) == "DETECTED" else "仅展示，不作为经营影响",
            "任务状态": WORKFLOW_LABELS.get(item["workflow_status"], item["workflow_status"]),
            "下一步": _next_action(anomaly, item["recommendation"]),
        })
    page_size = 20
    total_pages = max(1, (len(display_rows) + page_size - 1) // page_size)
    page_number = 1
    if total_pages > 1:
        page_number = st.selectbox("风险清单页码", range(1, total_pages + 1), format_func=lambda value: "第 {} 页".format(value))
    start = (page_number - 1) * page_size
    visible_rows = display_rows[start:start + page_size]
    headers = ("优先级", "发生了什么", "分析周期", "影响规模", "任务状态", "下一步")
    header = "".join('<div class="risk-cell">{}</div>'.format(label) for label in headers)
    body = []
    for row in visible_rows:
        cells = "".join(
            '<div class="risk-cell" data-label="{}">{}</div>'.format(escape(label), escape(str(row[label])))
            for label in headers
        )
        body.append('<div class="risk-list-row">{}</div>'.format(cells))
    st.markdown(
        '<div class="risk-list"><div class="risk-list-header">{}</div>{}</div>'.format(header, "".join(body)),
        unsafe_allow_html=True,
    )
    st.caption("共 {} 条 · 第 {} / {} 页 · 每页最多 {} 条".format(len(display_rows), page_number, total_pages, page_size))

    st.subheader("更新处理进度")
    task_labels = {
        item["anomaly"].anomaly_id: "{} · {} · {}".format(
            "不参与排序" if item["priority"] == "UNRANKED" else item["priority"],
            _risk_finding(item["anomaly"]), _period_label(item["current"]),
        ) for item in ordered
    }
    selected_anomaly_id = st.selectbox(
        "选择风险任务", list(task_labels), format_func=task_labels.get, key="risk_task_selector",
    )
    selected_item = next(item for item in ordered if item["anomaly"].anomaly_id == selected_anomaly_id)
    _render_work_item_editor(
        bundle, selected_item["anomaly"], selected_item["insight"],
        selected_item["recommendation"], selected_item["work_item"], "risk_work_item",
    )

    with st.expander("查看规则与审计编号"):
        audit_rows = [{
            "规则": RULE_LABELS.get(item["anomaly"].rule_id, item["anomaly"].rule_id),
            "规则编号": item["anomaly"].rule_id,
            "对象类型": ENTITY_LABELS.get(item["anomaly"].entity_type, item["anomaly"].entity_type),
            "状态": STATUS_LABELS.get(item["status"], item["status"]),
            "异常编号": item["anomaly"].anomaly_id,
        } for item in filtered]
        st.table(pd.DataFrame(audit_rows))


def _driver_summary(diagnosis) -> str:
    if not diagnosis or not diagnosis.driver_contributions:
        return "当前数据只能确认指标发生变化，尚不能定位主要业务驱动。"
    contributions = [item for item in diagnosis.driver_contributions if item.get("contribution") is not None]
    if not contributions:
        return "当前数据只能确认指标发生变化，尚不能定位主要业务驱动。"
    total = sum(abs(float(item["contribution"])) for item in contributions) or 1.0
    ranked = sorted(contributions, key=lambda item: abs(float(item["contribution"])), reverse=True)
    parts = ["{}约占{:.0%}".format(item["driver"], abs(float(item["contribution"])) / total) for item in ranked[:2]]
    return "变化拆解中，{}。这表示数学贡献，不代表已经确认外部原因。".format("、".join(parts))


def _insight_summary(insight, diagnosis, current, baseline) -> str:
    entity = _entity_name(insight.entity_type, insight.entity_name)
    metric = METRIC_LABELS.get(insight.metric_id, insight.metric_id)
    current_period, baseline_period = _period_label(current), _period_label(baseline)
    if insight.change_rate is None:
        movement = "发生达到规则门槛的变化"
    else:
        movement = "{} {:.1%}".format("上升" if insight.change_rate >= 0 else "下降", abs(insight.change_rate))
    impact = ""
    if insight.impact_amount is not None and current:
        impact = "，对应影响 {}".format(_format_insight_impact(insight, current))
    return "{}在{}的{}较{}{}{}。{}".format(
        entity, current_period, metric, baseline_period, movement, impact, _driver_summary(diagnosis),
    )


def _audit_flow(insight, anomaly, diagnosis, recommendation, evidence, current) -> None:
    stages = (
        ("发现", RULE_LABELS.get(anomaly.rule_id, "指标达到异常门槛") if anomaly else "指标达到异常门槛", "risk"),
        ("对象与周期", "{} · {}".format(_entity_name(insight.entity_type, insight.entity_name), _period_label(current)), ""),
        ("诊断", DIAGNOSIS_LABELS.get(str(diagnosis.status), "证据不足") if diagnosis else "证据不足", "verify" if diagnosis and str(diagnosis.status) == "VERIFIED_DRIVER" else ""),
        ("行动", ACTION_TYPE_LABELS.get(str(recommendation.action_type), "先调查") if recommendation else "先调查", ""),
    )
    html = "".join(
        '<div class="audit-step"><div class="audit-label">{}</div><div class="audit-value {}">{}</div></div>'.format(
            escape(label), css, escape(value)
        ) for label, value, css in stages
    )
    st.markdown('<div class="audit-flow">{}</div>'.format(html), unsafe_allow_html=True)


def _action_steps(recommendation, insight=None) -> tuple[str, ...]:
    if not recommendation:
        return ("确认异常比较周期和样本是否完整", "补充缺失的业务上下文", "证据足够后再决定经营动作")
    mapping = {
        "REC-GMV-AOV": (
            "比较当前期与对比期的 SKU 价格带、折扣率和低价商品销售占比",
            "锁定对客单价下降贡献最大的商品，并确认是主动促销还是非预期结构变化",
            "仅对主要影响商品做小范围组合或价格验证，完整运行一个比较周期",
        ),
        "REC-AOV-MIX": (
            "先确认 AOV 下降主要来自订单成交金额下降还是订单数增长带来的摊薄",
            "继续比较低价 SKU 占比、折扣率和价格带结构，锁定主要影响商品",
            "对主要影响商品做小范围组合、加购或价格验证，并完整运行一个比较周期",
        ),
        "REC-GMV-ORDERS": (
            "按市场、品类和 SKU 排查订单减少最集中的对象",
            "核对对应对象的流量、库存和活动记录，区分需求下降与供给限制",
            "只对已确认原因采取动作，并在下一个完整周期复盘 GMV",
        ),
        "REC-MARKET-GROWTH-RISK": (
            "暂缓扩大预算、库存和曝光",
            "核对增长同期的利润率、退货率以及增长集中 SKU",
            "保护指标恢复后再进行小范围增量验证",
        ),
        "REC-HERO-GROWTH-RISK": (
            "暂缓扩大该商品的备货和曝光",
            "核对利润率、退货率、折扣和订单集中来源",
            "保护指标恢复后再运行一个完整周期的小范围验证",
        ),
        "REC-MARKET-SCALE": (
            "确认增长不是重复数据或单笔大单造成，并锁定主要增长市场和商品",
            "在单一市场或渠道开展小范围增量投入，不同步扩大全部预算和库存",
            "完整运行一个比较周期；GMV 改善且利润率、退货率守住保护范围后再扩大",
        ),
    }
    action = _localized_action(recommendation.action, insight.entity_type, insight.entity_name) if insight else recommendation.action
    return mapping.get(recommendation.rule_id, (
        action,
        "记录本次核查结论和对应证据",
        "在下一个完整可比较周期复盘预期指标和保护指标",
    ))


def _guardrail_lines(recommendation, current, baseline, exact) -> list[str]:
    if not recommendation or not current:
        return []
    output = []
    for metric_id in recommendation.guardrail_metrics:
        now = exact.get((metric_id, current.entity_type, current.entity_id, current.period_start))
        before = exact.get((metric_id, current.entity_type, current.entity_id, baseline.period_start)) if baseline else None
        if now and now.current_value is not None:
            text = "{}：{}".format(METRIC_LABELS.get(metric_id, metric_id), _format_value(now.current_value, metric_id, now.currency or ""))
            if before and before.current_value is not None:
                text += "（对比期 {}）".format(_format_value(before.current_value, metric_id, before.currency or ""))
            output.append(text)
        else:
            output.append("{}：当前不可用".format(METRIC_LABELS.get(metric_id, metric_id)))
    return output


def _snapshot_table(current, baseline, metric_id: str) -> pd.DataFrame:
    rows = []
    for role, snapshot in (("当前期", current), ("对比期", baseline)):
        if snapshot is None:
            continue
        rows.append({
            "比较角色": role,
            "分析周期": _period_label(snapshot),
            "指标": METRIC_LABELS.get(metric_id, metric_id),
            "指标值": _format_value(snapshot.current_value, metric_id, snapshot.currency or ""),
            "样本量": "{:,} 单".format(snapshot.sample_size),
            "完整周期": "是" if snapshot.is_complete_period else "否",
            "数据质量": "{}级".format(snapshot.quality_status),
            "分析能力": STATUS_LABELS.get(snapshot.capability_status, snapshot.capability_status),
            "证据编号": snapshot.evidence_id,
        })
    return pd.DataFrame(rows)


def render_insight_center(bundle) -> None:
    page_header("洞察中心", "把变化、驱动、行动和停止条件放在同一张经营处置单里", "可信经营审计")
    artifacts = _artifacts(bundle)
    if not artifacts:
        return
    _workspace_metrics(artifacts)
    all_insights = [item for item in artifacts.insights if item.type == "ANOMALY"]
    if not all_insights:
        st.info("当前未发现达到规则阈值的异常。")
        return
    snapshot_by_id, exact = _snapshot_maps(artifacts)
    anomaly_by_id = {item.anomaly_id: item for item in artifacts.anomalies}
    diagnosis_by_id = {item.diagnosis_id: item for item in artifacts.diagnoses}
    recommendation_by_id = {item.recommendation_id: item for item in artifacts.recommendations}
    work_items = _work_item_map(bundle)
    item_by_insight = {}
    for insight_item in all_insights:
        anomaly_item = anomaly_by_id.get(insight_item.anomaly_id)
        recommendation_item = next(
            (recommendation_by_id.get(item_id) for item_id in insight_item.recommendation_ids if recommendation_by_id.get(item_id)),
            None,
        )
        item_by_insight[insight_item.insight_id] = {
            "anomaly": anomaly_item,
            "insight": insight_item,
            "diagnosis": diagnosis_by_id.get(insight_item.diagnosis_id),
            "recommendation": recommendation_item,
            "current": snapshot_by_id.get(insight_item.current_snapshot_id),
            "baseline": snapshot_by_id.get(insight_item.baseline_snapshot_id),
            "work_item": work_items.get(insight_item.anomaly_id),
        }
    show_history = st.toggle("查看历史周期", value=False)
    insights = all_insights
    if not show_history:
        latest = _latest_period(all_insights, snapshot_by_id)
        insights = [item for item in all_insights if snapshot_by_id.get(item.current_snapshot_id) and snapshot_by_id[item.current_snapshot_id].period_start == latest]
    insights = sorted(insights, key=lambda item: (-item.priority_score, item.insight_id))
    current_items = [item_by_insight[item.insight_id] for item in insights]
    all_items = [item_by_insight[item.insight_id] for item in all_insights]
    download_cols = st.columns((1, 1, 3))
    with download_cols[0]:
        _download_csv(
            _risk_export_frame(current_items), "洞察清单_当前视图.csv",
            "下载当前视图（{}条）".format(len(current_items)), "insight_current_download",
        )
    with download_cols[1]:
        _download_csv(
            _risk_export_frame(all_items), "洞察清单_全部记录.csv",
            "下载全部洞察（{}条）".format(len(all_items)), "insight_all_download",
        )

    list_insights = sorted(all_insights, key=lambda item: (-item.priority_score, item.insight_id))
    with st.expander("完整洞察清单（{}条）".format(len(list_insights))):
        list_page_size = 20
        list_pages = max(1, (len(list_insights) + list_page_size - 1) // list_page_size)
        list_page = 1
        if list_pages > 1:
            list_page = st.selectbox(
                "洞察清单页码", range(1, list_pages + 1),
                format_func=lambda value: "第 {} 页".format(value), key="insight_list_page",
            )
        visible = list_insights[(list_page - 1) * list_page_size:list_page * list_page_size]
        insight_rows = []
        for list_item in visible:
            item = item_by_insight[list_item.insight_id]
            insight_rows.append({
                "优先级": "{} · {:.1f}".format(list_item.priority, list_item.priority_score),
                "发生了什么": _risk_finding(item["anomaly"]),
                "分析周期": _period_label(item["current"]),
                "影响规模": _format_impact(item["anomaly"], item["current"]),
                "任务状态": WORKFLOW_LABELS.get(_workflow_value(item["anomaly"], item["work_item"]), _workflow_value(item["anomaly"], item["work_item"])),
                "下一步": _next_action(item["anomaly"], item["recommendation"]),
            })
        headers = ("优先级", "发生了什么", "分析周期", "影响规模", "任务状态", "下一步")
        header = "".join('<div class="risk-cell">{}</div>'.format(label) for label in headers)
        body = []
        for row in insight_rows:
            cells = "".join(
                '<div class="risk-cell" data-label="{}">{}</div>'.format(escape(label), escape(str(row[label])))
                for label in headers
            )
            body.append('<div class="risk-list-row">{}</div>'.format(cells))
        st.markdown(
            '<div class="risk-list"><div class="risk-list-header">{}</div>{}</div>'.format(header, "".join(body)),
            unsafe_allow_html=True,
        )
        st.caption("第 {} / {} 页 · 每页最多 {} 条".format(list_page, list_pages, list_page_size))
    labels = {
        item.insight_id: "[{}] {} · {} · {}".format(
            item.priority, _entity_name(item.entity_type, item.entity_name),
            RULE_LABELS.get(next((a.rule_id for a in artifacts.anomalies if a.anomaly_id == item.anomaly_id), ""), _change_text(item.change_rate)),
            _period_label(snapshot_by_id.get(item.current_snapshot_id)),
        ) for item in insights
    }
    selected_id = st.selectbox("选择经营问题", list(labels), format_func=labels.get)
    insight = next(item for item in insights if item.insight_id == selected_id)
    anomaly = anomaly_by_id.get(insight.anomaly_id)
    diagnosis = diagnosis_by_id.get(insight.diagnosis_id)
    recommendation = item_by_insight[insight.insight_id]["recommendation"]
    evidence = next((item for item in artifacts.evidence if item.evidence_id in insight.evidence_ids), None)
    current = item_by_insight[insight.insight_id]["current"]
    baseline = item_by_insight[insight.insight_id]["baseline"]
    _audit_flow(insight, anomaly, diagnosis, recommendation, evidence, current)

    summary = _insight_summary(insight, diagnosis, current, baseline)
    st.markdown(
        '<div class="decision-brief"><div class="decision-brief-label">经营结论</div><div class="decision-brief-text">{}</div></div>'.format(escape(summary)),
        unsafe_allow_html=True,
    )
    metrics = st.columns(4)
    metrics[0].metric("当前值 · {}".format(_period_label(current)), _format_value(insight.current_value, insight.metric_id, current.currency if current else ""))
    metrics[1].metric("对比期 · {}".format(_period_label(baseline)), _format_value(insight.previous_value, insight.metric_id, baseline.currency if baseline else ""))
    metrics[2].metric("变化幅度", _change_text(insight.change_rate), delta=_format_impact(anomaly, current) if anomaly and insight.impact_amount is not None else None)
    metrics[3].metric("证据支持度", "{:.0f}/100".format(insight.confidence_score), help="表示当前数据对诊断拆解的支持程度，不是真实因果概率")

    st.subheader("变化由什么构成")
    if diagnosis and diagnosis.driver_contributions:
        frame = pd.DataFrame(diagnosis.driver_contributions)
        frame = frame.loc[frame["contribution"].notna()].copy()
        total = frame.contribution.abs().sum() or 1.0
        frame["贡献占比"] = frame.contribution.abs() / total
        frame["方向"] = frame.contribution.map(lambda value: "增加" if value >= 0 else "减少")
        frame["标注"] = frame.apply(lambda row: "{} · {:.0%}".format(_format_value(row.contribution, insight.metric_id, current.currency if current else ""), row["贡献占比"]), axis=1)
        fig = px.bar(
            frame.sort_values("contribution"), x="contribution", y="driver", orientation="h",
            color="方向", text="标注", color_discrete_map={"增加": COLORS["teal"], "减少": COLORS["coral"]},
            labels={"contribution": "对本次变化的金额贡献", "driver": "驱动"},
        )
        fig.update_traces(textposition="outside", cliponaxis=False)
        fig.update_xaxes(zeroline=True, zerolinecolor=COLORS["ink"])
        render_chart(chart_layout(fig, profile="category_y", y_labels=frame.driver, item_count=len(frame), height=330), key="diagnosis_contribution")
        st.caption(_driver_summary(diagnosis))
    else:
        missing = "、".join(diagnosis.missing_context) if diagnosis and diagnosis.missing_context else "关键业务上下文"
        st.warning("当前只能确认指标变化，尚不能确定业务原因。需要补充或下钻：{}。".format(missing))

    left, right = st.columns((1.2, 1))
    with left:
        st.subheader("执行顺序")
        for index, step in enumerate(_action_steps(recommendation, insight), 1):
            st.markdown("**{}.** {}".format(index, step))
    with right:
        st.subheader("验收与停止")
        if recommendation:
            st.write("**责任角色：** {}".format(recommendation.owner_role))
            st.write("**预期改善：** {}".format(METRIC_LABELS.get(recommendation.expected_metric, recommendation.expected_metric)))
            st.write("**验证周期：** {}".format(recommendation.validation_period))
            for line in _guardrail_lines(recommendation, current, baseline, exact):
                st.write("**保护指标：** {}".format(line))
            st.warning("停止条件：{}".format(recommendation.stop_condition))
        else:
            st.info("当前证据不足，只能建立调查任务。")
    if insight.limitations:
        st.info("尚未验证的上下文：{}。这些限制不影响已展示的数值，但会限制经营原因判断。".format("；".join(insight.limitations)))

    st.subheader("处理进度")
    _render_work_item_editor(
        bundle, anomaly, insight, recommendation,
        item_by_insight[insight.insight_id]["work_item"], "insight_work_item",
    )

    with st.expander("事实快照", expanded=True):
        snapshot_frame = _snapshot_table(current, baseline, insight.metric_id)
        if snapshot_frame.empty:
            st.error("未找到当前洞察引用的指标快照。")
        else:
            st.table(snapshot_frame)
            definition = next((item for item in artifacts.metric_definitions if item.metric_id == insight.metric_id), None)
            if definition:
                st.caption("口径：{} · 版本 {}".format(definition.business_meaning, definition.version))

    with st.expander("证据索引"):
        if evidence:
            st.write("**数据来源：** 受控订单事实查询")
            st.write("**覆盖期间：** {} 至 {}".format(evidence.period_start, evidence.period_end))
            st.write("**结果规模：** {:,} 行；GMV 汇总 {:,.2f}".format(evidence.row_count, float(evidence.result_summary.get("gmv", 0))))
            st.write("**证据编号：** {}".format(evidence.evidence_id))
            st.caption("审计查询：{} · 版本 {} · 结果摘要 {}".format(evidence.query_name, evidence.query_version[:12], evidence.result_digest[:12]))
        else:
            st.info("该洞察没有可用证据包。")


def render_health_center(bundle) -> None:
    page_header("数据健康中心", "先确认数据能回答什么，再查看经营结论和补数路线", "可信经营审计")
    artifacts = _artifacts(bundle)
    if not artifacts:
        return
    quality = artifacts.data_quality
    supported = [item for item in artifacts.analysis_capability if str(item.status) != "UNSUPPORTED"]
    missing = [item for item in artifacts.field_quality if item.presence_status == "MISSING"]
    cols = st.columns(4)
    cols[0].metric("质量评分", "{:.0f}/100".format(quality.quality_score))
    cols[1].metric("可信度", "{}级".format(quality.quality_rating))
    cols[2].metric("可用能力", "{} / {}".format(len(supported), len(artifacts.analysis_capability)))
    cols[3].metric("缺失字段", str(len(missing)))
    st.caption(quality.quality_explanation)
    dimensions = _display_frame(artifacts.records("data_quality_dimensions"))
    if not dimensions.empty:
        fig = px.bar(
            dimensions.sort_values("score"), x="score", y="dimension", orientation="h",
            color="score", range_x=[0, 100], color_continuous_scale=[COLORS["coral"], COLORS["amber"], COLORS["teal"]],
            labels={"score": "得分", "dimension": "质量维度"}, title="五项数据质量评分",
        )
        render_chart(chart_layout(fig, profile="category_y", y_labels=dimensions.dimension, item_count=len(dimensions)), key="quality_dimensions")
    st.subheader("经营分析能力")
    localized_grid(_display_frame(artifacts.records("analysis_capability")), "analysis_capability", search=False, page_size=10)
    st.subheader("字段健康")
    localized_grid(_display_frame(artifacts.records("field_quality")), "field_quality", page_size=20)
    st.subheader("数据提升路线")
    improvements = _display_frame(artifacts.records("data_improvement_plan"))
    if improvements.empty:
        st.success("当前关键字段已覆盖，没有待生成的补数计划。")
    else:
        localized_grid(improvements.sort_values("priority"), "improvement_plan", search=False, page_size=10)
