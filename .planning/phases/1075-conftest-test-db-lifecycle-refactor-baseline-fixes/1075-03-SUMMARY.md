---
phase: 1075-conftest-test-db-lifecycle-refactor-baseline-fixes
plan: 03
subsystem: testing
tags: [pytest, test-ingest, mock-signature-drift, ssrf-revalidation, test-only-fix]

requires: [1075-01]
provides:
  - "test_ingest.py: 39/39 PASSED under both `pytest -x` and `pytest -n 2`"
  - "Two distinct production-code drift sources documented and dispositioned at the test surface: (1) `save_upload_file()` max_size_bytes kwarg from Phase 1066 feat IA-P0-02, (2) commit-time `validate_url_for_ssrf` re-validation from Phase 1066 feat IA-P0-03"
affects: [1075-04, 1075-05]

tech-stack:
  added: []
  patterns:
    - "Mock-side-effect signature drift detection: when a previously-passing pure-mock unit test starts returning HTTP 500 (broad-except-wrapped TypeError) but the production endpoint is unchanged-by-contract, the AsyncMock's `side_effect` callable has likely fallen behind a kwarg addition at the production call site. Fix: widen the side_effect signature with `**_` so the mock silently absorbs future kwargs the test does not exercise."
    - "Lazy-import patch target rule: when production code uses `from x.y.z import fn` INSIDE a function body, the symbol is re-bound on every call from the source module — patching the caller's namespace (e.g. `app.processing.ingest.router.fn`) has no effect because the symbol is not stable in that namespace. Patch the defining module instead (e.g. `app.modules.catalog.sources.security.validate_url_for_ssrf`). Mirrors the Plan 1075-02 `check_dataset_access` lesson."

key-files:
  created: []
  modified:
    - "backend/tests/test_ingest.py (+29 / -10 = 19 net lines: 6 lines in mock_file_save fixture for `**_` kwarg + 23 lines wrapping the service-commit dispatch test in a `with patch(...)` block. Two atomic commits.)"

key-decisions:
  - "Test-only fix, no production-code touched. The Phase 1066 IA-P0-02 (max_size_bytes enforcement) and IA-P0-03 (commit-time SSRF re-validation) features are correct hardening additions and stay. The tests were stale relative to those features."
  - "`**_` signature absorber chosen over a named `max_size_bytes=None` param. The mock's purpose is to neutralize the upload-save side effect; the test does not exercise size-enforcement behavior, so silently absorbing the kwarg is more future-proof than locking in a particular kwarg name. If a future production change adds another kwarg, the mock will keep working without further test edits."
  - "Patch target for SSRF gate is `app.modules.catalog.sources.security.validate_url_for_ssrf` (the defining module), NOT `app.processing.ingest.router.validate_url_for_ssrf` (the caller's namespace). Production uses a lazy from-import inside `commit_import`, so the symbol is not present in the router module namespace and patching there is a silent no-op."
  - "Two atomic commits (not one). The two fixes target distinct drift sources (separate Phase 1066 features, separate commits, separate semantics) and affect non-overlapping test surfaces. Splitting into two commits preserves blame traceability and lets a future bisect cleanly land on either drift independently. Contrast with Plan 1075-02's single-atomic-commit decision, which was correct THERE because all 3 tests shared a single root cause."

patterns-established:
  - "When a single integration-test file fails with mixed exception shapes (HTTP 500 vs HTTP 400 vs assertion-on-payload), the failures likely have INDEPENDENT root causes — triage each by traceback before assuming a shared cause. Plan 1075-02's shared-cause shape (3 identical 404s in the same class) was the exception, not the rule."
  - "Lazy-import gates (security checks, audit logging, IDOR guards) are common in newer code paths because they avoid circular-import risk. When triaging a test failure on a recently-added gate, ALWAYS grep the caller for `from x.y.z import fn` inside function bodies BEFORE setting a patch target."

requirements-completed: [TI-02 (partial — 3 of 11 baseline failures, the test_ingest.py subset)]

duration: ~10min
completed: 2026-05-21
---

# Phase 1075 Plan 03: Fix test_ingest.py 3 Failures (TI-02 partial) Summary

**The 3 v1015 baseline failures in `backend/tests/test_ingest.py` had two distinct root causes — both Phase 1066 production-code hardening additions that broke stale test mocks. `test_upload_success` and `test_csv_upload_success` failed because the autouse `mock_file_save` fixture's `_save_to_temp` side_effect did not accept the `max_size_bytes` kwarg added by feat IA-P0-02. `test_service_job_commits_with_service_body` failed because feat IA-P0-03 added a lazy-imported `validate_url_for_ssrf(job.source_url)` call to `commit_import`, which the test's fake `example.arcgis.com` hostname could not satisfy. Fixed both at the test surface — widened the mock signature with `**_`, and patched the SSRF gate at its defining module. Two atomic commits. Zero production-code drift. 39/39 PASSED sequential AND parallel.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-21 (post Plan 02 metadata commit)
- **Completed:** 2026-05-21
- **Tasks:** 4 (Task 1 triage → Task 2 fix x2 → Task 3 N/A no skips → Task 4 verify)
- **Files modified:** 1 (test-only)

