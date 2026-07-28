"""Versioned metric, anomaly, and recommendation catalogs."""
from __future__ import annotations

from .phase2_models import ActionType, AnomalyRule, MetricDefinition, RecommendationRule


COMMON_DIMENSIONS = ("global", "market", "category", "sku")
COMMON_TIME_GRAINS = ("selection", "month", "week", "event")


def _metric(
    metric_id, name, meaning, formula, *, numerator=None, denominator=None,
    unit="count", required=(), dimensions=COMMON_DIMENSIONS, minimum_sample=1,
    capability="sales_analysis", currency_policy="not_applicable",
):
    return MetricDefinition(
        metric_id=metric_id,
        name=name,
        business_meaning=meaning,
        formula=formula,
        numerator=numerator,
        denominator=denominator,
        unit=unit,
        currency_policy=currency_policy,
        grain=("dataset", "scope", "entity", "period"),
        supported_dimensions=tuple(dimensions),
        time_grain=COMMON_TIME_GRAINS,
        comparison_mode=("period_over_period", "explicit_event"),
        required_fields=tuple(required),
        minimum_sample=minimum_sample,
        null_policy="missing required input returns unavailable",
        zero_denominator_policy="return unavailable, never zero",
        quality_gate="A_OR_B_FOR_DECISIONS",
        capability_gate=capability,
        source_query="metric_aggregate_v1",
        version="1.0.0",
        owner="CrossBorder Analytics",
        limitations=("日期字段按自然日处理",),
    )


METRICS_CATALOG = (
    _metric("gmv", "GMV（成交总额）", "所选范围内按确认金额语义计算的成交金额", "SUM(gmv_amount_base)", unit="currency", required=("order_id", "total_amount"), currency_policy="target_currency_with_full_fx_coverage"),
    _metric("orders", "订单数", "唯一订单数量", "COUNT(order_id)", required=("order_id",)),
    _metric("aov", "AOV（平均客单价）", "每笔订单的平均成交金额", "gmv / orders", numerator="gmv", denominator="orders", unit="currency", required=("order_id", "total_amount"), currency_policy="target_currency_with_full_fx_coverage"),
    _metric("units", "销量", "所选范围内的商品数量", "SUM(quantity)", required=("quantity",)),
    _metric("customers", "客户数", "唯一客户数量", "COUNT(DISTINCT customer_id)", required=("customer_id",), dimensions=("global", "market"), capability="customer_analysis"),
    _metric("profit", "利润", "订单利润额合计", "SUM(profit_amount_base)", unit="currency", required=("profit_amount",), capability="profit_analysis", currency_policy="target_currency_with_full_fx_coverage"),
    _metric("profit_margin", "利润率", "利润占 GMV 的比例", "profit / gmv", numerator="profit", denominator="gmv", unit="ratio", required=("profit_amount", "total_amount"), capability="profit_analysis"),
    _metric("cost_amount", "成本", "订单成本合计", "SUM(cost_amount_base)", unit="currency", required=("cost_amount",), capability="commercial_attribution", currency_policy="target_currency_with_full_fx_coverage"),
    _metric("refund_amount", "退款金额", "退款金额合计", "SUM(refund_amount_base)", unit="currency", required=("refund_amount",), capability="commercial_attribution", currency_policy="target_currency_with_full_fx_coverage"),
    _metric("ad_spend", "广告花费", "广告花费合计", "SUM(ad_spend_base)", unit="currency", required=("ad_spend",), capability="commercial_attribution", currency_policy="target_currency_with_full_fx_coverage"),
    _metric("roas", "ROAS", "广告投入产出比", "gmv / ad_spend", numerator="gmv", denominator="ad_spend", unit="ratio", required=("ad_spend", "total_amount"), capability="commercial_attribution", currency_policy="target_currency_with_full_fx_coverage"),
    _metric("net_profit", "净利润", "扣除退款和广告后的净利润", "profit - refund - ad_spend", unit="currency", required=("profit_amount", "refund_amount", "ad_spend"), capability="commercial_attribution", currency_policy="target_currency_with_full_fx_coverage"),
    _metric("inventory_available", "可用库存", "可用库存数量合计", "SUM(inventory_available)", unit="count", required=("inventory_available",), capability="commercial_attribution"),
    _metric("stockout_rate", "缺货率", "缺货订单占订单数的比例", "stockout_orders / orders", numerator="stockout_orders", denominator="orders", unit="ratio", required=("stockout_flag", "order_id"), capability="commercial_attribution"),
    _metric("return_rate", "退货率", "退货订单占订单数的比例", "returned_orders / orders", numerator="returned_orders", denominator="orders", unit="ratio", required=("returned", "order_id"), capability="return_analysis"),
    _metric("growth_rate", "增长率", "当前值相对上一完整等长周期的变化", "(current - previous) / ABS(previous)", numerator="current_minus_previous", denominator="abs_previous", unit="ratio", required=("order_date",), capability="sales_analysis"),
    _metric("product_contribution", "商品贡献率", "SKU GMV 占筛选范围总 GMV 的比例", "product_gmv / filtered_total_gmv", numerator="product_gmv", denominator="filtered_total_gmv", unit="ratio", required=("product_id", "total_amount"), dimensions=("sku",), capability="product_analysis"),
    _metric("market_contribution", "市场/品类贡献率", "市场或品类 GMV 占筛选范围总 GMV 的比例", "entity_gmv / filtered_total_gmv", numerator="entity_gmv", denominator="filtered_total_gmv", unit="ratio", required=("total_amount",), dimensions=("market", "category"), capability="market_analysis"),
    _metric("market_quality_score", "市场质量评分", "规模、增长、利润和退货健康度的综合评分", "gmv_pct*0.30 + growth_pct*0.25 + margin_pct*0.25 + return_health_pct*0.20", unit="score", required=("order_date", "total_amount", "profit_amount", "returned"), dimensions=("market",), minimum_sample=30, capability="market_quality"),
)

