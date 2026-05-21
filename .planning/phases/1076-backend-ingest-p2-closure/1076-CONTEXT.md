# Phase 1076: Backend Ingest P2 Closure - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via `workflow.skip_discuss`)

<domain>
## Phase Boundary

Close 5 backend ingest P2 lifecycle hardening findings deferred from v1015/v1016 — all 5 are pre-classified P2 items from `.planning/audits/INGEST-AUDIT-2026-05-21.md`:

- **ING-02 (P2-02):** Drop internal `await session.commit()` from `backend/app/processing/ingest/metadata.py` helpers (`ensure_geom_column`, `clip_to_mercator_bounds`, `add_4326_column`, `grant_reader_access`). Let `_finalize_ingest` commit once at the phase-2 boundary (currently at `tasks_vector.py:296-299`). Add regression test asserting phase-2 failure rolls back the column-add.

- **ING-03 (P2-03):** Switch local-storage COG export at `backend/app/modules/catalog/datasets/api/router_export.py:383-400` from `await storage.get(asset_uri)` (full buffer to bytes) to a new `storage.get_stream(asset_uri)` provider method that returns an async iterator. Use it directly in `StreamingResponse`. Eliminates 5 GB resident memory spike on local-storage self-hosters.

- **ING-04 (P2-04):** Restrict worker exports temp-dir sweep at `backend/app/platform/jobs/worker.py:174-185` to entries older than 1 hour via `stat.st_mtime`; log skipped items. Avoids truncating in-flight large exports on worker restart.

- **ING-06 (P2-08):** Add single-retry behavior to `_apply_reupload_swap` at `backend/app/processing/ingest/tasks_common.py:880`. On `lock_timeout` failure, retry once with `SET LOCAL lock_timeout = '15s'` plus a brief sleep; log contention.

- **ING-07 (P2-09):** Add optional `strict_cog: bool` field (default `False`) to `RasterCommitRequest`. When `True`, raster commit rejects non-COG TIFFs at the magic-byte rule instead of routing through `check_and_prepare_cog` conversion.

**Out of scope:**
- Strict-COG default flip from `False` → `True` — deferred to a future minor/major (coordinated CLI/manifest schema bump per REQUIREMENTS.md)
- COG streaming for S3/remote storage paths — already redirect; this is local-storage only
- Autovacuum tuning beyond the single-retry — pure ops work
- Test infra changes (covered in Phase 1075)
- Frontend ingest changes (covered in Phase 1077)

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices at Claude's discretion — discuss skipped. Use ROADMAP success criteria, REQUIREMENTS.md, INGEST-AUDIT-2026-05-21.md detail, and codebase conventions.

### Known Defaults

- **Migration impact:** None required for ING-02..07. All are internal refactors/optional fields. `strict_cog` default `False` is backwards-compatible.
- **Test coverage:** ING-02 requires a new regression test for phase-2 failure rollback. ING-03..07 should each have at least a pin test or behavior assertion. Existing tests should continue passing.
- **Streaming provider:** `storage.get_stream()` should return `AsyncIterator[bytes]` or compatible. Match existing `storage` provider interface in `backend/app/platform/storage/`.
- **Lock retry strategy:** Single retry only. Don't introduce backoff loops. Sleep duration should be small (e.g., 100-500ms) to keep p99 latency bounded.
- **Logging:** Use existing structured logger; emit one `WARNING`-level event on lock contention with autovacuum correlation hint.
- **`strict_cog` placement:** Add to the Pydantic schema for `RasterCommitRequest`. Wire through to the magic-byte validation site in `backend/app/processing/ingest/validation.py`.

### Investigation order

1. Read `INGEST-AUDIT-2026-05-21.md` P2-02..09 sections for exact line refs.
2. Read all 5 target files to understand current shape.
3. Land each ING-XX as one plan, in dependency order:
   - ING-02 (metadata.py commits) — touches multiple call sites in metadata.py + adds test
   - ING-03 (COG streaming) — adds provider method + rewires export
   - ING-04 (temp-dir sweep) — small change to worker.py
   - ING-06 (lock retry) — small change to tasks_common.py
   - ING-07 (strict_cog flag) — schema + validation wire

</decisions>

<code_context>
## Existing Code Insights

- `backend/app/processing/ingest/metadata.py` — phase-2 helpers (line refs from audit):
  - `ensure_geom_column:814`
  - `clip_to_mercator_bounds:944`
  - `add_4326_column:1076`
  - `grant_reader_access:1091`
- `backend/app/processing/ingest/tasks_vector.py:296-299` — `_finalize_ingest` phase-2 commit boundary
- `backend/app/modules/catalog/datasets/api/router_export.py:383-400` — local-storage COG export site
- `backend/app/platform/jobs/worker.py:174-185` — exports temp-dir sweep
- `backend/app/processing/ingest/tasks_common.py:880` — `_apply_reupload_swap` lock_timeout
- `backend/app/processing/ingest/validation.py:23-36` — `.tif`/`.tiff` magic-byte rule (entry point for ING-07)
- `backend/app/modules/catalog/datasets/api/schemas.py` or `backend/app/modules/catalog/raster/schemas.py` (TBD by planner) — `RasterCommitRequest` Pydantic class

Patterns reinforced from Phase 1075 dispositions:
- v1015/v1016 added `validate_url_for_ssrf` as a lazy from-import inside ingest commit dispatch (Plan 03 finding); mock patch targets must hit the defining module
- v1016 Phase 1073 introduced `_job_phase_session` async ctx manager replacing 14+ session-bracket sites — ING-02's commit-removal landing should respect this pattern

</code_context>

<specifics>
## Specific Ideas

- 5 plans, 1 per ING requirement. Each plan: read targets, refactor, test, verify.
- Plan order: ING-02 (largest, most risk) → ING-03 → ING-04 → ING-06 → ING-07 → close-gate plan.
- Aim for atomic commits per task; tests land alongside production-code change in the same plan.

</specifics>

<deferred>
## Deferred Ideas

- COG streaming for S3/remote (already redirects — out of scope)
- `strict_cog` default flip — coordinated CLI/manifest schema bump (future minor)
- Autovacuum runtime tuning — ops/infra, not code

</deferred>
