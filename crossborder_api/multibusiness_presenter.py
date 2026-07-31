"""API presenter for registered multi-business analysis payloads."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from .presentation_contracts import build_business_presentation_contract


class MultiBusinessPresenter:
    def __init__(self, analysis_service) -> None:
        self.analysis_service = analysis_service

    def datasets(self) -> list[dict[str, Any]]:
        return self.analysis_service.list_datasets()

    def present(self, topic: str, dataset_id: str, *, page: int = 1, page_size: int = 20, **filters: Any) -> dict[str, Any]:
        cache_key = tuple(sorted((key, value) for key, value in filters.items() if value is not None))
        base = self._present_cached(topic, dataset_id, cache_key)
        details = list(base.get("details", []))
        offset = (page - 1) * page_size
        pagination = {"page": page, "page_size": page_size, "total": len(details), "pages": max(1, (len(details) + page_size - 1) // page_size)}
        rows = details[offset:offset + page_size]
        return {
            **base,
            "details": rows,
            "pagination": pagination,
            **build_business_presentation_contract(topic, base, rows, pagination),
        }

    @lru_cache(maxsize=128)
    def _present_cached(
        self,
        topic: str,
        dataset_id: str,
        filters: tuple[tuple[str, Any], ...],
    ) -> dict[str, Any]:
        return self.analysis_service.analyze(topic, dataset_id, **dict(filters))

    def clear_cache(self) -> None:
        self._present_cached.cache_clear()
