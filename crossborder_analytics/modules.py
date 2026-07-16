"""Evidence-backed ecommerce analysis modules."""
from dataclasses import replace
from typing import Dict, List, Optional, Tuple
import math

import numpy as np
import pandas as pd

from autoclean.analytics import AnalysisStatus, Evidence, ModuleResult
from crossborder_analytics.rfm import apply_rfm_rules, summarize_segments


def safe_divide(numerator, denominator, default=np.nan):
    return numerator / denominator if denominator not in (0, None) and not pd.isna(denominator) else default


def amount_column(frame: pd.DataFrame, field: str = "total_amount") -> str:
    base = field + "_base"
    return base if base in frame.columns else field


def period_label(value) -> str:
    return str(value) if value is not None else ""


def complete_months(frame: pd.DataFrame) -> Tuple[List[pd.Period], List[pd.Period]]:
    dates = frame["order_date"].dropna().sort_values()
    if dates.empty:
        return [], []
    periods = sorted(dates.dt.to_period("M").unique())
    incomplete = set()
    first, last = periods[0], periods[-1]
    if dates.min().day != 1:
        incomplete.add(first)
    last_day = dates.max().days_in_month
    if dates.max().day != last_day:
        incomplete.add(last)
    return [period for period in periods if period not in incomplete], sorted(incomplete)


def confidence(sample_size: int, coverage: float = 1.0) -> str:
    if coverage < 1:
        return "LOW"
    if sample_size >= 30:
        return "HIGH"
    if sample_size >= 10:
        return "MEDIUM"
    return "LOW"


class OverviewModule:
    name = "overview"
    required_fields = ("order_id", "order_date", "total_amount")

    def run(self, context) -> ModuleResult:
        frame = context.analysis_data
        amount = amount_column(frame)
        orders = int(frame["order_id"].nunique())
        gmv = float(frame[amount].sum())
        customers = int(frame["customer_id"].nunique()) if "customer_id" in frame else None
        units = int(frame["quantity"].sum()) if "quantity" in frame else None
        profit_col = amount_column(frame, "profit_amount") if "profit_amount" in frame else None
        profit = float(frame[profit_col].sum()) if profit_col and profit_col in frame else None
        returned_orders = int(frame.loc[frame["returned"].eq(True), "order_id"].nunique()) if "returned" in frame else None
        metrics = {
            "gmv": gmv,
            "orders": orders,
            "customers": customers,
            "units": units,
            "aov": safe_divide(gmv, orders),
            "profit_amount": profit,
            "profit_rate": safe_divide(profit, gmv) if profit is not None else None,
            "returned_orders": returned_orders,
            "return_rate": safe_divide(returned_orders, orders) if returned_orders is not None else None,
        }
        currency = context.metadata.get("target_currency") or context.metadata.get("source_currency") or "UNSPECIFIED"
        evidence = [
            Evidence("overview.gmv", "GMV", gmv, currency, "所选范围内的成交总额", formula="sum(total_amount)", source_fields=("total_amount",), sample_size=orders),
            Evidence("overview.orders", "订单数", orders, "orders", "唯一订单数量", formula="nunique(order_id)", source_fields=("order_id",), sample_size=orders),
            Evidence("overview.aov", "平均客单价", metrics["aov"], currency, "每笔订单的平均成交金额", formula="GMV / 订单数", source_fields=("total_amount", "order_id"), sample_size=orders),
        ]
        if profit is not None:
            evidence.extend([
                Evidence("overview.profit", "利润额", profit, currency, "利润字段合计", formula="sum(profit_amount)", source_fields=("profit_amount",), sample_size=orders),
                Evidence("overview.profit_rate", "利润率", metrics["profit_rate"], "ratio", "利润占GMV比例", formula="利润额 / GMV", source_fields=("profit_amount", "total_amount"), sample_size=orders),
            ])
        if returned_orders is not None:
            evidence.append(Evidence(
                "overview.return_rate", "退货率", metrics["return_rate"], "ratio", "退货订单占全部订单比例",
                formula="退货订单数 / 订单数", source_fields=("returned", "order_id"), sample_size=orders,
            ))
        return ModuleResult(self.name, AnalysisStatus.SUCCESS, metrics, evidence)


