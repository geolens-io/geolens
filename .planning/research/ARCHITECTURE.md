# Architecture Research — v1034 Raster Stretch & Colormap Completion

**Domain:** Raster tile serving / map builder editor controls
**Researched:** 2026-05-29
**Mode:** Project research — integration point mapping for three concrete features
**Confidence:** HIGH (all findings sourced from direct file inspection of the live codebase)

---

## Executive Summary

v1034 extends three interlocking surfaces that shipped in v1031/v1032/v1033 without fully closing the multi-band and configurable-bounds gaps. All three features share the same data path — `raster_tile_proxy` (backend) → `buildColormapTileUrl` / `raster-adapter.ts` (frontend tile URL) → MapLibre source teardown/recreate (map-sync.ts) — and none of them require new routes, new schema migrations, or changes to `map-sync.ts`.

The work is additive modification to five existing files plus a new fixture function in the seed script. The build order is: **fixture → multi-band backend → configurable-bounds backend → frontend controls → cleanup → verify**. Every dependency in this order is strict (later steps require earlier ones to already exist for verification to be meaningful).

---

## Feature 1: Per-Band Multi-Band Stretch (RASTER-STRETCH-03)

### The Hardcoded Call Site

**File:** `backend/app/processing/tiles/router.py`
**Function:** `raster_tile_proxy` (the `@router.get("/raster-proxy/...")` handler, line 510)
**The exact hardcoded line:**

```python
rescale_parts = (
    _compute_stretch_rescale(bands, stretch, n_bands=1) if bands else []
)
```

This is on line 580 (inside the `if stretch and stretch != "minmax" and not render_params.startswith("algorithm="):` block). `n_bands=1` is the only change required in `_compute_stretch_rescale`.

### Where `band_count` Is Read

`band_count` is already read from the SQL result in `_resolve_raster_access` (line 342 of the same file — the `ra.band_count` column) and returned in `row["band_count"]`. It is then consumed in `raster_auth_check` at line 485:

```python
bc = row["band_count"] or 1
```

And forwarded into `_titiler_render_params(row["band_count"], row["dtype"])` (line 494).

The stretch path in `raster_tile_proxy` calls `raster_auth_check` first (line 542) and gets `render_params` back via the response header `X-GeoLens-Render-Params`. `render_params` already contains the correct number of `bidx=` params based on `band_count` (from `_titiler_render_params`). This gives the stretch path access to how many bands were selected.

### The Fix

`raster_tile_proxy` does not currently re-read `band_count` after calling `raster_auth_check`. The cleanest fix is:

1. Parse the number of `bidx=` fragments already in `render_params` (a `render_params.count("bidx=")` gives the band count without a second DB read). Or, alternatively, parse `render_params` to count band selections.
2. Pass that count as `n_bands` to `_compute_stretch_rescale` instead of the hardcoded `1`.

The `_compute_stretch_rescale` function (lines 272–307) already loops `for i in range(n_bands)` and handles multi-band correctly — it just needs the right value passed in. The function is not modified.

The `_fetch_band_statistics` function (lines 244–269) already returns stats for ALL bands from `/cog/statistics` (sorted `b1`, `b2`, `b3`, ...). The cache key is `open_path` (unchanged — single-band and multi-band stats for the same asset are the same Titiler response, just more bands in the list).

**New vs Modified:**
- MODIFIED: `backend/app/processing/tiles/router.py` — `raster_tile_proxy` function, one argument change at the `_compute_stretch_rescale` call site

### Frontend Gating Change

**File:** `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx`
**Current gate (line 186):**
```tsx
{layer.band_count === 1 && (
```

**What to change:** Widen to include multi-band rasters where stretch is meaningful but colormap is not. The COLORMAP section (color LUT applied to single-band output) should stay `band_count === 1` only. The STRETCH section (percentile/stddev rescale per band) should show for any raster where `band_count >= 1`:

```tsx
{/* COLORMAP: single-band only */}
{layer.band_count === 1 && (
  ...colormap select...
)}
{/* STRETCH: all rasters (multi-band gets per-band rescale, single-band gets same as before) */}
{(layer.band_count != null && layer.band_count >= 1) && (
  ...stretch select...
)}
```

Or, if design decision is to keep them colocated in a single section, the section header condition becomes `band_count != null && band_count >= 1` while the colormap row inside is additionally gated on `band_count === 1`.

