"""Transactional SQLite persistence for Phase 2 analysis artifacts."""
from __future__ import annotations

from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping

from .phase2_models import AnalysisArtifacts, AnalysisRequest, AnalysisWorkItem, WorkItemStatus
from .phase2_utils import canonical_json, stable_id, utc_now


SCHEMA_VERSION = 5


SCHEMA = """
CREATE TABLE IF NOT EXISTS crossborder_schema_migrations (
    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_runs (
    scope_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, request_json TEXT NOT NULL,
    catalog_versions_json TEXT NOT NULL, status TEXT NOT NULL, error_reason TEXT,
    created_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS metric_definitions (
    metric_id TEXT NOT NULL, version TEXT NOT NULL, payload_json TEXT NOT NULL,
    PRIMARY KEY(metric_id, version)
);
CREATE TABLE IF NOT EXISTS metric_snapshots (
    snapshot_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, scope_id TEXT NOT NULL,
    metric_id TEXT NOT NULL, metric_version TEXT NOT NULL, entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL, period_type TEXT NOT NULL, period_start TEXT NOT NULL,
    period_end TEXT NOT NULL, current_value REAL, sample_size INTEGER NOT NULL,
    evidence_id TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_metric_snapshot_business_key ON metric_snapshots(
    dataset_id, scope_id, metric_id, metric_version, entity_type, entity_id,
    period_type, period_start, period_end
);
CREATE TABLE IF NOT EXISTS entity_assessments (
    assessment_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, scope_id TEXT NOT NULL,
    assessment_type TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS data_quality_snapshots (
    scope_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, quality_score REAL NOT NULL,
    quality_rating TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS data_quality_dimensions (
    scope_id TEXT NOT NULL, dimension TEXT NOT NULL, payload_json TEXT NOT NULL,
    PRIMARY KEY(scope_id, dimension)
);
CREATE TABLE IF NOT EXISTS field_quality (
    scope_id TEXT NOT NULL, field TEXT NOT NULL, payload_json TEXT NOT NULL,
    PRIMARY KEY(scope_id, field)
);
CREATE TABLE IF NOT EXISTS analysis_capabilities (
    scope_id TEXT NOT NULL, capability_id TEXT NOT NULL, status TEXT NOT NULL,
    payload_json TEXT NOT NULL, PRIMARY KEY(scope_id, capability_id)
);
CREATE TABLE IF NOT EXISTS data_improvement_plans (
    scope_id TEXT NOT NULL, improvement_id TEXT NOT NULL, priority TEXT NOT NULL,
    payload_json TEXT NOT NULL, PRIMARY KEY(scope_id, improvement_id)
);
CREATE TABLE IF NOT EXISTS anomaly_rules (
    rule_id TEXT NOT NULL, version TEXT NOT NULL, payload_json TEXT NOT NULL,
    PRIMARY KEY(rule_id, version)
);
CREATE TABLE IF NOT EXISTS anomalies (
    anomaly_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, scope_id TEXT NOT NULL,
    rule_id TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
    status TEXT NOT NULL, severity TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS diagnoses (
    diagnosis_id TEXT PRIMARY KEY, anomaly_id TEXT NOT NULL, status TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recommendation_rules (
    recommendation_rule_id TEXT NOT NULL, version TEXT NOT NULL, payload_json TEXT NOT NULL,
    PRIMARY KEY(recommendation_rule_id, version)
);
CREATE TABLE IF NOT EXISTS recommendations (
    recommendation_id TEXT PRIMARY KEY, diagnosis_id TEXT NOT NULL, action_type TEXT NOT NULL,
    priority TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence_bundles (
    evidence_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, scope_id TEXT NOT NULL,
    query_name TEXT NOT NULL, query_version TEXT NOT NULL, result_digest TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS insights (
    insight_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, priority TEXT NOT NULL,
    priority_score REAL NOT NULL, severity TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_opportunities (
    opportunity_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, market TEXT NOT NULL,
    status TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS product_opportunities (
    opportunity_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, product_id TEXT NOT NULL,
    opportunity_type TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS action_items (
    action_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, source_type TEXT NOT NULL,
    entity_id TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS opportunity_summaries (
    scope_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_work_items (
    work_item_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, anomaly_id TEXT NOT NULL,
    insight_id TEXT, workflow_status TEXT NOT NULL, owner TEXT NOT NULL,
    due_date TEXT, resolution_note TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(scope_id, anomaly_id)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_scope_metric ON metric_snapshots(scope_id, metric_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_scope_status ON anomalies(scope_id, status, severity);
CREATE INDEX IF NOT EXISTS idx_insights_scope_priority ON insights(scope_id, priority_score DESC);
CREATE INDEX IF NOT EXISTS idx_work_items_scope_status ON analysis_work_items(scope_id, workflow_status);
CREATE INDEX IF NOT EXISTS idx_market_opportunities_scope ON market_opportunities(scope_id, status);
CREATE INDEX IF NOT EXISTS idx_product_opportunities_scope ON product_opportunities(scope_id, opportunity_type);
CREATE INDEX IF NOT EXISTS idx_action_items_scope ON action_items(scope_id, source_type);
"""


