---
phase: 1094-cascade-spike
subsystem: testing
tags: [pytest, xdist, parallel, asyncpg, sqlalchemy, conftest, fixture-isolation, spike, audit, test-infra]
status: complete
plans: [1094-01-PLAN.md]
plan_summaries: [1094-01-SUMMARY.md]
requirements_completed: []  # PARA-01 (e) only — full PARA-01 closure (a/b/c/d) at Phase 1095
requirements_partial: [PARA-01 (e), PARA-02 (d)]
provides:
  - "Spike audit doc at .planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md identifying cascade surface, fix shape, WR-02 disposition, regression-pin shape"
  - "Pre-fix 3-run pytest -n auto baseline preserved at /tmp/v1022-1094-pre-fix-nauto-run{1,2,3}.{log,xml} for Phase 1095 post-fix delta comparison"
affects: [1095, 1096, 1097]
duration: ~25 min
completed: 2026-05-23
commit: 36f54f8a
---

# Phase 1094: Cascade Spike Summary

**Single-plan phase — direct rollup of Plan 01 SUMMARY.** The phase shipped one architectural audit doc reclassifying the v1021 carry-forward cascade surface.

## Plans

| # | Plan | Status | Commit | Detail |
|---|------|--------|--------|--------|
| 01 | [1094-01-PLAN.md](./1094-01-PLAN.md) | complete (spike deliverable) | `36f54f8a` | [1094-01-SUMMARY.md](./1094-01-SUMMARY.md) |

## Key Outcome

The plan-time hypothesis enumeration (CONTEXT.md H1-H5 + ROADMAP PARA-01 framing) anticipated the v1021 Phase 1093-02 Run 3 cascade shape (706 errors / 4787 `InvalidCatalogNameError` lines / per-worker DB CREATE/migrate). **The current HEAD `49625d27` does NOT reproduce that cascade.** A different, smaller surface (`_init_tile_pool_for_tests` direct `asyncpg.create_pool` contention) is now dominant on Runs 1/2/3 (distinct = 14/14/21; ICN frames = 0 across all runs).

The audit doc names:
- **Section 1.4** — dominant root cause: `_init_tile_pool_for_tests` in 3 sibling files bypasses all conftest.py retry envelopes
- **Section 3.2** — chosen fix shape: Shape A* — wrap `asyncpg.create_pool` in existing `_run_with_too_many_clients_retry` envelope at `backend/tests/conftest.py:359`
- **Section 4.3** — WR-02 disposition: INDEPENDENT — `_invoke_sleep_in_sync_context` only invoked from Category 4.3 engine-wrapper paths; observed cascade bypasses those entirely
- **Section 5.1** — regression-pin shape: `test_init_tile_pool_retries_on_transient_too_many_clients` + `test_init_tile_pool_retry_yields_event_loop_during_backoff` (also covers PARA-02 (b))

## Requirements Status

| Requirement | Status After Phase 1094 | Notes |
|-------------|-------------------------|-------|
| PARA-01 (a) ≤30 distinct deterministic | Deferred to Phase 1095 | Fix lands in Phase 1095 |
| PARA-01 (b) sequential 3055/0/38 | Preserved (no code changes) | Verified via 32-test pin subset spot-check |
| PARA-01 (c) -n 4 3054/0/38 | Not measured this phase | No code changes; assumed unchanged from v1021 close |
| PARA-01 (d) regression pin | Pin SHAPE proposed at Section 5.1; implementation deferred to Phase 1095 | |
| PARA-01 (e) spike audit doc | **SATISFIED** — `.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md` with `status: COMPLETE` | |
| PARA-02 (d) WR-02 prereq-for-PARA-01 disposition | **SATISFIED preliminary** — INDEPENDENT verdict at Section 4.3 | Full PARA-02 (a/b/c) deferred to Phase 1095 |
| HYG-01 | Out of scope (Phase 1096) | |
| CI-01 | Out of scope (Phase 1097) | |
| CLOSE-01 | Out of scope (Phase 1097) | |

REQUIREMENTS.md `[ ]` → `[x]` flip for PARA-01 + PARA-02 lands at Phase 1095 close per CONTEXT.md rule #2.

## Patterns Established

1. **Spike-discovery-reclassification pattern** — when measurement contradicts plan-time hypothesis enumeration, RECLASSIFY in the audit doc (don't force-fit observed evidence into anticipated framing). Audit Section 1.4 commits to a one-paragraph dominant root cause based on actual evidence.
2. **Hypothesis verdict family extension** — H1-H5 from plan + H6/H7 NEW from spike evidence; preserve all hypotheses with explicit verdicts (TRUE/FALSE/INCONCLUSIVE) so future planners see what was considered.
3. **WR-02 disposition by call-site map** — enumerate every caller of the suspect function + cross-reference against observed cascade traceback frames; INDEPENDENT vs PREREQUISITE follows directly from whether call sites intersect.
4. **Atomic-2-file docs commit pattern** — audit doc + plan SUMMARY.md only; out-of-phase-scope guard at commit time ensures no source-file edits leak from the spike.

## Next Phase

Phase 1095 (Cascade Fix + WR-02 Closure) — implement Shape A* + PARA-02 fix + regression pins; re-run `pytest -n auto` 3-run baseline for post-fix measurement.

---
*Phase: 1094-cascade-spike*
*Completed: 2026-05-23*
