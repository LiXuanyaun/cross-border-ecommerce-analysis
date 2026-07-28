# Maintenance Guide

## Storage Maintenance

Maintenance APIs are grouped under route modules and use service interfaces rather than private runtime storage fields.

Available operations:

- `GET /api/v1/scopes/capacity`: inspect database size, scope status counts and cleanup recommendations.
- `POST /api/v1/scopes/{scope_id}/archive`: archive a completed analysis scope.
- `DELETE /api/v1/scopes`: clean retained scopes, topic cache, low-value entity assessments and duplicate datasets.
- `POST /api/v1/datasets/{dataset_id}/archive`: archive imported datasets without deleting historical order rows.

Demo datasets are read-only and cannot be archived.

## Verification

Before architecture or storage changes, run:

```powershell
python -m pytest
cd frontend
npm test
npm run build
cd ..
python scripts\benchmark_sqlite.py --rows 100000
```

The 100,000-row benchmark should remain under the configured threshold and must not show an obvious regression.

For v4 releases also run the browser E2E against `/business/advertising`, `/business/returns` and `/business/logistics` at desktop and 393px widths. Verify no horizontal overflow, nonblank charts, the persistent simulated-data label and the three registered synthetic anomaly scenarios.

## Multi-Business Operations

- Do not edit or delete `data/AdventureWorksDW-data/`; source files are read-only input.
- Inspect `import_batches` and `import_files` before diagnosing duplicate imports. File hashes and natural business keys are the idempotency record.
- Use `PRAGMA foreign_key_check` after migration/import failures. Do not repair invalid business facts by bypassing foreign keys.
- Retain `dataset_id`, source/version and simulation disclosure in incident exports. A missing source, weak association rate or incomplete period must downgrade the conclusion.
- The controlled Agent may consume only registered multi-business metrics, anomalies and evidence. Keep arbitrary SQL out of prompts, tools and browser payloads.

## Operational Notes

- Keep `database/`, `.cache/`, generated reports and local WAL files out of Git.
- Prefer archiving scopes before destructive cleanup.
- Do not add API routes that directly access `runtime._service`.
- Keep React as the primary interface; use Streamlit only for legacy comparison or internal debugging.
