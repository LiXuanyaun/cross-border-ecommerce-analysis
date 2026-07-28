from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..app_state import envelope, runtime
from ..schemas import ApiEnvelope


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
