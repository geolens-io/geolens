# v1017 Test Infra & Audit Tail — Requirements Archive

**Defined:** 2026-05-21
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

**Milestone framing:** Hygiene/hardening close of v1015 + v1016 carryover. No new user-facing features; restore test signal accuracy, harden ingest lifecycle on residual P2 items, wire alembic clean-DB upgrade test into CI, and resolve one deferred verification gap. Public tag target: `v1.5.2` (patch).

## v1017 Requirements

Each maps to exactly one phase.

### Test Infrastructure

- [x] **TI-01**: Conftest test-DB lifecycle refactor — eliminate the 1363 `asyncpg.exceptions.InvalidCatalogNameError` errors observed in v1016 Phase 1074 full-suite run. Per-test database creation/teardown must succeed reliably across the entire `backend/tests/` tree under `pytest -x` and `pytest -n auto`.
- [x] **TI-02**: Fix 11 v1015 baseline pytest failures — `test_defer_orphan_guard.py` ×3, `test_ingest.py` ×3, `test_maps_style_json.py` ×5. Failures must be either fixed at root cause (production code or test logic) or skipped with a documented rationale in a `pytest.mark.skip(reason=...)` decorator linked to an issue. (Plan 02: 3/11 fixed — test_defer_orphan_guard.py complete. Plans 03 + 04 cover the remaining 8.)
- [x] **TI-03**: Establish post-v1017 pytest baseline — full `backend/tests/` suite passes (or has documented skips only); zero `InvalidCatalogNameError` errors. Captured in a baseline doc at `.planning/audits/PYTEST-BASELINE-2026-05-21.md` so future regressions are spotted immediately.

### CI Hardening

- [x] **CI-01**: Wire `test_alembic_upgrade_clean_db.sh` (built in v1016 Phase 1071 KNOWN-02) into GitHub Actions. The workflow must spin up a clean Postgres + PostGIS instance, run `alembic upgrade head`, and fail the build if migrations break against a fresh DB. Closes SEC-OBSV-03 from Phase 1072 triage.

### Ingest P2 Closure

Drawn from `.planning/audits/INGEST-AUDIT-2026-05-21.md`. P2-06 + P2-07 were closed in v1016 Phase 1073 (REMED-01, REMED-02). v1017 closes the remaining 7 documented P2 findings.

- [x] **ING-01**: P2-01 — Add `getCogDownloadUrl(id)` helper in `frontend/src/api/datasets.ts` alongside `getExportUrl()`. Replace string concat at `frontend/src/components/import/JobProgress.tsx:42`. Drift risk mitigation.
- [x] **ING-02**: P2-02 — Drop internal `await session.commit()` from `metadata.py` helpers (`ensure_geom_column`, `clip_to_mercator_bounds`, `add_4326_column`, `grant_reader_access`). Let `_finalize_ingest` commit once. Add a regression test that exercises a phase-2 failure scenario.
- [x] **ING-03**: P2-03 — Switch local-storage COG export from `await storage.get(asset_uri)` (full buffer) to a streaming `get_stream(asset_uri)` provider method. Eliminates 5 GB resident memory pre-stream on self-hosters.
- [x] **ING-04**: P2-04 — Restrict worker exports temp-dir sweep at `backend/app/platform/jobs/worker.py:174-185` to entries older than 1 hour via `stat.st_mtime`; log skipped items. Avoids truncating in-flight large exports on worker restart.
- [x] **ING-05**: P2-05 — Extract `uploadChunks(urls, file, partSize)` helper in a new `frontend/src/api/_presignedUpload.ts`; rewire `ingest.ts:147-159` + `datasets.ts:370-383` through it. Single point for future retry/abort/backoff.
- [x] **ING-06**: P2-08 — Add single-retry behaviour to `_apply_reupload_swap` at `tasks_common.py:880`. On `lock_timeout` failure, retry once with `SET LOCAL lock_timeout = '15s'` plus a brief sleep; log the contention event so ops can correlate with autovacuum runs.
- [x] **ING-07**: P2-09 — Add optional `strict_cog: bool` field to `RasterCommitRequest`. When true, raster commit rejects non-COG TIFFs at the magic-byte rule instead of silently routing through `check_and_prepare_cog` conversion. Default `False` preserves current behavior.

