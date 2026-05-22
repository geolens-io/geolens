---
captured: 2026-05-22
milestone: v1020
phase: 1088-fixture-isolation-fixes-regression-pins
plan: 02
requirement: FI-02
head_sha: cef2c788c72d79e1e76273150532b0b3469adb82
parent_audit: .planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md
fix_under_test: Plan 1088-01 (commit cef2c788) — silent-swallow → structured OperationalError handler
sequential_baseline: "3039 passed / 0 failed / 38 skipped / 14 deselected in 538.09s"
parallel_run_summary: "173 failed / 2680 passed / 36 skipped / 194 errors in 348.43s"
parallel_run_total_testcases: 3079
total_failures_classified: 365
decision: SPAWN-1088-03-AND-1088-04
---

# pytest -n auto Re-Measurement After Plan 1088-01 (Silent-Swallow Fix)

**DECISION: SPAWN-1088-03-AND-1088-04**

Categories 4.2 (188) and 4.3 (172) both remain above their thresholds (50 and 30 respectively).
Plan 1088-01's fix successfully closed Category 4.1 (407 → 0), but the cascade did NOT
transitively resolve Categories 4.2 and 4.3 — instead, both categories grew modestly
(4.2: 150 → 188, 4.3: 87 → 172), consistent with the audit's prediction that gw15
opening its previously-suppressed connections would shift cascade timing rather than
relieve total demand. Structural fixes are required for both.

This document is the **input gate for Plans 1088-03 (4.2 structural fix), 1088-04 (4.3
structural fix), and 1088-05 (final close-out + FI-02/FI-03 traceability flip)**. The
machine-readable `DECISION:` line above is consumed by Phase 1088's downstream planner
pre-execution gates.

---

## Section 1 — Methodology

This re-measurement reuses the audit's Section 1 measurement protocol verbatim. Specifically:

- **Step 1b** — stale per-worker test DB cleanup (1 stale DB dropped: `geolens_test_gw12_52765c65`)
- **Step 2** — sequential baseline re-verify (HARD GATE; assert `failed == 0`)
- **Step 4** — `pytest -n auto --junitxml=...` (no background sampler this run; the sampler
  output is advisory and the categorization parser consumes JUnit XML only)
- **Step 5** — Python JUnit XML parser (audit Section 1 Step-5 helper at
  `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md:167-209`), extended with a
  categorization function that maps each parsed failure to audit Section 4 categories
  using the heuristics paraphrased in `.planning/phases/1088-fixture-isolation-fixes-regression-pins/1088-02-PLAN.md:<interfaces>`:
    - **4.1**: `InvalidCatalogNameError` AND (fixture-phase error OR exception class match)
    - **4.2**: `TooManyConnections` / `CannotConnectNow` AND `phase == "setup"`
    - **4.3**: same exception families AND `phase == "in-test"`
    - **4.4**: same exception families AND `phase == "teardown"`
    - **4.5**: anything else (assertion / sandbox / non-cascade)

**Measurement HEAD:** `cef2c788c72d79e1e76273150532b0b3469adb82` (`fix(1088-01): replace
silent-swallow with structured OperationalError handler`).

**Parser sanity gate (audit Section 1 Step-5 line 215):** `PASS: 365 / 365 use
backend/tests/ prefix`.

---

## Section 2 — Sequential baseline gate (HARD GATE)

Verbatim final summary line from `/tmp/v1020-remeasure-1088-01-sequential-baseline.log`:

```
=== 3039 passed, 38 skipped, 14 deselected, 18 warnings in 538.09s (0:08:58) ===
```

- **failed == 0** ✅ (invariant satisfied)
- **passed == 3039** ✅ (matches Plan 1088-01 baseline, +3 over v1019 floor of 3036 — the
  3 new regression-pin tests from Plan 1088-01)
- **skipped == 38** (unchanged)

Sequential mode is intact. The hard gate is preserved — Plan 1088-01 did not regress the
sequential baseline. Proceed to parallel re-measurement.

---

## Section 3 — Parallel run result

Verbatim final summary line from `/tmp/v1020-remeasure-1088-01-xdist.log`:

```
= 173 failed, 2680 passed, 36 skipped, 10 warnings, 194 errors in 348.43s (0:05:48) =
```

JUnit XML at `/tmp/v1020-remeasure-1088-01.xml` reports `testcases=3079, failures=173,
errors=192` (the 2-error delta vs. tee'd log: pytest's terminal summary counts some
fixture-teardown errors as separate lines while JUnit XML pairs them with the failing
testcase — the categorization parser is JUnit-authoritative per audit Section 1
Step-5 design).

**Total classified failures (failures + errors):** 365.

**Wall clock:** 348.43s (vs. 269.12s pre-fix). The +79s is consistent with the gw15
worker now actually completing setup + running its 200+ assigned tests rather than
silently skipping them all on `InvalidCatalogNameError`.

---

## Section 4 — Per-category pre/post comparison

