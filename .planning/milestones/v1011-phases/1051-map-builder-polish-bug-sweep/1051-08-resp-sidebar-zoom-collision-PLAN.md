---
phase: 1051
plan: 08
type: execute
wave: 8
depends_on: ["1051-07"]
files_modified:
  - frontend/src/components/builder/BuilderMap.tsx
autonomous: false
requirements: [RESP-01]
tags: [builder, responsive, navigation-control, viewport-collision]

must_haves:
  truths:
    - "At viewport widths 800-1099px (rail mode, BUILDER_RAIL_BREAKPOINT < width < BUILDER_EDITOR_HIDDEN_BREAKPOINT), the collapsed right sidebar/rail no longer overlaps the MapLibre NavigationControl"
    - "NavigationControl remains clickable + visible at all viewport widths ≥800px"
    - "Wider viewports (>1100px) are unaffected — NavigationControl stays in its prior position"
    - "Fix is pure-CSS/positioning — no functional changes to NavigationControl, zoom behavior, or interaction model"
  artifacts:
    - path: "frontend/src/components/builder/BuilderMap.tsx"
      provides: "NavigationControl position adjusted (e.g., shifted to top-left at rail mode OR padded inward from top-right) per MCP measurement"
      contains: "NavigationControl"
  key_links:
    - from: "BuilderMap.tsx NavigationControl (line ~912)"
      to: "MapLibre canvas viewport"
      via: "position prop OR custom wrapper with responsive margin"
      pattern: "position="
---

<objective>
Fix RESP-01: At narrow viewport widths (≤1024 px, exact breakpoint identified in flight via Playwright MCP), the collapsed right sidebar/rail no longer visually overlaps or obscures the MapLibre `NavigationControl` zoom in/out buttons.

Per PATTERNS.md Plan 08: `BuilderMap.tsx:912` currently has `<NavigationControl position="top-right" />`. The collision typically appears at rail mode (<1100px from `BUILDER_RAIL_BREAKPOINT`). Likely fix strategies (Playwright MCP must confirm root cause first):
- Strategy A: shift `NavigationControl` to `position="top-left"` at all widths (simplest)
- Strategy B: keep `position="top-right"` but use a responsive `style` to push it leftward when the layout enters rail or editor-hidden mode
- Strategy C: constrain the right-sidebar/rail collapse footprint so it does not extend into the NavigationControl's anchor zone

This is a pure-CSS responsive fix (per critical_planning_directive #10). NO vitest case — manual MCP verification only.

Purpose: Zoom controls are core MapLibre interaction; cannot be visually obstructed at common viewport widths.
Output: Position fix in BuilderMap.tsx; MCP-verified at 800/900/1024/1100px.
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
<!-- From PATTERNS.md — current NavigationControl + layout breakpoints. -->

From frontend/src/components/builder/BuilderMap.tsx (line ~912):
```tsx
<NavigationControl position="top-right" />
<ScaleControl position="bottom-left" maxWidth={100} unit="metric" />
```

From frontend/src/components/builder/hooks/use-builder-layout.ts (lines 6-7):
```ts
const BUILDER_RAIL_BREAKPOINT = 1100  // <1100: rail mode (sidebar collapses to 64px)
const BUILDER_EDITOR_HIDDEN_BREAKPOINT = 800  // <800: editor panel hidden; Sheet overlay used
```

From frontend/src/pages/MapBuilderPage.tsx (around lines 93-94 + 934):
```ts
const { isRail, isEditorHidden } = useBuilderLayout();
// grid template:
isRail ? 'grid-cols-[64px_1fr]' : 'grid-cols-[340px_1fr]'
// when editor open:
isRail ? 'grid-cols-[64px_380px_1fr]' : 'grid-cols-[340px_380px_1fr]'
```

UI-SPEC §RESP-01: fix strategy options (shift to top-left OR add marginRight). Confirm via MCP measurement before choosing.
</interfaces>
</context>

<tasks>

<task type="checkpoint:orchestrator">
  <name>Task 1: Playwright MCP viewport audit — identify exact collision breakpoint</name>
  <files>(no files modified)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 08 — Collision analysis)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md (RESP-01)
    - frontend/src/components/builder/hooks/use-builder-layout.ts (breakpoint constants)
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Open a map. (2) Resize the viewport to 1200px (control), 1100px, 1024px, 900px, 800px (testing each rail-mode + editor-hidden boundary). (3) At each width, screenshot the right edge of the map showing the zoom controls + the collapsed right sidebar/rail. (4) Use `mcp_browser_evaluate` to get bounding rects of: the NavigationControl element (find by `.maplibregl-ctrl-zoom-in` or similar), the right sidebar's outermost element, and any LayerEditorPanel overlay. (5) Identify the exact viewport width(s) where overlap begins. (6) Record per-viewport: is overlap purely visual (DOM siblings positioned over each other) or is it an actual occlusion (zoom buttons unclickable)? Add incidental issues to scratch list for EMRG-01.
  </action>
  <verify>
    <automated>Playwright MCP captures bounding rects + screenshots at 5 viewport widths; records collision range.</automated>
  </verify>
  <acceptance_criteria>
    - Exact collision breakpoint(s) identified
    - Whether overlap is visual-only or occlusion confirmed
    - Strategy A / B / C choice rationale recorded for Task 2
  </acceptance_criteria>
  <done>Collision characterized; fix strategy chosen.</done>
