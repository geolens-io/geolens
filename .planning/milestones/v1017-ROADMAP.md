# v1017 Test Infra & Audit Tail — Milestone Archive

**Status:** ✅ Complete
**Shipped:** 2026-05-21
**Tag:** `v1017` (local) + `v1.5.2` (public) at commit `c968392b`
**Phases:** 5 (1075-1079)
**Plans:** 20 (5 + 6 + 2 + 2 + 5)
**Requirements:** 13/13 satisfied
**Audit:** PASSED — see `.planning/v1017-MILESTONE-AUDIT.md`

## Milestone Summary

Hygiene/hardening close of v1015 + v1016 carryover. No new user-facing features. Restored test signal accuracy (TI-01 conftest refactor eliminated 1363 `InvalidCatalogNameError`, TI-02 fixed all 11 named baseline failures), closed 7 deferred ingest P2 findings (ING-01..07), wired alembic clean-DB script into GitHub Actions (CI-01), re-verified Phase 1071 KNOWN-02 docker-smoke gap (VG-01 — with 3 latent script bugs fixed inline), captured post-fix pytest baseline (TI-03), and triaged the 196-item quick_tasks tail to 0 active (HYG-01).

Live Playwright MCP smoke 5/5 surfaces green at close-gate. CHANGELOG `[1.5.2] - 2026-05-21` covers all 13 requirements explicitly by ID.

## Key Decisions

- **Test infrastructure runs FIRST (Phase 1075)** — gates all downstream test signal.
- **Backend + Frontend P2 closures split by surface** (Phase 1076 / 1077) — testability + atomic close.
- **CI-01 alembic workflow (Phase 1078)** — independent of test infra and ingest work; parallel-safe.
- **TI-03 baseline doc LAST (Phase 1079)** — captures post-fix steady state.
- **VG-01 (Phase 1079)** caught 3 latent bugs in the Phase 1071 script (PYTHONPATH, PGSSLMODE, init-db.sh heredoc quoting) — fixed inline before script ran cleanly. The same fixes benefit CI-01.
- **Public tag `v1.5.2` (patch)** — hygiene/hardening only; no user-facing capability.
- **No fresh /sec-audit + /ingest-audit at front** — v1016 ran both clean 1 day prior; audits not needed for hygiene milestone.

## Carryover Closed

All v1016 STATE.md "Deferred Items" closed in v1017:
- 196 quick_tasks → archived (HYG-01; up from the 174 quoted in v1016 STATE)
- Phase 1071 KNOWN-02 docker-smoke → re-verified (VG-01)
- 7 v1015-carried P2 (TD-DEFER-01..08 minus the 1 closed in v1016 Phase 1073) → closed via ING-01..07
- 11 v1015 baseline pytest failures → fixed (TI-02)
- 1363 InvalidCatalogNameError errors → eliminated (TI-01)
- SEC-OBSV-03 alembic-clean-DB CI wiring → wired (CI-01)

## Deferred to v1018

8 items handed forward — full disposition in `.planning/v1017-MILESTONE-AUDIT.md`:

| Source | Item |
|--------|------|
| Phase 1075 NEW-DISCOVERY | 7 pre-existing failures in OTHER files (test_layering, test_phase_279_user_lifecycle ×2, test_reupload_idor, test_reupload_service ×2, test_tasks_common_phase_brackets) |
| Phase 1079-03 fix-discovery | backend/app/core/config.py:database_connect_args SSL handling (low priority) |

## Stats

- **Commits:** 53 (commit range `415f90a9..5754ec22`)
- **Files changed:** 944 (inflated by HYG-01 archive of 196 quick_tasks)
- **Substantive code changes:** Modest — refactors + new helpers + 5 new test files + 1 GitHub Actions job
- **Test count delta:** +20+ new tests across phases 1075/1076/1077 (6 conftest lifecycle + 3 metadata commit + 4 storage stream + 5 worker sweep + 5 lock retry + 4 strict-COG + 5 uploadChunks)

---

### ✅ v1017 Test Infra & Audit Tail (Shipped 2026-05-21)

