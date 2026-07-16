"""Command-line entrypoint for reproducible local analysis."""
import argparse
from pathlib import Path

from .reporting import export_bundle
from .service import AnalysisService


def parse_args():
    parser = argparse.ArgumentParser(description="CrossBorder AI Analytics 2.0")
    parser.add_argument("input", help="CSV或XLSX订单数据")
    parser.add_argument("--source-currency", required=True, help="无currency字段时的全表源币种")
    parser.add_argument("--target-currency", default="CNY", help="基准币种，默认CNY")
    parser.add_argument("--fx-rates", help="可选汇率CSV")
    parser.add_argument("--offline", action="store_true", help="禁用在线汇率")
    parser.add_argument("-o", "--output-dir", default="outputs/latest")
    return parser.parse_args()


def main():
    args = parse_args()
    service = AnalysisService(cache_dir=Path(".cache/fx"))
    context = service.prepare(
        args.input,
        source_currency=args.source_currency,
        target_currency=args.target_currency,
        fx_rates=args.fx_rates,
        online_fx=not args.offline,
    )
    bundle = service.run(context)
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
