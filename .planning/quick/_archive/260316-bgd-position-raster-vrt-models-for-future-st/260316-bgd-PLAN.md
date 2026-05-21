---
phase: 260316-bgd
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/raster/models.py
  - backend/alembic/versions/2026_03_16_stac_dataset_assets.py
  - backend/tests/test_stac_asset_model.py
autonomous: true
requirements: [STAC-01, STAC-02, STAC-03, STAC-04]

must_haves:
  truths:
    - "DatasetAsset model exists with STAC-aligned columns (key, href, media_type, roles)"
    - "Migration creates dataset_assets table and backfills from existing raster_assets"
    - "VRT datasets backfill with key='vrt', not key='data', per locked stable asset keys"
    - "RasterAsset.to_stac_properties() returns STAC-compatible dict with proj:epsg, proj:shape, gsd, bands"
    - "Existing raster_assets columns and code paths are unchanged"
  artifacts:
    - path: "backend/app/raster/models.py"
      provides: "DatasetAsset model + to_stac_properties method"
      contains: "class DatasetAsset"
    - path: "backend/alembic/versions/2026_03_16_stac_dataset_assets.py"
      provides: "Alembic migration with DDL + backfill"
      contains: "catalog.dataset_assets"
    - path: "backend/tests/test_stac_asset_model.py"
      provides: "Tests for DatasetAsset CRUD, to_stac_properties, and backfill assertions"
      contains: "test_to_stac_properties"
  key_links:
    - from: "backend/app/raster/models.py (DatasetAsset)"
      to: "catalog.datasets.id"
      via: "ForeignKey with CASCADE delete"
      pattern: "ForeignKey.*catalog\\.datasets\\.id.*CASCADE"
    - from: "backend/alembic/versions/2026_03_16_stac_dataset_assets.py"
      to: "catalog.raster_assets"
      via: "INSERT INTO dataset_assets SELECT FROM raster_assets"
      pattern: "INSERT INTO catalog\\.dataset_assets"
---

<objective>
Position Raster/VRT models for future STAC compliance by creating an asset-centric DatasetAsset table, adding a to_stac_properties() method to RasterAsset, and backfilling existing asset URIs into the new table.

Purpose: Decouple public asset references (href, media_type, roles) from internal processing fields on RasterAsset, establishing the foundation for future STAC API serialization.
Output: New DatasetAsset SQLAlchemy model, Alembic migration with backfill, to_stac_properties() method, integration tests.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260316-bgd-position-raster-vrt-models-for-future-st/260316-bgd-CONTEXT.md
@.planning/quick/260316-bgd-position-raster-vrt-models-for-future-st/260316-bgd-RESEARCH.md

@backend/app/raster/models.py
@backend/app/datasets/models.py
@backend/tests/test_raster_schema.py

<interfaces>
<!-- Existing models the executor needs -->

From backend/app/raster/models.py:
```python
class RasterAsset(Base):
    __tablename__ = "raster_assets"
    __table_args__ = (
        UniqueConstraint("dataset_id", name="uq_raster_assets_dataset"),
        {"schema": "catalog"},
    )
    # Key columns for backfill:
    dataset_id: Mapped[uuid.UUID]  # FK to catalog.datasets.id
    asset_uri: Mapped[str]         # Internal storage path -> becomes dataset_assets.href
    size_bytes: Mapped[int | None]
    quicklook_256_uri: Mapped[str | None]  # -> dataset_assets key="thumbnail"
    quicklook_512_uri: Mapped[str | None]  # -> dataset_assets key="overview"
    vrt_type: Mapped[str | None]           # NULL = COG, non-NULL = VRT
    # STAC-facing descriptive columns:
    epsg, crs_wkt, width, height, res_x, res_y, band_count, dtype, nodata, compression, band_info
```

From backend/app/datasets/models.py:
```python
class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (..., {"schema": "catalog"})
    id: Mapped[uuid.UUID]  # PK - DatasetAsset.dataset_id references this
```