**Milestone Goal:** Restore test signal accuracy by refactoring the broken conftest test-DB lifecycle that produced 1363 `InvalidCatalogNameError` errors in v1016's full pytest run; fix the 11 carried baseline pytest failures so a green suite means something; close the 7 deferred P2 ingest findings (TD-DEFER-01..08, minus the 1 closed in v1016); wire `test_alembic_upgrade_clean_db.sh` (built in v1016 Phase 1071) into GitHub Actions to close SEC-OBSV-03; re-verify the deferred Phase 1071 KNOWN-02 docker smoke; and trim the 174-item quick_tasks tail to under 50. Public tag target: `v1.5.2` (patch — hygiene/hardening only, no user-facing features).

**Sequencing rationale:** Test infrastructure runs FIRST (Phase 1075) so every downstream phase gets clean pytest signal. Backend + Frontend P2 closures (Phase 1076, 1077) split by surface for testability. CI-01 alembic workflow (Phase 1078) is independent of test infra and ingest work. Close-gate (Phase 1079) bundles the post-fix pytest baseline doc (TI-03 must be LAST so it captures the post-fix steady state), the deferred docker-smoke verification (VG-01), and the quick_tasks triage (HYG-01) into a single closure phase that also runs the full close-gate protocol.

- [x] **Phase 1075: Conftest Test-DB Lifecycle Refactor + Baseline Fixes** - Eliminate the 1363 `asyncpg.exceptions.InvalidCatalogNameError` conftest errors and fix the 11 v1015-carryover baseline pytest failures so pytest signal is trustworthy on all downstream phases (Complete 2026-05-21 within named scope; 7 verification-gap findings + parallel-mode environmental cap documented for Phase 1079)
- [x] **Phase 1076: Backend Ingest P2 Closure** - Close 5 backend P2 findings: metadata.py internal commit subversion (P2-02), local-storage COG streaming (P2-03), worker exports temp-dir age guard (P2-04), reupload swap autovacuum retry (P2-08), strict_cog raster commit flag (P2-09) (Complete 2026-05-21; 256/256 targeted regression tests passing)
- [x] **Phase 1077: Frontend Ingest P2 Closure** - Extract `getCogDownloadUrl()` helper (P2-01) and shared `uploadChunks()` presigned-upload helper (P2-05) so future retry/abort/backoff lands in one place (Complete 2026-05-21; 2105/2105 vitest tests passing across 213 files; `tsc -b` exit 0 with zero errors in touched files)
- [x] **Phase 1078: CI Alembic Clean-DB Upgrade Workflow** - Wire `test_alembic_upgrade_clean_db.sh` into a GitHub Actions workflow that spins up a clean Postgres + PostGIS, runs `alembic upgrade head`, and fails the build on migration regressions (Complete 2026-05-21; YAML lint exit 0; all 4 acceptance greps green; SEC-OBSV-03 closed structurally — e2e live-stack verify deferred to Phase 1079 VG-01)
- [x] **Phase 1079: Close Gate + Hygiene** - (Complete 2026-05-21; TI-03 baseline doc, VG-01 docker-smoke re-verify (3 latent script bugs fixed inline), HYG-01 archived 196 quick_tasks, full close-gate green, CHANGELOG [1.5.2] entry, tags cut) — was: Capture post-v1017 pytest baseline doc (TI-03), docker-smoke re-verify deferred Phase 1071 KNOWN-02 (VG-01), triage 174 quick_tasks to <50 active (HYG-01), full close-gate protocol (pytest + typecheck + e2e:smoke + live MCP), CHANGELOG `[1.5.2] - 2026-05-21`, tag `v1017` + `v1.5.2`

## Phase Details

### Phase 1075: Conftest Test-DB Lifecycle Refactor + Baseline Fixes
**Goal:** Restore trustworthy pytest signal — every downstream phase must be able to detect test regressions immediately
**Depends on:** Nothing (first phase; gates all downstream test signal)
**Requirements:** TI-01, TI-02
**Success Criteria** (what must be TRUE):
  1. Running `uv run pytest` in `backend/` produces zero `asyncpg.exceptions.InvalidCatalogNameError` errors across the full `backend/tests/` tree
  2. Per-test database creation/teardown works reliably under both `pytest -x` (sequential) and `pytest -n auto` (parallel) — no test contaminates another
  3. Each of the 11 v1015 baseline failures (`test_defer_orphan_guard.py` ×3, `test_ingest.py` ×3, `test_maps_style_json.py` ×5) is either fixed at root cause (production code or test logic) or skipped with `pytest.mark.skip(reason=...)` linked to a tracked GitHub issue
  4. Full backend pytest run reports the same green/red signal a developer sees locally — no infrastructure noise hiding logic regressions
