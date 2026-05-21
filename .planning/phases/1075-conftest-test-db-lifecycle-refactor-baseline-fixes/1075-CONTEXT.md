# Phase 1075: Conftest Test-DB Lifecycle Refactor + Baseline Fixes - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via `workflow.skip_discuss`)

<domain>
## Phase Boundary

Restore trustworthy pytest signal — every downstream phase must be able to detect test regressions immediately. Two requirements in this phase:

- **TI-01 (Conftest test-DB lifecycle refactor):** Eliminate the **1363 `asyncpg.exceptions.InvalidCatalogNameError` errors** observed in v1016 Phase 1074 full-suite run. Per-test database creation/teardown must succeed reliably across the entire `backend/tests/` tree under both `pytest -x` (sequential) and `pytest -n auto` (parallel).
- **TI-02 (Fix 11 v1015 baseline pytest failures):** `test_defer_orphan_guard.py` ×3, `test_ingest.py` ×3, `test_maps_style_json.py` ×5. Each failure must be either fixed at root cause (production code or test logic) or skipped with `pytest.mark.skip(reason=...)` linked to a tracked GitHub issue.

**Out of scope (deferred to v1018 or beyond):**
- Conftest hardening beyond `InvalidCatalogNameError` (e.g., richer fixture isolation, parametrized DB scenarios)
- New CI workflows (Phase 1078 covers CI alembic clean-DB)
- Production code refactors unrelated to the 11 failures
- Test parallelism beyond restoring `-n auto` correctness

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices at Claude's discretion — discuss skipped per user setting. Use ROADMAP success criteria, REQUIREMENTS.md TI-01/TI-02 detail, and codebase conventions.

### Known Defaults (from REQUIREMENTS.md + project memory)

- **Test DB pattern:** v1015 introduced per-test database creation. The `InvalidCatalogNameError` suggests tests are trying to connect to a DB that was either never created or was dropped before the test ran. Likely root cause: race condition in conftest fixture ordering, or async teardown running before all sessions close.
- **Skip-vs-fix policy:** Prefer root-cause fix. Only skip when (a) failure is environmental (e.g., requires container Postgres that isn't available locally) or (b) test is testing v1015 transitional code already superseded. Each skip must point to a GitHub issue.
- **Parallel safety:** Tests that mutate shared state (e.g., the `gid` sequence, global filesystem dirs) must scope mutations per-DB or per-worker-id (`pytest-xdist` provides `worker_id` fixture).
- **Verification:** Phase 1075 close requires `uv run pytest backend/tests/` with `-x` exits 0 AND `-n auto` exits 0 (or with documented skips only).

### Investigation order (planner discretion)

1. Read current `conftest.py` (backend root + `backend/tests/conftest.py`) to identify the test-DB fixture surface.
2. Reproduce one `InvalidCatalogNameError` to confirm the failing fixture chain.
3. Triage the 11 baseline failures by file to determine whether they share a root cause (e.g., `test_maps_style_json.py` ×5 likely share a fixture or model issue).
4. Land conftest fix first; then re-run pytest to see if baseline failures auto-resolve (some may be downstream of the lifecycle bug).
5. Address residual failures one at a time.

</decisions>

<code_context>
## Existing Code Insights

- `backend/tests/conftest.py` is the entry point for shared fixtures (likely contains `db_engine`, `async_session`, etc.).
- v1015 introduced per-test DB creation via Alembic 0021 (drop `last_heartbeat_at`) — this changed the test-DB lifecycle.
- v1016 Phase 1074 verified the 11 failures + 1363 errors are NOT regressions; they reproduce on pre-v1016 baseline.
- The `asyncpg.exceptions.InvalidCatalogNameError` is raised when a connection target catalog (database) doesn't exist. Common causes:
  1. Fixture creates DB but teardown drops it before child fixture finishes
  2. Connection pool holds stale connection to a deleted DB
  3. Per-worker DB naming collision under `-n auto`
- Affected test files are spread across feature areas:
  - `test_defer_orphan_guard.py` — likely tests orphan-record reaper from v1014/v1015
  - `test_ingest.py` — broad ingest pipeline tests
  - `test_maps_style_json.py` — map style JSON round-trip (v1004/v1005 cluster intent metadata)

Codebase patterns expected (project memory):
- FastAPI + asyncpg + SQLAlchemy async session pattern
- Alembic migrations in `backend/alembic/versions/`
- pytest-asyncio for async test support; likely `pytest-xdist` for parallel runs

</code_context>

<specifics>
## Specific Ideas

- Land conftest refactor as one atomic plan (Plan 01).
- Land 11 baseline failure fixes as Plan 02 — group by file (3 plans for 3 test files, OR 1 plan with 3 sections if scope allows).
- Aim for ≤3 plans total in this phase to keep scope tight.

</specifics>

<deferred>
## Deferred Ideas

- Pytest fixture documentation refresh — defer to v1018 hygiene
- `pytest-xdist` config tuning (worker count, dist=loadfile vs loadscope) — defer unless needed for `-n auto` to pass
- CI smoke-test addition (separate from CI-01 alembic workflow) — defer to v1018

</deferred>
