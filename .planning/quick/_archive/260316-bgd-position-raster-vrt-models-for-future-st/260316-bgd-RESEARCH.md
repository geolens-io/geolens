# Quick Task: Position Raster/VRT Models for Future STAC Compliance - Research

**Researched:** 2026-03-16
**Domain:** STAC 1.1.0 data model alignment, SQLAlchemy schema design
**Confidence:** HIGH

## Summary

The task is a backend-only schema refactor to position existing raster/VRT models for future STAC compliance. The existing `RasterAsset` model already contains most STAC-relevant metadata (epsg, bands, nodata, resolution, bbox via Record.spatial_extent). The main gap is that asset references (COG href, quicklook URIs, VRT file path) are embedded as columns on `RasterAsset` rather than being first-class rows in an asset table keyed by role.

**Primary recommendation:** Create a `dataset_assets` table with STAC-aligned columns (key, href, media_type, roles, title), backfill from existing `RasterAsset` URI columns, and add a `to_stac_properties()` method to `RasterAsset` that extracts descriptive metadata into a STAC-compatible dict. Map Collection = workspace with documented field correspondence.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Create a new `dataset_assets` table with STAC-aligned columns: key, media_type, roles[], href
- Each COG, VRT file, thumbnail, and quicklook becomes a separate asset row
- RasterAsset retains internal processing fields only (job status, generation IDs, internal paths)
- Stable asset keys: `data`, `vrt`, `thumbnail`, `overview`, `metadata`
- Column-level separation on the existing RasterAsset model (no new descriptive table)
- Add a `to_stac_properties()` method that extracts only descriptive fields
- Workspace = STAC Collection (natural mapping)
- Backend only -- no frontend changes

### Claude's Discretion
- Specific column types and constraints on dataset_assets
- Migration backfill strategy details
- to_stac_properties() return shape and implementation
- Whether to add provider/license fields to Collection model now or defer

### Deferred Ideas (OUT OF SCOPE)
- STAC API serialization endpoints
- Frontend surfacing of new asset data
- Full STAC temporal model
</user_constraints>

## STAC 1.1.0 Data Model Reference

### Asset Object (STAC spec)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| href | string | **YES** | URI to the asset (relative or absolute) |
| type | string | No (recommended) | Media type (e.g., `image/tiff; application=geotiff; profile=cloud-optimized`) |
| title | string | No | Display title |
| description | string | No | How asset was processed/created |
| roles | [string] | No (recommended) | Semantic roles for the asset |

**Standard roles:** `data`, `thumbnail`, `overview`, `metadata`. Custom roles permitted. Multiple roles per asset encouraged.

**Confidence:** HIGH -- sourced from STAC spec commons/assets.md

### Item Properties (STAC 1.1.0 common metadata)

In STAC 1.1.0, `bands` was promoted to common metadata (replacing both `eo:bands` and `raster:bands`). Key band-level fields:
- `data_type`, `nodata`, `statistics` (min/max/mean/stddev/valid_percent), `unit`

**Projection extension fields:** `proj:epsg`, `proj:shape` ([height, width]), `proj:transform` (6-element affine)

**Confidence:** HIGH -- STAC raster extension and projection extension docs

### Collection Required Fields

| Field | Type | Maps To |
|-------|------|---------|
| id | string | `collection.id` (UUID as string) |
| description | string | `collection.description` |
| license | string | SPDX identifier or "proprietary" -- **NOT on Collection model today** |
| extent.spatial.bbox | [[number]] | Computed from member datasets (already done) |
| extent.temporal.interval | [[string]] | Computed from member Record temporal_start/end |

**Optional but recommended:** `providers`, `keywords`, `summaries`, `title`

**Confidence:** HIGH -- STAC collection-spec

## Architecture: dataset_assets Table Design

### Recommended Schema

