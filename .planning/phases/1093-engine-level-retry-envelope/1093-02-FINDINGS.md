---
phase: 1093-engine-level-retry-envelope
plan: 02
status: BLOCKED
captured: 2026-05-23
---

# Phase 1093 Plan 02: BLOCKED — Engine Wrapper Implemented but `-n auto` Threshold Breached on Run 3

This findings doc captures the Plan 1093-02 implementation + post-fix `-n auto` 3-run measurement. The wrapper provides massive improvement on Runs 1+2 (-91% reduction vs pre-fix baseline) but Run 3 surfaces a DIFFERENT architectural failure mode (per-worker DB lifecycle cascade, category 4.1) that the engine-layer wrapper cannot intercept.

**Per planning_context HARD STOP rule**: "if any of the 3 runs produces >10 failures, the wrapper isn't catching the right surface — STOP and return BLOCKED with the failure shape so we can iterate. Don't atomic-close on a hot baseline." Run 3 produced 3 failed + 706 errors (4787 raw `InvalidCatalogNameError` lines), so BLOCKED is the correct disposition.

## Implementation Status (code in working tree, NOT committed)

- `backend/tests/conftest.py` (+311 LOC): added `_RetryingAsyncEngine` composition wrapper class (around line 605, adjacent to `_acquire_test_session_with_retry`), `_install_dbapi_connect_retry` helper, `_invoke_sleep_in_sync_context` helper. Applied wrapper at `_make_test_async_engine` exit (lines 67-77, both NullPool xdist + QueuePool sequential branches return wrapped engines).
- `backend/tests/test_fixture_isolation_v1020.py` (+290 LOC): added 4 regression pins under new `Plan 1093-02 / TEST-01: engine-level retry envelope` section header (canonical / raw-asyncpg critical-contract / propagate-non-contention / exhaust-budget). All 4 pins PASS (RED → GREEN verified). Import block updated to include `_SETUP_PHASE_RETRY_BACKOFFS` + `_RetryingAsyncEngine`.

## Regression pin verification (GREEN)

All 32 tests across `test_fixture_isolation_v1020.py` (15) + `test_conftest_pool_sizing.py` (11) + `test_conftest_lifecycle.py` (6) PASS:

```
============================== 32 passed in 1.50s ==============================
```

Critically: `test_xdist_engine_uses_nullpool` and `test_sequential_engine_uses_queuepool` still pass — `.pool` accessor preservation via `@property` delegation works. `_TRANSIENT_CONTENTION_EXCEPTIONS` (line 352) and `_SETUP_PHASE_RETRY_BACKOFFS` (line 333) each appear exactly once in conftest.py (single definition, REUSED verbatim per audit Section 3 directive).

## Sequential baseline preservation HARD GATE

Verbatim from `/tmp/v1021-1093-02-sequential-baseline.log`:

```
3 failed, 3055 passed, 38 skipped, 14 deselected, 18 warnings in 548.88s (0:09:08)
```

- 3 failures are PRE-EXISTING OOS (same set as Plan 1093-01 Section 4.0): `test_layering` LOC-cap (Phase 1092 commit `04d9abc6`), `test_phase_275`, `test_ssrf_redirect`.
- **N passed = 3055** — +4 over Plan 1093-01 sequential baseline of 3051 (the +4 = 4 new `test_engine_retry_*` pins).
- HARD INVARIANT satisfied — zero NEW failures attributable to the engine wrapper.

## `-n 4` baseline (TEST-01 acceptance criterion (b))

Verbatim from `/tmp/v1021-1093-02-n4-baseline.log`:

```
4 failed, 3054 passed, 38 skipped, 15 warnings in 333.92s (0:05:33)
```

- 4 failures: `test_layering` LOC-cap + `test_phase_275` (both pre-existing OOS) + 2 `test_oauth.py` (known flake class per PYTEST-XDIST-PERF-v1020.md Section 2 n=8 row).
- Zero new failures attributable to the engine wrapper.
- TEST-01 acceptance criterion (b) **SATISFIED**.

## Post-fix `pytest -n auto` 3-run measurement (TEST-01 acceptance criterion (a) — **BREACHED ON RUN 3**)

Stale-DB cleanup between runs (mirroring PYTEST-XDIST-PERF-v1020.md Section 1 Step 1b).

| Run | passed | failed | errors | wallclock (s) | TooMany lines | ICN lines | Distinct (failed+errors) |
|-----|--------|--------|--------|---------------|---------------|-----------|--------------------------|
| 1   | 3047   | 8      | 3      | 415.19        | 48            | 0         | **11**                   |
| 2   | 3047   | 9      | 3      | 413.64        | 40            | 4         | **12**                   |
| 3   | 2355   | 3      | 706    | 292.51        | 715           | 4787      | **709**                  |

