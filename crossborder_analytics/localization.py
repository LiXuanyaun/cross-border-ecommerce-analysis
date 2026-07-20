"""Centralized Chinese display labels for user-facing analytics artifacts."""
from __future__ import annotations

from typing import Any, Mapping, Optional

import pandas as pd


FIELD_LABELS = {
    "absolute_change": "绝对变化",
    "analysis_type": "分析类型",
    "aov": "AOV（平均客单价）",
    "avg_frequency": "平均购买频次",
    "avg_recency": "平均距最近购买天数",
    "baseline_value": "对比期数值",
    "canonical_field": "规范字段",
    "category": "品类",
    "category_conflict": "品类冲突",
    "category_count": "关联品类数",
    "change": "GMV（成交总额）变化",
    "change_rate": "变化率",
    "claim": "数据结论",
    "code": "问题代码",
    "column": "涉及字段",
    "comparison_period": "对比期间",
    "confidence": "置信度",
    "currency": "币种",
    "customer_id": "客户ID",
    "customers": "客户数",
    "delivery_time_days": "配送天数",
    "delivery_mean": "平均配送天数",
    "delivery_median": "配送天数中位数",
    "delivery_p90": "P90（90分位数）配送天数",
    "dimensions": "分析维度",
    "dimension_type": "构成维度",
    "dimension_value": "构成项",
    "details": "问题详情",
    "error_type": "错误类型",
    "evidence_count": "证据数量",
    "f_score": "F（购买频次）评分",
    "filters": "筛选条件",
    "formula": "计算口径",
    "field": "涉及字段",
    "frequency": "购买频次",
    "fx_source": "汇率来源",
    "gmv": "GMV（成交总额）",
    "gmv_share": "GMV占比",
    "share": "构成占比",
    "evidence_id": "证据编号",
    "preference_evidence_id": "偏好证据编号",
    "profit_evidence_id": "收益证据编号",
    "strategy_evidence_id": "策略证据编号",
    "id": "证据编号",
    "issue_type": "问题类型",
    "last_order": "最近购买日期",
    "m_score": "M（消费金额）评分",
    "message": "说明",
    "metric": "指标",
    "missing_fields": "缺失字段",
    "monetary": "消费金额",
    "month": "月份",
    "name": "分析模块",
    "orders": "订单数",
    "order_date": "订单日期",
    "order_id": "订单ID",
    "order_share": "订单占比",
    "period": "分析期间",
    "provider": "汇率服务商",
    "product_id": "商品ID",
    "product_name": "商品名称",
    "primary_category": "主品类",
    "profit": "利润额",
    "profit_amount": "利润额",
    "profit_margin": "利润率",
    "profit_rate": "利润率",
    "r_score": "R（最近购买）评分",
    "rate": "汇率",
    "recency_days": "距最近购买天数",
    "recommended_action": "运营建议",
    "region": "区域",
    "market": "市场",
    "market_source": "市场粒度",
    "relative_change": "相对变化",
    "return_rate": "退货率",
    "returned_gmv_exposure": "退货关联GMV（成交总额）",
    "returned_orders": "退货订单数",
    "returned": "是否退货",
    "sample_size": "样本量",
    "segment": "客户分群",
    "severity": "严重程度",
    "row_count": "涉及行数",
    "source_currency": "源币种",
    "source_field": "源字段",
    "source_fields": "数据字段",
    "status": "状态",
    "target_currency": "目标币种",
    "unit": "单位",
    "units": "销量",
    "quantity": "商品数量",
    "total_amount": "订单金额",
    "value": "数值",
    "classification": "商品分类",
    "first_order": "首次销售日期",
    "scale_health": "规模健康度",
    "profit_health": "利润健康度",
    "return_health": "退货健康度",
    "delivery_health": "履约健康度",
    "scale_benchmark": "规模基准",
    "portfolio_profit_rate": "组合利润率",
    "portfolio_return_rate": "组合退货率",
    "delivery_p90_benchmark": "履约P90基准",
    "strategy": "投入策略",
    "strategy_reason": "策略理由",
    "strategy_confidence": "策略置信度",
    "date": "日期",
    "priority": "优先级",
    "priority_score": "优先级得分",
    "period_start": "周期开始",
    "period_end": "周期结束",
    "entity_type": "对象类型",
    "entity_id": "对象编号",
    "entity_name": "对象名称",
    "metric_id": "指标编号",
    "rule_id": "规则编号",
    "diagnosis_status": "诊断状态",
    "diagnosis_summary": "诊断摘要",
    "recommendation_summary": "行动建议",
    "limitations": "分析限制",
    "impact_amount": "影响金额",
    "quality_score": "质量评分",
    "quality_rating": "可信度等级",
    "capability_id": "能力编号",
    "supported_conclusions": "可回答问题",
    "unsupported_conclusions": "不可回答问题",
    "reasons": "原因",
    "business_meaning": "业务含义",
    "presence_status": "存在状态",
    "completeness_rate": "完整率",
    "validity_rate": "有效率",
    "uniqueness_rate": "唯一率",
    "analysis_impact": "分析影响",
    "improvement_id": "提升计划编号",
    "issue": "数据问题",
    "impact": "业务影响",
    "unlocked_capabilities": "补齐后新增能力",
    "opportunity_id": "机会编号",
    "opportunity_type": "机会类型",
    "operating_status": "当前经营状态",
    "current_period": "当前周期",
    "current_gmv": "当前GMV（成交总额）",
    "previous_gmv": "对比期GMV（成交总额）",
    "gmv_change": "GMV（成交总额）变化金额",
    "gmv_growth_rate": "GMV（成交总额）增长率",
    "current_orders": "当前订单数",
    "previous_orders": "对比期订单数",
    "order_growth_rate": "订单增长率",
    "current_aov": "当前AOV（平均客单价）",
    "previous_aov": "对比期AOV（平均客单价）",
    "profit_margin_change": "利润率变化",
    "return_rate_change": "退货率变化",
    "sku_concentration": "SKU集中度",
    "primary_driver": "主要驱动",
    "driver_contributions": "驱动贡献",
    "top_categories": "主要贡献品类",
    "top_skus": "主要贡献SKU",
    "guardrail_metrics": "保护指标",
    "validation_period": "验证周期",
    "stop_condition": "停止条件",
    "market_coverage": "市场覆盖数",
    "market_growth_contribution": "市场增长贡献",
    "customer_concentration": "客户集中度",
    "high_value_customer_share": "高价值客户占比",
    "primary_market": "主要市场",
    "target_market": "主要机会市场",
    "primary_customer_group": "主要客户群",
    "rationale": "判断依据",
    "action_id": "行动编号",
    "source_type": "行动对象类型",
    "source_id": "来源机会编号",
    "current_judgement": "当前判断",
    "owner_role": "责任对象",
    "evidence_confidence": "证据可信度",
}


