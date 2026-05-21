# Quick Task 260316-gas: Assess Mixed Raster/Vector Search Design - Research

**Researched:** 2026-03-16
**Domain:** OGC API Records / STAC / Mixed-modality search and discovery
**Confidence:** HIGH (direct codebase inspection)

## Summary

This research documents the current state of GeoLens's search, discovery, and standards-alignment architecture to enable a gap analysis against the proposed record-first discovery design document. All findings are based on direct codebase inspection of the backend routers, models, schemas, search service, and frontend components.

GeoLens already has a strong foundation: a unified search endpoint returning OGC Record-style GeoJSON Features for all dataset types (vector, raster, VRT), a record_type discriminator for mixed-modality filtering, STAC-style assets on record output, and a UI with type-toggle filters and type-specific badges/cards. However, there are notable gaps in formal STAC Item compliance, OGC API Records conformance declaration, `datetime` query parameter support, faceted aggregation (counts per type), VRT lifecycle endpoints, and detail page consistency across modalities.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Implementation Decisions
- Produce BOTH a gap analysis document AND a phased implementation roadmap
- Gap analysis first, roadmap derived from identified gaps
- Analyze all three discovery layers at equal depth: Record search, STAC export, OGC Features alignment
- Pragmatic alignment: Focus on high-impact alignment points (endpoint shapes, query params, response schemas) without exhaustive spec coverage
- Assess both search results unification AND detail page consistency

### Specific Ideas
- The design doc references specific standards: STAC 1.1 common bands, OGC API Records `q`/`bbox`/`datetime` params, CQL2 filtering
- Concrete examples provided: STAC Item JSON for raster/VRT, OGC Records record for vector, mermaid diagrams
- Prioritized recommendations with acceptance criteria and tests already defined in the design doc
</user_constraints>

---

## 1. Current Search/Discovery Architecture

### Endpoints

| Endpoint | Purpose | Auth |
|----------|---------|------|
| `GET /search/datasets` | Primary search endpoint (frontend uses this) | Required |
| `GET /collections/datasets/items` | OGC Records items endpoint (mirrors /search/datasets) | Optional |
| `GET /collections/datasets/items/{id}` | Single OGC Record by ID | Optional |
| `GET /collections` | OGC collections listing (catalog + per-dataset feature collections) | Optional |
| `GET /collections/datasets` | Dataset catalog collection metadata | Optional |
| `GET /collections/datasets/queryables` | Queryable properties schema (OGC Features Part 3) | Public |
| `GET /collections/datasets/schema` | Record JSON Schema | Public |

### Query Parameters Supported

| Parameter | Type | Notes |
|-----------|------|-------|
| `q` | string | Full-text search (websearch_to_tsquery + ILIKE) |
| `bbox` | string | `minx,miny,maxx,maxy` spatial filter |
| `keywords` | list[str] | Keyword facet filter |
| `geometry_type` | string | Vector geometry type filter |
| `srid` | int | CRS filter |
| `source_organization` | string | Organization filter |
| `record_type` | string | `vector_dataset`, `raster_dataset`, `vrt_dataset` |
| `date_from` / `date_to` | date | Filter on `created_at` |
| `vintage_start` / `vintage_end` | date | Filter on temporal extent |
| `sort_by` | string | `relevance`, `date_added`, `name`, `last_updated` |
| `filter` | string | CQL2 filter expression |
| `filter-lang` | string | `cql2-text` or `cql2-json` |

### How Mixed Results Work

The search service (`backend/app/search/service.py`) queries all dataset types in a single query, joining `Dataset` to `Record`. The `record_type` column on `Record` discriminates types (`vector_dataset`, `raster_dataset`, `vrt_dataset`). After the main query:

1. Results are serialized via `dataset_to_ogc_record()` as GeoJSON Features
2. Raster/VRT results are enriched with a second query to `RasterAsset` for `band_count`, `epsg`, `res_x`, `res_y`, `width`, `height`, `dtype`, `nodata`
3. STAC assets are bulk-fetched from `DatasetAsset` table and attached as `stac_assets`

