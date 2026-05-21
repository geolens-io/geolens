# Gap Analysis: Record-First Discovery Architecture

**Date:** 2026-03-16 (revised)
**Scope:** GeoLens codebase vs. proposed mixed raster/vector search design document
**Confidence:** HIGH (direct codebase inspection of all referenced files)

---

## 1. Executive Summary

GeoLens has a strong foundation for record-first discovery: a unified search endpoint (`/search/datasets` and `/collections/datasets/items`) returns OGC Record-style GeoJSON Features across all modalities (vector, raster, VRT), with `record_type` as the discriminator. STAC fields (`stac_version`, `datetime`, `stac_assets`) were recently wired in. The UI supports mixed-modality search with type badges, quicklook thumbnails, and modality-aware filtering.

However, significant gaps remain. The search surface is still **dataset-centric, not truly record-centric** -- collections/workspaces/projects are not first-class search results in global discovery. Standards compliance is incomplete -- OGC Records conformance is not declared, the `datetime` query parameter is missing, and raster records carry vector-centric download assets. The dual `assets`/`stac_assets` pattern is the single most impactful cross-cutting issue, affecting OGC Record quality, STAC generation, frontend consumers, and machine interoperability. There is no faceted aggregation endpoint, no keyword facet UI, no dedicated STAC Item/Collection endpoints, no publication/security model for external STAC consumers, and the VRT lifecycle (regeneration, generation tracking) exists in schema but has no API or UI exposure.

Closing these gaps would elevate GeoLens from a pragmatically-aligned catalog to a formally interoperable one that machine clients can discover automatically and human users can navigate with richer faceted filters.

---

## 2. Methodology

This gap analysis compares the current GeoLens codebase against the recommendations in the ~76K character design document proposing a record-first discovery architecture aligned to OGC API Records, STAC 1.1, and OGC API Features.

**Files inspected:**
- Backend: `search/router.py`, `search/service.py`, `search/schemas.py`, `ogc/router.py`, `datasets/models.py`, `datasets/schemas.py`, `datasets/router.py`, `raster/models.py`, `ingest/router.py`
- Frontend: `search/FilterPanel.tsx`, `search/DatasetCard.tsx`, `stores/search-store.ts`
- Prior research: `260316-gas-RESEARCH.md`, `260316-cyi-SUMMARY.md`

Each gap is evaluated against the design doc's specific recommendations, with references to the actual code that would need to change.

---

## 3. Current Capabilities Summary

GeoLens already does well in several areas:

| Capability | Status | Evidence |
|---|---|---|
| Unified search across all modalities | Done | `search_datasets()` queries all record_types in one query |
| OGC Record-style GeoJSON output | Done | `dataset_to_ogc_record()` returns Feature with properties, links, assets |
| `record_type` discriminator | Done | CHECK constraint: `vector_dataset`, `raster_dataset`, `vrt_dataset` |
| Full-text search with ranking | Done | `ts_rank_cd` + ILIKE boosts + keyword/contact EXISTS |
| Hybrid semantic search (RRF) | Done | pgvector + RRF fusion when enabled |
| CQL2 filtering | Done | Part 3 support: `cql2-text` and `cql2-json` |
| Spatial filter (bbox) | Done | `ST_Intersects` on `Record.spatial_extent` |
| Type toggle filter (UI) | Done | `ToggleGroup`: All / Vector / Raster / VRT in `FilterPanel.tsx` |
| Type-specific badges on cards | Done | VRT (violet), Raster (emerald), geometry type (secondary) |
| Quicklook thumbnails for raster/VRT | Done | `DatasetCard.tsx` fetches `/datasets/{id}/quicklook?size=256` |
| STAC version on records | Done | `stac_version: "1.1.0"` on all records (quick task 260316-cyi) |
| STAC datetime rules | Done | `datetime`/`start_datetime`/`end_datetime` follow STAC 1.1.0 |
| STAC assets from DatasetAsset table | Done | `stac_assets` dict populated from `dataset_assets` rows |
| Visibility/RBAC filtering | Done | `apply_visibility_filter()` on all search paths |
| Saved searches | Done | CRUD endpoints + UI for authenticated users |
| Queryables schema (Part 3) | Done | `/collections/datasets/queryables` returns JSON Schema |
| Per-dataset OGC Features | Done | `/collections/{dataset_id}/items` for vector drill-down |

