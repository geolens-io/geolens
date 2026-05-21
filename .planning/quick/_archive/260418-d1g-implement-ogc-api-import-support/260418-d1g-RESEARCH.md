# Quick Task: Implement OGC API Import Support - Research

**Researched:** 2026-04-18
**Domain:** OGC API Features service detection, GDAL OAPIF driver, import pipeline integration
**Confidence:** HIGH

## Summary

The existing service import pipeline (probe -> preview -> commit -> ingest) has a clean adapter pattern: `probe.py` orchestrates detection, adapter modules handle service-specific probing/enrichment, `preview.py` builds GDAL source strings, and `tasks_vector.py`/`tasks_common.py` run ogr2ogr. Adding OGC API Features requires a new adapter module, modifications to the detection orchestrator, GDAL source builder, service type resolver, DB constraint, and minor frontend label updates.

GDAL's OAPIF driver uses the `OAPIF:{url}` prefix convention, handles pagination and CRS negotiation automatically, and supports Bearer auth via the `GDAL_HTTP_HEADERS` env var -- identical to the existing WFS auth pattern. The OGC API landing page provides reliable detection signals (`conformsTo` array and `links` with `rel: "data"` or `rel: "conformance"`).

**Primary recommendation:** Follow the WFS adapter pattern exactly -- create `adapters/ogcapi.py` with `probe_ogcapi()` and `enrich_ogcapi_layers()`, then wire into the existing orchestration points.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Implementation Decisions
- **Features only** (OGC API -- Features Part 1). No Records, Tiles, or Coverages.
- **Landing page probe**: Fetch the root URL, check for JSON response with OGC conformance links (`/conformance` or `conformsTo` array).
- No URL pattern fast path -- rely on the JSON landing page structure for reliable detection.
- Detection order in `detect_service_type()`: try WFS fast path -> ArcGIS fast path -> OGC API landing page probe -> WFS slow path -> ArcGIS slow path.
- **One collection = one layer**: Map OGC API collections 1:1 to the existing layer picker UI.
- User selects a single collection to import, same flow as WFS/ArcGIS. No batch multi-collection import.

### Claude's Discretion
- Authentication: Support Bearer token (same as WFS) -- OGC API commonly uses OAuth2/Bearer.
- GDAL source string: Use `OAPIF:{url}` prefix for ogrinfo and ogr2ogr operations.
- source_format value: `ogcapi_features` to match GDAL convention.
- Pagination during probe: Fetch `/collections` endpoint, no pagination needed for collection listing.
</user_constraints>

## Adapter Interface Pattern

Each adapter must provide two async functions. Here is the contract derived from the WFS and ArcGIS adapters:

### 1. `probe_*()` -- Service detection
**Signature:** `async def probe_ogcapi(url: str, client: httpx.AsyncClient, token: str | None = None) -> dict | None`
**Returns:** `{"service_type": "OGC API Features", "layers": [{"name": ..., "title": ..., ...}]}` or `None` if not this service type.
**Pattern:** Fetch URL, parse response, validate it matches service type, extract layer list. [VERIFIED: codebase grep of wfs.py and arcgis.py]

### 2. `enrich_*_layers()` -- Layer metadata enrichment
**Signature:** `async def enrich_ogcapi_layers(url: str, layers: list[dict], client: httpx.AsyncClient, token: str | None = None) -> list[dict]`
**Returns:** Enriched layer dicts with `geometry_type` and `feature_count` filled in.
**Pattern:** Use `asyncio.Semaphore(5)` for concurrency, run `ogrinfo -json -so OAPIF:{url} {layer_name}` per layer, parse JSON output. On failure, keep `geometry_type=None, feature_count=None`. [VERIFIED: codebase grep of wfs.py lines 130-202]

## OGC API Landing Page Detection

### What to check [CITED: docs.ogc.org/is/17-069r4 + ogcapi-workshop.ogc.org]

1. **Request:** `GET {url}` with `Accept: application/json`
2. **Primary signal:** Response JSON has a `conformsTo` array containing URIs matching `ogcapi-features-1`. Key conformance URIs:
   - `http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core`
   - `http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson`
3. **Secondary signal:** Response JSON has a `links` array with an entry where `rel` is `"data"` or `"conformance"`.
4. **Fallback:** If no `conformsTo` at top level, fetch `{url}/conformance` and check the response for a `conformsTo` array.

### Detection function pseudocode

```python
async def probe_ogcapi(url: str, client: httpx.AsyncClient, token: str | None = None) -> dict | None:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Step 1: Fetch landing page
    resp = await client.get(url, headers=headers)
    data = resp.json()

    # Step 2: Check conformsTo (may be at landing page or /conformance)
    conforms_to = data.get("conformsTo", [])
    if not conforms_to:
        # Check links for conformance rel
        links = data.get("links", [])
        has_data_link = any(l.get("rel") == "data" for l in links)
        conformance_link = next((l for l in links if l.get("rel") == "conformance"), None)
        if conformance_link:
            conf_resp = await client.get(conformance_link["href"], headers=headers)
            conforms_to = conf_resp.json().get("conformsTo", [])
        elif not has_data_link:
            return None

    # Step 3: Validate OGC API Features conformance
    is_ogc_features = any("ogcapi-features" in uri for uri in conforms_to)
    if not is_ogc_features and not has_data_link:
        return None

    # Step 4: Fetch collections
    collections_url = url.rstrip("/") + "/collections"
    col_resp = await client.get(collections_url, headers=headers)
    collections = col_resp.json().get("collections", [])

    layers = [
        {"name": c["id"], "title": c.get("title", c["id"]), "crs": None}
        for c in collections
    ]
    return {"service_type": "OGC API Features", "layers": layers}
```