**Key observation:** All record types share the same response shape. There is no separate STAC Item endpoint -- raster/VRT records are returned as OGC Record Features with STAC-like properties mixed in.

### Search Ranking

- FTS: `ts_rank_cd` on Record.search_vector + ILIKE boosts on title/summary + EXISTS on keywords/contacts
- Optional hybrid: pgvector semantic search with RRF (k=60) when enabled
- Sort options: relevance, date_added, name, last_updated

---

## 2. Current OGC/STAC Alignment

### OGC Conformance Declared

The conformance endpoint (`GET /conformance`) declares:
- OGC API Common Core (landing-page, json, oas30)
- OGC API Features Part 1 (core, geojson, oas30)
- OGC API Features Part 3 (filter, features-filter, cql2-text, cql2-json, basic-cql2)

**Not declared:**
- OGC API Records Core conformance class
- OGC API Records Record Schema
- Any STAC-related conformance

### Record Output Schema (dataset_to_ogc_record)

Current output structure for each record:

```json
{
  "type": "Feature",
  "stac_version": "1.1.0",
  "id": "<uuid>",
  "geometry": { "type": "Polygon", "coordinates": [...] },
  "bbox": [minx, miny, maxx, maxy],
  "properties": {
    "type": "dataset",
    "title": "...",
    "description": "...",
    "keywords": ["..."],
    "created": "ISO datetime",
    "updated": "ISO datetime",
    "crs": "EPSG:4326",
    "record_type": "vector_dataset|raster_dataset|vrt_dataset",
    "geometry_type": "POLYGON",
    "feature_count": 1234,
    "band_count": null,
    "license": "...",
    "source_organization": "...",
    "record_status": "published",
    "formats": ["application/geopackage+sqlite3", ...],
    "language": "en",
    "themes": [{"concepts": [{"id": "category"}]}],
    "contacts": [{"name": "...", "organization": "...", "role": "..."}],
    "datetime": "2024-01-01T00:00:00Z",
    "start_datetime": "...",
    "end_datetime": "...",
    "time": {"interval": [["...", ".."]]},
    "lineage": "...",
    "update_frequency": "...",
    "distributions": [{"type": "download", "format": "gpkg", "url": "..."}]
  },
  "links": [
    {"rel": "self", "href": "...", "type": "application/geo+json"},
    {"rel": "collection", "href": "...", "type": "application/json"},
    {"rel": "root", "href": "...", "type": "application/json"}
  ],
  "assets": {
    "download_gpkg": {"href": "...", "type": "...", "title": "...", "roles": ["data"]},
    "vector_tiles": {"href": "...", "type": "application/vnd.mapbox-vector-tile", "roles": ["visual"]},
    "ogc_features": {"href": "...", "type": "application/geo+json", "roles": ["data"]}
  },
  "stac_assets": {
    "data": {"href": "...", "type": "image/tiff; application=geotiff; profile=cloud-optimized", "roles": ["data"]}
  }
}
```

**Alignment observations:**
- `stac_version: "1.1.0"` is present on all records (added in quick task 260316-cyi)
- `datetime` / `start_datetime` / `end_datetime` follow STAC 1.1.0 rules
- `stac_assets` is a separate top-level key (not merged into `assets`)
- `assets` contains vector-specific download/tile/feature links for all record types (even raster)
- `properties.type` is always "dataset" (OGC Records spec)
- No `conformsTo` array on individual records
- No `proj:epsg`, `proj:shape`, `gsd`, or `bands` in record output (these exist on `RasterAsset.to_stac_properties()` but are not serialized into the OGC record)

### Per-Dataset OGC Features

The OGC Features router (`backend/app/ogc/router.py`) provides:
- `GET /collections/{dataset_id}` -- per-dataset collection metadata
- `GET /collections/{dataset_id}/items` -- paginated GeoJSON features
- `GET /collections/{dataset_id}/items/{feature_id}` -- single feature

These are vector-only endpoints. Raster datasets have no equivalent drill-down (no STAC Item endpoint for individual bands/tiles).

