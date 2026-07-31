"""Pure presentation shaping shared by API exports and regression tests."""
from __future__ import annotations

from typing import Mapping

import pandas as pd

from .rfm import SEGMENT_ORDER


def _snapshot_by_id(artifacts):
    return {item.snapshot_id: item for item in artifacts.metric_snapshots}


def _workflow_value(anomaly, work_item) -> str:
    if work_item:
        return str(work_item.workflow_status)
    return "COMPLETED" if str(anomaly.status) == "RECOVERED" else "TODO"


def latest_priority_insights(artifacts, limit: int = 3):
    """Return latest-period P0/P1 insights without duplicate entity/metric rows."""
    snapshot_by_id = _snapshot_by_id(artifacts)
    candidates = [item for item in artifacts.insights if item.type == "ANOMALY"]
    periods = [
        snapshot_by_id[item.current_snapshot_id].period_start
        for item in candidates
        if item.current_snapshot_id in snapshot_by_id
    ]
    if periods:
        latest = max(periods)
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


def build_risk_items(artifacts, work_items: Mapping[str, object] | None = None) -> list[dict]:
    """Join generated artifacts with mutable task state for presentation and export."""
    work_items = work_items or {}
    snapshot_by_id = _snapshot_by_id(artifacts)
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
