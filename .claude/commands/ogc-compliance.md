# /ogc-compliance — Standards Conformance Audit

Audit GeoLens OGC API Features, OGC API Records, STAC, and DCAT endpoints for spec conformance. Standards compliance is the foundation of the FAIR positioning — a regression here is silent and blocks adoption by the exact gov/enterprise buyers GeoLens targets.

---

## INTAKE (Serial — do this first)

### Step 1: Map the standards surface

**Architecture note:** GeoLens standards code is split across two locations:
- `backend/app/standards/` — OGC Features router, STAC router, DCAT serialization service
- `backend/app/modules/catalog/` — OGC Records (served via the search infrastructure), DCAT endpoints (in the dataset export router)

The OGC router is mounted at the API root (`/api/`), not under `/api/ogc/`. STAC is at `/api/stac/`. DCAT is at `/api/datasets/dcat/`.

```bash
# Discover all standards-related modules (flat structure — no nested subdirs)
find backend/app/standards/ogc backend/app/standards/stac backend/app/standards/dcat -type f -name "*.py" 2>/dev/null | sort

# Read each standards router
cat backend/app/standards/ogc/router.py
cat backend/app/standards/stac/router.py

# DCAT has no router — endpoints live in the dataset export router, serialization in the service
cat backend/app/modules/catalog/datasets/api/router_export.py
cat backend/app/standards/dcat/service.py

# OGC Records are served through the catalog search infrastructure
cat backend/app/modules/catalog/search/router.py

# Read supporting files: OGC filtering (CQL2 Part 3), error handling (RFC 7807), utils
cat backend/app/standards/ogc/filtering.py
cat backend/app/standards/ogc/errors.py
cat backend/app/standards/ogc/utils.py

# STAC serializer (OGC Record → STAC Item transformation — where mapping bugs live)
cat backend/app/standards/stac/serializer.py

# Find schema/model definitions for standards responses
for f in backend/app/standards/ogc/schemas.py backend/app/standards/stac/schemas.py backend/app/modules/catalog/search/schemas.py; do
  echo "=== $f ==="
  cat "$f"
done
```

### Step 2: Read supporting infrastructure

```bash
# CRS handling
grep -rn "crs\|srid\|epsg\|proj\|transform\|reproject" backend/app/standards/ogc/ backend/app/standards/stac/ backend/app/processing/tiles/ --include="*.py" 2>/dev/null | grep -v __pycache__

# Content negotiation
grep -rn "content.type\|accept\|media_type\|application/json\|application/geo\|text/html\|f=json\|f=html" backend/app/standards/ogc/ backend/app/standards/stac/ backend/app/standards/dcat/ backend/app/modules/catalog/datasets/api/router_export.py --include="*.py" 2>/dev/null | grep -v __pycache__

# Pagination (include search router — it serves Records pagination)
grep -rn "limit\|offset\|next\|prev\|numberMatched\|numberReturned\|startIndex\|token" backend/app/standards/ogc/ backend/app/standards/stac/ backend/app/modules/catalog/search/ --include="*.py" 2>/dev/null | grep -v __pycache__

# Link relations
grep -rn "rel.*self\|rel.*alternate\|rel.*next\|rel.*prev\|rel.*collection\|rel.*items\|rel.*root\|rel.*conformance" backend/app/standards/ogc/ backend/app/standards/stac/ backend/app/standards/dcat/ backend/app/modules/catalog/search/ --include="*.py" 2>/dev/null | grep -v __pycache__

# Check for conformance class declarations (scoped to standards + search, not all of backend/)
grep -rn "conformsTo\|conformance\|/conf/" backend/app/standards/ backend/app/modules/catalog/search/ --include="*.py" 2>/dev/null | grep -v __pycache__

# Public URL and link building infrastructure
cat backend/app/standards/ogc/utils.py
cat backend/app/core/public_urls.py

# Language negotiation (Accept-Language → OGC Common Part 1)
grep -rn "accept.language\|parse_accept_language\|language" backend/app/standards/ogc/utils.py backend/app/standards/ogc/router.py backend/app/modules/catalog/search/router.py 2>/dev/null

# RFC 7807 Problem Detail error handling
grep -rn "problem.json\|ProblemDetail\|application/problem" backend/app/standards/ogc/errors.py 2>/dev/null
```

### Step 3: Check if a running instance is available

```bash
# Check if docker is running and geolens is up
# OGC landing page is at API root (/api/), not /api/ogc/
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/ 2>/dev/null || \
echo "NO_RUNNING_INSTANCE"
```

If a running instance is detected, subagents should perform **live validation** in addition to static analysis. If no instance is detected, perform static analysis only and note that live testing was skipped.

---

## SPEC REFERENCE (Embedded)

These are the mandatory conformance requirements for each standard. Use these as the checklist — do not soften or skip requirements.

### OGC API — Common (Part 1: Core)

**Spec:** OGC API - Common - Part 1: Core 1.0

GeoLens declares 4 OGC Common conformance classes. These are foundational requirements that Features and Records build on.

**Conformance classes declared:**
- `http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/core`
- `http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/landing-page`
- `http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/json`
- `http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/oas30`

**Requirements:**
- Landing page at `/` with `title`, `description`, and `links` (rel=self, rel=conformance, rel=data, rel=service-desc)
- JSON encoding of all responses
- OpenAPI 3.0 document linked from landing page with `rel=service-desc`
- Accept-Language negotiation (GeoLens implements this in `ogc/utils.py:parse_accept_language`)

---

### OGC API — Features (Part 1: Core)

**Spec:** OGC API - Features - Part 1: Core 1.0 (OGC 17-069r4)

**Required endpoints:**

