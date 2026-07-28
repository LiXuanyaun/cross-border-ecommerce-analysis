"""Transactional SQLite persistence for Phase 2 analysis artifacts."""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
from pathlib import Path
import sqlite3
from types import UnionType
from typing import Any, Iterable, Mapping, Union, get_args, get_origin, get_type_hints

from .phase2_models import AnalysisArtifacts, AnalysisRequest, AnalysisWorkItem, WorkItemStatus, _json_value
from .phase2_utils import canonical_json, stable_id, utc_now


SCHEMA_VERSION = 5
DEFAULT_KEEP_LATEST_SCOPES = 8
DEFAULT_SCOPE_TTL_DAYS = 90
DEFAULT_MAX_ENTITY_ASSESSMENTS_PER_SCOPE = 1_000


SCHEMA = """
CREATE TABLE IF NOT EXISTS crossborder_schema_migrations (
    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_runs (
    scope_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, request_json TEXT NOT NULL,
    catalog_versions_json TEXT NOT NULL, status TEXT NOT NULL, error_reason TEXT,
    created_at TEXT NOT NULL, completed_at TEXT,
    unsupported_conclusions_json TEXT
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
CREATE TABLE IF NOT EXISTS topic_detail_cache (
    scope_id TEXT NOT NULL, topic TEXT NOT NULL, ordinal INTEGER NOT NULL,
    search_text TEXT NOT NULL, payload_json TEXT NOT NULL,
    PRIMARY KEY(scope_id, topic, ordinal)
);
CREATE TABLE IF NOT EXISTS analysis_work_items (
    work_item_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, anomaly_id TEXT NOT NULL,
    insight_id TEXT, workflow_status TEXT NOT NULL, owner TEXT NOT NULL,
    due_date TEXT, result_note TEXT NOT NULL, review_result TEXT NOT NULL,
    close_reason TEXT NOT NULL, closed_by TEXT NOT NULL, closed_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(scope_id, anomaly_id)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_scope_metric ON metric_snapshots(scope_id, metric_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_scope_status ON anomalies(scope_id, status, severity);
CREATE INDEX IF NOT EXISTS idx_insights_scope_priority ON insights(scope_id, priority_score DESC);
CREATE INDEX IF NOT EXISTS idx_work_items_scope_status ON analysis_work_items(scope_id, workflow_status);
CREATE INDEX IF NOT EXISTS idx_market_opportunities_scope ON market_opportunities(scope_id, status);
CREATE INDEX IF NOT EXISTS idx_product_opportunities_scope ON product_opportunities(scope_id, opportunity_type);
CREATE INDEX IF NOT EXISTS idx_action_items_scope ON action_items(scope_id, source_type);
CREATE INDEX IF NOT EXISTS idx_topic_detail_cache_scope_topic ON topic_detail_cache(scope_id, topic, ordinal);
"""


def _decode_value(annotation, value):
    if value is None:
        return None
    if annotation is Any:
        return value
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, UnionType):
        for option in args:
            if option is type(None):
                continue
            try:
                return _decode_value(option, value)
            except (TypeError, ValueError):
                continue
        return value
    if origin in (list,):
        item_type = args[0] if args else Any
        return [_decode_value(item_type, item) for item in value]
    if origin in (tuple,):
        if args and args[-1] is Ellipsis:
            return tuple(_decode_value(args[0], item) for item in value)
        return tuple(_decode_value(item_type, item) for item_type, item in zip(args, value))
    if origin in (dict,):
        key_type, value_type = args if len(args) == 2 else (Any, Any)
        return {
            _decode_value(key_type, key): _decode_value(value_type, item)
            for key, item in value.items()
        }
    try:
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            return annotation(value)
    except TypeError:
        pass
    if isinstance(annotation, type) and is_dataclass(annotation):
        hints = get_type_hints(annotation)
        values = {
            item.name: _decode_value(hints.get(item.name, Any), value[item.name])
            for item in fields(annotation)
            if item.name in value
        }
        return annotation(**values)
    return value


