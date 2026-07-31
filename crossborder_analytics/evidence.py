"""Controlled EvidenceBundle replay and digest verification."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .database import CrossBorderDatabase, SQLAnalysisRepository
from .phase2_storage import ArtifactStore
from .phase2_utils import frame_digest


class EvidenceReplayError(RuntimeError):
    pass


class EvidenceService:
    def __init__(self, database_path: Any):
        self.database_path = Path(database_path)
        self.artifacts = ArtifactStore(self.database_path)

    def replay(self, evidence_id: str) -> Mapping[str, Any]:
        payload = self.artifacts.payload("evidence_bundles", "evidence_id", evidence_id)
        if payload is None:
            raise EvidenceReplayError("Evidence not found: {}".format(evidence_id))
        query_name = payload["query_name"]
        if query_name != "metric_facts_v1":
            raise EvidenceReplayError("Evidence query is not replayable by the installed catalog")
        path = Path(__file__).resolve().parent / "sql" / "{}.sql".format(query_name)
        version = sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if version != payload["query_version"]:
            raise EvidenceReplayError("Installed SQL version does not match the evidence")
        database = CrossBorderDatabase(self.database_path)
        stored = database.store.get_dataset(payload["dataset_id"])
        if stored is None:
            raise EvidenceReplayError("Evidence dataset is unavailable")
        parameters = payload.get("query_parameters", {})
        filters = parameters.get("filters", {})
        repository = SQLAnalysisRepository(
            database, stored, filters=filters,
            market_field=parameters.get("market_dimension") or "region",
        )
        frame = repository.query(query_name)
        if "order_day" in frame:
            frame["order_day"] = pd.to_datetime(frame["order_day"])
        digest = frame_digest(frame)
        expected_summary = payload.get("result_summary", {})
        actual_summary = {
            "rows": len(frame),
            "orders": int(frame["orders"].sum()) if not frame.empty else 0,
            "gmv": float(frame["gmv"].sum()) if not frame.empty else 0.0,
        }
        return {
            "evidence_id": evidence_id,
            "matched": digest == payload["result_digest"] and len(frame) == payload["row_count"] and actual_summary == expected_summary,
            "expected_digest": payload["result_digest"],
            "actual_digest": digest,
            "row_count": len(frame),
            "result_summary": actual_summary,
        }
