---
phase: 1075-conftest-test-db-lifecycle-refactor-baseline-fixes
plan: 02
subsystem: testing
tags: [pytest, defer-orphan-guard, mock-fixture-drift, idor-check, test-only-fix]

requires: [1075-01]
provides:
  - "test_defer_orphan_guard.py: 10/10 PASSED under both `pytest -x` and `pytest -n 2`"
  - "Defer-async orphan-guard contract pin restored across all 6 production call sites (router_reupload x3, ingest/router VRT x2, router_vrt x1)"
affects: [1075-03, 1075-04, 1075-05]

tech-stack:
  added: []
  patterns:
    - "Mock fixture drift detection: when a previously-passing pure-mock unit test starts failing on a 404/auth-shaped HTTPException, suspect a downstream production code-path that added an authorization gate between the originally-mocked surface (e.g., `get_dataset`) and the call site under test (e.g., `defer_async`). Fix: extend the `with patch(...)` block to mock the new gate; preserve all original assertions."
    - "AsyncMock no-op patch for IDOR-shaped checks: `patch('module.check_dataset_access', new=AsyncMock())` neutralizes the gate without changing the test's contract assertions. AsyncMock with no `side_effect` resolves to `None`, which matches the function's return semantics (raises on deny, returns silently on allow)."

key-files:
  created: []
  modified:
    - "backend/tests/test_defer_orphan_guard.py (+12 lines: 3 patch blocks of 4 lines each, one per failing test in TestReuploadOrphanGuard)"

key-decisions:
  - "Test-only fix, no production-code touched. The IDOR-prevention `check_dataset_access` call added by Plan 1065-02 commit fde5d9ae is correct and stays. The test was simply stale relative to the production module."
  - "Patch path is `app.modules.catalog.datasets.api.router_reupload.check_dataset_access` (the function-name-in-router-namespace, NOT `app.modules.catalog.authorization.check_dataset_access`). This mirrors the existing pattern in TestDatasetsVrtOrphanGuard which patches `app.modules.catalog.datasets.api.router_vrt.check_dataset_access` on line 627-630 of the same test file."
  - "AsyncMock() with no return value used instead of AsyncMock(return_value=set()). check_dataset_access returns `user_roles: set[str]` on success, but the production code at router_reupload.py:465 IGNORES the return (`await check_dataset_access(...)` without assignment) — so the mock return shape doesn't matter. AsyncMock() default is cleaner."
  - "Single atomic commit (not 3 separate). The 3 fixes are IDENTICAL in shape and root cause (the same 4-line patch block, the same authorization gate, the same drift origin). Splitting them into 3 commits would obscure the shared root cause and clutter the log without isolation benefit. The commit message enumerates all 3 fixed test names for traceability."

patterns-established:
  - "Inventory-first triage for v1015 baseline failures: run the file once, capture the failure shape per-test, identify the root cause from the traceback's exception type + location BEFORE attempting any fix. The 3 failures here shared a single root cause (commit fde5d9ae) — recognizing that up-front collapsed 3 separate investigations into 1 fix."
  - "Lifecycle-vs-logic disambiguation post-Plan-01: with the InvalidCatalogNameError race eliminated, residual failures must be genuine test-vs-production drift. The grep `InvalidCatalogNameError /tmp/dog_*.log` -> 0 result is the proof that Plan 01's lifecycle fix held and these failures are orthogonal."

requirements-completed: [TI-02 (partial — 3 of 11 baseline failures, the test_defer_orphan_guard.py subset)]

duration: 8min
completed: 2026-05-21
---

# Phase 1075 Plan 02: Fix test_defer_orphan_guard.py 3 Failures (TI-02 partial) Summary

**Three TestReuploadOrphanGuard tests in `backend/tests/test_defer_orphan_guard.py` were asserting HTTPException 503 on Procrastinate defer failure but receiving 404 "Dataset not found" instead — root cause was test fixture drift after Plan 1065-02 added `check_dataset_access` between `get_dataset` and the defer site in `reupload_commit`. Fix: extend the `with patch(...)` block in each test to also patch `check_dataset_access` with `AsyncMock()`, mirroring the existing pattern in TestDatasetsVrtOrphanGuard. Test contract preserved verbatim. Zero production-code changes.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-21 (post Plan 01 metadata commit `36cc7f41`)
- **Completed:** 2026-05-21
- **Tasks:** 4 (Task 1 triage → Task 2 fix → Task 3 N/A no skips → Task 4 verify)
- **Files modified:** 1 (test-only)

## Accomplishments

