# Quick Task 260320-gsh: Vector Detail Page Map QA Assessment - Research

**Researched:** 2026-03-20
**Domain:** React + MapLibre GL + Terra Draw editing stack
**Confidence:** HIGH

## Summary

The vector detail page map editing stack spans ~2,125 lines across 6 files: `DatasetMap.tsx` (1,204 lines), `use-terra-draw.ts` (404), `DrawingToolbar.tsx` (171), `AttributeForm.tsx` (176), `drawing-store.ts` (57), `use-dataset-edit-capabilities.ts` (113). The component is functional and well-structured but has several optimization, maintainability, and test coverage issues worth addressing.

**Primary finding:** DatasetMap.tsx is a 1,200-line monolith doing too much (map rendering, tile management, drawing lifecycle, feature CRUD, keyboard shortcuts, fullscreen, overlay management, theme switching, dialogs). This is the single largest improvement opportunity.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Full scope: DatasetMap component, TerraDraw hook, drawing toolbar, edit capabilities -- the entire editing stack
- Report + fixes: Document findings AND fix any issues discovered -- code changes committed
- Write missing tests for uncovered paths, especially edge cases in TerraDraw lifecycle and map interactions

### Specific Ideas
- Focus on TerraDraw lifecycle management (strict mode, cleanup, event listeners)
- DatasetMap rendering, tile loading, bbox zoom, feature display
- Drawing toolbar mode filtering and geometry type mapping
- Edit affordances and capabilities (role-based permissions)
- Undo/redo history management
- Error handling and edge cases
</user_constraints>

## Findings

### 1. DatasetMap.tsx -- Optimization and Maintainability Issues

**1a. Monolith component (HIGH confidence)**
At 1,204 lines, DatasetMap handles 10+ concerns. This makes it hard to test, reason about, and modify. Extractable units:
- Map initialization and tile management (~200 lines: `addVectorLayers`, `addRasterLayers`, `addOverlaySource`, `refreshTileSource`, `handleLoad`)
- Feature CRUD operations (~150 lines: `saveAndRefresh`, `handleSaveEdit`, `handleDeleteFeature`, `handleEditAttributeSubmit`)
- Keyboard shortcut handlers (~50 lines: Escape, Ctrl+Z)
- Drawing session management (~60 lines: `finishDrawingSession`, `handleCloseDrawing`, `handleModeChange`)
- Discard confirmation logic (~30 lines: `requestDiscardConfirmation`, `handleConfirmDiscard`)

**1b. Multiple useDrawingStore selectors cause extra renders (MEDIUM confidence)**
Lines 144-152 call `useDrawingStore` 9 separate times with individual selectors. While Zustand shallow-compares each, any single property change triggers a re-render check for all 9. A single `useShallow` selector would be cleaner and equivalent:
```typescript
const { isDrawing, activeMode, setDrawing, ... } = useDrawingStore(
  useShallow((s) => ({ isDrawing: s.isDrawing, activeMode: s.activeMode, ... }))
);
```

**1c. `mapRef` + `mapInstance` dual-tracking (LOW severity)**
Lines 131-132 maintain both `mapRef` (for imperative access in callbacks) and `mapInstance` state (to pass to `useTerraDraw`). This is technically correct but slightly confusing. The pattern is necessary because `useTerraDraw` needs a reactive dependency, while callbacks need a non-stale reference.

**1d. Missing `t` in dependency arrays (LOW severity)**
`handleConfirmDiscard` (line 271) and several `handleSaveEdit`/`handleDeleteFeature` callbacks include `t` in deps. This is correct but could cause re-renders on language change during editing. Not a real problem in practice.

**1e. `refreshTileSource` removes and re-adds all layers (MEDIUM confidence)**
Lines 1159-1204: The refresh approach removes layers, removes source, re-adds source, re-adds layers. A simpler approach exists: `source.setTiles([newUrlWithCacheBuster])` would force a re-fetch without layer teardown. This is already partially done on line 805 for token refresh.

**1f. `sourcedata` event listener leak potential (LOW severity)**
In `saveAndRefresh` (lines 201-213), a `sourcedata` listener + 5s fallback timer is created per save. If the user saves multiple features rapidly, multiple listeners accumulate. The `map.off` in the fallback prevents permanent leaks but the pattern is fragile.

### 2. use-terra-draw.ts -- Lifecycle and Correctness

**2a. Strict mode handling is correct (HIGH confidence)**
Lines 104-258: The useEffect with `[map]` dependency correctly handles React strict mode's mount-unmount-remount. The cleanup on lines 109-123 explicitly removes stale `td-` prefixed sources/layers before creating a new instance. This is well-done.