---

## 4. Gap Inventory

### 4.1 Standards Alignment (GAP-STD-*)

#### GAP-STD-01: OGC API Records Conformance Not Declared

- **Current State:** `/conformance` endpoint (`ogc/router.py:138-160`) declares OGC API Common and Features Parts 1/3. No Records conformance classes.
- **Target State:** Declare `http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/core`, `http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/record-core-queryables`, and `http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/json` conformance classes.
- **Priority:** Medium
- **Effort:** S (add 3 URIs to conformance list)
- **Dependencies:** None

#### GAP-STD-02: No `datetime` OGC Query Parameter

- **Current State:** Search endpoints accept `date_from`/`date_to` (filter on `Record.created_at`) and `vintage_start`/`vintage_end` (filter on `Record.temporal_start`/`temporal_end`). No standard `datetime` parameter with OGC interval syntax (`../2024-01-01`, `2023-01-01/2024-01-01`).
  - See `search/router.py:324-331` for current parameter definitions.
  - See `search/service.py:294-301` for how vintage filters apply to `Record.temporal_start`/`Record.temporal_end`.
- **Target State:** Support `datetime` parameter per OGC API Common temporal filtering: `datetime=2023-01-01/2024-01-01` targeting `Record.temporal_start`/`temporal_end`. Keep existing params for backward compatibility.
- **Priority:** Medium
- **Effort:** M (parse interval syntax, add to both search and collection items endpoints, update queryables)
- **Dependencies:** None

#### GAP-STD-03: Dual Assets Keys (`assets` + `stac_assets`)

- **Current State:** `dataset_to_ogc_record()` (`search/service.py:615-616`) emits two top-level dicts:
  - `assets`: Always includes vector download links (`download_gpkg`, `download_geojson`, `download_shp`, `download_csv`), vector tiles, and OGC Features -- even for raster/VRT records.
  - `stac_assets`: Contains STAC-aligned asset references from `DatasetAsset` table (COG files, VRTs, thumbnails).
- **Target State:** Single `assets` dict per STAC Item spec. For raster/VRT records, merge relevant entries from both sources. For vector records, keep download/tile/feature assets.
- **Priority:** High -- the single most impactful cross-cutting issue, affecting OGC Record quality, STAC generation, frontend consumers, and machine interoperability.
- **Effort:** L (refactor `_build_assets()` and `_build_stac_assets()` to produce a single dict, conditionally including entries based on `record_type`; audit and update all frontend consumers of `stac_assets`; migration/deprecation period for external clients; regression testing)
- **Dependencies:** None, but affects STAC export (GAP-STAC-01) and frontend consumers

#### GAP-STD-04: No STAC Projection/Band Properties on Records

- **Current State:** `RasterAsset.to_stac_properties()` (`raster/models.py:65-92`) can produce `proj:epsg`, `proj:shape`, `gsd`, and `bands`. This method is **never called** in `dataset_to_ogc_record()`. Instead, raw `band_count`, `epsg`, `res_x`, `res_y`, etc. are patched onto `properties` as flat keys in the search handler (`search/router.py:198-208`).
- **Target State:** Raster/VRT records include `proj:epsg`, `proj:shape`, `gsd`, `bands` in `properties` following STAC 1.1 common metadata format.
- **Priority:** Medium
- **Effort:** M (call `to_stac_properties()` during enrichment, merge into properties dict, update `OGCRecordProperties` schema)
- **Dependencies:** Needs RasterAsset data in the search flow (already fetched)

#### GAP-STD-05: Vector Assets Emitted for Raster Records