**Plans:** 5/5 plans executed (Complete 2026-05-21)
- [x] 1075-01-PLAN.md — Conftest test-DB lifecycle refactor (TI-01: pytest-xdist worker isolation, ordered teardown, regression test)
- [x] 1075-02-PLAN.md — Fix `test_defer_orphan_guard.py` 3 failures (TI-02 partial)
- [x] 1075-03-PLAN.md — Fix `test_ingest.py` 3 named failures (TI-02 partial: test_upload_success, test_csv_upload_success, test_service_job_commits_with_service_body)
- [x] 1075-04-PLAN.md — Fix `test_maps_style_json.py` 5 failures (TI-02 partial — shared root-cause analysis)
- [x] 1075-05-PLAN.md — Full-suite verification + commit (TI-01 + TI-02 closed within named scope; 7 verification-gap findings handed to 1079, see `1075-05-VERIFICATION.md`)

### Phase 1076: Backend Ingest P2 Closure
**Goal:** Close the backend ingest P2 lifecycle hardening tail — remove all forward-only commit hazards, memory pressure spikes, and rare-but-real swap failures
**Depends on:** Phase 1075 (clean pytest signal needed to detect regressions in the new P2-02 regression test)
**Requirements:** ING-02, ING-03, ING-04, ING-06, ING-07
**Success Criteria** (what must be TRUE):
  1. `metadata.py` helpers (`ensure_geom_column`, `clip_to_mercator_bounds`, `add_4326_column`, `grant_reader_access`) no longer call `await session.commit()` internally; a new regression test asserts that a phase-2 failure after `add_4326_column` correctly rolls back the column-add change via `_finalize_ingest`'s outer commit boundary
  2. Local-storage COG export streams bytes from disk via a new `storage.get_stream()` provider method instead of reading the full file into memory — a 5 GB COG no longer pins 5 GB of resident memory before the first byte streams to the client
  3. Worker exports temp-dir sweep at `backend/app/platform/jobs/worker.py:174-185` only deletes entries older than 1 hour (via `stat.st_mtime`) and logs each skipped item; in-flight large exports survive worker restarts
  4. `_apply_reupload_swap` retries once with `SET LOCAL lock_timeout = '15s'` plus a brief sleep on a `lock_timeout` failure and logs the contention event for ops correlation
  5. `RasterCommitRequest` accepts an optional `strict_cog: bool` field (default `False`); when `True`, raster commit rejects non-COG TIFFs at the magic-byte rule instead of silently routing through `check_and_prepare_cog` conversion
**Plans:** 6/6 plans complete
- [x] 1076-01-PLAN.md — ING-02 metadata.py phase-2 commit boundary + regression test
- [x] 1076-02-PLAN.md — ING-03 local-storage COG streaming via storage.get_stream()
- [x] 1076-03-PLAN.md — ING-04 worker exports temp-dir mtime guard
- [x] 1076-04-PLAN.md — ING-06 _apply_reupload_swap lock_timeout single retry
- [x] 1076-05-PLAN.md — ING-07 strict_cog opt-in flag on RasterCommitRequest
- [x] 1076-06-PLAN.md — Phase verification + close-gate

### Phase 1077: Frontend Ingest P2 Closure
**Goal:** Close the frontend ingest P2 hygiene tail — centralize drift-prone URL construction and chunked-upload logic so future retry/abort/backoff lands in one place
**Depends on:** Phase 1075 (clean pytest signal; no inter-plan dependency on Phase 1076)
**Requirements:** ING-01, ING-05
**Success Criteria** (what must be TRUE):
  1. A `getCogDownloadUrl(id: string): string` helper exists in `frontend/src/api/datasets.ts` alongside `getExportUrl()`; `frontend/src/components/import/JobProgress.tsx:42` no longer constructs the `/api/datasets/.../download/cog` URL via string concatenation
  2. A new `frontend/src/api/_presignedUpload.ts` module exports a `uploadChunks(urls, file, partSize)` helper; both `frontend/src/api/ingest.ts:147-159` and `frontend/src/api/datasets.ts:370-383` consume it instead of carrying duplicate PUT loops
  3. Vitest covers the shared helper (presigned-upload chunk loop) — a future retry/abort/backoff change requires editing one location to land everywhere
