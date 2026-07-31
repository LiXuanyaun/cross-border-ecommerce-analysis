"""Versioned SQLite storage and named SQL queries for ecommerce orders."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional
from contextlib import closing
import json
import sqlite3

import pandas as pd

from autoclean.analytics import (
    DatasetContext, SQLiteDatasetStore, SQLiteStorageError, StoredDataset, ValidationIssue,
)
from autoclean.analytics.storage import _json_value, _quote_identifier, _sqlite_type

from .contract import ADVENTUREWORKS_LINK_FIELDS, ECOMMERCE_CONTRACT, ECOMMERCE_STORAGE_CONTRACT


SQL_DIR = Path(__file__).resolve().parent / "sql"
AMOUNT_FIELDS = ("price", "total_amount", "shipping_cost", "profit_amount", "cost_amount", "refund_amount", "ad_spend")
DERIVED_FIELDS = tuple("{}_base".format(field) for field in AMOUNT_FIELDS) + (
    "fx_rate",
    "fx_rate_date",
    "fx_source",
)
CANONICAL_AMOUNT_FIELDS = ("gmv_amount", "gmv_amount_base")
BASE_ORDER_COLUMNS = tuple(field.name for field in ECOMMERCE_CONTRACT.fields) + DERIVED_FIELDS + CANONICAL_AMOUNT_FIELDS
ADVENTUREWORKS_LINK_COLUMNS = tuple(field.name for field in ADVENTUREWORKS_LINK_FIELDS)
ORDER_COLUMNS = BASE_ORDER_COLUMNS + ADVENTUREWORKS_LINK_COLUMNS
LINEAGE_FIELDS = ("source_file_id", "source_row_number")
BASE_ORDER_COLUMNS = ("record_id",) + BASE_ORDER_COLUMNS + LINEAGE_FIELDS
ORDER_COLUMNS = ("record_id",) + ORDER_COLUMNS + LINEAGE_FIELDS


class CrossBorderDatasetStore(SQLiteDatasetStore):
    def _connect(self) -> sqlite3.Connection:
        connection = super()._connect()
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.execute("PRAGMA cache_size = -65536")
        return connection

    def store_context(
        self,
        context: DatasetContext,
        table_name: str,
        dataset_id: Optional[str] = None,
        final_status: str = "READY",
    ) -> StoredDataset:
        """Persist the canonical order frame without per-cell compatibility dispatch."""
        table_sql = _quote_identifier(table_name)
        frame = context.analysis_data.copy()
        if context.fatal_issues:
            raise SQLiteStorageError("Fatal validation issues prevent persistence")
        if frame.columns.duplicated().any():
            raise SQLiteStorageError("Duplicate DataFrame columns prevent persistence")
        for column in frame.columns:
            _quote_identifier(str(column))

        if final_status not in {"READY", "BUILDING"}:
            raise SQLiteStorageError("Unsupported dataset status: {}".format(final_status))
        resolved_id = dataset_id or self._dataset_id(context, table_name)
        existing = self.get_dataset(resolved_id)
        if existing is not None:
            if existing.table_name != table_name:
                raise SQLiteStorageError("Dataset id already belongs to another table")
            return existing

        grain_key = context.contract.grain_key
        if grain_key and grain_key not in frame.columns:
            raise SQLiteStorageError("Dataset grain key is missing: {}".format(grain_key))
        created_at = datetime.now(timezone.utc).isoformat()
        columns = [str(column) for column in frame.columns]
        column_defs = ["dataset_id TEXT NOT NULL"]
        column_defs.extend(
            "{} {}".format(_quote_identifier(column), _sqlite_type(frame[column]))
            for column in columns
        )
        if grain_key:
            column_defs.append(
                "PRIMARY KEY (dataset_id, {})".format(_quote_identifier(grain_key))
            )
        else:
            column_defs.insert(1, "_row_number INTEGER NOT NULL")
            column_defs.append("PRIMARY KEY (dataset_id, _row_number)")

        normalized = _normalize_sqlite_frame(frame)
        records = []
        for row_number, row in enumerate(normalized.itertuples(index=False, name=None)):
            prefix = (resolved_id,) if grain_key else (resolved_id, row_number)
            records.append(prefix + row)

        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO autoclean_datasets ("
                    "dataset_id, table_name, contract_name, source_sha256, source_filename, "
                    "row_count, status, field_mapping_json, semantic_overrides_json, lineage_json, "
                    "metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, 'IMPORTING', ?, ?, ?, ?, ?)",
                    (
                        resolved_id,
                        table_name,
                        context.contract.name,
                        context.metadata.get("sha256"),
                        context.metadata.get("filename"),
                        len(frame),
                        json.dumps(context.field_mapping, ensure_ascii=False, sort_keys=True),
                        json.dumps(context.semantic_overrides, ensure_ascii=False, sort_keys=True),
                        json.dumps(_json_value(context.lineage), ensure_ascii=False, sort_keys=True),
                        json.dumps(_json_value(context.metadata), ensure_ascii=False, sort_keys=True),
                        created_at,
                    ),
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS {} ({})".format(table_sql, ", ".join(column_defs))
                )
                existing_columns = {
                    row["name"] for row in connection.execute("PRAGMA table_info({})".format(table_sql))
                }
                for column in columns:
                    if column not in existing_columns:
                        connection.execute(
                            "ALTER TABLE {} ADD COLUMN {} {}".format(
                                table_sql, _quote_identifier(column), _sqlite_type(frame[column])
                            )
                        )

                insert_columns = ["dataset_id"] + ([] if grain_key else ["_row_number"]) + columns
                insert_sql = "INSERT INTO {} ({}) VALUES ({})".format(
                    table_sql,
                    ", ".join(_quote_identifier(column) for column in insert_columns),
                    ", ".join("?" for _ in insert_columns),
                )
                connection.executemany(insert_sql, records)

                stored_count = connection.execute(
                    "SELECT COUNT(*) FROM {} WHERE dataset_id = ?".format(table_sql),
                    (resolved_id,),
                ).fetchone()[0]
                if int(stored_count) != len(frame):
                    raise SQLiteStorageError(
                        "Stored row count mismatch: expected {}, got {}".format(len(frame), stored_count)
                    )
                if grain_key:
                    unique_count = connection.execute(
                        "SELECT COUNT(DISTINCT {}) FROM {} WHERE dataset_id = ?".format(
                            _quote_identifier(grain_key), table_sql
                        ),
                        (resolved_id,),
                    ).fetchone()[0]
                    if int(unique_count) != len(frame):
                        raise SQLiteStorageError("Stored grain is not unique")

                for issue in context.issues:
                    connection.execute(
                        "INSERT INTO autoclean_dataset_issues ("
                        "dataset_id, severity, code, message, field, row_count, details_json"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            resolved_id,
                            issue.severity,
                            issue.code,
                            issue.message,
                            issue.field,
                            issue.row_count,
                            json.dumps(_json_value(issue.details), ensure_ascii=False, sort_keys=True),
                        ),
                    )
                connection.execute(
                    "UPDATE autoclean_datasets SET status = ? WHERE dataset_id = ?",
                    (final_status, resolved_id),
                )
                connection.commit()
        except (sqlite3.Error, SQLiteStorageError) as exc:
            if isinstance(exc, SQLiteStorageError):
                raise
            raise SQLiteStorageError("Dataset persistence failed: {}".format(exc)) from exc

        return StoredDataset(resolved_id, table_name, len(frame), created_at, reused=False)


def _normalize_sqlite_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert each typed column once before the SQLite batch insert."""
    normalized = pd.DataFrame(index=frame.index)
    for column in frame.columns:
        source = frame[column]
        if pd.api.types.is_datetime64_any_dtype(source.dtype):
            values = source.map(lambda value: value.isoformat() if pd.notna(value) else None)
        elif pd.api.types.is_bool_dtype(source.dtype):
            values = source.astype("Int64").astype(object)
        else:
            values = source.astype(object)
        normalized[column] = values.where(source.notna(), None)
    return normalized