```python
class DatasetAsset(Base):
    __tablename__ = "dataset_assets"
    __table_args__ = (
        UniqueConstraint("dataset_id", "key", name="uq_dataset_assets_key"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(50), nullable=False)  # 'data', 'vrt', 'thumbnail', 'overview', 'metadata'
    href: Mapped[str] = mapped_column(Text, nullable=False)        # URI (local path, s3://, or public URL)
    media_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    roles: Mapped[list | None] = mapped_column(ARRAY(Text), nullable=True)  # ['data'], ['thumbnail', 'overview']
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

### Design Rationale

1. **`key` column (not just `roles`)**: STAC assets are keyed by a string in a dict (`"data": {...}`). The `key` is the stable lookup handle; `roles` is the semantic descriptor array. A COG asset has `key="data"` and `roles=["data"]`. A thumbnail has `key="thumbnail"` and `roles=["thumbnail", "overview"]`.

2. **`UniqueConstraint("dataset_id", "key")`**: One asset per key per dataset. Matches STAC's dict-keyed asset model.

3. **`media_type` not `type`**: Avoids Python keyword collision. Maps to STAC `type` on serialization.

4. **`size_bytes` on asset row**: Size is per-file, not per-dataset. Keeps file-level metadata with the file reference.

5. **No `storage_backend` column**: The href encodes this (s3:// vs local path). Simplifies the model. Storage resolution is already handled by the storage service layer.

### Standard Media Types

| Asset Key | Media Type | Roles |
|-----------|-----------|-------|
| `data` | `image/tiff; application=geotiff; profile=cloud-optimized` | `["data"]` |
| `vrt` | `application/x-gdal-vrt` or `application/xml` | `["data", "virtual"]` |
| `thumbnail` | `image/png` | `["thumbnail"]` |
| `overview` | `image/png` | `["overview"]` |
| `metadata` | `application/json` | `["metadata"]` |

## RasterAsset Column Classification

### STAC-Facing Descriptive (used by to_stac_properties)
- `epsg` -> `proj:epsg`
- `crs_wkt` -> `proj:wkt2`
- `width`, `height` -> `proj:shape`
- `res_x`, `res_y` -> `proj:transform` (partial)
- `band_count` -> len(bands)
- `band_info` -> `bands` (STAC 1.1 common metadata)
- `nodata` -> band-level nodata
- `dtype` -> band-level data_type
- `compression` -> informational, no direct STAC field

### Internal Processing (stays on RasterAsset only)
- `asset_uri` -- internal storage path (replaced by dataset_assets.href for public use)
- `sha256`, `source_sha256` -- integrity verification
- `driver` -- GDAL driver name
- `storage_backend` -- storage layer routing
- `cog_status` -- conversion tracking
- `quicklook_256_uri`, `quicklook_512_uri` -- internal paths (replaced by dataset_assets rows)
- `is_rotated` -- processing flag
- `vrt_type`, `resolution_strategy` -- VRT build parameters
- `status`, `current_generation_id`, `last_regenerated_at` -- VRT lifecycle tracking
- `ingested_at`, `created_at` -- internal timestamps

## to_stac_properties() Pattern

### Recommended: Method on Model

```python
# On RasterAsset
def to_stac_properties(self) -> dict:
    """Extract STAC-compatible properties from raster metadata."""
    props: dict = {}
    if self.epsg is not None:
        props["proj:epsg"] = self.epsg
    if self.crs_wkt:
        props["proj:wkt2"] = self.crs_wkt
    if self.width is not None and self.height is not None:
        props["proj:shape"] = [self.height, self.width]
    if self.res_x is not None and self.res_y is not None:
        # Simplified affine (no rotation): [res_x, 0, origin_x, 0, -res_y, origin_y]
        # Origin not stored -- omit transform, provide resolution only
        props["gsd"] = min(abs(self.res_x), abs(self.res_y))

    # Bands (STAC 1.1 common metadata format)
    if self.band_info:
        bands = []
        for b in self.band_info:
            band = {}
            if b.get("dtype"):
                band["data_type"] = b["dtype"]
            if b.get("nodata") is not None:
                band["nodata"] = b["nodata"]
            if b.get("color_interp"):
                band["name"] = b["color_interp"]
            bands.append(band)
        if bands:
            props["bands"] = bands

    return props
