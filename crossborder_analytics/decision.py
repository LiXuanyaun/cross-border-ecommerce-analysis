"""Pure decision-view transforms for markets, customers, and products."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def amount_column(frame: pd.DataFrame, field: str = "total_amount") -> str:
    base = field + "_base"
    return base if base in frame.columns else field


def resolve_market_field(frame: pd.DataFrame) -> Optional[str]:
    """Choose the best-covered geographic grain, preferring country on ties."""
    coverage = {}
    for field in ("country", "region"):
        if field in frame:
            values = frame[field].astype("string").str.strip().replace("", pd.NA)
            coverage[field] = int(values.notna().sum())
    available = {field: count for field, count in coverage.items() if count > 0}
    if not available:
        return None
    return max(available, key=lambda field: (available[field], field == "country"))


def market_series(frame: pd.DataFrame, field: Optional[str] = None) -> pd.Series:
    field = field or resolve_market_field(frame)
    if field is None or field not in frame:
        return pd.Series(pd.NA, index=frame.index, dtype="string", name="market")
    missing_label = "未标注国家" if field == "country" else "未标注区域"
    return frame[field].astype("string").str.strip().replace("", pd.NA).fillna(missing_label).rename("market")


def build_market_category_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    if "category" not in frame or resolve_market_field(frame) is None:
        return pd.DataFrame()
    source = frame.copy(deep=True)
    source["market"] = market_series(source)
    source["category"] = source["category"].astype("string").str.strip().replace("", pd.NA).fillna("未标注品类")
    amount = amount_column(source)
    aggregations = {
        "orders": ("order_id", "nunique"),
        "gmv": (amount, "sum"),
    }
    if "quantity" in source:
        aggregations["units"] = ("quantity", "sum")
    if "customer_id" in source:
        aggregations["customers"] = ("customer_id", "nunique")
    profit = amount_column(source, "profit_amount") if "profit_amount" in source else None
    if profit:
        aggregations["profit"] = (profit, "sum")
    if "returned" in source:
        aggregations["returned_orders"] = ("returned", "sum")
    result = source.groupby(["market", "category"], dropna=False).agg(**aggregations).reset_index()
    result["units"] = result["units"] if "units" in result else np.nan
    result["customers"] = result["customers"] if "customers" in result else np.nan
    result["profit"] = result["profit"] if "profit" in result else np.nan
    result["returned_orders"] = result["returned_orders"] if "returned_orders" in result else np.nan
    result["profit_rate"] = np.where(result.gmv.ne(0), result.profit / result.gmv, np.nan)
    result["return_rate"] = np.where(result.orders.ne(0), result.returned_orders / result.orders, np.nan)
    result["order_share"] = result.orders / result.groupby("market")["orders"].transform("sum")
    result["gmv_share"] = result.gmv / result.groupby("market")["gmv"].transform("sum")
    result["market_source"] = resolve_market_field(frame)
    return result.sort_values(["market", "order_share"], ascending=[True, False]).reset_index(drop=True)


def build_customer_composition(frame: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    if "customer_id" not in frame or customers.empty:
        return pd.DataFrame()
    source = frame.copy(deep=True)
    source = source.merge(customers[["customer_id", "segment"]], on="customer_id", how="inner")
    amount = amount_column(source)
    dimensions = []
    if resolve_market_field(source) is not None:
        source["market"] = market_series(source)
        dimensions.append(("market", "market"))
    if "category" in source:
        source["category"] = source["category"].astype("string").str.strip().replace("", pd.NA).fillna("未标注品类")
        dimensions.append(("category", "category"))
    outputs = []
    for dimension_type, field in dimensions:
        grouped = source.groupby(["segment", field], dropna=False).agg(
            orders=("order_id", "nunique"),
            customers=("customer_id", "nunique"),
            gmv=(amount, "sum"),
        ).reset_index().rename(columns={field: "dimension_value"})
        grouped["dimension_type"] = dimension_type
        grouped["order_share"] = grouped.orders / grouped.groupby("segment")["orders"].transform("sum")
        grouped["gmv_share"] = grouped.gmv / grouped.groupby("segment")["gmv"].transform("sum")
        grouped["share"] = grouped["gmv_share"]
        grouped["evidence_id"] = "customer.rfm"
        outputs.append(grouped)
    if not outputs:
        return pd.DataFrame()
    return pd.concat(outputs, ignore_index=True).loc[:, [
        "segment", "dimension_type", "dimension_value", "orders", "customers",
        "gmv", "order_share", "gmv_share", "share", "evidence_id",
    ]]


def _health_rank(series: pd.Series, reverse: bool = False) -> pd.Series:
    rank = series.rank(method="average", pct=True)
    return (1 - rank + (1 / max(int(series.notna().sum()), 1))) if reverse else rank


def apply_market_strategy(markets: pd.DataFrame) -> pd.DataFrame:
    result = markets.copy(deep=True)
    if result.empty:
        return result
    total_gmv = result.gmv.sum()
    result["gmv_share"] = result.gmv / total_gmv if total_gmv else np.nan
    scale_benchmark = result.gmv_share.median()
    portfolio_profit = result.profit.sum() / total_gmv if "profit" in result and result.profit.notna().any() and total_gmv else np.nan
    total_orders = result.orders.sum()
    portfolio_return = (
        (result.return_rate * result.orders).sum() / total_orders
        if "return_rate" in result and result.return_rate.notna().any() and total_orders else np.nan
    )
    delivery_benchmark = result.delivery_p90.median() if "delivery_p90" in result and result.delivery_p90.notna().any() else np.nan
    result["scale_health"] = _health_rank(result.gmv)
    result["profit_health"] = _health_rank(result.profit_rate) if "profit_rate" in result else np.nan
    result["return_health"] = _health_rank(result.return_rate, reverse=True) if "return_rate" in result else np.nan
    result["delivery_health"] = _health_rank(result.delivery_p90, reverse=True) if "delivery_p90" in result else np.nan
    result["portfolio_profit_rate"] = portfolio_profit
    result["portfolio_return_rate"] = portfolio_return
    result["delivery_p90_benchmark"] = delivery_benchmark
    result["scale_benchmark"] = scale_benchmark

    strategies = []
    reasons = []
    confidences = []
    for row in result.itertuples(index=False):
        profit_rate = getattr(row, "profit_rate", np.nan)
        return_rate = getattr(row, "return_rate", np.nan)
        delivery_p90 = getattr(row, "delivery_p90", np.nan)
        risk_fields = int(pd.notna(return_rate)) + int(pd.notna(delivery_p90))
        confidence = "HIGH" if risk_fields == 2 else "MEDIUM" if risk_fields == 1 else "LOW"
        if pd.isna(profit_rate):
            strategy, reason, confidence = "证据不足", "缺少利润字段，暂不判断投入方向", "LOW"
        elif profit_rate < 0:
            strategy, reason = "谨慎评估", "利润率为负，先核查定价、成本和订单结构"
        elif (pd.notna(return_rate) and pd.notna(portfolio_return) and return_rate > portfolio_return) or (
            pd.notna(delivery_p90) and pd.notna(delivery_benchmark) and delivery_p90 > delivery_benchmark
        ):
            strategy, reason = "先优化效率", "退货或履约指标弱于当前组合基准"
        elif pd.notna(portfolio_profit) and profit_rate >= portfolio_profit and row.gmv_share >= scale_benchmark:
            strategy, reason = "优先评估投入", "规模和利润质量均达到当前组合基准"
        elif pd.notna(portfolio_profit) and profit_rate >= portfolio_profit:
            strategy, reason = "小规模增量测试", "利润质量达标但当前市场规模较小"
        else:
            strategy, reason = "改善利润后再扩量", "利润率低于当前组合利润率"
        if risk_fields < 2 and strategy not in {"证据不足", "谨慎评估"}:
            reason += "；风险字段覆盖不完整"
        strategies.append(strategy)
        reasons.append(reason)
        confidences.append(confidence)
    result["strategy"] = strategies
    result["strategy_reason"] = reasons
    result["strategy_confidence"] = confidences
    return result


def composition_preview(data: pd.DataFrame, segment: str, dimension_type: str, limit: int = 8) -> pd.DataFrame:
    source = data.loc[data.dimension_type.eq(dimension_type)].copy()
    if segment != "全部客户":
        source = source.loc[source.segment.eq(segment)].copy()
    else:
        source = source.groupby("dimension_value", as_index=False).agg(
            orders=("orders", "sum"), customers=("customers", "sum"), gmv=("gmv", "sum")
        )
        source["gmv_share"] = source.gmv / source.gmv.sum() if source.gmv.sum() else np.nan
        source["order_share"] = source.orders / source.orders.sum() if source.orders.sum() else np.nan
    source = source.sort_values("gmv", ascending=False).reset_index(drop=True)
    if len(source) <= limit:
        return source
    top = source.iloc[:limit].copy()
    other = source.iloc[limit:]
    row = {
        "dimension_value": "其他",
        "orders": other.orders.sum(),
        "customers": other.customers.sum(),
        "gmv": other.gmv.sum(),
        "order_share": other.order_share.sum(),
        "gmv_share": other.gmv_share.sum(),
    }
    return pd.concat([top, pd.DataFrame([row])], ignore_index=True)
