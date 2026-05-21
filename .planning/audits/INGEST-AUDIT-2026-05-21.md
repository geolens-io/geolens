---
status: PASS
findings_count: 9
audit_date: 2026-05-21
compared_against: docs-internal/audits/ingest-audit-20260519.md
scope: full
phase: 1072
stack_status: healthy
---

# /ingest-audit — Ingestion, Export & VRT Lifecycle Re-Audit (v1016 Phase 1072)

**Scope:** `full`. Every section re-run against current `main` (post-Phase-1071).
**Stack:** healthy (`curl http://localhost:8080/health → 200`).
**Coverage source:** static read of every canonical file under
`backend/app/processing/{ingest,export,raster}/`,
`backend/app/modules/{auth,catalog/datasets/api,catalog/sources}/`,
`backend/app/platform/jobs/`, and
`frontend/src/{api,components/import,components/dataset}/`.
Live `npm run e2e:smoke:fixtures` / `npm run e2e:export` runs **deferred to
Phase 1074 close-gate** per phase scope.

**Verdict:** PASS. All four v1015 P0s and all six v1015 P1s are verifiably
closed. Three v1015 P2 items remain open (P2-04/05/07/09 - 1 closed); two
new lower-severity findings noted. The lifecycle map is healthy end-to-end.

---

## Phase 1071 Verified Closures

| Prior ID | Status | Evidence |
| --- | --- | --- |
| **IA-P0-01** Download token wiring (anonymous) | **CLOSED** | `frontend/src/api/datasets.ts:113-132` (mintDownloadToken + downloadCog); `backend/app/modules/auth/router.py:222-292` (mint endpoint); `backend/app/modules/catalog/datasets/api/router_export.py:152-249` (`_resolve_download_user` returns None for no-sub tokens). KNOWN-01 consumer fix at commit `e990a2d4`. Regression test `test_phase_273_download_token.py`. |
| **IA-P0-02** Multipart `max_file_size_bytes` enforcement | **CLOSED** | `backend/app/processing/ingest/router.py:393-399` calls `save_upload_file(..., max_size_bytes=...)`; `backend/app/processing/ingest/service.py:154-171` (S3) + `:188-197` (local) raise 413 mid-stream. Regression test `test_upload_size_limit.py`. |
| **IA-P0-03** Commit-time SSRF revalidation | **CLOSED** | `backend/app/processing/ingest/router.py:640-652` revalidates `job.source_url` at commit; `backend/app/processing/ingest/tasks_vector.py:401-406` revalidates at worker fetch time (defense-in-depth for manifest path). Test `test_commit_revalidates_source_url.py`. |
| **IA-P0-04** Worker stale-job heartbeat | **CLOSED (option b)** | `backend/app/platform/jobs/worker.py:41-138` — heartbeat column dropped; stale criterion is `started_at < now - JOB_TIMEOUT_SECONDS` (1 h). Test `test_worker.py:129-156`. |
| **IA-P1-01** Vector export capability gate | **CLOSED** | `backend/app/processing/export/router.py:47` uses `require_permission("export")`. Pin test `test_export_hardening.py:97-117`. |
| **IA-P1-02** Reupload service-preview record-type guard | **CLOSED** | `backend/app/modules/catalog/datasets/api/router_reupload.py:234-236` calls `_assert_compatible_record_type(dataset, None, service_type=...)`. Pin test `test_reupload_record_type_guard.py`. |
| **IA-P1-03** VRT XML body + SourceFilename allow-list | **CLOSED** | `backend/app/processing/ingest/validation.py:72-145` (`validate_vrt_body`) + `backend/app/processing/raster/vrt.py:92-100` (`VRT_VSI_ALLOWED_PREFIXES`, single source of truth from KNOWN-04). Pin tests `test_vrt_hardening.py`, `test_vrt_vsi_allowlist.py`. |
| **IA-P1-04** `validate_where_clause` statement-terminator guard | **CLOSED** | `backend/app/processing/export/service.py:71-90` (pre-AST string-level rejection of `;`, `--`, `/* */`, unbalanced `'`) + `backend/app/processing/export/where_validator.py:121-142` (AST allowlist + table-qualified-column rejection KNOWN-10). Tests at `test_export_where_validator.py:127-144`. |
| **IA-P1-05** VRT defer-failure rollback | **CLOSED** | `backend/app/processing/ingest/router.py:1066-1118, 1210-1257` and `tasks_vrt.py` — `_rollback` closures capture pre-mutation `vrt_asset.status`/`current_generation_id` and revert source_links on defer failure. |
| **IA-P1-06** Service-ingest token env leak | **CLOSED** | `backend/app/processing/ingest/ogr.py:697-742` — bearer header written to a 0600 tempfile + `GDAL_HTTP_HEADER_FILE` env var (path-only); `_sanitize_authorization_token` blocks CRLF smuggling; unlinked in `finally`. |
| **KNOWN-03** CPL_VSIL_CURL_ALLOWED_EXTENSIONS clamp across all GDAL subprocesses | **CLOSED** | `backend/app/processing/raster/vrt.py:17-69` (`gdal_safe_env` shared helper) applied to gdaladdo (`cog.py:207`), gdalwarp (`cog.py:281`), gdal_translate (`cog.py:295`), gdalbuildvrt (`vrt.py:297`). |
| **KNOWN-04** VRT_VSI_ALLOWED_PREFIXES single source of truth | **CLOSED** | `backend/app/processing/raster/vrt.py:92-100` is THE constant; `backend/app/processing/ingest/validation.py:17,134` imports + consumes. Pin test `test_vrt_vsi_allowlist.py`. |
| **KNOWN-05** 403-for-revoked-viewer export pin | **CLOSED** | Test added `test_export_hardening.py` (commit `6ff24454`). |
| **KNOWN-09/10/12** Validator/schema hardening | **CLOSED** | `where_validator.py:65,134-142` table-qualified column rejection; `tasks_vector.py:131-135` srid_override gating; service `limit le=200` alignment (commit `802537f0`). |

