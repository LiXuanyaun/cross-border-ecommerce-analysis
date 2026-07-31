from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field


T = TypeVar("T")
ApiStatus = Literal["SUCCESS", "PARTIAL", "SKIPPED", "FAILED", "FATAL"]
DataState = Literal[
    "READY", "EMPTY", "OUT_OF_RANGE", "INSUFFICIENT_DATA", "INCOMPLETE_PERIOD", "FAILED", "FATAL",
]


class ApiMeta(BaseModel):
    dataset_id: str | None = None
    scope_id: str | None = None
    generated_at: str | None = None
    quality_rating: str | None = None
    app_mode: str = "demo"


class ApiEnvelope(BaseModel, Generic[T]):
    status: ApiStatus = "SUCCESS"
    data: T
    meta: ApiMeta = Field(default_factory=ApiMeta)
    limitations: list[str] = Field(default_factory=list)


class AvailablePeriod(BaseModel):
    start: str
    end: str
    row_count: int


class FactCapability(BaseModel):
    fact: Literal["orders", "advertising", "refunds", "logistics"]
    topics: list[str]
    state: DataState
    source_table: str
    date_field: str
    available_periods: list[AvailablePeriod]
    recommended_period: dict[str, str] | None = None
    requested_period: dict[str, str] | None = None
    row_count: int
    missing_fields: list[str]
    quality_state: str
    simulation_state: Literal["ACTUAL", "SIMULATED", "MIXED"]
    recommendation_policy: str
    limitations: list[str]


class DatasetCapability(BaseModel):
    dataset_id: str
    contract_version: Literal["1.0.0"]
    facts: dict[str, FactCapability]


class VisualizationField(BaseModel):
    field: str
    label: str
    format: str


class VisualizationContract(BaseModel):
    id: str
    type: Literal["line", "bar", "pie"]
    title: str
    dimension: VisualizationField
    series: list[VisualizationField]
    rows: list[dict[str, Any]]


class TableContract(BaseModel):
    columns: list[VisualizationField]
    rows: list[dict[str, Any]]
    pagination: dict[str, int]


class TopicEvidenceContract(BaseModel):
    contract_version: Literal["topic-evidence.v1"]
    id: str
    metric: str
    value: float | int | None = None
    unit: str = ""
    claim: str
    formula: str
    sample_size: int | None = None
    confidence: str
    source_fields: list[str] = Field(default_factory=list)
    period: dict[str, str]
    filters: dict[str, Any] = Field(default_factory=dict)
    quality_state: str
    limitations: list[str] = Field(default_factory=list)


class TopicAiPayload(BaseModel):
    findings: list[dict[str, Any]]
    evidence: list[TopicEvidenceContract]
    actions: list[dict[str, Any]]


class TopicResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    topic: str
    summary: str
    ai: TopicAiPayload
    data_state: DataState = "READY"
    available_periods: list[AvailablePeriod] = Field(default_factory=list)
    recommended_period: dict[str, str] | None = None
    requested_period: dict[str, str] | None = None
    visualizations: list[VisualizationContract] = Field(default_factory=list)
    table: TableContract | None = None


class WorkItemPatch(BaseModel):
    workflow_status: Literal["TODO", "IN_PROGRESS", "COMPLETED", "REVIEWED", "CLOSED"]
    owner: str = ""
    deadline: str | None = None
    result_note: str = ""
    review_result: str = ""
    close_reason: str = ""
    closed_by: str = ""


class AgentSessionRequest(BaseModel):
    dataset_id: str


class AgentRunRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    dataset_id: str
    start: str | None = None
    end: str | None = None
    market: str | None = None
    category: str | None = None


class ProviderStatus(BaseModel):
    configured: bool
    source: str
    provider_name: str | None = None
    model: str | None = None
    wire_api: str | None = None
    ccswitch_available: bool = False
    message: str


class BusinessDataset(BaseModel):
    dataset_id: str
    name: str
    imported_at: str
    is_simulated: bool
    source_label: str


class BusinessMetric(BaseModel):
    id: str
    label: str
    value: float | int | None
    format: Literal["currency", "integer", "percent", "decimal", "days"]
    formula: str
    currency: str | None = None
    evidence_id: str


class BusinessEvidence(BaseModel):
    evidence_id: str
    metric_id: str
    metric: str
    value: float | int | None
    formula: str
    source_table: str
    period: dict[str, str]
    comparison_period: dict[str, str] | None = None
    threshold: str | None = None
    sample_size: int
    record_keys: list[str]
    limitations: list[str]


class BusinessAnomaly(BaseModel):
    id: str
    rule_id: str
    rule_version: str
    title: str
    entity: str
    status: str
    current_value: float | int | None
    comparison_value: float | int | None
    change_rate: float | None
    threshold: str
    reason: str
    recommendation: str
    evidence_ids: list[str]
    limitations: list[str]


class BusinessTopicData(BaseModel):
    topic: Literal["advertising", "returns", "logistics"]
    dataset_id: str
    scope_id: str
    period: dict[str, str]
    data_state: DataState
    available_periods: list[dict[str, str]]
    recommended_period: dict[str, str]
    filters: dict[str, Any]
    filter_options: dict[str, list[str]]
    data_source: dict[str, Any]
    quality: dict[str, Any]
    metrics: list[BusinessMetric]
    trend: dict[str, Any]
    ranking: dict[str, Any]
    anomalies: list[BusinessAnomaly]
    causes: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    evidence: list[BusinessEvidence]
    details: list[dict[str, Any]]
    pagination: dict[str, int] = Field(default_factory=dict)
    distribution: dict[str, Any] | None = None
    tracking_exceptions: list[dict[str, Any]] | None = None
    visualizations: list[VisualizationContract] = Field(default_factory=list)
    table: TableContract | None = None


def safe_value(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value
