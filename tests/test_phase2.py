from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from crossborder_analytics.evidence import EvidenceService
from crossborder_analytics.phase2_models import AnalysisRequest
from crossborder_analytics.phase2_storage import ArtifactStore
from crossborder_analytics.phase2_ui import build_risk_items, latest_priority_insights
from crossborder_analytics.reporting import export_bundle
from crossborder_analytics.service import AnalysisService


def _source(tmp_path: Path, *, optional=True) -> Path:
    rows = []
    order_number = 0
    for month in range(1, 5):
        end = pd.Timestamp(2025, month, 1) + pd.offsets.MonthEnd(0)
        dates = pd.date_range(pd.Timestamp(2025, month, 1), end, periods=40).normalize()
        for index, day in enumerate(dates):
            order_number += 1
            amount = 100.0 if month < 4 else 60.0
            row = {
                "order_id": "O{:04d}".format(order_number),
                "order_date": day.date().isoformat(),
                "total_amount": amount,
                "product_id": "P1" if index < 25 else "P2",
                "category": "核心品类" if index < 25 else "辅助品类",
                "region": "东区" if index % 2 else "西区",
                "quantity": 1,
            }
            if optional:
                row.update({
                    "customer_id": "C{:03d}".format(index % 35),
                    "profit_amount": amount * (.20 if month < 4 else .08),
                    "returned": bool(month == 4 and index < 12),
                })
            rows.append(row)
    path = tmp_path / "orders.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _bundle(tmp_path, *, optional=True, request=None):
    source = _source(tmp_path, optional=optional)
    service = AnalysisService(cache_dir=tmp_path / "fx", database_path=tmp_path / "phase2.db")
    context = service.prepare(source, source_currency="CNY", target_currency="CNY")
    return service.run(context, request=request), service


def test_phase2_persists_stable_metrics_and_replays_evidence(tmp_path):
    bundle, service = _bundle(tmp_path)
    assert bundle.metadata.get("phase2_error") is None
    assert bundle.artifacts.data_quality.quality_rating in {"A", "B"}
    assert bundle.artifacts.metric_snapshots
    assert bundle.artifacts.evidence
    assert all(item.evidence_id for item in bundle.artifacts.metric_snapshots)

    context = service.prepare(_source(tmp_path), source_currency="CNY", target_currency="CNY")
    repeated = service.run(context)
    assert [item.snapshot_id for item in repeated.artifacts.metric_snapshots] == [
        item.snapshot_id for item in bundle.artifacts.metric_snapshots
    ]
    replay = EvidenceService(tmp_path / "phase2.db").replay(bundle.artifacts.evidence[0].evidence_id)
    assert replay["matched"] is True

    with sqlite3.connect(tmp_path / "phase2.db") as connection:
        assert connection.execute("SELECT status FROM analysis_runs").fetchone()[0] == "READY"
        assert connection.execute("SELECT COUNT(*) FROM metric_snapshots").fetchone()[0] == len(bundle.artifacts.metric_snapshots)
        assert connection.execute("SELECT COUNT(*) FROM insights").fetchone()[0] == len(bundle.artifacts.insights)


def test_missing_business_fields_disable_metrics_and_create_improvement_plan(tmp_path):
    bundle, _ = _bundle(tmp_path, optional=False)
    metric_ids = {item.metric_id for item in bundle.artifacts.metric_snapshots}
    assert "profit" not in metric_ids
    assert "profit_margin" not in metric_ids
    assert "return_rate" not in metric_ids
    capability = {item.capability_id: str(item.status) for item in bundle.artifacts.analysis_capability}
    assert capability["profit_analysis"] == "UNSUPPORTED"
    assert capability["return_analysis"] == "UNSUPPORTED"
    priorities = {item.issue: item.priority for item in bundle.artifacts.data_improvement_plan}
    assert priorities["缺少 profit_amount"] == "P0"
    assert priorities["缺少 customer_id"] == "P1"


