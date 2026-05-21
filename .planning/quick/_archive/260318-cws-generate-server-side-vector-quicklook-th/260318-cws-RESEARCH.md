# Quick Task: Server-Side Vector Quicklook Thumbnails - Research

**Researched:** 2026-03-18
**Domain:** Vector geometry rendering to PNG, PostGIS, Pillow
**Confidence:** HIGH

## Summary

Vector datasets currently show a client-side SVG bbox preview (`BBoxPreview` component) while raster/VRT datasets show server-rendered PNG quicklooks. The goal is to generate actual geometry-rendering PNG thumbnails for vector datasets, matching the raster quicklook pattern.

**Primary recommendation:** Use Pillow ImageDraw (already a dependency) with PostGIS-queried simplified geometries. No new dependencies needed. Store quicklooks on `Dataset.quicklook_256_uri` (new column) and extend the existing `/api/datasets/{id}/quicklook` endpoint to serve vector quicklooks too.

## Current System Analysis

### 1. Client-Side BBoxPreview (Vector)
- **File:** `frontend/src/components/layout/BBoxPreview.tsx`
- Renders an SVG with simplified land mass outlines + a blue rectangle for the dataset bbox
- Used in `DatasetCard.tsx` line 224 as fallback when `hasQuicklook` is false
- Only shows bounding box, not actual geometry shapes

### 2. DatasetCard Preview Logic
- **File:** `frontend/src/components/search/DatasetCard.tsx`
- Line 22: `const hasQuicklook = isRaster || isVrt;` -- vectors explicitly excluded
- Line 34: Fetches `/api/datasets/${feature.id}/quicklook?size=256` for raster/VRT
- Line 208-225: Three-state rendering: quicklook image > loading spinner > error fallback > BBoxPreview
- **Change needed:** Set `hasQuicklook = true` for all record types (or check a quicklook_url field)

### 3. Raster Quicklook Pipeline
- **Generator:** `backend/app/raster/quicklook.py` -- `generate_quicklook(cog_path, size)` returns PNG bytes
- Uses Pillow (`PIL.Image`), rasterio, numpy
- Output: square PNG with aspect-preserved content on dark-neutral canvas `(40, 40, 50)`
- **Storage:** `RasterAsset.quicklook_256_uri` / `quicklook_512_uri` columns
- **Ingest hook:** `backend/app/ingest/tasks.py` lines 1167-1169 (raster), 1354-1357 (VRT)
- **Endpoint:** `backend/app/datasets/router.py` line 611 -- `get_quicklook()` reads from managed storage via `get_storage().get(uri)`
- Currently returns 400 for non-raster: line 636-640

### 4. Vector Data Access
- **Table structure:** Vector data stored in `data.{table_name}` with `geom` (original) and `geom_4326` (WGS84) columns
- `Dataset.table_name` at `backend/app/datasets/models.py` line 200
- `Dataset.geometry_type` at line 204 -- stores POINT, LINESTRING, POLYGON, MULTI* variants
- `Dataset.feature_count` at line 205

### 5. Vector Ingest Hook Point
- **File:** `backend/app/ingest/tasks.py`
- `ingest_file()` line 33: After dataset creation (line 176-192), before job completion (line 221)
- Best insertion point: after line 199 (`await session.flush()` after quality score), before line 201 (archive)
- Same pattern for `ingest_service()` starting line 254

## Recommended Approach: Pure Pillow + PostGIS

### Why Pillow ImageDraw (Option C)
| Option | New Deps | Complexity | Already Available |
|--------|----------|------------|-------------------|
| A: Matplotlib/Geopandas | matplotlib, geopandas (~100MB) | Low | NO |
| B: Pillow + cairosvg | cairosvg, cairo system lib | Medium | NO |
| **C: Pure Pillow** | **None** | **Medium** | **YES (Pillow, Shapely)** |
| D: GDAL render | None | High (no native render) | N/A |

