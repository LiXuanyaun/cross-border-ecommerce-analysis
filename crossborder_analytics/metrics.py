"""Metric snapshot engine backed by controlled SQL facts."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .decision import market_series
from .modules import amount_column
from .phase2_catalogs import ANOMALY_RULES, METRIC_BY_ID, METRICS_CATALOG, RECOMMENDATION_RULES
from .phase2_models import (
    AnalysisCapability, AnalysisRequest, DataQualitySummary, EntityAssessment,
    EvidenceBundle, MetricSnapshot,
)
from .phase2_utils import canonical_json, frame_digest, stable_id, utc_now


SQL_PATH = Path(__file__).resolve().parent / "sql" / "metric_facts_v1.sql"
MAX_LIFECYCLE_ASSESSMENTS = 1_000


def build_scope_id(dataset_id: str, request: AnalysisRequest, currency: str) -> str:
    request_payload = request.to_dict()
    request_payload.pop("analysis_mode", None)
    request_payload.pop("topic", None)
    versions = {
        "metrics": {item.metric_id: item.version for item in METRICS_CATALOG},
        "rules": {item.rule_id: item.version for item in ANOMALY_RULES},
        "recommendations": {item.recommendation_rule_id: item.version for item in RECOMMENDATION_RULES},
        "metric_query": sha256(SQL_PATH.read_bytes()).hexdigest(),
    }
    return stable_id("scope", dataset_id, request_payload, currency, versions)


def _pandas_facts(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=(
            "order_day", "market", "category", "sku", "order_id", "customer_id",
            "orders", "gmv", "units", "profit", "returned_orders", "returned_gmv",
        ))
    work = frame.copy()
    work["order_day"] = pd.to_datetime(work["order_date"]).dt.normalize()
    work["market"] = market_series(work) if any(field in work for field in ("country", "region")) else "未标注市场"
    work["category"] = work["category"].astype("string").str.strip().replace("", pd.NA).fillna("未标注品类") if "category" in work else "未标注品类"
    work["sku"] = work["product_id"].astype("string").str.strip().replace("", pd.NA).fillna("未标注SKU") if "product_id" in work else "未标注SKU"
    amount = amount_column(work)
    profit = amount_column(work, "profit_amount") if "profit_amount" in work else None
    work["units"] = work["quantity"] if "quantity" in work else np.nan
    work["customer_id"] = work["customer_id"] if "customer_id" in work else pd.NA
    work["profit"] = work[profit] if profit else np.nan
    for amount_field in ("cost_amount", "refund_amount", "ad_spend"):
        work[amount_field] = work[amount_column(work, amount_field)] if amount_field in work else np.nan
    work["inventory_available"] = pd.to_numeric(work["inventory_available"], errors="coerce") if "inventory_available" in work else np.nan
    work["stockout_flag"] = work["stockout_flag"].fillna(False).astype(bool).astype(int) if "stockout_flag" in work else 0
    returned = work["returned"].fillna(False).astype(bool) if "returned" in work else pd.Series(False, index=work.index)
    work["returned_orders"] = returned.astype(int)
    work["returned_gmv"] = np.where(returned, work[amount], 0.0)
    work["orders"] = 1
    work["gmv"] = work[amount]
    return work[[
        "order_day", "market", "category", "sku", "order_id", "customer_id",
        "orders", "gmv", "units", "profit", "cost_amount", "refund_amount", "ad_spend",
        "inventory_available", "stockout_flag", "returned_orders", "returned_gmv",
    ]].reset_index(drop=True)


def _periods(facts: pd.DataFrame, request: AnalysisRequest) -> List[Tuple[str, pd.Timestamp, pd.Timestamp, bool]]:
    if facts.empty:
        return []
    start = pd.Timestamp(facts["order_day"].min()).normalize()
    end = pd.Timestamp(facts["order_day"].max()).normalize()
    output = [("selection", start, end, True)]
    if request.period_type == "event":
        output.extend((
            ("event_baseline", pd.Timestamp(request.comparison_start), pd.Timestamp(request.comparison_end), True),
            ("event", pd.Timestamp(request.period_start), pd.Timestamp(request.period_end), True),
        ))
        return output
    if request.period_type == "week":
        cursor = start - pd.Timedelta(days=start.weekday())
        while cursor <= end:
            period_end = cursor + pd.Timedelta(days=6)
            output.append(("week", cursor, period_end, cursor >= start and period_end <= end))
            cursor += pd.Timedelta(days=7)
        return output
    for period in pd.period_range(start.to_period("M"), end.to_period("M"), freq="M"):
        period_start = period.start_time.normalize()
        period_end = period.end_time.normalize()
        output.append(("month", period_start, period_end, period_start >= start and period_end <= end))
    return output


def _capability_lookup(capabilities: Sequence[AnalysisCapability]) -> Mapping[str, str]:
    return {item.capability_id: str(item.status) for item in capabilities}


class MetricsEngine:
    def __init__(self, repository=None):
        self.repository = repository

    def _facts(self, context) -> Tuple[pd.DataFrame, float, str, str]:
        started = time.perf_counter()
        if self.repository:
            facts = self.repository.query("metric_facts_v1")
            query_version = sha256(SQL_PATH.read_bytes()).hexdigest()
            query_name = "metric_facts_v1"
        else:
            facts = _pandas_facts(context.analysis_data)
            query_version = "pandas-parity-v1"
            query_name = "metric_facts_pandas_parity"
        if "order_day" in facts:
            facts["order_day"] = pd.to_datetime(facts["order_day"])
        return facts, (time.perf_counter() - started) * 1000, query_name, query_version

    def run(
        self, context, dataset_id: str, scope_id: str, request: AnalysisRequest,
        quality: DataQualitySummary, capabilities: Sequence[AnalysisCapability],
    ) -> Tuple[List[MetricSnapshot], List[EntityAssessment], List[EvidenceBundle]]:
        facts, duration, query_name, query_version = self._facts(context)
        evidence_id = stable_id("ev", dataset_id, scope_id, query_name, query_version, request.to_dict())
        currency = context.metadata.get("target_currency") or context.metadata.get("source_currency")
        available = set(context.analysis_data.columns)
        capability = _capability_lookup(capabilities)
        calculated_at = utc_now()
        snapshots: List[MetricSnapshot] = []
        period_groups: Dict[Tuple[str, str, str], Dict[str, MetricSnapshot]] = {}

        for period_type, period_start, period_end, complete in _periods(facts, request):
            period_facts = facts.loc[facts["order_day"].between(period_start, period_end)].copy()
            entity_dimensions = [("global", None)]
            if {"country", "region"} & available:
                entity_dimensions.append(("market", "market"))
            if "category" in available:
                entity_dimensions.append(("category", "category"))
            if "product_id" in available:
                entity_dimensions.append(("sku", "sku"))
            for entity_type, column in entity_dimensions:
                if column is None:
                    groups = [("__all__", period_facts)]
                else:
                    group_source = period_facts
                    if entity_type == "sku":
                        threshold = 10
                        eligible = period_facts.groupby(column, dropna=False)["order_id"].nunique()
                        eligible = eligible.loc[eligible.ge(threshold)].index
                        if len(eligible) == 0:
                            continue
                        group_source = period_facts.loc[period_facts[column].isin(eligible)]
                    groups = group_source.groupby(column, dropna=False)
                for entity_id, group in groups:
                    entity_id = str(entity_id)
                    values = self._aggregate(group, available)
                    for metric_id, payload in values.items():
                        definition = METRIC_BY_ID[metric_id]
                        if entity_type not in definition.supported_dimensions:
                            continue
                        value, numerator, denominator, sample, limitations = payload
                        snapshot = self._snapshot(
                            dataset_id, scope_id, definition, entity_type, entity_id, period_type,
                            period_start, period_end, complete, value, numerator, denominator, sample,
                            currency, str(quality.quality_rating), capability.get(definition.capability_gate, "UNSUPPORTED"),
                            evidence_id, calculated_at, limitations,
                        )
                        snapshots.append(snapshot)
                        period_groups.setdefault((period_type, entity_type, entity_id), {})[metric_id] = snapshot

                    if entity_type in {"market", "category", "sku"} and values.get("gmv"):
                        total_gmv = float(period_facts["gmv"].sum()) if not period_facts.empty else 0.0
                        metric_id = "product_contribution" if entity_type == "sku" else "market_contribution"
                        entity_gmv = float(group["gmv"].sum()) if not group.empty else 0.0
                        contribution = entity_gmv / total_gmv if total_gmv else None
                        definition = METRIC_BY_ID[metric_id]
                        snapshots.append(self._snapshot(
                            dataset_id, scope_id, definition, entity_type, entity_id, period_type,
                            period_start, period_end, complete, contribution, entity_gmv, total_gmv,
                            int(group["order_id"].nunique()), currency, str(quality.quality_rating),
                            capability.get(definition.capability_gate, "UNSUPPORTED"), evidence_id,
                            calculated_at, (() if total_gmv else ("分母为零",)),
                        ))

        snapshots.extend(self._growth_snapshots(
            snapshots, dataset_id, scope_id, currency, str(quality.quality_rating),
            capability.get("sales_analysis", "UNSUPPORTED"), evidence_id, calculated_at,
        ))
        snapshots.extend(self._market_quality(
            snapshots, dataset_id, scope_id, currency, str(quality.quality_rating),
            capability.get("market_quality", "UNSUPPORTED"), evidence_id, calculated_at,
        ))
        assessments = self._lifecycle(facts, snapshots, dataset_id, scope_id, evidence_id)
        evidence = EvidenceBundle(
            evidence_id=evidence_id, dataset_id=dataset_id, scope_id=scope_id,
            database_schema_version=3, query_name=query_name, query_version=query_version,
            query_parameters={
                "dataset_id": dataset_id,
                "market_dimension": self.repository.market_field if self.repository else "pandas",
                **request.to_dict(),
            },
            metric_snapshot_ids=tuple(item.snapshot_id for item in snapshots),
            source_fields=tuple(sorted(available)), formula="受控订单事实聚合后按注册指标派生",
            period_start=str(facts["order_day"].min().date()) if not facts.empty else "",
            period_end=str(facts["order_day"].max().date()) if not facts.empty else "",
            executed_at=calculated_at, duration_ms=round(duration, 3), row_count=len(facts),
            result_digest=frame_digest(facts),
            result_summary={"rows": len(facts), "orders": int(facts["order_id"].nunique()) if not facts.empty else 0, "gmv": float(facts["gmv"].sum()) if not facts.empty else 0.0},
            limitations=("证据预览按日、市场、品类和 SKU 聚合",),
        )
        return snapshots, assessments, [evidence]

    @staticmethod
    def _aggregate(group: pd.DataFrame, available: set) -> Dict[str, tuple]:
        orders = int(group["order_id"].nunique()) if not group.empty else 0
        gmv = float(group["gmv"].sum()) if not group.empty else 0.0
        output = {
            "gmv": (gmv, gmv, None, orders, ()),
            "orders": (float(orders), float(orders), None, orders, ()),
            "aov": ((gmv / orders) if orders else None, gmv, float(orders), orders, (() if orders else ("分母为零",))),
        }
        if "quantity" in available:
            units = float(group["units"].sum()) if not group.empty else 0.0
            output["units"] = (units, units, None, orders, ())
        if "customer_id" in available:
            customers = float(group["customer_id"].nunique(dropna=True)) if not group.empty else 0.0
            output["customers"] = (customers, customers, None, orders, ())
        if "profit_amount" in available:
            profit = float(group["profit"].sum()) if not group.empty else 0.0
            output["profit"] = (profit, profit, None, orders, ())
            output["profit_margin"] = ((profit / gmv) if gmv else None, profit, gmv, orders, (() if gmv else ("分母为零",)))
        if "cost_amount" in available:
            cost = float(group["cost_amount"].sum()) if not group.empty else 0.0
            output["cost_amount"] = (cost, cost, None, orders, ())
        if "refund_amount" in available:
            refund = float(group["refund_amount"].sum()) if not group.empty else 0.0
            output["refund_amount"] = (refund, refund, None, orders, ())
        if "ad_spend" in available:
            ad_spend = float(group["ad_spend"].sum()) if not group.empty else 0.0
            output["ad_spend"] = (ad_spend, ad_spend, None, orders, ())
            output["roas"] = ((gmv / ad_spend) if ad_spend else None, gmv, ad_spend, orders, (() if ad_spend else ("分母为零",)))
        if {"profit_amount", "refund_amount", "ad_spend"} <= available:
            profit = float(group["profit"].sum()) if not group.empty else 0.0
            refund = float(group["refund_amount"].sum()) if not group.empty else 0.0
            ad_spend = float(group["ad_spend"].sum()) if not group.empty else 0.0
            net_profit = profit - refund - ad_spend
            output["net_profit"] = (net_profit, profit, refund + ad_spend, orders, ())
        if "inventory_available" in available:
            inventory = float(group["inventory_available"].sum()) if not group.empty else 0.0
            output["inventory_available"] = (inventory, inventory, None, orders, ())
        if "stockout_flag" in available:
            stockout_orders = float(group.loc[group["stockout_flag"].fillna(0).astype(int).gt(0), "order_id"].nunique()) if not group.empty else 0.0
            output["stockout_rate"] = ((stockout_orders / orders) if orders else None, stockout_orders, float(orders), orders, (() if orders else ("分母为零",)))
        if "returned" in available:
            returned = float(group.loc[group["returned_orders"].gt(0), "order_id"].nunique()) if not group.empty else 0.0
            output["return_rate"] = ((returned / orders) if orders else None, returned, float(orders), orders, (() if orders else ("分母为零",)))
        return output

    @staticmethod
    def _snapshot(
        dataset_id, scope_id, definition, entity_type, entity_id, period_type,
        period_start, period_end, complete, value, numerator, denominator, sample,
        currency, quality_status, capability_status, evidence_id, calculated_at, limitations,
    ) -> MetricSnapshot:
        start, end = pd.Timestamp(period_start).date().isoformat(), pd.Timestamp(period_end).date().isoformat()
        snapshot_id = stable_id("ms", dataset_id, scope_id, definition.metric_id, definition.version, entity_type, entity_id, period_type, start, end)
        normalize = lambda item: None if item is None or pd.isna(item) else round(float(item), 6)
        return MetricSnapshot(
            snapshot_id, dataset_id, scope_id, definition.metric_id, definition.version,
            entity_type, entity_id, period_type, start, end, bool(complete),
            normalize(value), normalize(numerator), normalize(denominator),
            int(sample), currency if definition.unit == "currency" else None,
            quality_status, capability_status, evidence_id, calculated_at, tuple(limitations),
        )

    def _growth_snapshots(self, snapshots, dataset_id, scope_id, currency, quality, capability, evidence_id, calculated_at):
        output = []
        base = [item for item in snapshots if item.metric_id == "gmv" and item.is_complete_period and item.period_type in {"month", "week", "event", "event_baseline"}]
        grouped: Dict[Tuple[str, str], List[MetricSnapshot]] = {}
        for item in base:
            period_group = "event" if item.period_type.startswith("event") else item.period_type
            grouped.setdefault((period_group, item.entity_type, item.entity_id), []).append(item)
        definition = METRIC_BY_ID["growth_rate"]
        for (_, entity_type, entity_id), items in grouped.items():
            items.sort(key=lambda item: item.period_start)
            for previous, current in zip(items, items[1:]):
                if current.current_value is None or previous.current_value is None:
                    continue
                denominator = abs(previous.current_value)
                value = (current.current_value - previous.current_value) / denominator if denominator else None
                limitations = ("基期为零",) if denominator == 0 else ()
                output.append(self._snapshot(
                    dataset_id, scope_id, definition, entity_type, entity_id,
                    "event" if current.period_type == "event" else current.period_type,
                    current.period_start, current.period_end, True, value,
                    current.current_value - previous.current_value, denominator,
                    current.sample_size, currency, quality, capability, evidence_id,
                    calculated_at, limitations,
                ))
        return output

    def _market_quality(self, snapshots, dataset_id, scope_id, currency, quality, capability, evidence_id, calculated_at):
        complete_months = sorted({item.period_start for item in snapshots if item.period_type == "month" and item.is_complete_period})
        if not complete_months:
            return []
        latest = complete_months[-1]
        table: Dict[str, Dict[str, MetricSnapshot]] = {}
        for item in snapshots:
            if item.entity_type == "market" and item.period_start == latest and item.period_type == "month":
                table.setdefault(item.entity_id, {})[item.metric_id] = item
        eligible = []
        for market, metrics in table.items():
            required = {key: metrics.get(key) for key in ("gmv", "growth_rate", "profit_margin", "return_rate", "orders")}
            if all(required.values()) and required["orders"].current_value >= 30 and all(required[key].current_value is not None for key in ("gmv", "growth_rate", "profit_margin", "return_rate")):
                eligible.append({"market": market, **{key: required[key].current_value for key in required}})
        if not eligible:
            return []
        frame = pd.DataFrame(eligible)
        for column in ("gmv", "growth_rate", "profit_margin", "return_rate"):
            frame[column + "_pct"] = frame[column].rank(method="average", pct=True) * 100
        frame["score"] = frame.gmv_pct * .30 + frame.growth_rate_pct * .25 + frame.profit_margin_pct * .25 + (100 - frame.return_rate_pct) * .20
        definition = METRIC_BY_ID["market_quality_score"]
        output = []
        for row in frame.itertuples():
            metrics = table[row.market]
            output.append(self._snapshot(
                dataset_id, scope_id, definition, "market", row.market, "month",
                metrics["gmv"].period_start, metrics["gmv"].period_end, True,
                row.score, row.score, None, int(metrics["orders"].current_value), currency,
                quality, capability, evidence_id, calculated_at, (),
            ))
        return output

    @staticmethod
    def _lifecycle(facts, snapshots, dataset_id, scope_id, evidence_id):
        complete_months = sorted({item.period_start for item in snapshots if item.metric_id == "gmv" and item.period_type == "month" and item.is_complete_period})
        if not complete_months or facts.empty:
            return []
        latest_start = pd.Timestamp(complete_months[-1])
        latest_end = latest_start + pd.offsets.MonthEnd(0)
        work = facts.copy()
        work["month"] = work.order_day.dt.to_period("M").astype(str)
        month_labels = [pd.Timestamp(value).strftime("%Y-%m") for value in complete_months]
        monthly = work.loc[work.month.isin(month_labels)].groupby(["sku", "month"]).agg(
            gmv=("gmv", "sum"), orders=("orders", "sum")
        )
        sku_index = pd.Index(sorted(work.sku.astype(str).unique()), name="sku")
        order_matrix = monthly.orders.unstack(fill_value=0).reindex(index=sku_index, columns=month_labels, fill_value=0)
        gmv_matrix = monthly.gmv.unstack(fill_value=0).reindex(index=sku_index, columns=month_labels, fill_value=0.0)
        stats = pd.DataFrame(index=sku_index)
        stats["observed"] = order_matrix.gt(0).sum(axis=1)
        stats["latest_orders"] = order_matrix.iloc[:, -1]
        totals = work.groupby("sku").agg(cumulative_orders=("orders", "sum"), first_order=("order_day", "min"))
        stats = stats.join(totals)
        stats["age_days"] = (latest_end - pd.to_datetime(stats.first_order)).dt.days
        recent_orders = order_matrix.iloc[:, -3:]
        recent_gmv = gmv_matrix.iloc[:, -3:]
        enough_recent = len(month_labels) >= 3 and recent_orders.ge(10).all(axis=1)
        if len(month_labels) >= 3:
            changes = recent_gmv.pct_change(axis=1, fill_method=None).iloc[:, 1:]
            declining = enough_recent & changes.le(-.20).all(axis=1)
            growing = enough_recent & changes.gt(0).all(axis=1)
            means = recent_gmv.mean(axis=1)
            stable = enough_recent & means.ne(0) & recent_gmv.std(axis=1, ddof=0).div(means).le(.20)
        else:
            declining = growing = stable = pd.Series(False, index=stats.index)
        labels = pd.Series("未分类", index=stats.index, dtype="string")
        labels.loc[stats.age_days.ge(90) & stable] = "成熟品"
        labels.loc[growing] = "成长品"
        labels.loc[declining] = "衰退品"
        labels.loc[stats.age_days.le(30) & stats.cumulative_orders.ge(5)] = "新品"
        labels.loc[stats.latest_orders.lt(10) | stats.observed.lt(2)] = "低样本"
        stats["lifecycle_label"] = labels.astype(str)
        stats = (
            stats.assign(low_sample=stats.lifecycle_label.eq("低样本"))
            .sort_values(
                ["low_sample", "latest_orders", "cumulative_orders"],
                ascending=[True, False, False],
            )
            .head(MAX_LIFECYCLE_ASSESSMENTS)
        )
        period_start, period_end = latest_start.date().isoformat(), latest_end.date().isoformat()
        def lifecycle_id(sku):
            payload = json.dumps(
                [dataset_id, scope_id, "sku_lifecycle", str(sku), period_start],
                ensure_ascii=False, separators=(",", ":"),
            )
            return "assess_{}".format(sha256(payload.encode("utf-8")).hexdigest()[:24])
        return [
            EntityAssessment(
                lifecycle_id(sku),
                dataset_id, scope_id, "sku_lifecycle", "sku", str(sku), period_start,
                period_end, str(label), int(latest_orders), (evidence_id,),
                (() if label != "低样本" else ("样本不足，不强行分类",)),
            )
            for sku, label, latest_orders in zip(
                stats.index, stats.lifecycle_label.array, stats.latest_orders.array,
            )
        ]