FIELD_DEFINITIONS = {
    "gmv": ("所选范围内订单金额合计", "订单金额合计"),
    "orders": ("唯一订单数量", "订单编号去重计数"),
    "customers": ("唯一客户数量", "客户编号去重计数"),
    "units": ("成交商品总件数", "商品数量合计"),
    "aov": ("每笔订单的平均成交金额", "GMV（成交总额）/ 订单数"),
    "profit": ("利润额合计", "单笔利润额合计"),
    "profit_amount": ("利润额合计", "单笔利润额合计"),
    "profit_rate": ("利润占GMV（成交总额）的比例", "利润额 / GMV（成交总额）"),
    "return_rate": ("退货订单占全部订单的比例", "退货订单数 / 订单数"),
    "returned_gmv_exposure": ("退货订单关联的成交金额，不代表实际退款损失", "退货订单金额合计"),
    "month": ("订单所属自然月", "由订单日期按月归集"),
    "classification": ("商品经营四象限分类", "销量P75与组合加权利润率共同判断"),
    "frequency": ("客户购买次数", "客户订单编号去重计数"),
    "monetary": ("客户累计消费金额", "客户订单金额合计"),
    "recency_days": ("距最近一次购买的天数", "分析锚点日期 - 最近购买日期"),
    "segment": ("RFM（客户价值模型）分群", "R/F/M百分位评分1-5"),
    "market": ("整份数据统一使用的市场粒度", "有有效国家时使用国家，否则使用区域"),
    "order_share": ("品类在当前市场的订单偏好", "市场品类订单数 / 市场订单数"),
    "gmv_share": ("对象在当前分组的成交贡献", "对象GMV（成交总额）/ 分组GMV（成交总额）"),
    "strategy": ("基于当前组合基准的市场投入方向", "规模、利润率、退货率与配送P90规则判断"),
    "primary_category": ("商品订单数最多的品类", "按商品和品类订单数降序选择；并列按品类名称稳定排序"),
    "delivery_mean": ("平均配送时长", "配送天数平均值"),
    "delivery_median": ("配送时长中位数", "配送天数50分位数"),
    "delivery_p90": ("90%的订单不超过该配送时长", "配送天数90分位数"),
}


