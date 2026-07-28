from __future__ import annotations

from typing import Any
import csv
import io

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from ..app_state import envelope, runtime
from ..schemas import ApiEnvelope


router = APIRouter(prefix="/api/v1")


@router.get("/overview", response_model=ApiEnvelope[dict[str, Any]])
def get_overview(dataset_id: str = "demo-all", start: str | None = None, end: str | None = None):
    try:
        data, bundle = runtime.overview(dataset_id, start, end)
    except KeyError:
        raise HTTPException(404, "数据集不存在")
    return envelope(data, bundle, dataset_id)


@router.get("/topics/{topic}", response_model=ApiEnvelope[dict[str, Any]])
def get_topic(
    topic: str,
    dataset_id: str = "demo-all",
    start: str | None = None,
    end: str | None = None,
    market: str | None = None,
    category: str | None = None,
    search: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=5, le=100),
):
    try:
        data, bundle = runtime.topic(dataset_id, topic, start, end, market, category, search, page, page_size)
    except KeyError:
        raise HTTPException(404, "分析主题或数据集不存在")
    return envelope(data, bundle, dataset_id)


@router.get("/topics/{topic}/export")
def export_topic_details(
    topic: str,
    dataset_id: str = "demo-all",
    start: str | None = None,
    end: str | None = None,
    market: str | None = None,
    category: str | None = None,
    search: str = "",
):
    try:
        data, _ = runtime.topic_export(dataset_id, topic, start, end, market, category, search)
    except KeyError:
        raise HTTPException(404, "分析主题或数据集不存在")
    columns = data["columns"]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([column["label"] for column in columns])
    for row in data["rows"]:
        writer.writerow([row.get(column["key"]) for column in columns])
    content = "\ufeff" + output.getvalue()
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="{}-details.csv"'.format(topic)},
    )
