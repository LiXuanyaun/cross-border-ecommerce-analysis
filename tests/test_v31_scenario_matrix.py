import importlib
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

from crossborder_analytics.service import AnalysisService
from crossborder_analytics.reporting import export_bundle


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "ecommerce_sales_34500.csv"

SCENARIO_MATRIX = {
    "S01": ("标准24个月完整数据", "tests.test_analysis:test_sample_acceptance_metrics_and_period_logic"),
    "S02": ("末月未完整", "tests.test_phase2:test_incomplete_period_is_unranked_instead_of_fake_p3"),
    "S03": ("不足2个完整月", "tests.test_analysis:test_missing_optional_modules_skip_without_failing_core"),
    "S04": ("缺少利润字段", "tests.test_phase2:test_missing_business_fields_disable_metrics_and_create_improvement_plan"),
    "S05": ("缺少退货字段", "tests.test_phase2:test_missing_business_fields_disable_metrics_and_create_improvement_plan"),
    "S06": ("缺少客户字段", "tests.test_phase2:test_missing_business_fields_disable_metrics_and_create_improvement_plan"),
    "S07": ("零订单或零分母", "tests.test_sqlite:test_empty_sql_filter_returns_zero_overview_instead_of_failing"),
    "S08": ("重复订单主键", "tests.test_sqlite:test_fatal_grain_conflict_never_persists_orders"),
    "S09": ("订单商品粒度", "tests.test_api:test_order_item_line_amount_counts_unique_orders_and_sums_lines"),
    "S10": ("商品行重复订单总额", "tests.test_api:test_order_item_repeated_order_total_is_deduplicated"),
    "S11": ("多币种且汇率完整", "tests.test_analysis:test_uploaded_fx_converts_all_money_and_keeps_source"),
    "S12": ("汇率覆盖不足", "tests.test_analysis:test_incomplete_fx_skips_consolidated_money_modules"),
    "S13": ("单一市场或品类", "tests.test_decision_workspace:test_market_strategy_rules_and_missing_evidence"),
    "S14": ("所有对象均改善", "tests.test_v31_scenario_matrix:test_s14_all_objects_improve_without_false_anomaly"),
    "S15": ("多个对象同时恶化", "tests.test_v31_scenario_matrix:test_s15_multiple_declines_are_ranked_by_formal_impact"),
    "S16": ("部分国家缺失", "tests.test_decision_workspace:test_country_is_one_dataset_grain_and_partial_missing_is_labeled"),
    "S17": ("中文字段和布尔值", "tests.test_analysis:test_chinese_fields_and_boolean_values_are_normalized"),
    "S18": ("100000行高基数", "tests.test_v31_scenario_matrix:test_s18_100k_complete_pipeline_under_15_seconds"),
    "S19": ("多文件同构合并", "tests.test_api:test_multi_file_order_import_commits_once_with_file_lineage"),
    "S20": ("多文件字段不一致", "tests.test_api:test_multi_file_field_drift_is_cleaned_into_one_dataset"),
}


def _resolve(reference: str):
    module_name, function_name = reference.split(":", 1)
    return getattr(importlib.import_module(module_name), function_name)


def test_v31_s01_s20_have_executable_acceptance_tests():
    assert set(SCENARIO_MATRIX) == {"S{:02d}".format(index) for index in range(1, 21)}
    for scenario_id, (name, reference) in SCENARIO_MATRIX.items():
        assert name, scenario_id
        assert callable(_resolve(reference)), reference


def _two_month_source(current_multiplier: dict[str, float]) -> pd.DataFrame:
    rows = []
    order_number = 0
    for month, end_day in (("2025-01", 31), ("2025-02", 28)):
        for market, multiplier in current_multiplier.items():
            for index in range(40):
                order_number += 1
                amount = 100.0 * (multiplier if month == "2025-02" else 1.0)
                rows.append({
                    "order_id": "O{:05d}".format(order_number),
                    "order_date": "{}-{:02d}".format(month, 1 if index < 20 else end_day),
                    "total_amount": amount,
                    "country": market,
                    "category": "Core",
                    "product_id": "{}-SKU".format(market),
                    "quantity": 1,
                    "profit_amount": amount * 0.2,
                    "returned": False,
                    "customer_id": "C{:05d}".format(order_number),
                })
    return pd.DataFrame(rows)


def _run_frame(frame: pd.DataFrame):
    service = AnalysisService(database_path=None, backend="pandas")
    csv_bytes = frame.to_csv(index=False).encode("utf-8")
    context = service.prepare(csv_bytes, filename="scenario.csv", source_currency="CNY", target_currency="CNY")
    return service.run(context)


def test_s14_all_objects_improve_without_false_anomaly():
    bundle = _run_frame(_two_month_source({"US": 1.1, "DE": 1.1, "JP": 1.1}))
    detected = [item for item in bundle.artifacts.anomalies if str(item.status) == "DETECTED"]
    assert detected == []
    assert bundle.recommendations == []


def test_s15_multiple_declines_are_ranked_by_formal_impact():
    bundle = _run_frame(_two_month_source({"US": 0.5, "DE": 0.6, "JP": 0.7}))
    insights = [item for item in bundle.artifacts.insights if item.type == "ANOMALY"]
    assert len(insights) >= 3
    impacts = [abs(float(item.impact_amount or 0.0)) for item in insights]
    assert [item.priority_score for item in insights] == sorted(
        (item.priority_score for item in insights), reverse=True,
    )
    assert impacts[0] == max(impacts)
    assert all(item.evidence_ids and item.anomaly_id for item in insights)


def test_s18_100k_complete_pipeline_under_15_seconds(tmp_path):
    source_service = AnalysisService(database_path=None, backend="pandas")
    context = source_service.prepare(SAMPLE, source_currency="CNY", target_currency="CNY")
    frames = []
    for batch in range(3):
        frame = context.analysis_data.copy()
        frame["order_id"] = frame["order_id"].astype(str) + "-{}".format(batch)
        frames.append(frame)
    data = pd.concat(frames, ignore_index=True).head(100_000)
    performance_context = replace(
        context,
        raw_data=data.copy(),
        analysis_data=data,
        metadata={**context.metadata, "sha256": "scenario-s18-100k", "rows": len(data)},
    )
    service = AnalysisService(database_path=tmp_path / "s18.db")
    started = time.perf_counter()
    bundle = service.run(performance_context)
    elapsed = time.perf_counter() - started
    assert bundle.metadata.get("phase2_error") is None
    assert len(bundle.artifacts.metric_snapshots) > 0
    assert elapsed <= 15.0, "100k pipeline took {:.3f}s".format(elapsed)
    report_started = time.perf_counter()
    export_bundle(bundle, tmp_path / "report")
    report_elapsed = time.perf_counter() - report_started
    assert report_elapsed <= 30.0, "100k report took {:.3f}s".format(report_elapsed)
