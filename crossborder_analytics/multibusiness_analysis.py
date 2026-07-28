"""Registered v4 metrics, rules and parameterized business-topic analysis."""
from __future__ import annotations

from contextlib import closing
from datetime import timedelta
from pathlib import Path
from typing import Any
import hashlib
import json
import sqlite3

import numpy as np
import pandas as pd


METRIC_CATALOG: dict[str, dict[str, str]] = {
    "ad.spend_usd": {"label": "广告花费", "format": "currency", "formula": "sum(fact_ad_performance_daily.spend_usd)"},
    "ad.impressions": {"label": "曝光", "format": "integer", "formula": "sum(impressions)"},
    "ad.clicks": {"label": "点击", "format": "integer", "formula": "sum(clicks)"},
    "ad.conversions": {"label": "转化", "format": "integer", "formula": "sum(conversions)"},
    "ad.ctr": {"label": "CTR", "format": "percent", "formula": "sum(clicks) / sum(impressions)"},
    "ad.cvr": {"label": "CVR", "format": "percent", "formula": "sum(conversions) / sum(clicks)"},
    "ad.cpc_usd": {"label": "CPC", "format": "currency", "formula": "sum(spend_usd) / sum(clicks)"},
    "ad.cpa_usd": {"label": "CPA", "format": "currency", "formula": "sum(spend_usd) / sum(conversions)"},
    "ad.roas": {"label": "ROAS", "format": "decimal", "formula": "sum(attributed_revenue_usd) / sum(spend_usd)"},
    "returns.return_rate": {"label": "退货率", "format": "percent", "formula": "returned order lines / purchased order lines"},
    "returns.refund_amount_usd": {"label": "退款金额", "format": "currency", "formula": "sum(refund_amount / original_line_sales_amount * order_line_gmv_usd)"},
    "returns.refund_rate": {"label": "退款金额率", "format": "percent", "formula": "refund_amount_usd / order_line_gmv_usd"},
    "returns.size_return_rate": {"label": "尺码退货率", "format": "percent", "formula": "size-related returned lines / purchased lines"},
    "logistics.transit_days": {"label": "平均运输时长", "format": "days", "formula": "avg(transit_days)"},
    "logistics.on_time_rate": {"label": "准时率", "format": "percent", "formula": "sum(on_time_flag) / shipment_count"},
    "logistics.delay_rate": {"label": "延误率", "format": "percent", "formula": "delayed shipments / shipment_count"},
    "logistics.delay_days": {"label": "平均延误天数", "format": "days", "formula": "avg(delay_days)"},
    "logistics.customs_delay_days": {"label": "平均清关滞留", "format": "days", "formula": "avg(customs_delay_days)"},
}


RULE_CATALOG: dict[str, dict[str, Any]] = {
    "AD_SPEND_UP_CVR_DOWN": {"version": "1.0.0", "threshold": "spend_change >= 50% AND cvr_change <= -20%"},
    "AD_LOW_ROAS": {"version": "1.0.0", "threshold": "ROAS < 2.0"},
    "AD_HIGH_CPA": {"version": "1.0.0", "threshold": "CPA > 75 USD"},
    "RETURN_SIZE_RATE_SPIKE": {"version": "1.0.0", "threshold": "size_return_rate >= 10% AND relative_change >= 50%"},
    "RETURN_HIGH_PRODUCT_RATE": {"version": "1.0.0", "threshold": "product_return_rate >= 12% AND purchased_lines >= 20"},
    "LOGISTICS_CUSTOMS_DELAY_SPIKE": {"version": "1.0.0", "threshold": "avg_delay_days >= 3 AND relative_change >= 50%"},
    "LOGISTICS_HIGH_DELAY_RATE": {"version": "1.0.0", "threshold": "delay_rate >= 20%"},
}


TOPICS = {"advertising", "returns", "logistics"}
SIMULATION_LIMITATION = "广告、退款和物流来自 synthetic_extension 模拟数据，仅用于功能验证，不能视为真实经营表现。"


def _ratio(numerator: float, denominator: float) -> float | None:
    return float(numerator / denominator) if denominator else None


def _change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return float((current - previous) / abs(previous))


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (np.integer, np.floating)):
        return value.item() if not pd.isna(value) else None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


