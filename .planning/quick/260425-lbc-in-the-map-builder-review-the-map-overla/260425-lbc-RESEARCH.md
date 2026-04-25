# Quick Task: Map Overlay Element Positioning Review - Research

**Researched:** 2026-04-25
**Domain:** Map builder UI overlay layout / CSS positioning
**Confidence:** HIGH

## Summary

The map builder canvas (`BuilderMap.tsx`) hosts 9 distinct overlay elements that float over the map. Several occupy the same spatial region and produce visual conflicts. The most severe conflict is the **ActiveFilterChips vs MeasurementWidget** collision -- both anchor to `top-left` with `top-12` offset, meaning they render directly on top of each other when both are visible.

A secondary issue exists in the bottom-left corner where the **EphemeralBadge** and **LegendWidget** can overlap each other and collide with MapLibre's ScaleControl.

**Primary recommendation:** Shift ActiveFilterChips below the widget host region (increase its `top` offset or make it dynamic based on measurement widget visibility), and stagger the bottom-left elements to avoid EphemeralBadge/Legend/ScaleControl collisions.

## User Constraints (from CONTEXT.md)

### Locked Decisions
- Review ALL map overlay elements and fix all positioning conflicts -- not just filter pills vs measure widget
- Use CSS positioning fixes (adjust margins, padding, absolute positions) for targeted conflict resolution. No structural layout system refactor
- Mobile is low/not a priority. Focus on desktop viewport sizes

### Claude's Discretion
- Specific z-index ordering when overlays must stack
- Exact pixel offsets and spacing values between elements

## Complete Overlay Inventory

All elements below are positioned `absolute` within the map canvas container (`div.flex-1.relative.min-h-0.min-w-0` in `MapBuilderPage.tsx`) or within the inner `BuilderMap.tsx` container (`div.relative.h-full.w-full`).

### Overlay Elements (from source code)

| # | Element | File | Position CSS | z-index | Visibility Condition |
|---|---------|------|-------------|---------|---------------------|
| 1 | **MapToolbar** (Pan/Measure/Legend toggle) | `MapToolbar.tsx` | `absolute top-3 left-1/2 -translate-x-1/2` | `z-[5]` | Always visible |
| 2 | **ActiveFilterChips** (filter pills) | `ActiveFilterChips.tsx` | `absolute top-12 left-3 right-3` | `z-10` | When any layer has an active filter |
| 3 | **MeasurementWidget** (via WidgetHost) | `WidgetHost.tsx` / `register-widgets.ts` | `absolute top-12 left-3` (anchor: `top-left`) | `z-10` | When measurement widget toggled on |
| 4 | **LegendWidget** (via WidgetHost) | `WidgetHost.tsx` / `register-widgets.ts` | `absolute bottom-10 left-4` (anchor: `bottom-left`) | `z-10` | Default visible; toggled via toolbar |
| 5 | **EphemeralBadge** (AI query result count) | `EphemeralBadge.tsx` | `absolute bottom-4 left-4` | `z-10` | When AI query result is active |
| 6 | **MapCoordReadout** (lat/lng/zoom) | `MapCoordReadout.tsx` | `absolute top-2 right-2` | `z-10` | Always (inside BuilderMap) |
| 7 | **NavigationControl** (zoom +/-/compass) | MapLibre built-in | `bottom-right` (MapLibre position) | MapLibre default | Always |
| 8 | **ScaleControl** (metric scale bar) | MapLibre built-in | `bottom-left` (MapLibre position) | MapLibre default | Always |
| 9 | **Tile loading bar** | `BuilderMap.tsx` | `absolute top-0 left-0 right-0` | `z-10` | During tile loading |
| 10 | **LayerEditorPanel** (flyout) | `MapBuilderPage.tsx` | `absolute left-0 top-0 bottom-0 w-72` | `z-20` | When a layer is expanded for editing |
| 11 | **Sidebar expand button** | `MapBuilderPage.tsx` | `absolute left-0 top-1/2 -translate-y-1/2` | `z-10` | When sidebar is collapsed |
| 12 | **FeaturePopup** | `FeaturePopup.tsx` (MapLibre Popup) | MapLibre-managed (at click coords) | MapLibre default | On feature click |