def test_complete_period_rules_diagnoses_and_recommendations_are_auditable(tmp_path):
    bundle, _ = _bundle(tmp_path)
    complete_months = [
        item for item in bundle.artifacts.metric_snapshots
        if item.metric_id == "gmv" and item.entity_type == "global" and item.period_type == "month" and item.is_complete_period
    ]
    assert [item.period_start for item in complete_months] == [
        "2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01"
    ]
    drops = [item for item in bundle.artifacts.anomalies if item.rule_id == "ANOM-GMV-DROP" and str(item.status) == "DETECTED"]
    assert drops
    diagnoses = {item.anomaly_id: item for item in bundle.artifacts.diagnoses}
    diagnosis = diagnoses[drops[-1].anomaly_id]
    assert diagnosis.explained_share == pytest.approx(1.0)
    assert diagnosis.residual_share == pytest.approx(0.0)
    assert str(diagnosis.status) == "VERIFIED_DRIVER"
    recommendations = [item for item in bundle.artifacts.recommendations if item.diagnosis_id == diagnosis.diagnosis_id]
    assert recommendations
    assert recommendations[0].validation_period
    assert recommendations[0].stop_condition
    assert recommendations[0].evidence_ids


def test_gmv_drop_recommendation_follows_aov_driver(tmp_path):
    bundle, _ = _bundle(tmp_path)
    drops = [
        item for item in bundle.artifacts.anomalies
        if item.rule_id == "ANOM-GMV-DROP" and str(item.status) == "DETECTED"
    ]
    diagnoses = {item.anomaly_id: item for item in bundle.artifacts.diagnoses}
    recommendations = {item.diagnosis_id: item for item in bundle.artifacts.recommendations}
    diagnosis = diagnoses[drops[-1].anomaly_id]
    recommendation = recommendations[diagnosis.diagnosis_id]

    assert diagnosis.primary_driver == "客单价"
    assert recommendation.rule_id == "REC-GMV-AOV"
    assert "价格带结构" in recommendation.action
    assert str(recommendation.action_type) == "OPTIMIZE"


def test_aov_anomaly_explains_numerator_and_denominator_before_price_mix_drilldown(tmp_path):
    bundle, _ = _bundle(tmp_path)
    aov_anomalies = [
        item for item in bundle.artifacts.anomalies
        if item.rule_id == "ANOM-AOV-DROP" and str(item.status) == "DETECTED"
    ]
    diagnoses = {item.anomaly_id: item for item in bundle.artifacts.diagnoses}
    diagnosis = diagnoses[aov_anomalies[-1].anomaly_id]
    recommendation = next(
        item for item in bundle.artifacts.recommendations
        if item.diagnosis_id == diagnosis.diagnosis_id
    )

    assert str(diagnosis.status) == "VERIFIED_DRIVER"
    assert diagnosis.explained_share == pytest.approx(1.0)
    assert {item["driver_code"] for item in diagnosis.driver_contributions} == {"numerator", "denominator"}
    assert diagnosis.primary_driver == "订单成交金额"
    assert "SKU 价格带结构" in diagnosis.missing_context
    assert recommendation.rule_id == "REC-AOV-MIX"
    assert str(recommendation.action_type) == "OPTIMIZE"


def test_overview_priority_insights_use_latest_period_and_deduplicate(tmp_path):
    bundle, _ = _bundle(tmp_path)
    selected = latest_priority_insights(bundle.artifacts, limit=10)
    snapshots = {item.snapshot_id: item for item in bundle.artifacts.metric_snapshots}
    periods = {snapshots[item.current_snapshot_id].period_start for item in selected}
    keys = {(item.entity_type, item.entity_id, item.metric_id) for item in selected}

    assert len(periods) <= 1
    assert len(keys) == len(selected)


def test_incomplete_period_is_unranked_instead_of_fake_p3(tmp_path):
    request = AnalysisRequest(filters={"order_date": ("2025-01-01", "2025-04-15")})
    bundle, _ = _bundle(tmp_path, request=request)
    suppressed = [item for item in build_risk_items(bundle.artifacts) if item["status"] == "SUPPRESSED"]

    assert suppressed
    assert all(item["priority"] == "UNRANKED" for item in suppressed)
    assert all(item["priority_score"] is None for item in suppressed)


