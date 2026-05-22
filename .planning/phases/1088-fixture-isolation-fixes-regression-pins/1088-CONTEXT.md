# Phase 1088: Fixture-Isolation Fixes + Regression Pins - Context

**Gathered:** 2026-05-22
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss); spike-driven scope from Phase 1087 audit Section 5

<domain>
## Phase Boundary

Developer running `cd backend && uv run pytest -n auto tests/` sees 0 fixture-scope failures from the cascade categories defined in FI-01, and the regression tests added in this phase reproduce the original failure when reverted.

This phase consumes Phase 1087's audit (`.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md`) Section 5 sequencing. The audit's key revelation:
- **648 actual failures** (not 192) under `pytest -n auto`
- **NONE** of the four v1019-hypothesized categories (Redis singleton, storage provider override, `app.dependency_overrides` leak, autouse-fixture coupling) reproduced — all four observed 0 failures
- **Per-worker DB lifecycle race** (gw15 setup failed silently in `_test_db_lifecycle`) accounts for **407/648 (62.8%)**, single-file structural defect at `backend/tests/conftest.py:275-278`
- **Remaining 239** are connection-contention subcategories that may partially resolve when the lifecycle race is fixed

Phase scope:
- Apply the single-file fix to `backend/tests/conftest.py:265-280` per Section 5's "FIX FIRST" sequencing (silent-swallow → structured handler with retry+raise).
- Re-measure with `pytest -n auto` per Section 5's re-measure protocol.
- Decide remaining sub-categories (4.2/4.3/4.4) based on post-fix counts: if dropped below thresholds documented in Section 5, accept as flake (covered by Phase 1090 HYG-02); if still high, plan structural fixes.
- Write FI-03 regression-pin tests under `backend/tests/test_fixture_isolation_v1020.py` (or split per-category as fix shape dictates).
- Hard floors: sequential `pytest tests/` stays green at 3036/0/38; `pytest -n auto` returns 0 failures from cascade categories.

This is the FIRST phase of v1020 with source-code changes (Phase 1087 was spike-only).

</domain>

<decisions>
## Implementation Decisions

### Fix sequencing (LOCKED — from audit Section 5)

Sequencing is determined by impact (failure count) and structural dependency:

1. **PLAN 1088-01 (FIX FIRST):** Per-worker DB lifecycle race in `_test_db_lifecycle` autouse session fixture. 407 failures → expected 0 post-fix. Single-file edit at `backend/tests/conftest.py:265-280`. **MUST land first** before any re-measure.

2. **PLAN 1088-02 (RE-MEASURE GATE):** After 1088-01 lands and is committed, re-run `pytest -n auto` per Section 5 re-measure protocol. Categorize residual failures by Section 4 categories. Decide:
   - If 4.2 setup contention drops below 50 → accept as flake (defer to HYG-02)
   - If 4.2 stays above 100 → structural fix needed, spawn Plan 1088-03
   - If 4.3 in-test contention drops below 30 → accept as flake (defer to HYG-02)
   - If 4.3 stays above 30 → structural fix needed, spawn Plan 1088-04
   - 4.4 teardown (2 failures) and 4.5 sandbox/assertion (2 failures) → always defer unless re-measure shows them rising

3. **PLAN 1088-03 (CONDITIONAL):** Setup-phase contention structural fix — only if 4.2 re-measure stays above threshold. Audit Section 5 suggests three illustrative approaches (widen stagger to 7-8s, semaphore on `_make_test_async_engine` + `_ensure_roles_and_admin`, retry-with-backoff in `_make_test_async_engine`). Planner picks shape during execution.

4. **PLAN 1088-04 (CONDITIONAL):** In-test contention structural fix — only if 4.3 re-measure stays above threshold. Audit Section 5 suggests retry-with-backoff wrapper around `override_get_db` in the `client` fixture (conftest.py:503-505).

5. **PLAN 1088-N (FINAL):** FI-03 regression pins. One regression test per category fixed in this phase. File location: `backend/tests/test_fixture_isolation_v1020.py` (single file) OR split per-category as fix-plan-author judges most useful. Each pin must FAIL on pre-fix HEAD and PASS on post-fix HEAD.

### Sequential baseline preservation (HARD GATE)

Every sub-plan in Phase 1088 must run `cd backend && uv run pytest tests/` before its SUMMARY commit and assert `failed == 0`. The 3036/0/38 floor from v1019 close-gate is non-negotiable. If a fix breaks sequential mode, the plan is rejected.

### Fix shape for Plan 1088-01 (illustrative — planner owns final shape)

Current code at `backend/tests/conftest.py:275-278` (from audit Section 4.1):
```python
except Exception:
    # silent-swallow — broken
    yield
    return
```

