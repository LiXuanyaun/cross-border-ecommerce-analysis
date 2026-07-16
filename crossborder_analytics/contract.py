"""Order-grain ecommerce dataset contract and domain validation."""
from typing import Dict, Optional

import pandas as pd

from autoclean.analytics import DatasetContract, FieldSpec, ValidationIssue


ECOMMERCE_CONTRACT = DatasetContract(
    name="cross_border_orders_v1",
    grain_key="order_id",
    fields=(
        FieldSpec("order_id", required=True, nullable=False, aliases=("订单号", "订单ID")),
        FieldSpec("customer_id", aliases=("客户ID", "用户ID")),
        FieldSpec("product_id", aliases=("商品ID", "SKU")),
        FieldSpec("category", aliases=("品类", "商品分类")),
        FieldSpec("price", dtype="float", aliases=("单价",)),
        FieldSpec("discount", dtype="float", aliases=("折扣", "折扣率")),
        FieldSpec("quantity", dtype="integer", aliases=("数量", "销量")),
        FieldSpec("payment_method", aliases=("支付方式",)),
        FieldSpec("order_date", dtype="date", required=True, nullable=False, aliases=("下单日期", "订单日期")),
        FieldSpec("delivery_time_days", dtype="float", aliases=("配送天数", "物流时长")),
        FieldSpec("region", aliases=("地区", "市场", "国家")),
        FieldSpec("returned", dtype="boolean", aliases=("是否退货", "退货")),
        FieldSpec("total_amount", dtype="float", required=True, nullable=False, aliases=("GMV", "订单金额", "销售额")),
        FieldSpec("shipping_cost", dtype="float", aliases=("运费",)),
        FieldSpec("profit_amount", dtype="float", aliases=("profit_margin", "利润", "利润额"), semantic="amount"),
        FieldSpec("customer_age", dtype="integer", aliases=("客户年龄",)),
        FieldSpec("customer_gender", aliases=("客户性别",)),
        FieldSpec("currency", aliases=("币种", "货币", "currency_code")),
    ),
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