MODULE_LABELS = {
    "dataset": "数据集校验",
    "overview": "经营总览",
    "sales": "销售分析",
    "product": "商品分析",
    "customer": "客户分析",
    "region": "区域市场",
    "market_category": "市场品类",
    "returns": "退货分析",
}

STATUS_LABELS = {
    "SUCCESS": "成功",
    "SKIPPED": "已跳过",
    "FAILED": "失败",
    "FATAL": "致命错误",
    "DETECTED": "已发现",
    "RECOVERED": "已恢复",
    "SUPPRESSED": "已抑制",
    "CRITICAL": "严重",
    "HIGH": "高",
    "MEDIUM": "中",
    "LOW": "低",
    "FULL": "完全支持",
    "PARTIAL": "部分支持",
    "UNSUPPORTED": "不支持",
    "VERIFIED_DRIVER": "已验证驱动",
    "LIKELY_DRIVER": "较可能驱动",
    "UNRESOLVED": "无法判断",
    "DATA_ISSUE": "数据问题",
    "PRESENT": "已识别",
    "MISSING": "缺失",
    "EXCELLENT": "优秀",
    "GOOD": "良好",
    "ATTENTION": "需关注",
    "UNUSABLE": "不可用",
}

CATEGORY_LABELS = {
    "Beauty": "美妆",
    "Electronics": "电子产品",
    "Fashion": "服饰",
    "Grocery": "食品杂货",
    "Home": "家居",
    "Sports": "运动户外",
    "Toys": "玩具",
}

REGION_LABELS = {
    "East": "东部",
    "West": "西部",
    "South": "南部",
    "North": "北部",
    "Central": "中部",
}

CURRENCY_LABELS = {
    "CNY": "CNY（人民币）",
    "USD": "USD（美元）",
    "EUR": "EUR（欧元）",
    "GBP": "GBP（英镑）",
    "JPY": "JPY（日元）",
    "HKD": "HKD（港币）",
    "AUD": "AUD（澳元）",
    "CAD": "CAD（加拿大元）",
    "CHF": "CHF（瑞士法郎）",
    "INR": "INR（印度卢比）",
    "BRL": "BRL（巴西雷亚尔）",
}

CONFIDENCE_LABELS = {"HIGH": "高", "MEDIUM": "中", "LOW": "低"}
ANALYSIS_TYPE_LABELS = {
    "category": "品类分析",
    "region": "区域分析",
    "products": "商品分析",
    "summary": "汇总",
}
UNIT_LABELS = {"orders": "笔订单", "customers": "位客户", "products": "个商品", "regions": "个区域", "rows": "个组合", "ratio": "比例"}

FORMULA_LABELS = {
    "sum(total_amount)": "GMV（成交总额）= 订单金额合计",
    "nunique(order_id)": "订单数 = 订单编号去重计数",
    "GMV / 订单数": "AOV（平均客单价）= GMV（成交总额）/ 订单数",
    "sum(profit_amount)": "利润额 = 单笔利润额合计",
    "利润额 / GMV": "利润率 = 利润额 / GMV（成交总额）",
    "退货订单数 / 订单数": "退货率 = 退货订单数 / 订单数",
    "完整月GMV / 上一完整月GMV - 1": "GMV（成交总额）环比 = 本完整月GMV / 上一完整月GMV - 1",
    "销量>=合格商品P75；利润率>=组合加权利润率": "高销量：销量不低于合格商品P75（75分位数）；高利润：利润率不低于组合加权利润率",
    "R/F/M百分位评分1-5": "RFM（客户价值模型）：最近购买、购买频次、消费金额按百分位评分1-5",
    "区域GMV、利润、客单价、退货与配送聚合": "按区域汇总GMV（成交总额）、利润、AOV（平均客单价）、退货与配送指标",
    "市场GMV、利润、客单价、退货与配送聚合": "按统一市场粒度汇总GMV（成交总额）、利润、AOV（平均客单价）、退货与配送指标",
    "sum(total_amount where returned=True)": "退货关联GMV（成交总额）= 退货订单金额合计",
}


