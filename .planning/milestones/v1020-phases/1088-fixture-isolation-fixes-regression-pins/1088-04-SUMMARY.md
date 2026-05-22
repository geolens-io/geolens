---
phase: 1088-fixture-isolation-fixes-regression-pins
plan: 04
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
  - asynccontextmanager
  - regression-pin
  - v1020

# Dependency graph
requires:
  - phase: 1087-xdist-fixture-isolation-audit
    provides: "Audit Section 4.3 root-cause analysis (87/648 in-test contention failures) + Section 5 illustrative fix shape (retry-with-backoff wrapper around override_get_db)"
  - plan: 1088-01
    provides: "_create_test_db_with_retry helper + _CREATE_DB_RETRY_BACKOFFS retry-budget shape; structural fix for category 4.1 (407 -> 0)"
  - plan: 1088-02
    provides: "Re-measure data showing post-1088-01 4.3 = 172 (>30 threshold) -> SPAWN-1088-03-AND-1088-04 decision gate"
  - plan: 1088-03
    provides: "_run_with_too_many_clients_retry async helper + _TRANSIENT_CONTENTION_EXCEPTIONS multi-class catch tuple (OperationalError + asyncpg.TooManyConnectionsError + asyncpg.CannotConnectNowError); structural fix for category 4.2 (188 -> 47)"

provides:
  - "Async-context-manager helper `_acquire_test_session_with_retry(session_factory, sleep_fn=asyncio.sleep, backoffs=_IN_TEST_RETRY_BACKOFFS)` at `backend/tests/conftest.py:453-583` that retries asyncpg connection acquisition during the FIRST query against the session (eager warm-up `SELECT 1` inside retry envelope) before yielding the session to the caller"
  - "New in-test retry budget constant `_IN_TEST_RETRY_BACKOFFS = (0.5, 1.0)` (1.5s total wait budget, distinct from setup-phase 7s budget) — bounded for per-request latency"
  - "Re-uses `_TRANSIENT_CONTENTION_EXCEPTIONS` catch tuple from Plan 1088-03 (no new catch shape)"
  - "Wired `override_get_db` (inside `client` fixture at conftest.py:~892) to use the new retry helper"
  - "Wired `test_db_session` fixture (at conftest.py:~1074) to use the same retry helper — Rule-2 extension beyond plan's named site after iter-1 measurement showed 66 of the residual 4.3 failures route through this fixture, not `override_get_db`"
  - "4 new regression pins in `backend/tests/test_fixture_isolation_v1020.py` (category 4.3 partial close, FI-03 partial): canonical SQLAlchemy-wrapped retry pin + asyncpg-raw critical-contract pin + propagate-non-contention + exhaust-budget"

