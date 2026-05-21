---
phase: quick-260323-lik
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/builder/map-sync.ts
  - frontend/src/components/builder/LayerStyleEditor.tsx
  - frontend/src/components/builder/__tests__/map-sync.raster.test.ts
autonomous: true
requirements: [QA-LAYER-CONFIG]

must_haves:
  truths:
    - "Opacity is always explicitly set on initial layer creation regardless of value"
    - "Label layer filter is synced when label layer already exists during syncLayersToMap"
    - "Silent catch blocks in map-sync log debug warnings for failed expressions"
    - "LayerStyleEditor uses shared getLayerType instead of duplicated local function"
    - "Custom outline-width paint property convention is documented with comments"
  artifacts:
    - path: "frontend/src/components/builder/map-sync.ts"
      provides: "Corrected opacity guards, label filter sync, debug logging, outline-width comments"
    - path: "frontend/src/components/builder/LayerStyleEditor.tsx"
      provides: "Uses getLayerType from map-sync instead of local duplicate"
    - path: "frontend/src/components/builder/__tests__/map-sync.raster.test.ts"
      provides: "Tests for opacity-at-1.0, label filter sync on existing layers"
  key_links:
    - from: "frontend/src/components/builder/LayerStyleEditor.tsx"
      to: "frontend/src/components/builder/map-sync.ts"
      via: "import { getLayerType }"
      pattern: "import.*getLayerType.*map-sync"
    - from: "frontend/src/components/builder/map-sync.ts"
      to: "maplibre-gl"
      via: "setPaintProperty for opacity on all geometry types"
      pattern: "setPaintProperty.*opacity"
---

<objective>
Apply 5 correctness and consistency fixes to the map layer configuration system identified during QA research.

Purpose: Eliminate subtle inconsistencies that could cause stale state on basemap reload, confuse debugging of AI-generated expressions, and reduce code drift risk from duplicated logic.
Output: Cleaner map-sync.ts with consistent opacity handling, complete label filter sync, debug logging, and documented custom properties.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/components/builder/map-sync.ts
@frontend/src/hooks/use-builder-layers.ts
@frontend/src/components/builder/LayerStyleEditor.tsx
@frontend/src/components/builder/__tests__/map-sync.raster.test.ts
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix map-sync.ts correctness issues</name>
  <files>frontend/src/components/builder/map-sync.ts</files>
  <action>
Apply 4 targeted fixes to map-sync.ts:

1. **Remove opacity < 1 guards** (lines 175-177, 204-206, 230-234, 252-254): Remove the `if (layer.opacity !== undefined && layer.opacity < 1)` conditions. Always set opacity explicitly on initial layer creation:
   - Circle: always call `map.setPaintProperty(layerId, 'circle-opacity', layer.opacity ?? 1)`
   - Line: always call `map.setPaintProperty(layerId, 'line-opacity', layer.opacity ?? 1)`
   - Fill: always compute `fillOpacity * (layer.opacity ?? 1)` and set `fill-opacity`
   - Outline: always call `map.setPaintProperty(outlineId, 'line-opacity', layer.opacity ?? 1)`

2. **Add label filter sync for existing label layers** (around line 330-337): In the `else` branch where the label layer already exists and properties are updated, add filter sync after the paint property updates:
   ```
   // Sync filter on existing label layer
   if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
     map.setFilter(labelId, layer.filter);
   } else {
     map.setFilter(labelId, null);
   }
   ```

