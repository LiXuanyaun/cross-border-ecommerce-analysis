"""Stable Phase 2 domain contracts for trusted business analysis."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd


class CodeEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class QualityRating(CodeEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class CapabilityStatus(CodeEnum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"


class AnomalyStatus(CodeEnum):
    DETECTED = "DETECTED"
    RECOVERED = "RECOVERED"
    SUPPRESSED = "SUPPRESSED"


class DiagnosisStatus(CodeEnum):
    VERIFIED_DRIVER = "VERIFIED_DRIVER"
    LIKELY_DRIVER = "LIKELY_DRIVER"
    UNRESOLVED = "UNRESOLVED"
    DATA_ISSUE = "DATA_ISSUE"


class ActionType(CodeEnum):
    INVESTIGATE = "INVESTIGATE"
    OPTIMIZE = "OPTIMIZE"
    SCALE = "SCALE"
    LIMIT = "LIMIT"
    DATA_REQUEST = "DATA_REQUEST"


class WorkItemStatus(CodeEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    REVIEW = "REVIEW"
    COMPLETED = "COMPLETED"
    DISMISSED = "DISMISSED"
    WAITING_DATA = "WAITING_DATA"


class MarketGrowthStatus(CodeEnum):
    HEALTHY_GROWTH = "健康增长"
    RISKY_GROWTH = "风险增长"
    STABLE = "稳定经营"
    CONTRACTING = "收缩待修复"
    LOW_VALUE = "低价值市场"
    INSUFFICIENT_SAMPLE = "样本不足"
    INSUFFICIENT_DATA = "数据不足"


class ProductOpportunityType(CodeEnum):
    SCALE = "扩量机会"
    MARKET_EXPANSION = "市场扩张机会"
    CUSTOMER_PENETRATION = "客户渗透机会"
    BUNDLE = "组合销售机会"
    PROFIT_REPAIR = "利润修复机会"
    HIGH_RISK_GROWTH = "高风险增长"
    WATCH = "观察机会"
    INSUFFICIENT_SAMPLE = "样本不足"
    INSUFFICIENT_DATA = "数据不足"


class Severity(CodeEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_json_value(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


class Serializable:
    def to_dict(self) -> Dict[str, Any]:
        return _json_value(asdict(self))


@dataclass(frozen=True)
class AnalysisRequest(Serializable):
    filters: Mapping[str, Any] = field(default_factory=dict)
    period_type: str = "month"
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    comparison_start: Optional[str] = None
    comparison_end: Optional[str] = None

    def __post_init__(self) -> None:
        if self.period_type not in {"month", "week", "event"}:
            raise ValueError("period_type must be month, week, or event")
        values = (self.period_start, self.period_end, self.comparison_start, self.comparison_end)
        if self.period_type == "event" and any(value is None for value in values):
            raise ValueError("event analysis requires an explicit event and comparison period")
        if self.period_type == "event":
            event_days = (pd.Timestamp(self.period_end) - pd.Timestamp(self.period_start)).days
            comparison_days = (pd.Timestamp(self.comparison_end) - pd.Timestamp(self.comparison_start)).days
            if event_days != comparison_days:
                raise ValueError("event and comparison periods must have equal length")


@dataclass(frozen=True)
class MetricDefinition(Serializable):
    metric_id: str
    name: str
    business_meaning: str
    formula: str
    numerator: Optional[str]
    denominator: Optional[str]
    unit: str
    currency_policy: str
    grain: Tuple[str, ...]
    supported_dimensions: Tuple[str, ...]
    time_grain: Tuple[str, ...]
    comparison_mode: Tuple[str, ...]
    required_fields: Tuple[str, ...]
    minimum_sample: int
    null_policy: str
    zero_denominator_policy: str
    quality_gate: str
    capability_gate: str
    source_query: str
    version: str
    owner: str
    limitations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class MetricSnapshot(Serializable):
    snapshot_id: str
    dataset_id: str
    scope_id: str
    metric_id: str
    metric_version: str
    entity_type: str
    entity_id: str
    period_type: str
    period_start: str
    period_end: str
    is_complete_period: bool
    current_value: Optional[float]
    numerator_value: Optional[float]
    denominator_value: Optional[float]
    sample_size: int
    currency: Optional[str]
    quality_status: str
    capability_status: str
    evidence_id: str
    calculated_at: str
    limitations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class EntityAssessment(Serializable):
    assessment_id: str
    dataset_id: str
    scope_id: str
    assessment_type: str
    entity_type: str
    entity_id: str
    period_start: str
    period_end: str
    value: str
    sample_size: int
    evidence_ids: Tuple[str, ...]
    limitations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class QualityDimension(Serializable):
    dimension: str
    score: float
    weight: float
    status: str
    finding: str
    recommendation: str


@dataclass(frozen=True)
class DataQualitySummary(Serializable):
    dataset_id: str
    scope_id: str
    quality_score: float
    quality_rating: QualityRating
    quality_explanation: str
    completeness: float
    validity: float
    field_coverage: float
    uniqueness: float
    time_coverage: float
    fatal_issues: int
    warning_issues: int
    calculated_at: str


@dataclass(frozen=True)
class FieldQuality(Serializable):
    dataset_id: str
    scope_id: str
    field: str
    business_meaning: str
    presence_status: str
    completeness_rate: Optional[float]
    validity_rate: Optional[float]
    uniqueness_rate: Optional[float]
    status: str
    analysis_impact: str


@dataclass(frozen=True)
class AnalysisCapability(Serializable):
    capability_id: str
    name: str
    status: CapabilityStatus
    supported_conclusions: Tuple[str, ...]
    unsupported_conclusions: Tuple[str, ...]
    reasons: Tuple[str, ...]
    affected_modules: Tuple[str, ...]
    unaffected_modules: Tuple[str, ...]


@dataclass(frozen=True)
class ImprovementPlan(Serializable):
    improvement_id: str
    priority: str
    issue: str
    impact: str
    recommended_action: str
    unlocked_capabilities: Tuple[str, ...]


@dataclass(frozen=True)
class AnomalyRule(Serializable):
    rule_id: str
    name: str
    metric_id: str
    entity_types: Tuple[str, ...]
    comparison_mode: str
    baseline_window: int
    direction: str
    threshold: float
    minimum_sample: Mapping[str, int]
    impact_formula: str
    severity_policy: str
    quality_gate: str
    capability_gate: str
    recovery_condition: str
    version: str
    limitations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Anomaly(Serializable):
    anomaly_id: str
    rule_id: str
    rule_version: str
    dataset_id: str
    scope_id: str
    entity_type: str
    entity_id: str
    entity_name: str
    metric_id: str
    current_snapshot_id: Optional[str]
    baseline_snapshot_id: Optional[str]
    current_value: Optional[float]
    baseline_value: Optional[float]
    absolute_change: Optional[float]
    change_rate: Optional[float]
    impact_amount: Optional[float]
    impact_type: str
    severity: Severity
    status: AnomalyStatus
    quality_status: str
    capability_status: str
    evidence_ids: Tuple[str, ...]
    limitations: Tuple[str, ...]
    detected_at: str
    recovery_of_anomaly_id: Optional[str] = None


@dataclass(frozen=True)
class DiagnosisResult(Serializable):
    diagnosis_id: str
    anomaly_id: str
    status: DiagnosisStatus
    diagnostic_method: str
    driver_dimension: str
    primary_driver: str
    driver_contributions: Tuple[Mapping[str, Any], ...]
    explained_amount: Optional[float]
    explained_share: float
    residual_amount: Optional[float]
    residual_share: float
    confidence_score: float
    finding: str
    alternative_explanations: Tuple[str, ...]
    missing_context: Tuple[str, ...]
    evidence_ids: Tuple[str, ...]
    limitations: Tuple[str, ...]
    diagnosed_at: str


@dataclass(frozen=True)
class RecommendationRule(Serializable):
    recommendation_rule_id: str
    supported_rule_ids: Tuple[str, ...]
    supported_diagnosis_statuses: Tuple[str, ...]
    driver_codes: Tuple[str, ...]
    preconditions: Tuple[str, ...]
    blocked_conditions: Tuple[str, ...]
    action_type: ActionType
    action_template: str
    owner_role: str
    expected_metric: str
    guardrail_metrics: Tuple[str, ...]
    validation_period: str
    stop_condition: str
    version: str


@dataclass(frozen=True)
class Recommendation(Serializable):
    recommendation_id: str
    diagnosis_id: str
    rule_id: str
    action_type: ActionType
    priority: str
    action: str
    rationale: str
    owner_role: str
    expected_metric: str
    guardrail_metrics: Tuple[str, ...]
    validation_period: str
    stop_condition: str
    evidence_ids: Tuple[str, ...]
    limitations: Tuple[str, ...]
    created_at: str


@dataclass(frozen=True)
class AnalysisWorkItem(Serializable):
    work_item_id: str
    scope_id: str
    anomaly_id: str
    insight_id: Optional[str]
    workflow_status: WorkItemStatus
    owner: str
    due_date: Optional[str]
    resolution_note: str
    updated_at: str


@dataclass(frozen=True)
class EvidenceBundle(Serializable):
    evidence_id: str
    dataset_id: str
    scope_id: str
    database_schema_version: int
    query_name: str
    query_version: str
    query_parameters: Mapping[str, Any]
    metric_snapshot_ids: Tuple[str, ...]
    source_fields: Tuple[str, ...]
    formula: str
    period_start: str
    period_end: str
    executed_at: str
    duration_ms: float
    row_count: int
    result_digest: str
    result_summary: Mapping[str, Any]
    limitations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class InsightView(Serializable):
    insight_id: str
    type: str
    priority: str
    priority_score: float
    severity: str
    entity_type: str
    entity_id: str
    entity_name: str
    metric_id: str
    current_snapshot_id: Optional[str]
    baseline_snapshot_id: Optional[str]
    anomaly_id: Optional[str]
    diagnosis_id: Optional[str]
    recommendation_ids: Tuple[str, ...]
    evidence_ids: Tuple[str, ...]
    current_value: Optional[float]
    previous_value: Optional[float]
    change_rate: Optional[float]
    impact_amount: Optional[float]
    finding: str
    impact: str
    diagnosis_status: str
    diagnosis_summary: str
    confidence_score: float
    recommendation_summary: str
    limitations: Tuple[str, ...]
    data_quality_level: str
    analysis_capability_status: str
    created_at: str


@dataclass(frozen=True)
class MarketOpportunity(Serializable):
    opportunity_id: str
    dataset_id: str
    scope_id: str
    market: str
    status: MarketGrowthStatus
    current_period: str
    comparison_period: str
    current_gmv: float
    previous_gmv: Optional[float]
    gmv_change: Optional[float]
    gmv_growth_rate: Optional[float]
    current_orders: int
    previous_orders: int
    order_growth_rate: Optional[float]
    current_aov: Optional[float]
    previous_aov: Optional[float]
    profit_margin: Optional[float]
    profit_margin_change: Optional[float]
    return_rate: Optional[float]
    return_rate_change: Optional[float]
    sku_concentration: Optional[float]
    quality_score: Optional[float]
    primary_driver: str
    driver_contributions: Tuple[Mapping[str, Any], ...]
    top_categories: Tuple[Mapping[str, Any], ...]
    top_skus: Tuple[Mapping[str, Any], ...]
    recommended_action: str
    guardrail_metrics: Tuple[str, ...]
    validation_period: str
    stop_condition: str
    evidence_ids: Tuple[str, ...]
    limitations: Tuple[str, ...]
    created_at: str


@dataclass(frozen=True)
class ProductOpportunity(Serializable):
    opportunity_id: str
    dataset_id: str
    scope_id: str
    product_id: str
    product_name: str
    category: str
    opportunity_type: ProductOpportunityType
    operating_status: str
    current_period: str
    comparison_period: str
    current_gmv: float
    previous_gmv: Optional[float]
    gmv_change: Optional[float]
    gmv_growth_rate: Optional[float]
    current_orders: int
    previous_orders: int
    profit_margin: Optional[float]
    profit_margin_change: Optional[float]
    return_rate: Optional[float]
    return_rate_change: Optional[float]
    market_coverage: int
    market_growth_contribution: Optional[float]
    customer_concentration: Optional[float]
    high_value_customer_share: Optional[float]
    primary_market: str
    target_market: str
    primary_customer_group: str
    rationale: str
    recommended_action: str
    guardrail_metrics: Tuple[str, ...]
    validation_period: str
    stop_condition: str
    evidence_ids: Tuple[str, ...]
    limitations: Tuple[str, ...]
    created_at: str


@dataclass(frozen=True)
class ActionItem(Serializable):
    action_id: str
    dataset_id: str
    scope_id: str
    source_type: str
    source_id: str
    entity_id: str
    entity_name: str
    current_judgement: str
    impact_amount: Optional[float]
    priority: str
    evidence_confidence: str
    primary_driver: str
    action: str
    owner_role: str
    guardrail_metrics: Tuple[str, ...]
    validation_period: str
    stop_condition: str
    evidence_ids: Tuple[str, ...]
    limitations: Tuple[str, ...]
    created_at: str


@dataclass
class AnalysisArtifacts:
    metric_definitions: List[MetricDefinition] = field(default_factory=list)
    metric_snapshots: List[MetricSnapshot] = field(default_factory=list)
    entity_assessments: List[EntityAssessment] = field(default_factory=list)
    data_quality: Optional[DataQualitySummary] = None
    data_quality_dimensions: List[QualityDimension] = field(default_factory=list)
    field_quality: List[FieldQuality] = field(default_factory=list)
    analysis_capability: List[AnalysisCapability] = field(default_factory=list)
    data_improvement_plan: List[ImprovementPlan] = field(default_factory=list)
    unsupported_conclusions: List[Mapping[str, Any]] = field(default_factory=list)
    anomaly_rules: List[AnomalyRule] = field(default_factory=list)
    anomalies: List[Anomaly] = field(default_factory=list)
    diagnoses: List[DiagnosisResult] = field(default_factory=list)
    recommendation_rules: List[RecommendationRule] = field(default_factory=list)
    recommendations: List[Recommendation] = field(default_factory=list)
    evidence: List[EvidenceBundle] = field(default_factory=list)
    insights: List[InsightView] = field(default_factory=list)
    market_opportunities: List[MarketOpportunity] = field(default_factory=list)
    product_opportunities: List[ProductOpportunity] = field(default_factory=list)
    action_items: List[ActionItem] = field(default_factory=list)
    opportunity_summary: Mapping[str, Any] = field(default_factory=dict)

    def records(self, name: str) -> List[Dict[str, Any]]:
        value = getattr(self, name)
        if value is None:
            return []
        if isinstance(value, list):
            return [item.to_dict() if hasattr(item, "to_dict") else _json_value(item) for item in value]
        return [value.to_dict() if hasattr(value, "to_dict") else _json_value(value)]


@dataclass
class CrossBorderAnalysisBundle:
    legacy: Any
    artifacts: AnalysisArtifacts

    @property
    def context(self):
        return self.legacy.context

    @property
    def results(self):
        return self.legacy.results

    @property
    def generated_at(self):
        return self.legacy.generated_at

    @property
    def metadata(self):
        return self.legacy.metadata

    @property
    def recommendations(self):
        if self.artifacts.recommendations:
            records = []
            for item in self.artifacts.recommendations:
                record = item.to_dict()
                record.update({"title": item.rationale, "level": item.priority})
                records.append(record)
            return records
        return self.legacy.recommendations

    @recommendations.setter
    def recommendations(self, value):
        self.legacy.recommendations = value

    @property
    def evidence(self):
        return self.legacy.evidence

    def status_frame(self):
        return self.legacy.status_frame()

    def evidence_frame(self):
        return self.legacy.evidence_frame()
