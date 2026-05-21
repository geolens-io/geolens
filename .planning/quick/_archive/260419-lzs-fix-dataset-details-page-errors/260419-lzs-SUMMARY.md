---
status: complete
---

# Quick Task 260419-lzs: Fix dataset details page errors

## Changes

### 1. Keywords 404 (OverviewTab.tsx)
`KeywordsSidebarCard` passed `dataset.id` to `useKeywords()`, but the backend `/records/{record_id}/keywords/` endpoint expects a record UUID. Changed to `dataset.record_id`.

### 2. Terra-draw re-mount crash (use-terra-draw.ts)
`TERRA_DRAW_MODES` were module-level singletons. TerraDraw registers modes internally on construction — when an error boundary recovered and re-mounted DatasetMap, the old mode objects were still "registered", causing `Can not register unless mode is unregistered`. Converted to a `createTerraDrawModes()` factory so fresh instances are created per mount.

### 3. useAllSettings / queryKey warnings (no code fix)
`useAllSettings is not defined` at DatasetPage.tsx:500 is a stale Vite HMR cache artifact — the symbol is not referenced in the current source. The `queryKey needs to be an Array` warning is a cascading effect during error boundary recovery. Both resolve on page refresh.

## Files Changed
- `frontend/src/components/dataset/tabs/OverviewTab.tsx` — pass `record_id` to keywords hook
- `frontend/src/components/drawing/hooks/use-terra-draw.ts` — factory function for mode instances

## Verification
- TypeScript: clean compile
- Tests: 34/34 pass (use-terra-draw: 26, use-records: 8)
- Commit: 5039d3b5