class ArtifactStore:
    def __init__(self, path: Any):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO crossborder_schema_migrations(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, utc_now()),
            )
            connection.commit()

    def begin_run(self, scope_id: str, dataset_id: str, request: AnalysisRequest, catalog_versions: Mapping[str, str]) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO analysis_runs(scope_id,dataset_id,request_json,catalog_versions_json,status,error_reason,created_at,completed_at) "
                "VALUES(?,?,?,?, 'PROCESSING', NULL, ?, NULL) "
                "ON CONFLICT(scope_id) DO UPDATE SET status='PROCESSING', error_reason=NULL, completed_at=NULL",
                (scope_id, dataset_id, canonical_json(request.to_dict()), canonical_json(catalog_versions), utc_now()),
            )
            connection.commit()

    def fail_run(self, scope_id: str, error: Exception) -> None:
        with self.connection() as connection:
            connection.execute(
                "UPDATE analysis_runs SET status='FAILED', error_reason=?, completed_at=? WHERE scope_id=?",
                (str(error)[:2000], utc_now(), scope_id),
            )
            connection.commit()

    @staticmethod
    def _payload(item) -> str:
        value = item.__dict__ if hasattr(item, "__dict__") else item
        return json.dumps(
            value, ensure_ascii=False, separators=(",", ":"),
            default=lambda nested: nested.item() if hasattr(nested, "item") else str(nested),
        )

    def save(self, scope_id: str, artifacts: AnalysisArtifacts) -> None:
        with self.connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.executemany(
                    "INSERT OR REPLACE INTO metric_definitions VALUES(?,?,?)",
                    [(item.metric_id, item.version, self._payload(item)) for item in artifacts.metric_definitions],
                )
                connection.executemany(
                    "INSERT OR REPLACE INTO metric_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(item.snapshot_id, item.dataset_id, item.scope_id, item.metric_id, item.metric_version,
                      item.entity_type, item.entity_id, item.period_type, item.period_start, item.period_end,
                      item.current_value, item.sample_size, item.evidence_id, self._payload(item))
                     for item in artifacts.metric_snapshots],
                )
                connection.executemany(
                    "INSERT OR REPLACE INTO entity_assessments VALUES(?,?,?,?,?,?,?)",
                    [(item.assessment_id, item.dataset_id, item.scope_id, item.assessment_type,
                      item.entity_type, item.entity_id, self._payload(item)) for item in artifacts.entity_assessments],
                )
                if artifacts.data_quality:
                    item = artifacts.data_quality
                    connection.execute("INSERT OR REPLACE INTO data_quality_snapshots VALUES(?,?,?,?,?)", (
                        item.scope_id, item.dataset_id, item.quality_score, str(item.quality_rating), self._payload(item),
                    ))
                self._save_list(connection, "data_quality_dimensions", artifacts.data_quality_dimensions, lambda x: (scope_id, x.dimension, self._payload(x)))
                self._save_list(connection, "field_quality", artifacts.field_quality, lambda x: (scope_id, x.field, self._payload(x)))
                self._save_list(connection, "analysis_capabilities", artifacts.analysis_capability, lambda x: (scope_id, x.capability_id, str(x.status), self._payload(x)))
                self._save_list(connection, "data_improvement_plans", artifacts.data_improvement_plan, lambda x: (scope_id, x.improvement_id, x.priority, self._payload(x)))
                self._save_list(connection, "anomaly_rules", artifacts.anomaly_rules, lambda x: (x.rule_id, x.version, self._payload(x)))
                self._save_list(connection, "anomalies", artifacts.anomalies, lambda x: (x.anomaly_id, x.dataset_id, x.scope_id, x.rule_id, x.entity_type, x.entity_id, str(x.status), str(x.severity), self._payload(x)))
                self._save_list(connection, "diagnoses", artifacts.diagnoses, lambda x: (x.diagnosis_id, x.anomaly_id, str(x.status), self._payload(x)))
                self._save_list(connection, "recommendation_rules", artifacts.recommendation_rules, lambda x: (x.recommendation_rule_id, x.version, self._payload(x)))
                self._save_list(connection, "recommendations", artifacts.recommendations, lambda x: (x.recommendation_id, x.diagnosis_id, str(x.action_type), x.priority, self._payload(x)))
                self._save_list(connection, "evidence_bundles", artifacts.evidence, lambda x: (x.evidence_id, x.dataset_id, x.scope_id, x.query_name, x.query_version, x.result_digest, self._payload(x)))
                self._save_list(connection, "insights", artifacts.insights, lambda x: (x.insight_id, scope_id, x.priority, x.priority_score, x.severity, self._payload(x)))
                connection.execute("DELETE FROM market_opportunities WHERE scope_id=?", (scope_id,))
                connection.execute("DELETE FROM product_opportunities WHERE scope_id=?", (scope_id,))
                connection.execute("DELETE FROM action_items WHERE scope_id=?", (scope_id,))
                self._save_list(connection, "market_opportunities", artifacts.market_opportunities, lambda x: (x.opportunity_id, scope_id, x.market, str(x.status), self._payload(x)))
                self._save_list(connection, "product_opportunities", artifacts.product_opportunities, lambda x: (x.opportunity_id, scope_id, x.product_id, str(x.opportunity_type), self._payload(x)))
                self._save_list(connection, "action_items", artifacts.action_items, lambda x: (x.action_id, scope_id, x.source_type, x.entity_id, self._payload(x)))
                connection.execute(
                    "INSERT OR REPLACE INTO opportunity_summaries VALUES(?,?)",
                    (scope_id, self._payload(artifacts.opportunity_summary)),
                )
                connection.execute("UPDATE analysis_runs SET status='READY', completed_at=? WHERE scope_id=?", (utc_now(), scope_id))
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _save_list(connection, table: str, items: Iterable[Any], values) -> None:
        rows = [values(item) for item in items]
        if not rows:
            return
        placeholders = ",".join("?" for _ in rows[0])
        connection.executemany("INSERT OR REPLACE INTO {} VALUES({})".format(table, placeholders), rows)

    def payload(self, table: str, key_field: str, key: str) -> Mapping[str, Any] | None:
        allowed = {
            "metric_snapshots": "snapshot_id", "evidence_bundles": "evidence_id",
            "anomalies": "anomaly_id", "diagnoses": "diagnosis_id",
            "recommendations": "recommendation_id", "insights": "insight_id",
            "market_opportunities": "opportunity_id",
            "product_opportunities": "opportunity_id", "action_items": "action_id",
        }
        if allowed.get(table) != key_field:
            raise ValueError("Unsupported artifact lookup")
        with self.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM {} WHERE {}=?".format(table, key_field), (key,)
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def work_items(self, scope_id: str) -> list[AnalysisWorkItem]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM analysis_work_items WHERE scope_id=? ORDER BY updated_at DESC, work_item_id",
                (scope_id,),
            ).fetchall()
        return [AnalysisWorkItem(
            row["work_item_id"], row["scope_id"], row["anomaly_id"], row["insight_id"],
            WorkItemStatus(row["workflow_status"]), row["owner"], row["due_date"],
            row["resolution_note"], row["updated_at"],
        ) for row in rows]

    def save_work_item(
        self, scope_id: str, anomaly_id: str, insight_id: str | None,
        workflow_status: WorkItemStatus | str, owner: str,
        due_date: str | None, resolution_note: str,
    ) -> AnalysisWorkItem:
        status = WorkItemStatus(str(workflow_status))
        item = AnalysisWorkItem(
            stable_id("work", scope_id, anomaly_id), scope_id, anomaly_id, insight_id,
            status, owner.strip(), due_date or None, resolution_note.strip(), utc_now(),
        )
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO analysis_work_items VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(scope_id, anomaly_id) DO UPDATE SET "
                "insight_id=excluded.insight_id, workflow_status=excluded.workflow_status, "
                "owner=excluded.owner, due_date=excluded.due_date, "
                "resolution_note=excluded.resolution_note, updated_at=excluded.updated_at",
                (
                    item.work_item_id, item.scope_id, item.anomaly_id, item.insight_id,
                    str(item.workflow_status), item.owner, item.due_date,
                    item.resolution_note, item.updated_at,
                ),
            )
            connection.commit()
        return item
