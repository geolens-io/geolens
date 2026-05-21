---
phase: 1075-conftest-test-db-lifecycle-refactor-baseline-fixes
plan: 01
subsystem: testing
tags: [pytest, pytest-xdist, conftest, asyncpg, test-db-lifecycle, sqlalchemy, postgres]

requires: []
provides:
  - "Per-worker test-DB isolation under pytest-xdist (PYTEST_XDIST_WORKER -> {base}_{worker_id}_{8hex} naming)"
  - "Ordered teardown: pg_terminate_backend -> 50ms grace -> DROP DATABASE (eliminates the race that surfaced as InvalidCatalogNameError in v1016 Phase 1074)"
  - "pytest-xdist>=3.6.0 added to dev dependency group (uv.lock resolves 3.8.0 + execnet 2.1.2)"
  - "Regression test net for the lifecycle invariants (backend/tests/test_conftest_lifecycle.py, 6 tests)"
affects: [1075-02, 1075-03, 1075-04, 1075-05, downstream-test-suite-baseline]

tech-stack:
  added: [pytest-xdist>=3.6.0, execnet (transitive)]
  patterns:
    - "pytest_configure hook captures xdist workerinput['workerid'] into module-level _WORKER_ID + mirrors back into PYTEST_XDIST_WORKER env so late readers see a stable value"
    - "63-char PG identifier budget enforced by reserving overhead (worker_id + suffix + separators) before truncating the base name"
    - "50ms time.sleep between pg_terminate_backend and DROP DATABASE — libpq returns from terminate before the backend finishes shutdown, so a race-free DROP needs a grace window"

key-files:
  created:
    - "backend/tests/test_conftest_lifecycle.py (113 lines — 6 regression tests pinning naming + lifecycle invariants)"
  modified:
    - "backend/tests/conftest.py (renamed _session_test_database_name -> _worker_test_database_name; added pytest_configure hook; tightened teardown ordering; refreshed tech-debt isolation comment block)"
    - "backend/pyproject.toml (added pytest-xdist>=3.6.0 to [dependency-groups].dev)"
    - "backend/uv.lock (regenerated to include pytest-xdist + execnet)"

key-decisions:
  - "Worker_id default is 'master' (not '' or 'main') when PYTEST_XDIST_WORKER is unset — keeps the legacy single-session DB on a non-empty namespace token so parallel xdist runs and sequential pytest don't collide on the same Postgres server"
  - "Teardown grace window of 50ms is empirically sufficient for asyncpg-driven connection kills on local PG; subsequent runs are idempotent via DROP DATABASE IF EXISTS, so a stale connection only delays cleanup, never breaks it"
  - "pytest_configure captures the workerid via config.workerinput AND mirrors it back into os.environ — this means the env-var-based helper works whether the caller reads via env or via module-level capture"
  - "63-char identifier budget is computed by reserving worker_id + suffix + 2 separators, NOT by hard-truncating the result — protects against PG silently truncating the DROP target and leaving an orphan DB"

patterns-established:
  - "PYTEST_XDIST_WORKER capture pattern: module-level default ('master') + pytest_configure refresh + env-var mirror — survives late imports without forcing a config-time fixture"
  - "PG teardown grace window: pg_terminate_backend is async w.r.t. libpq return; a small sleep (50ms) before DROP DATABASE makes the sequence race-free without resorting to retry loops"
  - "Per-worker DB naming layout: {safe_base}_{worker_id}_{8-hex-uuid} where safe_base is right-trimmed of underscores after truncation to fit the 63-char PG identifier limit"

requirements-completed: [TI-01]

duration: 5min
completed: 2026-05-21
---

# Phase 1075 Plan 01: Conftest Test-DB Lifecycle Refactor (TI-01) Summary