**GeoLens architecture note:** The OGC router (`ogc_router`) is mounted at the API root — endpoints are at `/api/`, `/api/conformance`, etc. (NOT `/api/ogc/`). The per-dataset router (`ogc_features_router`) handles `/api/collections/{dataset_id}/...`. There is no dedicated `/collections` list endpoint on the OGC router — collection discovery happens through the catalog search infrastructure (`/api/search/`).

| Path | Method | Purpose | Required | GeoLens Status |
|------|--------|---------|----------|----------------|
| `/` | GET | Landing page | Yes | `ogc_router` |
| `/conformance` | GET | Conformance declaration | Yes | `ogc_router` |
| `/collections` | GET | List collections | Yes | Served by search router, not OGC router — verify spec compliance |
| `/collections/{collectionId}` | GET | Collection metadata | Yes | `ogc_features_router` |
| `/collections/{collectionId}/items` | GET | Feature list (GeoJSON FeatureCollection) | Yes | `ogc_features_router` |
| `/collections/{collectionId}/items/{featureId}` | GET | Single feature (GeoJSON Feature) | Yes | `ogc_features_router` |

**Required response properties:**

Landing page (`/`):
- `title` (string)
- `description` (string)
- `links` (array) with at minimum: `rel=self`, `rel=conformance`, `rel=data`

Conformance (`/conformance`):
- `conformsTo` (array of URIs)
- MUST include: `http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core`
- MUST include: `http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson`
- SHOULD include: `http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30` (if OpenAPI doc served)
- GeoLens also declares OGC Common Part 1 classes (see above) and CQL2/Part 3 classes (see below)

Collections list (`/collections`):
- `collections` (array of collection objects)
- `links` (array)
- Each collection: `id`, `title`, `links` (with `rel=self`, `rel=items`), `extent` (with `spatial.bbox` and `temporal.interval`)

Feature collection (`/collections/{id}/items`):
- Valid GeoJSON FeatureCollection
- `type: "FeatureCollection"`
- `features` (array)
- `numberMatched` (integer, total count)
- `numberReturned` (integer, items in response)
- `links` with `rel=self`, and `rel=next` if more items exist

Single feature (`/collections/{id}/items/{featureId}`):
- Valid GeoJSON Feature
- `type: "Feature"`
- `id`
- `geometry` (GeoJSON geometry or null)
- `properties` (object)
- `links` with `rel=self`, `rel=collection`

**Required query parameters on `/items`:**
- `limit` (integer, default 10, min 1, max 10000)
- `bbox` (comma-separated: minLon,minLat,maxLon,maxLat)
- `datetime` (RFC 3339, intervals with `/`)

**Required HTTP behaviors:**
- `Content-Type: application/geo+json` for feature responses
- `Content-Type: application/json` for non-feature JSON responses
- 200 for success, 400 for bad params, 404 for not found
- Error responses MUST use RFC 7807 Problem Detail format (`application/problem+json`) — GeoLens implements this in `ogc/errors.py`
- CORS headers (`Access-Control-Allow-Origin`)
- `Link` headers echoing navigation links

**CRS requirements (Part 2, if claimed):**
- Default CRS: WGS84 (`http://www.opengis.net/def/crs/OGC/1.3/CRS84`)
- `crs` parameter support
- `Content-Crs` response header
- `storageCrs` in collection metadata

---

### OGC API — Features (Part 3: Filtering / CQL2)

**Spec:** OGC API - Features - Part 3: Filtering 1.0 / CQL2

**GeoLens declares these conformance classes — they MUST be audited since they are actively claimed:**
- `http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/filter`
- `http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/features-filter`
- `http://www.opengis.net/spec/cql2/1.0/conf/cql2-text`
- `http://www.opengis.net/spec/cql2/1.0/conf/cql2-json`
- `http://www.opengis.net/spec/cql2/1.0/conf/basic-cql2`

**Implementation:** `backend/app/standards/ogc/filtering.py`

**Required elements:**
- `filter` query parameter accepting CQL2 expressions
- `filter-lang` query parameter (`cql2-text` or `cql2-json`)
- `/collections/{id}/queryables` endpoint returning a JSON Schema of filterable properties
- Queryable properties must map to actual database columns
- Spatial predicates (`s_intersects`, `s_within`) on geometry fields
- Comparison operators on scalar fields

**GeoLens queryables (verify these match `DatasetQueryables` schema):**
- `title`, `description`, `geometry_type`, `srid`, `source_organization`, `license`, `created`, `updated`, `data_vintage_start`, `data_vintage_end`

---

### OGC API — Records (Part 1: Core)

**Spec:** OGC API - Records - Part 1: Core 1.0 (OGC 20-004)

**Required endpoints:**

Same structure as Features, plus catalog-specific concerns:

| Path | Method | Purpose | Required |
|------|--------|---------|----------|
| `/` | GET | Catalog landing page | Yes |
| `/conformance` | GET | Conformance declaration | Yes |
| `/collections` | GET | Record collections (catalogs) | Yes |
| `/collections/{catalogId}` | GET | Catalog metadata | Yes |
| `/collections/{catalogId}/items` | GET | Record list | Yes |
| `/collections/{catalogId}/items/{recordId}` | GET | Single record | Yes |

**Conformance classes:**
- `http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/core`
- `http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/sorting` (if sort supported)
- `http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/json` (JSON encoding)

**Record schema (required properties):**
- `id` (string)
- `type` → `"Feature"`
- `conformsTo` (array, at record level)
- `time` (temporal extent — `date`, `timestamp`, or `interval`)
- `geometry` (GeoJSON geometry or null)
- `properties` containing at minimum:
  - `title` (string)
  - `description` (string)
  - `type` (resource type: dataset, service, etc.)
  - `created` (datetime)
  - `updated` (datetime)
  - `keywords` (array of strings)
  - `themes` (array: `concepts` + `scheme`)
  - `language` (string or object)
  - `contacts` (array with `name`, `roles`)
  - `formats` (array: media types of distributions)
  - `license` (string)
