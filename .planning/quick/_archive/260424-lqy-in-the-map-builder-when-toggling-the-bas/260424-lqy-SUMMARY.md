---
phase: 260424-lqy
plan: 01
subsystem: frontend/builder
tags: [basemap, race-condition, cors, ux, animation]
dependency_graph:
  requires: []
  provides: [stable-basemap-switching, cors-safe-glyphs, basemap-picker-ux]
  affects: [BuilderMap, BasemapPicker, basemap-utils]
tech_stack:
  added: []
  patterns: [persistent-map-event-listener, css-grid-rows-animation]
key_files:
  modified:
    - frontend/src/components/builder/BuilderMap.tsx
    - frontend/src/lib/basemap-utils.ts
    - frontend/src/components/builder/BasemapPicker.tsx
    - frontend/src/components/builder/__tests__/BasemapPicker.test.tsx
decisions:
  - Persistent map.on listener keyed on [mapReady] — single registration survives all rapid style swaps
  - Blank basemap omits glyphs property entirely — zero symbol layers means zero glyph fetches
  - CSS grid-rows-[0fr]/[1fr] transition for expand animation — keeps options in DOM for smooth collapse
metrics:
  duration: ~4 minutes
  completed: 2026-04-24
---

# Quick Task 260424-lqy: Basemap Race Fix + Picker UX Polish Summary

**One-liner:** Persistent `map.on('style.load')` listener + OpenFreeMap glyphs + CSS grid-rows animation + Switch toggle for the basemap picker.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix race condition and CORS glyphs | cc5304ac | BuilderMap.tsx, basemap-utils.ts |
| 2 | Polish BasemapPicker UX | 04971ea0 | BasemapPicker.tsx, BasemapPicker.test.tsx |

## What Was Done

### Task 1: Race condition + CORS glyphs

**BuilderMap.tsx** — Replaced the `map.once('style.load')` approach (which re-registered a one-shot listener on every `basemapEntry?.url` change) with a persistent `map.on('style.load')` listener keyed on `[mapReady]` only. The old approach had a race: rapid basemap switches triggered cleanup before the one-shot fired, leaving no listener to re-add data layers. The persistent listener registers once when the map mounts and handles all subsequent style loads — no teardown/re-register per switch. Also resets `lastOrderKeyRef` to `''` on each `style.load` so layer order is fully re-applied. Removed `prevBasemapUrlRef` (guard no longer needed) and the `isStyleLoaded()` synchronous fallback (persistent listener is always registered before any switch).

**basemap-utils.ts** — Updated `FALLBACK_GLYPHS` from `demotiles.maplibre.org` (CORS-blocked) to `tiles.openfreemap.org/fonts/` (CORS-safe). Removed `glyphs` property from the blank basemap style object entirely — the blank style has no symbol/text layers so it never needs glyphs; omitting prevents any glyph fetch attempt. Replaced the hardcoded duplicate URL in the raster basemap branch with the `FALLBACK_GLYPHS` constant.

### Task 2: BasemapPicker UX

- **Expand animation:** Replaced `{open && (...)}` conditional with a CSS `grid-rows-[0fr]`/`grid-rows-[1fr]` transition wrapper — options stay in the DOM, animate smoothly in 200ms. The inner `overflow-hidden` div clips content during collapse.
- **Selected ring offset:** Added `ring-offset-2 ring-offset-background` to selected button — creates visible separation between ring and thumbnail, theme-aware.
- **Thumbnail height cap:** Added `max-h-14` to grid thumbnail `<img>` to prevent oversized images on wide sidebars.
- **Switch component:** Replaced native `<input type="checkbox">` with `<Switch size="sm">` from `@/components/ui/switch`. Removed the wrapping `<div role="group">` (single control, Switch carries its own `aria-label`).
- **Test update:** The "calls onChange and closes" test previously asserted `toHaveLength(0)` after closing — now options remain in DOM. Updated to assert the animation wrapper has `grid-rows-[0fr]` class instead.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `cc5304ac` exists: confirmed (`git log`)
- `04971ea0` exists: confirmed (`git log`)
- `BuilderMap.tsx` has `map.on('style.load'` and no `map.once`, no `prevBasemapUrlRef`
- `basemap-utils.ts` has `tiles.openfreemap.org/fonts/`, no `glyphs` on blank basemap
- `BasemapPicker.tsx` has `grid-rows`, `Switch`, `ring-offset-2`
- All 5 BasemapPicker tests pass
