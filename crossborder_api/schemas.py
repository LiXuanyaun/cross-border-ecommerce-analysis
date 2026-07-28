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


def safe_value(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value
