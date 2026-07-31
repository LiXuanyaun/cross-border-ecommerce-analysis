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
