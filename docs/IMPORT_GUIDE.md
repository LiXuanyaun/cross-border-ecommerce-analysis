# Import Guide

## Supported Files

The web import flow accepts CSV and Excel order files. v4 also accepts the AdventureWorksDW source adapter input (headerless, pipe-delimited) together with CSV dimension/fact extensions for campaign, carrier, return reason, advertising daily performance, attribution, returns, shipments and tracking events.

The web flow has no fixed file-count limit. Centralized capacity defaults to 100 MB per file and 1 GB per task through `CROSSBORDER_IMPORT_MAX_FILE_BYTES` and `CROSSBORDER_IMPORT_MAX_TASK_BYTES`; unsafe imports are blocked before business rows are written.

## AdventureWorks Multi-Business Import

1. Keep `data/AdventureWorksDW-data/` read-only. The adapter reads `FactInternetSales` and its product, category, customer, region, currency and exchange-rate dimensions.
2. Preview the extension directory. Confirm the detected file type, field sample, business grain, source/version, association rates and simulation warning.
3. Commit only when there are no `FATAL` validation issues. The importer writes the compatible order model first, then independent business tables in one SQLite transaction.
4. Reimporting the same source hash and business keys reports duplicates and does not increase rows.

The validation rejects unknown order/campaign/carrier/reason/shipment links, order attribution credit above 1, clicks above impressions, conversions above clicks, refunds above purchased quantities or line amounts, non-strict tracking time order, returns before delivery, non-cross-border customs events and non-USD advertising ROAS inputs.

## Required Fields

The minimum usable order dataset needs:

- order ID;
- order date;
- total amount.

Optional fields unlock richer analysis, including market, product, customer, profit and returns views.

## Import Steps

1. Upload files to `/api/v1/imports/preview`.
2. Review detected columns, suggested mappings, capability status and batch issues.
3. Confirm mapping, data grain, amount meaning and currency.
4. Commit through `/api/v1/imports`.
5. Use the returned `dataset_id` in overview, topics, reports and Agent analysis.

## Append To An Existing Web Dataset

The confirmation form can choose `追加到已有数据集`. The client sends the existing Web `dataset_id` as `target_dataset_id` to `/api/v1/imports`. The server validates grain, amount semantics, target currency and cross-batch order IDs, then creates a new versioned child dataset with `parent_dataset_id` and the complete source-file lineage. The parent remains read-only so prior reports and scopes do not drift. Repeating an already imported source file is idempotent; a new file containing an existing order ID is blocked as a whole batch.

## Safety Rules

- Empty files and files above the size limit are rejected.
- Field-set mismatches in multi-file batches block import.
- Duplicate files are skipped with warnings.
- Order-grain imports require unique order IDs.
- Order-item imports require explicit amount semantics.
- Fatal contract issues return `BLOCKED` and do not write partial business rows.
- Every business row stores `dataset_id`, `import_batch_id`, `data_origin`, `scenario_id`, `generator_version` and its source business key.
- `synthetic_extension` must stay visibly labelled as simulated data in preview, API, Dashboard and reports.
