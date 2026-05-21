---
phase: 1073-audit-remediation
verified: 2026-05-21T00:00:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
---

# Phase 1073: Audit Remediation Verification Report

**Phase Goal:** Close 4 P2 audit findings (REMED-01..04) from Phase 1072 triage; pin SEC-OBSV-01 + SEC-OBSV-02 docstrings as part of REMED-04.
**Verified:** 2026-05-21
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | After useReuploadCommit success, jobStatusByDataset cache is invalidated | VERIFIED | `use-dataset.ts:178` — `qc.invalidateQueries({ queryKey: queryKeys.ingest.jobStatusByDataset(variables.datasetId) })` in onSuccess; commit `eff60188` |
| 2 | useAddVrtSource/useRemoveVrtSource/useRegenerateVrt invalidate jobStatusByDataset | VERIFIED | `use-vrt.ts:31,44,78` — three invalidation calls; commit `c7e8650f` |
| 3 | useCreateVrt invalidates jobStatus(job_id) on success (VrtCreateResponse has no dataset_id) | VERIFIED | `use-ingest.ts:114` — `qc.invalidateQueries({ queryKey: queryKeys.ingest.jobStatus(data.job_id) })`; inline comment documents the response-shape rationale; commit `6a122faa` |
| 4 | JobStatusResponse declares progress (ge=0/le=1), current_step (Literal, 7 names), rows_processed (ge=0) — all default None | VERIFIED | `schemas.py:81-94` — all three fields with Pydantic bounds; commit `29167a28` |
| 5 | IngestJob model has 3 matching nullable columns (Float/String(32)/Integer) | VERIFIED | `models.py:72-74` — mapped columns confirmed |
| 6 | Alembic migration 0022 adds 3 columns to catalog.ingest_jobs (non-stub upgrade + downgrade) | VERIFIED | `backend/alembic/versions/0022_ingest_jobs_progress_columns.py` — 3 `op.add_column` calls; commit `690cd661` |
| 7 | Vector worker writes current_step at 4+ step boundaries | VERIFIED | `grep -cE 'current_step\s*=\s*"' tasks_vector.py` = 8; commit `b4a4f47d` |
| 8 | Raster worker writes current_step at 5 step boundaries | VERIFIED | `tasks_raster.py` — validating, cog_convert, quicklook, finalize, complete (lines 191,260,305,330,431); commit `880946be` |
| 9 | _finalize_ingest writes terminal progress=1.0, current_step="complete", rows_processed | VERIFIED | `tasks_common.py:814-815` — confirmed; commit `b4a4f47d` |
| 10 | _job_phase_session async context manager extracted to tasks_common.py | VERIFIED | `tasks_common.py:181` — @asynccontextmanager with IngestJob load, None-job short-circuit, rollback-on-exception; commit `86356123` |
| 11 | tasks_vector uses _job_phase_session at all session-bracket sites (19 calls, 0 bare async_session) | VERIFIED | grep count = 19 calls; `async_session()` non-comment count = 0 |
| 12 | tasks_raster uses _job_phase_session at all session-bracket sites (12 calls, 0 bare async_session) | VERIFIED | grep count = 12 calls; `async_session()` non-comment count = 0 |
| 13 | build_titiler_cog_url helper exists at backend/app/platform/storage/titiler_url.py | VERIFIED | File confirmed; `_TITILER_BASE_URL` constant at line 29; `def build_titiler_cog_url` at line 32; commit `afa5b320` |
| 14 | tiles/router.py routes cog/tiles call through helper (0 literal http://titiler:8000) | VERIFIED | `grep -c 'http://titiler:8000' router.py` = 0; `build_titiler_cog_url` count = 3 |
| 15 | stac_router.py routes cog/info and cog/statistics calls through helper (0 literal) | VERIFIED | `grep -c 'http://titiler:8000' stac_router.py` = 0; `build_titiler_cog_url` count = 3 |
| 16 | SEC-OBSV-01 docstring pinned at tiles/router.py::_titiler_client | VERIFIED | `tiles/router.py:52` — SEC-OBSV-01 block with internal-only rationale + make_safe_client migration trigger; commit `9e1cd403` |
| 17 | SEC-OBSV-02 docstring pinned at stac_router.py::_fetch_cog_info | VERIFIED | `stac_router.py:50` — SEC-OBSV-02 dual-gate enumeration (validate_url_for_ssrf + CPL_VSIL_CURL_ALLOWED_EXTENSIONS); commit `c6f69498` |

**Score:** 4/4 REMED requirements verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/dataset/hooks/use-dataset.ts` | useReuploadCommit with jobStatusByDataset invalidation | VERIFIED | Line 178 |
| `frontend/src/components/import/hooks/use-vrt.ts` | 3 VRT mutations with jobStatusByDataset invalidation | VERIFIED | Lines 31, 44, 78 |
| `frontend/src/components/import/hooks/use-ingest.ts` | useCreateVrt with jobStatus(job_id) invalidation | VERIFIED | Line 114 |
| `backend/app/platform/jobs/schemas.py` | JobStatusResponse with progress/current_step/rows_processed | VERIFIED | Lines 81–94 |
| `backend/app/platform/jobs/models.py` | IngestJob with 3 nullable columns | VERIFIED | Lines 72–74 |
| `backend/app/platform/jobs/router.py` | _job_to_status_response forwards 3 new fields | VERIFIED | Lines 227–229 |
| `backend/alembic/versions/0022_ingest_jobs_progress_columns.py` | Migration with 3 op.add_column + downgrade | VERIFIED | 3 add_column calls confirmed |
| `backend/app/processing/ingest/tasks_common.py` | _job_phase_session async context manager | VERIFIED | Line 182 |
| `backend/app/processing/ingest/tasks_vector.py` | Uses _job_phase_session; 0 bare async_session | VERIFIED | 19 calls; 0 bare |
| `backend/app/processing/ingest/tasks_raster.py` | Uses _job_phase_session; 0 bare async_session | VERIFIED | 12 calls; 0 bare |
| `backend/app/platform/storage/titiler_url.py` | build_titiler_cog_url helper + _TITILER_BASE_URL | VERIFIED | Lines 29, 32 |
| `backend/tests/test_ingest_progress.py` | 3 worker progress-write regression tests | VERIFIED | test_finalize_ingest_writes_terminal_progress, test_vector_worker_writes_ogr2ogr_step_before_subprocess, test_named_step_progress_is_non_decreasing |
| `backend/tests/test_tasks_common_phase_brackets.py` | 4 _job_phase_session contract tests | VERIFIED | loads-existing / yields-none / rolls-back / commit-persists |
| `backend/tests/test_titiler_url_helper.py` | 8 tests (6 helper-shape + 2 structural-pin) | VERIFIED | 8 test functions confirmed |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| useReuploadCommit | queryKeys.ingest.jobStatusByDataset(datasetId) | qc.invalidateQueries in onSuccess | WIRED | use-dataset.ts:177-179 |
| useAddVrtSource | queryKeys.ingest.jobStatusByDataset(datasetId) | qc.invalidateQueries in onSuccess | WIRED | use-vrt.ts:31 |
| useRemoveVrtSource | queryKeys.ingest.jobStatusByDataset(datasetId) | qc.invalidateQueries in onSuccess | WIRED | use-vrt.ts:44 |
| useRegenerateVrt | queryKeys.ingest.jobStatusByDataset(datasetId) | qc.invalidateQueries in onSuccess | WIRED | use-vrt.ts:78 |
| useCreateVrt | queryKeys.ingest.jobStatus(data.job_id) | qc.invalidateQueries in onSuccess | WIRED | use-ingest.ts:114 |
| tasks_vector.ingest_file | IngestJob.current_step / progress | current_step = "..." via _job_phase_session | WIRED | 8 assignment sites in tasks_vector.py |
| tasks_raster.ingest_raster | IngestJob.current_step / progress | current_step = "..." via _job_phase_session | WIRED | 6 assignment sites in tasks_raster.py |
| tasks_common._finalize_ingest | IngestJob progress=1.0, current_step="complete" | Direct ORM write at terminal site | WIRED | tasks_common.py:814-815 |
| tiles/router.py:343 | build_titiler_cog_url | import + call | WIRED | 0 literal; 3 build_titiler_cog_url refs |
| stac_router.py:55,69 | build_titiler_cog_url | import + 2 call sites | WIRED | 0 literal; 3 build_titiler_cog_url refs |

---

### Phase Boundary Checks

| Check | Expected | Status | Details |
|-------|----------|--------|---------|
| OpenAPI snapshots untouched | backend/openapi.json + frontend/src/types/openapi.ts not in phase 1073 diff | VERIFIED | `git diff --name-only HEAD~20 HEAD -- backend/openapi.json frontend/src/types/openapi.ts` = empty |
| CHANGELOG.md untouched | No CHANGELOG edits in phase 1073 | VERIFIED | `git diff --name-only HEAD~20 HEAD -- CHANGELOG.md` = empty |

---

### Carryover Items for Phase 1074 (Informational)

These are not gaps in Phase 1073 — they are explicitly deferred to Phase 1074 by the CONTEXT.md locked decisions.

| Item | Owner Phase | Notes |
|------|------------|-------|
| `alembic upgrade head` (migration 0022) in close-gate | 1074 | Migration file exists; run during 1074 close-gate |
| OpenAPI dual-snapshot refresh (`make openapi` + `npm run fetch-openapi`) | 1074 | Required because JobStatusResponse + IngestJob changed; project memory mandates geolens first |
| 3 pre-existing test_ingest.py failures (test_upload_success, test_csv_upload_success, test_service_job_commits_with_service_body) | 1074 triage | All 3 reproduce on pre-1073 baseline; not introduced by this phase |
| 15 v1015 baseline test failures from 1071-01 | Pending triage | Not a 1073 scope item |

---

### Anti-Patterns Found

No TBD/FIXME/XXX/placeholder markers found in any of the 11 modified files.

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| — | None | — | — |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| REMED-01 | 1073-01 | TanStack mutations invalidate jobStatusByDataset after reupload/VRT | SATISFIED | 5 mutations wired; 5 regression tests; commits d86ab0a1–6a122faa |
| REMED-02 | 1073-02 | JobStatusResponse + IngestJob + worker writes for progress/current_step/rows_processed | SATISFIED | Schema + model + migration 0022 + vector/raster worker writes + 3 regression tests; commits 29167a28–771a4e68 |
| REMED-03 | 1073-03 | _job_phase_session helper extracted; tasks_vector + tasks_raster consume it; 0 bare async_session calls remain | SATISFIED | Helper at tasks_common.py:182; 19+12 call sites; 4 contract tests; commits 86356123–005416a0 |
| REMED-04 | 1073-04 | build_titiler_cog_url helper + 3 callers + SEC-OBSV-01/02 docstrings + 8 structural tests | SATISFIED | titiler_url.py created; 0 literal http://titiler:8000 in callers; both docstrings pinned; commits 8cb818d6–d4968e3b |

---

### Human Verification Required

None — all closures are structural (code + tests), not UI/UX or real-time behavior. The dataset-detail warnings-banner refresh (REMED-01's live effect) is scheduled for Phase 1074 close-gate smoke run per CONTEXT.md.

---

### Gaps Summary

No gaps. All 4 REMED requirements are closed with observable, substantive evidence:

- **REMED-01**: 5 mutations instrumented (use-dataset.ts, use-vrt.ts, use-ingest.ts), 5 regression tests, all commits present.
- **REMED-02**: Schema + model + migration + worker writes wired at 8 (vector) + 6 (raster) step boundaries, terminal progress stamped in _finalize_ingest, 3 worker regression tests including load-bearing brief-session pin.
- **REMED-03**: _job_phase_session helper extracted, 14 session-bracket boilerplate sites replaced, 0 bare `async_session()` calls survive in either worker file, 4 contract regression tests.
- **REMED-04**: build_titiler_cog_url helper module created, 3 callers wired, 0 literal `http://titiler:8000` survives in non-comment lines of caller files, SEC-OBSV-01 + SEC-OBSV-02 docstrings pinned, 8 tests (6 helper-shape + 2 structural regression).

---

_Verified: 2026-05-21_
_Verifier: Claude (gsd-verifier)_
