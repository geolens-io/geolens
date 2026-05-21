# Requirements: GeoLens — Milestone v1015 Ingest/Export Lifecycle Hardening

**Defined:** 2026-05-20
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Milestone Goal:** Make every ingest, reupload, and export path correct, atomic, and secure by default. Close the 4 P0 + 5 P1 findings from `/ingest-audit` 2026-05-19, remediate the `router_reupload.py` resource-level IDOR that v1014 acknowledged but deferred, and fold in v1014's hygiene tail — flipping the v1014 milestone audit verdict from "tech_debt + WARNING" to clean.

## v1015 Requirements

REQ-IDs are sourced directly from the originating audit (`docs-internal/audits/ingest-audit-20260519.md` + `.planning/milestones/v1014-MILESTONE-AUDIT.md`) so traceability survives refactors. All 13 are scoped to this milestone.

### Download (Tier A — Ship-blocking)

- [x] **IA-P0-01**: User can click "Download COG" on any raster dataset detail page and receive the COG file. Backend exposes `POST /auth/download-token/{dataset_id}` returning a short-lived `typ='download'` token (helper `auth/service.py:create_download_token` already exists, currently unwired); frontend `downloadCog()` (currently passes session JWT as `?token=` and 401s against `router_export.py:185-201`) mints the download token first, then opens the existing `GET /api/datasets/{id}/download/cog/?token=...` URL. Add Playwright regression that fails on the prior `Authorization: Bearer <session-JWT>` path.

### Reupload (Tier A + Tier B)

- [ ] **REUPLOAD-IDOR-01**: All 6 `router_reupload.py` handlers enforce resource-level access via `check_dataset_access` (write-mode + ownership) in addition to the existing `require_permission("edit_metadata")` role gate. Closes pre-existing IDOR exposure that v1014 deferred (`.pre-commit-config.yaml:76-79` exclusion comment). Pre-commit `visibility-filter-coverage` hook exclusion for `router_reupload.py` is deleted at milestone close. Regression test asserts non-owner editor receives 403 from each handler.
- [ ] **IA-P1-02**: `reupload_service_preview` (`router_reupload.py:185-279`) calls `_assert_compatible_record_type` at function entry — mirroring the File-multipart (`:127`) and presigned (`:521`) paths — so vector→raster or any→VRT swaps surface a useful 4xx instead of a deep-pipeline 500.

### Ingest (Tier A — Ship-blocking)

- [ ] **IA-P0-02**: `/ingest/upload` (`router.py:366-447`) enforces `max_file_size_bytes` at HTTP entry via a chunked size check in `save_upload_file` (`service.py:115-161`) — closing asymmetry with the presigned path (`router.py:154-162` already validates). Worker no longer wastes staging disk on oversize uploads. Unit test: oversize upload returns 413 before any disk write.
- [ ] **IA-P0-03**: `commit_import` (`router.py:589-661`) re-runs `validate_url_for_ssrf` on `job.source_url` at commit time, and the service-URL worker tasks in `ingest_service` / `reupload_service` re-validate before fetch — closing the DNS-rebinding TOCTOU between preview and commit (default 60s job TTL). Mirrors the existing COG-redirect defense at `router_export.py:299-320`. Unit test: rebinding fixture (preview resolves public IP, commit resolves private) rejects at commit.
- [ ] **IA-P0-04**: `IngestJob.last_heartbeat_at` story is resolved. Either (a) long-running ingest tasks (file ingest worker, service-URL fetch, raster COG-conversion) write `last_heartbeat_at = utcnow()` every ≤60s and `recover_stale_jobs` (`worker.py:41-130`) keeps its 5-min cutoff; OR (b) the column + `IS NULL` branch are removed and stale recovery relies on the 1-hour `JOB_TIMEOUT_SECONDS` sweep in `jobs/router.fail_stale_jobs` (already invoked every 5 min by `_stale_jobs_sweeper`). The current state — column declared, queried, never written, collapsing to `created_at < now() - 5min` — must end. Regression test: rolling-deploy simulation (kill worker mid-ingest after 6 min) leaves the job recoverable on restart instead of force-killed.

### Service-Ingest Hardening (Tier B)

