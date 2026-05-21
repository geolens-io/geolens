---
gsd_state_version: 1.0
milestone: v1018
milestone_name: Hygiene — v1017 Tech-Debt Tail
status: planning
last_updated: "2026-05-21T21:20:27.604Z"
last_activity: 2026-05-21
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# State

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-05-21 — Milestone v1018 started

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Phase 1079 — close-gate-hygiene

## Last Shipped Milestone

**Version:** v1016 Hardening Sweep
**Shipped:** 2026-05-21
**Phases:** 1071-1074 (4 phases, 26/26 reqs)
**Tag:** `v1016` (local) + `v1.5.1` (public) at commit `70241f96`
**Archive:** `.planning/milestones/v1016-ROADMAP.md`

**Previous:** v1015 Ingest/Export Lifecycle Hardening (shipped 2026-05-20, public tag `v1.5.0`, archive `.planning/milestones/v1015-ROADMAP.md`)

## Phase Plan (v1017)

| Phase | Goal | Requirements | Depends on |
|-------|------|--------------|------------|
| 1075 | Conftest Test-DB Lifecycle Refactor + Baseline Fixes | TI-01, TI-02 | — |
| 1076 | Backend Ingest P2 Closure | ING-02, ING-03, ING-04, ING-06, ING-07 | 1075 |
| 1077 | Frontend Ingest P2 Closure | ING-01, ING-05 | 1075 |
| 1078 | CI Alembic Clean-DB Upgrade Workflow | CI-01 | — |
| 1079 | Close Gate + Hygiene | TI-03, VG-01, HYG-01 | 1075, 1076, 1077, 1078 |

**Coverage:** 13/13 requirements mapped — no orphans.

## Accumulated Context

### Decisions

