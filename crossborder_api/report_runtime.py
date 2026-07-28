from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from crossborder_analytics.reporting import export_bundle


def export_scoped_bundle(runtime: Any, dataset_id: str, report_format: str, start: str | None,
                         end: str | None, market: str | None, category: str | None,
                         expected_scope_id: str | None = None) -> tuple[Path, TemporaryDirectory]:
    bundle = runtime.bundle(dataset_id, start, end, market, category)
    scope_id = bundle.metadata.get("scope_id")
    if not scope_id:
        raise RuntimeError("报告导出缺少 scope_id")
    if expected_scope_id and expected_scope_id != scope_id:
        raise ValueError("报告范围与当前页面 scope_id 不一致")
    temp = TemporaryDirectory(prefix="crossborder-report-")
    paths = export_bundle(bundle, Path(temp.name))
    return Path(paths[report_format]), temp
