from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any
import math
import os

import pandas as pd

from crossborder_analytics.localization import value_for
from crossborder_analytics.phase2_catalogs import ANOMALY_RULES, METRICS_CATALOG
from crossborder_analytics.service import AnalysisService
from crossborder_analytics.data_quality import assess_business_quality
from crossborder_analytics.modules import amount_column
from .report_runtime import export_scoped_bundle
from .agent_tools import build_agent_tool_registry
from .services import AnalysisQueryService, DatasetService, DemoScenario, SCENARIOS, WorkItemService
from .state import StateStore
from .topic_decisions import formal_topic_decisions


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "ecommerce_sales_34500.csv"


def _clean(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return _clean(value.to_dict())
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean(item) for item in value]
    return value


def _records(frame: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    source = frame if limit is None else frame.head(limit)
    return [_clean(item) for item in source.to_dict("records")]


def _localize(value: Any, kind: str) -> str:
    if value is None:
        return "未标注"
    try:
        return str(value_for(value, kind))
    except Exception:
        return str(value)


METRIC_LABELS = {
    "gmv": "GMV（成交总额）",
    "orders": "订单数",
    "aov": "客单价",
    "profit": "利润",
    "profit_margin": "利润率",
    "return_rate": "退货率",
    "market_contribution": "市场贡献率",
    "product_contribution": "商品贡献率",
}


def _rate(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or not previous:
        return None
    return (float(current) - float(previous)) / abs(float(previous))


def _entity_label(entity_type: str, value: Any) -> str:
    if entity_type == "market":
        return _localize(value, "region")
    if entity_type == "category":
        return _localize(value, "category")
    return str(value)


def _threshold_text(rule) -> str:
    threshold = float(rule.threshold)
    if rule.direction == "decrease":
        return "变化率不低于 {:.1%}".format(threshold)
    if rule.direction == "increase":
        return "变化率低于 +{:.1%}".format(threshold)
    if rule.direction == "decrease_pp":
        return "降幅小于 {:.1f} 个百分点".format(abs(threshold) * 100)
    if rule.direction == "high":
        return "当前值低于 {:.1%}".format(threshold)
    if rule.direction == "low_margin":
        return "利润率高于 {:.1%}".format(threshold)
    if rule.direction == "absolute_pp":
        return "波动小于 {:.1f} 个百分点".format(abs(threshold) * 100)
    if rule.direction == "compound":
        return "增长质量保护指标恢复"
    return "不再触发规则阈值"


class AnalyticsRuntime:
    def __init__(self) -> None:
        self.app_mode = os.getenv("CROSSBORDER_APP_MODE", "demo").strip().lower()
        self._service = AnalysisService(cache_dir=ROOT / ".cache" / "fx")
        self.dataset_service = DatasetService(self._service, SAMPLE)
        self.analysis_query_service = AnalysisQueryService(self.dataset_service)
        from .presenters import OverviewPresenter, TopicPresenter
        self.overview_presenter = OverviewPresenter(self)
        self.topic_presenter = TopicPresenter(self)
        cached_bundle = lru_cache(maxsize=64)(self._bundle_uncached)
        self._bundle_cache_clear = cached_bundle.cache_clear

        def clear_bundle_cache() -> None:
            self.clear_analysis_cache()

        cached_bundle.cache_clear = clear_bundle_cache
        self.bundle = cached_bundle
        self.dataset_service.set_cache_clearer(self.clear_analysis_cache)
        self.agent_tools = build_agent_tool_registry()
        self.state_store = None
        if self.app_mode == "private":
            state_path = Path(os.getenv("CROSSBORDER_STATE_DB", ROOT / "database" / "crossborder_state.db"))
            self.state_store = StateStore(state_path)
        self.work_item_service = WorkItemService(self.app_mode, self.state_store)
        self._work_items = self.work_item_service.work_items
        from .agent_context_builder import AgentContextBuilder
        self.agent_context_builder = AgentContextBuilder(self)

    def _ensure_context(self):
        return self.dataset_service.ensure_demo_context()

    def _database(self):
        return self.dataset_service.database()

    def _artifact_store(self):
        return self.dataset_service.artifact_store()

    def _imported_scenarios(self) -> tuple[DemoScenario, ...]:
        return self.dataset_service.imported_scenarios()

    def _context_for(self, dataset_id: str):
        return self.dataset_service.context_for(dataset_id)

    def clear_analysis_cache(self) -> None:
        self._bundle_cache_clear()
        self.analysis_query_service.clear_cache()
        self.topic_presenter.clear_cache()

    def scenario(self, dataset_id: str) -> DemoScenario:
        return self.dataset_service.scenario(dataset_id)

    def date_bounds(self, dataset_id: str = "demo-all") -> tuple[str, str]:
        return self.dataset_service.date_bounds(dataset_id)

    def _bundle_uncached(
        self,
        dataset_id: str,
        start: str | None = None,
        end: str | None = None,
        market: str | None = None,
        category: str | None = None,
        period_type: str = "month",
        analysis_mode: str = "full",
        topic: str | None = None,
    ):
        return self.analysis_query_service.bundle(
            dataset_id, start, end, market, category, period_type, analysis_mode, topic,
        )

    def meta(self, bundle, dataset_id: str) -> dict[str, Any]:
        quality = bundle.artifacts.data_quality
        return {
            "dataset_id": dataset_id,
            "scope_id": bundle.metadata.get("scope_id"),
            "source_dataset_id": bundle.metadata.get("dataset_id"),
            "generated_at": bundle.generated_at,
            "quality_rating": str(quality.quality_rating) if quality else None,
            "quality_score": quality.quality_score if quality else None,
            "app_mode": self.app_mode,
        }

    @staticmethod
    def _metric_change(rows: pd.DataFrame, field: str) -> float | None:
        values = rows[field].dropna().tolist() if field in rows else []
        if len(values) < 2 or not values[-2]:
            return None
        return (float(values[-1]) - float(values[-2])) / abs(float(values[-2]))

    @staticmethod
    def _comparison_trend(
        frame: pd.DataFrame,
        current_start: str,
        current_end: str,
        comparison_start: str,
        comparison_end: str,
        grain: str,
    ) -> dict[str, Any]:
        source = frame.copy()
        source["order_date"] = pd.to_datetime(source["order_date"]).dt.normalize()
        amount = amount_column(source)
        current_start_date = pd.Timestamp(current_start).normalize()
        current_end_date = pd.Timestamp(current_end).normalize()
        comparison_start_date = pd.Timestamp(comparison_start).normalize()
        comparison_end_date = pd.Timestamp(comparison_end).normalize()

        if grain == "day":
            current_index = pd.date_range(current_start_date, current_end_date, freq="D")
            comparison_index = pd.date_range(comparison_start_date, comparison_end_date, freq="D")
            grouped = source.groupby("order_date")[amount].sum()
        else:
            current_index = pd.date_range(current_start_date, current_end_date, freq="7D")
            comparison_index = pd.date_range(comparison_start_date, comparison_end_date, freq="7D")
            current_rows = source.loc[source.order_date.between(current_start_date, current_end_date)].copy()
            comparison_rows = source.loc[source.order_date.between(comparison_start_date, comparison_end_date)].copy()
            current_rows["bucket"] = ((current_rows.order_date - current_start_date).dt.days // 7).astype(int)
            comparison_rows["bucket"] = ((comparison_rows.order_date - comparison_start_date).dt.days // 7).astype(int)
            current_values = current_rows.groupby("bucket")[amount].sum()
            comparison_values = comparison_rows.groupby("bucket")[amount].sum()

        if grain == "day":
            current_values = grouped.reindex(current_index, fill_value=0.0)
            comparison_values = grouped.reindex(comparison_index, fill_value=0.0)
        rows = []
        bucket_count = max(len(current_index), len(comparison_index))
        for index in range(bucket_count):
            current_date = current_index[index] if index < len(current_index) else None
            comparison_date = comparison_index[index] if index < len(comparison_index) else None
            rows.append({
                "label": "第{}日".format(index + 1) if grain == "day" else "第{}周".format(index + 1),
                "current_date": current_date.date().isoformat() if current_date is not None else "",
                "comparison_date": comparison_date.date().isoformat() if comparison_date is not None else "",
                "current": float(current_values.loc[current_date]) if grain == "day" and current_date is not None else (float(current_values.get(index, 0.0)) if current_date is not None else None),
                "comparison": float(comparison_values.loc[comparison_date]) if grain == "day" and comparison_date is not None else (float(comparison_values.get(index, 0.0)) if comparison_date is not None else None),
            })
        return {
            "grain": grain,
            "current_period": {"start": current_start_date.date().isoformat(), "end": current_end_date.date().isoformat()},
            "comparison_period": {"start": comparison_start_date.date().isoformat(), "end": comparison_end_date.date().isoformat()},
            "rows": rows,
        }

    def overview(self, dataset_id: str, start: str | None = None, end: str | None = None) -> tuple[dict, Any]:
        return self.overview_presenter.present(dataset_id, start, end)

    def topic(
        self,
        dataset_id: str,
        topic: str,
        start: str | None = None,
        end: str | None = None,
        market: str | None = None,
        category: str | None = None,
        search: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[dict, Any]:
        return self.topic_presenter.present(
            dataset_id, topic, start, end, market, category, search, page, page_size,
        )

    def topic_export(
        self,
        dataset_id: str,
        topic: str,
        start: str | None,
        end: str | None,
        market: str | None,
        category: str | None,
        search: str,
    ) -> tuple[dict, Any]:
        return self.topic_presenter.export(dataset_id, topic, start, end, market, category, search)

    def datasets(self) -> list[dict[str, Any]]:
        items = []
        for scenario in SCENARIOS + self._imported_scenarios():
            context = self._context_for(scenario.dataset_id)
            start, end = self.date_bounds(scenario.dataset_id)
            profile_frame = context.analysis_data
            for field, values in scenario.filters.items():
                profile_frame = profile_frame[profile_frame[field].isin(values)]
            count = len(profile_frame)
            profile_context = replace(context, analysis_data=profile_frame.copy())
            quality, _, _, _, _, _ = assess_business_quality(
                profile_context, scenario.dataset_id, "dataset-profile"
            )
            items.append({
                "dataset_id": scenario.dataset_id,
                "name": scenario.name,
                "description": scenario.description,
                "source_type": scenario.source_type,
                "row_count": count,
                "status": "READY",
                "quality_score": quality.quality_score,
                "period_start": start,
                "period_end": end,
                "updated_at": scenario.created_at or pd.Timestamp.now().isoformat(),
                "is_demo": scenario.is_demo,
            })
        return items

    def dataset_detail(self, dataset_id: str) -> tuple[dict, Any]:
        bundle = self.bundle(dataset_id)
        scenario = self.scenario(dataset_id)
        context = self._context_for(dataset_id)
        quality = bundle.artifacts.data_quality
        capabilities = [item.to_dict() for item in bundle.artifacts.analysis_capability]
        fields = [item.to_dict() for item in bundle.artifacts.field_quality]
        query_runs = bundle.metadata.get("query_runs", [])
        lineage = (
            {"source": SAMPLE.name, "scenario_filters": scenario.filters, "raw_read_only": True}
            if scenario.is_demo else context.lineage
        )
        profile_frame = context.analysis_data
        for field, values in scenario.filters.items():
            if field in profile_frame:
                profile_frame = profile_frame.loc[profile_frame[field].isin(values)]
        source_files = lineage.get("source_files") if isinstance(lineage, dict) else None
        import_history = (
            source_files if isinstance(source_files, list) else [{
                "source_filename": SAMPLE.name if scenario.is_demo else context.metadata.get("filename", "uploaded"),
                "source_type": scenario.source_type,
                "rows": len(profile_frame) if scenario.is_demo else context.metadata.get("rows"),
                "status": "READY",
                "created_at": scenario.created_at or context.metadata.get("created_at"),
            }]
        )
        fx_rates = context.metadata.get("fx_rates")
        fx_rate_rows = len(fx_rates) if hasattr(fx_rates, "__len__") else 0
        return _clean({
            "dataset": next(item for item in self.datasets() if item["dataset_id"] == dataset_id),
            "quality": quality.to_dict() if quality else None,
            "quality_dimensions": [item.to_dict() for item in bundle.artifacts.data_quality_dimensions],
            "fields": fields,
            "capabilities": capabilities,
            "query_runs": list(query_runs)[-10:],
            "lineage": lineage,
            "import_history": import_history,
            "metric_catalog": [item.to_dict() for item in METRICS_CATALOG],
            "rule_catalog": [item.to_dict() for item in ANOMALY_RULES],
            "capacity": self._artifact_store().capacity(),
            "fx_lineage": {
                "source_currency": context.metadata.get("source_currency"),
                "target_currency": context.metadata.get("target_currency"),
                "fx_complete": context.metadata.get("fx_complete"),
                "fx_provider": context.metadata.get("fx_provider"),
                "rate_rows": fx_rate_rows,
            },
        }), bundle

    def archive_dataset(self, dataset_id: str) -> bool:
        scenario = self.scenario(dataset_id)
        if scenario.is_demo:
            raise PermissionError("演示数据集不能归档")
        archived = self._database().archive_dataset(dataset_id)
        if archived:
            self.clear_analysis_cache()
        return archived

    def import_dataset(
        self,
        loaded,
        *,
        mapping: dict[str, str],
        source_file_id: str,
        dataset_name: str,
        data_grain: str,
        amount_semantic: str,
        source_currency: str | None,
        target_currency: str,
    ) -> dict[str, Any]:
        return self.dataset_service.import_dataset(
            loaded,
            mapping=mapping,
            source_file_id=source_file_id,
            dataset_name=dataset_name,
            data_grain=data_grain,
            amount_semantic=amount_semantic,
            source_currency=source_currency,
            target_currency=target_currency,
        )

    def import_datasets(
        self,
        loaded_files: list[tuple[Any, str]],
        *,
        mapping: dict[str, str],
        dataset_name: str,
        data_grain: str,
        amount_semantic: str,
        source_currency: str | None,
        target_currency: str,
    ) -> dict[str, Any]:
        return self.dataset_service.import_datasets(
            loaded_files,
            mapping=mapping,
            dataset_name=dataset_name,
            data_grain=data_grain,
            amount_semantic=amount_semantic,
            source_currency=source_currency,
            target_currency=target_currency,
        )

    def update_work_item(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.work_item_service.update(item_id, payload)

    def agent_context(
        self, dataset_id: str, question: str, start: str | None = None,
        end: str | None = None, market: str | None = None, category: str | None = None,
    ) -> tuple[dict[str, Any], Any]:
        return self.agent_context_builder.build(dataset_id, question, start, end, market, category)

    def export(
        self, dataset_id: str, report_format: str, start: str | None = None,
        end: str | None = None, market: str | None = None, category: str | None = None,
        scope_id: str | None = None,
    ):
        return export_scoped_bundle(self, dataset_id, report_format, start, end, market, category, scope_id)
