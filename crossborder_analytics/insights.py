"""Flatten audited artifacts into stable, prioritized InsightView records."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence

from .phase2_models import (
    AnalysisCapability, Anomaly, AnomalyStatus, DataQualitySummary, DiagnosisResult,
    DiagnosisStatus, InsightView, Recommendation,
)
from .phase2_utils import stable_id, utc_now


SEVERITY_SCORE = {"CRITICAL": 100.0, "HIGH": 75.0, "MEDIUM": 50.0, "LOW": 25.0}
CAPABILITY_SCORE = {"FULL": 100.0, "PARTIAL": 60.0, "UNSUPPORTED": 0.0}
DIAGNOSIS_SCORE = {"VERIFIED_DRIVER": 100.0, "LIKELY_DRIVER": 70.0, "UNRESOLVED": 40.0, "DATA_ISSUE": 20.0}


def _priority(score: float) -> str:
    if score >= 80:
        return "P0"
    if score >= 60:
        return "P1"
    if score >= 40:
        return "P2"
    return "P3"


class InsightEngine:
    def run(
        self, anomalies: Sequence[Anomaly], diagnoses: Sequence[DiagnosisResult],
        recommendations: Sequence[Recommendation], quality: DataQualitySummary,
        capabilities: Sequence[AnalysisCapability],
    ) -> List[InsightView]:
        detected = [item for item in anomalies if item.status == AnomalyStatus.DETECTED]
        if not detected:
            return [self._empty(quality, capabilities)]
        diagnosis_by_anomaly = {item.anomaly_id: item for item in diagnoses}
        recommendations_by_diagnosis = defaultdict(list)
        for item in recommendations:
            recommendations_by_diagnosis[item.diagnosis_id].append(item)
        impact_groups = defaultdict(list)
        for item in detected:
            impact_groups[item.impact_type].append(abs(item.impact_amount or item.change_rate or 0.0))

        output = []
        for anomaly in detected:
            diagnosis = diagnosis_by_anomaly.get(anomaly.anomaly_id)
            recs = recommendations_by_diagnosis.get(diagnosis.diagnosis_id if diagnosis else "", [])
            impact_value = abs(anomaly.impact_amount or anomaly.change_rate or 0.0)
            peers = sorted(impact_groups[anomaly.impact_type])
            impact_score = 100.0 * (sum(value <= impact_value for value in peers) / len(peers))
            risk_score = SEVERITY_SCORE[str(anomaly.severity)]
            urgency = 100.0 if str(anomaly.severity) == "CRITICAL" else (75.0 if str(anomaly.severity) == "HIGH" or anomaly.entity_type in {"global", "market"} else 50.0)
            diagnosis_status = str(diagnosis.status) if diagnosis else "UNRESOLVED"
            evidence_score = (
                quality.quality_score
                + CAPABILITY_SCORE.get(anomaly.capability_status, 0.0)
                + DIAGNOSIS_SCORE.get(diagnosis_status, 40.0)
            ) / 3
            if diagnosis_status == "UNRESOLVED":
                evidence_score = min(evidence_score, 40.0)
            score = round(impact_score * .40 + risk_score * .30 + urgency * .20 + evidence_score * .10, 2)
            current_period = anomaly.detected_at
            output.append(InsightView(
                insight_id=stable_id("ins", anomaly.anomaly_id, "1.0.0"),
                type="ANOMALY", priority=_priority(score), priority_score=score,
                severity=str(anomaly.severity), entity_type=anomaly.entity_type,
                entity_id=anomaly.entity_id, entity_name=anomaly.entity_name,
                metric_id=anomaly.metric_id, current_snapshot_id=anomaly.current_snapshot_id,
                baseline_snapshot_id=anomaly.baseline_snapshot_id, anomaly_id=anomaly.anomaly_id,
                diagnosis_id=diagnosis.diagnosis_id if diagnosis else None,
                recommendation_ids=tuple(item.recommendation_id for item in recs),
                evidence_ids=anomaly.evidence_ids,
                current_value=anomaly.current_value, previous_value=anomaly.baseline_value,
                change_rate=anomaly.change_rate, impact_amount=anomaly.impact_amount,
                finding=diagnosis.finding if diagnosis else "异常已确认，诊断证据尚未生成。",
                impact="{} 的 {} 发生变化".format(anomaly.entity_name, anomaly.metric_id),
                diagnosis_status=diagnosis_status,
                diagnosis_summary=diagnosis.finding if diagnosis else "证据不足",
                confidence_score=diagnosis.confidence_score if diagnosis else 0.0,
                recommendation_summary="；".join(item.action for item in recs) or "先补充证据再决定动作",
                limitations=tuple(dict.fromkeys(anomaly.limitations + tuple(item for rec in recs for item in rec.limitations))),
                data_quality_level=str(quality.quality_rating),
                analysis_capability_status=anomaly.capability_status, created_at=utc_now(),
            ))
        return sorted(output, key=lambda item: (-item.priority_score, -SEVERITY_SCORE.get(item.severity, 0), -(abs(item.impact_amount or 0)), item.insight_id))

    @staticmethod
    def _empty(quality, capabilities):
        supported = [item for item in capabilities if str(item.status) != "UNSUPPORTED"]
        capability_status = "FULL" if supported and len(supported) == len(capabilities) else ("PARTIAL" if supported else "UNSUPPORTED")
        return InsightView(
            stable_id("ins", quality.dataset_id, quality.scope_id, "no_anomaly"), "STATUS", "P3", 0.0,
            "LOW", "global", "__all__", "全部经营对象", "", None, None, None, None,
            (), (), None, None, None, None, "当前未发现达到规则阈值的异常",
            "规则已在当前完整周期和质量门槛下执行", "UNRESOLVED",
            "没有异常不等于没有经营风险；仅表示当前未达到注册阈值。", 0.0,
            "保持周期监测", (), str(quality.quality_rating), capability_status, utc_now(),
        )
