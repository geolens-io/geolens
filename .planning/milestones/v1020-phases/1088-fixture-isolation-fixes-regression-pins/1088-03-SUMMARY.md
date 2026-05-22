---
phase: 1088-fixture-isolation-fixes-regression-pins
plan: 03
subsystem: testing

tags:
  - pytest
  - pytest-xdist
  - sqlalchemy
  - asyncpg
  - postgres
  - fixture-isolation
  - conftest
  - too-many-connections
  - retry-with-backoff
  - regression-pin
  - v1020

# Dependency graph
requires:
  - phase: 1087-xdist-fixture-isolation-audit
    provides: "Audit Section 4.2 root-cause analysis + Section 5 illustrative fix shapes (widen stagger / semaphore / retry-with-backoff)"
  - plan: 1088-01
    provides: "_create_test_db_with_retry helper + `_CREATE_DB_RETRY_BACKOFFS` retry-budget shape; structural fix for category 4.1 (407 → 0)"
  - plan: 1088-02
    provides: "Re-measure data showing post-1088-01 4.2 = 188 (>50 threshold) → SPAWN-1088-03-AND-1088-04 decision gate"

provides:
  - "Async retry helper `_run_with_too_many_clients_retry(coro_fn, sleep_fn=asyncio.sleep, backoffs=(1.0, 2.0, 4.0))` at `backend/tests/conftest.py` (between `_test_db_lifecycle` and the `client` fixture)"
  - "Wired `_ensure_roles_and_admin` call inside the `client` fixture to use the new retry helper"
  - "Widened transient-contention catch tuple `_TRANSIENT_CONTENTION_EXCEPTIONS = (OperationalError, asyncpg.TooManyConnectionsError, asyncpg.CannotConnectNowError)` — covers both SQLAlchemy-wrapped and asyncpg-raw shapes"
  - "4 new regression pins in `backend/tests/test_fixture_isolation_v1020.py` (category 4.2 close, FI-03 partial): canonical SQLAlchemy-wrapped retry pin + asyncpg-raw critical-contract pin + propagate-non-contention + exhaust-budget"

