---
phase: 1088-fixture-isolation-fixes-regression-pins
plan: 02
subsystem: testing
type: re-measure-gate

tags:
  - pytest
  - pytest-xdist
  - re-measurement
  - fixture-isolation
  - decision-gate
  - audit
  - v1020

# Dependency graph
requires:
  - phase: 1088-fixture-isolation-fixes-regression-pins
    plan: 01
    provides: "Structured OperationalError handler at conftest.py:275-278 (replaces silent-swallow); category 4.1 closed (407 → 0)"
  - phase: 1087-xdist-fixture-isolation-audit
    provides: "Audit Section 1 Step-5 JUnit XML parser (reused verbatim) + Section 4 category definitions (4.1/4.2/4.3/4.4/4.5)"

provides:
  - "Post-1088-01 re-measurement under pytest -n auto (365 total failures vs. 648 pre-fix; −43.7%)"
  - "Per-category drift table: 4.1 (407 → 0), 4.2 (150 → 188), 4.3 (87 → 172), 4.4 (2 → 4), 4.5 (2 → 1)"
  - "Machine-readable DECISION line consumed by Phase 1088 downstream planners: SPAWN-1088-03-AND-1088-04"
  - "Audit doc cross-referencing parent (PYTEST-XDIST-FIXTURE-AUDIT-v1020.md) + reproducibility checklist"

affects:
  - 1088-03-setup-contention-structural-fix
  - 1088-04-in-test-contention-structural-fix
  - 1088-N-final-close-out

# Tech tracking
tech-stack:
  added: []  # No new dependencies — pure measurement plan
  patterns:
    - "Audit re-measurement gate — separate plan from the structural fix it measures, so the post-fix counts attribute cleanly to a single commit boundary (Plan 1088-01's `cef2c788`)"
    - "Categorization parser reuse — the audit's Section 1 Step-5 JUnit XML parser is consumed verbatim by the re-measure, ensuring post-fix counts are directly comparable to the audit's Section 4 pre-fix counts without re-categorization drift"
    - "Decision-line as machine-readable contract — the `DECISION:` line in the audit doc is parsed by downstream planner pre-execution gates, making the conditional-plan-spawn logic auditable rather than a planner judgment call"

key-files:
  created:
    - ".planning/audits/PYTEST-XDIST-REMEASURE-AFTER-1088-01.md"
  modified: []
  # No code changes in this plan — audit doc only.

key-decisions:
  - "DECISION: SPAWN-1088-03-AND-1088-04 — both 4.2 (188) and 4.3 (172) exceed their respective spawn thresholds (50 and 30). Cascade did not transitively resolve the secondary categories; gw15's newly-functioning setup phase shifted demand into 4.2/4.3 rather than reducing total demand."
  - "REQUIREMENTS.md FI-02 / FI-03 traceability flip is DEFERRED to the final close-out plan in Phase 1088 (likely 1088-05 or successor) per CONTEXT.md LOCKED sequencing and the TD-13 `requirements_traceability_flip` rule. This plan is the decision gate, not the close-out."
  - "Sequential baseline gate enforced before parallel re-measure — 3039/0/38 in 538.09s confirms Plan 1088-01 did not regress sequential mode (HARD GATE per audit Section 1 Step 2)."
  - "Background pg_stat_activity sampler (audit Section 1 Step 3) was OPTIONAL and skipped this run — the categorization parser consumes JUnit XML only, and sampler output is advisory for cascade-timing investigation (deferred to Plans 1088-03/04 if they need the sampler signal to validate their chosen fix shape)."

patterns-established:
  - "Re-measure-after-fix as a separate plan — keeps the structural-fix commit boundary clean for `git bisect` / cross-category attribution. Applicable to any future cascade-class fix where the post-fix drift across non-targeted categories is itself the input to a downstream conditional plan."
  - "Decision-line machine-readable contract — when a plan's primary deliverable is a recommendation that drives conditional-plan spawning, write the recommendation as a single grep-able line (`DECISION: <ENUM>`) so downstream planners can gate on it without parsing freeform prose."

requirements-completed: []
# FI-02 is partially supported by this plan (the re-measurement is the input to the
# eventual FI-02 close) but the REQUIREMENTS.md flip is DEFERRED to the final close-out
# plan in Phase 1088 per TD-13 `requirements_traceability_flip` rule.

