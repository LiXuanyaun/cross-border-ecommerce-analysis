"""Order-grain ecommerce dataset contract and domain validation."""
from typing import Dict, Optional

import pandas as pd

from autoclean.analytics import DatasetContract, FieldSpec, ValidationIssue


ECOMMERCE_CONTRACT = DatasetContract(
    name="cross_border_orders_v2",
    grain_key="order_id",
    fields=(
        FieldSpec("order_id", required=True, nullable=False, aliases=("订单号", "订单ID")),
        FieldSpec("customer_id", aliases=("客户ID", "用户ID")),
        FieldSpec("product_id", aliases=("商品ID", "SKU")),
        FieldSpec("product_name", aliases=("商品名称", "产品名称", "Product", "product_title")),
        FieldSpec("category", aliases=("品类", "商品分类")),
        FieldSpec("price", dtype="float", aliases=("单价",)),
        FieldSpec("discount", dtype="float", aliases=("折扣", "折扣率")),
        FieldSpec("quantity", dtype="integer", aliases=("数量", "销量")),
        FieldSpec("payment_method", aliases=("支付方式",)),
        FieldSpec("order_date", dtype="date", required=True, nullable=False, aliases=("下单日期", "订单日期")),
        FieldSpec("delivery_time_days", dtype="float", aliases=("配送天数", "物流时长")),
        FieldSpec("country", aliases=("国家", "目的国", "销售国家", "market_country")),
        FieldSpec("region", aliases=("地区", "区域", "大区", "市场")),
        FieldSpec("returned", dtype="boolean", aliases=("是否退货", "退货")),
        FieldSpec("total_amount", dtype="float", required=True, nullable=False, aliases=("GMV", "订单金额", "销售额")),
        FieldSpec("shipping_cost", dtype="float", aliases=("运费",)),
        FieldSpec("profit_amount", dtype="float", aliases=("profit_margin", "利润", "利润额"), semantic="amount"),
        FieldSpec("cost_amount", dtype="float", aliases=("成本", "商品成本", "订单成本"), semantic="amount"),
        FieldSpec("refund_amount", dtype="float", aliases=("退款金额", "退款额", "退款损失"), semantic="amount"),
        FieldSpec("ad_spend", dtype="float", aliases=("广告花费", "广告投放", "投放金额"), semantic="amount"),
        FieldSpec("campaign_id", aliases=("campaign_id", "campaign", "广告活动ID")),
        FieldSpec("inventory_available", dtype="integer", aliases=("可用库存", "库存可用量", "库存数量")),
        FieldSpec("stockout_flag", dtype="boolean", aliases=("缺货", "断货")),
        FieldSpec("return_reason", aliases=("退货原因", "退款原因")),
        FieldSpec("shipping_status", aliases=("发货状态", "物流状态")),
        FieldSpec("channel", aliases=("渠道", "销售渠道")),
        FieldSpec("store_id", aliases=("店铺ID", "门店ID", "店铺编号")),
        FieldSpec("customer_age", dtype="integer", aliases=("客户年龄",)),
        FieldSpec("customer_gender", aliases=("客户性别",)),
        FieldSpec("currency", aliases=("币种", "货币", "currency_code")),
    ),
)

# Import preview needs to inspect duplicate order ids before the user confirms
# whether each row is an order or an order line.
ECOMMERCE_IMPORT_CONTRACT = DatasetContract(
    name="cross_border_order_import_v3",
    grain_key=None,
    fields=ECOMMERCE_CONTRACT.fields,
)

ECOMMERCE_STORAGE_CONTRACT = DatasetContract(
    name="cross_border_order_records_v3",
    grain_key="record_id",
    fields=(FieldSpec("record_id", required=True, nullable=False),) + ECOMMERCE_CONTRACT.fields,
)


def domain_issues(frame: pd.DataFrame) -> list:
    issues = []
    checks = {
        "total_amount": (lambda value: value < 0, "订单金额不能为负数"),
        "price": (lambda value: value < 0, "价格不能为负数"),
        "quantity": (lambda value: value <= 0, "销量必须大于0"),
        "discount": (lambda value: (value < 0) | (value > 1), "折扣必须位于0到1之间"),
        "delivery_time_days": (lambda value: value < 0, "配送天数不能为负数"),
    }
    for field, (predicate, message) in checks.items():
        if field not in frame:
            continue
        mask = frame[field].notna() & predicate(frame[field])
        count = int(mask.sum())
        if count:
            issues.append(ValidationIssue(
                severity="WARNING",
                code="DOMAIN_RULE_FAILED",
                message="{}：{} 行".format(message, count),
                field=field,
                row_count=count,
            ))

    if {"price", "discount", "quantity", "total_amount"}.issubset(frame.columns):
        expected = frame["price"] * (1 - frame["discount"]) * frame["quantity"]
        mask = expected.notna() & frame["total_amount"].notna() & ((expected - frame["total_amount"]).abs() > 0.02)
        count = int(mask.sum())
        if count:
            issues.append(ValidationIssue(
                severity="WARNING",
                code="AMOUNT_FORMULA_MISMATCH",
                message="{} 行不满足 total_amount = price * (1-discount) * quantity".format(count),
                field="total_amount",
                row_count=count,
            ))
    return issues