def test_work_item_progress_persists_by_scope_and_anomaly(tmp_path):
    bundle, _ = _bundle(tmp_path)
    anomaly = next(item for item in bundle.artifacts.anomalies if str(item.status) == "DETECTED")
    insight = next(item for item in bundle.artifacts.insights if item.anomaly_id == anomaly.anomaly_id)
    store = ArtifactStore(tmp_path / "phase2.db")

    saved = store.save_work_item(
        bundle.metadata["scope_id"], anomaly.anomaly_id, insight.insight_id,
        "IN_PROGRESS", "华南运营组", "2025-05-31", "已完成价格带初查",
    )
    loaded = {item.anomaly_id: item for item in store.work_items(bundle.metadata["scope_id"])}[anomaly.anomaly_id]

    assert saved.work_item_id == loaded.work_item_id
    assert str(loaded.workflow_status) == "IN_PROGRESS"
    assert loaded.owner == "华南运营组"
    assert loaded.due_date == "2025-05-31"
    assert loaded.resolution_note == "已完成价格带初查"


def test_event_period_requires_equal_explicit_windows_and_exports_v25_manifest(tmp_path):
    with pytest.raises(ValueError, match="equal length"):
        AnalysisRequest(
            period_type="event", period_start="2025-03-01", period_end="2025-03-10",
            comparison_start="2025-02-01", comparison_end="2025-02-05",
        )
    request = AnalysisRequest(
        period_type="event", period_start="2025-03-01", period_end="2025-03-10",
        comparison_start="2025-02-01", comparison_end="2025-02-10",
    )
    bundle, _ = _bundle(tmp_path, request=request)
    event_snapshots = [item for item in bundle.artifacts.metric_snapshots if item.period_type == "event"]
    assert event_snapshots
    paths = export_bundle(bundle, tmp_path / "outputs")
    manifest = pd.read_json(paths["manifest"], typ="series")
    assert manifest["version"] == "2.5.0"
    assert manifest["metric_definitions"]
    assert manifest["insights"]
    assert paths["excel"].exists() and paths["docx"].exists()


def test_opportunity_objects_apply_sample_quality_and_shared_evidence(tmp_path):
    bundle, _ = _bundle(tmp_path)

    assert bundle.artifacts.market_opportunities
    assert all(str(item.status) == "样本不足" for item in bundle.artifacts.market_opportunities)
    assert bundle.artifacts.product_opportunities
    assert {str(item.opportunity_type) for item in bundle.artifacts.product_opportunities} == {"利润修复机会"}
    assert len(bundle.artifacts.action_items) == (
        len(bundle.artifacts.market_opportunities) + len(bundle.artifacts.product_opportunities)
    )
    known_evidence = {item.evidence_id for item in bundle.artifacts.evidence}
    assert all(set(item.evidence_ids).issubset(known_evidence) for item in bundle.artifacts.action_items)
    assert all(item.stop_condition and item.validation_period for item in bundle.artifacts.action_items)


def test_summary_and_scoped_exports_use_opportunity_objects(tmp_path):
    from docx import Document

    bundle, _ = _bundle(tmp_path)
    market = bundle.artifacts.market_opportunities[0].market
    paths = export_bundle(
        bundle, tmp_path / "summary", report_version="summary",
        report_scope="market", scope_value=market, include_action_details=True,
    )
    text = "\n".join(paragraph.text for paragraph in Document(paths["docx"]).paragraphs)
    assert "跨境电商经营分析与行动报告 · 摘要版" in text
    assert "当前不能判断的问题" in text
    sheets = pd.ExcelFile(paths["excel"]).sheet_names
    assert {"市场机会", "产品机会", "行动清单"}.issubset(set(sheets))
    manifest = pd.read_json(paths["manifest"], typ="series")
    assert manifest["market_opportunities"]
    assert manifest["product_opportunities"]
    assert manifest["action_items"]
    assert manifest["report_options"]["scope_value"] == market