`layer` is typed as `MapLayerResponse` (from `BaseStyleEditorProps.layer`). `band_count?: number | null` is already declared at line 916 of `frontend/src/types/api.ts`.

**New vs Modified:**
- MODIFIED: `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx` — section gate condition only

### Map-Sync / Adapter: No Change Required

`buildColormapTileUrl` (in `raster-adapter.ts`, line 55) already reads `paint['_colormap']` and `paint['_stretch']` and appends both as query params. It does not need to know about band count — the backend proxy handles the per-band logic server-side.

`syncRasterLayer` in `map-sync.ts` (line 624) already calls `buildColormapTileUrl(token.tile_url, adapterInput.paint)` before the tile-URL diff comparison (line 648). If `_stretch` changes in paint, the URL changes, the source diff fires, and MapLibre re-fetches with the new URL — this path is unchanged and already works.

**Confirmed: `map-sync.ts` and `raster-adapter.ts` need zero changes for feature 1.**

---

## Feature 2: Configurable Stretch Bounds (RASTER-STRETCH-UI-01)

### New Query Params

Three new optional query params thread from frontend to backend:

| Param | Type | Purpose |
|-------|------|---------|
| `pmin` | float (0–100) | Lower percentile bound (default: 2) |
| `pmax` | float (0–100) | Upper percentile bound (default: 98) |
| `sigma` | float (>0) | σ multiplier for stddev stretch (default: 2.0) |

### Threading from RasterEditor → Tile URL → Backend

**Step 1 — RasterEditor (MODIFIED):**
`frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx`

Add two number inputs / sliders for `pmin`/`pmax` (visible when stretch === 'percentile') and one for `sigma` (visible when stretch === 'stddev'). Write them to paint via `onPaintProp('_pmin', value)`, `onPaintProp('_pmax', value)`, `onPaintProp('_sigma', value)`. These are builder-private paint keys following the same `_` prefix convention as `_colormap` and `_stretch`.

**Step 2 — buildColormapTileUrl (MODIFIED):**
`frontend/src/components/builder/layer-adapters/raster-adapter.ts`
Function: `buildColormapTileUrl` (line 55)

Add reads for `paint['_pmin']`, `paint['_pmax']`, `paint['_sigma']` and forward as query params when non-default:

```ts
if (typeof paint['_pmin'] === 'number' && paint['_pmin'] !== 2) {
  params.set('pmin', String(paint['_pmin']));
}
// ... pmax, sigma similarly
```

The function's return value changes when these values are set, causing the tile URL to differ, triggering the `syncRasterLayer` source-teardown path in `map-sync.ts` naturally — no changes needed in `map-sync.ts`.

**Step 3 — raster_tile_proxy (MODIFIED):**
`backend/app/processing/tiles/router.py`
Function: `raster_tile_proxy` (line 510)

Add three new `Query` parameters:
```python
pmin: float | None = Query(None, ge=0, le=100),
pmax: float | None = Query(None, ge=0, le=100),
sigma: float | None = Query(None, gt=0),
```

These are passed into `_compute_stretch_rescale` which uses them instead of the hardcoded `percentile_2`/`percentile_98` keys and `_STDDEV_SIGMA`.

**Step 4 — _compute_stretch_rescale (MODIFIED):**
`backend/app/processing/tiles/router.py`
Function: `_compute_stretch_rescale` (line 272)

Extend signature:
```python
def _compute_stretch_rescale(
    bands: list[dict], stretch: str, n_bands: int,
    pmin: float = 2.0, pmax: float = 98.0, sigma: float = 2.0
) -> list[str]:
```

Then use `pmin`/`pmax` to select the right percentile keys from the Titiler statistics response and `sigma` instead of `_STDDEV_SIGMA`.

Note: Titiler `/cog/statistics` returns fixed percentile keys (`percentile_2`, `percentile_98`, and optionally others). If `pmin`/`pmax` are non-default values, the backend must request those percentiles explicitly from Titiler via `/cog/statistics?p=<pmin>&p=<pmax>`. Check Titiler's `/cog/statistics` API — it accepts `p` params for custom percentile computation. This is a potential complication: the current `_fetch_band_statistics` function uses a fixed URL with no `p` params.

