from __future__ import annotations

from typing import Any


FIELD_CATALOG: dict[str, tuple[str, str]] = {
    "period": ("月份", "text"),
    "value": ("指标值", "decimal"),
    "secondary": ("辅助指标", "decimal"),
    "name": ("对象", "text"),
    "ad_date": ("广告日期", "date"),
    "campaign_id": ("广告活动", "text"),
    "country": ("国家", "text"),
    "channel": ("渠道", "text"),
    "platform": ("平台", "text"),
    "impressions": ("曝光", "integer"),
    "clicks": ("点击", "integer"),
    "conversions": ("转化", "integer"),
    "spend_usd": ("广告花费", "currency"),
    "attributed_revenue_usd": ("归因收入", "currency"),
    "cvr": ("转化率", "percent"),
    "roas": ("ROAS", "decimal"),
    "return_request_date": ("退款申请日期", "date"),
    "return_id": ("退款记录", "text"),
    "product_name": ("商品", "text"),
    "category": ("品类", "text"),
    "return_quantity": ("退款数量", "integer"),
    "refund_amount_usd": ("退款金额", "currency"),
    "reason_category": ("退款原因", "text"),
    "return_rate": ("退货率", "percent"),
    "ship_date": ("发货日期", "date"),
    "shipment_id": ("运单", "text"),
    "carrier_name": ("承运商", "text"),
    "region": ("地区", "text"),
    "transit_days": ("运输天数", "days"),
    "delay_days": ("延误天数", "days"),
    "delay_rate": ("延误率", "percent"),
    "on_time_flag": ("准时状态", "boolean"),
    "customs_delay_days": ("清关滞留天数", "days"),
    "shipment_status": ("物流状态", "text"),
}

BUSINESS_DETAIL_FIELDS = {
    "advertising": (
        "ad_date", "campaign_id", "country", "channel", "platform", "impressions",
        "clicks", "conversions", "spend_usd", "attributed_revenue_usd",
    ),
    "returns": (
        "return_request_date", "return_id", "product_name", "category", "country",
        "return_quantity", "refund_amount_usd", "reason_category",
    ),
    "logistics": (
        "ship_date", "shipment_id", "carrier_name", "country", "region", "transit_days",
        "delay_days", "on_time_flag", "customs_delay_days", "shipment_status",
    ),
}

BUSINESS_RANKING = {
    "advertising": ("campaign_id", "spend_usd"),
    "returns": ("product_name", "refund_amount_usd"),
    "logistics": ("carrier_name", "delay_rate"),
}


def _field(field: str, *, label: str | None = None, value_format: str | None = None) -> dict[str, str]:
    registered_label, registered_format = FIELD_CATALOG.get(field, (field, "text"))
    return {"field": field, "label": label or registered_label, "format": value_format or registered_format}


def build_business_presentation_contract(
    topic: str,
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    pagination: dict[str, int],
) -> dict[str, Any]:
    trend = payload.get("trend", {})
    trend_series = [
        _field(field) for field in list(trend.get("series", []))[:2]
    ]
    ranking = payload.get("ranking", {})
    ranking_dimension, ranking_value = BUSINESS_RANKING[topic]
    columns = [_field(field) for field in BUSINESS_DETAIL_FIELDS[topic]]
    return {
        "visualizations": [
            {
                "id": "{}_trend".format(topic), "type": "line", "title": trend.get("title", "趋势"),
                "dimension": _field("period"), "series": trend_series, "rows": list(trend.get("rows", [])),
            },
            {
                "id": "{}_ranking".format(topic), "type": "bar", "title": ranking.get("title", "排名"),
                "dimension": _field(ranking_dimension), "series": [_field(ranking_value)],
                "rows": list(ranking.get("rows", [])),
            },
        ],
        "table": {"columns": columns, "rows": rows, "pagination": pagination},
    }


def build_topic_presentation_contract(payload: dict[str, Any]) -> dict[str, Any]:
    trend = payload.get("trend", {})
    trend_series = [_field("value", value_format=trend.get("format", "decimal"))]
    if trend.get("secondary_label"):
        trend_series.append(_field("secondary", label=trend["secondary_label"], value_format=trend.get("secondary_format") or "decimal"))
    composition = payload.get("composition", {})
    ranking = payload.get("ranking", {})
    visualizations = [
        {
            "id": "{}_trend".format(payload.get("topic", "topic")), "type": "line",
            "title": trend.get("title", "趋势"), "dimension": _field("period"),
            "series": trend_series, "rows": list(trend.get("rows", [])),
        },
        {
            "id": "{}_composition".format(payload.get("topic", "topic")), "type": "pie",
            "title": composition.get("title", "构成"), "dimension": _field("name"),
            "series": [_field("value", value_format=composition.get("format", "decimal"))],
            "rows": list(composition.get("rows", [])),
        },
        {
            "id": "{}_ranking".format(payload.get("topic", "topic")), "type": "bar",
            "title": ranking.get("title", "排名"), "dimension": _field("name"),
            "series": [_field("value", value_format=ranking.get("format", "decimal"))],
            "rows": list(ranking.get("rows", [])),
        },
    ]
    columns = [
        {"field": column["key"], "label": column["label"], "format": column.get("format", "text")}
        for column in payload.get("columns", [])
    ]
    return {
        "visualizations": visualizations,
        "table": {
            "columns": columns,
            "rows": list(payload.get("details", [])),
            "pagination": dict(payload.get("pagination", {})),
        },
    }
