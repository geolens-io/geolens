# Phase 1077: Frontend Ingest P2 Closure - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via `workflow.skip_discuss`)

<domain>
## Phase Boundary

Close 2 frontend ingest P2 hygiene findings deferred from v1015/v1016 — both pre-classified P2 items from `.planning/audits/INGEST-AUDIT-2026-05-21.md`:

- **ING-01 (P2-01):** Add `getCogDownloadUrl(id: string): string` helper in `frontend/src/api/datasets.ts` next to `getExportUrl()`. Replace string concat at `frontend/src/components/import/JobProgress.tsx:42` with the helper call. Drift risk mitigation — when the route changes in the future, one update site instead of two.

- **ING-05 (P2-05):** Extract `uploadChunks(urls, file, partSize)` helper into a new `frontend/src/api/_presignedUpload.ts`. Rewire `frontend/src/api/ingest.ts:147-159` and `frontend/src/api/datasets.ts:370-383` (identical chunked PUT loops) to call the helper. Single canonical location for future retry-on-ETag-mismatch / exponential backoff / abort signal.

**Out of scope:**
- Retry/backoff/abort logic itself — extract first; future work adds the resilience.
- Other frontend ingest hygiene (e.g., toast deduplication, loading-state polish) — separate scope.
- Backend route changes — covered in Phase 1076.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices at Claude's discretion — discuss skipped. Use ROADMAP success criteria, REQUIREMENTS.md, INGEST-AUDIT-2026-05-21.md detail, and `frontend/src/api/` conventions.

### Known Defaults

- **TypeScript style:** Follow existing patterns in `frontend/src/api/datasets.ts` — bare functions, named exports, JSDoc on public-facing helpers.
- **Test coverage:** Add a vitest test for `uploadChunks` since it's a new shared helper. `getCogDownloadUrl` is too thin for a dedicated test; existing component tests of `JobProgress` should cover correctness via the call site.
- **No backwards-compat hacks:** Drop the duplicated chunked-PUT loops entirely; both call sites switch to the helper in this phase.
- **No frontend API contract changes:** Both changes are internal refactors — no behavioral change observable from the UI.

### Investigation order

1. Read existing `getExportUrl()` in `datasets.ts:51-61` to match style.
2. Read the two chunked-PUT loops side-by-side to confirm they're identical.
3. Land ING-01 first (simpler, single new function + single call-site rewrite).
4. Land ING-05 second (new file + rewire 2 call sites + new vitest test).
5. Run vitest + typecheck after each plan.

</decisions>

<code_context>
## Existing Code Insights

- `frontend/src/api/datasets.ts:51-61` — `getExportUrl()` pattern to mirror for `getCogDownloadUrl()`
- `frontend/src/api/datasets.ts:370-383` — second chunked PUT loop (one of two)
- `frontend/src/api/ingest.ts:147-159` — first chunked PUT loop (identical shape)
- `frontend/src/components/import/JobProgress.tsx:42` — string-concat call site

The two chunked-PUT loops use `fetch(url, { method: 'PUT', body: chunk })` against presigned URLs and read ETag headers on success. They should be identical post-extraction; if not, the planner needs to identify and reconcile the divergence (could be a hidden v1014/v1015 fix in only one site).

**Frontend stack (project memory):** React 19 + Vite + TypeScript + TanStack Query + vitest + Testing Library. `apiFetch()` is the canonical HTTP client wrapper in `frontend/src/api/client.ts`.

</code_context>

<specifics>
## Specific Ideas

- 2 plans: one per ING + one close-gate plan (3 total)
- Or merge: 2 plans, no separate close-gate (verification in Plan 02). Planner discretion.

</specifics>

<deferred>
## Deferred Ideas

- Retry/abort logic on the chunked upload helper — future v1018/marketplace work
- Centralized URL builder for ALL dataset routes — broader refactor, separate scope
- Frontend test infrastructure overhaul — separate scope

</deferred>