# Metrics
duration: ~16 min (work) + ~9 min (sequential baseline) + ~6 min (parallel run) ≈ 31 min total
completed: 2026-05-22
---

# Phase 1088 Plan 02: pytest -n auto Re-Measurement After Silent-Swallow Fix Summary

**Re-measured `pytest -n auto` against HEAD `cef2c788` (post-Plan-1088-01) and categorized residual failures using the audit's Section 1 Step-5 JUnit XML parser. Category 4.1 (per-worker DB lifecycle race) dropped from 407 → 0 (resolved). Categories 4.2 (setup contention) and 4.3 (in-test contention) both exceeded their spawn thresholds: 150 → 188 (4.2) and 87 → 172 (4.3). DECISION: SPAWN-1088-03-AND-1088-04. Audit doc at `.planning/audits/PYTEST-XDIST-REMEASURE-AFTER-1088-01.md`; no code changes.**

## Performance

- **Duration:** ~31 min total (16 min executor work + 9 min sequential baseline + 6 min parallel run; no overlap)
- **Sequential baseline:** `3039 passed, 38 skipped, 14 deselected, 18 warnings in 538.09s (0:08:58)` — verbatim from `/tmp/v1020-remeasure-1088-01-sequential-baseline.log`
- **Parallel run:** `173 failed, 2680 passed, 36 skipped, 10 warnings, 194 errors in 348.43s (0:05:48)` — verbatim from `/tmp/v1020-remeasure-1088-01-xdist.log`
- **Started:** 2026-05-22 (single-session execution)
- **Completed:** 2026-05-22
- **Tasks:** 4 (drop stale DBs + sequential gate; parallel run + categorize; write audit doc; SUMMARY + commit)
- **Files modified:** 2 (1 new audit doc + this SUMMARY — no code)

## Accomplishments

- Sequential baseline gate verified — Plan 1088-01's structural fix did not regress sequential mode. 3039 passed / 0 failed / 38 skipped (matches Plan 1088-01 floor; +3 over v1019 3036 floor).
- Parallel `pytest -n auto` re-measured against HEAD `cef2c788`. JUnit XML well-formed (3079 testcases / 173 failures / 192 errors). Sanity gate: `PASS: 365 / 365 use backend/tests/ prefix`.
- Categorization parser (`/tmp/v1020-remeasure-1088-01-parse.py`) wraps the audit's Section 1 Step-5 helper VERBATIM and adds a `categorize()` function for the audit's Section 4 categories. Per-category counts:

  | Category | Pre-fix | Post-fix | Delta | Disposition |
  |----------|---------|----------|-------|-------------|
  | 4.1 lifecycle race | 407 | 0 | −407 | **RESOLVED** |
  | 4.2 setup contention | 150 | 188 | +38 | **SPAWN-1088-03** (>= 50) |
  | 4.3 in-test contention | 87 | 172 | +85 | **SPAWN-1088-04** (>= 30) |
  | 4.4 teardown contention | 2 | 4 | +2 | DEFER (document only) |
  | 4.5 sandbox/assertion | 2 | 1 | −1 | DEFER (document only) |
  | **Total** | 648 | 365 | −283 (−43.7%) | |

- Audit doc `.planning/audits/PYTEST-XDIST-REMEASURE-AFTER-1088-01.md` written with: machine-readable `DECISION: SPAWN-1088-03-AND-1088-04` line; verbatim summary lines from both logs; full pre/post comparison table; cross-category drift commentary explaining the +85 4.3 rise as expected cascade-shift; reproducibility checklist naming all 7 input artifacts.

## Task Commits

Per the plan's Task 4 instruction, Tasks 3+4 deliverables ship together in a SINGLE commit to keep the audit doc + its SUMMARY atomic. The single commit subject is `docs(1088-02): re-measure after silent-swallow fix; SPAWN-1088-03-AND-1088-04`.

1. **Task 1: Drop stale per-worker DBs + sequential baseline gate** — measurement-only step; no commit. Stale DB count: 1 (`geolens_test_gw12_52765c65` dropped). Sequential baseline log file written to `/tmp/v1020-remeasure-1088-01-sequential-baseline.log`. `failed == 0` ✅.
2. **Task 2: Run pytest -n auto + categorize** — measurement-only step; no commit. JUnit XML + inventory JSON + categories JSON written to `/tmp/v1020-remeasure-1088-01-*`. Sanity gate passed (`365 / 365 use backend/tests/ prefix`).
3. **Task 3: Write re-measure audit doc** — bundled into single commit (docs).
4. **Task 4: SUMMARY + commit** — the single commit itself (docs).