| Category | Description | Pre-fix (audit Section 4) | Post-1088-01 | Delta | Disposition |
|----------|-------------|---------------------------|--------------|-------|-------------|
| 4.1 | per-worker DB lifecycle race (gw15 setup failed) | 407 | 0 | **−407** | **RESOLVED (407 → 0)** — Plan 1088-01's structured `OperationalError` handler closed the silent-swallow at `conftest.py:275-278`. No `InvalidCatalogNameError` failures observed. |
| 4.2 | setup-phase connection contention (TooManyConnections during fixture setup) | 150 | 188 | +38 | **STRUCTURAL FIX NEEDED — spawn Plan 1088-03** (>= 50 threshold). The fix shifted cascade timing: gw15 now opens its previously-suppressed connections, raising concurrent setup-phase demand. |
| 4.3 | in-test connection contention (TooManyConnections inside test body) | 87 | 172 | +85 | **STRUCTURAL FIX NEEDED — spawn Plan 1088-04** (>= 30 threshold). Same shift-of-cascade-timing dynamic — gw15's setup-phase completions free workers to enter test bodies concurrently. |
| 4.4 | teardown-phase connection contention | 2 | 4 | +2 | **DEFER (document only)** — count is up but still in flake territory. Likely resolves once 4.2 fix lands (same exception family, same window). |
| 4.5 | sandbox subsystem error / assertion failure (non-cascade) | 2 | 1 | −1 | **DEFER (document only)** — count down. The single residual (`test_bulk_delete_success`: `assert 1 == 2`) is a logic assertion failure consistent with a cascade side-effect; re-verify after 4.2/4.3 fixes. |
| **Total** | | **648** | **365** | **−283 (−43.7%)** | |

---

## Section 5 — Cross-category drift commentary

Audit Section 5 (`.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md:1321-1328`) requires
that the re-measure SUMMARY show movement across ALL categories, not just the targeted
one, because cascade categories interact. Drift observations:

1. **4.1 → 0 (as predicted):** The structured handler replaces the silent-swallow and the
   gw15 worker (or whichever worker would have lost the race this run) now either retries
   successfully or fails loudly. In this run, no `InvalidCatalogNameError` failures
   appeared — confirming that the lifecycle race is closed at the fixture level. This
   matches audit Section 5's prediction at line 1244-1267.

2. **4.2 INCREASED (150 → 188, +25.3%):** This was anticipated. The audit explicitly noted
   at lines 1272-1281 that once 4.1 is fixed, "gw15 will now open connections, potentially
   reducing the per-worker peak from 3 to 2 (or perturbing other workers into the cascade
   window)." The observed drift confirms the "perturb other workers" branch — total
   demand rose because a previously-silent worker now participates fully.

3. **4.3 INCREASED (87 → 172, +97.7%):** The largest drift. Cause: gw15 completing setup
   means 16 workers (not 15) are concurrently in test-execution phases, raising the
   probability of in-test connection-acquisition races. The doubling is consistent with
   adding ~6.7% more active workers (gw15 of 15) producing a non-linear demand spike at
   the `max_connections=30` ceiling.

4. **4.4 essentially flat (+2):** Teardown contention is a narrow window. The small rise
   tracks the 4.2 rise (same exception family). Expected to fall to 0 once 4.2's
   structural fix lands (audit Section 5 line 1303-1305).

5. **4.5 fell (−1):** The pre-fix `AssertionError` from `test_endpoint_routes_vector_raster_and_vrt_entries_to_existing_queue`
   did not recur — consistent with the audit's hypothesis (Section 4.10) that it was a
   cascade-downstream effect of 4.1. The 1 residual is a different test
   (`test_bulk_delete_success`: `assert 1 == 2`) — also likely cascade-downstream.

**Total failure reduction:** 648 → 365 (−43.7%). The dominant category was fully closed,
but the secondary categories absorbed the freed cascade capacity rather than vanishing.
Structural fixes for 4.2 and 4.3 are required.

---

## Section 6 — Decision-point recommendation

```
DECISION: SPAWN-1088-03-AND-1088-04
```

**Rationale:**

- **4.1 RESOLVED:** Plan 1088-01's structured handler closes the dominant root cause.
  No further work on the lifecycle race; this category is owned by the regression pin
  at `backend/tests/test_fixture_isolation_v1020.py::test_lifecycle_retries_on_transient_too_many_clients`.