- **Current State:** `_build_assets()` (`search/service.py:400-437`) generates `download_gpkg`, `download_geojson`, `download_shp`, `download_csv` for ALL records regardless of type. Raster records get both these vector download links AND raster `stac_assets`.
- **Target State:** Raster/VRT records should only include raster-appropriate assets (COG download, tile endpoint, thumbnail). Vector records keep their current assets.
- **Priority:** Low
- **Effort:** S (conditionally build assets based on `record_type`)
- **Dependencies:** GAP-STD-03 (should be addressed together)

#### GAP-STD-06: No `stac_extensions` Array on Records

- **Current State:** `stac_version: "1.1.0"` is present (added in 260316-cyi) but no `stac_extensions` array declaring which STAC extensions the record conforms to.
- **Target State:** Raster/VRT records include `stac_extensions: ["https://stac-extensions.github.io/projection/v2.0.0/schema.json", ...]` when projection/band properties are present.
- **Priority:** Low
- **Effort:** S (conditional array based on which STAC properties are populated)
- **Dependencies:** GAP-STD-04 (extensions only meaningful once the STAC properties they claim to conform to actually exist on the record)

#### GAP-STD-07: No `conformsTo` on Individual Records

- **Current State:** Records have no per-record `conformsTo` array.
- **Target State:** OGC Records spec allows optional `conformsTo` on each record, indicating it conforms to both OGC Record and STAC Item schemas.
- **Priority:** Low
- **Effort:** S
- **Dependencies:** GAP-STD-01

#### GAP-STD-08: Offset-Based Pagination

- **Current State:** Both `/search/datasets` and `/collections/datasets/items` use `offset`/`limit` pagination (`search/router.py:334-335`). OGC Features `/collections/{id}/items` also uses offset pagination (`ogc/router.py:261`).
- **Target State:** Design doc recommends token/cursor-based pagination for stability under concurrent writes and for performance at depth. GeoLens already has keyset cursor pagination for dataset data rows (v11.0), but the catalog search itself still uses offset.
- **Priority:** Low
- **Effort:** L (implement cursor-based pagination for search results, significant refactor of pagination URLs and state management)
- **Dependencies:** None, but breaking change for API consumers

---

### 4.2 Search/Discovery (GAP-SEARCH-*)

#### GAP-SEARCH-01: No Faceted Count Aggregation

- **Current State:** Search returns `numberMatched` (total count) but no breakdown by facet. UI shows "127 datasets" but not "Vector (95) | Raster (22) | VRT (10)".
  - See `search/service.py:310-311` -- single `COUNT(*)` on filtered subquery.
  - See `FilterPanel.tsx:270-290` -- ToggleGroup shows static labels without counts.
- **Target State:** Return faceted counts (at minimum `record_type` counts) alongside search results, or via a separate aggregation endpoint. UI displays counts on type toggle buttons.
- **Priority:** High
- **Effort:** M (add GROUP BY record_type count query alongside main search, or separate `/search/facets` endpoint; update `OGCFeatureCollectionResponse` schema or create new response type; update `FilterPanel.tsx`)
- **Dependencies:** None

#### GAP-SEARCH-02: No Aggregation Endpoint

- **Current State:** No `/search/facets` or `/collections/datasets/aggregations` endpoint. The collection metadata endpoint (`_build_collection_metadata`) does aggregate `geometry_types`, `srids`, and `keywords` in summaries (`search/router.py:492-532`), but these are catalog-wide, not filtered by current search criteria.
- **Target State:** A dedicated `/search/facets` endpoint that accepts the same filter parameters as search and returns counts grouped by key facets (record_type, geometry_type, top keywords, source_organization). This should be the canonical contract -- embedding counts in the primary search response can be decided later to avoid coupling.
- **Priority:** Medium
- **Effort:** M (new endpoint + service function with GROUP BY queries, reusing existing filter logic)
- **Dependencies:** None

#### GAP-SEARCH-03: No Keyword Facet in UI

