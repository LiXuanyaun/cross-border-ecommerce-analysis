from __future__ import annotations

import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .app_state import agent, envelope, runtime
from .runtime import ROOT
from .routes import agent as agent_routes
from .routes import analytics, business, core, datasets, imports, maintenance, reports
from .telemetry import log_event


app = FastAPI(title="CrossBorder AI Analytics API", version="3.1.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


for router in (
    core.router, analytics.router, business.router, datasets.router, imports.router,
    maintenance.router, agent_routes.router, reports.router,
):
    app.include_router(router)


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