- `links` with typed link relations (`rel=self`, `rel=alternate`, etc.)
- `linkTemplates` (optional, for templated links)

**Required query parameters:**
- `q` (free-text search — keywords)
- `type` (filter by record type)
- `externalId` (filter by external identifier)
- All Features Core params: `limit`, `bbox`, `datetime`

**Sortables (if conformance class claimed):**
- `sortby` parameter with `+`/`-` prefix for direction
- `/collections/{id}/sortables` endpoint listing sortable properties

---

### STAC (SpatioTemporal Asset Catalog)

**Spec:** STAC Spec 1.0.0 / STAC API 1.0.0

**Required endpoints (STAC API):**

| Path | Method | Purpose | Required |
|------|--------|---------|----------|
| `/` | GET | STAC root catalog | Yes |
| `/conformance` | GET | Conformance | Yes (if OGC API compliant) |
| `/collections` | GET | List STAC collections | Yes |
| `/collections/{collectionId}` | GET | STAC collection | Yes |
| `/collections/{collectionId}/items` | GET | STAC items | Yes |
| `/collections/{collectionId}/items/{itemId}` | GET | Single STAC item | Yes |
| `/search` | GET/POST | Cross-collection search | Yes (if Item Search) |

**STAC Catalog root (`/`):**
- `type`: `"Catalog"`
- `id` (string)
- `stac_version`: `"1.0.0"`
- `description` (string)
- `links` with `rel=self`, `rel=root`, `rel=child` (for each collection), `rel=conformance`, `rel=search`, `rel=service-desc`
- `conformsTo` (array of URIs)

**STAC Collection:**
- `type`: `"Collection"`
- `id`, `title`, `description`
- `stac_version`: `"1.0.0"`
- `stac_extensions` (array of extension URIs)
- `license` (SPDX identifier or `"proprietary"`)
- `extent.spatial.bbox` (array of bboxes, first is overall)
- `extent.temporal.interval` (array of intervals)
- `links` with `rel=self`, `rel=root`, `rel=parent`, `rel=items`
- `keywords` (array)
- `providers` (array with `name`, `roles`, `url`)
- `summaries` (object with property summaries)
- `assets` (optional, collection-level assets)

**STAC Item:**
- `type`: `"Feature"`
- `stac_version`: `"1.0.0"`
- `stac_extensions` (array)
- `id` (string)
- `geometry` (GeoJSON geometry, required, null allowed)
- `bbox` (bounding box, required if geometry is not null)
- `properties`:
  - `datetime` (RFC 3339 or null)
  - If `datetime` is null: `start_datetime` AND `end_datetime` required
- `links` with `rel=self`, `rel=root`, `rel=parent`, `rel=collection`
- `assets` (object, at least one asset entry):
  - Each asset: `href` (required), `title`, `description`, `type` (media type), `roles` (array)
- `collection` (string, parent collection ID)

**STAC Item Search (`/search`):**
- GET with query params, POST with JSON body
- Parameters: `bbox`, `datetime`, `intersects` (GeoJSON geometry), `ids`, `collections`, `limit`
- Response: GeoJSON FeatureCollection with `type`, `features`, `links`, `context` (with `returned`, `matched`)

**Common STAC validation errors:**
- Missing `stac_version` on items/collections
- `bbox` missing when `geometry` is not null
- `datetime` null without `start_datetime`/`end_datetime`
- Invalid SPDX license identifiers
- Missing `rel=root` links
- `assets` as empty object (at least one asset expected)
- Collection `extent.temporal.interval` with wrong nesting (must be array of arrays)

---

### DCAT (Data Catalog Vocabulary)

**Spec:** DCAT 3.0 (W3C Recommendation) / DCAT-AP (Application Profile)

**GeoLens implements DCAT 3.0** (not 2.0). Key DCAT 3 additions over 2.0: `dcat:Resource` base class, `dcat:DataService` as first-class, `dcat:DatasetSeries`.

**Implementation:** Serialization is in `backend/app/standards/dcat/service.py`. Endpoints are in `backend/app/modules/catalog/datasets/api/router_export.py` (NOT under `backend/app/standards/dcat/`).

**Endpoints:**
- `GET /api/datasets/dcat/` — Full DCAT 3 JSON-LD Catalog (respects visibility)
- `GET /api/datasets/{dataset_id}/dcat/` — Single dataset DCAT 3 JSON-LD Record

**Required elements (DCAT 3.0):**

`dcat:Catalog`:
- `dct:title` (literal)
- `dct:description` (literal)
- `dcat:dataset` (links to datasets)
- `dct:publisher` (foaf:Agent)
- `dcat:themeTaxonomy` (recommended)
- `dct:issued` / `dct:modified` (recommended)
- `dct:language` (recommended)

`dcat:Dataset`:
- `dct:title` (literal, required)
- `dct:description` (literal, required)
- `dcat:distribution` (links to distributions)
- `dcat:keyword` (literal, recommended)
- `dcat:theme` (URI, recommended)
- `dct:publisher` (foaf:Agent)
- `dct:issued` / `dct:modified`
- `dct:spatial` (geographic coverage)
- `dct:temporal` (temporal coverage)
- `dct:identifier`
- `dcat:contactPoint` (vcard:Kind)

`dcat:Distribution`:
- `dcat:accessURL` or `dcat:downloadURL` (at least one required)
- `dct:format` or `dcat:mediaType`
- `dct:title` (recommended)
- `dct:license`