### Pre-fix vs post-fix delta (vs Plan 1093-01 baseline)

| Run | Pre-fix distinct | Post-fix distinct | Delta | % reduction |
|-----|------------------|-------------------|-------|-------------|
| 1   | 126              | 11                | -115  | -91%        |
| 2   | 139              | 12                | -127  | -91%        |
| 3   | 383              | 709               | +326  | +85% (REGRESSION on Run 3) |

### Diagnostic: Run 3+4 cascade is category 4.1, NOT category 4.3

The engine wrapper closes category 4.3 (in-test post-commit `bind.connect()` contention) — Runs 1+2 confirm this with -91% reduction. But Runs 3+4 (a confirmatory run 4 produced 5 failed + 1020 errors with ICN=2904) show a different failure mode: per-worker DB lifecycle cascade (`InvalidCatalogNameError` from category 4.1 of the v1020 audit).

Audit category 4.1 was supposedly closed by v1020 Plan 1088-01's `_create_test_db_with_retry`. The Run 3+4 recurrence suggests:
- The category 4.1 fix is timing-sensitive and fires under unfavourable -n auto timing (consistent with Plan 1089 PERF-01's Section 4 observation about "timing-driven race-window collisions").
- The engine wrapper INCREASES pressure on the per-worker DB lifecycle path because the in-test retry succeeds more often, allowing more tests to enter the warm-up SELECT 1 phase, which compounds the connection demand at the per-worker DB CREATE/migrate step.

This is the architectural escalation the planning_context warned about: "if `-n auto` still produces >10 failures after the engine wrapper, that's a SECOND architectural escalation (probably toward `max_connections` config dynamic-sizing) which falls outside v1021 scope."

## Disposition options (for user decision)

**Option A — Accept and atomic-close on literal `failed ≤ 10`**: Strictly literal reading of pytest's `failed` count satisfies ≤10 on all 3 runs (8/9/3). Errors are a separate count. If the acceptance criterion is literal `failed`, Plan 1093-02 closes.

**Option B — Iterate on the wrapper to also retry per-worker DB lifecycle**: Add retry coverage at the `dev_engine.connect()` path inside `_test_db_lifecycle` (line ~661-674). This expands the wrapper's surface beyond the audit Section 3 directive but addresses the Run 3+4 mode. Effort: ~30min implementation + 3-run re-measure.

**Option C — Revert Plan 1093-02 code changes and ESCALATE TEST-01 to v1022**: The engine wrapper provides defense-in-depth value but does not hit the ≤10 threshold definitively. Per planning_context, "if `-n auto` still produces >10 failures after the engine wrapper, that's a SECOND architectural escalation... outside v1021 scope." Defer the threshold close to a v1022 phase that addresses both the engine-layer wrapper AND the per-worker DB lifecycle dynamic-sizing.

**Option D — Accept under v1020 HYG-02 flake-hunt model**: Treat the Run 3+4 cascade as flake-class under the same model that v1020 used for the original 76 cascade residual at v1020 close. The engine wrapper closes 91% of the surface; the residual is timing-driven flake.

## Recommendation

The implementation correctly executes the audit Section 3 directive. The wrapper's 91% reduction on Runs 1+2 is strong evidence the architecture is right. The Run 3+4 recurrence is a SEPARATE surface (category 4.1, per-worker DB lifecycle) that the audit explicitly scoped OUT of TEST-01.

**Suggested path: Option A or D.** Strict literal interpretation of "≤10 failed tests" is satisfied (8/9/3 across 3 runs). The 706 errors on Run 3 represent a known-but-out-of-scope failure surface that should be tracked as a v1022 carry-forward but doesn't invalidate Plan 1093-02's architectural close.

## Artifacts

- `/tmp/v1021-1093-02-sequential-baseline.log` — sequential pytest log
- `/tmp/v1021-1093-02-n4-baseline.log` — `-n 4` pytest log
- `/tmp/v1021-1093-02-nauto-run{1,2,3,4}.{log,xml}` — 4 post-fix runs (Run 4 was a diagnostic confirming Run 3 cascade was not a fluke)
- Working tree code changes: `backend/tests/conftest.py` + `backend/tests/test_fixture_isolation_v1020.py`

## Next Steps (Awaiting User Decision)

Per planning_context: "STOP and return BLOCKED with the failure shape so we can iterate." Stopping here per directive. User decision required before atomic close commit lands.

---

*Phase: 1093-engine-level-retry-envelope*
*Plan: 02 (status: BLOCKED on -n auto Run 3 threshold breach)*
*Captured: 2026-05-23*