class MultiBusinessAnalysisService:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def list_datasets(self) -> list[dict[str, Any]]:
        if not self.database_path.exists():
            return []
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT b.dataset_id, MIN(b.started_at) imported_at, "
                "SUM(CASE WHEN b.data_origin='synthetic_extension' THEN 1 ELSE 0 END) extension_batches "
                "FROM import_batches b GROUP BY b.dataset_id HAVING extension_batches > 0 ORDER BY imported_at DESC"
            ).fetchall()
        return [
            {
                "dataset_id": row["dataset_id"],
                "name": "AdventureWorks 多业务分析",
                "imported_at": row["imported_at"],
                "is_simulated": True,
                "source_label": "AdventureWorks 原始订单 + 模拟广告/退款/物流数据",
            }
            for row in rows
        ]

    def analyze(
        self,
        topic: str,
        dataset_id: str,
        start: str | None = None,
        end: str | None = None,
        country: str | None = None,
        channel: str | None = None,
        platform: str | None = None,
        campaign_id: str | None = None,
        category: str | None = None,
        return_reason: str | None = None,
        carrier_id: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any]:
        if topic not in TOPICS:
            raise ValueError("topic must be advertising, returns or logistics")
        bounds = self._date_bounds(topic, dataset_id)
        if not bounds:
            raise KeyError(dataset_id)
        selected_start = pd.Timestamp(start or bounds[0]).normalize()
        selected_end = pd.Timestamp(end or bounds[1]).normalize()
        if selected_start > selected_end:
            raise ValueError("start must be on or before end")
        filters = {
            "country": country, "channel": channel, "platform": platform,
            "campaign_id": campaign_id, "category": category, "return_reason": return_reason,
            "carrier_id": carrier_id, "region": region,
        }
        scope_payload = {
            "dataset_id": dataset_id, "topic": topic, "start": selected_start.date().isoformat(),
            "end": selected_end.date().isoformat(), **filters,
        }
        scope_id = "scope_{}".format(hashlib.sha256(json.dumps(scope_payload, sort_keys=True).encode()).hexdigest()[:16])
        if topic == "advertising":
            payload = self._advertising(dataset_id, selected_start, selected_end, filters, scope_id)
        elif topic == "returns":
            payload = self._returns(dataset_id, selected_start, selected_end, filters, scope_id)
        else:
            payload = self._logistics(dataset_id, selected_start, selected_end, filters, scope_id)
        return _json_value({
            "topic": topic,
            "dataset_id": dataset_id,
            "scope_id": scope_id,
            "period": {"start": selected_start.date().isoformat(), "end": selected_end.date().isoformat()},
            "filters": {key: value for key, value in filters.items() if value},
            "filter_options": self._filter_options(topic, dataset_id),
            "data_source": {
                "is_simulated": True,
                "label": "模拟数据",
                "description": "AdventureWorks 原始订单 + synthetic_extension 广告、退款、物流数据",
                "data_origin": "synthetic_extension",
            },
            "quality": {
                "status": "WARNING",
                "association_status": "VALIDATED",
                "limitations": [SIMULATION_LIMITATION, *payload.pop("limitations", [])],
            },
            **payload,
        })

    def report_payload(self, dataset_id: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        return {topic: self.analyze(topic, dataset_id, start, end) for topic in sorted(TOPICS)}

    def _connect(self):
        connection = sqlite3.connect(str(self.database_path))
        connection.row_factory = sqlite3.Row
        return connection

    def _date_bounds(self, topic: str, dataset_id: str) -> tuple[str, str] | None:
        mapping = {
            "advertising": ("fact_ad_performance_daily", "ad_date"),
            "returns": ("fact_returns", "return_request_date"),
            "logistics": ("fact_shipments", "ship_date"),
        }
        table, field = mapping[topic]
        if not self.database_path.exists():
            return None
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT MIN({0}), MAX({0}) FROM {1} WHERE dataset_id=?".format(field, table),
                    (dataset_id,),
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        return (str(row[0])[:10], str(row[1])[:10]) if row and row[0] and row[1] else None

    @staticmethod
    def _where(base_field: str, dataset_id: str, start: pd.Timestamp, end: pd.Timestamp, filters: list[tuple[str, Any]]):
        clauses = ["dataset_id = ?", "date({}) BETWEEN date(?) AND date(?)".format(base_field)]
        params: list[Any] = [dataset_id, start.date().isoformat(), end.date().isoformat()]
        for expression, value in filters:
            if value:
                clauses.append("{} = ?".format(expression))
                params.append(value)
        return " AND ".join(clauses), params

    def _read(self, sql: str, params: list[Any]) -> pd.DataFrame:
        with closing(self._connect()) as connection:
            return pd.read_sql_query(sql, connection, params=params)

    def _evidence(self, scope_id: str, metric_id: str, value: Any, period: tuple[pd.Timestamp, pd.Timestamp], source_table: str, sample_size: int, record_keys: list[str], comparison_period=None, threshold=None) -> dict[str, Any]:
        definition = METRIC_CATALOG[metric_id]
        evidence_id = "ev_{}".format(hashlib.sha256("|".join((scope_id, metric_id, str(period), str(value))).encode()).hexdigest()[:18])
        return {
            "evidence_id": evidence_id, "metric_id": metric_id, "metric": definition["label"],
            "value": value, "formula": definition["formula"], "source_table": source_table,
            "period": {"start": period[0].date().isoformat(), "end": period[1].date().isoformat()},
            "comparison_period": comparison_period,
            "threshold": threshold, "sample_size": int(sample_size), "record_keys": record_keys[:20],
            "limitations": [SIMULATION_LIMITATION],
        }

    def _metric(self, scope_id, metric_id, value, period, source_table, sample_size, record_keys, evidence):
        item = self._evidence(scope_id, metric_id, value, period, source_table, sample_size, record_keys)
        evidence.append(item)
        definition = METRIC_CATALOG[metric_id]
        return {
            "id": metric_id, "label": definition["label"], "value": value,
            "format": definition["format"], "formula": definition["formula"],
            "currency": "USD" if definition["format"] == "currency" else None,
            "evidence_id": item["evidence_id"],
        }

    def _advertising(self, dataset_id, start, end, filters, scope_id):
        where, params = self._where("ad_date", dataset_id, start, end, [
            ("target_country_code", filters["country"]), ("channel", filters["channel"]),
            ("platform", filters["platform"]), ("campaign_id", filters["campaign_id"]),
        ])
        frame = self._read(
            "SELECT ad_date, campaign_id, target_country_code country, channel, platform, impressions, clicks, "
            "conversions, spend_usd, attributed_revenue_usd, scenario_id FROM fact_ad_performance_daily WHERE " + where,
            params,
        )
        evidence: list[dict[str, Any]] = []
        spend = float(frame.spend_usd.sum())
        impressions, clicks, conversions = (int(frame[field].sum()) for field in ("impressions", "clicks", "conversions"))
        revenue = float(frame.attributed_revenue_usd.sum())
        values = {
            "ad.spend_usd": spend, "ad.impressions": impressions, "ad.clicks": clicks,
            "ad.conversions": conversions, "ad.ctr": _ratio(clicks, impressions),
            "ad.cvr": _ratio(conversions, clicks), "ad.cpc_usd": _ratio(spend, clicks),
            "ad.cpa_usd": _ratio(spend, conversions), "ad.roas": _ratio(revenue, spend),
        }
        keys = frame.campaign_id.astype(str).drop_duplicates().tolist()
        metrics = [self._metric(scope_id, key, value, (start, end), "fact_ad_performance_daily", len(frame), keys, evidence) for key, value in values.items()]
        monthly = self._ad_group(frame.assign(period=pd.to_datetime(frame.ad_date).dt.to_period("M").astype(str)), "period")
        ranking = self._ad_group(frame, "campaign_id").sort_values("spend_usd", ascending=False)
        anomalies = self._ad_anomalies(dataset_id, end, filters, scope_id, evidence)
        return {
            "metrics": metrics,
            "trend": {"title": "广告花费与转化效率趋势", "grain": "month", "rows": monthly.to_dict("records"), "series": ["spend_usd", "conversions", "cvr", "roas"]},
            "ranking": {"title": "活动投入与效率排名", "dimension": "campaign_id", "rows": ranking.head(20).to_dict("records")},
            "anomalies": anomalies,
            "causes": self._causes(anomalies), "actions": self._actions(anomalies), "evidence": evidence,
            "details": frame.sort_values("ad_date", ascending=False).head(200).to_dict("records"),
            "limitations": ["ROAS 只使用 USD 花费和 USD 归因收入；归因模型为数据文件记录的 last-click。"],
        }

    @staticmethod
    def _ad_group(frame: pd.DataFrame, dimension: str) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(columns=[dimension, "spend_usd", "impressions", "clicks", "conversions", "ctr", "cvr", "cpc_usd", "cpa_usd", "roas"])
        grouped = frame.groupby(dimension, dropna=False).agg(
            spend_usd=("spend_usd", "sum"), impressions=("impressions", "sum"), clicks=("clicks", "sum"),
            conversions=("conversions", "sum"), attributed_revenue_usd=("attributed_revenue_usd", "sum"),
        ).reset_index()
        grouped["ctr"] = grouped.clicks / grouped.impressions.replace(0, np.nan)
        grouped["cvr"] = grouped.conversions / grouped.clicks.replace(0, np.nan)
        grouped["cpc_usd"] = grouped.spend_usd / grouped.clicks.replace(0, np.nan)
        grouped["cpa_usd"] = grouped.spend_usd / grouped.conversions.replace(0, np.nan)
        grouped["roas"] = grouped.attributed_revenue_usd / grouped.spend_usd.replace(0, np.nan)
        return grouped

    def _ad_anomalies(self, dataset_id, end, filters, scope_id, evidence):
        current_start = end - timedelta(days=119)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=119)
        query_filters = [("target_country_code", filters["country"]), ("channel", filters["channel"]), ("platform", filters["platform"]), ("campaign_id", filters["campaign_id"])]
        frames = []
        for label, left, right in (("current", current_start, end), ("previous", previous_start, previous_end)):
            where, params = self._where("ad_date", dataset_id, left, right, query_filters)
            source = self._read("SELECT campaign_id, spend_usd, impressions, clicks, conversions, attributed_revenue_usd FROM fact_ad_performance_daily WHERE " + where, params)
            grouped = self._ad_group(source, "campaign_id").add_prefix(label + "_").rename(columns={label + "_campaign_id": "campaign_id"})
            frames.append(grouped)
        comparison = frames[0].merge(frames[1], on="campaign_id", how="left")
        anomalies = []
        comparison_period = {"start": previous_start.date().isoformat(), "end": previous_end.date().isoformat()}
        for row in comparison.itertuples():
            spend_change = _change(row.current_spend_usd, row.previous_spend_usd)
            cvr_change = _change(row.current_cvr, row.previous_cvr)
            rules = []
            if spend_change is not None and cvr_change is not None and spend_change >= 0.5 and cvr_change <= -0.2:
                rules.append(("AD_SPEND_UP_CVR_DOWN", "花费上升但转化效率下降", row.current_cvr, row.previous_cvr, cvr_change, "拆分搜索词与受众，暂停低效投放并用两周窗口复核 CVR。"))
            if pd.notna(row.current_roas) and row.current_roas < 2:
                rules.append(("AD_LOW_ROAS", "低 ROAS 活动", row.current_roas, row.previous_roas, _change(row.current_roas, row.previous_roas), "收紧出价与地域，优先保留归因收入覆盖花费的活动。"))
            if pd.notna(row.current_cpa_usd) and row.current_cpa_usd > 75:
                rules.append(("AD_HIGH_CPA", "高 CPA 活动", row.current_cpa_usd, row.previous_cpa_usd, _change(row.current_cpa_usd, row.previous_cpa_usd), "核查点击质量和落地页转化，设置 75 USD CPA 止损线。"))
            for rule_id, title, current, previous, change, recommendation in rules:
                ev = self._evidence(scope_id, "ad.cvr" if rule_id == "AD_SPEND_UP_CVR_DOWN" else ("ad.roas" if rule_id == "AD_LOW_ROAS" else "ad.cpa_usd"), current, (current_start, end), "fact_ad_performance_daily", 120, [str(row.campaign_id)], comparison_period, RULE_CATALOG[rule_id]["threshold"])
                evidence.append(ev)
                anomalies.append(self._anomaly(rule_id, title, str(row.campaign_id), current, previous, change, ev, recommendation))
        return anomalies

    def _returns(self, dataset_id, start, end, filters, scope_id):
        where, params = self._where("r.return_request_date", dataset_id, start, end, [
            ("o.country", filters["country"]), ("o.category", filters["category"]),
            ("rr.reason_category", filters["return_reason"]),
        ])
        returns = self._read(
            "SELECT r.return_id, r.sales_order_number, r.sales_order_line_number, r.return_request_date, "
            "r.return_quantity, r.refund_amount, r.original_line_sales_amount, r.product_key, "
            "rr.reason_category, o.product_id, o.product_name, o.category, o.country, o.quantity purchased_quantity, "
            "o.gmv_amount_base line_gmv_usd, CASE WHEN r.original_line_sales_amount > 0 THEN "
            "r.refund_amount / r.original_line_sales_amount * o.gmv_amount_base ELSE 0 END refund_amount_usd "
            "FROM fact_returns r JOIN dim_return_reason rr ON rr.dataset_id=r.dataset_id AND rr.return_reason_id=r.return_reason_id "
            "JOIN business_order_lines bol ON bol.dataset_id=r.dataset_id AND bol.sales_order_number=r.sales_order_number "
            "AND bol.sales_order_line_number=r.sales_order_line_number JOIN orders o ON o.dataset_id=bol.dataset_id AND o.record_id=bol.record_id "
            "WHERE r." + where,
            params,
        )
        order_where, order_params = self._where("order_date", dataset_id, start, end, [("country", filters["country"]), ("category", filters["category"])])
        orders = self._read("SELECT record_id, order_date, product_id, product_name, category, country, quantity, gmv_amount_base FROM orders WHERE " + order_where, order_params)
        evidence: list[dict[str, Any]] = []
        returned_lines = int(len(returns))
        purchased_lines = int(len(orders))
        refund = float(returns.refund_amount_usd.sum()) if not returns.empty else 0.0
        gmv = float(orders.gmv_amount_base.sum()) if not orders.empty else 0.0
        size_lines = int(returns.reason_category.astype(str).str.contains("Size|Fit", case=False, na=False).sum()) if not returns.empty else 0
        values = {
            "returns.return_rate": _ratio(returned_lines, purchased_lines),
            "returns.refund_amount_usd": refund,
            "returns.refund_rate": _ratio(refund, gmv),
            "returns.size_return_rate": _ratio(size_lines, purchased_lines),
        }
        keys = returns.return_id.astype(str).tolist() if not returns.empty else []
        metrics = [self._metric(scope_id, key, value, (start, end), "fact_returns + orders", purchased_lines, keys, evidence) for key, value in values.items()]
        monthly = self._return_monthly(returns, orders, start, end)
        ranking = self._return_ranking(returns, orders)
        anomalies = self._return_anomalies(dataset_id, end, filters, scope_id, evidence)
        reason_rows = returns.groupby("reason_category", dropna=False).agg(return_lines=("return_id", "nunique"), refund_amount_usd=("refund_amount_usd", "sum")).reset_index().sort_values("return_lines", ascending=False) if not returns.empty else pd.DataFrame(columns=["reason_category", "return_lines", "refund_amount_usd"])
        return {
            "metrics": metrics,
            "trend": {"title": "退货与退款趋势", "grain": "month", "rows": monthly.to_dict("records"), "series": ["return_rate", "refund_amount_usd"]},
            "ranking": {"title": "高退款商品排名", "dimension": "product", "rows": ranking.head(20).to_dict("records")},
            "distribution": {"title": "退货原因分布", "rows": reason_rows.to_dict("records")},
            "anomalies": anomalies, "causes": self._causes(anomalies), "actions": self._actions(anomalies),
            "evidence": evidence, "details": returns.sort_values("return_request_date", ascending=False).head(200).to_dict("records"),
            "limitations": ["退款 USD 金额按退款占原订单行金额比例乘以订单行 USD GMV 换算；退货率使用订单行而非订单数。"],
        }

    @staticmethod
    def _return_monthly(returns, orders, start, end):
        months = pd.period_range(start.to_period("M"), end.to_period("M"), freq="M").astype(str)
        order_month = orders.copy()
        if not order_month.empty and "order_date" in order_month:
            order_month["period"] = pd.to_datetime(order_month.order_date).dt.to_period("M").astype(str)
        returned = returns.copy()
        if not returned.empty:
            returned["period"] = pd.to_datetime(returned.return_request_date).dt.to_period("M").astype(str)
            result = returned.groupby("period").agg(returned_lines=("return_id", "nunique"), refund_amount_usd=("refund_amount_usd", "sum")).reindex(months, fill_value=0).reset_index()
        else:
            result = pd.DataFrame({"period": months, "returned_lines": 0, "refund_amount_usd": 0.0})
        if not order_month.empty:
            denominators = order_month.groupby("period").record_id.nunique().reindex(months, fill_value=0)
            result["purchased_lines"] = denominators.to_numpy()
            result["return_rate"] = result.returned_lines / result.purchased_lines.replace(0, np.nan)
        else:
            result["purchased_lines"] = 0
            result["return_rate"] = np.nan
        return result

    @staticmethod
    def _return_ranking(returns, orders):
        purchased = orders.groupby(["product_id", "product_name", "category"], dropna=False).agg(purchased_lines=("record_id", "nunique"), gmv_usd=("gmv_amount_base", "sum")).reset_index() if not orders.empty else pd.DataFrame(columns=["product_id", "product_name", "category", "purchased_lines", "gmv_usd"])
        returned = returns.groupby(["product_id", "product_name", "category"], dropna=False).agg(returned_lines=("return_id", "nunique"), refund_amount_usd=("refund_amount_usd", "sum")).reset_index() if not returns.empty else pd.DataFrame(columns=["product_id", "product_name", "category", "returned_lines", "refund_amount_usd"])
        result = purchased.merge(returned, on=["product_id", "product_name", "category"], how="left").fillna({"returned_lines": 0, "refund_amount_usd": 0.0})
        result["return_rate"] = result.returned_lines / result.purchased_lines.replace(0, np.nan)
        result["refund_rate"] = result.refund_amount_usd / result.gmv_usd.replace(0, np.nan)
        return result.sort_values(["refund_amount_usd", "return_rate"], ascending=False)

    def _return_anomalies(self, dataset_id, end, filters, scope_id, evidence):
        current_start = end - timedelta(days=119)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=119)
        rows = []
        for label, left, right in (("current", current_start, end), ("previous", previous_start, previous_end)):
            order_where, order_params = self._where("order_date", dataset_id, left, right, [("country", filters["country"])])
            orders = self._read("SELECT record_id, category, product_id, product_name, gmv_amount_base FROM orders WHERE " + order_where, order_params)
            return_where, return_params = self._where("r.return_request_date", dataset_id, left, right, [("o.country", filters["country"])])
            returned = self._read(
                "SELECT r.return_id, rr.reason_category, o.category, o.product_id, o.product_name FROM fact_returns r "
                "JOIN dim_return_reason rr ON rr.dataset_id=r.dataset_id AND rr.return_reason_id=r.return_reason_id "
                "JOIN business_order_lines bol ON bol.dataset_id=r.dataset_id AND bol.sales_order_number=r.sales_order_number AND bol.sales_order_line_number=r.sales_order_line_number "
                "JOIN orders o ON o.dataset_id=bol.dataset_id AND o.record_id=bol.record_id WHERE r." + return_where,
                return_params,
            )
            clothing_orders = int(orders.category.astype(str).eq("Clothing").sum())
            size_returns = int((returned.category.astype(str).eq("Clothing") & returned.reason_category.astype(str).str.contains("Size|Fit", case=False, na=False)).sum())
            rows.append({"label": label, "rate": _ratio(size_returns, clothing_orders), "denominator": clothing_orders, "keys": returned.loc[returned.category.astype(str).eq("Clothing"), "return_id"].astype(str).tolist()})
        current, previous = rows
        anomalies = []
        rate_change = _change(current["rate"], previous["rate"])
        if current["rate"] is not None and current["rate"] >= 0.10 and rate_change is not None and rate_change >= 0.5:
            rule_id = "RETURN_SIZE_RATE_SPIKE"
            ev = self._evidence(scope_id, "returns.size_return_rate", current["rate"], (current_start, end), "fact_returns + orders", current["denominator"], current["keys"], {"start": previous_start.date().isoformat(), "end": previous_end.date().isoformat()}, RULE_CATALOG[rule_id]["threshold"])
            evidence.append(ev)
            anomalies.append(self._anomaly(rule_id, "Clothing 尺码退货率上升", "Clothing / Size & Fit", current["rate"], previous["rate"], rate_change, ev, "复核尺码表、版型和高退货 SKU，先在德国商品页做尺码提示实验。"))
        return anomalies

    def _logistics(self, dataset_id, start, end, filters, scope_id):
        where, params = self._where("ship_date", dataset_id, start, end, [
            ("destination_country", filters["country"]), ("carrier_id", filters["carrier_id"]),
            ("destination_region", filters["region"]),
        ])
        shipments = self._read(
            "SELECT shipment_id, sales_order_number, carrier_id, carrier_name, destination_country country, "
            "destination_region region, ship_date, promised_delivery_date, actual_delivery_date, transit_days, "
            "delay_days, on_time_flag, cross_border_flag, customs_delay_days, shipment_status, scenario_id "
            "FROM fact_shipments WHERE " + where,
            params,
        )
        evidence: list[dict[str, Any]] = []
        count = len(shipments)
        delayed = int(shipments.delay_days.gt(0).sum()) if count else 0
        values = {
            "logistics.transit_days": float(shipments.transit_days.mean()) if count else None,
            "logistics.on_time_rate": float(shipments.on_time_flag.mean()) if count else None,
            "logistics.delay_rate": _ratio(delayed, count),
            "logistics.delay_days": float(shipments.delay_days.mean()) if count else None,
            "logistics.customs_delay_days": float(shipments.customs_delay_days.mean()) if count else None,
        }
        keys = shipments.shipment_id.astype(str).tolist() if count else []
        metrics = [self._metric(scope_id, key, value, (start, end), "fact_shipments", count, keys, evidence) for key, value in values.items()]
        source = shipments.assign(period=pd.to_datetime(shipments.ship_date).dt.to_period("M").astype(str)) if count else shipments.assign(period=pd.Series(dtype=str))
        monthly = self._shipment_group(source, "period")
        ranking = self._shipment_group(shipments, "carrier_name").sort_values(["delay_rate", "delay_days"], ascending=False)
        anomalies = self._logistics_anomalies(dataset_id, end, filters, scope_id, evidence)
        exception_details = self._tracking_exceptions(dataset_id, keys)
        return {
            "metrics": metrics,
            "trend": {"title": "运输时效与延误趋势", "grain": "month", "rows": monthly.to_dict("records"), "series": ["transit_days", "on_time_rate", "delay_rate", "delay_days"]},
            "ranking": {"title": "承运商时效排名", "dimension": "carrier_name", "rows": ranking.head(20).to_dict("records")},
            "anomalies": anomalies, "causes": self._causes(anomalies), "actions": self._actions(anomalies),
            "evidence": evidence, "details": shipments.sort_values("ship_date", ascending=False).head(200).to_dict("records"),
            "tracking_exceptions": exception_details,
            "limitations": ["运输时长按 ship_date 至 actual_delivery_date；未签收包裹不纳入完整运输时长均值。"],
        }

    @staticmethod
    def _shipment_group(frame, dimension):
        if frame.empty:
            return pd.DataFrame(columns=[dimension, "shipments", "transit_days", "on_time_rate", "delay_rate", "delay_days", "customs_delay_days"])
        result = frame.groupby(dimension, dropna=False).agg(
            shipments=("shipment_id", "nunique"), transit_days=("transit_days", "mean"),
            on_time_rate=("on_time_flag", "mean"), delay_rate=("delay_days", lambda values: float(values.gt(0).mean())),
            delay_days=("delay_days", "mean"), customs_delay_days=("customs_delay_days", "mean"),
        ).reset_index()
        return result

    def _logistics_anomalies(self, dataset_id, end, filters, scope_id, evidence):
        current_start = end - timedelta(days=119)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=119)
        query_filters = [("destination_country", filters["country"]), ("carrier_id", filters["carrier_id"]), ("destination_region", filters["region"])]
        groups = []
        for label, left, right in (("current", current_start, end), ("previous", previous_start, previous_end)):
            where, params = self._where("ship_date", dataset_id, left, right, query_filters)
            source = self._read("SELECT shipment_id, carrier_name, destination_region, transit_days, on_time_flag, delay_days, customs_delay_days FROM fact_shipments WHERE " + where, params)
            grouped = self._shipment_group(source.assign(route=source.carrier_name.astype(str) + " / " + source.destination_region.astype(str)), "route").add_prefix(label + "_").rename(columns={label + "_route": "route"})
            groups.append(grouped)
        comparison = groups[0].merge(groups[1], on="route", how="left")
        anomalies = []
        for row in comparison.itertuples():
            change = _change(row.current_delay_days, row.previous_delay_days)
            if pd.notna(row.current_delay_days) and row.current_delay_days >= 3 and change is not None and change >= 0.5:
                rule_id = "LOGISTICS_CUSTOMS_DELAY_SPIKE"
                ev = self._evidence(scope_id, "logistics.delay_days", row.current_delay_days, (current_start, end), "fact_shipments + fact_tracking_events", int(row.current_shipments), [str(row.route)], {"start": previous_start.date().isoformat(), "end": previous_end.date().isoformat()}, RULE_CATALOG[rule_id]["threshold"])
                evidence.append(ev)
                anomalies.append(self._anomaly(rule_id, "GlobalPost 欧洲线路清关及配送延误上升" if "GlobalPost / Europe" in str(row.route) else "线路延误上升", str(row.route), row.current_delay_days, row.previous_delay_days, change, ev, "核查 CUSTOMS_HOLD 轨迹与报关资料完整性，按周监控平均延误天数并准备承运商切换。"))
        return anomalies

    def _tracking_exceptions(self, dataset_id, shipment_ids):
        if not shipment_ids:
            return []
        # Keep the query bounded and parameterized; UI detail is capped to 200 shipments.
        ids = shipment_ids[:200]
        placeholders = ",".join("?" for _ in ids)
        return self._read(
            "SELECT tracking_event_id, shipment_id, event_sequence, event_code, event_timestamp, event_location, exception_flag "
            "FROM fact_tracking_events WHERE dataset_id=? AND shipment_id IN ({}) AND exception_flag=1 "
            "ORDER BY shipment_id, event_sequence LIMIT 200".format(placeholders),
            [dataset_id, *ids],
        ).to_dict("records")

    def _filter_options(self, topic, dataset_id):
        fields = {
            "advertising": (("country", "target_country_code"), ("channel", "channel"), ("platform", "platform"), ("campaign_id", "campaign_id")),
            "returns": (("country", "o.country"), ("category", "o.category"), ("return_reason", "rr.reason_category")),
            "logistics": (("country", "destination_country"), ("carrier_id", "carrier_id"), ("region", "destination_region")),
        }
        output = {}
        with closing(self._connect()) as connection:
            for key, field in fields[topic]:
                if topic == "returns":
                    sql = "SELECT DISTINCT {0} FROM fact_returns r JOIN dim_return_reason rr ON rr.dataset_id=r.dataset_id AND rr.return_reason_id=r.return_reason_id JOIN business_order_lines bol ON bol.dataset_id=r.dataset_id AND bol.sales_order_number=r.sales_order_number AND bol.sales_order_line_number=r.sales_order_line_number JOIN orders o ON o.dataset_id=bol.dataset_id AND o.record_id=bol.record_id WHERE r.dataset_id=? AND {0} IS NOT NULL ORDER BY {0}".format(field)
                else:
                    table = "fact_ad_performance_daily" if topic == "advertising" else "fact_shipments"
                    sql = "SELECT DISTINCT {0} FROM {1} WHERE dataset_id=? AND {0} IS NOT NULL ORDER BY {0}".format(field, table)
                output[key] = [str(row[0]) for row in connection.execute(sql, (dataset_id,)).fetchall()]
        return output

    @staticmethod
    def _anomaly(rule_id, title, entity, current, previous, change, evidence, recommendation):
        return {
            "id": "an_{}".format(hashlib.sha256((rule_id + entity + evidence["evidence_id"]).encode()).hexdigest()[:16]),
            "rule_id": rule_id, "rule_version": RULE_CATALOG[rule_id]["version"], "title": title,
            "entity": entity, "status": "需关注", "current_value": current, "comparison_value": previous,
            "change_rate": change, "threshold": RULE_CATALOG[rule_id]["threshold"],
            "reason": "指标已达到版本化规则阈值；这是相关性诊断，不是已证明因果。",
            "recommendation": recommendation, "evidence_ids": [evidence["evidence_id"]],
            "limitations": [SIMULATION_LIMITATION, "规则命中不证明因果，需要运营核查或实验验证。"],
        }

    @staticmethod
    def _causes(anomalies):
        return [{"anomaly_id": item["id"], "entity": item["entity"], "explanation": item["reason"], "evidence_ids": item["evidence_ids"]} for item in anomalies]

    @staticmethod
    def _actions(anomalies):
        return [{"anomaly_id": item["id"], "priority": "P1" if index == 0 else "P2", "title": item["recommendation"], "threshold": item["threshold"], "evidence_ids": item["evidence_ids"]} for index, item in enumerate(anomalies)]