class SalesModule:
    name = "sales"
    required_fields = ("order_id", "order_date", "total_amount")

    def run(self, context) -> ModuleResult:
        frame = context.analysis_data.copy()
        amount = amount_column(frame)
        frame["month"] = frame["order_date"].dt.to_period("M")
        aggregation = {"gmv": (amount, "sum"), "orders": ("order_id", "nunique")}
        profit_col = amount_column(frame, "profit_amount") if "profit_amount" in frame else None
        if profit_col and profit_col in frame:
            aggregation["profit"] = (profit_col, "sum")
        monthly = frame.groupby("month").agg(**aggregation).reset_index()
        monthly["month"] = monthly["month"].astype(str)
        monthly["aov"] = monthly["gmv"] / monthly["orders"]
        if "profit" in monthly:
            monthly["profit_rate"] = monthly["profit"] / monthly["gmv"]

        complete, incomplete = complete_months(frame)
        latest = complete[-1] if complete else None
        previous = complete[-2] if len(complete) >= 2 else None
        current_gmv = float(frame.loc[frame.month.eq(latest), amount].sum()) if latest else None
        previous_gmv = float(frame.loc[frame.month.eq(previous), amount].sum()) if previous else None
        mom = safe_divide(current_gmv - previous_gmv, previous_gmv) if previous_gmv is not None else None

        contributions = {}
        if latest and previous:
            for dimension in ("category", "region"):
                if dimension not in frame:
                    continue
                current = frame[frame.month.eq(latest)].groupby(dimension)[amount].sum()
                prior = frame[frame.month.eq(previous)].groupby(dimension)[amount].sum()
                table = pd.concat([current.rename("current"), prior.rename("previous")], axis=1).fillna(0)
                table["change"] = table.current - table.previous
                table["change_rate"] = np.where(table.previous.ne(0), table.change / table.previous, np.nan)
                contributions[dimension] = table.reset_index().sort_values("change")

        evidence = []
        if latest:
            evidence.append(Evidence(
                "sales.latest_complete_gmv", "最近完整月GMV", current_gmv,
                context.metadata.get("target_currency", ""), "最近完整月经营规模",
                baseline_value=previous_gmv, absolute_change=(current_gmv - previous_gmv) if previous_gmv is not None else None,
                relative_change=mom, period=str(latest), comparison_period=str(previous or ""),
                formula="完整月GMV / 上一完整月GMV - 1", source_fields=("order_date", "total_amount"),
                sample_size=int(frame.month.eq(latest).sum()),
            ))
        data = {
            "monthly": monthly,
            "latest_complete_month": str(latest or ""),
            "previous_complete_month": str(previous or ""),
            "incomplete_months": [str(item) for item in incomplete],
            "mom": mom,
            "category_contribution": contributions.get("category", pd.DataFrame()),
            "region_contribution": contributions.get("region", pd.DataFrame()),
            "seasonality_available": len(complete) >= 24,
        }
        message = "" if len(complete) >= 24 else "完整月份少于24个，正式季节性分析已跳过"
        return ModuleResult(self.name, AnalysisStatus.SUCCESS, data, evidence, message=message)


