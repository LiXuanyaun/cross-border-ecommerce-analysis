"""Versioned publication of the unified demo dataset and its business facts."""
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd
from autoclean.analytics import ValidationIssue

from .adventureworks import AdventureWorksAdapter
from .database import AMOUNT_FIELDS, CrossBorderDatabase
from .multibusiness_schema import foreign_key_violations, migrate_multibusiness_schema
from .service import AnalysisService
from .unified_dataset import (
    MERGE_RULE_VERSION,
    TARGET_CURRENCY,
    UNIFIED_DATASET_NAME,
    USD_TO_CNY_RATE,
    UnifiedDatasetPreviewService,
)


BUSINESS_COPY_ORDER = (
    "import_batches",
    "import_files",
    "business_orders",
    "business_order_lines",
    "dim_campaign",
    "dim_carrier",
    "dim_return_reason",
    "fact_ad_performance_daily",
    "bridge_order_attribution",
    "fact_shipments",
    "fact_returns",
    "fact_tracking_events",
)

BUSINESS_DELETE_ORDER = tuple(reversed(BUSINESS_COPY_ORDER))

UNIFIED_DDL = """
CREATE TABLE IF NOT EXISTS unified_dataset_versions (
    dataset_id TEXT PRIMARY KEY,
    merge_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    status TEXT NOT NULL,
    target_currency TEXT NOT NULL,
    usd_to_cny_rate REAL NOT NULL,
    source_files_json TEXT NOT NULL,
    input_rows INTEGER NOT NULL,
    retained_rows INTEGER NOT NULL,
    duplicate_rows INTEGER NOT NULL,
    conflict_rows INTEGER NOT NULL,
    quarantined_rows INTEGER NOT NULL,
    unified_amount REAL NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS unified_order_lineage (
    dataset_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    source_dataset_id TEXT NOT NULL,
    source_record_key TEXT NOT NULL,
    source_currency TEXT NOT NULL,
    source_amount REAL NOT NULL,
    target_currency TEXT NOT NULL,
    target_amount REAL NOT NULL,
    fx_rate REAL NOT NULL,
    merge_version TEXT NOT NULL,
    decision TEXT NOT NULL,
    PRIMARY KEY (dataset_id, record_id),
    FOREIGN KEY (dataset_id, record_id) REFERENCES orders(dataset_id, record_id)
);

CREATE TABLE IF NOT EXISTS unified_dataset_lifecycle (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    restore_until TEXT
);
"""


