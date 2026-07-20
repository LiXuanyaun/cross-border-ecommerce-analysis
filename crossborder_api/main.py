from __future__ import annotations

from pathlib import Path
from typing import Any
import csv
import io
import json
import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agent import AgentManager
from .runtime import AnalyticsRuntime, ROOT, SCENARIOS
from .schemas import AgentRunRequest, AgentSessionRequest, WorkItemPatch


app = FastAPI(title="CrossBorder AI Analytics API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
runtime = AnalyticsRuntime()
agent = AgentManager(runtime)


def envelope(data: Any, bundle=None, dataset_id: str | None = None, limitations: list[str] | None = None):
    meta = {"app_mode": runtime.app_mode}
    if bundle is not None and dataset_id:
        meta.update(runtime.meta(bundle, dataset_id))
    return {"status": "SUCCESS", "data": data, "meta": meta, "limitations": limitations or []}


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "mode": runtime.app_mode}


@app.get("/api/v1/app/bootstrap")
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


@app.get("/api/v1/overview")
def get_overview(dataset_id: str = "demo-all", start: str | None = None, end: str | None = None):
    try:
        data, bundle = runtime.overview(dataset_id, start, end)
    except KeyError:
        raise HTTPException(404, "数据集不存在")
    return envelope(data, bundle, dataset_id)


@app.get("/api/v1/topics/{topic}")
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


@app.get("/api/v1/topics/{topic}/export")
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


@app.get("/api/v1/datasets")
def datasets():
    return envelope(runtime.datasets())


@app.get("/api/v1/datasets/{dataset_id}")
def dataset_detail(dataset_id: str):
    try:
        data, bundle = runtime.dataset_detail(dataset_id)
    except KeyError:
        raise HTTPException(404, "数据集不存在")
    return envelope(data, bundle, dataset_id)


@app.patch("/api/v1/work-items/{item_id}")
def update_work_item(item_id: str, payload: WorkItemPatch):
    try:
        data = runtime.update_work_item(item_id, payload.model_dump())
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    return envelope(data)


@app.get("/api/v1/agent/status")
def provider_status():
    return envelope(agent.provider.safe_status())


@app.post("/api/v1/agent/import-ccswitch")
def import_ccswitch():
    try:
        return envelope(agent.provider.import_ccswitch())
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v1/agent/sessions")
def create_agent_session(payload: AgentSessionRequest):
    try:
        runtime.scenario(payload.dataset_id)
    except KeyError:
        raise HTTPException(404, "数据集不存在")
    return envelope(agent.create_session(payload.dataset_id))


@app.post("/api/v1/agent/sessions/{session_id}/runs")
async def start_agent_run(session_id: str, payload: AgentRunRequest):
    try:
        run_id = agent.start(session_id, payload.dataset_id, payload.question)
    except KeyError:
        raise HTTPException(404, "分析会话不存在")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return envelope({"run_id": run_id})


@app.get("/api/v1/agent/runs/{run_id}/events")
async def agent_events(run_id: str):
    async def stream():
        async for event in agent.events(run_id):
            yield "data: {}\n\n".format(json.dumps(event, ensure_ascii=False))
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/v1/reports/{dataset_id}/{report_format}")
def report(dataset_id: str, report_format: str):
    if report_format not in {"excel", "markdown", "docx", "manifest"}:
        raise HTTPException(400, "不支持的报告格式")
    try:
        path, temp = runtime.export(dataset_id, report_format)
    except KeyError:
        raise HTTPException(404, "数据集不存在")
    response = FileResponse(path, filename=path.name)
    response.background = _TemporaryCleanup(temp)
    return response


class _TemporaryCleanup:
    def __init__(self, temp) -> None:
        self.temp = temp

    async def __call__(self) -> None:
        self.temp.cleanup()


DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = DIST / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")


def run() -> None:
    import uvicorn
    uvicorn.run("crossborder_api.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