- **4.2 (188) > 50 threshold → SPAWN Plan 1088-03:** Structural fix for setup-phase
  contention. Per audit Section 5 lines 1283-1287, candidate approaches include
  (a) widening the stagger to 7-8s per worker (last worker at gw15 × 8 = 120s wall-clock
  cost vs. current 75s), (b) per-worker setup-phase semaphore serialising
  `_make_test_async_engine` + `_ensure_roles_and_admin`, or (c) retry-with-backoff inside
  `_make_test_async_engine` for `TooManyConnections` (mirror Plan 1088-01's helper shape).
  The planner for Plan 1088-03 chooses the shape.

- **4.3 (172) > 30 threshold → SPAWN Plan 1088-04:** Structural fix for in-test
  contention. Per audit Section 5 lines 1296-1299, candidate approach is a retry-with-backoff
  wrapper around `override_get_db` in the `client` fixture (conftest.py:503-505), so a
  transient `TooManyConnections` during request handling is retried at the session-factory
  level rather than failing the test.

- **4.4 (4)** — DEFER. Below any threshold; expected to resolve when 4.2 lands.

- **4.5 (1)** — DEFER. Single assertion failure, almost certainly cascade-downstream.
  Re-verify after 4.2/4.3 fixes land.

- **Plans 1088-03 and 1088-04 may proceed in any order or in parallel.** Each must
  independently preserve the sequential `failed == 0` baseline. Each must include its
  own re-measurement step inside the plan (or its own follow-up re-measure plan, at the
  planner's discretion) before its SUMMARY commit. The final close-out (Plan 1088-05 or
  successor) consolidates FI-02 / FI-03 / ROADMAP.md flips per TD-13.

---

## Section 7 — Reproducibility checklist

To re-run this re-measurement against a fresh stack:

1. `git rev-parse HEAD` — confirm SHA `cef2c788c72d79e1e76273150532b0b3469adb82` (or
   downstream descendant).
2. `docker compose ps db` — confirm `geolens-db-1` healthy on `127.0.0.1:5434`.
3. Drop stale per-worker test DBs:
   ```bash
   docker compose exec -T db psql -U geolens -d geolens -At -c "SELECT datname FROM pg_database WHERE datname LIKE 'geolens%test_gw%' OR datname LIKE 'geolens%test_master%';" > /tmp/v1020-remeasure-1088-01-stale-dbs.txt
   # generate DROP statements + execute
   ```
4. Run sequential baseline:
   ```bash
   cd /Users/ishiland/Code/geolens/backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) uv run pytest tests/ 2>&1 | tee /tmp/v1020-remeasure-1088-01-sequential-baseline.log
   ```
5. Run parallel suite with JUnit XML:
   ```bash
   cd /Users/ishiland/Code/geolens/backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) uv run pytest -n auto --junitxml=/tmp/v1020-remeasure-1088-01.xml tests/ 2>&1 | tee /tmp/v1020-remeasure-1088-01-xdist.log
   ```
6. Run the parser:
   ```bash
   python3 /tmp/v1020-remeasure-1088-01-parse.py
   ```

**Input artifacts:**

- `/tmp/v1020-remeasure-1088-01-stale-dbs.txt` — list of stale per-worker DBs (1 entry: `geolens_test_gw12_52765c65`)
- `/tmp/v1020-remeasure-1088-01-sequential-baseline.log` — sequential pytest log (3039/0/38 in 538.09s)
- `/tmp/v1020-remeasure-1088-01-xdist.log` — parallel pytest log (173 failed / 2680 passed / 194 errors in 348.43s)
- `/tmp/v1020-remeasure-1088-01.xml` — JUnit XML (well-formed; 3079 testcases / 173 failures / 192 errors)
- `/tmp/v1020-remeasure-1088-01-parse.py` — categorization helper (mirrors audit Section 1 Step-5 verbatim + adds `categorize()` function for the audit's Section 4 categories)
- `/tmp/v1020-remeasure-1088-01-inventory.json` — per-failure inventory (365 entries)
- `/tmp/v1020-remeasure-1088-01-categories.json` — per-category counts (4.1=0, 4.2=188, 4.3=172, 4.4=4, 4.5=1, total=365)

---

## Section 8 — Cross-references

- **Parent audit:** `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` (Phase 1087)
  — categories 4.1–4.5 defined in Section 4; pre-fix counts (407 / 150 / 87 / 2 / 2) are
  the comparison baseline used in Section 4 above.
- **Fix under measurement:** `.planning/phases/1088-fixture-isolation-fixes-regression-pins/1088-01-SUMMARY.md`
  (Phase 1088 Plan 01) — replaced the silent-swallow at `backend/tests/conftest.py:275-278`
  with a structured `OperationalError` handler.
- **Re-measure protocol source:** `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md`
  Section 5 (lines 1312-1328).
- **Decision thresholds:** `.planning/phases/1088-fixture-isolation-fixes-regression-pins/1088-CONTEXT.md`
  `<decisions>` — `4.2 spawn Plan 1088-03 if >= 50`, `4.3 spawn Plan 1088-04 if >= 30`,
  `4.4 + 4.5 defer unless rising significantly`.
- **REQUIREMENTS.md FI-02 / FI-03:** traceability flip is DEFERRED to the final close-out
  plan in Phase 1088 (likely 1088-05 or successor), per TD-13 `requirements_traceability_flip`
  rule. Not flipped by this plan — this plan is the decision gate, not the close-out.

---

*Phase: 1088-fixture-isolation-fixes-regression-pins*
*Plan: 02 (re-measure gate)*
*Captured: 2026-05-22*
