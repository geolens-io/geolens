---
phase: 1088-fixture-isolation-fixes-regression-pins
plan: 01
subsystem: testing

tags:
  - pytest
  - pytest-xdist
  - sqlalchemy
  - postgres
  - fixture-isolation
  - conftest
  - operational-error
  - retry-with-backoff
  - regression-pin
  - v1020

# Dependency graph
requires:
  - phase: 1087-xdist-fixture-isolation-audit
    provides: "Audit Section 4.1 root-cause analysis + Section 5 fix sequencing (FIX FIRST)"
  - phase: 1085-pytest-xdist-stabilization (v1019 TD-10)
    provides: "_make_test_async_engine helper + NullPool branch + _SETUP_STAGGER_SECONDS=5.0 (preserved verbatim by this plan)"

provides:
  - "Structured `except OperationalError` handler in `_test_db_lifecycle` replacing the silent-swallow at conftest.py:275-278"
  - "Extracted `_create_test_db_with_retry(make_engine_fn, quoted_db_name, sleep_fn=time.sleep, backoffs=(1.0, 2.0, 4.0))` helper, importable for direct testability"
  - "Regression pin file `backend/tests/test_fixture_isolation_v1020.py` with 3 tests pinning the contention-retry / propagate-non-contention / exhaust-budget contracts (category 4.1 close, FI-03 partial)"

affects:
  - 1088-02-re-measure-gate
  - 1088-N-requirements-flip
  - 1089-ci-wiring
  - 1090-flake-hunt

# Tech tracking
tech-stack:
  added: []  # No new dependencies — sqlalchemy.exc.OperationalError already transitively imported via the existing SQLAlchemyError line.
  patterns:
    - "Extracted-helper-for-testability — pull the retry loop out of the autouse session fixture into a private module-level helper so unit tests can mock the engine factory + sleep_fn without driving the live fixture (mirrors `_make_test_async_engine` extraction from v1019 commit `ea24168c`)"
    - "Distinguished-OperationalError-branches — split `except OperationalError` on `\"too many clients already\"` substring: contention path retries with bounded backoff + fails loudly on exhaustion, unreachable-host path preserves `pytest.skip` for unit-only runs"
    - "Pre-quoted-identifier contract at helper boundary — `_create_test_db_with_retry` takes an already-quoted `quoted_db_name` so the helper cannot accidentally introduce SQL-injection surface; quoting stays at the call site via `_quote_database_identifier`"

key-files:
  created:
    - "backend/tests/test_fixture_isolation_v1020.py"
  modified:
    - "backend/tests/conftest.py"

key-decisions:
  - "Strategy A (extracted helper) over Strategy B (class-level patch of SQLAlchemy connect) — helper extraction makes the retry loop directly testable without a live engine, mirrors the v1019 `_make_test_async_engine` extraction pattern, and the regression pin imports the helper cleanly without monkey-patching internals."
  - "Retry budget = (1.0, 2.0, 4.0) seconds = 7s cumulative wait, bounded below the 75s gw15 stagger window — under the absolute worst case (every retry on every worker hits TooManyConnections), the cumulative wait does not push the parallel run past the existing stagger-overhead ceiling."
  - "`pytest.skip` for non-contention OperationalError preserves the pre-fix unit-only-run semantics verbatim — pure unit-test runs outside Docker continue to short-circuit DB setup with a clear diagnostic message rather than failing every DB-backed test."
  - "REQUIREMENTS.md FI-02 / FI-03 traceability flip is DEFERRED to Plan 1088-N per CONTEXT.md LOCKED sequencing and the TD-13 `requirements_traceability_flip` rule — this plan is the structural fix only."
  - "Re-measurement under `pytest -n auto` is DEFERRED to Plan 1088-02 per CONTEXT.md atomicity rule — keeping the fix and the measurement in separate plans makes the cross-category drift (4.1→0 + perturbation of 4.2/4.3/4.4) attributable to a single commit boundary."

patterns-established:
  - "Bounded retry on transient Postgres contention — exponential-backoff with explicit budget tuple, dispose-and-recreate engine per attempt, raise-on-exhaustion. Applicable to any session-scoped DDL fixture under -n auto."
  - "Audit-cited inline comment block — when fixing a defect with a documented root cause in an audit, the replacement code carries a multi-line comment naming the audit file + section + failure-count impact so a future reader can trace the WHY without grepping git history."