### Spatial Conflict Analysis

#### CONFLICT 1 (CRITICAL): ActiveFilterChips vs MeasurementWidget -- top-left collision

- **ActiveFilterChips**: `top-12 left-3 right-3 z-10`
- **MeasurementWidget** (via WidgetHost `top-left` anchor): `top-12 left-3 z-10`
- **Problem**: Both start at exactly `top-12 left-3`. When the measure tool is active AND a layer has a filter, the filter pills render directly behind/on top of the measurement widget panel. Same z-index (`z-10`), same top offset (`top-12` = 48px), same left offset (`left-3` = 12px).
- **Severity**: HIGH -- this is the user-reported issue.

#### CONFLICT 2 (MODERATE): EphemeralBadge vs LegendWidget vs ScaleControl -- bottom-left stack

- **LegendWidget** (via WidgetHost `bottom-left` anchor): `bottom-10 left-4 z-10`
- **EphemeralBadge**: `bottom-4 left-4 z-10`
- **ScaleControl**: MapLibre `bottom-left` (default renders at ~`bottom-0 left-10`)
- **Problem**: EphemeralBadge at `bottom-4` (16px from bottom) sits below the Legend at `bottom-10` (40px). When the legend has many layers, it can grow tall and overlap the EphemeralBadge. The ScaleControl also occupies the bottom-left corner and can overlap with the EphemeralBadge.
- **Severity**: MODERATE -- EphemeralBadge only appears during AI query results, and legend height depends on layer count.

#### CONFLICT 3 (LOW): MapCoordReadout vs NavigationControl -- top-right adjacency

- **MapCoordReadout**: `top-2 right-2 z-10` (inside BuilderMap)
- **NavigationControl**: MapLibre `bottom-right` position
- **Problem**: These are in different corners (top-right vs bottom-right), so no overlap. However, MapCoordReadout is very close to the top-right corner where future widgets could be placed.
- **Severity**: LOW -- no current conflict.

#### CONFLICT 4 (LOW): LayerEditorPanel vs ActiveFilterChips/MeasurementWidget

- **LayerEditorPanel**: `absolute left-0 top-0 bottom-0 w-72 z-20`
- **ActiveFilterChips**: `left-3`, **MeasurementWidget**: `left-3`
- **Problem**: When the layer editor flyout is open (288px wide), the filter chips and measurement widget start at `left-3` (12px) which is behind the flyout. The flyout has `z-20` so it covers them, but the filter chips extend `right-3` so they are still partially visible on the right side of the map. The measurement widget is fully hidden behind the flyout.
- **Severity**: LOW -- the flyout z-index wins, but ideally overlays should shift right when the flyout is open.

### Widget Anchor Positions (from WidgetHost.tsx)

```
ANCHOR_POSITIONS = {
  'top-left':     'absolute top-12 left-3 z-10 flex flex-col gap-2',
  'top-right':    'absolute top-12 right-3 z-10 flex flex-col gap-2',
  'bottom-left':  'absolute bottom-10 left-4 z-10 flex flex-col gap-2',
  'bottom-right': 'absolute bottom-4 right-4 z-10 flex flex-col gap-2',
}
```

Comment in code explains the offsets:
- `top-left`: "below MapToolbar (h-8 + top-3 = ~44px ~ top-12)"
- `bottom-left`: "above ScaleControl"
- `bottom-right`: "above NavigationControl"

### Registered Widgets

| Widget | Anchor | defaultVisible |
|--------|--------|---------------|
| `measurement` | `top-left` | `false` |
| `legend` | `bottom-left` | `true` |

