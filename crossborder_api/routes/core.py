from __future__ import annotations

from fastapi import APIRouter

from ..app_state import envelope, runtime
from ..runtime import SCENARIOS


router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health():
    return {"status": "ok", "mode": runtime.app_mode}


@router.get("/app/bootstrap")
def bootstrap():
    start, end = runtime.date_bounds()
    return envelope({
        "app_name": "CrossBorder",
        "navigation": [
            {"id": "overview", "label": "经营总览", "path": "/"},
            {"id": "analytics", "label": "专题分析", "path": "/analytics"},
            {"id": "data", "label": "数据中心", "path": "/data"},
            {"id": "ai", "label": "AI分析师", "path": "/ai"},
        ],
        "workspace": {"id": "default", "name": "默认工作空间"},
        "default_dataset_id": SCENARIOS[0].dataset_id,
        "date_bounds": {"start": start, "end": end},
        "mode": runtime.app_mode,
    })