## OGC API `/collections` Response Structure [CITED: ogcapi-workshop.ogc.org]

```json
{
  "collections": [
    {
      "id": "collection_identifier",
      "title": "Human-readable title",
      "description": "Optional description",
      "extent": {
        "spatial": { "bbox": [[-180, -90, 180, 90]], "crs": "..." },
        "temporal": { "interval": [["...", "..."]] }
      },
      "itemType": "feature",
      "crs": ["http://www.opengis.net/def/crs/OGC/1.3/CRS84"],
      "storageCrs": "...",
      "links": [{ "rel": "items", "href": "...", "type": "..." }]
    }
  ]
}
```

**Mapping to LayerInfo:**
| OGC Field | LayerInfo Field | Notes |
|-----------|----------------|-------|
| `id` | `name` | Internal identifier for GDAL layer arg |
| `title` | `title` | Display name |
| N/A | `geometry_type` | Filled by ogrinfo enrichment |
| N/A | `feature_count` | Filled by ogrinfo enrichment |
| -- | `layer_id` | Set to collection `id` (string) |
| -- | `layer_type` | Default `"layer"` |

## GDAL OAPIF Driver Usage [VERIFIED: Context7 /websites/gdal_en_stable + GDAL docs search]

### Source string format
- **ogrinfo:** `ogrinfo -json -so OAPIF:{base_url} {collection_id}`
- **ogr2ogr:** `ogr2ogr -f PostgreSQL PG:... OAPIF:{base_url} {collection_id} [flags]`
- **Direct collection URL:** `OAPIF:{base_url}/collections/{collection_id}` (alternative, but using layer name arg is consistent with WFS pattern)

### Authentication
Same as WFS -- use `GDAL_HTTP_HEADERS` environment variable:
```python
env = {**os.environ, "GDAL_HTTP_HEADERS": f"Authorization: Bearer {token}"}
```
This is already the pattern used in `wfs.py:enrich_wfs_layers()` (line 151) and `ogr.py:run_ogr2ogr_service()` (line 528). [VERIFIED: codebase grep]

### Key driver behaviors
- Handles pagination automatically (default PAGE_SIZE=1000)
- Supports CRS negotiation (Part 2 extension, GDAL >= 3.7)
- Defaults to OGC:CRS84 (WGS84) when no storageCRS advertised
- Driver short name: `OAPIF` (formerly `WFS3` before GDAL 3.1)

## Files Requiring Changes

### Backend (7 files)

| File | Change | Details |
|------|--------|---------|
| `backend/app/modules/catalog/sources/adapters/ogcapi.py` | **NEW** | `probe_ogcapi()`, `enrich_ogcapi_layers()` |
| `backend/app/modules/catalog/sources/probe.py` | Modify | Import + wire `probe_ogcapi`/`enrich_ogcapi_layers` into `detect_service_type()`. Insert OGC probe between fast paths and slow paths per CONTEXT.md decision. Update `ServiceNotRecognized` message. |
| `backend/app/modules/catalog/sources/preview.py` | Modify | Add `OGC API Features` branch to `build_gdal_source()`: returns `(f"OAPIF:{base_url}", layer_name)`. Add OAPIF token env handling in `run_service_preview()`. |
| `backend/app/processing/ingest/tasks_common.py` | Modify | Add `OGC API Features` branch to `resolve_service_type()`: returns `("ogcapi_features", "ogcapi_features")`. |
| `backend/app/processing/ingest/ogr.py` | Modify | Add `ogcapi_features` to `run_ogr2ogr_service()` token handling (same as WFS: `GDAL_HTTP_HEADERS` env var). |
| `backend/app/modules/catalog/datasets/domain/models.py` | Modify | Add `'ogcapi_features'` to `chk_datasets_source_format` CHECK constraint. |
| `backend/alembic/versions/` | **NEW** | Migration to update the CHECK constraint on `datasets.source_format`. |

### Frontend (4 files)

| File | Change | Details |
|------|--------|---------|
| `frontend/src/components/import/ServiceUrlForm.tsx` | Modify | Add `OGC API Features` to supported types display (line ~287). |
| `frontend/src/components/import/WorkflowRail.tsx` | Modify | Update rail description copy (line 135). |
| `frontend/src/i18n/labels.ts` | Modify | Add `ogcapi_features: 'common:enums.sourceFormat.ogcapiFeatures'` to `SOURCE_FORMAT_KEYS`. |
| `frontend/src/i18n/locales/en/common.json` | Modify | Add `"ogcapiFeatures": "OGC API Features"` to `enums.sourceFormat`. |

