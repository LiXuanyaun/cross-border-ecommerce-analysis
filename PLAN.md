# CrossBorder AI Analytics v4.0 Plan

Status: Complete

## Objective

Complete the AdventureWorks-backed advertising, returns and logistics analysis loop without changing existing order-analysis behavior or public API contracts.

## Scope

- Import headerless pipe-delimited AdventureWorks order and dimension files into the existing normalized order model.
- Add independently-grained SQLite dimensions/facts, provenance, import batches, file hashes and idempotent business keys.
- Extend preview/import with file classification, field/grain preview, linkage quality, warnings/errors and simulated-data disclosure.
- Add registered multi-business metrics, anomaly rules, evidence and limitations for advertising, returns and logistics.
- Add FastAPI presenters/routes, React topic pages, reports and controlled Agent context.
- Add fixtures, regression coverage, documentation, version `4.0.0`, staged commits and tag.

## Key Decisions

- Keep the existing `orders` table and order analytics compatible; new grains live in separate tables.
- Treat SQL and registered metrics as the fact layer. React and Agent consumers only present backend conclusions.
- Preserve `dataset_id`, `scope_id`, period, currency, quality state and provenance through every output.
- Store synthetic extensions as simulated data and display a persistent warning in APIs, pages and reports.
- Use file SHA-256 plus table-specific business keys for idempotency; raw source files remain read-only and untracked.
- ROAS uses attributed USD revenue divided by USD spend. Return-linked GMV is not refund loss.

## Steps

- [x] Audit existing architecture, schemas, import formats and report/Agent contracts.
- [x] Phase 1: add v4 SQLite migrations, foreign keys, provenance/import tables and data access services.
- [x] Phase 2: add AdventureWorks adapter, multi-business classifiers/previews/importers and idempotency validation.
- [x] Phase 3: add registered metrics, evidence-backed rules, presenters and API contracts.
- [x] Phase 4: add three responsive React topic pages plus Excel/DOCX/manifest and Agent context sections.
- [x] Phase 5: add fixtures/tests/docs/version release, run all acceptance gates, create staged commits and tag.

## Acceptance Criteria

- All required dimensions/facts exist independently and retain provenance and raw linkage keys.
- Reimporting identical files does not increase row counts; invalid links and business constraints are reported explicitly.
- The German search-ad, Clothing size-return and GlobalPost Europe delay scenarios are detected with metrics, thresholds, evidence records and limitations.
- Existing order analysis, API paths and Dashboard remain compatible.
- Advertising, returns and logistics pages include KPI, trend, ranking, anomaly, causes, actions, filters and a persistent simulated-data label at desktop and 393px widths.
- Excel, DOCX, manifest and controlled Agent context use the same registered metrics/evidence as the API.
- Version metadata is `4.0.0`; documentation and data dictionary/rule definitions are current.

## Verification

- `python -m pytest`
- `npm test` in `frontend/`
- `npm run build` in `frontend/`
- React Playwright desktop and 393px E2E, including overflow and nonblank-chart checks
- `python scripts/benchmark_sqlite.py` with 100,000 rows under 15 seconds
- Render and inspect generated DOCX pages and visually inspect every exported Excel sheet

## Release Commits

1. Data model and migration
2. AdventureWorks and multi-business import
3. Analysis rules and API
4. Dashboard and reports
5. Tests, documentation and v4.0.0 release/tag