- **Current State:** API supports `keywords` query parameter (`search/router.py:315`). Backend filters by keyword match (`search/service.py:276-285`). Search store has `keywords: string[]` field (`search-store.ts:7`). However, the FilterPanel has **no keyword picker UI** -- the field is never exposed to users.
- **Target State:** Keyword/tag facet selector in FilterPanel, showing available keywords (optionally with counts) and allowing multi-select filtering.
- **Priority:** Medium
- **Effort:** M (fetch available keywords from aggregation or collection summaries, build multi-select combobox component, wire to search store)
- **Dependencies:** GAP-SEARCH-02 (benefits from aggregation endpoint for filtered counts)

#### GAP-SEARCH-04: No Source Organization Filter in UI

- **Current State:** API supports `source_organization` parameter. Search store has `source_organization` field. FilterPanel does not expose it.
- **Target State:** Source organization filter dropdown or combobox in FilterPanel.
- **Priority:** Low
- **Effort:** S (similar pattern to geometry type select, just needs UI wiring)
- **Dependencies:** None

#### GAP-SEARCH-05: No Vintage/Temporal Extent Filter in UI

- **Current State:** API supports `vintage_start`/`vintage_end`. Search store has these fields. FilterPanel only shows `date_from`/`date_to` (which filter on `created_at`, not temporal extent).
- **Target State:** Separate temporal extent filter or unified date filter that targets the dataset's temporal coverage rather than ingestion date.
- **Priority:** Low
- **Effort:** S (add date inputs targeting vintage params, or combine with GAP-STD-02 datetime param)
- **Dependencies:** GAP-STD-02 (datetime parameter unification)

#### GAP-SEARCH-06: No Search Ranking Boost Signals

- **Current State:** FTS ranking uses `ts_rank_cd` with fixed boosts for title (0.3), summary (0.12), keywords (0.1/0.08), contacts (0.05/0.04). No boost for record_status (published vs draft), workspace context, or catalog freshness.
- **Target State:** Design doc recommends: published > ready status boost, user workspace affinity, de-boost large inventories, freshness signal.
- **Priority:** Low
- **Effort:** M (add conditional rank boosts in `search_datasets()`)
- **Dependencies:** None

#### GAP-SEARCH-07: Collections Not First-Class Search Results

- **Current State:** Search endpoints (`/search/datasets`, `/collections/datasets/items`) return only datasets (vector, raster, VRT). Collections/workspaces/projects are not included in global discovery results. Collection metadata is available only via `/collections/datasets` (catalog-wide metadata) and individual collection endpoints, but collections never appear alongside datasets in search results.
- **Target State:** The design doc's core principle is "record-first discovery" where the primary search unit is the *record* -- and records include both datasets AND collections. For a mixed raster/vector catalog, especially with large imagery inventories, collections should be first-class search results (e.g., "2010 Statewide Imagery" collection appearing alongside individual datasets when a user searches "2010 imagery"). Collections would appear as record_type=`collection` with their own badges, spatial extent, and member count.
- **Design risk:** Collection results must not crowd out datasets. The ADR must define: (a) when collections appear in global search, (b) how they rank relative to datasets (default search should still feel dataset-first), (c) whether result-type grouping is used in the UI, and (d) whether collections are always shown or only on high-relevance/exact matches.
- **Priority:** High -- without this, the system is dataset-centric, not truly record-centric as the design doc proposes.
- **Effort:** L (requires extending search query to include collection records, adding `collection` as a record_type or separate entity in search results, updating UI cards to handle collection rendering, adding collection-specific drill-down, plus ranking strategy to prevent collection dominance)
- **Dependencies:** None, but fundamentally changes the search contract

---

### 4.3 UI/UX (GAP-UI-*)

#### GAP-UI-01: No Faceted Count Badges on Type Toggle

- **Current State:** `FilterPanel.tsx` ToggleGroup shows "All / Vector / Raster / VRT" as static labels (lines 278-289).
- **Target State:** Show counts: "All (127) / Vector (95) / Raster (22) / VRT (10)" -- updating as other filters change.
- **Priority:** Medium
- **Effort:** S (once GAP-SEARCH-01 provides counts, display them in badge components on toggle items)
- **Dependencies:** GAP-SEARCH-01

#### GAP-UI-02: Detail Page Modality Consistency

