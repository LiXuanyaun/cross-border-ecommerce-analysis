"""Deterministic market growth, product opportunity, and action objects."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .decision import amount_column, market_series, resolve_market_field
from .phase2_models import (
    ActionItem, MarketGrowthStatus, MarketOpportunity, MetricSnapshot,
    ProductOpportunity, ProductOpportunityType,
)
from .phase2_utils import stable_id, utc_now


RULE_VERSION = "1.0.0"
MARKET_MIN_ORDERS = 30
PRODUCT_MIN_ORDERS = 10
PRODUCT_CANDIDATE_MIN_ORDERS = 3


def _rate(current: float, previous: float) -> Optional[float]:
    return (float(current) / float(previous) - 1.0) if previous else None


def _ratio(numerator: float, denominator: float) -> Optional[float]:
    return float(numerator) / float(denominator) if denominator else None


def _delta(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or pd.isna(current) or pd.isna(previous):
        return None
    return float(current) - float(previous)


def _windows(snapshots: Sequence[MetricSnapshot]) -> Optional[Tuple[Tuple[str, str, str], Tuple[str, str, str]]]:
    global_gmv = [
        item for item in snapshots
        if item.metric_id == "gmv" and item.entity_type == "global" and item.is_complete_period
    ]
    events = {item.period_type: item for item in global_gmv if item.period_type in {"event", "event_baseline"}}
    if {"event", "event_baseline"}.issubset(events):
        baseline, current = events["event_baseline"], events["event"]
        return (
            (baseline.period_start, baseline.period_end, "活动对照期"),
            (current.period_start, current.period_end, "活动期"),
        )
    for period_type in ("month", "week"):
        periods = sorted(
            (item for item in global_gmv if item.period_type == period_type),
            key=lambda item: (item.period_start, item.period_end),
        )
        if len(periods) >= 2:
            previous, current = periods[-2], periods[-1]
            return (
                (previous.period_start, previous.period_end, previous.period_start),
                (current.period_start, current.period_end, current.period_start),
            )
    return None


def _period_frame(frame: pd.DataFrame, window: Tuple[str, str, str]) -> pd.DataFrame:
    return frame.loc[pd.to_datetime(frame["order_date"]).between(pd.Timestamp(window[0]), pd.Timestamp(window[1]))].copy()


def _aggregate(source: pd.DataFrame, entity: str) -> pd.DataFrame:
    if source.empty:
        return pd.DataFrame()
    amount = amount_column(source)
    source = source.copy()
    source["__profit"] = source[amount_column(source, "profit_amount")] if "profit_amount" in source else np.nan
    source["__returned"] = source["returned"].fillna(False).astype(bool) if "returned" in source else np.nan
    aggregations: Dict[str, Tuple[str, str]] = {
        "orders": ("order_id", "nunique"),
        "gmv": (amount, "sum"),
        "profit": ("__profit", "sum"),
    }
    if "returned" in source:
        aggregations["returned_orders"] = ("__returned", "sum")
    if "customer_id" in source:
        aggregations["customers"] = ("customer_id", "nunique")
    result = source.groupby(entity, dropna=False).agg(**aggregations).reset_index()
    result["profit_margin"] = np.where(result.gmv.ne(0), result.profit / result.gmv, np.nan)
    result["return_rate"] = (
        np.where(result.orders.ne(0), result.returned_orders / result.orders, np.nan)
        if "returned_orders" in result else np.nan
    )
    result["aov"] = np.where(result.orders.ne(0), result.gmv / result.orders, np.nan)
    return result


def _paired(previous: pd.DataFrame, current: pd.DataFrame, key: str) -> pd.DataFrame:
    columns = ["orders", "gmv", "profit", "profit_margin", "return_rate", "aov"]
    left = previous.set_index(key).reindex(columns=columns).add_suffix("_previous") if not previous.empty else pd.DataFrame(columns=[key, *columns]).set_index(key).add_suffix("_previous")
    right = current.set_index(key).reindex(columns=columns).add_suffix("_current") if not current.empty else pd.DataFrame(columns=[key, *columns]).set_index(key).add_suffix("_current")
    result = left.join(right, how="outer").fillna({
        "orders_previous": 0, "gmv_previous": 0.0, "profit_previous": 0.0,
        "orders_current": 0, "gmv_current": 0.0, "profit_current": 0.0,
    }).reset_index()
    return result


def _top_changes(previous: pd.DataFrame, current: pd.DataFrame, key: str, limit: int = 3) -> Tuple[Mapping[str, Any], ...]:
    paired = _paired(previous, current, key)
    if paired.empty:
        return ()
    paired["gmv_change"] = paired.gmv_current - paired.gmv_previous
    return tuple(
        {"name": str(row[key]), "gmv_change": float(row.gmv_change), "current_gmv": float(row.gmv_current)}
        for _, row in paired.sort_values("gmv_change", ascending=False).head(limit).iterrows()
    )


def _order_aov_drivers(row: pd.Series) -> Tuple[str, Tuple[Mapping[str, Any], ...]]:
    previous_orders, current_orders = float(row.orders_previous), float(row.orders_current)
    previous_aov = float(row.aov_previous) if pd.notna(row.aov_previous) else 0.0
    current_aov = float(row.aov_current) if pd.notna(row.aov_current) else 0.0
    order_amount = (current_orders - previous_orders) * (current_aov + previous_aov) / 2
    aov_amount = (current_aov - previous_aov) * (current_orders + previous_orders) / 2
    driver = "订单量" if abs(order_amount) >= abs(aov_amount) else "客单价"
    return driver, (
        {"driver": "订单量", "contribution_amount": float(order_amount)},
        {"driver": "客单价", "contribution_amount": float(aov_amount)},
    )


def _quality_scores(snapshots: Sequence[MetricSnapshot], current_start: str) -> Dict[str, float]:
    return {
        item.entity_id: float(item.current_value)
        for item in snapshots
        if item.metric_id == "market_quality_score" and item.period_start == current_start
        and item.current_value is not None
    }


class OpportunityEngine:
    def run(self, context, artifacts, legacy_results):
        windows = _windows(artifacts.metric_snapshots)
        if windows is None:
            return [], [], [], {"product_candidate_min_orders": PRODUCT_CANDIDATE_MIN_ORDERS, "excluded_low_sample_products": 0}
        previous_window, current_window = windows
        frame = context.analysis_data.copy()
        previous = _period_frame(frame, previous_window)
        current = _period_frame(frame, current_window)
        evidence_ids = tuple(sorted({item.evidence_id for item in artifacts.metric_snapshots}))
        created_at = utc_now()
        markets = self._markets(
            frame, previous, current, previous_window, current_window,
            context.metadata.get("dataset_id") or artifacts.data_quality.dataset_id,
            artifacts.data_quality.scope_id, evidence_ids,
            _quality_scores(artifacts.metric_snapshots, current_window[0]), created_at,
        )
        products, excluded_low_sample_products = self._products(
            frame, previous, current, previous_window, current_window,
            context.metadata.get("dataset_id") or artifacts.data_quality.dataset_id,
            artifacts.data_quality.scope_id, evidence_ids, legacy_results, created_at,
        )
        actions = self._actions(markets, products, created_at)
        summary = {
            "product_candidate_min_orders": PRODUCT_CANDIDATE_MIN_ORDERS,
            "excluded_low_sample_products": excluded_low_sample_products,
            "listed_insufficient_sample_products": sum(
                str(item.opportunity_type) == "样本不足" for item in products
            ),
        }
        return markets, products, actions, summary

    def _markets(
        self, frame, previous, current, previous_window, current_window,
        dataset_id, scope_id, evidence_ids, quality_scores, created_at,
    ) -> List[MarketOpportunity]:
        if resolve_market_field(frame) is None:
            return []
        for source in (previous, current):
            source["market"] = market_series(source)
        paired = _paired(_aggregate(previous, "market"), _aggregate(current, "market"), "market")
        current_total = float(paired.gmv_current.sum())
        current_detail = current.copy()
        current_detail["sku"] = current_detail.get("product_id", pd.Series("未标注SKU", index=current_detail.index)).astype("string").fillna("未标注SKU")
        opportunities = []
        for _, row in paired.iterrows():
            market = str(row.market)
            current_market = current.loc[current.market.astype(str).eq(market)]
            previous_market = previous.loc[previous.market.astype(str).eq(market)]
            gmv_growth = _rate(row.gmv_current, row.gmv_previous)
            order_growth = _rate(row.orders_current, row.orders_previous)
            margin_change = _delta(row.profit_margin_current, row.profit_margin_previous)
            return_change = _delta(row.return_rate_current, row.return_rate_previous)
            market_skus = current_detail.loc[current_detail.market.astype(str).eq(market)].groupby("sku")[amount_column(current_detail)].sum()
            concentration = _ratio(float(market_skus.max()) if not market_skus.empty else 0.0, float(market_skus.sum()))
            missing_quality = not {"profit_amount", "returned"}.issubset(frame.columns)
            sample_low = int(row.orders_current) < MARKET_MIN_ORDERS or int(row.orders_previous) < MARKET_MIN_ORDERS
            risk = ((margin_change is not None and margin_change <= -0.05) or (return_change is not None and return_change >= 0.05))
            share = _ratio(row.gmv_current, current_total) or 0.0
            if sample_low:
                status = MarketGrowthStatus.INSUFFICIENT_SAMPLE
            elif missing_quality:
                status = MarketGrowthStatus.INSUFFICIENT_DATA
            elif gmv_growth is not None and gmv_growth >= 0.20:
                status = MarketGrowthStatus.RISKY_GROWTH if risk else MarketGrowthStatus.HEALTHY_GROWTH
            elif gmv_growth is not None and (gmv_growth <= -0.20 or row.profit_margin_current < 0):
                status = MarketGrowthStatus.CONTRACTING
            elif share < 0.05 and (gmv_growth is None or gmv_growth <= 0):
                status = MarketGrowthStatus.LOW_VALUE
            else:
                status = MarketGrowthStatus.STABLE
            driver, contributions = _order_aov_drivers(row)
            categories = _top_changes(
                _aggregate(previous_market.assign(category=previous_market.get("category", "未标注品类")), "category"),
                _aggregate(current_market.assign(category=current_market.get("category", "未标注品类")), "category"),
                "category",
            ) if "category" in frame else ()
            skus = _top_changes(
                _aggregate(previous_market.assign(sku=previous_market.get("product_id", "未标注SKU")), "sku"),
                _aggregate(current_market.assign(sku=current_market.get("product_id", "未标注SKU")), "sku"),
                "sku",
            ) if "product_id" in frame else ()
            action, stop = self._market_action(status)
            limitations = ["仅识别数据贡献关系，不判断广告、活动、库存或竞争变化等真实原因"]
            if missing_quality:
                limitations.append("缺少利润额或退货标记，无法判断增长质量")
            opportunity_id = stable_id("mktopp", dataset_id, scope_id, market, current_window[0], RULE_VERSION)
            opportunities.append(MarketOpportunity(
                opportunity_id, dataset_id, scope_id, market, status, current_window[2], previous_window[2],
                float(row.gmv_current), float(row.gmv_previous), float(row.gmv_current-row.gmv_previous), gmv_growth,
                int(row.orders_current), int(row.orders_previous), order_growth,
                float(row.aov_current) if pd.notna(row.aov_current) else None,
                float(row.aov_previous) if pd.notna(row.aov_previous) else None,
                float(row.profit_margin_current) if not missing_quality and pd.notna(row.profit_margin_current) else None, margin_change,
                float(row.return_rate_current) if pd.notna(row.return_rate_current) else None, return_change,
                concentration, quality_scores.get(market), driver, contributions, categories, skus,
                action, ("profit_margin", "return_rate"), "下一个完整可比较周期", stop,
                evidence_ids, tuple(limitations), created_at,
            ))
        return sorted(opportunities, key=lambda item: (item.gmv_change or 0.0, item.current_gmv), reverse=True)

    @staticmethod
    def _market_action(status: MarketGrowthStatus) -> Tuple[str, str]:
        mapping = {
            MarketGrowthStatus.HEALTHY_GROWTH: ("小范围增加投入，并按主要增长品类和SKU验证增量", "利润率下降5个百分点或退货率上升5个百分点时停止扩量"),
            MarketGrowthStatus.RISKY_GROWTH: ("暂停扩大投入，优先核对利润和退货恶化集中的商品", "利润率与退货率恢复保护阈值前不扩大投入"),
            MarketGrowthStatus.CONTRACTING: ("定位收缩贡献最大的品类和SKU，核对可控经营事件", "连续两个完整周期未改善时重新评估市场投入"),
            MarketGrowthStatus.LOW_VALUE: ("维持低成本观察，验证该市场是否具备可持续需求", "下一个完整周期仍低于5%规模占比且无增长时停止增量测试"),
            MarketGrowthStatus.STABLE: ("保持经营并观察订单量、客单价和质量保护指标", "任一保护指标触发风险阈值时转入修复"),
            MarketGrowthStatus.INSUFFICIENT_SAMPLE: ("继续收集样本，不执行确定性扩量动作", "两期订单均达到30单后重新判断"),
            MarketGrowthStatus.INSUFFICIENT_DATA: ("补充利润和退货字段后重新判断增长质量", "关键保护字段补齐前不执行确定性扩量动作"),
        }
        return mapping[status]

    def _products(
        self, frame, previous, current, previous_window, current_window,
        dataset_id, scope_id, evidence_ids, legacy_results, created_at,
    ) -> List[ProductOpportunity]:
        if "product_id" not in frame:
            return []
        for source in (previous, current):
            source["sku"] = source["product_id"].astype("string").fillna("未标注SKU")
            if resolve_market_field(frame):
                source["market"] = market_series(source)
        paired = _paired(_aggregate(previous, "sku"), _aggregate(current, "sku"), "sku")
        candidate_mask = (paired.orders_previous + paired.orders_current).ge(PRODUCT_CANDIDATE_MIN_ORDERS)
        excluded_low_sample_products = int((~candidate_mask).sum())
        paired = paired.loc[candidate_mask].copy()
        product_result = legacy_results.get("product")
        product_table = product_result.data.get("products", pd.DataFrame()) if product_result and product_result.data else pd.DataFrame()
        status_map = product_table.set_index(product_table.product_id.astype(str))["classification"].to_dict() if not product_table.empty else {}
        name_map = frame.groupby(frame.product_id.astype(str))["product_name"].first().to_dict() if "product_name" in frame else {}
        category_map = frame.groupby(frame.product_id.astype(str))["category"].agg(lambda values: values.mode().iloc[0] if not values.mode().empty else "未标注品类").to_dict() if "category" in frame else {}
        current_by_sku = {str(key): group for key, group in current.groupby("sku", sort=False)}
        previous_by_sku = {str(key): group for key, group in previous.groupby("sku", sort=False)}
        customer_result = legacy_results.get("customer")
        customer_table = customer_result.data.get("customers", pd.DataFrame()) if customer_result and customer_result.data else pd.DataFrame()
        high_value_customers = set()
        customer_segment_map: Dict[str, str] = {}
        if not customer_table.empty and {"customer_id", "segment"}.issubset(customer_table.columns):
            customer_segment_map = customer_table.set_index(customer_table.customer_id.astype(str))["segment"].astype(str).to_dict()
            high_value_customers = set(
                customer_table.loc[customer_table.segment.isin(["VIP客户", "高价值客户"]), "customer_id"].astype(str)
            )
        portfolio_high_value_share = None
        if high_value_customers and "customer_id" in current:
            current_amount = amount_column(current)
            portfolio_high_value_share = _ratio(
                current.loc[current.customer_id.astype(str).isin(high_value_customers), current_amount].sum(),
                current[current_amount].sum(),
            )
        multi_product_orders = set()
        if current.order_id.duplicated().any():
            multi_product_orders = set(
                current.groupby("order_id").sku.nunique().loc[lambda values: values.gt(1)].index.astype(str)
            )
        category_market_candidates: Dict[str, List[str]] = {}
        if "market" in current and "category" in current:
            for category in set(current.category.dropna().astype(str)):
                current_category = current.loc[current.category.astype(str).eq(category)]
                previous_category = previous.loc[previous.category.astype(str).eq(category)]
                candidates = _paired(_aggregate(previous_category, "market"), _aggregate(current_category, "market"), "market")
                if not candidates.empty:
                    candidates["growth"] = candidates.gmv_current - candidates.gmv_previous
                    category_market_candidates[category] = candidates.loc[candidates.growth.gt(0)].sort_values("growth", ascending=False).market.astype(str).tolist()
        total_market_growth = 0.0
        if resolve_market_field(frame):
            market_pair = _paired(_aggregate(previous, "market"), _aggregate(current, "market"), "market") if "market" in previous and "market" in current else pd.DataFrame()
            if not market_pair.empty:
                total_market_growth = float((market_pair.gmv_current-market_pair.gmv_previous).clip(lower=0).sum())
        opportunities = []
        for _, row in paired.iterrows():
            sku = str(row.sku)
            current_sku = current_by_sku.get(sku, current.iloc[0:0])
            previous_sku = previous_by_sku.get(sku, previous.iloc[0:0])
            gmv_growth = _rate(row.gmv_current, row.gmv_previous)
            margin_change = _delta(row.profit_margin_current, row.profit_margin_previous)
            return_change = _delta(row.return_rate_current, row.return_rate_previous)
            markets = current_sku.market.nunique() if "market" in current_sku else 0
            market_gmv = current_sku.groupby("market")[amount_column(current_sku)].sum().sort_values(ascending=False) if "market" in current_sku else pd.Series(dtype=float)
            primary_market = str(market_gmv.index[0]) if not market_gmv.empty else "无法判断"
            customer_gmv = current_sku.groupby("customer_id")[amount_column(current_sku)].sum() if "customer_id" in current_sku else pd.Series(dtype=float)
            customer_concentration = _ratio(float(customer_gmv.max()) if not customer_gmv.empty else 0.0, float(customer_gmv.sum()))
            present_markets = set(current_sku.market.astype(str)) if "market" in current_sku else set()
            target_market = next(
                (market for market in category_market_candidates.get(str(category_map.get(sku, "未标注品类")), []) if market not in present_markets),
                "",
            )
            high_value_share = None
            primary_customer_group = "无法判断"
            if high_value_customers and "customer_id" in current_sku:
                sku_amount = amount_column(current_sku)
                high_value_share = _ratio(
                    current_sku.loc[current_sku.customer_id.astype(str).isin(high_value_customers), sku_amount].sum(),
                    current_sku[sku_amount].sum(),
                )
                customer_mix = current_sku.assign(
                    __segment=current_sku.customer_id.astype(str).map(customer_segment_map).fillna("未分群")
                ).groupby("__segment")[sku_amount].sum().sort_values(ascending=False)
                if not customer_mix.empty:
                    primary_customer_group = str(customer_mix.index[0])
            bundle_share = _ratio(
                current_sku.order_id.astype(str).isin(multi_product_orders).sum(), len(current_sku)
            ) if multi_product_orders else None
            missing_quality = not {"profit_amount", "returned"}.issubset(frame.columns)
            sample_low = int(row.orders_current) < PRODUCT_MIN_ORDERS or int(row.orders_previous) < PRODUCT_MIN_ORDERS
            risk = ((margin_change is not None and margin_change <= -0.05) or (return_change is not None and return_change >= 0.05))
            if sample_low:
                opportunity_type = ProductOpportunityType.INSUFFICIENT_SAMPLE
            elif missing_quality:
                opportunity_type = ProductOpportunityType.INSUFFICIENT_DATA
            elif gmv_growth is not None and gmv_growth >= 0.30 and risk:
                opportunity_type = ProductOpportunityType.HIGH_RISK_GROWTH
            elif row.profit_margin_current < 0 or (margin_change is not None and margin_change <= -0.05):
                opportunity_type = ProductOpportunityType.PROFIT_REPAIR
            elif target_market and markets <= 2 and gmv_growth is not None and gmv_growth >= 0.10:
                opportunity_type = ProductOpportunityType.MARKET_EXPANSION
            elif gmv_growth is not None and gmv_growth >= 0.20 and row.profit_margin_current >= 0 and (pd.isna(row.return_rate_current) or row.return_rate_current < 0.20):
                opportunity_type = ProductOpportunityType.SCALE
            elif (
                high_value_share is not None and portfolio_high_value_share is not None
                and high_value_share + 0.10 < portfolio_high_value_share
                and gmv_growth is not None and gmv_growth >= 0
            ):
                opportunity_type = ProductOpportunityType.CUSTOMER_PENETRATION
            elif bundle_share is not None and bundle_share >= 0.30 and row.profit_margin_current >= 0:
                opportunity_type = ProductOpportunityType.BUNDLE
            else:
                opportunity_type = ProductOpportunityType.WATCH
            action, stop = self._product_action(opportunity_type, target_market)
            rationale = self._product_rationale(
                opportunity_type, gmv_growth,
                None if missing_quality else row.profit_margin_current,
                row.return_rate_current, target_market,
            )
            limitations = ["机会判断不预测未来销量，不把市场贡献关系表述为经营原因"]
            if "customer_id" not in frame:
                limitations.append("缺少客户ID，客户渗透与客户集中风险不可判断")
            limitations.append("订单级数据不能验证组合销售机会" if not frame.order_id.duplicated().any() else "组合销售需另行验证商品共购稳定性")
            opportunity_id = stable_id("prodopp", dataset_id, scope_id, sku, current_window[0], RULE_VERSION)
            opportunities.append(ProductOpportunity(
                opportunity_id, dataset_id, scope_id, sku, str(name_map.get(sku, sku)), str(category_map.get(sku, "未标注品类")),
                opportunity_type, str(status_map.get(sku, "样本不足")), current_window[2], previous_window[2],
                float(row.gmv_current), float(row.gmv_previous), float(row.gmv_current-row.gmv_previous), gmv_growth,
                int(row.orders_current), int(row.orders_previous),
                float(row.profit_margin_current) if not missing_quality and pd.notna(row.profit_margin_current) else None, margin_change,
                float(row.return_rate_current) if pd.notna(row.return_rate_current) else None, return_change,
                int(markets), _ratio(float(row.gmv_current-row.gmv_previous), total_market_growth), customer_concentration,
                high_value_share, primary_market, target_market or "无已验证目标市场",
                primary_customer_group, rationale, action,
                ("profit_margin", "return_rate"), "下一个完整可比较周期", stop,
                evidence_ids, tuple(limitations), created_at,
            ))
        return sorted(opportunities, key=lambda item: (item.gmv_change or 0.0, item.current_gmv), reverse=True), excluded_low_sample_products

    @staticmethod
    def _target_market(current: pd.DataFrame, previous: pd.DataFrame, sku: str, category: str) -> str:
        if "market" not in current or "category" not in current:
            return ""
        present = set(current.loc[current.sku.astype(str).eq(sku), "market"].astype(str))
        current_category = current.loc[current.category.astype(str).eq(str(category))]
        previous_category = previous.loc[previous.category.astype(str).eq(str(category))]
        candidates = _paired(_aggregate(previous_category, "market"), _aggregate(current_category, "market"), "market")
        if candidates.empty:
            return ""
        candidates["growth"] = candidates.gmv_current - candidates.gmv_previous
        candidates = candidates.loc[~candidates.market.astype(str).isin(present) & candidates.growth.gt(0)]
        return str(candidates.sort_values("growth", ascending=False).iloc[0].market) if not candidates.empty else ""

    @staticmethod
    def _product_action(kind: ProductOpportunityType, target_market: str) -> Tuple[str, str]:
        mapping = {
            ProductOpportunityType.SCALE: ("小范围增加商品投入并复盘增量质量", "利润率下降5个百分点或退货率升至20%时停止扩量"),
            ProductOpportunityType.MARKET_EXPANSION: ("在{}进行小样本市场测试".format(target_market or "候选市场"), "测试期利润率为负或退货率达到20%时停止测试"),
            ProductOpportunityType.PROFIT_REPAIR: ("核对售价、成本、折扣和履约成本，先修复利润再评估扩量", "利润率恢复前不增加投入"),
            ProductOpportunityType.HIGH_RISK_GROWTH: ("暂停扩大投入，优先检查利润和退货风险集中的市场", "保护指标恢复前不扩大投入"),
            ProductOpportunityType.WATCH: ("保持观察并验证增长是否能跨完整周期持续", "连续两个周期无改善时降低优先级"),
            ProductOpportunityType.INSUFFICIENT_SAMPLE: ("继续收集样本，不输出确定性投入建议", "两期订单均达到10单后重新判断"),
            ProductOpportunityType.INSUFFICIENT_DATA: ("补充利润和退货字段后重新判断商品机会", "关键保护字段补齐前不执行确定性投入动作"),
            ProductOpportunityType.CUSTOMER_PENETRATION: ("在已有高价值客户群中进行渗透测试", "客户复购与利润保护指标未改善时停止测试"),
            ProductOpportunityType.BUNDLE: ("验证稳定共购组合后进行小范围组合销售测试", "组合利润率或退货率触发保护阈值时停止"),
        }
        return mapping[kind]

    @staticmethod
    def _product_rationale(kind, growth, margin, return_rate, target_market) -> str:
        return "机会类型：{}；GMV变化率{}，利润率{}，退货率{}{}。".format(
            kind.value,
            "无法计算" if growth is None else "{:.1%}".format(growth),
            "无法计算" if pd.isna(margin) else "{:.1%}".format(margin),
            "无法计算" if pd.isna(return_rate) else "{:.1%}".format(return_rate),
            "；候选测试市场{}".format(target_market) if target_market else "",
        )

    @staticmethod
    def _actions(markets, products, created_at) -> List[ActionItem]:
        actions: List[ActionItem] = []
        for item in markets:
            priority = {
                "风险增长": "P0", "收缩待修复": "P1", "健康增长": "P1",
                "稳定经营": "P2", "低价值市场": "P2", "样本不足": "P2", "数据不足": "P1",
            }[item.status.value]
            confidence = "LOW" if item.status.value in {"样本不足", "数据不足"} else "HIGH"
            actions.append(ActionItem(
                stable_id("act", item.scope_id, item.opportunity_id), item.dataset_id, item.scope_id,
                "market", item.opportunity_id, item.market, item.market, item.status.value,
                item.gmv_change, priority, confidence, item.primary_driver,
                item.recommended_action, "市场运营负责人",
                item.guardrail_metrics, item.validation_period, item.stop_condition,
                item.evidence_ids, item.limitations, created_at,
            ))
        for item in products:
            priority = {
                "高风险增长": "P0", "利润修复机会": "P1", "扩量机会": "P1",
                "市场扩张机会": "P1", "客户渗透机会": "P2", "组合销售机会": "P2",
                "观察机会": "P2", "样本不足": "P2", "数据不足": "P1",
            }[item.opportunity_type.value]
            confidence = "LOW" if item.opportunity_type.value in {"样本不足", "数据不足"} else "HIGH"
            actions.append(ActionItem(
                stable_id("act", item.scope_id, item.opportunity_id), item.dataset_id, item.scope_id,
                "product", item.opportunity_id, item.product_id, item.product_name,
                item.opportunity_type.value, item.gmv_change, priority, confidence, item.rationale,
                item.recommended_action, "商品运营负责人", item.guardrail_metrics,
                item.validation_period, item.stop_condition, item.evidence_ids, item.limitations, created_at,
            ))
        priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        return sorted(actions, key=lambda item: (
            priority_rank.get(item.priority, 9), -abs(item.impact_amount or 0.0),
            0 if item.evidence_confidence == "HIGH" else 1, item.action_id,
        ))
