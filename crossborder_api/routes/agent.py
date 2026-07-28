from __future__ import annotations

from typing import Any
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..app_state import agent, envelope, runtime
from ..schemas import AgentRunRequest, AgentSessionRequest, ApiEnvelope


router = APIRouter(prefix="/api/v1")


@router.get("/agent/status", response_model=ApiEnvelope[dict[str, Any]])
def provider_status():
    return envelope(agent.provider.safe_status())


@router.post("/agent/import-ccswitch")
def import_ccswitch():
    try:
        return envelope(agent.provider.import_ccswitch())
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc))


@router.post("/agent/sessions", response_model=ApiEnvelope[dict[str, Any]])
def create_agent_session(payload: AgentSessionRequest):
    try:
        runtime.scenario(payload.dataset_id)
    except KeyError:
        raise HTTPException(404, "数据集不存在")
    return envelope(agent.create_session(payload.dataset_id))


@router.post("/agent/sessions/{session_id}/runs", response_model=ApiEnvelope[dict[str, Any]])
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


@router.get("/agent/runs/{run_id}/events")
async def agent_events(run_id: str):
    async def stream():
        async for event in agent.events(run_id):
            yield "data: {}\n\n".format(json.dumps(event, ensure_ascii=False))
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
