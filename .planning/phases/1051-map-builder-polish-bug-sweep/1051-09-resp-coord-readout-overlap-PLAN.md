---
phase: 1051
plan: 09
type: execute
wave: 9
depends_on: ["1051-08"]
files_modified:
  - frontend/src/components/map/MapCoordReadout.tsx
autonomous: false
requirements: [RESP-02]
tags: [builder, responsive, coord-readout, viewport-collision, top-right-zone]

must_haves:
  truths:
    - "At narrow viewport widths, the MapCoordReadout pill no longer overlaps the MapLibre NavigationControl (top-right zone) — both remain visible and legible"
    - "MapCoordReadout pill still anchors to a top-edge location (no full-page repositioning); only horizontal offset adjusts"
    - "Existing pointer-events-none behavior preserved (pill does not steal click events)"
    - "Wider viewports (>1100px) are unaffected"
  artifacts:
    - path: "frontend/src/components/map/MapCoordReadout.tsx"
      provides: "Responsive horizontal offset (right-N px or alternative anchor) to avoid the NavigationControl zone"
      contains: "right-"
  key_links:
    - from: "MapCoordReadout.tsx absolute positioning (line ~111)"
      to: "BuilderMap.tsx NavigationControl (post-Plan-08 position)"
      via: "Both anchor to map canvas top edge; horizontal offsets must not collide"
      pattern: "right-"
---

<objective>
Fix RESP-02: At narrow viewport widths, the MapCoordReadout pill no longer overlaps the MapLibre map-widget container. Per critical_planning_directive #4 and PATTERNS.md Plan 09: UI-SPEC §RESP-02 was incorrectly stating "bottom-right" — the actual collision is `MapCoordReadout` at `top-2 right-14` colliding with the `NavigationControl` (top-right zone). The plan reframes around this top-right zone conflict.

Since Plan 08 (RESP-01) may have moved `NavigationControl` to `top-left` at narrow widths, the collision dynamic may have shifted. Playwright MCP must measure the post-Plan-08 layout BEFORE applying the Plan 09 fix.

Fix strategies (MCP-confirmed):
- Strategy A: increase the `right-14` offset to clear the NavigationControl at narrow widths only (e.g., `right-${isRail ? '20' : '14'}`)
- Strategy B: reposition MapCoordReadout to `bottom-left` adjacent to `ScaleControl` (gets it out of the NavigationControl zone entirely)
- Strategy C: clip the representative-fraction display text at narrow widths to reduce horizontal footprint

