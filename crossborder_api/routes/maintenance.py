from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from crossborder_analytics.phase2_storage import (
    DEFAULT_KEEP_LATEST_SCOPES,
    DEFAULT_MAX_ENTITY_ASSESSMENTS_PER_SCOPE,
)

from ..app_state import envelope, runtime
from ..schemas import ApiEnvelope, WorkItemPatch


router = APIRouter(prefix="/api/v1")


@router.patch("/work-items/{item_id}", response_model=ApiEnvelope[dict[str, Any]])
def update_work_item(item_id: str, payload: WorkItemPatch):
    try:
        data = runtime.update_work_item(item_id, payload.model_dump())
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return envelope(data)


@router.get("/scopes/capacity")
def scope_capacity():
    if runtime.dataset_service.database_path is None:
        raise HTTPException(503, "分析存储未配置")
    return envelope(runtime.dataset_service.artifact_store().capacity())


@router.post("/scopes/{scope_id}/archive")
def archive_scope(scope_id: str):
    if runtime.dataset_service.database_path is None:
        raise HTTPException(503, "分析存储未配置")
    archived = runtime.dataset_service.artifact_store().archive_scope(scope_id)
    if not archived:
        raise HTTPException(404, "分析范围不存在或正在计算")
    runtime.clear_analysis_cache()
    return envelope({"scope_id": scope_id, "status": "ARCHIVED"})


@router.delete("/scopes")
def cleanup_scopes(
    keep_latest: int = Query(DEFAULT_KEEP_LATEST_SCOPES, ge=0, le=500),
    ttl_days: int | None = Query(None, ge=0, le=3650),
    compact: bool = Query(True),
    clear_topic_cache: bool = Query(True),
    max_entity_assessments: int = Query(DEFAULT_MAX_ENTITY_ASSESSMENTS_PER_SCOPE, ge=0, le=100_000),
    keep_low_sample_assessments: bool = Query(False),
    purge_duplicate_datasets: bool = Query(True),
):
    if runtime.dataset_service.database_path is None:
        raise HTTPException(503, "分析存储未配置")
    store = runtime.dataset_service.artifact_store()
    purged_duplicate_datasets = []
    purged_dataset_scopes = []
    if purge_duplicate_datasets:
        purged_duplicate_datasets = runtime.dataset_service.database().purge_duplicate_ready_datasets()
        purged_dataset_scopes = store.cleanup_dataset_scopes(purged_duplicate_datasets)
    cleared_topic_cache_rows = store.clear_topic_detail_cache() if clear_topic_cache else 0
    trimmed_entity_assessments = store.trim_entity_assessments(
        max_per_scope=max_entity_assessments,
        keep_low_sample=keep_low_sample_assessments,
    )
    removed = store.maintenance_cleanup(
        keep_latest=keep_latest, ttl_days=ttl_days, compact=False,
    )
    compacted = store.compact() if compact and (
        removed or cleared_topic_cache_rows or trimmed_entity_assessments
        or purged_duplicate_datasets or purged_dataset_scopes
    ) else False
    runtime.clear_analysis_cache()
    return envelope({
        "removed_scope_ids": removed,
        "removed_count": len(removed),
        "keep_latest": keep_latest,
        "ttl_days": ttl_days,
        "compacted": compacted,
        "clear_topic_cache": clear_topic_cache,
        "cleared_topic_cache_rows": cleared_topic_cache_rows,
        "max_entity_assessments": max_entity_assessments,
        "keep_low_sample_assessments": keep_low_sample_assessments,
        "trimmed_entity_assessments": trimmed_entity_assessments,
        "purge_duplicate_datasets": purge_duplicate_datasets,
        "purged_duplicate_dataset_ids": purged_duplicate_datasets,
        "purged_dataset_scope_ids": purged_dataset_scopes,
    })
