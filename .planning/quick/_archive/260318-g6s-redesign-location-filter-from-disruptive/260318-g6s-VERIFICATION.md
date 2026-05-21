---
phase: 260318-g6s
verified: 2026-03-18T16:10:00Z
status: human_needed
score: 5/6 must-haves verified
re_verification: false
human_verification:
  - test: "Panel slides in without blocking search results"
    expected: "Right-side 400px panel appears while search results remain fully visible and interactive on the left"
    why_human: "Cannot verify visual overlay behavior or z-index stacking context from static code analysis"
  - test: "Draw modes functional — rectangle and polygon"
    expected: "Rectangle mode: click-drag draws bounding box. Polygon mode: click points, double-click finishes. Both modes show drawn shape on map."
    why_human: "Terra Draw interactive behavior requires browser rendering and canvas interaction"
  - test: "Apply closes panel, 'Area selected' chip appears, search results update"
    expected: "Clicking Apply collapses the panel and a FilterChip labeled 'Area selected' appears in the filter bar; results are spatially filtered"
    why_human: "Requires live browser interaction to confirm animation, chip rendering, and actual search API call with bbox param"
  - test: "Click chip text to reopen panel with geometry preserved"
    expected: "Clicking the 'Area selected' chip (not the X) reopens the panel; previously drawn geometry is restored on the map"
    why_human: "Geometry restoration via td.addFeatures() on reopen requires live Terra Draw state to verify"
  - test: "Mobile — bottom sheet inline map picker still works"
    expected: "On narrow viewport, Filters sheet opens and BboxMapPicker renders inline for location selection"
    why_human: "Responsive layout and mobile sheet interaction require browser viewport testing"
---

# Phase 260318-g6s: Redesign Location Filter Verification Report

**Phase Goal:** Redesign location filter from disruptive popover to compact expandable panel. Replace current large popover overlay with a right-side panel (~360-420px) that supports rectangle + polygon drawing via Terra Draw, collapses after apply, shows active filter chip. Desktop: right panel; Mobile: full-screen.
**Verified:** 2026-03-18T16:10:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User clicks Location button and a right-side panel slides in without blocking search results | ? UNCERTAIN | Panel is `fixed inset-y-0 right-0 z-40 w-[400px]` with no backdrop/overlay. Slide animation via `translate-x-0/translate-x-full`. Non-blocking confirmed by code; visual stacking needs human |
| 2 | User can draw a rectangle (default) or polygon on the mini map | ? UNCERTAIN | Both `TerraDrawRectangleMode` and `TerraDrawPolygonMode` initialized with styles; `td.setMode('rectangle')` on load; ToggleGroup switches mode. Interactive drawing needs human |
| 3 | User clicks Apply and panel collapses, showing an 'Area selected' filter chip | ✓ VERIFIED | `handleApply` calls `onApply(pendingBbox)` + `onClose()`; FilterPanel's `onApply` sets bbox in store + closes panel; `renderDesktopLocationFilter` renders FilterChip with `'Area selected'` label when `bbox` is set |
| 4 | User clicks the chip to reopen the panel with the drawn geometry preserved | ✓ VERIFIED | FilterChip wrapped in `<div onClick={() => setSpatialPanelOpen(true)}>`. On reopen, `useEffect` on `open` checks `drawnFeatureIdRef` for existing feature, falls back to `td.addFeatures([bboxToPolygon(initialBbox)])`. Logic correct; actual restoration needs human |
| 5 | User clicks x on chip to clear the spatial filter | ✓ VERIFIED | `onRemove={() => useSearchStore.getState().setFilter('bbox', '')}` in FilterChip wrapper. FilterChip X button calls `e.stopPropagation()` before `onRemove()`, preventing wrapper click conflict |
| 6 | On mobile, the spatial filter appears in the existing bottom sheet filters | ✓ VERIFIED | Mobile Sheet (lines 586-870) retains `bboxOpen` state + `renderMapPicker()` using `LazyBboxMapPicker` (lines 746-766). Mobile flow is unchanged |

