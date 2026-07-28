# Project Context

## 1. Project Mission

项目为什么存在？

CrossBorder AI Analytics 要把跨境电商订单数据转化为可追溯、可复算、可行动的经营判断。它不是普通 BI 图表项目，也不是只包装回答的聊天机器人，而是面向运营复盘、异常定位、证据核查和行动闭环的本地经营分析产品。

解决什么问题？

跨境电商团队常有订单数据，但缺少统一指标口径、可信周期比较、异常解释、证据链和可跟进任务。系统负责数据理解、质量评估、指标计算、异常诊断、建议生成、报告导出和 Agent 辅助分析；证据不足时必须降级或停止，不用 Mock、随机数、Placeholder 或模板文案补齐结论。

目标用户是谁？

主要用户是跨境电商运营负责人、经营分析人员和管理者；他们需要做周报、月报、专题复盘、异常处置和试点验证。当前产品面向本地单用户、创业 Demo、试点级商业 MVP 和未来受控 AI Agent 场景。

---

## 2. Product Goal

当前产品目标：

把项目从“能跑的分析 Demo”推进为可试点的证据型经营分析平台：React + FastAPI 是主产品界面，SQLite 是本地事实层，Streamlit 保留用于历史兼容和业务口径对照。

核心价值：

原始数据只读；指标口径公开；页面、报告、任务和 AI 使用一致 `scope_id`；所有判断绑定真实数据、周期、公式、阈值和证据；缺少成本、退款、广告、库存、活动、物流等变量时明确说明不可回答边界。

当前阶段：

项目已经越过上一轮 76 分评估基线，进入更接近试点产品的阶段；但当前最终评分需要重新完整评测，不能沿用旧分数。最新重点是性能进入硬门槛、数据库容量治理、`runtime.py` 继续拆分、真实商业字段接入，以及 Agent 从受控工具观察升级为更完整 planner-executor。

---

## 3. Current Status

已经完成：

- CSV/XLSX 读取、订单字段契约、原始数据哈希、非破坏性分析视图、历史汇率、数据质量评估和 SQLite 版本化幂等入库。
- 经营总览、专题分析、数据中心和 AI 分析师四页 React 产品界面；FastAPI 提供统一数据、报告、任务和 Agent 接口。
- 指标、异常、诊断、建议、证据、洞察、机会、任务、报告和 manifest 的持久化链路。
- 市场、商品、客户、利润和退货五个专题按“趋势对比、Top5 异常、关键发现、驱动因素、数据证据、建议动作”呈现。
- 日期、市场、品类筛选进入稳定 `scope_id`；搜索、分页和每页数量只影响明细，不改变 KPI、趋势、证据和报告口径。
- 任务状态固定为 `TODO`、`IN_PROGRESS`、`COMPLETED`、`REVIEWED`、`CLOSED`，并记录负责人、截止日期、处理结果、复盘结论和关闭信息。
- DataHub 已有指标目录、规则目录、容量、归档和清理建议，不再只是展示壳。
- AI 分析师已接入受控 Tool Registry、会话、SSE 事件、执行计划、工具观察、证据绑定和 CC Switch 私有模式导入入口。
- AI 分析师页面已修复“像假逻辑”的展示问题：右侧结果区现在以本轮问题、本轮回答、工具轨迹和证据摘要为第一屏；对话栏固定高度并内部滚动。
- 前端完成路由级懒加载、ECharts 按需注册和 chunk 拆分；前端 build、Vitest 和浏览器回归已通过。

正在进行：

- 重新完整评估当前版本，不再沿用上一轮 76 分结论。
- 将 100k SQLite 基准压进 15 秒硬门槛，并继续治理 `metric_snapshots`、`entity_assessments`、`topic_detail_cache` 等高增长表。
- 继续拆分 `crossborder_api/runtime.py`，降低 Web 投影层维护风险。
- 验证 Agent 回答是否真正随问题、历史对话、scope 和工具结果变化，而不是过度依赖确定性兜底。
- 准备 3-5 名真实运营人员的试点验证，并用真实问题校准规则、阈值和建议边界。

未来计划：

