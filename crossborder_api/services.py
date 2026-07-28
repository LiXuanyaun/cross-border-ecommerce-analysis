from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from crossborder_analytics.database import CrossBorderDatabase
from crossborder_analytics.phase2_models import AnalysisRequest
from crossborder_analytics.phase2_storage import ArtifactStore
from crossborder_analytics.service import AnalysisService

from .dataset_import_runtime import import_datasets as import_uploaded_datasets


@dataclass(frozen=True)
class DemoScenario:
    dataset_id: str
    name: str
    description: str
    filters: dict[str, tuple[str, ...]]
    source_type: str
    is_demo: bool = True
    created_at: str | None = None
    metadata: dict[str, Any] | None = None


SCENARIOS = (
    DemoScenario("demo-all", "全量经营演示数据", "完整订单样例，覆盖经营、商品、客户与退货分析", {}, "只读样例"),
    DemoScenario("demo-west", "区域经营演示数据", "从全量样例筛选 West 区域形成的可追溯场景", {"region": ("West",)}, "派生场景"),
    DemoScenario("demo-risk", "退货风险演示数据", "从全量样例筛选 Electronics 品类形成的风险场景", {"category": ("Electronics",)}, "派生场景"),
)


class DatasetService:
    def __init__(
        self,
        analysis_service: AnalysisService,
        sample_path: Path,
        cache_clearer: Callable[[], None] | None = None,
    ) -> None:
        self.analysis_service = analysis_service
        self.sample_path = sample_path
        self._lock = RLock()
        self._demo_context = None
        self._cache_clearer = cache_clearer or (lambda: None)

    def set_cache_clearer(self, cache_clearer: Callable[[], None]) -> None:
        self._cache_clearer = cache_clearer

    @property
    def database_path(self):
        return self.analysis_service.database_path

    def clear_analysis_cache(self) -> None:
        self._cache_clearer()

    def ensure_demo_context(self):
        if self._demo_context is None:
            with self._lock:
                if self._demo_context is None:
                    self._demo_context = self.analysis_service.prepare(
                        self.sample_path, source_currency="CNY", target_currency="CNY"
                    )
        return self._demo_context

    def database(self) -> CrossBorderDatabase:
        if self.analysis_service.database_path is None:
            raise RuntimeError("SQL 数据库未配置")
        return CrossBorderDatabase(self.analysis_service.database_path)

    def artifact_store(self) -> ArtifactStore:
        if self.analysis_service.database_path is None:
            raise RuntimeError("分析结果存储未配置")
        return ArtifactStore(self.analysis_service.database_path)

    def imported_scenarios(self) -> tuple[DemoScenario, ...]:
        output = []
        for item in self.database().list_datasets():
            metadata = item["metadata"]
            filename = item.get("filename") or "上传数据"
            output.append(DemoScenario(
                dataset_id=item["dataset_id"],
                name=str(metadata.get("dataset_name") or Path(filename).stem),
                description="由 {} 导入的正式数据集".format(filename),
                filters={},
                source_type="Web 上传",
                is_demo=False,
                created_at=item["created_at"],
                metadata=metadata,
            ))
        return tuple(output)

    def scenario(self, dataset_id: str) -> DemoScenario:
        for item in SCENARIOS + self.imported_scenarios():
            if item.dataset_id == dataset_id:
                return item
        raise KeyError(dataset_id)

    def context_for(self, dataset_id: str):
        if any(item.dataset_id == dataset_id for item in SCENARIOS):
            return self.ensure_demo_context()
        context = self.database().load_context(dataset_id)
        if context is None:
            raise KeyError(dataset_id)
        return context

    def date_bounds(self, dataset_id: str = "demo-all") -> tuple[str, str]:
        frame = self.context_for(dataset_id).analysis_data
        return frame.order_date.min().date().isoformat(), frame.order_date.max().date().isoformat()

    def archive_dataset(self, dataset_id: str) -> bool:
        scenario = self.scenario(dataset_id)
        if scenario.is_demo:
            raise PermissionError("演示数据集不能归档")
        archived = self.database().archive_dataset(dataset_id)
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
        return self.import_datasets(
            [(loaded, source_file_id)],
            mapping=mapping,
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
        return import_uploaded_datasets(
            self,
            loaded_files,
            mapping=mapping,
            dataset_name=dataset_name,
            data_grain=data_grain,
            amount_semantic=amount_semantic,
            source_currency=source_currency,
            target_currency=target_currency,
        )


class AnalysisQueryService:
    def __init__(self, dataset_service: DatasetService) -> None:
        self.dataset_service = dataset_service

    def clear_cache(self) -> None:
        self.bundle.cache_clear()

    @lru_cache(maxsize=64)
    def bundle(
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
        scenario = self.dataset_service.scenario(dataset_id)
        filters: dict[str, Any] = {key: list(values) for key, values in scenario.filters.items()}
        if start and end:
            filters["order_date"] = (start, end)
        if market:
            filters["region"] = [market]
        if category:
            filters["category"] = [category]
        return self.dataset_service.analysis_service.run(
            self.dataset_service.context_for(dataset_id),
            request=AnalysisRequest(
                filters=filters, period_type=period_type, analysis_mode=analysis_mode, topic=topic,
            ),
        )
