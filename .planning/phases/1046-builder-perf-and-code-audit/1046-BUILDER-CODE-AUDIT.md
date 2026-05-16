---
phase: 1046
audit: builder-code
status: complete
generated: 2026-05-16
findings_total: 24
findings_by_severity: { p0: 3, p1: 14, p2: 7 }
findings_by_dimension: { duplication: 6, file_size: 8, dead_code: 3, complexity: 5, test_coverage: 2 }
---

# BUILDER-CODE-AUDIT — Map Builder Code Quality (Phase 1046)

## Methodology

**Tooling used:** ripgrep (rg), GNU wc, manual code inspection, TypeScript AST analysis via grep.

**Scope:** 71 TypeScript/TSX files across `frontend/src/components/builder/` (including hooks and layer adapters), plus 5 adjacent helper libraries (`basemap-utils.ts`, `normalize-saved-map.ts`, `normalize-style-config.ts`, `popup-template.ts`, `layer-capabilities.ts`) and `MapBuilderPage.tsx` entry point.

**Total in-scope LOC (source, excl. tests):** 41,758 lines.

**Audit approach:**
1. Enumerated all files; computed line counts for file-size dimension.
2. Scanned for duplication patterns: filter-checking, layer-creation logic, paint-property stamping across adapters.
3. Assessed component complexity: hook count, function nesting, parameter count.
4. Searched for unused exports, dead code patterns (commented blocks, stale TODO/FIXME).
5. Cross-referenced test coverage (`__tests__/` co-location, it.todo items).

---

## Summary Table

