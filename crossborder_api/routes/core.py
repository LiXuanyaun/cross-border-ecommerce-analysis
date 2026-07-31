from __future__ import annotations

from fastapi import APIRouter

from ..app_state import envelope, runtime
from ..build_identity import current_build_fingerprint
from ..runtime import ROOT


router = APIRouter(prefix="/api/v1")
BUILD_FINGERPRINT = current_build_fingerprint(ROOT)


@router.get("/health")
def health():
    return {
        "status": "ok",
        "mode": runtime.app_mode,
        "workspace_root": str(ROOT.resolve()),
        "build_fingerprint": BUILD_FINGERPRINT,
        "unified_dataset_id": runtime.unified_dataset_id(),
    }


@router.get("/app/bootstrap")
def bootstrap():
    default_dataset_id = runtime.unified_dataset_id() if runtime.app_mode == "private" else None
    capability_dataset_id = default_dataset_id or "demo-all"
    start, end = runtime.date_bounds(capability_dataset_id)
    capability = runtime.dataset_capabilities(capability_dataset_id, fact="orders")
    recommended_period = capability["facts"]["orders"]["recommended_period"]
    return envelope({
        "app_name": "CrossBorder",
        "navigation": [
            {"id": "overview", "label": "经营总览", "path": "/"},
            {"id": "analytics", "label": "专题分析", "path": "/analytics"},
            {"id": "business", "label": "多业务分析", "path": "/business/advertising"},
            {"id": "data", "label": "数据中心", "path": "/data"},
            {"id": "ai", "label": "AI分析师", "path": "/ai"},
        ],
        "workspace": {"id": "default", "name": "默认工作空间"},
        "default_dataset_id": default_dataset_id,
        "date_bounds": {"start": start, "end": end},
        "recommended_period": recommended_period,
        "period_source": "AUTO",
        "capability_contract_version": capability["contract_version"],
        "mode": runtime.app_mode,
    })
