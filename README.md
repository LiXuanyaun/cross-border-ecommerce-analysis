<p align="center">
  <img src="./frontend/public/crossborder-logo.png" alt="CrossBorder AI Analytics" width="260" />
</p>

<p align="center">
  <strong>面向跨境电商的证据型经营分析平台</strong>
</p>

<p align="center">
  从订单、市场到广告、退货与物流，让每一个经营结论都能追溯到数据、口径和证据。
</p>

<p align="center">
  <a href="docs/ARCHITECTURE.md">架构说明</a> ·
  <a href="docs/IMPORT_GUIDE.md">导入指南</a> ·
  <a href="docs/SQLITE_DATA_LAYER.md">SQLite 数据层</a> ·
  <a href="docs/MULTI_BUSINESS_DATA_DICTIONARY.md">多业务数据字典</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-4.0.0-1769ff" alt="version 4.0.0" />
  <img src="https://img.shields.io/badge/python-3.10%2B-3776ab" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/frontend-React%2018-149eca" alt="React 18" />
  <img src="https://img.shields.io/badge/backend-FastAPI-009688" alt="FastAPI" />
  <img src="https://img.shields.io/badge/storage-SQLite-003b57" alt="SQLite" />
</p>

> CrossBorder AI Analytics 不只是把数据画成图表，而是把“数据准备 → 指标计算 → 异常识别 → 经营诊断 → 建议与行动 → 报告复盘”连成一条可复算、可审计的分析链路。

## 为什么做它？

跨境电商经营分析经常卡在三个地方：原始文件口径不一致，报表数字无法复核；缺字段或缺周期时，系统仍然给出看似确定的结论；AI 能够生成文字，却不能证明这些文字来自哪一份数据、哪个时期和哪套指标。

本项目把数据身份、分析范围、指标定义、质量状态和证据链视为正式契约。无论是 Dashboard、报告、任务还是 AI 分析师，都使用同一份版本化数据和同一套注册指标。

## 核心亮点

| 能力 | 解决的问题 | 项目实现 |
| --- | --- | --- |
| **证据优先** | 结论无法解释，建议无法复盘 | `MetricSnapshot → Anomaly → Diagnosis → Recommendation → Evidence → Action`，每一步都可回溯 |
| **数据质量即产品能力** | 缺字段、样本不足和不完整月份被误判为经营问题 | 按数据集能力返回 `READY`、`PARTIAL`、`INSUFFICIENT_DATA`、`EMPTY` 等明确状态，并生成补数路线 |
| **统一数据集身份** | 总览、专题、报告和 Agent 使用了不同范围 | `dataset_id`、`scope_id`、周期、币种和质量状态贯穿所有页面与输出 |
| **不破坏原始数据** | 导入和清洗覆盖源文件，历史报表漂移 | 原始文件只读；规范化结果写入版本化 SQLite；追加数据生成只读子版本 |
| **多业务事实模型** | 把广告、退货、物流事件误当成订单行 | 订单、广告、退货、物流保持各自业务粒度，通过统一 `dataset_id` 协同分析 |
| **受控 AI 分析** | AI 混用数据、编造数字或绕过权限 | Agent 只能调用注册工具和参数化查询，带着明确范围、证据和降级状态运行 |

## 能分析什么？

### 经营总览

从一张总览看清 GMV、订单数、客单价、利润、市场表现、商品表现和增长机会；系统会自动识别最新可比较的完整周期，不用固定日期掩盖数据范围问题。

### 订单专题

五个可独立筛选、查看明细和导出的分析主题：

- **市场**：国家优先、区域回退，查看规模、贡献、增长和市场策略。
- **商品**：商品结构、销售排行、贡献、利润质量和商品详情。
- **客户**：客户规模、构成、RFM 分群和高价值客户线索。
- **利润**：利润额、利润率、贡献结构和高销售低利润对象。
- **退货**：退货关联 GMV、退货风险与相关商品/市场暴露。

### 多业务专题