**2b. Undo history stores full snapshots (MEDIUM concern)**
Lines 96-98, 296-310: Every `change` event stores a complete feature snapshot. For datasets with many features loaded into Terra Draw, this could consume significant memory. In practice, Terra Draw typically has 0-5 features at a time in this app (user draws one feature, or selects one for editing), so this is acceptable but worth noting.

**2c. `clear()` does not reset undo history (BUG)**
Line 386-389: The `clear` callback calls `draw.clear()` but does NOT reset `historyRef.current` or `setCanUndo(false)`. After clearing, `canUndo` may still be true, and pressing undo would attempt to restore features from the previous cleared state. The `setMode` function correctly resets history (line 316-318) but `clear` does not.

**2d. `undo` uses synchronous `isRestoringRef` flag (MEDIUM confidence)**
Lines 367-384: The `isRestoringRef` flag prevents the `change` handler from recording undo operations. Since `draw.clear()` and `draw.addFeatures()` are synchronous and the change handler runs synchronously, this pattern is correct. But if Terra Draw ever becomes async, this would break.

**2e. Missing `deselectFeature` from `useTerraDraw` return (LOW severity)**
The hook returns `deselectFeature` but it's never used by DatasetMap. The deselection path uses `removeFeatures([tdId])` instead. Dead code -- could be cleaned up.

**2f. `getAvailableModes` does not include 'select' (by design)**
The mapping (lines 22-29) only includes drawing modes. The `select` mode is always available via the toolbar. This is correct but could confuse future developers -- worth a comment.

### 3. DrawingToolbar.tsx -- Clean and Correct

**3a. Well-structured (HIGH confidence)**
The toolbar correctly filters modes by geometry type, shows/hides the editing action bar based on `selectedFeature`, and delegates all actions via callbacks. No significant issues.

**3b. Reads `setMode` from store but also receives `onModeChange` prop (LOW concern)**
Line 61-66: The toolbar reads `setMode` from the store as a fallback for `onModeChange`. In practice, `DatasetMap` always passes `onModeChange`, so the store-direct path is dead code.

### 4. AttributeForm.tsx -- Functional but Limited

**4a. `editableColumns` recomputed on every render (LOW severity)**
Line 73: `columns.filter(...)` runs on every render. Should be `useMemo`.

**4b. No input validation (MEDIUM concern)**
Number fields accept any string (including empty). The form converts empty to `null` on submit, which is fine, but there's no min/max validation, no required field marking, and no error states. This is acceptable for a basic editing form but limits data quality.

**4c. `useEffect` depends on `initialValues` reference (potential bug)**
Line 81-84: When `initialValues` changes (e.g., switching to a different feature), the form resets. But since `initialValues` is an object, React compares by reference. If the parent creates a new object with same content, the form resets unnecessarily. The eslint-disable comment on line 83 suppresses the missing `editableColumns` dependency warning.

### 5. drawing-store.ts -- Simple and Correct

No issues found. The store is minimal and well-typed. `clearDrawing` correctly resets all state. `clearSelectedFeature` correctly resets `isEditDirty`.

### 6. use-dataset-edit-capabilities.ts -- Correct and Well-Tested

**6a. `helperOverrides` reference stability (LOW concern)**
Line 106-112: The `useMemo` depends on `helperOverrides`. If the caller passes an inline object, this recomputes every render. Callers should memoize the override object.

**6b. Thorough test coverage**
The `DatasetPage.edit-affordances.test.tsx` covers the key scenarios: editor save/cancel flow, viewer denial, dirty geometry not showing metadata bar, legacy tab hash normalization.

### 7. Test Coverage Gaps

**Existing coverage:**
- `DatasetMap.test.tsx` (273 lines): Tests interaction states (static vs edit mode), accessibility (aria-labels), callback props, zoom-to-extent visibility. All surface-level render tests with mocked Terra Draw.
- `DatasetPage.edit-affordances.test.tsx` (343 lines): Tests full edit flow through DatasetPage with mocked DatasetMap.

**Missing test coverage (HIGH priority):**
1. **`use-terra-draw.ts` has ZERO tests.** No test file exists. Key scenarios to cover:
   - Initialization with null map (returns not-ready)
   - Initialization with valid map (returns ready)
   - `setMode` changes mode on draw instance
   - `onFinish` callback fires and removes feature from canvas
   - `onEditFinish` callback fires on drag actions
   - Undo/redo cycle (push history, undo restores previous)
   - `clear()` bug -- canUndo should reset (see 2c above)
   - `getAvailableModes()` mapping correctness
   - `getModeName()` mapping correctness
   - `extractSingleGeometry()` decomposition (currently in DatasetMap, untested)