---

## 3. Current UI Search Experience

### Search Page (`SearchPage.tsx`)

- Full-text search bar at top
- Saved searches for authenticated users
- FilterPanel with filters and sort
- DatasetCard list with pagination

### Filters Available in UI

| Filter | Implementation |
|--------|---------------|
| Record type | ToggleGroup: All / Vector / Raster / VRT |
| Geometry type | Select dropdown (hidden when raster/VRT selected) |
| Location (bbox) | Map picker popover |
| Date range | Date from/to popover |
| Sort | Dropdown: relevance, date_added, name, last_updated |

**Not in UI:**
- Keyword facet filter (API supports it, UI does not expose)
- Source organization filter
- SRID filter
- Vintage (temporal extent) filter
- No faceted counts (e.g., "Vector (42) | Raster (15) | VRT (3)")

### DatasetCard Anatomy

Each card shows:
- Title (linked to `/datasets/{id}`)
- Description (2-line clamp)
- Status badge (draft/archived/deprecated, hidden when published)
- Type badge: VRT (violet), Raster (emerald), or geometry type (secondary)
- Band count (raster/VRT) or feature count (vector)
- CRS badge
- Source organization badge
- Quality score badge
- Keywords (first 3 + overflow count)
- Provenance line: "Updated by [user] . [relative time]"
- Right panel: quicklook thumbnail (raster/VRT) or BBox SVG preview (vector)

### Detail Pages

All dataset types route to `/datasets/{id}` via `DatasetPage.tsx`. The backend `GET /datasets/{id}` endpoint returns a `DatasetResponse` that includes:
- `record_type` discriminator
- `raster` sub-object (RasterMetadata) for raster/VRT
- `stac_assets` dict for STAC-aligned assets
- VRT-specific fields: `raster.vrt_type`, `raster.source_count`, `raster.resolution_strategy`, `raster.status`

A separate endpoint `GET /datasets/{id}/vrt-sources/` returns the ordered source list for VRT datasets.

---

## 4. Current Data Model

### Core Tables (catalog schema)

| Table | Purpose |
|-------|---------|
| `records` | Metadata record (title, summary, spatial_extent, temporal, visibility, record_type, search_vector) |
| `datasets` | Physical dataset (table_name, srid, geometry_type, feature_count, column_info, source_format) |
| `record_keywords` | Keywords (keyword, vocabulary_uri, keyword_type) |
| `record_contacts` | Contacts (role, name, email, organization) |
| `record_distributions` | Distribution links (type, format, url, media_type) |
| `raster_assets` | Raster/VRT physical metadata (asset_uri, epsg, band_count, width, height, dtype, vrt_type, status) |
| `dataset_assets` | STAC-aligned asset references (key, href, media_type, roles) |
| `vrt_source_links` | VRT-to-source dataset links (vrt_dataset_id, source_dataset_id, position) |
| `record_embeddings` | pgvector embeddings for semantic search |

### Record-Dataset Relationship

- `Record` 1:1 `Dataset` (via `record_id` FK on Dataset)
- `Record` 1:N `RecordKeyword`, `RecordContact`, `RecordDistribution`
- `Dataset` 1:1 `RasterAsset` (for raster/VRT)
- `Dataset` 1:N `DatasetAsset` (STAC assets)
- VRT Dataset N:M source Datasets via `vrt_source_links`

### Record Type Discriminator

`Record.record_type` is a CHECK constraint enum: `'vector_dataset', 'raster_dataset', 'vrt_dataset', 'map', 'service', 'collection'`

---

## 5. Identified Gaps

### 5.1 Standards Alignment Gaps