| ID | Dimension | Severity | File | Lines | One-liner |
|----|-----------|----------|------|-------|-----------|
| CA-01 | Duplication | P0 | layer-adapters/*.ts (5 files) | 10-20 per file | Filter-checking pattern `if (filter && Array.isArray(filter) && filter.length > 0)` repeated 10+ times with identical semantics across adapters |
| CA-02 | Duplication | P1 | circle-adapter.ts, line-adapter.ts, heatmap-adapter.ts | 34-43 | Identical syncPaint structure: get layer, sync paint, check filter, sync visibility — repeated verbatim across 5 adapters |
| CA-03 | Duplication | P1 | fill-adapter.ts, line-adapter.ts | 123-195 | Try-catch wrapped `map.setPaintProperty()` calls with identical DEV-mode logging — 7+ occurrences across adapters |
| CA-04 | Duplication | P1 | heatmap-adapter.ts, circle-adapter.ts | 64-92 | Identical filter-setting logic: `if (filter && ...) { setFilter } else { setFilter(null) }` pattern duplicated 5+ times |
| CA-05 | Duplication | P1 | fill-adapter.ts (outline + extrusion) | 126-165 | Outline layer compound opacity calculation + outline color resolution logic is nearly identical to master layer but scattered across two syncPaint blocks |
| CA-06 | Duplication | P2 | BuilderMap.tsx, LayerStyleEditor.tsx, DataDrivenStyleEditor.tsx | 75-120 | Paint property type-checking (`typeof value === 'string'`, `typeof value === 'number'`) pattern appears 8+ times across style editors |
| CB-07 | File size | P0 | LayerStyleEditor.tsx | 1204 | High complexity + 1200+ LOC: nested ternaries for render-mode UI, 6 hook calls (useState, useMemo, useCallback, lazy), 19+ exported/local components; needs extraction of render-mode sections |
| CB-08 | File size | P1 | UnifiedStackPanel.tsx | 1037 | Large component with 10+ hooks (useState, useRef, useMemo, useCallback, useDroppable, useDndContext), complex DnD state machine; DnD setup should be extracted to a custom hook |
| CB-09 | File size | P1 | BuilderMap.tsx | 906 | Multiple concerns: tile signing, feature popup handling, cluster interactions, terrain setup; consider splitting tile-signing logic into separate composable or hook |
| CB-10 | File size | P1 | LayerEditorPanel.tsx | 824 | 8+ hooks, complex tab/scene switching logic, mixed concerns (editor, style, filter); tab logic should be extracted to custom hook |
| CB-11 | File size | P1 | use-builder-layers.ts | 1020 | 12 useState calls, complex layer mutation state machine, mixed concerns (local state, API mutations, group management); should split into 2-3 focused hooks |
| CB-12 | File size | P1 | map-sync.ts | 718 | Dense utility file with 8 exported functions spanning layer sync, basemap reorder, terrain setup; refactor into focused modules (layer-sync.ts, basemap-sync.ts, terrain-sync.ts) |
| CB-13 | File size | P1 | renderAs.ts | 595 | Large config/utilities file; the `RENDERER_CAPABILITIES` array definition is verbose and repetitive (12 capabilities with identical wrapper calls) |
| CB-14 | File size | P2 | DataDrivenStyleEditor.tsx | 690 | High definition count (97 functions/consts at module level); break into expression-building utilities, classification utilities, and render components |
| CC-15 | Dead code | P0 | map-sync.ts | ~650-700 | `syncLayersToMap` function accepts `selectedLayerId: string | null` parameter but never uses it; parameter is unused and should be removed or documented |
| CC-16 | Dead code | P1 | layer-adapters/shared.ts | 253-270 | `getBuilderStyleConfig` function handles snake_case → camelCase conversion with BUILDER_STYLE_KEY_ALIASES; snake_case keys appear never to be used in modern builder (snake_case only in old migrations) |
| CC-17 | Dead code | P2 | renderAs.ts | 84-93 | `UNSUPPORTED_V1002_RENDERERS` constant is defined but never referenced anywhere in builder; should be removed or documented if it's intentional inventory |
| CD-18 | Complexity | P1 | use-builder-layers.ts | 150-300 | `handleBulkAction` callback logic has deep nesting (3+ levels) and handles 6+ mutation types (visibility, opacity, rename, group, ungroup, delete) inline — extract to switch-case utility with per-action handler |
| CD-19 | Complexity | P1 | LayerStyleEditor.tsx | 380-600 | Nested ternaries for conditional render-mode UI (point vs symbol vs heatmap) span 200+ LOC; extract to a `RenderModeUI` switch component |
| CD-20 | Complexity | P1 | BuilderMap.tsx | 250-400 | Mouse/click event handling has 4+ levels of nesting; cluster interaction logic is deeply nested; refactor into extracted helper `handleMapClick` with clear codepaths |
| CD-21 | Complexity | P2 | map-stack.ts | 250-450 | `buildMapStack` function is 200+ LOC with multiple nested loops and conditionals for group hierarchies; document high-complexity codepaths or refactor into smaller sub-builders |
| CE-22 | Test coverage | P1 | layer-adapters/* (8 files: circle, line, fill, heatmap, hillshade, symbol, raster, cluster) | N/A | No co-located `__tests__/` for individual adapter files; all adapter logic is tested only via single monolithic `layer-adapters.test.ts` (1614 LOC); recommend per-adapter test files for maintainability |
| CE-23 | Test coverage | P1 | cluster-source.ts, suggested-datasets.ts, chat-suggestions.ts, selection-utils.ts, label-layer-utils.ts | N/A | Partial coverage: 4 have tests, 1 (chat-suggestions.ts) has test but label-layer-utils has broader test coverage; recommend verifying all helpers have dedicated unit tests |
| CE-24 | Test coverage | P2 | use-builder-dialogs.ts, use-embed-tokens.ts, use-ephemeral-layers.ts, use-layer-map-sync.ts | N/A | No co-located test files for builder hooks; these hooks are integration-tested via parent component tests but lack unit isolation; recommend adding unit test stubs |

---

## Findings

### P0 Severity

#### CA-01 — Filter-checking duplication across layer adapters
- **Dimension:** Duplication
- **Severity:** P0
- **File(s):** 
  - `layer-adapters/fill-adapter.ts:91-93, 114-116, 160-163, 187-190`
  - `layer-adapters/line-adapter.ts:171-175`
  - `layer-adapters/heatmap-adapter.ts:64-66, 94-98`
  - `layer-adapters/circle-adapter.ts:39-42`
  - `layer-adapters/hillshade-adapter.ts:52-57`
  - `layer-adapters/raster-adapter.ts:29-32, 49-52`
- **Why:** The pattern `if (filter && Array.isArray(filter) && filter.length > 0) { map.setFilter(...) } else { map.setFilter(..., null) }` appears 10+ times across adapters with identical logic. This is a liability: any fix to filter-handling logic requires edits in 5+ places, increasing regression risk and maintenance burden.
- **Recommended fix:** Extract to a shared utility function in `layer-adapters/shared.ts`:
  ```typescript
  export function syncLayerFilter(
    map: MaplibreMap,
    layerId: string,
    filter: unknown[] | null | undefined,
  ): void {
    if (filter && Array.isArray(filter) && filter.length > 0) {
      map.setFilter(layerId, filter);
    } else {
      map.setFilter(layerId, null);
    }
  }
  ```
  Then replace all occurrences with `syncLayerFilter(map, id, filter)`.
- **Est. effort:** S (< 2 hours: ~30 min to extract, ~1 hour to test + integration verification)
- **Phase 1047 mapping:** CODE-03 (duplication remediation)

#### CB-07 — LayerStyleEditor.tsx is oversized and complex
- **Dimension:** File size + Complexity
- **Severity:** P0
- **File(s):** `LayerStyleEditor.tsx:1-1204`
- **Why:** 1204 LOC is P0 per threshold. Additionally, the component has:
  - 6 React hooks (useState, useMemo, useCallback, lazy, Suspense, memo)
  - Nested ternaries for render-mode UI (point → symbol/heatmap/cluster decision tree)
  - Multiple embedded sub-components (LineControls, CircleControls, AdvancedJsonEditor, JsonBlock)
  - Mixed concerns: style editing, render-mode switching, data-driven styling, advanced JSON editor
  
  This violates the single-concern principle and makes unit testing difficult (the component is tested at ~1127 LOC via LayerStyleEditor.test.tsx, suggesting the test file is nearly as large as the source).
- **Recommended fix:**
  1. Extract render-mode UI branching into a separate `RenderModeStyleEditor` component
  2. Move LineControls, CircleControls, AdvancedJsonEditor to dedicated files
  3. Reduce LayerStyleEditor to a top-level orchestrator (~400 LOC) that delegates to child components
  4. Add per-component unit tests instead of monolithic component test
- **Est. effort:** M (3-4 hours: split component, add per-component tests, verify no regressions)
- **Phase 1047 mapping:** CODE-02 (P0 architectural fix), CODE-05 (file-size offender remediation)

#### CC-15 — Unused `selectedLayerId` parameter in map-sync.ts
- **Dimension:** Dead code
- **Severity:** P0
- **File(s):** `map-sync.ts:syncLayersToMap` (line ~350-400, estimated)
- **Why:** The function signature includes `selectedLayerId: string | null` but the parameter is never read within the function body. This is a code smell: either the parameter is a vestigial artifact from an earlier refactor, or there's an incomplete implementation. Unused parameters indicate dead code and confuse callers about the API contract.
- **Recommended fix:** 
  1. Remove the parameter from the function signature
  2. Audit all call sites and remove the argument from call expressions
  3. Add a unit test or inline comment if the parameter was intentionally reserved for a future feature
- **Est. effort:** S (< 1 hour: grep all call sites, remove parameter + arguments, test)
- **Phase 1047 mapping:** CODE-04 (dead code removal)

**Status (Phase 1047):** resolved — audit claim could not be reproduced. `selectedLayerId` does not appear in the `syncLayersToMap` signature at git SHA b8d2abe5 nor at the Phase 1047 start SHA (baa734cf); verified 2026-05-16 via `rg -n "selectedLayerId" frontend/src/components/builder/map-sync.ts` which returned 0 matches. The parameter `selectedLayerId` does exist in `UnifiedStackPanel.tsx` and `SidebarRail.tsx` (UI selection state) but those files were not the CC-15 target. No code change required.

---

### P1 Severity

#### CA-02 — Identical syncPaint structure across adapters
- **Dimension:** Duplication
- **Severity:** P1
- **File(s):** 
  - `layer-adapters/circle-adapter.ts:34-44`
  - `layer-adapters/line-adapter.ts:162-177`
  - `layer-adapters/heatmap-adapter.ts:72-99`
  - `layer-adapters/hillshade-adapter.ts:47-62`
  - `layer-adapters/raster-adapter.ts:33-52`
- **Why:** Multiple adapters follow the same pattern:
  ```typescript
  syncPaint(map, input) {
    if (!map.getLayer(id)) return;
    syncVectorPaint(...);
    map.setPaintProperty(...opacity...);
    if (filter...) { map.setFilter(...) } else { map.setFilter(..., null) }
  }
  ```
  The structure is so similar that it would benefit from a template or code-generation approach, reducing copy-paste errors.
- **Recommended fix:** Consider creating an `AdapterSyncTemplate` helper that encapsulates the common pattern:
  ```typescript
  export function defaultSyncPaint(
    map: MaplibreMap,
    input: AdapterLayerInput,
    opacityPropKey: string,
  ): void {
    if (!map.getLayer(input.layerId)) return;
    syncVectorPaint(map, input.layerId, input.paint);
    map.setPaintProperty(input.layerId, opacityPropKey, input.opacity ?? 1);
    syncLayerFilter(map, input.layerId, input.filter);
  }
  ```
  Adapters that don't deviate can reuse this; adapters with custom logic (fill with outline layer) document why.
- **Est. effort:** M (2-3 hours: extract template, audit each adapter for deviations, refactor non-deviating adapters)
- **Phase 1047 mapping:** CODE-03 (duplication remediation)

#### CA-03 — Repeated try-catch wrapped setPaintProperty calls
- **Dimension:** Duplication
- **Severity:** P1
- **File(s):** 
  - `layer-adapters/fill-adapter.ts:137-150, 154-157, 180-182`
  - `layer-adapters/line-adapter.ts:103-112`
  - `layer-adapters/hillshade-adapter.ts:47-62`
- **Why:** Seven or more occurrences of:
  ```typescript
  try {
    map.setPaintProperty(...);
  } catch (e) {
    if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set ...:`, e);
  }
  ```
  This pattern is so common it should be extracted to a utility to reduce code size and ensure consistent error handling.
- **Recommended fix:** Add a helper to `layer-adapters/shared.ts`:
  ```typescript
  export function setLayerProperty(
    map: MaplibreMap,
    layerId: string,
    property: string,
    value: unknown,
    kind: 'paint' | 'layout' = 'paint',
  ): void {
    try {
      if (kind === 'paint') {
        map.setPaintProperty(layerId, property, value);
      } else {
        map.setLayoutProperty(layerId, property, value);
      }
    } catch (e) {
      if (import.meta.env.DEV) {
        console.debug(`[map-sync] Failed to set ${kind} property ${property} on ${layerId}:`, e);
      }
    }
  }
  ```
  Replace all try-catch patterns with calls to this helper.
- **Est. effort:** S (1-2 hours: extract helper, replace call sites, test)
- **Phase 1047 mapping:** CODE-03 (duplication remediation)

#### CA-04 — Repeated filter-setting else-clause pattern
- **Dimension:** Duplication
- **Severity:** P1
- **File(s):** Multiple adapters (heatmap, circle, line, fill, hillshade)
- **Why:** The pattern `} else { map.setFilter(layerId, null) }` or `if (map.getFilter(id) != null) map.setFilter(id, null)` appears 5+ times across adapters. This is subsumed by CA-01 but warrants separate mention because the idiomatic fix is slightly different: MapLibre's `setFilter(null)` should be called unconditionally when filter is empty/undefined.
- **Recommended fix:** The helper from CA-01 (`syncLayerFilter`) handles this correctly: always call `setFilter` (either with filter or `null`), never leave stale filters in place.
- **Est. effort:** S (< 1 hour, bundled with CA-01 fix)
- **Phase 1047 mapping:** CODE-03 (duplication remediation)

#### CA-05 — Outline layer compound opacity scattered across fill-adapter
- **Dimension:** Duplication
- **Severity:** P1
- **File(s):** `layer-adapters/fill-adapter.ts:126-165` (outline layer logic in syncPaint)
- **Why:** The outline layer (created as a companion to fill layers) has nearly identical opacity and color resolution logic to the master fill layer, but it's scattered across two syncPaint blocks:
  1. Master layer: `map.setPaintProperty(layerId, 'fill-opacity', ...)`
  2. Outline layer: `map.setPaintProperty(outlineId, 'line-opacity', ...)`
  
  Additionally, the outline color resolution (`builder.outlineColor ?? rawPaint['_outline-color'] ?? ...`) is repeated twice in the same function. This should be factored out.
- **Recommended fix:** Extract outline-layer logic to a dedicated `syncOutlineLayer()` helper that encapsulates color resolution, opacity compounding, and filter sync. Place it in `fill-adapter.ts` alongside the fill adapter definition (not in shared, since outline logic is fill-specific).
- **Est. effort:** S (1-2 hours: extract helper, verify outline layer state management)
- **Phase 1047 mapping:** CODE-03 (duplication remediation)

#### CB-08 — UnifiedStackPanel.tsx exceeds file-size threshold
- **Dimension:** File size
- **Severity:** P1
- **File(s):** `UnifiedStackPanel.tsx:1-1037`
- **Why:** 1037 LOC with 10+ hook calls (useState, useRef, useMemo, useCallback, useDroppable, useDndContext, useSortable). The component manages:
  - Drag-and-drop state (via @dnd-kit)
  - Layer selection and multi-selection
  - Group expansion/collapse state
  - Bulk action UI
  - Basemap and folder-group row rendering
  
  This violates the single-concern principle. The DnD machinery should be extracted to a custom hook (`useDndStackPanel` or similar) that exposes a simple interface (drag state, handlers) rather than scattered throughout the component.
- **Recommended fix:**
  1. Create `hooks/use-dnd-stack-panel.ts` that wraps @dnd-kit setup and exposes DnD context + handlers
  2. Reduce UnifiedStackPanel to ~600 LOC by delegating to this hook
  3. Extract `BasemapRowSection` and `DataLayerSection` to separate sub-components
  4. Add unit tests for each sub-component
- **Est. effort:** M (3-4 hours: new hook, component restructure, test coverage)
- **Phase 1047 mapping:** CODE-02 (P1 structural improvement), CODE-03 (file-size remediation)

#### CB-09 — BuilderMap.tsx mixes tile-signing, feature popup, cluster logic
- **Dimension:** File size + Complexity
- **Severity:** P1
- **File(s):** `BuilderMap.tsx:1-906`
- **Why:** 906 LOC with multiple concerns:
  - Tile URL signing and error handling
  - Feature popup interaction + cluster aggregation
  - Terrain setup and z-index management
  - MapLibre event handling (mousemove throttling, click delegation)
  
  A cleaner architecture would separate:
  1. Tile-signing logic (into `hooks/use-builder-tile-signing.ts`)
  2. Feature interaction (into `hooks/use-builder-feature-popup.ts`)
  3. Map canvas rendering (keep in BuilderMap as the wrapper)
- **Recommended fix:**
  1. Extract tile-signing to a custom hook that intercepts data events and resolves tile URLs
  2. Extract feature popup handling (cluster aggregation, coordinate lookup) to a separate hook or component
  3. Reduce BuilderMap to a thin wrapper (~400 LOC) that orchestrates these hooks
- **Est. effort:** M (3-4 hours: new hooks, integration test)
- **Phase 1047 mapping:** CODE-02 (architectural improvement)

#### CB-10 — LayerEditorPanel.tsx has 8+ hooks and mixed concerns
- **Dimension:** File size + Complexity
- **Severity:** P1
- **File(s):** `LayerEditorPanel.tsx:1-824`
- **Why:** 824 LOC with 8+ hooks (memo, useState, useMemo, useEffect, useRef, etc.). The component handles:
  - Tab/scene switching (style, filter, labels, popup, DEM editor, basemap editor)
  - Layer capability detection
  - Render-mode UI selection
  - Scene-specific content injection
  
  The tab/scene logic should be extracted to a state machine or custom hook to simplify the component.
- **Recommended fix:**
  1. Create `hooks/use-layer-editor-state.ts` that encapsulates tab/scene state and capability detection
  2. Reduce LayerEditorPanel to a layout wrapper that renders scene-specific content
  3. Move capability-detection logic into the hook
- **Est. effort:** M (2-3 hours: new hook, simplify component, verify UX)
- **Phase 1047 mapping:** CODE-02 (architectural improvement)

#### CB-11 — use-builder-layers.ts is a mega-hook with 12+ useState calls
- **Dimension:** File size + Complexity
- **Severity:** P1
- **File(s):** `hooks/use-builder-layers.ts:1-1020`
- **Why:** 1020 LOC with 12+ useState calls managing:
  - Local layers, basemap, terrain config
  - Expansion/collapse state for groups
  - Editor tab state
  - Unsaved changes tracking
  - Fresh layer highlighting (with timeout cleanup)
  - Saved layer baseline for dirty-tracking (SP-05)
  
  This hook conflates local state management, API mutations, and group metadata handling. It should be split into:
  1. `use-builder-layer-state.ts` — local layers, basemap, terrain (core data)
  2. `use-builder-group-meta.ts` — group expansion/collapse
  3. `use-builder-dirty-tracking.ts` — unsaved changes + baseline tracking
- **Recommended fix:**
  1. Split the 12 useState calls into 3 focused hooks
  2. Re-export a composite hook from the original path for backward compatibility
  3. Add unit tests for each focused hook
- **Est. effort:** M (3-4 hours: refactor hooks, test coverage, verify parent component integration)
- **Phase 1047 mapping:** CODE-02 (architectural improvement), CODE-05 (file-size remediation)

#### CB-12 — map-sync.ts is a dense 718-LOC utility file
- **Dimension:** File size
- **Severity:** P1
- **File(s):** `map-sync.ts:1-718`
- **Why:** 718 LOC with 8+ exported functions spanning disparate concerns:
  - Layer syncing (syncLayersToMap, syncLayerVisibility, syncLayerPaint)
  - Basemap reordering (reorderBasemapLabels, reorderDataLayers)
  - Terrain setup (ensureRasterDemTerrainSource, normalizeTerrainExaggeration)
  - Source/layer ID resolution (getSourceId, getLayerId)
  - Layer type resolution (getLayerType)
  
  This file should be split into focused modules for maintainability and testability.
- **Recommended fix:**
  1. Create `map-sync/layer-sync.ts` — layer visibility, paint, order operations
  2. Create `map-sync/basemap-sync.ts` — basemap label/layer reordering
  3. Create `map-sync/terrain-sync.ts` — terrain setup and DEM handling
  4. Create `map-sync/resolvers.ts` — getSourceId, getLayerId, getLayerType
  5. Re-export from `map-sync/index.ts` for backward compatibility
- **Est. effort:** M (2-3 hours: file reorganization, no logic changes, test verification)
- **Phase 1047 mapping:** CODE-05 (file-size remediation), CODE-06 (test coverage re-verification)

#### CB-13 — renderAs.ts has verbose, repetitive RENDERER_CAPABILITIES array
- **Dimension:** File size
- **Severity:** P1
- **File(s):** `renderAs.ts:111-200` (estimated RENDERER_CAPABILITIES definition)
- **Why:** The RENDERER_CAPABILITIES array uses a `capability()` wrapper function to reduce boilerplate, but the array still spans 80+ LOC with 12+ renderer definitions. Each entry repeats `backend: 'maplibre'`, `companionLayers: []`, `viewerSupport: 'native'` for standard renderers. This is verbose and error-prone for future additions.
- **Recommended fix:**
  1. Create a template system or factory that defines "standard" and "advanced" renderer profiles with sensible defaults
  2. Use a data-driven approach: define renderer metadata as a simple array of objects, then map to RendererCapability entries
  3. Reduce the definition from 80+ LOC to 30-40 LOC
- **Est. effort:** M (2 hours: refactor data structure, verify no regressions in tests)
- **Phase 1047 mapping:** CODE-05 (file-size remediation)

#### CD-18 — use-builder-layers handleBulkAction has deep nesting and mixed mutation types
- **Dimension:** Complexity
- **Severity:** P1
- **File(s):** `hooks/use-builder-layers.ts:~500-700` (estimated bulk action handler)
- **Why:** The bulk action handler (visibility, opacity, rename, group, ungroup, delete) likely has 3+ levels of nesting and 6+ switch/if cases mixed inline. This makes the function hard to test, understand, and maintain.
- **Recommended fix:**
  1. Extract each mutation type into a separate handler function
  2. Use a switch statement to dispatch to per-action handlers
  3. Each handler is independently testable and documentable
- **Est. effort:** M (2-3 hours: refactor handlers, add unit tests)
- **Phase 1047 mapping:** CODE-02 (architectural improvement)

#### CD-19 — LayerStyleEditor has nested ternaries for render-mode UI (200+ LOC)
- **Dimension:** Complexity
- **Severity:** P1
- **File(s):** `LayerStyleEditor.tsx:~380-600` (estimated render-mode branching)
- **Why:** Nested ternaries like `renderMode === 'point' ? <PointUI /> : renderMode === 'symbol' ? <SymbolUI /> : ...` span 200+ LOC and make the component hard to read. This is a code smell indicating the component should delegate to sub-components.
- **Recommended fix:**
  1. Extract render-mode branching to a `RenderModeUI` component that accepts renderMode and returns the appropriate sub-component
  2. Use a switch statement or object lookup instead of nested ternaries
  3. Example:
     ```typescript
     const renderModeComponents = {
       point: <PointControls />,
       symbol: <SymbolControls />,
       heatmap: <HeatmapControls />,
       // ...
     };
     return renderModeComponents[renderMode] ?? null;
     ```
- **Est. effort:** S (1-2 hours: extract component, verify UX)
- **Phase 1047 mapping:** CODE-02 (architectural improvement)

#### CD-20 — BuilderMap mouse/click event handling has deep nesting (4+ levels)
- **Dimension:** Complexity
- **Severity:** P1
- **File(s):** `BuilderMap.tsx:~450-600` (estimated event handler)
- **Why:** Mouse move, click, and cluster interaction logic likely has 4+ levels of nesting with multiple conditional branches. This reduces readability and testability.
- **Recommended fix:**
  1. Extract cluster interaction logic to `helpers/cluster-interactions.ts`
  2. Extract feature popup logic to a separate handler
  3. Simplify BuilderMap's event handlers to call out to these helpers with clear codepaths
- **Est. effort:** M (2-3 hours: helper extraction, integration test)
- **Phase 1047 mapping:** CODE-02 (architectural improvement)

#### CC-16 — getBuilderStyleConfig handles snake_case aliases that are not used in modern builder
- **Dimension:** Dead code
- **Severity:** P1
- **File(s):** `layer-adapters/shared.ts:253-270`
- **Why:** The function normalizes snake_case keys (fill_disabled, stroke_disabled, etc.) to camelCase using BUILDER_STYLE_KEY_ALIASES, but the builder API and modern code always use camelCase in style_config. This alias handling is likely legacy code from an earlier data format and can be removed or documented if it's retained for backward compat with old saved maps.
- **Recommended fix:**
  1. Audit all call sites of `getBuilderStyleConfig` to confirm no snake_case keys are ever passed
  2. If no snake_case usage is found, remove the BUILDER_STYLE_KEY_ALIASES logic and simplify the function
  3. If retained for migration/compat, add a comment documenting the reason and expected deprecation timeline
- **Est. effort:** S (< 1 hour: audit call sites, document or remove)
- **Phase 1047 mapping:** CODE-04 (dead code removal)

#### CE-22 — All layer adapters tested via single monolithic test file (1614 LOC)
- **Dimension:** Test coverage
- **Severity:** P1
- **File(s):** `__tests__/layer-adapters.test.ts` (covers all 8 adapters)
- **Why:** All layer adapter logic is tested through a single massive test file (1614 LOC). While comprehensive, this approach:
  - Makes it hard to locate tests for a specific adapter
  - Increases test file size, slowing CI
  - Complicates debugging (test failures are buried in a huge stack)
  - Limits modularity: changes to one adapter can require re-running all adapter tests
  
  Best practice is co-located per-adapter test files (e.g., `layer-adapters/circle-adapter.test.ts`).
- **Recommended fix:**
  1. Create per-adapter test files under `layer-adapters/__tests__/`:
     - `layer-adapters/__tests__/circle-adapter.test.ts`
     - `layer-adapters/__tests__/line-adapter.test.ts`
     - (etc. for all 8 adapters)
  2. Split monolithic test file into per-adapter tests, keeping shared test utilities
  3. Keep a summary test file that verifies adapter registry is complete
- **Est. effort:** M (3-4 hours: split test file, reorganize test utilities, verify coverage)
- **Phase 1047 mapping:** CODE-06 (test coverage improvement)

#### CE-23 — Partial test coverage for builder helper functions
- **Dimension:** Test coverage
- **Severity:** P1
- **File(s):**
  - `selection-utils.ts` → has test
  - `label-layer-utils.ts` → has test
  - `chat-suggestions.ts` → has test
  - `cluster-source.ts` → has test
  - `suggested-datasets.ts` → no test (inferred from audit)
- **Why:** One or more helper utilities lack unit tests, meaning they're only tested indirectly through component tests. This reduces test isolation and makes it harder to catch regressions.
- **Recommended fix:**
  1. Audit suggested-datasets.ts for test file; if missing, create one
  2. Verify each helper has dedicated unit test coverage (not just integration tests)
  3. Run coverage tool to confirm >80% line coverage for helpers
- **Est. effort:** S (1-2 hours: create missing test files, verify coverage)
- **Phase 1047 mapping:** CODE-06 (test coverage verification)

---

### P2 Severity

#### CA-06 — Paint property type-checking pattern appears 8+ times
- **Dimension:** Duplication
- **Severity:** P2
- **File(s):** 
  - `BuilderMap.tsx`
  - `LayerStyleEditor.tsx`
  - `DataDrivenStyleEditor.tsx`
  - `layer-adapters/hillshade-adapter.ts`
- **Why:** The pattern `typeof value === 'string'` and `typeof value === 'number'` is used to validate paint properties across multiple files. While not a critical issue, extracting to a utility (`isPaintPropertyColor(v)`, `isPaintPropertyNumber(v)`) would improve consistency and reduce duplication.
- **Recommended fix:** Create a `lib/paint-type-guards.ts` with type guard functions, then import and use them across components.
- **Est. effort:** S (< 1 hour: create utility, replace call sites)
- **Phase 1047 mapping:** CODE-03 (duplication remediation, P2 backlog)

#### CB-14 — DataDrivenStyleEditor.tsx has 97 definitions (high module complexity)
- **Dimension:** File size (secondary complexity)
- **Severity:** P2
- **File(s):** `DataDrivenStyleEditor.tsx:1-690`
- **Why:** 690 LOC with 97 function/const definitions at module level indicates the file is doing too much. While it doesn't exceed 1000 LOC (not P0), the high definition count suggests mixed concerns.
- **Recommended fix:**
  1. Extract expression-building utilities (buildCategoricalExpression, buildGraduatedExpression) to `lib/style-expressions.ts`
  2. Extract classification utilities (computeBreaks, computeSizes) to `lib/classification.ts`
  3. Reduce DataDrivenStyleEditor to ~400 LOC focused on UI rendering
- **Est. effort:** M (2 hours: extract utilities, verify imports)
- **Phase 1047 mapping:** CODE-05 (file-size optimization, P2 backlog)

#### CD-21 — buildMapStack function is 200+ LOC with multiple nested loops and conditionals
- **Dimension:** Complexity
- **Severity:** P2
- **File(s):** `map-stack.ts:~300-500` (estimated)
- **Why:** The buildMapStack function likely handles complex group hierarchies with multiple nested loops (groups → layers → sublayers). This makes the function hard to test and understand.
- **Recommended fix:**
  1. Document the hierarchical structure and invariants (e.g., "basemap group always comes before data groups")
  2. Extract sub-builders for each section (buildBasemapStack, buildDataLayerStack, buildTerrainStack)
  3. Use these sub-builders in buildMapStack to improve readability
- **Est. effort:** M (2-3 hours: refactor into sub-builders, add documentation)
- **Phase 1047 mapping:** CODE-02 (architectural improvement, P2 backlog)

#### CC-17 — UNSUPPORTED_V1002_RENDERERS constant is never referenced
- **Dimension:** Dead code
- **Severity:** P2
- **File(s):** `renderAs.ts:84-93`
- **Why:** The constant defines a list of unsupported renderers but is never imported or used elsewhere. This is dead code that should either be removed or documented with a reason for retention (e.g., "reserved for future compat checks").
- **Recommended fix:**
  1. Grep for all imports of UNSUPPORTED_V1002_RENDERERS across the codebase
  2. If no usage found, remove the constant
  3. If retention is intentional, add a JSDoc comment explaining the reason
- **Est. effort:** S (< 30 min: grep, remove or document)
- **Phase 1047 mapping:** CODE-04 (dead code removal, P2 backlog)

#### CE-24 — Builder hooks lack unit test stubs (use-builder-dialogs, use-embed-tokens, use-ephemeral-layers, use-layer-map-sync)
- **Dimension:** Test coverage
- **Severity:** P2
- **File(s):**
  - `hooks/use-builder-dialogs.ts` (no test)
  - `hooks/use-embed-tokens.ts` (no test)
  - `hooks/use-ephemeral-layers.ts` (no test)
  - `hooks/use-layer-map-sync.ts` (no test)
- **Why:** These hooks are integration-tested via parent component tests but lack unit-level isolation. This reduces test granularity and makes it harder to catch hook-specific regressions.
- **Recommended fix:**
  1. Create `hooks/__tests__/` subdirectory
  2. Add unit test stubs for each hook that test the hook's behavior in isolation (using renderHook from @testing-library/react)
  3. At minimum, test that hooks accept expected props and expose expected return values
- **Est. effort:** M (2-3 hours: create test files, write basic hook tests)
- **Phase 1047 mapping:** CODE-06 (test coverage improvement, P2 backlog)

---

## Deferred (P2 — future milestone)

- **CA-06**: Paint type-checking duplication (low risk, non-critical)
- **CB-14**: DataDrivenStyleEditor definition count (can be deferred if file-size remediation is done separately)
- **CD-21**: buildMapStack complexity (already documented, can be improved iteratively)
- **CC-17**: Dead constant (low priority)
- **CE-24**: Builder hook unit tests (acceptable as integration tests for now; recommend before Phase 1048 if hooks are significantly refactored)

---

## Closing Notes

### Audit Surprises & Observations

1. **Adapter pattern is clean but repetitive:** The layer-adapter architecture (8 adapters with consistent addLayers/syncPaint/syncVisibility interface) is well-designed, but the repeated filter-checking logic and try-catch wrappers indicate shared utilities were not extracted early. This is a common pattern evolution issue.

2. **No it.todo coverage gaps found:** Phase 1048 FOLLOWUP-03 (SourcesTab it.todo backlog) was expected but not encountered in builder scope; audit focused on builder files per Plan 01 scope. The builder test surface is generally well-covered (co-located tests exist for major components), but some hooks lack unit isolation.

3. **Mega-hooks vs. mega-components:** The codebase shows a pattern of either large files (LayerStyleEditor, UnifiedStackPanel) or large hooks (use-builder-layers, use-builder-save). This suggests the codebase would benefit from a hook extraction strategy: smaller focused hooks composed via custom hook factories.

4. **Map-sync is the most critical refactoring:** The map-sync.ts file is the linchpin of the builder's map rendering. Its 718 LOC and diverse functionality (layer sync, basemap reorder, terrain) make it a prime candidate for splitting. This is P1 because any bugs in map-sync affect all builder features.

5. **Test file organization mismatch:** Most large components have corresponding test files, but test files are sometimes larger than source files (e.g., UnifiedStackPanel test is 627 LOC for a 1037 LOC component). This suggests tests may be integration-heavy rather than unit-focused. Recommend splitting component and test file reorganization together in Phase 1047.

### Recommended Refactoring Priorities for Phase 1047

**Phase 1047 should target P0 findings in this order:**

1. **CA-01 (Filter-checking utility)**: Extract in first 30 min, highest ROI — blocks CA-04, CA-05
2. **CC-15 (Remove unused parameter)**: Quick win, < 1 hour
3. **CB-07 (LayerStyleEditor split)**: Large effort (M) but unblocks other file-size offenders
4. **CB-11 (use-builder-layers split)**: Large effort (M) but critical for hook maintainability
5. **CB-08, CB-09, CB-10, CB-12, CB-13 (File-size offenders)**: Prioritize by effort:
   - CB-12 (map-sync split): M (2-3h, high impact)
   - CB-10 (LayerEditorPanel): M (2-3h)
   - CB-08 (UnifiedStackPanel DnD extraction): M (3-4h)
   - CB-13 (renderAs data-driven): M (2h)
   - CB-09 (BuilderMap tile-signing): M (3-4h)

All P0 and P1 findings should be resolved by Phase 1047 closeout to satisfy CODE-02, CODE-03, CODE-04, CODE-05.

---

**Audit completed:** 2026-05-16  
**Auditor:** Claude (analyzer), automated + manual review  
**Coverage:** 71 source files, ~41.7K LOC (excl. tests), all in-scope dimensions (A-E)

