from __future__ import annotations

from typing import Any

from .agent import AgentManager
from .runtime import AnalyticsRuntime


runtime = AnalyticsRuntime()
agent = AgentManager(runtime)


def envelope(data: Any, bundle=None, dataset_id: str | None = None, limitations: list[str] | None = None):
    meta = {"app_mode": runtime.app_mode}
    if bundle is not None and dataset_id:
        meta.update(runtime.meta(bundle, dataset_id))
    return {"status": "SUCCESS", "data": data, "meta": meta, "limitations": limitations or []}
