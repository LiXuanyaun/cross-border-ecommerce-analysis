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
    target_dataset_id: str | None = None,
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

    batch_issues = list(duplicate_issues)
    contract = ECOMMERCE_CONTRACT if data_grain == "order" else ECOMMERCE_IMPORT_CONTRACT
    contexts = []
    accepted_files = []
    failed_files = []
    for loaded, source_file_id in unique_files:
        file_mapping = {
            standard: source
            for standard, source in mapping.items()
            if source in loaded.data.columns
        }
        context = dataset_service.analysis_service.prepare_loaded(
            loaded,
            mapping=file_mapping or None,
            source_currency=source_currency,
            target_currency=target_currency,
            contract=contract,
        )
        if context.fatal_issues:
            failed_files.append({
                "source_file_id": source_file_id,
                "filename": loaded.metadata.get("filename"),
                "status": "FAILED",
                "row_count": len(loaded.data),
                "issues": [issue.to_dict() for issue in context.issues],
            })
            batch_issues.append(ValidationIssue(
                "WARNING", "FILE_SKIPPED", "文件未通过 autoclean，已跳过并保留失败原因",
                details={
                    "filename": loaded.metadata.get("filename"),
                    "source_file_id": source_file_id,
                },
            ))
            continue
        row_numbers = pd.Series(range(2, len(context.analysis_data) + 2), index=context.analysis_data.index)
        context.analysis_data["source_file_id"] = source_file_id
        context.analysis_data["source_row_number"] = row_numbers
        context.analysis_data["record_id"] = source_file_id + ":" + row_numbers.astype(str)
        accepted_files.append((loaded, source_file_id))
        contexts.append(context)

    if not accepted_files:
        issues = [issue.to_dict() for issue in batch_issues]
        issues.extend(item for failed in failed_files for item in failed["issues"])
        return {
            "status": "BLOCKED",
            "dataset_id": None,
            "source_file_id": unique_files[0][1],
            "source_file_ids": [item[1] for item in unique_files],
            "reused": False,
            "row_count": 0,
            "failed_files": failed_files,
            "issues": issues,
        }

    unique_files = accepted_files

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
        "import_status": "READY",
        "partial_import": bool(failed_files),
        "failed_file_count": len(failed_files),
    })
    context.lineage.update({
        "source_files": file_lineage,
        "source_row_number_basis": "1-based file row including header",
    })

    if target_dataset_id:
        try:
            target = dataset_service.scenario(target_dataset_id)
        except KeyError as exc:
            raise ValueError("追加目标数据集不存在或已归档") from exc
        if (target.metadata or {}).get("import_origin") != "web":
            raise ValueError("只能向 Web 上传的数据集追加，统一/示例数据集不可修改")
        existing = dataset_service.context_for(target_dataset_id)
        existing_metadata = dict(existing.metadata or {})
        merge_issues = []
        expected_grain = existing_metadata.get("data_grain")
        expected_amount = existing_metadata.get("amount_semantic")
        expected_currency = existing_metadata.get("target_currency")
        if expected_grain and expected_grain != data_grain:
            merge_issues.append(ValidationIssue(
                "FATAL", "DATA_GRAIN_MISMATCH", "追加数据的粒度与目标数据集不一致",
                details={"target": expected_grain, "incoming": data_grain},
            ))
        if expected_amount and expected_amount != amount_semantic:
            merge_issues.append(ValidationIssue(
                "FATAL", "AMOUNT_SEMANTIC_MISMATCH", "追加数据的金额语义与目标数据集不一致",
                details={"target": expected_amount, "incoming": amount_semantic},
            ))
        if expected_currency and expected_currency != target_currency:
            merge_issues.append(ValidationIssue(
                "FATAL", "TARGET_CURRENCY_MISMATCH", "追加数据的目标币种与目标数据集不一致",
                details={"target": expected_currency, "incoming": target_currency},
            ))

        existing_frame = existing.analysis_data.copy()
        incoming_frame = context.analysis_data.copy()
        existing_record_ids = set(existing_frame.get("record_id", pd.Series(dtype="string")).dropna().astype(str))
        duplicate_record_mask = incoming_frame.get("record_id", pd.Series(dtype="string")).astype(str).isin(existing_record_ids)
        duplicate_record_count = int(duplicate_record_mask.sum())
        if duplicate_record_count:
            merge_issues.append(ValidationIssue(
                "WARNING", "DUPLICATE_RECORD_SKIPPED", "已有来源记录已存在，重复行已跳过",
                row_count=duplicate_record_count,
            ))
            incoming_frame = incoming_frame.loc[~duplicate_record_mask].copy()

        if data_grain == "order" and "order_id" in existing_frame and "order_id" in incoming_frame:
            existing_order_ids = set(existing_frame["order_id"].dropna().astype(str))
            overlapping = incoming_frame[incoming_frame["order_id"].dropna().astype(str).isin(existing_order_ids)]
            if not overlapping.empty:
                merge_issues.append(ValidationIssue(
                    "FATAL", "GRAIN_CONFLICT", "追加数据包含目标数据集已有的 order_id，批次未写入",
                    field="order_id", row_count=len(overlapping),
                ))

        if not incoming_frame.empty:
            combined_frame = pd.concat([existing_frame, incoming_frame], ignore_index=True, sort=False)
        else:
            combined_frame = existing_frame
        source_files = []
        for item in list((existing.lineage or {}).get("source_files") or []) + file_lineage:
            source_id = str(item.get("source_file_id") or "")
            if source_id and not any(str(previous.get("source_file_id") or "") == source_id for previous in source_files):
                source_files.append(dict(item))
        source_ids = [str(item.get("source_file_id")) for item in source_files if item.get("source_file_id")]
        source_hashes = [str(item.get("source_sha256") or "") for item in source_files]
        merged_metadata = dict(existing_metadata)
        merged_metadata.update({
            "dataset_name": existing_metadata.get("dataset_name") or target.name,
            "data_grain": expected_grain or data_grain,
            "amount_semantic": expected_amount or amount_semantic,
            "source_file_ids": source_ids,
            "source_row_number_basis": "1-based file row including header",
            "filename": "{} + {} files".format(target.name, len(source_files)),
            "sha256": hashlib.sha256("|".join(sorted(source_hashes)).encode("utf-8")).hexdigest(),
            "rows": len(combined_frame),
            "import_origin": "web",
            "import_status": "BLOCKED" if any(issue.severity == "FATAL" for issue in merge_issues) else "READY",
            "parent_dataset_id": target_dataset_id,
            "merge_mode": "append",
        })
        # The child must receive a new content-derived identity; never reuse the parent id.
        merged_metadata.pop("dataset_id", None)
        merged_context = replace(
            existing,
            raw_data=combined_frame.copy(),
            analysis_data=combined_frame,
            issues=list(existing.issues) + list(context.issues) + merge_issues,
            lineage={
                **dict(existing.lineage or {}),
                "source_files": source_files,
                "source_row_number_basis": "1-based file row including header",
                "parent_dataset_id": target_dataset_id,
            },
            metadata=merged_metadata,
        )
        if any(issue.severity == "FATAL" for issue in merge_issues) or merged_context.fatal_issues:
            return {
                "status": "BLOCKED",
                "dataset_id": None,
                "source_file_id": unique_files[0][1],
                "source_file_ids": [item[1] for item in unique_files],
                "reused": False,
                "merged": True,
                "parent_dataset_id": target_dataset_id,
                "row_count": 0,
                "issues": [issue.to_dict() for issue in merged_context.issues],
                "failed_files": failed_files,
            }
        if incoming_frame.empty:
            return {
                "status": "READY",
                "dataset_id": target_dataset_id,
                "source_file_id": unique_files[0][1],
                "source_file_ids": source_ids,
                "reused": True,
                "merged": True,
                "parent_dataset_id": target_dataset_id,
                "row_count": len(existing_frame),
                "previous_row_count": len(existing_frame),
                "appended_row_count": 0,
                "skipped_row_count": duplicate_record_count,
                "issues": [issue.to_dict() for issue in merged_context.issues],
                "failed_files": failed_files,
            }
        context = merged_context
        file_lineage = source_files
        previous_row_count = len(existing_frame)
        appended_row_count = len(incoming_frame)
    if context.fatal_issues:
        return {
            "status": "BLOCKED",
            "dataset_id": None,
            "source_file_id": unique_files[0][1],
            "source_file_ids": [item[1] for item in unique_files],
            "reused": False,
            "row_count": 0,
            "failed_files": failed_files,
            "issues": [issue.to_dict() for issue in context.issues],
        }
    stored = dataset_service.analysis_service.persist(context)
    dataset_service.clear_analysis_cache()
    result = {
        "status": "READY",
        "dataset_id": stored.dataset_id,
        "source_file_id": unique_files[0][1],
        "source_file_ids": [item[1] for item in unique_files],
        "reused": stored.reused,
        "row_count": stored.row_count,
        "issues": [issue.to_dict() for issue in context.issues],
    }
    if failed_files:
        result["failed_files"] = failed_files
    if target_dataset_id:
        result.update({
            "merged": True,
            "parent_dataset_id": target_dataset_id,
            "previous_row_count": previous_row_count,
            "appended_row_count": appended_row_count,
            "skipped_row_count": duplicate_record_count,
        })
    return result