- 接入成本、退款、广告、库存、活动、渠道、物流、多店铺等关键经营变量。
- 建立更硬的 E2E、性能门禁、容量门禁和 Agent 评测集。
- 完成真正的 planner-executor Agent 工具链：规划、选择工具、试错、反思、降级和评测。
- 用真实用户试点结果校准商业价值、任务完成率、建议收益和付费意愿。

---

## 4. Technical Architecture

技术栈：

Python 3.10+、pandas、NumPy、SQLite、FastAPI、Uvicorn、httpx、React 18、TypeScript、React Router、TanStack Query、ECharts、Radix UI、TailwindCSS、Vitest、pytest 和 Playwright。Streamlit、Plotly 与 Matplotlib 继续支撑兼容界面和历史报告。

模块关系：

AutoClean 提供读取、契约、质量、上下文和基础存储能力；`crossborder_analytics` 提供跨境电商语义、指标、规则、诊断、建议、证据、洞察、机会和报告；`crossborder_api` 将同一分析服务封装为 Web API、状态、报告、任务和 Agent 工具；`frontend` 消费稳定 DTO 构建产品界面；`app.py` 是 Streamlit 兼容入口。

数据流：

只读原始文件 -> AutoClean 规范化分析视图 -> SQLite 与受控 SQL -> MetricSnapshot -> Anomaly -> DiagnosisResult -> Recommendation -> EvidenceBundle -> Insight / Opportunity / ActionItem -> FastAPI -> React 页面、任务、报告和 Agent。前端不自行猜测结论，只格式化后端返回的结构化判断。

关键组件：

- `crossborder_analytics/service.py`：分析上下文、筛选、传统模块与可信分析链路编排。
- `crossborder_analytics/database.py` 与 `crossborder_analytics/sql/`：版本化订单、命名参数查询和事实来源。
- `metrics.py`、`anomalies.py`、`diagnosis.py`、`recommendations_v2.py`、`evidence.py`、`insights.py`：确定性分析引擎。
- `decision.py`、`decision_brief.py`、`opportunities.py`：经营判断、决策简报和增长机会。
- `phase2_models.py`、`phase2_catalogs.py`、`phase2_storage.py`：领域契约、规则目录、派生对象与任务状态。
- `crossborder_api/runtime.py`：Overview、Topic、DataHub 和 Agent Context 的 Web 数据适配层；仍偏大，是后续拆分重点。
- `crossborder_api/task_lifecycle.py`、`report_runtime.py`、`agent_tools.py`、`telemetry.py`：任务状态校验、同 scope 报告导出、受控工具注册表和结构化 API 日志。
- `crossborder_api/agent.py`：Agent 会话、模型 provider、CC Switch 导入、SSE 运行事件、确定性兜底和回答契约。
- `frontend/src/pages/OverviewPage.tsx`：经营总览；`AnalyticsPage.tsx`：五主题分析；`DataHubPage.tsx`：数据中心；`AiAnalystPage.tsx`：AI 分析师。

---

## 5. Important Decisions

Decision: 原始业务数据始终只读，标准化、类型转换、汉化和币种换算只生成分析或展示副本。

Reason: 商业分析必须可追溯，页面和报告不能静默改变源事实。

Date: 2026-07-16

Decision: SQL 是正式事实来源；Python 负责业务推导；只开放注册指标和参数化查询，不向页面或 Agent 开放任意 SQL。

Reason: 先稳定数据版本、查询口径和证据血缘，避免指标漂移与权限绕过。

Date: 2026-07-19

Decision: 不完整周期不参与环比、异常优先级和确定性经营判断；比较必须使用页面明确展示的完整、等长周期。

Reason: 未完成月份与完整基期不可公平比较，会制造趋势断崖和假异常。

Date: 2026-07-21

Decision: 分析状态与人工任务状态分离；任务完成、驳回或等待补数不得改写历史异常和诊断事实。

Reason: 分析事实需要可审计，人工处置又必须能独立流转和复盘。

Date: 2026-07-21

Decision: 专题分析采用决策优先的信息板；先呈现趋势、异常、发现、驱动、证据和动作，再提供构成、排行和明细下钻。

Reason: 运营人员首先需要判断是否行动，通用 KPI 加独立 AI 侧栏会打断经营阅读顺序。

Date: 2026-07-21