**Serialization:**
- JSON-LD with `@context` pointing to DCAT namespace
- OR RDF/XML, Turtle
- Content negotiation should support multiple serializations
- `@context` must include:
  - `dcat`: `http://www.w3.org/ns/dcat#`
  - `dct`: `http://purl.org/dc/terms/`
  - `foaf`: `http://xmlns.com/foaf/0.1/`

**GeoLens-specific DCAT checks:**
- Spatial coverage should use GeoJSON or WKT geometry, not just bbox text
- Temporal coverage should use `dcat:startDate`/`dcat:endDate` within `dct:PeriodOfTime`
- Distributions should link to OGC API endpoints (Features, tiles) and download URLs
- Theme vocabulary should reference an established taxonomy (GEMET, ISO topic categories)

---

## SUBAGENT DISPATCH (Parallel)

Run these 5 subagents in parallel. Subagent 1 covers OGC Common + Features + CQL2/Part 3 (all declared conformance classes). Subagent 2 covers Records (via the search infrastructure). Subagents 3-4 cover STAC and DCAT. Subagent 5 handles cross-cutting concerns.

### Subagent 1: OGC API Features & CQL2/Part 3 Conformance

**Goal:** Verify OGC API Features Part 1 (Core) conformance, CRS handling if Part 2 is claimed, and CQL2/Part 3 filtering (which IS claimed).

**Key files:**
- `backend/app/standards/ogc/router.py` — `ogc_router` (landing, conformance) + `ogc_features_router` (collections, items)
- `backend/app/standards/ogc/schemas.py` — response models
- `backend/app/standards/ogc/filtering.py` — CQL2 parsing, queryables
- `backend/app/standards/ogc/errors.py` — RFC 7807 Problem Detail
- `backend/app/standards/ogc/utils.py` — `build_url()`, `parse_accept_language()`
- `backend/app/core/public_urls.py` — `get_public_api_url()`

**Process:**

1. **Endpoint inventory:** Read `backend/app/standards/ogc/router.py`. Map every registered route against the required endpoints table above. Flag missing endpoints. Note: OGC router is at API root (`/api/`), not `/api/ogc/`.

2. **Response schema validation:** For each endpoint, read `backend/app/standards/ogc/schemas.py`. Check every required property listed in the spec reference above. Pay close attention to:
   - `links` arrays — every required `rel` value must be present
   - `numberMatched` / `numberReturned` on FeatureCollection responses
   - `Content-Type` headers (`application/geo+json` vs `application/json`)
   - GeoJSON validity (`type`, `geometry`, `properties` structure)

3. **Query parameter support:** Check that `limit`, `bbox`, and `datetime` are accepted on `/items` endpoints:
   ```bash
   grep -n "limit\|bbox\|datetime" backend/app/standards/ogc/router.py backend/app/standards/ogc/schemas.py 2>/dev/null
   ```
   Verify:
   - `limit` has default, min, and max validation
   - `bbox` is parsed as 4 or 6 floats (2D or 3D)
   - `datetime` supports single instants and intervals (`../` notation)

4. **Conformance declaration:** Check that `/conformance` exists and `conformsTo` includes the correct URIs. Flag any conformance class declared but not actually implemented. GeoLens declares 13 conformance classes including OGC Common Part 1, Features Part 1, CQL2, and Records — verify each is backed by implementation.

5. **CRS handling:** Check if CRS Part 2 is declared or implemented:
   ```bash
   grep -rn "crs\|CRS84\|EPSG\|Content-Crs\|storageCrs" backend/app/standards/ogc/ --include="*.py" | grep -v __pycache__
   ```
   If Part 2 is claimed: verify `crs` query parameter, `Content-Crs` header, `storageCrs` in collection metadata, and coordinate transformation logic.

6. **Pagination:** Verify `rel=next`/`rel=prev` link generation:
   - Links must use correct `limit` and `offset`/`startIndex`/token
   - `rel=next` must be absent when on last page
   - `numberMatched` must reflect total, not page count

7. **Error handling:**
   - Invalid `bbox` → 400 with RFC 7807 Problem Detail body (`application/problem+json`)
   - Non-existent collection → 404
   - Non-existent feature → 404
   - `limit` out of range → 400
   - Read `backend/app/standards/ogc/errors.py` and verify Problem Detail structure (title, status, detail fields)

8. **CQL2 / Part 3 Filtering (REQUIRED — conformance is claimed):**
   - Read `backend/app/standards/ogc/filtering.py`
   - Verify `filter` and `filter-lang` query parameters are accepted
   - Verify `/collections/datasets/queryables` endpoint exists and returns valid JSON Schema
   - Check that `DatasetQueryables` maps to actual database columns
   - Test CQL2-Text and CQL2-JSON parsing
   - Verify spatial predicates (`s_intersects`, `s_within`) work on geometry fields

9. **OGC Common Part 1 (REQUIRED — conformance is claimed):**
   - Landing page has `rel=service-desc` link to OpenAPI document
   - JSON encoding for all responses
   - Accept-Language negotiation: read `ogc/utils.py:parse_accept_language` and verify it's used in responses