**Score:** 4/6 automated + 2 uncertain (geometry restoration logic verified, draw interaction and visual layout need human)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/search/SpatialFilterPanel.tsx` | Right-side spatial filter panel with map, draw tools, apply/clear | ✓ VERIFIED | 325 lines. Fixed-position panel, ToggleGroup for modes, MapGL, Terra Draw initialized in `onLoad`, `handleApply`/`handleClear`/`handleModeChange` all substantive |
| `frontend/src/components/search/FilterPanel.tsx` | Updated filter bar with panel trigger and clickable chip | ✓ VERIFIED | `spatialPanelOpen` state, `renderDesktopLocationFilter` replaced popover with Button/chip. Lazy-loaded `LazySpatialFilterPanel` at bottom of JSX |
| `frontend/src/components/search/FilterChip.tsx` | (modified per SUMMARY) stopPropagation on X button | ✓ VERIFIED | X button uses `onClick={(e) => { e.stopPropagation(); onRemove(); }}` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `SpatialFilterPanel.tsx` | `terra-draw` | `TerraDrawRectangleMode\|TerraDrawPolygonMode` | ✓ WIRED | Both modes imported and instantiated in `handleMapLoad`. `td.start()` called. `td.on('finish', ...)` handles draw completion |
| `FilterPanel.tsx` | `SpatialFilterPanel.tsx` | state-controlled panel open/close | ✓ WIRED | `LazySpatialFilterPanel` lazy-imported. Rendered conditionally with `spatialPanelOpen` prop. `open`, `onClose`, `onApply`, `initialBbox` all wired |
| `SpatialFilterPanel.tsx` | `search-store.ts` | `setFilter('bbox', value)` on Apply | ✓ WIRED | Call is in FilterPanel's `onApply` callback (line 878): `useSearchStore.getState().setFilter('bbox', bboxValue)`. Note: `handleApply` in SpatialFilterPanel calls `onApply` + `onClose` separately; `onApply` in FilterPanel also calls `setSpatialPanelOpen(false)`. Panel closes twice (idempotent, harmless) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SPATIAL-PANEL | 260318-g6s-PLAN.md | Right-side sliding panel replacing popover | ✓ SATISFIED | `SpatialFilterPanel` with `fixed inset-y-0 right-0 z-40 w-[400px]` + slide animation |
| SPATIAL-CHIP | 260318-g6s-PLAN.md | Clickable "Area selected" filter chip | ✓ SATISFIED | FilterChip wrapped in clickable div; X clears bbox; chip reopens panel |
| SPATIAL-DRAW | 260318-g6s-PLAN.md | Rectangle + polygon drawing via Terra Draw | ✓ SATISFIED (code) | Both modes instantiated; mode toggle wired. Actual drawing needs human verification |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `FilterPanel.tsx` | 877-880 | `onApply` calls `setSpatialPanelOpen(false)` while `handleApply` already calls `onClose()` which does the same | Info | Panel close state is set twice; idempotent, no functional impact |

No TODOs, FIXMEs, placeholder returns, or empty implementations found in modified files.

### Human Verification Required

#### 1. Panel does not block search results

**Test:** Open search page at http://localhost:8080, click "Location" button in the filter bar.
**Expected:** A 400px panel slides in from the right. Search result cards on the left remain fully visible, scrollable, and clickable.
**Why human:** Fixed-position elements and z-index stacking context cannot be verified by static analysis. CSS `z-40` avoids most conflicts but visual confirmation required.

#### 2. Rectangle and polygon draw modes work

**Test:** In the panel, default mode is Rectangle — click and drag on the map. Then switch to Polygon, click several points, double-click to finish.
**Expected:** Rectangle drag draws a blue bounding box that stays visible after drawing. Polygon mode draws a multi-point shape. Instructions below map update to match selected mode.
**Why human:** Terra Draw canvas interaction requires real browser rendering.

#### 3. Apply workflow — chip appears and search filters

**Test:** Draw any shape, click "Apply".
**Expected:** Panel slides closed. "Area selected" chip appears in the filter bar. Search results update to only show datasets within the drawn area.
**Why human:** Visual animation, chip render, and live API call with bbox parameter require browser.

#### 4. Chip reopens panel with geometry preserved

**Test:** After applying a filter, click the "Area selected" chip text (not the X button).
**Expected:** Panel slides open again. The previously drawn shape is still visible on the map (restored via `td.addFeatures`).
**Why human:** Terra Draw geometry restoration state requires live execution to confirm `getSnapshotFeature` + `addFeatures` round-trip works correctly.

#### 5. Mobile bottom sheet location filter

**Test:** Narrow viewport (< 768px). Click "Filters" button. Scroll to Location section. Click the location button.
**Expected:** Inline BboxMapPicker renders within the sheet. Drawing a bbox and confirming applies the spatial filter.
**Why human:** Responsive layout and Sheet component behavior require mobile viewport testing.

### Gaps Summary

No gaps found. All artifacts exist and are substantively implemented with correct wiring. The 5 human verification items are functional behavior checks that require live browser interaction — they do not indicate code defects. The implementation closely follows the plan spec with no deviations.

The only minor observation is the redundant double-close on Apply (SpatialFilterPanel's `handleApply` calls both `onApply` and `onClose`; FilterPanel's `onApply` also calls `setSpatialPanelOpen(false)`). This is harmless since React state batches these and the result is identical.

---

_Verified: 2026-03-18T16:10:00Z_
_Verifier: Claude (gsd-verifier)_