- **Current State:** All dataset types route to `/datasets/{id}` via `DatasetPage.tsx`. The `DatasetResponse` schema (`datasets/schemas.py:92-136`) includes `raster: RasterMetadata | None` and `stac_assets`, with VRT-specific fields nested under `raster` (vrt_type, source_count, resolution_strategy, status). The page conditionally renders raster/VRT sections.
- **Target State:** Design doc suggests consistent layout skeleton with type-specific drill-down panels: raster shows band info + tile preview, VRT shows source list + generation status, vector shows schema + feature preview.
- **Priority:** Medium
- **Effort:** M (refactor detail page to have a clear shared layout with pluggable type-specific panels)
- **Dependencies:** GAP-VRT-02 (generation tracking needs API exposure first)

#### GAP-UI-03: No SRID/CRS Filter in UI

- **Current State:** API supports `srid` parameter. Search store has `srid` field. FilterPanel does not expose it.
- **Target State:** CRS filter option (select from known SRIDs in catalog).
- **Priority:** Low
- **Effort:** S
- **Dependencies:** GAP-SEARCH-02 (aggregation for available SRIDs)

---

### 4.4 VRT Lifecycle (GAP-VRT-*)

#### GAP-VRT-01: No VRT Regeneration Endpoint

- **Current State:** VRTs are created once during ingest (`ingest/tasks.py:1287-1452`). The ingest flow creates a VRT file from source datasets, registers it as a RasterAsset, and inserts `vrt_source_links`. There is an endpoint to add individual sources to an existing VRT (`ingest/router.py:708-870`) which re-generates the VRT file, but no standalone "regenerate VRT" endpoint for when sources change upstream.
- **Target State:** `POST /datasets/{id}/vrt/regenerate` endpoint that rebuilds the VRT from current sources with atomic swap (new generation replaces old).
- **Priority:** Medium
- **Effort:** L (new endpoint, service function, GDAL VRT rebuild logic, atomic file swap, generation tracking; effort is borderline XL when accounting for rollback, status transitions, and regression tests)
- **Dependencies:** GAP-VRT-02 (generation tracking must exist first -- regeneration without a stable generation model leads to awkward retrofits around status, rollback, and UI display)

#### GAP-VRT-02: No VRT Generation Tracking API/UI

- **Current State:** `RasterAsset` model has `current_generation_id` and `last_regenerated_at` columns (`raster/models.py:62-63`), but these are **never populated** by any code path. No API endpoint exposes generation history. No UI shows generation status.
- **Target State:** Populate generation columns during VRT creation. API endpoint to view generation metadata. UI panel on VRT detail page showing current generation, last regeneration time, and source health. This establishes the generation model that regeneration (GAP-VRT-01) builds on top of.
- **Priority:** Medium
- **Effort:** M (populate columns during VRT creation, add API endpoint, add UI panel)
- **Dependencies:** None -- this is the foundation for VRT lifecycle

#### GAP-VRT-03: No VRT Source Health Monitoring

- **Current State:** `vrt_source_links` table links VRT to source datasets by ID and position. No check whether sources still exist, are accessible, or have changed since VRT creation.
- **Target State:** Health check that verifies each source dataset still exists and its raster asset is accessible. Surface status in VRT detail page.
- **Priority:** Low
- **Effort:** M (health check service, status caching, UI display)
- **Dependencies:** GAP-VRT-02

---

### 4.5 STAC Export (GAP-STAC-*)

#### GAP-STAC-01: No Dedicated STAC Item Endpoint

- **Current State:** Raster/VRT records are returned as OGC Record Features via `/collections/datasets/items/{id}` (`search/router.py:767-839`). There is no STAC-native endpoint that returns a proper STAC Item JSON with `stac_version`, `stac_extensions`, merged `assets`, and STAC-specific `links` (e.g., `rel: "root"` pointing to a STAC catalog).
- **Target State:** `GET /stac/items/{id}` returning a STAC 1.1 compliant Item JSON for raster/VRT records. Vector records would 404 or redirect to OGC Record.
- **Priority:** Medium
- **Effort:** L (new router, serializer that transforms OGC Record to STAC Item, merge assets, add STAC-specific links; validator-based acceptance tests; effort previously sized as M but borderline L when accounting for STAC schema validation and client compatibility testing)
- **Dependencies:** GAP-STD-03, GAP-STD-04, GAP-STD-06

