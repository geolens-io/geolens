# Quick Task 260322-kec: FK Auto-Detection, RelatedRecordsPanel Activation, record_type Validation - Research

**Researched:** 2026-03-22
**Domain:** FK relationships, feature selection, record_type pipeline
**Confidence:** HIGH

## Summary

Three targeted investigations covering FK auto-detection, read-only panel activation, and record_type='table' pipeline validation. All findings are from direct codebase inspection.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- This task covers items 1, 2, and 4 from the follow-up list
- Excel/JSON ingestion deferred to backlog (too large for quick task)

### Claude's Discretion
- FK auto-detection matching strategy (column name matching vs. value sampling)
- How read-only feature selection integrates with existing popup/table click handlers
- Whether record_type validation needs code changes or just verification
</user_constraints>

---

## 1. FK Auto-Detection

### Current State

**`_infer_semantic_role()` in `metadata.py:437-474`** never assigns `'foreign_key'`. It maps `_id` suffix columns to `'identifier'`. The `'foreign_key'` role exists in the DB CHECK constraint and Pydantic schema (`SEMANTIC_ROLES`) but is never auto-populated -- it can only be set via manual `PATCH /api/datasets/{id}/attributes/{attr_id}/`.

**`column_info`** stored on `Dataset.column_info` (JSONB list) contains per-column: `name`, `type`, `ordinal_position`, `is_nullable`. This is the raw PostgreSQL information_schema data.

**`AttributeMetadata`** model has richer data per column: `field_name`, `data_type`, `semantic_role`, `example_values` (up to 10 distinct sample values), `domain_type`, `title`.

**`sample_values`** stored on `Dataset.sample_values` (JSONB dict) maps column name to list of up to 10 distinct string values.

### Recommended FK Detection Strategy

**When to run:** Post-ingestion, as part of the existing `create_dataset` flow (or immediately after `generate_attribute_metadata`). Not a background task -- the query is lightweight.

**Matching algorithm (column name matching):**
1. For each column in the new dataset with `semantic_role='identifier'` (columns ending in `_id`), query `catalog.attribute_metadata` for other datasets that have a column with the same `field_name` and `semantic_role` IN (`'identifier'`).
2. If a match is found, auto-create a `DatasetRelationship` row with `source_column=<this_column>`, `target_column=<matched_column>`, `target_dataset_id=<matched_dataset's record_id>`.
3. Skip self-references (same dataset).

**Why column name matching over value sampling:** Value sampling requires cross-dataset SQL queries and is expensive for large catalogs. Column name matching (`parcel_id` in table A matches `parcel_id` in table B) captures the dominant FK pattern and is O(1 query) against the attribute_metadata table.

**Implementation location:** New function `auto_detect_relationships()` in `backend/app/datasets/service.py`, called from `ingest_file` task after `generate_attribute_metadata`.

### Key Files
- `backend/app/ingest/metadata.py` -- `_infer_semantic_role()` (line 437), `generate_attribute_metadata()` (line 504)
- `backend/app/datasets/models.py` -- `DatasetRelationship` (line 394), `AttributeMetadata` (line 332)
- `backend/app/datasets/service.py` -- `create_dataset()` (line 139), relationship CRUD functions
- `backend/app/ingest/tasks.py` -- `ingest_file()` task

---

## 2. RelatedRecordsPanel Read-Only Activation

### Current Wiring

**DatasetPage.tsx line 113:** `selectedFeatureGid` comes exclusively from `useDrawingStore((s) => s.selectedFeature?.gid ?? null)`.

**DatasetPage.tsx line 742:** Panel renders when `selectedFeatureGid != null` AND record_type is vector_dataset. Currently does NOT include `record_type === 'table'`.

**Drawing store** (`stores/drawing-store.ts`): `selectedFeature` is only set when `isDrawing=true` and `activeMode='select'`, via `setSelectedFeature()`. This means the panel never shows in read-only mode.

**Feature selection in DatasetMap.tsx:** Map click handler (line 216-217) calls `selectFeatureFromMap(map, e.point)` but only when `activeMode === 'select'` (editing mode). No read-only click handler exists.

**FeaturePopup** (`components/map/FeaturePopup.tsx`): Used in BuilderMap and ViewerMap but NOT in DatasetMap. DatasetMap has no popup mechanism for read-only clicks.