METRIC_BY_ID = {item.metric_id: item for item in METRICS_CATALOG}


ANOMALY_RULES = (
    AnomalyRule("ANOM-GMV-DROP", "GMV 异常下降", "gmv", ("global", "market", "category", "sku"), "period_over_period", 1, "decrease", -0.20, {"global": 30, "market": 30, "category": 30, "sku": 10}, "gmv_change", "impact_and_duration", "A_OR_B", "sales_analysis", "next complete period no longer triggers", "1.0.0"),
    AnomalyRule("ANOM-GMV-SPIKE", "GMV 异常增长", "gmv", ("global", "market", "category", "sku"), "period_over_period", 1, "increase", 0.30, {"global": 30, "market": 30, "category": 30, "sku": 10}, "gmv_change", "impact_and_duration", "A_OR_B", "sales_analysis", "next complete period no longer triggers", "1.0.0"),
    AnomalyRule("ANOM-MARGIN-DROP", "利润率下降", "profit_margin", ("global", "market", "category", "sku"), "period_over_period", 1, "decrease_pp", -0.05, {"global": 30, "market": 30, "category": 30, "sku": 10}, "profit_change", "impact_and_duration", "A_OR_B", "profit_analysis", "margin decline below five points", "1.0.0"),
    AnomalyRule("ANOM-HIGH-SALES-LOW-MARGIN", "高销售低利润 SKU", "profit_margin", ("sku",), "cross_section", 0, "low_margin", 0.0, {"sku": 10}, "profit_change", "impact_and_duration", "A_OR_B", "profit_analysis", "margin returns above portfolio guardrail", "1.0.0"),
    AnomalyRule("ANOM-HIGH-RETURN", "高退货对象", "return_rate", ("global", "market", "category", "sku"), "cross_section", 0, "high", 0.20, {"global": 20, "market": 20, "category": 20, "sku": 20}, "returned_gmv_exposure", "impact_and_duration", "A_OR_B", "return_analysis", "return rate falls below thresholds", "1.0.0", ("退货关联 GMV 不代表实际退款损失",)),
    AnomalyRule("ANOM-MARKET-UNHEALTHY-GROWTH", "市场增长质量恶化", "gmv", ("market",), "period_over_period", 1, "compound", 0.20, {"market": 30}, "gmv_change", "impact_and_duration", "A_OR_B", "market_quality", "growth guardrails recover", "1.0.0"),
    AnomalyRule("ANOM-MIX-SHIFT", "品类或市场贡献突变", "market_contribution", ("market", "category"), "period_over_period", 1, "absolute_pp", 0.10, {"market": 30, "category": 30}, "gmv_change", "impact_and_duration", "A_OR_B", "sales_analysis", "share shift below threshold", "1.0.0"),
    AnomalyRule("ANOM-AOV-DROP", "客单价下降", "aov", ("global", "market", "category"), "period_over_period", 1, "decrease", -0.15, {"global": 30, "market": 30, "category": 30}, "gmv_change", "impact_and_duration", "A_OR_B", "sales_analysis", "AOV decline below threshold", "1.0.0"),
    AnomalyRule("ANOM-HERO-GROWTH-RISK", "爆品增长质量风险", "gmv", ("sku",), "period_over_period", 1, "compound", 0.50, {"sku": 10}, "gmv_change", "impact_and_duration", "A_OR_B", "product_analysis", "growth quality guardrails recover", "1.0.0", ("该规则不预测未来销量",)),
)


