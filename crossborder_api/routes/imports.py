from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from autoclean.analytics import SQLiteStorageError
from autoclean.analytics.io import FatalError

from ..app_state import envelope, runtime
from ..import_preview import UploadedFilePayload, build_import_preview, load_uploaded_tabular


router = APIRouter(prefix="/api/v1")


@router.post("/imports/preview")
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


@router.post("/imports")
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
