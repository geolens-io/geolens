---
quick_id: 260530-ezw
status: complete
date: 2026-05-30
---

# Quick Task 260530-ezw — Summary

Six reported items triaged: **3 were verification requests (resolved as working)** and **3 were real defects/UX gaps (fixed + verified)**.

## Verification results — no code change

| Concern | Result | Evidence |
|---------|--------|----------|
| Raster download link `/api/rasters/{id}/{hash}/source.cog.tif` | **Stale URL, not a bug.** Not emitted anywhere in current code. The live route `/api/datasets/{id}/download/cog` works (200 auth / 401 anon, 21 MB tiff). The `/rasters/...source.cog.tif` form is a stale tab/bundle or old bookmark. | curl repro; grep of frontend+backend (only `source.cog.tif` strings are filesystem keys, never URLs) |
| Tile services | **Working.** Raster tiles 200 via `/raster-tiles/{id}/tiles/{z}/{x}/{y}.png` (vite rewrites → `/tiles/raster-proxy/...`). Vector `.pbf` 200, correctly gated. | curl z0–z2 = 200 image/png; vector token + pbf tested public/private |
| Vector download links (public/unpublished) | **Working, correctly gated.** `/datasets/{id}/export?format={gpkg,geojson,shp,csv}` → 200 with real bodies (auth), 401 anon (even public — file export is an authenticated egress path by design; OGC Features + vector tiles serve anonymous). | VECTOR-FINDINGS.md — all 4 formats live-tested |

Product note (not a bug): `/export` requires auth even for public datasets, so anonymous users of a public dataset can only egress via OGC Features / vector tiles, not the file-export formats. Flag if public file download is desired.

## Fixes (3 atomic commits)

1. **`259201eb` — Basemap "labels only" reorder revealed full imagery.** `reorderBasemapAboveData` (`map-sync.ts`) lifted every non-data basemap layer above the data, including the opaque background/land/water fills. With a labels-only basemap those fills painted over the data on reorder. Fix: skip base-fill layers (background/land/water) when lifting; only roads/buildings/boundaries/labels float above data. Exported `isLandLayer`/`isWaterLayer` from `basemap-utils.ts`. Regression test rewritten (`UnifiedStackPanel.basemap-drag.test.tsx`) to pin base-fills-stay-below-data.

2. **`cc321149` — Thumbnail `ERR_FILE_NOT_FOUND` on map list + search.** `useMapThumbnail`/`useQuicklook` cached a `URL.createObjectURL` blob in React Query but revoked it in a `useEffect` cleanup on unmount; the dead URL stayed in cache, so the next consumer (list↔grid toggle, back-nav within gcTime, StrictMode remount) rendered a revoked blob → `net::ERR_FILE_NOT_FOUND` (both the `blob:` and abbreviated `<uuid>:1` shapes). Fix: new `lib/blob-url-cache.ts` subscribes once per QueryClient and revokes blob URLs on cache **eviction/replacement**, not unmount. Hook tests updated.

3. **`452c5ada` — Import Style JSON clarity.** `POST /maps/import` always `create_map()`s a **new** map — it never overwrites the current map, so no destructive-overwrite warning is warranted. Gap was the dialog (opened from the current map's builder) gave no signal a separate map was created. Added an Import-tab note ("Importing creates a new map — your current map won't be changed") and surfaced the created map name + "Open new map" action in the summary. i18n keys added for en/de/es/fr.

## Gates

- `npm run typecheck` — clean
- vitest — 1423 passing across touched areas (thumbnail hooks, quicklook, StyleJsonDialog, basemap-drag/map-sync); rewrote the 4 tests that asserted the old buggy behavior
- eslint touched files — clean
- i18n parity en/de/es/fr maintained
- **Live Playwright MCP (orchestrator-driven, fresh bundle after frontend restart):** map list ↔ grid toggled 4× → **0 `ERR_FILE_NOT_FOUND`**; Style JSON → Import tab shows the clarifying note (i18n resolved).

## Investigation artifacts

- `VECTOR-FINDINGS.md`, `BASEMAP-LABELS-FINDINGS.md`, `THUMBNAIL-FINDINGS.md`
