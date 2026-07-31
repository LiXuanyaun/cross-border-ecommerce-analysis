from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..app_state import envelope, runtime
from ..schemas import ApiEnvelope, DatasetCapability


router = APIRouter(prefix="/api/v1")


@router.get("/datasets", response_model=ApiEnvelope[list[dict[str, Any]]])
def datasets():
    return envelope(runtime.datasets())


@router.get("/datasets/{dataset_id}", response_model=ApiEnvelope[dict[str, Any]])
def dataset_detail(dataset_id: str):
    try:
        data, bundle = runtime.dataset_detail(dataset_id)
    except KeyError:
        raise HTTPException(404, "数据集不存在")
    return envelope(data, bundle, dataset_id)


@router.get("/datasets/{dataset_id}/capabilities", response_model=ApiEnvelope[DatasetCapability])
def dataset_capabilities(
    dataset_id: str,
    fact: str | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
):
    try:
        data = runtime.dataset_capabilities(dataset_id, fact=fact, start=start, end=end)
    except KeyError:
        raise HTTPException(404, "数据集不存在")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return envelope(data, dataset_id=dataset_id)


@router.post("/datasets/{dataset_id}/archive")
def archive_dataset(dataset_id: str):
    try:
        archived = runtime.archive_dataset(dataset_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except KeyError:
        raise HTTPException(404, "数据集不存在")
    if not archived:
        raise HTTPException(404, "数据集不存在或已归档")
    return envelope({"dataset_id": dataset_id, "status": "ARCHIVED"})