### Verification Gap

- [x] **VG-01**: Phase 1071 KNOWN-02 docker-smoke re-verify — confirm the alembic clean-DB upgrade script runs successfully against a freshly built `docker compose up -d --build` stack (db + api + worker). Document any environmental discrepancies between the in-script approach and live container runtime. Closes the deferred follow-up flagged in v1016 STATE.md `Deferred Items`.

### Hygiene Close

- [x] **HYG-01**: Quick_tasks tail triage — review the 174 carried `quick_tasks` records, archive or close those superseded by v1014/v1015/v1016 work, and move any still-relevant items into `.planning/todos/pending/` with proper frontmatter. Goal: trim the tail to under 50 active items.

## Future Requirements

Items deferred from v1017 to future milestones:

- TD-2 P2-10..P2-15 (if surfaced in a future audit beyond the 7 documented in INGEST-AUDIT-2026-05-21) — track separately.
- Promotion of `strict_cog` from optional opt-in to required default — coordinated with a CLI/manifest schema bump.
- Conftest hardening beyond `InvalidCatalogNameError` — fixtures, isolation, parallel-run safety improvements.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Fresh `/sec-audit` + `/ingest-audit` re-pass at front | v1016 ran both clean on 2026-05-21 (1 day prior); audits run at close-gate as verification, not gating. |
| New user-facing features | v1017 is a patch tag (`v1.5.2`); user-facing capability ships in next minor/major. |
| Pause v1.7 Marketplace resume | v1.7 Marketplace & Distribution remains paused at Phase 40 (AWS AMI Build); independent scope. |
| Map Builder polish / Bug fixes | v1011/v1011.1 closed the builder polish tail; if new builder bugs surface they go to a separate milestone, not v1017. |
| Cross-repo docs/marketing | Lives in `~/Code/getgeolens.com/` repo; out of this repo's scope. |
| Backend API contract changes | None planned — all v1017 changes are internal hardening + helper extraction; OpenAPI snapshot is stable across the milestone. |

## Traceability

Populated by `gsd-roadmapper` 2026-05-21.

| Requirement | Phase | Status |
|-------------|-------|--------|
| TI-01 | Phase 1075 | Complete |
| TI-02 | Phase 1075 | Complete (11/11 — Plans 02 + 03 + 04 done) |
| TI-03 | Phase 1079 | Complete |
| CI-01 | Phase 1078 | Complete |
| ING-01 | Phase 1077 | Complete |
| ING-02 | Phase 1076 | Complete |
| ING-03 | Phase 1076 | Complete |
| ING-04 | Phase 1076 | Complete |
| ING-05 | Phase 1077 | Complete |
| ING-06 | Phase 1076 | Complete |
| ING-07 | Phase 1076 | Complete |
| VG-01 | Phase 1079 | Complete |
| HYG-01 | Phase 1079 | Complete |

**Coverage:**
- v1017 requirements: 13 total
- Mapped to phases: 13 (100%) ✓
- Unmapped: 0

**Phase distribution:**
- Phase 1075 (Conftest + Baseline Fixes): 2 reqs (TI-01, TI-02)
- Phase 1076 (Backend Ingest P2): 5 reqs (ING-02, ING-03, ING-04, ING-06, ING-07)
- Phase 1077 (Frontend Ingest P2): 2 reqs (ING-01, ING-05)
- Phase 1078 (CI Alembic Workflow): 1 req (CI-01)
- Phase 1079 (Close Gate + Hygiene): 3 reqs (TI-03, VG-01, HYG-01)

---

*Requirements defined: 2026-05-21*
*Last updated: 2026-05-21 — traceability populated by `gsd-roadmapper` after roadmap creation*
