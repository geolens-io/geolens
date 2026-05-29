---
phase: "1134"
name: "Map Functionality and Smaller-Screen Polish"
gathered: "2026-05-27"
status: "Ready for planning"
mode: "Auto-generated (discuss skipped via workflow.skip_discuss)"
---

# Phase 1134: Map Functionality and Smaller-Screen Polish — Context

<domain>
## Phase Boundary

Close the Tier-1 `todo.md` bug-shape items (delete-layer, visibility-toggle, rename-group focus) and the ≤800px layout collisions so the `dispatchLayerAction` boundary is stable before Phase 1135's AI staging work touches it.

**Requirements:** MAP-07, MAP-08, MAP-09, MAP-10, MAP-16, MAP-17, MAP-18, MAP-19, MAP-20, MAP-22.

**5 ROADMAP success criteria:**
1. Delete layer works across every render mode without orphan sources/layer-stack entries/save-state drift; regression pinned in `use-builder-layers.test.tsx`.
2. Visibility toggle works across all render modes immediately; per-adapter `syncVisibility` regression pin in `layer-adapters/__tests__/`.
3. Rename group input focuses on first paint via rAF-deferred focus (v1011 BUG-03 pattern); regression pin in `UnifiedStackPanel.test.tsx`.
4. ≤800px viewport: right-sidebar Sheet does not overlap NavigationControl (sidebar collapse trigger fixed; NavigationControl stays at `top-left` per Pitfall #10), lat/long readout does not overlap widget container, every `<SheetContent>` in builder opts out of duplicate-X via `showCloseButton={false}` (Pitfall #11 negative-control pin).
5. Map container does not scroll page body during pan/zoom; filter pills do not collide with measure-widget; Notes icon shows presence indicator when notes exist.

**Ground truth:** Use findings from Phase 1133 `.planning/phases/1133-audit-first-builder-walkthrough/1133-BUILDER-WALKTHROUGH-AUDIT.md` — the audit identifies exact failure modes (e.g., `circle-adapter.ts` and `heatmap-adapter.ts` missing `syncLayerFilter` from `syncPaint`; `raster-adapter.ts` `addLayers` early-return).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices at Claude's discretion (discuss phase skipped). ROADMAP success criteria + Phase 1133 audit doc are the spec.

### Key Pre-Decided Anchors (from STATE.md decisions + ROADMAP invariants)
- **Pitfall #10 (smaller-screen NavigationControl):** Stays `top-left`. Fix is the sidebar collapse trigger, NOT moving NavigationControl. v1011 RESP-01/02 contract holds.
- **Pitfall #11 (`<SheetContent>` close button):** Use `showCloseButton={false}` and add negative-control regression pin so the duplicate-X bug stays gone.
- **dispatchLayerAction boundary stability:** This phase MUST NOT widen `BuilderLayerAction` union. Phase 1135's AI staging tests pin against post-1134 behavior.
- **No architecture rewrites:** Polish only. No new files >500 LOC, no rename of >3 exported symbols.
- **Test pins:** Each success criterion has a NAMED regression test file — write them as part of the plan.

</decisions>

<code_context>
## Existing Code Insights

Anchor files (will be expanded in plan-phase):
- `frontend/src/builder/layer-adapters/{fill,line,circle,symbol,heatmap,cluster,raster}-adapter.ts` (per-render-mode syncVisibility / syncPaint / syncLayerFilter)
- `frontend/src/builder/dispatchLayerAction.ts` (v1027 typed boundary — do NOT widen union)
- `frontend/src/builder/map-sync.ts` (v1026 reconciler — orphan-source cleanup lives here)
- `frontend/src/components/builder/UnifiedStackPanel.tsx` (delete-layer, visibility-toggle, rename-group entry points)
- `frontend/src/hooks/use-builder-layers.ts` (orchestration; needs orphan-source guard verification)
- `frontend/src/components/ui/sheet.tsx` (showCloseButton prop; v1011 RESP-03 contract)
- `frontend/src/components/MapCoordReadout.tsx` (lat/long readout positioning; v1011 cross-context offset contract)
- `frontend/src/pages/MapBuilderPage.tsx` (smaller-screen sidebar collapse trigger)

</code_context>

<specifics>
## Specific Ideas

- Single-pass per-adapter sweep for `syncVisibility` BUG-01 + `syncPaint` missing `syncLayerFilter` (circle, heatmap per audit).
- `raster-adapter.ts addLayers` early-return fix: distinguish source-exists from layer-exists; re-add missing layer when source exists but layer was removed.
- Rename-group focus: replicate v1011 BUG-03 rAF-deferred pattern; add Radix DropdownMenu compatibility check.
- ≤800px sweep: viewport sweep at 800×600 + 414×896 via Playwright MCP after fixes; verify sidebar collapse trigger no longer overlaps NavigationControl.
- Notes presence indicator: small visual (dot or count badge) on Notes icon when active map has notes.

</specifics>

<deferred>
## Deferred Ideas

None — discuss skipped. ROADMAP + Phase 1133 audit are the spec.

</deferred>
