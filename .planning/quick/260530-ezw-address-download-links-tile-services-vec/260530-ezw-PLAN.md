---
quick_id: 260530-ezw
title: Download links / tiles / vector verify + basemap-labels reorder, thumbnail blob, import-style clarity
status: ready
---

# Quick Task 260530-ezw

Address six reported items. Three were **verification** requests (resolved as working, no code change). Three are **real bugs/UX gaps** that get fixed.

## Investigation results (no code change)

1. **Raster download links** — The reported URL `/api/rasters/{id}/{hash}/source.cog.tif` is **not emitted anywhere** in current code (frontend or backend). The live download route `/api/datasets/{id}/download/cog` works: 200 with auth (21 MB tiff), 401 anonymous. The `/rasters/...source.cog.tif` form is a stale tab/bundle or external bookmark. **No fix — report only.**
2. **Tile services** — Raster tiles return 200 via the frontend-origin `/raster-tiles/{id}/tiles/{z}/{x}/{y}.png` path (vite rewrites to `/tiles/raster-proxy/...`). Vector `.pbf` tiles 200 and are correctly gated (public anon OK; private requires HMAC sig). **Working.**
3. **Vector download links (public/unpublished)** — `/datasets/{id}/export?format={gpkg,geojson,shp,csv}` returns 200 with real bodies under auth; 401 anonymous (even for public — file export is an authenticated egress path by design; OGC Features + vector tiles are the anonymous paths). Correctly gated for private. **Working.** (No draft/ready vector datasets exist; private-published exercised the restricted path.)

## Fixes

### Task 1 — Basemap "labels only" reordering reveals base fills (BUG)
- **Root cause:** `reorderBasemapAboveData` (`frontend/src/components/builder/map-sync.ts:298-319`) lifts **every** non-data basemap layer above the data layers when `basemap_position === 'top'`, including the opaque `background`/land/water base fills. Those fills then paint over the data → "more than just labels."
- **Fix:** Skip base-fill layers (background/land/water) when lifting; only roads/buildings/boundaries/labels float above data. Export `isLandLayer`/`isWaterLayer` from `frontend/src/lib/basemap-utils.ts`.
- **Files:** `frontend/src/components/builder/map-sync.ts`, `frontend/src/lib/basemap-utils.ts`
- **Verify:** Builder with a basemap at `position='top'` keeps base fills below data; labels/detail float above. Live MCP: reorder basemap, confirm data still visible.

### Task 2 — Thumbnail `ERR_FILE_NOT_FOUND` on map list + search (BUG)
- **Root cause:** `useMapThumbnail` and `useQuicklook` create `URL.createObjectURL` blobs cached in React Query, but revoke them in a `useEffect` cleanup on component unmount. The dead blob string stays in cache; the next consumer/remount (e.g. list↔grid toggle, back-nav within gcTime) renders the revoked URL → `net::ERR_FILE_NOT_FOUND` (both the `blob:` and abbreviated `<uuid>:1` shapes are the same failure).
- **Fix:** Revoke blob URLs when React Query **evicts/replaces** the entry, not on component unmount. Add `frontend/src/lib/blob-url-cache.ts` that subscribes once per QueryClient to the query cache and revokes blob URLs on `removed` (and on `updated` when a refetch replaces the blob). Remove the `useEffect` revoke blocks from both hooks.
- **Files:** new `frontend/src/lib/blob-url-cache.ts`, `frontend/src/components/maps/hooks/use-map-thumbnail.ts`, `frontend/src/components/maps/hooks/use-quicklook.ts`, plus existing tests if they assert unmount-revoke.
- **Verify:** Toggle map list↔grid repeatedly; no console `ERR_FILE_NOT_FOUND`; thumbnails persist.

### Task 3 — Import Style JSON: clarify it does NOT overwrite (UX)
- **Finding:** `POST /maps/import` calls `create_map(...)` → import always creates a **new** map; the current map is never modified. So no destructive-overwrite warning is warranted — the gap is that the dialog (opened from inside the current map's builder) gives no indication a *separate* map was created.
- **Fix:** Add a clarifying note in the Import tab ("Importing creates a new map — your current map won't be changed.") and surface the created map in the success summary with an "Open new map" action. Add i18n keys to en/de/es/fr (`styleJson.importHint`, `styleJson.summary.newMap`, `styleJson.openNewMap`).
- **Files:** `frontend/src/components/builder/StyleJsonDialog.tsx`, `frontend/src/i18n/locales/{en,de,es,fr}/builder.json`
- **Verify:** Open Style JSON → Import tab shows the note; importing a valid style shows the new-map name + Open action.

## Gates
- `npm run typecheck` clean
- `npm run test` (vitest) for touched areas green (thumbnail hooks, StyleJsonDialog, map-sync/basemap)
- i18n key parity across en/de/es/fr
- Live Playwright MCP (orchestrator-driven) spot-check of basemap reorder + thumbnail toggle