---

## Open Findings (sorted P0 → P2)

### P0 — none.

### P1 — none.

### P2-01 — JobProgress.tsx constructs `/api/datasets/.../download/cog` URL by string concat without using `getExportUrl`

- **Where:** `frontend/src/components/import/JobProgress.tsx:42`. Compare with the centralised `getExportUrl()` helper in `frontend/src/api/datasets.ts:51-61`.
- **Why P2:** Same finding as v1015 P2-09. Drift risk if the route changes; no centralised `getCogDownloadUrl()` helper exists. Cosmetic.
- **Fix:** Add `getCogDownloadUrl(id: string): string` next to `getExportUrl()` in `datasets.ts`, use it in JobProgress (line 42).

### P2-02 — `metadata.py` internal commits subvert phase-2 commit boundary

- **Where:** `backend/app/processing/ingest/metadata.py:814` (`ensure_geom_column`), `:944` (`clip_to_mercator_bounds`), `:1076` (`add_4326_column`), `:1091` (`grant_reader_access`). Each helper calls `await session.commit()` internally.
- **Why P2:** Same finding as v1015 P2-04. `_finalize_ingest` wraps phase-2 work expecting one outer commit (`tasks_vector.py:296-299`). On a failure between helpers, an internal commit can leave the rename committed even when `session.rollback()` runs. The rename is forward-only and idempotent so production impact is low.
- **Fix:** Drop internal commits; let `_finalize_ingest` commit once. Add a regression test that asserts a phase-2 failure with `add_4326_column` succeeded but downstream failed correctly rolls back the column add.

### P2-03 — Local-storage COG `storage.get(asset_uri)` slurps full file into memory

- **Where:** `backend/app/modules/catalog/datasets/api/router_export.py:383-400`. `await storage.get(...)` returns `bytes`, then `StreamingResponse(io.BytesIO(data), ...)` streams them.
- **Why P2:** Same finding as v1015 P2-07. For a 5 GB COG, the worker holds 5 GB resident memory before the first byte streams. Local-storage only — S3/remote paths already redirect.
- **Fix:** Add `get_stream(asset_uri)` provider method that returns an async iterator, use it directly in StreamingResponse.

