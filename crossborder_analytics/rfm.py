"""RFM customer segmentation helpers."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


SEGMENT_ORDER = ["VIP客户", "高价值客户", "流失风险客户", "普通客户"]


@dataclass(frozen=True)
class RfmRules:
    vip_r_min: int = 4
    vip_f_min: int = 4
    vip_m_min: int = 4
    churn_r_max: int = 2
    churn_value_min: int = 3
    high_m_min: int = 4
    high_activity_min: int = 3


def apply_rfm_rules(customers: pd.DataFrame, rules: RfmRules = RfmRules()) -> pd.DataFrame:
    """Return a copy of customer rows with segment recalculated from RFM scores."""
    result = customers.copy(deep=True)
    result["segment"] = "普通客户"

    vip = (
        result["r_score"].ge(rules.vip_r_min)
        & result["f_score"].ge(rules.vip_f_min)
        & result["m_score"].ge(rules.vip_m_min)
    )
    churn = (
        result["r_score"].le(rules.churn_r_max)
        & (result["f_score"].ge(rules.churn_value_min) | result["m_score"].ge(rules.churn_value_min))
        & ~vip
    )
    high = (
        result["m_score"].ge(rules.high_m_min)
        & (result["r_score"].ge(rules.high_activity_min) | result["f_score"].ge(rules.high_activity_min))
        & ~vip
        & ~churn
    )

    result.loc[high, "segment"] = "高价值客户"
    result.loc[churn, "segment"] = "流失风险客户"
    result.loc[vip, "segment"] = "VIP客户"
    return result


def summarize_segments(customers: pd.DataFrame) -> pd.DataFrame:
    """Aggregate segment size and value metrics for dashboard charts."""
    summary = customers.groupby("segment", observed=False).agg(
        customers=("customer_id", "nunique"),
        gmv=("monetary", "sum"),
        avg_recency=("recency_days", "mean"),
        avg_frequency=("frequency", "mean"),
    ).reset_index()
    order = {name: index for index, name in enumerate(SEGMENT_ORDER)}
    summary["_order"] = summary["segment"].map(order).fillna(len(order))
    return summary.sort_values("_order").drop(columns="_order").reset_index(drop=True)
