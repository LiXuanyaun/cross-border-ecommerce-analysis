from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from crossborder_analytics.unified_dataset import (
    CleanupPreviewService,
    USD_TO_CNY_RATE,
    UnifiedDatasetPreviewService,
)
from crossborder_analytics.unified_materialization import UnifiedDatasetMaterializationService
from crossborder_analytics.unified_lifecycle import UnifiedDatasetLifecycleService
from crossborder_analytics.database import CrossBorderDatabase
from crossborder_analytics.multibusiness_import import MultiBusinessImportService
from crossborder_analytics.service import AnalysisService
from crossborder_api.main import app, runtime


ADVENTUREWORKS_FIXTURE = Path(__file__).parent / "fixtures" / "adventureworks_v4"


def _write_demo_source(path: Path) -> None:
    path.write_text(
        "order_id,customer_id,product_id,category,price,discount,quantity,order_date,total_amount\n"
        "D-1,C-1,P-1,Clothing,10,0,1,2025-01-01,10\n"
        "D-2,C-2,P-2,Electronics,20,0,1,2025-01-02,20\n",
        encoding="utf-8",
    )


def test_merge_preview_resolves_v1_policy_without_writing_sources(tmp_path):
    demo_path = tmp_path / "demo.csv"
    _write_demo_source(demo_path)
    before = hashlib.sha256(demo_path.read_bytes()).hexdigest()

    preview = UnifiedDatasetPreviewService(demo_path, ADVENTUREWORKS_FIXTURE).preview()

    assert preview["status"] == "READY"
    assert preview["can_materialize"] is True
    assert preview["blocking_checks"] == []
    assert preview["duplicate_preview"]["status"] == "COMPLETE"
    assert preview["duplicate_preview"]["fuzzy_matching_performed"] is False
    assert preview["row_reconciliation"] == {
        "input_rows": 5,
        "retained_rows": 5,
        "duplicate_rows": 0,
        "quarantined_rows": 0,
        "difference": 0,
    }
    expected = (
        preview["amount_reconciliation"]["source_amounts"]["demo-all"]
        + preview["amount_reconciliation"]["source_amounts"][preview["sources"][1]["dataset_id"]]
        * USD_TO_CNY_RATE
    )
    assert preview["amount_reconciliation"]["status"] == "RECONCILED"
    assert preview["amount_reconciliation"]["unified_amount"] == expected
    assert all(item["read_only"] for item in preview["source_files"])
    assert hashlib.sha256(demo_path.read_bytes()).hexdigest() == before
    assert list(tmp_path.iterdir()) == [demo_path]