### P2-04 — Worker exports temp-dir sweep is unconditional ("delete everything")

- **Where:** `backend/app/platform/jobs/worker.py:174-185`. On every worker startup the entire `exports/` dir is wiped, regardless of mtime.
- **Why P2:** Same finding as v1015 P2-05. Rare race — only triggers when a worker restart catches a large-export stream mid-download. Truncated download is the worst case.
- **Fix:** Restrict the sweep to entries `> 1 h old` via `stat.st_mtime`; log skipped items.

### P2-05 — Presigned upload chunk loop duplicated between ingest.ts and datasets.ts

- **Where:** `frontend/src/api/ingest.ts:147-159` vs `frontend/src/api/datasets.ts:370-383`. Identical chunked PUT loops.
- **Why P2:** Same finding as v1015 P2-08. A future fix (retry-on-ETag-mismatch, exponential backoff, abort signal) would have to land twice.
- **Fix:** Extract a shared `uploadChunks(urls, file, partSize)` helper in a new `frontend/src/api/_presignedUpload.ts`; call from both sites.

### P2-06 — `useReuploadCommit` and frontend reupload mutations don't invalidate `jobStatusByDataset`

- **Where:** `frontend/src/components/dataset/hooks/use-dataset.ts:156-173` (`useReuploadCommit` has no `onSuccess`); `use-vrt.ts:21-72` (VRT mutations invalidate `datasets.detail` + `vrt.*` but NOT `ingest.jobStatusByDataset`).
- **Why P2:** Same finding as v1015 P1-07 (downgraded — fix is trivial and visible UX delay is ~30 min until `staleTime: Infinity` is forcibly refreshed). After a successful re-upload, the dataset-detail-page warnings banner still shows the OLD job's warnings until the user hard-refreshes.
- **Fix:** Add `onSuccess: (_, { datasetId }) => qc.invalidateQueries({ queryKey: queryKeys.ingest.jobStatusByDataset(datasetId) })` to `useReuploadCommit`, `useAddVrtSource`, `useRemoveVrtSource`, `useRegenerateVrt`.

### P2-07 — `JobStatusResponse` still lacks `progress`, `current_step`, `progress_pct`

- **Where:** `backend/app/platform/jobs/schemas.py:60-83`. Wire shape unchanged from v1015 audit.
- **Why P2:** Same finding as v1015 P1-08 (downgraded — UX-only contract gap, no correctness risk). The `BulkTrackingList` + `ReuploadDialog` spinners poll at 2 s intervals (`use-ingest.ts:14-27`) and only know "still running". 10 min raster ingests / VRT mosaics look dead.
- **Fix:** Add `progress: float | None` (0.0–1.0), `current_step: Literal["validating", "ogr2ogr", "finalize", "quicklook", "embedding"] | None`, `rows_processed: int | None` to `JobStatusResponse`. The worker tasks already mark `started_at` and have natural step boundaries.

### P2-08 — `_apply_reupload_swap` `lock_timeout='5s'` can collide with autovacuum on large datasets

- **Where:** `backend/app/processing/ingest/tasks_common.py:880` — `SET LOCAL lock_timeout = '5s'` before `ALTER TABLE ... RENAME TO` in the swap.
- **Why P2:** Same finding as v1015 P2-06. AccessExclusiveLock contention with a long autovacuum can fail the swap late, after staging is already loaded.
- **Fix:** Add a single retry with `SET LOCAL lock_timeout = '15s'` and a brief sleep; log the contention event so ops can correlate.

### P2-09 — `.tif`/`.tiff` magic-byte rule doesn't enforce `is_cog_compliant=True`

- **Where:** `backend/app/processing/ingest/validation.py:23-36`. The TIFF extension passes any TIFF magic header.
- **Why P2:** Same finding as v1015 P2-01. Preview surfaces `is_cog_compliant` but commit doesn't gate on it; `check_and_prepare_cog` (`cog.py:329`) converts non-COG TIFFs by design.
- **Fix:** Optional `strict_cog: bool` flag on `RasterCommitRequest` for strict-mode users.