2. **DrawingToolbar has ZERO tests.** Key scenarios:
   - Correct mode buttons shown for each geometry type
   - Active mode button highlighted
   - Edit action bar shown when feature selected
   - Undo button disabled state

3. **AttributeForm has ZERO tests.** Key scenarios:
   - Column type to input type mapping
   - Form submission with various column types
   - Skip button behavior (new feature only)
   - Initial values population (edit mode)

4. **DatasetMap editing flow is untested.** The existing tests mock Terra Draw entirely. No test verifies:
   - Feature selection click handler
   - Save/delete/cancel flows
   - Keyboard shortcuts (Escape, Ctrl+Z)
   - Discard confirmation dialog flow
   - Overlay management

### 8. Easy-Win Enhancements

| Enhancement | Impact | Effort |
|------------|--------|--------|
| Fix `clear()` not resetting undo history | Bug fix | 2 lines |
| Add unit tests for `getAvailableModes` / `getModeName` / `extractSingleGeometry` | Coverage for pure functions | ~50 lines |
| Memoize `editableColumns` in AttributeForm | Prevents unnecessary re-renders | 1 line change |
| Use `source.setTiles()` with cache-buster instead of layer teardown in `refreshTileSource` | Simpler, less error-prone tile refresh | ~20 lines |
| Add DrawingToolbar render tests | Coverage for mode filtering | ~80 lines |
| Remove unused `deselectFeature` from useTerraDraw return (or document why it exists) | Code hygiene | 1 line |

## Common Pitfalls

### Pitfall 1: Terra Draw + React Strict Mode Double Mount
**What goes wrong:** Terra Draw sources/layers from first mount persist on the map after cleanup, causing "Source already exists" errors on re-mount.
**How handled:** The code explicitly removes `td-` prefixed sources/layers before creating a new instance (lines 108-123 of use-terra-draw.ts). This is correct.

### Pitfall 2: Stale Closures in Event Handlers
**What goes wrong:** Event handlers capture stale values from the render they were created in.
**How handled:** Uses `useRef` for callbacks (`onFinishRef`, `onEditFinishRef`) and reads store state directly via `useDrawingStore.getState()` in handlers. This is correct.

### Pitfall 3: MapLibre Source/Layer Ordering
**What goes wrong:** Adding layers to MapLibre after style changes can cause layers to disappear or z-order issues.
**How handled:** The `transformStyle` callback in theme switching (lines 566-584) preserves custom sources/layers across style changes. This is correct but somewhat fragile.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Vitest + React Testing Library |
| Config file | `frontend/vitest.config.ts` |
| Quick run command | `cd frontend && npx vitest run --reporter=verbose` |
| Full suite command | `cd frontend && npx vitest run` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| QA-01 | Pure function correctness (getAvailableModes, getModeName, extractSingleGeometry) | unit | `cd frontend && npx vitest run src/hooks/__tests__/use-terra-draw.test.ts -t "pure functions"` | No |
| QA-02 | TerraDraw lifecycle (init, cleanup, strict mode) | unit | `cd frontend && npx vitest run src/hooks/__tests__/use-terra-draw.test.ts` | No |
| QA-03 | DrawingToolbar mode filtering and rendering | unit | `cd frontend && npx vitest run src/components/drawing/__tests__/DrawingToolbar.test.tsx` | No |
| QA-04 | AttributeForm type mapping and submission | unit | `cd frontend && npx vitest run src/components/drawing/__tests__/AttributeForm.test.tsx` | No |
| QA-05 | DatasetMap editing integration (select, save, delete) | integration | `cd frontend && npx vitest run src/components/dataset/__tests__/DatasetMap.test.tsx` | Partial |

### Wave 0 Gaps
- [ ] `frontend/src/hooks/__tests__/use-terra-draw.test.ts` -- covers QA-01, QA-02
- [ ] `frontend/src/components/drawing/__tests__/DrawingToolbar.test.tsx` -- covers QA-03
- [ ] `frontend/src/components/drawing/__tests__/AttributeForm.test.tsx` -- covers QA-04

## Sources

### Primary (HIGH confidence)
- Direct code analysis of all 6 files in the editing stack
- Existing test files reviewed for coverage assessment

### Secondary (MEDIUM confidence)
- React + Zustand best practices for selector patterns
- MapLibre GL JS source management patterns

## Metadata

**Confidence breakdown:**
- Component analysis: HIGH -- direct code review
- Bug identification (clear/undo): HIGH -- clear logic path
- Test gap analysis: HIGH -- verified no test files exist
- Performance concerns: MEDIUM -- based on React rendering patterns, not profiling

**Research date:** 2026-03-20
**Valid until:** 2026-04-20