def _missing_series(index: pd.Index, field: str) -> pd.Series:
    spec = ECOMMERCE_CONTRACT.field(field)
    dtype = spec.dtype if spec else None
    if dtype == "float" or field.endswith("_base") or field == "fx_rate":
        return pd.Series(float("nan"), index=index, dtype="float64")
    if dtype == "integer":
        return pd.Series(pd.NA, index=index, dtype="Int64")
    if field == "sales_order_line_number":
        return pd.Series(pd.NA, index=index, dtype="Int64")
    if dtype == "boolean":
        return pd.Series(pd.NA, index=index, dtype="boolean")
    if dtype == "date" or field == "fx_rate_date":
        return pd.Series(pd.NaT, index=index, dtype="datetime64[ns]")
    return pd.Series(pd.NA, index=index, dtype="string")


def storage_frame(context) -> pd.DataFrame:
    frame = context.analysis_data.copy()
    if "record_id" not in frame:
        order_ids = frame.get("order_id", pd.Series(range(len(frame)), index=frame.index)).astype(str)
        frame["record_id"] = "order:" + order_ids
    if "gmv_amount" not in frame and "total_amount" in frame:
        frame["gmv_amount"] = frame["total_amount"]
    if "gmv_amount_base" not in frame:
        source = "total_amount_base" if "total_amount_base" in frame else "total_amount"
        if source in frame:
            frame["gmv_amount_base"] = frame[source]
    storage_columns = (
        ORDER_COLUMNS
        if any(field in frame.columns for field in ADVENTUREWORKS_LINK_COLUMNS)
        else BASE_ORDER_COLUMNS
    )
    for field in storage_columns:
        if field not in frame:
            frame[field] = _missing_series(frame.index, field)
    return frame.loc[:, storage_columns]