affects:
  - 1088-N-requirements-flip
  - 1089-ci-wiring
  - 1090-flake-hunt

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "@asynccontextmanager-wrapped retry helper mirroring `_run_with_too_many_clients_retry`'s catch contract — same `_TRANSIENT_CONTENTION_EXCEPTIONS` tuple + same loud-fail-on-exhaust + injected sleep_fn for testability, but yields a SESSION (vs. returning a coroutine result) so it composes naturally with the existing `async with test_session_factory() as session: yield session` shape inside `override_get_db` / `test_db_session`."
    - "Eager warm-up query inside retry envelope to bridge the NullPool lazy-connection gap — under SQLAlchemy + asyncpg + NullPool, `session = await async_sessionmaker()` is cheap (no connection acquired); the asyncpg `_connect_addr` is only invoked LAZILY when the first query executes against the session. A retry envelope around bare `__aenter__` therefore provides ZERO coverage for in-test contention. Issuing `await session.execute(text('SELECT 1'))` INSIDE the retry envelope forces the connection acquisition to fire (and be retry-protected) before the session is yielded to the caller. Plan 1088-04 iter-1 measurement confirmed: bare-`__aenter__` retry dropped 4.3 by 2 (137 -> 135); warm-up retry dropped 4.3 by 71 (137 -> 66) on iter-2, and extending the fix to `test_db_session` dropped to 48 on iter-3."
    - "Multi-fixture parallel wrap — when the plan names ONE fixture site but measurement shows the contention surface is replicated across a SIBLING fixture using the same access pattern (here `test_db_session` at line ~1074, structurally identical to `override_get_db` at line ~892), the fix shape must propagate to the sibling. Without the Rule-2 extension to `test_db_session`, iter-2 stayed at 4.3 = 66 (well above 30); with it, iter-3 reached 48."
    - "Measurement-driven scope expansion (Rule-2) — every Plan 1088 sub-plan has needed inline scope adjustment after measurement: 1088-01 added regression pin pre-bug (companion pins for symmetric coverage); 1088-03 widened catch tuple (iter-1 -> iter-2 from 42% to 75% coverage); 1088-04 extended fix site to second fixture (iter-2 -> iter-3 from 4.3=66 to 4.3=48). The Plan 1088-N close-out should note this as a v1020 process pattern: audit-driven plans naming a SINGLE site need a Rule-2 budget for sibling sites discovered via iter-N measurement."

key-files:
  created: []
  modified:
    - "backend/tests/conftest.py"
    - "backend/tests/test_fixture_isolation_v1020.py"

key-decisions:
  - "`@asynccontextmanager`-wrapped helper over inline-for-loop or sync-style helper — composes cleanly with the existing `async with test_session_factory() as session: yield session` shape at both `override_get_db` and `test_db_session` call sites; the helper's `yield session` matches the caller's expected async-generator contract; teardown via `cm.__aexit__` mirrors the original `__aexit__` invariant."
  - "Eager warm-up `SELECT 1` inside retry envelope — chosen over the bare-`__aenter__` shape in the original plan after iter-1 measurement showed bare-`__aenter__` retry produced 0 effective coverage (137 -> 135). The warm-up is required by the NullPool lazy-connection contract: without it, the asyncpg connection-acquisition (and its TooManyConnectionsError surface) fires LATER, inside the request handler, OUTSIDE the retry envelope. Documented inline in the helper docstring + iter-1/2/3 progression in this SUMMARY."
  - "**Rule-2 extension to `test_db_session`** — the plan named only `override_get_db` (audit Section 5 line 1296-1299), but iter-2 measurement showed 66 of the residual 4.3 failures route through `test_db_session` instead (tests that combine direct DB writes via `test_db_session` with HTTP requests via `client` open >=2 distinct asyncpg connections per test body — same lazy-connection failure shape, different fixture entry point). Per Rule 2 (missing critical functionality to hit hard threshold), extended the fix to `test_db_session` at conftest.py:~1074. Iter-3 result: 4.3 = 48 (vs. 4.3 = 66 without the extension)."
  - "Retry-budget `(0.5, 1.0)` = 1.5s total for in-test path, distinct from setup-phase `(1.0, 2.0, 4.0)` = 7s. In-test retries fire per-request and a single test may issue several sequential `TestClient.post(...)` calls — a 7s budget per request could compound to >30s per test body. 1.5s is tight enough to keep tests responsive but wide enough to clear the connection-saturation peak in measurement (iter-2/3 numbers confirm the budget closes ~71/89 of the post-1088-03 cascade)."
  - "Re-use `_TRANSIENT_CONTENTION_EXCEPTIONS` from Plan 1088-03 verbatim (no new catch shape) — Plan 1088-03 already established that BOTH SQLAlchemy-wrapped OperationalError AND raw asyncpg exception classes must be in the catch tuple. Plan 1088-04's new helper imports the same tuple, so any future widening (or narrowing) is locked-down at the module level for both setup and in-test paths."
  - "4 regression pins (canonical / asyncpg-raw critical-contract / propagate-non-contention / exhaust-budget) — same coverage envelope as Plan 1088-01's sync helper + Plan 1088-03's async helper. The asyncpg-raw pin is the most important: it locks down that the catch tuple stays widened to include `asyncpg.TooManyConnectionsError`, preventing a future refactor from re-introducing the iter-1 zero-coverage bug."
  - "REQUIREMENTS.md FI-02 / FI-03 traceability flip is DEFERRED to Plan 1088-N per CONTEXT.md LOCKED sequencing + TD-13 `requirements_traceability_flip` rule — this plan is the structural-fix-and-measure step only."

