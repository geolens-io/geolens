---
phase: 1085-pytest-n-auto-stabilization
plan: 01
subsystem: testing
tags: [pytest, xdist, asyncpg, postgres, connection-pool, spike]

requires:
  - phase: 1083-close-gate
    provides: "PYTEST-BASELINE-v1018.md — sequential baseline 3025/0/38, host confirmed 16-core M-series"

provides:
  - "PYTEST-XDIST-SPIKE-v1019.md at .planning/audits/ — measured cascade data + chosen fix shape"
  - "Confirmed cascade reproduction: 2453 cascade errors, 45% test error rate under -n auto"
  - "Fix shape decision: (a) per-worker pool sizing in conftest.py"

affects:
  - "1085-02 (plan 02 consumes spike doc Section 5 to scope its single-file edit)"

tech-stack:
  added: []
  patterns:
    - "Background pg_stat_activity sampler pattern for measuring Postgres connection fan-out mid-run"
    - "Spike-first, evidence-driven fix-shape selection for DB connection ceiling problems"

key-files:
  created:
    - ".planning/audits/PYTEST-XDIST-SPIKE-v1019.md"
  modified: []

key-decisions:
  - "Chose fix shape (a): per-worker pool sizing in backend/tests/conftest.py — pool_size=1 max_overflow=0 for xdist workers, pool_size=5 max_overflow=2 for sequential mode"
  - "Cascade confirmed severe: 628 TooManyConnectionsError + 1824 CannotConnectNowError = 2453 errors in one run"
  - "Sampling strategy A (background pg_stat_activity) chosen over B (conftest instrumentation) — sufficient granularity without temporary code changes"

patterns-established:
  - "Connection-fan-out spike pattern: background sampler + xdist run + grep cascade-error count → evidence-based fix-shape selection"

requirements-completed: [TD-10]

duration: 10min
completed: 2026-05-21
---

# Phase 1085 Plan 01: pytest xdist Spike Summary

**`pytest -n auto` cascade confirmed at 2453 errors (45% of 3062 tests errored); fix shape (a) chosen — per-worker pool_size=1 in conftest.py — reducing 16×7=112 theoretical peak to 16×1=16 actual connections (14 below max_connections=30 ceiling)**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-21T21:35:00Z (approx)
- **Completed:** 2026-05-22T01:45:50Z
- **Tasks:** 1 of 1
- **Files modified:** 1 (spike doc created)

## Accomplishments

- Confirmed `max_connections=30` live against `geolens-db-1` container (`db/postgresql.conf:11`)
- Confirmed 16 xdist workers spawn under `-n auto` on this 16-core M-series macOS host (all gw0..gw15 visible in `pg_stat_activity`)
- Measured cascade reproduction: 628 `TooManyConnectionsError` + 1824 `CannotConnectNowError` + 1 `InvalidCatalogNameError` = 2453 total cascade-error lines; final result `2 failed, 1669 passed, 23 skipped, 1369 errors in 41.13s`
- Sampler captured peak snapshot of 29 concurrent test-DB connections (post-recovery); pre-cascade peak was ≥30 (confirmed by Postgres entering recovery mode for 10 consecutive 2s samples)
- Committed spike doc at `.planning/audits/PYTEST-XDIST-SPIKE-v1019.md` with all four measured numbers + three-shape analysis + chosen fix shape + Plan 02 file scope

## Spike Numbers

| Metric | Value |
|--------|-------|
| `postgres_max_connections` | 30 |
| xdist worker count (`-n auto`) | 16 (gw0..gw15) |
| per-worker pool ceiling | 7 (pool_size=5 + max_overflow=2) |
| per-worker peak (observed) | 4 (gw4 at 21:39:31) |
| total peak (observed, post-recovery) | 29 (21:39:31 row-sum; total query blank = recovery mode) |
| theoretical peak | 112 (16 × 7 = 3.7× ceiling) |
| cascade reproduction | YES — TooManyConnectionsError=628, CannotConnectNowError=1824 |

