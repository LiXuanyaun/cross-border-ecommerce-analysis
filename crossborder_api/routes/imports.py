from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from autoclean.analytics import SQLiteStorageError
from autoclean.analytics.io import FatalError

from ..app_state import envelope, runtime
from ..import_capacity import IMPORT_CAPACITY, format_bytes
from ..import_preview import UploadedFilePayload, build_import_preview, load_uploaded_tabular
from ..import_staging import ImportStagingStore


router = APIRouter(prefix="/api/v1")
staging_store = ImportStagingStore()


@router.post("/imports/adventureworks/preview")
def adventureworks_preview(directory: str = Form(...)):
    try:
        return envelope(runtime.multi_business_import_service.preview_directory(directory))
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc))


@router.post("/imports/adventureworks")
def adventureworks_import(directory: str = Form(...)):
    try:
        result = runtime.multi_business_import_service.import_directory(directory)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    runtime.clear_analysis_cache()
    return envelope(result, dataset_id=result.get("dataset_id"))


@router.post("/imports/preview")
async def import_preview(
    files: list[UploadFile] = File(...),
    selected_sheets_json: str | None = Form(None),
):
    if not files:
        raise HTTPException(400, "请选择至少一个 CSV 或 XLSX 文件")
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
    total_bytes = 0
    for file in files:
        content = await file.read()
        if not content:
            raise HTTPException(400, "{} 是空文件".format(file.filename or "上传文件"))
        if len(content) > IMPORT_CAPACITY.max_file_bytes:
            raise HTTPException(400, "{} 大小为 {}，超过单文件上限 {}".format(
                file.filename or "上传文件", format_bytes(len(content)),
                format_bytes(IMPORT_CAPACITY.max_file_bytes),
            ))
        total_bytes += len(content)
        if total_bytes > IMPORT_CAPACITY.max_task_bytes:
            raise HTTPException(400, "当前批次大小为 {}，超过单任务上限 {}；请拆分批次或调整配置".format(
                format_bytes(total_bytes), format_bytes(IMPORT_CAPACITY.max_task_bytes),
            ))
        filename = file.filename or "uploaded.csv"
        payloads.append(UploadedFilePayload(
            filename=filename,
            content=content,
            selected_sheet=selected_sheets.get(filename),
        ))
    preview = build_import_preview(payloads)
    staged = staging_store.stage(payloads)
    preview.update({"preview_id": staged.preview_id, "expires_at": staged.expires_at})
    return envelope(preview)


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
    preview_id: str | None = Form(None),
    target_dataset_id: str | None = Form(None),
):
    uploads = list(files or [])
    if file is not None:
        uploads.append(file)
    if not uploads and not preview_id:
        raise HTTPException(400, "请选择至少一个 CSV 或 XLSX 文件")
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
        total_bytes = 0
        if preview_id:
            try:
                staged_payloads = staging_store.load(preview_id)
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(400, str(exc))
        else:
            staged_payloads = []
            for upload in uploads:
                filename = upload.filename or "uploaded.csv"
                content = await upload.read()
                if not content:
                    raise HTTPException(400, "{} 是空文件".format(filename))
                if len(content) > IMPORT_CAPACITY.max_file_bytes:
                    raise HTTPException(400, "{} 大小为 {}，超过单文件上限 {}".format(
                        filename, format_bytes(len(content)), format_bytes(IMPORT_CAPACITY.max_file_bytes),
                    ))
                total_bytes += len(content)
                if total_bytes > IMPORT_CAPACITY.max_task_bytes:
                    raise HTTPException(400, "当前批次大小为 {}，超过单任务上限 {}；请拆分批次或调整配置".format(
                        format_bytes(total_bytes), format_bytes(IMPORT_CAPACITY.max_task_bytes),
                    ))
                staged_payloads.append(UploadedFilePayload(filename, content))
        for payload in staged_payloads:
            sheet = selected_sheets.get(payload.filename) or (selected_sheet if len(staged_payloads) == 1 else payload.selected_sheet)
            loaded = load_uploaded_tabular(UploadedFilePayload(payload.filename, payload.content, sheet))
            loaded_files.append((loaded, "src_{}".format(loaded.metadata["sha256"][:12])))
        result = runtime.import_datasets(
            loaded_files,
            mapping=mapping,
            dataset_name=dataset_name,
            data_grain=data_grain,
            amount_semantic=amount_semantic,
            source_currency=source_currency,
            target_currency=target_currency,
            target_dataset_id=target_dataset_id.strip() if target_dataset_id and target_dataset_id.strip() else None,
        )
    except (FatalError, SQLiteStorageError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    if preview_id and result.get("status") == "READY":
        staging_store.delete(preview_id)
    return envelope(result, dataset_id=result.get("dataset_id"))