requirements-completed: []
# FI-02 and FI-03 are addressed structurally by this plan but the REQUIREMENTS.md
# traceability flip lives in Plan 1088-N per the TD-13 `requirements_traceability_flip`
# rule (flip must land in the SAME commit as its SUMMARY.md). Partial-close note:
# this plan closes audit category 4.1 (407/648 failures, 62.8% of total) — the
# remaining 239 failures (categories 4.2/4.3/4.4/4.5) are re-measured in Plan 1088-02.

# Metrics
duration: ~17min (work) + ~9min 30s (sequential baseline)
completed: 2026-05-22
---

# Phase 1088 Plan 01: Per-Worker DB Lifecycle Race Fix Summary

**Replaced silent-swallow at `backend/tests/conftest.py:275-278` with a structured `except OperationalError` handler that retries on `"too many clients already"` with backoff `(1.0, 2.0, 4.0)` and fails loudly on exhaustion, while preserving `pytest.skip` semantics for genuinely unreachable Postgres hosts. Closes audit category 4.1 (407/648 failures, 62.8% of total) structurally; FI-03 regression pin lives at `backend/tests/test_fixture_isolation_v1020.py::test_lifecycle_retries_on_transient_too_many_clients`.**

## Performance

- **Duration:** ~27 min total (17 min work + 9 min 30 s sequential baseline gate)
- **Sequential baseline:** `3039 passed, 38 skipped, 14 deselected, 18 warnings in 570.33s (0:09:30)` — verbatim from `/tmp/1088-01-sequential-baseline.log`
- **Started:** 2026-05-22 (single-session execution)
- **Completed:** 2026-05-22T15:30:04Z
- **Tasks:** 3
- **Files modified:** 2 (1 modified, 1 created)

## Accomplishments

- Replaced the broad-except silent-swallow that was the dominant structural defect surfaced by Phase 1087's v1020 audit (407/648 = 62.8% of all `-n auto` failures).
- Extracted `_create_test_db_with_retry(make_engine_fn, quoted_db_name, sleep_fn=time.sleep, backoffs=(1.0, 2.0, 4.0))` private module-level helper at `backend/tests/conftest.py` (between `_drop_test_database_if_exists` and `_test_db_lifecycle`) so the retry loop is unit-testable without a live engine.
- Wired the helper into `_test_db_lifecycle`'s setup phase with two-branch `except OperationalError` handler: contention path → retry then fail-loudly-on-exhaustion; non-contention path → `pytest.skip(f"Postgres unreachable: {e}")` preserving existing unit-only-run semantics.
- Created `backend/tests/test_fixture_isolation_v1020.py` (NEW FILE) with 3 regression pins:
  - `test_lifecycle_retries_on_transient_too_many_clients` — the FI-03 / audit Section 4.1 canonical pin (asserts factory called >=2 times, DROP+CREATE both ran on the retry attempt, first engine disposed, exactly one 1.0s backoff sleep).
  - `test_lifecycle_propagates_non_contention_operational_error` — companion pin guarding against a future refactor widening the retry net to include unreachable-host shapes.
  - `test_lifecycle_exhausts_retry_budget_then_fails_loudly` — companion pin asserting the 1 + len(backoffs) = 4 total-attempts contract + that the helper re-raises after exhaustion (NOT silently swallows).
- Sequential baseline preservation HARD GATE: **PASSED.** `3039 passed, 0 failed, 38 skipped` — +3 over v1019's 3036 floor (the new regression-pin file adds 3 tests; the 38 skips are unchanged).
- v1019 patterns preserved verbatim — `_make_test_async_engine` (commit `ea24168c`), `_SETUP_STAGGER_SECONDS=5.0` (commit `1aaf81c5`), `_derive_test_pool_sizing`, `_get_setup_stagger_delay`, NullPool branch — all 17 `test_conftest_pool_sizing.py` + `test_conftest_lifecycle.py` tests pass. Diff scope is surgical: line 12 import + new helper + replaced silent-swallow region only.

## Task Commits

Each task was committed atomically. NOTE: Per the plan's Task 3 instruction, Tasks 1+2+3 deliverables ship together in a SINGLE commit to keep the structural fix + its regression pin + the SUMMARY atomic. The single commit subject is `fix(1088-01): replace silent-swallow with structured OperationalError handler`.