RECOMMENDATION_RULES = (
    RecommendationRule("REC-GMV-ORDERS", ("ANOM-GMV-DROP",), ("VERIFIED_DRIVER", "LIKELY_DRIVER"), ("orders",), (), (), ActionType.INVESTIGATE, "定位 {entity} 订单减少最集中的市场、品类和 SKU，再核对流量、库存与活动变化", "市场运营负责人", "gmv", ("profit_margin", "return_rate"), "下一个完整可比较周期", "利润率下降 5 个百分点或退货率上升 5 个百分点时停止后续经营调整", "1.1.0"),
    RecommendationRule("REC-GMV-AOV", ("ANOM-GMV-DROP",), ("VERIFIED_DRIVER", "LIKELY_DRIVER"), ("aov",), (), (), ActionType.OPTIMIZE, "检查 {entity} 的低价 SKU 占比、折扣率和价格带结构，先在主要影响商品上验证组合与定价调整", "商品运营负责人", "gmv", ("profit_margin", "return_rate"), "下一个完整可比较周期", "利润率下降 5 个百分点或退货率上升 5 个百分点时停止调整", "1.1.0"),
    RecommendationRule("REC-AOV-MIX", ("ANOM-AOV-DROP", "ANOM-MIX-SHIFT"), ("VERIFIED_DRIVER", "LIKELY_DRIVER"), ("aov", "numerator", "denominator", "sku", "category"), (), (), ActionType.OPTIMIZE, "检查 {entity} 的低价 SKU 占比、折扣率、加购和价格带结构", "商品运营负责人", "aov", ("profit_margin", "return_rate"), "下一个完整可比较周期", "利润率下降 5 个百分点或退货率上升 5 个百分点时停止调整", "1.1.0"),
    RecommendationRule("REC-MARGIN-SKU", ("ANOM-MARGIN-DROP", "ANOM-HIGH-SALES-LOW-MARGIN"), ("VERIFIED_DRIVER", "LIKELY_DRIVER"), ("numerator", "denominator", "internal_margin"), (), (), ActionType.OPTIMIZE, "审核 {entity} 主要驱动 SKU 的售价、成本、折扣和履约成本", "商品运营与财务负责人", "profit_margin", ("gmv", "return_rate"), "下一个完整可比较周期", "GMV 明显下降或退货率达到高风险阈值时停止调整", "1.1.0"),
    RecommendationRule("REC-RETURN-SKU", ("ANOM-HIGH-RETURN",), ("VERIFIED_DRIVER", "LIKELY_DRIVER"), ("returned_orders", "orders", "sku", "market"), (), (), ActionType.INVESTIGATE, "检查 {entity} 高退货商品的质量、描述、尺码和退货原因", "售后与商品质量负责人", "return_rate", ("gmv", "profit_margin"), "下一个完整可比较周期", "缺少退货原因码时不执行商品下架等确定性动作", "1.1.0"),
    RecommendationRule("REC-MARKET-GROWTH-RISK", ("ANOM-MARKET-UNHEALTHY-GROWTH",), ("VERIFIED_DRIVER", "LIKELY_DRIVER"), ("orders", "aov"), (), (), ActionType.INVESTIGATE, "暂停扩大 {entity} 的投入，先核对本期利润率、退货率和增长集中 SKU", "市场运营负责人", "profit_margin", ("gmv", "return_rate"), "下一个完整可比较周期", "利润率或退货率未恢复到保护范围前不扩大投入", "1.1.0"),
    RecommendationRule("REC-HERO-GROWTH-RISK", ("ANOM-HERO-GROWTH-RISK",), ("VERIFIED_DRIVER", "LIKELY_DRIVER"), ("orders", "aov"), (), (), ActionType.INVESTIGATE, "暂停扩大 {entity} 的备货和曝光，先核对利润率、退货率及增长来源", "商品运营负责人", "profit_margin", ("gmv", "return_rate"), "下一个完整可比较周期", "利润率或退货率未恢复到保护范围前不扩大备货和曝光", "1.1.0"),
    RecommendationRule("REC-MARKET-SCALE", ("ANOM-GMV-SPIKE",), ("VERIFIED_DRIVER",), ("orders", "aov"), ("healthy_guardrails",), ("quality_below_B",), ActionType.SCALE, "在利润率和退货率健康的前提下，对 {entity} 进行小范围增量投入", "市场运营负责人", "gmv", ("profit_margin", "return_rate"), "下一个完整可比较周期", "利润率下降或退货率上升达到 5 个百分点时停止增量投入", "1.1.0"),
)