affects:
  - 1088-04-in-test-contention-fix (consumable retry helper; 4.3 remains > 30 threshold per this plan's re-measure, will need separate fix)
  - 1088-N-requirements-flip
  - 1089-ci-wiring
  - 1090-flake-hunt

# Tech tracking
tech-stack:
  added: []  # No new package dependencies. `asyncpg` and `asyncio` are already in-tree (asyncpg via sqlalchemy[asyncio]; asyncio is stdlib).
  patterns:
    - "Async retry-wrapper helper mirroring sync helper shape — `_run_with_too_many_clients_retry` parallels `_create_test_db_with_retry` (Plan 1088-01) so both setup-phase contention sites use a consistent retry contract: same backoff budget (1.0 + 2.0 + 4.0 = 7s), same loud-fail-on-exhaust semantics, same injected sleep_fn for testability."
    - "Multi-class exception catch tuple — `_TRANSIENT_CONTENTION_EXCEPTIONS` is a module-level tuple of all transient-contention shapes (SQLAlchemy-wrapped + raw asyncpg). Iteration-1 of this plan caught only `OperationalError` and achieved only 42% retry coverage (188 → 109) because the majority of contention errors surface as RAW `asyncpg.exceptions.TooManyConnectionsError` through the `bind.connect()` → `greenlet_spawn` path before SQLAlchemy translates them. The widened tuple is the structural fix that actually closes the 4.2 cascade (188 → 47, -75%)."
    - "Inline measurement-driven comment block — the `_TRANSIENT_CONTENTION_EXCEPTIONS` tuple and the helper docstring both cite the iter-1 → iter-2 transition (`42% coverage → measurement showed widening was necessary`) so a future maintainer who narrows the catch back to `OperationalError`-only has the WHY in plain sight."

key-files:
  created: []
  modified:
    - "backend/tests/conftest.py"
    - "backend/tests/test_fixture_isolation_v1020.py"

key-decisions:
  - "Shape (c) — retry-with-backoff inside the async helper — over shape (a) widen-stagger and shape (b) per-worker semaphore. Rationale: (1) mirrors Plan 1088-01's already-vetted retry-with-backoff pattern in the same module; (2) targets the root cause (transient contention) directly without wall-clock penalty for healthy runs (vs. shape (a) which adds 30-45s always); (3) no cross-worker coordination complexity (vs. shape (b) which needs a process-wide lock file + cleanup contract)."
  - "**Widening the catch to BOTH SQLAlchemy-wrapped AND raw asyncpg exception classes** — discovered as a Rule-1 bug fix mid-execution after the first measurement showed 188 → 109 (-42% only, well above the 50 threshold). The asyncpg `TooManyConnectionsError` surfaces RAW (not wrapped) through SQLAlchemy's `bind.connect()` → `greenlet_spawn` path. Without widening the catch, the retry path would never engage for the dominant failure shape. The fix is a 3-element exception tuple at module level + an `isinstance(e, OperationalError)` substring guard that preserves the propagate-non-contention contract for sqlalchemy.OperationalError shapes (DNS, auth, refused-connection)."
  - "Retry-budget = (1.0, 2.0, 4.0) = 7s cumulative wait — verbatim from Plan 1088-01's `_CREATE_DB_RETRY_BACKOFFS`. Same rationale: bounded well below the 75s gw15 stagger window; total parallel wall-clock impact bounded by the staggered-startup ceiling, not the sum of retries."
  - "Wrap `_ensure_roles_and_admin` (not `_make_test_async_engine`) — `_make_test_async_engine` only creates an engine object; it does NOT open a connection. The FIRST async-session connection acquisition is inside `_ensure_roles_and_admin` (the first `async with session_factory() as session: ...` block). Wrapping the FIRST DB-touching call is the surgical fix; wrapping engine creation would do nothing."
  - "**4 regression pins instead of 1** — the canonical pin (`test_setup_phase_contention_retries_or_serializes`) covers the SQLAlchemy-wrapped retry path. A second critical-contract pin (`test_setup_phase_contention_retries_raw_asyncpg_too_many_connections`) specifically exercises the RAW asyncpg path, guarding against a future refactor narrowing the catch back to `OperationalError`-only — exactly the bug that limited iter-1 of this plan to 42% coverage. Two companion pins (`test_setup_phase_propagates_non_contention_operational_error`, `test_setup_phase_exhausts_retry_budget_then_fails_loudly`) cover the propagate + exhaust branches. Same coverage envelope as Plan 1088-01's sync helper."
  - "REQUIREMENTS.md FI-02 / FI-03 traceability flip is DEFERRED to Plan 1088-N per CONTEXT.md LOCKED sequencing and TD-13 `requirements_traceability_flip` rule — this plan is the structural fix only."

patterns-established:
  - "Multi-class transient-contention catch contract for async retry wrappers — when the underlying driver (asyncpg) can raise exceptions either as the raw driver class OR via the ORM's translation layer (SQLAlchemy's `OperationalError`), the catch tuple must enumerate BOTH. Module-level tuple lets future callers see exactly which exception shapes are considered 'transient enough to retry' and which propagate."
  - "Measurement-driven catch-widening — when the first measurement shows partial coverage (<50% reduction), do not lengthen the backoff schedule or change the wrap site; instead, inspect the failure traceback for the exception CLASS that escaped the catch. The first-iteration `188 → 109 (-42%)` measurement of this plan was the diagnostic signal that catch-by-class needed widening, not the retry mechanism itself."

requirements-completed: []
# FI-02 and FI-03 are addressed structurally by this plan but the
# REQUIREMENTS.md traceability flip lives in Plan 1088-N per the TD-13
# `requirements_traceability_flip` rule. Partial-close note: this plan
# closes audit category 4.2 (from 188 → 47, below the 50 threshold).
# Category 4.3 remains at 137 (above the 30 threshold) and is owned by
# Plan 1088-04. Categories 4.4 (1) and 4.5 (1) are deferred per CONTEXT.md.

# Metrics
duration: ~38min (work + 2 sequential baselines + 2 parallel re-measures)
completed: 2026-05-22
---

# Phase 1088 Plan 03: Setup-Phase Async-Session Contention Fix Summary

**Wrapped the `client` fixture's `_ensure_roles_and_admin` call (the FIRST async-session connection acquisition under the per-worker test_engine) with a bounded retry-with-backoff helper that catches BOTH SQLAlchemy-wrapped `OperationalError` AND raw `asyncpg.TooManyConnectionsError` / `CannotConnectNowError`. Reduces audit category 4.2 from 188 → 47 (-75%, below the 50 threshold). Category 4.3 carries forward to Plan 1088-04 (137 / 30 threshold). FI-03 regression pin lives at `backend/tests/test_fixture_isolation_v1020.py::test_setup_phase_contention_retries_or_serializes` plus 3 companion pins (raw-asyncpg / propagate / exhaust).**

## Plan Execution

- **Fix shape chosen:** (c) retry-with-backoff inside the async helper — see Decisions below for rationale.
- **Files modified:** `backend/tests/conftest.py`, `backend/tests/test_fixture_isolation_v1020.py`.
- **Iter-1 → Iter-2 widening:** First-iteration retry helper caught only `OperationalError` and achieved only 42% reduction (188 → 109, above 50 threshold). Live-traceback inspection of the iter-1 failures showed the asyncpg `TooManyConnectionsError` was being re-raised RAW (not wrapped) through SQLAlchemy's `bind.connect()` → `greenlet_spawn` path. Widened the catch to `(OperationalError, asyncpg.exceptions.TooManyConnectionsError, asyncpg.exceptions.CannotConnectNowError)`. Iter-2 measurement: 188 → 47 (-75%, below 50 threshold).

## Sequential Baseline Preservation HARD GATE (Iter-2)

Verbatim from `/tmp/v1020-1088-03-sequential-baseline-v2.log`:

```
=== 3043 passed, 38 skipped, 14 deselected, 18 warnings in 538.14s (0:08:58) ===
```

- **M failed = 0** — invariant satisfied (non-negotiable per CONTEXT.md).
- **N passed = 3043** — over the v1019 floor of 3036 (+4 from the regression pins added in this plan; +3 from Plan 1088-01 already in the 3039 baseline).
- **K skipped = 38** — unchanged.

## Parallel Re-measure (Iter-2, post-widening)

Verbatim from `/tmp/v1020-1088-03-xdist-v2.log`:

```
= 138 failed, 2860 passed, 36 skipped, 15 warnings, 49 errors in 394.91s (0:06:34) =
```

JUnit XML at `/tmp/v1020-1088-03-v2.xml` reports 186 classified failures (138 failed + 49 errors with 1 dedup, JUnit-authoritative per audit Section 1 Step-5 design).

### Per-category counts post-fix

```
4.1: 0     (unchanged from Plan 1088-01)
4.2: 47    (188 → 47, -75% — below 50 threshold)
4.3: 137   (172 → 137, -20% partial benefit — STILL above 30, Plan 1088-04 owns)
4.4: 1     (4 → 1)
4.5: 1     (1 → 1)
total: 186 (365 → 186, -49%)
```

### Cross-category drift commentary

| Category | Description | Post-1088-01 | Post-1088-03 | Delta | Disposition |
|----------|-------------|--------------|--------------|-------|-------------|
| 4.1 | per-worker DB lifecycle race | 0 | 0 | unchanged | **RESOLVED (Plan 1088-01)** — Plan 1088-03 did not regress. |
| 4.2 | setup-phase async-session contention | 188 | **47** | **−141 (−75.0%)** | **BELOW 50 THRESHOLD** — accept residual as transient flake (HYG-02 in Phase 1090). Structural fix in this plan. |
| 4.3 | in-test connection contention | 172 | 137 | −35 (−20.3%) | **PARTIAL DROP** — setup-phase relief reduces in-test contention slightly. Still above 30 threshold; structural fix owned by Plan 1088-04. |
| 4.4 | teardown-phase contention | 4 | 1 | −3 | **DEFER** — below any threshold. |
| 4.5 | sandbox subsystem / assertion (non-cascade) | 1 | 1 | unchanged | **DEFER** — single residual assertion failure consistent with cascade side-effect; re-verify after Plan 1088-04. |
| **Total** | | **365** | **186** | **−179 (−49.0%)** | Combined Plan 1088-01 + 1088-03 effect: **648 → 186 (−71.3% from pre-fix baseline)** |

### Threshold check

- **Category 4.2 = 47 < 50 → PASS.** Plan 1088-03's structural fix satisfies the CONTEXT.md `<decisions>` exit criterion. Residual is acceptable transient flake (Phase 1090 HYG-02 coverage).
- **Category 4.3 = 137 > 30 → ESCALATE.** Plan 1088-04 owns the in-test contention structural fix per the Plan 1088-02 audit-doc's `DECISION: SPAWN-1088-03-AND-1088-04`.

## Code Changes

### `backend/tests/conftest.py`

- Added `import asyncio` (line 1) — the helper's default `sleep_fn` parameter is `asyncio.sleep`.
- Added `import asyncpg.exceptions` (line 9) — required to construct `_TRANSIENT_CONTENTION_EXCEPTIONS` tuple at module level.
- Added module-level constants (after `_test_db_lifecycle`):
  - `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` — same shape as `_CREATE_DB_RETRY_BACKOFFS` from Plan 1088-01.
  - `_TRANSIENT_CONTENTION_EXCEPTIONS = (OperationalError, asyncpg.exceptions.TooManyConnectionsError, asyncpg.exceptions.CannotConnectNowError)` — the catch tuple covering both SQLAlchemy-wrapped and raw asyncpg shapes. Inline comment block cites Plan 1088-03 + audit Section 4.2 + the iter-1 → iter-2 widening rationale.
- Added async helper `_run_with_too_many_clients_retry(coro_fn, sleep_fn=asyncio.sleep, backoffs=_SETUP_PHASE_RETRY_BACKOFFS)` — mirrors `_create_test_db_with_retry`'s signature shape (zero-arg callable + injected sleep_fn + injected backoffs tuple). Catches `_TRANSIENT_CONTENTION_EXCEPTIONS`; for `OperationalError` shapes, applies the substring guard so non-contention shapes (DNS, auth) propagate; for raw asyncpg classes, retries unconditionally (they are unambiguously contention by construction).
- Wired the helper into the `client` fixture at the `_ensure_roles_and_admin` call site — replaced direct `await _ensure_roles_and_admin(...)` with `await _run_with_too_many_clients_retry(lambda: _ensure_roles_and_admin(test_session_factory))`. Inline comment block cites Plan 1088-03 + audit Section 4.2.

### `backend/tests/test_fixture_isolation_v1020.py`

- Updated module docstring to also reference Plan 1088-03 + audit Section 4.2.
- Added `_run_with_too_many_clients_retry` import.
- Added 4 new regression pins (all `@pytest.mark.asyncio`, pure-unit shape, no live DB):
  - `test_setup_phase_contention_retries_or_serializes` — canonical pin covering the SQLAlchemy-wrapped `OperationalError` retry path.
  - `test_setup_phase_contention_retries_raw_asyncpg_too_many_connections` — **critical-contract pin** covering the RAW `asyncpg.TooManyConnectionsError` retry path; this pin would have caught the iter-1 bug.
  - `test_setup_phase_propagates_non_contention_operational_error` — companion pin asserting non-contention OperationalError shapes propagate immediately.
  - `test_setup_phase_exhausts_retry_budget_then_fails_loudly` — companion pin asserting 1 + len(backoffs) = 4 total attempts on exhaust, then loud re-raise.

## v1019 Patterns Preserved

- `_make_test_async_engine(test_database_url: str)` — signature unchanged; callers at conftest.py:584 still pass only `settings.test_database_url`. Verified by `grep -n "def _make_test_async_engine"`.
- NullPool branch at conftest.py:64-66 — unchanged. Verified by `grep -q "poolclass=NullPool"`.
- `_SETUP_STAGGER_SECONDS = 5.0` at conftest.py:106 — unchanged. Verified by `grep -qE "_SETUP_STAGGER_SECONDS\s*=\s*[0-9.]+"`.
- `_derive_test_pool_sizing` at conftest.py:27-48 — unchanged.
- `_get_setup_stagger_delay` at conftest.py:109-129 — unchanged.
- 17/17 `tests/test_conftest_pool_sizing.py` + `tests/test_conftest_lifecycle.py` tests pass.
- All TD-09..TD-14 v1019 deliverables (frontend typecheck, /maps/new redirect, /api/api/ fix, process retro, ssl=False probe) — none in scope, none regressed.

## Self-Check: PASSED

- `backend/tests/conftest.py` exists, contains `import asyncpg.exceptions` (line 9), `_TRANSIENT_CONTENTION_EXCEPTIONS = (...)` (module-level tuple), `async def _run_with_too_many_clients_retry(...)` (new helper), and the wired-in retry call at the `_ensure_roles_and_admin` invocation site.
- `backend/tests/test_fixture_isolation_v1020.py` exists, contains `def test_setup_phase_contention_retries_or_serializes` (greppable, exactly 1 match) plus 3 companion pins. All 7 tests in the file pass against post-fix HEAD (3 from Plan 1088-01 unchanged + 4 new).
- Sequential `pytest tests/` baseline (iter-2): 3043 passed / 0 failed / 38 skipped — over the 3036 floor.
- Parallel `pytest -n auto` re-measure (iter-2): category 4.2 = 47, below the 50 threshold.
- REQUIREMENTS.md unchanged in this commit (will be verified by Plan 1088-N's flip gate; explicitly assert via `git diff-tree --no-commit-id --name-only -r HEAD | grep -c '^\.planning/REQUIREMENTS\.md$'` returns 0).

## Issues Encountered

- **Iter-1 measurement undershot threshold.** The first measurement after Task 1+2 commit-ready showed 4.2 = 109 (above 50 threshold). Inspection of the JUnit XML failure traceback revealed the asyncpg exception was being raised RAW through SQLAlchemy's greenlet boundary, bypassing the `except OperationalError` clause entirely. Resolution: widened the catch tuple to include `asyncpg.exceptions.TooManyConnectionsError` + `asyncpg.exceptions.CannotConnectNowError`, added a critical-contract regression pin (`test_setup_phase_contention_retries_raw_asyncpg_too_many_connections`), and re-ran both gates. Iter-2 measurement: 4.2 = 47 (below 50 threshold). The iter-1 → iter-2 transition is documented inline in the `_TRANSIENT_CONTENTION_EXCEPTIONS` comment block and the helper docstring so a future maintainer who narrows the catch back to `OperationalError`-only has the WHY in plain sight.
- Two stale per-worker test DBs (`geolens_test_gw0_d23af85e`, `geolens_test_gw15_459b72e9`) were dropped before the iter-2 parallel re-measure (audit Section 1 Step 1b protocol).

## Deviations from Plan

**Rule-1 bug fix (auto-applied):** The first-iteration retry helper caught only `sqlalchemy.exc.OperationalError`, but the dominant failure surface produced RAW `asyncpg.exceptions.TooManyConnectionsError` through SQLAlchemy's `greenlet_spawn` path. This is a Rule-1 deviation (code doesn't work as intended — retry path never engaged for the majority of failures). Fix applied inline: widened the catch tuple to `_TRANSIENT_CONTENTION_EXCEPTIONS = (OperationalError, asyncpg.TooManyConnectionsError, asyncpg.CannotConnectNowError)`, added a critical-contract regression pin (`test_setup_phase_contention_retries_raw_asyncpg_too_many_connections`) so the contract is locked-down post-fix. Verified by iter-2 measurement: 188 → 47, below threshold.

**Rule-2 addition (auto-applied):** Original plan called for 1 regression pin (`test_setup_phase_contention_retries_or_serializes`). Added 3 companion pins: (a) the asyncpg-raw critical-contract pin from the Rule-1 deviation above, (b) `test_setup_phase_propagates_non_contention_operational_error` (matches Plan 1088-01's symmetric coverage of `OperationalError` propagate-non-contention shape), (c) `test_setup_phase_exhausts_retry_budget_then_fails_loudly` (matches Plan 1088-01's loud-fail-on-exhaust contract). Without (b) and (c), the retry helper's 3-branch contract (retry → propagate → exhaust) has only 1 branch pinned — exactly the criticism the Plan 1088-01 SUMMARY raised under its "Companion pins" decision. Cost: ~70 LOC pure-unit code, sub-second runtime.

## Deferred to Plan 1088-04 / 1088-N

- **Category 4.3 in-test contention (137 failures, > 30 threshold)** — owned by Plan 1088-04 per the Plan 1088-02 audit-doc decision `SPAWN-1088-03-AND-1088-04`. Audit Section 5 suggests wrapping `override_get_db` in the `client` fixture with a retry helper (consumable shape: this plan's `_run_with_too_many_clients_retry` is directly usable in async generator fixture body).
- **REQUIREMENTS.md FI-02 / FI-03 traceability flip** — DEFERRED to Plan 1088-N per CONTEXT.md LOCKED sequencing + TD-13 `requirements_traceability_flip` rule.
- **Category 4.4 (1 failure)** + **Category 4.5 (1 failure)** — DEFER per CONTEXT.md (`4.4 + 4.5 defer unless rising significantly`). Re-verify after Plan 1088-04.

## Next Phase Readiness

- **Plan 1088-04 (in-test contention structural fix)** is unblocked. The `_run_with_too_many_clients_retry` helper is consumable in async-generator fixtures and can be wrapped around the `override_get_db` body or the `async with test_session_factory() as session: yield session` call site at `backend/tests/conftest.py:605-607`. Expected drift: 4.3 = 137 → < 30, with possible knock-on relief for 4.4 + 4.5.
- **No code blockers** for downstream plans. The helper extraction + multi-class catch contract is reusable.

---

*Phase: 1088-fixture-isolation-fixes-regression-pins*
*Plan: 03*
*Completed: 2026-05-22*
