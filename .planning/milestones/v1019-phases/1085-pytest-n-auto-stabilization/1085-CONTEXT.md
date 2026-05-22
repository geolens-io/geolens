# Phase 1085: pytest -n auto Stabilization - Context

**Gathered:** 2026-05-22
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

`pytest -n auto` completes a 16-worker xdist run against the backend test suite without triggering a Postgres recovery cascade; the chosen fix is evidence-driven from a committed spike doc.

This is REQ TD-10. The symptom is well-known from v1017/v1018 audits: when xdist spawns 16 workers (default on a 16-core macOS dev host), each worker opens its own asyncpg pool against the test-DB family, and the fan-out can exceed Postgres `max_connections`, triggering a recovery cycle that cascades across worker test-DBs. The v1018 audit flagged it as an "environmental cap deferred per user decision."

</domain>

<decisions>
## Implementation Decisions

### Pre-locked decisions from REQUIREMENTS.md / user direction:
- **Spike-first**: Plan 1085-01 must commit `.planning/audits/PYTEST-XDIST-SPIKE-v1019.md` BEFORE any fix lands. The spike doc records measurement methodology, observed numbers, chosen fix shape, and rationale.
- **Three fix shape options** (planner picks ONE based on spike evidence):
  - (a) per-worker pool sizing in `backend/tests/conftest.py` — scale asyncpg pool min/max per `PYTEST_XDIST_WORKER`
  - (b) docker-compose / postgres-test container `max_connections` bump
  - (c) Cap `-n` at 4 or 8 in Makefile / CI invocation
- **Sequential mode must still pass**: the fix must not break `uv run pytest backend/` (sequential, no xdist).

### Plan structure:
- Plan 1085-01: SPIKE — measure max_connections, per-worker concurrent connection count, decide fix shape
- Plan 1085-02: IMPLEMENT — apply chosen fix from Plan 01 + regression test + verification run

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be gathered during plan-phase research and during the spike. Expected touch points:
- `backend/tests/conftest.py` — already refactored in v1017 Phase 1075-01 for per-worker test-DB isolation via `PYTEST_XDIST_WORKER`; pool sizing lives here if shape (a) chosen
- `docker-compose.yml` or `docker-compose.test.yml` — `postgres-test` service container if shape (b) chosen
- `Makefile` — test target if shape (c) chosen
- `pyproject.toml` — pytest config if `-n` default needs to live in addopts

v1017 Phase 1075 established the per-worker test-DB isolation pattern (eliminated 1363 `InvalidCatalogNameError`). The asyncpg pool fan-out is a separate dimension — each worker has its own DB but still opens its own pool of N connections.

</code_context>

<specifics>
## Specific Ideas

**Plan 1085-01 spike scope:**
- Capture `SHOW max_connections;` against the running `postgres-test` container
- Capture per-worker concurrent connection count via `pg_stat_activity` snapshot during a `pytest -n auto` run (likely needs to be sampled mid-run)
- Decide fix shape: pool sizing (a) is the lightest backend touch, max_connections bump (b) requires a docker rebuild, cap `-n` (c) is the simplest but masks the underlying contention
- Recommendation lean: pool sizing (a) — keeps `-n auto` reliable, scales naturally per host, doesn't depend on container or Makefile state

**Plan 1085-02 implement scope:**
- Apply chosen fix at the right surface
- Add a regression test or doc-pin that ties pool sizing (or whichever knob) to expected behavior
- Run `pytest -n auto backend/` end-to-end against the rebuilt stack — must complete green with zero asyncpg recovery cascade errors
- Run sequential `uv run pytest backend/` — must still pass (must_have from REQUIREMENTS.md)

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped. All TD-10 scope is fixed by REQUIREMENTS.md.

</deferred>