- [ ] **IA-P1-06**: `run_ogr2ogr_service` (`ingest/ogr.py:591-593`) stops passing the bearer token via subprocess env `GDAL_HTTP_HEADERS=Authorization: Bearer <token>` (observable via `/proc/<pid>/environ`). Switch to either a temp-file-backed `GDAL_HTTP_HEADER_FILE` (preferred) or a one-shot `GDAL_HTTP_BEARER` env wrapper that is cleared post-spawn. Honors the AUTH-04 comment promise at `router.py:626-628` ("never persisted"). Unit test: subprocess env audit asserts `Authorization:` substring absent.
- [ ] **IA-P1-03**: `.vrt` ingestion is hardened against magic-byte bypass + GDAL `<SourceFilename>` path-traversal/SSRF. (a) `validation.py:71-72` adds explicit `<VRTDataset` XML sniff for `.vrt` extensions (currently `EXTENSION_CONTENT_MAP` lookup misses VRT and skips validation); (b) worker env sets `CPL_VSIL_CURL_ALLOWED_EXTENSIONS=tif,tiff,vrt` + `VRT_VIRTUAL_OVERVIEWS=NO`; (c) `manifest_sources._reject_dotdot_segments` extension scans VRT body content for `../` and absolute paths inside `<SourceFilename>`. Admin-only blast-radius today, defense-in-depth. Tests cover all three layers.

### Export (Tier B)

- [ ] **IA-P1-04**: `validate_where_clause` (`export/service.py:49-77`) rejects statement terminators (`;`), comments (`--`, `/* */`), and unbalanced single-quotes — in addition to the current `re.findall(r"[A-Za-z_][A-Za-z0-9_]*", where)` identifier allow-list. Raw clause continues to `ogr2ogr -where` (`export/ogr.py:87-88`); block at the validator, do not rely on libpq multi-statement behavior via GDAL driver. Unit tests cover at least: `; DROP TABLE foo`, `' OR '1'='1`, `-- comment`, `/* block */`, and balanced positive cases.
- [ ] **IA-P1-01**: `export_dataset_endpoint` (`processing/export/router.py:31-45`) uses `Depends(require_permission("export"))` instead of `Depends(get_current_active_user)` — closing capability-matrix asymmetry with `download_cog` (`router_export.py:236-245`). Regression test: admin revokes `export` from `viewer`, viewer's `/api/datasets/{id}/export/` returns 403.

### Hygiene Close-out (Tier C)

- [ ] **HYG-01**: Pending-todo files exist under `.planning/todos/pending/` for the 5 v1014 deferred INFO findings — Phase 1062 IN-01 (`.env.example` PASSWORD_MIN_LENGTH/PASSWORD_REQUIRE_CLASSES doc), IN-02 (whitespace symbol-class ambiguity), IN-03 (`exp.Dot` AST bypass test); Phase 1063 IN-01 (`_sanitize_authorization_token` 8-char min undocumented), IN-02 (`StacSearchBody.limit/offset` no `ge`/`le` constraints). Each follows the template established by `2026-05-20-in01-revalidate-redirect-http-305.md`.
- [ ] **HYG-02**: The 6 stale REQUIREMENTS.md unchecked boxes for v1014 already-implemented requirements (SEC-S12, SEC-S13, SEC-FU-05, SEC-FU-06, SEC-FU-07, SEC-CTRL-01) are retroactively ticked in `.planning/milestones/v1014-REQUIREMENTS.md` archive with a one-line `(retroactive)` annotation. This is documentation-only — the implementations already shipped under v1014.
- [ ] **HYG-03**: The 2 existing cheap v1014 INFO todos are closed and moved from `.planning/todos/pending/` to `.planning/todos/resolved/`: `2026-05-20-in01-revalidate-redirect-http-305.md` (return HTTP 305 from `_revalidate_redirect` instead of 302), `2026-05-20-in02-run-ogr2ogr-gdal-followlocation-comment.md` (codify `GDAL_HTTP_FOLLOWLOCATION=NO` rationale comment in `ingest/ogr.py`).

## Future Requirements

Deferred to a future polish/security cycle. Tracked but not in v1015 roadmap.

### Ingest Polish

