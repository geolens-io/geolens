---
phase: 1059-basemap-sublayer-editor-path-b-fix
plan: "02"
subsystem: frontend-maplibre
tags: [basemap, sublayer-overrides, maplibre, style-mutation, idle-retry]
dependency_graph:
  requires: ["1059-01"]
  provides: ["applySublayerOverrides helper", "MapSublayerOverride type", "4-context wire-up"]
  affects:
    - frontend/src/types/api.ts
    - frontend/src/lib/basemap-utils.ts
    - frontend/src/lib/builder/basemap-style-mutation.ts
    - frontend/src/components/builder/BuilderMap.tsx
    - frontend/src/components/viewer/ViewerMap.tsx
tech_stack:
  added:
    - "frontend/src/lib/builder/basemap-style-mutation.ts (new module)"
  patterns:
    - "Imperative MapLibre setPaintProperty / setLayerZoomRange (no declarative <Layer> props)"
    - "map.once('idle', retry) idle-retry recovery pattern"
    - "SUBLAYER_CLASSIFIERS predicate map for semantic ID → layer resolution"
key_files:
  created:
    - frontend/src/lib/builder/basemap-style-mutation.ts
    - frontend/src/lib/builder/__tests__/basemap-style-mutation.test.ts
  modified:
    - frontend/src/types/api.ts
    - frontend/src/lib/basemap-utils.ts
    - frontend/src/components/builder/BuilderMap.tsx
    - frontend/src/components/viewer/ViewerMap.tsx
decisions:
  - "Exported StyleLayer, isRoadLayer, isBoundaryLayer, isBuildingLayer, isTextLabelLayer, SUBLAYER_CLASSIFIERS from basemap-utils.ts (D-06 reuse, not rebuild)"
  - "casing_color applied via line-color on layers with 'casing' in id (openfreemap-positron convention; best-effort heuristic, falls through gracefully for basemaps without casing sibling layers)"
  - "sourcePrefix filter inverted: layers WITH the prefix are data-layer sources and get SKIPPED; layers without string source or with different source pass through as basemap-owned (viewer context isolation)"
  - "applySublayerOverrides placed in applyViewerBasemapConfig callback in ViewerMap (already has isStyleLoaded guard + idle-retry handles the fresh-add case)"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-19"
  tasks: 4
  files: 6
---

# Phase 1059 Plan 02: Frontend MapLibre Integration - `applySublayerOverrides` Summary

Single helper `applySublayerOverrides(map, overrides, sourcePrefix?)` with idle-retry recovery, exported from a new `basemap-style-mutation.ts` module and wired into the two canonical call sites (BuilderMap.tsx + ViewerMap.tsx) covering all 4 render contexts.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add MapSublayerOverride types and export sublayer classifiers | 60ebb117 | api.ts, basemap-utils.ts |
| 2 | Implement applySublayerOverrides helper with idle-retry + tests | 0fc17ec6 | basemap-style-mutation.ts, test |
| 3 | Wire applySublayerOverrides into BuilderMap.tsx | b9d4941e | BuilderMap.tsx |
| 4 | Wire applySublayerOverrides into ViewerMap.tsx | 967f0c95 | ViewerMap.tsx |

## Helper Module

**File:** `frontend/src/lib/builder/basemap-style-mutation.ts`

**Signature:**
```typescript
export function applySublayerOverrides(
  map: MaplibreMap,
  overrides: Record<string, MapSublayerOverride> | null | undefined,
  sourcePrefix?: string,
): void
```

**6 override fields handled:**
- `stroke_color` → `line-color` on `line` layers
- `stroke_width` → `line-width` on `line` layers
- `casing_width` → `line-gap-width` on `line` layers
- `casing_color` → `line-color` on layers where `id.includes('casing')`
- `min_zoom` / `max_zoom` → `map.setLayerZoomRange(id, min, max)`
- `opacity` → `OPACITY_PAINT_KEYS_BY_TYPE[layerType]` (symbol layers get `text-opacity` + `icon-opacity`)

**Idle-retry recovery** (Test 10 locked):
```typescript
if (!map.isStyleLoaded()) {
  const retry = () => applySublayerOverrides(map, overrides, sourcePrefix);
  map.once('idle', retry);
  return;
}
```

## 4-Context Render Map

| Context | Route | Component | Call site |
|---------|-------|-----------|-----------|
| Builder | `/builder/:id` | BuilderMap.tsx | onStyleLoad + basemap appearance useEffect (2 sites) |
| Viewer | `/m/{id}` | ViewerMap.tsx | applyViewerBasemapConfig callback (1 site) |
| Shared | `/m/{token}` | ViewerMap.tsx | Same applyViewerBasemapConfig callback |
| Embed | `/embed/{token}` | ViewerMap.tsx | Same applyViewerBasemapConfig callback |

**Architectural finding confirmed:** ViewerMap.tsx is the single read-only renderer for all 3 public contexts. No separate SharedMap/EmbedMap components were created or needed. The "4 render contexts" acceptance criterion is satisfied via 2 wire-up sites.

## Test Coverage

