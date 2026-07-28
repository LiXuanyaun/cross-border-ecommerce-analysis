from __future__ import annotations

from typing import Any

from crossborder_analytics.localization import value_for


def _localize(value: Any, kind: str) -> str:
    if value is None:
        return "未标注"
    try:
        return str(value_for(value, kind))
    except Exception:
        return str(value)


def _entity_label(entity_type: str, value: Any) -> str:
    if entity_type == "market":
        return _localize(value, "region")
    if entity_type == "category":
        return _localize(value, "category")
    return str(value)


def formal_topic_decisions(bundle, topic: str, current_period: dict[str, str]) -> dict[str, Any]:
    artifacts = bundle.artifacts
    snapshots = {item.snapshot_id: item for item in artifacts.metric_snapshots}
    rules = {item.rule_id: item for item in artifacts.anomaly_rules}
    diagnoses = {item.anomaly_id: item for item in artifacts.diagnoses}
    recommendations_by_diagnosis: dict[str, list[Any]] = {}
    for item in artifacts.recommendations:
        recommendations_by_diagnosis.setdefault(item.diagnosis_id, []).append(item)

    entity_types = {
        "market": {"market"},
        "product": {"sku", "category"},
        "customer": {"customer"},
        "profit": {"global", "market", "category", "sku"},
        "returns": {"global", "market", "category", "sku"},
    }[topic]
    metric_ids = {
        "market": {"gmv", "growth_rate", "market_contribution", "profit_margin", "return_rate"},
        "product": {"gmv", "growth_rate", "product_contribution", "profit_margin", "return_rate"},
        "customer": {"customers"},
        "profit": {"profit", "profit_margin", "gmv"},
        "returns": {"return_rate", "gmv"},
    }[topic]
    candidates = [
        item for item in artifacts.anomalies
        if item.entity_type in entity_types and item.metric_id in metric_ids
    ]
    current = [
        item for item in candidates
        if item.current_snapshot_id in snapshots
        and snapshots[item.current_snapshot_id].period_start == current_period["start"]
    ]
    if current:
        candidates = current
    candidates.sort(key=lambda item: (
        0 if str(item.status) == "DETECTED" else 1,
        -abs(float(item.impact_amount or item.change_rate or 0.0)),
        item.anomaly_id,
    ))

    anomaly_rows = []
    driver_rows = []
    recommendation_rows = []
    evidence_ids = set()
    for rank, anomaly in enumerate(candidates[:10], start=1):
        rule = rules.get(anomaly.rule_id)
        snapshot = snapshots.get(anomaly.current_snapshot_id)
        diagnosis = diagnoses.get(anomaly.anomaly_id)
        evidence_ids.update(anomaly.evidence_ids)
        anomaly_rows.append({
            "id": anomaly.anomaly_id,
            "rank": rank,
            "object": _entity_label(anomaly.entity_type, anomaly.entity_name),
            "current_value": anomaly.current_value,
            "comparison_value": anomaly.baseline_value,
            "change_rate": anomaly.change_rate,
            "impact_amount": anomaly.impact_amount,
            "status": str(anomaly.status),
            "severity": str(anomaly.severity),
            "metric_id": anomaly.metric_id,
            "metric_version": snapshot.metric_version if snapshot else None,
            "rule_id": anomaly.rule_id,
            "rule_version": anomaly.rule_version,
            "evidence_ids": list(anomaly.evidence_ids),
            "limitations": list(anomaly.limitations),
            "rule": rule.to_dict() if rule else None,
        })
        if diagnosis and str(diagnosis.status) in {"VERIFIED_DRIVER", "LIKELY_DRIVER"}:
            for contribution in diagnosis.driver_contributions:
                driver_rows.append({
                    "id": "{}:{}".format(diagnosis.diagnosis_id, len(driver_rows) + 1),
                    "object": str(contribution.get("label") or contribution.get("driver") or contribution.get("name") or diagnosis.primary_driver),
                    "impact_amount": contribution.get("impact_amount") or contribution.get("contribution"),
                    "impact_share": contribution.get("impact_share") or contribution.get("share"),
                    "status": str(diagnosis.status),
                    "diagnosis_id": diagnosis.diagnosis_id,
                    "anomaly_id": anomaly.anomaly_id,
                    "metric_id": anomaly.metric_id,
                    "metric_version": snapshot.metric_version if snapshot else None,
                    "rule_id": anomaly.rule_id,
                    "rule_version": anomaly.rule_version,
                    "evidence_ids": list(diagnosis.evidence_ids),
                })
            for recommendation in recommendations_by_diagnosis.get(diagnosis.diagnosis_id, []):
                evidence_ids.update(recommendation.evidence_ids)
                recommendation_rows.append({
                    "id": recommendation.recommendation_id,
                    "title": recommendation.action,
                    "action": recommendation.action,
                    "rationale": recommendation.rationale,
                    "owner": recommendation.owner_role,
                    "validation_period": recommendation.validation_period,
                    "stop_condition": recommendation.stop_condition,
                    "guardrail_metrics": list(recommendation.guardrail_metrics),
                    "diagnosis_id": diagnosis.diagnosis_id,
                    "anomaly_id": anomaly.anomaly_id,
                    "metric_id": anomaly.metric_id,
                    "metric_version": snapshot.metric_version if snapshot else None,
                    "rule_id": anomaly.rule_id,
                    "rule_version": anomaly.rule_version,
                    "evidence_ids": list(recommendation.evidence_ids),
                })

    anomaly_ids = {item["id"] for item in anomaly_rows if item["status"] == "DETECTED"}
    insight_rows = [item for item in artifacts.insights if item.anomaly_id in anomaly_ids]
    if not insight_rows and not anomaly_ids:
        insight_rows = [item for item in artifacts.insights if item.type == "STATUS"]
    findings = [{
        "id": item.insight_id,
        "priority": item.priority,
        "title": _entity_label(item.entity_type, item.entity_name),
        "finding": item.finding,
        "metric_id": item.metric_id or None,
        "metric_version": snapshots[item.current_snapshot_id].metric_version if item.current_snapshot_id in snapshots else None,
        "rule_id": next((row["rule_id"] for row in anomaly_rows if row["id"] == item.anomaly_id), None),
        "rule_version": next((row["rule_version"] for row in anomaly_rows if row["id"] == item.anomaly_id), None),
        "evidence_ids": list(item.evidence_ids),
        "limitations": list(item.limitations),
    } for item in insight_rows[:5]]
    findings = list({item["finding"]: item for item in reversed(findings)}.values())
    if not findings:
        findings = [{
            "id": "{}-no-formal-anomaly".format(topic),
            "priority": "P3",
            "title": "规则执行状态",
            "finding": "当前专题没有达到正式规则阈值的异常；不生成确定性原因或建议。",
            "metric_id": None,
            "metric_version": None,
            "rule_id": None,
            "rule_version": None,
            "evidence_ids": [],
            "limitations": ["没有异常不等于没有经营风险"],
        }]
    evidence = [item.to_dict() for item in artifacts.evidence if item.evidence_id in evidence_ids]
    return {
        "summary": findings[0]["finding"] if findings else "当前范围没有达到正式规则阈值的结论。",
        "anomalies": anomaly_rows[:5],
        "drivers": driver_rows[:5],
        "findings": findings,
        "evidence": evidence,
        "actions": recommendation_rows[:5],
    }
