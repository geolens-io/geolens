# Phase 1050: builder-smoke-carryover - Context

**Gathered:** 2026-05-17
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss=true)

<domain>
## Phase Boundary

All 5 v1010.1 carried-forward smoke findings (SF-04 dedupe MapLibre sources, SF-05 blob revoke timing, SF-06 anonymous pre-auth probes, SF-07 double initial thumbnail PUT, SF-08 false-positive basemap toast) ship with code-level fixes; v1010.1 SMOKE-FINDINGS.md "Observed" surfaces re-verify clean against a fresh stack; CHANGELOG `[Unreleased]` records the close; smoke gate (typecheck / vitest / e2e:smoke:builder / Playwright MCP re-verify) is green.

This is a hygiene-close milestone. No new features, no design contracts, no architecture changes. Each plan maps 1:1 to a v1010.1 smoke finding with root cause and recommended fix already documented in `.planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md`.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per `workflow.skip_discuss=true`. Use ROADMAP.md phase goal + per-plan touch surface, the v1010.1 SMOKE-FINDINGS.md "Recommended fix" guidance, and existing codebase conventions to guide decisions.

### Established conventions to follow
- Use `apiFetch()` from `frontend/src/api/client.ts` for any new API calls
- Auth state via `useAuthStore` (zustand with persist)
- React Query hooks under `frontend/src/hooks/` follow existing `enabled`-gate patterns
- Builder hooks under `frontend/src/components/builder/hooks/` — share helpers in `layer-adapters/shared.ts` where extracted by v1010
- MapLibre imperative API for source/layer management — declarative `<Source>` / `<Layer>` not reliable per memory `Known Issues & Workarounds`
- FastAPI route trailing-slash convention applies (see memory)
- Toast via shared toast util (e.g. `useToast` / `toast()` — match the existing builder hooks)
- Smoke gate parity with v1010 / v1010.1: typecheck 0, vitest green, e2e:smoke:builder green, Playwright MCP re-verify of "Observed" surfaces

### Key decisions baked into the plan
- **SF-04 source-id keying:** prefer reusing source per `dataset_table_name` for non-cluster layers; preserve per-layer cluster sources (cluster radius/minPoints are per-layer settings). Reference-count or recompute-from-stack the source's referenced layer set on every removeSource path.
- **SF-05 revoke timing:** preferred fix is deferring `URL.revokeObjectURL(blob)` until either `<img onLoad>`/`onError` or component unmount; a long-timeout patch is a stopgap.
- **SF-06 pre-auth gating:** preferred fix is per-hook `enabled: isAuthenticated` (so we never send the fetch), not a global error-handler suppressor. The admin probe must additionally gate on `user.is_admin`.
- **SF-07 debounce:** the 500ms debounce must wrap the effect-fired side effect, not just the click handler. Likely a missing `useDebouncedCallback`/`useEffect` ordering issue in `use-builder-save.ts`.
- **SF-08 basemap toast:** track `basemapLoadedAt: number | null` (or equivalent) on first successful style load; suppress connection-issue toast for transient style-fetch errors after `basemapLoadedAt` is set.

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be gathered during plan-phase research. Likely files in scope:

- `frontend/src/components/builder/hooks/use-builder-layers.ts` — source registration, `swapLayerOnMap` (~line 760), per-layer cleanup
- `frontend/src/components/builder/hooks/use-builder-save.ts` — thumbnail PUT debounce, basemap-connection check
- `frontend/src/components/builder/cluster-source.ts` — cluster-source override (preserve per-layer)
- `frontend/src/components/builder/BuilderMap.tsx` — basemap error handler
- React Query hooks for `/api/auth/me/`, `/api/auth/me/permissions/`, `/api/admin/ai-status/`, `/api/search/saved/`, `/api/auth/refresh/` (locate via grep on each endpoint path)
- Thumbnail blob lifecycle — locate via `git grep "revokeObjectURL" frontend/src`
- `frontend/src/lib/builder/raf-coalesce.ts` (v1010 — for any debounce alignment)
- `frontend/src/components/builder/layer-adapters/shared.ts` (v1010 helpers — `syncLayerFilter`, `setLayerProperty`)

</code_context>

<specifics>
## Specific Ideas

Per-plan touch surfaces and success criteria are already defined in `.planning/ROADMAP.md` Phase 1050 detail section. Each plan derives its concrete fix from the corresponding SF-XX entry in `.planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md` (root cause + recommended fix).

Plan 06 CTRL-01 is the close gate — typecheck + vitest + e2e:smoke:builder + Playwright MCP re-verify + CHANGELOG `[Unreleased]` populated.

</specifics>

<deferred>
## Deferred Ideas

Out of scope (per REQUIREMENTS.md):
- SP-03 / M-02 fresh-add maplibre sync race (predates v1010.1)
- SP-07 backend `has_quicklook` predicate (predates v1010.1)
- SP-12 representative-fraction "1:N" pane (new feature)
- Any 999.x backlog phase

</deferred>