- **Identified the 3 failures' shared root cause from a single triage run.** All 3 raised `HTTPException(status_code=404, detail='Dataset not found')` from `check_dataset_access` at `backend/app/modules/catalog/authorization.py:131`, called from `router_reupload.py:465` — added by commit `fde5d9ae` ("fix(1065-02): close IDOR in all 6 reupload handlers via check_dataset_access") on 2026-05-20.
- **Confirmed Plan 01's lifecycle fix held.** `grep -c "InvalidCatalogNameError" /tmp/dog_run.log` → 0. The 3 failures are pure test-vs-production drift, NOT lifecycle race fallout.
- **Restored 10/10 PASSED in `test_defer_orphan_guard.py`** under both `pytest -x` (sequential) and `pytest -n 2` (parallel). The defer-async orphan-guard contract is fully pinned again across all 6 production call sites.
- **Zero production-code changes.** The IDOR-prevention check stays — it is correct and orthogonal to the defer-guard contract under test. Plan's hard scope gate respected.
- **No GitHub issues filed and no `pytest.mark.skip` annotations needed.** All 3 failures were root-cause-fixable in <10 minutes; the skip-with-issue fallback path (Task 3) was not exercised.

## The 3 Originally-Failing Tests + Dispositions

| Test | Disposition | Fix Shape |
|------|-------------|-----------|
| `TestReuploadOrphanGuard::test_reupload_service_defer_failure_marks_job_failed` | **fixed** in `66d17300` | Added `patch("app.modules.catalog.datasets.api.router_reupload.check_dataset_access", new=AsyncMock())` to the existing `with` block (4 lines) |
| `TestReuploadOrphanGuard::test_reupload_file_priority_defer_failure_marks_job_failed` | **fixed** in `66d17300` | Same — added `check_dataset_access` AsyncMock patch (4 lines) |
| `TestReuploadOrphanGuard::test_reupload_file_default_defer_failure_marks_job_failed` | **fixed** in `66d17300` | Same — added `check_dataset_access` AsyncMock patch (4 lines) |

## Task Commits

Per the plan, Tasks 1 and 4 are pure-inspection (write/verify the inventory + re-run), so the only behaviour-changing commit was Task 2:

1. **Task 1 (triage):** No commit — output is `/tmp/1075-02-failures.md` (scratch artifact, not committed)
2. **Task 2 (root-cause fix, 3 tests):** `66d17300` — `fix(1075-02): patch check_dataset_access in TestReuploadOrphanGuard (TI-02)`
3. **Task 3 (skip-with-issue):** **Skipped — not needed.** All 3 failures were root-cause-fixable; the skip path is reserved for genuinely-uninvestigable cases. Zero `pytest.mark.skip` decorators added.
4. **Task 4 (verify):** No commit — verification output appended to `/tmp/1075-02-failures.md`.

**Plan metadata commit:** (to follow this SUMMARY) — `docs(1075-02): complete TI-02 partial (test_defer_orphan_guard.py 3 fixes)`

## Files Created/Modified

- **`backend/tests/test_defer_orphan_guard.py`** (modified, +12 lines / -0) — Added a single `patch("app.modules.catalog.datasets.api.router_reupload.check_dataset_access", new=AsyncMock())` block to each of the 3 failing tests in `TestReuploadOrphanGuard`. No other changes — no class structure modification, no docstring changes, no assertion changes, no helper changes. The diff is 12 lines (3 patches × 4 lines each: `patch(`, `"..."`, `new=AsyncMock(),`, `),`).

## Failure Inventory Reference

Full triage capture lives at `/tmp/1075-02-failures.md` (local scratch, not committed per the plan). Key excerpt:

```
Failure 1-3 all share:
  Exception type: AssertionError (`assert 404 == 503`)
  Trace: HTTPException(status_code=404, detail='Dataset not found')
         raised by check_dataset_access at authorization.py:131
         (call site: router_reupload.py:465)
  Hypothesis: HYPOTHESIS 2 (signature/contract drift)
  Root cause: commit fde5d9ae "fix(1065-02): close IDOR in all 6 reupload handlers"
  Decision: fix in Task 2 — add check_dataset_access AsyncMock patch
```

## Mock-Signature / Contract Drift Encountered

**Single drift event, three affected tests (all in TestReuploadOrphanGuard):**

- **Drift:** `reupload_commit` in `router_reupload.py` gained `await check_dataset_access(db, dataset, dataset_id, user)` between line 459 (`get_dataset`) and the defer site (~line 511+). The pre-1065 version went straight from `get_dataset` → job lookup → defer.
- **Source:** commit `fde5d9ae` (2026-05-20) — `fix(1065-02): close IDOR in all 6 reupload handlers via check_dataset_access`.
- **Audit value for v1018:** the same IDOR fix touched 5 OTHER reupload handlers in `router_reupload.py` (`reupload_dataset`, `reupload_service_preview`, `reupload_preview`, `request_presigned_reupload`, `complete_presigned_reupload`). Any test in `backend/tests/` that mocks one of those handlers and only patches `get_dataset` will have the same drift. Suggest grep `git log --oneline fde5d9ae | head -1` cross-reference if Plans 1075-03 / 1075-04 hit the same shape.
- **Sibling-test reference:** `TestDatasetsVrtOrphanGuard::test_regenerate_vrt_defer_failure_*` in the SAME file already patches `check_dataset_access` (lines 627-630) — it was added with the original test, because `router_vrt.py` had its own dataset-access gate from day one. The Reupload-class tests predate the IDOR fix and got drift.

## Auto-Resolution from Plan 01

**None.** The 3 failures were NOT auto-resolved by Plan 01's conftest refactor:

