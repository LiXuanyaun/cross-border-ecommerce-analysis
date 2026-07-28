# Project Context

## 1. Project Mission

项目为什么存在？CrossBorder AI Analytics 将跨境电商订单数据转化为可追溯、可复算、可执行的经营判断，而不只是展示图表或生成聊天回答。

解决什么问题？统一数据质量、指标口径、周期比较、异常、证据、建议、任务和报告，帮助运营人员完成经营复盘与问题处置。

目标用户是谁？跨境电商运营负责人、经营分析人员和管理者；当前定位是本地单用户、试点级商业 MVP。

---

## 2. Product Goal

当前产品目标：在 `4.0.0` 架构基础上完成 AdventureWorks 订单、广告、退款和物流的多业务分析闭环，使页面、报告、任务和 Agent 始终共享同一数据范围与证据链。

核心价值：原始数据只读；结论有正式口径和证据；字段、质量或周期不足时明确降级；建议可以进入任务和复盘。

当前阶段：React/FastAPI 和 SQLite 主链路已可用，正在收敛性能、容量、前端维护性、Agent 真实性和真实用户验证。

---

## 3. Current Status

已经完成：
- CSV/XLSX 预检与导入、AdventureWorks 适配器、版本化 SQLite、指标/异常/诊断/建议/证据链、四页 React 产品、报告与任务闭环。
- 广告、退款和物流已使用独立业务事实表、导入批次/哈希和注册规则；API、专题页面、报告与 Agent 共用指标和证据。
- FastAPI 已拆分路由、服务、Presenter 和 Agent 上下文；Streamlit `app.py` 仅保留兼容与口径对照。
- Agent 已有注册工具、计划、SSE 工具事件和确定性降级；私有模式支持 provider 与本地状态持久化。

正在进行：
- 重跑完整回归与 10 万行性能/容量验收，建立 Agent 评测与 3-5 人试点。

未来计划：
- 接入成本、库存、活动、渠道、店铺和真实物流数据，再评估更自主的 Agent 循环。

---

## 4. Technical Architecture

技术栈：Python 3.10+、AutoClean 6.6、pandas、SQLite、FastAPI、React 18、TypeScript、TanStack Query、ECharts、TailwindCSS、pytest、Vitest、Playwright 和 Docker。

模块关系：`frontend` -> `crossborder_api` routes -> services/presenters -> `crossborder_analytics` -> SQLite/ArtifactStore；`AnalyticsRuntime` 只作为兼容 facade。

数据流：CSV/XLSX 或 AdventureWorksDW -> 预检和标准化 -> 版本化订单/多业务事实数据集 -> 命名 SQL/注册指标 -> 异常/诊断/建议/证据 -> 页面、任务、报告和受控 Agent。

关键组件：`crossborder_analytics/` 负责分析核心、领域对象、存储和报告；`crossborder_api/` 负责 API、应用服务、任务和 Agent；`frontend/src/features/` 负责主页面；`data/ecommerce_sales_34500.csv` 是默认样例，`data/AdventureWorksDW-data/` 是只读多业务订单源。

---

## 5. Important Decisions

Decision: React + FastAPI 是主产品，Streamlit 仅用于兼容和内部核对。
Reason: 主界面需要稳定 Web 交互，同时保留历史口径验证能力。
Date: 2026-07-28

Decision: 原始数据只读；SQL 和注册指标是正式事实层；不开放任意 SQL。
Reason: 保证事实、口径、权限和证据血缘可审计。
Date: v3.1

Decision: `dataset_id`、`scope_id`、周期、币种和质量状态贯穿页面、报告、任务和 Agent；Agent 先使用受控工具与透明降级。
Reason: 防止混算并保证结论可复算；先验证证据边界，再扩大模型自主性。
Date: 2026-07-28

Decision: AdventureWorks 订单保持兼容订单事实；广告、退款和物流使用独立事实表，并由导入批次、文件哈希、自然业务键和外键保证血缘、隔离与幂等。
Reason: 不混淆业务粒度，且可以在不破坏原有订单分析和 API 契约的前提下接入扩展数据。
Date: 2026-07-28

Decision: AdventureWorks 扩展数据在当前版本是模拟数据，所有页面、报告、API 和 Agent 上下文必须持续披露来源和限制。
Reason: 保护经营判断，避免将演示验证场景误报为真实运营事实或因果。
Date: 2026-07-28

---

## 6. AI Development Rules

修改代码时：遵循根目录 `AGENTS.md`；复杂任务必须先更新 `PLAN.md`，再进入实现。

必须：先定位后读取；保持真实数据、统一 scope、完整可比周期和 API 契约；运行与风险匹配的测试并说明未运行项。

不要：不用 Mock、随机数、Placeholder 或前端猜测制造业务结论；不覆盖用户改动；不把旧评分、旧 PRD 或历史测试结果写成当前状态。

测试要求：后端 pytest；前端 Vitest + build；布局用浏览器回归；数据层变更运行 10 万行基准。

文档要求：稳定决策更新本文件；每日进展写入 `docs/founder-log/`；安装和命令写入 README。

---

## 7. Known Risks

当前风险：分支为 `codex/architecture-refactor-v3.1.1`；未跟踪的 `data/AdventureWorksDW-data/` 用途未知，禁止自动清理或纳入默认场景。

技术风险：前端 feature 文件仍偏大；SQLite 快照/缓存会增长；性能受环境和数据形态影响；React 与 Streamlit 双链路需防回归。

产品风险：Agent 仍是受控工具链加可选模型；当前广告、退款和物流为模拟扩展数据，且仍缺少成本、库存、活动和真实多店铺数据，不能完成经营因果归因。

商业风险：持续使用、任务采纳、实际收益、接入成本和付费意愿尚未由真实试点证明。
