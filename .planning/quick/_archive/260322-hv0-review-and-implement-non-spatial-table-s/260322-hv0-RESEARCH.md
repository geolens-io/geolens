# Quick Task 260322-hv0: Non-Spatial Table Support - Research

**Researched:** 2026-03-22
**Domain:** CSV ingestion, non-spatial datasets, FK relationships, data grid UI
**Confidence:** HIGH

## Summary

The codebase already has partial non-spatial support: `geometry_type=None` is valid on Dataset, the features API handles `has_geometry=False`, the export router blocks spatial formats for non-spatial datasets, and the `/rows` endpoint excludes geometry columns automatically. However, the **file-based ingestion pipeline** (`ingest/tasks.py`) always assumes geometry exists -- it calls `clip_to_mercator_bounds` and `add_4326_column` unconditionally, which will fail on a pure CSV without lat/lon columns. The **service-based ingestion** (`ingest/service.py:276`) already handles this correctly by checking for `geom` column presence.

The frontend renders `VectorDetailPanel` for all vector datasets (including `geometry_type=None`), which includes a map hero area that would be meaningless for non-spatial data. The `AttributeTable` component (using `@tanstack/react-table`) already provides a full data grid with keyset pagination, inline editing, and column filtering -- it just needs to be promoted as the primary view for non-spatial datasets.

**Primary recommendation:** Fix the ingestion pipeline to handle non-spatial CSVs, add a `dataset_relationships` table for FK modeling, and create a dedicated non-spatial detail layout that uses the data grid as hero instead of the map.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Foreign-key joins between tables -- e.g., parcels.owner_id -> owners.id
- Auto-detect from column_info `foreign_key` semantic_role or let users define manually
- NOT parent-child hierarchy, NOT embedding-similarity
- CSV only for now -- most common non-spatial format
- ogr2ogr can handle CSV natively
- Data grid tab on dataset detail page -- paginated table view
- For spatial datasets with FK relationships, show related table data in a sub-panel or expandable rows
- Non-spatial datasets get the data grid as their primary view (no map tab)

### Claude's Discretion
- Exact data grid component choice (reuse existing table components vs. new)
- FK relationship storage schema (new table vs. JSON in existing model)
- Pagination strategy for related records

### Deferred Ideas
- Excel/JSON ingestion (future task)
</user_constraints>

## 1. Current Non-Spatial Support (Code Audit)

### What Works (Confidence: HIGH)

| Area | File | Status | Notes |
|------|------|--------|-------|
| Dataset model | `models.py:204` | Works | `geometry_type` is nullable, no constraint requires it |
| Features API | `features/router.py:101` | Works | `has_geometry = dataset.geometry_type is not None` branches correctly |
| Features service | `features/service.py:81-87` | Works | Non-geometry SELECT: `gid, NULL::json AS geometry, to_jsonb(t.*) - 'gid' AS properties` |
| Rows endpoint | `datasets/service.py:519-529` | Works | Skips `geom`, `geom_4326`, `wkb_geometry` from SELECT |
| Export router | `export/router.py:87-91` | Works | Blocks gpkg/geojson/shp, allows CSV |
| Service ingestion | `ingest/service.py:276-312` | Works | Checks `has_geom`, skips spatial metadata when false |
| Record type constraint | `models.py:51` | Needs new value | Only has `vector_dataset`, `raster_dataset`, `vrt_dataset`, `map`, `service`, `collection` -- no `table` type |

### What Breaks (Confidence: HIGH)

| Area | File | Problem | Fix Required |
|------|------|---------|-------------|
| File ingestion | `ingest/tasks.py:150-154` | Always calls `clip_to_mercator_bounds()` and `add_4326_column()` -- both reference `geom`/`geom_4326` which won't exist in a non-spatial CSV table | Add geometry check before spatial steps |
| ogr2ogr flags | `ingest/ogr.py:258-259` | Always passes `-nlt PROMOTE_TO_MULTI`, `-lco GEOMETRY_NAME=geom`, `-lco SPATIAL_INDEX=GIST` -- these fail or are meaningless without geometry | Conditionally omit spatial flags |
| CSV ogr2ogr | `ingest/ogr.py:272-282` | Always tries `X_POSSIBLE_NAMES`/`Y_POSSIBLE_NAMES` to auto-detect geometry from CSV | Need fallback when no lat/lon columns found |
| Metadata extraction | `ingest/metadata.py:34-41` | `get_table_srid()` calls `Find_SRID('data', table, 'geom')` -- will error if no geom column | Skip when geometry_type is None |
| Metadata extraction | `ingest/metadata.py:64-76` | `get_extent()` references `geom_4326` | Skip when geometry_type is None |
| Quality score | `ingest/metadata.py:201-213` | `compute_quality_score()` runs `ST_IsValid(geom)` unconditionally | Skip geometry validity for non-spatial |
| Vector quicklook | `ingest/tasks.py:207` | Tries to generate quicklook from geometry | Skip for non-spatial |
| Frontend hero | `DatasetPage.tsx:452-711` | Always renders `DatasetMap` for vector_dataset record_type | Need non-spatial layout path |

