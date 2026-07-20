"""Generate and run a reproducible 100k-order SQLite benchmark."""
from pathlib import Path
from time import perf_counter
import argparse

import pandas as pd

from crossborder_analytics.service import AnalysisService


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".cache" / "benchmark"
ROWS = 100_000


def parse_args():
    parser = argparse.ArgumentParser(description="CrossBorder SQLite benchmark")
    parser.add_argument("--rows", type=int, default=ROWS)
    parser.add_argument("--database", default=str(OUTPUT / "ecommerce_100k.db"))
    parser.add_argument("--assert-regression", action="store_true", help="Phase 2 相对兼容基线超过20%%时失败")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = pd.read_csv(ROOT / "data" / "ecommerce_sales_34500.csv")
    repeats = (args.rows + len(source) - 1) // len(source)
    frame = pd.concat([source] * repeats, ignore_index=True).iloc[:args.rows].copy()
    frame["order_id"] = ["BENCH{:07d}".format(index) for index in range(args.rows)]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT / "orders_100k.csv"
    database_path = Path(args.database)
    frame.to_csv(csv_path, index=False)

    baseline_database = database_path.with_name(database_path.stem + "_baseline.db")
    baseline_service = AnalysisService(
        cache_dir=OUTPUT / "fx", database_path=baseline_database, enable_phase2=False,
    )
    baseline_started = perf_counter()
    baseline_context = baseline_service.prepare(csv_path, source_currency="CNY", target_currency="CNY")
    baseline_service.run(baseline_context)
    baseline_elapsed = perf_counter() - baseline_started

    service = AnalysisService(cache_dir=OUTPUT / "fx", database_path=database_path, enable_phase2=True)
    started = perf_counter()
    context = service.prepare(csv_path, source_currency="CNY", target_currency="CNY")
    bundle = service.run(context)
    elapsed = perf_counter() - started
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
    print("rows={:,}".format(args.rows))
    print("pipeline_seconds={:.3f}".format(elapsed))
    print("phase1_compatible_seconds={:.3f}".format(baseline_elapsed))
    regression = (elapsed / baseline_elapsed - 1) if baseline_elapsed else 0.0
    print("phase2_regression_percent={:.1f}".format(regression * 100))
    print("slowest_query_seconds={:.3f}".format(slowest / 1000))
    print("market_category_query_seconds={:.3f}".format(market_query / 1000))
    print("product_detail_seconds={:.3f}".format(detail_elapsed))
    print("product_detail_query_count={}".format(len(detail["query_runs"])))
    print("storage_reused={}".format(bundle.context.metadata.get("storage_reused")))
    print("dataset_id={}".format(bundle.metadata.get("dataset_id")))
    if args.assert_regression and regression > .20:
        raise RuntimeError("Phase 2 regression {:.1%} exceeds 20%".format(regression))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