**AttributeTable** (`components/dataset/AttributeTable.tsx`): No row click/selection handler exists. Rows are only clickable for inline cell editing.

### Recommended Approach

Create a lightweight `selectedReadOnlyFeature` state (not in drawing store -- that's editing-only). Options:

**Option A (Recommended): Local state in DatasetPage**
- Add `const [readOnlyFeatureGid, setReadOnlyFeatureGid] = useState<number | null>(null)` in DatasetPage
- Pass `onFeatureClick` callback to DatasetMap for non-editing mode clicks
- In DatasetMap, add a map click handler that fires when NOT in drawing mode, extracts gid from clicked feature
- Merge: `const effectiveGid = selectedFeatureGid ?? readOnlyFeatureGid`
- Pass `effectiveGid` to RelatedRecordsPanel

**Option B: New zustand store**
- Overkill for a single page-level state. Not recommended.

**DatasetMap changes needed:**
- Add `onFeatureClick?: (gid: number) => void` prop
- Add map click handler when `!isDrawing` that queries rendered features at click point, extracts gid, calls `onFeatureClick`
- The existing vector tile source layer IDs are needed to query features

**RelatedRecordsPanel condition fix:**
- Line 742: also include `record_type === 'table'` in the guard condition

### Key Files
- `frontend/src/pages/DatasetPage.tsx` -- lines 113, 742
- `frontend/src/stores/drawing-store.ts` -- selectedFeature state
- `frontend/src/components/dataset/DatasetMap.tsx` -- map click handling
- `frontend/src/components/dataset/RelatedRecordsPanel.tsx` -- panel component

---

## 3. record_type='table' Validation

### Migration 0002 (CORRECT)

`backend/alembic/versions/0002_add_table_record_type.py` correctly:
- Drops the existing CHECK constraint
- Adds new constraint including `'table'` in the allowed values
- Downgrade correctly removes `'table'`

### SQLAlchemy Model (CORRECT)

`Record` model line 51: CHECK constraint includes `'table'` in the allowed values list.

### Service Layer (CORRECT)

`backend/app/datasets/service.py` line 160-161:
```python
record_type = "table" if geometry_type is None else "vector_dataset"
```
When `geometry_type` is `None` (non-spatial CSV), record_type is set to `'table'`.

### Ingest Pipeline (CORRECT)

`ingest_file()` task (tasks.py):
- Line 107-108: `geometry_type = info.get("geometry_type")` from ogrinfo, `has_geometry = geometry_type is not None`
- When `has_geometry` is False, spatial steps (clip, add_4326_column) are skipped
- `geometry_type=None` is passed to `create_dataset()`, which sets `record_type='table'`

### Frontend (MOSTLY CORRECT, 2 ISSUES)

1. **DatasetPage line 408:** `const isTable = dataset.record_type === 'table'` -- correctly detected
2. **DatasetPage lines 604-610:** Table datasets show DataTab hero grid instead of map -- correct
3. **DatasetPage line 726:** VectorDetailPanel handles `record_type === 'table'` -- correct
4. **DatasetPage line 456:** Stats line includes `record_type === 'table'` -- correct

**Issue 1 - Line 742:** RelatedRecordsPanel guard excludes `record_type === 'table'`:
```tsx
{selectedFeatureGid != null && (dataset.record_type === 'vector_dataset' || !dataset.record_type) && (
```
Should also include `dataset.record_type === 'table'`.

**Issue 2 - DatasetResponse schema line 133:** Default is `"vector_dataset"` which is fine since server always provides the value. No issue.

### Pydantic Schema (CORRECT)

`DatasetResponse.record_type: str = "vector_dataset"` -- the default is only a fallback; the server always sends the actual value.

### Frontend TypeScript Types

`DatasetRelationship` interface in `api.ts` line 1129 includes all needed fields. No issues.

### Verdict

**record_type='table' pipeline is complete and correct.** The only code change needed is the RelatedRecordsPanel guard condition (addressed in item 2 above).

---

## Summary of Required Changes

| Item | Status | Changes Needed |
|------|--------|----------------|
| FK auto-detection | New feature | New `auto_detect_relationships()` in service.py, call from ingest_file task |
| RelatedRecordsPanel read-only | New feature | Add `onFeatureClick` to DatasetMap, local state in DatasetPage, update guard condition |
| record_type='table' validation | Verified correct | Fix guard condition on line 742 of DatasetPage.tsx (part of item 2) |
