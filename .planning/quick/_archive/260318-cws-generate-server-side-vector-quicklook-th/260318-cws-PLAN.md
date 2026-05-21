---
phase: 260318-cws
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/vector/__init__.py
  - backend/app/vector/quicklook.py
  - backend/app/datasets/models.py
  - backend/alembic/versions/2026_03_18_cws_01_vector_quicklook_uri.py
  - backend/app/datasets/router.py
  - backend/app/ingest/tasks.py
  - frontend/src/components/search/DatasetCard.tsx
autonomous: true
requirements: [VECTOR-QUICKLOOK]

must_haves:
  truths:
    - "Vector datasets display rendered geometry thumbnails on search cards instead of bbox rectangles"
    - "New vector ingests auto-generate a 256px quicklook PNG stored in managed storage"
    - "Existing vector datasets generate quicklooks on-demand when the endpoint is hit"
    - "Quicklook endpoint returns PNG for vector, raster, and VRT dataset types"
  artifacts:
    - path: "backend/app/vector/quicklook.py"
      provides: "Vector geometry rendering to PNG via Pillow + Shapely"
      exports: ["generate_vector_quicklook"]
    - path: "backend/alembic/versions/2026_03_18_cws_01_vector_quicklook_uri.py"
      provides: "Migration adding quicklook_256_uri to catalog.datasets"
    - path: "backend/app/datasets/models.py"
      provides: "quicklook_256_uri column on Dataset model"
      contains: "quicklook_256_uri"
  key_links:
    - from: "backend/app/ingest/tasks.py"
      to: "backend/app/vector/quicklook.py"
      via: "generate_vector_quicklook() call after quality score"
      pattern: "generate_vector_quicklook"
    - from: "backend/app/datasets/router.py"
      to: "backend/app/vector/quicklook.py"
      via: "lazy generation fallback in get_quicklook endpoint"
      pattern: "generate_vector_quicklook"
    - from: "frontend/src/components/search/DatasetCard.tsx"
      to: "/api/datasets/{id}/quicklook"
      via: "hasQuicklook = true for all types"
      pattern: "hasQuicklook"
---

<objective>
Generate server-side vector quicklook thumbnails with actual geometry rendering using Pillow + Shapely (no new dependencies). Vector datasets will show real geometry shapes instead of the current client-side bbox rectangle preview.

Purpose: Visual parity between raster and vector dataset cards -- users see actual data shapes at a glance.
Output: Vector quicklook generator, DB migration, ingest hooks, endpoint extension, frontend enablement.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260318-cws-generate-server-side-vector-quicklook-th/260318-cws-RESEARCH.md

<interfaces>
<!-- Existing patterns to follow -->

From backend/app/raster/quicklook.py:
```python
def generate_quicklook(cog_path: str, size: int) -> bytes:
    """Returns PNG bytes. Dark-neutral canvas (40,40,50), aspect-preserved, square output."""
```

From backend/app/datasets/models.py (Dataset class, lines 190-220):
```python
class Dataset(Base):
    id: Mapped[uuid.UUID]
    record_id: Mapped[uuid.UUID]
    table_name: Mapped[str]
    geometry_type: Mapped[str | None]  # POINT, LINESTRING, POLYGON, MULTI*
    feature_count: Mapped[int | None]
    # No quicklook_256_uri yet -- must add
```

From backend/app/datasets/router.py (get_quicklook, line 611-665):
```python
@router.get("/{dataset_id}/quicklook")
async def get_quicklook(dataset_id, size=256, user=..., db=...):
    # Currently rejects non-raster with 400
    # Reads RasterAsset.quicklook_256_uri via storage.get()
    # Returns Response(content=data, media_type="image/png")
```

From backend/app/ingest/tasks.py:
```python
# ingest_file(): Hook after line 199 (quality score flush), before line 201 (archive)
# ingest_service(): Hook after line 397 (quality score flush), before line 399 (job complete)
```

From backend/app/storage (get_storage pattern):
```python
storage = get_storage()
await storage.put(key, file_obj)  # store
data = await storage.get(uri)      # retrieve
```

