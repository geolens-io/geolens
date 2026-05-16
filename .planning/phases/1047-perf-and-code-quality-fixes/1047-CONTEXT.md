# Phase 1047: perf-and-code-quality-fixes - Context

**Gathered:** 2026-05-16
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

All P0 audit findings and all PERF requirements are remediated — large-map paint is faster, input latency is sub-16ms, bulk ops batch correctly, paint updates coalesce per animation frame, route chunks are lazy-loaded, and all code-quality P0/P1 findings are either fixed or explicitly deferred with rationale.

**Requirements covered (from ROADMAP.md / REQUIREMENTS.md):**
- PERF-01 — Large-map first paint inside measured budget; automated check or Playwright timing assertion.
- PERF-02 — Hover/click on a 50+ layer unified stack with input latency under 16ms.
- PERF-03 — Bulk visibility/opacity/group/ungroup/delete batches with rollback + progress affordances; no v1009 regression.
- PERF-04 — Paint property updates coalesce into one MapLibre repaint per rAF; unit-level rAF coalescing test passes.
- PERF-05 — Builder route entry chunk shrinks via lazy-load of LayerEditorPanel, AddDataModal, and Settings scene; before/after documented.
- PERF-06 — All perf changes ship with measured before/after; no regression in smoke runtime, vitest runtime, or cold build.
- CODE-02 — All P0 audit findings remediated and committed with regression tests where applicable.
- CODE-03 — All P1 audit findings remediated OR explicitly deferred-with-rationale in the audit doc; no silent skips.
- CODE-04 — No new dead code remains; audit re-verification confirms removal.
- CODE-05 — File-size offenders drop below threshold OR explicit accepted-with-rationale.
- CODE-06 — No behavior regressions: vitest builder suite green, builder smoke green, typecheck clean, public component contracts preserved.

**Inputs (frozen by Phase 1046):**
- `.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md` — 24 findings (P0=3, P1=14, P2=7).
- `.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-PERF-BASELINE.md` — 8 bottlenecks (PB-01..PB-08) with per-PERF targets and reproduction steps.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting (`workflow.skip_discuss=true`). Use ROADMAP phase goal, REQUIREMENTS.md (PERF-01..06, CODE-02..06), the two audit documents in Phase 1046, and codebase conventions to guide decisions.

### Inherited / Constrained by Phase 1046 outputs

- **P0 fix list is fixed.** CA-01 (filter utility), CB-07 (LayerStyleEditor split), CC-15 (unused `selectedLayerId` removal) must all ship.
- **PERF target table is fixed.** Each PERF-01..06 has a recommended target in BUILDER-PERF-BASELINE.md "Recommended Targets for Phase 1047"; plans must hit or document deviation.
- **PB-01 lazy-load is the PERF-05 lever.** Lazy-load LayerEditorPanel, AddDataModal, Settings scene plus DEMEditorScene + StyleJsonDialog as forecast in PB-01 (40% entry-chunk reduction target).
- **Bulk-delete batching prefers ONE additive backend endpoint.** REQUIREMENTS.md "Out of Scope" carves an exception for ONE backend endpoint if essential — PB-03 calls for `/api/maps/{id}/layers/bulk-delete` to drop 50 sequential PUTs to 1 batched call. Document the endpoint as the milestone exception.
- **Test map seeded once, reused across PERF measurements.** Phase 1046 left PERF-01..04 runtime-blocked; this phase must seed the 50-layer map early and capture before/after timings during fix work, not at the end.
- **No new design tokens.** REQUIREMENTS.md "Out of Scope" — visual vocabulary stays on `sketch-findings-geolens`. UI-touching changes (progress affordances for bulk ops, rollback toasts) reuse existing patterns.
- **P1 defer-vs-fix is per-finding.** Default to fix; only defer if (a) effort exceeds milestone budget OR (b) the fix introduces a higher-risk regression surface. Each P1 deferral writes a rationale stub back into BUILDER-CODE-AUDIT.md.
- **No render-mode work.** Out of scope per REQUIREMENTS.md "Out of Scope" / "Future Requirements".
- **Backwards-compat:** Public component contracts preserved (CODE-06). Internal-only refactors (helper extraction, file splits) are unconstrained as long as builder tests + smoke stay green.

### Verification gates

- **Per-PERF:** Before/after metric pair must land in the phase SUMMARY (or per-plan note); CI / Playwright check where applicable.
- **rAF coalescing:** PERF-04 requires a unit-level test that proves paint updates collapse to one rAF tick.
- **Smoke / typecheck / vitest:** CODE-06 gate — must be green at phase close. Builder smoke runtime tracked against PERF-06 baseline (≤10.5s vitest, ≤1.7s cold build, ≤50s e2e:smoke:builder).
- **Audit re-verification:** CODE-04 — dead code (CC-15, CC-16 if shipped, CC-17 P2 — at minimum confirm none re-appears). Plan author re-greps audited dirs at phase end.

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be deepened during plan-phase research. Starting points (from Phase 1046 audit):

**P0 fix surface:**
- `frontend/src/lib/adapters/{fill,line,circle,symbol,raster}-adapter.ts` — filter-checking duplication (CA-01); extract `hasActiveFilters(layer)` utility.
- `frontend/src/components/builder/LayerStyleEditor.tsx` — 1204 LOC, complex; split per-render-mode (CB-07).
- `frontend/src/lib/builder/map-sync.ts` — unused `selectedLayerId` parameter; trivial removal (CC-15).

