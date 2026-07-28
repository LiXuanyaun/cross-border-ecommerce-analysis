# Import Guide

## Supported Files

The web import flow accepts CSV and Excel files. Excel imports can preview sheet names and commit a selected sheet.

The current public contract supports one batch of up to 20 files and blocks unsafe imports before writing business rows.

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

## Safety Rules

- Empty files and files above the size limit are rejected.
- Field-set mismatches in multi-file batches block import.
- Duplicate files are skipped with warnings.
- Order-grain imports require unique order IDs.
- Order-item imports require explicit amount semantics.
- Fatal contract issues return `BLOCKED` and do not write partial business rows.
