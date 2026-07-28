from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


ACTIVE_STATUSES = {"TODO", "IN_PROGRESS", "COMPLETED", "REVIEWED", "CLOSED"}


def normalize_work_item_patch(payload: dict[str, Any]) -> dict[str, Any]:
    status = str(payload.get("workflow_status") or "").strip().upper()
    if status not in ACTIVE_STATUSES:
        raise ValueError("任务状态必须是 TODO、IN_PROGRESS、COMPLETED、REVIEWED 或 CLOSED")

    normalized = {
        "workflow_status": status,
        "owner": str(payload.get("owner") or "").strip(),
        "deadline": payload.get("deadline") or payload.get("due_date"),
        "result_note": str(payload.get("result_note") or "").strip(),
        "review_result": str(payload.get("review_result") or "").strip(),
        "close_reason": str(payload.get("close_reason") or "").strip(),
        "closed_by": str(payload.get("closed_by") or "").strip(),
        "closed_at": payload.get("closed_at"),
    }
    if normalized["deadline"] is not None:
        normalized["deadline"] = str(normalized["deadline"]).strip() or None

    if status == "IN_PROGRESS":
        if not normalized["owner"]:
            raise ValueError("任务进入处理中必须填写负责人")
        if not normalized["deadline"]:
            raise ValueError("任务进入处理中必须填写截止日期")
    if status == "COMPLETED" and not normalized["result_note"]:
        raise ValueError("任务标记已完成必须填写处理结果")
    if status == "REVIEWED" and not normalized["review_result"]:
        raise ValueError("任务标记已复盘必须填写复盘结论")
    if status == "CLOSED":
        if not normalized["close_reason"]:
            raise ValueError("关闭任务必须填写关闭原因")
        if not normalized["closed_by"]:
            raise ValueError("关闭任务必须填写关闭人")
        if not normalized["closed_at"]:
            normalized["closed_at"] = datetime.now(timezone.utc).isoformat()

    return normalized
