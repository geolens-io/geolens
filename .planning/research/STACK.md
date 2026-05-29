# Stack Research — v1034 Raster Stretch & Colormap Completion

**Domain:** Completing a half-built raster-rendering feature in an existing GIS catalog
**Researched:** 2026-05-29
**Confidence:** HIGH (Titiler/COG syntax verified via Context7 + existing codebase cross-check; fixture source license confirmed)

---

## TL;DR

No new dependencies. The three new things v1034 needs are: (1) pass the real `band_count` instead of the hardcoded `1` to the already-correct `_compute_stretch_rescale`, (2) expose percentile/σ bounds as query params on the proxy endpoint, and (3) download `GRAY_50M_SR.zip` from the NACIS CDN (public domain) and ingest it as a single-band COG via the existing three-step ingest API.

---

## 1. Titiler Version

**Image pinned in `docker-compose.yml`:** `ghcr.io/developmentseed/titiler:2.0.2`

This is the authoritative version. All URL syntax and response shapes below are confirmed against the Context7 docs for the `/developmentseed/titiler` library (source reputation: High, 1483 code snippets).

---

## 2. `/cog/statistics` — Response Shape (CONFIRMED)

### Response structure

The endpoint returns a flat dict keyed by band name strings `"b1"`, `"b2"`, `"b3"`, etc. (NOT `"1"`, `"2"`, `"3"`). The existing `_fetch_band_statistics` parser in `router.py:259-265` already handles this correctly — it sorts by `int(k[1:])` and builds a list ordered `b1, b2, ...`.

Each band value is an object with these fields:

```json
{
  "b1": {
    "min": 102.0,
    "max": 3200.0,
    "mean": 847.3,
    "count": 45000,
    "sum": 38128500.0,
    "std": 312.7,
    "median": 720.0,
    "majority": 650.0,
    "minority": 3200.0,
    "unique": 2841,
    "histogram": [...],
    "valid_percent": 98.3,
    "masked_pixels": 750,
    "valid_pixels": 44250,
    "percentile_2": 180.0,
    "percentile_98": 1800.0
  }
}
```

### Key field names used by `_compute_stretch_rescale`

| Field | Used for |
|-------|----------|
| `percentile_2` | Lower bound of percentile stretch |
| `percentile_98` | Upper bound of percentile stretch |
| `mean` | Center for stddev stretch |
| `std` | Half-width for stddev stretch |
| `min` | Clamp floor for stddev |
| `max` | Clamp ceiling for stddev |

These match the live field names verified in Context7. The existing code at `router.py:287-288` uses `b.get("percentile_2")` and `b.get("percentile_98")` — correct.

### Configuring percentile bounds via `?p=` query param

The statistics endpoint accepts `?p=N` (repeatable) to request specific percentiles. Default is `[2, 98]` when no `p` is supplied. To make bounds configurable:

```
GET /cog/statistics?url=...&p=5&p=95
```

This returns `percentile_5` and `percentile_95` fields (not `percentile_2`/`percentile_98`). When implementing configurable bounds, the backend must:
1. Accept `pmin`/`pmax` (or `p_low`/`p_high`) as proxy query params
2. Forward them as `?p=pmin&p=pmax` to Titiler's `/cog/statistics`
3. Read `b.get(f"percentile_{pmin}")` and `b.get(f"percentile_{pmax}")` from the response

The `_band_stats_cache` key is currently `open_path` only. When percentile bounds become configurable, the cache key must include the bounds: `f"{open_path}:{pmin}:{pmax}"` to avoid serving cached p2/p98 stats for a p5/p95 request.

---

## 3. Titiler Tile Endpoint — `rescale` Syntax for Multi-Band

### Confirmed syntax (Context7 + CHANGES.md)

Multi-band per-band rescale uses **repeated `rescale=lo,hi` params**, one per band:

```
# Single band (current):
rescale=0,255

# Three-band, one pair per band — the ONLY correct format since rio-tiler 2.1:
rescale=0,255&rescale=0,1000&rescale=0,10000
```

The old comma-separated format (`rescale=0,255,0,1000,0,10000`) was retired in rio-tiler 2.1. Titiler 2.0.2 uses a current rio-tiler that expects the repeated-param form. This matches the existing `_titiler_render_params` logic, which already emits one `rescale=0,{max}` fragment per selected band in a loop.

### What the existing `_apply_stretch_rescale` does

`_apply_stretch_rescale(render_params, rescale_parts)` drops ALL existing `rescale=` fragments from `render_params` and appends the new list. This is already correct for multi-band — no changes needed to this function.

### The single line that needs changing for RASTER-STRETCH-03

In `raster_tile_proxy` (router.py:581):