### Cache Key Change: Critical

**Current cache key:** `open_path` (the S3/local path string)
**Required cache key:** `(open_path, pmin, pmax)` because different percentile bounds require Titiler to compute different stats.

`_band_stats_cache` is currently typed as `LRUCache[str, list[dict] | None]`. It must change to a compound key:

```python
_band_stats_cache: LRUCache[tuple[str, float, float], list[dict] | None] = LRUCache(maxsize=256)
```

And `_fetch_band_statistics` must accept `pmin`/`pmax` params and pass them to Titiler's statistics URL, keying by the tuple.

`sigma` does NOT need to be in the cache key because sigma is used only in the local `_compute_stretch_rescale` computation — the raw stats (mean, std) from Titiler are sigma-independent.

The statsURL call in `_fetch_band_statistics` becomes:
```python
stats_url = build_titiler_cog_url(
    "statistics",
    query={"url": open_path, "p": str(pmin), "p": str(pmax)},
)
```

Note: `urlencode` in `build_titiler_cog_url` does not handle repeated keys (`p=2&p=98`). The `query` dict approach only allows one value per key. This means either: (a) pass `pmin`/`pmax` as `raw_query_suffix` already-encoded, or (b) extend `build_titiler_cog_url` to accept multi-value query params. Option (a) is simpler and consistent with how `render_params` is already forwarded.

**New vs Modified:**
- MODIFIED: `backend/app/processing/tiles/router.py` — `_fetch_band_statistics`, `_compute_stretch_rescale`, `raster_tile_proxy` signatures + cache key type
- MODIFIED: `frontend/src/components/builder/layer-adapters/raster-adapter.ts` — `buildColormapTileUrl`
- MODIFIED: `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx` — new inputs for pmin/pmax/sigma (conditional on stretch mode)

---

## Feature 3: Single-Band Raster Test Fixture (TESTDATA-01)

### Current State of seed-natural-earth.py

The script is vector-only. Its `ingest_dataset` function (line 542) calls:
1. `POST /api/ingest/upload` with a ZIP containing a Shapefile
2. `POST /api/ingest/preview/{job_id}` (server auto-detects vector)
3. `POST /api/ingest/commit/{job_id}` with `{"title":..., "visibility":"public", "srid_override":4326}`

For rasters, the commit body is a `RasterCommitRequest` (not `VectorCommitRequest`). The server distinguishes them via `file_type` in `job.user_metadata`, which is set automatically during upload when the filename ends in `.tif`/`.tiff`/`.vrt` (router.py line 334–366, `_stamp_raster_metadata`). So raster ingest does NOT require a different commit body shape — only the file extension triggers the raster path.

### What the Seed Script Does Not Have

- No raster download or ingest path
- No idempotency check for rasters (the existing check looks for existing source filenames via `existing` dict — same mechanism would work for a `.tif` file)
- No COG source (natural-earth does not distribute GeoTIFFs)

### Recommended Fixture Source

A small, freely-redistributable, public-domain single-band GeoTIFF. Good candidates:
- **SRTM/ETOPO tiles** (NASA) — already COG-compatible, public domain
- **USGS National Elevation Dataset sample tiles** — public domain
- **Natural Earth raster quickstart** — `https://naturalearth.s3.amazonaws.com/packages/Natural_Earth_quick_start.zip` contains a world raster (multi-band) — not ideal for single-band test
- **A generated synthetic GeoTIFF** — created at script runtime using GDAL (requires GDAL on PATH) — no download dependency, fully deterministic, any CRS/band-count

The synthetic approach is most reliable for CI (no external CDN dependency, no bandwidth, deterministic data). GDAL is already a dependency of the geolens stack.

### How to Extend seed-natural-earth.py

**New function (idempotent ingest of a raster):**

