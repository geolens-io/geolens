---
phase: quick-260425-lbc
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/builder/ActiveFilterChips.tsx
  - frontend/src/components/builder/EphemeralBadge.tsx
  - frontend/src/components/map-widgets/WidgetHost.tsx
autonomous: true
requirements: [OVERLAY-AUDIT]

must_haves:
  truths:
    - "ActiveFilterChips and MeasurementWidget never overlap when both visible"
    - "EphemeralBadge does not collide with LegendWidget or ScaleControl"
    - "All overlay z-index values form a clear hierarchy without ambiguous stacking"
    - "No overlay element is clipped or hidden behind another at rest"
  artifacts:
    - path: "frontend/src/components/builder/ActiveFilterChips.tsx"
      provides: "Filter chips positioned below widget host region"
      contains: "top-"
    - path: "frontend/src/components/builder/EphemeralBadge.tsx"
      provides: "Ephemeral badge positioned clear of legend and scale control"
      contains: "bottom-"
    - path: "frontend/src/components/map-widgets/WidgetHost.tsx"
      provides: "Widget anchor positions with corrected offsets"
      contains: "ANCHOR_POSITIONS"
  key_links:
    - from: "frontend/src/components/builder/ActiveFilterChips.tsx"
      to: "frontend/src/components/map-widgets/WidgetHost.tsx"
      via: "non-overlapping top-left spatial region"
      pattern: "top-"
    - from: "frontend/src/components/builder/EphemeralBadge.tsx"
      to: "frontend/src/components/map-widgets/WidgetHost.tsx"
      via: "non-overlapping bottom-left spatial region"
      pattern: "bottom-"
---

<objective>
Fix all map overlay positioning conflicts in the map builder canvas.

Purpose: Multiple overlay elements (filter chips, measurement widget, ephemeral badge, legend, scale control) share the same spatial regions and collide when simultaneously visible. The critical conflict is ActiveFilterChips vs MeasurementWidget -- both anchor at `top-12 left-3 z-10`.

Output: All overlays positioned with clear spatial separation and proper z-index hierarchy.
</objective>

<execution_context>
@.claude/get-shit-done/workflows/execute-plan.md
@.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260425-lbc-in-the-map-builder-review-the-map-overla/260425-lbc-CONTEXT.md
@.planning/quick/260425-lbc-in-the-map-builder-review-the-map-overla/260425-lbc-RESEARCH.md
@frontend/src/pages/MapBuilderPage.tsx
@frontend/src/components/builder/BuilderMap.tsx

<interfaces>
<!-- Current overlay positioning (the source of conflicts) -->

From frontend/src/components/builder/MapToolbar.tsx:
```tsx
// Always visible, top-center
<div className="absolute top-3 left-1/2 -translate-x-1/2 z-[5]">
```
Toolbar height: h-8 (32px) + top-3 (12px) = bottom edge at ~44px

From frontend/src/components/map-widgets/WidgetHost.tsx:
```tsx
const ANCHOR_POSITIONS: Record<WidgetAnchor, string> = {
  'top-left':     'absolute top-12 left-3 z-10 flex flex-col gap-2',
  'top-right':    'absolute top-12 right-3 z-10 flex flex-col gap-2',
  'bottom-left':  'absolute bottom-10 left-4 z-10 flex flex-col gap-2',
  'bottom-right': 'absolute bottom-4 right-4 z-10 flex flex-col gap-2',
};
```

From frontend/src/components/builder/ActiveFilterChips.tsx:
```tsx
// CONFLICT: same position as WidgetHost top-left
<div className="absolute top-12 left-3 right-3 z-10 flex flex-wrap gap-1.5 pointer-events-none">
```

From frontend/src/components/builder/EphemeralBadge.tsx:
```tsx
// CONFLICT: bottom-4 left-4 overlaps with ScaleControl and tall legends
<div className="absolute bottom-4 left-4 z-10 ...">
```

From frontend/src/components/map/MapCoordReadout.tsx:
```tsx
// No conflict currently -- top-right corner, inside BuilderMap
<div className="absolute top-2 right-2 z-10 pointer-events-none">
```