```python
# Current — hardcoded n_bands=1 (single-band only):
rescale_parts = _compute_stretch_rescale(bands, stretch, n_bands=1)

# Multi-band fix — pass real band count, capped at 3 (RGB rendering max):
n_selected = min(band_count or 1, 3) if (band_count or 1) >= 3 else max(band_count or 1, 1)
rescale_parts = _compute_stretch_rescale(bands, stretch, n_bands=n_selected)
```

The `band_count` is available from the DB row (`row["band_count"]`) which is already fetched by `_resolve_raster_access`. No additional DB query needed.

### `_compute_stretch_rescale` already handles n_bands > 1

The function at router.py:272-306 loops `for i in range(n_bands)` and reads `bands[i]` for each — it already works correctly for n_bands=3. The only current limitation is the call site hardcodes `n_bands=1`.

---

## 4. Configurable Percentile/σ Bounds — Implementation Shape

### Backend (RASTER-STRETCH-UI-01)

Add two optional query params to `raster_tile_proxy`:

```python
pmin: float = Query(2.0, ge=0.1, le=49.9, description="Lower percentile bound (default 2)")
pmax: float = Query(98.0, ge=50.1, le=99.9, description="Upper percentile bound (default 98)")
sigma: float = Query(2.0, ge=0.5, le=5.0, description="Sigma multiplier for stddev stretch (default 2.0)")
```

When `stretch == "percentile"`, pass `pmin`/`pmax` to the statistics fetch and read `f"percentile_{int(pmin)}"` from the response. When `stretch == "stddev"`, use `sigma` instead of the hardcoded `_STDDEV_SIGMA = 2.0`.

Cache key for `_band_stats_cache` must incorporate `pmin`/`pmax` when non-default — otherwise the LRU cache returns p2/p98 stats for a p5/p95 request.

### Frontend

`buildColormapTileUrl` in `raster-adapter.ts` must forward new paint keys `_pmin`/`_pmax`/`_sigma` as query params alongside `stretch`. The `RasterEditor` gets two new numeric inputs (visible only when `_stretch !== 'minmax'`): a percentile range slider (shown for `percentile`) or a sigma spinner (shown for `stddev`).

---

## 5. Test Fixture — Single-Band Raster COG

### Recommended source

**Natural Earth 1:50m Gray Earth with Shaded Relief and Hypsography**

| Property | Value |
|----------|-------|
| File | `GRAY_50M_SR.zip` |
| URL | `https://naciscdn.org/naturalearth/50m/raster/GRAY_50M_SR.zip` |
| Size | ~18 MB (compressed), verified 200 OK |
| License | **Public domain** (confirmed at naturalearthdata.com/about/terms-of-use/) |
| Band count | 1 (single-band grayscale uint8) |
| CRS | EPSG:4326 |
| Resolution | 50m-scale (~0.0167° ≈ ~1.5 km at equator) |
| Content | Grayscale shaded relief derived from SRTM Plus — ideal for testing stretch/colormap UI |

**Why this source over alternatives:**
- Already on the same NACIS CDN the seed script uses; consistent CDN_BASE and download pattern
- Public domain — can be committed to the seed script without any license concern
- Single-band uint8 — exercises all three stretch modes (minmax trivial, percentile/stddev meaningful on 0–255 grayscale gradient data)
- Small enough to seed quickly; the zip extracts to `GRAY_50M_SR.tif` plus sidecar files
- Not a DEM — the tile proxy's `algorithm=terrainrgb` branch does NOT fire, so colormap + stretch both apply
- Fits `band_count=1` gating logic in RasterEditor

**Why not NLCD land cover:**
- CONUS extent only; large files (30 m resolution nationwide = multi-GB uncompressed)
- Categorical data (integer class codes 11–95) — percentile stretch produces degenerate ranges on sparse class histograms
- Not already on the NACIS CDN; requires a different download mechanism

**Why not 10m Natural Earth gray earth (`GRAY_HR_SR.zip`):**
- 75 MB compressed — 4× larger than necessary for a dev fixture; slows seed and CI

### How the GeoTIFF needs to arrive as a COG

The existing raster ingest pipeline (`ingest_raster` task) handles COG conversion internally. When you upload a raw GeoTIFF via `/api/ingest/upload`, the worker runs GDAL to convert it to a COG in the staging area before registering it. The seed fixture only needs to deliver the `.tif` inside a `.zip` (or bare `.tif` — both are accepted per `router.py:97-98`).

The zip from `GRAY_50M_SR.zip` contains `GRAY_50M_SR.tif` — this is a valid GeoTIFF that will be COG-converted by the worker. No pre-conversion step needed in the seed script.