```

**Why method on model, not separate serializer:** The model already has all the data. A method is discoverable, testable, and avoids import gymnastics. Future STAC API endpoint can call `raster_asset.to_stac_properties()` directly. If serialization grows complex, extract to a dedicated module later.

## Migration Strategy

### Alembic Migration Plan

1. **Create `dataset_assets` table** with the schema above
2. **Backfill from RasterAsset** using a data migration:

```python
def upgrade():
    # Create table
    op.execute("""
        CREATE TABLE catalog.dataset_assets (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            dataset_id UUID NOT NULL,
            key VARCHAR(50) NOT NULL,
            href TEXT NOT NULL,
            media_type VARCHAR(100),
            title TEXT,
            description TEXT,
            roles TEXT[],
            size_bytes BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_dataset_assets PRIMARY KEY (id),
            CONSTRAINT fk_da_dataset FOREIGN KEY (dataset_id)
                REFERENCES catalog.datasets(id) ON DELETE CASCADE,
            CONSTRAINT uq_dataset_assets_key UNIQUE (dataset_id, key)
        )
    """)
    op.execute(
        "CREATE INDEX ix_dataset_assets_dataset_id ON catalog.dataset_assets (dataset_id)"
    )

    # Backfill COG assets
    op.execute("""
        INSERT INTO catalog.dataset_assets (dataset_id, key, href, media_type, roles, size_bytes)
        SELECT dataset_id, 'data', asset_uri,
               'image/tiff; application=geotiff; profile=cloud-optimized',
               ARRAY['data'], size_bytes
        FROM catalog.raster_assets
        WHERE asset_uri IS NOT NULL AND vrt_type IS NULL
    """)

    # Backfill VRT assets
    op.execute("""
        INSERT INTO catalog.dataset_assets (dataset_id, key, href, media_type, roles)
        SELECT dataset_id, 'data', asset_uri,
               'application/xml',
               ARRAY['data', 'virtual']
        FROM catalog.raster_assets
        WHERE asset_uri IS NOT NULL AND vrt_type IS NOT NULL
    """)

    # Backfill thumbnails (256px)
    op.execute("""
        INSERT INTO catalog.dataset_assets (dataset_id, key, href, media_type, roles)
        SELECT dataset_id, 'thumbnail', quicklook_256_uri,
               'image/png', ARRAY['thumbnail']
        FROM catalog.raster_assets
        WHERE quicklook_256_uri IS NOT NULL
    """)

    # Backfill overviews (512px)
    op.execute("""
        INSERT INTO catalog.dataset_assets (dataset_id, key, href, media_type, roles)
        SELECT dataset_id, 'overview', quicklook_512_uri,
               'image/png', ARRAY['overview']
        FROM catalog.raster_assets
        WHERE quicklook_512_uri IS NOT NULL
    """)