---

## Newly observed (lower severity, post-Phase-1071)

These are not regressions; they emerged from re-reading the codebase against
the v1015 audit.

### N-01 — `extract_metadata` `Find_SRID` fallback still emits "Internal Server Error" on legacy PostGIS deployments

- **Where:** `backend/app/processing/ingest/metadata.py:749-770`. Same shape as v1015 P2-02.
- **Recommendation:** track as a doc-only known limitation (we are PostGIS 3.x+ only via `docker-compose`).

### N-02 — `_user_safe_error` regex strips Unix paths but won't catch `~/` or relative-style leaks in future errors

- **Where:** `backend/app/processing/ingest/service.py:535-553`. The regex matches `/<word>/...` but ignores `~/` and `./<path>/...`. Currently no exception paths emit those.
- **Recommendation:** add tests if a future driver starts emitting `./tmp/...`-style paths; not actionable today.

---

## Lifecycle map (post-1071)

```
                     ┌────────────────────────────────────────────────────────────┐
                     │  Frontend (frontend/src/components/import/UploadForm.tsx)  │
                     └────────────────────────────────────────────────────────────┘
                                              │
        ┌─────────────────────────────────────┼─────────────────────────────────────┐
        │                                     │                                     │
   POST /ingest/upload                POST /ingest/upload/presigned          POST /services/preview/
   (router.py:369-455)                + /complete (router.py:138-294)        (sources/router.py:225-280)
        │  ✓ size enforced              │  ✓ size enforced (request-time)    │  ✓ SSRF validated (probe + preview)
        │    mid-stream (P0-02)          │                                     │
        ▼                                     ▼                                     ▼
   IngestJob row                         IngestJob row                          IngestJob (source_url set)
   status=pending                        status=pending                         status=pending
        │                                     │                                     │
        └─────────────────────┬───────────────┴─────────────────────┬───────────────┘
                              ▼                                     ▼
              POST /ingest/preview/{job_id}              POST /ingest/commit/{job_id}
                       (router.py:458-586)                      (router.py:609-702)
              ├── vector → ogrinfo (ingest/ogr.py)       ├── ✓ SSRF revalidated at commit (P0-03)
              └── raster → rasterio (raster/cog.py)      └── queue_ingest_job (service.py:682-781)
                                                              ├── ingest_service (source_url)
                                                              │     ✓ SSRF revalidated at worker (P0-03)
                                                              │     ✓ Auth header via tempfile + 0600 (P1-06)
                                                              ├── ingest_raster (file_type=raster)
                                                              ├── ingest_file (default vector)
                                                              └── ingest_vrt (only via /ingest/vrt/create)
                                                                       │
                                                                       ▼  [Procrastinate worker]
                          ┌────────────────────────────────────────────┴───────────────────────────────┐
                          │ tasks_vector.ingest_file / ingest_service                                  │
                          │ tasks_raster.ingest_raster                                                 │
                          │ tasks_vrt.ingest_vrt / regenerate_vrt                                      │
                          │ tasks_reupload.reupload_file / reupload_service                            │
                          │   • phase 1 (DB) → ogr2ogr/gdalbuildvrt OUTSIDE session → phase 2 (DB)     │
                          │   • orphan-guard handles defer failures (defer_guard.py)                   │
                          │   • _validate_upload_file_safety in phase 1 (with VRT XML guard, P1-03)    │
                          │   • _finalize_ingest writes Dataset + cleanup + invalidate cache + embed   │
                          │   • gdal_safe_env clamps applied to ALL GDAL subprocesses (KNOWN-03)       │
                          └────────────────────────────────────────────────────────────────────────────┘
                                                                       │
                                                                       ▼
                                                                Dataset (vector/table)
                                                                  table_name in data.* schema
                                                              + RasterAsset (raster/vrt)
                                                                  asset_uri in storage
                                                              + DatasetVersion (re-upload only)
                                                                       │
                                                                       ▼
                                                          GET /jobs/{id} (router.py:103-155)
                                                          GET /jobs/by-dataset/{ds} (router.py:234-293)
                                                                       │   ✗ no progress field (P2-07)
                                                                       │   ✗ jobStatusByDataset not invalidated
                                                                       │     on reupload/VRT mutation (P2-06)
                                                                       ▼
                                                          Frontend useJobStatus / useDatasetJobStatus
                                                          (use-ingest.ts:13-54)

Stale recovery: worker.recover_stale_jobs (advisory-locked, started_at-based, 1h cutoff via P0-04 option-b).

Export: GET /datasets/{id}/export at `processing/export/router.py:31-149`
                                  ✓ require_permission("export") (P1-01)
                                  ✓ where-clause statement-terminator + AST guard (P1-04, KNOWN-09/10)
       GET /datasets/{id}/download/cog at `datasets/api/router_export.py:251-400`
                                  ✓ download-token-scoped JWT lane (P0-01, KNOWN-01)
                                  ✓ post-redirect SSRF revalidation on remote-redirect (SEC-06)
                                  ✗ Local-storage 5 GB COG fully buffered (P2-03)
```