</task>

<task type="auto">
  <name>Task 2: Apply NavigationControl position/offset fix</name>
  <files>frontend/src/components/builder/BuilderMap.tsx</files>
  <read_first>
    - frontend/src/components/builder/BuilderMap.tsx (NavigationControl line ~912, surrounding ScaleControl + other controls)
    - frontend/src/components/builder/hooks/use-builder-layout.ts (isRail, isEditorHidden booleans + the consumer pattern in MapBuilderPage.tsx)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 08 — Recommended fix strategy + likely actual fix)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md (RESP-01 contract)
  </read_first>
  <action>
    Per Task 1 strategy choice, apply ONE of:
    
    Strategy A (RECOMMENDED PATTERNS.md default if simple shift suffices): change `<NavigationControl position="top-right" />` to `<NavigationControl position="top-left" />` at all viewports. Verify ScaleControl (bottom-left) does not collide with the new NavigationControl placement.
    
    Strategy B (if shift-to-left causes a new conflict): keep `position="top-right"` but consume the layout context (`useBuilderLayout`) and conditionally wrap the control in a positioned div that adds responsive `marginRight` when `isRail` is true. Example: `<NavigationControl position={isRail ? 'top-left' : 'top-right'} />`.
    
    Strategy C (if rail itself bleeds into map column): adjust the rail width / map column edge in `MapBuilderPage.tsx` grid-cols template — but this is broader scope; ONLY apply if MCP shows the rail actively bleeds.
    
    DO NOT: rewrite NavigationControl behavior; modify zoom logic; add new MapLibre controls. Pure-CSS responsive fix only per REQUIREMENTS.md Out-of-Scope.
    
    Document the chosen strategy + rationale in a comment near the change site.
  </action>
  <verify>
    <automated>cd frontend && npx tsc --noEmit</automated>
  </verify>
  <acceptance_criteria>
    - `cd frontend && npx tsc --noEmit` returns 0 errors
    - Diff is minimal: only BuilderMap.tsx (and possibly use-builder-layout consumption if Strategy B)
    - No new dependencies added
    - No vitest case (per critical_planning_directive #10 — pure-CSS RESP-* fixes use MCP verify only)
  </acceptance_criteria>
  <done>NavigationControl positioning adjusted per chosen strategy.</done>
</task>

<task type="checkpoint:orchestrator">
  <name>Task 3: Playwright MCP post-fix re-verify at all 5 viewports + atomic commit</name>
  <files>(no files modified beyond commit)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Reload page. (2) Resize viewport to each width tested in Task 1 (1200/1100/1024/900/800). (3) At each width: confirm NavigationControl is fully visible, fully clickable (click zoom-in, observe zoom level increment). (4) Confirm no overlap with the right sidebar/rail OR LayerEditorPanel. (5) Confirm ScaleControl at bottom-left is unaffected by the change. (6) Confirm v1010.2 SF-04 source dedupe (no extra MapLibre source/layer churn introduced by the positioning change). After MCP verify passes, create atomic commit with subject: `fix(builder): collapsed sidebar no longer overlaps MapLibre zoom controls at narrow viewports (RESP-01)`. Stage only BuilderMap.tsx.
  </action>
  <verify>
    <automated>git log --oneline -1 && git show --stat HEAD</automated>
  </verify>
  <acceptance_criteria>
    - Playwright MCP confirms no overlap at 800/900/1024px
    - Zoom controls clickable + functional at all 5 widths
    - ScaleControl unaffected
    - Commit exists with subject `fix(builder): collapsed sidebar no longer overlaps MapLibre zoom controls at narrow viewports (RESP-01)`
    - `git diff HEAD~1 HEAD --stat` shows only BuilderMap.tsx
  </acceptance_criteria>
  <done>RESP-01 fix verified live + committed atomically.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client-only positioning | Pure CSS/positioning change; no API surface; no untrusted input |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1051-08 | (n/a) | NavigationControl position | accept | No security surface |
</threat_model>

<verification>
- Playwright MCP confirms no overlap at narrow viewports
- Zoom controls clickable
- `npx tsc --noEmit` returns 0 errors
- No vitest case (pure-CSS RESP-* fix per planner directive)
</verification>

<success_criteria>
- At narrow viewport widths (800-1099px), the collapsed sidebar does NOT overlap MapLibre zoom controls
- Wider viewports (>1100px) unaffected
- Zoom controls remain clickable / hover-affordant
- Atomic commit on main with subject `fix(builder): collapsed sidebar no longer overlaps MapLibre zoom controls at narrow viewports (RESP-01)`
</success_criteria>

<output>
Create `.planning/phases/1051-map-builder-polish-bug-sweep/1051-08-SUMMARY.md` with: collision-breakpoint findings, chosen strategy + rationale, files modified, MCP screenshots at each viewport.
</output>
