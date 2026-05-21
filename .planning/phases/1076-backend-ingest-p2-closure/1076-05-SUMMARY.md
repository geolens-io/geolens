---
phase: 1076-backend-ingest-p2-closure
plan: 05
subsystem: api
tags: [raster, cog, schema, opt-in, backwards-compatible, pydantic, ingest]

# Dependency graph
requires:
  - phase: 1075-conftest-test-db-lifecycle-refactor-baseline-fixes
    provides: stable test-DB lifecycle for new raster behavior test
provides:
  - "Optional `strict_cog: bool = False` field on RasterCommitRequest"
  - "Module-level `_enforce_strict_cog(...)` helper in tasks_raster.py"
  - "Behavior-pinning regression test for strict-mode COG gating"
affects: [v1077-frontend-ingest, v1079-close-gate, future-strict-cog-default-flip]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Opt-in commit-request flag with default-False backward-compat"
    - "Module-level async helper extracted from inline gate block for clean test surface"

key-files:
  created:
    - "backend/tests/test_strict_cog_enforcement.py"
  modified:
    - "backend/app/processing/ingest/schemas.py"
    - "backend/app/processing/ingest/tasks_raster.py"
    - "backend/tests/test_commit_request_schemas.py"

key-decisions:
  - "Extract gate into module-level `_enforce_strict_cog` helper (Option A from plan) to keep the regression test slim — direct helper invocation, no full Procrastinate task spin-up."
  - "Manifest-VRT jobs bypass the gate (is_manifest_vrt=True) — VRTs are XML, not TIFFs, and `check_cog_compliance` would fail for unrelated reasons."
  - "Gate runs via `asyncio.to_thread` (rasterio.open is I/O-bound CPU work) — same pattern as the rest of Phase 1 in `ingest_raster`."
  - "ValueError shape mirrors the existing `Missing CRS` ValueError two lines above so the outer `except Exception` handler at tasks_raster.py:444 writes the failure via `_job_phase_session('error_write')` with zero new plumbing."
  - "`expected_compression` parameter passed through to `check_cog_compliance` so the gate respects the user's `RasterCommitRequest.compression` knob — a TIFF compressed with `DEFLATE` should pass when the user set `compression='DEFLATE'` and fail when they set `compression='LZW'` and the source is DEFLATE."

patterns-established:
  - "Opt-in strict-mode gating via Pydantic `Field(default=False)` on commit-request schemas — default preserves existing call sites, opt-in surfaces strict semantics at the operator boundary."
  - "Pre-CPU-work pre-flight check between Phase 1 session close and the heavy `to_thread` block — raises ValueError that bubbles to the outer except handler instead of needing its own error-write."

requirements-completed: [ING-07]

# Metrics
duration: 18min
completed: 2026-05-21
---

# Phase 1076 Plan 05: ING-07 (strict_cog field on RasterCommitRequest) Summary

**Optional `strict_cog: bool = False` field on RasterCommitRequest gates non-COG TIFFs at commit time via a pre-flight `check_cog_compliance` probe; default preserves the existing auto-convert behavior.**

## Performance

- **Duration:** 18 min
- **Started:** 2026-05-21
- **Completed:** 2026-05-21
- **Tasks:** 3
- **Files modified:** 4 (3 modified + 1 created)

## Accomplishments

- `RasterCommitRequest.strict_cog: bool = False` field added with backward-compatible default — every existing raster commit call site sees zero behavior change.
- `_enforce_strict_cog(...)` helper extracted as a module-level async function in `tasks_raster.py` — runs `check_cog_compliance` via `asyncio.to_thread`; raises `ValueError("Strict-COG mode rejected upload: <reason>. Disable strict_cog or upload a COG-compliant TIFF.")` on non-compliance.
- Gate wired into `ingest_raster` between the CRS validation block and the `cog_convert` progress write — the ValueError bubbles to the existing outer `except Exception` handler that writes the failure via `_job_phase_session("error_write")`.
- 3 schema unit tests + 4 behavior tests added; 92/92 tests pass across the combined regression gate (`test_commit_request_schemas.py` + `test_strict_cog_enforcement.py` + `test_raster_ingest.py` + `test_raster_validation.py` + `test_raster_schema.py`).
- Manifest-VRT jobs (`is_manifest_vrt=True`) bypass the gate — VRTs are XML, not TIFFs.

