---
phase: 1051-map-builder-polish-bug-sweep
reviewed: 2026-05-18T13:50:00Z
depth: standard
iteration: 2
files_reviewed: 32
files_reviewed_list:
  - frontend/src/components/builder/BasemapGroupRow.tsx
  - frontend/src/components/builder/BasemapSublayerEditorScene.tsx
  - frontend/src/components/builder/BuilderMap.tsx
  - frontend/src/components/builder/FolderGroupRow.tsx
  - frontend/src/components/builder/SettingsEditorScene.tsx
  - frontend/src/components/builder/SublayerConfigIndicators.tsx
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx
  - frontend/src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx
  - frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx
  - frontend/src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx
  - frontend/src/components/builder/__tests__/SettingsEditorScene.test.tsx
  - frontend/src/components/builder/__tests__/SettingsEditorScene.widgets.test.tsx
  - frontend/src/components/builder/__tests__/SublayerConfigIndicators.test.tsx
  - frontend/src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx
  - frontend/src/components/builder/hooks/__tests__/use-builder-layers.delete.test.ts
  - frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.test.ts
  - frontend/src/components/builder/hooks/use-builder-layers.ts
  - frontend/src/components/builder/hooks/use-builder-save.ts
  - frontend/src/components/builder/hooks/use-layer-map-sync.ts
  - frontend/src/components/builder/layer-adapters/circle-adapter.ts
  - frontend/src/components/builder/layer-adapters/fill-adapter.ts
  - frontend/src/components/builder/layer-adapters/heatmap-adapter.ts
  - frontend/src/components/builder/layer-adapters/line-adapter.ts
  - frontend/src/components/builder/map-sync.ts
  - frontend/src/components/map/MapCoordReadout.tsx
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
  - frontend/src/pages/MapBuilderPage.tsx
  - frontend/src/types/api.ts
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 1051: Code Review Report (Iteration 2)

**Reviewed:** 2026-05-18T13:50:00Z
**Depth:** standard
**Iteration:** 2 (re-review after iter-1 fix loop)
**Files Reviewed:** 32
**Status:** issues_found

## Summary

Iteration-2 re-review of Phase 1051 confirms **all 17 iter-1 findings (CR-01..04, WR-01..09, IN-01..04) are resolved.** Each fix was verified by reading the post-fix source at the call site, validating the diff matches the prescribed fix, and tracing call-chain side effects. i18n parity is intact (4 locales × 956 lines each, `basemapGroup.rowName` present in all four).

**No new BLOCKERs.** The adversarial sweep against the fixes themselves surfaced **2 minor WARNINGs and 2 INFOs**:

- **WR-01 (new)**: `heatmap-adapter.syncPaint` writes `heatmap-opacity` twice on every paint sync — the generic `for (const [prop, val] of Object.entries(rawPaint))` loop sets the *uncompounded* raw value first, then the post-loop block at line 99 overrides with the compounded value. Net result is correct on settle, but a transient flash to the uncompounded opacity is observable when master_opacity ≠ 1.
- **WR-02 (new)**: CR-02 fix in `BasemapGroupRow.tsx` has no regression test. The very contract that was broken (row click during multi-selection fires `onSelectGroup`) has no assertion in `__tests__/BasemapGroupRow.test.tsx` — a future refactor could re-introduce the bug undetected.

- **IN-01 (new)**: WR-08 fix expanded `structuralKey` to drive both popup-clear AND auto-fit. The auto-fit effect at line 886 doesn't care about heatmapRamp/heightColumn changes (it's gated by `layerCountChanged`), so the extra dependency runs are harmless but misleading. Future-reader hazard.
- **IN-02 (new)**: CR-04 fix has no unit test. Critical-tier behavior (heatmap-opacity compounding on add-time) is asserted only by the existing `renderAs.test.ts` test which checks the literal `{ 'heatmap-opacity': 0.8 }` patch — not the runtime compounding formula.

### Iter-1 finding verification (all 17 closed)