class ProductModule:
    name = "product"
    required_fields = ("order_id", "product_id", "quantity", "total_amount")

    def run(self, context) -> ModuleResult:
        frame = context.analysis_data
        amount = amount_column(frame)
        aggregations = {
            "orders": ("order_id", "nunique"),
            "units": ("quantity", "sum"),
            "gmv": (amount, "sum"),
        }
        profit_col = amount_column(frame, "profit_amount") if "profit_amount" in frame else None
        if profit_col and profit_col in frame:
            aggregations["profit"] = (profit_col, "sum")
        product = frame.groupby("product_id").agg(**aggregations).reset_index()
        if "profit" in product:
            product["profit_rate"] = product["profit"] / product["gmv"]
        else:
            product["profit"] = np.nan
            product["profit_rate"] = np.nan

        eligible = product.orders.ge(3) & product.profit_rate.notna()
        volume_threshold = float(product.loc[eligible, "units"].quantile(0.75)) if eligible.any() else np.nan
        portfolio_margin = safe_divide(product.profit.sum(), product.gmv.sum()) if product.profit.notna().any() else np.nan
        product["classification"] = "样本不足"
        high_volume = product.units.ge(volume_threshold) & eligible
        high_margin = product.profit_rate.ge(portfolio_margin) & eligible
        product.loc[high_volume & high_margin, "classification"] = "核心商品"
        product.loc[high_volume & ~high_margin & eligible, "classification"] = "引流商品"
        product.loc[~high_volume & high_margin & eligible, "classification"] = "潜力商品"
        product.loc[~high_volume & ~high_margin & eligible, "classification"] = "淘汰观察"
        action_map = {
            "核心商品": "评估增加投入",
            "引流商品": "检查成本与定价",
            "潜力商品": "小规模测试推广",
            "淘汰观察": "评估减少补货",
            "样本不足": "继续积累样本",
        }
        product["recommended_action"] = product.classification.map(action_map)
        evidence = [Evidence(
            "product.matrix", "商品矩阵", int(eligible.sum()), "products",
            "满足三笔订单门槛的商品进入四象限",
            formula="销量>=合格商品P75；利润率>=组合加权利润率",
            source_fields=("product_id", "quantity", "total_amount", "profit_amount"),
            sample_size=int(eligible.sum()), confidence=confidence(int(eligible.sum())),
        )]
        return ModuleResult(self.name, AnalysisStatus.SUCCESS, {
            "products": product.sort_values("gmv", ascending=False),
            "volume_threshold": volume_threshold,
            "portfolio_margin": portfolio_margin,
            "eligible_products": int(eligible.sum()),
        }, evidence)


class CustomerModule:
    name = "customer"
    required_fields = ("order_id", "customer_id", "order_date", "total_amount")

    def run(self, context) -> ModuleResult:
        frame = context.analysis_data
        amount = amount_column(frame)
        anchor = frame.order_date.max().normalize() + pd.Timedelta(days=1)
        customer = frame.groupby("customer_id").agg(
            last_order=("order_date", "max"),
            frequency=("order_id", "nunique"),
            monetary=(amount, "sum"),
        ).reset_index()
        customer["recency_days"] = (anchor - customer.last_order).dt.days

        def score(series, reverse=False):
            result = np.ceil(series.rank(method="average", pct=True) * 5).clip(1, 5).astype(int)
            return 6 - result if reverse else result

        customer["r_score"] = score(customer.recency_days, reverse=True)
        customer["f_score"] = score(customer.frequency)
        customer["m_score"] = score(customer.monetary)
        customer = apply_rfm_rules(customer)
        segment_summary = summarize_segments(customer)
        evidence = [Evidence(
            "customer.rfm", "RFM客户分群", len(customer), "customers", "按购买新鲜度、频率和金额划分客户",
            period=anchor.date().isoformat(), formula="R/F/M百分位评分1-5",
            source_fields=("customer_id", "order_date", "order_id", "total_amount"), sample_size=len(customer),
        )]
        return ModuleResult(self.name, AnalysisStatus.SUCCESS, {
            "customers": customer.sort_values(["segment", "monetary"], ascending=[True, False]),
            "segments": segment_summary,
            "anchor_date": anchor.date().isoformat(),
        }, evidence)


