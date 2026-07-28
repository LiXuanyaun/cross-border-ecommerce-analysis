from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..app_state import runtime


router = APIRouter(prefix="/api/v1")


@router.get("/reports/{dataset_id}/{report_format}")
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
