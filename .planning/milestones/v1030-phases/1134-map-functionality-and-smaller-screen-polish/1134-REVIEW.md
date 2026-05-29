---
phase: 1134-map-functionality-and-smaller-screen-polish
reviewed: 2026-05-27T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - frontend/src/components/builder/ActiveFilterChips.tsx
  - frontend/src/components/builder/BuilderRail.tsx
  - frontend/src/components/builder/hooks/builder-layer-mutations.ts
  - frontend/src/components/builder/layer-adapters/raster-adapter.ts
  - frontend/src/components/builder/layer-adapters/symbol-adapter.ts
  - frontend/src/pages/MapBuilderPage.tsx
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
findings:
  critical: 0
  warning: 3
  info: 1
  total: 4
status: issues_found
---

# Phase 1134: Code Review Report

**Reviewed:** 2026-05-27
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Phase 1134 is a targeted polish pass — overflow scroll cap on filter chips, Notes presence dot on rail + mobile, raster split-guard, and symbol-adapter `syncLayerFilter` migration. The architecture is sound and test coverage is solid (new tests pin every changed behavior). No critical issues were found. Three warnings are raised: a functional scroll-blocking pattern in the filter chip container, a crash risk in the `summarizeFilter` `"literal"` branch when the filter value is malformed, and a future-facing companion-removal gap for the `'arrow'` render mode. A minor code quality note on `normalizeRasterBounds` double-call is also included.

---

## Warnings

### WR-01: `pointer-events-none` blocks scroll on the overflowing chip container

**File:** `frontend/src/components/builder/ActiveFilterChips.tsx:124`

**Issue:** The outer wrapper has both `overflow-y-auto` and `pointer-events-none`. `pointer-events: none` on a scrollable container suppresses the wheel/touch-scroll events the browser needs to scroll that container. Children restore `pointer-events-auto` for click targets, but the scroll gutter between chips — and any empty space inside the container — is not pointer-interactive. When the chip list exceeds 40 vh (i.e. the cap is actually needed), users cannot scroll the container to reach or clear chips near the bottom. The cap fires exactly when it matters most and simultaneously makes the overflow unreachable.

The intent of `pointer-events-none` is to let map drag/zoom events pass through to the canvas behind the widget host. The right fix is to keep `pointer-events-none` on the parent but restore it on the scrollable container itself, not just on individual chips.

**Fix:**
```tsx
// Before:
<div className="flex flex-wrap gap-1.5 max-h-[40vh] overflow-y-auto pointer-events-none">

// After: restore pointer-events on the scroll container so wheel/touch-scroll works,
// while keeping the map canvas reachable in the gaps between chips.
<div className="flex flex-wrap gap-1.5 max-h-[40vh] overflow-y-auto pointer-events-auto">
  {chips.map((chip) => (
    <span
      ...
      className="... /* remove pointer-events-auto from here since the parent now has it */"
    >
```

Alternatively, if the map-passthrough goal requires `pointer-events-none` on the wrapper, remove `overflow-y-auto` and `max-h-[40vh]` from the wrapper and apply them to an inner scroll container that itself has `pointer-events-auto`:
```tsx
<div className="pointer-events-none">          {/* passthrough wrapper */}
  <div className="pointer-events-auto flex flex-wrap gap-1.5 max-h-[40vh] overflow-y-auto">
    {chips.map(...)}
  </div>
</div>
```

---

### WR-02: `summarizeFilter` crashes on malformed `["literal", <non-array>]` — unguarded `.slice()`

**File:** `frontend/src/components/builder/ActiveFilterChips.tsx:57-58`

**Issue:** In the `"in"` expression branch, once `filter[2][0] === 'literal'` is confirmed, `filter[2][1]` is immediately cast as `unknown[]` and `.slice(0, 2)` is called. There is no `Array.isArray(filter[2][1])` guard. A filter of `["in", ["get", "field"], ["literal", null]]` or `["in", ["get", "field"], ["literal"]]` (no value argument) causes `vals` to be `null` or `undefined` respectively, and `vals.slice(...)` throws `TypeError: Cannot read properties of null (reading 'slice')` at render time. This crashes the chip container and (absent an error boundary) could propagate visually. Filters are stored as opaque JSON in the backend and may arrive malformed from older exports or third-party imports.

```tsx
// Current (line 56-59):
if (field && Array.isArray(filter[2]) && filter[2][0] === 'literal') {
  const vals = filter[2][1] as unknown[];
  const preview = vals.slice(0, 2).map(v => String(v)).join(', ');
  return `${field} in (${preview}${vals.length > 2 ? ', …' : ''})`;
}

// Fix: guard filter[2][1] before trusting it as an array
if (field && Array.isArray(filter[2]) && filter[2][0] === 'literal') {
  const raw = filter[2][1];
  if (!Array.isArray(raw)) {
    return `${field} in (…)`;   // degenerate literal — still useful summary, no crash
  }
  const vals = raw as unknown[];
  const preview = vals.slice(0, 2).map(v => String(v)).join(', ');
  return `${field} in (${preview}${vals.length > 2 ? ', …' : ''})`;
}
```

---

### WR-03: `deriveCompanionIds` will silently orphan the `-arrow` companion for `render_mode: 'arrow'` when a future caller passes `renderModeByLayerId`

**File:** `frontend/src/components/builder/hooks/builder-layer-mutations.ts:23-37`