- **2026-05-21 (v1017 Phase 1078):** CI-01 closed — `backend/scripts/test_alembic_upgrade_clean_db.sh` (built in v1016 Phase 1071) now wired into `.github/workflows/ci.yml` as a new `alembic-clean-db` job between `backend-test` and the frontend section. Uses the same `actions/checkout@v6` + `astral-sh/setup-uv@v8.1.0` (v0.10.2) + `actions/setup-python@v6` (3.13) shape as the other backend gates; triggers on path-filter match (backend/alembic/**, backend/scripts/test_alembic_upgrade_clean_db.sh, backend/app/models/**, db/**) OR push to main. SEC-OBSV-03 (v1016 Phase 1072 observational finding) is structurally closed; end-to-end live CI run deferred to Phase 1079 VG-01 (docker-smoke re-verify). YAML lint passes (`python3 -c "import yaml; yaml.safe_load(...)"` exits 0); all 4 acceptance greps green. Zero existing CI job modified; purely additive. See `.planning/phases/1078-ci-alembic-clean-db-upgrade-workflow/1078-VERIFICATION.md` for the evidence trail and `.planning/phases/1078-ci-alembic-clean-db-upgrade-workflow/1078-SUMMARY.md` for the closure summary.
- **2026-05-21 (v1017 Phase 1077):** Both ING-01 + ING-05 closed; frontend ingest P2 tail fully resolved. Cumulative impact: 1 new `getCogDownloadUrl(id)` helper centralizing the COG download path-construction (single edit site for future route changes), 1 new `uploadChunks(urls, file, partSize)` helper centralizing the chunked-PUT loop (single edit site for future retry / abort / backoff), and 1 new `_presignedUpload.test.ts` (5 pinned behaviors). Full frontend regression gate green: `npx tsc -b` exits 0 with zero errors in any of Plan 01's 5 touched/created files; `npx vitest run` reports 213/213 test files and 2105/2105 tests passing. Zero observable UI behavior change. See `.planning/phases/1077-frontend-ingest-p2-closure/1077-VERIFICATION.md` for the full test evidence trail and `.planning/phases/1077-frontend-ingest-p2-closure/1077-SUMMARY.md` for the closure summary.
- **2026-05-21 (v1017 Phase 1076):** All 5 ING requirements (ING-02, ING-03, ING-04, ING-06, ING-07) closed; backend ingest P2 tail fully resolved. Cumulative impact: 4 internal commits dropped from `metadata.py` phase-2 helpers, 1 new `StorageProvider.get_stream()` async-generator method, 1 mtime-guarded worker exports sweep, 1 single-retry on `lock_timeout` in `_apply_reupload_swap`, 1 opt-in `strict_cog` flag on `RasterCommitRequest`. 256/256 targeted regression tests pass; zero cross-plan interference; zero anomalies. See `.planning/phases/1076-backend-ingest-p2-closure/1076-VERIFICATION.md` for the full test evidence trail and `.planning/phases/1076-backend-ingest-p2-closure/1076-SUMMARY.md` for the closure summary.
- **2026-05-21 (v1017):** Test infrastructure MUST run first (Phase 1075) so every downstream phase gets clean pytest signal — TI-01 conftest refactor is a precondition for accurate test results on ING-02 regression test + close-gate.
- **2026-05-21 (v1017):** TI-03 pytest baseline doc is the LAST phase work (Phase 1079) — it captures the post-fix steady state after all 4 prior phases land.
- **2026-05-21 (v1017):** CI-01 alembic workflow (Phase 1078) is independent of test infra and ingest P2 work — can execute in parallel with Phase 1076/1077 if/when capacity allows.
- **2026-05-21 (v1017):** Ingest P2 split by surface — backend (Phase 1076: ING-02/03/04/06/07) needs new regression test for P2-02 commit boundary; frontend (Phase 1077: ING-01/05) is mostly helper extraction. Splitting allows the backend phase to gate on the new regression test independently.
- **2026-05-21 (v1017):** Re-audit NOT scheduled at the front — v1016 audits passed clean 1 day prior (2026-05-21). Audits run at close-gate as verification only, not gating.
- **2026-05-21 (v1017):** Public tag target `v1.5.2` (patch) — hygiene/hardening only, no user-facing features, no migrations beyond what's needed for ING-02 regression test fixtures.
- [Phase ?]: 2026-05-21 (1075-01): worker_id default is 'master' (not empty/blank) for the test-DB naming layout — prevents collisions between sequential pytest and parallel xdist runs against the same Postgres server. 50ms grace window between pg_terminate_backend and DROP DATABASE eliminates the libpq-async-shutdown race that surfaced as 1363 InvalidCatalogNameError errors in v1016 Phase 1074.
- [Phase ?]: 1075-04: Single atomic commit for all 5 test_maps_style_json.py failures because they share one root cause (Phase 1060 commit a400eb89 builder canonicalization), mirroring Plan 02's shared-cause precedent
- [Phase ?]: 1075-04: MapLibre style-JSON wire-vs-storage casing asymmetry is intentional contract. Build (export) emits camelCase for frontend; parse (import) → MapLayerInput → DB uses snake_case for persistence parity. Tests must choose casing per the boundary they pin
- 2026-05-21 (v1017 Phase 1075-05): TI-01 closure verified at full-suite scale — `grep -c "InvalidCatalogNameError"` returns 0 on both `pytest tests/` (sequential, 539s, 2994 PASS) and `pytest tests/ -n auto` (parallel, 56s, 1649 PASS truncated by recovery cascade). The conftest test-DB lifecycle refactor (Plan 1075-01) scales to the full backend/tests/ tree.
- 2026-05-21 (v1017 Phase 1075-05): TI-02 closure verified within named scope — all 11 v1015 baseline failures in the 3 named files (test_defer_orphan_guard.py x3, test_ingest.py x3, test_maps_style_json.py x5) are now PASSED. Zero `pytest.mark.skip` decorators were exercised across Plans 02/03/04.
- 2026-05-21 (v1017 Phase 1075-05): VERIFICATION GAP — full-suite run uncovered 7 unexpected failures in OTHER test files (test_layering, test_phase_279_user_lifecycle x2, test_reupload_idor, test_reupload_service x2, test_tasks_common_phase_brackets) outside TI-02's named scope. These are pre-existing drift surfaces (2 production-code drift, 2 test-fixture drift, 2 environmental/GDAL, 1 async lifecycle drift) that per-file Plans 02/03/04 could not surface. Recommended follow-up: Plan 1075-06 OR v1018 hygiene task to disposition via the Plan 02/03/04 protocol. Critical advisory to Phase 1079 TI-03 planner: do NOT mark the post-v1017 pytest baseline doc as "captured" without first dispositioning these 7.
- 2026-05-21 (v1017 Phase 1075-05): PARALLEL-MODE ENVIRONMENTAL CAP — `pytest -n auto` (16 xdist workers on this host) triggered a Postgres backend crash and postmaster recovery mode, producing 1363 `asyncpg.exceptions.CannotConnectNowError`. This is a DIFFERENT exception class and root cause from TI-01's surface (host PG load capacity vs test-DB lifecycle race). Recommended follow-up: tune to `-n 4` or `-n 8` for host runs, increase PG max_connections, or add per-worker pool sizing to conftest. NOT a TI-01 regression.
- [Phase ?]: ING-02 / P2-02 closed: phase-2 metadata helpers no longer commit internally; _finalize_ingest at tasks_common.py:821 owns the phase-2 commit boundary. Regression test test_phase_2_commit_boundary.py (204 lines, 3 tests) pins the rollback invariant.
- [Phase ?]: ING-03: Protocol uses def get_stream returning AsyncIterator (canonical async-generator structural shape) — router calls without await and hands directly to StreamingResponse
- [Phase ?]: ING-03: S3 provider get_stream raises NotImplementedError (S3 path returns 302 presigned redirect and never reaches get_stream)
- [Phase ?]: ING-03: Pre-stream storage.exists() probe at the router before handing iterator to StreamingResponse — deferred FileNotFoundError would surface as 500 instead of clean 404
- [Phase ?]: Worker exports sweep gated on mtime>1h via EXPORTS_SWEEP_AGE_SECONDS=3600; helper extracted to module level for unit testing (ING-04)
- [Phase ?]: ING-07 / P2-09 closed (Phase 1076-05): RasterCommitRequest gains optional strict_cog: bool = False; module-level _enforce_strict_cog(...) helper in tasks_raster.py runs check_cog_compliance via asyncio.to_thread between CRS validation and the cog_convert progress write. Default False preserves backward compatibility — 67 existing raster tests + new 4-test pin file = 92/92 passing.

### Pending Todos

- 174 v1014/v1015/v1016 quick_tasks queued for triage in HYG-01 (Phase 1079) — review, archive superseded, promote still-relevant to `.planning/todos/pending/`, target <50 active.

### Blockers/Concerns

None — v1017 roadmap is complete and ready for plan-phase.

## Session Continuity

Last session: 2026-05-21T22:45:00.000Z
Stopped at: Phase 1078 complete (2/2 plans); CI-01 + SEC-OBSV-03 closed; all v1017 phase predecessors for Phase 1079 are now closed
Resume file: None

## Operator Next Steps

- Phase 1078 is closed. All four predecessors for Phase 1079 are now satisfied (1075, 1076, 1077, 1078).
  - Invoke `/gsd:plan-phase 1079` (Close Gate + Hygiene — TI-03, VG-01, HYG-01)
- Phase 1079's TI-03 baseline planner MUST first disposition the 7 verification-gap failures documented in `.planning/phases/1075-conftest-test-db-lifecycle-refactor-baseline-fixes/1075-05-VERIFICATION.md` (or open Plan 1075-06 to do so before TI-03 captures). Phase 1076 also surfaced 3 pre-existing environmental issues (ENV-01..03) that overlap with the verification-gap set — see `1076-VERIFICATION.md` Pre-Existing Environmental Issues section. Phase 1077 surfaced 36 pre-existing TypeScript diagnostic errors in 14 untouched frontend test files — see `1077-VERIFICATION.md` Typecheck section for the full inventory; candidate for HYG-01 triage in Phase 1079.
- Phase 1079's VG-01 task exercises the same `test_alembic_upgrade_clean_db.sh` script against a live `docker compose up -d --build` stack, which doubles as the e2e closure of SEC-OBSV-03 (Phase 1078 closed it structurally; Phase 1079 closes it end-to-end).

## Deferred Items

Carried into v1017 from v1016 close (2026-05-21):

- **174 quick_tasks** — triaged in Phase 1079 HYG-01 (target: trim to <50 active)
- **1 verification_gap** — Phase 1071 KNOWN-02 docker smoke (deferred from Phase 1074 close-gate); re-verified live in Phase 1079 VG-01
- **8 v1015-carried P2** — TD-DEFER-01..08; 7 closed in v1017 ING-01..07 (1 was closed in v1016 Phase 1073 REMED-01/02)
- **11 v1015 baseline pytest failures + 1363 test-DB-lifecycle conftest infra errors** — Phase 1075 TI-01 (conftest) + TI-02 (11 failures) → CLOSED 2026-05-21 within named scope
- **SEC-OBSV-03 alembic-clean-DB CI wiring** — Phase 1078 CI-01 → CLOSED 2026-05-21 (structural; e2e live-stack verify deferred to Phase 1079 VG-01)

Discovered 2026-05-21 by Plan 1075-05 full-suite verification (NOT in original v1017 scope):

- **7 new sequential failures outside TI-02 named scope** — `test_layering.py::test_no_unjustified_broad_except_sites`, `test_phase_279_user_lifecycle.py::test_register_emits_user_register_audit`, `test_phase_279_user_lifecycle.py::test_register_disabled_does_not_emit_audit`, `test_reupload_idor.py::TestReuploadIDOROwnerAllowed::test_owner_gets_non_404_on_service_preview`, `test_reupload_service.py::TestServiceReuploadWorker::test_reupload_service_preserves_identity_and_increments_version`, `test_reupload_service.py::TestServiceReuploadWorker::test_reupload_service_without_token_returns_retry_guidance_on_auth_failure`, `test_tasks_common_phase_brackets.py::test_job_phase_session_none_branch_rolls_back_on_exception`. Recommended disposition: Plan 1075-06 follow-up OR v1018 hygiene sweep. See `.planning/phases/1075-conftest-test-db-lifecycle-refactor-baseline-fixes/1075-05-VERIFICATION.md` NEW-DISCOVERY table for per-test root cause and fix shape.
- **Parallel-mode environmental cap (`pytest -n auto` on 16 xdist workers triggers Postgres recovery cascade — 1363 CannotConnectNowError)** — Recommended disposition: tune `-n 4`/`-n 8` for host runs OR increase PG `max_connections` OR add per-worker pool sizing to conftest. Defer to v1018 conftest hardening or Phase 1079 follow-up.