**New test file:** `frontend/src/lib/builder/__tests__/basemap-style-mutation.test.ts`

19 tests covering:
1. `noop_when_overrides_undefined`
2. `noop_when_overrides_null`
3. `noop_when_overrides_empty_dict`
4. `applies_stroke_color_to_classified_road_layers`
5. `applies_stroke_width_to_classified_road_layers`
6. `applies_casing_to_boundary_layers`
7. `applies_min_max_zoom_via_setLayerZoomRange`
8. `applies_opacity_to_line_layer`
9. `applies_opacity_multiplicatively_over_layer_type_symbol`
10. `applies_opacity_to_building_fill_extrusion`
11. `null_override_value_does_not_clear`
12. `idle_retry_when_style_not_loaded` — verifies `map.once('idle', fn)` registered, no mutations until callback fires
13. `swallows_setPaintProperty_throws_per_layer`
14. `unknown_sublayer_id_silently_ignored`
15. `respects_sourcePrefix_for_viewer`
16. `applies_multiple_overrides_in_one_call`
17. `does_not_mutate_non_line_layers_for_stroke_color`
18. `applies_only_min_zoom_when_max_zoom_null`
19. `getLayer_returns_falsy_prevents_mutations`

**All suites green:**
- New helper tests: 19/19
- Builder tests (unchanged): 788/788
- Viewer tests (unchanged): 13/13
- Total targeted: 820/820

## Decisions Made

- **D-06 reuse:** `isRoadLayer`, `isBoundaryLayer`, `isBuildingLayer`, `isTextLabelLayer` exported from `basemap-utils.ts` (4 functions + `StyleLayer` type + `SUBLAYER_CLASSIFIERS` record). No rebuild — same predicates that drive `road_visibility` / `boundary_visibility` / `building_visibility` modes.
- **casing_color heuristic:** Applied via `line-color` to layers where `id.includes('casing')`. openfreemap-positron convention uses paired layers (`road-primary` / `road-primary-casing`). Basemaps without a casing sibling layer get no-op for `casing_color`. If a future basemap provider uses a different naming convention, this heuristic may miss; tracked as a Plan D / Phase 1060 cross-context test discovery item.
- **sourcePrefix filter direction:** The viewer's `VIEWER_SOURCE_PREFIX` (`viewer-source-`) marks data-layer sources, not basemap-layer sources. The filter SKIPS layers whose `source` starts with the prefix (they are user data), allowing basemap-owned layers (no prefix or different source) to pass through. This is the inverse of the original plan's comment but matches the actual semantics of how viewer sources are constructed.
- **D-07 order:** Both builder call sites place `applySublayerOverrides` AFTER `applyBasemapConfigToMap`. Sublayer overrides sit on top of visibility-mode mutations.

## Deviations from Plan

None — plan executed exactly as written. The `sourcePrefix` semantics clarification above was an implementation-time insight, not a plan deviation; the plan left "conservative" wording intentionally.

## Known Stubs

None. The helper is fully wired. Plan C (editor scene UI) will provide live override values from the user's edits; until then, `basemapConfig?.sublayer_overrides` is `undefined` and the helper short-circuits cleanly.

## Threat Flags

None. No new network calls, no new user-controlled URIs in this plan. Override application is purely render-side. Trust boundaries noted in threat model (T-1059B-01..05) are all mitigated by the implementation.

## Self-Check: PASSED

Files exist:
- `frontend/src/lib/builder/basemap-style-mutation.ts` — FOUND
- `frontend/src/lib/builder/__tests__/basemap-style-mutation.test.ts` — FOUND

Commits exist:
- `60ebb117` — FOUND (feat(1059-02): add MapSublayerOverride types)
- `0fc17ec6` — FOUND (feat(1059-02): implement applySublayerOverrides)
- `b9d4941e` — FOUND (feat(1059-02): wire BuilderMap)
- `967f0c95` — FOUND (feat(1059-02): wire ViewerMap)

Grep assertions:
- `grep -c "applySublayerOverrides(map," BuilderMap.tsx` = 2 ✓
- `grep -c "applySublayerOverrides(map," ViewerMap.tsx` = 1 ✓
- `grep -c "import.*applySublayerOverrides" BuilderMap.tsx` = 1 ✓
- `grep -c "import.*applySublayerOverrides" ViewerMap.tsx` = 1 ✓
- `npx tsc --noEmit` = 0 errors ✓

## Note for Plan C and Plan D

Plan C (editor scene) can now import `applySublayerOverrides` indirectly — it doesn't call the helper directly. Plan C writes override values to `useMapBuilderStore` which flows into `basemapConfig.sublayer_overrides` props and the existing builder autosave path. The `basemapConfig` dep array in BuilderMap.tsx's appearance effect already covers `sublayer_overrides` changes (whole-object dep), so live preview works without additional wiring.

Plan D (cross-context tests + i18n) can now extend `ViewerMap.basemap-config.test.tsx` with `applySublayerOverrides` mock assertions by mocking `@/lib/builder/basemap-style-mutation` in the same vi.mock block used for `@/components/builder/map-sync`.