Alembic head: "188_01_vrt_generations"
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Vector quicklook generator + DB migration</name>
  <files>
    backend/app/vector/__init__.py,
    backend/app/vector/quicklook.py,
    backend/app/datasets/models.py,
    backend/alembic/versions/2026_03_18_cws_01_vector_quicklook_uri.py
  </files>
  <action>
1. Create `backend/app/vector/__init__.py` (empty).

2. Create `backend/app/vector/quicklook.py` with an async function:
```python
async def generate_vector_quicklook(
    db: AsyncSession, table_name: str, geometry_type: str, size: int = 256
) -> bytes:
```

Implementation details:
- Query simplified geometries from PostGIS: `SELECT ST_AsGeoJSON(ST_Simplify(geom_4326, 0.01)) AS geojson FROM data.{table_name} WHERE geom_4326 IS NOT NULL LIMIT 5000`. The table_name is system-generated (UUID-based), so use `text()` with string formatting for the table name only (not parameterizable in SQL). Validate table_name matches pattern `^[a-z0-9_]+$` before interpolation.
- Parse results with `shapely.geometry.shape(json.loads(row.geojson))`.
- Compute combined bounds from all geometries using `shapely.ops.unary_union(geoms).bounds`. If bounds have zero extent (single point), add 0.01 degree padding on each side.
- Create coordinate transform function `geo_to_pixel(x, y, bounds, size, padding=16)` that maps WGS84 coords to pixel space. Preserve aspect ratio: compute scale as `min(effective/dx, effective/dy)` where `effective = size - 2*padding`. Center the geometry in the canvas. Y is inverted (maxy maps to top).
- Create Pillow canvas: `Image.new("RGB", (size, size), (40, 40, 50))` (dark neutral, matches raster).
- Draw geometries based on type:
  - Polygon/MultiPolygon: `draw.polygon(coords, fill=(47, 75, 126), outline=(29, 78, 216))` -- fill is #3b82f6 at 30% on dark bg, outline is #1d4ed8.
  - LineString/MultiLineString: `draw.line(coords, fill=(29, 78, 216), width=2)`.
  - Point/MultiPoint: `draw.ellipse([cx-3, cy-3, cx+3, cy+3], fill=(47, 75, 126), outline=(29, 78, 216))`.
  - GeometryCollection: iterate sub-geometries and draw each by type.
  - For Multi* types, iterate `.geoms` and draw each sub-geometry.
  - For Polygons, draw exterior ring only (skip holes for thumbnails).
- Return PNG bytes via `BytesIO` + `canvas.save(buf, format="PNG", optimize=False)`.
- If query returns 0 geometries, return a blank dark canvas PNG.

3. Add column to `backend/app/datasets/models.py` Dataset class, after `quality_score_numeric` (line 216):
```python
quicklook_256_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
```

4. Create alembic migration `backend/alembic/versions/2026_03_18_cws_01_vector_quicklook_uri.py`:
- revision: `"cws_01_vector_quicklook_uri"`
- down_revision: `"188_01_vrt_generations"`
- upgrade: `ALTER TABLE catalog.datasets ADD COLUMN IF NOT EXISTS quicklook_256_uri TEXT;`
- downgrade: `ALTER TABLE catalog.datasets DROP COLUMN IF EXISTS quicklook_256_uri;`
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && python -c "from app.vector.quicklook import generate_vector_quicklook; print('import ok')" 2>&1 | head -5</automated>
  </verify>
  <done>Vector quicklook generator module exists with generate_vector_quicklook function. Dataset model has quicklook_256_uri column. Migration file exists and chains from head.</done>
</task>

<task type="auto">
  <name>Task 2: Wire into ingest pipeline + extend quicklook endpoint + enable frontend</name>
  <files>
    backend/app/ingest/tasks.py,
    backend/app/datasets/router.py,
    frontend/src/components/search/DatasetCard.tsx
  </files>
  <action>
1. **Ingest pipeline hooks** -- Add vector quicklook generation in both ingest paths, non-fatal (same pattern as raster):