VALUE_MAPS = {
    "analysis_type": ANALYSIS_TYPE_LABELS,
    "category": CATEGORY_LABELS,
    "confidence": CONFIDENCE_LABELS,
    "currency": CURRENCY_LABELS,
    "formula": FORMULA_LABELS,
    "metric": {
        "GMV": "GMV（成交总额）",
        "gmv": "GMV（成交总额）",
        "orders": "订单数",
        "customers": "客户数",
        "units": "销量",
        "aov": "AOV（平均客单价）",
        "profit": "利润额",
        "profit_amount": "利润额",
        "profit_rate": "利润率",
        "return_rate": "退货率",
        "平均客单价": "AOV（平均客单价）",
        "RFM客户分群": "RFM（客户价值模型）分群",
        "退货关联GMV": "退货关联GMV（成交总额）",
        "returned_gmv_exposure": "退货关联GMV（成交总额）",
    },
    "name": MODULE_LABELS,
    "region": REGION_LABELS,
    "source_currency": CURRENCY_LABELS,
    "status": STATUS_LABELS,
    "severity": STATUS_LABELS,
    "target_currency": CURRENCY_LABELS,
    "unit": {**UNIT_LABELS, **CURRENCY_LABELS},
}


def label_for(value: Any) -> str:
    """Return a localized field or well-known display label with safe fallback."""
    if value is None:
        return ""
    text = str(value)
    return FIELD_LABELS.get(text, MODULE_LABELS.get(text, STATUS_LABELS.get(text, text)))


def currency_label(value: Any) -> str:
    return CURRENCY_LABELS.get(str(value), str(value)) if value is not None else ""


def value_for(value: Any, field: Optional[str] = None) -> Any:
    """Translate one display value without changing unknown or missing values."""
    if value is None or (not isinstance(value, (dict, list, tuple, set)) and pd.isna(value)):
        return value
    if isinstance(value, bool):
        return "是" if value else "否"
    mapping = VALUE_MAPS.get(field or "", {})
    return mapping.get(str(value), value)


def raw_value(value: Any, field: Optional[str] = None) -> Any:
    """Map a localized option back to its stable internal value."""
    mapping = VALUE_MAPS.get(field or "", {})
    reverse = {localized: raw for raw, localized in mapping.items()}
    return reverse.get(value, value)


def localize_formula(value: Any) -> Any:
    return value_for(value, "formula")


def localize_source_fields(value: Any) -> Any:
    if isinstance(value, (list, tuple, set)):
        return "、".join(label_for(item) for item in value)
    if not isinstance(value, str):
        return value
    return "、".join(label_for(item.strip()) for item in value.split(",") if item.strip())


def localize_frame(frame: pd.DataFrame, value_maps: Optional[Mapping[str, Mapping[str, str]]] = None) -> pd.DataFrame:
    """Return a localized display copy; the analysis DataFrame is never mutated."""
    localized = frame.copy(deep=True)
    extra_maps = value_maps or {}
    for column in localized.columns:
        if column in {"source_fields", "missing_fields"}:
            localized[column] = localized[column].map(localize_source_fields)
            continue
        if column in {"canonical_field", "field"}:
            localized[column] = localized[column].map(label_for)
            continue
        mapping = extra_maps.get(column) or VALUE_MAPS.get(column)
        if mapping:
            localized[column] = localized[column].map(lambda item: mapping.get(str(item), item) if not pd.isna(item) else item)
        elif column == "metric":
            localized[column] = localized[column].map(label_for)
    return localized.rename(columns={column: label_for(column) for column in localized.columns})


def field_guide_frame() -> pd.DataFrame:
    rows = []
    for field, (definition, formula) in FIELD_DEFINITIONS.items():
        rows.append({
            "中文名称": label_for(field),
            "规范字段": field,
            "业务定义": definition,
            "计算公式": formula,
        })
    return pd.DataFrame(rows)
