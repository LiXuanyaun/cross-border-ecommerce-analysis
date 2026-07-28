from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any
import math
import os

import pandas as pd

from crossborder_analytics.localization import value_for
from crossborder_analytics.decision_brief import build_decision_brief
from crossborder_analytics.phase2_catalogs import ANOMALY_RULES, METRICS_CATALOG
from crossborder_analytics.service import AnalysisService
from crossborder_analytics.data_quality import assess_business_quality
from crossborder_analytics.modules import amount_column
from .report_runtime import export_scoped_bundle
from .agent_tools import build_agent_tool_registry
from .services import AnalysisQueryService, DatasetService, DemoScenario, SCENARIOS
from .state import StateStore
from .task_lifecycle import normalize_work_item_patch
from .topic_decisions import formal_topic_decisions


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "ecommerce_sales_34500.csv"


def _clean(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return _clean(value.to_dict())
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean(item) for item in value]
    return value


def _records(frame: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    source = frame if limit is None else frame.head(limit)
    return [_clean(item) for item in source.to_dict("records")]


def _localize(value: Any, kind: str) -> str:
    if value is None:
        return "未标注"
    try:
        return str(value_for(value, kind))
    except Exception:
        return str(value)


METRIC_LABELS = {
    "gmv": "GMV（成交总额）",
    "orders": "订单数",
    "aov": "客单价",
    "profit": "利润",
    "profit_margin": "利润率",
    "return_rate": "退货率",
    "market_contribution": "市场贡献率",
    "product_contribution": "商品贡献率",
}


def _rate(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or not previous:
        return None
    return (float(current) - float(previous)) / abs(float(previous))


def _entity_label(entity_type: str, value: Any) -> str:
    if entity_type == "market":
        return _localize(value, "region")
    if entity_type == "category":
        return _localize(value, "category")
    return str(value)


def _threshold_text(rule) -> str:
    threshold = float(rule.threshold)
    if rule.direction == "decrease":
        return "变化率不低于 {:.1%}".format(threshold)
    if rule.direction == "increase":
        return "变化率低于 +{:.1%}".format(threshold)
    if rule.direction == "decrease_pp":
        return "降幅小于 {:.1f} 个百分点".format(abs(threshold) * 100)
    if rule.direction == "high":
        return "当前值低于 {:.1%}".format(threshold)
    if rule.direction == "low_margin":
        return "利润率高于 {:.1%}".format(threshold)
    if rule.direction == "absolute_pp":
        return "波动小于 {:.1f} 个百分点".format(abs(threshold) * 100)
    if rule.direction == "compound":
        return "增长质量保护指标恢复"
    return "不再触发规则阈值"


class AnalyticsRuntime:
    def __init__(self) -> None:
        self.app_mode = os.getenv("CROSSBORDER_APP_MODE", "demo").strip().lower()
        self._service = AnalysisService(cache_dir=ROOT / ".cache" / "fx")
        self.dataset_service = DatasetService(self._service, SAMPLE)
        self.analysis_query_service = AnalysisQueryService(self.dataset_service)
        cached_bundle = lru_cache(maxsize=64)(self._bundle_uncached)
        self._bundle_cache_clear = cached_bundle.cache_clear

        def clear_bundle_cache() -> None:
            self.clear_analysis_cache()

        cached_bundle.cache_clear = clear_bundle_cache
        self.bundle = cached_bundle
        self.dataset_service.set_cache_clearer(self.clear_analysis_cache)
        self.agent_tools = build_agent_tool_registry()
        self.state_store = None
        if self.app_mode == "private":
            state_path = Path(os.getenv("CROSSBORDER_STATE_DB", ROOT / "database" / "crossborder_state.db"))
            self.state_store = StateStore(state_path)
        self._work_items = self.state_store.load_work_items() if self.state_store else {}

    def _ensure_context(self):
        return self.dataset_service.ensure_demo_context()

    def _database(self):
        return self.dataset_service.database()

    def _artifact_store(self):
        return self.dataset_service.artifact_store()

    def _imported_scenarios(self) -> tuple[DemoScenario, ...]:
        return self.dataset_service.imported_scenarios()

    def _context_for(self, dataset_id: str):
        return self.dataset_service.context_for(dataset_id)

    def clear_analysis_cache(self) -> None:
        self._bundle_cache_clear()
        self.analysis_query_service.clear_cache()
        self._topic_base.cache_clear()

    def scenario(self, dataset_id: str) -> DemoScenario:
        return self.dataset_service.scenario(dataset_id)

    def date_bounds(self, dataset_id: str = "demo-all") -> tuple[str, str]:
        return self.dataset_service.date_bounds(dataset_id)

    def _bundle_uncached(
        self,
        dataset_id: str,
        start: str | None = None,
        end: str | None = None,
        market: str | None = None,
        category: str | None = None,
        period_type: str = "month",
        analysis_mode: str = "full",
        topic: str | None = None,
    ):
        return self.analysis_query_service.bundle(
            dataset_id, start, end, market, category, period_type, analysis_mode, topic,
        )

    def meta(self, bundle, dataset_id: str) -> dict[str, Any]:
        quality = bundle.artifacts.data_quality
        return {
            "dataset_id": dataset_id,
            "scope_id": bundle.metadata.get("scope_id"),
            "source_dataset_id": bundle.metadata.get("dataset_id"),
            "generated_at": bundle.generated_at,
            "quality_rating": str(quality.quality_rating) if quality else None,
            "quality_score": quality.quality_score if quality else None,
            "app_mode": self.app_mode,
        }

    @staticmethod
    def _metric_change(rows: pd.DataFrame, field: str) -> float | None:
        values = rows[field].dropna().tolist() if field in rows else []
        if len(values) < 2 or not values[-2]:
            return None
        return (float(values[-1]) - float(values[-2])) / abs(float(values[-2]))

    @staticmethod
    def _comparison_trend(
        frame: pd.DataFrame,
        current_start: str,
        current_end: str,
        comparison_start: str,
        comparison_end: str,
        grain: str,
    ) -> dict[str, Any]:
        source = frame.copy()
        source["order_date"] = pd.to_datetime(source["order_date"]).dt.normalize()
        amount = amount_column(source)
        current_start_date = pd.Timestamp(current_start).normalize()
        current_end_date = pd.Timestamp(current_end).normalize()
        comparison_start_date = pd.Timestamp(comparison_start).normalize()
        comparison_end_date = pd.Timestamp(comparison_end).normalize()

        if grain == "day":
            current_index = pd.date_range(current_start_date, current_end_date, freq="D")
            comparison_index = pd.date_range(comparison_start_date, comparison_end_date, freq="D")
            grouped = source.groupby("order_date")[amount].sum()
        else:
            current_index = pd.date_range(current_start_date, current_end_date, freq="7D")
            comparison_index = pd.date_range(comparison_start_date, comparison_end_date, freq="7D")
            current_rows = source.loc[source.order_date.between(current_start_date, current_end_date)].copy()
            comparison_rows = source.loc[source.order_date.between(comparison_start_date, comparison_end_date)].copy()
            current_rows["bucket"] = ((current_rows.order_date - current_start_date).dt.days // 7).astype(int)
            comparison_rows["bucket"] = ((comparison_rows.order_date - comparison_start_date).dt.days // 7).astype(int)
            current_values = current_rows.groupby("bucket")[amount].sum()
            comparison_values = comparison_rows.groupby("bucket")[amount].sum()

        if grain == "day":
            current_values = grouped.reindex(current_index, fill_value=0.0)
            comparison_values = grouped.reindex(comparison_index, fill_value=0.0)
        rows = []
        bucket_count = max(len(current_index), len(comparison_index))
        for index in range(bucket_count):
            current_date = current_index[index] if index < len(current_index) else None
            comparison_date = comparison_index[index] if index < len(comparison_index) else None
            rows.append({
                "label": "第{}日".format(index + 1) if grain == "day" else "第{}周".format(index + 1),
                "current_date": current_date.date().isoformat() if current_date is not None else "",
                "comparison_date": comparison_date.date().isoformat() if comparison_date is not None else "",
                "current": float(current_values.loc[current_date]) if grain == "day" and current_date is not None else (float(current_values.get(index, 0.0)) if current_date is not None else None),
                "comparison": float(comparison_values.loc[comparison_date]) if grain == "day" and comparison_date is not None else (float(comparison_values.get(index, 0.0)) if comparison_date is not None else None),
            })
        return {
            "grain": grain,
            "current_period": {"start": current_start_date.date().isoformat(), "end": current_end_date.date().isoformat()},
            "comparison_period": {"start": comparison_start_date.date().isoformat(), "end": comparison_end_date.date().isoformat()},
            "rows": rows,
        }

    def overview(self, dataset_id: str, start: str | None = None, end: str | None = None) -> tuple[dict, Any]:
        selection_start, selection_end = self.date_bounds(dataset_id)
        selection_start = start or selection_start
        selection_end = end or selection_end
        bundle = self.bundle(dataset_id, selection_start, selection_end)
        artifacts = bundle.artifacts

        scenario = self.scenario(dataset_id)
        source = self._context_for(dataset_id).analysis_data.copy()
        for field, values in scenario.filters.items():
            if field in source:
                source = source.loc[source[field].astype(str).isin([str(value) for value in values])]
        source["order_date"] = pd.to_datetime(source["order_date"]).dt.normalize()
        amount = amount_column(source)

        global_months = [
            item for item in artifacts.metric_snapshots
            if item.entity_type == "global" and item.entity_id == "__all__"
            and item.period_type == "month" and item.is_complete_period
        ]
        period_starts = sorted({item.period_start for item in global_months})
        current_start = period_starts[-1] if period_starts else selection_start
        comparison_start = period_starts[-2] if len(period_starts) > 1 else current_start
        current_snapshots = {item.metric_id: item for item in global_months if item.period_start == current_start}
        comparison_snapshots = {item.metric_id: item for item in global_months if item.period_start == comparison_start}
        current_sample = current_snapshots.get("gmv")
        comparison_sample = comparison_snapshots.get("gmv")
        current_period = {
            "start": current_start,
            "end": current_sample.period_end if current_sample else selection_end,
            "type": "month",
        }
        comparison_period = {
            "start": comparison_start,
            "end": comparison_sample.period_end if comparison_sample else comparison_start,
            "type": "month",
        }

        kpi_specs = [
            ("gmv", "gmv", "GMV（成交总额）", "currency", "blue", "下降达到20%或增长达到30%触发异常"),
            ("profit_rate", "profit_margin", "利润率", "percent", "violet", "下降达到5个百分点触发异常"),
            ("orders", "orders", "订单数", "integer", "green", "不设自动异常阈值，仅观察环比"),
            ("aov", "aov", "客单价", "currency", "orange", "下降达到15%触发异常"),
        ]
        kpis = []
        for public_id, metric_id, label, value_format, tone, threshold in kpi_specs:
            current = current_snapshots.get(metric_id)
            previous = comparison_snapshots.get(metric_id)
            sparkline = [
                {
                    "label": period[:7],
                    "value": next(
                        (item.current_value for item in global_months if item.period_start == period and item.metric_id == metric_id),
                        None,
                    ),
                }
                for period in period_starts[-8:]
            ]
            kpis.append({
                "id": public_id,
                "label": label,
                "value": current.current_value if current else None,
                "previous_value": previous.current_value if previous else None,
                "format": value_format,
                "change": _rate(
                    current.current_value if current else None,
                    previous.current_value if previous else None,
                ),
                "tone": tone,
                "sparkline": sparkline,
                "basis": "最近完整月；环比上一完整月",
                "threshold": threshold,
                "metric_id": metric_id,
                "metric_version": current.metric_version if current else None,
                "evidence_id": current.evidence_id if current else None,
            })

        market_current = source.loc[source.order_date.between(current_period["start"], current_period["end"])]
        yoy_start = (pd.Timestamp(current_period["start"]) - pd.DateOffset(years=1)).date().isoformat()
        yoy_end = (pd.Timestamp(current_period["end"]) - pd.DateOffset(years=1)).date().isoformat()
        market_previous = source.loc[source.order_date.between(yoy_start, yoy_end)]
        market_field = "country" if "country" in source and source["country"].notna().any() else "region"
        current_market_gmv = market_current.groupby(market_field)[amount].sum()
        previous_market_gmv = market_previous.groupby(market_field)[amount].sum()
        total_market_gmv = float(current_market_gmv.sum())
        markets = []
        for rank, (market, gmv) in enumerate(current_market_gmv.sort_values(ascending=False).head(5).items(), start=1):
            previous_gmv = float(previous_market_gmv.get(market, 0.0))
            markets.append({
                "rank": rank,
                "market": str(market),
                "name": _localize(market, "region"),
                "gmv": float(gmv),
                "share": float(gmv) / total_market_gmv if total_market_gmv else None,
                "yoy": _rate(float(gmv), previous_gmv),
                "previous_gmv": previous_gmv,
            })

        sales_result = bundle.results.get("sales")
        sales_data = sales_result.data if sales_result and isinstance(sales_result.data, dict) else {}
        category_source = sales_data.get("category_contribution")
        categories_frame = pd.DataFrame(columns=["category", "gmv"])
        if isinstance(category_source, pd.DataFrame) and "current" in category_source:
            categories_frame = (
                category_source.rename(columns={"current": "gmv"})
                .sort_values("gmv", ascending=False)
            )
        category_total = float(categories_frame.gmv.sum())
        categories = [
            {
                **row,
                "name": _localize(row.get("category"), "category"),
                "share": float(row.get("gmv", 0.0)) / category_total if category_total else None,
            }
            for row in _records(categories_frame, 7)
        ]
        monthly_source = sales_data.get("monthly")
        if isinstance(monthly_source, pd.DataFrame) and "month" in monthly_source:
            trend_frame = monthly_source.sort_values("month").tail(12)
        else:
            source_for_trend = source.copy()
            source_for_trend["month"] = source_for_trend["order_date"].dt.to_period("M").astype(str)
            trend_frame = (
                source_for_trend.groupby("month")
                .agg(gmv=(amount, "sum"), orders=("order_id", "nunique"))
                .reset_index()
                .sort_values("month")
                .tail(12)
            )

        snapshot_by_id = {item.snapshot_id: item for item in artifacts.metric_snapshots}
        anomaly_by_id = {item.anomaly_id: item for item in artifacts.anomalies}
        rule_by_id = {item.rule_id: item for item in artifacts.anomaly_rules}
        diagnosis_by_id = {item.diagnosis_id: item for item in artifacts.diagnoses}
        recommendation_by_id = {item.recommendation_id: item for item in artifacts.recommendations}
        evidence_by_id = {item.evidence_id: item for item in artifacts.evidence}
        latest_insight_period = max(
            (
                snapshot_by_id[item.current_snapshot_id].period_start
                for item in artifacts.insights
                if item.current_snapshot_id in snapshot_by_id
            ),
            default=None,
        )
        latest_insights = [
            item for item in artifacts.insights
            if item.current_snapshot_id in snapshot_by_id
            and snapshot_by_id[item.current_snapshot_id].period_start == latest_insight_period
        ]
        latest_insights.sort(key=lambda item: (-item.priority_score, item.insight_id))

        tasks = []
        seen = set()
        for insight in latest_insights:
            key = (insight.entity_type, insight.entity_id, insight.metric_id)
            if key in seen:
                continue
            seen.add(key)
            anomaly = anomaly_by_id.get(insight.anomaly_id)
            if anomaly is None:
                continue
            rule = rule_by_id.get(anomaly.rule_id)
            diagnosis = diagnosis_by_id.get(insight.diagnosis_id)
            recommendation = next(
                (recommendation_by_id[item_id] for item_id in insight.recommendation_ids if item_id in recommendation_by_id),
                None,
            )
            current = snapshot_by_id.get(insight.current_snapshot_id)
            baseline = snapshot_by_id.get(insight.baseline_snapshot_id)
            evidence = next(
                (evidence_by_id[item_id] for item_id in insight.evidence_ids if item_id in evidence_by_id),
                None,
            )
            saved = self._work_items.get(anomaly.anomaly_id, {})
            deadline = saved.get("deadline") or saved.get("due_date")
            tasks.append({
                "id": anomaly.anomaly_id,
                "insight_id": insight.insight_id,
                "object": _entity_label(insight.entity_type, insight.entity_name),
                "object_type": insight.entity_type,
                "metric_id": insight.metric_id,
                "metric_version": current.metric_version if current else None,
                "rule_id": anomaly.rule_id,
                "rule_version": anomaly.rule_version,
                "metric_label": METRIC_LABELS.get(insight.metric_id, insight.metric_id),
                "anomaly": rule.name if rule else anomaly.rule_id,
                "finding": insight.finding,
                "impact_amount": insight.impact_amount,
                "impact_type": anomaly.impact_type,
                "target_threshold": _threshold_text(rule) if rule else "不再触发当前规则",
                "priority": insight.priority,
                "analysis_status": str(anomaly.status),
                "status": saved.get("workflow_status", "TODO"),
                "owner": saved.get("owner", recommendation.owner_role if recommendation else "经营负责人"),
                "deadline": deadline,
                "result_note": saved.get("result_note", ""),
                "review_result": saved.get("review_result", ""),
                "close_reason": saved.get("close_reason", ""),
                "closed_by": saved.get("closed_by", ""),
                "closed_at": saved.get("closed_at"),
                "current_value": insight.current_value,
                "comparison_value": insight.previous_value,
                "change_rate": insight.change_rate,
                "current_period": {"start": current.period_start, "end": current.period_end} if current else None,
                "comparison_period": {"start": baseline.period_start, "end": baseline.period_end} if baseline else None,
                "diagnosis": {
                    "status": str(diagnosis.status) if diagnosis else insight.diagnosis_status,
                    "summary": diagnosis.finding if diagnosis else insight.diagnosis_summary,
                    "confidence_score": diagnosis.confidence_score if diagnosis else insight.confidence_score,
                    "drivers": list(diagnosis.driver_contributions) if diagnosis else [],
                },
                "recommendation": {
                    "action": recommendation.action if recommendation else insight.recommendation_summary,
                    "rationale": recommendation.rationale if recommendation else insight.diagnosis_summary,
                    "expected_metric": METRIC_LABELS.get(recommendation.expected_metric, recommendation.expected_metric) if recommendation else None,
                    "validation_period": recommendation.validation_period if recommendation else None,
                    "stop_condition": recommendation.stop_condition if recommendation else None,
                },
                "evidence": {
                    "ids": list(insight.evidence_ids),
                    "source_fields": list(evidence.source_fields) if evidence else [],
                    "formula": evidence.formula if evidence else None,
                    "row_count": evidence.row_count if evidence else None,
                    "quality_level": insight.data_quality_level,
                },
                "created_at": insight.created_at,
            })

        opportunities = []
        candidates = [
            item for item in [*artifacts.market_opportunities, *artifacts.product_opportunities]
            if item.gmv_change is not None and item.gmv_change > 1000
            and (
                hasattr(item, "market")
                or str(item.opportunity_type) not in {"样本不足", "数据不足", "高风险增长"}
            )
        ]
        candidates.sort(key=lambda item: (-float(item.gmv_change or 0.0), item.opportunity_id))
        for item in candidates[:2]:
            is_market = hasattr(item, "market")
            opportunities.append({
                "id": item.opportunity_id,
                "object": _localize(item.market, "region") if is_market else item.product_name,
                "object_type": "market" if is_market else "product",
                "status": str(item.status) if is_market else str(item.opportunity_type),
                "estimated_growth": item.gmv_change,
                "growth_rate": item.gmv_growth_rate,
                "basis": (
                    "最近完整周期 GMV 差额，主要由{}贡献".format(item.primary_driver)
                    if is_market else item.rationale
                ),
                "current_period": item.current_period,
                "comparison_period": item.comparison_period,
                "current_gmv": item.current_gmv,
                "previous_gmv": item.previous_gmv,
                "recommended_action": item.recommended_action,
                "guardrail_metrics": list(item.guardrail_metrics),
                "validation_period": item.validation_period,
                "stop_condition": item.stop_condition,
                "evidence_ids": list(item.evidence_ids),
            })

        insight_snapshot_groups: dict[tuple[str, str, str], list[Any]] = {}
        for snapshot in artifacts.metric_snapshots:
            if snapshot.period_type == "month" and snapshot.is_complete_period:
                insight_snapshot_groups.setdefault(
                    (snapshot.metric_id, snapshot.entity_type, snapshot.entity_id), [],
                ).append(snapshot)
        for group in insight_snapshot_groups.values():
            group.sort(key=lambda item: item.period_start)

        insights = []
        tasks_by_insight = {item["insight_id"]: item for item in tasks}
        for insight in latest_insights[:6]:
            task = tasks_by_insight.get(insight.insight_id)
            if task:
                anomaly = anomaly_by_id.get(insight.anomaly_id)
                insight_snapshot = snapshot_by_id.get(insight.current_snapshot_id)
                history = insight_snapshot_groups.get(
                    (insight.metric_id, insight.entity_type, insight.entity_id), [],
                )
                history = [item for item in history if item.period_start <= current_start][-12:]
                changes = []
                for previous, current in zip(history, history[1:]):
                    rate = _rate(current.current_value, previous.current_value)
                    changes.append({"period": current.period_start, "change_rate": rate})
                current_direction = 1 if (insight.change_rate or 0) > 0 else -1
                streak = 0
                for item in reversed(changes):
                    rate = item["change_rate"]
                    if rate is None or (1 if rate > 0 else -1) != current_direction:
                        break
                    streak += 1
                similar = []
                if anomaly is not None:
                    for historical_anomaly in artifacts.anomalies:
                        if (
                            historical_anomaly.anomaly_id != anomaly.anomaly_id
                            and historical_anomaly.rule_id == anomaly.rule_id
                            and historical_anomaly.entity_type == anomaly.entity_type
                            and historical_anomaly.entity_id == anomaly.entity_id
                            and historical_anomaly.current_snapshot_id in snapshot_by_id
                        ):
                            historical_snapshot = snapshot_by_id[historical_anomaly.current_snapshot_id]
                            if historical_snapshot.period_start < current_start:
                                similar.append({
                                    "period": historical_snapshot.period_start,
                                    "change_rate": historical_anomaly.change_rate,
                                    "impact_amount": historical_anomaly.impact_amount,
                                })
                similar.sort(key=lambda item: item["period"], reverse=True)

                exact_snapshots = {
                    (item.metric_id, item.entity_type, item.entity_id, item.period_start): item
                    for item in artifacts.metric_snapshots
                }
                current_margin = exact_snapshots.get(("profit_margin", insight.entity_type, insight.entity_id, current_start))
                previous_margin = exact_snapshots.get(("profit_margin", insight.entity_type, insight.entity_id, comparison_start))
                current_return = exact_snapshots.get(("return_rate", insight.entity_type, insight.entity_id, current_start))
                previous_return = exact_snapshots.get(("return_rate", insight.entity_type, insight.entity_id, comparison_start))
                margin_healthy = (
                    current_margin is not None and previous_margin is not None
                    and current_margin.current_value is not None and previous_margin.current_value is not None
                    and current_margin.current_value >= previous_margin.current_value
                )
                return_healthy = (
                    current_return is not None and previous_return is not None
                    and current_return.current_value is not None and previous_return.current_value is not None
                    and current_return.current_value <= previous_return.current_value
                )
                if current_direction > 0 and margin_healthy and return_healthy:
                    sustainability_level = "较强"
                    sustainability_reason = "增长同时满足利润率不下降、退货率不上升两项质量护栏"
                elif current_direction > 0:
                    sustainability_level = "待验证"
                    sustainability_reason = "增长尚未同时通过利润率与退货率两项质量护栏"
                elif streak >= 2:
                    sustainability_level = "风险延续"
                    sustainability_reason = "已连续{}个完整周期同向下降".format(streak)
                elif similar:
                    sustainability_level = "需关注"
                    sustainability_reason = "近12个完整月曾出现{}次同类规则命中".format(len(similar))
                else:
                    sustainability_level = "暂未持续"
                    sustainability_reason = "当前仅出现单周期变化，历史未发现同类规则命中"
                insights.append({
                    "id": insight.insight_id,
                    "created_at": insight.created_at,
                    "period": current_start,
                    "priority": insight.priority,
                    "object": task["object"],
                    "metric_label": task["metric_label"],
                    "finding": insight.finding,
                    "analysis_status": task["analysis_status"],
                    "change_rate": insight.change_rate,
                    "impact_amount": insight.impact_amount,
                    "sustainability": {
                        "level": sustainability_level,
                        "reason": sustainability_reason,
                        "same_direction_periods": streak,
                        "profit_margin_guardrail": margin_healthy,
                        "return_rate_guardrail": return_healthy,
                    },
                    "history": {
                        "lookback_months": len(history),
                        "similar_occurrences": len(similar),
                        "similar_periods": similar[:4],
                        "recent_changes": changes[-6:],
                    },
                    "evidence": task["evidence"],
                    "recommendation": task["recommendation"],
                    "metric_id": insight.metric_id,
                    "metric_version": insight_snapshot.metric_version if insight_snapshot else None,
                    "rule_id": task["rule_id"],
                    "rule_version": task["rule_version"],
                })

        methodology = {
            "kpis": {
                "basis": "最近完整月（{} 至 {}）".format(current_period["start"], current_period["end"]),
                "comparison": "环比上一完整月（{} 至 {}）".format(comparison_period["start"], comparison_period["end"]),
                "threshold": "各指标阈值在卡片内单独标注",
            },
            "trend": {
                "basis": "当前完整月（{} 至 {}）内按日或7日序号周汇总 GMV".format(current_period["start"], current_period["end"]),
                "comparison": "上一完整月（{} 至 {}）的同序号日或周".format(comparison_period["start"], comparison_period["end"]),
                "threshold": "仅用于观察，不单独触发经营结论",
            },
            "tasks": {
                "basis": "最近完整月命中的已注册异常规则",
                "comparison": "环比上一完整月",
                "threshold": "每条事项显示对应规则恢复阈值",
            },
            "markets": {
                "basis": "最近完整月市场 GMV Top5",
                "comparison": "同比去年同月",
                "threshold": "按 GMV 降序，不设异常判断阈值",
            },
            "products": {
                "basis": "最近完整月品类 GMV 构成",
                "comparison": "环比上一完整月",
                "threshold": "展示全部有成交品类，按 GMV 降序",
            },
            "opportunities": {
                "basis": "最近完整月环比 GMV 增量 Top2",
                "comparison": "{} 对比 {}".format(current_period["start"][:7], comparison_period["start"][:7]),
                "threshold": "GMV 环比增量 > ¥1,000，且排除样本不足、数据不足与高风险增长",
            },
            "insights": {
                "basis": "最近完整月异常对象的独立持续性分析",
                "comparison": "回看最近12个完整月的同类规则与连续方向",
                "threshold": "增长需同时满足利润率不下降、退货率不上升才判为可持续性较强",
            },
        }

        return _clean({
            "period": current_period,
            "current_period": current_period,
            "comparison_period": comparison_period,
            "selection_period": {"start": selection_start, "end": selection_end},
            "kpis": kpis,
            "trends": {
                "day": self._comparison_trend(source, current_period["start"], current_period["end"], comparison_period["start"], comparison_period["end"], "day"),
                "week": self._comparison_trend(source, current_period["start"], current_period["end"], comparison_period["start"], comparison_period["end"], "week"),
            },
            "trend": _records(trend_frame),
            "markets": markets,
            "market_comparison_period": {"start": yoy_start, "end": yoy_end, "type": "year_over_year"},
            "categories": categories,
            "tasks": tasks,
            "opportunities": opportunities,
            "insights": insights,
            "methodology": methodology,
            "currency": "CNY",
        }), bundle

    @lru_cache(maxsize=128)
    def _topic_base(
        self,
        dataset_id: str,
        topic: str,
        start: str | None,
        end: str | None,
        market: str | None,
        category: str | None,
    ) -> tuple[dict, Any]:
        return self._topic_uncached(dataset_id, topic, start, end, market, category)

    def topic(
        self,
        dataset_id: str,
        topic: str,
        start: str | None,
        end: str | None,
        market: str | None,
        category: str | None,
        search: str,
        page: int,
        page_size: int,
    ) -> tuple[dict, Any]:
        base, bundle = self._topic_base(dataset_id, topic, start, end, market, category)
        scope_id = bundle.metadata.get("scope_id")
        if not scope_id:
            raise RuntimeError("专题分析缺少 scope_id")
        detail_records = list(base.get("_detail_records", []))
        if search:
            needle = search.casefold()
            detail_records = [
                row for row in detail_records
                if needle in str(row).casefold()
            ]
        total = len(detail_records)
        offset = (page - 1) * page_size
        rows = detail_records[offset:offset + page_size]
        public_base = {
            key: value for key, value in base.items()
            if key != "_detail_records"
        }
        data = {
            **public_base,
            "details": rows,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "pages": max(1, math.ceil(total / page_size)),
            },
        }
        return data, bundle

    def _topic_uncached(
        self,
        dataset_id: str,
        topic: str,
        start: str | None,
        end: str | None,
        market: str | None,
        category: str | None,
    ) -> tuple[dict, Any]:
        bundle = self.bundle(
            dataset_id, start, end, market, category, analysis_mode="topic", topic=topic,
        )
        sales = bundle.results["sales"].data
        overview = bundle.results["overview"].data
        source = bundle.context.analysis_data.copy()
        source["order_date"] = pd.to_datetime(source["order_date"])
        source["month"] = source.order_date.dt.to_period("M").astype(str)
        amount = amount_column(source)
        profit_field = next(
            (field for field in ("profit_amount_base", "profit_amount") if field in source),
            None,
        )
        market_field = "country" if "country" in source and source.country.notna().any() else "region"
        source["_gmv"] = pd.to_numeric(source[amount], errors="coerce").fillna(0.0)
        source["_profit"] = (
            pd.to_numeric(source[profit_field], errors="coerce").fillna(0.0)
            if profit_field else 0.0
        )
        source["_returned"] = source.returned.eq(True) if "returned" in source else False
        source["_returned_gmv"] = source._gmv.where(source._returned, 0.0)

        monthly_aggregations: dict[str, tuple[str, str]] = {
            "gmv": ("_gmv", "sum"),
            "orders": ("order_id", "nunique"),
            "profit": ("_profit", "sum"),
            "returned_orders": ("_returned", "sum"),
            "returned_gmv_exposure": ("_returned_gmv", "sum"),
        }
        if "quantity" in source:
            monthly_aggregations["units"] = ("quantity", "sum")
        if "customer_id" in source:
            monthly_aggregations["customers"] = ("customer_id", "nunique")
        if "product_id" in source:
            monthly_aggregations["products"] = ("product_id", "nunique")
        if market_field in source:
            monthly_aggregations["markets"] = (market_field, "nunique")
        if "delivery_time_days" in source:
            monthly_aggregations["delivery_mean"] = ("delivery_time_days", "mean")
        monthly = source.groupby("month").agg(**monthly_aggregations).reset_index().sort_values("month")
        monthly["aov"] = monthly.gmv / monthly.orders.where(monthly.orders.ne(0))
        monthly["profit_rate"] = monthly.profit / monthly.gmv.where(monthly.gmv.ne(0))
        monthly["return_rate"] = monthly.returned_orders / monthly.orders.where(monthly.orders.ne(0))
        monthly["return_exposure_share"] = monthly.returned_gmv_exposure / monthly.gmv.where(monthly.gmv.ne(0))
        monthly["gmv_per_customer"] = monthly.gmv / monthly.get("customers", pd.Series(index=monthly.index, dtype=float)).where(monthly.get("customers", pd.Series(index=monthly.index, dtype=float)).ne(0))
        monthly["frequency"] = monthly.orders / monthly.get("customers", pd.Series(index=monthly.index, dtype=float)).where(monthly.get("customers", pd.Series(index=monthly.index, dtype=float)).ne(0))

        selection_start = pd.Timestamp(start or self.date_bounds(dataset_id)[0]).normalize()
        selection_end = pd.Timestamp(end or self.date_bounds(dataset_id)[1]).normalize()
        complete_months = monthly.month.astype(str).tolist()
        if complete_months and selection_start.day > 1:
            complete_months = complete_months[1:]
        if complete_months and selection_end < selection_end.to_period("M").end_time.normalize():
            complete_months = complete_months[:-1]
        if len(complete_months) < 2:
            complete_months = monthly.month.astype(str).tolist()

        if market_field in source:
            market_month = source.groupby(["month", market_field])._gmv.sum()
            monthly["top_market_share"] = monthly.month.map(
                lambda value: float(market_month.get(value, pd.Series(dtype=float)).max() / monthly.loc[monthly.month.eq(value), "gmv"].iloc[0])
                if monthly.loc[monthly.month.eq(value), "gmv"].iloc[0] else None
            )
        if "product_id" in source:
            product_month_profit = source.groupby(["month", "product_id"])._profit.sum()
            profitable = product_month_profit.gt(0).groupby(level=0).sum()
            loss_amount = product_month_profit.where(product_month_profit.lt(0), 0.0).groupby(level=0).sum().abs()
            monthly["profitable_products"] = monthly.month.map(profitable).fillna(0)
            monthly["loss_amount"] = monthly.month.map(loss_amount).fillna(0.0)

        def metric(metric_id: str, label: str, value: Any, value_format: str, series_key: str) -> dict[str, Any]:
            series = monthly[["month", series_key]].dropna() if series_key in monthly else pd.DataFrame()
            if not series.empty:
                series = series.loc[series.month.astype(str).isin(complete_months)]
            values = series[series_key].tolist() if not series.empty else []
            change = _rate(float(values[-1]), float(values[-2])) if len(values) >= 2 else None
            return {
                "id": metric_id,
                "label": label,
                "value": value,
                "format": value_format,
                "change": change,
                "sparkline": [
                    {"label": row.month, "value": row[series_key]}
                    for _, row in series.tail(8).iterrows()
                ],
            }

        def composition_rows(frame: pd.DataFrame, name_key: str, value_key: str, kind: str | None = None) -> list[dict[str, Any]]:
            if frame.empty:
                return []
            ordered = frame.sort_values(value_key, ascending=False).head(8)
            positive_total = float(ordered[value_key].clip(lower=0).sum())
            return [
                {
                    "name": _localize(row[name_key], kind) if kind else str(row[name_key]),
                    "value": row[value_key],
                    "chart_value": max(float(row[value_key]), 0.0),
                    "share": max(float(row[value_key]), 0.0) / positive_total if positive_total else None,
                }
                for _, row in ordered.iterrows()
            ]

        def ranking_rows(frame: pd.DataFrame, name_key: str, value_key: str, secondary_key: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
            if frame.empty:
                return []
            output = []
            for rank, (_, row) in enumerate(frame.sort_values(value_key, ascending=False).head(5).iterrows(), start=1):
                output.append({
                    "rank": rank,
                    "name": _localize(row[name_key], kind) if kind else str(row[name_key]),
                    "value": row[value_key],
                    "secondary": row.get(secondary_key) if secondary_key else None,
                })
            return output

        orders = int(source.order_id.nunique())
        gmv = float(source._gmv.sum())
        profit = float(source._profit.sum())
        returned_orders = int(source._returned.sum())
        returned_exposure = float(source._returned_gmv.sum())
        analysis_frame: pd.DataFrame
        columns: list[dict[str, str]]
        trend_key: str
        trend_title: str
        trend_format: str
        trend_secondary_key: str | None = None
        trend_secondary_label: str | None = None
        trend_secondary_format: str | None = None
        composition_title: str
        composition_format: str
        ranking_title: str
        ranking_format: str
        ranking_secondary_format: str | None = None
        module_name: str

        if topic == "market":
            analysis_frame = bundle.results["region"].data.sort_values("gmv", ascending=False).copy()
            analysis_frame["name"] = analysis_frame.market.map(lambda value: _localize(value, "region"))
            market_total = float(analysis_frame.gmv.sum())
            top = analysis_frame.iloc[0] if not analysis_frame.empty else None
            top_share = float(top.gmv / market_total) if top is not None and market_total else None
            summary = (
                "{}以{}的 GMV 位列第一，占当前市场组合的{:.1%}；策略判断为“{}”。".format(
                    top["name"], "¥{:,.0f}".format(top.gmv), top_share or 0.0, top.strategy,
                ) if top is not None else "当前筛选范围没有可参与市场比较的订单。"
            )
            metrics = [
                metric("market_gmv", "市场 GMV", gmv, "currency", "gmv"),
                metric("market_count", "覆盖市场", len(analysis_frame), "integer", "markets"),
                metric("top_market_share", "头部市场占比", top_share, "percent", "top_market_share"),
                metric("delivery_mean", "平均履约天数", float(source.delivery_time_days.mean()) if "delivery_time_days" in source else None, "decimal", "delivery_mean"),
            ]
            composition = composition_rows(analysis_frame, "market", "gmv", "region")
            ranking = ranking_rows(analysis_frame, "market", "gmv", "profit_rate", "region")
            columns = [
                {"key": "name", "label": "市场", "format": "text"}, {"key": "gmv", "label": "GMV", "format": "currency"},
                {"key": "orders", "label": "订单数", "format": "integer"}, {"key": "customers", "label": "客户数", "format": "integer"},
                {"key": "profit_rate", "label": "利润率", "format": "percent"}, {"key": "return_rate", "label": "退货率", "format": "percent"},
                {"key": "delivery_p90", "label": "履约 P90", "format": "days"}, {"key": "strategy", "label": "投入策略", "format": "text"},
            ]
            trend_key, trend_title, trend_format = "gmv", "市场 GMV 趋势", "currency"
            composition_title, composition_format = "市场 GMV 构成", "currency"
            ranking_title, ranking_format, ranking_secondary_format = "市场规模排名", "currency", "percent"
            module_name = "region"
        elif topic == "product":
            analysis_frame = bundle.results["product"].data["products"].sort_values("gmv", ascending=False).copy()
            analysis_frame["name"] = analysis_frame.product_name.fillna(analysis_frame.product_id)
            category_frame = source.groupby("category", dropna=False)._gmv.sum().rename("gmv").reset_index()
            top = analysis_frame.iloc[0] if not analysis_frame.empty else None
            summary = (
                "{}贡献{} GMV，当前归类为“{}”；商品矩阵共有{:,}个商品达到三笔订单门槛。".format(
                    top["name"], "¥{:,.0f}".format(top.gmv), top.classification,
                    int(bundle.results["product"].data.get("eligible_products", 0)),
                ) if top is not None else "当前筛选范围没有商品经营记录。"
            )
            metrics = [
                metric("product_gmv", "商品 GMV", gmv, "currency", "gmv"),
                metric("units", "商品销量", float(source.quantity.sum()) if "quantity" in source else None, "integer", "units"),
                metric("product_count", "经营商品", int(source.product_id.nunique()), "integer", "products"),
                metric("product_return_rate", "商品退货率", returned_orders / orders if orders else None, "percent", "return_rate"),
            ]
            composition = composition_rows(category_frame, "category", "gmv", "category")
            ranking = ranking_rows(analysis_frame, "name", "gmv", "classification")
            columns = [
                {"key": "name", "label": "商品", "format": "text"}, {"key": "product_id", "label": "商品编码", "format": "text"},
                {"key": "primary_category", "label": "主要品类", "format": "category"}, {"key": "gmv", "label": "GMV", "format": "currency"},
                {"key": "orders", "label": "订单数", "format": "integer"}, {"key": "units", "label": "销量", "format": "integer"},
                {"key": "profit_rate", "label": "利润率", "format": "percent"}, {"key": "classification", "label": "经营分类", "format": "text"},
            ]
            trend_key, trend_title, trend_format = "units", "商品销量趋势", "integer"
            trend_secondary_key, trend_secondary_label, trend_secondary_format = "products", "经营商品数", "integer"
            composition_title, composition_format = "品类 GMV 构成", "currency"
            ranking_title, ranking_format, ranking_secondary_format = "商品 GMV 排名", "currency", "text"
            module_name = "product"
        elif topic == "customer":
            segments = bundle.results["customer"].data["segments"].sort_values("gmv", ascending=False).copy()
            analysis_frame = bundle.results["customer"].data["customers"].sort_values("monetary", ascending=False).copy()
            analysis_frame["name"] = analysis_frame.customer_id
            customer_count = int(source.customer_id.nunique())
            top = segments.iloc[0] if not segments.empty else None
            summary = (
                "{}贡献{} GMV，覆盖{:,}名客户；RFM 锚点为{}。".format(
                    top.segment, "¥{:,.0f}".format(top.gmv), int(top.customers),
                    bundle.results["customer"].data.get("anchor_date"),
                ) if top is not None else "当前筛选范围没有可进行 RFM 分群的客户。"
            )
            metrics = [
                metric("customers", "客户数", customer_count, "integer", "customers"),
                metric("customer_gmv", "客户 GMV", gmv, "currency", "gmv"),
                metric("gmv_per_customer", "人均贡献", gmv / customer_count if customer_count else None, "currency", "gmv_per_customer"),
                metric("frequency", "平均购买频次", orders / customer_count if customer_count else None, "decimal", "frequency"),
            ]
            composition = composition_rows(segments, "segment", "customers")
            ranking = ranking_rows(segments, "segment", "gmv", "customers")
            columns = [
                {"key": "customer_id", "label": "客户", "format": "text"}, {"key": "segment", "label": "客户分群", "format": "text"},
                {"key": "recency_days", "label": "最近购买间隔", "format": "days"}, {"key": "frequency", "label": "购买频次", "format": "integer"},
                {"key": "monetary", "label": "累计贡献", "format": "currency"}, {"key": "r_score", "label": "R 分", "format": "integer"},
                {"key": "f_score", "label": "F 分", "format": "integer"}, {"key": "m_score", "label": "M 分", "format": "integer"},
            ]
            trend_key, trend_title, trend_format = "customers", "月度活跃客户趋势", "integer"
            trend_secondary_key, trend_secondary_label, trend_secondary_format = "gmv_per_customer", "人均贡献", "currency"
            composition_title, composition_format = "RFM 客户构成", "integer"
            ranking_title, ranking_format, ranking_secondary_format = "客户分群价值排名", "currency", "integer"
            module_name = "customer"
            churn = next((row for _, row in segments.iterrows() if row.segment == "流失风险客户"), None)
        elif topic == "profit":
            analysis_frame = bundle.results["product"].data["products"].sort_values("profit", ascending=False).copy()
            analysis_frame["name"] = analysis_frame.product_name.fillna(analysis_frame.product_id)
            category_profit = source.groupby("category", dropna=False)._profit.sum().rename("profit").reset_index()
            top = analysis_frame.iloc[0] if not analysis_frame.empty else None
            loss_products = analysis_frame.loc[analysis_frame.profit.lt(0)]
            loss_amount = abs(float(loss_products.profit.sum()))
            summary = (
                "{}贡献利润{}，位列商品利润第一；当前有{:,}个亏损商品，合计亏损{}。".format(
                    top["name"], "¥{:,.0f}".format(top.profit), len(loss_products), "¥{:,.0f}".format(loss_amount),
                ) if top is not None else "当前筛选范围缺少可复算利润记录。"
            )
            metrics = [
                metric("profit", "利润", profit, "currency", "profit"),
                metric("profit_rate", "利润率", profit / gmv if gmv else None, "percent", "profit_rate"),
                metric("profitable_products", "盈利商品", int(analysis_frame.profit.gt(0).sum()), "integer", "profitable_products"),
                metric("loss_amount", "商品亏损额", loss_amount, "currency", "loss_amount"),
            ]
            composition = composition_rows(category_profit, "category", "profit", "category")
            ranking = ranking_rows(analysis_frame, "name", "profit", "profit_rate")
            columns = [
                {"key": "name", "label": "商品", "format": "text"}, {"key": "product_id", "label": "商品编码", "format": "text"},
                {"key": "primary_category", "label": "主要品类", "format": "category"}, {"key": "profit", "label": "利润", "format": "currency"},
                {"key": "profit_rate", "label": "利润率", "format": "percent"}, {"key": "gmv", "label": "GMV", "format": "currency"},
                {"key": "orders", "label": "订单数", "format": "integer"}, {"key": "classification", "label": "经营分类", "format": "text"},
            ]
            trend_key, trend_title, trend_format = "profit", "月度利润趋势", "currency"
            trend_secondary_key, trend_secondary_label, trend_secondary_format = "profit_rate", "利润率", "percent"
            composition_title, composition_format = "品类利润构成", "currency"
            ranking_title, ranking_format, ranking_secondary_format = "商品利润贡献排名", "currency", "percent"
            module_name = "product"
        elif topic == "returns":
            product_returns = source.groupby("product_id").agg(
                orders=("order_id", "nunique"), returned_orders=("_returned", "sum"),
                gmv=("_gmv", "sum"), returned_gmv_exposure=("_returned_gmv", "sum"),
            ).reset_index()
            product_returns["return_rate"] = product_returns.returned_orders / product_returns.orders.where(product_returns.orders.ne(0))
            product_lookup = bundle.results["product"].data["products"][["product_id", "product_name", "primary_category"]]
            analysis_frame = product_returns.merge(product_lookup, on="product_id", how="left").sort_values(["return_rate", "orders"], ascending=[False, False])
            analysis_frame["name"] = analysis_frame.product_name.fillna(analysis_frame.product_id)
            category_returns = source.groupby("category", dropna=False).agg(
                returned_gmv_exposure=("_returned_gmv", "sum"), orders=("order_id", "nunique"), returned_orders=("_returned", "sum"),
            ).reset_index()
            category_returns["return_rate"] = category_returns.returned_orders / category_returns.orders.where(category_returns.orders.ne(0))
            eligible_ranking = analysis_frame.loc[analysis_frame.orders.ge(3)]
            top = category_returns.sort_values("return_rate", ascending=False).iloc[0] if not category_returns.empty else None
            summary = (
                "{}退货率最高，为{:.1%}；退货关联 GMV 为{}，该金额不代表实际退款损失。".format(
                    _localize(top.category, "category"), top.return_rate, "¥{:,.0f}".format(top.returned_gmv_exposure),
                ) if top is not None else "当前筛选范围没有可计算退货率的订单。"
            )
            metrics = [
                metric("return_rate", "退货率", returned_orders / orders if orders else None, "percent", "return_rate"),
                metric("returned_orders", "退货订单", returned_orders, "integer", "returned_orders"),
                metric("returned_exposure", "退货关联 GMV", returned_exposure, "currency", "returned_gmv_exposure"),
                metric("return_exposure_share", "关联 GMV 占比", returned_exposure / gmv if gmv else None, "percent", "return_exposure_share"),
            ]
            composition = composition_rows(category_returns, "category", "returned_gmv_exposure", "category")
            ranking = ranking_rows(eligible_ranking, "name", "return_rate", "orders")
            columns = [
                {"key": "name", "label": "商品", "format": "text"}, {"key": "product_id", "label": "商品编码", "format": "text"},
                {"key": "primary_category", "label": "主要品类", "format": "category"}, {"key": "orders", "label": "订单数", "format": "integer"},
                {"key": "returned_orders", "label": "退货订单", "format": "integer"}, {"key": "return_rate", "label": "退货率", "format": "percent"},
                {"key": "returned_gmv_exposure", "label": "退货关联 GMV", "format": "currency"}, {"key": "gmv", "label": "GMV", "format": "currency"},
            ]
            trend_key, trend_title, trend_format = "return_rate", "月度退货率趋势", "percent"
            trend_secondary_key, trend_secondary_label, trend_secondary_format = "returned_orders", "退货订单", "integer"
            composition_title, composition_format = "品类退货关联 GMV", "currency"
            ranking_title, ranking_format, ranking_secondary_format = "高退货商品排名", "percent", "integer"
            module_name = "returns"
        else:
            raise KeyError(topic)

        available_months = complete_months
        comparison_count = min(6, max(1, len(available_months) // 2))
        current_months = available_months[-comparison_count:]
        comparison_months = available_months[-2 * comparison_count:-comparison_count]
        if not comparison_months and len(available_months) > 1:
            comparison_months = available_months[:-1]
            current_months = available_months[-1:]

        current_source = source.loc[source.month.isin(current_months)].copy()
        comparison_source = source.loc[source.month.isin(comparison_months)].copy()

        def period_for(frame: pd.DataFrame) -> dict[str, str | None]:
            if frame.empty:
                return {"start": None, "end": None}
            return {
                "start": frame.order_date.min().date().isoformat(),
                "end": frame.order_date.max().date().isoformat(),
            }

        current_period = period_for(current_source)
        comparison_period = period_for(comparison_source)

        decision_config = {
            "market": {
                "trend_title": "市场 GMV 趋势对比", "trend_format": "currency", "trend_metric": "gmv",
            },
            "product": {
                "trend_title": "商品销量趋势对比", "trend_format": "integer", "trend_metric": "units",
            },
            "customer": {
                "trend_title": "活跃客户趋势对比", "trend_format": "integer", "trend_metric": "customers",
            },
            "profit": {
                "trend_title": "利润趋势对比", "trend_format": "currency", "trend_metric": "profit",
            },
            "returns": {
                "trend_title": "退货率趋势对比", "trend_format": "percent", "trend_metric": "return_rate",
            },
        }[topic]

        def monthly_value(frame: pd.DataFrame, month_value: str, metric_id: str) -> float | None:
            rows = frame.loc[frame.month.eq(month_value)]
            if rows.empty:
                return None
            if metric_id == "units":
                return float(pd.to_numeric(rows.get("quantity"), errors="coerce").fillna(0).sum()) if "quantity" in rows else None
            if metric_id == "customers":
                return float(rows.customer_id.nunique()) if "customer_id" in rows else None
            if metric_id == "profit":
                return float(rows._profit.sum())
            if metric_id == "return_rate":
                period_orders = int(rows.order_id.nunique())
                return float(rows._returned.sum() / period_orders) if period_orders else None
            return float(rows._gmv.sum())

        comparison_trend_rows = []
        for index, current_month in enumerate(current_months):
            previous_month = comparison_months[index] if index < len(comparison_months) else None
            comparison_trend_rows.append({
                "label": "{}月".format(str(current_month)[5:7]),
                "current_period": current_month,
                "comparison_period": previous_month,
                "current": monthly_value(current_source, current_month, decision_config["trend_metric"]),
                "comparison": monthly_value(comparison_source, previous_month, decision_config["trend_metric"]) if previous_month else None,
            })

        current_label = "{} 至 {}".format(current_period["start"], current_period["end"])
        comparison_label = "{} 至 {}".format(comparison_period["start"], comparison_period["end"])
        formal = formal_topic_decisions(bundle, topic, current_period)
        decision_summary = formal["summary"]
        anomalies = formal["anomalies"]
        drivers = formal["drivers"]
        findings = formal["findings"]
        evidence = formal["evidence"]
        actions = formal["actions"]

        decision_board = {
            "basis": "本期 {}；上期 {}。异常、诊断和建议仅来自正式版本化分析链路。".format(current_label, comparison_label),
            "trend": {
                "title": decision_config["trend_title"], "format": decision_config["trend_format"],
                "current_period": current_period, "comparison_period": comparison_period,
                "rows": comparison_trend_rows,
            },
            "anomalies": anomalies,
            "drivers": drivers,
        }

        detail_frame = analysis_frame.copy()
        detail_records = _records(detail_frame)

        scenario = self.scenario(dataset_id)
        filter_source = self._context_for(dataset_id).analysis_data.copy()
        for field, values in scenario.filters.items():
            if field in filter_source:
                filter_source = filter_source.loc[filter_source[field].astype(str).isin([str(value) for value in values])]
        market_options = sorted(str(value) for value in filter_source[market_field].dropna().unique()) if market_field in filter_source else []
        category_options = sorted(str(value) for value in filter_source.category.dropna().unique()) if "category" in filter_source else []

        trend_rows = [
            {
                "period": row.month,
                "value": row[trend_key],
                "secondary": row.get(trend_secondary_key) if trend_secondary_key else None,
            }
            for _, row in monthly.tail(12).iterrows()
        ]
        report = {
            "title": "{}专题分析报告".format({"market": "市场", "product": "商品", "customer": "客户", "profit": "利润", "returns": "退货"}[topic]),
            "generated_at": bundle.generated_at,
            "period": {"start": start or self.date_bounds(dataset_id)[0], "end": end or self.date_bounds(dataset_id)[1]},
            "filters": {"market": market or "全部市场", "category": _localize(category, "category") if category else "全部品类"},
            "summary": decision_summary,
            "findings": findings,
            "evidence": evidence,
            "actions": actions,
        }
        return _clean({
            "topic": topic,
            "summary": decision_summary,
            "metrics": metrics,
            "trend": {
                "title": trend_title, "format": trend_format, "rows": trend_rows,
                "secondary_label": trend_secondary_label, "secondary_format": trend_secondary_format,
            },
            "composition": {"title": composition_title, "format": composition_format, "rows": composition},
            "ranking": {"title": ranking_title, "format": ranking_format, "secondary_format": ranking_secondary_format, "rows": ranking},
            "columns": columns,
            "details": [],
            "pagination": {"page": 1, "page_size": 0, "total": 0, "pages": 1},
            "_detail_records": detail_records,
            "filters": {
                "start": start or self.date_bounds(dataset_id)[0], "end": end or self.date_bounds(dataset_id)[1],
                "markets": [{"value": value, "label": _localize(value, "region")} for value in market_options],
                "categories": [{"value": value, "label": _localize(value, "category")} for value in category_options],
            },
            "decision_board": decision_board,
            "ai": {"findings": findings, "evidence": evidence, "actions": actions},
            "report": report,
        }), bundle

    def topic_export(
        self,
        dataset_id: str,
        topic: str,
        start: str | None,
        end: str | None,
        market: str | None,
        category: str | None,
        search: str,
    ) -> tuple[dict, Any]:
        data, bundle = self.topic(
            dataset_id, topic, start, end, market, category, search, 1, 1_000_000,
        )
        return {"columns": data["columns"], "rows": data["details"]}, bundle

    def datasets(self) -> list[dict[str, Any]]:
        items = []
        for scenario in SCENARIOS + self._imported_scenarios():
            context = self._context_for(scenario.dataset_id)
            start, end = self.date_bounds(scenario.dataset_id)
            profile_frame = context.analysis_data
            for field, values in scenario.filters.items():
                profile_frame = profile_frame[profile_frame[field].isin(values)]
            count = len(profile_frame)
            profile_context = replace(context, analysis_data=profile_frame.copy())
            quality, _, _, _, _, _ = assess_business_quality(
                profile_context, scenario.dataset_id, "dataset-profile"
            )
            items.append({
                "dataset_id": scenario.dataset_id,
                "name": scenario.name,
                "description": scenario.description,
                "source_type": scenario.source_type,
                "row_count": count,
                "status": "READY",
                "quality_score": quality.quality_score,
                "period_start": start,
                "period_end": end,
                "updated_at": scenario.created_at or pd.Timestamp.now().isoformat(),
                "is_demo": scenario.is_demo,
            })
        return items

    def dataset_detail(self, dataset_id: str) -> tuple[dict, Any]:
        bundle = self.bundle(dataset_id)
        scenario = self.scenario(dataset_id)
        context = self._context_for(dataset_id)
        quality = bundle.artifacts.data_quality
        capabilities = [item.to_dict() for item in bundle.artifacts.analysis_capability]
        fields = [item.to_dict() for item in bundle.artifacts.field_quality]
        query_runs = bundle.metadata.get("query_runs", [])
        lineage = (
            {"source": SAMPLE.name, "scenario_filters": scenario.filters, "raw_read_only": True}
            if scenario.is_demo else context.lineage
        )
        profile_frame = context.analysis_data
        for field, values in scenario.filters.items():
            if field in profile_frame:
                profile_frame = profile_frame.loc[profile_frame[field].isin(values)]
        source_files = lineage.get("source_files") if isinstance(lineage, dict) else None
        import_history = (
            source_files if isinstance(source_files, list) else [{
                "source_filename": SAMPLE.name if scenario.is_demo else context.metadata.get("filename", "uploaded"),
                "source_type": scenario.source_type,
                "rows": len(profile_frame) if scenario.is_demo else context.metadata.get("rows"),
                "status": "READY",
                "created_at": scenario.created_at or context.metadata.get("created_at"),
            }]
        )
        fx_rates = context.metadata.get("fx_rates")
        fx_rate_rows = len(fx_rates) if hasattr(fx_rates, "__len__") else 0
        return _clean({
            "dataset": next(item for item in self.datasets() if item["dataset_id"] == dataset_id),
            "quality": quality.to_dict() if quality else None,
            "quality_dimensions": [item.to_dict() for item in bundle.artifacts.data_quality_dimensions],
            "fields": fields,
            "capabilities": capabilities,
            "query_runs": list(query_runs)[-10:],
            "lineage": lineage,
            "import_history": import_history,
            "metric_catalog": [item.to_dict() for item in METRICS_CATALOG],
            "rule_catalog": [item.to_dict() for item in ANOMALY_RULES],
            "capacity": self._artifact_store().capacity(),
            "fx_lineage": {
                "source_currency": context.metadata.get("source_currency"),
                "target_currency": context.metadata.get("target_currency"),
                "fx_complete": context.metadata.get("fx_complete"),
                "fx_provider": context.metadata.get("fx_provider"),
                "rate_rows": fx_rate_rows,
            },
        }), bundle

    def archive_dataset(self, dataset_id: str) -> bool:
        scenario = self.scenario(dataset_id)
        if scenario.is_demo:
            raise PermissionError("演示数据集不能归档")
        archived = self._database().archive_dataset(dataset_id)
        if archived:
            self.clear_analysis_cache()
        return archived

    def import_dataset(
        self,
        loaded,
        *,
        mapping: dict[str, str],
        source_file_id: str,
        dataset_name: str,
        data_grain: str,
        amount_semantic: str,
        source_currency: str | None,
        target_currency: str,
    ) -> dict[str, Any]:
        return self.dataset_service.import_dataset(
            loaded,
            mapping=mapping,
            source_file_id=source_file_id,
            dataset_name=dataset_name,
            data_grain=data_grain,
            amount_semantic=amount_semantic,
            source_currency=source_currency,
            target_currency=target_currency,
        )

    def import_datasets(
        self,
        loaded_files: list[tuple[Any, str]],
        *,
        mapping: dict[str, str],
        dataset_name: str,
        data_grain: str,
        amount_semantic: str,
        source_currency: str | None,
        target_currency: str,
    ) -> dict[str, Any]:
        return self.dataset_service.import_datasets(
            loaded_files,
            mapping=mapping,
            dataset_name=dataset_name,
            data_grain=data_grain,
            amount_semantic=amount_semantic,
            source_currency=source_currency,
            target_currency=target_currency,
        )

    def update_work_item(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.app_mode != "private":
            raise PermissionError("演示模式不允许永久修改任务")
        normalized = normalize_work_item_patch(payload)
        self._work_items[item_id] = {"id": item_id, **normalized}
        if self.state_store:
            self.state_store.save_work_item(item_id, self._work_items[item_id])
        return self._work_items[item_id]

    def agent_context(
        self, dataset_id: str, question: str, start: str | None = None,
        end: str | None = None, market: str | None = None, category: str | None = None,
    ) -> tuple[dict[str, Any], Any]:
        overview, bundle = self.overview(dataset_id, start, end)
        if market or category:
            bundle = self.bundle(dataset_id, start, end, market, category)
        lowered = question.lower()
        tool_names = ["get_dataset_profile", "get_data_quality", "query_metrics"]
        tool_names.extend(["get_metric", "compare_periods"])
        decision_requested = any(token in lowered for token in ("建议", "行动", "怎么办", "报告"))
        diagnosis_requested = decision_requested or any(
            token in lowered for token in ("异常", "下降", "风险", "为什么", "原因", "问题")
        )
        if diagnosis_requested:
            tool_names.extend(["list_anomalies", "get_diagnosis", "get_evidence"])
        if decision_requested:
            tool_names.extend(["create_task", "get_recommendations", "generate_report", "generate_review_report", "explain_limitation"])
        quality = bundle.artifacts.data_quality.to_dict() if bundle.artifacts.data_quality else None
        insights = [item.to_dict() for item in bundle.artifacts.insights[:5]]
        evidence = [item.to_dict() for item in bundle.artifacts.evidence[:3]]
        recommendations = [item.to_dict() for item in bundle.artifacts.recommendations[:5]]
        decision_brief = build_decision_brief(bundle.artifacts, bundle.metadata)
        anomaly_by_id = {item.anomaly_id: item for item in bundle.artifacts.anomalies}
        trace = []
        for insight in bundle.artifacts.insights[:5]:
            anomaly = anomaly_by_id.get(insight.anomaly_id or "")
            trace.append({
                "insight_id": insight.insight_id,
                "anomaly_id": insight.anomaly_id,
                "rule_id": anomaly.rule_id if anomaly else None,
                "rule_version": anomaly.rule_version if anomaly else None,
                "metric_id": insight.metric_id,
                "evidence_ids": list(insight.evidence_ids),
            })
        execution_context = {
            "question": question,
            "dataset": {
                "dataset_id": dataset_id,
                "name": self.scenario(dataset_id).name,
            },
            "period": overview["period"],
            "filters": {"start": start, "end": end, "market": market, "category": category},
            "scope_id": bundle.metadata.get("scope_id"),
            "overview": overview,
            "quality": quality,
            "insights": insights,
            "evidence": evidence,
            "recommendations": recommendations,
            "decision_brief": decision_brief,
            "trace": trace,
        }
        agent_plan = self.agent_tools.plan(question, execution_context)
        planned_tools = [
            tool
            for step in agent_plan
            for tool in step.get("tools", [])
        ]
        tool_names = list(dict.fromkeys(planned_tools or tool_names))
        tool_observations = self.agent_tools.execute_plan(agent_plan, execution_context)
        return _clean({
            "question": question,
            "dataset": {
                "dataset_id": dataset_id,
                "name": self.scenario(dataset_id).name,
            },
            "period": overview["period"],
            "filters": {"start": start, "end": end, "market": market, "category": category},
            "scope_id": bundle.metadata.get("scope_id"),
            "tools": list(dict.fromkeys(tool_names)),
            "agent_plan": agent_plan,
            "overview": overview,
            "quality": quality,
            "insights": insights,
            "evidence": evidence,
            "recommendations": recommendations,
            "decision_brief": decision_brief,
            "trace": trace,
            "tool_observations": tool_observations,
        }), bundle

    def export(
        self, dataset_id: str, report_format: str, start: str | None = None,
        end: str | None = None, market: str | None = None, category: str | None = None,
        scope_id: str | None = None,
    ):
        return export_scoped_bundle(self, dataset_id, report_format, start, end, market, category, scope_id)
