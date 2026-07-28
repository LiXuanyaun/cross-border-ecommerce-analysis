from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")
ApiStatus = Literal["SUCCESS", "PARTIAL", "SKIPPED", "FAILED", "FATAL"]


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


class WorkItemPatch(BaseModel):
    workflow_status: Literal["TODO", "IN_PROGRESS", "COMPLETED", "REVIEWED", "CLOSED"]
    owner: str = ""
    deadline: str | None = None
    result_note: str = ""
    review_result: str = ""
    close_reason: str = ""
    closed_by: str = ""


class AgentSessionRequest(BaseModel):
    dataset_id: str = "demo-all"


class AgentRunRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    dataset_id: str = "demo-all"
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
    distribution: dict[str, Any] | None = None
    tracking_exceptions: list[dict[str, Any]] | None = None


def safe_value(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value
