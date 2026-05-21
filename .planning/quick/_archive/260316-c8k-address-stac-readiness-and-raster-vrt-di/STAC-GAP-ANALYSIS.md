# STAC 1.1.0 Compliance Gap Analysis

**Date:** 2026-03-16
**Scope:** GeoLens catalog infrastructure vs. STAC 1.1.0 specification
**Status:** Audit only -- no code changes

## Executive Summary

GeoLens has strong STAC foundations already in place. The `DatasetAsset` model stores assets with STAC-aligned fields (key, href, media_type, roles, size_bytes), `RasterAsset.to_stac_properties()` produces projection extension and band metadata, and the OGC record output is already a GeoJSON Feature -- the same base structure as a STAC Item. Three critical gaps remain for Item compliance: `stac_version` literal, `bbox` array, and `properties.datetime` field. Closing these three gaps would make the existing record output a valid STAC Item with minimal additive changes and no structural refactoring.

## What Already Exists

| GeoLens Artifact | STAC Concept | Notes |
|------------------|-------------|-------|
| `DatasetAsset` model (key, href, media_type, roles, size_bytes) | STAC Asset | Schema designed for STAC alignment from day one |
| `RasterAsset.to_stac_properties()` | `proj:epsg`, `proj:wkt2`, `proj:shape`, `gsd`, `bands` | Projection extension + STAC 1.1 common metadata bands |
| `Record.record_type` | STAC Item type discrimination | Values: `vector_dataset`, `raster_dataset`, `vrt_dataset` |
| `dataset_to_ogc_record()` output | STAC Item structure | GeoJSON Feature with id, geometry, properties, links |
| `Record.spatial_extent` | Item `geometry` | GeoJSON geometry, present on all spatial datasets |
| `Record.id` (UUID) | Item `id` | Unique string identifier |
| `Record.links` (self, collection, root) | Item `links` | Present but missing `type` field on some links |
| Backfill migration for `dataset_assets` | Existing data readiness | All raster/VRT assets already populated |
| `record_type` search filter | Type-based discovery | Backend exact match, frontend chips (All/Vector/Raster/VRT) |

## Gap Analysis

| STAC 1.1.0 Requirement | Status | Gap | Priority |
|------------------------|--------|-----|----------|
| **Item** | | | |
| `type` = "Feature" | Present | None | -- |
| `stac_version` = "1.1.0" | Missing | Add literal string to record output | HIGH |
| `id` (unique string) | Present | None (UUID) | -- |
| `geometry` (GeoJSON or null) | Present | None (`spatial_extent`) | -- |
| `bbox` (array of numbers) | Missing | Compute from geometry envelope | HIGH |
| `properties.datetime` (RFC 3339 or null) | Missing | Map from `temporal_start` or set null | HIGH |
| `links` (array with rel, href, type) | Partial | Add `type` field to all link objects | LOW |
| `assets` (object keyed by string) | Missing from output | Query `DatasetAsset` rows, serialize as dict | MEDIUM |
| **Asset** | | | |
| `href` (required) | Present | None (`DatasetAsset.href`) | -- |
| `type` (media type, strongly recommended) | Present | None (`DatasetAsset.media_type`) | -- |
| `roles` (array) | Present | None (`DatasetAsset.roles`) | -- |
| `title` (string) | Present | None (`DatasetAsset.title`) | -- |
| **Collection** | | | |
| `type` = "Collection" | Missing | Add literal to collection output | MEDIUM |
| `stac_version` = "1.1.0" | Missing | Add literal | MEDIUM |
| `license` | Partial | `Record.license` exists but not at collection level | LOW |
| `extent` (spatial + temporal) | Partial | Spatial extent exists, temporal needs aggregation | MEDIUM |
| **Catalog** | | | |
| `type` = "Catalog" | Missing | Add to OGC landing page | LOW |
| `stac_version` | Missing | Add literal | LOW |
| `description` | Present | OGC landing page has description | -- |
| `links` | Present | OGC landing page has links | -- |
| **Conformance** | | | |
| STAC conformance URIs | Missing | Add `https://api.stacspec.org/v1.0.0/core` and related URIs to `/conformance` | MEDIUM |

## Prioritized Roadmap

### Quick Wins (1-2 tasks, no breaking changes)

These are additive field additions to the existing record output:

1. **Add `stac_version` literal** -- Add `"stac_version": "1.1.0"` to `dataset_to_ogc_record()` output. One-line change.

2. **Compute `bbox` from geometry** -- Use `ST_Envelope` or Python geometry bounds to produce `[west, south, east, north]` array. Add to record output.

3. **Add `properties.datetime`** -- Map `temporal_start` to `properties.datetime` (RFC 3339). Set null when no temporal extent. Possibly add `start_datetime`/`end_datetime` from temporal range.

### Medium Effort (1 phase)

4. **Include DatasetAsset in record output** -- Query `DatasetAsset` rows for each item, format as STAC assets dict keyed by `asset.key`. The model is already STAC-aligned, so serialization is straightforward.

5. **Add Collection type and stac_version** -- Augment collection-level output with `"type": "Collection"` and `"stac_version": "1.1.0"`. Add spatial/temporal extent aggregation.

6. **Add STAC conformance URIs** -- Append STAC conformance classes to the existing OGC conformance response:
   - `https://api.stacspec.org/v1.0.0/core`
   - `https://api.stacspec.org/v1.0.0/item-search`
   - `https://api.stacspec.org/v1.0.0/ogcapi-features`

### Future (separate milestone)

7. **Full STAC API endpoints** -- Dedicated `/stac/items`, `/stac/collections` routes returning strict STAC JSON. May coexist with OGC endpoints or replace them.

8. **STAC search with CQL2** -- Implement STAC-compliant search endpoint supporting CQL2 filter expressions, temporal/spatial queries, and free-text search.

9. **Catalog root endpoint** -- `/stac` root returning a STAC Catalog object with links to collections and conformance.

10. **STAC extensions** -- Declare conformance with extensions already partially supported (projection, raster bands) via `stac_extensions` array on items.

## Architecture Notes

The path to STAC compliance is largely **additive**, not structural:

- **OGC record output is already a GeoJSON Feature** -- the same base structure as a STAC Item. Adding `stac_version`, `bbox`, and `properties.datetime` makes it a valid STAC Item without restructuring.

- **DatasetAsset model was designed STAC-aligned from day one** -- fields map directly to STAC Asset properties. No schema changes needed.

- **No breaking changes required** -- All gaps can be closed by adding fields to existing output. Existing API consumers see additional fields, not changed ones.

- **Incremental adoption path** -- GeoLens can serve dual OGC Records + STAC Items from the same data, adding STAC fields progressively. A future milestone can add dedicated STAC endpoints if strict spec conformance is needed.

- **`record_type` enables STAC type discrimination** -- The existing `vector_dataset` / `raster_dataset` / `vrt_dataset` values map naturally to STAC Item categorization, supporting filtered discovery across dataset types.
