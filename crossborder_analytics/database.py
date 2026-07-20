"""Versioned SQLite storage and named SQL queries for ecommerce orders."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from contextlib import closing
import sqlite3

import pandas as pd

from autoclean.analytics import SQLiteDatasetStore, StoredDataset

from .contract import ECOMMERCE_CONTRACT


SQL_DIR = Path(__file__).resolve().parent / "sql"
AMOUNT_FIELDS = ("price", "total_amount", "shipping_cost", "profit_amount")
DERIVED_FIELDS = tuple("{}_base".format(field) for field in AMOUNT_FIELDS) + (
    "fx_rate",
    "fx_rate_date",
    "fx_source",
)
ORDER_COLUMNS = tuple(field.name for field in ECOMMERCE_CONTRACT.fields) + DERIVED_FIELDS


def _missing_series(index: pd.Index, field: str) -> pd.Series:
    spec = ECOMMERCE_CONTRACT.field(field)
    dtype = spec.dtype if spec else None
    if dtype == "float" or field.endswith("_base") or field == "fx_rate":
        return pd.Series(float("nan"), index=index, dtype="float64")
    if dtype == "integer":
        return pd.Series(pd.NA, index=index, dtype="Int64")
    if dtype == "boolean":
        return pd.Series(pd.NA, index=index, dtype="boolean")
    if dtype == "date" or field == "fx_rate_date":
        return pd.Series(pd.NaT, index=index, dtype="datetime64[ns]")
    return pd.Series(pd.NA, index=index, dtype="string")


def storage_frame(context) -> pd.DataFrame:
    frame = context.analysis_data.copy()
    for field in ORDER_COLUMNS:
        if field not in frame:
            frame[field] = _missing_series(frame.index, field)
    return frame.loc[:, ORDER_COLUMNS]


class CrossBorderDatabase:
    def __init__(self, path: Any):
        self.path = Path(path)
        self.store = SQLiteDatasetStore(self.path)

    def persist(self, context) -> StoredDataset:
        self._migrate_orders_schema()
        stored_context = replace(context, analysis_data=storage_frame(context))
        stored = self.store.store_context(stored_context, "orders")
        self._ensure_indexes()
        context.metadata.update({
            "database_path": str(self.path.resolve()),
            "database_schema_version": 3,
            "dataset_id": stored.dataset_id,
            "stored_rows": stored.row_count,
            "storage_reused": stored.reused,
            "analysis_backend": "sql",
        })
        return stored

    def _migrate_orders_schema(self) -> None:
        """Add optional 2.2 columns to databases created by CrossBorder 2.1."""
        if not self.path.exists():
            return
        with closing(sqlite3.connect(str(self.path))) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'orders'"
            ).fetchone()
            if not exists:
                return
            columns = {row[1] for row in connection.execute("PRAGMA table_info(orders)")}
            for column in ("country", "product_name"):
                if column not in columns:
                    connection.execute("ALTER TABLE orders ADD COLUMN {} TEXT".format(column))
            connection.commit()

    def _ensure_indexes(self) -> None:
        statements = (
            "CREATE INDEX IF NOT EXISTS idx_orders_dataset_date ON orders(dataset_id, order_date)",
            "CREATE INDEX IF NOT EXISTS idx_orders_dataset_region ON orders(dataset_id, region)",
            "CREATE INDEX IF NOT EXISTS idx_orders_dataset_country ON orders(dataset_id, country)",
            "CREATE INDEX IF NOT EXISTS idx_orders_dataset_category ON orders(dataset_id, category)",
            "CREATE INDEX IF NOT EXISTS idx_orders_dataset_product ON orders(dataset_id, product_id)",
            "CREATE INDEX IF NOT EXISTS idx_orders_dataset_customer ON orders(dataset_id, customer_id)",
        )
        with closing(sqlite3.connect(str(self.path))) as connection:
            for statement in statements:
                connection.execute(statement)
            connection.commit()


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