This is a pure-CSS responsive fix (per critical_planning_directive #10). NO vitest case — manual MCP verification only.

Purpose: Coord readout is informational; cannot occlude or be occluded by the primary zoom interaction zone.
Output: Position/offset adjustment in MapCoordReadout.tsx; MCP-verified at 800/900/1024/1100px (consistent with Plan 08 viewport set).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-CONTEXT.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md

<interfaces>
<!-- From PATTERNS.md — current MapCoordReadout position + the corrected understanding. -->

From frontend/src/components/map/MapCoordReadout.tsx (lines 110-127):
```tsx
return (
  <div className="absolute top-2 right-14 z-10 pointer-events-none">
    <div className="font-mono text-2xs tracking-wide text-muted-foreground/70 bg-background/60 backdrop-blur-sm rounded px-1.5 py-0.5">
      {Math.abs(coords.lat).toFixed(2)}° {latDir}
      {' · '}
      {Math.abs(coords.lng).toFixed(2)}° {lngDir}
      {' · '}
      <span className="text-foreground/50">z</span> {coords.zoom.toFixed(1)}
      ...
    </div>
  </div>
);
```

CORRECTION (per PATTERNS.md finding #2 + critical_planning_directive #4): `MapCoordReadout` is positioned `top-2 right-14` — TOP-RIGHT of map canvas, offset 56px from right edge. UI-SPEC §RESP-02 incorrectly stated "bottom-right". The collision is with `NavigationControl`, not with bottom-area widgets.

From frontend/src/components/map-widgets/WidgetHost.tsx (line 17 — top-right anchor for widgets):
```ts
'top-right': 'absolute top-12 right-3 z-10 flex flex-col gap-2',
```
WidgetHost top-right sits 12 units (48px) from top — below MapCoordReadout's `top-2` (8px). They don't collide vertically. The actual collision is the coord pill widening at narrow widths or the NavigationControl repositioning shifting it.

Plan 08 (RESP-01) may have moved NavigationControl to `top-left` — confirm dependency-ordering: Plan 09 depends on Plan 08 being committed first (depends_on includes 1051-08).
</interfaces>
</context>

<tasks>

<task type="checkpoint:orchestrator">
  <name>Task 1: Playwright MCP audit — measure top-right zone post-Plan-08</name>
  <files>(no files modified)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 09 — Corrected top-right framing)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md (RESP-02 contract — note: UI-SPEC has an error per critical_planning_directive #4; follow PATTERNS.md framing)
    - frontend/src/components/map/MapCoordReadout.tsx (current position)
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Open a map. (2) Resize viewport to 1200, 1100, 1024, 900, 800 (same set as Plan 08). (3) At each width: screenshot the top-right of the map canvas. (4) Use `mcp_browser_evaluate` to get bounding rects of: MapCoordReadout pill, NavigationControl, WidgetHost top-right wrapper. (5) Identify post-Plan-08 collision dynamics — if NavigationControl moved to top-left, the top-right zone may have a NEW occupant (e.g., a widget) that now collides with MapCoordReadout. (6) Record: does MapCoordReadout text wrap or extend off-edge at narrow widths? Does it intersect the WidgetHost zone? Add incidental issues to scratch list for EMRG-01.
  </action>
  <verify>
    <automated>Playwright MCP captures bounding rects + screenshots at 5 viewport widths post-Plan-08.</automated>
  </verify>
  <acceptance_criteria>
    - Post-Plan-08 top-right zone layout characterized
    - Exact viewport widths where MapCoordReadout overlaps another widget identified
    - Strategy A/B/C choice rationale recorded for Task 2
  </acceptance_criteria>
  <done>Post-Plan-08 collision characterized; fix strategy chosen.</done>
</task>

<task type="auto">
  <name>Task 2: Apply MapCoordReadout responsive offset/anchor fix</name>
  <files>frontend/src/components/map/MapCoordReadout.tsx</files>
  <read_first>
    - frontend/src/components/map/MapCoordReadout.tsx (full file — small)
    - frontend/src/components/builder/hooks/use-builder-layout.ts (isRail / isEditorHidden — if a responsive variant is needed)
    - frontend/src/components/builder/BuilderMap.tsx (post-Plan-08 NavigationControl position — for cross-check)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 09 — fix strategy options)
  </read_first>
  <action>
    Per Task 1 strategy choice, apply ONE of:
    
    Strategy A (RECOMMENDED — minimal): increase the horizontal offset at narrow widths. Add an `isNarrow` prop or consume `useBuilderLayout` (if MapCoordReadout is only used inside the builder) and conditionally apply `right-${isRail ? '20' : '14'}` (or a different offset based on Task 1 measurements). NOTE: MapCoordReadout may be used outside the builder (e.g., in the view-map page) — if so, the responsive variant must default safely. Check via `git grep -n 'MapCoordReadout' frontend/src/`.
    
    Strategy B: reposition to bottom-left. Change the outer `<div className="absolute top-2 right-14 z-10 pointer-events-none">` to `<div className="absolute bottom-2 left-4 z-10 pointer-events-none">` (or similar bottom-left coordinate). Verify the bottom-left ScaleControl does not collide.
    
    Strategy C: clip representative-fraction at narrow widths via CSS truncation (`max-w-[200px] truncate`).
    
    DO NOT: rewrite the readout's data model; change the units rendered. Pure-CSS responsive fix only.
    
    Document the chosen strategy + rationale in a comment near the change.
  </action>
  <verify>
    <automated>cd frontend && npx tsc --noEmit</automated>
  </verify>
  <acceptance_criteria>
    - `cd frontend && npx tsc --noEmit` returns 0 errors
    - Diff is minimal: only MapCoordReadout.tsx (and possibly `useBuilderLayout` import if Strategy A)
    - No vitest case (pure-CSS RESP-* fix per planner directive)
    - Existing `pointer-events-none` retained
  </acceptance_criteria>
  <done>MapCoordReadout positioning adjusted per chosen strategy.</done>
</task>

<task type="checkpoint:orchestrator">
  <name>Task 3: Playwright MCP post-fix re-verify at 5 viewports + atomic commit</name>
  <files>(no files modified beyond commit)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Reload page. (2) Resize viewport to 1200/1100/1024/900/800. (3) At each width: confirm MapCoordReadout pill does not visually overlap any widget OR control. (4) Confirm pill text remains legible (not clipped to unreadability or wrapping wrongly). (5) Confirm mouse hover still updates coord values (no functional regression — the readout subscribes to map `move` events). (6) Spot-check: clicking through the pill area (pointer-events-none) still works for any underlying map control. After MCP verify passes, create atomic commit with subject: `fix(builder): coord readout pill no longer overlaps top-right widget zone at narrow viewports (RESP-02)`. Stage only MapCoordReadout.tsx.
  </action>
  <verify>
    <automated>git log --oneline -1 && git show --stat HEAD</automated>
  </verify>
  <acceptance_criteria>
    - Playwright MCP confirms no overlap at all tested viewports
    - Pill remains visible + legible
    - No functional regression to coord-update subscription
    - Commit exists with subject `fix(builder): coord readout pill no longer overlaps top-right widget zone at narrow viewports (RESP-02)`
    - `git diff HEAD~1 HEAD --stat` shows only MapCoordReadout.tsx
  </acceptance_criteria>
  <done>RESP-02 fix verified live + committed atomically.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client-only positioning | Pure CSS/positioning change; no API surface |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1051-09 | (n/a) | MapCoordReadout position | accept | No security surface |
</threat_model>

<verification>
- Playwright MCP confirms no overlap at 800-1200px
- Pill legible at all widths
- `npx tsc --noEmit` returns 0 errors
- No vitest case (pure-CSS RESP-* fix)
</verification>

<success_criteria>
- At narrow viewport widths, MapCoordReadout does NOT overlap the NavigationControl OR any other top-right widget
- Both elements remain visible/legible
- Wider viewports unaffected
- Atomic commit on main with subject `fix(builder): coord readout pill no longer overlaps top-right widget zone at narrow viewports (RESP-02)`
</success_criteria>

<output>
Create `.planning/phases/1051-map-builder-polish-bug-sweep/1051-09-SUMMARY.md` with: post-Plan-08 collision analysis, chosen strategy + rationale, files modified, MCP screenshots at each viewport.
</output>