**Top P1 fix surface (subject to per-finding fix-vs-defer call):**
- `frontend/src/components/builder/UnifiedStackPanel.tsx`, `BuilderMap.tsx`, `LayerEditorPanel.tsx` — file-size + mixed concerns.
- `frontend/src/hooks/use-builder-layers.ts` — mega-hook (12+ useState, deep nested handleBulkAction).
- `frontend/src/lib/builder/map-sync.ts`, `frontend/src/lib/adapters/fill-adapter.ts` — repeated syncPaint / try-catch / outline opacity patterns.

**PERF fix surface:**
- `frontend/src/pages/MapBuilderPage.tsx` — lazy-load 5 editor scenes (PB-01 → PERF-05).
- `frontend/src/components/builder/LayerStyleEditor.tsx` opacity slider — add 100ms debounce + rAF coalescing (PB-02 → PERF-04).
- `frontend/src/hooks/use-builder-layers.ts` handleBulkAction → bulk-delete batching (PB-03 → PERF-03), backend addition: `POST /api/maps/{id}/layers/bulk-delete`.
- Expression editor + color picker — align debounce clocks (PB-04, PB-06 → PERF-04).
- `frontend/src/components/builder/BulkActionBar.tsx` — memoize, fix selectedIds re-render (PB-05, PB-08 → PERF-02).
- `frontend/vite.config.ts` — bundle inspection for PERF-05 before/after.
- `frontend/src/components/builder/StackRow.tsx` — input latency surface (PERF-02).

**Verification scripts:**
- `e2e/builder-v1-5.spec.ts` is the current Playwright smoke seed; PERF-01..03 timing assertions can extend this or live in a new `e2e/perf/builder-large-map.spec.ts`.
- A seeder/script (likely `scripts/seed-large-builder-map.ts` or via API) is needed for the 50-layer test map; plan must decide reuse vs new.

</code_context>

<specifics>
## Specific Ideas

- **Wave shape (plan grouping hint):** Group by file overlap to enable wave-based execution.
  - **Wave A — Trivial wins / unblock:** CC-15 (param removal), CA-01 (filter utility), seed 50-layer test map fixture.
  - **Wave B — Lazy-load + bundle (PERF-05):** PB-01 / PB-07 across MapBuilderPage and editor scenes.
  - **Wave C — Debounce / rAF (PERF-04):** PB-02 / PB-04 / PB-06 — opacity slider, color picker, expression editor + unit-level rAF coalescing test.
  - **Wave D — Bulk-op batching (PERF-03):** PB-03 backend endpoint + frontend handleBulkAction; PB-05 / PB-08 input-latency memoization for PERF-02.
  - **Wave E — LayerStyleEditor split (CB-07):** Largest single CODE refactor; final because it touches many P1 items co-located in the file.
  - **Wave F — P1 sweep + audit re-verify:** Remaining P1 fixes by sub-area; CODE-04 dead-code re-grep; CODE-05 file-size verification; CODE-06 final smoke + vitest + typecheck.

- **Backend addition (single milestone exception):** `POST /api/maps/{id}/layers/bulk-delete` with body `{ layer_ids: string[] }`; returns `{ deleted: string[], failed: [{ id, reason }] }`. Wire into existing v1009 `Promise.allSettled` rollback toast.

- **`hasActiveFilters(layer)` lives in** `frontend/src/lib/builder/layer-filters.ts` (or co-located with adapters under `frontend/src/lib/adapters/_filter-utils.ts`); plan picks based on existing barrel exports.

- **LayerStyleEditor split:** Per-render-mode child components — `LayerStyleEditor/FillEditor.tsx`, `LineEditor.tsx`, `CircleEditor.tsx`, `SymbolEditor.tsx`, `RasterEditor.tsx`, with a thin parent dispatch. Reduces per-file LOC and complexity; preserves public `LayerStyleEditor` import surface.

- **rAF coalescing utility:** Introduce `frontend/src/lib/builder/raf-coalesce.ts` (or use existing helper if one exists) — single utility wraps style-property writes so multiple updates in the same frame collapse to one MapLibre setPaintProperty per frame. Unit test asserts coalescing behavior.

- **Per-PERF before/after metric capture:** Phase SUMMARY.md should include a table mirroring BUILDER-PERF-BASELINE.md "Recommended Targets" with measured after-values + delta. Per-plan SUMMARY also acceptable if metrics are scattered.

- **P1 deferral rationale stubs:** Each P1 not shipped this phase must get a one-line `**Status (Phase 1047):** deferred — <rationale>` annotation appended under its finding in BUILDER-CODE-AUDIT.md.

</specifics>

<deferred>
## Deferred Ideas

- **Mobile / responsive perf work** — out of scope per REQUIREMENTS.md "Future Requirements".
- **AI authoring + new render modes + new widgets** — out of scope per REQUIREMENTS.md.
- **All P2 findings** — out of scope unless they sit on top of a P0/P1 fix and incur near-zero marginal cost.
- **History panel UX iteration** — deferred.
- **FOLLOWUP-01..03 + CLOSE-01..02** — owned by Phase 1048.
- **Add Data modal audit** — owned by Phase 1048 (FOLLOWUP-02).

</deferred>