class UnifiedDatasetMaterializationService:
    """Build all unified facts under a hidden status, then publish them together."""

    def __init__(
        self,
        demo_path: str | Path,
        adventureworks_path: str | Path,
        database_path: str | Path,
        state_database_path: str | Path | None = None,
    ) -> None:
        self.demo_path = Path(demo_path)
        self.adventureworks_path = Path(adventureworks_path)
        self.database_path = Path(database_path)
        self.preview_service = UnifiedDatasetPreviewService(
            demo_path,
            adventureworks_path,
            database_path,
            state_database_path,
        )

    def materialize(self) -> dict[str, Any]:
        preview = self.preview_service.preview()
        if not preview["can_materialize"]:
            raise RuntimeError(
                "Unified dataset policy is blocked: {}".format(
                    ", ".join(preview["blocking_checks"]),
                )
            )
        source_dataset_id = str(preview["sources"][1]["dataset_id"])
        dataset_id = "unified-{}".format(preview["merge_version"])
        existing = self._published_version(dataset_id)
        if existing:
            return {
                "status": "READY",
                "dataset_id": dataset_id,
                "merge_version": preview["merge_version"],
                "row_count": existing["retained_rows"],
                "reused": True,
                "source_dataset_id": source_dataset_id,
            }
        if not self._has_business_facts(source_dataset_id):
            raise RuntimeError(
                "AdventureWorks business facts are not registered for {}; import them before materialization".format(
                    source_dataset_id,
                )
            )

        self._purge_staged(dataset_id)
        context, lineage_rows = self._build_context(preview)
        database = CrossBorderDatabase(self.database_path)
        try:
            stored = database.persist(context, dataset_id=dataset_id, final_status="BUILDING")
            migrate_multibusiness_schema(self.database_path)
            self._publish(
                dataset_id,
                source_dataset_id,
                preview,
                lineage_rows,
            )
        except Exception:
            self._purge_staged(dataset_id)
            raise
        return {
            "status": "READY",
            "dataset_id": dataset_id,
            "merge_version": preview["merge_version"],
            "row_count": stored.row_count,
            "reused": False,
            "source_dataset_id": source_dataset_id,
        }

    def _build_context(self, preview: dict[str, Any]):
        demo = AnalysisService(database_path=None, backend="pandas").prepare(
            self.demo_path,
            source_currency="CNY",
            target_currency=TARGET_CURRENCY,
            online_fx=False,
        )
        adventureworks = AdventureWorksAdapter().load_orders(self.adventureworks_path)
        demo_frame = demo.analysis_data.copy()
        aw_source = adventureworks.loaded.data.copy()
        aw_frame = aw_source.copy()

        demo_frame["record_id"] = "demo:" + demo_frame["order_id"].astype(str) + ":1"
        demo_frame["sales_order_number"] = demo_frame["order_id"].astype(str)
        demo_frame["sales_order_line_number"] = pd.Series(1, index=demo_frame.index, dtype="Int64")
        demo_frame["source_file_id"] = "src_demo_{}".format(str(demo.metadata["sha256"])[:12])
        demo_frame["source_row_number"] = pd.Series(
            range(2, len(demo_frame) + 2), index=demo_frame.index, dtype="Int64",
        )
        self._set_base_amounts(demo_frame, 1.0, "source CNY")
        self._set_base_amounts(
            aw_frame,
            USD_TO_CNY_RATE,
            "{} fixed demo USD/CNY {:.2f}".format(MERGE_RULE_VERSION, USD_TO_CNY_RATE),
        )
        combined = pd.concat([demo_frame, aw_frame], ignore_index=True, sort=False)
        if combined["record_id"].duplicated().any():
            raise RuntimeError("Unified record_id is not unique")

        demo_lineage = pd.DataFrame({
            "record_id": demo_frame["record_id"],
            "source_dataset_id": "demo-all",
            "source_record_key": demo_frame["order_id"].astype(str) + ":1",
            "source_currency": "CNY",
            "source_amount": pd.to_numeric(demo.analysis_data["total_amount"], errors="coerce"),
            "target_currency": TARGET_CURRENCY,
            "target_amount": demo_frame["gmv_amount_base"],
            "fx_rate": 1.0,
            "decision": "RETAINED",
        })
        aw_lineage = pd.DataFrame({
            "record_id": aw_frame["record_id"],
            "source_dataset_id": adventureworks.dataset_id,
            "source_record_key": (
                aw_source["sales_order_number"].astype(str)
                + ":"
                + aw_source["sales_order_line_number"].astype("Int64").astype(str)
            ),
            "source_currency": "USD",
            "source_amount": pd.to_numeric(aw_source["total_amount"], errors="coerce"),
            "target_currency": TARGET_CURRENCY,
            "target_amount": aw_frame["gmv_amount_base"],
            "fx_rate": USD_TO_CNY_RATE,
            "decision": "RETAINED",
        })
        lineage_rows = pd.concat([demo_lineage, aw_lineage], ignore_index=True)
        lineage_rows["merge_version"] = preview["merge_version"]

        metadata = dict(demo.metadata)
        metadata.update({
            "dataset_name": UNIFIED_DATASET_NAME,
            "filename": "unified:{}".format(preview["merge_version"]),
            "sha256": hashlib.sha256(
                "|".join(item["sha256"] for item in preview["source_files"]).encode("ascii")
            ).hexdigest(),
            "rows": len(combined),
            "data_grain": "canonical_order_line",
            "amount_semantic": "discounted merchandise amount; recorded freight separate; tax unavailable",
            "import_origin": "unified",
            "data_origin": "demo-all+adventureworks",
            "is_simulated": True,
            "target_currency": TARGET_CURRENCY,
            "merge_version": preview["merge_version"],
            "merge_rule_version": MERGE_RULE_VERSION,
            "usd_to_cny_rate": USD_TO_CNY_RATE,
            "simulation_disclosure": (
                "demo-all 与 AdventureWorks 为示例来源；AdventureWorks 多业务事实为演示推算数据；"
                "USD 金额按版本化固定演示汇率折算为 CNY，不可用于财务核算。"
            ),
        })
        lineage = dict(demo.lineage)
        lineage.update({
            "source_files": preview["source_files"],
            "merge_version": preview["merge_version"],
            "merge_rule_version": MERGE_RULE_VERSION,
            "raw_read_only": True,
        })
        semantic_overrides = dict(demo.semantic_overrides)
        semantic_overrides.update({
            "target_currency": TARGET_CURRENCY,
            "date_semantic": "source-local calendar date",
            "amount_semantic": metadata["amount_semantic"],
        })
        issues = list(demo.issues) + [
            ValidationIssue(
                "WARNING",
                "UNIFIED_DEMO_FX_POLICY",
                "AdventureWorks USD 金额使用固定演示汇率折算为 CNY，不可用于财务核算",
                details={"usd_to_cny_rate": USD_TO_CNY_RATE, "rule_version": MERGE_RULE_VERSION},
            ),
            ValidationIssue(
                "WARNING",
                "NON_OVERLAPPING_SOURCE_PERIODS",
                "两个示例来源期间不重叠，统一数据用于功能覆盖与历史结构分析",
            ),
        ]
        return replace(
            demo,
            raw_data=combined.copy(),
            analysis_data=combined,
            issues=issues,
            lineage=lineage,
            metadata=metadata,
            semantic_overrides=semantic_overrides,
        ), lineage_rows

    @staticmethod
    def _set_base_amounts(frame: pd.DataFrame, rate: float, fx_source: str) -> None:
        for field in AMOUNT_FIELDS:
            if field not in frame:
                continue
            converted = pd.to_numeric(frame[field], errors="coerce") * rate
            frame[field] = converted
            frame["{}_base".format(field)] = converted
        if "gmv_amount" not in frame and "total_amount" in frame:
            frame["gmv_amount"] = frame["total_amount"]
        else:
            frame["gmv_amount"] = pd.to_numeric(frame["gmv_amount"], errors="coerce") * rate
        frame["gmv_amount_base"] = frame["gmv_amount"]
        frame["currency"] = TARGET_CURRENCY
        frame["fx_rate"] = rate
        frame["fx_rate_date"] = pd.to_datetime(frame["order_date"], errors="coerce")
        frame["fx_source"] = fx_source

    def _publish(
        self,
        dataset_id: str,
        source_dataset_id: str,
        preview: dict[str, Any],
        lineage_rows: pd.DataFrame,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(UNIFIED_DDL)
            connection.execute("BEGIN IMMEDIATE")
            batch_map, file_map = self._copy_business_facts(
                connection, source_dataset_id, dataset_id, preview["merge_version"],
            )
            if not batch_map or not file_map:
                raise RuntimeError("Unified business fact copy produced no import lineage")
            lineage_insert = (
                "INSERT INTO unified_order_lineage (dataset_id, record_id, source_dataset_id, "
                "source_record_key, source_currency, source_amount, target_currency, target_amount, "
                "fx_rate, merge_version, decision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            )
            connection.executemany(
                lineage_insert,
                [
                    (
                        dataset_id,
                        row.record_id,
                        row.source_dataset_id,
                        row.source_record_key,
                        row.source_currency,
                        float(row.source_amount),
                        row.target_currency,
                        float(row.target_amount),
                        float(row.fx_rate),
                        row.merge_version,
                        row.decision,
                    )
                    for row in lineage_rows.itertuples(index=False)
                ],
            )
            amount = preview["amount_reconciliation"]
            rows = preview["row_reconciliation"]
            connection.execute(
                "INSERT INTO unified_dataset_versions (dataset_id, merge_version, rule_version, status, "
                "target_currency, usd_to_cny_rate, source_files_json, input_rows, retained_rows, duplicate_rows, "
                "conflict_rows, quarantined_rows, unified_amount, created_at, published_at) "
                "VALUES (?, ?, ?, 'READY', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    dataset_id,
                    preview["merge_version"],
                    MERGE_RULE_VERSION,
                    TARGET_CURRENCY,
                    USD_TO_CNY_RATE,
                    json.dumps(preview["source_files"], ensure_ascii=False, sort_keys=True),
                    rows["input_rows"],
                    rows["retained_rows"],
                    rows["duplicate_rows"],
                    preview["duplicate_preview"]["conflict_rows"],
                    rows["quarantined_rows"],
                    amount["unified_amount"],
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO unified_dataset_lifecycle (dataset_id, status, reason, actor, changed_at) "
                "VALUES (?, 'READY', 'initial atomic publication', 'system', ?)",
                (dataset_id, now),
            )
            connection.execute(
                "UPDATE autoclean_datasets SET status='READY' WHERE dataset_id=? AND status='BUILDING'",
                (dataset_id,),
            )
            if connection.total_changes <= 0:
                raise RuntimeError("Unified dataset publication did not update registry")
            connection.commit()
        violations = foreign_key_violations(self.database_path)
        if violations:
            raise RuntimeError("Unified foreign key validation failed: {}".format(violations[:5]))

    def _copy_business_facts(self, connection, source_id: str, target_id: str, merge_version: str):
        source_batches = connection.execute(
            "SELECT import_batch_id FROM import_batches WHERE dataset_id=? ORDER BY import_batch_id",
            (source_id,),
        ).fetchall()
        batch_map = {
            str(row["import_batch_id"]): self._mapped_id("ub", merge_version, str(row["import_batch_id"]))
            for row in source_batches
        }
        source_files = connection.execute(
            "SELECT import_file_id FROM import_files WHERE dataset_id=? ORDER BY import_file_id",
            (source_id,),
        ).fetchall()
        file_map = {
            str(row["import_file_id"]): self._mapped_id("uf", merge_version, str(row["import_file_id"]))
            for row in source_files
        }
        for table in BUSINESS_COPY_ORDER:
            columns = [row[1] for row in connection.execute("PRAGMA table_info({})".format(table))]
            rows = connection.execute(
                "SELECT * FROM {} WHERE dataset_id=?".format(table),
                (source_id,),
            ).fetchall()
            prepared = []
            for row in rows:
                values = dict(row)
                values["dataset_id"] = target_id
                if "import_batch_id" in values:
                    values["import_batch_id"] = batch_map[str(values["import_batch_id"])]
                if "import_file_id" in values:
                    values["import_file_id"] = file_map[str(values["import_file_id"])]
                prepared.append(tuple(values[column] for column in columns))
            if prepared:
                connection.executemany(
                    "INSERT INTO {} ({}) VALUES ({})".format(
                        table,
                        ", ".join('"{}"'.format(column) for column in columns),
                        ", ".join("?" for _ in columns),
                    ),
                    prepared,
                )
        return batch_map, file_map

    def _published_version(self, dataset_id: str):
        if not self.database_path.is_file():
            return None
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            connection.row_factory = sqlite3.Row
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='unified_dataset_versions'"
            ).fetchone()
            if not exists:
                return None
            row = connection.execute(
                "SELECT * FROM unified_dataset_versions WHERE dataset_id=? AND status='READY'",
                (dataset_id,),
            ).fetchone()
            return dict(row) if row else None

    def _has_business_facts(self, dataset_id: str) -> bool:
        if not self.database_path.is_file():
            return False
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='business_orders'"
            ).fetchone()
            if not exists:
                return False
            return connection.execute(
                "SELECT 1 FROM business_orders WHERE dataset_id=? LIMIT 1",
                (dataset_id,),
            ).fetchone() is not None

    def _purge_staged(self, dataset_id: str) -> None:
        if not self.database_path.is_file():
            return
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            existing_tables = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            for table in BUSINESS_DELETE_ORDER:
                if table in existing_tables:
                    connection.execute("DELETE FROM {} WHERE dataset_id=?".format(table), (dataset_id,))
            for table in (
                "unified_order_lineage",
                "unified_dataset_versions",
                "unified_dataset_lifecycle",
                "orders",
                "autoclean_dataset_issues",
                "autoclean_query_runs",
                "autoclean_datasets",
            ):
                if table in existing_tables:
                    connection.execute("DELETE FROM {} WHERE dataset_id=?".format(table), (dataset_id,))
            connection.commit()

    @staticmethod
    def _mapped_id(prefix: str, merge_version: str, source_id: str) -> str:
        digest = hashlib.sha256((merge_version + ":" + source_id).encode("utf-8")).hexdigest()[:20]
        return "{}_{}_{}".format(prefix, merge_version[:8], digest)
