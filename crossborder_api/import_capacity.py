from __future__ import annotations

from dataclasses import dataclass
import os


MIB = 1024 * 1024


@dataclass(frozen=True)
class ImportCapacity:
    max_file_bytes: int
    max_task_bytes: int

    @classmethod
    def from_env(cls) -> "ImportCapacity":
        return cls(
            max_file_bytes=_positive_int("CROSSBORDER_IMPORT_MAX_FILE_BYTES", 100 * MIB),
            max_task_bytes=_positive_int("CROSSBORDER_IMPORT_MAX_TASK_BYTES", 1024 * MIB),
        )


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} 必须大于 0")
    return value


IMPORT_CAPACITY = ImportCapacity.from_env()


def format_bytes(value: int) -> str:
    if value >= 1024 * MIB:
        return f"{value / (1024 * MIB):.2f}GB"
    return f"{value / MIB:.2f}MB"