```python
async def ingest_raster_fixture(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    existing_by_filename: dict[str, str],
) -> dict | None:
    """Ingest a small single-band COG fixture for raster stretch/colormap testing.

    Idempotent: skips if a dataset with source_filename 'testdata_singleband.tif'
    already exists in existing_by_filename.
    """
    FIXTURE_FILENAME = "testdata_singleband.tif"
    if FIXTURE_FILENAME in existing_by_filename:
        return {"status": "skipped", "dataset_id": existing_by_filename[FIXTURE_FILENAME]}

    # Generate a tiny single-band COG using GDAL (gdal_translate)
    # ... or download from a stable public URL ...

    headers = {"X-Api-Key": api_key}
    # Upload
    upload_resp = await client.post(
        f"{base_url}/api/ingest/upload",
        headers=headers,
        files={"file": (FIXTURE_FILENAME, tif_bytes, "image/tiff")},
    )
    upload_resp.raise_for_status()
    job_id = upload_resp.json()["job_id"]

    # Preview (triggers raster detection via _stamp_raster_metadata)
    preview_resp = await client.post(
        f"{base_url}/api/ingest/preview/{job_id}",
        headers=headers,
    )
    preview_resp.raise_for_status()

    # Commit as raster (RasterCommitRequest shape)
    commit_resp = await client.post(
        f"{base_url}/api/ingest/commit/{job_id}",
        headers=headers,
        json={
            "title": "Test Single-Band Raster",
            "visibility": "public",
        },
    )
    commit_resp.raise_for_status()
    result = await poll_job(client, base_url, api_key, job_id)
    return result
```

The raster path does NOT need `srid_override` if the GeoTIFF has a valid CRS embedded. It does NOT need `compression` or `resampling` — defaults are fine for a test fixture.

**Where to call it in main():** After the vector seed loop, add a dedicated raster fixture step with its own progress print, before `create_collections`.

**Idempotency key:** The existing `existing` dict is built from `GET /api/datasets?limit=...` and keyed by `source_filename`. A `.tif` upload will appear there once ingested, so re-running the script skips it automatically — the same mechanism as vector datasets.

**New vs Modified:**
- MODIFIED: `scripts/seed-natural-earth.py` — add `ingest_raster_fixture` function + call in `main()`

---

## Complete Data Flow (All Three Features Combined)

```
[RasterEditor.tsx]
  user changes _stretch='percentile', _pmin=5, _pmax=95
        │
        ▼ onPaintProp writes to layer.paint
[buildColormapTileUrl in raster-adapter.ts]
  reads paint['_colormap'], ['_stretch'], ['_pmin'], ['_pmax'], ['_sigma']
  returns baseUrl?stretch=percentile&pmin=5&pmax=95
        │
        ▼ URL differs from current source tiles[0]
[syncRasterLayer in map-sync.ts]
  detects tile URL diff → removeLayer → removeSource → addLayers with new URL
  (no code change in map-sync.ts)
        │
        ▼ MapLibre fetches new tile URL
[raster_tile_proxy in tiles/router.py]
  receives ?stretch=percentile&pmin=5&pmax=95
  calls _fetch_band_statistics(open_path, pmin=5, pmax=95)
        │
        ▼ cache miss (new pmin/pmax)
[_fetch_band_statistics]
  GET http://titiler:8000/cog/statistics?url=...&p=5&p=95
  stores result in _band_stats_cache[(open_path, 5.0, 95.0)]
        │
        ▼
[_compute_stretch_rescale(bands, 'percentile', n_bands, pmin=5, pmax=95)]
  n_bands = count of bidx= in render_params (e.g. 3 for RGB)
  computes rescale=lo,hi per band from percentile_5/percentile_95 fields
        │
        ▼
[_apply_stretch_rescale(render_params, rescale_parts)]
  replaces existing rescale= fragments with new per-band values
        │
        ▼
[build_titiler_cog_url(..., raw_query_suffix=render_params)]
  builds http://titiler:8000/cog/tiles/WebMercatorQuad/z/x/y.png?url=...&bidx=1&bidx=2&bidx=3&rescale=lo1,hi1&rescale=lo2,hi2&rescale=lo3,hi3
        │
        ▼
[Titiler] renders tile with per-band stats rescale
```

---

## New vs Modified Components