Migration conventions (from existing migrations):
- revision ID format: "NNN_NN_description" (e.g., "180_01_gid_indexes")
- down_revision chains from latest: "180_01_gid_indexes"
- Uses raw SQL via op.execute() for DDL + data migrations
- Schema: "catalog"
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: DatasetAsset model, to_stac_properties method, and tests</name>
  <files>backend/app/raster/models.py, backend/tests/test_stac_asset_model.py</files>
  <behavior>
    - DatasetAsset model has columns: id (UUID PK), dataset_id (FK), key (String 50), href (Text), media_type (String 100 nullable), title (Text nullable), description (Text nullable), roles (ARRAY Text nullable), size_bytes (BigInteger nullable), created_at (DateTime TZ)
    - UniqueConstraint on (dataset_id, key) named "uq_dataset_assets_key"
    - Stable asset keys per CONTEXT.md locked decision: 'data' (COG), 'vrt' (VRT), 'thumbnail', 'overview', 'metadata'
    - RasterAsset.to_stac_properties() with full metadata returns dict with keys: proj:epsg, proj:wkt2, proj:shape, gsd, bands
    - to_stac_properties() with sparse metadata omits missing fields (no None values in output)
    - to_stac_properties() maps band_info entries to STAC 1.1 band format: data_type, nodata, name (from color_interp). Specifically: band_info JSON entries use keys: dtype (maps to data_type), nodata (maps to nodata), color_interp (maps to name)
    - DatasetAsset CRUD: insert with all fields, query by dataset_id, unique constraint rejects duplicate (dataset_id, key)
    - Backfill assertions: after running migration SQL, COG rows have key='data' with media_type='image/tiff; application=geotiff; profile=cloud-optimized' and roles=['data']; VRT rows have key='vrt' with media_type='application/x-gdal-vrt' and roles=['data','virtual']
  </behavior>
  <action>
1. Add DatasetAsset class to backend/app/raster/models.py AFTER the existing RasterAsset class. Use the schema from RESEARCH.md exactly:
   - `__tablename__ = "dataset_assets"`, schema "catalog"
   - UniqueConstraint("dataset_id", "key", name="uq_dataset_assets_key")
   - Columns: id (UUID PK gen_random_uuid), dataset_id (FK catalog.datasets.id CASCADE), key (String 50), href (Text), media_type (String 100 nullable), title (Text nullable), description (Text nullable), roles (ARRAY Text nullable), size_bytes (BigInteger nullable), created_at (DateTime TZ server_default now)
   - Import ARRAY from sqlalchemy.dialects.postgresql (already imported in datasets/models.py but needs adding to raster/models.py)

2. Add `to_stac_properties(self) -> dict` method to RasterAsset class, following the pattern from RESEARCH.md:
   - proj:epsg from self.epsg
   - proj:wkt2 from self.crs_wkt
   - proj:shape as [self.height, self.width] (STAC convention: rows, cols)
   - gsd as min(abs(res_x), abs(res_y))
   - bands array from self.band_info, mapping each entry: b["dtype"] -> "data_type", b["nodata"] -> "nodata", b["color_interp"] -> "name"
   - Only include fields that have non-None values. Return empty dict if no metadata.

3. Add comments to RasterAsset grouping columns as "# STAC-facing descriptive" vs "# Internal processing" per RESEARCH.md classification. Do NOT rename or remove any columns.

4. Create backend/tests/test_stac_asset_model.py with integration tests (follow test_raster_schema.py patterns):
   - test_dataset_asset_insert: Create Record+Dataset+DatasetAsset, verify round-trip via SELECT
   - test_dataset_asset_unique_key: Insert two assets with same (dataset_id, key), assert IntegrityError
   - test_dataset_asset_cascade_delete: Delete Dataset, verify DatasetAsset rows removed
   - test_to_stac_properties_full: Create RasterAsset with all metadata fields populated (including band_info with dtype, nodata, color_interp keys), call to_stac_properties(), assert exact output shape including bands mapped correctly
   - test_to_stac_properties_sparse: Create RasterAsset with only epsg set, assert output has only proj:epsg key
   - test_to_stac_properties_empty: Create RasterAsset with no metadata, assert empty dict returned
   - test_backfill_asset_keys: Simulate backfill by inserting DatasetAsset rows matching migration logic -- verify COG asset has key='data', media_type='image/tiff; application=geotiff; profile=cloud-optimized', roles=['data']; VRT asset has key='vrt', media_type='application/x-gdal-vrt', roles=['data','virtual']; thumbnail has key='thumbnail'; overview has key='overview'. This validates the migration constants without requiring Alembic execution in the test suite.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/backend && python -m pytest tests/test_stac_asset_model.py -x -q --timeout=30</automated>
  </verify>
  <done>DatasetAsset model defined in models.py, to_stac_properties method on RasterAsset returns correct STAC-compatible dicts, all 7 tests pass green (6 original + 1 backfill assertion test).</done>
