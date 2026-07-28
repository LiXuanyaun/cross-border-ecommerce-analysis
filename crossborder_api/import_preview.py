from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
import hashlib

import pandas as pd

from autoclean.analytics import LoadedDataset, ValidationIssue, load_tabular, prepare_context
from autoclean.analytics.io import FatalError

from crossborder_analytics.contract import ECOMMERCE_CONTRACT, ECOMMERCE_IMPORT_CONTRACT, domain_issues
from crossborder_analytics.multibusiness_import import classify_business_file, preview_business_payload


REQUIRED_FIELDS = {"order_id", "order_date", "total_amount"}


@dataclass(frozen=True)
class UploadedFilePayload:
    filename: str
    content: bytes
    selected_sheet: str | None = None


def load_uploaded_tabular(file: UploadedFilePayload) -> LoadedDataset:
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".xlsx", ".xls"} or not file.selected_sheet:
        return load_tabular(BytesIO(file.content), filename=file.filename)
    try:
        frame = pd.read_excel(
            BytesIO(file.content),
            sheet_name=file.selected_sheet,
            engine="openpyxl" if suffix == ".xlsx" else None,
        )
    except Exception as exc:
        raise FatalError("无法读取Excel工作表 {}: {}".format(file.selected_sheet, exc)) from exc
    return LoadedDataset(
        data=frame,
        metadata={
            "filename": file.filename,
            "source_location": None,
            "sha256": hashlib.sha256(file.content).hexdigest(),
            "file_size": len(file.content),
            "rows": len(frame),
            "columns": len(frame.columns),
            "column_names": frame.columns.tolist(),
            "encoding": None,
            "sheet_name": file.selected_sheet,
        },
    )


