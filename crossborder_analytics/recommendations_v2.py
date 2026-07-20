"""Recommendations gated by diagnosis status and data quality."""
from __future__ import annotations

from typing import Dict, List, Sequence

from .phase2_catalogs import RECOMMENDATION_RULES
from .phase2_models import (
    ActionType, Anomaly, DataQualitySummary, DiagnosisResult, DiagnosisStatus,
    MetricSnapshot, Recommendation, Severity,
)
from .phase2_utils import stable_id, utc_now


GENERIC_INVESTIGATE = "先核对业务事件和缺失上下文，再决定是否采取经营动作"
GENERIC_DATA = "修复数据问题或补充关键字段后重新运行分析"


class RecommendationEngine:
    def run(
        self, diagnoses: Sequence[DiagnosisResult], anomalies: Sequence[Anomaly],
        quality: DataQualitySummary, snapshots: Sequence[MetricSnapshot] = (),
    ) -> List[Recommendation]:
        anomaly_by_id = {item.anomaly_id: item for item in anomalies}
        snapshot_by_id = {item.snapshot_id: item for item in snapshots}
        exact = {
            (item.metric_id, item.entity_type, item.entity_id, item.period_start): item
            for item in snapshots
        }
        output = []
        for diagnosis in diagnoses:
            anomaly = anomaly_by_id[diagnosis.anomaly_id]
            driver_code = self._primary_driver_code(diagnosis)
            matching = [
                rule for rule in RECOMMENDATION_RULES
                if anomaly.rule_id in rule.supported_rule_ids and str(diagnosis.status) in rule.supported_diagnosis_statuses
                and (not rule.driver_codes or driver_code in rule.driver_codes)
                and self._preconditions_met(rule, anomaly, snapshot_by_id, exact)
            ]
            if diagnosis.status == DiagnosisStatus.DATA_ISSUE:
                output.append(self._generic(diagnosis, anomaly, ActionType.DATA_REQUEST, GENERIC_DATA, quality))
            elif diagnosis.status == DiagnosisStatus.UNRESOLVED or not matching:
                output.append(self._generic(diagnosis, anomaly, ActionType.INVESTIGATE, GENERIC_INVESTIGATE, quality))
            else:
                for rule in matching:
                    action_type = rule.action_type
                    limitations = list(diagnosis.limitations)
                    if action_type in {ActionType.SCALE, ActionType.LIMIT} and str(quality.quality_rating) not in {"A", "B"}:
                        action_type = ActionType.INVESTIGATE
                        limitations.append("数据可信度不足，经营动作已降级为调查")
                    output.append(Recommendation(
                        stable_id("rec", diagnosis.diagnosis_id, rule.recommendation_rule_id, rule.version),
                        diagnosis.diagnosis_id, rule.recommendation_rule_id, action_type,
                        self._priority(anomaly.severity), rule.action_template.format(entity=anomaly.entity_name), diagnosis.finding,
                        rule.owner_role, rule.expected_metric, rule.guardrail_metrics,
                        rule.validation_period, rule.stop_condition, diagnosis.evidence_ids,
                        tuple(limitations) + tuple("缺少{}".format(item) for item in diagnosis.missing_context), utc_now(),
                    ))
        return output

    @staticmethod
    def _primary_driver_code(diagnosis: DiagnosisResult) -> str:
        contributions = [
            item for item in diagnosis.driver_contributions
            if item.get("contribution") is not None
        ]
        if not contributions:
            return ""
        primary = max(contributions, key=lambda item: abs(float(item["contribution"])))
        return str(primary.get("driver_code") or "")

    @staticmethod
    def _preconditions_met(rule, anomaly, snapshot_by_id, exact) -> bool:
        if rule.recommendation_rule_id == "REC-MARKET-SCALE" and anomaly.entity_type != "market":
            return False
        if "healthy_guardrails" not in rule.preconditions:
            return True
        current = snapshot_by_id.get(anomaly.current_snapshot_id)
        baseline = snapshot_by_id.get(anomaly.baseline_snapshot_id)
        if current is None or baseline is None:
            return False
        margin_current = exact.get(("profit_margin", current.entity_type, current.entity_id, current.period_start))
        margin_baseline = exact.get(("profit_margin", baseline.entity_type, baseline.entity_id, baseline.period_start))
        return_current = exact.get(("return_rate", current.entity_type, current.entity_id, current.period_start))
        return_baseline = exact.get(("return_rate", baseline.entity_type, baseline.entity_id, baseline.period_start))
        values = (margin_current, margin_baseline, return_current, return_baseline)
        if not all(values) or any(item.current_value is None for item in values):
            return False
        margin_change = margin_current.current_value - margin_baseline.current_value
        return_change = return_current.current_value - return_baseline.current_value
        return (
            margin_current.current_value > 0
            and return_current.current_value < .20
            and margin_change > -.05
            and return_change < .05
        )

    @staticmethod
    def _priority(severity: Severity) -> str:
        return {Severity.CRITICAL: "P0", Severity.HIGH: "P1", Severity.MEDIUM: "P2", Severity.LOW: "P3"}[severity]

    def _generic(self, diagnosis, anomaly, action_type, action, quality):
        return Recommendation(
            stable_id("rec", diagnosis.diagnosis_id, str(action_type), "1.1.0"), diagnosis.diagnosis_id,
            "REC-GENERIC-{}".format(action_type), action_type, self._priority(anomaly.severity),
            action, diagnosis.finding, "数据分析师" if action_type == ActionType.DATA_REQUEST else "运营负责人",
            anomaly.metric_id, ("data_quality",), "补数或核查后重新分析",
            "证据仍不足时不升级为确定性经营动作", diagnosis.evidence_ids,
            tuple(diagnosis.limitations) + tuple("缺少{}".format(item) for item in diagnosis.missing_context), utc_now(),
        )
