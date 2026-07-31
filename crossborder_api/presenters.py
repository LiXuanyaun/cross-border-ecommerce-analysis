from __future__ import annotations

from functools import lru_cache
from typing import Any
from types import SimpleNamespace
from datetime import datetime, timezone
import math

import pandas as pd

from .runtime import (
    SAMPLE, METRIC_LABELS, _clean, _entity_label, _localize, _rate, _records, _threshold_text,
)
from .topic_decisions import customer_normal_decisions, formal_topic_decisions
from .presentation_contracts import build_topic_presentation_contract
from crossborder_analytics.decision import market_series, resolve_market_field
from crossborder_analytics.modules import amount_column
from crossborder_analytics.metrics import build_scope_id
from crossborder_analytics.phase2_models import AnalysisRequest


class _RuntimeBackedPresenter:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def __getattr__(self, name: str) -> Any:
        return getattr(self.runtime, name)


class OverviewPresenter(_RuntimeBackedPresenter):
    def present(self, dataset_id: str, start: str | None = None, end: str | None = None) -> tuple[dict, Any]:
        capability_contract = self.runtime.dataset_capabilities(
            dataset_id, fact="orders", start=start, end=end,
        )
        capability = capability_contract["facts"]["orders"]
        if capability["state"] in {"EMPTY", "OUT_OF_RANGE", "INSUFFICIENT_DATA", "FAILED", "FATAL"}:
            return self._empty_overview(dataset_id, start, end, capability)
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
        market_field = (
            bundle.metadata.get("market_dimension")
            or resolve_market_field(market_current)
            or resolve_market_field(source)
        )
        source["_market"] = market_series(source, market_field)
        market_current = source.loc[source.order_date.between(current_period["start"], current_period["end"])]
        market_previous = source.loc[source.order_date.between(yoy_start, yoy_end)]
        current_market_gmv = market_current.groupby("_market")[amount].sum() if market_field else pd.Series(dtype=float)
        previous_market_gmv = market_previous.groupby("_market")[amount].sum() if market_field else pd.Series(dtype=float)
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
            "data_state": capability["state"],
            "available_periods": capability["available_periods"],
            "recommended_period": capability["recommended_period"],
            "requested_period": capability["requested_period"],
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

    def _empty_overview(self, dataset_id, start, end, capability):
        selected = capability.get("requested_period") or capability.get("recommended_period")
        if selected is None:
            periods = capability.get("available_periods") or []
            selected = {"start": periods[-1]["start"], "end": periods[-1]["end"]} if periods else {"start": start or "", "end": end or ""}
        scenario = self.scenario(dataset_id)
        filters: dict[str, Any] = {key: list(values) for key, values in scenario.filters.items()}
        if selected["start"] and selected["end"]:
            filters["order_date"] = (selected["start"], selected["end"])
        request = AnalysisRequest(filters=filters)
        metadata = scenario.metadata or {}
        currency = str(metadata.get("target_currency") or metadata.get("source_currency") or "CNY")
        scope_id = build_scope_id(dataset_id, request, currency)
        bundle = SimpleNamespace(
            metadata={"scope_id": scope_id, "dataset_id": dataset_id},
            artifacts=SimpleNamespace(data_quality=None),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        period = {"start": selected["start"], "end": selected["end"], "type": "selection"}
        trend = {"grain": "day", "current_period": period, "comparison_period": period, "rows": []}
        methodology_item = {"basis": "当前范围没有订单事实", "comparison": "不可比较", "threshold": "事实记录数必须大于 0"}
        return {
            "scope_id": scope_id,
            "data_state": capability["state"],
            "available_periods": capability.get("available_periods", []),
            "recommended_period": capability.get("recommended_period"),
            "requested_period": capability.get("requested_period"),
            "period": period, "current_period": period, "comparison_period": period,
            "selection_period": period, "market_comparison_period": period,
            "kpis": [], "trends": {"day": trend, "week": {**trend, "grain": "week"}}, "trend": [],
            "markets": [], "categories": [], "tasks": [], "opportunities": [], "insights": [],
            "methodology": {key: methodology_item for key in ("kpis", "trend", "tasks", "markets", "products", "opportunities", "insights")},
            "currency": currency,
        }, bundle




class TopicPresenter(_RuntimeBackedPresenter):
    def clear_cache(self) -> None:
        self._topic_base.cache_clear()

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

    def present(
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
        capability_contract = self.runtime.dataset_capabilities(
            dataset_id, fact="orders", start=start, end=end,
        )
        capability = capability_contract["facts"]["orders"]
        if capability["state"] in {"EMPTY", "OUT_OF_RANGE", "INSUFFICIENT_DATA", "FAILED", "FATAL"}:
            data, bundle = self._empty_topic(
                dataset_id, topic, start, end, market, category, capability,
            )
            data["pagination"] = {"page": page, "page_size": page_size, "total": 0, "pages": 1}
            data.update(build_topic_presentation_contract(data))
            return data, bundle
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
            "data_state": capability["state"],
            "available_periods": capability["available_periods"],
            "recommended_period": capability["recommended_period"],
            "requested_period": capability["requested_period"],
            "details": rows,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "pages": max(1, math.ceil(total / page_size)),
            },
        }
        data.update(build_topic_presentation_contract(data))
        return data, bundle

    def _empty_topic(self, dataset_id, topic, start, end, market, category, capability):
        selected = capability.get("requested_period") or capability.get("recommended_period")
        if selected is None:
            periods = capability.get("available_periods") or []
            selected = {"start": periods[-1]["start"], "end": periods[-1]["end"]} if periods else {"start": start or "", "end": end or ""}
        scenario = self.scenario(dataset_id)
        filters: dict[str, Any] = {key: list(values) for key, values in scenario.filters.items()}
        if selected["start"] and selected["end"]:
            filters["order_date"] = (selected["start"], selected["end"])
        if market:
            filters["region"] = [market]
        if category:
            filters["category"] = [category]
        request = AnalysisRequest(filters=filters, analysis_mode="topic", topic=topic)
        metadata = scenario.metadata or {}
        currency = str(metadata.get("target_currency") or metadata.get("source_currency") or "CNY")
        scope_id = build_scope_id(dataset_id, request, currency)
        bundle = SimpleNamespace(
            metadata={"scope_id": scope_id, "dataset_id": dataset_id},
            artifacts=SimpleNamespace(data_quality=None),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        empty_period = {"start": selected["start"], "end": selected["end"], "type": "month"}
        state_label = "当前选择时期与订单事实不相交" if capability["state"] == "OUT_OF_RANGE" else "当前范围没有可分析的订单事实"
        trend = {
            "title": "当前范围趋势", "format": "currency", "secondary_label": None,
            "secondary_format": None, "rows": [],
        }
        data = {
            "topic": topic,
            "scope_id": scope_id,
            "summary": state_label,
            "data_state": capability["state"],
            "available_periods": capability.get("available_periods", []),
            "recommended_period": capability.get("recommended_period"),
            "requested_period": capability.get("requested_period"),
            "metrics": [],
            "trend": trend,
            "composition": {"title": "当前范围构成", "format": "currency", "rows": []},
            "ranking": {"title": "当前范围排名", "format": "currency", "secondary_format": None, "rows": []},
            "columns": [],
            "details": [],
            "filters": {"start": selected["start"], "end": selected["end"], "markets": [], "categories": []},
            "decision_board": {
                "basis": state_label,
                "trend": {**trend, "current_period": empty_period, "comparison_period": empty_period},
                "anomalies": [], "drivers": [],
                "state": {"status": "INSUFFICIENT", "title": state_label, "description": "请使用可用时期后重新分析。", "missing_fields": capability.get("missing_fields", [])},
            },
            "ai": {"findings": [], "evidence": [], "actions": []},
            "report": {
                "title": "{}专题分析".format(topic), "generated_at": bundle.generated_at,
                "period": empty_period, "filters": {"market": market or "全部", "category": category or "全部"},
                "summary": state_label, "findings": [], "evidence": [], "actions": [],
            },
        }
        data.update(build_topic_presentation_contract(data))
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
        # Topic views share the full-scope artifacts with overview; their own
        # filtering and presentation happen below and must not overwrite that scope.
        bundle = self.bundle(
            dataset_id, start, end, market, category, analysis_mode="full", topic=None,
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
        market_field = resolve_market_field(source) or "region"
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

        # The overview already exposes daily and weekly buckets. Topic pages use
        # the same rule so a one-month dataset does not collapse to one point.
        current_start = pd.Timestamp(current_period["start"]) if current_period["start"] else None
        current_end = pd.Timestamp(current_period["end"]) if current_period["end"] else None
        span_days = (current_end - current_start).days + 1 if current_start is not None and current_end is not None else 0
        trend_grain = "day" if span_days <= 45 else "week" if span_days <= 180 else "month"

        def trend_bucket(value: pd.Series, grain: str) -> pd.Series:
            dates = pd.to_datetime(value)
            if grain == "day":
                return dates.dt.normalize()
            if grain == "week":
                return dates.dt.to_period("W-SUN").dt.start_time
            return dates.dt.to_period("M").dt.start_time

        def bucket_keys(period: dict[str, str | None], grain: str) -> list[pd.Timestamp]:
            if not period["start"] or not period["end"]:
                return []
            start_value = pd.Timestamp(period["start"])
            end_value = pd.Timestamp(period["end"])
            if grain == "day":
                return list(pd.date_range(start_value, end_value, freq="D"))
            if grain == "week":
                start_value = start_value.to_period("W-SUN").start_time
                end_value = end_value.to_period("W-SUN").start_time
                return list(pd.date_range(start_value, end_value, freq="7D"))
            start_value = start_value.to_period("M").start_time
            end_value = end_value.to_period("M").start_time
            return list(pd.date_range(start_value, end_value, freq="MS"))

        current_trend_source = current_source.copy()
        comparison_trend_source = comparison_source.copy()
        current_trend_source["_trend_bucket"] = trend_bucket(current_trend_source.order_date, trend_grain)
        comparison_trend_source["_trend_bucket"] = trend_bucket(comparison_trend_source.order_date, trend_grain)

        def trend_value(frame: pd.DataFrame, bucket: pd.Timestamp, metric_id: str) -> float | None:
            rows = frame.loc[frame["_trend_bucket"].eq(bucket)]
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

        current_keys = bucket_keys(current_period, trend_grain)
        comparison_keys = bucket_keys(comparison_period, trend_grain)
        comparison_trend_rows = []
        for index, current_bucket in enumerate(current_keys):
            comparison_bucket = comparison_keys[index] if index < len(comparison_keys) else None
            if trend_grain == "day":
                label = current_bucket.strftime("%m-%d")
            elif trend_grain == "week":
                label = "{}周".format(current_bucket.strftime("%m-%d"))
            else:
                label = current_bucket.strftime("%Y-%m")
            comparison_trend_rows.append({
                "label": label,
                "current_period": current_bucket.date().isoformat(),
                "comparison_period": comparison_bucket.date().isoformat() if comparison_bucket is not None else None,
                "current": trend_value(current_trend_source, current_bucket, decision_config["trend_metric"]),
                "comparison": trend_value(comparison_trend_source, comparison_bucket, decision_config["trend_metric"]) if comparison_bucket is not None else None,
            })

        current_label = "{} 至 {}".format(current_period["start"], current_period["end"])
        comparison_label = (
            "{} 至 {}".format(comparison_period["start"], comparison_period["end"])
            if comparison_period["start"] and comparison_period["end"] else "暂无可比周期"
        )
        formal = formal_topic_decisions(bundle, topic, current_period)
        decision_summary = formal["summary"]
        anomalies = formal["anomalies"]
        drivers = formal["drivers"]
        findings = formal["findings"]
        evidence = formal["evidence"]
        actions = formal["actions"]
        decision_state = {
            "status": "ANOMALY" if anomalies else "HEALTHY",
            "title": "发现需要关注的异常" if anomalies else "当前范围未发现符合规则的异常",
            "description": "请按影响和证据优先级复核。" if anomalies else "继续按当前节奏监测正式指标。",
            "missing_fields": [],
        }
        if topic == "customer" and not anomalies:
            required_customer_fields = ("customer_id", "order_id", "order_date", "total_amount")
            missing_customer_fields = [
                field for field in required_customer_fields
                if field not in source or not source[field].notna().any()
            ]
            normal = customer_normal_decisions(
                customer_count=customer_count,
                order_count=orders,
                gmv=gmv,
                segments=segments,
                period=period_for(source),
                filters={
                    "market": market or "全部市场",
                    "category": _localize(category, "category") if category else "全部品类",
                },
                missing_fields=missing_customer_fields,
            )
            decision_state = normal["state"]
            decision_summary = normal["summary"]
            drivers = normal["drivers"]
            findings = normal["findings"]
            evidence = normal["evidence"]
            actions = normal["actions"]

        decision_board = {
            "basis": "本期 {}；上期 {}。异常、诊断和建议仅来自正式版本化分析链路。".format(current_label, comparison_label),
            "trend": {
                "title": decision_config["trend_title"], "format": decision_config["trend_format"],
                "grain": trend_grain,
                "current_period": current_period, "comparison_period": comparison_period,
                "rows": comparison_trend_rows,
            },
            "anomalies": anomalies,
            "drivers": drivers,
            "state": decision_state,
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

    def export(
        self,
        dataset_id: str,
        topic: str,
        start: str | None,
        end: str | None,
        market: str | None,
        category: str | None,
        search: str,
    ) -> tuple[dict, Any]:
        data, bundle = self.present(
            dataset_id, topic, start, end, market, category, search, 1, 1_000_000,
        )
        return {"columns": data["columns"], "rows": data["details"]}, bundle