## 2. CSV Ingestion via ogr2ogr

### Current Behavior (Confidence: HIGH)

ogr2ogr handles CSV natively. The current `run_ogr2ogr()` already detects CSV via `is_csv` check and adds:
- `-oo X_POSSIBLE_NAMES=lon*,lng*,long*,x` -- auto-detect longitude columns
- `-oo Y_POSSIBLE_NAMES=lat*,y` -- auto-detect latitude columns
- `-a_srs EPSG:4326` as default CRS

When a CSV has no columns matching these patterns, ogr2ogr creates a **non-spatial table** in PostgreSQL (no `geom` column at all). This is the correct behavior for pure tabular data.

### Required Changes for Non-Spatial CSV Path

The fix is in `run_ogr2ogr()` and `ingest_file()`:

1. **ogr2ogr call**: When no geometry is expected, omit `-nlt PROMOTE_TO_MULTI`, `-lco GEOMETRY_NAME=geom`, `-lco SPATIAL_INDEX=GIST`. Keep `-lco FID=gid` (needed for keyset pagination).

2. **Detection strategy**: After `run_ogrinfo()`, check `geometry_type`. If None, use a non-spatial ogr2ogr invocation. For CSV specifically, run ogrinfo first -- if `geometryFields` is empty, it's non-spatial.

3. **Post-import pipeline**: Skip `clip_to_mercator_bounds`, `add_4326_column`, quicklook generation. Still call `grant_reader_access`, `extract_metadata` (but the metadata functions need guards).

### ogr2ogr Non-Spatial Flags

```bash
ogr2ogr -f PostgreSQL PG:... source.csv \
  -nln data.table_name \
  -lco FID=gid \
  -lco PRECISION=NO \
  --config PG_USE_COPY YES
# No -nlt, no GEOMETRY_NAME, no SPATIAL_INDEX
```

## 3. FK Relationship Storage Schema

### Recommendation: New `dataset_relationships` Table (Confidence: HIGH)

A dedicated join table is the right approach because:
- Relationships are bidirectional (parcels -> owners, but also navigate owners -> parcels)
- A single dataset can have multiple FK relationships to different tables
- Relationships need their own metadata (FK column name, target column name)
- JSON on the Dataset model would denormalize and create update anomalies

```sql
CREATE TABLE catalog.dataset_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_dataset_id UUID NOT NULL REFERENCES catalog.datasets(id) ON DELETE CASCADE,
    target_dataset_id UUID NOT NULL REFERENCES catalog.datasets(id) ON DELETE CASCADE,
    source_column TEXT NOT NULL,      -- e.g., "owner_id"
    target_column TEXT NOT NULL,      -- e.g., "id" or "gid"
    relationship_type TEXT NOT NULL DEFAULT 'foreign_key',
    label TEXT,                       -- optional display label
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(source_dataset_id, target_dataset_id, source_column)
);
```

### Auto-Detection from Semantic Roles

The `attribute_metadata` table already supports `semantic_role = 'foreign_key'`. The auto-detect flow:
1. During ingestion, `_infer_semantic_role()` already marks `*_id` columns as `identifier` -- extend to detect FK patterns
2. User can manually set `semantic_role = 'foreign_key'` on any column via the Structure tab
3. A separate step (manual or triggered) creates the `dataset_relationships` row by matching column values to target datasets

### Why Not JSON on Dataset

- A dataset could be the FK target of many other datasets (1:N on the relationship side)
- JSON fields can't be queried efficiently for "find all datasets that reference this one"
- Migrations and schema changes are harder with embedded JSON

### Why Not column_info Foreign Key Type

- `column_info` is auto-extracted from the physical PostgreSQL table schema and refreshed on re-upload
- FK relationships are a catalog-level concept, not a physical DB constraint
- Mixing catalog semantics into `column_info` would conflate two concerns

## 4. Related Records Query Pattern

### Single-Feature FK Lookup

When a user clicks a feature and the dataset has FK relationships:

```sql
-- Given: parcels feature with owner_id = 42
-- Relationship: parcels.owner_id -> owners.gid
SELECT gid, to_jsonb(t.*) - 'gid' AS properties
FROM data.owners_table t
WHERE t.gid = :fk_value
LIMIT 50 OFFSET :offset;
```

### Proposed API Endpoint

```
GET /datasets/{dataset_id}/features/{gid}/related/{relationship_id}?limit=50&after=0
```

