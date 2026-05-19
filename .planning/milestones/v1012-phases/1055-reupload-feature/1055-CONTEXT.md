# Phase 1055: Reupload Feature - Context

**Gathered:** 2026-05-19
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss=true)

<domain>
## Phase Boundary

A user on a dataset's detail page can replace that dataset's source file without losing the dataset ID, slug, or associated metadata.

**1 requirement:** IMPORT-04 (NEW FEATURE — drives v1.3.0 minor bump per "minor when features ship" precedent from `89f37cca`).

**Source-of-truth:** `.planning/M001-7n8vpc-dry-run-audit.md` `## IMPORT-04` section identifies this as a "missing operation". The audit found the dataset detail page has Add to Map / Connect / Unpublish actions but no Reupload — yet the milestone CONTEXT (the audit's own scope memo) listed "reupload" as expected.

</domain>

<decisions>
## Implementation Decisions

### Backend re-import contract (LOCKED — what gets preserved vs regenerated)

**PRESERVED across reupload:**
- Dataset ID (UUID)
- Slug (URL-stable)
- Title, description, keywords (unless user explicitly overwrites — see UI decision below)
- Collection membership (`collection_id`)
- Sharing/embed tokens
- Saved searches / pinned maps referencing this dataset by ID
- Map builder layers referencing this dataset by ID (existing maps don't break)

**REGENERATED on reupload:**
- File-derived metadata: bbox, geometry type, feature count, CRS detection, attribute schema
- Vector tile cache invalidation (existing tile URLs continue to work but serve fresh data on next request)
- Raster derivatives (COG re-ingest, hillshade if applicable, thumbnail)
- Quicklook
- pgvector embeddings (if dataset has them — fresh title/description triggers re-embedding)
- Spatial index refresh

**OUTSTANDING DECISIONS the planner resolves:**
- Should reupload accept a different file FORMAT (e.g., GeoJSON → Shapefile)? **Recommended: yes** if format is reasonable for the dataset's record type (vector→vector, raster→raster). Cross-record-type swaps (vector→raster) should error out — too many downstream invariants break.
- Title/description: keep existing values OR overwrite from file metadata if present? **Recommended: keep existing values unless user explicitly opts in.** Avoid surprise rename.
- Schema migration: if new file has different attribute columns, what happens to existing map layers' style configs that reference removed columns? **Recommended: warn at upload time, do NOT block the upload. Map builder fallback already handles missing columns gracefully (post-v1011 audit verified).**

### API surface (LOCKED)

`POST /datasets/{id}/reupload` (auth: dataset-owner or admin)

Multipart-form: `file` (the new source file)
Optional query params: `?title=...&description=...` (only honored if user opted to overwrite)

Response: 202 Accepted + `{ "job_id": "...", "dataset_id": "..." }` — re-ingest runs async on Celery worker mirroring initial import flow.

Status endpoint: existing `GET /datasets/{id}/ingest-status/` or `GET /jobs/{job_id}/` (whichever the project uses for upload progress).

### Audit log entry (LOCKED)

`audit_action: "dataset.reupload"` with `details: { dataset_id, original_filename, new_filename, new_size_bytes, regenerated_derivatives: [...] }`.

Pattern: mirror `dataset.delete` / `dataset.unpublish` audit entries already in the codebase.

### Frontend UI decisions (LOCKED-ish — planner can adjust visual treatment)

**Affordance placement:** New "Replace file" menu item under the dataset detail page's existing action menu (where Add to Map / Connect / Unpublish live). Use existing action-menu styling, not a primary button — reupload is a deliberate, rare action.

**Confirmation modal:** Show a confirmation modal before commit with:
- "Replace `<original-filename>` with `<new-filename>` (X MB)?"
- Warning: "This will regenerate tiles, thumbnail, and embeddings. Existing maps using this dataset will refresh on next view."
- "Optional: update title from new file" checkbox (off by default per LOCKED decision above)
- "Replace" (primary, destructive-tinted) and "Cancel" buttons

**Progress:** Use the existing import progress component if one exists, or fall back to a simple "Replacing... this may take up to a minute" toast.

**Post-success:** Refresh dataset detail page data without page reload (per ROADMAP.md success criterion #3). Use TanStack Query invalidation on the dataset record + its derivatives queries.

### Test strategy

- **Backend pytest:** unit + integration test for `POST /datasets/{id}/reupload` (happy path, wrong-format error, wrong-record-type error, audit-log write, ID/slug preservation).
- **Frontend vitest:** component test for the menu item + confirmation modal + post-success refetch behavior.
- **e2e:** Optional happy-path Playwright test wiring upload → wait for ingest → assert dataset detail reflects new file. May be deferred to Phase 1056 live MCP run if time-pressured.

### Out of scope

- **Background reprocessing on file rename without content change** — that's a different operation; reupload semantically replaces content.
- **Diff view between old vs new file** — feature creep; if users want diff, they can compare before uploading.
- **Cross-record-type swap (vector→raster)** — explicitly excluded per decision above; planner returns 400.
- **Bulk reupload via CLI** — not in this phase; `geolens` CLI may add this later.

</decisions>

<code_context>
## Existing Code Insights

**Files most likely to touch (backend):**

- `backend/app/modules/datasets/router.py` — add `POST /reupload` endpoint
- `backend/app/modules/datasets/service.py` (or wherever the import-orchestration lives) — re-import flow that preserves ID/slug
- `backend/app/modules/audit/service.py` — add `dataset.reupload` audit action constant
- `backend/app/modules/datasets/tasks.py` (or wherever Celery tasks live for ingest) — adapt for re-ingest
- `backend/tests/test_datasets_*.py` — new test file or extension for reupload behavior

**Files most likely to touch (frontend):**

- `frontend/src/pages/datasets/DatasetDetailPage.tsx` (or similar) — action menu addition
- `frontend/src/components/datasets/ReuploadModal.tsx` (NEW) — confirmation modal component
- `frontend/src/api/datasets.ts` — new `reuploadDataset(id, file, opts)` function
- `frontend/src/hooks/use-datasets.ts` — invalidation on success
- `frontend/src/i18n/locales/*/dataset.json` — new keys for menu item, modal copy, success/failure toasts

**Reference patterns (existing in repo):**

- Initial dataset upload flow: `scripts/seed-natural-earth.py` uses `POST /datasets/upload` (or similar) — the reupload endpoint should mirror its multipart-form contract
- Audit log writes: `dataset.delete` audit action — reupload follows the same shape
- Async ingest progress: existing import wizard uses Celery + polling — reupload reuses
- `ProcessingPort` / `CatalogPort` separation (v13.x boundary work) — reupload must respect these ports; planner should grep for current boundary

**Generated SDKs:**

After backend endpoint lands, `backend/openapi.json` regenerates and Python+TypeScript SDKs (re-emitted from OpenAPI per v1007 pattern) get updated. Plan should include SDK regen as a step.

</code_context>

<specifics>
## Specific Ideas

- IMPORT-04 audit verbatim (audit `## IMPORT-04`): "No UI affordance to Reupload / Replace dataset file. Dataset detail page for a file-uploaded dataset shows Add to Map / Connect / Unpublish actions + Overview / Metadata / Data / Structure / Access tabs + 'Add summary' inline. Missing: any 'replace file' or 'reupload' affordance."

- ROADMAP.md Phase 1055 success criteria (3):
  1. "Replace file" (or equivalent) button visible on dataset detail page for datasets imported via file upload.
  2. Clicking the button opens a file picker; selecting and confirming triggers re-ingestion that preserves dataset ID + slug, regenerates tiles + thumbnail, writes audit-log entry.
  3. Dataset detail page reflects updated file without page reload.

</specifics>

<deferred>
## Deferred Ideas

- **Reupload for service-URL-imported datasets (WFS, ArcGIS, STAC)** — service-URL datasets have a different update model (refresh from source, not file replacement). Out of scope for IMPORT-04 — explicitly file-upload-only this phase.
- **Schema-aware migration assistant** — if new file's attribute columns differ from old, suggest column mappings. Defer; soft-warn for now.
- **Audit-log diff between old vs new** — would be nice but feature creep.

</deferred>
