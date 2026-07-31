"""Reversible retirement and time-gated cleanup for superseded derived datasets."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from .unified_dataset import CleanupPreviewService


LIFECYCLE_DDL = """
CREATE TABLE IF NOT EXISTS unified_dataset_lifecycle (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    restore_until TEXT
);

CREATE TABLE IF NOT EXISTS unified_cleanup_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    source_metadata_json TEXT NOT NULL,
    deleted_rows_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class UnifiedDatasetLifecycleService:
    def __init__(self, database_path: str | Path, state_database_path: str | Path | None = None):
        self.database_path = Path(database_path)
        self.state_database_path = Path(state_database_path) if state_database_path else None

    def status(self, unified_dataset_id: str) -> dict[str, Any]:
        if not self.database_path.is_file():
            return {"unified_dataset_id": unified_dataset_id, "sources": [], "cleanup_audit": []}
        self._ensure_schema()
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            connection.row_factory = sqlite3.Row
            sources = self._source_candidates(connection, unified_dataset_id)
            events = {
                str(row["dataset_id"]): dict(row)
                for row in connection.execute(
                    "SELECT l.* FROM unified_dataset_lifecycle l "
                    "JOIN (SELECT dataset_id, MAX(event_id) event_id FROM unified_dataset_lifecycle GROUP BY dataset_id) latest "
                    "ON latest.event_id=l.event_id"
                )
            }
            audit = [dict(row) for row in connection.execute(
                "SELECT dataset_id, action, actor, reason, deleted_rows_json, created_at "
                "FROM unified_cleanup_audit ORDER BY audit_id DESC"
            )]
        return {
            "unified_dataset_id": unified_dataset_id,
            "sources": [
                {
                    "dataset_id": item["dataset_id"],
                    "dataset_name": item["metadata"].get("dataset_name") or item["source_filename"],
                    "registry_status": item["status"],
                    "last_lifecycle_event": events.get(item["dataset_id"]),
                }
                for item in sources
            ],
            "cleanup_audit": audit,
            "raw_source_files_included": False,
        }

    def deactivate_sources(
        self,
        unified_dataset_id: str,
        *,
        actor: str = "system",
        rollback_days: int = 7,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        changed_at = self._utc(now)
        restore_until = changed_at + timedelta(days=rollback_days)
        self._ensure_schema()
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            connection.row_factory = sqlite3.Row
            self._assert_unified_ready(connection, unified_dataset_id)
            candidates = self._source_candidates(connection, unified_dataset_id)
            connection.execute("BEGIN IMMEDIATE")
            deactivated = []
            for item in candidates:
                if item["status"] != "READY":
                    continue
                connection.execute(
                    "UPDATE autoclean_datasets SET status='SUPERSEDED' WHERE dataset_id=? AND status='READY'",
                    (item["dataset_id"],),
                )
                connection.execute(
                    "INSERT INTO unified_dataset_lifecycle "
                    "(dataset_id, status, reason, actor, changed_at, restore_until) "
                    "VALUES (?, 'SUPERSEDED', 'replaced by accepted unified dataset', ?, ?, ?)",
                    (item["dataset_id"], actor, changed_at.isoformat(), restore_until.isoformat()),
                )
                deactivated.append(item["dataset_id"])
            connection.commit()
        return {
            "status": "SUPERSEDED",
            "unified_dataset_id": unified_dataset_id,
            "deactivated_dataset_ids": deactivated,
            "restore_until": restore_until.isoformat(),
            "physical_delete_allowed": False,
        }

    def restore_sources(
        self,
        dataset_ids: list[str],
        *,
        actor: str = "system",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        changed_at = self._utc(now)
        self._ensure_schema()
        restored = []
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for dataset_id in sorted(set(dataset_ids)):
                cursor = connection.execute(
                    "UPDATE autoclean_datasets SET status='READY' WHERE dataset_id=? AND status='SUPERSEDED'",
                    (dataset_id,),
                )
                if not cursor.rowcount:
                    continue
                connection.execute(
                    "INSERT INTO unified_dataset_lifecycle "
                    "(dataset_id, status, reason, actor, changed_at) "
                    "VALUES (?, 'RESTORED', 'manual rollback during retention window', ?, ?)",
                    (dataset_id, actor, changed_at.isoformat()),
                )
                restored.append(dataset_id)
            connection.commit()
        return {"status": "RESTORED", "restored_dataset_ids": restored}

    def purge_eligible(
        self,
        *,
        actor: str = "system",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        changed_at = self._utc(now)
        self._ensure_schema()
        state_references = CleanupPreviewService(
            self.database_path,
            self.state_database_path,
        )._state_references()
        purged = []
        skipped = []
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            connection.row_factory = sqlite3.Row
            candidates = connection.execute(
                "SELECT d.dataset_id, d.source_filename, d.source_sha256, d.row_count, d.metadata_json, "
                "l.restore_until FROM autoclean_datasets d "
                "JOIN unified_dataset_lifecycle l ON l.event_id=("
                "SELECT MAX(l2.event_id) FROM unified_dataset_lifecycle l2 WHERE l2.dataset_id=d.dataset_id) "
                "WHERE d.status='SUPERSEDED' AND l.status='SUPERSEDED'"
            ).fetchall()
            for row in candidates:
                dataset_id = str(row["dataset_id"])
                restore_until = datetime.fromisoformat(str(row["restore_until"]))
                if restore_until > changed_at:
                    skipped.append({"dataset_id": dataset_id, "reason": "ROLLBACK_WINDOW_ACTIVE"})
                    continue
                blocking = state_references.get(dataset_id, [])
                if blocking:
                    skipped.append({
                        "dataset_id": dataset_id,
                        "reason": "ACTIVE_STATE_REFERENCES",
                        "references": blocking,
                    })
                    continue
                deleted = self._purge_one(connection, dataset_id)
                connection.execute(
                    "INSERT INTO unified_cleanup_audit "
                    "(dataset_id, action, actor, reason, source_metadata_json, deleted_rows_json, created_at) "
                    "VALUES (?, 'PURGED', ?, 'rollback window elapsed and no active state references', ?, ?, ?)",
                    (
                        dataset_id,
                        actor,
                        json.dumps({
                            "source_filename": row["source_filename"],
                            "source_sha256": row["source_sha256"],
                            "row_count": row["row_count"],
                            "metadata": json.loads(row["metadata_json"] or "{}"),
                        }, ensure_ascii=False, sort_keys=True),
                        json.dumps(deleted, sort_keys=True),
                        changed_at.isoformat(),
                    ),
                )
                purged.append(dataset_id)
            connection.commit()
        return {
            "status": "COMPLETE",
            "purged_dataset_ids": purged,
            "skipped": skipped,
            "raw_source_files_included": False,
        }

    def _purge_one(self, connection, dataset_id: str) -> dict[str, int]:
        tables = []
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ):
            table = str(row[0])
            if table in {"unified_dataset_lifecycle", "unified_cleanup_audit"}:
                continue
            columns = {str(item[1]) for item in connection.execute("PRAGMA table_info(\"{}\")".format(table))}
            if "dataset_id" in columns:
                tables.append(table)
        deleted = {}
        connection.execute("PRAGMA defer_foreign_keys = ON")
        for table in sorted(tables, key=self._delete_priority):
            cursor = connection.execute(
                'DELETE FROM "{}" WHERE dataset_id=?'.format(table.replace('"', '""')),
                (dataset_id,),
            )
            if cursor.rowcount:
                deleted[table] = int(cursor.rowcount)
        return deleted

    def _source_candidates(self, connection, unified_dataset_id: str):
        rows = connection.execute(
            "SELECT dataset_id, source_filename, status, metadata_json FROM autoclean_datasets "
            "WHERE table_name='orders' AND dataset_id<>?",
            (unified_dataset_id,),
        ).fetchall()
        output = []
        for row in rows:
            metadata = json.loads(row["metadata_json"] or "{}")
            if metadata.get("import_origin") not in {"adventureworks", "unified"}:
                continue
            output.append({
                "dataset_id": str(row["dataset_id"]),
                "source_filename": row["source_filename"],
                "status": str(row["status"]),
                "metadata": metadata,
            })
        return output

    @staticmethod
    def _assert_unified_ready(connection, dataset_id: str) -> None:
        row = connection.execute(
            "SELECT d.status, v.status FROM autoclean_datasets d "
            "JOIN unified_dataset_versions v ON v.dataset_id=d.dataset_id WHERE d.dataset_id=?",
            (dataset_id,),
        ).fetchone()
        if row is None or tuple(row) != ("READY", "READY"):
            raise RuntimeError("Unified dataset is not accepted and ready")

    def _ensure_schema(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            connection.executescript(LIFECYCLE_DDL)

    @staticmethod
    def _utc(value: datetime | None) -> datetime:
        resolved = value or datetime.now(timezone.utc)
        return resolved if resolved.tzinfo else resolved.replace(tzinfo=timezone.utc)

    @staticmethod
    def _delete_priority(table: str) -> tuple[int, str]:
        parents = {"autoclean_datasets", "import_batches", "business_orders", "business_order_lines", "orders"}
        return (1 if table in parents else 0, table)