def _clean(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value


def _issue_dict(issue: ValidationIssue, filename: str | None = None) -> dict[str, Any]:
    payload = issue.to_dict()
    if filename:
        payload.setdefault("details", {})
        payload["details"] = {**payload["details"], "filename": filename}
    return _clean(payload)


def _normalized(text: str) -> str:
    return "".join(str(text).strip().lower().replace("_", "").replace("-", "").split())


def _mapping_confidence(standard_field: str, source_field: str) -> float:
    spec = ECOMMERCE_CONTRACT.field(standard_field)
    if spec is None:
        return 0.0
    source_key = _normalized(source_field)
    if source_key == _normalized(spec.name):
        return 1.0
    if source_key in {_normalized(alias) for alias in spec.aliases}:
        return 0.92
    return 0.68


def _field_mappings(context) -> list[dict[str, Any]]:
    rows = []
    for spec in ECOMMERCE_CONTRACT.fields:
        source = context.field_mapping.get(spec.name)
        rows.append({
            "standard_field": spec.name,
            "source_field": source,
            "dtype": spec.dtype,
            "required": spec.required,
            "nullable": spec.nullable,
            "semantic": spec.semantic,
            "confidence": _mapping_confidence(spec.name, source) if source else 0.0,
            "requires_confirmation": bool(source and _mapping_confidence(spec.name, source) < 0.85),
            "status": "MAPPED" if source else ("MISSING_REQUIRED" if spec.required else "UNMAPPED"),
            "sample_values": _sample_values(context.raw_data, source),
        })
    return rows


def _sample_values(frame: pd.DataFrame, source_field: str | None) -> list[Any]:
    if not source_field or source_field not in frame:
        return []
    values = frame[source_field].dropna().astype(str).head(3).tolist()
    return values


def _sheet_names(filename: str, content: bytes) -> list[str]:
    if Path(filename).suffix.lower() not in {".xlsx", ".xls"}:
        return []
    try:
        return list(pd.ExcelFile(BytesIO(content)).sheet_names)
    except Exception:
        return []


def _preview_file(file: UploadedFilePayload) -> tuple[dict[str, Any], Any | None]:
    try:
        loaded = load_uploaded_tabular(file)
        context = prepare_context(
            loaded,
            ECOMMERCE_IMPORT_CONTRACT,
            semantic_overrides={"profit_amount": "order_profit_amount"},
        )
        context.issues.extend(domain_issues(context.analysis_data))
    except FatalError as exc:
        digest = hashlib.sha256(file.content).hexdigest()
        metadata = {
            "filename": file.filename,
            "sha256": digest,
            "file_size": len(file.content),
            "rows": 0,
            "columns": 0,
            "column_names": [],
            "encoding": None,
        }
        issue = ValidationIssue("FATAL", "FILE_READ_FAILED", str(exc))
        return {
            "filename": file.filename,
            "source_file_id": "src_{}".format(digest[:12]),
            "status": "FAILED",
            "metadata": metadata,
            "sheets": _sheet_names(file.filename, file.content),
            "selected_sheet": None,
            "columns": [],
            "field_mappings": [],
            "issues": [_issue_dict(issue, file.filename)],
            "capabilities": [],
        }, None

    metadata = dict(loaded.metadata)
    digest = str(metadata.get("sha256") or hashlib.sha256(file.content).hexdigest())
    issues = [_issue_dict(issue, file.filename) for issue in context.issues]
    capabilities = _capabilities(context)
    status = "BLOCKED" if context.fatal_issues else "READY_FOR_CONFIRMATION"
    sheets = _sheet_names(file.filename, file.content)
    return _clean({
        "filename": file.filename,
        "source_file_id": "src_{}".format(digest[:12]),
        "status": status,
        "metadata": metadata,
        "sheets": sheets,
        "selected_sheet": file.selected_sheet or (sheets[0] if sheets else None),
        "columns": list(metadata.get("column_names", [])),
        "field_mappings": _field_mappings(context),
        "issues": issues,
        "capabilities": capabilities,
    }), context


def _capabilities(context) -> list[dict[str, Any]]:
    mapped = set(context.field_mapping)
    specs = [
        ("overview", "经营总览", REQUIRED_FIELDS),
        ("market", "市场分析", {"country", "region"}),
        ("product", "商品分析", {"product_id"}),
        ("customer", "客户分析", {"customer_id"}),
        ("profit", "利润分析", {"profit_amount"}),
        ("returns", "退货分析", {"returned"}),
    ]
    output = []
    for capability_id, name, required in specs:
        if capability_id == "overview":
            available = REQUIRED_FIELDS.issubset(mapped)
        else:
            available = bool(required & mapped)
        output.append({
            "id": capability_id,
            "name": name,
            "status": "FULL" if available else "DISABLED",
            "reason": "字段满足当前分析要求" if available else "缺少 {}".format(" / ".join(sorted(required))),
        })
    return output


def build_import_preview(files: list[UploadedFilePayload]) -> dict[str, Any]:
    classifications = [classify_business_file(file.filename, file.content) for file in files]
    if any(item["file_type"] != "unknown" for item in classifications):
        previews = [preview_business_payload(file.filename, file.content) for file in files]
        fatal = any(issue["severity"] == "FATAL" for item in previews for issue in item["issues"])
        return _clean({
            "status": "BLOCKED" if fatal else "READY_FOR_MAPPING_CONFIRMATION",
            "file_count": len(previews),
            "total_rows": sum(int(item.get("row_count") or 0) for item in previews),
            "files": previews,
            "batch_issues": [{
                "severity": "WARNING",
                "code": "ASSOCIATION_VALIDATED_ON_COMMIT",
                "message": "上传文件的关联成功率将在与目标 AdventureWorks 订单数据集绑定后再次验证",
            }],
            "is_simulated": any(item.get("is_simulated") for item in previews),
            "next_step": "确认文件类型、字段、粒度和模拟数据标识后绑定订单数据集",
        })
    previews: list[dict[str, Any]] = []
    contexts = []
    for file in files:
        preview, context = _preview_file(file)
        previews.append(preview)
        if context is not None:
            contexts.append((preview, context))

    batch_issues = _batch_issues(previews, contexts)
    fatal = any(issue["severity"].upper() == "FATAL" for preview in previews for issue in preview["issues"])
    fatal = fatal or any(issue["severity"].upper() == "FATAL" for issue in batch_issues)
    status = "BLOCKED" if fatal else "READY_FOR_MAPPING_CONFIRMATION"
    return _clean({
        "status": status,
        "file_count": len(previews),
        "total_rows": sum(int(item["metadata"].get("rows") or 0) for item in previews),
        "files": previews,
        "batch_issues": batch_issues,
        "next_step": "修复阻断问题后重新上传" if fatal else "确认字段映射、数据粒度、金额语义和币种后可入库",
    })


def _batch_issues(previews: list[dict[str, Any]], contexts: list[tuple[dict[str, Any], Any]]) -> list[dict[str, Any]]:
    issues: list[ValidationIssue] = []
    if len(previews) <= 1:
        return []

    column_sets = {item["filename"]: set(item["columns"]) for item in previews if item["columns"]}
    if column_sets:
        first_name, first_columns = next(iter(column_sets.items()))
        for filename, columns in list(column_sets.items())[1:]:
            missing = sorted(first_columns - columns)
            extra = sorted(columns - first_columns)
            if missing or extra:
                issues.append(ValidationIssue(
                    "FATAL",
                    "FIELD_SET_MISMATCH",
                    "文件字段不一致，无法按同一映射合并导入",
                    details={
                        "baseline_file": first_name,
                        "filename": filename,
                        "missing_columns": missing,
                        "extra_columns": extra,
                    },
                ))

    hashes: dict[str, list[str]] = {}
    for item in previews:
        digest = str(item["metadata"].get("sha256") or "")
        if digest:
            hashes.setdefault(digest, []).append(item["filename"])
    for filenames in hashes.values():
        if len(filenames) > 1:
            issues.append(ValidationIssue(
                "WARNING",
                "DUPLICATE_FILE_CONTENT",
                "同一批次包含内容完全相同的文件",
                details={"filenames": filenames},
            ))

    order_rows = []
    for preview, context in contexts:
        source = context.field_mapping.get("order_id")
        if not source or source not in context.raw_data:
            continue
        frame = context.raw_data[[source]].copy()
        frame.columns = ["order_id"]
        frame["filename"] = preview["filename"]
        order_rows.append(frame)
    if order_rows:
        combined = pd.concat(order_rows, ignore_index=True)
        duplicated = combined["order_id"].notna() & combined["order_id"].duplicated(keep=False)
        duplicate_count = int(duplicated.sum())
        if duplicate_count:
            filenames = sorted(combined.loc[duplicated, "filename"].astype(str).unique().tolist())
            issues.append(ValidationIssue(
                "WARNING",
                "CROSS_FILE_DUPLICATE_ORDER_ID",
                "跨文件存在重复订单号，必须确认订单商品粒度或修复订单粒度唯一键",
                field="order_id",
                row_count=duplicate_count,
                details={"filenames": filenames},
            ))

    return [_issue_dict(issue) for issue in issues]