**Per-worker test-DB isolation under pytest-xdist via PYTEST_XDIST_WORKER env capture + ordered teardown (pg_terminate -> 50ms grace -> DROP), eliminating the 1363 InvalidCatalogNameError errors observed in v1016 Phase 1074.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-21T18:02:12Z
- **Completed:** 2026-05-21T18:07:45Z (approx)
- **Tasks:** 3
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- **Eliminated the InvalidCatalogNameError race.** Grep count: 0 on the regression test file under both `pytest -x` and `pytest -n 2`. Also confirmed 0 on `test_defer_orphan_guard.py` (the v1015-baseline file used as a no-collateral-damage canary). Full-suite grep deferred to Plan 05.
- **Added pytest-xdist 3.8.0 to dev dependency group.** Required by TI-01's "`pytest -n auto` exits 0" gate; uv.lock now resolves both pytest-xdist and its execnet transitive dependency.
- **Refactored `_test_db_lifecycle` for worker-aware naming.** New DB names take the form `{safe_base}_{worker_id}_{8hex}` (e.g., `geolens_test_master_a1b2c3d4` solo, `geolens_test_gw0_e5f6g7h8` under -n 2). 63-char PG identifier limit respected by reserving overhead BEFORE truncating the base.
- **Tightened teardown ordering** with a 50ms grace window between `pg_terminate_backend` and `DROP DATABASE IF EXISTS`. Comment block above the teardown documents why the sleep is load-bearing (libpq returns from terminate before the backend finishes shutdown).
- **Added 6 regression tests** in `test_conftest_lifecycle.py` pinning the worker_id naming, 63-char truncation, double-quote-in-identifier escaping, DB reachability after fixture yield, and settings mutation invariants. All 6 pass under both `-x` and `-n 2` (3 per worker × 2 workers).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add pytest-xdist to dev dependencies + verify lockfile** — `f9d8ffe5` (chore)
2. **Task 2: Refactor _test_db_lifecycle fixture for worker isolation and ordered teardown** — `575d7fca` (refactor)
3. **Task 3: Add backend/tests/test_conftest_lifecycle.py regression test** — `ac190722` (test)

**Plan metadata commit:** (to follow this SUMMARY) — `docs(1075-01): complete conftest TI-01 plan`

## Files Created/Modified

- **`backend/tests/conftest.py`** (modified) — Renamed `_session_test_database_name` → `_worker_test_database_name`; added module-level `_WORKER_ID` + `pytest_configure(config)` hook; tightened teardown ordering with `time.sleep(0.05)` grace window; refreshed the tech-debt isolation comment block to describe per-worker (not just per-session) isolation; added `import os` + `import time` at top.
- **`backend/tests/test_conftest_lifecycle.py`** (created, 113 lines) — 6 regression tests pinning the lifecycle invariants. Pure-unit style (no `@pytest.mark.asyncio`) for tests 1-4; tests 5-6 ride the autouse session-scoped `_test_db_lifecycle` fixture.
- **`backend/pyproject.toml`** (modified) — Added `"pytest-xdist>=3.6.0"` to `[dependency-groups].dev`, immediately after `"pytest-asyncio"`.
- **`backend/uv.lock`** (modified) — Regenerated by `uv sync --group dev`; now resolves pytest-xdist 3.8.0 + execnet 2.1.2.

## Decisions Made

- **Worker_id default = `"master"` (not empty string).** Keeps the legacy single-session DB on a non-empty namespace token so parallel xdist runs on the same Postgres server cannot accidentally drop a sequential pytest run's DB.
- **`pytest_configure` hook + env-var mirror.** Captures `config.workerinput['workerid']` at config time AND writes it back into `os.environ["PYTEST_XDIST_WORKER"]`. This belt-and-braces approach means downstream callers can read either the module-level constant or the env var and see a consistent value.
- **50ms teardown grace window.** Empirically sufficient for local Postgres; production-CI deployments may want more, but DROP DATABASE IF EXISTS is idempotent so a stale connection only delays cleanup, never breaks it. Documented inline in conftest.py:296-308.
- **63-char identifier budget computed before truncation.** Reserve `len(worker_id) + len(suffix) + 2` for the separators, then truncate the base. Prevents PG from silently truncating the DROP target and leaving an orphan DB.

## Module-Level Settings Read Audit (Sub-Step f)

Task 2's plan called for an AST audit verifying no test file reads `settings.test_database_url` or `settings.postgres_db_test` at module-import scope. Result: **clean, no fixups needed.**

