from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..app_state import envelope, runtime
from ..schemas import ApiEnvelope, BusinessDataset, BusinessTopicData


router = APIRouter(prefix="/api/v1/business", tags=["multi-business"])


@router.get("/datasets", response_model=ApiEnvelope[list[BusinessDataset]])
def business_datasets():
    return envelope(runtime.multi_business_presenter.datasets())


@router.get("/{topic}", response_model=ApiEnvelope[BusinessTopicData])
def business_topic(
    topic: str,
    dataset_id: str,
    start: str | None = None,
    end: str | None = None,
    country: str | None = None,
    channel: str | None = None,
    platform: str | None = None,
    campaign_id: str | None = None,
    category: str | None = None,
    return_reason: str | None = None,
    carrier_id: str | None = None,
    region: str | None = None,
):
    try:
        data = runtime.multi_business_presenter.present(
            topic,
            dataset_id,
            start=start,
            end=end,
            country=country,
            channel=channel,
            platform=platform,
            campaign_id=campaign_id,
            category=category,
            return_reason=return_reason,
            carrier_id=carrier_id,
            region=region,
        )
    except KeyError:
        raise HTTPException(404, "数据集没有可用的多业务事实，请先导入 AdventureWorks 扩展数据")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return envelope(data, dataset_id=dataset_id, scope_id=data["scope_id"], limitations=data["quality"]["limitations"])