当数据集中包含扩展事实时，进入同一数据身份下的三个业务视图：

| 专题 | 关注内容 | 当前数据边界 |
| --- | --- | --- |
| 广告 | 花费、曝光、点击、转化、ROAS、Campaign 表现 | 归因收入与花费需满足 USD 口径；AdventureWorks 扩展目前为模拟数据 |
| 退货 | 退货数量、原因、商品与市场暴露 | 退货关联 GMV 不等同于真实退款额或利润损失 |
| 物流 | 发货、承运商、时效、追踪事件和履约异常 | 物流事件保持独立粒度，不回写订单事实 |

## 一条可审计的数据链

```mermaid
flowchart LR
  A["CSV / XLSX / AdventureWorksDW"] --> B["预检与字段语义确认"]
  B --> C["版本化统一数据集"]
  C --> D["SQLite + 注册指标 + 受控 SQL"]
  D --> E["指标快照与数据质量"]
  E --> F["异常与经营诊断"]
  F --> G["建议、行动与证据"]
  G --> H["Dashboard / 报告 / Agent"]
```

核心约束：

- 原始文件只读，任何转换都生成规范化视图或新版本。
- 相同来源重复导入保持幂等；不同 `dataset_id` 不会混算。
- 不完整月份只展示，不参与月环比结论。
- 缺字段、汇率不完整、样本不足或证据不够时，结果会显式降级。
- “贡献”或“相关”不会被包装成已经证明的因果关系。
- SQL 是正式事实层，所有查询使用受控、参数化的命名 SQL；不提供任意 SQL 控制台。

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 20+
- Git（安装 AutoClean 6.6 的固定 Tag 时使用）

### 安装并启动

```powershell
git clone https://github.com/LiXuanyaun/cross-border-ecommerce-analysis.git
cd cross-border-ecommerce-analysis

python -m pip install -r requirements.txt
.\start.cmd
```

启动脚本会自动安装前端依赖、构建 React 应用、准备统一数据集，并在 `http://127.0.0.1:8000` 启动产品。默认的 `start.cmd` 使用 `private` 模式。

首次只想查看演示数据，也可以使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_web.ps1 `
  -Mode demo -Build -OpenBrowser
```

演示模式允许浏览和分析样例数据，但不允许上传文件或修改共享任务。私有模式会在本地保存任务、Agent 会话和工具事件；CC Switch 的 API Key 只进入后端进程内存，不返回浏览器，也不写入项目数据库和日志。没有 CC Switch 时，可参考 `.env.example` 配置 OpenAI 兼容模型。

### Docker

```powershell
docker build -t crossborder-ai .
docker run --rm -p 8000:8000 crossborder-ai
```

## 数据导入

### 普通订单数据

支持 CSV/XLSX 预览、字段映射、金额语义确认、币种转换、质量检查和版本化导入。最小可用字段为：

- 订单 ID
- 订单日期
- 订单金额

补充国家/区域、商品、客户、利润、数量和退货字段后，系统会解锁更多分析能力。导入流程会先生成预览，确认无 `FATAL` 问题后才在一个 SQLite 事务中提交；非法数据不会留下半成品。

### AdventureWorks 多业务数据

将 AdventureWorksDW 文件放入本地只读目录，再通过数据中心导入。系统会识别文件类型、字段、业务粒度、关联率和模拟数据标识：

- 订单适配为标准订单事实，保留 `SalesOrderNumber` 与 `SalesOrderLineNumber`。
- 广告、退货、物流写入独立事实表，不改变既有 `orders` 粒度。
- 文件哈希、导入批次、自然业务键和外键用于血缘、幂等和关联校验。
- 追加到已有 Web 数据集会创建带 `parent_dataset_id` 的新版本，父版本保持只读。

完整字段和校验规则见 [导入指南](docs/IMPORT_GUIDE.md)。

## AI 分析师

AI 分析师建立在确定性的分析事实之上，而不是替代指标层：

