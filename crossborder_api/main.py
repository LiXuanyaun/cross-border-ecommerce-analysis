from __future__ import annotations

from pathlib import Path
from typing import Any
import csv
import io
import json
import os
import time

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agent import AgentManager
from autoclean.analytics import SQLiteStorageError
from autoclean.analytics.io import FatalError
from crossborder_analytics.phase2_storage import (
    DEFAULT_KEEP_LATEST_SCOPES,
    DEFAULT_MAX_ENTITY_ASSESSMENTS_PER_SCOPE,
)

from .import_preview import UploadedFilePayload, build_import_preview, load_uploaded_tabular
from .runtime import AnalyticsRuntime, ROOT, SCENARIOS
from .schemas import AgentRunRequest, AgentSessionRequest, ApiEnvelope, WorkItemPatch
from .telemetry import log_event


app = FastAPI(title="CrossBorder AI Analytics API", version="3.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
runtime = AnalyticsRuntime()
agent = AgentManager(runtime)


@app.middleware("http")
async def request_log_middleware(request: Request, call_next):
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        log_event(
            "api_request",
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=elapsed_ms,
            dataset_id=request.query_params.get("dataset_id"),
            scope_id=request.query_params.get("scope_id"),
        )


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


@app.get("/api/v1/overview", response_model=ApiEnvelope[dict[str, Any]])
def get_overview(dataset_id: str = "demo-all", start: str | None = None, end: str | None = None):
    try:
        data, bundle = runtime.overview(dataset_id, start, end)
    except KeyError:
        raise HTTPException(404, "数据集不存在")
    return envelope(data, bundle, dataset_id)


@app.get("/api/v1/topics/{topic}", response_model=ApiEnvelope[dict[str, Any]])
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


@app.get("/api/v1/datasets", response_model=ApiEnvelope[list[dict[str, Any]]])
def datasets():
    return envelope(runtime.datasets())


@app.get("/api/v1/datasets/{dataset_id}", response_model=ApiEnvelope[dict[str, Any]])
def dataset_detail(dataset_id: str):
    try:
        data, bundle = runtime.dataset_detail(dataset_id)
    except KeyError:
        raise HTTPException(404, "数据集不存在")
    return envelope(data, bundle, dataset_id)


@app.post("/api/v1/datasets/{dataset_id}/archive")
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


@app.post("/api/v1/imports/preview")
async def import_preview(
    files: list[UploadFile] = File(...),
    selected_sheets_json: str | None = Form(None),
):
    if not files:
        raise HTTPException(400, "请选择至少一个 CSV 或 XLSX 文件")
    if len(files) > 20:
        raise HTTPException(400, "单次最多选择 20 个文件")
    selected_sheets: dict[str, str] = {}
    if selected_sheets_json:
        try:
            parsed = json.loads(selected_sheets_json)
            if not isinstance(parsed, dict):
                raise ValueError
            selected_sheets = {str(key): str(value) for key, value in parsed.items() if value}
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(400, "selected_sheets_json 必须是文件名到 Sheet 名的 JSON 对象")
    payloads: list[UploadedFilePayload] = []
    for file in files:
        content = await file.read()
        if not content:
            raise HTTPException(400, "{} 是空文件".format(file.filename or "上传文件"))
        if len(content) > 100 * 1024 * 1024:
            raise HTTPException(400, "{} 超过 100MB 上限".format(file.filename or "上传文件"))
        filename = file.filename or "uploaded.csv"
        payloads.append(UploadedFilePayload(
            filename=filename,
            content=content,
            selected_sheet=selected_sheets.get(filename),
        ))
    return envelope(build_import_preview(payloads))


@app.post("/api/v1/imports")
async def commit_import(
    files: list[UploadFile] | None = File(None),
    file: UploadFile | None = File(None),
    mapping_json: str = Form(...),
    dataset_name: str = Form(""),
    selected_sheet: str | None = Form(None),
    data_grain: str = Form(...),
    amount_semantic: str = Form(...),
    source_currency: str | None = Form(None),
    target_currency: str = Form("CNY"),
    selected_sheets_json: str | None = Form(None),
):
    uploads = list(files or [])
    if file is not None:
        uploads.append(file)
    if not uploads:
        raise HTTPException(400, "请选择至少一个 CSV 或 XLSX 文件")
    if len(uploads) > 20:
        raise HTTPException(400, "单次最多选择 20 个文件")
    try:
        mapping_payload = json.loads(mapping_json)
        if not isinstance(mapping_payload, dict):
            raise ValueError
        mapping = {
            str(standard): str(source)
            for standard, source in mapping_payload.items()
            if standard and source
        }
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(400, "mapping_json 必须是标准字段到源字段的 JSON 对象")
    source_currency = source_currency.strip().upper() if source_currency and source_currency.strip() else None
    target_currency = target_currency.strip().upper()
    if source_currency and (len(source_currency) != 3 or not source_currency.isalpha()):
        raise HTTPException(400, "源币种必须是三位字母代码")
    if len(target_currency) != 3 or not target_currency.isalpha():
        raise HTTPException(400, "目标币种必须是三位字母代码")
    selected_sheets = {}
    if selected_sheets_json:
        try:
            selected_sheets = json.loads(selected_sheets_json)
            if not isinstance(selected_sheets, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(400, "selected_sheets_json 必须是文件名到 Sheet 名的 JSON 对象")
    try:
        loaded_files = []
        for upload in uploads:
            filename = upload.filename or "uploaded.csv"
            content = await upload.read()
            if not content:
                raise HTTPException(400, "{} 是空文件".format(filename))
            if len(content) > 100 * 1024 * 1024:
                raise HTTPException(400, "{} 超过 100MB 上限".format(filename))
            sheet = selected_sheets.get(filename) or (selected_sheet if len(uploads) == 1 else None)
            loaded = load_uploaded_tabular(UploadedFilePayload(filename, content, sheet))
            loaded_files.append((loaded, "src_{}".format(loaded.metadata["sha256"][:12])))
        result = runtime.import_datasets(
            loaded_files,
            mapping=mapping,
            dataset_name=dataset_name,
            data_grain=data_grain,
            amount_semantic=amount_semantic,
            source_currency=source_currency,
            target_currency=target_currency,
        )
    except (FatalError, SQLiteStorageError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return envelope(result, dataset_id=result.get("dataset_id"))


@app.patch("/api/v1/work-items/{item_id}", response_model=ApiEnvelope[dict[str, Any]])
def update_work_item(item_id: str, payload: WorkItemPatch):
    try:
        data = runtime.update_work_item(item_id, payload.model_dump())
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return envelope(data)


@app.get("/api/v1/scopes/capacity")
def scope_capacity():
    if runtime.dataset_service.database_path is None:
        raise HTTPException(503, "分析存储未配置")
    return envelope(runtime.dataset_service.artifact_store().capacity())


@app.post("/api/v1/scopes/{scope_id}/archive")
def archive_scope(scope_id: str):
    if runtime.dataset_service.database_path is None:
        raise HTTPException(503, "分析存储未配置")
    archived = runtime.dataset_service.artifact_store().archive_scope(scope_id)
    if not archived:
        raise HTTPException(404, "分析范围不存在或正在计算")
    runtime.clear_analysis_cache()
    return envelope({"scope_id": scope_id, "status": "ARCHIVED"})


@app.delete("/api/v1/scopes")
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


@app.get("/api/v1/agent/status", response_model=ApiEnvelope[dict[str, Any]])
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


@app.post("/api/v1/agent/sessions", response_model=ApiEnvelope[dict[str, Any]])
def create_agent_session(payload: AgentSessionRequest):
    try:
        runtime.scenario(payload.dataset_id)
    except KeyError:
        raise HTTPException(404, "数据集不存在")
    return envelope(agent.create_session(payload.dataset_id))


@app.post("/api/v1/agent/sessions/{session_id}/runs", response_model=ApiEnvelope[dict[str, Any]])
async def start_agent_run(session_id: str, payload: AgentRunRequest):
    try:
        run_id = agent.start(
            session_id, payload.dataset_id, payload.question,
            payload.start, payload.end, payload.market, payload.category,
        )
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
def report(
    dataset_id: str,
    report_format: str,
    start: str | None = None,
    end: str | None = None,
    market: str | None = None,
    category: str | None = None,
    scope_id: str | None = None,
):
    if report_format not in {"excel", "markdown", "docx", "manifest"}:
        raise HTTPException(400, "不支持的报告格式")
    try:
        path, temp = runtime.export(dataset_id, report_format, start, end, market, category, scope_id)
    except KeyError:
        raise HTTPException(404, "数据集不存在")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
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