1. **Task 1: Structured OperationalError handler in `_test_db_lifecycle`** — bundled into the single commit (fix)
2. **Task 2: Regression pin for category 4.1 per-worker DB lifecycle race** — bundled into the single commit (test)
3. **Task 3: Sequential baseline gate + SUMMARY + atomic commit** — the single commit itself (fix + test + docs)

## Files Created/Modified

- `backend/tests/conftest.py` — Added `OperationalError` to the existing `from sqlalchemy.exc import` line at conftest.py:12. Inserted `_create_test_db_with_retry` helper (additive) between `_drop_test_database_if_exists` and `_test_db_lifecycle`. Replaced the silent-swallow `try/except Exception:/yield;return/finally:dispose` block inside `_test_db_lifecycle` with: `quoted_db_name` assignment hoisted above the helper call + `_open_dev_engine` inner factory + `_create_test_db_with_retry(_open_dev_engine, quoted_db_name)` + structured `except OperationalError` handler that branches on `"too many clients already"` substring. No other regions touched.
- `backend/tests/test_fixture_isolation_v1020.py` — NEW FILE. 3 regression pins for audit Section 4.1 (1 canonical + 2 companions). File-level docstring cites audit + plan + REQUIREMENTS.md deferral. Pure-unit shape (no live DB I/O — all engines are `MagicMock`).

## Decisions Made

- **Helper-extraction (Strategy A) over class-level patch (Strategy B).** The plan's `<action>` allowed either; extraction was chosen because (a) it mirrors the v1019 `_make_test_async_engine` extraction pattern, (b) the regression pin imports the helper cleanly without `unittest.mock.patch` of SQLAlchemy internals, (c) the helper is reusable if Plans 1088-03/04 add similar retry wrappers around `_make_test_async_engine` or `override_get_db`.
- **Backoff tuple `(1.0, 2.0, 4.0)` = 7s cumulative wait.** Bounded well below the 75s gw15 stagger window. Picked over a wider tuple (e.g., `(2.0, 5.0, 10.0)`) because the audit's measured contention windows close within ~3-5s once gw0..gw14 finish their setup phase; 7s is enough to clear the window without doubling wall-clock penalty for legitimate failures.
- **`pytest.skip` over `pytest.fail` on non-contention OperationalError.** The original `except Exception: yield; return` had this semantic (silently treat unreachable hosts as "skip DB setup, let unit tests pass"); preserving it as an explicit `pytest.skip` keeps backward compatibility with developers who run `pytest tests/test_some_unit.py` without Docker up. The diagnostic `f"Postgres unreachable: {e}"` makes the skip reason loud in the test output.
- **Pre-quoted identifier at the helper boundary.** The helper takes `quoted_db_name: str` (already escaped via `_quote_database_identifier`), not a raw `db_name`. This keeps the quoting trust boundary at the call site — the helper cannot introduce identifier-injection surface even if a future caller passes an attacker-controlled name.
- **Companion pins (`propagates_non_contention` and `exhausts_retry_budget`) beyond the required canonical pin.** The plan required only `test_lifecycle_retries_on_transient_too_many_clients`. Two companions were added because the structured handler has 3 distinct branches (retry-then-succeed, propagate-immediately, exhaust-then-raise); each branch needs at least one regression pin or a future refactor could silently re-introduce the silent-swallow on one of them.

## Deviations from Plan

**None — plan executed exactly as written.** Strategy A vs B was a planner-allowed choice, not a deviation. Companion pins beyond the required canonical pin are an additive Rule-2 strengthening (correctness of the retry-contract): without them, only one of the three branches is pinned and a future maintainer could regress the propagate / exhaust contracts undetected. Cost: ~80 LOC of pure-unit test code, no live-DB dependency, sub-second runtime.

## Issues Encountered

- `git grep` exit-code-1 against the new (untracked) regression-pin file — `git grep` only walks tracked files. Resolved by passing `--untracked` (or by alternative `grep -rn` outside the git index). The plan's verify-gate command `git grep -n "def test_lifecycle_retries_on_transient_too_many_clients" tests/test_fixture_isolation_v1020.py | grep -c ...` would behave correctly POST-commit (after the file is tracked); pre-commit it requires the `--untracked` flag. No fix to the plan needed — this is a property of `git grep`, not a bug.
- One SQLAlchemy deprecation warning (`websockets.legacy is deprecated`) surfaced in the sequential run output — pre-existing, unrelated to this plan. Not regressed.

