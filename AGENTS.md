# Repository Instructions

## Context Budget

- Define the decision to make and the smallest likely file set before reading. Start with metadata (`git status`, `git log`, `git diff --stat`, file outlines) rather than file contents.
- Read `docs/PROJECT_CONTEXT.md` only when product intent, architecture or business rules are relevant.
- Use jcodemunch symbol/index tools when available; otherwise use `rg` and focused line reads.
- Before a raw file read, check its size. For files over 300 lines, retrieve an outline, symbol or search hits first, then read windows of at most 120 lines. Never combine multiple large raw file reads in one command.
- Keep exploratory command output below 120 lines or roughly 12 KB. Use result limits, file globs and narrow patterns. If output is truncated, discard it and rerun a narrower query instead of reasoning from the partial dump.
- Retrieve PRDs, audits, founder logs and history only when the task specifically needs them. Never scan a full PRD merely to establish current implementation state.
- Do not inspect `data/`, `notebook/`, `dist/`, `outputs/`, `.cache/`, databases or generated files unless required.
- Stop discovery when the decision is supported by one current authoritative source and one verification source; expand only for conflicts, high-risk changes or missing evidence.
- Summarize research into `PLAN.md` for complex work, then implement from that plan. Do not carry exploratory dumps, dead ends or repeated evidence into implementation.
- Summarize findings; do not paste full files, full diffs or unchanged context.

## Low-Token Routines

- Simple task: locate -> read the target hunk -> edit -> run one targeted verification. Do not load project history or architecture unless the change depends on it.
- Daily review/project memory: start with today's `git log`, `git status`, diff stats, the current daily log and `docs/PROJECT_CONTEXT.md`. Read `PLAN.md` or `CHANGELOG.md` only when today's commits need interpretation; read README/PRDs only if changed or contradictory.
- For documentation-only work, reuse current same-day test/CI evidence and state what was not rerun. Rerun suites only when code changed after that evidence, the claim is uncertain, or the user requests live verification.
- Run long checks separately with realistic timeouts. Poll running work at roughly 30-second intervals and never repeat a successful check because another parallel check timed out.
- Final verification defaults to `git diff --check`, `git diff --stat`, `git status --short` and focused key-line checks. Print a full diff only for review tasks or when needed to diagnose a defect.
- If a user gives a token budget, treat it as a hard envelope: reserve most of it for implementation and verification, and stop optional discovery before consuming the reserve.

## Task Workflow

Simple, isolated fixes may follow: locate -> edit -> targeted verification.

A task is complex when it crosses modules, changes an API or data contract, affects database/performance behavior, changes a major user workflow, or is expected to touch more than three files.

For every complex task, before implementation:

1. Create or refresh root `PLAN.md`.
2. Record objective, scope, key decisions, ordered steps, acceptance criteria and verification.
3. Resolve research into the plan; do not carry large exploratory output into implementation.
4. Update plan status while working and mark it complete only after verification.

Keep `PLAN.md` concise and replace stale task details when the next complex task begins.

## Product Invariants

- Raw business files are read-only; transformations create normalized views or versioned artifacts.
- SQL and registered metrics are the formal fact layer; UI and Agent code must not invent business conclusions.
- Preserve `dataset_id`, `scope_id`, period, currency and quality state across pages, reports, tasks and Agent runs.
- Incomplete periods, missing fields, weak quality or insufficient evidence must produce an explicit downgrade.
- Do not present contribution or correlation as proven causality; return-linked GMV is not refund loss.
- Agent access is limited to registered tools and parameterized queries; never expose arbitrary SQL.

## Architecture Boundaries

- React + FastAPI is the primary product; Streamlit `app.py` is compatibility and internal comparison only.
- FastAPI routes call services/presenters and must not access `runtime._service` directly.
- New backend logic belongs in explicit services, presenters or `crossborder_analytics`, not in the runtime facade.
- Frontend conclusions come from backend contracts; frontend code handles presentation and interaction.

## Verification

- Backend: run the affected pytest subset; use `python -m pytest` for shared contracts.
- Frontend: run `npm test` and `npm run build`; add browser regression for layout or workflow changes.
- Database/performance: run `python scripts/benchmark_sqlite.py` when relevant.
- Agent: cover demo/private behavior, provider failure, deterministic downgrade and SSE events.
- State any verification not run.

## Safety And Documentation

- Preserve user changes and untracked data; do not reset, clean, delete or commit unrelated files.
- Stable architecture and decisions update `docs/PROJECT_CONTEXT.md`.
- Daily progress belongs in `docs/founder-log/YYYY-MM-DD.md`.
- Setup details belong in `README.md`; do not duplicate them here.
