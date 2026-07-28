# 多业务数据字典

## 适用范围

v4.0 将 AdventureWorks 订单与模拟广告、退款、物流扩展分开存储。所有业务表均包含 `dataset_id`、`import_batch_id`、`data_origin`、`scenario_id`、`generator_version`；`source_*` 字段保留原始业务关联键。`synthetic_extension` 仅用于功能验证，不能被描述为真实经营数据。

| 表 | 粒度 | 主业务键 | 主要关联 |
|---|---|---|---|
| `import_batches` | 一次导入 | `import_batch_id` | 数据集、来源、版本、状态 |
| `import_files` | 一个源文件 | `import_file_id` | SHA-256、类型、粒度、行数 |
| `business_orders` | 一个销售订单 | `dataset_id + sales_order_number` | 标准订单事实 |
| `business_order_lines` | 一个销售订单行 | `dataset_id + sales_order_number + sales_order_line_number` | 标准订单记录 |
| `dim_campaign` | 一个广告活动 | `dataset_id + campaign_id` | 广告日表现、归因 |
| `dim_carrier` | 一个承运商 | `dataset_id + carrier_id` | 发货、轨迹 |
| `dim_return_reason` | 一个退货原因 | `dataset_id + return_reason_id` | 退款退货 |
| `fact_ad_performance_daily` | 日期×活动 | `dataset_id + ad_date + campaign_id` | 广告活动 |
| `bridge_order_attribution` | 一条订单归因 | `dataset_id + attribution_id` | 订单、活动 |
| `fact_returns` | 一次退货/退款 | `dataset_id + return_id` | 订单行、包裹、原因 |
| `fact_shipments` | 一个包裹 | `dataset_id + shipment_id` | 销售订单、承运商 |
| `fact_tracking_events` | 一个包裹轨迹节点 | `dataset_id + tracking_event_id` | 包裹、承运商 |

## 口径字段

- 广告：`spend_usd` 与 `attributed_revenue_usd` 是 ROAS 的唯一金额口径；`billing_currency` 必须为 `USD`。
- 归因：每个 `sales_order_number` 的 `attribution_credit` 合计不得超过 1。
- 退款：`return_quantity` 不得超过 `original_order_quantity`，`refund_amount` 不得超过 `original_line_sales_amount`。
- 物流：`event_sequence` 在包裹内唯一，`event_timestamp` 随序号严格递增；`CUSTOMS` 事件必须标记跨境。