## Files Created/Modified

- `.planning/audits/PYTEST-XDIST-REMEASURE-AFTER-1088-01.md` — NEW FILE. Frontmatter cites HEAD SHA, parent audit, decision branch, sequential + parallel summary lines. 8 sections (decision line + methodology + sequential gate + parallel result + per-category table + drift commentary + decision-point recommendation + reproducibility checklist + cross-references). 
- `.planning/phases/1088-fixture-isolation-fixes-regression-pins/1088-02-SUMMARY.md` — NEW FILE (this file).

No code changes — `git diff-tree --no-commit-id --name-only -r HEAD` for the commit shows ONLY these two files.

## Decisions Made

- **`DECISION: SPAWN-1088-03-AND-1088-04`** — both 4.2 (188) and 4.3 (172) exceed their thresholds. Plan 1088-03 owns the 4.2 setup-contention structural fix (audit Section 5 lines 1283-1287 names three candidate approaches: widen stagger, semaphore, retry-with-backoff). Plan 1088-04 owns the 4.3 in-test-contention structural fix (audit Section 5 lines 1296-1299 suggests retry-with-backoff around `override_get_db`). The two plans may proceed in parallel or in any order; each independently preserves the sequential baseline.
- **`pytest.skip` for unreachable hosts preserved verbatim** — Plan 1088-01's structured handler still skips on non-`TooManyConnections` `OperationalError`. This re-measurement confirms no skip-related regression (skipped count = 36 in parallel mode, 38 sequential — unchanged from pre-fix run pattern). No action needed.
- **Background pg_stat_activity sampler skipped this run.** The audit's Section 1 Step 3 sampler is optional; the categorization parser consumes JUnit XML only. The sampler signal is advisory for cascade-timing investigation; Plans 1088-03 and 1088-04 may re-enable it if their chosen fix shape requires the timing data.
- **REQUIREMENTS.md FI-02 / FI-03 traceability flip is DEFERRED to Plan 1088-N per TD-13.** This plan ships ONLY the audit doc + SUMMARY. The traceability flip lives in the final close-out plan in Phase 1088, per CONTEXT.md LOCKED sequencing.

## Deviations from Plan

**None — plan executed exactly as written.** Sequential baseline gate passed on first try; parallel run completed without interruption; categorization produced the expected category-4.1 = 0 result. The DECISION branch (`SPAWN-1088-03-AND-1088-04`) is the natural outcome of the measured counts against the thresholds in CONTEXT.md and the plan `<objective>` section.

## Issues Encountered

- **xdist final summary vs JUnit XML count mismatch (2 errors):** The tee'd pytest log reports `194 errors`; the JUnit XML reports `192 errors`. Per audit Section 1 Step-5 design, JUnit XML is the authoritative artifact (the terminal summary occasionally lists some fixture-teardown errors as separate lines while JUnit pairs them with the failing testcase). Total classified = 365 = 173 + 192 (JUnit-authoritative). Not a regression or bug — documented in the audit doc Section 3.
- **Single stale per-worker DB found in pre-measurement cleanup.** Pre-existing from Plan 1088-01's sequential baseline run (gw12 was killed mid-teardown when the executor moved to commit). Dropped idempotently; no impact on measurement.

## Cross-Category Drift Highlights

(Full table + commentary in audit doc Sections 4 and 5.)

The most informative drift was 4.3 (in-test contention) nearly doubling from 87 → 172. Mechanism: with gw15 no longer silently failing setup, all 16 workers are now concurrently in test-execution phase, raising the probability of in-test connection-acquisition races against `max_connections=30`. This is the exact "cascade shift" the audit predicted in Section 5 (lines 1272-1287) — the FIX for 4.1 doesn't reduce TOTAL demand, it shifts demand from "gw15 fails all its setups" to "16 workers concurrently competing for connections during test bodies."

The Plan 1088-04 planner should anticipate that the 4.3 fix is the highest-leverage remaining structural change. Audit Section 5's suggested approach (retry-with-backoff wrapper around `override_get_db` at conftest.py:503-505) is consistent with Plan 1088-01's `_create_test_db_with_retry` extraction pattern.