## Chosen Fix Shape

**Shape (a): per-worker pool sizing in `backend/tests/conftest.py`**

Plan 02 will set `pool_size=1, max_overflow=0` when `PYTEST_XDIST_WORKER != "master"`, and keep `pool_size=5, max_overflow=2` for sequential mode. This brings total connections under xdist from 112 theoretical → 16 actual (14 below ceiling).

## Files Plan 02 Will Touch

- `backend/tests/conftest.py` (lines 354-360 — `create_async_engine` pool sizing in `client` fixture)
- `backend/tests/test_conftest_pool_sizing.py` (new — regression pin for sequential vs xdist pool sizing)

## Sampling Strategy

**Strategy A** (background `pg_stat_activity` sampler) — sufficient to confirm the cascade and measure the post-recovery peak. The 2-second sampling interval missed the exact moment of peak (Postgres was in recovery during that window), but 2453 cascade error lines in `/tmp/v1019-xdist-spike.log` and `TooManyConnectionsError` messages directly confirm max_connections=30 was exceeded.

## Cascade Reproduction: YES

```
TooManyConnectionsError:   628
CannotConnectNowError:    1824
InvalidCatalogNameError:     1
ConnectionFailureError:      0
Total cascade errors:      2453  (grep against /tmp/v1019-xdist-spike.log)
```

Final pytest summary: `2 failed, 1669 passed, 23 skipped, 1369 errors in 41.13s`

## Task Commits

1. **Task 1: Measure + write spike doc** - `af902329` (feat)

**Plan metadata:** (final commit follows)

## Files Created/Modified

- `.planning/audits/PYTEST-XDIST-SPIKE-v1019.md` — spike measurement doc with 4 numbers, 3-shape analysis, chosen shape (a), Plan 02 file scope

## Decisions Made

- Strategy A (background sampler) chosen over Strategy B (conftest instrumentation) — 2s granularity was sufficient to confirm the cascade; no temporary code modifications needed
- Fix shape (a) chosen: smallest blast radius (one file, conftest-only), no production config changes, scales naturally per host, sequential mode unchanged
- `pool_size=1, max_overflow=0` (not `1+1=2`) for xdist workers: `16 × 2 = 32` would exceed `max_connections=30` by 2; `16 × 1 = 16` gives 14 headroom — the stricter option is correct

## Deviations from Plan

None — plan executed exactly as written. Sampling Strategy A was used as described. No implementation files were modified. The spike doc satisfies all must_haves.

## Reproducibility

To re-run the spike against a fresh stack:
1. `docker compose ps db` — confirm healthy on `127.0.0.1:5434`
2. Start background sampler (exact command in PYTEST-XDIST-SPIKE-v1019.md Section 1)
3. Run `cd backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) uv run pytest -n auto tests/ 2>&1 | tee /tmp/v1019-xdist-spike.log`
4. Kill sampler; analyze `/tmp/pgstat-xdist.log`

## Next Phase Readiness

- Plan 02 (`1085-02`) has unambiguous scope: read PYTEST-XDIST-SPIKE-v1019.md Section 5 → `backend/tests/conftest.py` lines 354-360 (add PYTEST_XDIST_WORKER-conditional pool sizing) + new `test_conftest_pool_sizing.py` regression test
- No blockers. Sequential baseline (3025/0/38) unchanged by this plan.

---

## Self-Check: PASS

- `.planning/audits/PYTEST-XDIST-SPIKE-v1019.md` exists: YES
- Commit `af902329` exists: YES
- `git diff backend/tests/conftest.py db/postgresql.conf docker-compose.yml Makefile`: EMPTY (no implementation changes)
- Spike doc contains max_connections=30: YES
- Spike doc picks exactly one fix shape: YES (shape a)
- Spike doc names Plan 02 files: YES (`backend/tests/conftest.py`)

---
*Phase: 1085-pytest-n-auto-stabilization*
*Completed: 2026-05-21*