Returns `DatasetRowsResponse` (already exists) with the related records.

### Pagination

Use the same keyset pagination pattern as `get_dataset_rows()` -- `WHERE gid > :after_gid ORDER BY gid LIMIT :limit`. This is already proven in the codebase.

### Performance Considerations

- Add a B-tree index on the FK column of the source table: `CREATE INDEX idx_{table}_owner_id ON data.{table}(owner_id)` -- ogr2ogr won't create this automatically
- For reverse lookups (given an owner, find all parcels), the same index works
- Limit + keyset pagination keeps queries O(1) regardless of total related records

## 5. Frontend Data Grid Components

### Existing Components (Confidence: HIGH)

| Component | Location | Tech | Reusable? |
|-----------|----------|------|-----------|
| `AttributeTable` | `components/dataset/AttributeTable.tsx` | `@tanstack/react-table v8.21.3` | Yes -- primary candidate |
| `DataTab` | `components/dataset/tabs/DataTab.tsx` | Wrapper around AttributeTable | Yes |
| `DataTablePagination` | `components/admin/DataTablePagination.tsx` | Custom pagination | Admin-only, different pattern |
| `DataTableSearch` | `components/admin/DataTableSearch.tsx` | Search input | Admin-only |

### Recommendation: Reuse AttributeTable

`AttributeTable` already provides:
- `@tanstack/react-table` with dynamic columns from API
- Keyset pagination with cursor history
- Inline cell editing (click to edit, Enter/Escape/blur)
- Per-column ILIKE filtering
- Loading and empty states
- Responsive overflow scrolling

For non-spatial datasets, the `DataTab`/`AttributeTable` should become the **primary view** (hero position) instead of being buried in a tab.

### Non-Spatial Detail Layout

Create a new panel (or modify existing `VectorDetailPanel`) that:
1. Shows the data grid in the hero area (where the map would be)
2. Keeps Overview, Metadata, Structure, Access tabs below
3. Omits the map-related UI (zoom-to-extent, draw tools, tile URL in Connect dropdown)

### Related Records Sub-Panel

For spatial datasets with FK relationships, when a user clicks a feature in the popup:
- Show a "Related Records" expandable section in the feature popup or side panel
- Fetch from the proposed `/related/` endpoint
- Render using a simplified `AttributeTable` (read-only, no editing)

## Common Pitfalls

### Pitfall 1: ogr2ogr CSV Geometry Auto-Detection
**What goes wrong:** ogr2ogr with `X_POSSIBLE_NAMES`/`Y_POSSIBLE_NAMES` may pick up columns like `x_offset` or `year` that aren't coordinates, creating invalid geometry.
**How to avoid:** Run ogrinfo first. If `geometryFields` is empty in the JSON output, use non-spatial ingestion path. Don't pass `-oo X_POSSIBLE_NAMES` at all for explicitly non-spatial imports.

### Pitfall 2: Missing `gid` Column in Non-Spatial Tables
**What goes wrong:** The `-lco FID=gid` flag should still work for non-spatial CSV imports, creating an auto-increment `gid` column. But verify this works without the geometry-related layer creation options.
**How to avoid:** Test CSV import without geometry flags and confirm `gid` column is created.

### Pitfall 3: metadata.py Functions Assuming Geometry
**What goes wrong:** `get_table_srid()`, `get_extent()`, `get_geometry_type()`, `compute_quality_score()` all query geometry columns. They'll throw SQL errors on non-spatial tables.
**How to avoid:** Guard all geometry-dependent metadata calls with a `has_geometry` check. The `extract_metadata()` function should return `None` for spatial fields when no geometry exists.

### Pitfall 4: Record Type Classification
**What goes wrong:** Non-spatial datasets currently get `record_type = 'vector_dataset'` which is semantically wrong and causes the frontend to render a map.
**How to avoid:** Either add a new record_type (e.g., `'table'`) or use the existing `geometry_type is None` check in the frontend to swap layouts. Adding a new record_type requires a DB migration and updating the CHECK constraint.

## Sources

### Primary (HIGH confidence)
- Direct code audit of `backend/app/ingest/tasks.py`, `backend/app/ingest/ogr.py`, `backend/app/ingest/metadata.py`
- Direct code audit of `backend/app/features/service.py`, `backend/app/features/router.py`
- Direct code audit of `backend/app/datasets/models.py`, `backend/app/datasets/service.py`, `backend/app/datasets/schemas.py`
- Direct code audit of `frontend/src/components/dataset/AttributeTable.tsx`, `frontend/src/pages/DatasetPage.tsx`
- Direct code audit of `backend/app/ingest/service.py:275-312` (service ingestion non-spatial path)

### Secondary (MEDIUM confidence)
- ogr2ogr CSV handling behavior based on GDAL documentation and existing code patterns
