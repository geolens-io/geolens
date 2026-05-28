---
phase: 1136-per-render-mode-editor-polish
reviewed: 2026-05-27T00:00:00Z
depth: deep
files_reviewed: 6
files_reviewed_list:
  - frontend/src/components/builder/layer-adapters/raster-adapter.ts
  - frontend/src/components/builder/layer-adapters/line-adapter.ts
  - frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/LineEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/FillEditor.tsx
  - frontend/src/components/builder/BasemapGroupEditorScene.tsx
findings:
  critical: 1
  warning: 2
  info: 2
  total: 5
status: issues_found
---

# Phase 1136: Code Review Report

**Reviewed:** 2026-05-27
**Depth:** deep
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Phase 1136 adds raster paint sliders (RasterEditor), line-cap/join selects (LineEditor), a
`parseFloat` coercion fix for `deriveExtrusionRange` (FillEditor), and a "No basemap" preset
card (BasemapGroupEditorScene). Most of the implementation is correct. The `RASTER_OWNED_PAINT_PROPERTIES`
export, coalesceFrame keying, Reset path, and `deriveExtrusionRange` NaN/Infinity guards are all solid.

One blocker exists: the `syncOwnedLayoutProperties` call added to `lineAdapter.syncPaint` uses
`clearMissing: true` (the default), which silently resets `line-cap` and `line-join` from the
`addLayers`-hardcoded `'round'`/`'round'` defaults back to MapLibre's spec defaults (`'butt'`/`'miter'`)
whenever `input.layout` does not carry those keys. This affects all pre-existing line layers that
never had `line-cap`/`line-join` explicitly saved, AND any live layer after a user changes Cap without
also having Join stored. The existing test (line-adapter.test.ts:113) passes only because the mock's
`getLayoutProperty` returns `undefined`; in production the map returns `'round'` after `addLayers`,
triggering the clear path.

Two warnings round out the findings: the test mock gap that hides the production bug, and the
`BasemapGroupEditorScene` rendering the SUBLAYERS section header/hint with an empty list when
`sublayers=[]`. Both are exploitable production surfaces.

---

## Critical Issues

### CR-01: `syncPaint` with empty `input.layout` silently clears `addLayers` `line-cap`/`line-join` defaults

**File:** `frontend/src/components/builder/layer-adapters/line-adapter.ts:224`

**Issue:** `syncPaint` passes `(input.layout ?? {})` to `syncOwnedLayoutProperties` with the default
`clearMissing: true`. When `input.layout` does not contain `line-cap` or `line-join` (true for all
pre-1136 maps and for any edit where the user did not explicitly set those properties), the following
path fires:

```
hasDesired = false   // prop not in layout
clearMissing = true  // default
current = map.getLayoutProperty(layerId, 'line-cap') → 'round'   // set by addLayers
// NOT undefined → the early-exit guard does not apply
→ map.setLayoutProperty(layerId, 'line-cap', undefined)           // RESETS to MapLibre spec default 'butt'
→ map.setLayoutProperty(layerId, 'line-join', undefined)          // RESETS to MapLibre spec default 'miter'
```

`addLayers` hardcodes `'line-cap': 'round'` and `'line-join': 'round'` (line-adapter.ts:194-195).
After `syncPaint`, those values are silently reverted to `'butt'` and `'miter'`. This affects:

1. **All pre-1136 line layers on reload** — they load with `'round'`/`'round'` from `addLayers`, then
   `syncPaint` immediately clears them to `'butt'`/`'miter'` on the first map-sync cycle.
2. **Live sessions when Cap is changed without a stored Join** — `onLayoutChange` is called with
   `{ ...(layer.layout ?? {}), 'line-cap': val }`. If `'line-join'` was never saved, it is absent
   from the new layout object, triggering `setLayoutProperty('line-join', undefined)`, resetting the
   map's join style while the Select still shows `'round'` (via the `?? 'round'` fallback).

The consequence for users: rounded line caps/joins drawn correctly before edit are replaced with butt
caps and miter joins after the first paint sync or Cap-select interaction.

**Fix:** Pass `clearMissing: false` on this call so that properties absent from the stored layout are
left at their current map state (the `addLayers` defaults remain intact):

```typescript
// line-adapter.ts:224
syncOwnedLayoutProperties(map, layerId, (input.layout ?? {}) as Record<string, unknown>, {
  ownedProperties: LINE_OWNED_LAYOUT_PROPERTIES,
  clearMissing: false,   // ← add this
});
```

`clearMissing: false` is the correct semantic here: `syncOwnedLayoutProperties` should reconcile
*stored* cap/join values onto the map when present, but must leave the map's existing value
untouched when the user has not explicitly chosen a value. This matches how `syncOwnedPaintProperties`
is called with `clearMissing: false` for paint properties in other adapters where adapter-level
defaults are authoritative.

---

## Warnings

### WR-01: `line-adapter.test.ts` mock hides the CR-01 production bug

**File:** `frontend/src/components/builder/layer-adapters/__tests__/line-adapter.test.ts:113-124`

