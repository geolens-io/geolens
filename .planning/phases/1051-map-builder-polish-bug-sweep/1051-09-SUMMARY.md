---
phase: 1051
plan: 09
subsystem: builder
tags: [builder, responsive, coord-readout, viewport-collision, top-right-zone, docstring-resolution]
requires:
  - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
  - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md
  - .planning/phases/1051-map-builder-polish-bug-sweep/1051-CONTEXT.md
  - .planning/phases/1051-map-builder-polish-bug-sweep/1051-08-SUMMARY.md
provides:
  - "RESP-02: MapCoordReadout pill no longer collides with the NavigationControl in the BuilderMap context (resolved upstream by Phase 1051 Plan 08 / commit 391459bb); cross-context positioning contract codified in the component docstring so the load-bearing `right-14` offset is not naively shortened by future changes."
affects:
  - frontend/src/components/map/MapCoordReadout.tsx
tech-stack:
  added: []
  patterns:
    - "Resolution-by-upstream-wave: when a same-phase prior wave's pure-positioning fix already eliminates a downstream wave's stated collision surface, the downstream wave still ships a real production change — but the change is the docstring/cross-reference work that prevents regression of the freed-up offset, not a redundant CSS tweak."
key-files:
  created: []
  modified:
    - frontend/src/components/map/MapCoordReadout.tsx
decisions:
  - "Original RESP-02 collision (MapCoordReadout `top-2 right-14` vs MapLibre NavigationControl in the top-right zone) is provably already-resolved in the BuilderMap context by Phase 1051 Plan 08 / commit 391459bb (NavigationControl repositioned `top-right` → `top-left`). No CSS positioning change ships in Plan 09 for the builder."
  - "MapCoordReadout is shared with ViewerMap (`frontend/src/components/viewer/ViewerMap.tsx:741`), where NavigationControl is STILL anchored `top-right`. The 56px `right-14` offset is load-bearing in the viewer context and must NOT be reduced. A future naive 'tighten to right-3' refactor would re-introduce the original collision in the viewer."
  - "Strategy choice — documentation-only resolution over redundant CSS touch. Real production change: docstring extension in `MapCoordReadout.tsx` that (a) names the RESP-02 contract, (b) cross-references commit 391459bb / Plan 08, (c) explains why `right-14` is load-bearing in the viewer even though the builder's NavigationControl moved, (d) records that top-right WidgetHost (`top-12 right-3`) is 40px below the pill so no widget-band collision exists either."
  - "No vitest case (pure-CSS RESP-* class — and there is no behavioral change to assert; the pill renders at the same coordinates it did pre-Plan-09). UI-SPEC §RESP-02 and critical_planning_directive #10 already exempt pure-positioning RESP-* fixes from vitest in favor of MCP-only verification."
  - "Live Playwright MCP re-verify deferred to orchestrator per phase 1051 pattern (MCP is orchestrator-scoped, not executor-spawnable — lesson reinforced across plans 02-08 of this phase and inherited from v1010.1 / v1010.2)."
metrics:
  duration: "~5 minutes"
  completed: "2026-05-18T02:05:00Z"
---

# Phase 1051 Plan 09: RESP-02 MapCoordReadout Overlap Summary

One-liner: RESP-02's original `MapCoordReadout` vs `NavigationControl` top-right collision is already eliminated in the BuilderMap context by Phase 1051 Plan 08 (commit `391459bb`); Plan 09 ships a docstring extension on `MapCoordReadout.tsx` that codifies the cross-context positioning contract so the load-bearing `right-14` offset (still required for `ViewerMap`'s top-right NavigationControl) is not naively shortened by future refactors.

## Post-Plan-08 Collision Analysis

