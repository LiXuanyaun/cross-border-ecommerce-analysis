from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
import sqlite3
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "1.0.0"


@dataclass(frozen=True)
class FactDefinition:
    table: str
    date_field: str
    required_fields: tuple[str, ...]
    topics: tuple[str, ...]
    recommendation_policy: str


FACTS = {
    "orders": FactDefinition(
        table="orders",
        date_field="order_date",
        required_fields=(
            "dataset_id", "record_id", "order_date", "gmv_amount_base", "quantity",
            "product_id", "customer_id", "country",
        ),
        topics=("overview", "market", "product", "customer", "profit", "returns"),
        recommendation_policy="latest_complete_month",
    ),
    "advertising": FactDefinition(
        table="fact_ad_performance_daily",
        date_field="ad_date",
        required_fields=("dataset_id", "ad_date", "campaign_id", "spend_usd"),
        topics=("advertising",),
        recommendation_policy="latest_12_months",
    ),
    "refunds": FactDefinition(
        table="fact_returns",
        date_field="return_request_date",
        required_fields=("dataset_id", "return_id", "return_request_date", "refund_amount"),
        topics=("refunds",),
        recommendation_policy="latest_12_months",
    ),
    "logistics": FactDefinition(
        table="fact_shipments",
        date_field="ship_date",
        required_fields=("dataset_id", "shipment_id", "ship_date"),
        topics=("logistics",),
        recommendation_policy="latest_12_months",
    ),
}

FACT_ALIASES = {"returns": "refunds"}


class DatasetCapabilityService:
    def __init__(self, dataset_service) -> None:
        self.dataset_service = dataset_service

    def clear_cache(self) -> None:
        self._discover_cached.cache_clear()

    def discover(
        self,
        dataset_id: str,
        *,
        fact: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        normalized_fact = FACT_ALIASES.get(fact or "", fact)
        if normalized_fact and normalized_fact not in FACTS:
            raise ValueError("fact must be orders, advertising, refunds or logistics")
        if bool(start) != bool(end):
            raise ValueError("start and end must be provided together")
        if start and end:
            selected_start = _parse_date(start, "start")
            selected_end = _parse_date(end, "end")
            if selected_start > selected_end:
                raise ValueError("start must be on or before end")
        return deepcopy(self._discover_cached(dataset_id, normalized_fact, start, end))

    @lru_cache(maxsize=128)
    def _discover_cached(
        self,
        dataset_id: str,
        fact: str | None,
        start: str | None,
        end: str | None,
    ) -> dict[str, Any]:
        scenario = self.dataset_service.scenario(dataset_id)
        selected = (_parse_date(start, "start"), _parse_date(end, "end")) if start and end else None
        definitions = {fact: FACTS[fact]} if fact else FACTS
        facts = {
            fact_id: self._fact_capability(dataset_id, scenario, fact_id, definition, selected)
            for fact_id, definition in definitions.items()
        }
        return {
            "dataset_id": dataset_id,
            "contract_version": CONTRACT_VERSION,
            "facts": facts,
        }

    def _fact_capability(
        self,
        dataset_id: str,
        scenario,
        fact_id: str,
        definition: FactDefinition,
        selected: tuple[date, date] | None,
    ) -> dict[str, Any]:
        columns, day_counts, origins = self._load_sql_fact(dataset_id, definition)
        if fact_id == "orders" and not day_counts:
            columns, day_counts = self._load_context_orders(dataset_id)
        missing_fields = sorted(set(definition.required_fields) - columns) if columns else list(definition.required_fields)
        periods = _segmented_periods(day_counts)
        recommended = _recommended_period(day_counts, periods, definition.recommendation_policy)
        state, selected_rows, incomplete = _selection_state(day_counts, periods, selected)
        if not day_counts:
            state = "INSUFFICIENT_DATA" if missing_fields or not columns else "EMPTY"

        simulation_state = _simulation_state(bool(getattr(scenario, "is_demo", False)), origins)
        limitations: list[str] = []
        if missing_fields:
            limitations.append("缺少必要字段：{}".format("、".join(missing_fields)))
        if simulation_state in {"SIMULATED", "MIXED"}:
            limitations.append("包含演示或模拟数据，不可直接用于正式财务核算。")
        if incomplete:
            limitations.append("当前范围包含不完整月份，不生成正式环比结论。")

        return {
            "fact": fact_id,
            "topics": list(definition.topics),
            "state": state,
            "source_table": definition.table,
            "date_field": definition.date_field,
            "available_periods": periods,
            "recommended_period": recommended,
            "requested_period": (
                {"start": selected[0].isoformat(), "end": selected[1].isoformat()}
                if selected else None
            ),
            "row_count": selected_rows if selected else sum(day_counts.values()),
            "missing_fields": missing_fields,
            "quality_state": "WARNING" if limitations else "READY",
            "simulation_state": simulation_state,
            "recommendation_policy": definition.recommendation_policy,
            "limitations": limitations,
        }

    def _load_sql_fact(
        self, dataset_id: str, definition: FactDefinition,
    ) -> tuple[set[str], dict[date, int], set[str]]:
        raw_path = self.dataset_service.database_path
        if raw_path is None:
            return set(), {}, set()
        path = Path(raw_path)
        if not path.exists():
            return set(), {}, set()
        with closing(sqlite3.connect(str(path))) as connection:
            table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (definition.table,)
            ).fetchone()
            if not table_exists:
                return set(), {}, set()
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info({})".format(definition.table))}
            if definition.date_field not in columns or "dataset_id" not in columns:
                return columns, {}, set()
            rows = connection.execute(
                "SELECT date({field}) day, COUNT(*) row_count FROM {table} "
                "WHERE dataset_id=? AND {field} IS NOT NULL GROUP BY date({field}) ORDER BY date({field})".format(
                    field=definition.date_field, table=definition.table,
                ),
                (dataset_id,),
            ).fetchall()
            origins: set[str] = set()
            if "data_origin" in columns:
                origins = {
                    str(row[0]) for row in connection.execute(
                        "SELECT DISTINCT data_origin FROM {} WHERE dataset_id=? AND data_origin IS NOT NULL".format(
                            definition.table
                        ),
                        (dataset_id,),
                    )
                }
        return columns, {date.fromisoformat(row[0]): int(row[1]) for row in rows}, origins

    def _load_context_orders(self, dataset_id: str) -> tuple[set[str], dict[date, int]]:
        frame = self.dataset_service.context_for(dataset_id).analysis_data
        columns = {str(column) for column in frame.columns}
        if "order_date" not in columns:
            return columns, {}
        values = frame["order_date"].dropna()
        counts: dict[date, int] = defaultdict(int)
        for value in values:
            parsed = value.date() if hasattr(value, "date") else date.fromisoformat(str(value)[:10])
            counts[parsed] += 1
        return columns, dict(counts)


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("{} must use YYYY-MM-DD".format(name)) from exc