patterns-established:
  - "@asynccontextmanager retry-wrapper for session-yielding fixtures — when a fixture's contract is `async with cm() as x: yield x`, the retry wrapper that preserves the contract is itself an `@asynccontextmanager` that handles retry internally and re-raises the original async-generator yield/teardown shape. Inline for-loop retry would force the caller to be a generator too (more boilerplate, easier to break)."
  - "Lazy-connection warm-up contract for NullPool — under SQLAlchemy + asyncpg + NullPool, a retry envelope around bare-`__aenter__` is INSUFFICIENT for in-test contention. The envelope MUST include the first query to force eager connection acquisition. The warm-up `SELECT 1` pattern is the standard solution and should be documented inline at every helper where NullPool is in play."
  - "Iter-N measurement-driven scope review — when a plan names a SINGLE fix site, the post-fix measurement should ALSO trace which test files / fixtures the residual failures route through. If a SIBLING fixture has the same access pattern, Rule 2 extends the fix; if the residual is structurally outside any retry envelope, escalate the threshold check rather than expanding scope indefinitely. This plan's iter-2 -> iter-3 transition is the canonical example."

requirements-completed: []
# FI-02 and FI-03 are addressed structurally by this plan but the
# REQUIREMENTS.md traceability flip lives in Plan 1088-N per the TD-13
# `requirements_traceability_flip` rule. Partial-close note: this plan
# reduces audit category 4.3 from 137 (post-1088-03) to 48 (post-1088-04).
# The 48 residual is ABOVE the 30 threshold from CONTEXT.md, but the
# remaining failures route through `bind.connect()` calls that fire
# AFTER `await session.commit()` releases the connection — i.e., they
# happen OUTSIDE any retry envelope a session-factory-level helper can
# provide. The architectural fix (engine-level pool retry or
# transaction-binding of sessions) is outside the scope of the audit's
# Section 5 suggestion. Plan 1088-N decides whether to ESCALATE further
# (engine-level retry) or ACCEPT the residual under Phase 1090 HYG-02
# flake hunt. Combined Plan 1088-01 + 1088-03 + 1088-04 effect:
# 648 -> 76 (-88.3% from pre-fix baseline).

# Metrics
duration: ~70min (work + 3 sequential baselines + 3 parallel re-measures across iter-1/2/3)
completed: 2026-05-22
---

# Phase 1088 Plan 04: In-Test Connection Contention Fix (Partial) Summary

**Wrapped `override_get_db` (inside `client` fixture) AND `test_db_session` fixture with `_acquire_test_session_with_retry` (a new `@asynccontextmanager` helper that eagerly triggers asyncpg connection acquisition via a warm-up `SELECT 1` inside the retry envelope, then yields the session to the caller). Reduces audit category 4.3 from 137 -> 48 (-65%, but still ABOVE the 30 threshold). The residual 48 failures route through `bind.connect()` calls that fire AFTER `await session.commit()` releases the warm-up's connection — OUTSIDE any retry envelope a session-factory-level helper can wrap. Plan 1088-N decides whether to ESCALATE (engine-level pool retry) or ACCEPT the residual under Phase 1090 HYG-02.**

## Plan Execution

