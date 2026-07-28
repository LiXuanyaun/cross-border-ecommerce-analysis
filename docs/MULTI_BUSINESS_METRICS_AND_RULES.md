# 多业务指标与异常规则

所有指标由 `crossborder_analytics.multibusiness_analysis.METRIC_CATALOG` 注册，所有异常由 `RULE_CATALOG` 版本化；Dashboard、API、报告和 Agent 引用相同证据编号与限制。

| 专题 | 指标 | 公式/口径 |
|---|---|---|
| 广告 | 花费、曝光、点击、转化 | 日表现汇总 |
| 广告 | CTR、CVR、CPC、CPA、ROAS | 点击/曝光、转化/点击、USD 花费/点击、USD 花费/转化、USD 归因收入/USD 花费 |
| 退款 | 退货率、退款金额、退款金额率、尺码退货率 | 退货订单行/购买订单行；按订单行 USD GMV 换算的退款；退款/USD 订单行 GMV；尺码原因退货行/购买行 |
| 物流 | 平均运输时长、准时率、延误率、平均延误天数、平均清关滞留 | 包裹事实的平均值或占比 |

| 规则 ID | 阈值 | 行动边界 |
|---|---|---|
| `AD_SPEND_UP_CVR_DOWN` | 花费增幅 >= 50%，CVR 变动 <= -20% | 检查搜索词、出价、落地页与归因覆盖 |
| `AD_LOW_ROAS` | ROAS < 2.0 | 降低或暂停低回报活动，复核归因窗口 |
| `AD_HIGH_CPA` | CPA > 75 USD | 限制获客成本并检查受众/素材 |
| `RETURN_SIZE_RATE_SPIKE` | 尺码退货率 >= 10%，相对增幅 >= 50% | 复核尺码表、商品页和供应商批次 |
| `RETURN_HIGH_PRODUCT_RATE` | 商品退货率 >= 12%，购买行 >= 20 | 下钻商品、原因和目的国家 |
| `LOGISTICS_CUSTOMS_DELAY_SPIKE` | 平均延误天数 >= 3，相对增幅 >= 50% | 与承运商核对清关资料和路线容量 |
| `LOGISTICS_HIGH_DELAY_RATE` | 延误率 >= 20% | 检查服务等级、目的国家和异常轨迹 |

当前场景必须识别：德国搜索广告的花费上涨/CVR 下降、Clothing 尺码退货率上升、GlobalPost 欧洲线路清关与配送延误上升。结论均受模拟来源、关联完整度和筛选周期限制，不能声称因果。