**Plans:** TBD
**UI hint:** yes

### Phase 1078: CI Alembic Clean-DB Upgrade Workflow
**Goal:** Migration regressions against a fresh database fail the CI build immediately, not at production rollout
**Depends on:** Nothing (independent of test infra and ingest P2 work — can execute in parallel with Phase 1076/1077)
**Requirements:** CI-01
**Success Criteria** (what must be TRUE):
  1. A new GitHub Actions workflow (`.github/workflows/alembic-clean-db.yml` or equivalent) spins up a clean Postgres + PostGIS service container, runs `backend/scripts/test_alembic_upgrade_clean_db.sh`, and fails the build if the script exits non-zero
  2. The workflow runs on every push to `main` plus every pull request that touches `backend/alembic/`, `backend/scripts/test_alembic_upgrade_clean_db.sh`, or `backend/app/models/`
  3. A deliberately-broken migration (asserted via a temporary local sandbox or a pinned negative-control test commit) is shown to fail the workflow — confirming the build break is real, not a green-on-skip false positive
  4. SEC-OBSV-03 (the observational finding from Phase 1072 triage) is documentably closed in the v1017 milestone audit
**Plans:** TBD

### Phase 1079: Close Gate + Hygiene
**Goal:** v1017 ships with a captured post-fix pytest baseline doc, the deferred Phase 1071 docker-smoke gap closed, and the quick_tasks tail trimmed — and the full close-gate protocol passes on rebuilt containers
**Depends on:** Phase 1075, 1076, 1077, 1078 (all phases must land before TI-03's baseline doc captures the steady state)
**Requirements:** TI-03, VG-01, HYG-01
**Success Criteria** (what must be TRUE):
  1. `.planning/audits/PYTEST-BASELINE-2026-05-21.md` exists and documents the post-v1017 pytest baseline: total tests, total skips (with rationale linked to issues), zero `InvalidCatalogNameError` errors, exact pass count — future regressions are spotted immediately by diffing against this baseline
  2. `backend/scripts/test_alembic_upgrade_clean_db.sh` runs successfully against a freshly-built `docker compose up -d --build` stack (db + api + worker); any environmental discrepancies between the in-script test approach and live container runtime are documented in the v1017 milestone audit — Phase 1071 KNOWN-02 deferred verification is closed
  3. The 174-item `quick_tasks` tail is reviewed; superseded items (closed by v1014/v1015/v1016 work) are archived to `resolved/`; still-relevant items are promoted to `.planning/todos/pending/` with proper frontmatter; active count is under 50
  4. Full close-gate protocol passes: full `uv run pytest` in `backend/` (clean baseline per TI-01/TI-02/TI-03), `npm run typecheck` exit 0, `npm run e2e:smoke:builder` green, live Playwright MCP smoke (orchestrator-driven) 5/5 surfaces green on rebuilt `localhost:8080` containers
  5. `CHANGELOG.md` carries a `[1.5.2] - 2026-05-21` entry summarizing the test-infra refactor, ingest P2 closures, and CI workflow addition; local `v1017` + public `v1.5.2` tags cut at the post-baseline-doc commit
**Plans:** TBD

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1075. Conftest Test-DB Lifecycle Refactor + Baseline Fixes | 5/5 | Complete | 2026-05-21 |
| 1076. Backend Ingest P2 Closure | 6/6 | Complete | 2026-05-21 |
| 1077. Frontend Ingest P2 Closure | 2/2 | Complete | 2026-05-21 |
| 1078. CI Alembic Clean-DB Upgrade Workflow | 2/2 | Complete | 2026-05-21 |
| 1079. Close Gate + Hygiene | 5/5 | Complete | 2026-05-21 |