| File | Status | What Changes |
|------|--------|--------------|
| `backend/app/processing/tiles/router.py` | MODIFIED | `raster_tile_proxy`: `n_bands` from render_params count + `pmin`/`pmax`/`sigma` Query params; `_fetch_band_statistics`: cache key `(open_path, pmin, pmax)` + p-param forwarding to Titiler; `_compute_stretch_rescale`: extended signature with `pmin`/`pmax`/`sigma` defaults; `_band_stats_cache` type annotation |
| `frontend/src/components/builder/layer-adapters/raster-adapter.ts` | MODIFIED | `buildColormapTileUrl`: read `_pmin`, `_pmax`, `_sigma` from paint; append as query params when non-default |
| `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx` | MODIFIED | Section gate widened for stretch (multi-band); COLORMAP gate unchanged (`band_count===1`); new pmin/pmax/sigma inputs conditional on stretch mode |
| `scripts/seed-natural-earth.py` | MODIFIED | Add `ingest_raster_fixture()` function + call in `main()` |
| `backend/app/platform/storage/titiler_url.py` | NO CHANGE | `build_titiler_cog_url` — p params forwarded via `raw_query_suffix`, not `query` dict |
| `frontend/src/components/builder/map-sync.ts` | NO CHANGE | Source teardown/recreate already fires on tile URL diff |
| `frontend/src/types/api.ts` | NO CHANGE | `band_count?: number | null` on `MapLayerResponse` already exists (line 916) |
| `frontend/src/components/builder/LayerStyleEditor/types.ts` | NO CHANGE | `BaseStyleEditorProps.layer: MapLayerResponse` already has `band_count` |

---

## Dependency-Ordered Build Sequence

### Step 1: Fixture (TESTDATA-01)
**Rationale:** All subsequent UI verification requires a real raster in the system. Without a single-band COG, the colormap+stretch section never renders (band_count check), and multi-band stretch cannot be verified without a known 3-band COG. Build this first so every later step has something to test against.

Files: `scripts/seed-natural-earth.py`

### Step 2: Multi-Band Backend Fix (RASTER-STRETCH-03 backend)
**Rationale:** Backend change is independent of frontend controls — it only changes the `n_bands` argument. Can be verified with curl/httpx against the running proxy to confirm multi-rescale tile URLs generate different byte responses. Does not require any frontend change. Must precede the frontend gating change so backend is ready when frontend starts sending multi-band stretch requests.

Files: `backend/app/processing/tiles/router.py` — `raster_tile_proxy` n_bands derivation only

### Step 3: Configurable-Bounds Backend (RASTER-STRETCH-UI-01 backend)
**Rationale:** Adds `pmin`/`pmax`/`sigma` Query params + updates cache key. Must be landed before the frontend starts sending these params, otherwise the backend ignores them silently. Cache-key change is load-bearing — without it, `pmin=5` and `pmin=2` serve identical tiles from cache.

Files: `backend/app/processing/tiles/router.py` — `_fetch_band_statistics`, `_compute_stretch_rescale`, `raster_tile_proxy` new params, cache type

### Step 4: Frontend Controls
**Rationale:** Depends on the backend accepting `pmin`/`pmax`/`sigma` (step 3) and the multi-band backend being ready (step 2). Two sub-steps, either order:

4a. **Widen multi-band gate in RasterEditor** — changes `band_count === 1` section gate to expose stretch for multi-band; no new URL params
4b. **Add configurable-bounds inputs + tile URL params** — adds `_pmin`/`_pmax`/`_sigma` to paint → `buildColormapTileUrl` → tile URL → triggers re-fetch

Files: `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx`, `frontend/src/components/builder/layer-adapters/raster-adapter.ts`

### Step 5: Cleanup (v1033 tech debt)
**Rationale:** Remove dead `onRenderModeChange` member and rework `hillshadeTerrainNote` advisory. Independent of all above — no functional behavior change. Can be done any time after the feature work is stable, before close-gate.

Files: Wherever `onRenderModeChange` is declared (search in builder components) and the `hillshadeTerrainNote` string (likely in RasterEditor or DEMEditor).

### Step 6: Verify (Close-Gate)
Playwright MCP live smoke on the single-band fixture (colormap + stretch + configurable bounds) and a multi-band dataset (stretch section visible, colormap hidden). Backend test for `_compute_stretch_rescale` with n_bands>1 and custom pmin/pmax. Verify cache key isolation (different pmin/pmax → different cache entries).

---

## Component Boundaries