def _month_index(value: date) -> int:
    return value.year * 12 + value.month


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _month_end(value: date) -> date:
    return value.replace(day=monthrange(value.year, value.month)[1])


def _shift_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _segmented_periods(day_counts: dict[date, int]) -> list[dict[str, Any]]:
    if not day_counts:
        return []
    days = sorted(day_counts)
    output: list[dict[str, Any]] = []
    segment_start = days[0]
    previous = days[0]
    row_count = day_counts[days[0]]
    for current in days[1:]:
        if _month_index(current) - _month_index(previous) > 1:
            output.append({"start": segment_start.isoformat(), "end": previous.isoformat(), "row_count": row_count})
            segment_start = current
            row_count = 0
        row_count += day_counts[current]
        previous = current
    output.append({"start": segment_start.isoformat(), "end": previous.isoformat(), "row_count": row_count})
    return output


def _recommended_period(
    day_counts: dict[date, int], periods: list[dict[str, Any]], policy: str,
) -> dict[str, str] | None:
    if not day_counts:
        return None
    days = sorted(day_counts)
    if policy == "latest_complete_month":
        by_month: dict[tuple[int, int], list[date]] = defaultdict(list)
        for day in days:
            by_month[(day.year, day.month)].append(day)
        complete = [
            values for values in by_month.values()
            if min(values) == _month_start(min(values)) and max(values) == _month_end(max(values))
        ]
        if complete:
            latest = max(complete, key=max)
            return {"start": min(latest).isoformat(), "end": max(latest).isoformat()}
    latest = periods[-1]
    latest_start = date.fromisoformat(latest["start"])
    latest_end = date.fromisoformat(latest["end"])
    window_start = max(latest_start, _shift_months(latest_end, -11))
    return {"start": window_start.isoformat(), "end": latest_end.isoformat()}


def _selection_state(
    day_counts: dict[date, int],
    periods: list[dict[str, Any]],
    selected: tuple[date, date] | None,
) -> tuple[str, int, bool]:
    if not selected:
        return "READY" if day_counts else "EMPTY", sum(day_counts.values()), False
    start, end = selected
    overlaps = any(start <= date.fromisoformat(item["end"]) and end >= date.fromisoformat(item["start"]) for item in periods)
    if not overlaps:
        return "OUT_OF_RANGE", 0, False
    selected_days = [day for day in day_counts if start <= day <= end]
    if not selected_days:
        return "EMPTY", 0, False
    latest = max(selected_days)
    incomplete = end >= latest and latest == max(day_counts) and latest != _month_end(latest)
    return (
        "INCOMPLETE_PERIOD" if incomplete else "READY",
        sum(day_counts[day] for day in selected_days),
        incomplete,
    )


def _simulation_state(is_demo: bool, origins: set[str]) -> str:
    if origins == {"synthetic_extension"}:
        return "SIMULATED"
    if "synthetic_extension" in origins:
        return "MIXED"
    return "SIMULATED" if is_demo else "ACTUAL"