| ID | Status | Verification |
|----|--------|--------------|
| CR-01 | Fixed | `SublayerConfigIndicators.tsx:65-66` — `isExpressionValue` checks `typeof value[0] === 'string'` |
| CR-02 | Fixed | `BasemapGroupRow.tsx:67-74, 92-100` — both click + keydown handlers honor `isMultiSelectionActive` |
| CR-03 | Fixed | `MapBuilderPage.tsx:696` — `normalizeBasemapConfig(null, layers.showBasemapLabels)` replaces inline literal |
| CR-04 | Fixed | `heatmap-adapter.ts:50-51` — `storedHeatmapOpacity * (opacity ?? 1)` mirrors syncPaint formula |
| WR-01 | Fixed | `use-builder-layers.ts:379, 555` — both call sites use `` `group-${crypto.randomUUID()}` `` |
| WR-02 | Fixed | `UnifiedStackPanel.tsx:113-118, 1111` — props are non-optional; runtime guards removed |
| WR-03 | Fixed | `SettingsEditorScene.tsx:58` — `disabled && 'cursor-not-allowed opacity-50'` on wrapper |
| WR-04 | Fixed | `BuilderMap.tsx:100, 377, 895, 962` — `mapInstance` state mirror added + cleanup |
| WR-05 | Fixed | `BasemapSublayerEditorScene.tsx:191-202, 218-227` — min/max relaxed to 0/22 + clamp handler |
| WR-06 | Fixed | `BuilderMap.tsx:175-186` — `setMapStyle(styleValue)` removed from catch; placeholder retained |
| WR-07 | Fixed | `use-builder-save.ts:160, 189-197, 599-600` — guard keyed by `userId:mapId` |
| WR-08 | Fixed | `BuilderMap.tsx:716-730` — `structuralKey` includes `dataset_table_name` + `:hm:`/`:hc:` extras |
| WR-09 | Fixed | `FolderGroupRow.test.tsx:387-391` — Test 21 removed with explanatory comment block |
| IN-01 | Fixed | `BasemapGroupRow.tsx:62-65` + 4 locale files — `basemapGroup.rowName` added consistently |
| IN-02 | Fixed | `MapBuilderPage.tsx:270, 466, 477, 844-857` — all `TODO(Phase 1038)` renamed to `TODO(BUILDER-SUBLAYER-PERSIST)` |
| IN-03 | Fixed | `SettingsEditorScene.tsx:23, 136` — `TERRAIN_EXAGGERATION_UI_MAX = 3.0` extracted with docstring |
| IN-04 | Fixed | `AGENTS.md:25-35` — "Inline review-comment convention" subsection added |

All 17 fixes are correct in shape, scope, and intent. No iter-1 regression detected.

---

## Warnings

### WR-01: heatmap-adapter syncPaint double-writes heatmap-opacity (transient flash)

**File:** `frontend/src/components/builder/layer-adapters/heatmap-adapter.ts:84-99`

**Issue:** The `syncPaint` body has two passes that both write `heatmap-opacity`:

```typescript
// Sync only heatmap-* properties, skip custom props
for (const [prop, val] of Object.entries(rawPaint)) {
  if (CUSTOM_PAINT_PROPS.has(prop)) continue;
  if (!prop.startsWith('heatmap-')) continue;
  try {
    const current = map.getPaintProperty(layerId, prop);
    if (paintValueChanged(current, val)) {
      map.setPaintProperty(layerId, prop, val);   // ← writes raw stored opacity
    }
  } catch (e) { ... }
}

// Compound stored heatmap-opacity with master opacity
const storedOpacity = (rawPaint['heatmap-opacity'] as number) ?? 0.8;
map.setPaintProperty(layerId, 'heatmap-opacity', storedOpacity * (input.opacity ?? 1));
```

When `master_opacity = 0.5` and `rawPaint['heatmap-opacity'] = 0.8`:

1. **Pass 1 (loop)**: `current = 0.8 * 0.5 = 0.4` (compounded from prior sync), `val = 0.8` (raw from rawPaint). `paintValueChanged(0.4, 0.8) → true`. Writes `0.8` (raw, *uncompounded*).
2. **Pass 2 (line 99)**: writes `0.8 * 0.5 = 0.4` (correctly compounded).

The settled value is correct (0.4), but during the synchronous sequence between line 90 and line 99, MapLibre has the layer at `heatmap-opacity = 0.8`. If MapLibre internally batches paint property changes across a single frame, the user sees a flash to full-saturation heatmap on every master-opacity-driven sync. Even if MapLibre coalesces the two writes within the same frame, the loop work is wasted.

This is the same defect class as CR-04 (which was the *add-time* version of this bug). CR-04's fix only addressed `addLayers`; `syncPaint` still has it.

**Fix:** Skip `heatmap-opacity` inside the generic loop so the compounding write at line 99 is the only writer:

```typescript
for (const [prop, val] of Object.entries(rawPaint)) {
  if (CUSTOM_PAINT_PROPS.has(prop)) continue;
  if (!prop.startsWith('heatmap-')) continue;
  if (prop === 'heatmap-opacity') continue;  // compounded write below owns this property
  try {
    const current = map.getPaintProperty(layerId, prop);
    if (paintValueChanged(current, val)) {
      map.setPaintProperty(layerId, prop, val);
    }
  } catch (e) { /* ... */ }
}

const storedOpacity = (rawPaint['heatmap-opacity'] as number) ?? 0.8;
map.setPaintProperty(layerId, 'heatmap-opacity', storedOpacity * (input.opacity ?? 1));
```

This makes the compounding write the single source of truth, eliminates the transient flash, and removes the loop's no-op work.

---

### WR-02: CR-02 fix has no regression test in BasemapGroupRow.test.tsx

**File:** `frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx` (no `isMultiSelectionActive` test cases)

**Issue:** The CR-02 fix added `if (isMultiSelectionActive) return;` to both `handleRowClick` and `onKeyDown` in `BasemapGroupRow.tsx`. The fix is correct, but `BasemapGroupRow.test.tsx` does not exercise this branch — `grep isMultiSelectionActive` in that test file returns zero matches.

The only related coverage is `UnifiedStackPanel.basemap-drag.test.tsx:183-198` (Test 3), which tests the *grip* cursor styling under multi-selection — not the row-body click suppression. The behavioral contract "row click during multi-selection is a no-op" has no assertion at any level of the test pyramid.