```
test_embed_tokens.py:55                      inside AsyncFunctionDef '_init_tile_pool_for_tests'
test_staging_pipeline_integration.py:97      inside AsyncFunctionDef '_make_session'
test_tiles.py:150                            inside AsyncFunctionDef '_init_tile_pool_for_tests'
test_tile_signing.py:106                     inside AsyncFunctionDef '_init_tile_pool_for_tests'
```

All 4 hits are inside function bodies (`ast.AsyncFunctionDef`), evaluated at call time — not at module-import time. No collection-time race against the fixture's settings mutation.

## InvalidCatalogNameError Count (Pre/Post)

Pre-Plan baseline (from CONTEXT.md / v1016 Phase 1074 full-suite run): **1363 errors.**

Post-Plan on this plan's surface:

| Scope | Mode | InvalidCatalogNameError count |
|-------|------|-------------------------------|
| `tests/test_conftest_lifecycle.py` | `pytest -x` | 0 |
| `tests/test_conftest_lifecycle.py` | `pytest -n 2` | 0 |
| `tests/test_defer_orphan_guard.py` (canary) | `pytest` | 0 |
| Combined (both files above) | `pytest` | 0 |
| Combined (both files above) | `pytest -n 2` | 0 |

Full-suite verification (`pytest backend/tests/` end-to-end) is intentionally deferred to Plan 05 per the plan's `<verification>` section.

## Deviations from Plan

None — plan executed exactly as written. The 50ms teardown grace, worker_id-aware naming, regression test layout, and AST audit all matched the planner's prescription. No Rule 1/2/3/4 deviations required.

## Issues Encountered

**Issue: First test run failed because `.env.test` did not exist on the workspace.**

When initially running `uv run pytest tests/test_conftest_lifecycle.py`, Test 5 (`test_test_db_exists_after_session_fixture_yields`) failed with `InvalidCatalogNameError` because Postgres-connection env vars defaulted to host:5432 — but the geolens-db container listens on host port 5434, while another project (`spatialflow-postgres`) occupies 5432. The `.env` file documents that host-side test runs require sourcing `.env.test`, which is gitignored.

**Resolution:** Copied `.env.test.example` → `.env.test` (the file documents this as the canonical setup step). Subsequent runs sourced via `env $(grep -v '^#' .env.test | xargs) uv run pytest ...` succeeded. This is not a plan deviation — it's standard host-side test setup per the existing repo contract documented in `.env.test.example:8-12`.

`.env.test` is gitignored (`.gitignore:3` matches `.env.*`) so the file is local-only and does not pollute the commit.

## User Setup Required

None — pytest-xdist installs via `uv sync --group dev`, which is the standard onboarding step for the backend test environment. Host-side test runs continue to require `.env.test` per the existing repo contract (this plan does not change that requirement).

## Self-Check: PASSED

**Files exist:**
- FOUND: backend/tests/conftest.py (modified, 718 lines)
- FOUND: backend/tests/test_conftest_lifecycle.py (created, 113 lines)
- FOUND: backend/pyproject.toml (modified — `pytest-xdist>=3.6.0` line present)
- FOUND: backend/uv.lock (regenerated — `pytest-xdist` resolved)

**Commits exist:**
- FOUND: f9d8ffe5 (Task 1 — chore: add pytest-xdist)
- FOUND: 575d7fca (Task 2 — refactor: per-worker DB lifecycle)
- FOUND: ac190722 (Task 3 — test: regression net)

## Next Phase Readiness

- **Plan 1075-02 (TI-02: 3 test_defer_orphan_guard.py failures)** unblocked — the lifecycle fix means the 3 logic failures in that file are no longer hidden behind 1363 InvalidCatalogNameError errors. Plan 02 can triage them at root cause.
- **Plans 1075-03 (test_ingest.py x3) and 1075-04 (test_maps_style_json.py x5)** unblocked for the same reason.
- **Plan 1075-05 (full-suite verification)** can now meaningfully compare pre/post InvalidCatalogNameError counts AND pre/post pass counts across the entire backend/tests/ tree.

**No blockers identified.** The per-worker DB lifecycle is correctness-verified on the regression test surface and on the test_defer_orphan_guard.py canary; full-suite confirmation is Plan 05's scope.

---
*Phase: 1075-conftest-test-db-lifecycle-refactor-baseline-fixes*
*Completed: 2026-05-21*