## Task Commits

Each task was committed atomically. The TDD shape was preserved locally for Task 1 (tests written first, confirmed RED with `AttributeError: 'RasterCommitRequest' object has no attribute 'strict_cog'`, then schema field added — confirmed GREEN with 21/21 passing) but the test edit and the schema edit ship as one feat commit because they form a single pure-additive unit; splitting into a `test:` commit that breaks the suite and a follow-up `feat:` commit that fixes it would leave a known-red commit on `main`. Tasks 2 and 3 ship as separate feat/test commits since the production-code change in Task 2 lands without a new dedicated test (it is a wire-through; backward-compat is proven by the existing 67 raster tests still passing), and Task 3 is the dedicated behavior pin.

1. **Task 1: add strict_cog field to RasterCommitRequest** — `0baf8e1f` (feat)
2. **Task 2: wire strict_cog gate into ingest_raster** — `83ab14a7` (feat)
3. **Task 3: pin strict_cog enforcement behavior** — `236c6755` (test)

## Files Created/Modified

- `backend/app/processing/ingest/schemas.py` — added optional `strict_cog: bool = Field(default=False, ...)` to `RasterCommitRequest` (lines 185-194).
- `backend/app/processing/ingest/tasks_raster.py` — added `check_cog_compliance` to the import block (line 12), added module-level `_enforce_strict_cog(...)` helper (lines 36-72), and wired the call at line 261 (between CRS validation and the `cog_convert` progress write).
- `backend/tests/test_commit_request_schemas.py` — 3 new tests in `TestRasterCommitRequest` (default, opt-in, model_validate omission); `TestFieldDistribution.test_raster_fields` updated to include `"strict_cog"` in the expected set.
- `backend/tests/test_strict_cog_enforcement.py` — new 99-line file with 4 behavior tests pinning the four gate branches (strict+non-compliant raises, strict+compliant passes, non-strict skips check, VRT skips check).

## Decisions Made

- **Helper extraction (Option A from plan)** — extracted `_enforce_strict_cog` as a module-level async function in `tasks_raster.py` instead of leaving an inline block. Rationale: clean test surface — Task 3's behavior tests import the helper directly and patch `check_cog_compliance` at its `tasks_raster` import site. The alternative (inline + integration-shaped tests with mocks for `resolve_file_path`, `_validate_upload_file_safety`, etc.) is too heavy for a pin test.
- **`expected_compression` pass-through** — the helper forwards the user's `RasterCommitRequest.compression` value to `check_cog_compliance(file_path, expected_compression=user_compression)`. This means the strict gate respects the user's compression preference: a DEFLATE-compressed source TIFF passes when the user requested DEFLATE (their default), but fails when they requested LZW and the source is DEFLATE. Matches the contract documented at `cog.py:130-137`.
- **Gate placement** — placed after the CRS validation block (`if not meta.get("crs_wkt") and not assign_crs:`) and before the `progress_write_cog_convert` `_job_phase_session` block. Rationale: by this point we've already done `extract_raster_metadata` (cheap) but not yet the expensive `check_and_prepare_cog` subprocess. CRS missing is a higher-priority failure (no point checking COG compliance on a file with no CRS — the operator cannot fix that with strict_cog alone).
- **Bypass for manifest-VRT** — `is_manifest_vrt=True` returns early from the helper. Rationale: VRTs are XML, not TIFFs; `check_cog_compliance` would fail with an opaque rasterio error rather than a meaningful "Not a COG" reason.
- **No new error-write plumbing** — the ValueError bubbles to the existing outer `except Exception as exc:` handler at `tasks_raster.py:444` which already writes `status="failed"` + `error_message=str(exc)` via `_job_phase_session("error_write")`. Same path used by the existing "Missing CRS" ValueError two lines above.

