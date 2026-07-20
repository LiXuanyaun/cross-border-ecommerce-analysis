# CrossBorder AI Analytics 3.0

面向跨境电商运营复盘的证据型经营分析平台。项目以 AutoClean 6.6 为非破坏性数据与质量底座，将规范化订单和版本化分析对象写入 SQLite，再由注册指标、异常规则、诊断、建议和受控 SQL 证据生成 Dashboard、Excel、Markdown、DOCX 和可审计 manifest。

3.0 新增基于 React、TypeScript、TailwindCSS 与 FastAPI 的企业级 Web 界面。原 Streamlit `app.py` 继续保留，用于业务口径对照和兼容运行。

## 核心约束

- 原始文件只读，不填充、截断、删除或覆盖订单。
- `profit_margin` 在当前样例中映射为单笔利润额 `profit_amount`；利润率由利润额除以 GMV 派生。
- 不完整月份只展示，不参与月环比结论。
- 缺字段、样本不足或汇率不完整时模块显式降级，不编造结果。
- 退货金额称为“退货关联GMV”，没有退款额和成本时不声称真实损失。
- SQLite 只保存规范化分析视图；相同数据重复导入保持幂等，不同 `dataset_id` 绝不混算。
- 市场维度整份数据统一选择：有有效 `country` 时使用国家，否则回退 `region`；国家缺失值显示“未标注国家”。
- 页面内商品分类、客户分群和热力图模式只改变构成预览、详情与行动清单，不改变固定分析模型和完整报告。
- 市场增长和产品机会按最新两个完整可比较周期确定性分类；跨两期合计少于 3 单的商品只计入样本不足汇总，不生成机会或行动项。
- 摘要版和完整版《跨境电商经营分析与行动报告》使用相同指标、机会、行动和证据；报告范围只改变关注对象。

## 安装

```powershell
cd D:\projects\cross-border-ecommerce-analysis
python -m pip install -r requirements.txt
```

安装过程会从 GitHub 的固定 `v6.6.0` Tag 获取 AutoClean，并以 editable 模式安装本项目。需要本机已安装 Git 且能够访问 GitHub，不再要求相邻目录中存在 AutoClean 仓库。

## 启动 Dashboard

### React + FastAPI（推荐）

```powershell
cd D:\projects\cross-border-ecommerce-analysis
python -m pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
powershell -ExecutionPolicy Bypass -File .\scripts\start_web.ps1
```

访问 `http://127.0.0.1:8000`。默认使用 `demo` 模式：样例数据可筛选、分析和生成临时报告，但不能上传文件或修改共享任务。

FastAPI 的 OpenAPI Schema 位于 `/openapi.json`。后端契约调整后，在服务运行期间执行 `cd frontend; npm run generate:api` 可刷新 `src/generated/api.ts`，业务组件继续通过页面级 DTO 封装使用这些接口。