From frontend/src/components/map-widgets/WidgetPanel.tsx:
```tsx
// Widget panel container: min-w-48 (192px)
<div className="rounded-lg border bg-background/95 backdrop-blur-sm shadow-lg min-w-48">
```

MapLibre controls (inside BuilderMap):
- NavigationControl: position="bottom-right"
- ScaleControl: position="bottom-left" (renders at ~bottom-0, left edge, ~24px tall)
</interfaces>

## Spatial Layout Reference

```
+----------------------------------------------------------+
|  [MapCoordReadout]                          top-2 right-2 |
|                                                           |
|              [MapToolbar]         top-3 center, z-[5]     |
|                                                           |
|  [WidgetHost top-left]            top-12 left-3, z-10    |
|  (MeasurementWidget)                                      |
|  [ActiveFilterChips]  <-- CONFLICT: SAME top-12 left-3   |
|                                                           |
|                                                           |
|                                                           |
|  [LegendWidget]                   bottom-10 left-4, z-10 |
|  [EphemeralBadge] <-- CONFLICT    bottom-4 left-4, z-10  |
|  [ScaleControl]   <-- CONFLICT    bottom-left (maplibre)  |
|                                         [NavigationCtrl]  |
+----------------------------------------------------------+
```

## Target Layout

```
+----------------------------------------------------------+
|  [MapCoordReadout]                          top-2 right-2 |
|                                                           |
|              [MapToolbar]         top-3 center, z-[5]     |
|                                                           |
|  [WidgetHost top-left]            top-12 left-3, z-10    |
|  (MeasurementWidget)                                      |
|                                                           |
|  [ActiveFilterChips]              top-24 left-3, z-[8]   |
|  (pushed below widget region)                             |
|                                                           |
|  [LegendWidget]                   bottom-14 left-4, z-10 |
|  [EphemeralBadge]                 bottom-8 left-4, z-[8] |
|  [ScaleControl]                   bottom-left (maplibre)  |
|                                         [NavigationCtrl]  |
+----------------------------------------------------------+
```
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix top-left collision -- push ActiveFilterChips below widget host region</name>
  <files>frontend/src/components/builder/ActiveFilterChips.tsx</files>
  <action>
Fix the critical ActiveFilterChips vs MeasurementWidget collision.

In `ActiveFilterChips.tsx`, change the container div's positioning classes:

**Current:** `absolute top-12 left-3 right-3 z-10`
**Target:** `absolute top-24 left-3 right-3 z-[8]`

Changes:
1. `top-12` (48px) -> `top-24` (96px): Pushes filter chips below the widget host region. The MeasurementWidget panel starts at top-12 (48px) and is roughly 140-160px tall with header+content+actions. Using top-24 (96px) provides clearance below the MapToolbar while leaving room for the widget. When the measurement widget is not open, the extra top space is acceptable -- the chips still sit near the top of the map.

2. `z-10` -> `z-[8]`: Lower z-index than widgets (z-10) so that if any widget extends into the chip area, the widget renders on top. Filter chips are informational/dismissible and should visually yield to interactive widget panels. This also ensures the MapToolbar at z-[5] remains below both.

The `right-3` and `pointer-events-none` remain unchanged -- chips still span the width and pass through clicks on non-chip areas.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx vitest run --reporter=verbose 2>&1 | tail -20</automated>
  </verify>
  <done>ActiveFilterChips starts at top-24 (96px from top), below the widget host top-left anchor at top-12. z-index lowered to z-[8] so widgets stack above chips. No visual overlap between filter pills and measurement widget.</done>
</task>

<task type="auto">
  <name>Task 2: Fix bottom-left stack -- stagger EphemeralBadge and widen Legend clearance</name>
  <files>frontend/src/components/builder/EphemeralBadge.tsx, frontend/src/components/map-widgets/WidgetHost.tsx</files>
  <action>
Fix the bottom-left collision between EphemeralBadge, LegendWidget, and ScaleControl.

**EphemeralBadge.tsx** -- change the container div's positioning:

**Current:** `absolute bottom-4 left-4 z-10`
**Target:** `absolute bottom-8 left-4 z-[8]`