def test_materialization_publishes_orders_lineage_and_business_facts_atomically(tmp_path):
    demo_path = tmp_path / "demo.csv"
    database = tmp_path / "analysis.db"
    _write_demo_source(demo_path)
    source_hash = hashlib.sha256(demo_path.read_bytes()).hexdigest()
    core = AnalysisService(database_path=database)
    imported = MultiBusinessImportService(database, core).import_directory(ADVENTUREWORKS_FIXTURE)
    service = UnifiedDatasetMaterializationService(
        demo_path,
        ADVENTUREWORKS_FIXTURE,
        database,
    )

    first = service.materialize()
    second = service.materialize()

    assert first["status"] == "READY"
    assert first["row_count"] == 5
    assert first["reused"] is False
    assert second == {**first, "reused": True}
    assert hashlib.sha256(demo_path.read_bytes()).hexdigest() == source_hash
    context = CrossBorderDatabase(database).load_context(first["dataset_id"])
    assert context is not None
    core.run(context)
    with sqlite3.connect(database) as connection:
        dataset_id = first["dataset_id"]
        assert connection.execute(
            "SELECT status FROM autoclean_datasets WHERE dataset_id=?", (dataset_id,),
        ).fetchone()[0] == "READY"
        assert connection.execute(
            "SELECT COUNT(*) FROM orders WHERE dataset_id=?", (dataset_id,),
        ).fetchone()[0] == 5
        assert connection.execute(
            "SELECT COUNT(*) FROM unified_order_lineage WHERE dataset_id=?", (dataset_id,),
        ).fetchone()[0] == 5
        assert connection.execute(
            "SELECT COUNT(*) FROM autoclean_datasets WHERE json_extract(metadata_json, '$.import_origin')='unified'",
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM fact_returns WHERE dataset_id=?", (dataset_id,),
        ).fetchone()[0] == connection.execute(
            "SELECT COUNT(*) FROM fact_returns WHERE dataset_id=?", (imported["dataset_id"],),
        ).fetchone()[0]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_cleanup_preview_marks_referenced_duplicate_as_skipped(tmp_path):
    database = tmp_path / "analysis.db"
    state_database = tmp_path / "state.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE autoclean_datasets (
                dataset_id TEXT PRIMARY KEY,
                source_sha256 TEXT,
                source_filename TEXT,
                row_count INTEGER,
                status TEXT,
                metadata_json TEXT,
                created_at TEXT
            );
            CREATE TABLE orders (dataset_id TEXT, record_id TEXT);
            CREATE TABLE analysis_runs (dataset_id TEXT, run_id TEXT);
            """
        )
        connection.executemany(
            "INSERT INTO autoclean_datasets VALUES (?, 'same-hash', 'orders.csv', 2, 'READY', '{}', ?)",
            (("old", "2026-07-01"), ("new", "2026-07-02")),
        )
        connection.executemany(
            "INSERT INTO orders VALUES (?, ?)",
            (("old", "old-1"), ("old", "old-2"), ("new", "new-1"), ("new", "new-2")),
        )
        connection.execute("INSERT INTO analysis_runs VALUES ('old', 'run-1')")
    with sqlite3.connect(state_database) as connection:
        connection.execute("CREATE TABLE agent_sessions (dataset_id TEXT, session_id TEXT)")
        connection.execute("INSERT INTO agent_sessions VALUES ('old', 'session-1')")

    preview = CleanupPreviewService(database, state_database).preview()
    targets = {item["dataset_id"]: item for item in preview["targets"]}

    assert preview["physical_delete_allowed"] is False
    assert preview["raw_source_files_included"] is False
    assert targets["old"]["duplicate_candidate"] is True
    assert targets["old"]["planned_action"] == "SKIP_REFERENCED"
    assert {item["table"] for item in targets["old"]["references"]} >= {
        "orders", "analysis_runs", "agent_sessions",
    }
    assert targets["new"]["planned_action"] == "KEEP"


def test_source_lifecycle_restores_and_time_gates_physical_cleanup(tmp_path):
    demo_path = tmp_path / "demo.csv"
    database = tmp_path / "analysis.db"
    state_database = tmp_path / "state.db"
    _write_demo_source(demo_path)
    source_hash = hashlib.sha256(demo_path.read_bytes()).hexdigest()
    core = AnalysisService(database_path=database)
    imported = MultiBusinessImportService(database, core).import_directory(ADVENTUREWORKS_FIXTURE)
    unified = UnifiedDatasetMaterializationService(
        demo_path, ADVENTUREWORKS_FIXTURE, database, state_database,
    ).materialize()
    lifecycle = UnifiedDatasetLifecycleService(database, state_database)
    started = datetime(2026, 7, 31, tzinfo=timezone.utc)

    deactivated = lifecycle.deactivate_sources(unified["dataset_id"], now=started)
    restored = lifecycle.restore_sources(deactivated["deactivated_dataset_ids"], now=started)
    lifecycle.deactivate_sources(unified["dataset_id"], now=started)
    with sqlite3.connect(state_database) as connection:
        connection.execute("CREATE TABLE agent_sessions (dataset_id TEXT, session_id TEXT)")
        connection.execute(
            "INSERT INTO agent_sessions VALUES (?, 'session-1')", (imported["dataset_id"],),
        )

    blocked = lifecycle.purge_eligible(now=started + timedelta(days=8))
    with sqlite3.connect(state_database) as connection:
        connection.execute("DELETE FROM agent_sessions")
    purged = lifecycle.purge_eligible(now=started + timedelta(days=8))

    assert deactivated["physical_delete_allowed"] is False
    assert restored["restored_dataset_ids"] == [imported["dataset_id"]]
    assert blocked["skipped"][0]["reason"] == "ACTIVE_STATE_REFERENCES"
    assert purged["purged_dataset_ids"] == [imported["dataset_id"]]
    assert hashlib.sha256(demo_path.read_bytes()).hexdigest() == source_hash
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT status FROM autoclean_datasets WHERE dataset_id=?", (unified["dataset_id"],),
        ).fetchone()[0] == "READY"
        assert connection.execute(
            "SELECT COUNT(*) FROM unified_cleanup_audit WHERE dataset_id=?", (imported["dataset_id"],),
        ).fetchone()[0] == 1


def test_unified_dataset_preview_api_uses_runtime_service(monkeypatch):
    monkeypatch.setattr(runtime, "unified_dataset_preview", lambda: {
        "status": "BLOCKED",
        "can_materialize": False,
    })

    with TestClient(app) as client:
        response = client.get("/api/v1/maintenance/unified-dataset/preview")

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "BLOCKED", "can_materialize": False}