**Available dependencies:** Pillow>=10.0.0, Shapely>=2.0 (both in `backend/pyproject.toml`)

### Rendering Pipeline

```python
# backend/app/vector/quicklook.py (new file)

async def generate_vector_quicklook(
    db: AsyncSession, table_name: str, geometry_type: str, size: int = 256
) -> bytes:
    """Generate a PNG thumbnail by querying simplified geometries from PostGIS."""

    # 1. Query simplified geometries as GeoJSON from PostGIS
    #    - ST_Simplify to reduce point count
    #    - LIMIT to prevent OOM on large datasets
    #    - Use geom_4326 for consistent coordinate space
    sql = text("""
        SELECT ST_AsGeoJSON(
            ST_Simplify(geom_4326, 0.01)
        ) AS geojson
        FROM data.:table_name
        WHERE geom_4326 IS NOT NULL
        LIMIT 5000
    """)

    # 2. Parse with Shapely, compute bounds
    from shapely.geometry import shape
    geometries = [shape(json.loads(row.geojson)) for row in results]

    # 3. Compute transform: geo coords -> pixel coords
    #    minx,miny,maxx,maxy -> 0,0,size,size with padding

    # 4. Draw with Pillow ImageDraw
    from PIL import Image, ImageDraw
    canvas = Image.new("RGB", (size, size), (40, 40, 50))  # dark neutral bg
    draw = ImageDraw.Draw(canvas)

    # For polygons: draw.polygon(coords, fill=blue_fill, outline=blue_stroke)
    # For lines: draw.line(coords, fill=blue_stroke, width=2)
    # For points: draw.ellipse(bbox, fill=blue_fill, outline=blue_stroke)

    # 5. Return PNG bytes
```

### Coordinate Transform Logic
```python
def geo_to_pixel(x, y, bounds, size, padding=16):
    """Transform WGS84 coordinates to pixel space."""
    minx, miny, maxx, maxy = bounds
    # Add padding
    effective = size - 2 * padding
    # Scale to fit, preserving aspect ratio
    dx = maxx - minx or 1
    dy = maxy - miny or 1
    scale = min(effective / dx, effective / dy)
    px = padding + (x - minx) * scale
    py = padding + (maxy - y) * scale  # y-inverted
    return (px, py)
```

### Styling
Match the frontend blue primary palette from `frontend/src/lib/map-colors.ts`:
- **Fill:** `#3b82f6` with 30% opacity -> RGB blend on dark bg: `(47, 75, 126)`
- **Stroke:** `#1d4ed8`, width 1-2px
- **Background:** `(40, 40, 50)` -- matches raster quicklook canvas
- **Points:** 4px radius filled circles
- **Lines:** 2px stroke, no fill
- **Polygons:** filled + stroked

### Geometry Type Handling
| Type | Draw Method | Notes |
|------|------------|-------|
| Point/MultiPoint | `draw.ellipse()` | 3-4px radius circles |
| LineString/MultiLineString | `draw.line()` | 2px width |
| Polygon/MultiPolygon | `draw.polygon()` | Fill + outline |
| GeometryCollection | Mixed | Handle each sub-geometry by type |

## Storage & Schema Changes

### New Column on Dataset Model
```python
# backend/app/datasets/models.py - add to Dataset class
quicklook_256_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
```

### Migration
```sql
ALTER TABLE catalog.datasets ADD COLUMN IF NOT EXISTS quicklook_256_uri TEXT;
```

### Endpoint Changes
**File:** `backend/app/datasets/router.py` line 611-665

Current logic checks `record_type in ("raster_dataset", "vrt_dataset")` and reads from `RasterAsset.quicklook_256_uri`. Extend to:
1. If raster/VRT: existing RasterAsset lookup
2. If vector: read from `Dataset.quicklook_256_uri`

### Frontend Changes
**File:** `frontend/src/components/search/DatasetCard.tsx` line 22

