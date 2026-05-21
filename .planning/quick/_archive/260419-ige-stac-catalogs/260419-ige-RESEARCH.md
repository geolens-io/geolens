# Quick Task 260419-ige: STAC Catalog Import — Research

**Date:** 2026-04-19

## 1. GeoLens Current Architecture (Relevant to STAC Import)

### Existing Ingestion Patterns
GeoLens has two service import flows that serve as direct analogs:

- **WFS import**: `POST /ingest/service/preview` → `POST /ingest/service/commit`
  - User provides URL, GeoLens fetches layer metadata, user confirms, background task imports
- **ArcGIS FeatureServer import**: Same endpoint pattern, different source detection

Both use a preview→commit two-phase pattern. STAC import should follow this convention.

### Data Model Mapping

| STAC Concept | GeoLens Concept | Notes |
|-------------|-----------------|-------|
| Catalog (root) | — | Not persisted; just a connection endpoint |
| Collection | Collection + record_type='collection' | Create/assign GeoLens Collection |
| Item | Record (record_type='raster_dataset') + Dataset | One Item = one Dataset record |
| Asset (COG) | DatasetAsset / source_url | Remote URL, Titiler serves directly |
| Item.geometry | Record.spatial_extent | GeoJSON → PostGIS POLYGON |
| Item.datetime | Record.temporal_start/end | Handle null datetime + start/end range |
| Item.properties.title | Record.title | Fallback to Item.id if no title |
| Collection.license | Record.license | SPDX identifier |
| Collection.providers | RecordContact rows | Map STAC roles to ISO CI_RoleCode |
| Collection.keywords | RecordKeyword rows | keyword_type='theme' |
| proj:epsg | Dataset.srid | From Projection extension |
| proj:shape | Raster width/height metadata | |
| eo:cloud_cover | Custom metadata / column_info | Store in JSONB |

### Titiler Remote COG Support
Titiler (already deployed) can serve remote COGs:
```
GET /cog/tiles/{z}/{x}/{y}?url=https://example.com/data.tif
GET /cog/info?url=https://example.com/data.tif
GET /cog/statistics?url=https://example.com/data.tif
```

This means STAC import doesn't need to download anything — just register the asset URL and point Titiler at it.

### Existing STAC Export
GeoLens already has a STAC API at `/stac/` that exports published raster datasets. Key files:
- `backend/app/standards/stac/router.py` — STAC API endpoints
- `backend/app/standards/stac/serializer.py` — transforms Records/Datasets to STAC Items

The serializer already understands the Record→STAC mapping in the export direction. The import direction is the inverse.

## 2. STAC API Integration

### pystac-client Usage
```python
from pystac_client import Client

client = Client.open("https://earth-search.aws.element84.com/v1/")

# List collections
collections = list(client.get_collections())

# Search items in a collection
results = client.search(
    collections=["sentinel-2-l2a"],
    bbox=[-73.21, 43.99, -73.12, 44.05],
    datetime="2023-01-01/2023-12-31",
    max_items=50
)
for item in results.items():
    # item.id, item.geometry, item.bbox, item.datetime
    # item.assets["visual"].href  -> COG URL
    pass
```

### Key Endpoints to Consume
- `GET /` — Landing page with conformance info
- `GET /collections` — List all collections
- `GET /collections/{id}` — Collection detail
- `GET /collections/{id}/items` — Browse items (paginated)
- `POST /search` — Cross-collection search (bbox, datetime, intersects, ids, collections)

### Auth Considerations
- Most public STAC APIs are unauthenticated
- Some (Planetary Computer) require signing asset URLs for download
- For import reference mode, auth isn't needed if Titiler can reach the COGs

## 3. Recommended Architecture

### Backend

**New module**: `backend/app/processing/ingest/stac.py`

Endpoints:
```
POST /ingest/stac/connect          — Validate STAC API URL, return landing page info
GET  /ingest/stac/collections      — List collections from connected STAC API
GET  /ingest/stac/collections/{id} — Collection detail with item count
POST /ingest/stac/search           — Search items (bbox, datetime, collection filters)
POST /ingest/stac/import           — Import selected items as GeoLens datasets
```

**Dependencies**: `pystac-client` (add to requirements)

**Import flow**:
1. Validate STAC API URL (check conformance, STAC version)
2. Fetch collections metadata
3. Search items within user-selected collection(s)
4. For each selected item:
   - Create Record (record_type='raster_dataset', source_format='stac')
   - Create Dataset with COG asset URL as source_url
   - Map metadata: bbox→spatial_extent, datetime→temporal, proj:epsg→srid
   - Create RecordContacts from STAC providers
   - Create RecordKeywords from STAC keywords
   - Optionally create/assign GeoLens Collection from STAC Collection
5. Return created dataset IDs

### Frontend

**New page**: `/catalog/import/stac` (or modal flow from Add Data)

**Components**:
- `StacConnectForm` — URL input with validation indicator
- `StacCollectionPicker` — Card grid of available collections (title, description, extent, thumbnail)
- `StacItemBrowser` — List/grid with:
  - Map showing item footprints (GeoJSON polygons)
  - Date range filter
  - Bbox filter (draw on map)
  - Thumbnail previews where available
  - Checkbox selection for bulk import
- `StacImportConfirm` — Preview selected items, confirm import, show progress

**Stepped wizard flow**: Connect → Browse Collections → Search Items → Import

## 4. Pitfalls & Gotchas

1. **STAC version variance**: Older catalogs may use STAC 0.9 or 1.0.0-beta. pystac-client handles version negotiation but some fields may be missing.

2. **Large catalogs**: Earth Search has millions of items. Always paginate, enforce max_items limits, require bbox or datetime filter before searching.

3. **Asset accessibility**: Some COGs are on private/requester-pays S3 buckets. Titiler needs read access. Surface clear errors when COGs are unreachable.

4. **Missing metadata**: Not all STAC Items have title, description, or even proj:epsg. Build robust fallbacks (Item.id as title, bbox center for preview, etc.).

5. **Rate limiting**: Some STAC APIs rate-limit. Use reasonable request pacing for bulk metadata fetching.

6. **GeoJSON geometry types**: STAC Item geometries can be complex MultiPolygons (satellite footprints). Store as-is in spatial_extent or simplify to envelope.

7. **Temporal edge cases**: Items may have `datetime: null` with `start_datetime`/`end_datetime` for date ranges. Handle both patterns.