class CrossBorderDatabase:
    def __init__(self, path: Any):
        self.path = Path(path)
        self.store = CrossBorderDatasetStore(self.path)

    def persist(
        self,
        context,
        dataset_id: str | None = None,
        *,
        final_status: str = "READY",
    ) -> StoredDataset:
        self._migrate_orders_schema()
        dataset_id = dataset_id or context.metadata.get("dataset_id")
        stored_context = replace(
            context,
            analysis_data=storage_frame(context),
            contract=ECOMMERCE_STORAGE_CONTRACT,
        )
        stored = self.store.store_context(
            stored_context,
            "orders",
            dataset_id=dataset_id,
            final_status=final_status,
        )
        context.metadata.update({
            "database_path": str(self.path.resolve()),
            "database_schema_version": 4,
            "dataset_id": stored.dataset_id,
            "stored_rows": stored.row_count,
            "storage_reused": stored.reused,
            "analysis_backend": "sql",
        })
        return stored

    def _migrate_orders_schema(self) -> None:
        """Move legacy order-key storage to a record-key table without dropping rows."""
        if not self.path.exists():
            return
        with closing(sqlite3.connect(str(self.path))) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'orders'"
            ).fetchone()
            if not exists:
                return
            info = list(connection.execute("PRAGMA table_info(orders)"))
            primary_key = [row[1] for row in sorted(info, key=lambda item: item[5]) if row[5]]
            existing = {row[1]: row for row in info}
            gmv_type = str(existing["gmv_amount_base"][2]).upper() if "gmv_amount_base" in existing else ""
            if primary_key == ["dataset_id", "record_id"] and gmv_type == "REAL":
                return
            desired = list(dict.fromkeys(["dataset_id", *ORDER_COLUMNS]))
            definitions = []
            for column in desired:
                if column == "dataset_id":
                    definitions.append('"dataset_id" TEXT NOT NULL')
                elif column == "record_id":
                    definitions.append('"record_id" TEXT NOT NULL')
                else:
                    if column in CANONICAL_AMOUNT_FIELDS or column.endswith("_base") or column == "fx_rate":
                        sql_type = "REAL"
                    elif column == "source_row_number":
                        sql_type = "INTEGER"
                    else:
                        sql_type = existing.get(column, (None, None, "TEXT"))[2] or "TEXT"
                    definitions.append('"{}" {}'.format(column, sql_type))
            definitions.append('PRIMARY KEY ("dataset_id", "record_id")')
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DROP TABLE IF EXISTS orders_v3_migration")
            connection.execute("CREATE TABLE orders_v3_migration ({})".format(", ".join(definitions)))
            target_columns = []
            select_values = []
            for column in desired:
                target_columns.append('"{}"'.format(column))
                if column == "record_id":
                    if "record_id" in existing:
                        select_values.append(
                            "COALESCE(record_id, 'legacy:' || dataset_id || ':' || COALESCE(order_id, rowid))"
                        )
                    else:
                        select_values.append("'legacy:' || dataset_id || ':' || COALESCE(order_id, rowid)")
                elif column in existing:
                    select_values.append('"{}"'.format(column))
                else:
                    select_values.append("NULL")
            connection.execute(
                "INSERT INTO orders_v3_migration ({}) SELECT {} FROM orders".format(
                    ", ".join(target_columns), ", ".join(select_values)
                )
            )
            connection.execute("DROP TABLE orders")
            connection.execute("ALTER TABLE orders_v3_migration RENAME TO orders")
            connection.commit()

    def list_datasets(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(str(self.path))) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT dataset_id, source_filename, row_count, metadata_json, created_at "
                "FROM autoclean_datasets WHERE table_name = 'orders' AND status = 'READY' "
                "ORDER BY created_at DESC"
            ).fetchall()
        output = []
        for row in rows:
            metadata = _json_object(row["metadata_json"])
            if metadata.get("import_origin") not in {"web", "adventureworks", "unified"}:
                continue
            output.append({
                "dataset_id": row["dataset_id"],
                "filename": row["source_filename"],
                "row_count": int(row["row_count"]),
                "created_at": row["created_at"],
                "metadata": metadata,
            })
        return output

    def load_context(self, dataset_id: str) -> DatasetContext | None:
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(str(self.path))) as connection:
            connection.row_factory = sqlite3.Row
            record = connection.execute(
                "SELECT field_mapping_json, semantic_overrides_json, lineage_json, metadata_json "
                "FROM autoclean_datasets WHERE dataset_id = ? AND table_name = 'orders' AND status = 'READY'",
                (dataset_id,),
            ).fetchone()
            if record is None:
                return None
            frame = pd.read_sql_query(
                "SELECT * FROM orders WHERE dataset_id = ?", connection, params=(dataset_id,)
            ).drop(columns=["dataset_id"], errors="ignore")
            issue_rows = connection.execute(
                "SELECT severity, code, message, field, row_count, details_json "
                "FROM autoclean_dataset_issues WHERE dataset_id = ? ORDER BY id",
                (dataset_id,),
            ).fetchall()
        _restore_storage_types(frame)
        issues = [
            ValidationIssue(
                row["severity"], row["code"], row["message"], field=row["field"],
                row_count=int(row["row_count"]), details=_json_object(row["details_json"]),
            )
            for row in issue_rows
        ]
        metadata = _json_object(record["metadata_json"])
        metadata["dataset_id"] = dataset_id
        return DatasetContext(
            raw_data=frame.copy(),
            analysis_data=frame,
            contract=ECOMMERCE_CONTRACT,
            field_mapping=_json_object(record["field_mapping_json"]),
            semantic_overrides=_json_object(record["semantic_overrides_json"]),
            issues=issues,
            lineage=_json_object(record["lineage_json"]),
            metadata=metadata,
        )

    def archive_dataset(self, dataset_id: str) -> bool:
        if not self.path.exists():
            return False
        with closing(sqlite3.connect(str(self.path))) as connection:
            cursor = connection.execute(
                "UPDATE autoclean_datasets SET status = 'ARCHIVED' "
                "WHERE dataset_id = ? AND status = 'READY' AND table_name = 'orders'",
                (dataset_id,),
            )
            connection.commit()
        return cursor.rowcount > 0

    def purge_datasets(self, dataset_ids: Iterable[str]) -> list[str]:
        ids = [str(item) for item in dataset_ids if item]
        if not ids or not self.path.exists():
            return []
        placeholders = ",".join("?" for _ in ids)
        with closing(sqlite3.connect(str(self.path))) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = [
                str(row[0])
                for row in connection.execute(
                    "SELECT dataset_id FROM autoclean_datasets "
                    "WHERE table_name='orders' AND dataset_id IN ({})".format(placeholders),
                    ids,
                )
            ]
            if not existing:
                connection.rollback()
                return []
            existing_placeholders = ",".join("?" for _ in existing)
            for table in ("orders", "autoclean_dataset_issues", "autoclean_query_runs", "autoclean_datasets"):
                connection.execute(
                    "DELETE FROM {} WHERE dataset_id IN ({})".format(table, existing_placeholders),
                    existing,
                )
            connection.commit()
        return existing

    def purge_duplicate_ready_datasets(self, *, include_web: bool = False) -> list[str]:
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(str(self.path))) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT dataset_id, source_sha256, source_filename, row_count, "
                "metadata_json, created_at FROM autoclean_datasets "
                "WHERE table_name='orders' AND status='READY'"
            ).fetchall()
        groups: dict[tuple[str, str, int], list[sqlite3.Row]] = {}
        for row in rows:
            metadata = _json_object(row["metadata_json"])
            if metadata.get("import_origin") == "web" and not include_web:
                continue
            sha = str(row["source_sha256"] or "")
            filename = str(row["source_filename"] or "")
            row_count = int(row["row_count"] or 0)
            if not sha or not filename or row_count <= 0:
                continue
            groups.setdefault((sha, filename, row_count), []).append(row)
        duplicate_ids: list[str] = []
        for candidates in groups.values():
            if len(candidates) <= 1:
                continue
            ordered = sorted(candidates, key=lambda row: str(row["created_at"] or ""), reverse=True)
            duplicate_ids.extend(str(row["dataset_id"]) for row in ordered[1:])
        return self.purge_datasets(duplicate_ids)


