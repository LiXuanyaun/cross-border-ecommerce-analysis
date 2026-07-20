"""Build evidence-bound BI decision cases from audited analysis artifacts."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from .phase2_catalogs import METRIC_BY_ID
from .phase2_models import AnalysisArtifacts


ENTITY_LABELS = {
    "global": "整体业务",
    "market": "市场",
    "category": "类目",
    "sku": "SKU",
}

UNAVAILABLE_METRICS = (
    ("advertising_roi", "广告 ROI", "缺少广告花费与归因收入字段"),
    ("ctr", "CTR（点击率）", "缺少广告曝光与点击字段"),
    ("cvr", "CVR（转化率）", "缺少访问与转化漏斗字段"),
    ("inventory_turnover", "库存周转", "缺少库存与成本字段"),
)


def _unique(values):
    return list(dict.fromkeys(value for value in values if value))


def _limitations(values, missing_context=()):
    normalized = []
    seen = set()

    def append(text: str, *, is_missing: bool = False) -> None:
        value = str(text).strip()
        if not value:
            return
        subject = value[2:] if value.startswith("缺少") else value
        key = subject.casefold()
        if key in seen:
            return
        seen.add(key)
        normalized.append(f"缺少{subject}" if is_missing else value)

    for value in values:
        append(value)
    for value in missing_context:
        append(value, is_missing=True)
    return normalized


def _metric_name(metric_id: str) -> str:
    definition = METRIC_BY_ID.get(metric_id)
    return definition.name if definition else metric_id


def _metric_unit(metric_id: str, currency: str | None = None) -> str:
    definition = METRIC_BY_ID.get(metric_id)
    if definition and definition.unit == "currency":
        return currency or "CNY"
    return definition.unit if definition else "number"


def _entity_name(entity_type: str, entity_name: str) -> str:
    if entity_type == "global" or entity_name == "__all__":
        return "整体业务"
    return entity_name


def _signed_direction(value: float | None) -> str:
    if value is None:
        return "发生变化"
    return "上升" if value > 0 else "下降" if value < 0 else "保持不变"


def _summary(anomaly, diagnosis, current, baseline) -> str:
    entity = _entity_name(anomaly.entity_type, anomaly.entity_name)
    metric = _metric_name(anomaly.metric_id)
    driver = diagnosis.primary_driver if diagnosis else "证据尚不足"
    if anomaly.metric_id in {"profit_margin", "return_rate", "market_contribution"}:
        if current and baseline and current.current_value is not None and baseline.current_value is not None:
            delta = current.current_value - baseline.current_value
            return (
                f"{entity} {metric}由 {baseline.current_value:.1%} 变为 {current.current_value:.1%}，"
                f"{_signed_direction(delta)} {abs(delta):.1%}；当前可复算主驱动为{driver}。"
            )
    rate = anomaly.change_rate
    if rate is not None:
        return (
            f"{entity} {metric}较对比周期{_signed_direction(rate)} {abs(rate):.1%}，"
            f"当前可复算主驱动为{driver}。"
        )
    return f"{entity} {metric}触发异常规则；当前可复算主驱动为{driver}。"


def _action_playbook(rule_id: str, entity: str, missing_context: tuple[str, ...]) -> dict[str, Any]:
    missing = "、".join(_unique(missing_context))
    playbooks = {
        "REC-GMV-AOV": {
            "title": f"对 {entity} 高影响 SKU 开展价格带验证",
            "action": f"按 GMV 影响对 {entity} 的 SKU 排序，选取 Top 10 SKU 建立价格带与折扣对照组，只在保护指标稳定时扩大调整。",
            "steps": [
                "生成当前周期与对比周期的 SKU 价格带、折扣率和 GMV 影响清单",
                "选取 Top 10 影响 SKU 建立原方案与调整方案对照组",
                "完成一个完整可比较周期后，按 GMV、利润率和退货率决定保留或停止",
            ],
        },
        "REC-GMV-ORDERS": {
            "title": f"建立 {entity} 订单流失恢复清单",
            "action": f"将 {entity} 的订单下降拆到市场、类目和 SKU，给 Top 影响对象分配负责人并逐项关闭已验证的流失来源。",
            "steps": [
                "生成订单下降金额与订单数贡献排名，并锁定 Top 影响对象",
                "为每个对象登记已知业务事件、负责人和恢复动作",
                "下一完整周期复核订单数、GMV、利润率和退货率是否恢复",
            ],
        },
        "REC-AOV-MIX": {
            "title": f"重组 {entity} 的成交价格带",
            "action": f"对 {entity} 的低价成交集中 SKU 建立组合与价格带实验，限制实验范围并保留利润率和退货率保护线。",
            "steps": [
                "输出低价 SKU 占比、折扣率和客单价贡献排名",
                "选择主要影响 SKU 建立组合方案与价格带对照实验",
                "达到验证周期后按客单价、GMV 和保护指标决定是否扩大",
            ],
        },
        "REC-MARGIN-SKU": {
            "title": f"建立 {entity} SKU 损益修复清单",
            "action": f"将 {entity} 的售价、已知利润额、折扣和履约信息汇总到 SKU 损益清单，优先处理负贡献且 GMV 影响最高的对象。",
            "steps": [
                "按利润影响与 GMV 规模生成 SKU 优先级清单",
                "为 Top 影响 SKU 补齐可用的售价、折扣、利润额和履约信息",
                "仅对证据完整的 SKU 执行小范围修复并复核 GMV 与退货率",
            ],
        },
        "REC-RETURN-SKU": {
            "title": f"执行 {entity} 高退货订单闭环",
            "action": f"对 {entity} 的高退货订单建立原因采集、商品页修正和复核清单，未取得原因证据前不执行下架。",
            "steps": [
                "输出高退货 SKU、订单量和退货率排名",
                "完成 Top 影响订单的退货原因采集并归档",
                "对有明确原因证据的商品页或履约问题实施修正并复核退货率",
            ],
        },
        "REC-MARKET-GROWTH-RISK": {
            "title": f"冻结 {entity} 新增投入并执行增长质量复核",
            "action": f"暂停扩大 {entity} 的新增投入，将增长集中 SKU、利润率和退货率纳入恢复清单，保护指标恢复前不扩量。",
            "steps": [
                "冻结尚未执行的新增投入计划",
                "输出增长集中 SKU 及其利润率、退货率保护指标",
                "保护指标恢复后再以小范围实验重新验证增量",
            ],
        },
        "REC-HERO-GROWTH-RISK": {
            "title": f"冻结 {entity} 新增备货与曝光",
            "action": f"暂停扩大 {entity} 的备货和曝光，将利润率、退货率及增长来源列入恢复门槛后再决定扩量。",
            "steps": [
                "冻结尚未执行的新增备货和曝光计划",
                "记录当前利润率、退货率和增长集中度作为恢复基线",
                "达到保护门槛后再进行小范围增量实验",
            ],
        },
        "REC-MARKET-SCALE": {
            "title": f"对 {entity} 启动受控增量实验",
            "action": f"在 {entity} 选取主要增长类目执行小范围增量实验，以利润率和退货率作为强制停止条件。",
            "steps": [
                "选取贡献最高且保护指标健康的类目作为实验组",
                "限定增量范围并记录实验前 GMV、利润率和退货率",
                "验证周期结束后仅扩大满足全部保护条件的实验组",
            ],
        },
    }
    if rule_id.startswith("REC-GENERIC-DATA_REQUEST"):
        return {
            "title": f"补齐 {entity} 的关键分析字段",
            "action": f"建立 {entity} 的缺失字段补录任务，字段通过质量校验后重新运行分析。",
            "steps": [f"补录并校验：{missing or '当前诊断所需字段'}", "重新运行同一数据范围的指标与异常分析", "证据达到门槛后再生成经营动作"],
        }
    if rule_id.startswith("REC-GENERIC-INVESTIGATE"):
        return {
            "title": f"建立 {entity} 异常业务事件核验单",
            "action": f"为 {entity} 登记对比周期内的业务事件、负责人和证据状态，完成核验前不升级为经营调整。",
            "steps": [f"登记并核验缺失上下文：{missing or '业务事件'}", "将业务事件与指标变化周期对齐", "证据达到诊断门槛后重新生成动作"],
        }
    return playbooks.get(rule_id, {
        "title": f"执行 {entity} 受控经营验证",
        "action": f"围绕 {entity} 的已识别影响建立负责人、验证周期和保护指标，完成验证后再决定是否扩大。",
        "steps": ["锁定主要影响对象", "执行小范围验证并记录保护指标", "验证周期结束后按证据决定继续或停止"],
    })


def build_decision_brief(artifacts: AnalysisArtifacts, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    metadata = dict(metadata or {})
    snapshots = {item.snapshot_id: item for item in artifacts.metric_snapshots}
    anomalies = {item.anomaly_id: item for item in artifacts.anomalies}
    diagnoses = {item.diagnosis_id: item for item in artifacts.diagnoses}
    recommendations = {item.recommendation_id: item for item in artifacts.recommendations}
    evidence = {item.evidence_id: item for item in artifacts.evidence}

    candidates = []
    for insight in artifacts.insights:
        if not insight.anomaly_id or insight.anomaly_id not in anomalies:
            continue
        anomaly = anomalies[insight.anomaly_id]
        current = snapshots.get(anomaly.current_snapshot_id or "")
        if current is None or not current.is_complete_period or str(anomaly.status) != "DETECTED":
            continue
        candidates.append((insight, anomaly, current))

    if not candidates:
        return {
            "status": "SKIPPED",
            "message": "当前数据不足，无法生成该分析。",
            "cases": [],
            "key_findings": [],
            "top_impact": [],
            "unavailable_metrics": [
                {"metric_id": key, "metric": name, "status": "SKIPPED", "reason": reason}
                for key, name, reason in UNAVAILABLE_METRICS
            ],
        }

    latest_period = max(current.period_start for _, _, current in candidates)
    current_candidates = [item for item in candidates if item[2].period_start == latest_period]
    current_candidates.sort(key=lambda item: (-item[0].priority_score, -(abs(item[1].impact_amount or 0))))
    deduplicated = []
    seen = set()
    for item in current_candidates:
        key = (item[1].entity_type, item[1].entity_id, item[1].metric_id)
        if key not in seen:
            deduplicated.append(item)
            seen.add(key)

    global_deltas = {}
    for snapshot in artifacts.metric_snapshots:
        if snapshot.entity_type == "global" and snapshot.entity_id == "__all__":
            global_deltas[(snapshot.metric_id, snapshot.period_start)] = snapshot

    backend = metadata.get("analysis_backend")
    source_label = "SQL 注册指标聚合" if backend == "sql" else "分析引擎注册指标聚合"
    cases = []
    used_actions = set()
    for rank, (insight, anomaly, current) in enumerate(deduplicated[:5], 1):
        baseline = snapshots.get(anomaly.baseline_snapshot_id or "")
        diagnosis = diagnoses.get(insight.diagnosis_id or "")
        entity = _entity_name(anomaly.entity_type, anomaly.entity_name)
        metric = _metric_name(anomaly.metric_id)
        unit = _metric_unit(anomaly.metric_id, current.currency)
        impact_ratio = None
        if anomaly.entity_type == "global":
            impact_ratio = anomaly.change_rate
        elif baseline and anomaly.impact_amount is not None:
            global_baseline = global_deltas.get((anomaly.metric_id, baseline.period_start))
            if global_baseline and global_baseline.current_value not in {None, 0}:
                impact_ratio = anomaly.impact_amount / abs(global_baseline.current_value)

        drivers = []
        if diagnosis:
            for item in diagnosis.driver_contributions:
                contribution = item.get("contribution")
                if contribution is None:
                    continue
                share = None
                if anomaly.absolute_change not in {None, 0}:
                    share = abs(float(contribution)) / abs(float(anomaly.absolute_change))
                drivers.append({
                    "name": str(item.get("driver") or item.get("driver_code") or "未标注驱动"),
                    "driver_code": str(item.get("driver_code") or ""),
                    "impact_amount": float(contribution),
                    "contribution_share": share,
                    "unit": unit,
                })
            drivers.sort(key=lambda item: abs(item["impact_amount"]), reverse=True)
            for index, item in enumerate(drivers, 1):
                item["rank"] = index
            residual_threshold = max(0.01, abs(float(anomaly.absolute_change or 0)) * 0.0001)
            if diagnosis.residual_amount is not None and abs(float(diagnosis.residual_amount)) > residual_threshold:
                drivers.append({
                    "rank": len(drivers) + 1,
                    "name": "未解释残差",
                    "driver_code": "residual",
                    "impact_amount": diagnosis.residual_amount,
                    "contribution_share": diagnosis.residual_share,
                    "unit": unit,
                })

        evidence_rows = [{
            "metric": metric,
            "metric_id": anomaly.metric_id,
            "current_value": anomaly.current_value,
            "comparison_value": anomaly.baseline_value,
            "absolute_change": anomaly.absolute_change,
            "change_rate": anomaly.change_rate,
            "unit": unit,
            "source": source_label,
            "formula": METRIC_BY_ID.get(anomaly.metric_id).business_meaning if anomaly.metric_id in METRIC_BY_ID else "注册指标计算",
            "period_start": current.period_start,
            "period_end": current.period_end,
            "comparison_start": baseline.period_start if baseline else None,
            "comparison_end": baseline.period_end if baseline else None,
            "status": "SUCCESS",
        }]
        for evidence_id in _unique(list(insight.evidence_ids) + (list(diagnosis.evidence_ids) if diagnosis else [])):
            bundle = evidence.get(evidence_id)
            if bundle:
                evidence_rows[0]["source_fields"] = list(bundle.source_fields)
                evidence_rows[0]["row_count"] = bundle.row_count
                evidence_rows[0]["limitations"] = list(bundle.limitations)
                break

        action_rows = []
        for recommendation_id in insight.recommendation_ids:
            recommendation = recommendations.get(recommendation_id)
            if recommendation is None:
                continue
            action_key = (anomaly.entity_type, anomaly.entity_id, recommendation.rule_id, recommendation.expected_metric)
            if action_key in used_actions:
                continue
            used_actions.add(action_key)
            playbook = _action_playbook(recommendation.rule_id, entity, diagnosis.missing_context if diagnosis else ())
            expected_definition = METRIC_BY_ID.get(recommendation.expected_metric)
            action_rows.append({
                "priority": recommendation.priority,
                "action_type": str(recommendation.action_type),
                "title": playbook["title"],
                "action": playbook["action"],
                "steps": playbook["steps"],
                "reason": _summary(anomaly, diagnosis, current, baseline),
                "affected_object": entity,
                "owner_role": recommendation.owner_role,
                "expected_metric": expected_definition.name if expected_definition else recommendation.expected_metric,
                "expected_benefit": {
                    "status": "SKIPPED",
                    "value": None,
                    "message": "当前数据不足，无法可靠估算预期收益；需要通过受控实验验证。",
                },
                "validation_target": {
                    "metric": expected_definition.name if expected_definition else recommendation.expected_metric,
                    "target_value": anomaly.baseline_value,
                    "message": "以恢复至对比周期水平作为验证目标，不作为收益预测。" if anomaly.baseline_value is not None else "当前数据不足，无法设置数值目标。",
                },
                "guardrail_metrics": [_metric_name(item) for item in recommendation.guardrail_metrics],
                "validation_period": recommendation.validation_period,
                "stop_condition": recommendation.stop_condition,
                "limitations": _limitations(recommendation.limitations),
            })

        finding_summary = _summary(anomaly, diagnosis, current, baseline)
        case = {
            "rank": rank,
            "case_id": insight.insight_id,
            "period_start": current.period_start,
            "period_end": current.period_end,
            "comparison_start": baseline.period_start if baseline else None,
            "comparison_end": baseline.period_end if baseline else None,
            "anomaly": {
                "object_name": entity,
                "object_type": ENTITY_LABELS.get(anomaly.entity_type, anomaly.entity_type),
                "metric": metric,
                "metric_id": anomaly.metric_id,
                "current_value": anomaly.current_value,
                "comparison_value": anomaly.baseline_value,
                "absolute_change": anomaly.absolute_change,
                "change_rate": anomaly.change_rate,
                "impact_amount": anomaly.impact_amount,
                "impact_ratio": impact_ratio,
                "unit": unit,
                "priority": insight.priority,
                "severity": insight.severity,
            },
            "finding": {
                "what_happened": f"{entity} {metric}{_signed_direction(anomaly.change_rate if anomaly.change_rate is not None else anomaly.absolute_change)}",
                "impact_level": insight.priority,
                "main_object": entity,
                "summary": finding_summary,
                "confidence_score": diagnosis.confidence_score if diagnosis else 0.0,
            },
            "drivers": drivers,
            "evidence": evidence_rows,
            "actions": action_rows,
            "limitations": _limitations(
                insight.limitations,
                diagnosis.missing_context if diagnosis else (),
            ),
            "chain": {
                "anomaly": f"{entity} · {metric}",
                "drivers": [item["name"] for item in drivers if item["driver_code"] != "residual"],
                "object": entity,
                "evidence": [item["metric"] for item in evidence_rows],
                "actions": [item["title"] for item in action_rows],
            },
        }
        cases.append(case)

    return {
        "status": "SUCCESS" if cases else "SKIPPED",
        "message": "" if cases else "当前数据不足，无法生成该分析。",
        "period_start": latest_period,
        "cases": cases,
        "key_findings": [item["finding"] for item in cases],
        "top_impact": [item["anomaly"] | {"rank": item["rank"], "case_id": item["case_id"]} for item in cases],
        "unavailable_metrics": [
            {"metric_id": key, "metric": name, "status": "SKIPPED", "reason": reason}
            for key, name, reason in UNAVAILABLE_METRICS
        ],
    }