Change:
```typescript
const hasQuicklook = isRaster || isVrt;
```
To:
```typescript
const hasQuicklook = true; // all dataset types now have quicklooks
```

Or better: check `properties.quicklook_url` from the OGC response, which is already set for rasters at `backend/app/datasets/router.py:208`.

## Integration: Ingest Pipeline

### Hook Points (3 places)
1. **`ingest_file()`** line ~200 (after quality score, before archive): For file-based vector uploads
2. **`ingest_service()`** at equivalent point: For WFS/ArcGIS service imports
3. **On-demand generation** via endpoint: Fallback for existing datasets without quicklooks

### Recommended: Generate at ingest + lazy fallback
```python
# In ingest_file(), after quality score computation:
try:
    from app.vector.quicklook import generate_vector_quicklook
    ql_bytes = await generate_vector_quicklook(session, table_name, geometry_type, 256)
    storage = get_storage()
    ql_key = f"vectors/{dataset.id}/quicklook_256.png"
    await storage.put(ql_key, io.BytesIO(ql_bytes))
    dataset.quicklook_256_uri = ql_key
    await session.flush()
except Exception:
    pass  # Non-fatal, like raster VRT quicklooks
```

### Lazy endpoint fallback for existing datasets
In the quicklook endpoint, if `dataset.quicklook_256_uri` is None and record_type is vector:
1. Generate on the fly
2. Store to managed storage
3. Update the URI column
4. Return the image

## Performance Considerations

- **Feature limit:** Cap at 5000 features with `ST_Simplify(geom_4326, 0.01)` for reasonable rendering time
- **Large datasets:** For 100K+ feature datasets, use `TABLESAMPLE` or `ORDER BY random() LIMIT 5000`
- **Simplification tolerance:** 0.01 degrees (~1km) is good for 256px thumbnails
- **Generation time:** Expected <500ms for typical datasets (query + draw)

## Common Pitfalls

1. **Empty geometry:** Some features may have NULL geom_4326 -- always filter `WHERE geom_4326 IS NOT NULL`
2. **Single-point datasets:** A single point has zero extent -- add minimum extent padding
3. **Antimeridian crossing:** Geometries spanning the dateline may have extreme x-range -- detect and handle
4. **Table name injection:** Use parameterized queries; table names need format-string but should be validated (they're system-generated UUIDs)
5. **Pillow polygon winding:** Pillow doesn't care about winding order, but Shapely exterior coords should work fine

## File Inventory

| File | Action | Purpose |
|------|--------|---------|
| `backend/app/vector/quicklook.py` | **NEW** | Vector quicklook generation function |
| `backend/app/datasets/models.py:200` | ADD column | `quicklook_256_uri` on Dataset |
| `backend/alembic/versions/...` | **NEW** | Migration for new column |
| `backend/app/datasets/router.py:611` | MODIFY | Extend endpoint for vector quicklooks |
| `backend/app/ingest/tasks.py:~200` | MODIFY | Hook quicklook gen into file ingest |
| `backend/app/ingest/tasks.py:~350` | MODIFY | Hook quicklook gen into service ingest |
| `frontend/src/components/search/DatasetCard.tsx:22` | MODIFY | Enable quicklook for vectors |

## Sources

### Primary (HIGH confidence)
- `backend/app/raster/quicklook.py` -- existing quicklook generation pattern
- `backend/app/datasets/models.py` -- Dataset model, table_name field
- `backend/app/datasets/router.py:611-665` -- quicklook endpoint
- `backend/app/ingest/tasks.py` -- ingest pipeline hook points
- `frontend/src/components/search/DatasetCard.tsx` -- frontend preview logic
- `frontend/src/components/layout/BBoxPreview.tsx` -- current vector preview
- `frontend/src/lib/map-colors.ts` -- color constants (fill: #3b82f6, stroke: #1d4ed8)
- `backend/pyproject.toml` -- Pillow>=10.0.0, Shapely>=2.0 confirmed available
