---
phase: 260424-lqy
verified: 2026-04-24T16:14:30Z
status: gaps_found
score: 4/5 must-haves verified
gaps:
  - truth: "All existing BasemapPicker tests pass"
    status: failed
    reason: "4 of 5 tests fail. The CSS grid-rows animation wrapper keeps all grid options permanently in the DOM, meaning label text and alt text appear twice (once in the header button, once in the collapsed grid). Tests using singular getByText/getByAltText queries throw 'Found multiple elements.' Only the 'uses SVG fallback for unknown basemap IDs' test passes."
    artifacts:
      - path: "frontend/src/components/builder/__tests__/BasemapPicker.test.tsx"
        issue: "Tests 1-4 use getByText('Positron') and getByAltText('Positron') which fail with MultipleElementsFoundError. The plan only updated line 53 (toHaveLength(0) → grid-rows class check) but did not update the other four test queries to handle duplicate text/alt text from the always-in-DOM animation wrapper."
    missing:
      - "Update 'renders collapsed with current basemap label' to use getAllByText('Positron')[0] or scope to the header button"
      - "Update 'uses static PNG for built-in basemap thumbnail' to scope the img query to the header (e.g., within the aria-expanded button)"
      - "Update 'expands grid on click and shows all enabled basemaps' — getByText('Positron') click is ambiguous; scope to the header button"
      - "Update 'calls onChange and closes on basemap selection' — same getByText ambiguity on line 50"
---

# Quick Task 260424-lqy: Basemap Race Fix + Picker UX Polish — Verification Report

**Task Goal:** Fix map builder basemap selector race condition (rapid basemap toggling causes layers to disappear) and polish the basemap picker UX.
**Verified:** 2026-04-24T16:14:30Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|---------|
| 1  | Rapid basemap toggling (4+ switches in <1s) never causes data layers to disappear | VERIFIED | `map.on('style.load', onStyleLoad)` with `[mapReady]` dep at BuilderMap.tsx:220. No `map.once` in the style.load effect. Persistent listener survives any number of rapid style swaps. |
| 2  | Blank basemap produces zero CORS errors in the browser console | VERIFIED | basemap-utils.ts:68 — blank basemap style object has no `glyphs` property. FALLBACK_GLYPHS updated to `tiles.openfreemap.org/fonts/` (line 13). Raster basemap uses FALLBACK_GLYPHS constant (line 95). |
| 3  | Selected basemap shows a visible ring differentiated from the background | VERIFIED | BasemapPicker.tsx:70 — selected button has `ring-2 ring-primary ring-offset-2 ring-offset-background bg-accent`. |
| 4  | Basemap grid expands/collapses with a smooth animation, not an instant toggle | VERIFIED | BasemapPicker.tsx:52-55 — `grid transition-[grid-template-rows] duration-200 ease-out` wrapper, toggling `grid-rows-[1fr]` / `grid-rows-[0fr]`. Options remain in DOM for smooth collapse. |
| 5  | Labels toggle uses the project Switch component, visually consistent with the rest of the UI | VERIFIED | BasemapPicker.tsx:7 imports `Switch` from `@/components/ui/switch`; lines 91-96 render `<Switch size="sm" checked={showLabels} onCheckedChange={onToggleLabels} .../>`. No native `<input type="checkbox">`. |

**Score (truths):** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/builder/BuilderMap.tsx` | Persistent style.load listener (`map.on`) | VERIFIED | Line 220: `map.on('style.load', onStyleLoad)`. Dep array `[mapReady]` only. |
| `frontend/src/lib/basemap-utils.ts` | CORS-safe glyph URL using OpenFreeMap endpoint | VERIFIED | Line 13: `FALLBACK_GLYPHS = 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf'`. Blank basemap omits `glyphs`. Raster uses constant. |
| `frontend/src/components/builder/BasemapPicker.tsx` | Polished picker with animation, ring offset, Switch component | VERIFIED | `grid-rows` transition, `ring-offset-2 ring-offset-background`, `Switch` component all present. |
| `frontend/src/components/builder/__tests__/BasemapPicker.test.tsx` | All tests pass | FAILED | 4 of 5 tests fail — see Gaps Summary. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| BuilderMap.tsx style.load handler | syncLayersToMap | persistent listener reads syncInputsRef.current | WIRED | Lines 210-218: handler destructures syncInputsRef.current and calls syncLayersToMap. |
| basemap-utils.ts FALLBACK_GLYPHS | toMaplibreStyle inline styles | constant reference | WIRED | Line 95: `glyphs: FALLBACK_GLYPHS` in raster branch. Blank branch omits glyphs entirely. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `BuilderMap.tsx` | 203 | Comment references removed `map.once()` approach | Info | Accurate historical comment, not a code smell. |

### Behavioral Spot-Checks

Step 7b: SKIPPED — changes are UI and style-switching logic; no runnable entry points to test without a live browser.

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|---------|
| BASEMAP-RACE-FIX | Fix race condition where rapid basemap toggling drops data layers | SATISFIED | Persistent `map.on` listener with `[mapReady]` dep; no per-switch teardown. |
| BASEMAP-UX-POLISH | Polished basemap picker (animation, ring offset, Switch toggle) | SATISFIED | All three UX improvements present in BasemapPicker.tsx. |

### Human Verification Required

1. **Rapid basemap toggling in browser**
   - Test: Open map builder with 2+ data layers. Click 5 different basemaps in under 1 second.
   - Expected: All data layers remain visible after final basemap loads.
   - Why human: Requires a live browser + actual MapLibre map event timing.

2. **Blank basemap CORS check**
   - Test: Switch to blank basemap and open browser DevTools Network tab.
   - Expected: Zero requests to any glyph URL; no CORS errors in console.
   - Why human: CORS errors only appear at runtime in a real browser.

3. **Grid animation smoothness**
   - Test: Click the basemap picker header to expand/collapse repeatedly.
   - Expected: Smooth 200ms slide animation, not an instant show/hide.
   - Why human: CSS animation quality cannot be verified programmatically.

## Gaps Summary

The three source files (BuilderMap.tsx, basemap-utils.ts, BasemapPicker.tsx) are correctly implemented — all five observable truths are met in the code. The single gap is in the test file.

**Root cause:** The plan's animation wrapper (CSS `grid-rows-[0fr]`/`grid-rows-[1fr]`) keeps all basemap option buttons permanently in the DOM. This means both the header button and the hidden grid contain "Positron" text and a `Positron` alt-tagged image. The plan identified and fixed only one broken assertion (line 53 `toHaveLength(0)`), but did not update four other `getByText`/`getByAltText` singular queries that also break from the same DOM duplication. Running the test suite confirms: 4 of 5 tests fail with `Found multiple elements with the text: Positron` / `Found multiple elements with the alt text: Positron`.

The fix is straightforward: scope the header-button queries by `aria-label` or use `getAllByText` with index 0, or scope with `within()`.

---

_Verified: 2026-04-24T16:14:30Z_
_Verifier: Claude (gsd-verifier)_