- **Fix shape chosen:** @asynccontextmanager wrap of session-factory acquisition + eager warm-up SELECT 1 — see Decisions for rationale.
- **Files modified:** `backend/tests/conftest.py`, `backend/tests/test_fixture_isolation_v1020.py`.
- **Iter-1 -> Iter-2 -> Iter-3 progression:**
  - **iter-1** (bare-`__aenter__` retry around `test_session_factory()` only): 4.3 dropped 137 -> 135 (0% effective coverage). Live traceback inspection showed the asyncpg `_connect_addr` fires LAZILY on the first query (`session.execute`), AFTER `__aenter__` succeeds. The retry envelope was empty by the time the contention error surfaced.
  - **iter-2** (added eager warm-up `SELECT 1` inside retry envelope, override_get_db only): 4.3 dropped 137 -> 66. Significant gain. But 66 was still above 30 threshold.
  - **iter-3** (Rule-2 extension: same fix applied to `test_db_session` fixture): 4.3 dropped 66 -> 48. Most of the residual was routing through `test_db_session` (66 of 79 iter-2 4.3 failures had the same lazy-connection shape via that fixture).
- **iter-3 residual analysis:** All 48 residual 4.3 failures route through `bind.connect()` calls that fire AFTER `await session.commit()` (e.g., `await session.refresh(...)` immediately after a commit; multiple sequential request handlers within one test body). The session's warm-up connection is released on commit; subsequent operations acquire a fresh asyncpg connection that can race the ceiling again. A session-factory-level retry helper CANNOT protect post-commit query connection acquisitions because they happen inside test code, not inside the fixture envelope. Closing this residual requires either (a) engine-level connection retry via custom `creator` or pool subclass, or (b) accepting under HYG-02 flake hunt.

## Sequential Baseline Preservation HARD GATE (iter-3)

Verbatim from `/tmp/v1020-1088-04-sequential-baseline-v3.log`:

```
=== 3047 passed, 38 skipped, 14 deselected, 18 warnings in 542.76s (0:09:02) ===
```

