# AdventureWorksDW 模拟业务扩展数据

> **重要：本目录中小写文件名的 `dim_*.csv`、`fact_*.csv`、`bridge_*.csv` 均为模拟数据，不是 AdventureWorks 原始事实数据。**

这些数据用于证明系统可以分析广告、退款退货和物流业务。模拟记录通过订单号、订单行、客户、产品和区域等键，与 `FactInternetSales.csv` 的真实示例结构关联。

## 文件说明

| 文件 | 粒度 | 用途 | 主要关联键 |
|---|---|---|---|
| `dim_campaign.csv` | 一行一个广告活动 | 广告活动、渠道和平台 | `campaign_id` |
| `fact_ad_performance_daily.csv` | 日期 + 广告活动 | 花费、曝光、点击、转化、ROAS | `campaign_id` |
| `bridge_order_attribution.csv` | 订单 + 广告活动 | 把广告转化关联到订单 | `sales_order_number`, `campaign_id` |
| `dim_return_reason.csv` | 一行一个退货原因 | 退货原因分类 | `return_reason_id` |
| `fact_returns.csv` | 一行一笔订单行退货 | 退货原因、数量、退款金额 | `sales_order_number`, `sales_order_line_number` |
| `dim_carrier.csv` | 一行一个模拟承运商 | 承运商和服务级别 | `carrier_id` |
| `fact_shipments.csv` | 一行一个订单包裹 | 时效、延误、跨境和承运商 | `sales_order_number`, `shipment_id` |
| `fact_tracking_events.csv` | 一行一个物流轨迹事件 | 揽收、清关、派送、签收 | `shipment_id` |

## 内置验证场景

| 场景编号 | 模拟问题 | 应看到的信号 |
|---|---|---|
| `SCN_AD_DE_SEARCH_EFFICIENCY_DECLINE` | 德国搜索广告加大投入但效率下降 | 花费上升超过 2 倍，转化率下降 |
| `SCN_RET_CLOTHING_SIZE_SPIKE` | 服装尺码退货上升 | Clothing 类目的尺码原因退货明显增加 |
| `SCN_LOGISTICS_EU_CUSTOMS_DELAY` | 欧洲线路清关延误 | GlobalPost 的清关滞留和延误天数上升 |

场景窗口是源订单最大日期之前的最后 120 天，具体日期和校验结果见 `synthetic_scenario_manifest.json`。

## 数据标识

每一行都有以下字段：

- `data_origin=synthetic_extension`
- `generator_version=1.0.0`
- `scenario_id`：`BASELINE` 或具体异常场景编号
- `seed=20260728`
- `generated_at=2026-07-28T00:00:00.000Z`

这些字段必须保留在数据库和报告中。展示模拟结果时，应明确标注“模拟数据”。

## 重新生成

在本目录运行：

```powershell
node .\generate_synthetic_extensions.js
```

生成器只使用 Node.js 内置模块。固定随机种子和固定生成时间保证重复运行得到相同文件。生成结束前会检查外键、退款上限、归因比例、事件顺序和三个场景是否足够明显；任何检查失败都会停止生成并报错。

## 使用边界

- 广告花费统一以 USD 表示。归因桥同时保留订单币种收入和按 `FactCurrencyRate.AverageRate` 换算的 USD 收入；广告 ROAS 只使用 USD 收入，避免混用币种。
- 当前采用末次点击归因，每个被归因订单的信用为 1，不支持多触点归因。
- 一个订单对应一个模拟包裹。拆单、合单和部分发货不在本版本范围内。
- 退款数据是订单行粒度，不能与订单表直接相加后再汇总，否则会重复计算订单金额。
- 模拟数据适合功能演示、规则测试和 Dashboard 验证，不适合训练真实业务预测模型或得出真实市场结论。