## Accomplishments

- **Identified two independent drift sources from a single triage run.** The 3 failures shared a file but not a cause — `test_upload_success` and `test_csv_upload_success` shared HYPOTHESIS 3 (file-upload contract drift, mock signature), while `test_service_job_commits_with_service_body` was HYPOTHESIS 5 (service-URL dispatch drift, new SSRF gate). Both root causes were Phase 1066 features (commits `e11924c3` and `f8c91297`).
- **Confirmed Plan 01's lifecycle fix held.** `grep -c "InvalidCatalogNameError" /tmp/ingest_named.log` → 0 on the initial triage run. The 3 failures are pure test-vs-production drift, NOT lifecycle race fallout — the same negative-result data point Plan 02 reported.
- **Restored 39/39 PASSED in `test_ingest.py`** under both `pytest -x` (sequential) and `pytest -n 2` (parallel). Zero `InvalidCatalogNameError`. Zero `FAILED`. Zero `ERROR`. Zero `SKIPPED`.
- **Zero production-code changes.** Both Phase 1066 hardening features stay — they are correct and orthogonal to the test contracts under verification. Plan's hard scope gate respected (`git diff --stat backend/app/` → empty).
- **No GitHub issues filed and no `pytest.mark.skip` annotations needed.** Both fixes were root-cause-fixable in <5 minutes each; the skip-with-issue fallback path (Task 3) was not exercised.

## The 3 Originally-Failing Tests + Dispositions