Audit-suggested replacement:
```python
except OperationalError as e:
    err_msg = str(e).lower()
    if "too many clients already" in err_msg or "tooManyConnectionsError" in err_msg:
        # transient: retry with exponential backoff
        for attempt, wait_s in enumerate([1.0, 2.0, 4.0]):
            time.sleep(wait_s)
            try:
                # retry connect/create flow
                ...
                break
            except OperationalError:
                if attempt == 2:
                    raise  # re-raise after final attempt — fail loudly, not silently
    else:
        # truly unreachable (DNS, refused connection, etc.) — preserve skip semantics
        pytest.skip(f"Postgres unreachable: {e}")
```

The shape choice (retry semantics, attempt count, sleep timings, whether to skip vs xfail vs error) is the planner's call. The HARD requirement: silent-swallow MUST go; failure mode MUST be loud (test error or explicit skip with diagnostic message).

### Regression-pin shapes (LOCKED targets from audit Section 5)

For FI-03, each category fixed in FI-02 gets a pin:

- **4.1 per-worker DB lifecycle race:** Mock `dev_engine.connect()` to raise `OperationalError("too many clients already")` once, then succeed. Assert: per-worker test DB IS created (NOT silently skipped) and downstream `client` fixture acquires connection without `InvalidCatalogNameError`.
- **4.2 setup-phase contention:** Pin shape depends on chosen fix; if semaphore, assert N concurrent invocations complete without `TooManyConnections`; if stagger widen, assert no overlap window; if retry, assert retry path is hit and succeeds.
- **4.3 in-test contention:** Test that opens 3 sequential `TestClient.post(...)` calls in tight loop; pre-fix fails under concurrent load; post-fix retries and succeeds.
- **4.4 teardown:** Either covered by 4.2's pin (same fix shape) or separate pin asserting `await test_engine.dispose()` completes within bounded retry window.

### TD-13 rules in effect

1. **REQ citation pinning** (per `<req_citation_pinning>` rule): every plan in Phase 1088 cites regression-pin tests by exact `path::TestClass::test_name` node-ID. Planner validates via `git grep -n "def <test_name>" <path>` before PLAN.md commit. Since FI-03 pins are NEW tests being created, the planner cites the *intended* node-ID, and the executor's verify gate confirms the test exists at that exact name after creation.

2. **Traceability flip** (per `<requirements_traceability_flip>` rule): the FINAL plan in Phase 1088 (likely 1088-N for regression pins) must flip BOTH FI-02 AND FI-03 in REQUIREMENTS.md (`[ ]` → `[x]`, traceability row `Pending` → `Complete`) in the SAME commit as its SUMMARY.md write. The verify gate uses `git diff-tree --no-commit-id --name-only -r HEAD` (NOT `git log -1 --name-only`).

### Out of scope for this phase

- Frontend changes (no `frontend/` edits)
- Schema/migration changes (no Alembic revisions)
- `postgresql.conf` `max_connections` bump (rejected in REQUIREMENTS.md Out of Scope)
- `-n` worker count cap below `auto` (rejected in REQUIREMENTS.md Out of Scope)
- CI workflow changes (Phase 1089 owns CI-01 and CI-02)
- Default `make test` switch to parallel (Phase 1089 owns CI-02)
- Perf benchmark (Phase 1089 owns PERF-01)
- Skip audit (Phase 1090 owns HYG-01)
- Flake hunt 3× runs (Phase 1090 owns HYG-02)
- Tag cuts (Phase 1090 owns close-gate tagging)

</decisions>

<code_context>
## Existing Code Insights

**The target file:**
- `backend/tests/conftest.py` — defines `_test_db_lifecycle` autouse session fixture (lines ~256-280 per audit), `client` fixture (~503-505), `_make_test_async_engine` helper, `_ensure_roles_and_admin`, `_SETUP_STAGGER_SECONDS=5.0`, NullPool branch for xdist async engines.

**Lines targeted by Plan 1088-01:**
- conftest.py:265-280 — the silent-swallow `except Exception: yield; return` block in `_test_db_lifecycle`'s setup-phase error handler.

**Lines potentially targeted by Plan 1088-03 (if needed):**
- conftest.py:357-370 — `_make_test_async_engine` (per-worker async engine factory; NullPool branch)
- conftest.py:5.0 second stagger location (currently at 5.0s; may widen to 7-8s)
- `_ensure_roles_and_admin` location (TBD — planner reads conftest)

**Lines potentially targeted by Plan 1088-04 (if needed):**
- conftest.py:503-505 — `override_get_db` in `client` fixture

**v1019 patterns to preserve (must not regress):**
- NullPool branch from commit `9c9daf61` + `ea24168c` (`_make_test_async_engine` helper)
- 5s startup stagger from commit `1aaf81c5` (`_SETUP_STAGGER_SECONDS`)
- Sequential pytest baseline: 3036/0/38 in ~540s
- All TD-09..TD-14 v1019 deliverables (frontend typecheck, `/maps/new` redirect, `/api/api/` fix, process retro, ssl=False probe)