## Fix Recommendations

### Fix 1: ActiveFilterChips vs MeasurementWidget (CRITICAL)

The ActiveFilterChips currently uses a hardcoded `top-12`. It needs to be pushed below the measurement widget when it is visible.

**Option A (recommended -- CSS-only):** Move ActiveFilterChips to a higher `top` offset (e.g., `top-14` or `top-16`) and reduce its `left` start so it avoids the widget panel area. Since the MeasurementWidget panel is ~192px wide (`min-w-48` = 12rem) and the WidgetPanel adds padding/header, the filter chips should start after that width when the widget is open.

**Option B (prop-based):** Pass `measureActive` state into `ActiveFilterChips` and conditionally adjust `top` or add `left` padding. This is more precise but couples the components.

**Option C (layout approach):** Render ActiveFilterChips inside the WidgetHost `top-left` anchor container as a flex sibling below widgets, so they naturally stack. This avoids hardcoded offsets but requires refactoring ActiveFilterChips into the widget system.

Recommended: **Option A** -- simplest CSS adjustment. Increase the `top` value on ActiveFilterChips to clear the toolbar + widget space, or give the chips a higher `top` offset and let them flow below. Since the user wants minimal CSS fixes, adjusting the `top` offset is the safest approach.

### Fix 2: EphemeralBadge vs Legend/ScaleControl (MODERATE)

Move EphemeralBadge upward or to a different position to avoid overlap with ScaleControl and potential Legend overflow. Options:
- Move EphemeralBadge to `bottom-12` or higher to clear the ScaleControl
- Or move it to the `bottom-right` corner (would need to avoid NavigationControl)

### Fix 3: LayerEditorPanel overlay occlusion (LOW)

When the layer editor flyout is open (`w-72` = 288px), the `left-3` positioned overlays are hidden behind it. Could add a `left` offset when `editingLayer` is truthy, but this is a minor issue and the user may not want this level of complexity.

## z-index Hierarchy (current)

| z-index | Elements |
|---------|----------|
| `z-50` | WebGL context lost overlay (BuilderMap) |
| `z-20` | LayerEditorPanel flyout, sidebar collapse button |
| `z-10` | ActiveFilterChips, WidgetHost (all anchors), EphemeralBadge, MapCoordReadout, tile loading bar, sidebar expand button |
| `z-[5]` | MapToolbar |
| default | MapLibre NavigationControl, ScaleControl, AttributionControl, FeaturePopup |

**Note:** All floating overlay elements share `z-10`, which means DOM order determines stacking when they overlap. In the MapBuilderPage render order: MapToolbar, then ActiveFilterChips, then WidgetHost -- so WidgetHost renders on top of ActiveFilterChips when they overlap.

## Key File Paths

| File | Role |
|------|------|
| `frontend/src/pages/MapBuilderPage.tsx` | Page layout, renders all overlays in map canvas area |
| `frontend/src/components/builder/BuilderMap.tsx` | Map canvas, NavigationControl/ScaleControl placement, MapCoordReadout |
| `frontend/src/components/builder/MapToolbar.tsx` | Floating toolbar at top-center |
| `frontend/src/components/builder/ActiveFilterChips.tsx` | Filter pills overlay |
| `frontend/src/components/builder/EphemeralBadge.tsx` | AI query result badge |
| `frontend/src/components/map-widgets/WidgetHost.tsx` | Widget anchor positions (`ANCHOR_POSITIONS`) |
| `frontend/src/components/map-widgets/register-widgets.ts` | Widget registrations (measurement=top-left, legend=bottom-left) |
| `frontend/src/components/map-widgets/WidgetPanel.tsx` | Widget panel container (min-w-48) |
| `frontend/src/components/map/MapCoordReadout.tsx` | Coordinate readout |

## Sources

### Primary (HIGH confidence)
- All findings from direct codebase inspection of the files listed above [VERIFIED: codebase grep + file reads]
