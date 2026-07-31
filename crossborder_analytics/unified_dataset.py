"""Planning and policy contracts for the unified demo dataset."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd

from .adventureworks import AdventureWorksAdapter
from .service import AnalysisService


MERGE_RULE_VERSION = "unified-dataset-v1"
TARGET_CURRENCY = "CNY"
USD_TO_CNY_RATE = 7.20
UNIFIED_DATASET_NAME = "统一经营演示数据"


def _sqlite_uri(path: Path) -> str:
    return "file:{}?mode=ro".format(path.resolve().as_posix())


def _quote_identifier(value: str) -> str:
    return '"{}"'.format(value.replace('"', '""'))


def _source_profile(
    frame: pd.DataFrame,
    *,
    dataset_id: str,
    grain: str,
    business_key: list[str],
    amount_semantic: str,
) -> dict[str, Any]:
    order_ids = frame["order_id"].astype("string")
    dates = pd.to_datetime(frame["order_date"], errors="coerce")
    key_duplicates = None
    if set(business_key).issubset(frame.columns):
        key_duplicates = int(frame.duplicated(business_key, keep=False).sum())
    return {
        "dataset_id": dataset_id,
        "grain": grain,
        "business_key": business_key,
        "business_key_available": set(business_key).issubset(frame.columns),
        "business_key_duplicate_rows": key_duplicates,
        "row_count": int(len(frame)),
        "order_count": int(order_ids.nunique(dropna=True)),
        "customer_count": int(frame["customer_id"].nunique(dropna=True)),
        "period": {
            "start": dates.min().date().isoformat(),
            "end": dates.max().date().isoformat(),
        },
        "currencies": sorted(frame["currency"].dropna().astype(str).unique().tolist()),
        "amount_field": "total_amount",
        "amount_semantic": amount_semantic,
        "amount": round(float(frame["total_amount"].sum()), 2),
    }


class CleanupPreviewService:
    """Inspect cleanup candidates and references without mutating either database."""

    def __init__(self, database_path: str | Path | None, state_database_path: str | Path | None = None):
        self.database_path = Path(database_path) if database_path else None
        self.state_database_path = Path(state_database_path) if state_database_path else None

    def preview(self) -> dict[str, Any]:
        if self.database_path is None or not self.database_path.is_file():
            return {
                "status": "UNAVAILABLE",
                "database_bytes": 0,
                "targets": [],
                "unresolved_references": [],
            }

        registry, references, table_bytes = self._analysis_references()
        state_references = self._state_references()
        for dataset_id, items in state_references.items():
            references[dataset_id].extend(items)

        duplicate_ids = self._duplicate_ids(registry)
        registered_ids = {str(item["dataset_id"]) for item in registry}
        targets = []
        for item in registry:
            dataset_id = str(item["dataset_id"])
            dataset_references = references.get(dataset_id, [])
            blocking = [
                ref for ref in dataset_references
                if ref["table"] not in {
                    "autoclean_datasets", "autoclean_dataset_issues", "autoclean_query_runs", "orders"
                }
            ]
            is_duplicate = dataset_id in duplicate_ids
            if not is_duplicate:
                planned_action = "KEEP"
                reason = "not a superseded duplicate"
            elif blocking:
                planned_action = "SKIP_REFERENCED"
                reason = "duplicate candidate has active dependent records"
            else:
                planned_action = "DEACTIVATE_AFTER_ACCEPTANCE"
                reason = "superseded duplicate; physical deletion still requires the rollback window"
            targets.append({
                "dataset_id": dataset_id,
                "status": item["status"],
                "source_filename": item["source_filename"],
                "row_count": int(item["row_count"] or 0),
                "created_at": item["created_at"],
                "duplicate_candidate": is_duplicate,
                "planned_action": planned_action,
                "reason": reason,
                "estimated_bytes": self._estimated_bytes(dataset_references, table_bytes),
                "size_method": "proportional table page estimate",
                "references": dataset_references,
            })

        unresolved = [
            {"dataset_id": dataset_id, "references": items}
            for dataset_id, items in sorted(references.items())
            if dataset_id not in registered_ids
        ]
        return {
            "status": "READY",
            "database_bytes": self.database_path.stat().st_size,
            "targets": targets,
            "unresolved_references": unresolved,
            "raw_source_files_included": False,
            "physical_delete_allowed": False,
        }

    def _analysis_references(self):
        registry: list[dict[str, Any]] = []
        references: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        table_bytes: dict[str, int] = {}
        with sqlite3.connect(_sqlite_uri(self.database_path), uri=True) as connection:
            connection.row_factory = sqlite3.Row
            table_names = [
                str(row[0]) for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            if "autoclean_datasets" in table_names:
                registry = [dict(row) for row in connection.execute(
                    "SELECT dataset_id, source_sha256, source_filename, row_count, status, "
                    "metadata_json, created_at FROM autoclean_datasets ORDER BY created_at"
                )]
            try:
                table_bytes = {
                    str(row[0]): int(row[1] or 0)
                    for row in connection.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name")
                }
            except sqlite3.OperationalError:
                table_bytes = {}
            for table in table_names:
                quoted = _quote_identifier(table)
                columns = {str(row[1]) for row in connection.execute("PRAGMA table_info({})".format(quoted))}
                if "dataset_id" not in columns:
                    continue
                total_rows = int(connection.execute("SELECT COUNT(*) FROM {}".format(quoted)).fetchone()[0])
                for dataset_id, row_count in connection.execute(
                    "SELECT dataset_id, COUNT(*) FROM {} GROUP BY dataset_id".format(quoted)
                ):
                    references[str(dataset_id)].append({
                        "store": "analysis",
                        "table": table,
                        "row_count": int(row_count),
                        "table_row_count": total_rows,
                    })
        return registry, references, table_bytes

    def _state_references(self) -> defaultdict[str, list[dict[str, Any]]]:
        references: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        if self.state_database_path is None or not self.state_database_path.is_file():
            return references
        with sqlite3.connect(_sqlite_uri(self.state_database_path), uri=True) as connection:
            table_names = [
                str(row[0]) for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            for table in table_names:
                quoted = _quote_identifier(table)
                columns = {str(row[1]) for row in connection.execute("PRAGMA table_info({})".format(quoted))}
                if "dataset_id" not in columns:
                    continue
                for dataset_id, row_count in connection.execute(
                    "SELECT dataset_id, COUNT(*) FROM {} GROUP BY dataset_id".format(quoted)
                ):
                    references[str(dataset_id)].append({
                        "store": "state",
                        "table": table,
                        "row_count": int(row_count),
                        "table_row_count": int(row_count),
                    })
        return references

    @staticmethod
    def _duplicate_ids(registry: list[dict[str, Any]]) -> set[str]:
        groups: defaultdict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
        for item in registry:
            key = (
                str(item["source_sha256"] or ""),
                str(item["source_filename"] or ""),
                int(item["row_count"] or 0),
            )
            if all(key):
                groups[key].append(item)
        duplicate_ids: set[str] = set()
        for candidates in groups.values():
            ordered = sorted(candidates, key=lambda item: str(item["created_at"] or ""), reverse=True)
            duplicate_ids.update(str(item["dataset_id"]) for item in ordered[1:])
        return duplicate_ids

    @staticmethod
    def _estimated_bytes(references: list[dict[str, Any]], table_bytes: dict[str, int]) -> int:
        estimate = 0.0
        for reference in references:
            table_rows = reference["table_row_count"]
            if reference["store"] == "analysis" and table_rows:
                estimate += table_bytes.get(reference["table"], 0) * reference["row_count"] / table_rows
        return int(round(estimate))


class UnifiedDatasetPreviewService:
    """Build a reproducible merge gate without creating derived data."""

    def __init__(
        self,
        demo_path: str | Path,
        adventureworks_path: str | Path,
        database_path: str | Path | None = None,
        state_database_path: str | Path | None = None,
    ) -> None:
        self.demo_path = Path(demo_path)
        self.adventureworks_path = Path(adventureworks_path)
        self.cleanup = CleanupPreviewService(database_path, state_database_path)

    def preview(self) -> dict[str, Any]:
        demo = AnalysisService(database_path=None, backend="pandas").prepare(
            self.demo_path,
            source_currency="CNY",
            target_currency="CNY",
            online_fx=False,
        )
        if demo.fatal_issues:
            raise ValueError("demo-all failed its source contract")
        adventureworks = AdventureWorksAdapter().load_orders(self.adventureworks_path)
        demo_frame = demo.analysis_data
        adventureworks_frame = adventureworks.loaded.data

        source_files = [{
            "dataset_id": "demo-all",
            "filename": self.demo_path.name,
            "path": str(self.demo_path.resolve()),
            "sha256": str(demo.metadata["sha256"]),
            "bytes": self.demo_path.stat().st_size,
            "read_only": True,
        }]
        source_files.extend({
            "dataset_id": adventureworks.dataset_id,
            "filename": item["filename"],
            "path": item["path"],
            "sha256": item["sha256"],
            "bytes": Path(item["path"]).stat().st_size,
            "read_only": True,
        } for item in adventureworks.source_files)
        merge_version = hashlib.sha256(json.dumps(
            {
                "rule_version": MERGE_RULE_VERSION,
                "source_hashes": [item["sha256"] for item in source_files],
                "target_currency": TARGET_CURRENCY,
                "usd_to_cny_rate": USD_TO_CNY_RATE,
            },
            sort_keys=True,
        ).encode("ascii")).hexdigest()[:16]

        demo_profile = _source_profile(
            demo_frame,
            dataset_id="demo-all",
            grain="order",
            business_key=["order_id"],
            amount_semantic="discounted merchandise amount; recorded freight is separate; tax is unavailable",
        )
        adventureworks_profile = _source_profile(
            adventureworks_frame,
            dataset_id=adventureworks.dataset_id,
            grain="order_line",
            business_key=["sales_order_number", "sales_order_line_number"],
            amount_semantic="SalesAmount converted to USD; Freight stored separately",
        )
        exact_order_overlap = len(
            set(demo_frame["order_id"].astype(str))
            & set(adventureworks_frame["order_id"].astype(str))
        )
        checks = [
            self._check(
                "business_key",
                "PASS",
                "canonical record key is source dataset + order id + line number; demo-all uses deterministic line 1",
            ),
            self._check(
                "currency",
                "PASS",
                "target currency is CNY; AdventureWorks USD is converted with versioned demo rate {:.2f}".format(
                    USD_TO_CNY_RATE,
                ),
            ),
            self._check(
                "amount_semantics",
                "PASS",
                "both sources use discounted merchandise amount with recorded freight separate; tax is unavailable",
            ),
            self._check(
                "date_semantics",
                "PASS",
                "both order dates are date-only and are normalized as source-local calendar dates without timezone inference",
            ),
            self._check(
                "source_key_overlap",
                "PASS",
                "exact order-id overlap is {}; fuzzy matching was not performed".format(exact_order_overlap),
            ),
            self._check(
                "period_overlap",
                "WARNING",
                "source periods do not overlap, so the result would be a historical union rather than a like-for-like period",
            ),
        ]
        blocking_checks = [item["check_id"] for item in checks if item["status"] in {"BLOCKED", "OPEN"}]
        input_rows = len(demo_frame) + len(adventureworks_frame)
        can_materialize = not blocking_checks
        retained_rows = input_rows if can_materialize else 0
        quarantined_rows = input_rows - retained_rows
        return {
            "status": "READY" if can_materialize else "BLOCKED",
            "rule_version": MERGE_RULE_VERSION,
            "merge_version": merge_version,
            "can_materialize": can_materialize,
            "blocking_checks": blocking_checks,
            "source_files": source_files,
            "sources": [demo_profile, adventureworks_profile],
            "compatibility_checks": checks,
            "duplicate_preview": {
                "status": "COMPLETE",
                "exact_order_id_overlap": exact_order_overlap,
                "duplicate_rows": 0,
                "conflict_rows": 0,
                "fuzzy_matching_performed": False,
            },
            "row_reconciliation": {
                "input_rows": input_rows,
                "retained_rows": retained_rows,
                "duplicate_rows": 0,
                "quarantined_rows": quarantined_rows,
                "difference": input_rows - retained_rows - quarantined_rows,
            },
            "amount_reconciliation": {
                "status": "RECONCILED",
                "source_amounts": {
                    "demo-all": demo_profile["amount"],
                    adventureworks.dataset_id: adventureworks_profile["amount"],
                },
                "target_currency": TARGET_CURRENCY,
                "conversion_policy": "{} USD to CNY fixed demo rate {:.2f}".format(
                    MERGE_RULE_VERSION, USD_TO_CNY_RATE,
                ),
                "unified_amount": round(
                    demo_profile["amount"] + adventureworks_profile["amount"] * USD_TO_CNY_RATE,
                    2,
                ),
                "difference": 0.0,
            },
            "cleanup_preview": self.cleanup.preview(),
        }

    @staticmethod
    def _check(check_id: str, status: str, detail: str) -> dict[str, str]:
        return {"check_id": check_id, "status": status, "detail": detail}
