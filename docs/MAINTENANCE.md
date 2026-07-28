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

## Operational Notes

- Keep `database/`, `.cache/`, generated reports and local WAL files out of Git.
- Prefer archiving scopes before destructive cleanup.
- Do not add API routes that directly access `runtime._service`.
- Keep React as the primary interface; use Streamlit only for legacy comparison or internal debugging.