## Sequential Baseline Preservation HARD GATE

Verbatim from `/tmp/1088-01-sequential-baseline.log`:

```
=== 3039 passed, 38 skipped, 14 deselected, 18 warnings in 570.33s (0:09:30) ===
```

- **M failed = 0** — invariant satisfied (non-negotiable per plan + CONTEXT.md).
- **N passed = 3039** — over the v1019 floor of 3036 (+3 from the new regression-pin file).
- **K skipped = 38** — unchanged.

## Partial-Close Notes for FI-02 / FI-03

- **FI-02 (audit-driven fix):** This plan closes audit category 4.1 structurally — silent-swallow replaced, retry-with-backoff in place, sequential baseline preserved. **Full close of FI-02 depends on Plan 1088-02 re-measure** confirming the 407 → 0 drop under `pytest -n auto`. REQUIREMENTS.md flip is NOT made in this commit per the CONTEXT.md LOCKED decision and TD-13 `requirements_traceability_flip` rule.
- **FI-03 (regression pin):** Category-4.1 regression pin landed at `backend/tests/test_fixture_isolation_v1020.py::test_lifecycle_retries_on_transient_too_many_clients`. Additional pins for categories 4.2/4.3/4.4 (if needed after re-measure) are owned by Plan 1088-03 / 1088-04 / 1088-N. REQUIREMENTS.md flip lives in 1088-N.

## Deferred to Plan 1088-02 / 1088-N

- **Re-measure under `pytest -n auto`** — DEFERRED to Plan 1088-02 per CONTEXT.md atomicity rule. Expected outcome per audit Section 5: category 4.1 drops from 407 to ~0; categories 4.2/4.3/4.4 may shift up or down as gw15 starts opening connections.
- **REQUIREMENTS.md FI-02 / FI-03 traceability flip** — DEFERRED to Plan 1088-N per CONTEXT.md LOCKED sequencing + TD-13 `requirements_traceability_flip` rule (the flip MUST land in the SAME commit as its SUMMARY.md write).
- **Plans 1088-03 / 1088-04** — CONDITIONAL on Plan 1088-02 re-measure thresholds.

## Self-Check: PASSED

- `backend/tests/conftest.py` exists, contains `from sqlalchemy.exc import SQLAlchemyError, OperationalError` (line 12), `def _create_test_db_with_retry(...)` (new helper), `except OperationalError as e` (the structured handler), and `pytest.skip(f"Postgres unreachable: {e}")` (the preserved skip branch). The exact triple-line silent-swallow shape (`except Exception:\n    # DB host unreachable...\n    yield\n    return`) no longer exists in `_test_db_lifecycle`.
- `backend/tests/test_fixture_isolation_v1020.py` exists, contains exactly 1 match for `def test_lifecycle_retries_on_transient_too_many_clients` plus 2 companion-pin definitions. All 3 tests pass against post-fix HEAD.
- v1019 patterns preserved: `_make_test_async_engine`, `_SETUP_STAGGER_SECONDS=5.0`, `_derive_test_pool_sizing`, `_get_setup_stagger_delay`, NullPool branch. `test_conftest_pool_sizing.py` + `test_conftest_lifecycle.py` = 17/17 pass.
- Sequential `pytest tests/` baseline: 3039 passed / 0 failed / 38 skipped — over the 3036 floor.
- REQUIREMENTS.md unchanged in this commit (will be verified by Plan 1088-N's flip gate).

## Next Phase Readiness

- **Plan 1088-02 (re-measure gate)** is unblocked. Recommended next actions:
  - Drop stale per-worker DBs (audit Section 1 Step 1b).
  - Re-run sequential baseline (`pytest tests/`) to confirm 0 failed (defensive double-check).
  - Run `pytest -n auto --junitxml=/tmp/v1020-junit-post-1088-01.xml`.
  - Re-categorize via the audit Section 1 Step-5 Python helper.
  - Expected: category 4.1 = 0 (down from 407). Watch for cross-category drift in 4.2 (150 baseline) as gw15 now opens connections.
- **No code blockers** for downstream plans. The helper extraction is consumable by future retry-wrapper work in Plans 1088-03 / 1088-04 if their re-measure thresholds trip.

---

*Phase: 1088-fixture-isolation-fixes-regression-pins*
*Plan: 01*
*Completed: 2026-05-22*