In `ingest_file()`, after quality score flush (after line 199), before archive (line 201):
```python
# 8b2. Generate vector quicklook thumbnail
try:
    from app.vector.quicklook import generate_vector_quicklook
    from app.storage import get_storage
    ql_bytes = await generate_vector_quicklook(
        session, table_name, metadata.get("geometry_type", ""), 256
    )
    ql_storage = get_storage()
    ql_key = f"vectors/{dataset.id}/quicklook_256.png"
    await ql_storage.put(ql_key, io.BytesIO(ql_bytes))
    dataset.quicklook_256_uri = ql_key
    await session.flush()
except Exception:
    pass  # Non-fatal
```

In `ingest_service()`, after quality score flush (after line 397), before job completion (line 399):
Same block as above.

Ensure `import io` is present at the top of tasks.py (it likely is already; check and add if missing).

2. **Extend quicklook endpoint** in `backend/app/datasets/router.py` `get_quicklook()` (line 611-665):

Replace the record_type guard (lines 636-640) and raster-only logic with:
```python
record_type = getattr(dataset.record, "record_type", None)

if record_type in ("raster_dataset", "vrt_dataset"):
    # Existing raster/VRT path -- read from RasterAsset
    from app.raster.models import RasterAsset
    ra_result = await db.execute(
        select(RasterAsset).where(RasterAsset.dataset_id == dataset.id)
    )
    raster_asset = ra_result.scalar_one_or_none()
    if raster_asset is None:
        raise HTTPException(status_code=404, detail="Raster asset not found")
    uri = raster_asset.quicklook_256_uri if size <= 256 else raster_asset.quicklook_512_uri
elif record_type == "vector_dataset":
    uri = dataset.quicklook_256_uri
    # Lazy generation for existing datasets without quicklooks
    if uri is None:
        try:
            from app.vector.quicklook import generate_vector_quicklook
            ql_bytes = await generate_vector_quicklook(
                db, dataset.table_name, dataset.geometry_type or "", size
            )
            storage = get_storage()
            ql_key = f"vectors/{dataset.id}/quicklook_256.png"
            await storage.put(ql_key, io.BytesIO(ql_bytes))
            dataset.quicklook_256_uri = ql_key
            await db.commit()
            return Response(
                content=ql_bytes,
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=3600"},
            )
        except Exception:
            raise HTTPException(status_code=404, detail="Quicklook generation failed")
else:
    raise HTTPException(status_code=400, detail="Quicklook not available for this dataset type")
```

Keep the existing storage.get(uri) return path at the bottom for both raster and vector cached URIs. Move the `from app.raster.models import RasterAsset` import inside the raster branch (it's already there at line 619 -- move it into the if-block so it doesn't run for vectors). Add `import io` at the top of the file if not present.

3. **Frontend** -- In `frontend/src/components/search/DatasetCard.tsx` line 22, change:
```typescript
const hasQuicklook = isRaster || isVrt;
```
to:
```typescript
const hasQuicklook = true; // All dataset types now have server-rendered quicklooks
```
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && grep -n "hasQuicklook = true" frontend/src/components/search/DatasetCard.tsx && grep -n "vector_dataset" backend/app/datasets/router.py | head -5 && grep -n "generate_vector_quicklook" backend/app/ingest/tasks.py | head -5</automated>
  </verify>
  <done>Ingest pipeline generates quicklooks for new vector uploads. Quicklook endpoint serves vector quicklooks (cached or lazy-generated). Frontend requests quicklooks for all dataset types. Existing vector datasets get quicklooks on first card view.</done>
</task>

</tasks>

<verification>
1. Run alembic migration: `cd backend && alembic upgrade head` -- column added without error
2. Import check: `python -c "from app.vector.quicklook import generate_vector_quicklook"`
3. Frontend build: `cd frontend && npx tsc --noEmit` -- no type errors
4. Manual: browse search page -- vector dataset cards should show rendered geometry thumbnails instead of bbox rectangles (lazy generation on first view)
</verification>

<success_criteria>
- Vector datasets on the search page display actual geometry shapes as PNG thumbnails
- New vector ingests store quicklook PNGs in managed storage automatically
- Existing vector datasets generate quicklooks on-demand (lazy) on first endpoint hit
- No new Python dependencies added (Pillow + Shapely already available)
- Raster/VRT quicklook behavior unchanged
</success_criteria>

<output>
After completion, create `.planning/quick/260318-cws-generate-server-side-vector-quicklook-th/260318-cws-SUMMARY.md`
</output>