**Issue:** `deriveCompanionIds` looks up the adapter by `renderMode` and uses the result only when `adapter.type === renderMode`. The adapter registry does not contain an `'arrow'` key; `getAdapter('arrow')` returns the `circleAdapter` fallback whose `type === 'circle'`. The `adapter.type === renderMode` guard (`'circle' === 'arrow'`) fails, so the code correctly falls through to the FALLBACK_SUFFIXES path — which does include `-arrow`. This is safe today.

However, the logic is fragile: the safety depends entirely on the fallback path being reached. The comment says "Existing callers that omit `renderModeByLayerId` continue to use the suffix-list fallback". But when a future caller does pass a `renderModeByLayerId` map with `render_mode: 'arrow'`, the code still falls through to the suffix list — which is correct, but not because of explicit intent. There is no test case for `'arrow'` in the new MAP-17 test suite (Test 3b covers `'line'` but not `'arrow'`).

The risk: if someone adds `'arrow'` to the registry as a first-class adapter type (which would map correctly to `lineAdapter`'s `getLayerIds` → `[layerId, arrowLayerId(layerId)]`) or if they add an `'arrow'` adapter with the wrong `getLayerIds`, the behavior changes silently. Currently this is a WARNING because all three production call sites omit `renderModeByLayerId` and are unaffected.

**Fix:** Add a test case for `'arrow'` render mode to the MAP-17 test file, and add a JSDoc note on `deriveCompanionIds` documenting that `'arrow'` is a known render_mode not in the registry and its companion is covered by the fallback suffix list:

```typescript
// In builder-layer-mutations.test.ts — add alongside Test 3b:
it('Test 3c: arrow render mode → falls back to suffix sweep (arrow not in registry)', () => {
  const removeLayer = vi.fn();
  const map = makeMap({ removeLayer });
  const renderModeByLayerId = new Map([['l1', 'arrow']]);

  removePerLayerCompanions(map as never, ['l1'], renderModeByLayerId);

  // 'arrow' is not a registry key → circleAdapter fallback fails the type guard
  // → suffix sweep fires → 7 calls including -arrow companion
  expect(removeLayer).toHaveBeenCalledTimes(7);
  expect(removeLayer).toHaveBeenCalledWith('layer-l1-arrow');
});
```

---

## Info

### IN-01: `normalizeRasterBounds` called twice on the truthy-check hot path

**File:** `frontend/src/components/builder/layer-adapters/raster-adapter.ts:71`

**Issue:** The bounds spread uses a ternary that calls `normalizeRasterBounds(bounds)` twice — once as a truthy predicate and once to get the return value. The function is pure and cheap, so this is not a correctness bug. It is a code clarity issue: a reader might assume the two calls could return different values.

```typescript
// Current (line 71):
...(normalizeRasterBounds(bounds) ? { bounds: normalizeRasterBounds(bounds) } : {}),

// Fix: compute once
const normalizedBounds = normalizeRasterBounds(bounds);
map.addSource(sourceId, {
  type: 'raster',
  tiles: [`${window.location.origin}${tileUrl}`],
  tileSize: tileSize ?? 256,
  minzoom: minzoom ?? 0,
  maxzoom: maxzoom ?? 18,
  ...(normalizedBounds ? { bounds: normalizedBounds } : {}),
});
```

---

## Verified Correct

The following areas were inspected and found sound:

- **`deriveCompanionIds` type guard for `'arrow'`**: correctly falls through to the suffix list (see WR-03 for the survivability caveat).
- **`visible === false` vs `!visible` discrepancy in `raster-adapter.ts:83,86`**: `AdapterLayerInput.visible` is typed `boolean` (not `boolean | null | undefined`), so both forms are equivalent. The asymmetry is cosmetic.
- **BuilderRail `notes.trim().length > 0` presence-dot**: safe — `notes` prop is typed `string` (never null/undefined per `BuilderRailProps`).
- **Mobile Notes dot in `MapBuilderPage.tsx:1346`**: mirrors the rail implementation correctly using `dockNotes.trim().length > 0`.
- **`mt-12` on both SheetContent blocks**: both instances (lines 1265 and 1386) are consistent; both preserve `showCloseButton={false}` per Pitfall #11 contract.
- **i18n `rail.notesPresent` key**: present in all four locales (en/de/es/fr) at line 832 with appropriate translations.
- **`symbolAdapter.syncPaint` `syncLayerFilter` migration**: both `addLayers` and `syncPaint` now route through `syncLayerFilter`, consistent with the fill/line/circle/heatmap adapter shape. Tests 3 and 4 pin the filter/null behavior.
- **FALLBACK_SUFFIXES completeness**: the 7-entry suffix list (`''`, `-outline`, `-label`, `-extrusion`, `-arrow`, `-cluster`, `-cluster-count`) covers all known companion layer patterns. The `-label` suffix is documented in the comment as intentionally included even though labels are managed by `map-sync.ts`.
- **Raster split-guard correctness**: Test 2 (WALK-R-05) correctly validates that source-exists/layer-missing results in `addLayer` being called without `addSource`. The early-return was at the source check; the guard is now correctly split.
- **`BuilderLayerAction` union not widened**: confirmed — no changes to the action union type.
- **NavigationControl placement**: unchanged at `top-left` (Pitfall #10 preserved).

---

_Reviewed: 2026-05-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
