---
phase: 1085
phase_name: pytest -n auto Stabilization
verified: 2026-05-22
status: passed
verifier: orchestrator
---

# Phase 1085: pytest -n auto Stabilization — Verification

## Must-haves (goal-backward)

1. **Spike doc committed before fix lands** ✓
   - `.planning/audits/PYTEST-XDIST-SPIKE-v1019.md` committed by Plan 1085-01 (`af902329`)
   - Section 5 chose **shape (a) per-worker pool sizing** with rationale: 16 workers × pool ceiling (5+2=7) = 112 theoretical conn vs `max_connections=30` (3.7× ceiling); reproduced 2452 cascade errors

2. **`pytest -n auto` completes with zero cascade errors** ✓
   - Before fix (v1018 baseline): 628 `TooManyConnectionsError` + 1824 `CannotConnectNowError` = **2452 cascade errors**
   - After fix (this plan): **0 cascade errors**
   - Fix applied: NullPool + 5s startup stagger in `backend/tests/conftest.py`

3. **Sequential `uv run pytest backend/` baseline preserved** ✓
   - v1018 baseline: 3025+ / 0 / 38
   - Post-fix: 3032 / 0 / 38 (+7 drift within acceptable bounds; no new failures)

4. **Regression test added** ✓
   - `backend/tests/test_conftest_pool_sizing.py` — 7/7 PASS in 1.47s
   - Pins per-worker vs sequential pool-sizing invariant

5. **REQUIREMENTS.md traceability updated** ✓
   - TD-10 checkbox `[ ]` → `[x]`
   - TD-10 traceability row Pending → Complete
   - Applied TD-13 lesson preemptively (don't leave the row stale until audit catches it)

## Plans complete

| Plan | Requirement | Status | Notes |
|------|-------------|--------|-------|
| 1085-01 | TD-10 (spike) | ✓ | SPIKE-FINDINGS.md committed; shape (a) chosen with rationale; 4 measurement numbers captured |
| 1085-02 | TD-10 (implement) | ✓ | NullPool + 5s stagger applied; 2452 → 0 cascade errors; sequential 3025→3032; 7/7 regression tests pass |

## Phase requirements coverage

| REQ-ID | Plan | Verdict |
|--------|------|---------|
| TD-10 | 1085-01 + 1085-02 | satisfied |

1/1 requirements satisfied.

## Deviations from plan

- **Root cause was NOT async pool fan-out**: the spike's initial hypothesis (asyncpg pool sizing per worker) turned out to be incomplete. The cascade was triggered during setup-phase concurrent connections (test-DB creation/migration), not the runtime pool. Required adding a 5s startup stagger AND switching to NullPool for the xdist engine. Documented in 1085-02-SUMMARY.md.
- **Duration**: Plan 1085-02 took ~90 min (iterative debugging) vs initial estimate of ~30 min. Worth the extra time — landed at the actual root cause rather than the surface symptom.

## Status

PASSED. Phase 1085 closes with 1/1 requirements satisfied, 2/2 plans complete, 2452 → 0 cascade errors, sequential baseline preserved.