3. **Add debug logging to silent catch blocks** (lines 171, 200, 226, 272): Replace empty catch blocks with `console.debug` calls:
   ```
   catch (e) {
     if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set ${prop} on ${layerId}:`, e);
   }
   ```
   Apply this pattern to all 4 silent catch blocks in the file (expression application catches at lines ~171, ~200, ~226, and the existing-source sync catch at ~272). Also apply to the two outline paint sync catches (~285, ~291).

4. **Add comment documenting outline-width custom property** (near line 238-241): Add a comment block above the outline layer creation explaining the convention:
   ```
   // Custom paint properties: 'fill-outline-color' and 'outline-width' are stored
   // in the layer's paint JSON but are NOT standard MapLibre fill paint properties.
   // They are read here and applied to a separate 'line' layer that acts as the
   // polygon outline, because MapLibre's native fill-outline-color is fixed at 1px.
   ```
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx vitest run frontend/src/components/builder/__tests__/map-sync.raster.test.ts --reporter=verbose 2>&1 | tail -20</automated>
  </verify>
  <done>All 4 fixes applied: opacity always set, label filter synced on existing layers, debug logging in catch blocks, outline-width convention documented.</done>
</task>

<task type="auto">
  <name>Task 2: Replace duplicate getGeometryType in LayerStyleEditor</name>
  <files>frontend/src/components/builder/LayerStyleEditor.tsx</files>
  <action>
1. Remove the local `getGeometryType` function (lines 15-20).
2. Add import of `getLayerType` from `@/components/builder/map-sync` at the top.
3. Replace the single usage at line 56: change `getGeometryType(layer.dataset_geometry_type)` to `getLayerType(layer.dataset_geometry_type)`.

The return types are identical (`'fill' | 'line' | 'circle'`), so no other changes needed.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -20</automated>
  </verify>
  <done>LayerStyleEditor imports getLayerType from map-sync instead of maintaining a duplicate function. TypeScript compiles cleanly.</done>
</task>

<task type="auto">
  <name>Task 3: Add unit tests for opacity and label filter sync fixes</name>
  <files>frontend/src/components/builder/__tests__/map-sync.raster.test.ts</files>
  <action>
Add 3 new test cases to the existing `syncLayersToMap` describe block:

1. **"vector layer with opacity 1.0 still sets opacity paint property"**: Create a vector Point layer with `opacity: 1`. Assert `setPaintProperty` was called with `('layer-...', 'circle-opacity', 1)`. This validates the removal of the `< 1` guard.

2. **"fill layer with opacity 1.0 sets fill-opacity and outline line-opacity"**: Create a fill Polygon layer with `opacity: 1`. Assert `setPaintProperty` was called with fill-opacity (0.3 * 1 = 0.3) and outline line-opacity (1).

3. **"existing label layer syncs filter during paint update"**: Set up a layer with `label_config: { column: 'name' }` and `filter: ['==', 'type', 'park']`. Mock `getSource` and `getLayer` to return truthy for the source and label layer (simulating existing-source path). Call `syncLayersToMap`. Assert `setFilter` was called with the label layer ID and the filter expression.

Use the existing `makeLayer`, `makeVectorToken`, and `createMockMap` helpers.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx vitest run frontend/src/components/builder/__tests__/map-sync.raster.test.ts --reporter=verbose 2>&1 | tail -30</automated>
  </verify>
  <done>3 new tests pass: opacity-at-1.0 for circle, opacity-at-1.0 for fill+outline, and label filter sync on existing layers.</done>
</task>

</tasks>

<verification>
- All existing map-sync tests pass (no regressions)
- 3 new tests validate the specific fixes
- TypeScript compiles cleanly after LayerStyleEditor refactor
- No new lint errors
</verification>

<success_criteria>
- Opacity is explicitly set on MapLibre layers at creation regardless of value (no conditional skip at 1.0)
- Label layer filter is synced in both the new-label and existing-label paths of syncLayersToMap
- All catch blocks in map-sync.ts log debug messages in dev mode
- getGeometryType duplication eliminated from LayerStyleEditor
- outline-width custom property convention documented in map-sync.ts
- All tests pass
</success_criteria>

<output>
After completion, create `.planning/quick/260323-lik-thorough-qa-pass-on-map-layer-configurat/260323-lik-SUMMARY.md`
</output>