- 通过注册工具读取指标、异常、诊断、建议、证据和报告。
- 每次会话绑定明确的 `dataset_id`、`scope_id` 和分析范围。
- 支持计划、流式工具事件（SSE）和可查看的分析过程。
- Provider 不可用、输出为空或数字无法通过证据校验时，自动转为透明的确定性降级。
- Agent 不开放任意 SQL，不接触浏览器端 API Key。

## 输出与复盘

同一套指标、规则版本和证据编号可以导出为：

- `analysis_result.xlsx`
- `cross_border_analysis_report.md`
- `cross_border_analysis_report.docx`
- `analysis_manifest.json`

Excel 除业务明细外，还包含指标定义、指标快照、异常、诊断、建议、证据、数据质量、分析能力和数据改进计划。多业务数据集会额外输出广告、退货、物流和多业务证据工作表。

报告、Dashboard、任务和 Agent 共享同一 `scope_id`，因此可以从一个行动回到对应的指标、时期、数据质量和证据。

## 技术架构

```text
React + TypeScript
        |
FastAPI /api/v1
        |
Routes -> Services -> Presenters
        |
AnalysisService + Registered Metrics + Named SQL
        |
Versioned SQLite + ArtifactStore
        |
MetricSnapshot -> Anomaly -> Diagnosis -> Recommendation -> Evidence
        |
Dashboard / Reports / Work Items / Controlled Agent
```

技术栈：Python、AutoClean 6.6、pandas、SQLite、FastAPI、React 18、TypeScript、TanStack Query、ECharts、TailwindCSS、pytest、Vitest、Playwright 和 Docker。

主产品只有 React + FastAPI 一条链路。后端路由负责协议，服务和 Presenter 负责应用编排，`crossborder_analytics` 负责分析、存储和报告；前端只消费后端契约，不在组件内重新推断业务结论。

## 测试与开发

```powershell
# 后端
python -m pytest

# 前端
cd frontend
npm install
npm test
npm run build
```

SQLite 数据层和 100,000 行本地基准：

```powershell
python .\scripts\benchmark_sqlite.py
```

常用开发入口：

- OpenAPI Schema：`http://127.0.0.1:8000/openapi.json`
- 健康检查：`GET /api/v1/health`
- 导入预览：`POST /api/v1/imports/preview`
- 订单专题：`GET /api/v1/topics/{topic}`
- 多业务专题：`GET /api/v1/business/{advertising|returns|logistics}`

## 当前边界

这是一个本地单用户、试点级商业 MVP，当前有意保持边界清晰：

- 不提供多租户权限、多店铺实时 API 接入和趋势预测。
- 公开演示模式不调用真实模型；真实 Agent 能力优先在本地私有模式交付。
- AdventureWorks 的广告、退货和物流扩展是模拟数据，页面、报告和 Agent 都会持续披露这一点。
- 没有退款额、成本或其他必要字段时，不把退货关联 GMV 表述为真实损失。
- 不完整周期、缺失字段和低样本不会被静默补齐，也不会生成虚假的机会或行动项。

## 项目文档

- [架构说明](docs/ARCHITECTURE.md)：模块边界、数据流和工程约束
- [导入指南](docs/IMPORT_GUIDE.md)：普通订单和 AdventureWorks 导入流程
- [SQLite 数据层](docs/SQLITE_DATA_LAYER.md)：版本、事务、命名 SQL 和查询边界
- [多业务数据字典](docs/MULTI_BUSINESS_DATA_DICTIONARY.md)：广告、退货、物流事实模型
- [多业务指标与异常规则](docs/MULTI_BUSINESS_METRICS_AND_RULES.md)：指标口径、异常和证据要求
- [维护指南](docs/MAINTENANCE.md)：数据库、缓存和统一数据集维护
- [项目上下文](docs/PROJECT_CONTEXT.md)：产品目标、重要决策和当前状态

<p align="center">
  <sub>CrossBorder AI Analytics · 用证据把数据变成下一步行动</sub>
</p>