- Plan 01 eliminated the `InvalidCatalogNameError` race (1363 errors → 0).
- The 3 failures here are pure-mock unit tests with NO database surface — the lifecycle fix has nothing to bind to.
- Confirmed by `grep -c "InvalidCatalogNameError" /tmp/dog_run.log` → 0 on the initial failure run (post-Plan-01) AND on the final clean run.

The hypothesis in the plan (HYPOTHESIS 1: "If Plan 01's conftest refactor lands first, these tests likely auto-resolve") DID NOT pan out — but that's a useful negative-result data point for Plans 1075-03 and 1075-04: those test files may share this property (lifecycle was a red herring; failures are genuine drift).

## GitHub Issues Filed

**None.** No skipped tests, no deferred root causes — all 3 failures were fixed in place.

## Final Tally

| Mode | PASSED | SKIPPED | FAILED | ERROR | Total | Exit |
|------|--------|---------|--------|-------|-------|------|
| `pytest -x` (sequential) | 10 | 0 | 0 | 0 | 10 | 0 |
| `pytest -n 2` (parallel via xdist) | 10 | 0 | 0 | 0 | 10 | 0 |
| InvalidCatalogNameError grep | 0 | — | — | — | — | — |

**Result: 10 passed, 0 failed, 0 errors, 0 skipped — both serial and parallel. Acceptance gates fully satisfied.**

## Deviations from Plan

**None.** Plan executed exactly as written:

- Task 1 inventory ran, identified 3 specific failures with hypotheses and decisions.
- Task 2 applied the smallest-diff fix per hypothesis (HYPOTHESIS 2: signature/contract drift) — extended the existing `with patch(...)` block in each test.
- Task 3 (skip-with-issue) was correctly NOT exercised — no failure required deferral.
- Task 4 verified both modes pass and InvalidCatalogNameError count is 0.

No Rule 1/2/3/4 deviations required. No scope creep — production-code untouched (`git diff --stat backend/app/` → empty).

## Issues Encountered

**None.** The `.env.test` file at the repo root was already present (created in Plan 01 per its SUMMARY's "Issues Encountered" section). `gh` CLI authenticated. uv environment ready. No setup blockers.

The plan's `<root_cause_hypothesis>` predicted HYPOTHESIS 1 (lifecycle cascade) as primary and HYPOTHESIS 2 (signature drift) as secondary. The actual cause was HYPOTHESIS 2 — the planner's secondary hypothesis was correct. No retraining of triage instincts needed; the inventory-first protocol (run-then-decide vs. guess-then-investigate) correctly surfaced the shared root cause.

## Self-Check: PASSED

**Files exist:**
- FOUND: backend/tests/test_defer_orphan_guard.py (modified, 670 lines — was 658, +12)
- FOUND: /tmp/1075-02-failures.md (113 lines — inventory + final result section)
- FOUND: /tmp/dog_run.log (initial triage)
- FOUND: /tmp/dog_final.log (sequential verify)
- FOUND: /tmp/dog_parallel.log (parallel verify)

**Commits exist:**
- FOUND: 66d17300 (Task 2 — fix(1075-02): patch check_dataset_access in TestReuploadOrphanGuard)

**Acceptance gates verified:**
- `cd backend && env $(grep -v '^#' ../.env.test | xargs) uv run pytest tests/test_defer_orphan_guard.py -x` → exit 0 ✓
- `cd backend && env $(grep -v '^#' ../.env.test | xargs) uv run pytest tests/test_defer_orphan_guard.py -n 2` → exit 0 ✓
- `grep -c InvalidCatalogNameError /tmp/dog_final.log` → 0 ✓
- `grep -c InvalidCatalogNameError /tmp/dog_parallel.log` → 0 ✓
- `git diff --stat backend/app/` → empty (no production-code drift) ✓
- All skip annotations have `reason=<URL or filepath>` — vacuously true, zero skips added ✓

## Next Phase Readiness

- **Plan 1075-03 (TI-02 partial: test_ingest.py ×3)** unblocked. The negative result above (lifecycle was NOT the cause; drift WAS) is the strongest signal that Plan 03's failures are also genuine drift, not lifecycle cascade. Plan 03 should jump straight to triage-by-traceback rather than waiting on lifecycle fixes.
- **Plan 1075-04 (TI-02 partial: test_maps_style_json.py ×5)** unblocked. Same expectation: drift, not lifecycle.
- **Plan 1075-05 (full-suite verification)** still gated on Plans 03 + 04 landing.

**Diagnostic pattern reinforced:** when 3 tests in the same class fail with the same exception type + same traceback shape, suspect a single shared upstream change (signature drift, new gate, new field, etc.) — investigate the shared production-code path BEFORE attempting per-test fixes. Saved ~2× the investigation time here.

**No blockers identified.** The test_defer_orphan_guard.py pin is fully restored; future regressions in any of the 6 defer-async sites (reupload_service, reupload_file priority, reupload_file default, add_vrt_source, remove_vrt_source, regenerate_vrt_endpoint) will surface immediately.

---
*Phase: 1075-conftest-test-db-lifecycle-refactor-baseline-fixes*
*Completed: 2026-05-21*