</task>

<task type="auto">
  <name>Task 2: Alembic migration with DDL and backfill</name>
  <files>backend/alembic/versions/2026_03_16_stac_dataset_assets.py</files>
  <action>
Create Alembic migration file at backend/alembic/versions/2026_03_16_stac_dataset_assets.py:

- revision = "stac_dataset_assets"
- down_revision = "180_01_gid_indexes" (current head)
- Docstring: "Create dataset_assets table and backfill from raster_assets. Positions the data model for future STAC 1.1.0 compliance by separating public asset references from internal processing metadata."

upgrade():
1. CREATE TABLE catalog.dataset_assets with all columns matching the DatasetAsset model (id UUID PK DEFAULT gen_random_uuid(), dataset_id UUID NOT NULL FK, key VARCHAR(50) NOT NULL, href TEXT NOT NULL, media_type VARCHAR(100), title TEXT, description TEXT, roles TEXT[], size_bytes BIGINT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())
2. Add constraints: PK, FK to catalog.datasets(id) ON DELETE CASCADE, UNIQUE(dataset_id, key)
3. CREATE INDEX ix_dataset_assets_dataset_id ON catalog.dataset_assets(dataset_id)
4. Backfill COG data assets: INSERT from raster_assets WHERE asset_uri IS NOT NULL AND vrt_type IS NULL, key='data', media_type='image/tiff; application=geotiff; profile=cloud-optimized', roles=ARRAY['data']
5. Backfill VRT data assets: INSERT from raster_assets WHERE asset_uri IS NOT NULL AND vrt_type IS NOT NULL, key='vrt', media_type='application/x-gdal-vrt', roles=ARRAY['data','virtual'] (per CONTEXT.md locked decision: 'vrt' is a distinct stable asset key, NOT 'data')
6. Backfill thumbnails: INSERT from raster_assets WHERE quicklook_256_uri IS NOT NULL, key='thumbnail', media_type='image/png', roles=ARRAY['thumbnail']
7. Backfill overviews: INSERT from raster_assets WHERE quicklook_512_uri IS NOT NULL, key='overview', media_type='image/png', roles=ARRAY['overview']

downgrade():
1. DROP TABLE IF EXISTS catalog.dataset_assets

Use raw SQL via op.execute() for all DDL and DML (consistent with existing migration patterns). Do NOT drop or alter any columns on raster_assets.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && docker compose exec -T backend alembic upgrade head 2>&1 | tail -5</automated>
  </verify>
  <done>Migration applies cleanly against running database, dataset_assets table exists with backfilled rows -- COGs keyed as 'data', VRTs keyed as 'vrt', thumbnails as 'thumbnail', overviews as 'overview'.</done>
</task>

</tasks>

<verification>
1. All tests pass: `cd backend && python -m pytest tests/test_stac_asset_model.py -x -q --timeout=30`
2. Migration applies: `docker compose exec -T backend alembic upgrade head`
3. Verify backfill populated rows with correct keys: `docker compose exec -T db psql -U geolens -d geolens -c "SELECT key, media_type, count(*) FROM catalog.dataset_assets GROUP BY key, media_type"`
4. Verify VRT assets use key='vrt': `docker compose exec -T db psql -U geolens -d geolens -c "SELECT count(*) FROM catalog.dataset_assets WHERE key='vrt'"`
5. Existing raster tests still pass: `cd backend && python -m pytest tests/test_raster_schema.py -x -q --timeout=30`
6. No changes to existing raster_assets columns (verify with git diff on models.py that only additions were made)
</verification>

<success_criteria>
- DatasetAsset model in backend/app/raster/models.py with STAC-aligned columns
- to_stac_properties() on RasterAsset returns correct STAC property dict with band_info keys mapped correctly (dtype->data_type, nodata->nodata, color_interp->name)
- Alembic migration creates table and backfills COG (key='data'), VRT (key='vrt'), thumbnail, and overview assets
- 7 integration tests pass covering CRUD, constraints, property extraction, and backfill key assertions
- Zero changes to existing RasterAsset column names, types, or constraints
- Existing test_raster_schema.py continues to pass
</success_criteria>

<output>
After completion, create `.planning/quick/260316-bgd-position-raster-vrt-models-for-future-st/260316-bgd-SUMMARY.md`
</output>