```

**Key decisions:**
- Do NOT drop `quicklook_*_uri` or `asset_uri` columns from RasterAsset yet -- they remain for internal processing. Cleanup is a future task.
- Backfill is idempotent due to unique constraint (will fail on re-run, which is fine for a migration).
- VRT assets get `roles=["data", "virtual"]` to distinguish from COG data assets.

## Workspace-as-Collection Mapping

### Field Correspondence

| STAC Collection Field | GeoLens Source | Notes |
|----------------------|----------------|-------|
| `id` | `collection.id` (UUID) | Cast to string |
| `title` | `collection.name` | Direct map |
| `description` | `collection.description` | Direct map, required in STAC |
| `license` | **NOT ON MODEL** | Default to `"proprietary"` for now |
| `extent.spatial.bbox` | Computed from member Records | Already done in collections service |
| `extent.temporal.interval` | Computed from member Record temporal_start/end | Partial -- need to aggregate |
| `providers` | **NOT ON MODEL** | Optional in STAC, defer |
| `keywords` | Could aggregate member Record keywords | Optional, defer |

**Recommendation:** Do NOT add `license` or `providers` columns to Collection model in this task. Document the mapping in code comments only. When STAC serialization is built, these can be added or defaulted. The critical work is the asset table and metadata method.

## Common Pitfalls

### Pitfall 1: Over-engineering the asset table
**What goes wrong:** Adding STAC extension columns (proj:epsg, bands, etc.) directly to the asset table, duplicating data from RasterAsset.
**How to avoid:** Asset table stores only asset-level fields (href, type, roles). Processing/descriptive metadata stays on RasterAsset, extracted via `to_stac_properties()`.

### Pitfall 2: Breaking existing quicklook/tile URL resolution
**What goes wrong:** Changing how `quicklook_256_uri` is resolved in the API response by prematurely switching to dataset_assets lookup.
**How to avoid:** Existing code paths continue reading from RasterAsset columns. The dataset_assets table is additive -- new code can read from it, but existing code remains untouched.

### Pitfall 3: Forgetting VRT-specific asset handling
**What goes wrong:** VRT datasets have no uploaded file -- their "data" asset is a generated VRT XML file. Treating them identically to COGs during backfill.
**How to avoid:** Use `vrt_type IS NOT NULL` to detect VRT records and assign appropriate media_type (`application/xml`) and roles (`["data", "virtual"]`).

### Pitfall 4: STAC datetime vs GeoLens temporal model
**What goes wrong:** STAC Items require a `datetime` property (or `start_datetime`/`end_datetime`). The existing Record model has `temporal_start`/`temporal_end` as dates, not datetimes.
**How to avoid:** In `to_stac_properties()`, convert dates to ISO datetime strings with `T00:00:00Z` suffix. This is a serialization concern, not a schema change.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | backend/pytest.ini |
| Quick run command | `cd backend && python -m pytest tests/ -x -q --timeout=30` |
| Full suite command | `cd backend && python -m pytest tests/ --timeout=60` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command |
|--------|----------|-----------|-------------------|
| STAC-01 | dataset_assets table creation + backfill | unit | `pytest tests/test_migrations.py -x -k dataset_assets` |
| STAC-02 | to_stac_properties() returns correct shape | unit | `pytest tests/raster/test_stac_properties.py -x` |
| STAC-03 | Backfill populates correct keys for COG/VRT/thumbnails | unit | `pytest tests/raster/test_asset_backfill.py -x` |
| STAC-04 | DatasetAsset model CRUD | unit | `pytest tests/raster/test_dataset_asset_model.py -x` |

### Wave 0 Gaps
- [ ] `tests/raster/test_stac_properties.py` -- covers to_stac_properties method
- [ ] `tests/raster/test_dataset_asset_model.py` -- covers DatasetAsset CRUD

## Sources

### Primary (HIGH confidence)
- [STAC spec commons/assets.md](https://github.com/radiantearth/stac-spec/blob/master/commons/assets.md) -- Asset object structure
- [STAC Item spec](https://github.com/radiantearth/stac-spec/blob/master/item-spec/item-spec.md) -- Item properties, asset roles
- [STAC Collection spec](https://github.com/radiantearth/stac-spec/blob/master/collection-spec/collection-spec.md) -- Collection required fields
- [STAC Projection Extension](https://github.com/stac-extensions/projection) -- proj:epsg, proj:shape, proj:transform
- [STAC Raster Extension](https://github.com/stac-extensions/raster) -- bands, data_type, nodata, statistics
- [STAC 1.1 bands discussion](https://github.com/radiantearth/stac-spec/discussions/1213) -- bands promoted to common metadata

### Secondary (MEDIUM confidence)
- [OGC STAC Community Standard](https://docs.ogc.org/cs/25-004/25-004.html) -- OGC-adopted version
- [pgstac docs](https://stac-utils.github.io/pgstac/pgstac/) -- reference for JSONB-based STAC storage (not directly applicable to our relational model)

## Metadata

**Confidence breakdown:**
- Asset table design: HIGH -- derived directly from STAC spec Asset Object + existing codebase analysis
- to_stac_properties pattern: HIGH -- straightforward mapping from existing columns to STAC fields
- Migration strategy: HIGH -- standard Alembic pattern, existing backfill precedent in codebase
- Collection mapping: HIGH -- STAC Collection spec is well-defined, workspace mapping is natural

**Research date:** 2026-03-16
**Valid until:** 2026-04-16 (STAC 1.1.0 is stable, unlikely to change)