Changes:
1. `bottom-4` (16px) -> `bottom-8` (32px): Raises the badge above the ScaleControl. MapLibre's ScaleControl renders at approximately bottom-0 and is ~24px tall. Moving to bottom-8 (32px) clears it.
2. `z-10` -> `z-[8]`: Lower than the LegendWidget's z-10, so if the legend grows tall enough to reach the badge's vertical space, the legend panel renders on top. The badge is ephemeral (dismissible) and should yield to the legend.

**WidgetHost.tsx** -- adjust the `bottom-left` anchor position:

In the `ANCHOR_POSITIONS` object, change:
**Current:** `'bottom-left': 'absolute bottom-10 left-4 z-10 flex flex-col gap-2'`
**Target:** `'bottom-left': 'absolute bottom-14 left-4 z-10 flex flex-col gap-2'`

Change `bottom-10` (40px) -> `bottom-14` (56px): This raises the legend widget higher above the ScaleControl (~24px) and the EphemeralBadge (now at bottom-8 = 32px). The gap between bottom-8 (badge) and bottom-14 (legend) provides 24px clearance, enough to prevent overlap for standard-height badges.

Update the ANCHOR_POSITIONS comment to reflect the new offset rationale:
```
// bottom-left: above ScaleControl (~24px) + EphemeralBadge (~32px)
```
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx vitest run --reporter=verbose 2>&1 | tail -20</automated>
  </verify>
  <done>EphemeralBadge at bottom-8 clears ScaleControl. LegendWidget at bottom-14 clears both EphemeralBadge and ScaleControl. z-index hierarchy: widgets z-10 > badge z-[8] > MapToolbar z-[5]. No bottom-left collisions.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>
All map overlay positioning conflicts resolved:
1. ActiveFilterChips moved from top-12 to top-24 -- no longer collides with MeasurementWidget
2. EphemeralBadge moved from bottom-4 to bottom-8 -- clears ScaleControl
3. LegendWidget anchor moved from bottom-10 to bottom-14 -- clears EphemeralBadge and ScaleControl
4. z-index hierarchy established: LayerEditor z-20 > Widgets z-10 > Chips/Badge z-[8] > Toolbar z-[5]
  </what-built>
  <how-to-verify>
    1. Open the map builder at http://localhost:8080/maps/{id}/builder
    2. Add a layer with data and apply a filter to it -- confirm filter pills appear near the top but below the toolbar area (at ~96px from top)
    3. Click the Measure tool (ruler icon in toolbar) -- confirm the MeasurementWidget panel appears at top-left and does NOT overlap with filter chips
    4. With both filter chips and measure widget visible, verify they are visually separated with no overlap
    5. Toggle the Legend on (layers icon in toolbar) -- confirm it sits in the bottom-left above the scale bar
    6. If AI chat is available, trigger an ephemeral query result -- confirm the EphemeralBadge appears between the scale bar and the legend, with no overlap
    7. Check that the scale bar (bottom-left) is fully visible and not covered by any overlay
    8. Check that NavigationControl (bottom-right zoom buttons) and MapCoordReadout (top-right) are unaffected
  </how-to-verify>
  <resume-signal>Type "approved" or describe any remaining positioning issues</resume-signal>
</task>

</tasks>

<verification>
- All overlay elements have distinct spatial positions with no overlap at rest
- z-index hierarchy is clear: z-20 (flyout) > z-10 (widgets) > z-[8] (chips/badge) > z-[5] (toolbar) > default (maplibre controls)
- Filter chips visible below toolbar + widget region
- EphemeralBadge visible above ScaleControl
- Legend visible above EphemeralBadge
- No regressions in existing WidgetHost tests
</verification>

<success_criteria>
- Zero spatial conflicts between any pair of simultaneously-visible overlay elements
- All elements visually accessible without scrolling or dismissing other overlays
- Existing tests pass
- Manual verification confirms no visual regressions
</success_criteria>

<output>
After completion, create `.planning/quick/260425-lbc-in-the-map-builder-review-the-map-overla/260425-lbc-SUMMARY.md`
</output>
