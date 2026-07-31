"""Generate and run a reproducible 100k-order SQLite benchmark."""
from pathlib import Path
from time import perf_counter
import argparse
import platform
import statistics
import sys

import pandas as pd

from crossborder_analytics.service import AnalysisService
from crossborder_api.services import AnalysisQueryService, DatasetService


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".cache" / "benchmark"
ROWS = 100_000


def parse_args():
    parser = argparse.ArgumentParser(description="CrossBorder SQLite benchmark")
    parser.add_argument("--rows", type=int, default=ROWS)
    parser.add_argument("--database", default=str(OUTPUT / "ecommerce_100k.db"))
    parser.add_argument("--max-seconds", type=float, default=15.0)
    parser.add_argument("--max-database-mb", type=float, default=200.0)
    parser.add_argument("--reuse-database", action="store_true")
    parser.add_argument("--samples", type=int, default=5)
    return parser.parse_args()


def percentile(values: list[float], proportion: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * proportion)))
    return ordered[index]


def main() -> int:
    args = parse_args()
    source = pd.read_csv(ROOT / "data" / "ecommerce_sales_34500.csv")
    repeats = (args.rows + len(source) - 1) // len(source)
    frame = pd.concat([source] * repeats, ignore_index=True).iloc[:args.rows].copy()
    frame["order_id"] = ["BENCH{:07d}".format(index) for index in range(args.rows)]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT / "orders_100k.csv"
    database_path = Path(args.database)
    if not args.reuse_database:
        for candidate in (database_path, Path(str(database_path) + "-wal"), Path(str(database_path) + "-shm")):
            if candidate.exists():
                candidate.unlink()
    frame.to_csv(csv_path, index=False)

    service = AnalysisService(cache_dir=OUTPUT / "fx", database_path=database_path)
    prepare_started = perf_counter()
    context = service.prepare(csv_path, source_currency="CNY", target_currency="CNY")
    prepare_elapsed = perf_counter() - prepare_started
    analysis_started = perf_counter()
    bundle = service.run(context)
    analysis_elapsed = perf_counter() - analysis_started
    elapsed = prepare_elapsed + analysis_elapsed
    failures = {
        name: result.message
        for name, result in bundle.results.items()
        if result.status.value in {"FAILED", "FATAL"}
    }
    if failures:
        raise RuntimeError("Benchmark failed: {}".format(failures))

    query_runs = bundle.metadata.get("query_runs", [])
    slowest = max((item["duration_ms"] for item in query_runs), default=0.0)
    market_query = next((item["duration_ms"] for item in query_runs if item["name"] == "market_category_analysis"), 0.0)
    product_id = str(bundle.results["product"].data["products"].iloc[0].product_id)
    detail_started = perf_counter()
    detail = service.product_detail(bundle, product_id)
    detail_elapsed = perf_counter() - detail_started
    query_service = AnalysisQueryService(DatasetService(service, csv_path))
    page_cold_started = perf_counter()
    query_service.bundle("demo-all", analysis_mode="topic", topic="market")
    page_cold_elapsed = perf_counter() - page_cold_started
    page_hot_samples = []
    hot_detail_samples = [detail_elapsed]
    for _ in range(max(1, args.samples)):
        hot_started = perf_counter()
        query_service.bundle("demo-all", analysis_mode="topic", topic="market")
        page_hot_samples.append(perf_counter() - hot_started)
        hot_detail_started = perf_counter()
        service.product_detail(bundle, product_id)
        hot_detail_samples.append(perf_counter() - hot_detail_started)
    database_bytes = sum(
        candidate.stat().st_size
        for candidate in (database_path, Path(str(database_path) + "-wal"), Path(str(database_path) + "-shm"))
        if candidate.exists()
    )
    database_mb = database_bytes / 1024 / 1024
    print("environment={}".format(platform.platform()))
    print("python={}".format(sys.version.split()[0]))
    print("pandas={}".format(pd.__version__))
    print("rows={:,}".format(args.rows))
    print("cold_prepare_seconds={:.3f}".format(prepare_elapsed))
    print("cold_analysis_seconds={:.3f}".format(analysis_elapsed))
    print("pipeline_seconds={:.3f}".format(elapsed))
    print("database_mb={:.3f}".format(database_mb))
    print("slowest_query_seconds={:.3f}".format(slowest / 1000))
    print("market_category_query_seconds={:.3f}".format(market_query / 1000))
    print("product_detail_seconds={:.3f}".format(detail_elapsed))
    print("page_cold_analysis_seconds={:.3f}".format(page_cold_elapsed))
    print("page_hot_analysis_p50_seconds={:.3f}".format(statistics.median(page_hot_samples)))
    print("page_hot_analysis_p95_seconds={:.3f}".format(percentile(page_hot_samples, .95)))
    print("hot_detail_p50_seconds={:.3f}".format(statistics.median(hot_detail_samples)))
    print("hot_detail_p95_seconds={:.3f}".format(percentile(hot_detail_samples, .95)))
    print("product_detail_query_count={}".format(len(detail["query_runs"])))
    print("storage_reused={}".format(bundle.context.metadata.get("storage_reused")))
    print("dataset_id={}".format(bundle.metadata.get("dataset_id")))
    if elapsed > args.max_seconds:
        raise RuntimeError(
            "Pipeline {:.3f}s exceeds {:.3f}s".format(elapsed, args.max_seconds)
        )
    if database_mb > args.max_database_mb:
        raise RuntimeError(
            "Database {:.3f}MB exceeds {:.3f}MB".format(database_mb, args.max_database_mb)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