```
┌─────────────────────────────────────────────────────────────┐
│ RasterEditor.tsx                                             │
│  band_count gate → colormap (=1 only) + stretch (>=1)       │
│  pmin/pmax inputs (when stretch=percentile)                  │
│  sigma input (when stretch=stddev)                           │
│  writes: onPaintProp('_colormap'|'_stretch'|'_pmin'|'_pmax'|'_sigma', v) │
└────────────────────────────┬────────────────────────────────┘
                             │ paint dict
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ buildColormapTileUrl (raster-adapter.ts)                     │
│  reads _colormap, _stretch, _pmin, _pmax, _sigma             │
│  returns tile URL with query params                          │
└────────────────────────────┬────────────────────────────────┘
                             │ tile URL diff
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ syncRasterLayer (map-sync.ts) — UNCHANGED                   │
│  detects URL diff → MapLibre source teardown+recreate        │
└────────────────────────────┬────────────────────────────────┘
                             │ HTTP tile request
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ raster_tile_proxy (tiles/router.py)                          │
│  new Query params: pmin, pmax, sigma                         │
│  n_bands from render_params bidx count                       │
│  calls _fetch_band_statistics(open_path, pmin, pmax)         │
│  calls _compute_stretch_rescale(bands, stretch, n_bands,     │
│    pmin, pmax, sigma)                                        │
│  _band_stats_cache key: (open_path, pmin, pmax)              │
└────────────────────────────┬────────────────────────────────┘
                             │ Titiler HTTP
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ Titiler /cog/statistics?url=...&p=pmin&p=pmax               │
│ Titiler /cog/tiles/.../z/x/y.png?bidx=1...&rescale=lo,hi... │
└─────────────────────────────────────────────────────────────┘
```

---

## Scalability / Load Considerations

The `_band_stats_cache` LRU is bounded at 256 entries. With the compound `(open_path, pmin, pmax)` key, a single raster file with 5 different pmin/pmax combinations would occupy 5 cache entries instead of 1. For a typical deployment with ~10–20 raster datasets and 3 common pmin/pmax combinations (2/98, 5/95, 1/99), this is ~30–60 entries — well within the 256 ceiling. The `maxsize=256` bound from v1033 HYG-01 remains appropriate.

---

## Contract Preservation Notes

- `_colormap` and `_stretch` keys in paint are already excluded from `RASTER_OWNED_PAINT_PROPERTIES` (Pitfall 6 — they mutate tile URL, not MapLibre paint). The new `_pmin`, `_pmax`, `_sigma` keys follow the same convention and must also be excluded from `RASTER_OWNED_PAINT_PROPERTIES`.
- `buildColormapTileUrl` is called from `syncRasterLayer` BEFORE the tile-URL diff comparison (map-sync.ts line 648). This ordering is load-bearing: new paint keys must be readable by `buildColormapTileUrl` before the diff fires. No change needed — the function already receives the full `adapterInput.paint`.
- The backend allowlist `_ALLOWED_STRETCH` (line 230 of router.py) already contains `{"minmax", "percentile", "stddev"}`. No new stretch modes are added — only the bounds become configurable.
- The Titiler colormap allowlist `_ALLOWED_COLORMAPS` (line 223) is unchanged.

---

## Sources

All findings verified by direct file inspection at HEAD (commit `f2c06400`):

- `backend/app/processing/tiles/router.py` — lines 189–312 (stretch functions), 510–675 (raster_tile_proxy handler) — HIGH confidence
- `backend/app/platform/storage/titiler_url.py` — full file — HIGH confidence
- `backend/app/processing/ingest/schemas.py` — lines 110–196 (commit request shapes) — HIGH confidence
- `backend/app/processing/ingest/router.py` — lines 322–366 (`_stamp_raster_metadata`, `file_type` detection) — HIGH confidence
- `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx` — full file — HIGH confidence
- `frontend/src/components/builder/layer-adapters/raster-adapter.ts` — full file — HIGH confidence
- `frontend/src/components/builder/map-sync.ts` — lines 624–688 (`syncRasterLayer`) — HIGH confidence
- `frontend/src/components/builder/LayerStyleEditor/types.ts` — full file (`BaseStyleEditorProps`) — HIGH confidence
- `frontend/src/types/api.ts` — lines 890–917 (`MapLayerResponse.band_count`) — HIGH confidence
- `scripts/seed-natural-earth.py` — lines 542–616 (`ingest_dataset`), 955–1030 (`process_one`) — HIGH confidence
- `.planning/PROJECT.md` — lines 15–36 (v1034 scope) — HIGH confidence
