# GitHub CI Regression Repair - 2026-07-31

Status: Complete.

## Objective

修复 GitHub CI 的三个已知失败，同时保持“国家优先、区域回退”和统一数据集按当前分析范围选择有效市场维度的双重契约。

## Scope And Decisions

- 前端测试与生产构建先于包含浏览器回归的 Python 全量测试。
- S20 场景矩阵引用当前可执行的多文件字段漂移清洗测试。
- 普通数据仍优先使用 `country`；统一混合数据由当前分析范围确定市场维度，并将该维度显式传给 SQL 与 Presenter。

## Steps

1. 修复 CI 顺序和失效测试引用。
2. 恢复国家优先，并贯穿 active market dimension。
3. 运行前端测试/构建、目标 Python 测试、浏览器回归和全量 pytest。

## Acceptance And Verification

- 三个原始失败通过。
- 统一总览仍返回有效市场，而不是退化为单一“未标注国家”。
- `npm test`、`npm run build`、浏览器回归和 `python -m pytest -q` 通过。
- `npm test`: 5 files, 10 tests passed.
- `npm run build`: passed；仅保留已有 ECharts chunk size warning。
- 四个关键 Python 回归：4 passed。
- `python -m pytest -q`: passed；仅有现存 Starlette/httpx 弃用警告。

---

# Agent 真实接入可见性与降级修复 - 2026-07-31

Status: Complete.

## Objective

让真实 provider 的调用状态、模型回答是否被采用、以及 fallback 原因在 Agent 页面可见，同时保留数字证据校验和确定性降级，不把模型编造的经营数字展示给用户。

## Scope

- 后端 Agent run 增加模型调用状态事件和结果元数据。
- 数字校验使用规范化数值，避免 `808.5` 与 `808.50` 等格式差异造成误判。
- 前端显示 provider、模型状态、fallback 原因和本轮最终状态。
- 增加真实模型成功、空响应、输出校验失败和数值格式化回归测试。

## Acceptance

- 已配置 provider 时，运行记录明确显示模型调用开始、成功采用或 fallback。
- 未配置 provider 时，页面明确显示使用确定性分析，不再让用户误以为调用了模型。
- 模型输出包含未授权数字时仍被拒绝；合法的数字格式差异不会误拒绝。
- 现有 Agent、前端测试和生产构建通过。

## Verification

- `python -m pytest tests/test_api_state.py tests/test_api_contracts.py -q`: 18 passed.
- `npm test`: 5 files, 10 tests passed.
- `npm run build`: passed; existing large ECharts chunk warning remains non-blocking.
- `python -m compileall -q crossborder_api`: passed.
- Live `/api/v1/agent/status` confirmed CC Switch provider configuration without exposing credentials; the running process must be restarted to load this change.

## Market Dimension Regression Repair - 2026-07-31

Status: Complete.

The unified dataset has complete `region` coverage but only partial `country` coverage. A prior country-first change selected `country` for the whole dataset, while the latest complete month had no country values, collapsing the overview market chart into `未标注国家`. Market dimension resolution now selects the highest-coverage field and prefers country only on ties. Added a unified overview regression assertion and verified the result returns North, West, South, East and Central.

Verification:

- `python -m pytest tests/test_decision_workspace.py::test_country_is_one_dataset_grain_and_partial_missing_is_labeled tests/test_api.py::test_unified_overview_uses_active_market_dimension_and_quality_scope -q`: passed.
- Direct unified overview run: returned North, West, South, East and Central.
- The existing process on port 8000 has an older build fingerprint and must be restarted before the browser reflects this fix.

---

# Import Merge Workflow - 2026-07-31

Status: Complete.

## Objective

Allow a new compliant order file to be appended into an existing private Web dataset while preserving the parent version, lineage, quality checks and dashboard state.

## Decisions

- New import remains the default; merge is an explicit user choice.
- Merge targets only READY Web datasets. Unified/demo datasets are read-only.
- Merge is transactional and keeps the target `dataset_id`.
- Duplicate source records are idempotently skipped; conflicting duplicate `order_id` values are blocked for order-grain imports.

## Steps

- [x] Add backend merge contract and versioned append persistence.
- [x] Add import UI target selection and merged result state.
- [x] Add API regression tests for append, duplicate and rollback behavior.
- [x] Run focused backend and frontend verification, then update project memory.

## Acceptance

- User can choose “追加到现有数据集” during import.
- Successful merge creates a new child `dataset_id`, updates row count/period/lineage/capabilities, and keeps the parent version readable.
- Invalid/conflicting merge leaves the original dataset unchanged.
- Dashboard cache/catalog refreshes after merge.

## Verification

- `python -m pytest tests/test_api.py tests/test_api_contracts.py tests/test_api_state.py -q`: 48 passed.
- `npm test -- --run`: 10 passed.
- `npm run build`: passed.
- Private service health and catalog checked at `http://127.0.0.1:8031`; catalog exposes unified data plus Web imports.
- Browser DOM check confirmed the top dataset selector exposes both private and unified datasets.

## Follow-up: Adaptive Topic Trend

- [x] Use daily/weekly/monthly topic trend buckets based on the selected period.
- [x] Show an explicit no-comparison state when the dataset has no prior period.
- [x] Add a one-month imported-dataset regression test and rerun frontend/backend checks.

## Follow-up Verification

- `python -m pytest tests/test_api.py tests/test_api_contracts.py tests/test_api_state.py -q`
- `npm test -- --run`
- `npm run build`
- `python -m pytest tests/test_react_e2e.py::test_react_primary_pages_at_desktop_and_393px -q`

## Follow-up: Multi-business Upload Contract

- [x] Keep AdventureWorks/multi-business preview files from entering the autoclean order form.
- [x] Render their `row_count` and `field_preview` shape without a client crash.
- [x] Verify a real `fact_returns.csv` upload in the browser and add an API regression test.

## Follow-up: Unified Autoclean Upload Path

- [x] Route every Data Hub upload preview through the autoclean ecommerce contract.
- [x] Return a stable blocked preview for non-order files instead of switching contracts.
- [x] Restart the private service and verify `fact_returns.csv` is blocked with metadata and field mappings.

## Follow-up: Unified Overview Recovery

Status: Complete.

### Objective

Restore market performance, pending tasks and operating insights for the unified dataset without weakening explicit quality downgrades.

### Scope

- Resolve market dimension from the active data range and use the available geographic field.
- Evaluate quality and anomaly gates against the selected analysis range and the dataset's declared grain.
- Invalidate cached artifacts created with the previous quality policy.
- Add a unified overview regression test.

### Acceptance

- The unified dataset returns non-empty market rows for the 2024-06-01 to 2025-08-31 selection.
- The same overview returns pending tasks and operating insights when registered anomalies are detected.
- Existing empty/out-of-range behavior remains explicit.

### Verification

- Focused backend tests for unified overview and API contracts: passed.
- Frontend tests and production build: passed.
- `git diff --check` and status review: passed.

## Follow-up: Partial Batch Cleaning

- [x] Remove batch-level field-set blocking so autoclean evaluates each file independently.
- [x] Combine qualified files into one new dataset while preserving per-file lineage.
- [x] Persist qualified files and report failed files separately; explicit append remains opt-in.