10. **Live testing (if instance available):**
   ```bash
   # Landing page (OGC router is at API root, NOT /api/ogc/)
   curl -s http://localhost:8000/api/ | python3 -m json.tool

   # Conformance
   curl -s http://localhost:8000/api/conformance | python3 -m json.tool

   # Items with bbox filter (use a valid bbox for test data)
   curl -s "http://localhost:8000/api/collections/{test_collection}/items?limit=2&bbox=-180,-90,180,90"

   # Single feature
   curl -s "http://localhost:8000/api/collections/{test_collection}/items/{test_feature_id}"

   # CQL2 filtering
   curl -s "http://localhost:8000/api/collections/datasets/queryables" | python3 -m json.tool
   curl -s "http://localhost:8000/api/collections/datasets/items?filter=title%20LIKE%20'%25test%25'&filter-lang=cql2-text"

   # Error cases — verify RFC 7807 response body
   curl -s "http://localhost:8000/api/collections/nonexistent"
   curl -s "http://localhost:8000/api/collections/{test_collection}/items?limit=-1"
   curl -s "http://localhost:8000/api/collections/{test_collection}/items?bbox=invalid"
   ```

**Output:** Compliance table: Requirement | Status | Evidence | Notes

---

### Subagent 2: OGC API Records Conformance

**Goal:** Verify OGC API Records Part 1 (Core) conformance.

**Key files — Records is NOT in the OGC standards directory. It's served through the catalog search infrastructure:**
- `backend/app/modules/catalog/search/router.py` — Records search endpoint (`GET /api/search/`)
- `backend/app/modules/catalog/search/schemas.py` — `OGCRecordProperties`, `OGCRecordResponse`, `OGCFeatureCollectionResponse`
- `backend/app/modules/catalog/search/service.py` — `SearchFilters`, `search_datasets()`, `get_facet_counts()`
- Conformance is declared in `backend/app/standards/ogc/router.py` (the shared `/conformance` endpoint)

**Process:**

1. **Endpoint inventory:** Read `backend/app/modules/catalog/search/router.py`. Map routes against required endpoints. Records shares the Features structure but adds catalog-specific semantics. Note: the search router may use different URL patterns than the spec expects — verify the mapping.

2. **Record schema validation:** Read `backend/app/modules/catalog/search/schemas.py`. Check `OGCRecordProperties` and `OGCRecordResponse` for every required property from the spec reference. Records has a richer required property set than Features:
   - `properties.type` (resource type)
   - `properties.themes` (with `concepts` and `scheme`)
   - `properties.contacts` (with `name` and `roles`)
   - `properties.formats`
   - `properties.keywords`
   - `time` at the record level
   - `conformsTo` at the record level

3. **Search support:** Check `q` (free-text), `type`, and `externalId` query parameters:
   ```bash
   grep -n "\"q\"\|free.text\|type.*filter\|externalId\|external_id\|record_type\|sort_by" backend/app/modules/catalog/search/router.py backend/app/modules/catalog/search/schemas.py 2>/dev/null
   ```
   The `q` parameter is critical — it drives catalog discovery. Verify it maps to `_build_text_filter()` in `search/service.py` (7-clause OR: tsvector FTS, ILIKE on title/summary/keywords/contacts).

4. **Sortables (if claimed):**
   - Does `/collections/{id}/sortables` exist?
   - Does `sortby` parameter work with `+`/`-` direction prefix?
   - Check `SearchFilters.sort_by` in `search/service.py` for supported sort fields (relevance, title, created, updated)

5. **Conformance URIs:** Verify the Records-specific conformance classes are declared and implemented. The conformance endpoint is shared with Features at `GET /api/conformance`.

6. **Cross-reference with Features:** Records is built on Features Core but uses a separate router implementation. Verify that all Features Core requirements (links, pagination, error handling) also hold for Records responses from the search router. Check `OGCFeatureCollectionResponse` for `numberMatched`/`numberReturned`, proper link rels, etc.

7. **Live testing (if instance available):**
   ```bash
   # Records-specific search (search router, not OGC router)
   curl -s "http://localhost:8000/api/search/?q=elevation"
   curl -s "http://localhost:8000/api/search/?type=dataset"

   # Verify record properties
   curl -s "http://localhost:8000/api/search/?limit=1" | \
     python3 -c "import sys,json; fc=json.load(sys.stdin); r=fc.get('features',[{}])[0]; p=r.get('properties',{}); [print(f'MISSING: {k}') for k in ['title','description','type','created','updated','keywords','themes','contacts','formats','license'] if k not in p]"
   ```

**Output:** Compliance table + record schema coverage matrix

---

### Subagent 3: STAC Conformance

**Goal:** Verify STAC Catalog/Collection/Item schema conformance and STAC API endpoint compliance.

**Key files:**
- `backend/app/standards/stac/router.py` — All STAC endpoints (at `/api/stac/`)
- `backend/app/standards/stac/schemas.py` — STAC response models
- `backend/app/standards/stac/serializer.py` — OGC Record → STAC Item transformation (where mapping bugs live)

**Process:**

1. **Endpoint inventory:** Read `backend/app/standards/stac/router.py`. Map STAC routes against required endpoints. Check if `/search` (Item Search) is implemented. Note: GeoLens has an extra non-spec endpoint `GET /stac/items/{item_id}` (item without collection context) — flag for review but don't treat as a conformance failure.

2. **Schema validation — Catalog root:**
   - `type` must be `"Catalog"`
   - `stac_version` must be `"1.0.0"`
   - `links` must include `rel=self`, `rel=root`, `rel=child` for each collection
   - `conformsTo` must list STAC API conformance classes

3. **Schema validation — Collection:**
   - `type` must be `"Collection"`
   - `stac_version` present
   - `license` is valid SPDX identifier or `"proprietary"`
   - `extent.spatial.bbox` is array of arrays (first is overall)
   - `extent.temporal.interval` is array of arrays (NOT array of strings — common mistake)
   - `links` with all required rels
   - `summaries` present (recommended but important for discovery)

4. **Schema validation — Item:**
   - `stac_version` present on every item
   - `bbox` present when `geometry` is not null
   - `datetime` handling: if null, `start_datetime` AND `end_datetime` must both be in `properties`
   - `assets` is non-empty object with at least one asset having `href`
   - `collection` property matches parent collection ID
   - `links` include `rel=self`, `rel=root`, `rel=parent`, `rel=collection`

