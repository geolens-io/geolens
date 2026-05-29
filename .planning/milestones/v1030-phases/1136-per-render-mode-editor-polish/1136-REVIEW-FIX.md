---
phase: 1136-per-render-mode-editor-polish
fixed_at: 2026-05-27T17:51:00Z
review_path: .planning/phases/1136-per-render-mode-editor-polish/1136-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 1136: Code Review Fix Report

**Fixed at:** 2026-05-27T17:51:00Z
**Source review:** .planning/phases/1136-per-render-mode-editor-polish/1136-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5
- Fixed: 5
- Skipped: 0

## Fixed Issues

### CR-01: `syncPaint` with empty `input.layout` silently clears `addLayers` `line-cap`/`line-join` defaults

**Files modified:** `frontend/src/components/builder/layer-adapters/line-adapter.ts`
**Commit:** f339bc88
**Applied fix:** Added `clearMissing: false` to the `syncOwnedLayoutProperties` call at `syncPaint` (line 229).
With `clearMissing: true` (the default), any property absent from `input.layout` would cause
`setLayoutProperty(id, prop, undefined)` to fire when the map already had a non-undefined value
(e.g. `'round'` set by `addLayers`). `clearMissing: false` skips that branch entirely — stored
values are reconciled onto the map when present, but absent values leave the map's current state
untouched. Added an explanatory comment documenting why `clearMissing: false` is the correct
semantic here.

---

### WR-01: `line-adapter.test.ts` mock hides the CR-01 production bug

**Files modified:** `frontend/src/components/builder/layer-adapters/__tests__/line-adapter.test.ts`
**Commit:** 19e08a68
**Applied fix:** Added a new test `'does NOT reset line-cap / line-join when layout is empty but map
already has "round" (CR-01 pin)'` inside the existing `syncOwnedLayoutProperties` describe block.
The test overrides `getLayoutProperty` to return `'round'` for both `line-cap` and `line-join` (simulating
post-`addLayers` map state), calls `syncPaint` with `layout: {}`, then asserts that no
`setLayoutProperty(..., undefined)` calls fire for those properties. The test passes with the
CR-01 fix in place and would fail without it.

---

### WR-02: `BasemapGroupEditorScene` renders SUBLAYERS section header and hint when `sublayers` is empty

**Files modified:** `frontend/src/components/builder/BasemapGroupEditorScene.tsx`
**Commit:** 239251b1
**Applied fix:** Wrapped the entire SUBLAYERS `<section>` element (lines 149–243) in a
`{sublayers.length > 0 && ( ... )}` conditional. When the blank basemap is active or the basemap
data has not yet loaded, the section heading, hint text, and empty `<ul>` are no longer rendered.

---

### IN-01: `deriveExtrusionRange` has no regression pin for genuinely non-parseable string inputs

**Files modified:** `frontend/src/components/builder/LayerStyleEditor/__tests__/FillEditor.test.tsx`
**Commit:** a669347b
**Applied fix:** Added test `'hides range hint when all sample values are non-parseable strings
(IN-01 pin)'`. Unlike the existing test which uses numeric strings `['39009', '39004']` and bypasses
`deriveExtrusionRange` entirely (via `numericColumns: []` / `currentHeightCol: ''`), this test passes
`numericColumns` and `currentHeightCol` both set so the function is actually exercised with
`['abc', 'xyz', 'n/a']`. Confirms `Number.isFinite` filtering produces no valid range and suppresses
the range hint correctly.

---

### IN-02: `BasemapGroupEditorScene` does not filter `BLANK_BASEMAP_ID` from the `presets` prop

**Files modified:** `frontend/src/pages/MapBuilderPage.tsx`
**Commit:** 60ec39b0
**Applied fix:** Added `BLANK_BASEMAP_ID` to the import from `@/lib/basemap-utils` and changed the
`presets` array construction at line 868 to `.filter((b) => b.id !== BLANK_BASEMAP_ID).map(...)`.
This prevents a hypothetical duplicate card if an admin ever creates a basemap entry with `id: 'blank'`
in the catalog. Added a comment explaining the rationale at the call site.

---

_Fixed: 2026-05-27T17:51:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
