# CrossBorder AI Analytics

面向跨境电商运营复盘的证据型经营分析平台。项目以 AutoClean 6.4 为非破坏性数据底座，提供经营总览、销售、商品、客户、区域、退货与运营分析，并从同一份证据包生成 Dashboard、Excel、Markdown、DOCX 和可审计 manifest。

## 核心约束

- 原始文件只读，不填充、截断、删除或覆盖订单。
- `profit_margin` 在当前样例中映射为单笔利润额 `profit_amount`；利润率由利润额除以 GMV 派生。
- 不完整月份只展示，不参与月环比结论。
- 缺字段、样本不足或汇率不完整时模块显式降级，不编造结果。
- 退货金额称为“退货关联GMV”，没有退款额和成本时不声称真实损失。

## 安装

```powershell
cd D:\projects\cross-border-ecommerce-analysis
python -m pip install -r requirements.txt
```

`requirements.txt` 会以 editable 模式安装相邻的 `../AutoClean-v1` 和本项目。

## 启动 Dashboard

```powershell
streamlit run app.py
```

默认载入 `data/ecommerce_sales_34500.csv`。侧边栏可上传 CSV/XLSX、调整字段映射、选择源币种和基准币种、上传历史汇率表，并按日期、区域和品类筛选。

## 命令行导出

```powershell
python -m crossborder_analytics.cli data/ecommerce_sales_34500.csv `
  --source-currency CNY `
  --target-currency CNY `
  -o outputs/latest
```

多币种数据默认从 Frankfurter/ECB 读取历史日汇率并缓存。也可上传或通过 CLI 传入汇率表：

```csv
date,source_currency,target_currency,rate
2025-01-03,USD,CNY,7.2
```

周末和节假日最多回溯 7 天。跨币种金额合计要求 100% 汇率覆盖。

## 输出

- `analysis_result.xlsx`
- `cross_border_analysis_report.md`
- `cross_border_analysis_report.docx`
- `analysis_manifest.json`

Excel 必含 `summary`、`product_analysis`、`customer_analysis`、`region_analysis`、`return_analysis`、`module_status`、`evidence`、`data_quality` 和 `fx_rates`。

## 测试

```powershell
python -m pytest
```

测试覆盖样例指标基线、部分月份、缺少可选字段、重复订单、历史汇率、RFM、低样本商品和四类导出。

### 浏览器自动化验收

项目使用本机已安装的 Chrome 和 Edge，不下载额外浏览器。启动两个隔离的调试窗口：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_debug_browsers.ps1
```

Chrome 仅在 `127.0.0.1:9222` 提供调试接口，Edge 使用 `127.0.0.1:9223`。自动化资料保存在 `.cache/browser-debug`，不会读取日常浏览器资料。

检查连接和页面结构：

```powershell
python .\scripts\browser_control.py --browser all status
python .\scripts\browser_control.py --browser chrome snapshot --url http://localhost:8501
python .\scripts\browser_control.py --browser edge screenshot --output .cache\browser-debug\screenshots\edge.png
```

运行 Chrome 与 Edge 的侧栏折叠、窄屏布局和截图验收：

```powershell
$env:BROWSER_E2E='1'
python -m pytest tests\test_sidebar_browser.py
```

## 当前边界

MVP 假设一行一订单，为本地单用户应用。SQL查询、自然语言问答、LLM、趋势预测、多店铺/API 实时接入不在本期范围。

## 项目复盘与路线图

今日交付总结、可复用工程经验、当前缺点和 P0-P3 优化计划见：

- [阶段总结与工程化路线图](docs/PROJECT_REVIEW_2026-07-16.md)