| Test | Disposition | Fix Shape | Commit |
|------|-------------|-----------|--------|
| `TestUpload::test_upload_success` | **fixed** | Widened `_save_to_temp(file, job_id, **_)` in autouse `mock_file_save` fixture to absorb the `max_size_bytes` kwarg added to `save_upload_file()` by Phase 1066 feat IA-P0-02 | `0c58f795` |
| `TestCsvUpload::test_csv_upload_success` | **fixed** | Same fixture edit as above resolves this test simultaneously (one fixture, one edit). | `0c58f795` |
| `TestCommitImportDispatch::test_service_job_commits_with_service_body` | **fixed** | Wrapped the POST call in `with patch("app.modules.catalog.sources.security.validate_url_for_ssrf", new=AsyncMock()):` to no-op the SSRF gate added by Phase 1066 feat IA-P0-03. Patch target is the defining module (not the router's namespace) because the import is lazy and re-binds per call. | `f9d5558e` |

## Task Commits

Per the plan, Tasks 1 and 4 are pure-inspection (write/verify the inventory + re-run), so the only behaviour-changing commits were Task 2's two:

1. **Task 1 (triage):** No commit — output is `/tmp/1075-03-failures.md` (scratch artifact, not committed).
2. **Task 2a (fix mock signature for upload tests):** `0c58f795` — `fix(1075-03): widen mock_file_save signature for max_size_bytes kwarg (TI-02)`
3. **Task 2b (fix SSRF gate patch for service-commit test):** `f9d5558e` — `fix(1075-03): patch validate_url_for_ssrf in service-commit dispatch test (TI-02)`
4. **Task 3 (skip-with-issue):** **Skipped — not needed.** All 3 failures were root-cause-fixable; the skip path is reserved for genuinely-uninvestigable cases. Zero `pytest.mark.skip` decorators added.
5. **Task 4 (verify):** No commit — verification output appended to `/tmp/1075-03-failures.md`.

**Plan metadata commit:** (to follow this SUMMARY) — `docs(1075-03): complete TI-02 partial (test_ingest.py 3 fixes)`

## Files Created/Modified

- **`backend/tests/test_ingest.py`** (modified, +29 / -10 net) — Two non-overlapping hunks:
  - Lines 51-56: 5 comment lines + 1-character signature change (`_save_to_temp(file, job_id, **_)` instead of `_save_to_temp(file, job_id)`) in the autouse `mock_file_save` fixture.
  - Lines 1358-1380 (post-fix line numbers): wrapped the existing POST call in a `with patch("app.modules.catalog.sources.security.validate_url_for_ssrf", new=AsyncMock()):` block + a 10-line explanatory comment. The patch is scoped to this single test, not class-scoped or file-scoped — other service-URL tests can opt in independently if they hit the same gate.

## Failure Inventory Reference

Full triage capture lives at `/tmp/1075-03-failures.md` (local scratch, not committed per the plan). Key excerpt:

```
Failure 1 (test_upload_success):
  Exception type: assert 500 == 201
  Trace: TypeError: mock_file_save.<locals>._save_to_temp() got an unexpected keyword argument 'max_size_bytes'
  Hypothesis: HYPOTHESIS 3 (file-upload contract drift — mock side_effect signature)
  Root cause: commit e11924c3 "feat(1066-01): enforce max_file_size_bytes at multipart upload HTTP entry"
  Decision: fix in Task 2 — widen mock side_effect signature with **_

Failure 2 (test_csv_upload_success):
  Same root cause as Failure 1. Auto-resolved by Failure 1's fixture edit.

Failure 3 (test_service_job_commits_with_service_body):
  Exception type: assert 400 == 202
  Trace: detail="source_url failed safety check at commit time: Could not resolve hostname: example.arcgis.com"
  Hypothesis: HYPOTHESIS 5 (service-URL dispatch drift, new SSRF gate)
  Root cause: commit f8c91297 "feat(1066-02): re-validate source_url SSRF at commit + worker fetch"
  Decision: fix in Task 2 — patch validate_url_for_ssrf at defining module
```

## Mock-Signature / Contract Drift Encountered

Two distinct drift events affecting the 3 tests:

| Drift | Source commit | Affects | Fix shape |
|-------|---------------|---------|-----------|
| `save_upload_file()` gained `max_size_bytes` kwarg | `e11924c3` (Phase 1066 feat IA-P0-02) | `test_upload_success`, `test_csv_upload_success` | Widen mock side_effect signature with `**_` |
| `commit_import` re-validates `source_url` via `validate_url_for_ssrf` (lazy from-import) | `f8c91297` (Phase 1066 feat IA-P0-03) | `test_service_job_commits_with_service_body` | `patch("app.modules.catalog.sources.security.validate_url_for_ssrf", new=AsyncMock())` |

**Audit value for Plan 04 / future hygiene:** any test that uploads through `/ingest/upload` will hit Drift 1, and any test that commits a service-URL job will hit Drift 2 unless it patches the gate OR uses a real-resolving hostname (which would still fail under the private-IP block). Plan 04 (`test_maps_style_json.py x5`) is unlikely to hit either — the maps router does not call `save_upload_file` or `validate_url_for_ssrf` — but a `grep` cross-reference is cheap insurance.

## Auto-Resolution from Plan 01

**None.** Consistent with Plan 02's negative result — the lifecycle fix has nothing to bind to here because the 3 failures are pure-mock unit tests (with a real-DB envelope via the `client` fixture, but the failure point is the mocked side_effect, not the DB).

- Plan 01 eliminated the `InvalidCatalogNameError` race.
- `grep -c "InvalidCatalogNameError" /tmp/ingest_named.log` → 0 on initial triage AND on final verify runs.
- The plan's HYPOTHESIS 1 ("conftest cascade") was correctly ruled out at the inventory stage.

## GitHub Issues Filed

**None.** No skipped tests, no deferred root causes — all 3 failures were fixed in place.

## Final Tally

| Mode | PASSED | SKIPPED | FAILED | ERROR | Total | Exit |
|------|--------|---------|--------|-------|-------|------|
| `pytest -x` (sequential) | 39 | 0 | 0 | 0 | 39 | 0 |
| `pytest -n 2` (parallel via xdist) | 39 | 0 | 0 | 0 | 39 | 0 |
| InvalidCatalogNameError grep | 0 | — | — | — | — | — |

**Result: 39 passed, 0 failed, 0 errors, 0 skipped — both serial and parallel. Acceptance gates fully satisfied.**

## Scope Adherence

- `git diff --stat backend/app/` → empty (no production-code drift)
- `git diff --stat backend/tests/test_ingest.py` → +29 / -10 (39 line delta, well under the 100-line ceiling)
- All other tests in `test_ingest.py` that passed pre-Plan-03 still pass (verified by `--collect-only -q` count of 39 matching post-fix PASSED count of 39).
- No `pytest.mark.skip` decorators added — every disposition is FIXED.
- No new test files, no fixture extensions, no helper modules.

## Deviations from Plan

**None.** Plan executed exactly as written:

- Task 1 inventory ran, identified 3 specific failures with hypotheses and decisions.
- Task 2 applied the smallest-diff fix per hypothesis — two atomic commits because the two drift sources are independent (HYPOTHESIS 3 vs HYPOTHESIS 5, separate Phase 1066 features).
- Task 3 (skip-with-issue) was correctly NOT exercised — no failure required deferral.
- Task 4 verified both modes pass and InvalidCatalogNameError count is 0.

No Rule 1/2/3/4 deviations required. The plan's "single atomic commit per fix" guidance was honored — two distinct fixes, two commits. Plan 02's single-commit decision was a special case for 3 tests sharing a single root cause; this plan's 3 tests had 2 root causes, so 2 commits are the more honest pattern.

## Issues Encountered

**None.** The `.env.test` file at the repo root was already present (from Plan 01). `uv` environment ready. No setup blockers.

The plan's `<root_cause_hypothesis>` predicted HYPOTHESIS 1 (lifecycle cascade) as primary, then 2/3/4/5 as candidate causes. The actual causes were HYPOTHESIS 3 (file-upload contract drift — but the *mock signature* sub-shape, not the patch *target path* sub-shape the plan emphasized) and HYPOTHESIS 5 (service-URL dispatch). Reading the actual traceback was essential — the plan's HYPOTHESIS 3 framing was "mock target path moved" (e.g., `app.processing.ingest.upload.save_upload_file`), but the actual cause was "mock target path is correct, but the side_effect's signature is stale." A finer-grained sub-classification of "contract drift" into (a) target moved vs (b) signature widened would help future planners discriminate.

## Self-Check: PASSED

**Files exist:**
- FOUND: backend/tests/test_ingest.py (modified, 1487 lines — was 1468, +19 net)
- FOUND: /tmp/1075-03-failures.md (inventory + final result section)
- FOUND: /tmp/ingest_named.log (initial triage capture)
- FOUND: /tmp/ingest_seq.log (sequential verify)
- FOUND: /tmp/ingest_par.log (parallel verify)

**Commits exist:**
- FOUND: 0c58f795 (Task 2a — fix(1075-03): widen mock_file_save signature for max_size_bytes kwarg)
- FOUND: f9d5558e (Task 2b — fix(1075-03): patch validate_url_for_ssrf in service-commit dispatch test)

**Acceptance gates verified:**
- `cd backend && env $(grep -v '^#' ../.env.test | xargs) uv run pytest tests/test_ingest.py -x` → exit 0 ✓
- `cd backend && env $(grep -v '^#' ../.env.test | xargs) uv run pytest tests/test_ingest.py -n 2` → exit 0 ✓
- `grep -c InvalidCatalogNameError /tmp/ingest_seq.log` → 0 ✓
- `grep -c InvalidCatalogNameError /tmp/ingest_par.log` → 0 ✓
- `git diff --stat backend/app/` → empty (no production-code drift) ✓
- All skip annotations have `reason=<URL or filepath>` — vacuously true, zero skips added ✓
- 3 named tests all PASSED (verified by `grep -E "test_upload_success|test_csv_upload_success|test_service_job_commits_with_service_body" /tmp/ingest_seq.log` — all appear in the PASSED dotline summary) ✓

## Next Phase Readiness

- **Plan 1075-04 (TI-02 partial: test_maps_style_json.py ×5)** unblocked. Plans 02 and 03 both reported that the lifecycle was a red herring and the failures were pure drift — Plan 04 should jump straight to traceback triage rather than expecting auto-resolution. The maps router does not import `save_upload_file` or `validate_url_for_ssrf`, so neither Drift 1 nor Drift 2 propagates there; the 5 failures will have a different shape.
- **Plan 1075-05 (full-suite verification)** still gated on Plan 04 landing. After 04, the full backend/tests/ tree should be cleanly comparable pre/post v1075.

**Diagnostic patterns reinforced:**

1. **Triage-by-traceback before triage-by-hypothesis.** The plan's HYPOTHESIS framework correctly enumerated 5 possible causes, but the inventory step (run the file, read the traceback, decide root cause) is what disambiguates them. Don't pre-commit to a hypothesis before running the tests.

2. **Independent drift sources warrant independent commits.** Plan 02 collapsed 3 tests into 1 commit because they shared a cause; Plan 03 split 2 tests + 1 test into 2 commits because the causes were independent. The Plan-02 → Plan-03 contrast is the canonical example.

3. **Lazy from-imports demand patch targets at the defining module.** The router's `from app.modules.catalog.sources.security import validate_url_for_ssrf` lives INSIDE `commit_import`, so the symbol never settles into `app.processing.ingest.router.validate_url_for_ssrf`. Patching there would have been a silent no-op. Always read the import location (top-of-module vs inside-function) before setting a patch target.

4. **Broad-except is a failure-shape amplifier.** The original `test_upload_success` failure looked like a generic 500 because `router.py:446` wraps everything in `except Exception` → HTTP 500. The actual error was a TypeError on the mock, but the test surface saw only "the API returned 500." When a test fails with HTTP 500 on a previously-passing test, ALWAYS check the captured stderr/log for the underlying TypeError or ValueError — the wrapper swallows the signal.

**No blockers identified.** test_ingest.py is now a clean baseline for any future ingest-pipeline regression triage.

---
*Phase: 1075-conftest-test-db-lifecycle-refactor-baseline-fixes*
*Completed: 2026-05-21*
