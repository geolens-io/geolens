# Phase 1046: builder-perf-and-code-audit - Context

**Gathered:** 2026-05-16
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Structured audit artifacts exist — `BUILDER-CODE-AUDIT.md` classifies code-quality findings P0/P1/P2 across builder directories, and `BUILDER-PERF-BASELINE.md` records measurable baseline metrics for all six PERF requirements — so Phase 1047 has a concrete, prioritized fix list.

**Success criteria (from ROADMAP.md):**
1. BUILDER-CODE-AUDIT.md exists with P0/P1/P2 findings covering duplication, file-size offenders, dead code, and complexity hotspots across `frontend/src/components/builder/`, `frontend/src/hooks/use-builder-*`, `frontend/src/lib/builder-*`, and adjacent style helpers (`basemap-utils.ts`, `fill-adapter.ts`).
2. BUILDER-PERF-BASELINE.md exists with measured baseline metrics for large-map first-paint, input latency on 50+ layer maps, bulk-op batching profile, rAF repaint coalescing status, and route entry chunk sizes.
3. Every finding in both documents is tagged P0, P1, or P2 with enough detail for a plan author to write an implementation plan without additional investigation.
4. Baseline metrics reference the specific test map and tooling used so Phase 1047 can reproduce and compare.

**Requirements covered:** CODE-01 (audit production; PERF baselines feed forward into 1047 requirements).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting (`workflow.skip_discuss=true`). Use ROADMAP phase goal, success criteria, REQUIREMENTS.md (PERF-01..06, CODE-01..06), and codebase conventions to guide decisions.

### Inherited from milestone setup
- Audit-first shape — this phase produces docs, Phase 1047 ships fixes.
- Audit scope is `frontend/src/components/builder/`, `frontend/src/hooks/use-builder-*`, `frontend/src/lib/builder-*`, plus `basemap-utils.ts` / `fill-adapter.ts` style helpers used by builder.
- Perf baseline must be reproducible — record test map, tooling, and methodology.
- No code changes in this phase — audit-only.

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be gathered during plan-phase research. Likely starting points:

- `frontend/src/components/builder/` — UnifiedStackPanel, StackRow, LayerEditorPanel, BulkActionBar, BasemapGroupRow, FolderGroupRow, AddDataModal, SidebarRail, EmptyStackState
- `frontend/src/hooks/use-builder-*` — use-builder-layers, use-builder-save, use-builder-history, etc.
- `frontend/src/lib/builder-*` — builder helpers
- `frontend/src/lib/basemap-utils.ts` + `frontend/src/lib/adapters/fill-adapter.ts` (paint helpers consumed by builder)
- `frontend/vite.config.ts` — for bundle/chunk analysis
- `frontend/src/pages/MapBuilderPage.tsx` — route entry

Reference patterns from v1009's `BUILDER-UX-AUDIT.md` for audit structure (P0/P1/P2 classification, finding → file/line, recommended fix).

</code_context>

<specifics>
## Specific Ideas

- Phase 1046 produces **two artifacts** stored under the phase directory:
  - `1046-BUILDER-CODE-AUDIT.md`
  - `1046-BUILDER-PERF-BASELINE.md`
- BUILDER-CODE-AUDIT.md sections: Duplication, File-size Offenders, Dead Code, Complexity Hotspots, Test Coverage Gaps. Each finding includes: ID, severity (P0/P1/P2), file/lines, why, recommended fix, est. effort.
- BUILDER-PERF-BASELINE.md sections: Methodology (tooling: Chrome DevTools Performance panel, Lighthouse, Vite bundle analyzer; test map: a representative 50+ layer saved map seeded for repeatability; browser: Chromium), Baseline Metrics (PERF-01..06 each), Identified Bottlenecks (P0/P1/P2 tagged).
- Perf baseline needs an actual large saved map. Plans should produce a deterministic way to seed one — either reuse an existing fixture or create a fresh seed script under `.planning/phases/1046-*/scripts/seed-large-map.ts` (or similar).
- No code changes in this phase except possibly seed scripts / test fixtures needed for measurement.

</specifics>

<deferred>
## Deferred Ideas

- Actual fix implementation — deferred to Phase 1047 (perf-and-code-quality-fixes).
- Backend perf work — out of scope; audit is frontend builder only.
- Mobile perf — deferred to a future milestone.

</deferred>