| Gap | Current State | Design Recommendation | Impact |
|-----|--------------|----------------------|--------|
| No OGC Records conformance declared | Conformance only lists Features/Common | Should declare Records Core | LOW -- declaration only |
| No `datetime` OGC query param | Only `date_from`/`date_to` on `created_at` and `vintage_start`/`vintage_end` | OGC Records mandates `datetime` for temporal filtering | MEDIUM -- machine clients expect it |
| Dual assets keys | `assets` (vector-centric) + `stac_assets` (raster) as separate keys | Single `assets` dict per STAC Item spec | MEDIUM -- confusing for STAC clients |
| No STAC projection/band properties on records | `RasterAsset.to_stac_properties()` exists but is not called in `dataset_to_ogc_record()` | `proj:epsg`, `proj:shape`, `gsd`, `bands` in properties | MEDIUM -- raster records lack key metadata in search results |
| No `conformsTo` on individual records | Not present | OGC Records spec allows per-record conformance | LOW |
| Vector assets on raster records | `_build_assets()` generates download_gpkg/shp/geojson for ALL records | Raster records should have raster-appropriate assets only | LOW -- confusing but not breaking |

### 5.2 Search/Discovery Gaps

| Gap | Current State | Design Recommendation | Impact |
|-----|--------------|----------------------|--------|
| No faceted counts | UI shows total count only | Type-by-type counts (Vector: 42, Raster: 15, VRT: 3) | MEDIUM -- helps users gauge catalog composition |
| No keyword facet in UI | API supports `keywords` filter but UI has no keyword picker | Keyword/tag facet selector | LOW-MEDIUM |
| No aggregation endpoint | No `/search/facets` or similar | Endpoint returning counts by record_type, geometry_type, keywords | MEDIUM |
| No `datetime` param | Temporal search uses custom `vintage_start`/`vintage_end` | Standard `datetime` param with interval syntax | MEDIUM |

### 5.3 UI/UX Gaps

| Gap | Current State | Design Recommendation | Impact |
|-----|--------------|----------------------|--------|
| No faceted count badges on type toggle | ToggleGroup shows All/Vector/Raster/VRT without counts | Badge counts next to each type | LOW-MEDIUM |
| Card preview not type-aware for vector | SVG bbox for vector, quicklook for raster | Consistent but still different -- this is actually good | N/A (already good) |
| Detail page consistency | All types go to same DatasetPage, but raster/VRT fields are conditional | Design doc suggests consistent layout with type-specific drill-down panels | MEDIUM |

### 5.4 VRT Lifecycle Gaps

| Gap | Current State | Design Recommendation | Impact |
|-----|--------------|----------------------|--------|
| No VRT regeneration endpoint | VRT created once at ingest | Regeneration when sources change, atomic swap | MEDIUM |
| No VRT generation tracking | `raster_assets.current_generation_id` and `last_regenerated_at` columns exist but no API/UI | Expose generation history, status | LOW |
| No VRT source health monitoring | No check if sources still exist/accessible | Source health status in VRT detail | LOW |

### 5.5 STAC Export Gaps

| Gap | Current State | Design Recommendation | Impact |
|-----|--------------|----------------------|--------|
| No dedicated STAC Item endpoint | Raster records returned as OGC Record Features | `/stac/items/{id}` returning proper STAC Item JSON | MEDIUM |
| No STAC Catalog/Collection endpoint | No STAC-specific collection wrapper | `/stac/` landing page, STAC Collection for raster subsets | MEDIUM |
| STAC extensions not declared | `stac_version` present but no `stac_extensions` array | Declare projection, bands, processing extensions | LOW |

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection of all files listed above
- `backend/app/search/router.py` -- search and OGC Records endpoints
- `backend/app/ogc/router.py` -- OGC Features endpoints
- `backend/app/search/service.py` -- search service and record serialization
- `backend/app/datasets/models.py` -- data model
- `backend/app/raster/models.py` -- RasterAsset and DatasetAsset models
- `frontend/src/components/search/` -- search UI components
- `frontend/src/stores/search-store.ts` -- search state management

## Metadata

**Confidence breakdown:**
- Current architecture: HIGH -- direct code inspection
- Gap identification: HIGH -- based on code vs design doc comparison
- Standards alignment: MEDIUM -- based on general OGC/STAC knowledge, not spec verification

**Research date:** 2026-03-16
**Valid until:** 2026-04-16
