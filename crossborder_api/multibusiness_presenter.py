"""API presenter for registered multi-business analysis payloads."""
from __future__ import annotations

from typing import Any


class MultiBusinessPresenter:
    def __init__(self, analysis_service) -> None:
        self.analysis_service = analysis_service

    def datasets(self) -> list[dict[str, Any]]:
        return self.analysis_service.list_datasets()

    def present(self, topic: str, dataset_id: str, **filters: Any) -> dict[str, Any]:
        return self.analysis_service.analyze(topic, dataset_id, **filters)