def _json_object(value: str | None) -> dict[str, Any]:
    import json
    parsed = json.loads(value or "{}")
    return parsed if isinstance(parsed, dict) else {}


def _restore_storage_types(frame: pd.DataFrame) -> None:
    for spec in ECOMMERCE_CONTRACT.fields:
        if spec.name not in frame:
            continue
        if spec.dtype == "date":
            frame[spec.name] = pd.to_datetime(frame[spec.name], errors="coerce")
        elif spec.dtype == "float":
            frame[spec.name] = pd.to_numeric(frame[spec.name], errors="coerce")
        elif spec.dtype == "integer":
            frame[spec.name] = pd.to_numeric(frame[spec.name], errors="coerce").astype("Int64")
        elif spec.dtype == "boolean":
            frame[spec.name] = frame[spec.name].map({1: True, 0: False, "1": True, "0": False}).astype("boolean")
        else:
            frame[spec.name] = frame[spec.name].astype("string")
    for field in DERIVED_FIELDS:
        if field not in frame:
            continue
        if field == "fx_rate_date":
            frame[field] = pd.to_datetime(frame[field], errors="coerce")
        elif field != "fx_source":
            frame[field] = pd.to_numeric(frame[field], errors="coerce")


class SQLAnalysisRepository:
    """Execute the packaged query catalog for one isolated dataset version."""

    def __init__(
        self,
        database: CrossBorderDatabase,
        stored: StoredDataset,
        filters: Optional[Mapping[str, Any]] = None,
        market_field: str = "region",
    ):
        self.database = database
        self.store = database.store
        self.stored = stored
        self.filters = dict(filters or {})
        self.market_field = market_field if market_field in {"country", "region"} else "region"
        self.query_runs: list[Dict[str, Any]] = []
        self._cache: Dict[str, pd.DataFrame] = {}

    def _filter_clause(self) -> tuple[str, Dict[str, Any]]:
        clauses = ["dataset_id = :dataset_id"]
        params: Dict[str, Any] = {"dataset_id": self.stored.dataset_id}
        date_range = self.filters.get("order_date")
        if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
            clauses.extend((
                "date(order_date) >= date(:start_date)",
                "date(order_date) <= date(:end_date)",
            ))
            params["start_date"] = pd.Timestamp(date_range[0]).date().isoformat()
            params["end_date"] = pd.Timestamp(date_range[1]).date().isoformat()
        for field in ("region", "category"):
            values = self.filters.get(field)
            if values in (None, [], ()):
                continue
            sequence = list(values) if isinstance(values, (list, tuple, set)) else [values]
            placeholders = []
            for index, value in enumerate(sequence):
                key = "{}_{}".format(field, index)
                placeholders.append(":" + key)
                params[key] = value
            clauses.append("{} IN ({})".format(field, ", ".join(placeholders)))
        return " AND ".join(clauses), params

    def query(self, name: str) -> pd.DataFrame:
        if name in self._cache:
            return self._cache[name].copy()
        path = SQL_DIR / "{}.sql".format(name)
        if not path.exists():
            raise KeyError("Unknown SQL query: {}".format(name))
        where, params = self._filter_clause()
        market = (
            "COALESCE(NULLIF(TRIM(country), ''), '未标注国家')"
            if self.market_field == "country"
            else "COALESCE(NULLIF(TRIM(region), ''), '未标注区域')"
        )
        sql = path.read_text(encoding="utf-8").replace("/* FILTERS */", where).replace("/* MARKET */", market)
        if self.stored.row_count >= 100_000 and name in {"product_analysis", "customer_rfm_base"}:
            sql = sql.rstrip().rstrip(";") + " LIMIT 2000"
        frame = self.store.query_frame(name, sql, params)
        self.query_runs.append({
            "name": name,
            "duration_ms": frame.attrs.get("duration_ms", 0.0),
            "rows": len(frame),
        })
        self._cache[name] = frame.copy()
        return frame

    def overview(self) -> pd.DataFrame:
        return self.query("overview")

    def monthly_sales(self) -> pd.DataFrame:
        return self.query("monthly_sales")

    def sales_contribution(self) -> pd.DataFrame:
        return self.query("sales_contribution")

    def market_analysis(self) -> pd.DataFrame:
        return self.query("market_analysis")

    def market_category_analysis(self) -> pd.DataFrame:
        return self.query("market_category_analysis")

    def product_analysis(self) -> pd.DataFrame:
        return self.query("product_analysis")

    def loss_product_analysis(self) -> pd.DataFrame:
        return self.query("loss_product_analysis")

    def customer_rfm_base(self) -> pd.DataFrame:
        return self.query("customer_rfm_base")

    def return_analysis(self) -> pd.DataFrame:
        return self.query("return_analysis")

    def product_detail(self, name: str, product_id: str) -> pd.DataFrame:
        path = SQL_DIR / "{}.sql".format(name)
        where, params = self._filter_clause()
        params["product_id"] = product_id
        market = (
            "COALESCE(NULLIF(TRIM(country), ''), '未标注国家')"
            if self.market_field == "country"
            else "COALESCE(NULLIF(TRIM(region), ''), '未标注区域')"
        )
        sql = path.read_text(encoding="utf-8").replace("/* FILTERS */", where).replace("/* MARKET */", market)
        frame = self.store.query_frame(name, sql, params)
        self.query_runs.append({"name": name, "duration_ms": frame.attrs.get("duration_ms", 0.0), "rows": len(frame)})
        return frame


def build_sql_repository(
    path: Any,
    context,
    filters: Optional[Mapping[str, Any]] = None,
    market_field: str = "region",
) -> SQLAnalysisRepository:
    database = CrossBorderDatabase(path)
    stored = database.persist(context)
    return SQLAnalysisRepository(database, stored, filters=filters, market_field=market_field)
