"""Cross-border business capability and data improvement assessment."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import pandas as pd

from autoclean.analytics import assess_data_quality

from .decision import resolve_market_field
from .modules import complete_months
from .phase2_models import (
    AnalysisCapability, CapabilityStatus, DataQualitySummary, FieldQuality,
    ImprovementPlan, QualityDimension, QualityRating,
)
from .phase2_utils import stable_id, utc_now


FIELD_MEANINGS = {
    "order_id": ("订单 ID", "支持订单粒度和订单数"),
    "order_date": ("订单日期", "支持趋势、周期比较和月度归因"),
    "total_amount": ("订单金额", "支持 GMV（成交总额）和客单价"),
    "product_id": ("SKU", "支持商品贡献和生命周期分析"),
    "product_name": ("商品名称", "改善商品结果的可读性"),
    "category": ("品类", "支持品类结构和贡献分析"),
    "customer_id": ("客户 ID", "支持客户、RFM（客户价值模型）和复购分析"),
    "country": ("国家", "支持国家市场分析"),
    "region": ("区域", "在国家不可用时支持区域市场分析"),
    "quantity": ("商品数量", "支持销量分析"),
    "profit_amount": ("订单利润", "支持利润、利润率和增长质量判断"),
    "cost_amount": ("订单成本", "支持净利润和毛利分析"),
    "refund_amount": ("退款金额", "支持真实退款损失分析"),
    "ad_spend": ("广告花费", "支持 ROAS 和广告投入效率分析"),
    "campaign_id": ("活动 ID", "支持活动归因分析"),
    "inventory_available": ("可用库存", "支持库存缺货影响分析"),
    "stockout_flag": ("缺货标记", "支持缺货率和库存风险分析"),
    "return_reason": ("退货原因", "支持退货原因归因"),
    "shipping_status": ("发货状态", "支持履约与发货归因"),
    "channel": ("渠道", "支持渠道组合分析"),
    "store_id": ("店铺 ID", "支持店铺组合分析"),
    "returned": ("退货状态", "支持退货率和风险暴露分析"),
    "shipping_cost": ("物流成本", "支持履约成本分析"),
    "delivery_time_days": ("配送时长", "支持履约体验分析"),
    "currency": ("订单币种", "支持跨币种金额汇总"),
}


def _field_complete(frame: pd.DataFrame, field: str, threshold: float = 0.8) -> bool:
    return field in frame and (frame[field].notna().mean() if len(frame) else 1.0) >= threshold


def _capability(
    capability_id: str, name: str, supported: Sequence[str], unsupported: Sequence[str],
    reasons: Sequence[str], affected: Sequence[str], unaffected: Sequence[str],
) -> AnalysisCapability:
    if supported and not unsupported:
        status = CapabilityStatus.FULL
    elif supported:
        status = CapabilityStatus.PARTIAL
    else:
        status = CapabilityStatus.UNSUPPORTED
    return AnalysisCapability(
        capability_id, name, status, tuple(supported), tuple(unsupported), tuple(reasons),
        tuple(affected), tuple(unaffected),
    )


def build_capability_map(context) -> List[AnalysisCapability]:
    frame = context.analysis_data
    complete, _ = complete_months(frame) if "order_date" in frame else ([], [])
    market_field = resolve_market_field(frame)
    markets = int(frame[market_field].nunique(dropna=True)) if market_field else 0
    customers = int(frame["customer_id"].nunique(dropna=True)) if "customer_id" in frame else 0
    capabilities = []

    sales_supported = ["GMV、订单数和客单价"] if {"order_id", "total_amount"}.issubset(frame) else []
    sales_unsupported = [] if len(complete) >= 2 else ["完整周期趋势和环比"]
    capabilities.append(_capability(
        "sales_analysis", "销售分析", sales_supported, sales_unsupported,
        (() if len(complete) >= 2 else ("完整月份少于 2 个",)), ("销售分析",),
        ("商品销售排行",) if "product_id" in frame else (),
    ))

    order_total_lines = (
        context.metadata.get("data_grain") == "order_item"
        and context.metadata.get("amount_semantic") == "order_total"
    )
    product_supported = ["商品销量"] if "product_id" in frame else []
    if {"product_id", "total_amount"}.issubset(frame) and not order_total_lines:
        product_supported.append("商品销售贡献")
    product_unsupported = [] if _field_complete(frame, "profit_amount") else ["商品利润贡献"]
    if order_total_lines:
        product_unsupported.append("商品 GMV 贡献")
    capabilities.append(_capability(
        "product_analysis", "商品分析", product_supported, product_unsupported,
        tuple(
            reason for reason in (
                None if _field_complete(frame, "profit_amount") else "缺少或利润字段完整率低于 80%",
                "订单总金额重复在商品行，无法无损分摊到 SKU" if order_total_lines else None,
            ) if reason
        ),
        ("商品分析",), ("销售趋势",),
    ))

    profit_ready = _field_complete(frame, "profit_amount")
    capabilities.append(_capability(
        "profit_analysis", "利润分析", ["利润和利润率"] if profit_ready else [],
        [] if profit_ready else ["利润率、高销售低利润商品和市场利润质量"],
        (() if profit_ready else ("缺少或利润字段完整率低于 80%",)),
        ("利润分析", "商品分析", "市场分析"), ("GMV", "订单数"),
    ))

    commercial_fields = [
        "cost_amount",
        "refund_amount",
        "ad_spend",
        "campaign_id",
        "inventory_available",
        "stockout_flag",
        "return_reason",
        "shipping_status",
        "channel",
        "store_id",
    ]
    commercial_present = [field for field in commercial_fields if _field_complete(frame, field, 0.5)]
    commercial_missing = [field for field in ("cost_amount", "refund_amount", "ad_spend") if not _field_complete(frame, field)]
    capabilities.append(_capability(
        "commercial_attribution", "商业归因", ["净利润、退款、广告和库存归因"] if commercial_present else [],
        [] if commercial_present else ["净利润、退款、广告和库存归因"],
        tuple(
            reason for reason in (
                None if _field_complete(frame, "cost_amount") else "缺少成本字段",
                None if _field_complete(frame, "refund_amount") else "缺少退款字段",
                None if _field_complete(frame, "ad_spend") else "缺少广告花费字段",
                None if _field_complete(frame, "inventory_available") and _field_complete(frame, "stockout_flag") else "库存可用量或缺货字段不足",
                None if _field_complete(frame, "return_reason") else "缺少退货原因字段",
                None if _field_complete(frame, "campaign_id") or _field_complete(frame, "channel") or _field_complete(frame, "store_id") else "缺少活动、渠道或店铺维度",
            ) if reason
        ),
        ("利润分析", "商品分析", "市场分析", "退货分析", "库存分析"), ("GMV", "订单数"),
    ))

    customer_supported = ["客户数和客户构成"] if customers else []
    customer_unsupported = [] if customers >= 100 else ["稳定的 RFM 和高价值客户判断"]
    capabilities.append(_capability(
        "customer_analysis", "客户分析", customer_supported, customer_unsupported,
        (() if customers >= 100 else (("缺少 customer_id",) if not customers else ("客户数少于 100",))),
        ("客户分析", "RFM"), ("销售趋势", "商品销量排行"),
    ))

    market_supported = ["市场 GMV 和市场贡献"] if market_field and markets >= 2 else []
    market_unsupported = [] if market_supported and profit_ready else ["市场利润质量"]
    capabilities.append(_capability(
        "market_analysis", "市场分析", market_supported, market_unsupported,
        (() if market_supported else ("缺少市场字段或市场数量少于 2",)),
        ("区域市场",), ("全局经营总览",),
    ))

    return_ready = _field_complete(frame, "returned")
    capabilities.append(_capability(
        "return_analysis", "退货风险", ["退货率和退货关联 GMV"] if return_ready else [],
        [] if return_ready else ["高退货商品和高风险市场"],
        (() if return_ready else ("缺少或退货字段完整率低于 80%",)),
        ("退货与运营",), ("GMV", "利润分析", "商业归因") if profit_ready else ("GMV",),
    ))

    quality_supported = market_supported and profit_ready and return_ready
    capabilities.append(_capability(
        "market_quality", "市场增长质量", ["市场质量评分和增长保护指标"] if quality_supported else [],
        [] if quality_supported else ["市场增长质量评分"],
        (() if quality_supported else ("市场、利润或退货证据不完整",)),
        ("区域市场", "风险中心"), ("全局销售趋势",),
    ))

    capabilities.append(_capability(
        "seasonality", "季节性分析", ["季节性模式"] if len(complete) >= 24 else [],
        [] if len(complete) >= 24 else ["正式季节性判断"],
        (() if len(complete) >= 24 else ("完整月份少于 24 个",)),
        ("销售分析",), ("月度环比",),
    ))
    return capabilities


def build_improvement_plan(context, capabilities: Sequence[AnalysisCapability]) -> List[ImprovementPlan]:
    frame = context.analysis_data
    candidates = (
        ("profit_amount", "P0", "补充 SKU 成本或订单利润", "利润与增长质量判断不可用", ("利润分析", "商品盈利分析", "市场增长质量")),
        ("cost_amount", "P1", "补充订单成本", "净利润和毛利判断不可用", ("净利润", "毛利分析", "广告投放效率")),
        ("refund_amount", "P1", "补充退款金额", "真实退款损失不可见", ("退款损失", "退货原因归因")),
        ("ad_spend", "P1", "补充广告花费", "ROAS 和广告效率不可见", ("ROAS", "广告投入效率")),
        ("inventory_available", "P2", "补充可用库存", "库存缺货影响不可见", ("库存缺货分析", "补货优先级")),
        ("stockout_flag", "P2", "补充缺货标记", "缺货率不可见", ("库存缺货分析", "库存预警")),
        ("campaign_id", "P2", "补充活动 ID", "活动归因不可见", ("活动增量", "投放归因")),
        ("return_reason", "P2", "补充退货原因", "退货原因归因不可见", ("退货原因分析",)),
        ("shipping_status", "P3", "补充发货状态", "履约归因不可见", ("履约质量",)),
        ("channel", "P3", "补充渠道字段", "渠道组合分析不可见", ("渠道分析",)),
        ("store_id", "P3", "补充店铺字段", "店铺组合分析不可见", ("店铺分析",)),
        ("customer_id", "P1", "补充稳定客户 ID", "客户价值和复购判断不可用", ("RFM", "复购分析", "高价值客户识别")),
        ("returned", "P2", "补充退货状态", "退货风险判断不可用", ("高退货商品", "高风险市场")),
        ("shipping_cost", "P3", "补充物流成本", "履约成本不可见", ("物流成本分析", "市场履约质量")),
    )
    output = []
    for field, priority, action, impact, unlocked in candidates:
        if field in frame:
            continue
        output.append(ImprovementPlan(
            stable_id("imp", field, priority), priority, "缺少 {}".format(field), impact,
            action, tuple(unlocked),
        ))
    return output


def assess_business_quality(context, dataset_id: str, scope_id: str):
    quality_context = context
    if (
        context.metadata.get("data_grain") in {"order_item", "canonical_order_line"}
        and "record_id" in context.analysis_data
    ):
        quality_context = replace(
            context,
            contract=replace(context.contract, grain_key="record_id"),
        )
    generic = assess_data_quality(quality_context)
    summary = DataQualitySummary(
        dataset_id=dataset_id,
        scope_id=scope_id,
        quality_score=generic.quality_score,
        quality_rating=QualityRating(generic.quality_rating),
        quality_explanation=generic.quality_explanation,
        completeness=generic.completeness,
        validity=generic.validity,
        field_coverage=generic.field_coverage,
        uniqueness=generic.uniqueness,
        time_coverage=generic.time_coverage,
        fatal_issues=generic.fatal_issues,
        warning_issues=generic.warning_issues,
        calculated_at=utc_now(),
    )
    dimensions = [QualityDimension(
        item.dimension, item.score, item.weight, item.status, item.finding, item.recommendation
    ) for item in generic.dimensions]
    fields = []
    for item in generic.fields:
        meaning, impact = FIELD_MEANINGS.get(item.field, (item.field, "用于已注册的相关分析"))
        fields.append(FieldQuality(
            dataset_id, scope_id, item.field, meaning,
            "PRESENT" if item.present else "MISSING",
            item.completeness_rate, item.validity_rate, item.uniqueness_rate,
            item.status, impact if item.present else "{}不可用".format(impact),
        ))
    capabilities = build_capability_map(quality_context)
    improvements = build_improvement_plan(quality_context, capabilities)
    unsupported = [
        {"capability_id": item.capability_id, "name": item.name, "conclusion": conclusion, "reasons": list(item.reasons)}
        for item in capabilities for conclusion in item.unsupported_conclusions
    ]
    return summary, dimensions, fields, capabilities, improvements, unsupported


def build_data_quality_report(context) -> Dict[str, Any]:
    """Backward-compatible dictionary report used by earlier UI integrations."""
    dataset_id = str(context.metadata.get("dataset_id") or context.metadata.get("sha256") or "unpersisted")
    summary, dimensions, fields, capabilities, improvements, unsupported = assess_business_quality(
        context, dataset_id, "legacy"
    )
    return {
        "summary": summary.to_dict(),
        "dimensions": [item.to_dict() for item in dimensions],
        "fields": [item.to_dict() for item in fields],
        "capabilities": [item.to_dict() for item in capabilities],
        "improvements": [item.to_dict() for item in improvements],
        "unsupported_conclusions": unsupported,
    }


def quality_summary_frame(report: Mapping[str, Any]) -> pd.DataFrame:
    return pd.DataFrame([report.get("summary", {})])


def quality_dimensions_frame(report: Mapping[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(report.get("dimensions", []))