- **IA-P1-05**: VRT orphan-guard rollback regression test (defensive depth on existing orphan-cleanup path).
- **IA-P1-07**: Dataset job-status cache invalidation on job termination (currently a quality-of-life staleness window).
- **IA-P2 × 10**: 10 P2 findings from ingest-audit 2026-05-19 — bundled into a smaller follow-up after v1015 ships.

### v13.12 Polish Sweep

- **v13.12 LOW × 71**: Naming, doc drift, low-severity polish — defer to dedicated polish sweep.
- **v13.12 MEDIUM × 83**: Scalability cliffs not yet hit; selective adoption only if a P1 forces it.

## Out of Scope

| Feature / Topic | Reason |
|---|---|
| `recreate-public-repo-before-launch` | Cross-repo task; belongs in `~/Code/getgeolens.com/.planning/`, not this repo's milestone. |
| 999.6 Tenant scoping infrastructure | Cloud SaaS prerequisite; user explicitly off near-term roadmap (decision 2026-05-20). |
| 999.13 Persistent connector registry | Deployment/distribution P2; user kept in backlog 2026-05-20. |
| 999.14 Helm chart + AMI Packer pipeline | Deployment/distribution P2; user kept in backlog 2026-05-20. |
| 999.15 SBOM + signed image distribution | Deployment/distribution P2; user kept in backlog 2026-05-20. |
| 999.16 Extract geolens-schemas package | Deployment/distribution P2; user kept in backlog 2026-05-20. |
| Wholesale `router_reupload.py` redesign | Out of scope; `REUPLOAD-IDOR-01` adds the missing resource-level guard without restructuring the 6-handler shape. |
| New ingest formats / new export formats | Hardening milestone, not a feature milestone. |
| GDAL/ogr2ogr version bump | Risk-amplifying outside the audit-finding scope; defer to dedicated upgrade phase. |

## Traceability

Populated by gsd-roadmapper during ROADMAP.md creation.

| Requirement | Phase | Status |
|---|---|---|
| IA-P0-01 | Phase 1065 | Complete |
| REUPLOAD-IDOR-01 | Phase 1065 | Pending |
| IA-P1-02 | Phase 1065 | Pending |
| IA-P0-02 | Phase 1066 | Pending |
| IA-P0-03 | Phase 1066 | Pending |
| IA-P0-04 | Phase 1067 | Pending |
| IA-P1-06 | Phase 1068 | Pending |
| IA-P1-03 | Phase 1068 | Pending |
| IA-P1-04 | Phase 1069 | Pending |
| IA-P1-01 | Phase 1069 | Pending |
| HYG-01 | Phase 1070 | Pending |
| HYG-02 | Phase 1070 | Pending |
| HYG-03 | Phase 1070 | Pending |

**Coverage:**
- v1015 requirements: 13 total
- Mapped to phases: 13
- Unmapped: 0

## Pre-tag gates (per v1010-v1014 pattern)

- typecheck 0 / vitest passing / e2e:smoke:builder full pass / i18n parity
- backend pytest passing (heartbeat decision tests, IDOR closure tests, where-clause validator unit tests, SSRF re-validation tests)
- live Playwright MCP smoke on `localhost:8080` driven by orchestrator — verifies IA-P0-01 download path end-to-end, REUPLOAD-IDOR closure, and worker heartbeat behavior under simulated rolling deploy
- CHANGELOG `[1.5.0]` populated with measured numbers

## Tag plan

- Local tag: `v1015` at the milestone close-gate commit
- Public tag: `v1.5.0` (per v1014 precedent — public tags align with public release cadence, not milestone counter)

## Source documents

- `docs-internal/audits/ingest-audit-20260519.md` (607 lines — lifecycle map + test-gap table + remediation plan)
- `.planning/backlog/ingest-audit-20260519-findings.md` (12-finding backlog table)
- `.planning/milestones/v1014-MILESTONE-AUDIT.md` (WARNING gaps + `router_reupload.py` IDOR section)
- `.pre-commit-config.yaml:76-79` (`router_reupload.py` exclusion comment — to be deleted at milestone close)
- `.planning/seeds/v1015-ingest-export-lifecycle-hardening.md` (this milestone's planted seed)

---
*Requirements defined: 2026-05-20*
*Last updated: 2026-05-21 — traceability table populated by gsd-roadmapper*