### Other locale files (3 files, same pattern)
- `frontend/src/i18n/locales/fr/common.json`
- `frontend/src/i18n/locales/de/common.json`
- `frontend/src/i18n/locales/es/common.json`

## Key Integration Points

### 1. Detection order in `probe.py`

Per CONTEXT.md decision, insert between fast paths and slow paths:

```python
# Fast path: ArcGIS URL pattern
if _looks_like_arcgis(url):
    ...
# Fast path: WFS URL pattern
elif _looks_like_wfs(url):
    ...
else:
    # NEW: Try OGC API landing page probe first (before slow WFS/ArcGIS)
    ogcapi_result = await probe_ogcapi(url, client, token=token)
    if ogcapi_result is not None:
        enriched = await enrich_ogcapi_layers(url, ogcapi_result["layers"], client, token=token)
        return _build_ogcapi_response(ogcapi_result, enriched, url)

    # Slow path: try WFS then ArcGIS
    ...
```

### 2. `build_gdal_source()` in `preview.py`

Add branch:
```python
elif service_type.startswith("OGC API"):
    return (f"OAPIF:{base_url}", layer_name)
```

### 3. `resolve_service_type()` in `tasks_common.py`

Add branch:
```python
elif raw.startswith("OGC API"):
    return "ogcapi_features", "ogcapi_features"
```

### 4. `run_ogr2ogr_service()` in `ogr.py`

Extend the token env var logic from WFS-only to include OAPIF:
```python
if token and service_type in ("wfs", "ogcapi_features"):
    env = {**os.environ, "GDAL_HTTP_HEADERS": f"Authorization: Bearer {token}"}
```

### 5. DB migration

The `chk_datasets_source_format` CHECK constraint on `catalog.datasets` must be updated to include `'ogcapi_features'`:
```sql
ALTER TABLE catalog.datasets DROP CONSTRAINT chk_datasets_source_format;
ALTER TABLE catalog.datasets ADD CONSTRAINT chk_datasets_source_format CHECK (
    source_format IS NULL OR source_format IN (
        'geojson', 'shapefile', 'shp', 'gpkg', 'csv', 'kml', 'gml',
        'wfs', 'arcgis_featureserver', 'fgdb', 'created', 'geotiff',
        'ogcapi_features'
    )
);
```

## Common Pitfalls

### Pitfall 1: Content negotiation
**What goes wrong:** Many OGC API servers return HTML by default. Without `Accept: application/json`, the probe gets an HTML page.
**How to avoid:** Always send `Accept: application/json` header in the landing page and collections requests.

### Pitfall 2: Absolute vs relative conformance/collections URLs
**What goes wrong:** The `links` array may contain relative URLs (e.g., `/conformance`) instead of absolute URLs.
**How to avoid:** Use `urljoin(url, link_href)` when following links from the landing page.

### Pitfall 3: OAPIF driver not recognizing collection-scoped URLs
**What goes wrong:** Passing `OAPIF:{base_url}/collections/{id}` as both source and layer name causes double-pathing.
**How to avoid:** Use `OAPIF:{base_url}` as the source and pass the collection `id` as the layer name argument, consistent with the WFS pattern.

### Pitfall 4: Preview duplicate detection bypass
**What goes wrong:** The duplicate source check in `router.py` currently uses ArcGIS-specific URL normalization. OGC API URLs would hit the `except Exception: pass` fallback and skip duplicate detection.
**How to avoid:** Extend the duplicate detection block to handle OGC API service types, or at minimum ensure the `resolve_service_type()` call succeeds for OGC API so the check runs.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `numberMatched` in `/collections/{id}/items?limit=0` returns total feature count for enrichment | Adapter Interface | Would need alternate count strategy; ogrinfo fallback covers this |
| A2 | Most OGC API servers include `conformsTo` at the landing page level (not only at `/conformance`) | Detection | Lower detection rate; the `/conformance` fallback handles this |

## Sources

### Primary (HIGH confidence)
- Context7 `/websites/gdal_en_stable` - OAPIF driver syntax, open options, CRS support, authentication
- Codebase: `backend/app/modules/catalog/sources/adapters/wfs.py` - adapter pattern, enrichment pattern
- Codebase: `backend/app/modules/catalog/sources/adapters/arcgis.py` - adapter pattern
- Codebase: `backend/app/modules/catalog/sources/probe.py` - detection orchestration
- Codebase: `backend/app/modules/catalog/sources/preview.py` - GDAL source building
- Codebase: `backend/app/processing/ingest/tasks_common.py` - service type resolution
- Codebase: `backend/app/modules/catalog/datasets/domain/models.py` - CHECK constraint

### Secondary (MEDIUM confidence)
- [OGC API Features Part 1 Core spec](https://docs.ogc.org/is/17-069r4/17-069r4.html) - landing page and conformance structure
- [OGC API Workshop](https://ogcapi-workshop.ogc.org/api-deep-dive/features/) - collections response structure
- [GDAL OAPIF driver docs](https://gdal.org/en/latest/drivers/vector/oapif.html) - driver capabilities

### Tertiary (LOW confidence)
- None