- **M failed = 0** — invariant satisfied (non-negotiable per CONTEXT.md).
- **N passed = 3047** — over the v1019 floor of 3036 (+4 from this plan's 4 new regression pins; +7 cumulative from Plans 1088-01/03/04).
- **K skipped = 38** — unchanged.

## Parallel Re-measure (iter-3, post-`test_db_session`-extension)

Verbatim from `/tmp/v1020-1088-04-xdist-v3.log`:

```
= 52 failed, 2974 passed, 38 skipped, 15 warnings, 24 errors in 418.20s (0:06:58) =
```

JUnit XML at `/tmp/v1020-remeasure-1088-04-v3.xml` reports 76 classified failures (52 failed + 24 errors, JUnit-authoritative per audit Section 1 Step-5 design).

### Per-category counts post-fix (iter-3)

```
4.1: 0     (unchanged from Plan 1088-01)
4.2: 21    (47 -> 21, -55%) — additional drop from warm-up reducing pressure on setup phase
4.3: 48    (137 -> 48, -65% partial benefit — STILL above 30 threshold)
4.4: 3     (1 -> 3, +2 — flake territory)
4.5: 4     (1 -> 4, +3 — investigate post-Plan-1088-N)
total: 76  (186 -> 76, -59%)
```

### Cross-category drift commentary (post-1088-03 -> post-1088-04)

| Category | Description | Post-1088-03 | Post-1088-04 | Delta | Disposition |
|----------|-------------|--------------|--------------|-------|-------------|
| 4.1 | per-worker DB lifecycle race | 0 | 0 | unchanged | **RESOLVED (Plan 1088-01)** — neither 1088-03 nor 1088-04 regressed. |
| 4.2 | setup-phase async-session contention | 47 | **21** | **-26 (-55%)** | **STILL BELOW 50 THRESHOLD** — additional drop because in-test warm-up retries (1088-04) bleed off the contention peak that previously hit setup phase too. Plan 1088-03's structural fix is reinforced. |
| 4.3 | in-test connection contention | 137 | **48** | **-89 (-65%)** | **ABOVE 30 THRESHOLD — ESCALATE.** Structural improvement is significant (-65%) but the residual fires outside any session-factory-level retry envelope. See iter-3 residual analysis above. |
| 4.4 | teardown-phase contention | 1 | 3 | +2 | **DEFER** — flake territory; below any threshold. |
| 4.5 | sandbox / assertion (non-cascade) | 1 | 4 | +3 | **DEFER** — small absolute count; re-verify after Plan 1088-N's disposition for 4.3. |
| **Total** | | **186** | **76** | **-110 (-59%)** | Combined Plan 1088-01 + 1088-03 + 1088-04 effect: **648 -> 76 (-88.3% from pre-fix baseline)** |

### Threshold check

- **Category 4.3 = 48 > 30 -> ESCALATE.** Plan 1088-04's structural fix DOES NOT satisfy the CONTEXT.md `<decisions>` exit criterion. The residual is architectural: post-commit query connection acquisition fires outside any retry envelope a session-factory-level helper can wrap. **Plan 1088-N decides:** (a) further structural fix at engine-pool level (invasive, expands scope substantially), or (b) accept under Phase 1090 HYG-02 flake hunt (consistent with audit Section 5 language "if the residual count after fixes is <30, treat as acceptable flake under HYG-02. If higher, structural fix is needed" — the audit anticipated this branch).

## Verbatim assertion (per plan task 3 step 5)

`4.3 = 48 > 30` (FAILS the `<30` threshold per CONTEXT.md `<decisions>`).
Combined post-1088-04 reduction from pre-fix baseline: `648 -> 76 (-88.3%)`.

## Code Changes

### `backend/tests/conftest.py`

- Added `from contextlib import asynccontextmanager` (line 7) — required for the new helper's decorator.
- Added module-level constant `_IN_TEST_RETRY_BACKOFFS = (0.5, 1.0)` (line 467) — distinct from `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)`. Inline comment block cites Plan 1088-04 + audit Section 4.3 + the per-request vs. per-fixture-setup distinction.
- Added `@asynccontextmanager`-decorated helper `_acquire_test_session_with_retry(session_factory, sleep_fn=asyncio.sleep, backoffs=_IN_TEST_RETRY_BACKOFFS)` at lines 470-584. Re-uses `_TRANSIENT_CONTENTION_EXCEPTIONS` catch tuple from Plan 1088-03 (no new catch shape). Issues `await session.execute(text("SELECT 1"))` inside the retry envelope to force eager asyncpg connection acquisition before yielding the session.
- Wired `override_get_db` (inside `client` fixture, line ~892) to use the new helper:
  ```python
  async def override_get_db():
      async with _acquire_test_session_with_retry(test_session_factory) as session:
          yield session
  ```
- Wired `test_db_session` fixture (line ~1074, Rule-2 extension) to use the same helper:
  ```python
  async with _acquire_test_session_with_retry(db_module.async_session) as session:
      yield session
  ```
  Inline docstring cites Plan 1088-04 + Rule-2 + iter-2 measurement showing 66 of 79 residual 4.3 failures routed through this fixture.

### `backend/tests/test_fixture_isolation_v1020.py`

- Added `_IN_TEST_RETRY_BACKOFFS` and `_acquire_test_session_with_retry` to the `from tests.conftest import (...)` block.
- Added 4 new regression pins under a new "Plan 1088-04 / audit Section 4.3" section header (parallel to the existing Plan 1088-03 section):
  - `test_in_test_contention_retries_succeeds` — canonical pin for the SQLAlchemy-wrapped OperationalError warm-up retry path; asserts factory invoked >=2 times, post-retry session is yielded, warm-up SELECT 1 was executed, and the configured 0.5s first-backoff was used.
  - `test_in_test_contention_retries_raw_asyncpg_too_many_connections` — **critical-contract pin** mirroring Plan 1088-03's raw-asyncpg pin. Locks down that the catch tuple stays widened to include `asyncpg.TooManyConnectionsError`. Without this pin, a future refactor could narrow the catch back to `OperationalError`-only and silently drop the dominant in-test contention surface.
  - `test_in_test_propagates_non_contention_operational_error` — companion pin asserting non-contention OperationalError shapes (DNS, auth) propagate immediately. Mirrors the same-named setup-phase pin.
  - `test_in_test_exhausts_retry_budget_then_fails_loudly` — companion pin asserting 1 + len(backoffs) = 4 total attempts on exhaust, then loud re-raise. Mirrors the same-named setup-phase pin.
- All 11 tests in the file pass against post-1088-04 HEAD (3 from Plan 1088-01 + 4 from Plan 1088-03 + 4 from Plan 1088-04).

## v1019 Patterns Preserved

- `_make_test_async_engine(test_database_url: str)` — signature unchanged. Verified by `grep -nE "def _make_test_async_engine\(test_database_url: str\)"`.
- NullPool branch at conftest.py:64-66 — unchanged. Verified by `grep -q "poolclass=NullPool"`.
- `_SETUP_STAGGER_SECONDS = 5.0` at conftest.py:109 — unchanged. Verified by `grep -qE "_SETUP_STAGGER_SECONDS\s*=\s*[0-9.]+"`.
- `_derive_test_pool_sizing` — unchanged.
- `_get_setup_stagger_delay` — unchanged.
- 17/17 `tests/test_conftest_pool_sizing.py` + `tests/test_conftest_lifecycle.py` tests pass.
- All TD-09..TD-14 v1019 deliverables (frontend typecheck, /maps/new redirect, /api/api/ fix, process retro, ssl=False probe) — none in scope, none regressed.

## Plan 1088-01 + 1088-03 regions preserved

- conftest.py:~275 — Plan 1088-01's structured `OperationalError` handler at `_test_db_lifecycle` setup phase — unchanged. Verified by `git diff HEAD` showing only 4 hunks: imports (line 7), new in-test helpers (line 467+), `override_get_db` (line ~892), `test_db_session` (line ~1074). No diff hunks in the 200-360 range (Plan 1088-01 + 1088-03 territory).
- conftest.py:~323 — Plan 1088-03's `_SETUP_PHASE_RETRY_BACKOFFS` constant — unchanged.
- conftest.py:~342 — Plan 1088-03's `_TRANSIENT_CONTENTION_EXCEPTIONS` tuple — unchanged (re-used directly, NOT modified).
- conftest.py:~350 — Plan 1088-03's `_run_with_too_many_clients_retry` async helper — unchanged.
- conftest.py:~960 — Plan 1088-03's `_ensure_roles_and_admin` retry-wrap call — unchanged.

## Self-Check: PASSED

- `backend/tests/conftest.py` exists, contains `from contextlib import asynccontextmanager` (line 7), `_IN_TEST_RETRY_BACKOFFS = (0.5, 1.0)` constant, `@asynccontextmanager`-decorated `_acquire_test_session_with_retry` helper, and the wired-in retry-acm calls in both `override_get_db` and `test_db_session`.
- `backend/tests/test_fixture_isolation_v1020.py` exists, contains `def test_in_test_contention_retries_succeeds` (greppable, exactly 1 match) plus 3 companion pins. All 11 tests in the file pass against post-fix HEAD.
- Sequential `pytest tests/` baseline (iter-3): 3047 passed / 0 failed / 38 skipped — over the 3036 floor.
- Parallel `pytest -n auto` re-measure (iter-3): category 4.3 = 48, **ABOVE the 30 threshold**. Threshold check: ESCALATE.
- REQUIREMENTS.md unchanged in this commit (will be verified by Plan 1088-N's flip gate; explicitly assert via `git diff-tree --no-commit-id --name-only -r HEAD | grep -c '^\.planning/REQUIREMENTS\.md$'` returns 0).
- ROADMAP.md unchanged in this commit (will be flipped by Plan 1088-N's traceability gate).

## Issues Encountered

- **iter-1 zero-effective-coverage diagnosis.** First attempt wrapped only `__aenter__` of the session factory (matching plan's `<interfaces>` literally), but live measurement showed 4.3 dropped from 137 to 135 — i.e., 0% coverage. Live traceback inspection of one failure (`test_anon_get_private_dataset_returns_404`) revealed the asyncpg `_connect_addr` fires LAZILY at `session.execute(...)` inside the request handler, AFTER `__aenter__` succeeds. The retry envelope was empty by the time the contention error surfaced. **Resolution:** added eager warm-up `SELECT 1` inside the retry envelope (iter-2). Documented inline in helper docstring + this SUMMARY's "Plan Execution" section.

- **iter-2 -> iter-3 sibling-fixture extension.** Iter-2 measurement showed 4.3 = 66 (still above threshold). Failure-traceback inspection showed 66 of the residual failures came from tests using BOTH `client` (override_get_db, fixed in iter-2) AND `test_db_session` (NOT in the plan's named-fix-site list) — the `test_db_session` fixture has the structurally identical `async with db_module.async_session() as session: yield session` shape but was untouched. **Resolution:** Rule-2 extension to wrap `test_db_session` with the same helper (iter-3). Documented inline in `test_db_session` docstring + this SUMMARY's "Plan Execution" + "Key Decisions" sections.

- **iter-3 architectural residual.** All 48 iter-3 residual failures fire on `bind.connect()` calls that happen AFTER `await session.commit()` releases the warm-up's connection. The fixture-level retry envelope CANNOT wrap these — they fire inside test code, on subsequent queries that need fresh asyncpg connections. Closing this residual would require either engine-level connection retry (custom `creator` or pool subclass — invasive, expands scope substantially) or accepting under HYG-02. **Resolution:** ESCALATE the threshold check to Plan 1088-N for the (a)-vs-(b) decision; report the partial close with explicit numbers.

- One stale per-worker test DB (`geolens_test_gw8_650f029f`) was dropped before the iter-2 parallel re-measure (audit Section 1 Step 1b protocol). Iter-1 and iter-3 had 0 stale DBs.

## Deviations from Plan

**Rule 1 bug fix (auto-applied):** The plan's `<interfaces>` directed wrapping `test_session_factory()` (i.e., `__aenter__` of the session context manager). Iter-1 measurement showed this provided ZERO coverage because of the NullPool lazy-connection contract — asyncpg's `_connect_addr` is invoked LAZILY at the first `session.execute(...)`, AFTER `__aenter__` succeeds. **Fix applied inline:** added eager warm-up `SELECT 1` inside the retry envelope. The warm-up forces the asyncpg connection-acquisition to fire WITHIN the retry-protected scope. Verified by iter-2 measurement: 137 -> 66 (-52% per-fixture coverage).

**Rule 2 missing critical functionality (auto-applied):** The plan named only `override_get_db` (audit Section 5 line 1296-1299). Iter-2 measurement showed 66 of 79 residual 4.3 failures routed through the SIBLING `test_db_session` fixture (line ~1074, structurally identical to `override_get_db` — same `async with cm() as s: yield s` shape, same NullPool lazy-connection contract, different entry point). Per Rule 2 (missing critical functionality to hit hard threshold of `4.3 < 30`), extended the fix to `test_db_session`. Without this extension, 4.3 would be at 66 (well above 30); with it, 4.3 reached 48. Documented inline in `test_db_session` docstring.

**Rule 4 architectural decision NOT taken (REPORTED for Plan 1088-N):** Iter-3 measurement showed 48 residual 4.3 failures fire on `bind.connect()` calls AFTER `await session.commit()` — OUTSIDE any session-factory-level retry envelope. Closing this residual would require:
- (a) Engine-level connection-retry via custom `async_creator=` or pool subclass — invasive change to `_make_test_async_engine`, would alter the v1019 NullPool pattern's surface behavior.
- (b) Accept under Phase 1090 HYG-02 flake hunt — consistent with audit Section 5 language ("if the residual count after fixes is <30, treat as acceptable flake under HYG-02").

This is a Rule 4 (architectural) decision and per the deviation rules requires checkpoint, NOT auto-apply. Plan 1088-N owns the decision. Reported here with full measurement context (iter-1/2/3 progression, root-cause analysis of post-commit failure shape, explicit (a)-vs-(b) options).

## Deferred to Plan 1088-N

- **Category 4.3 residual disposition (48 failures, > 30 threshold)** — Plan 1088-N decides between engine-level retry (option a) or HYG-02 acceptance (option b).
- **REQUIREMENTS.md FI-02 / FI-03 traceability flip** — DEFERRED to Plan 1088-N per CONTEXT.md LOCKED sequencing + TD-13 `requirements_traceability_flip` rule.
- **Category 4.4 (3 failures)** — DEFER per CONTEXT.md (flake territory, below any threshold).
- **Category 4.5 (4 failures)** — DEFER per CONTEXT.md; investigate post-Plan-1088-N if they persist after 4.3 disposition.

## Reproducibility

Artifacts at `/tmp/`:
- `v1020-1088-04-sequential-baseline-v3.log` — sequential pytest log (3047/0/38 in 542.76s)
- `v1020-1088-04-xdist-v3.log` — parallel pytest log (52 failed / 2974 passed / 24 errors in 418.20s)
- `v1020-remeasure-1088-04-v3.xml` — JUnit XML (3055 testcases / 52 failures / 24 errors)
- `v1020-remeasure-1088-04-parse.py` — categorization helper (mirrors `/tmp/v1020-remeasure-1088-01-parse.py` verbatim, parameterised on iter-N XML path)
- `v1020-remeasure-1088-04-v3-inventory.json` — per-failure inventory (76 entries)
- `v1020-remeasure-1088-04-v3-categories.json` — per-category counts (4.1=0, 4.2=21, 4.3=48, 4.4=3, 4.5=4, total=76)
- Iter-2 artifacts preserved: `v1020-1088-04-sequential-baseline-v2.log`, `v1020-1088-04-xdist-v2.log`, `v1020-remeasure-1088-04-v2.xml`, `v1020-remeasure-1088-04-v2-inventory.json`, `v1020-remeasure-1088-04-v2-categories.json`.

To re-run iter-3 against a fresh stack:
1. `git rev-parse HEAD` — confirm Plan 1088-04's commit SHA (subject contains `1088-04`).
2. `docker compose ps db` — confirm `geolens-db-1` healthy on `127.0.0.1:5434`.
3. Drop stale per-worker test DBs (audit Section 1 Step 1b protocol).
4. Run sequential baseline: `cd /Users/ishiland/Code/geolens/backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) uv run pytest tests/`.
5. Run parallel suite: `cd /Users/ishiland/Code/geolens/backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) uv run pytest -n auto --junitxml=/tmp/v1020-remeasure-1088-04-v3.xml tests/`.
6. Run the parser: `python3 /tmp/v1020-remeasure-1088-04-parse.py`.

## Next Phase Readiness

- **Plan 1088-N (final close-out)** is unblocked. It now has all the measurement data + the (a)-vs-(b) decision context for the 4.3 residual.
- **No code blockers** for downstream plans. The retry helpers (`_create_test_db_with_retry`, `_run_with_too_many_clients_retry`, `_acquire_test_session_with_retry`) and the catch tuple (`_TRANSIENT_CONTENTION_EXCEPTIONS`) are stable and reusable.

---

*Phase: 1088-fixture-isolation-fixes-regression-pins*
*Plan: 04*
*Completed: 2026-05-22*
