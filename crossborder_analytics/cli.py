"""Command-line entrypoint for reproducible local analysis."""
import argparse
from pathlib import Path

from .reporting import export_bundle
from .service import AnalysisService
from .phase2_models import AnalysisRequest


def parse_args():
    parser = argparse.ArgumentParser(description="CrossBorder AI Analytics 4.0.0")
    parser.add_argument("input", help="CSV或XLSX订单数据")
    parser.add_argument("--source-currency", required=True, help="无currency字段时的全表源币种")
    parser.add_argument("--target-currency", default="CNY", help="基准币种，默认CNY")
    parser.add_argument("--fx-rates", help="可选汇率CSV")
    parser.add_argument("--offline", action="store_true", help="禁用在线汇率")
    parser.add_argument("--database", default="database/ecommerce.db", help="SQLite数据库路径")
    parser.add_argument("--backend", choices=("sql", "pandas"), default="sql", help="分析后端，默认sql")
    parser.add_argument("--period-type", choices=("month", "week", "event"), default="month", help="比较周期，默认自然月")
    parser.add_argument("--start-date", help="可选分析范围开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", help="可选分析范围结束日期 YYYY-MM-DD")
    parser.add_argument("--period-start", help="活动期开始日期")
    parser.add_argument("--period-end", help="活动期结束日期")
    parser.add_argument("--comparison-start", help="等长对照期开始日期")
    parser.add_argument("--comparison-end", help="等长对照期结束日期")
    parser.add_argument("-o", "--output-dir", default="outputs/latest")
    return parser.parse_args()


def main():
    args = parse_args()
    service = AnalysisService(
        cache_dir=Path(".cache/fx"),
        database_path=Path(args.database),
        backend=args.backend,
    )
    context = service.prepare(
        args.input,
        source_currency=args.source_currency,
        target_currency=args.target_currency,
        fx_rates=args.fx_rates,
        online_fx=not args.offline,
    )
    filters = {}
    if args.start_date and args.end_date:
        filters["order_date"] = (args.start_date, args.end_date)
    request = AnalysisRequest(
        filters=filters, period_type=args.period_type, period_start=args.period_start,
        period_end=args.period_end, comparison_start=args.comparison_start,
        comparison_end=args.comparison_end,
    )
    bundle = service.run(context, request=request)
    if any(result.status.value == "FATAL" for result in bundle.results.values()):
        for result in bundle.results.values():
            if result.status.value == "FATAL":
                print("FATAL: {}".format(result.message))
        return 1
    paths = export_bundle(bundle, args.output_dir)
    print("分析完成")
    for name, path in paths.items():
        print("{}: {}".format(name, path.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