## Deviations from Plan

None — plan executed exactly as written. The plan offered a choice between Option A (extract helper in Task 2 or Task 3) and Option B (monkeypatch at module level + slim wrapper). Option A was the plan's preferred recommendation and was followed.

## Verification

All plan-level acceptance gates green:

| Gate | Expected | Actual | Status |
|---|---|---|---|
| `grep -c "strict_cog" schemas.py` | >= 1 | 1 | PASS |
| `grep -c "strict_cog" tasks_raster.py` | >= 1 | 8 | PASS |
| `grep -c "strict_cog" test_commit_request_schemas.py` | >= 4 | 9 | PASS |
| `grep -c "check_cog_compliance" tasks_raster.py` | >= 2 (import + call) | 2 | PASS |
| `RasterCommitRequest.model_fields` contains `"strict_cog"` | True | True | PASS |
| `test_strict_cog_enforcement.py` line count | > 50 | 99 | PASS |
| Combined regression (5 test files, 92 tests) | All pass | 92/92 | PASS |

Combined regression command (run from `/Users/ishiland/Code/geolens/backend`):

```
env $(grep -v '^#' ../.env.test | xargs) uv run pytest \
  tests/test_commit_request_schemas.py \
  tests/test_strict_cog_enforcement.py \
  tests/test_raster_ingest.py \
  tests/test_raster_validation.py \
  tests/test_raster_schema.py -x
```

Output: `92 passed in 4.15s`.

## Issues Encountered

None.

## Backward Compatibility Note

`strict_cog` defaults to `False`. Every existing raster commit call site (admin UI, manifest catalog ingest, programmatic API consumers) constructs `RasterCommitRequest` without supplying the flag, so Pydantic applies `default=False`, the user_metadata payload either omits `strict_cog` entirely (when serialized without it) or includes `strict_cog=False`, and `_enforce_strict_cog(...)` returns early without invoking `check_cog_compliance`. The 67 existing raster-test cases (`test_raster_ingest.py` + `test_raster_validation.py` + `test_raster_schema.py`) pass unchanged. Operators must explicitly opt in to see the new strict behavior.

## User Setup Required

None — pure schema + Python code addition; no new dependencies, no migrations, no environment variables.

## Next Phase Readiness

- ING-07 / P2-09 closed; `RasterCommitRequest` now has the wire contract for strict-COG mode.
- Frontend toggle for `strict_cog` lives in v1077 or later (out of scope per plan objective).
- Default flip from `False` → `True` is deferred to a future coordinated CLI/manifest schema bump (out of scope per plan objective).
- Phase 1076 remaining plan: 1076-06 (close-gate plan).

## Self-Check

PASSED — see verification table above.

- `backend/app/processing/ingest/schemas.py` — present, contains `strict_cog` field.
- `backend/app/processing/ingest/tasks_raster.py` — present, contains `_enforce_strict_cog` helper + call site + `check_cog_compliance` import.
- `backend/tests/test_commit_request_schemas.py` — present, 21 tests pass.
- `backend/tests/test_strict_cog_enforcement.py` — present, 99 lines, 4 tests pass.
- Task commits `0baf8e1f`, `83ab14a7`, `236c6755` — all present in `git log --oneline -5`.

## Threat Flags

None — no new security-relevant surface beyond what's documented in the plan's `<threat_model>`. The strict_cog rejection reasons are static category labels from `check_cog_compliance` that already surface today in the preview response (per T-1076-19 disposition).

---
*Phase: 1076-backend-ingest-p2-closure*
*Plan: 05*
*Completed: 2026-05-21*
