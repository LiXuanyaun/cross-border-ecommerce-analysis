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


def _evidence_unit(metric_id: str | None, currency: str | None) -> str:
    if currency:
        return currency
    if metric_id and (metric_id.endswith("rate") or "margin" in metric_id or "contribution" in metric_id):
        return "%"
    return ""


def customer_normal_decisions(
    *,
    customer_count: int,
    order_count: int,
    gmv: float,
    segments,
    period: dict[str, str | None],
    filters: dict[str, str],
    missing_fields: list[str],
) -> dict[str, Any]:
    if missing_fields or customer_count <= 0 or segments.empty:
        missing = missing_fields or ["customer_id 或有效客户样本"]
        text = "客户专题数据不足：缺少{}，无法判断客户经营状态。".format("、".join(missing))
        return {
            "state": {
                "status": "INSUFFICIENT",
                "title": "客户分析数据不足",
                "description": text,
                "missing_fields": missing,
            },
            "summary": text,
            "findings": [{
                "id": "customer-insufficient-data",
                "priority": "P2",
                "title": "数据完整性",
                "finding": text,
                "limitations": ["缺失字段补齐前不生成异常或确定性判断"],
            }],
            "drivers": [],
            "evidence": [],
            "actions": [{
                "id": "customer-complete-data",
                "title": "补充客户分析所需字段后重算",
                "action": "补充{}并重新运行客户专题。".format("、".join(missing)),
                "owner": "数据负责人",
                "validation_period": "字段补齐后",
                "trigger_condition": "必需字段可用且通过质量校验",
                "metric_id": "customers",
                "rule_id": None,
                "rule_version": None,
                "evidence_ids": [],
            }],
        }

    segment_rows = segments.sort_values("gmv", ascending=False).to_dict("records")
    top = segment_rows[0]
    average_contribution = gmv / customer_count if customer_count else None
    frequency = order_count / customer_count if customer_count else None
    period_value = {
        "start": str(period.get("start") or ""),
        "end": str(period.get("end") or ""),
    }
    limitations = ["分群贡献用于描述经营结构，不证明因果", "未命中规则不代表未来没有风险"]
    drivers = []
    for rank, row in enumerate(segment_rows[:5], start=1):
        segment_gmv = float(row.get("gmv") or 0.0)
        drivers.append({
            "id": "customer-segment-{}".format(rank),
            "rank": rank,
            "object": str(row.get("segment") or "未分群客户"),
            "current_value": float(row.get("customers") or 0),
            "comparison_value": None,
            "change_rate": None,
            "impact_amount": segment_gmv,
            "impact_share": segment_gmv / gmv if gmv else None,
            "status": "贡献结构",
            "severity": "INFO",
            "orders": int(row.get("customers") or 0),
            "evidence_ids": ["customer-segment-structure"],
            "limitations": ["贡献结构不代表该分群导致整体变化"],
        })
    evidence_specs = (
        (
            "customer-count",
            "客户数",
            customer_count,
            "",
            "当前分析范围覆盖{:,}名去重客户。".format(customer_count),
            "count(distinct customer_id)",
            ["customer_id"],
        ),
        (
            "customer-average-contribution",
            "人均贡献",
            average_contribution,
            "CNY",
            "当前范围内每名客户平均贡献¥{:,.0f}。".format(average_contribution or 0.0),
            "sum(gmv_amount_base) / count(distinct customer_id)",
            ["customer_id", "total_amount", "currency"],
        ),
        (
            "customer-frequency",
            "平均购买频次",
            frequency,
            "次",
            "当前范围内每名客户平均完成{:.2f}次购买。".format(frequency or 0.0),
            "count(distinct order_id) / count(distinct customer_id)",
            ["order_id", "customer_id"],
        ),
        (
            "customer-segment-structure",
            "客户分群贡献",
            float(top.get("gmv") or 0.0),
            "CNY",
            "{}是贡献最高的分群，占客户 GMV 的{:.1%}。".format(
                top["segment"], float(top["gmv"]) / gmv if gmv else 0.0,
            ),
            "RFM 分群后按 segment 汇总 gmv_amount_base",
            ["customer_id", "order_date", "order_id", "total_amount"],
        ),
    )
    evidence = [{
        "contract_version": "topic-evidence.v1",
        "id": evidence_id,
        "metric": metric,
        "value": value,
        "unit": unit,
        "claim": claim,
        "formula": formula,
        "sample_size": order_count,
        "confidence": "可复算",
        "source_fields": fields,
        "period": period_value,
        "filters": filters,
        "quality_state": "PASS",
        "limitations": limitations,
    } for evidence_id, metric, value, unit, claim, formula, fields in evidence_specs]
    return {
        "state": {
            "status": "HEALTHY",
            "title": "当前范围未发现符合规则的客户异常",
            "description": "继续查看客户规模、分群贡献和监测条件。",
            "missing_fields": [],
        },
        "summary": (
            "当前范围未发现符合规则的客户异常；共有{:,}名客户，人均贡献{}，"
            "{}是当前贡献最高的分群。"
        ).format(customer_count, "¥{:,.0f}".format(average_contribution or 0.0), top["segment"]),
        "findings": [
            {
                "id": "customer-healthy-scale",
                "priority": "P3",
                "title": "客户规模与价值",
                "finding": "当前覆盖{:,}名客户，人均贡献{}，平均购买频次为{:.2f}次。".format(
                    customer_count, "¥{:,.0f}".format(average_contribution or 0.0), frequency or 0.0,
                ),
                "evidence_ids": ["customer-count", "customer-average-contribution", "customer-frequency"],
                "limitations": limitations,
            },
            {
                "id": "customer-healthy-segments",
                "priority": "P3",
                "title": "客户分群贡献",
                "finding": "{}贡献{}，占客户 GMV 的{:.1%}；这是构成贡献，不代表因果。".format(
                    top["segment"], "¥{:,.0f}".format(float(top["gmv"])),
                    float(top["gmv"]) / gmv if gmv else 0.0,
                ),
                "evidence_ids": ["customer-segment-structure"],
                "limitations": limitations,
            },
        ],
        "drivers": drivers,
        "evidence": evidence,
        "actions": [
            {
                "id": "customer-monitor-value",
                "title": "维持分群运营并按月复核客户价值",
                "action": "继续按当前分群策略运营，每个完整月复核人均贡献和购买频次。",
                "owner": "客户运营",
                "validation_period": "下一个完整月",
                "trigger_condition": "人均贡献环比下降 10% 或购买频次连续两月下降时复查",
                "metric_id": "customers",
                "rule_id": None,
                "rule_version": None,
                "evidence_ids": ["customer-count", "customer-average-contribution", "customer-frequency"],
            },
            {
                "id": "customer-monitor-churn",
                "title": "监测流失风险客户占比",
                "action": "跟踪流失风险分群的客户数与贡献占比，不将构成变化解释为确定性原因。",
                "owner": "客户运营",
                "validation_period": "每月",
                "trigger_condition": "流失风险客户占比较当前上升 5 个百分点时复查",
                "metric_id": "customers",
                "rule_id": None,
                "rule_version": None,
                "evidence_ids": ["customer-segment-structure"],
            },
        ],
    }


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
    evidence = []
    for item in artifacts.evidence:
        if item.evidence_id not in evidence_ids:
            continue
        relevant_snapshots = [
            snapshots[snapshot_id]
            for snapshot_id in item.metric_snapshot_ids
            if snapshot_id in snapshots
            and snapshots[snapshot_id].metric_id in metric_ids
            and snapshots[snapshot_id].period_start == current_period["start"]
        ]
        primary = relevant_snapshots[0] if relevant_snapshots else None
        claim = next(
            (row["finding"] for row in findings if item.evidence_id in row.get("evidence_ids", [])),
            "该证据支持当前专题的正式指标与规则判断。",
        )
        filters = item.query_parameters.get("filters", {}) if isinstance(item.query_parameters, dict) else {}
        evidence.append({
            "contract_version": "topic-evidence.v1",
            "id": item.evidence_id,
            "metric": primary.metric_id if primary else "专题正式指标集合",
            "value": primary.current_value if primary else None,
            "unit": _evidence_unit(primary.metric_id if primary else None, primary.currency if primary else None),
            "claim": claim,
            "formula": item.formula,
            "sample_size": primary.sample_size if primary else item.row_count,
            "confidence": primary.quality_status if primary else "待评估",
            "source_fields": list(item.source_fields),
            "period": {"start": item.period_start, "end": item.period_end},
            "filters": filters if isinstance(filters, dict) else {},
            "quality_state": primary.quality_status if primary else "待评估",
            "limitations": list(item.limitations),
        })
    return {
        "summary": findings[0]["finding"] if findings else "当前范围没有达到正式规则阈值的结论。",
        "anomalies": anomaly_rows[:5],
        "drivers": driver_rows[:5],
        "findings": findings,
        "evidence": evidence,
        "actions": recommendation_rows[:5],
    }
