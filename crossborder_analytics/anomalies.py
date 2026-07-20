"""Versioned anomaly rules that consume MetricSnapshot only."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .phase2_catalogs import ANOMALY_RULES
from .phase2_models import (
    Anomaly, AnomalyRule, AnomalyStatus, DataQualitySummary, MetricSnapshot, Severity,
)
from .phase2_utils import stable_id, utc_now


PERIOD_TYPES = {"month", "week", "event"}


def _severity(rule_id: str, impact_share: float, guardrail_breach: bool = False) -> Severity:
    if guardrail_breach and impact_share >= .25:
        return Severity.CRITICAL
    if guardrail_breach or impact_share >= .10 or rule_id in {"ANOM-MARGIN-DROP", "ANOM-MARKET-UNHEALTHY-GROWTH"}:
        return Severity.HIGH
    if impact_share >= .05:
        return Severity.MEDIUM
    return Severity.LOW


class RulesEngine:
    def __init__(self, rules: Sequence[AnomalyRule] = ANOMALY_RULES):
        self.rules = tuple(rules)

    def run(self, snapshots: Sequence[MetricSnapshot], quality: DataQualitySummary) -> List[Anomaly]:
        by_key: Dict[Tuple[str, str, str, str], List[MetricSnapshot]] = defaultdict(list)
        exact: Dict[Tuple[str, str, str, str], MetricSnapshot] = {}
        for item in snapshots:
            by_key[(item.metric_id, item.entity_type, item.entity_id, item.period_type)].append(item)
            exact[(item.metric_id, item.entity_type, item.entity_id, item.period_start)] = item
        for values in by_key.values():
            values.sort(key=lambda item: item.period_start)

        output: List[Anomaly] = []
        for rule in self.rules:
            if rule.rule_id == "ANOM-MARKET-UNHEALTHY-GROWTH":
                output.extend(self._market_growth(rule, by_key, exact, quality))
            elif rule.rule_id == "ANOM-HERO-GROWTH-RISK":
                output.extend(self._hero_growth(rule, by_key, exact, quality))
            elif rule.comparison_mode == "period_over_period":
                output.extend(self._period_rule(rule, by_key, exact, quality))
            elif rule.rule_id == "ANOM-HIGH-SALES-LOW-MARGIN":
                output.extend(self._low_margin(rule, by_key, exact, quality))
            elif rule.rule_id == "ANOM-HIGH-RETURN":
                output.extend(self._high_return(rule, by_key, exact, quality))
        return sorted(output, key=lambda item: (item.detected_at, item.rule_id, item.entity_type, item.entity_id))

    @staticmethod
    def _gate(rule, current, baseline, quality):
        limitations = []
        minimum = int(rule.minimum_sample.get(current.entity_type, 1))
        if str(quality.quality_rating) not in {"A", "B"}:
            limitations.append("数据可信度为 {} 级，规则被抑制".format(quality.quality_rating))
        if current.capability_status == "UNSUPPORTED":
            limitations.append("分析能力不支持该规则")
        if current.sample_size < minimum or (baseline and baseline.sample_size < minimum):
            limitations.append("样本量低于规则门槛 {}".format(minimum))
        if not current.is_complete_period or (baseline and not baseline.is_complete_period):
            limitations.append("比较周期不完整")
        return tuple(limitations)

    def _period_rule(self, rule, by_key, exact, quality):
        output = []
        for (metric_id, entity_type, entity_id, period_type), values in by_key.items():
            if metric_id != rule.metric_id or entity_type not in rule.entity_types or period_type not in PERIOD_TYPES:
                continue
            previous_triggered = None
            for baseline, current in zip(values, values[1:]):
                limitations = self._gate(rule, current, baseline, quality)
                change = None if current.current_value is None or baseline.current_value is None else current.current_value - baseline.current_value
                rate = None if change is None or baseline.current_value == 0 else change / abs(baseline.current_value)
                triggered, impact_share, guardrail = self._trigger(rule, current, baseline, rate, change, exact)
                status = AnomalyStatus.SUPPRESSED if limitations else (AnomalyStatus.DETECTED if triggered else (AnomalyStatus.RECOVERED if previous_triggered else None))
                if status is None:
                    previous_triggered = None
                    continue
                anomaly = self._anomaly(rule, current, baseline, status, change, rate, impact_share, guardrail, limitations, previous_triggered)
                output.append(anomaly)
                previous_triggered = anomaly.anomaly_id if status == AnomalyStatus.DETECTED else None
        return output

    @staticmethod
    def _trigger(rule, current, baseline, rate, change, exact):
        impact_share = 0.0
        guardrail = False
        if rule.rule_id == "ANOM-GMV-DROP":
            triggered = rate is not None and rate <= rule.threshold
            minimum_share = .05
        elif rule.rule_id == "ANOM-GMV-SPIKE":
            triggered = rate is not None and rate >= rule.threshold
            minimum_share = .10
        elif rule.rule_id == "ANOM-MARGIN-DROP":
            triggered = change is not None and change <= rule.threshold
            minimum_share = 0.0
            guardrail = triggered
        elif rule.rule_id == "ANOM-MIX-SHIFT":
            triggered = change is not None and abs(change) >= rule.threshold
            minimum_share = 0.0
        elif rule.rule_id == "ANOM-AOV-DROP":
            triggered = rate is not None and rate <= rule.threshold
            minimum_share = 0.0
        else:
            return False, 0.0, False
        if current.entity_type != "global" and change is not None:
            global_current = exact.get(("gmv", "global", "__all__", current.period_start))
            global_baseline = exact.get(("gmv", "global", "__all__", baseline.period_start))
            if global_current and global_baseline and global_current.current_value is not None and global_baseline.current_value is not None:
                total_change = global_current.current_value - global_baseline.current_value
                impact_share = abs(change) / abs(total_change) if total_change else 0.0
            if minimum_share and impact_share < minimum_share:
                triggered = False
        else:
            impact_share = 1.0 if triggered else 0.0
        return triggered, impact_share, guardrail

    def _low_margin(self, rule, by_key, exact, quality):
        candidates = []
        for (metric_id, entity_type, entity_id, period_type), values in by_key.items():
            if metric_id == "profit_margin" and entity_type == "sku" and period_type in PERIOD_TYPES:
                complete = [item for item in values if item.is_complete_period]
                if complete:
                    candidates.append(complete[-1])
        if not candidates:
            return []
        gmv_values = [exact.get(("gmv", "sku", item.entity_id, item.period_start)) for item in candidates]
        valid_gmv = sorted(item.current_value for item in gmv_values if item and item.current_value is not None)
        cutoff = valid_gmv[max(0, int(len(valid_gmv) * .8) - 1)] if valid_gmv else None
        output = []
        for current in candidates:
            gmv = exact.get(("gmv", "sku", current.entity_id, current.period_start))
            overall = exact.get(("profit_margin", "global", "__all__", current.period_start))
            limitations = self._gate(rule, current, None, quality)
            low = current.current_value is not None and overall and overall.current_value is not None and (current.current_value <= 0 or current.current_value <= overall.current_value - .05)
            triggered = bool(gmv and cutoff is not None and gmv.current_value >= cutoff and low)
            status = AnomalyStatus.SUPPRESSED if limitations else (AnomalyStatus.DETECTED if triggered else None)
            if status:
                output.append(self._anomaly(rule, current, overall, status, None, None, .2 if triggered else 0, triggered, limitations, None))
        return output

    def _high_return(self, rule, by_key, exact, quality):
        output = []
        for (metric_id, entity_type, entity_id, period_type), values in by_key.items():
            if metric_id != "return_rate" or entity_type not in rule.entity_types or period_type not in PERIOD_TYPES:
                continue
            current = next((item for item in reversed(values) if item.is_complete_period), None)
            if not current:
                continue
            overall = exact.get(("return_rate", "global", "__all__", current.period_start))
            limitations = self._gate(rule, current, None, quality)
            triggered = current.current_value is not None and current.current_value >= .20 and (entity_type == "global" or (overall and overall.current_value is not None and current.current_value >= overall.current_value + .05))
            status = AnomalyStatus.SUPPRESSED if limitations else (AnomalyStatus.DETECTED if triggered else None)
            if status:
                output.append(self._anomaly(rule, current, overall, status, None, None, .1 if triggered else 0, triggered, limitations, None))
        return output

    def _market_growth(self, rule, by_key, exact, quality):
        return self._compound_growth(rule, by_key, exact, quality, "market", .20, .05, .05)

    def _hero_growth(self, rule, by_key, exact, quality):
        return self._compound_growth(rule, by_key, exact, quality, "sku", .50, .05, .05, require_growth_share=.30)

    def _compound_growth(self, rule, by_key, exact, quality, entity_type, growth_threshold, margin_drop, return_rise, require_growth_share=0.0):
        output = []
        for (metric_id, kind, entity_id, period_type), values in by_key.items():
            if metric_id != "gmv" or kind != entity_type or period_type not in PERIOD_TYPES:
                continue
            previous_triggered = None
            for baseline, current in zip(values, values[1:]):
                limitations = self._gate(rule, current, baseline, quality)
                if current.current_value is None or baseline.current_value in {None, 0}:
                    growth = None
                else:
                    growth = (current.current_value - baseline.current_value) / abs(baseline.current_value)
                margin_current = exact.get(("profit_margin", entity_type, entity_id, current.period_start))
                margin_base = exact.get(("profit_margin", entity_type, entity_id, baseline.period_start))
                return_current = exact.get(("return_rate", entity_type, entity_id, current.period_start))
                return_base = exact.get(("return_rate", entity_type, entity_id, baseline.period_start))
                margin_delta = margin_current.current_value - margin_base.current_value if margin_current and margin_base and margin_current.current_value is not None and margin_base.current_value is not None else None
                return_delta = return_current.current_value - return_base.current_value if return_current and return_base and return_current.current_value is not None and return_base.current_value is not None else None
                guardrail = (margin_delta is not None and margin_delta <= -margin_drop) or (return_delta is not None and return_delta >= return_rise)
                impact_share = 0.0
                global_current = exact.get(("gmv", "global", "__all__", current.period_start))
                global_base = exact.get(("gmv", "global", "__all__", baseline.period_start))
                if global_current and global_base:
                    total_growth = global_current.current_value - global_base.current_value
                    impact_share = abs(current.current_value - baseline.current_value) / abs(total_growth) if total_growth else 0.0
                triggered = growth is not None and growth >= growth_threshold and guardrail and impact_share >= require_growth_share
                status = AnomalyStatus.SUPPRESSED if limitations else (AnomalyStatus.DETECTED if triggered else (AnomalyStatus.RECOVERED if previous_triggered else None))
                if status:
                    anomaly = self._anomaly(rule, current, baseline, status, current.current_value - baseline.current_value, growth, impact_share, guardrail, limitations, previous_triggered)
                    output.append(anomaly)
                    previous_triggered = anomaly.anomaly_id if status == AnomalyStatus.DETECTED else None
        return output

    @staticmethod
    def _anomaly(rule, current, baseline, status, change, rate, impact_share, guardrail, limitations, recovery_of):
        anomaly_id = stable_id(
            "anom", current.dataset_id, current.scope_id, rule.rule_id, current.entity_type,
            current.entity_id, current.metric_id, current.period_start,
        )
        if "MARGIN" in rule.rule_id:
            impact_type = "profit_margin_change_pp"
        elif "RETURN" in rule.rule_id:
            impact_type = "returned_gmv_exposure"
        elif "AOV" in rule.rule_id:
            impact_type = "aov_change"
        elif "MIX" in rule.rule_id:
            impact_type = "contribution_change_pp"
        else:
            impact_type = "gmv_change"
        impact_amount = change if impact_type in {"gmv_change", "aov_change", "profit_margin_change_pp", "contribution_change_pp"} else None
        evidence_ids = tuple(dict.fromkeys([current.evidence_id] + ([baseline.evidence_id] if baseline else [])))
        return Anomaly(
            anomaly_id, rule.rule_id, rule.version, current.dataset_id, current.scope_id,
            current.entity_type, current.entity_id, current.entity_id, current.metric_id,
            current.snapshot_id, baseline.snapshot_id if baseline else None,
            current.current_value, baseline.current_value if baseline else None,
            change, rate, impact_amount, impact_type, _severity(rule.rule_id, impact_share, guardrail),
            status, current.quality_status, current.capability_status, evidence_ids,
            tuple(limitations) + tuple(rule.limitations), utc_now(), recovery_of,
        )
