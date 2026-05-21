---
phase: 260329-p4p
plan: 01
subsystem: frontend/builder
tags: [basemap, thumbnails, static-assets, ui]
dependency_graph:
  requires: []
  provides: [static-basemap-thumbnails]
  affects: [frontend/src/components/builder/BasemapPicker.tsx]
tech_stack:
  added: []
  patterns: [vite-static-imports, imagemagick-asset-generation]
key_files:
  created:
    - frontend/src/assets/basemaps/positron.png
    - frontend/src/assets/basemaps/dark.png
    - frontend/src/assets/basemaps/osm.png
    - frontend/src/assets/basemaps/bright.png
  modified:
    - frontend/src/components/builder/BasemapPicker.tsx
decisions:
  - "Used ImageMagick to generate map-like placeholder PNGs after WebGL not available in headless Chromium"
  - "Force-added PNGs with git add -f to bypass project-wide *.png gitignore"
  - "Kept osm-standard as alias for openstreetmap in BUILTIN_THUMBNAILS for backward compat"
metrics:
  duration: 15min
  completed: "2026-03-29"
  tasks_completed: 2
  files_changed: 5
---

# Phase 260329-p4p Plan 01: Basemap Thumbnail Replacement Summary

**One-liner:** Replaced inline SVG colored-rectangle basemap thumbnails with static PNG map-like images and a globe SVG fallback, increasing thumbnail size from 24px to 32px.

## What Was Built

Task 1 created 4 static PNG thumbnail assets in `frontend/src/assets/basemaps/`. Each is 320x320px with a recognizable map-like appearance (land/water shapes, grid lines, road traces) using the distinctive color palette of each basemap style:
- **positron.png** (6.7KB): light gray with blue water, green-tinted land
- **dark.png** (6.6KB): dark navy with dark blue ocean, dark green land
- **bright.png** (6.7KB): warm cream with vibrant blue water, bright green land
- **osm.png** (8.4KB): tan/cream with blue water, green parks, orange roads

Task 2 refactored `BasemapPicker.tsx`:
- Replaced `basemapThumbnail()` inline SVG data URIs with Vite static PNG imports
- Added `BUILTIN_THUMBNAILS` lookup map covering all 4 built-in basemap IDs (plus `osm-standard` alias)
- Added globe SVG data URI as `FALLBACK_THUMBNAIL` for custom/unknown basemaps
- Increased collapsed row thumbnail from `w-6 h-6` (24px) to `w-8 h-8` (32px)
- Increased grid gap from `gap-1.5` to `gap-2`

## Deviations from Plan

### Auto-adapted: PNG capture method

**Found during:** Task 1

**Issue:** Playwright headless Chromium could not create a WebGL context (required by MapLibre GL), making it impossible to capture real map screenshots via headless browser. Error: "Failed to initialize WebGL" with SwiftShader fallback also failing.

**Fix:** Used ImageMagick (`magick`) to generate map-like placeholder PNGs with distinct color palettes, coast-like polygon shapes, and grid lines — closely matching the plan's fallback specification. Result is visually distinctive and clearly "map-like" without relying on actual tile rendering.

**Files modified:** `frontend/src/assets/basemaps/*.png`

### Auto-adapted: Git *.png gitignore bypass

**Found during:** Task 1 commit

**Issue:** Project `.gitignore` includes `*.png` globally, so the new assets were invisible to git status.

**Fix:** Used `git add -f` to force-add the intentional PNG assets. This is the correct approach for deliberately-tracked binary assets that would otherwise be caught by a broad gitignore rule.

## Commits

- `eb2d7f7b`: feat(260329-p4p): add static basemap thumbnail PNG assets
- `29ab92dd`: feat(260329-p4p): refactor BasemapPicker to use static PNG thumbnails

## Known Stubs

None — all 4 built-in basemap IDs are wired to PNG imports. The fallback globe SVG is intentional behavior for custom basemaps.

## Self-Check: PASSED

- frontend/src/assets/basemaps/positron.png: FOUND
- frontend/src/assets/basemaps/dark.png: FOUND
- frontend/src/assets/basemaps/osm.png: FOUND
- frontend/src/assets/basemaps/bright.png: FOUND
- frontend/src/components/builder/BasemapPicker.tsx: FOUND (modified)
- Commit eb2d7f7b: FOUND
- Commit 29ab92dd: FOUND
- TypeScript: PASSED (npx tsc --noEmit, no errors)
- Tests: PASSED (84 test files, 801 tests)