If a fully pre-converted COG is preferred for deterministic behavior (bypasses the worker COG step), the GDAL command is:

```bash
gdal_translate GRAY_50M_SR.tif GRAY_50M_SR_COG.tif \
  -of COG \
  -co COMPRESS=DEFLATE \
  -co BLOCKSIZE=256
```

This requires GDAL >= 3.1 (COG driver built-in). The project already has GDAL available in the worker and dev environment.

---

## 6. Seed Script Integration Pattern

### How to add the raster fixture to `seed-natural-earth.py`

The existing `ingest_dataset()` function at line 542 handles vector files (.zip with shapefiles). For raster, the commit step requires `file_type == "raster"` in job metadata — this is set automatically by `_stamp_raster_metadata` in the upload handler when the file extension is `.tif`/`.tiff`.

The commit body for a raster dataset is a `RasterCommitRequest`, but the seed script only needs to POST `{"title": "...", "visibility": "public"}` — the router discriminates raster vs. vector by job metadata, not by the commit body schema. No code change to `ingest_dataset()` is needed; the same three-step flow works.

Recommended addition (a standalone function in the seed script, called after the main vector import loop):

```python
RASTER_DATASETS = [
    {
        "stem": "GRAY_50M_SR",
        "url": "https://naciscdn.org/naturalearth/50m/raster/GRAY_50M_SR.zip",
        "name": "Natural Earth Shaded Relief (1:50m)",
        "tags": ["raster", "shaded-relief", "natural-earth", "grayscale"],
    }
]
```

The download and ingest flow mirrors the vector datasets exactly: download zip → POST to `/api/ingest/upload` → POST to `/api/ingest/preview/{job_id}` → POST to `/api/ingest/commit/{job_id}` with `{"title": ..., "visibility": "public"}` → poll until complete.

---

## 7. What NOT to Add

- **No new Python dependencies.** `rasterio`, `GDAL`, `rio-cogeo`, `cachetools` already in the project. The multi-band fix is pure logic changes to existing functions.
- **No new Titiler query params beyond what's documented.** The `/cog/statistics` `?p=N` param is already part of the Titiler API.
- **No pre-converted fixture hosting.** Downloading from NACIS at seed time is the correct pattern (matches how all other Natural Earth data is seeded). Do not commit the `.tif` to the repo.
- **No change to `_apply_stretch_rescale`.** It already strips and replaces all rescale fragments; the function is correct for multi-band.
- **No change to `_fetch_band_statistics`.** It already returns all bands as a list ordered `b1, b2, ...`; the caller just needs to pass `n_bands > 1`.
- **No frontend changes for the multi-band feature itself.** The UI selects stretch mode per-layer; the backend computes the right number of rescale pairs automatically from the stored `band_count`. The frontend does not need to know how many bands there are to send `stretch=percentile`.

---

## 8. Confidence Assessment

| Area | Confidence | Basis |
|------|------------|-------|
| Titiler rescale multi-band syntax | HIGH | Context7 docs + CHANGES.md + existing `_titiler_render_params` code already uses this pattern |
| `/cog/statistics` response field names | HIGH | Context7 docs match field names already used in existing `_compute_stretch_rescale` |
| Percentile `p=` query param to statistics | HIGH | Context7 StatisticsParams source confirms `alias="p"` |
| Band stats cache key extension needed | HIGH | LRU cache currently keyed on `open_path` only; configurable bounds require key extension |
| `GRAY_50M_SR.zip` URL and license | HIGH | HTTP 200 + 18 MB content-length verified via curl; public domain confirmed on terms-of-use page |
| COG conversion not required before seed upload | MEDIUM | Based on how `_stamp_raster_metadata` detects `.tif` and worker converts; not smoke-tested end-to-end with this specific file yet |
| `n_bands` calculation for multi-band | HIGH | Direct reading of existing `_compute_stretch_rescale` loop logic |

---

## Sources

- Context7 Titiler library (`/developmentseed/titiler`) — statistics endpoint, rescale syntax, StatisticsParams
- `backend/app/processing/tiles/router.py` — `_compute_stretch_rescale`, `_fetch_band_statistics`, `_apply_stretch_rescale`, `_titiler_render_params`
- `backend/app/platform/storage/titiler_url.py` — URL builder
- `backend/app/processing/ingest/router.py` — raster commit discrimination
- `frontend/src/components/builder/layer-adapters/raster-adapter.ts` — `buildColormapTileUrl`
- `docker-compose.yml` — Titiler 2.0.2 image pin
- `https://naciscdn.org/naturalearth/50m/raster/GRAY_50M_SR.zip` — 200 OK, 18 279 677 bytes
- `https://www.naturalearthdata.com/about/terms-of-use/` — public domain confirmed