5. **Common STAC pitfalls — check each one explicitly:**
   ```bash
   # stac_version presence
   grep -rn "stac_version" backend/app/standards/stac/ --include="*.py" | grep -v __pycache__

   # bbox derivation from geometry
   grep -rn "bbox\|bounds\|envelope" backend/app/standards/stac/ --include="*.py" | grep -v __pycache__

   # Temporal extent nesting (must be array of arrays)
   grep -rn "temporal\|interval" backend/app/standards/stac/ --include="*.py" | grep -v __pycache__

   # Asset construction
   grep -rn "assets\|href\|download" backend/app/standards/stac/ --include="*.py" | grep -v __pycache__

   # License field
   grep -rn "license\|spdx" backend/app/standards/stac/ --include="*.py" | grep -v __pycache__
   ```

6. **STAC Item Search (if `/search` exists):**
   - GET and POST support
   - `bbox`, `datetime`, `intersects`, `ids`, `collections`, `limit` parameters
   - Response includes `context` with `returned` and `matched`
   - Cross-collection search works correctly

7. **Serializer audit:** Read `backend/app/standards/stac/serializer.py` — this is the OGC Record → STAC Item transformation layer. Verify:
   - `datetime` from record temporal extent maps correctly (null handling, start/end fallback)
   - `bbox` is derived from record spatial geometry
   - `assets` are populated from record distributions (href, media type, roles)
   - `collection` property matches the parent collection ID
   - No required STAC Item properties are dropped during transformation

8. **STAC Extensions:** List any `stac_extensions` declared on collections/items and verify the extension schemas are actually satisfied.

8. **Live testing (if instance available):**
   ```bash
   # Root catalog
   curl -s http://localhost:8000/api/stac/ | python3 -c "
   import sys,json; c=json.load(sys.stdin)
   assert c.get('type')=='Catalog', f'type={c.get(\"type\")}'
   assert c.get('stac_version')=='1.0.0', f'stac_version={c.get(\"stac_version\")}'
   rels=[l['rel'] for l in c.get('links',[])]
   for r in ['self','root']: assert r in rels, f'missing rel={r}'
   print('Root catalog: PASS')
   "

   # Validate an item
   curl -s "http://localhost:8000/api/stac/collections/{collection}/items?limit=1" | python3 -c "
   import sys,json; fc=json.load(sys.stdin)
   item=fc['features'][0] if fc.get('features') else None
   if not item: print('No items found'); sys.exit()
   errors=[]
   if 'stac_version' not in item: errors.append('missing stac_version')
   if item.get('geometry') and 'bbox' not in item: errors.append('geometry present but bbox missing')
   props=item.get('properties',{})
   if props.get('datetime') is None:
     if 'start_datetime' not in props: errors.append('datetime null, missing start_datetime')
     if 'end_datetime' not in props: errors.append('datetime null, missing end_datetime')
   if not item.get('assets'): errors.append('empty or missing assets')
   print('ERRORS:' + str(errors) if errors else 'Item validation: PASS')
   "
   ```

**Output:** Compliance table + list of STAC-specific pitfalls found/clear

---

### Subagent 4: DCAT Conformance

**Goal:** Verify DCAT 3.0 vocabulary compliance and serialization correctness.

**Key files — DCAT endpoints are NOT under `backend/app/standards/dcat/`:**
- `backend/app/standards/dcat/service.py` — `record_to_dcat()`, `catalog_to_dcat()` serialization
- `backend/app/modules/catalog/datasets/api/router_export.py` — DCAT endpoints (`/api/datasets/dcat/`, `/api/datasets/{id}/dcat/`)

**Process:**

1. **Endpoint and serialization discovery:**
   ```bash
   # DCAT endpoints are in the dataset export router, NOT in standards/dcat/
   cat backend/app/modules/catalog/datasets/api/router_export.py

   # DCAT serialization service
   cat backend/app/standards/dcat/service.py

   # Check serialization format
   grep -rn "json.ld\|jsonld\|turtle\|rdf.xml\|n3\|ntriples\|context\|@context" backend/app/standards/dcat/service.py backend/app/modules/catalog/datasets/api/router_export.py 2>/dev/null

   # Content negotiation
   grep -rn "accept\|content.type\|media_type\|produces" backend/app/standards/dcat/service.py backend/app/modules/catalog/datasets/api/router_export.py 2>/dev/null
   ```

2. **Catalog (`dcat:Catalog`) validation:**
   - `dct:title` present
   - `dct:description` present
   - `dcat:dataset` links to datasets
   - `dct:publisher` with `foaf:Agent` structure
   - `@context` includes correct namespace URIs

3. **Dataset (`dcat:Dataset`) validation:**
   - Required: `dct:title`, `dct:description`
   - Recommended: `dcat:keyword`, `dcat:theme`, `dct:publisher`, `dct:issued`, `dct:modified`
   - Spatial: `dct:spatial` should use GeoJSON or WKT, not just bbox text
   - Temporal: `dct:temporal` with `dcat:startDate`/`dcat:endDate` inside `dct:PeriodOfTime`
   - `dcat:distribution` links present
   - `dcat:contactPoint` with vcard structure

4. **Distribution (`dcat:Distribution`) validation:**
   - At least one of `dcat:accessURL` or `dcat:downloadURL`
   - `dct:format` or `dcat:mediaType` specified
   - Distributions should include OGC API endpoint URLs (Features items endpoint, tile endpoints)

