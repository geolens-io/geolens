---
phase: 1134-map-functionality-and-smaller-screen-polish
fixed_at: 2026-05-27T13:35:00Z
review_path: .planning/phases/1134-map-functionality-and-smaller-screen-polish/1134-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 1134: Code Review Fix Report

**Fixed at:** 2026-05-27T13:35:00Z
**Source review:** .planning/phases/1134-map-functionality-and-smaller-screen-polish/1134-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4
- Fixed: 4
- Skipped: 0

## Fixed Issues

### WR-01: `pointer-events-none` blocks scroll on the overflowing chip container

**Files modified:** `frontend/src/components/builder/ActiveFilterChips.tsx`, `frontend/src/components/builder/__tests__/ActiveFilterChips.test.tsx`
**Commits:** `5811aaea` (source fix), `9b157580` (test update)
**Applied fix:** Split the single `<div className="... pointer-events-none overflow-y-auto max-h-[40vh]">` into two levels: outer `<div className="pointer-events-none">` for map drag passthrough, and inner `<div className="pointer-events-auto flex flex-wrap gap-1.5 max-h-[40vh] overflow-y-auto">` for scrollable surface. Removed `pointer-events-auto` from individual `<span>` chips (parent now has it). Updated the MAP-20 regression test to assert the new two-level structure (outer wrapper has only `pointer-events-none`; inner scroll container has `pointer-events-auto` + scroll classes).

---

### WR-02: `summarizeFilter` crashes on malformed `["literal", <non-array>]`

**Files modified:** `frontend/src/components/builder/ActiveFilterChips.tsx`
**Commit:** `10661519`
**Applied fix:** Added `Array.isArray(raw)` guard before casting `filter[2][1]` as `unknown[]` in the `"in"/"literal"` branch. Malformed filters with a null or absent second element (`["literal", null]` or `["literal"]`) now return the safe summary `"${field} in (…)"` instead of throwing `TypeError: Cannot read properties of null (reading 'slice')` at render time.

---

### WR-03: `deriveCompanionIds` missing regression pin for `'arrow'` render mode

**Files modified:** `frontend/src/components/builder/hooks/__tests__/builder-layer-mutations.test.ts`, `frontend/src/components/builder/hooks/builder-layer-mutations.ts`
**Commit:** `4d93b96d`
**Applied fix:** Added Test 3c to the MAP-17 describe block asserting that `render_mode: 'arrow'` correctly falls through to the FALLBACK_SUFFIXES sweep (7 `removeLayer` calls, including `layer-l1-arrow`). Also added a JSDoc block on `deriveCompanionIds` documenting that `'arrow'` is a known render_mode not in the registry and that its companion is covered by the fallback suffix list, with a pointer to Test 3c.

---

### IN-01: `normalizeRasterBounds` called twice on the truthy-check hot path

**Files modified:** `frontend/src/components/builder/layer-adapters/raster-adapter.ts`
**Commit:** `6ebf88da`
**Applied fix:** Assigned `normalizeRasterBounds(bounds)` to a `const normalizedBounds` local variable before `map.addSource()`, then used `normalizedBounds` in the spread ternary. No behavior change — purely cosmetic clarity improvement so a reader cannot assume the two calls could return different values.

---

_Fixed: 2026-05-27T13:35:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