Decision: AI 分析师页面必须以本轮问答、工具轨迹和证据为中心，KPI 和趋势只是上下文。

Reason: 对话型产品的信任来自“我的问题改变了系统输出”；固定仪表盘会让真实后端能力看起来像假逻辑。

Date: 2026-07-22

Decision: 不再把上一轮 76 分评估写成当前分数；当前状态需要重新完整评测。

Reason: Agent 页面、私有模式路径、前端回归和产品体验已发生新变化，旧分数只能作为历史基线。

Date: 2026-07-22

---

## 6. AI Development Rules

修改代码时：

先读取用户指定阶段、现有契约、真实数据流和最近 founder log。仓库有大量未提交改动，任何修改都必须保护用户已有工作，不要重置、清理或顺手重构无关模块。

必须：

- 使用中文业务语言；缩写首次出现时说明含义；避免空泛“AI 洞察”。
- 所有 KPI、趋势、异常、机会、证据和动作来自真实筛选后数据；展示周期、比较周期、公式、阈值或判断依据。
- 保持 `scope_id` 在页面、报告、任务和 AI 中一致；scope 不一致时拒绝导出或明确降级。
- 使用完整可比较周期；数据不足时明确降级，不回退为看似确定的结论。
- 区分数学贡献、相关关系和已验证原因；缺少广告、库存、活动、价格等数据时只提出核查方向。
- Agent 页面必须展示本轮问题、回答、工具状态、证据和限制；模型未配置或失败时要让用户看见降级原因。
- 前端布局要限制高度和滚动区域，尤其是 AI 对话、报告预览、工具轨迹和长回答。
- 所有“查看、详情、导出、报告、筛选、分页、导入”入口实现真实交互，并让按钮文字与实际行为一致。

不要：

- 不要使用 Mock、随机数据、Placeholder、可见 TODO 或重复模板文案补齐页面。
- 不要让前端根据展示数据临时猜异常、原因和建议。
- 不要把退货关联 GMV 写成真实退款损失，不要把贡献写成确定因果。
- 不要把旧评分当成当前评分；涉及评分必须说明评测时间、测试结果和未过门槛。
- 不要在性能、容量、真实导入、Agent 真实性和试点验证收口前继续堆装饰性智能能力。

测试要求：

- 后端共享口径改动运行 `python -m pytest` 或最小相关 pytest；性能相关改动运行 `scripts/benchmark_sqlite.py`。
- 前端改动至少运行 `npm run build` 和 `npm run test -- --run`；关键布局和交互改动运行 Playwright 浏览器回归。
- 页面在桌面和 393px 移动视口检查水平溢出、文字裁切、内部滚动、图表非空和按钮语义。
- Agent 改动需要验证 demo 模式、private 模式、CC Switch 导入、模型失败降级和 SSE 工具事件显示。

文档要求：

- 稳定产品状态、架构、规则和决策更新 `docs/PROJECT_CONTEXT.md`。
- 每日推进、阻碍和 Tomorrow Top 3 写入 `docs/founder-log/YYYY-MM-DD.md`。
- 发布或重要验收时同步 README、OpenAPI 类型、测试结果、性能结果和迁移说明。

---

## 7. Known Risks

当前风险：

工作区包含大量跨阶段、未提交或未跟踪改动，且 React/FastAPI 新产品与旧 Streamlit 兼容链路并存。未来操作必须保留现状，按产品边界拆分提交，不能用清理命令覆盖用户工作。

技术风险：

`runtime.py` 仍偏大；SQLite 数据库体积和快照/缓存增长压力仍未完全解决；100k 基准上一次仍高于 15 秒门槛，需重新跑最新版本确认；GitHub Actions 已定义 CI、性能门禁和 Docker smoke test，但还需要持续验证远端环境稳定性。

产品风险：

AI 分析师已有受控工具和可见轨迹，但还不是成熟 planner-executor Agent；如果模型未配置或模型调用失败，确定性兜底仍可能显得模板化。真实运营问题、追问、多轮上下文和工具选择需要评测集验证。

商业风险：

当前演示数据缺少成本、退款、广告、库存、活动、退货原因、物流节点、渠道和店铺等关键变量，限制商业归因深度。真实团队的持续使用、任务完成率、建议收益、付费意愿和数据接入成本仍未知。