**Sources of truth for failure inventory:**
- `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` Section 3 — 648 node-IDs with category tags
- `/tmp/v1020-junit.xml` — JUnit XML (may be deleted; spike re-measure recreates it)
- `/tmp/v1020-failure-inventory.json` — structured per-failure inventory (may be deleted)

**Reproducibility:**
- All measurement methodology in audit Section 1 (verbatim from v1019 spike, slightly extended Step 1b for stale-DB cleanup)
- HEAD reference: `d340c22e` was the audit's measurement HEAD; current HEAD has Phase 1087 SUMMARY + REVIEW + VERIFICATION on top of that

**Where the regression pins go:**
- `backend/tests/test_fixture_isolation_v1020.py` (NEW FILE — does not exist yet) — single file with per-category test functions/classes
- OR `backend/tests/test_fixture_isolation_v1020_<category>.py` split — planner picks based on test count + reuse

</code_context>

<specifics>
## Specific Ideas

**Plan shape (planner discretion — likely 2-5 plans depending on re-measure outcomes):**

- **Plan 1088-01** (UNCONDITIONAL): Fix per-worker DB lifecycle race at conftest.py:265-280. Single-file edit. Single regression pin for 4.1 (FI-03 partial). Sequential baseline preserved. **Re-measure NOT in this plan** — keep the plan atomic; re-measure lives in Plan 1088-02.

- **Plan 1088-02** (UNCONDITIONAL): Re-measure gate. Run `pytest -n auto`, categorize residual failures, decide thresholds. Output: `.planning/audits/PYTEST-XDIST-REMEASURE-AFTER-1088-01.md` (or similar) with pre/post counts per category. Branch logic: if all post-fix counts below thresholds, proceed to final FI-03 pin plan (1088-N). If above thresholds, spawn Plan 1088-03 and/or 1088-04.

- **Plan 1088-03** (CONDITIONAL — only if 4.2 above threshold): Setup-phase contention structural fix. Re-measure included. Regression pin for 4.2 (FI-03 partial).

- **Plan 1088-04** (CONDITIONAL — only if 4.3 above threshold): In-test contention structural fix. Re-measure included. Regression pin for 4.3 (FI-03 partial).

- **Plan 1088-N (FINAL)**: Consolidates FI-03 regression-pin tests, runs final close gate (sequential 3036/0/38 + parallel 0-cascade), flips REQUIREMENTS.md FI-02 + FI-03 + ROADMAP.md Phase 1088 in SAME commit per TD-13.

**Reading the audit Section 5 carefully:**
The audit explicitly says "the v1020 fix strategy [may be] a single-category close rather than a four-category sweep" if 4.1 cascades resolve 4.2/4.3/4.4. The planner should plan for the OPTIMISTIC case (1088-01 + 1088-02 + 1088-N = 3 plans, all conditional fixes skipped) and be prepared to add conditional plans only if re-measure data demands them.

**Re-measure protocol (verbatim from Section 5):**
1. Drop stale per-worker DBs (Section 1 Step 1b of audit).
2. Re-run sequential baseline (audit Section 1 Step 2) — assert `failed == 0`.
3. Re-run `pytest -n auto --junitxml=...` (audit Section 1 Step 4).
4. Re-categorize via the audit Section 1 Step-5 Python helper.
5. Cross-reference with audit Section 4 category counts.
6. SUMMARY reports: pre-fix count + post-fix count + cross-category drift.

**Hard floor recap:**
- Sequential: 3036/0/38 (or higher — N and K can vary; M must stay 0)
- Parallel `pytest -n auto`: failures from categories 4.1 + 4.2 + 4.3 + 4.4 = 0
- Failures from category 4.5 (sandbox/assertion, 2 items) — accept as case-by-case; document in SUMMARY but don't block
- No frontend, no schema, no `max_connections`, no `-n` cap

</specifics>

<deferred>
## Deferred Ideas

- **CI gate wiring** — Phase 1089 (CI-01)
- **`make test` default switch to parallel** — Phase 1089 (CI-02)
- **Perf benchmark** — Phase 1089 (PERF-01)
- **38-skip audit** — Phase 1090 (HYG-01)
- **3× flake hunt** — Phase 1090 (HYG-02)
- **v1019 WR-01 paper-trail** — Phase 1090 (HYG-03)
- **Worker-count tuning beyond `-n auto`** — Phase 1089 PERF-01 may recommend changing default; not for Phase 1088
- **Audit Section 4.5 assertion-failure case-by-case investigation** — document in SUMMARY only; do not block close on it; flag for HYG-02 or HYG-01 disposition

</deferred>