#### GAP-STAC-02: No STAC Catalog/Collection Endpoint

- **Current State:** `/collections/datasets` returns OGC Collection metadata. No STAC-specific catalog landing page or STAC Collection wrapper.
- **Target State:** `GET /stac/` landing page (STAC Catalog) and `GET /stac/collections/rasters` (STAC Collection for raster/VRT subsets) with proper STAC conformance URIs and `rel: "child"` links.
- **Priority:** Medium
- **Effort:** L (new router with catalog/collection JSON, STAC search endpoint with `datetime`/`bbox`/`collections` params)
- **Dependencies:** GAP-STD-01, GAP-STAC-01

#### GAP-STAC-03: No STAC-Specific Conformance

- **Current State:** No STAC API conformance classes declared anywhere.
- **Target State:** STAC catalog declares conformance to STAC API Core, STAC Item Search, STAC Collection, etc.
- **Priority:** Low
- **Effort:** S (add conformance URIs once STAC endpoints exist)
- **Dependencies:** GAP-STAC-02

---

### 4.6 Publication & Security (GAP-PUB-*)

#### GAP-PUB-01: No Publication State Model for External Consumers

- **Current State:** Datasets have `visibility` (public/private/workspace) and RBAC filtering controls who sees what in the internal UI. However, there is no explicit "publication state" that governs what is eligible for external machine-client consumption (STAC export, OGC Records discovery). The implicit assumption is that visibility=public means externally discoverable, but this is not formalized.
- **Target State:** Explicit publication lifecycle: `draft` (work-in-progress, editors only) → `ready` (technically valid, usable internally) → `internal` (visible in GeoLens UI, not externally published) → `published` (eligible for STAC/OGC Records external endpoints). Optionally `deprecated` later. This determines what appears in `/stac/` endpoints and what asset URLs are exposed. A binary published/not-published flag is insufficient because: (a) a dataset can be technically valid but not externally publishable, (b) a VRT may be usable internally while regenerating or awaiting review, (c) vector datasets need the same lifecycle semantics as rasters.
- **Priority:** High -- building STAC endpoints without clear publication semantics risks exposing internal records or, conversely, having empty external catalogs because nothing is explicitly "published."
- **Effort:** M (add publication_state enum column, define state transition rules, filter external endpoints to `published` only, update internal search to respect all states)
- **Dependencies:** Should be decided before GAP-STAC-01

#### GAP-PUB-02: No Asset URL Security Strategy for External Endpoints

- **Current State:** Internal API returns direct file paths or internal URLs for assets. RBAC prevents unauthorized users from seeing records, but once a record is visible, asset URLs are exposed directly. This is acceptable for internal use where all users are authenticated, but problematic for STAC export where responses may be cached or shared.
- **Target State:** Explicit asset URL strategy covering all access contexts:
  - **GeoLens web app users:** Auth-gated direct URLs (current behavior, acceptable)
  - **STAC machine clients:** Signed URLs with expiry or proxy endpoint (responses may be cached/shared)
  - **Thumbnails vs full data assets:** Thumbnails can be public URLs for published records; full data assets require auth
  - **Background jobs / internal services:** Direct URLs behind service auth (no signing overhead)
  - **Internal vs published datasets:** Internal datasets use direct URLs; published datasets use signed/proxied URLs in STAC output
  Internal asset hrefs must never leak through STAC responses.