def _artifacts_from_payload(payload: Mapping[str, Any]) -> AnalysisArtifacts:
    hints = get_type_hints(AnalysisArtifacts)
    values = {}
    for item in fields(AnalysisArtifacts):
        annotation = hints.get(item.name, Any)
        raw = payload.get(item.name)
        if raw is None and get_origin(annotation) is list:
            raw = []
        values[item.name] = _decode_value(annotation, raw)
    return AnalysisArtifacts(**values)


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
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(analysis_runs)")
            }
            if "unsupported_conclusions_json" not in columns:
                connection.execute("ALTER TABLE analysis_runs ADD COLUMN unsupported_conclusions_json TEXT")
            work_item_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(analysis_work_items)")
            }
            if "result_note" not in work_item_columns:
                connection.execute("ALTER TABLE analysis_work_items ADD COLUMN result_note TEXT NOT NULL DEFAULT ''")
                if "resolution_note" in work_item_columns:
                    connection.execute("UPDATE analysis_work_items SET result_note=resolution_note WHERE result_note=''")
            if "review_result" not in work_item_columns:
                connection.execute("ALTER TABLE analysis_work_items ADD COLUMN review_result TEXT NOT NULL DEFAULT ''")
            if "close_reason" not in work_item_columns:
                connection.execute("ALTER TABLE analysis_work_items ADD COLUMN close_reason TEXT NOT NULL DEFAULT ''")
            if "closed_by" not in work_item_columns:
                connection.execute("ALTER TABLE analysis_work_items ADD COLUMN closed_by TEXT NOT NULL DEFAULT ''")
            if "closed_at" not in work_item_columns:
                connection.execute("ALTER TABLE analysis_work_items ADD COLUMN closed_at TEXT")
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
                "ON CONFLICT(scope_id) DO UPDATE SET status='PROCESSING', error_reason=NULL, completed_at=NULL, unsupported_conclusions_json=NULL",
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

    def load(self, scope_id: str) -> AnalysisArtifacts | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT unsupported_conclusions_json FROM analysis_runs "
                "WHERE scope_id=? AND status='READY'",
                (scope_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            payload: dict[str, Any] = {
                "metric_definitions": self._payload_rows("metric_definitions"),
                "metric_snapshots": self._payload_rows("metric_snapshots", scope_id),
                "entity_assessments": self._payload_rows("entity_assessments", scope_id),
                "data_quality": self._payload_row("data_quality_snapshots", scope_id),
                "data_quality_dimensions": self._payload_rows("data_quality_dimensions", scope_id),
                "field_quality": self._payload_rows("field_quality", scope_id),
                "analysis_capability": self._payload_rows("analysis_capabilities", scope_id),
                "data_improvement_plan": self._payload_rows("data_improvement_plans", scope_id),
                "anomaly_rules": self._payload_rows("anomaly_rules"),
                "anomalies": self._payload_rows("anomalies", scope_id),
                "diagnoses": self._payload_rows("diagnoses", scope_id),
                "recommendation_rules": self._payload_rows("recommendation_rules"),
                "recommendations": self._payload_rows("recommendations", scope_id),
                "evidence": self._payload_rows("evidence_bundles", scope_id),
                "insights": self._payload_rows("insights", scope_id),
                "market_opportunities": self._payload_rows("market_opportunities", scope_id),
                "product_opportunities": self._payload_rows("product_opportunities", scope_id),
                "action_items": self._payload_rows("action_items", scope_id),
                "opportunity_summary": self._payload_row("opportunity_summaries", scope_id) or {},
                "unsupported_conclusions": json.loads(row["unsupported_conclusions_json"] or "[]"),
            }
            return _artifacts_from_payload(payload)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError("Stored artifacts are invalid for scope {}: {}".format(scope_id, exc)) from exc

    def _payload_rows(self, table: str, scope_id: str | None = None) -> list[dict[str, Any]]:
        with self.connection() as connection:
            if scope_id is None:
                rows = connection.execute("SELECT payload_json FROM {} ORDER BY rowid".format(table)).fetchall()
            elif table == "diagnoses":
                rows = connection.execute(
                    "SELECT payload_json FROM diagnoses WHERE anomaly_id IN "
                    "(SELECT anomaly_id FROM anomalies WHERE scope_id=?) ORDER BY rowid",
                    (scope_id,),
                ).fetchall()
            elif table == "recommendations":
                rows = connection.execute(
                    "SELECT payload_json FROM recommendations WHERE diagnosis_id IN "
                    "(SELECT diagnosis_id FROM diagnoses WHERE anomaly_id IN "
                    "(SELECT anomaly_id FROM anomalies WHERE scope_id=?)) ORDER BY rowid",
                    (scope_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT payload_json FROM {} WHERE scope_id=? ORDER BY rowid".format(table), (scope_id,)
                ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def _payload_row(self, table: str, scope_id: str) -> dict[str, Any] | None:
        rows = self._payload_rows(table, scope_id)
        return rows[0] if rows else None

    def capacity(self) -> dict[str, Any]:
        database_file = self.path if self.path.exists() else None
        wal_file = Path(str(self.path) + "-wal")
        shm_file = Path(str(self.path) + "-shm")
        file_bytes = {
            "database": database_file.stat().st_size if database_file else 0,
            "wal": wal_file.stat().st_size if wal_file.exists() else 0,
            "shm": shm_file.stat().st_size if shm_file.exists() else 0,
        }
        with self.connection() as connection:
            statuses = {
                row["status"]: int(row["count"])
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS count FROM analysis_runs GROUP BY status"
                )
            }
            counts = {
                table: int(connection.execute("SELECT COUNT(*) FROM {}".format(table)).fetchone()[0])
                for table in (
                    "analysis_runs", "metric_snapshots", "entity_assessments",
                    "anomalies", "diagnoses", "recommendations", "evidence_bundles",
                    "insights", "market_opportunities", "product_opportunities",
                    "action_items", "topic_detail_cache",
                )
            }
            latest_runs = [
                dict(row) for row in connection.execute(
                    "SELECT scope_id, status, created_at, completed_at FROM analysis_runs "
                    "ORDER BY COALESCE(completed_at, created_at) DESC LIMIT 10"
                )
            ]
        ready_scopes = int(statuses.get("READY", 0))
        total_bytes = sum(file_bytes.values())
        recommendations = []
        if ready_scopes > DEFAULT_KEEP_LATEST_SCOPES:
            recommendations.append(
                "当前 READY scope 超过 {} 个，建议保留最近 {} 个并清理旧 scope".format(
                    DEFAULT_KEEP_LATEST_SCOPES, DEFAULT_KEEP_LATEST_SCOPES,
                )
            )
        if total_bytes > 200 * 1024 * 1024:
            recommendations.append("数据库超过 200MB，建议执行 scope 清理或归档历史分析范围")
        if not recommendations:
            recommendations.append("容量处于健康范围，保持重复 scope 命中缓存")
        return {
            "database_path": str(self.path.resolve()),
            "database_bytes": total_bytes,
            "file_bytes": file_bytes,
            "scope_statuses": statuses,
            "record_counts": counts,
            "latest_runs": latest_runs,
            "retention_policy": {
                "keep_latest_default": DEFAULT_KEEP_LATEST_SCOPES,
                "ttl_days_default": DEFAULT_SCOPE_TTL_DAYS,
                "max_entity_assessments_per_scope": DEFAULT_MAX_ENTITY_ASSESSMENTS_PER_SCOPE,
            },
            "cleanup_recommendations": recommendations,
        }

    def save_topic_details(self, scope_id: str, topic: str, rows: Iterable[Mapping[str, Any]]) -> None:
        normalized = [
            (
                scope_id,
                topic,
                ordinal,
                str(row).casefold(),
                json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            )
            for ordinal, row in enumerate(rows)
        ]
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM topic_detail_cache WHERE scope_id=? AND topic=?", (scope_id, topic)
            )
            if normalized:
                connection.executemany(
                    "INSERT INTO topic_detail_cache(scope_id,topic,ordinal,search_text,payload_json) "
                    "VALUES(?,?,?,?,?)",
                    normalized,
                )
            connection.commit()

    def topic_details_page(
        self, scope_id: str, topic: str, search: str, page: int, page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        if page < 1 or page_size < 1:
            raise ValueError("page and page_size must be positive")
        where = "scope_id=? AND topic=?"
        params: list[Any] = [scope_id, topic]
        if search:
            where += " AND instr(search_text, ?) > 0"
            params.append(search.casefold())
        offset = (page - 1) * page_size
        with self.connection() as connection:
            total = int(connection.execute(
                "SELECT COUNT(*) FROM topic_detail_cache WHERE " + where, params
            ).fetchone()[0])
            rows = connection.execute(
                "SELECT payload_json FROM topic_detail_cache WHERE " + where +
                " ORDER BY ordinal LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows], total

    def clear_topic_detail_cache(self) -> int:
        with self.connection() as connection:
            cursor = connection.execute("DELETE FROM topic_detail_cache")
            connection.commit()
        return int(cursor.rowcount)

    def trim_entity_assessments(
        self,
        max_per_scope: int = DEFAULT_MAX_ENTITY_ASSESSMENTS_PER_SCOPE,
        *,
        keep_low_sample: bool = False,
    ) -> int:
        max_per_scope = max(0, int(max_per_scope))
        with self.connection() as connection:
            scopes = [
                str(row["scope_id"])
                for row in connection.execute(
                    "SELECT DISTINCT scope_id FROM entity_assessments WHERE assessment_type='sku_lifecycle'"
                )
            ]
            delete_ids: list[str] = []
            for scope_id in scopes:
                rows = connection.execute(
                    "SELECT assessment_id, payload_json FROM entity_assessments "
                    "WHERE scope_id=? AND assessment_type='sku_lifecycle'",
                    (scope_id,),
                ).fetchall()
                ranked = []
                for row in rows:
                    try:
                        payload = json.loads(row["payload_json"])
                    except json.JSONDecodeError:
                        payload = {}
                    value = str(payload.get("value") or "")
                    sample_size = int(payload.get("sample_size") or 0)
                    low_sample = value == "低样本"
                    ranked.append((low_sample, -sample_size, str(row["assessment_id"])))
                ranked.sort()
                candidates = ranked if keep_low_sample else [
                    item for item in ranked if not item[0]
                ]
                if max_per_scope == 0:
                    candidates = []
                else:
                    candidates = candidates[:max_per_scope]
                keep_ids = {assessment_id for _, _, assessment_id in candidates}
                for _, _, assessment_id in ranked:
                    if assessment_id not in keep_ids:
                        delete_ids.append(assessment_id)
            if not delete_ids:
                return 0
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                "DELETE FROM entity_assessments WHERE assessment_id=?",
                [(assessment_id,) for assessment_id in delete_ids],
            )
            connection.commit()
        return len(delete_ids)

    def archive_scope(self, scope_id: str) -> bool:
        with self.connection() as connection:
            cursor = connection.execute(
                "UPDATE analysis_runs SET status='ARCHIVED' WHERE scope_id=? AND status!='PROCESSING'",
                (scope_id,),
            )
            connection.commit()
        return cursor.rowcount > 0

    def cleanup_scopes(
        self,
        keep_latest: int = DEFAULT_KEEP_LATEST_SCOPES,
        ttl_days: int | None = None,
    ) -> list[str]:
        keep_latest = max(0, int(keep_latest))
        ttl_days = None if ttl_days is None else max(0, int(ttl_days))
        cutoff = None
        if ttl_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT scope_id, COALESCE(completed_at, created_at) AS activity_at "
                "FROM analysis_runs WHERE status!='PROCESSING' "
                "ORDER BY activity_at DESC",
            ).fetchall()
            scope_ids = []
            for index, row in enumerate(rows):
                should_remove = index >= keep_latest
                if cutoff is not None:
                    try:
                        activity_at = datetime.fromisoformat(str(row["activity_at"]).replace("Z", "+00:00"))
                        should_remove = should_remove or activity_at < cutoff
                    except ValueError:
                        should_remove = True
                if should_remove:
                    scope_ids.append(str(row["scope_id"]))
            if not scope_ids:
                return []
            connection.execute("BEGIN IMMEDIATE")
            for scope_id in scope_ids:
                self._delete_scope_records(connection, scope_id)
            connection.commit()
        return scope_ids

    def cleanup_dataset_scopes(self, dataset_ids: Iterable[str]) -> list[str]:
        ids = [str(item) for item in dataset_ids if item]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self.connection() as connection:
            scope_ids = [
                str(row["scope_id"])
                for row in connection.execute(
                    "SELECT scope_id FROM analysis_runs "
                    "WHERE status!='PROCESSING' AND dataset_id IN ({})".format(placeholders),
                    ids,
                )
            ]
            if not scope_ids:
                return []
            connection.execute("BEGIN IMMEDIATE")
            for scope_id in scope_ids:
                self._delete_scope_records(connection, scope_id)
            connection.commit()
        return scope_ids

    @staticmethod
    def _delete_scope_records(connection, scope_id: str) -> None:
        connection.execute(
            "DELETE FROM recommendations WHERE diagnosis_id IN ("
            "SELECT diagnosis_id FROM diagnoses WHERE anomaly_id IN ("
            "SELECT anomaly_id FROM anomalies WHERE scope_id=?))",
            (scope_id,),
        )
        connection.execute(
            "DELETE FROM diagnoses WHERE anomaly_id IN (SELECT anomaly_id FROM anomalies WHERE scope_id=?)",
            (scope_id,),
        )
        for table in (
            "metric_snapshots", "entity_assessments", "data_quality_snapshots",
            "data_quality_dimensions", "field_quality", "analysis_capabilities",
            "data_improvement_plans", "anomalies", "evidence_bundles", "insights",
            "market_opportunities", "product_opportunities", "action_items",
            "opportunity_summaries", "topic_detail_cache", "analysis_work_items",
        ):
            connection.execute("DELETE FROM {} WHERE scope_id=?".format(table), (scope_id,))
        connection.execute("DELETE FROM analysis_runs WHERE scope_id=?", (scope_id,))

    def compact(self) -> bool:
        if not self.path.exists():
            return False
        with self.connection() as connection:
            try:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.OperationalError:
                pass
            connection.execute("VACUUM")
        return True

    def maintenance_cleanup(
        self,
        keep_latest: int = DEFAULT_KEEP_LATEST_SCOPES,
        ttl_days: int | None = DEFAULT_SCOPE_TTL_DAYS,
        *,
        compact: bool = True,
    ) -> list[str]:
        removed = self.cleanup_scopes(keep_latest=keep_latest, ttl_days=ttl_days)
        if removed and compact:
            self.compact()
        return removed

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
                connection.execute(
                    "UPDATE analysis_runs SET status='READY', completed_at=?, unsupported_conclusions_json=? WHERE scope_id=?",
                    (
                        utc_now(),
                        json.dumps(artifacts.unsupported_conclusions, ensure_ascii=False, separators=(",", ":")),
                        scope_id,
                    ),
                )
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
            row["result_note"], row["review_result"], row["close_reason"],
            row["closed_by"], row["closed_at"], row["updated_at"],
        ) for row in rows]

    def save_work_item(
        self, scope_id: str, anomaly_id: str, insight_id: str | None,
        workflow_status: WorkItemStatus | str, owner: str,
        due_date: str | None, result_note: str, review_result: str = "",
        close_reason: str = "", closed_by: str = "", closed_at: str | None = None,
    ) -> AnalysisWorkItem:
        status = WorkItemStatus(str(workflow_status))
        item = AnalysisWorkItem(
            stable_id("work", scope_id, anomaly_id), scope_id, anomaly_id, insight_id,
            status, owner.strip(), due_date or None, result_note.strip(),
            review_result.strip(), close_reason.strip(), closed_by.strip(), closed_at, utc_now(),
        )
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO analysis_work_items("
                "work_item_id,scope_id,anomaly_id,insight_id,workflow_status,owner,due_date,"
                "result_note,review_result,close_reason,closed_by,closed_at,updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(scope_id, anomaly_id) DO UPDATE SET "
                "insight_id=excluded.insight_id, workflow_status=excluded.workflow_status, "
                "owner=excluded.owner, due_date=excluded.due_date, "
                "result_note=excluded.result_note, review_result=excluded.review_result, "
                "close_reason=excluded.close_reason, closed_by=excluded.closed_by, "
                "closed_at=excluded.closed_at, updated_at=excluded.updated_at",
                (
                    item.work_item_id, item.scope_id, item.anomaly_id, item.insight_id,
                    str(item.workflow_status), item.owner, item.due_date,
                    item.result_note, item.review_result, item.close_reason,
                    item.closed_by, item.closed_at, item.updated_at,
                ),
            )
            connection.commit()
        return item
