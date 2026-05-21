---
phase: 260328-pax
plan: 01
subsystem: frontend/widgets
tags: [widget, measurement, legend, turf, i18n]
dependency_graph:
  requires:
    - 260328-g46 (WidgetHost, WidgetPanel, registry infrastructure)
    - 260328-os6 (ViewerMap adapter layer)
  provides:
    - MeasurementWidget: click-to-measure distance/area with GeoJSON map overlay
    - LegendWidget: layer swatches reading ctx.layers with categorical/graduated support
  affects:
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/components/widgets/
    - frontend/src/i18n/locales/*/builder.json
tech_stack:
  added:
    - "@turf/distance@^7.3.4"
    - "@turf/area@^7.3.4"
    - "@turf/helpers@^7.3.4"
  patterns:
    - Widget registers via registerWidget() into the global widget registry
    - Widget cleanup on unmount via useEffect return function
    - LegendWidget mirrors MapLegend logic adapted to WidgetContext
key_files:
  created:
    - frontend/src/components/widgets/builtin/MeasurementWidget.tsx
    - frontend/src/components/widgets/builtin/LegendWidget.tsx
  modified:
    - frontend/src/components/widgets/register-widgets.ts
    - frontend/src/components/widgets/WidgetPanel.tsx
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/package.json
decisions:
  - MeasurementWidget uses refs to track current mode/points inside map click handler closure to avoid stale closure bugs
  - LegendWidget reads ctx.layers directly (MapLayerResponse[]) rather than transforming to MapLegendLayer format
  - Removed PlaceholderWidget registration in favor of real widgets
  - WidgetPanel max-h increased from 64 to 80 to give legend/measurement more vertical room
metrics:
  duration: "9 min"
  completed: "2026-03-28"
  tasks_completed: 2
  files_changed: 9
---

# Phase 260328-pax Plan 01: Map Builder Step 4 — Measurement and Legend Widgets Summary

**One-liner:** Measurement widget with @turf distance/area calculation and GeoJSON map overlay; Legend widget reading ctx.layers with categorical/graduated/flat swatch rendering — both wired into existing widget infrastructure, standalone MapLegend removed.

## Tasks Completed

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 | Install @turf, create MeasurementWidget | 2208b9f7 | MeasurementWidget.tsx, package.json, 4 i18n files |
| 2 | Create LegendWidget, register both widgets, remove MapLegend | 798c1957 | LegendWidget.tsx, register-widgets.ts, WidgetPanel.tsx, MapBuilderPage.tsx |
| 3 | Human verification checkpoint | skipped | — |

## What Was Built

### MeasurementWidget (`frontend/src/components/widgets/builtin/MeasurementWidget.tsx`)

- Distance mode: accumulates click points, sums `@turf/distance` between consecutive pairs (in meters)
- Area mode: computes `@turf/area` on closed polygon when 3+ points are placed
- GeoJSON source `_measure-src` with `_measure-line` (dashed blue line) and `_measure-points` (blue circles) layers added to the map on mount
- Crosshair cursor set on mount, restored on unmount
- Full cleanup on unmount: removes click handler, layers, source — guarded with `map.getSource()` checks
- Unit toggle: metric (m/km, m2/km2) vs imperial (ft/mi, ft2/mi2) with appropriate thresholds
- "Clear" button resets all state and empties the GeoJSON source
- Mode change rebuilds overlay and recomputes result from existing points
- i18n via `builder:widgets.measurement.*`

### LegendWidget (`frontend/src/components/widgets/builtin/LegendWidget.tsx`)

- Filters `ctx.layers` to visible layers where `show_in_legend !== false`
- Categorical mode: renders colored swatch (3x3 rounded) + value label per category
- Graduated mode: renders color swatch + range label (`< break[0]`, `break[i-1] - break[i]`, `>= break[last]`)
- Flat-color mode: uses `ColorizedGeometryIcon` + layer name (same as existing MapLegend)
- Respects `opacity` via inline style, respects `_outline-color` and `_stroke-disabled` paint properties for swatch borders
- Empty state when no eligible layers
- i18n via `builder:widgets.legend.*`

### Registration (`frontend/src/components/widgets/register-widgets.ts`)

- `measurement` registered with slot `top-left`, `defaultVisible: false`, icon `Ruler`
- `legend` registered with slot `bottom-left`, `defaultVisible: true`, icon `Layers`
- PlaceholderWidget registration removed

### MapBuilderPage changes

- Removed `import { MapLegend }` and the `legendLayers` const
- Removed `<MapLegend layers={legendLayers} />` JSX — legend now provided by LegendWidget inside WidgetHost

## Deviations from Plan

None — plan executed exactly as written.

## Checkpoints Skipped

**Task 3 (checkpoint:human-verify):** Skipped per execution constraints. Manual verification needed:
1. Open a map with multiple styled layers at http://localhost:8080
2. Click widget toolbar — verify "Measure" and "Legend" appear (placeholder gone)
3. Toggle Legend ON — verify layer swatches at bottom-left
4. Toggle Measurement ON — click map points to verify distance/area measurement and GeoJSON overlay
5. Close Measurement — verify overlay and crosshair cursor cleaned up
6. Fresh map load — verify Legend visible by default, Measurement not visible

## Known Stubs

None — both widgets fully wired to live data (ctx.layers, ctx.mapInstance).

## Self-Check: PASSED

- `frontend/src/components/widgets/builtin/MeasurementWidget.tsx` — FOUND (308 lines, min_lines: 80)
- `frontend/src/components/widgets/builtin/LegendWidget.tsx` — FOUND (112 lines, min_lines: 50)
- `frontend/src/components/widgets/register-widgets.ts` — FOUND, 2 registrations (measurement + legend)
- `MapBuilderPage.tsx` — no MapLegend import or usage
- i18n `widgets.measurement.*` and `widgets.legend.*` present in all 4 locales
- `@turf/distance`, `@turf/area`, `@turf/helpers` in package.json
- Commits 2208b9f7 and 798c1957 — FOUND
- `npx tsc --noEmit` — zero errors
