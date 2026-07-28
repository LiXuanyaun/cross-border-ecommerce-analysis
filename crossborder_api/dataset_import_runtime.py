from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
import hashlib

import pandas as pd

from autoclean.analytics import ValidationIssue
from crossborder_analytics.contract import ECOMMERCE_CONTRACT, ECOMMERCE_IMPORT_CONTRACT


def import_datasets(
    dataset_service,
    loaded_files: list[tuple[Any, str]],
    *,
    mapping: dict[str, str],
    dataset_name: str,
    data_grain: str,
    amount_semantic: str,
    source_currency: str | None,
    target_currency: str,
) -> dict[str, Any]:
    if data_grain not in {"order", "order_item"}:
        raise ValueError("data_grain 必须是 order 或 order_item")
    if amount_semantic not in {"order_total", "line_amount"}:
        raise ValueError("amount_semantic 必须是 order_total 或 line_amount")

    unique_files = []
    duplicate_issues = []
    seen_hashes = set()
    for loaded, source_file_id in loaded_files:
        digest = str(loaded.metadata.get("sha256") or "")
        if digest and digest in seen_hashes:
            duplicate_issues.append(ValidationIssue(
                "WARNING", "DUPLICATE_FILE_SKIPPED",
                "同一批次中的重复文件已跳过，不会重复写入订单",
                details={"filename": loaded.metadata.get("filename")},
            ))
            continue
        seen_hashes.add(digest)
        unique_files.append((loaded, source_file_id))
    if not unique_files:
        raise ValueError("没有可导入的唯一文件")

    baseline_columns = set(unique_files[0][0].data.columns)
    batch_issues = list(duplicate_issues)
    for loaded, _ in unique_files[1:]:
        columns = set(loaded.data.columns)
        if columns != baseline_columns:
            batch_issues.append(ValidationIssue(
                "FATAL", "FIELD_SET_MISMATCH", "文件字段不一致，整批导入已阻断",
                details={
                    "filename": loaded.metadata.get("filename"),
                    "missing_columns": sorted(baseline_columns - columns),
                    "extra_columns": sorted(columns - baseline_columns),
                },
            ))

    contract = ECOMMERCE_CONTRACT if data_grain == "order" else ECOMMERCE_IMPORT_CONTRACT
    contexts = []
    for loaded, source_file_id in unique_files:
        context = dataset_service.analysis_service.prepare_loaded(
            loaded,
            mapping=mapping,
            source_currency=source_currency,
            target_currency=target_currency,
            contract=contract,
        )
        row_numbers = pd.Series(range(2, len(context.analysis_data) + 2), index=context.analysis_data.index)
        context.analysis_data["source_file_id"] = source_file_id
        context.analysis_data["source_row_number"] = row_numbers
        context.analysis_data["record_id"] = source_file_id + ":" + row_numbers.astype(str)
        contexts.append(context)

    context = replace(
        contexts[0],
        raw_data=pd.concat([item.raw_data for item in contexts], ignore_index=True),
        analysis_data=pd.concat([item.analysis_data for item in contexts], ignore_index=True),
        issues=[issue for item in contexts for issue in item.issues] + batch_issues,
        lineage=dict(contexts[0].lineage),
        metadata=dict(contexts[0].metadata),
    )
    if data_grain == "order" and context.analysis_data.get("order_id") is not None:
        duplicate_count = int(context.analysis_data["order_id"].duplicated(keep=False).sum())
        if duplicate_count and not any(issue.code == "GRAIN_CONFLICT" for issue in context.issues):
            context.issues.append(ValidationIssue(
                "FATAL", "GRAIN_CONFLICT",
                "订单粒度下 order_id 必须跨文件唯一",
                field="order_id", row_count=duplicate_count,
            ))
    if data_grain == "order" and amount_semantic != "order_total":
        context.issues.append(ValidationIssue(
            "FATAL", "AMOUNT_SEMANTIC_MISMATCH",
            "订单粒度必须将 total_amount 确认为订单总金额",
        ))

    frame = context.analysis_data
    amount_field = "total_amount_base" if "total_amount_base" in frame else "total_amount"
    if data_grain == "order_item" and amount_semantic == "order_total" and amount_field in frame:
        inconsistent = frame.groupby("order_id", dropna=False)[amount_field].nunique(dropna=True).gt(1)
        if inconsistent.any():
            context.issues.append(ValidationIssue(
                "FATAL", "INCONSISTENT_ORDER_TOTAL",
                "同一订单的订单总金额不一致，无法安全去重",
                field="total_amount", row_count=int(frame.order_id.isin(inconsistent[inconsistent].index).sum()),
            ))
        first_line = ~frame["order_id"].duplicated(keep="first")
        frame["gmv_amount_base"] = frame[amount_field].where(first_line, 0.0)
        frame["gmv_amount"] = frame["total_amount"].where(first_line, 0.0)
    elif amount_field in frame:
        frame["gmv_amount_base"] = frame[amount_field]
        frame["gmv_amount"] = frame["total_amount"]

    file_lineage = [
        {
            "source_file_id": source_file_id,
            "source_filename": loaded.metadata.get("filename"),
            "source_sha256": loaded.metadata.get("sha256"),
            "selected_sheet": loaded.metadata.get("sheet_name"),
            "rows": len(loaded.data),
        }
        for loaded, source_file_id in unique_files
    ]
    combined_digest = hashlib.sha256(
        "|".join(sorted(str(item[0].metadata.get("sha256") or "") for item in unique_files)).encode("utf-8")
    ).hexdigest()
    filenames = [str(item[0].metadata.get("filename") or "uploaded") for item in unique_files]
    context.metadata.update({
        "dataset_name": dataset_name.strip() or Path(str(unique_files[0][0].metadata.get("filename") or "dataset")).stem,
        "data_grain": data_grain,
        "amount_semantic": amount_semantic,
        "source_file_ids": [item[1] for item in unique_files],
        "source_row_number_basis": "1-based file row including header",
        "selected_sheets": {item["source_filename"]: item["selected_sheet"] for item in file_lineage},
        "filename": filenames[0] if len(filenames) == 1 else "{} + {} files".format(filenames[0], len(filenames) - 1),
        "sha256": combined_digest,
        "rows": len(frame),
        "import_origin": "web",
        "import_status": "BLOCKED" if context.fatal_issues else "READY",
    })
    context.lineage.update({
        "source_files": file_lineage,
        "source_row_number_basis": "1-based file row including header",
    })
    if context.fatal_issues:
        return {
            "status": "BLOCKED",
            "dataset_id": None,
            "source_file_id": unique_files[0][1],
            "source_file_ids": [item[1] for item in unique_files],
            "reused": False,
            "row_count": 0,
            "issues": [issue.to_dict() for issue in context.issues],
        }
    stored = dataset_service.analysis_service.persist(context)
    dataset_service.clear_analysis_cache()
    return {
        "status": "READY",
        "dataset_id": stored.dataset_id,
        "source_file_id": unique_files[0][1],
        "source_file_ids": [item[1] for item in unique_files],
        "reused": stored.reused,
        "row_count": stored.row_count,
        "issues": [issue.to_dict() for issue in context.issues],
    }