5. **JSON-LD structural checks:**
   ```bash
   # Check @context completeness
   grep -A 20 "@context" backend/app/standards/dcat/service.py 2>/dev/null
   ```
   Required namespaces in `@context`:
   - `dcat: http://www.w3.org/ns/dcat#`
   - `dct` / `dcterms: http://purl.org/dc/terms/`
   - `foaf: http://xmlns.com/foaf/0.1/`
   - `vcard: http://www.w3.org/2006/vcard/ns#` (if contactPoint used)
   - `skos: http://www.w3.org/2004/02/skos/core#` (GeoLens uses SKOS for themes)
   - `dqv: http://www.w3.org/ns/dqv#` (GeoLens uses DQV for data quality)
   - `locn: http://www.w3.org/ns/locn#` or `dct:spatial` (for spatial coverage)

6. **DCAT-AP compatibility (check but don't require):**
   - `dcat:theme` uses EU vocabulary or GEMET
   - `adms:identifier` for additional identifiers
   - `dct:accrualPeriodicity` for update frequency
   Note as recommended improvements, not failures.

7. **Live testing (if instance available):**
   ```bash
   # DCAT catalog (all public datasets)
   curl -s http://localhost:8000/api/datasets/dcat/ | python3 -m json.tool

   # Single dataset DCAT record
   curl -s http://localhost:8000/api/datasets/{dataset_id}/dcat/ | python3 -m json.tool

   # With content negotiation:
   curl -s -H "Accept: application/ld+json" http://localhost:8000/api/datasets/dcat/
   ```

**Output:** Compliance table + JSON-LD context completeness matrix

---

### Subagent 5: Cross-Cutting Concerns

**Goal:** Audit shared infrastructure that affects all standards endpoints: CRS handling, content negotiation, pagination, link generation, error handling, spatial edge cases.

**Process:**

1. **CRS handling across all standards:**
   ```bash
   # How are coordinates served?
   grep -rn "CRS84\|4326\|srid\|transform\|reproject\|ST_Transform" backend/app/standards/ogc/ backend/app/standards/stac/ backend/app/standards/dcat/ backend/app/processing/tiles/ --include="*.py" | grep -v __pycache__

   # Is CRS84 (lon/lat) or EPSG:4326 (lat/lon) used? This is a common source of axis order bugs.
   grep -rn "axis.order\|lon.*lat\|lat.*lon\|x.*y.*order" backend/app/ --include="*.py" | grep -v __pycache__
   ```
   - OGC API uses CRS84 (lon,lat) by default, NOT EPSG:4326 (lat,lon)
   - Verify coordinate axis order is consistent across Features, STAC, and any bbox parameters
   - Check if PostGIS `ST_AsGeoJSON` outputs are in the correct axis order

2. **Content negotiation:**
   - Features: `application/geo+json` for features, `application/json` for metadata
   - STAC: `application/geo+json` for items, `application/json` for catalog/collection
   - DCAT: `application/ld+json` (JSON-LD), optionally `text/turtle`, `application/rdf+xml`
   - HTML representations (human-readable landing pages) — check `f=html` or `Accept: text/html`
   - OpenAPI document: linked from landing page with `rel=service-desc`

3. **Pagination consistency:**
   ```bash
   # Compare pagination implementations across standards
   grep -n "limit\|offset\|next\|prev\|page\|cursor\|token" backend/app/standards/ogc/router.py backend/app/standards/stac/router.py backend/app/modules/catalog/search/router.py 2>/dev/null | grep -v __pycache__
   ```
   - Same pagination strategy across Features, Records, and STAC?
   - `limit` default and max values consistent?
   - Off-by-one in `numberMatched` vs `numberReturned`?
   - Empty last page handling (does `rel=next` disappear correctly?)

4. **Link generation:**
   - Are link `href` values absolute URLs (required by OGC)?
   - Are `type` attributes set on links (e.g., `"type": "application/geo+json"`)?
   - Do links include `title` attributes for human readability?
   - Is the `self` link on every response correct (including query params)?
   - Base URL construction: does it respect `X-Forwarded-*` headers for reverse proxy deployments?
   ```bash
   # Link building utilities and public URL resolution
   cat backend/app/standards/ogc/utils.py
   cat backend/app/core/public_urls.py
   grep -rn "base_url\|request.url\|X-Forward\|forwarded\|proxy\|build_url\|get_public_api_url" backend/app/standards/ogc/ backend/app/standards/stac/ backend/app/standards/dcat/ backend/app/core/public_urls.py --include="*.py" | grep -v __pycache__
   ```

5. **Spatial edge cases:** Check if the codebase handles:
   - Antimeridian-crossing bboxes (e.g., `bbox=170,-45,-170,-30` where minLon > maxLon)
   - Empty geometry collections
   - Null geometries (valid in GeoJSON)
   - Mixed geometry types within a collection
   - Very large coordinate precision (PostGIS default is 15+ decimal places — standards clients may choke)
   - 3D coordinates (Z values) — does `bbox` support 6-element form?
   ```bash
   grep -rn "antimeridian\|dateline\|wrap\|null.*geometry\|empty.*geometry\|precision\|decimal_places\|ST_ReducePrecision\|ST_SnapToGrid" backend/app/ --include="*.py" | grep -v __pycache__
   ```

6. **CORS:**
   ```bash
   grep -rn "cors\|CORS\|Access-Control\|allow_origin" backend/app/ --include="*.py" | grep -v __pycache__
   ```
   OGC APIs MUST serve CORS headers for browser-based clients (web maps).

7. **OpenAPI document:**
   - Linked from landing page with `rel=service-desc`?
   - Accurately describes all standards endpoints?
   - FastAPI auto-generates this, but verify it's exposed at the standards path

**Output:** Cross-cutting findings table with severity ratings. Spatial edge case coverage matrix.

---

## SYNTHESIS (Serial — after all subagents complete)

### Scoring

Assign a conformance grade per standard and a cross-cutting grade:

| Standard | What it measures |
|----------|-----------------|
| **OGC API Common** | Landing page, conformance declaration, JSON encoding, OpenAPI, language negotiation |
| **OGC API Features** | Endpoint coverage, response schema, query params, CRS, pagination, RFC 7807 errors |
| **OGC API Features Part 3 / CQL2** | Filter param, filter-lang, queryables endpoint, CQL2-Text/JSON parsing, spatial predicates |
| **OGC API Records** | Endpoint coverage, record schema completeness, search support |
| **STAC** | Catalog/Collection/Item schema, Item Search, serializer mapping, extension handling |
| **DCAT** | Vocabulary completeness (DCAT 3.0), JSON-LD validity, serialization |
| **Cross-Cutting** | CRS consistency, content negotiation, pagination, links, edge cases, CORS |

Grading scale:
- **A** — Fully conformant. Would pass an OGC compliance test suite.
- **B** — Minor gaps. Core functionality works but missing recommended properties or edge cases.
- **C** — Significant gaps. Required properties missing or incorrect. Usable but non-conformant.
- **D** — Structural issues. Endpoints exist but responses substantially deviate from spec.
- **F** — Non-functional or missing entirely.

Compute **overall standards health** as the minimum of all grades (standards are pass/fail to consuming clients — the weakest link determines interoperability).

### Regression Risk Assessment

For each finding, note whether it's:
- **Stable** — Unlikely to regress without intentional changes
- **Fragile** — Could regress from routine development (e.g., schema changes, new fields)
- **At Risk** — Depends on external factors (e.g., PostGIS version, library updates)

### Action Items

Prioritized action list:

| Field | Description |
|-------|-------------|
| Priority | P0 (blocks launch — interop failure), P1 (blocks FAIR compliance claims), P2 (nice-to-have, improves robustness) |
| Action | Specific fix with file path |
| Standard | Which standard(s) affected |
| Effort | Hours estimate |
| Regression Risk | How likely this is to re-break |

Sort by priority, then effort.

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/ogc-compliance-{YYYYMMDD}.md`

### Report structure

```markdown
# OGC/STAC/DCAT Standards Compliance Audit — {YYYY-MM-DD}

## Scorecard
<!-- Grades table + overall standards health -->

## Executive Summary
<!-- 3-5 sentences: overall conformance posture, biggest risks, top fix -->

## 1. OGC API Common & Features
### 1a. Common Part 1 (Landing Page, JSON, OAS30, Language Negotiation)
### 1b. Endpoint Coverage
### 1c. Response Schema Compliance
### 1d. Query Parameter Support
### 1e. CRS Handling
### 1f. Pagination & Links
### 1g. RFC 7807 Error Handling
### 1h. CQL2 / Part 3 Filtering (Queryables, filter param, CQL2-Text/JSON)

## 2. OGC API Records
### 2a. Endpoint Coverage (search router mapping)
### 2b. Record Schema Completeness
### 2c. Search & Filtering (q, type, externalId)
### 2d. Sortables

## 3. STAC
### 3a. Catalog Root
### 3b. Collection Schema
### 3c. Item Schema
### 3d. Serializer Mapping (Record → STAC Item)
### 3e. Item Search
### 3f. Common Pitfalls Checklist

## 4. DCAT (3.0)
### 4a. Vocabulary Coverage
### 4b. JSON-LD Validity & Namespace Completeness
### 4c. Serialization & Content Negotiation
### 4d. DCAT-AP Compatibility

## 5. Cross-Cutting Concerns
### 5a. CRS & Axis Order Consistency
### 5b. Content Negotiation
### 5c. Pagination Consistency
### 5d. Link Generation (build_url, public_urls)
### 5e. Spatial Edge Cases
### 5f. CORS
### 5g. OpenAPI

## 6. Regression Risk Map
<!-- Table of fragile areas -->

## 7. Prioritized Action Items
<!-- Synthesized fixes table -->

## 8. Comparison to Prior Audit
<!-- If a previous ogc-compliance audit exists, diff findings -->
```

### Post-delivery

1. If `lessons.md` exists, append any reusable insights about OGC/STAC/DCAT implementation patterns discovered during this audit.
2. Print a one-line summary: overall grade + count of P0 issues.

---

## WHAT NOT TO FLAG

Avoid false positives on these:

- **Missing OGC API Features Part 2 (CRS)** — Only flag if the conformance class is declared. CRS support beyond CRS84 is optional.
- **Missing STAC extensions** — Extensions are optional. Only flag if `stac_extensions` lists an extension that isn't actually implemented.
- **DCAT-AP specific requirements** — DCAT-AP is a European profile. Flag as "recommended improvement" not "failure" unless GeoLens explicitly claims DCAT-AP conformance.
- **HTML representations** — Nice to have but not required by OGC Core. Flag as P2.
- **STAC `/search` endpoint** — Only required if the Item Search conformance class is declared. If not declared, note its absence as a recommendation, not a failure.
- **Advanced OGC filtering (CQL2, Part 3)** — GeoLens DOES declare CQL2/Part 3 conformance (5 classes). These MUST be audited. Only skip CQL2 features beyond what's declared (e.g., advanced CQL2 functions, spatial joins).
- **Tile endpoints** — These are a separate OGC API (Tiles). Out of scope for this audit unless they affect Features/Records/STAC responses.
- **Auth on standards endpoints** — Basic auth (e.g., public vs. internal visibility) on standards endpoints is fine. Only flag if auth completely blocks anonymous access to public datasets, which would break standards client compatibility.