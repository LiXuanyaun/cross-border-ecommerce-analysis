"""Deterministic identifiers and canonical result hashing."""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): canonical_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (tuple, list, set)):
        return [canonical_value(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(canonical_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(prefix: str, *parts: Any) -> str:
    digest = sha256(canonical_json(parts).encode("utf-8")).hexdigest()[:24]
    return "{}_{}".format(prefix, digest)


def frame_digest(frame: pd.DataFrame) -> str:
    normalized = frame.copy()
    normalized.columns = [str(column) for column in normalized.columns]
    for column in normalized.columns:
        series = normalized[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            normalized[column] = pd.to_datetime(series).dt.strftime("%Y-%m-%dT%H:%M:%S.%f").fillna("<NULL>")
        elif pd.api.types.is_numeric_dtype(series):
            normalized[column] = pd.to_numeric(series, errors="coerce").astype("float64").round(10)
        else:
            normalized[column] = series.astype("string").fillna("<NULL>")
    row_hashes = np.sort(pd.util.hash_pandas_object(normalized, index=False, categorize=True).to_numpy(dtype="uint64"))
    digest = sha256()
    digest.update(canonical_json(list(normalized.columns)).encode("utf-8"))
    digest.update(row_hashes.tobytes())
    return digest.hexdigest()