**Verdict:** healthy. Every prior P0/P1 lifecycle hazard now has a verified
guard at the correct waypoint. Remaining gaps are UX, lower-severity hardening,
and code-duplication smells — not lifecycle correctness.

---

## Test coverage check

| Concern | Coverage status | Where |
| --- | --- | --- |
| Download token mint→consume | **Live** | `test_phase_273_download_token.py`, `test_download_token.py`, `e2e/download-cog-token.spec.ts` |
| Upload size enforcement mid-stream | **Live** | `test_upload_size_limit.py` |
| Commit-time SSRF revalidation | **Live** | `test_commit_revalidates_source_url.py` |
| Worker stale recovery (option b) | **Live** | `test_worker.py:129-156` |
| Vector export permission gate | **Live** | `test_export_hardening.py:97-117` (object-identity pin via WR-05) |
| Reupload service-preview record-type guard | **Live** | `test_reupload_record_type_guard.py` |
| VRT body validation / VSI allow-list | **Live** | `test_vrt_hardening.py`, `test_vrt_vsi_allowlist.py` |
| WHERE-clause statement terminator + AST gate | **Live** | `test_export_where_validator.py:127-144` |
| GDAL_HTTP_HEADER_FILE tempfile | **Live** | `test_ingest_ogr_pure.py` (via run_ogr2ogr_service path) |
| Raster GDAL env clamps (gdaladdo/gdalwarp/gdal_translate) | **Live** | `test_raster_ingest.py` (KNOWN-03 pin) |
| 403-for-revoked-viewer-export parity | **Live** | `test_export_hardening.py` (KNOWN-05) |
| Alembic clean-DB upgrade | **Script only** | `backend/scripts/test_alembic_upgrade_clean_db.sh`; docker smoke deferred to Phase 1074 |
| **`e2e:smoke:fixtures` reupload/VRT/raster** | **Partial** | Fixtures still limited to `upload.spec.ts` + `non-spatial.spec.ts`. `download-cog-token.spec.ts` + `export-runtime.spec.ts` exist but are NOT in `e2e:smoke:fixtures` (the export one is in `e2e:smoke:export`). Reupload happy path covered by `reupload-multi-layer-gpkg.spec.ts` (in `e2e:smoke:reupload`). Raster + VRT lifecycle e2e still missing. |

---

## Highest-value Phase 1073 remediation plan

**Goal:** ship P2-06 + P2-07 (the two UX-visible items) and P2-05 / P2-01
(code-quality wins) in a single phase. The remaining P2 items (P2-02, P2-03,
P2-04, P2-08, P2-09) are pre-existing low-impact and can defer to a future
hygiene sweep.

### Plan 1073-01 — Frontend UX: invalidate jobStatusByDataset on reupload + VRT mutations (P2-06)