class RegionModule:
    name = "region"
    required_fields = ("order_id", "region", "total_amount")

    def run(self, context) -> ModuleResult:
        frame = context.analysis_data
        amount = amount_column(frame)
        aggregation = {"gmv": (amount, "sum"), "orders": ("order_id", "nunique")}
        if "customer_id" in frame:
            aggregation["customers"] = ("customer_id", "nunique")
        profit_col = amount_column(frame, "profit_amount") if "profit_amount" in frame else None
        if profit_col and profit_col in frame:
            aggregation["profit"] = (profit_col, "sum")
        if "delivery_time_days" in frame:
            aggregation.update({
                "delivery_mean": ("delivery_time_days", "mean"),
                "delivery_median": ("delivery_time_days", "median"),
                "delivery_p90": ("delivery_time_days", lambda series: series.quantile(0.9)),
            })
        region = frame.groupby("region").agg(**aggregation).reset_index()
        region["aov"] = region.gmv / region.orders
        region["profit_rate"] = region.profit / region.gmv if "profit" in region else np.nan
        if "returned" in frame:
            returns = frame.groupby("region")["returned"].mean().rename("return_rate").reset_index()
            region = region.merge(returns, on="region", how="left")
        evidence = [Evidence(
            "region.ranking", "区域市场排名", len(region), "regions", "按GMV比较区域市场",
            formula="区域GMV、利润、客单价、退货与配送聚合", source_fields=("region", "total_amount"), sample_size=len(frame),
        )]
        return ModuleResult(self.name, AnalysisStatus.SUCCESS, region.sort_values("gmv", ascending=False), evidence)


class ReturnModule:
    name = "returns"
    required_fields = ("order_id", "returned", "total_amount")

    def run(self, context) -> ModuleResult:
        frame = context.analysis_data.copy()
        amount = amount_column(frame)
        returned = frame.returned.eq(True)
        orders = int(frame.order_id.nunique())
        returned_orders = int(frame.loc[returned, "order_id"].nunique())
        exposure = float(frame.loc[returned, amount].sum())
        summary = {
            "orders": orders,
            "returned_orders": returned_orders,
            "return_rate": safe_divide(returned_orders, orders),
            "returned_gmv_exposure": exposure,
        }
        breakdowns = {}
        for dimension in ("category", "region"):
            if dimension not in frame:
                continue
            table = frame.groupby(dimension).agg(
                orders=("order_id", "nunique"),
                returned_orders=("returned", "sum"),
                gmv=(amount, "sum"),
            ).reset_index()
            exposure_table = frame[returned].groupby(dimension)[amount].sum().rename("returned_gmv_exposure").reset_index()
            table = table.merge(exposure_table, on=dimension, how="left").fillna({"returned_gmv_exposure": 0})
            table["return_rate"] = table.returned_orders / table.orders
            breakdowns[dimension] = table.sort_values("return_rate", ascending=False)
        product_ranking = pd.DataFrame()
        if "product_id" in frame:
            product = frame.groupby("product_id").agg(
                orders=("order_id", "nunique"), returned_orders=("returned", "sum"), gmv=(amount, "sum")
            ).reset_index()
            product = product[product.orders.ge(30)].copy()
            if not product.empty:
                product["return_rate"] = product.returned_orders / product.orders
                product_ranking = product.sort_values("return_rate", ascending=False)

        monthly = pd.DataFrame()
        if "order_date" in frame:
            frame["month"] = frame.order_date.dt.to_period("M").astype(str)
            monthly = frame.groupby("month").agg(
                orders=("order_id", "nunique"), returned_orders=("returned", "sum")
            ).reset_index()
            monthly["return_rate"] = monthly.returned_orders / monthly.orders

        message = "" if not product_ranking.empty else "没有商品达到30笔订单门槛，高退货商品排名已跳过"
        evidence = [Evidence(
            "returns.rate", "退货率", summary["return_rate"], "ratio", "退货订单占全部订单比例",
            formula="退货订单数 / 订单数", source_fields=("returned", "order_id"), sample_size=orders,
        ), Evidence(
            "returns.gmv_exposure", "退货关联GMV", exposure, context.metadata.get("target_currency", ""),
            "退货订单对应的成交金额，不代表实际退款损失", formula="sum(total_amount where returned=True)",
            source_fields=("returned", "total_amount"), sample_size=returned_orders,
        )]
        return ModuleResult(self.name, AnalysisStatus.SUCCESS, {
            "summary": summary,
            "category": breakdowns.get("category", pd.DataFrame()),
            "region": breakdowns.get("region", pd.DataFrame()),
            "products": product_ranking,
            "monthly": monthly,
        }, evidence, message=message)


ALL_MODULES = [OverviewModule(), SalesModule(), ProductModule(), CustomerModule(), RegionModule(), ReturnModule()]