This is a defense-in-depth gap: a future refactor that drops the `isMultiSelectionActive` guard (e.g., a maintainer "cleaning up unused parameter" sees `_e: React.MouseEvent` and removes the whole branch) re-introduces the silent-BulkActionBar-unmount bug undetected.

**Fix:** Add a regression test to `BasemapGroupRow.test.tsx`:

```typescript
it('Test CR-02: row click during multi-selection does NOT fire onSelectGroup', () => {
  const onSelectGroup = vi.fn();
  render(
    <BasemapGroupRow
      {...defaultProps({ groupId: 'grp-ms', onSelectGroup, isMultiSelectionActive: true })}
    />,
  );

  const nameSpan = screen.getByText(/Basemap · Positron/);
  fireEvent.click(nameSpan);

  expect(onSelectGroup).not.toHaveBeenCalled();
});

it('Test CR-02: Enter/Space keydown during multi-selection does NOT fire onSelectGroup', () => {
  const onSelectGroup = vi.fn();
  render(
    <BasemapGroupRow
      {...defaultProps({ groupId: 'grp-ms', onSelectGroup, isMultiSelectionActive: true })}
    />,
  );

  const row = document.getElementById('stack-row-grp-ms')!;
  fireEvent.keyDown(row, { key: 'Enter' });
  fireEvent.keyDown(row, { key: ' ' });

  expect(onSelectGroup).not.toHaveBeenCalled();
});
```

---

## Info

### IN-01: structuralKey overloaded — drives popup-clear AND auto-fit (developer hazard)

**File:** `frontend/src/components/builder/BuilderMap.tsx:716-730, 886`

**Issue:** WR-08's fix expanded `structuralKey` to include `heatmapRamp`, `heightColumn`, and `dataset_table_name`. The key is consumed by two `useEffect`s:

1. Line 735 (popup-clear): correctly invalidates when any structural property changes — *this was the intent*.
2. Line 886 (auto-fit): now also re-runs on heatmapRamp/heightColumn changes, but its `layerCountChanged` gate immediately returns. Net: harmless extra effect runs, but the dependency array misleads readers about what the effect responds to.

This is a code-quality hazard, not a bug. A future maintainer reading the auto-fit effect might assume heatmapRamp changes should trigger a re-fit (they shouldn't — fit is purely a layer-count concern). The `structuralKey` name itself implies "all structural concerns," which is now slightly overstated.

**Fix:** Either split the key, or rename + document:

```typescript
// Option A: split. Auto-fit needs only id/visibility; popup needs the full key.
const fitKey = useMemo(
  () => layers.map((l) => `${l.id}:${l.visible}`).join(','),
  [layers],
);
const structuralKey = useMemo(/* ... full key as today ... */, [layers]);

useEffect(() => { setPopupInfo(null); }, [structuralKey]);
useEffect(() => { /* auto-fit */ }, [layers.length, fitKey, mapReady]);

// Option B: rename to `popupInvalidationKey` and remove from auto-fit deps.
```

Option B is the lower-churn path since the auto-fit effect already short-circuits on no-layer-count-change.

---

### IN-02: CR-04 fix has no direct unit test (critical-tier behavior unprotected)

**File:** `frontend/src/components/builder/layer-adapters/heatmap-adapter.ts:50-51`

**Issue:** CR-04 was a BLOCKER-tier visual-flash defect (heatmap-opacity overwritten on every add). The fix correctly mirrors the syncPaint compounding formula at add-time, but there is no unit test that asserts the formula. `renderAs.test.ts:226-239` asserts the *initial patch* contains `'heatmap-opacity': 0.8` but does not exercise the adapter's `addLayers` runtime path nor the compounding behavior.

A regression that re-introduces `(opacity ?? 1) * 0.8` (the original buggy formula) would not fail any test. Given that this exact bug was introduced once and only caught by adversarial review, asserting the formula in code is appropriate insurance.

**Fix:** Add a focused test against the adapter:

```typescript
// In a new heatmap-adapter.test.ts or appended to renderAs.test.ts:
it('Phase 1051 CR-04: addLayers compounds stored heatmap-opacity with master opacity', () => {
  const mockMap = createMockMap();
  const addLayerSpy = vi.spyOn(mockMap, 'addLayer');

  heatmapAdapter.addLayers(mockMap, {
    layerId: 'l1',
    sourceId: 's1',
    sourceLayer: 'sl1',
    sourceType: 'vector',
    paint: { 'heatmap-opacity': 0.5 },
    opacity: 0.6,
    visible: true,
    filter: null,
    style_config: { render_mode: 'heatmap' },
  });

  const passedPaint = addLayerSpy.mock.calls[0][0].paint as Record<string, number>;
  expect(passedPaint['heatmap-opacity']).toBeCloseTo(0.5 * 0.6, 4);
});
```

This makes the compounding contract a first-class assertion and protects against a re-introduction of the buggy formula.

---

_Reviewed: 2026-05-18T13:50:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Iteration: 2 (--auto fix loop re-review)_
