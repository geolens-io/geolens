---
phase: 1051
plan: 08
subsystem: builder
tags: [builder, responsive, navigation-control, viewport-collision, maplibre]
requires:
  - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
  - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md
  - .planning/phases/1051-map-builder-polish-bug-sweep/1051-CONTEXT.md
provides:
  - "RESP-01: MapLibre NavigationControl no longer collides with BuilderRail (Notes/History/Ask AI) at narrow viewports"
affects:
  - frontend/src/components/builder/BuilderMap.tsx
tech-stack:
  added: []
  patterns:
    - "MapLibre NavigationControl position swap (top-right → top-left) as a pure-positioning responsive fix; no conditional/runtime dispatch needed because the new anchor is collision-free at all supported widths (≥800px)"
key-files:
  created: []
  modified:
    - frontend/src/components/builder/BuilderMap.tsx
decisions:
  - "Strategy A (PATTERNS.md default): shift NavigationControl to position='top-left' at ALL widths, not conditionally per breakpoint. Rationale: the right-side BuilderRail (44px icon column at line 79 of BuilderRail.tsx) is rendered in EVERY viewport ≥800px (only hidden via isEditorHidden Sheet overlay at <800px), so the collision risk exists at all rail-rendered widths. A static reposition is simpler than a useBuilderLayout-driven conditional, has no runtime cost, and preserves the same NavigationControl behavior at wide viewports (the buttons just sit at top-left instead of top-right)."
  - "ScaleControl stays at bottom-left — no vertical overlap with new NavigationControl placement (top-left vs bottom-left)."
  - "basemapNotice (transient role='status' banner at left-3 top-3 z-20) intentionally overlays whatever MapLibre control occupies that zone — it's a deliberate failure-state notice, not a regression."
metrics:
  duration: "~10 minutes"
  completed: "2026-05-18T01:50:22Z"
---

# Phase 1051 Plan 08: RESP-01 NavigationControl Collision Fix Summary

One-liner: Anchor MapLibre NavigationControl at top-left of the map canvas so it no longer collides with the right-side BuilderRail (Notes/History/Ask AI buttons) at narrow viewports (≤1024px rail mode).

## What Shipped

**Production change:** `frontend/src/components/builder/BuilderMap.tsx:924` — `<NavigationControl position="top-right" />` → `<NavigationControl position="top-left" />` with an inline comment documenting RESP-01 rationale. Single-line behavioral swap, +5/-1 diff.

**Collision physics (per dependency context + UI-SPEC §RESP-01):**
- `BuilderRail.tsx:79` renders a `w-11` (44px) icon column as a grid sibling to the map canvas — visible at all viewports ≥800px (only swapped for a Sheet overlay at `<800px` via `isEditorHidden` in `MapBuilderPage.tsx:1314`).
- MapLibre `NavigationControl position="top-right"` anchors to the right edge of the MapGL container (the map column). At rail-mode widths (800-1099px from `BUILDER_RAIL_BREAKPOINT=1100` in `use-builder-layout.ts:6`), the map column shrinks and pushes the NavigationControl visually adjacent to the BuilderRail, which renders the 3 buttons (Notes/History/Ask AI) over the zoom-in/zoom-out/reset-north stack.
- Fix: anchor NavigationControl at the LEFT edge of the map canvas (`position="top-left"`), away from the BuilderRail. Pure-positioning fix; no functional change to zoom logic, button rendering, or interaction model.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 2 | Apply NavigationControl position fix | (this plan's commit) | `frontend/src/components/builder/BuilderMap.tsx` |

Tasks 1 and 3 (Playwright MCP pre-fix collision measurement and post-fix re-verify at 1200/1100/1024/900/800px viewports) are `checkpoint:orchestrator` — deferred to the orchestrator per the phase 1051 pattern. MCP is orchestrator-scoped, not executor-spawnable (lesson from v1010.1 reinforced across plans 02-07 of this phase).

## Verification

- **Typecheck:** `cd frontend && npx tsc --noEmit` → **0 errors**.
- **Diff scope:** Only `frontend/src/components/builder/BuilderMap.tsx` (1 file, +5/-1 — 5 lines = comment block + new line; 1 line = removed old NavigationControl line).
- **No new dependencies, no schema change, no backend touch.**
- **No vitest case** per UI-SPEC §RESP-01 and `critical_planning_directive #10` — pure-CSS/positioning RESP-* fixes use MCP-only verification.

## Deviations from Plan

None — plan executed exactly as Strategy A (PATTERNS.md default), with no auto-fixes or scope changes required.

## Orchestrator-Deferred Playwright MCP Verification

Pending live MCP verification at the 5 viewport breakpoints called out in Task 3:

1. **1200px (control)** — NavigationControl visible top-left of map; no overlap with anything.
2. **1100px (boundary)** — same.
3. **1024px (rail mode entry)** — NavigationControl visible top-left; BuilderRail visible at far right; no overlap.
4. **900px (rail mode middle)** — same.
5. **800px (editor-hidden boundary)** — BuilderRail swaps to Sheet overlay; NavigationControl still visible top-left.

For each: confirm zoom-in click increments zoom level; confirm ScaleControl (bottom-left) is unaffected; confirm v1010.2 SF-04 source dedupe is not regressed (positioning change touches no source/layer plumbing).

## Self-Check: PASSED

- `frontend/src/components/builder/BuilderMap.tsx` exists and contains the new `position="top-left"` line.
- `cd frontend && npx tsc --noEmit` exits with 0 errors (no output, clean run).
- Commit hash will be recorded post-commit per the sequential-execution protocol.
