"""Clean and compact persisted Phase 2 analysis artifacts."""
from __future__ import annotations

from pathlib import Path
import argparse

from crossborder_analytics.database import CrossBorderDatabase
from crossborder_analytics.phase2_storage import (
    DEFAULT_MAX_ENTITY_ASSESSMENTS_PER_SCOPE,
    DEFAULT_KEEP_LATEST_SCOPES,
    DEFAULT_SCOPE_TTL_DAYS,
    ArtifactStore,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "database" / "ecommerce.db"


def _database_bytes(path: Path) -> int:
    return sum(
        candidate.stat().st_size
        for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"))
        if candidate.exists()
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Clean old analysis scopes and compact SQLite storage")
    parser.add_argument("--database", default=str(DEFAULT_DATABASE))
    parser.add_argument("--keep-latest", type=int, default=DEFAULT_KEEP_LATEST_SCOPES)
    parser.add_argument("--ttl-days", type=int, default=DEFAULT_SCOPE_TTL_DAYS)
    parser.add_argument("--max-entity-assessments", type=int, default=DEFAULT_MAX_ENTITY_ASSESSMENTS_PER_SCOPE)
    parser.add_argument("--keep-low-sample-assessments", action="store_true")
    parser.add_argument("--keep-topic-cache", action="store_true")
    parser.add_argument("--keep-duplicate-datasets", action="store_true")
    parser.add_argument("--skip-compact", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database_path = Path(args.database)
    before = _database_bytes(database_path)
    store = ArtifactStore(database_path)
    purged_datasets = []
    purged_dataset_scopes = []
    if not args.keep_duplicate_datasets:
        purged_datasets = CrossBorderDatabase(database_path).purge_duplicate_ready_datasets()
        purged_dataset_scopes = store.cleanup_dataset_scopes(purged_datasets)
    cleared_topic_rows = 0
    if not args.keep_topic_cache:
        cleared_topic_rows = store.clear_topic_detail_cache()
    trimmed_assessments = store.trim_entity_assessments(
        max_per_scope=args.max_entity_assessments,
        keep_low_sample=args.keep_low_sample_assessments,
    )
    removed = store.maintenance_cleanup(
        keep_latest=args.keep_latest,
        ttl_days=args.ttl_days,
        compact=False,
    )
    compacted = False
    if not args.skip_compact and (
        removed or cleared_topic_rows or trimmed_assessments
        or purged_datasets or purged_dataset_scopes
    ):
        compacted = store.compact()
    after = _database_bytes(database_path)
    print("database={}".format(database_path.resolve()))
    print("removed_scopes={}".format(len(removed)))
    print("purged_duplicate_datasets={}".format(len(purged_datasets)))
    print("purged_dataset_scopes={}".format(len(purged_dataset_scopes)))
    print("cleared_topic_cache_rows={}".format(cleared_topic_rows))
    print("trimmed_entity_assessments={}".format(trimmed_assessments))
    print("compacted={}".format(compacted))
    print("before_mb={:.3f}".format(before / 1024 / 1024))
    print("after_mb={:.3f}".format(after / 1024 / 1024))
    if removed:
        print("removed_scope_ids={}".format(",".join(removed)))
    if purged_datasets:
        print("purged_dataset_ids={}".format(",".join(purged_datasets)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