## Sequential Baseline Preservation HARD GATE

Verbatim from `/tmp/v1020-remeasure-1088-01-sequential-baseline.log`:

```
=== 3039 passed, 38 skipped, 14 deselected, 18 warnings in 538.09s (0:08:58) ===
```

- **M failed = 0** — invariant satisfied (non-negotiable per plan + CONTEXT.md).
- **N passed = 3039** — matches Plan 1088-01 floor (+3 over v1019 3036 from Plan 1088-01's regression-pin file).
- **K skipped = 38** — unchanged.

## Partial-Close Notes for FI-02 / FI-03

- **FI-02:** Plan 1088-01 closed category 4.1 structurally (407 failures → 0). This re-measurement quantifies cross-category drift and routes the remaining 4.2/4.3 work to Plans 1088-03 and 1088-04. Full close of FI-02 depends on Plans 1088-03 + 1088-04 landing structural fixes that bring 4.2 and 4.3 below threshold. REQUIREMENTS.md flip is DEFERRED to the final close-out plan (1088-N) per TD-13 `requirements_traceability_flip` rule.
- **FI-03:** Plan 1088-01 landed the category-4.1 regression pin at `backend/tests/test_fixture_isolation_v1020.py::test_lifecycle_retries_on_transient_too_many_clients`. Pins for 4.2 and 4.3 are owned by Plans 1088-03 and 1088-04 (per audit Section 5 lines 1340-1351). REQUIREMENTS.md flip lives in 1088-N.

## Deferred to Plans 1088-03 / 1088-04 / 1088-N

- **Plan 1088-03 (setup-phase contention structural fix)** — UNBLOCKED. Audit Section 5 candidate approaches: (a) widen stagger to 7-8s, (b) per-worker setup semaphore, (c) retry-with-backoff in `_make_test_async_engine`. Planner picks shape during execution.
- **Plan 1088-04 (in-test contention structural fix)** — UNBLOCKED. Audit Section 5 suggested approach: retry-with-backoff wrapper around `override_get_db` at conftest.py:503-505. Planner may consume Plan 1088-01's `_create_test_db_with_retry` helper as a reuse target.
- **Plan 1088-N (final close-out)** — depends on Plans 1088-03 + 1088-04 completing. Owns: final re-measurement; FI-02 + FI-03 + ROADMAP.md Phase 1088 traceability flips in a single commit per TD-13.

## Self-Check: PASSED

- `.planning/audits/PYTEST-XDIST-REMEASURE-AFTER-1088-01.md` exists. Contains: `DECISION: SPAWN-1088-03-AND-1088-04`; pre-fix counts 407 / 150 / 87 / 2 / 2; post-fix counts 0 / 188 / 172 / 4 / 1; cross-reference to parent audit + Plan 1088-01 SUMMARY; reproducibility checklist.
- `/tmp/v1020-remeasure-1088-01.xml` exists and is well-formed (3079 testcases; 173 failures + 192 errors).
- `/tmp/v1020-remeasure-1088-01-categories.json` exists with keys `4.1, 4.2, 4.3, 4.4, 4.5, total`.
- Sequential `pytest tests/` baseline: 3039 passed / 0 failed / 38 skipped — invariant preserved.
- REQUIREMENTS.md NOT modified in this commit (deferred to Plan 1088-N).

## Next Phase Readiness

- **Plans 1088-03 and 1088-04 are UNBLOCKED.** The decision-line `DECISION: SPAWN-1088-03-AND-1088-04` is machine-readable at the top of the audit doc; downstream planner pre-execution gates can grep for it.
- **No code blockers.** Plans 1088-03 and 1088-04 may proceed in parallel or in any order. Each plan independently preserves the sequential baseline gate and re-measures cross-category drift in its own SUMMARY per audit Section 5 protocol.
- **`_create_test_db_with_retry` helper from Plan 1088-01 is consumable** by any retry-with-backoff approach in Plans 1088-03 / 1088-04 (per Plan 1088-01's `affects: 1088-N-requirements-flip, 1089-ci-wiring` note).

---

*Phase: 1088-fixture-isolation-fixes-regression-pins*
*Plan: 02*
*Completed: 2026-05-22*