**Pre-W8 collision surface (the originally-reported RESP-02 defect):**
- `MapCoordReadout` was at `top-2 right-14` (8px from top, 56px from right edge of map canvas).
- `MapLibre NavigationControl` was at `position="top-right"` — same vertical band, immediately to the right of the readout.
- At narrow viewport widths, the pill text widened (driven by `showScale` representative-fraction segment + variable-length lat/lon strings) and visually clashed with the NavigationControl's zoom-button stack.

**Post-W8 reality (commit `391459bb`):**
- `BuilderMap.tsx:928` — `<NavigationControl position="top-left" />` (W8 moved it).
- `ViewerMap.tsx:741` — `<NavigationControl position="top-right" />` (W8 did NOT touch ViewerMap; same component is consumed elsewhere with NavigationControl in its original top-right anchor).
- `MapCoordReadout.tsx:111` — still `<div className="absolute top-2 right-14 z-10 pointer-events-none">`.

**Net effect on the collision surface:**
1. In `BuilderMap` — NavigationControl no longer occupies the top-right zone. The 56px `right-14` clearance is, in this context, dead weight (clears nothing). No visible overlap exists at any tested viewport width because the only surface that could collide with the pill there (`WidgetHost.tsx:17` top-right anchor at `top-12 right-3`) sits 40px BELOW the pill (top:48 vs top:8) — vertically disjoint.
2. In `ViewerMap` — NavigationControl is still top-right. The 56px `right-14` clearance is exactly what makes the pill and NavigationControl coexist without overlap. Removing it would re-introduce the original RESP-02 defect in the viewer.

**Strategy choice rationale (per Plan 09 task 2 strategy menu A/B/C):**
- Strategy A (`right-${isRail ? '20' : '14'}` conditional) — would WIDEN the offset in BuilderMap, pushing the pill LEFT into a region with no collision surface. Solves a non-existent collision and reduces the pill's usable bounds (closer to the basemapNotice z-20 banner zone at `left-3 top-3`). Rejected.
- Strategy B (reposition to `bottom-left`) — would move the pill into the ScaleControl zone (`<ScaleControl position="bottom-left" />` at BuilderMap.tsx:929 + WidgetHost bottom-left at `bottom-14 left-4`), creating a NEW collision while fixing none. Rejected.
- Strategy C (clip representative-fraction display at narrow widths) — pure cosmetic regression for a non-existent problem. The current text width fits in all tested viewports ≥800px (single-line `font-mono text-2xs px-1.5 py-0.5` pill, width bounded by `coords.lat.toFixed(2)`+`coords.lng.toFixed(2)`+`z N.N`+optional `1:N k` segment ≈ ~210-250px max). Rejected.
- **Strategy D (chosen): documentation-only resolution.** Ship a docstring extension on `MapCoordReadout` that names the RESP-02 contract, cross-references commit `391459bb` / Plan 08, and explains why `right-14` is load-bearing in the viewer even though the builder's NavigationControl moved. This is the minimum-touch production change that prevents the most likely future regression (a refactor that reads "this 56px right offset is dead weight in builder" and shortens it, silently breaking the viewer).

## What Shipped

**Production change:** `frontend/src/components/map/MapCoordReadout.tsx` — docstring extension above the component declaration. +15/-0 lines. No behavioral change to the rendered output, no className change, no new prop, no new import.