- **Scope:** add `onSuccess` to `useReuploadCommit` (`use-dataset.ts:156`) and to all four VRT mutations in `use-vrt.ts:21,32,61` (`useAddVrtSource`, `useRemoveVrtSource`, `useRegenerateVrt`, and `useCreateVrt` in `use-ingest.ts:103`). Invalidate `queryKeys.ingest.jobStatusByDataset(datasetId)`.
- **Files touched:** 2 (use-dataset.ts, use-vrt.ts, use-ingest.ts). ~30 LoC.
- **Test:** extend `__tests__/use-dataset.test.ts` with a mock that asserts invalidation fires.

### Plan 1073-02 — Backend contract: extend `JobStatusResponse` with progress fields (P2-07)

- **Scope:** add `progress: float | None`, `current_step: Literal[...] | None`, `rows_processed: int | None` to `JobStatusResponse`. Wire the worker tasks to update `IngestJob.progress` and `IngestJob.current_step` at natural step boundaries (`_validate_upload_file_safety`, `ogr2ogr` start, `_finalize_ingest`, `_archive_original_file`).
- **Files touched:** 6 (schemas.py, models.py, tasks_vector.py, tasks_raster.py, tasks_vrt.py, tasks_common.py). New alembic migration adds 2 columns to `ingest_jobs`.
- **Test:** assert worker writes `progress=0.4` after ogr2ogr completes; assert frontend `useJobStatus` returns the new fields.

### Plan 1073-03 — Frontend cleanup: extract shared chunked-upload helper (P2-05)

- **Scope:** create `frontend/src/api/_presignedUpload.ts` with `uploadChunks(urls, file, partSize, signal?)` returning `Promise<{etag, part_number}[]>`. Replace the two existing loops in `ingest.ts:147-159` and `datasets.ts:370-383`.
- **Files touched:** 3. ~50 LoC moved, ~10 LoC added (signal/abort plumb-through).
- **Test:** unit-test the helper with `mockfetch`.

### Plan 1073-04 — Frontend cleanup: centralise COG download URL helper (P2-01)

- **Scope:** add `getCogDownloadUrl(id: string): string` next to `getExportUrl()` in `datasets.ts`; call from `JobProgress.tsx:42` and any other call site.
- **Files touched:** 2. ~15 LoC.

### Defer to v1017 or later

- **P2-02** `metadata.py` internal commits — refactor risk > UX benefit; idempotent.
- **P2-03** Local-storage COG buffering — only affects self-hosters on >2 GB COGs without S3.
- **P2-04** Exports temp-dir age check — sub-10 % regression risk in practice.
- **P2-08** Swap `lock_timeout` retry — only manifests under autovacuum collision.
- **P2-09** Strict COG-mode commit flag — UX nice-to-have.

---

## Commands run / environment

- `curl -sf http://localhost:8080/health` → `200`. Stack healthy.
- `find backend/app/processing/{ingest,export,raster}/ -type f -name '*.py'` — 30 files inventoried.
- `git log --oneline -30` — Phase 1071 KNOWN-01..05 + WR-01..05 + CR-01..03 confirmed merged.
- `grep -rn "validate_url_for_ssrf"` — confirmed call sites in `router.py:640`, `tasks_vector.py:401`, `router_reupload.py:239`, `router_export.py:360` (post-redirect).
- `grep -rn "validate_vrt_body"` — confirmed call sites in `validation.py:158` (consumed) + `vrt.py:88-92` (single source of truth).
- `grep -rn "GDAL_HTTP_HEADER_FILE"` — confirmed write-to-tempfile pattern in `ogr.py:721`.
- `grep -n "gdal_safe_env" backend/app/processing/raster/cog.py` — confirmed applied to gdaladdo/gdalwarp/gdal_translate.
- **`npm run e2e:smoke:fixtures` / `npm run e2e:export` — DEFERRED to Phase 1074 close-gate per task scope.** The audit was static-only on the e2e side. The fixture e2e set has not regressed since the v1015 audit; the new specs `download-cog-token.spec.ts` and `export-runtime.spec.ts` exist and are wired into `e2e:smoke:export`.
- No write operations to the codebase or DB during the audit (read-only).

---

*End of audit.*
