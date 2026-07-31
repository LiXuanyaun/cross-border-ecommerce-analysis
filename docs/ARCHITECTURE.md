# CrossBorder AI Analytics Architecture

## Boundary

React + FastAPI is the single product interface. Historical calculations are protected by domain tests, API contracts and report regressions instead of a second UI runtime.

The public API, metric definitions, anomaly rules, evidence relationships, SQLite schema and report outputs are treated as stable contracts. Architecture changes must preserve those contracts unless a release explicitly says otherwise.

## Backend Layers

```text
FastAPI app
  -> route modules
  -> app_state runtime/agent envelope
  -> AnalyticsRuntime compatibility facade
  -> application services and presenters
  -> crossborder_analytics analysis core
  -> SQLite order facts, multi-business facts and artifact store
```

`crossborder_api/main.py` owns application assembly, middleware, route registration and SPA fallback only.

Route modules:

- `routes/core.py`: health and bootstrap.
- `routes/analytics.py`: overview, topic payloads and topic CSV export.
- `routes/datasets.py`: dataset listing, detail and archive.
- `routes/imports.py`: import preview and committed import.
- `routes/maintenance.py`: work items and scope storage maintenance.
- `routes/agent.py`: provider status, sessions, runs and events.
- `routes/reports.py`: report downloads.
- `routes/business.py`: advertising, returns and logistics topic payloads.

Application services:

- `DatasetService`: demo/imported dataset lookup, context loading, archive and import coordination.
- `AnalysisQueryService`: cached analysis execution and filter-to-request conversion.
- `WorkItemService`: private-mode work item persistence and validation.
- `AgentContextBuilder`: controlled Agent context, plan, evidence trace and tool observations.
- `OverviewPresenter` and `TopicPresenter`: API-facing page payload assembly.
- `MultiBusinessPresenter`: filters and presents registered multi-business metrics, evidence and limitations.

`AnalyticsRuntime` remains the compatibility facade for existing callers. New code should prefer explicit services or presenters instead of adding more processing to `runtime.py`.

## Data Flow

1. Files are previewed through AutoClean import contracts.
2. AdventureWorks adapter imports headerless pipe-delimited order sources into the compatible order store; extensions are previewed, validated and persisted in independent SQLite facts.
3. Analysis runs use registered metrics, anomaly rules, diagnosis, recommendations and evidence bundles. Business-topic queries use parameterized, registered SQL only.
4. Presenters convert stable artifacts into API payloads for React.
5. Reports and Agent answers reuse the same scope and evidence chain.

## Invariants

- Existing API paths stay stable.
- `dataset_id` and `scope_id` are preserved across overview, topics, reports and Agent context.
- Metrics and anomaly rules have a single source of truth in `crossborder_analytics`.
- Route modules must not access `runtime._service`; storage operations go through services.
- SQLite databases remain compatible across the v3.1 architecture refactor.
- v4 does not put campaign, refund, shipment or tracking grain into `orders`; each business row carries `dataset_id`, `import_batch_id`, origin, scenario, generator version and raw linkage keys.
- Simulated extensions are disclosed in API, React, reports and Agent context. The Agent receives registered metrics/evidence only and cannot issue arbitrary SQL.
