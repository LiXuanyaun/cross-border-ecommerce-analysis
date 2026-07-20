"""Deterministic diagnostic decomposition for detected anomalies."""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .phase2_catalogs import ANOMALY_RULES
from .phase2_models import (
    Anomaly, AnomalyStatus, DataQualitySummary, DiagnosisResult, DiagnosisStatus,
    MetricSnapshot,
)
from .phase2_utils import stable_id, utc_now


RULE_BY_ID = {item.rule_id: item for item in ANOMALY_RULES}


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class DiagnosisEngine:
    def run(
        self, anomalies: Sequence[Anomaly], snapshots: Sequence[MetricSnapshot],
        quality: DataQualitySummary,
    ) -> List[DiagnosisResult]:
        by_id = {item.snapshot_id: item for item in snapshots}
        exact = {(item.metric_id, item.entity_type, item.entity_id, item.period_start): item for item in snapshots}
        output = []
        for anomaly in anomalies:
            if anomaly.status != AnomalyStatus.DETECTED:
                continue
            current = by_id.get(anomaly.current_snapshot_id)
            baseline = by_id.get(anomaly.baseline_snapshot_id)
            output.append(self._diagnose(anomaly, current, baseline, exact, quality))
        return output

    def _diagnose(self, anomaly, current, baseline, exact, quality):
        contributions: List[Mapping[str, float | str]] = []
        method = "registered_metric_decomposition_v1"
        missing_context: List[str] = []
        alternatives: List[str] = []
        explained_amount = None
        total_change = anomaly.absolute_change
        explained_share = 0.0
        primary = "证据不足"

        if current and baseline and anomaly.metric_id == "gmv":
            current_orders = exact.get(("orders", current.entity_type, current.entity_id, current.period_start))
            baseline_orders = exact.get(("orders", current.entity_type, current.entity_id, baseline.period_start))
            current_aov = exact.get(("aov", current.entity_type, current.entity_id, current.period_start))
            baseline_aov = exact.get(("aov", current.entity_type, current.entity_id, baseline.period_start))
            if all((current_orders, baseline_orders, current_aov, baseline_aov)) and all(item.current_value is not None for item in (current_orders, baseline_orders, current_aov, baseline_aov)):
                order_effect = (current_orders.current_value - baseline_orders.current_value) * (current_aov.current_value + baseline_aov.current_value) / 2
                aov_effect = (current_aov.current_value - baseline_aov.current_value) * (current_orders.current_value + baseline_orders.current_value) / 2
                contributions = [
                    {"driver_code": "orders", "driver": "订单数", "contribution": order_effect},
                    {"driver_code": "aov", "driver": "客单价", "contribution": aov_effect},
                ]
                explained_amount = order_effect + aov_effect
                explained_share = self._share(explained_amount, total_change)
                primary = max(contributions, key=lambda item: abs(float(item["contribution"]))) ["driver"]
                missing_context.extend(("广告流量", "库存", "活动", "价格变更"))
                alternatives.append("外部经营事件可能影响订单数或客单价，当前订单数据无法验证")
        elif current and baseline and anomaly.metric_id == "aov":
            method = "aov_structure_diagnostics_v1"
            contributions, explained_amount = self._ratio_decomposition(current, baseline)
            contributions = [
                {
                    **item,
                    "driver": "订单成交金额" if item["driver_code"] == "numerator" else "订单数",
                }
                for item in contributions
            ]
            explained_share = self._share(explained_amount, total_change)
            if contributions:
                primary = max(contributions, key=lambda item: abs(float(item["contribution"]))) ["driver"]
            missing_context.extend(("订单金额分布", "SKU 价格带结构", "折扣事件"))
            alternatives.append("当前拆解能区分订单成交金额与订单数影响，仍不能直接确认价格变化或商品结构原因")
        elif current and baseline and anomaly.metric_id in {"profit_margin", "return_rate", "market_contribution"}:
            contributions, explained_amount = self._ratio_decomposition(current, baseline)
            explained_share = self._share(explained_amount, total_change)
            if contributions:
                primary = max(contributions, key=lambda item: abs(float(item["contribution"]))) ["driver"]
            if anomaly.metric_id == "profit_margin":
                missing_context.extend(("成本明细", "折扣事件", "履约成本"))
            elif anomaly.metric_id == "return_rate":
                missing_context.append("退货原因码")
            else:
                missing_context.append("活动与渠道上下文")
        elif current and anomaly.rule_id == "ANOM-HIGH-SALES-LOW-MARGIN":
            contributions = [{"driver_code": "internal_margin", "driver": "SKU 内部利润率", "contribution": current.current_value or 0.0}]
            explained_amount = current.current_value
            explained_share = 1.0 if current.current_value is not None else 0.0
            primary = "SKU 内部利润率"
            missing_context.extend(("成本明细", "折扣事件", "履约成本"))
        elif current and anomaly.rule_id == "ANOM-HIGH-RETURN":
            contributions = [
                {"driver_code": "returned_orders", "driver": "退货订单分子", "contribution": current.numerator_value or 0.0},
                {"driver_code": "orders", "driver": "订单分母", "contribution": current.denominator_value or 0.0},
            ]
            explained_share = .5
            primary = "退货订单集中度"
            missing_context.append("退货原因码")
            alternatives.append("商品质量、描述、尺码和物流仅为待核查方向，当前无法确认")

        residual_amount = None if total_change is None or explained_amount is None else total_change - explained_amount
        residual_share = max(0.0, 1 - explained_share)
        if str(quality.quality_rating) in {"C", "D"}:
            status = DiagnosisStatus.DATA_ISSUE
            finding = "当前异常主要受数据可信度限制，停止经营解释并优先修复数据。"
        elif explained_share >= .80:
            status = DiagnosisStatus.VERIFIED_DRIVER
            finding = "可重复的数据拆解显示，变化主要由{}贡献。".format(primary)
        elif explained_share >= .50:
            status = DiagnosisStatus.LIKELY_DRIVER
            finding = "现有数据表明，变化较可能与{}相关，仍有部分尚未解释。".format(primary)
        else:
            status = DiagnosisStatus.UNRESOLVED
            finding = "当前证据无法充分解释该异常，不生成确定性经营原因。"
        rule = RULE_BY_ID[anomaly.rule_id]
        sample_ratio = current.sample_size / max(int(rule.minimum_sample.get(anomaly.entity_type, 1)), 1) if current else 0.0
        confidence = round(100 * min(_bounded(explained_share), quality.quality_score / 100, quality.field_coverage / 100, _bounded(sample_ratio)), 2)
        diagnosis_id = stable_id("diag", anomaly.anomaly_id, "1.2.0")
        evidence_ids = tuple(dict.fromkeys(anomaly.evidence_ids))
        return DiagnosisResult(
            diagnosis_id, anomaly.anomaly_id, status, method, "metric_components", str(primary),
            tuple(contributions), explained_amount, round(explained_share, 6), residual_amount,
            round(residual_share, 6), confidence, finding, tuple(alternatives),
            tuple(dict.fromkeys(missing_context)), evidence_ids,
            tuple(anomaly.limitations), utc_now(),
        )

    @staticmethod
    def _share(explained, total):
        if explained is None or total is None:
            return 0.0
        if total == 0:
            return 1.0 if explained == 0 else 0.0
        return _bounded(abs(explained) / abs(total))

    @staticmethod
    def _ratio_decomposition(current: MetricSnapshot, baseline: MetricSnapshot):
        p1, p0 = current.numerator_value, baseline.numerator_value
        d1, d0 = current.denominator_value, baseline.denominator_value
        if None in {p1, p0, d1, d0} or d1 == 0 or d0 == 0:
            return [], None
        numerator_effect = .5 * ((p1 / d0 - p0 / d0) + (p1 / d1 - p0 / d1))
        denominator_effect = .5 * ((p0 / d1 - p0 / d0) + (p1 / d1 - p1 / d0))
        return [
            {"driver_code": "numerator", "driver": "分子变化", "contribution": numerator_effect},
            {"driver_code": "denominator", "driver": "分母变化", "contribution": denominator_effect},
        ], numerator_effect + denominator_effect