本地私有模式允许从 AI 分析师页面一键读取当前 CC Switch Codex provider：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_web.ps1 -Mode private
```

CC Switch 的 API Key 只进入后端进程内存，不返回浏览器、不写入项目数据库和日志。私有模式的任务状态、Agent 会话、消息、运行和工具事件保存在 `database/crossborder_state.db`；演示模式会话只存在内存中并按 `CROSSBORDER_DEMO_SESSION_TTL` 清理。没有 CC Switch 的部署环境可参考 `.env.example` 配置 OpenAI 兼容模型。

### Streamlit 兼容界面

```powershell
streamlit run app.py
```

默认载入 `data/ecommerce_sales_34500.csv`。侧栏顶部是明确的页面导航；全局只保留影响全部页面的分析周期。上传 CSV/XLSX、字段映射、源币种、基准币种和历史汇率统一收在“数据与口径”区域，区域和品类不作为全局筛选器。

“区域市场”页面提供动态的市场×品类热力图，可在订单偏好和收益贡献之间切换；市场策略矩阵公开规模、利润、退货和履约基准。“商品分析”提供完整分页清单、动态分类、搜索/列筛选、同页商品详情及当前预览下载。“客户分析”的 RFM（客户价值模型）保持固定，分群选择只联动市场/品类构成和客户清单。

“市场增长”页面按 GMV（成交总额）增长、订单、客单价、利润率、退货率、SKU 集中度、样本和质量区分健康增长、风险增长、稳定、收缩、低价值、样本不足与数据不足；“产品机会”页面在原有经营分类之外识别扩量、扩市场、客户渗透、组合销售、利润修复、高风险增长和观察机会。两页均支持固定矩阵、局部筛选、详情和当前清单下载。

“导出”页面可选择摘要版或完整版、整体或指定市场/品类范围、是否附带行动明细，以及 DOCX/Excel 格式。导出设置不重新计算数据；Excel 同时保留完整指标与证据审计表。

Phase 2 新增三个工作区：“风险中心”按 P0-P3 管理异常，“洞察中心”把指标变化、驱动贡献、行动边界和证据串在同一审计轨道，“数据健康中心”展示 A-D 可信度、字段健康、分析能力和补数路线。所有工作区、CLI 和报告读取同一批持久化对象。

Dashboard 所有 Plotly 图表使用同一套响应式布局：时间轴按周期数量调整角度和刻度密度，中文分类标签自动换行，水平图和热力图按内容增加高度，标题、图例、坐标轴及色条启用自动边距。报告中的 Matplotlib 图片使用相同中文字体回退和安全画布边距。

规范化数据默认保存在 `database/ecommerce.db`。数据库、WAL 和临时文件不会进入 Git；当前数据集编号、入库记录数和数据库版本可在“数据准备”视图查看。

表结构、版本隔离、事务边界和命名查询目录见 [SQLite 数据层说明](docs/SQLITE_DATA_LAYER.md)。

## 命令行导出

```powershell
python -m crossborder_analytics.cli data/ecommerce_sales_34500.csv `
  --source-currency CNY `
  --target-currency CNY `
  --database database/ecommerce.db `
  -o outputs/latest
```

需要对照旧版 pandas 聚合时，可显式传入 `--backend pandas`。Dashboard 和 CLI 不会在数据库失败后静默回退。

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

Excel 在原有业务 Sheet 之外增加 `metric_definitions`、`metric_snapshots`、`anomalies`、`diagnoses`、`recommendations`、`evidence`、`data_quality_summary`、`data_quality_dimensions`、`field_quality`、`analysis_capability`、`data_improvement_plan` 和 `data_quality_issues`。

## 测试

```powershell
python -m pytest
```

测试覆盖样例指标基线、部分月份、缺少可选字段、重复订单、历史汇率、RFM、国家优先/区域回退、市场品类占比、策略规则、商品品类冲突、商品详情和四类导出。

SQL 数据层另外覆盖版本幂等、筛选参数、失败回滚、查询日志，以及市场品类、客户构成和商品详情的 pandas 结果对账。运行 10 万行本地基准（包含市场热力查询和商品详情查询）：

```powershell
python .\scripts\benchmark_sqlite.py
```

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

## Web 架构

```text
React SPA
  -> FastAPI /api/v1
  -> AnalysisService / AnalysisRequest
  -> SQLite + 受控 SQL
  -> 指标、异常、诊断、建议、证据、报告
```

一级导航固定为经营总览、专题分析、数据中心和 AI 分析师。Agent 只能调用注册的指标、异常、诊断、建议、证据和报告工具，不开放任意 SQL。

单容器部署：

```powershell
docker build -t crossborder-ai .
docker run --rm -p 8000:8000 crossborder-ai

# 私有模式使用命名卷持久化任务与 Agent 状态
docker run --rm -p 8000:8000 `
  -e CROSSBORDER_APP_MODE=private `
  -v crossborder-state:/app/state `
  crossborder-ai
```

## 当前边界

MVP 假设一行一订单，当前只开放预定义、参数化 SQL，不提供任意 SQL 控制台。公开演示模式不调用真实模型；真实 Agent 首先作为本地私有能力交付。多租户权限、趋势预测、多店铺/API 实时接入不在本期范围。

## 项目复盘与路线图

今日交付总结、可复用工程经验、当前缺点和 P0-P3 优化计划见：

- [阶段总结与工程化路线图](docs/PROJECT_REVIEW_2026-07-16.md)
- [今日总结、反思与优化](docs/DAILY_RETROSPECTIVE_2026-07-16.md)