**Issue:** The test "does NOT call setLayoutProperty for line-cap or line-join when input.layout is
empty" passes only because `createMockMap` returns `undefined` from `getLayoutProperty`. In production,
after `addLayers` sets `'line-cap': 'round'`, `getLayoutProperty` returns `'round'` (not `undefined`),
which bypasses the early-exit guard and triggers `setLayoutProperty('line-cap', undefined)`. The test
correctly documents the intended behaviour but the mock does not simulate the post-`addLayers` state,
so the bug is invisible in CI.

**Fix:** Add a complementary test that pre-seeds the layout state to simulate the post-`addLayers`
condition, and assert that `setLayoutProperty` is NOT called for cap/join when the mock returns their
current `'round'` values:

```typescript
it('does NOT reset line-cap / line-join when layout is empty but map already has "round" (CR-01 pin)', () => {
  const map = createMockMap({ layerExists: true });
  // Simulate post-addLayers state: map has both properties set to 'round'
  map.getLayoutProperty.mockImplementation((_id: string, prop: string) => {
    if (prop === 'line-cap' || prop === 'line-join') return 'round';
    return undefined;
  });
  lineAdapter.syncPaint(
    map as unknown as import('maplibre-gl').Map,
    makeInput({ layout: {} }),
  );
  const capResets = map.setLayoutProperty.mock.calls.filter(
    ([, prop, val]) => (prop === 'line-cap' || prop === 'line-join') && val === undefined,
  );
  expect(capResets).toHaveLength(0);
});
```

This test will FAIL until `clearMissing: false` is applied (CR-01 fix), providing the regression pin
the test suite currently lacks.

---

### WR-02: `BasemapGroupEditorScene` renders SUBLAYERS section header and hint when `sublayers` is empty

**File:** `frontend/src/components/builder/BasemapGroupEditorScene.tsx:148-241`

**Issue:** The SUBLAYERS section (heading + helper text + `<ul>`) renders unconditionally regardless
of `sublayers.length`. When `sublayers` is `[]` (blank basemap is active, or basemap data has not yet
loaded), the UI shows a "SUBLAYERS" heading, the "Click any sublayer in the sidebar…" hint, and an
empty list box — with no content inside. This presents confusing empty UI to users who select "No
basemap" from the preset grid (which triggers `onSwapBasemap(BLANK_BASEMAP_ID)`, at which point the
basemap has no sublayers).

**Fix:** Gate the entire section on a non-empty `sublayers` array:

```tsx
{sublayers.length > 0 && (
  <section className="border-b">
    {/* ... existing sublayers content ... */}
  </section>
)}
```

---

## Info

### IN-01: `deriveExtrusionRange` has no regression pin for genuinely non-parseable string inputs

**File:** `frontend/src/components/builder/LayerStyleEditor/__tests__/FillEditor.test.tsx:324-342`

**Issue:** The test labelled "hides range hint when all string values are non-numeric" uses `fcode`
values `['39009', '39004']`, which are actually parseable as integers by `parseFloat`. The test
hides the range because `numericColumns=[]` and `currentHeightCol=''` bypass `deriveExtrusionRange`
entirely — the function is never called. There is no test that directly calls `deriveExtrusionRange`
(or reaches it via the component) with inputs like `['abc', 'xyz']`, `[null, undefined]`, or `[{}]`.
The implementation correctly handles all these via the `Number.isFinite` filter, but the test comment
misrepresents what is actually being tested.

**Fix:** Add a test that passes genuinely non-parseable values through the component with a numeric
column and `currentHeightCol` set, confirming the range hint is suppressed:

```tsx
it('hides range hint when all sample values are non-parseable strings', () => {
  const layer = makeFillLayer({
    dataset_column_info: [{ name: 'label', type: 'character varying' }],
    dataset_sample_values: { label: ['abc', 'xyz', 'n/a'] as unknown as number[] },
  });
  render(
    <FillEditor
      {...makeProps(layer, {
        numericColumns: [{ name: 'label', type: 'character varying' }],
        currentHeightCol: 'label',
        isPolygon: true,
      })}
    />,
  );
  expect(screen.queryByText(/Range:/)).not.toBeInTheDocument();
});
```

---

### IN-02: `BasemapGroupEditorScene` does not filter `BLANK_BASEMAP_ID` from the `presets` prop

**File:** `frontend/src/pages/MapBuilderPage.tsx:864-869`

**Issue:** The `presets` array passed to `BasemapGroupEditorScene` is built by mapping the entire
`basemaps` API response without filtering `BLANK_BASEMAP_ID`. The component renders `BLANK_BASEMAP_ID`
as a dedicated hardcoded card before the `presets.map()` loop. If an admin ever configures a basemap
entry with `id: 'blank'` in the admin panel, that entry would appear twice in the preset grid —
once as the hardcoded "No basemap" card and again as a regular preset tile.

The backend default list does not include `'blank'`, so this is not a current production risk. But
the component's contract does not document that `BLANK_BASEMAP_ID` must be absent from `presets`.

**Fix:** Either filter at the call site or add a defensive filter inside `BasemapGroupEditorScene`:

```typescript
// MapBuilderPage.tsx:864
const presets = basemaps
  .filter((b) => b.id !== BLANK_BASEMAP_ID)
  .map((b) => ({ id: b.id, name: b.label, provider: '' }));
```

---

_Reviewed: 2026-05-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