- **Priority:** Medium -- not urgent for Phase 1/2 work, but must be resolved before STAC endpoints go live.
- **Effort:** M (signed URL generation or proxy endpoint, asset URL rewriting in STAC serializer, per-context URL strategy)
- **Dependencies:** GAP-PUB-01 (need to know what's published before deciding how to expose it)

---

## 5. Cross-Cutting Concerns

### Assets Refactoring (GAP-STD-03 + GAP-STD-05 + GAP-STAC-01)
The dual `assets`/`stac_assets` pattern is the single most impactful cross-cutting issue. It affects:
- OGC Record output quality (standards alignment)
- STAC Item generation (can't just forward current output)
- Frontend consumers that read asset URLs
- Machine client interoperability

Recommended approach: Refactor `_build_assets()` to be modality-aware, accepting `record_type` and conditionally including entries. Merge DatasetAsset rows into the same dict. This unblocks GAP-STAC-01 and fixes GAP-STD-05 simultaneously. Given its cross-cutting impact, this should be treated as foundational work (Phase 2), not deferred cleanup.

### Cross-Modal Search Contract (GAP-SEARCH-07 + GAP-PUB-01)
The ADR must define a searchable record type taxonomy that makes clear what appears in global discovery and what does not:

**Top-level search results (records):**
- `collection` -- workspace/project/collection records
- `vector_dataset` -- vector datasets
- `raster_dataset` -- raster (COG-backed) datasets
- `vrt_dataset` -- virtual raster mosaics
- (future: `service` -- tile/WMS/etc. service endpoints)

**NOT top-level search results (by default):**
- Source COGs within a collection (components, not records)
- Individual vector features (belong in OGC Features drill-down, not catalog search)
- Internal processing artifacts (VRT XML files, thumbnails, metadata sidecars)

This exclusion list is as important as the inclusion list. Without it, different teams will make different assumptions about what "record" means.

### Collection Ranking (GAP-SEARCH-07)
Collections in discovery introduce a ranking problem. Default search should still feel dataset-first -- users searching "parcels" should see the parcels dataset before 5 collection/grouping records. The ADR should lock: when collections appear, how they rank relative to datasets, whether result-type grouping is used, and whether collections are always shown or only on high-relevance matches.

### Publication & Security (GAP-PUB-01 + GAP-PUB-02)
STAC endpoints expose records to machine clients outside GeoLens's UI-based auth flow. Before building STAC export, the project must define: what is publishable, what goes into public STAC, and how asset URLs are exposed safely. Otherwise technically correct STAC endpoints will have fuzzy publication semantics. The publication lifecycle must be richer than a binary flag -- at minimum: `draft` / `ready` / `internal` / `published`.

### STAC as Serialization Layer, Not Search Driver
STAC export should be a serialization/publication layer over GeoLens's internal search model. It should NOT drive internal search semantics. The architecture should be: GeoLens internal catalog model first, STAC serialization second. This distinction matters for vector and mixed-content UX -- STAC's raster-centric ecosystem should not dictate how vector datasets are discovered or presented in the GeoLens UI.

### Datetime Parameter Unification (GAP-STD-02 + GAP-SEARCH-05)
The current `date_from`/`date_to` (created_at) and `vintage_start`/`vintage_end` (temporal extent) split is confusing. Adding the standard `datetime` parameter targeting temporal extent would:
- Satisfy OGC API Records requirement
- Enable STAC search via same parameter
- Simplify the UI date filter (one clear "data coverage" date filter)

### Aggregation as Foundation (GAP-SEARCH-01 + GAP-SEARCH-02 + GAP-SEARCH-03 + GAP-UI-01)
Faceted counts enable multiple UI improvements. Building the `/search/facets` endpoint first unblocks keyword facet UI, type count badges, and potential CRS/organization facets. The initial contract should be a dedicated endpoint; embedding counts in the primary search response can be a later optimization to avoid premature coupling.

### VRT Dependency Ordering and Concurrency (GAP-VRT-02 → GAP-VRT-01 → GAP-VRT-03)
Generation tracking (GAP-VRT-02) must come before regeneration (GAP-VRT-01). Regeneration without a stable generation model leads to awkward retrofits around status, rollback, and UI display. The correct order: establish generation metadata/status first, then add manual regenerate on top of that, then source health monitoring.

The VRT lifecycle implementation must explicitly address:
- **Source ordering persistence:** `vrt_source_links.position` already exists but must be treated as deterministic for band-stack and overlap precedence
- **Mutation locking / serialization:** At most one active regeneration per VRT; concurrent requests must be rejected or queued
- **Generation status model:** Clear states: `active` / `regenerating` / `failed` / `superseded`
- **Failure rollback / atomic swap:** New VRT file built to temp path, validated, then swapped; previous generation preserved until swap confirmed
- **UI treatment during regeneration:** VRT detail page shows "regenerating" status, disables regenerate button, optionally shows progress

These are not optional nice-to-haves -- they are required for operational reliability. If they appear only in the gap analysis but not in Phase 4 acceptance criteria, they risk being underbuilt.

### Effort Sizing Reality Check
Many "M" items are borderline "L" once tests, migration, client-compatibility, and regression risk are accounted for. In particular: assets unification (GAP-STD-03), STAC export (GAP-STAC-01/02), and VRT regeneration (GAP-VRT-01) should be treated as larger-than-labeled.

---

## 6. Summary Matrix

| Gap ID | Title | Priority | Effort | Dependencies |
|---|---|---|---|---|
| GAP-STD-01 | OGC Records conformance declaration | Medium | S | None |
| GAP-STD-02 | `datetime` OGC query parameter | Medium | M | None |
| GAP-STD-03 | Dual assets keys merge | High | L | None |
| GAP-STD-04 | STAC projection/band properties on records | Medium | M | None |
| GAP-STD-05 | Vector assets on raster records | Low | S | GAP-STD-03 |
| GAP-STD-06 | `stac_extensions` array | Low | S | GAP-STD-04 |
| GAP-STD-07 | Per-record `conformsTo` | Low | S | GAP-STD-01 |
| GAP-STD-08 | Cursor-based catalog pagination | Low | L | None |
| GAP-SEARCH-01 | Faceted count aggregation | High | M | None |
| GAP-SEARCH-02 | Aggregation endpoint (`/search/facets`) | Medium | M | None |
| GAP-SEARCH-03 | Keyword facet UI | Medium | M | GAP-SEARCH-02 |
| GAP-SEARCH-04 | Source organization filter UI | Low | S | None |
| GAP-SEARCH-05 | Vintage/temporal extent filter UI | Low | S | GAP-STD-02 |
| GAP-SEARCH-06 | Search ranking boost signals | Low | M | None |
| GAP-SEARCH-07 | Collections as first-class search results | High | L | None |
| GAP-UI-01 | Faceted count badges on type toggle | Medium | S | GAP-SEARCH-01 |
| GAP-UI-02 | Detail page modality consistency | Medium | M | GAP-VRT-02 |
| GAP-UI-03 | SRID/CRS filter UI | Low | S | GAP-SEARCH-02 |
| GAP-VRT-01 | VRT regeneration endpoint | Medium | L | GAP-VRT-02 |
| GAP-VRT-02 | VRT generation tracking API/UI | Medium | M | None |
| GAP-VRT-03 | VRT source health monitoring | Low | M | GAP-VRT-02 |
| GAP-STAC-01 | Dedicated STAC Item endpoint | Medium | L | GAP-STD-03, GAP-STD-04, GAP-STD-06, GAP-PUB-01 |
| GAP-STAC-02 | STAC Catalog/Collection endpoint | Medium | L | GAP-STD-01, GAP-STAC-01 |
| GAP-STAC-03 | STAC-specific conformance | Low | S | GAP-STAC-02 |
| GAP-PUB-01 | Publication state model | High | M | None |
| GAP-PUB-02 | Asset URL security for external endpoints | Medium | M | GAP-PUB-01 |

**Totals:** 26 gaps identified (23 original + 3 new: GAP-SEARCH-07, GAP-PUB-01, GAP-PUB-02)
- High: 4 (GAP-STD-03, GAP-SEARCH-01, GAP-SEARCH-07, GAP-PUB-01)
- Medium: 12
- Low: 10

**Effort distribution:** S: 8, M: 10, L: 6, XL: 0
**Note:** Several M items are borderline L (assets unification, STAC export, VRT regeneration) when accounting for tests, migration, and client compatibility.
