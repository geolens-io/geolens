# Quick Task 260326-8ea: Fix map console errors (outline-width) — Summary

**Completed:** 2026-03-26
**Commits:** e1c37c3d, e251e811, 181753d6

## Root Cause

Commit `d2f1b93f` (Mar 25) renamed custom paint props from `outline-width` → `_outline-width` across frontend/backend code but did not include a DB migration. Maps styled before the rename still had `outline-width` in their paint JSON, which `stripCustomProps` didn't filter out, causing MapLibre `addLayer()` to reject the unknown property. The failure cascaded to `finalizeLayer` calls on the non-existing layer.

## Changes

### Task 1: map-sync.ts hardening
- Added `outline-width` and `outline-color` (non-prefixed) to `CUSTOM_PAINT_PROPS`
- Wrapped all three geometry branch `addLayer` calls in try-catch with `console.warn`
- Added fallback reads for non-prefixed outline props in outline layer creation
- Updated `use-builder-layers.ts` with same fallback reads for live sync

### Task 2: ViewerMap.tsx fix
- Imported and applied `stripCustomProps` to all three geometry type `addLayer` paint args
- Added try-catch around all `addLayer` calls
- Added fallback reads for non-prefixed outline props

### Task 3: Alembic migration
- Created `0008_normalize_outline_paint.py` migration
- Renames `outline-width` → `_outline-width` and `outline-color` → `_outline-color` in `catalog.map_layers.paint` JSONB
- Handles collision case (both forms present — removes non-prefixed)
- Downgrade reverses the rename

## Verification

- Playwright: 0 console errors on affected map page (previously 3 errors + 3 warnings)
- TypeScript: clean compile
- Verifier: 4/4 must-haves passed
