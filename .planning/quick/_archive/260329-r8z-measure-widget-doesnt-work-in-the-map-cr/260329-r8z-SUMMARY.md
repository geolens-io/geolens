---
phase: 260329-r8z
plan: 01
subsystem: frontend/map-builder
tags: [bug-fix, widget, maplibre, react-state]
dependency_graph:
  requires: []
  provides: [working-measure-widget-in-map-creator]
  affects: [MapBuilderPage, WidgetHost, MeasurementWidget]
tech_stack:
  added: []
  patterns: [react-state-plus-ref-dual-pattern]
key_files:
  modified:
    - frontend/src/pages/MapBuilderPage.tsx
decisions:
  - "Keep mapInstanceRef alongside new mapInstance state — ref is still used for imperative ops in use-builder-layers; state drives re-renders for widget consumers"
metrics:
  duration: 5min
  completed: "2026-03-29"
---

# Quick Task 260329-r8z: Measure Widget Fix Summary

**One-liner:** Added `mapInstance` state variable in MapBuilderPage so WidgetHost re-renders with the real map instance after load, fixing the measure widget receiving null.

## What Was Done

The measure widget received `mapInstance: null` because `WidgetHost` was reading `mapInstanceRef.current` during render. React refs don't trigger re-renders when mutated, so widgets always saw null unless an unrelated state change happened to fire after the map loaded — a race condition.

**Fix (3 lines in MapBuilderPage.tsx):**

1. Added `const [mapInstance, setMapInstance] = useState<MaplibreMap | null>(null)`
2. Added `setMapInstance(map)` in `handleMapRef` callback alongside the existing `layers.handleMapRef(map)` call
3. Changed `WidgetHost ctx` prop from `mapInstance: mapInstanceRef.current` to `mapInstance` (the state variable)

The existing `mapInstanceRef` is preserved — `use-builder-layers.ts` still uses it for imperative zoom, style sync, and ephemeral layer operations.

## Deviations from Plan

None — plan executed exactly as written.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1    | 0fbc33ce | fix(260329-r8z): pass mapInstance state to WidgetHost so measure widget gets non-null map |

## Self-Check: PASSED

- `frontend/src/pages/MapBuilderPage.tsx` modified: FOUND
- Commit `0fbc33ce` exists: FOUND
- TypeScript: no compile errors