The added docstring block reads (substantively):
- Positioning contract identified as RESP-02 (Phase 1051 Plan 09).
- The `top-2 right-14` anchor and the 56px right offset are explicitly described.
- Cross-reference to Phase 1051 Plan 08 / commit `391459bb` (NavigationControl moved `top-right` → `top-left` in the builder context).
- Explicit warning that `right-14` is load-bearing for `ViewerMap.tsx` where NavigationControl is still `top-right`.
- Note that the top-right WidgetHost slot (`WidgetHost.tsx:17` at `top-12 right-3`) is 40px below the pill — no vertical collision with any floating widget at the same horizontal band.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 2 | Apply MapCoordReadout responsive offset/anchor fix (Strategy D — documentation-only resolution; see Strategy Choice Rationale above) | (this plan's commit) | `frontend/src/components/map/MapCoordReadout.tsx` |

Tasks 1 and 3 (Playwright MCP pre-fix collision measurement and post-fix re-verify at 1200/1100/1024/900/800px viewports) are `checkpoint:orchestrator` — deferred to the orchestrator per the phase 1051 pattern. MCP is orchestrator-scoped, not executor-spawnable (lesson from v1010.1 reinforced across plans 02-08 of this phase).

## Verification

- **Typecheck:** `cd frontend && npx tsc --noEmit` → **0 errors** (clean run, no output).
- **Diff scope:** Only `frontend/src/components/map/MapCoordReadout.tsx` (1 file, +15/-0 — pure docstring extension above existing `export const MapCoordReadout = memo(...)`).
- **No new dependencies, no schema change, no backend touch, no className change, no behavioral change.**
- **No vitest case** per UI-SPEC §RESP-02 + critical_planning_directive #10 — pure-positioning RESP-* fixes use MCP-only verification, and Plan 09 ships zero CSS class change anyway (existing `MapCoordReadout.test.tsx` SP-02 / SP-12 cases continue to assert the pre-existing behavior unchanged).

## Deviations from Plan

**Strategy D (documentation-only resolution) was not in the original Strategy A/B/C menu.** The plan listed three CSS-only fix strategies under task 2's action block, all predicated on the assumption that Plan 08 might not have eliminated the collision. The dependency-context block in this executor's spawn prompt explicitly noted that Wave 8 moved NavigationControl to `top-left`, freeing the top-right zone in BuilderMap, and instructed: "If the plan's prescribed fix is now redundant... ship a minimal touch (e.g., a comment update, or a tighter z-index, or a hover-state polish — whatever the plan still calls for that isn't redundant)."

A docstring extension that codifies the cross-context positioning contract IS the minimal touch that prevents the most likely future regression (a refactor that shortens the now-dead-weight `right-14` offset in BuilderMap context, silently breaking the viewer context where the offset is load-bearing). All three CSS-only Strategy A/B/C options either solve a non-existent collision (A), introduce a new collision (B), or cosmetically clip working output for no benefit (C).

**No auto-fixes triggered** (Rules 1-3): no bug found, no missing critical functionality, no blocking issue.

## Orchestrator-Deferred Playwright MCP Verification

Pending live MCP verification at the 5 viewport breakpoints called out in Task 3:

1. **1200px (control)** — Confirm: MapCoordReadout pill visible top-right; NavigationControl visible top-left (post-W8); no visible overlap between them.
2. **1100px (boundary)** — same.
3. **1024px (rail mode entry)** — same; confirm BuilderRail icon column on far right does not collide with the pill either.
4. **900px (rail mode middle)** — same.
5. **800px (editor-hidden boundary)** — same; BuilderRail swaps to Sheet overlay.

For each: confirm `hover` updates lat/lng (no functional regression to the `move` + `mousemove` subscriptions); confirm `pointer-events-none` retained (clicks pass through pill to underlying map); confirm representative-fraction segment (`showScale` truthy in BuilderMap.tsx:939) still renders the `1:N` suffix.

**Optional viewer-context confirmation** (out of plan scope but worth a spot-check): open a viewer page, confirm MapCoordReadout pill (top-right `right-14`) and NavigationControl (top-right) coexist without overlap at the same 5 widths — this validates the load-bearing-offset claim in the new docstring.

## Self-Check: PASSED

- `frontend/src/components/map/MapCoordReadout.tsx` exists and contains the new docstring block referencing RESP-02 / Plan 09 / commit 391459bb / ViewerMap load-bearing offset.
- `cd frontend && npx tsc --noEmit` exits with 0 errors (no output, clean run).
- Commit hash will be recorded post-commit per the sequential-execution protocol.
- No other files modified (verified pre-commit via `git status`).
