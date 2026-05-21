# Phase 1073: Audit Remediation - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Close the 4 P2 audit findings that Phase 1072 triage assigned to v1016. All 4 are UX-visible OR maintenance refactors — no security/correctness HIGH/MEDIUM remediation needed.

**In scope (4 reqs):**

- **REMED-01**: TanStack mutations for re-upload commit + VRT creation invalidate `jobStatusByDataset` (ingest-audit P2-06). After successful re-upload, dataset-detail page shows STALE warnings until forced refresh. ~30 LoC, ~1h.
- **REMED-02**: `JobStatusResponse` schema carries `progress` / `current_step` / `rows_processed` fields populated by ingest worker writes (ingest-audit P2-07). 10-min raster ingests look dead in UI. Schema add + 2-3 worker write sites; ~2h.
- **REMED-03**: Ingest task chunk-loop logic deduplicated into a shared helper testable in isolation (ingest-audit P2-05). Refactor, no behavior change; ~1.5h.
- **REMED-04**: COG URL construction consolidated into a single storage helper; SEC-OBSV-01 + SEC-OBSV-02 docstring contracts pinned at the same time (ingest-audit P2-01 + sec-audit defense-in-depth). Single helper + 3 callsite updates + 2 docstrings; ~1h.

**Out of scope (deferred):**
- 8 v1015-carried P2 → v1017 hygiene milestone (TD-DEFER-01..08)
- 1 CI gate wiring (SEC-OBSV-03 alembic clean-DB script in CI) → Phase 1074
- 1 live-stack e2e gate (INGEST-OBSV-01 + KNOWN-02 docker smoke) → Phase 1074

</domain>

<decisions>
## Implementation Decisions

### Locked Decisions

- **Plan organization (4 plans, all Wave 1 parallel-safe — no file overlap):**
  - `1073-01`: REMED-01 — TanStack invalidation (frontend hooks)
  - `1073-02`: REMED-02 — JobStatusResponse + worker writes (backend schema + 2-3 worker sites)
  - `1073-03`: REMED-03 — chunk-loop helper extraction (backend refactor)
  - `1073-04`: REMED-04 — COG URL helper + SEC-OBSV docstrings (backend storage + docs)

- **OpenAPI snapshot rebuild required after REMED-02** (Phase 1074 will run `make openapi` then `npm run fetch-openapi` per the project memory note "OpenAPI dual-snapshot refresh order"). Plan 1073-02 produces the schema change; downstream snapshot refresh is a Phase 1074 close-gate task.

- **No CHANGELOG touches in this phase** (Phase 1074 GATE-01 writes the [1.5.1] entry).

### Claude's Discretion

- TanStack invalidation strategy (`invalidateQueries` vs `setQueryData`) — use `invalidateQueries` for safety + simplicity unless there's a specific reason to use `setQueryData`.
- Worker progress write cadence for REMED-02 — every N rows OR every M seconds, whichever is more natural per the worker's existing pattern.
- Whether REMED-03's helper lives in `tasks_common.py` (existing) or a new `chunking.py` file — prefer `tasks_common.py` to minimize file count.
- REMED-04 helper location — `backend/app/platform/storage/cog_url.py` OR add to existing storage module. Pick whichever has clearest "single source of truth" semantics.

</decisions>

<code_context>
## Existing Code Insights

Will be gathered during plan-phase research per plan. Anchors per plan:

- **REMED-01:** `frontend/src/api/ingest.ts` (useReuploadCommit), `frontend/src/api/vrt.ts` (useCreateVrt), `frontend/src/api/datasets.ts` (`jobStatusByDataset` queryKey)
- **REMED-02:** `backend/app/processing/ingest/schemas.py` (`JobStatusResponse`), `backend/app/processing/ingest/tasks_vector.py` + `tasks_raster.py` (chunk loops where progress should be written)
- **REMED-03:** `backend/app/processing/ingest/tasks_common.py` (existing shared helpers), `tasks_vector.py` + `tasks_raster.py` (duplicated chunk-loop logic)
- **REMED-04:** `backend/app/platform/storage/*.py` (existing helpers), `backend/app/processing/raster/cog.py`, `backend/app/modules/catalog/sources/stac_router.py:50` (`_fetch_cog_info`), `backend/app/processing/tiles/router.py:51` (Titiler proxy)

</code_context>

<specifics>
## Specific Ideas

- **REMED-02 progress fields:** Match the shape any existing UI consumer expects. Check `frontend/src/components/dataset/JobStatus.tsx` (if exists) for the read shape before defining write shape. Typical fields: `progress: number (0.0-1.0)`, `current_step: str`, `rows_processed: int`.
- **REMED-04 SEC-OBSV docstrings:**
  - SEC-OBSV-01: `tiles/router.py:51` Titiler proxy `httpx.AsyncClient(follow_redirects=True)` — add docstring "Internal-only Titiler proxy; if exposed externally, replace with safer client."
  - SEC-OBSV-02: `stac_router.py:50` `_fetch_cog_info` — add docstring "Relies on dual-gate: caller-side `validate_url_for_ssrf` + Titiler extension allowlist. Future callers must preserve both gates."

</specifics>

<deferred>
## Deferred Ideas

None — all 4 P2 in scope.
</deferred>
