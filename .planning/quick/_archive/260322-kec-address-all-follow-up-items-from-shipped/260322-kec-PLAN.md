---
phase: quick-260322-kec
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/datasets/service.py
  - backend/app/ingest/tasks.py
  - frontend/src/components/dataset/DatasetMap.tsx
  - frontend/src/pages/DatasetPage.tsx
autonomous: true
requirements: [FK-AUTO, PANEL-READONLY, TABLE-VALIDATION]

must_haves:
  truths:
    - "Ingesting a dataset with _id columns auto-creates DatasetRelationship rows to matching datasets"
    - "Clicking a feature in read-only mode on DatasetMap shows the RelatedRecordsPanel"
    - "RelatedRecordsPanel renders for record_type='table' datasets"
    - "Self-referencing FK auto-detection is skipped"
  artifacts:
    - path: "backend/app/datasets/service.py"
      provides: "auto_detect_relationships() function"
      contains: "auto_detect_relationships"
    - path: "frontend/src/components/dataset/DatasetMap.tsx"
      provides: "onFeatureClick prop for read-only clicks"
      contains: "onFeatureClick"
    - path: "frontend/src/pages/DatasetPage.tsx"
      provides: "readOnlyFeatureGid state, effectiveGid merging, table guard fix"
      contains: "readOnlyFeatureGid"
  key_links:
    - from: "backend/app/datasets/service.py"
      to: "catalog.attribute_metadata"
      via: "query matching field_names across datasets"
      pattern: "auto_detect_relationships"
    - from: "frontend/src/components/dataset/DatasetMap.tsx"
      to: "frontend/src/pages/DatasetPage.tsx"
      via: "onFeatureClick callback prop"
      pattern: "onFeatureClick"
    - from: "frontend/src/pages/DatasetPage.tsx"
      to: "frontend/src/components/dataset/RelatedRecordsPanel.tsx"
      via: "effectiveGid passed as featureGid"
      pattern: "effectiveGid"
---

<objective>
Implement FK auto-detection during ingestion, enable RelatedRecordsPanel in read-only mode via map clicks, and fix the record_type='table' guard condition.

Purpose: Complete the FK relationship feature so it works end-to-end without manual setup and activates in both editing and read-only contexts.
Output: Backend auto-detects FK relationships on ingest; frontend activates related records panel on read-only feature clicks including table datasets.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@backend/app/datasets/service.py
@backend/app/datasets/models.py (DatasetRelationship at line 394, AttributeMetadata at line 332)
@backend/app/ingest/metadata.py (_infer_semantic_role at line 437, generate_attribute_metadata at line 504)
@backend/app/ingest/tasks.py (ingest_file, ingest_service_layer)
@frontend/src/components/dataset/DatasetMap.tsx (DatasetMapProps at line 42, click handler at line 211)
@frontend/src/pages/DatasetPage.tsx (selectedFeatureGid at line 113, guard at line 742)

<interfaces>
<!-- Key types and contracts the executor needs -->

From backend/app/datasets/models.py:
```python
class DatasetRelationship(Base):
    __tablename__ = "dataset_relationships"
    id: Mapped[uuid.UUID]
    source_dataset_id: Mapped[uuid.UUID]  # FK -> catalog.records.id
    target_dataset_id: Mapped[uuid.UUID]  # FK -> catalog.records.id
    source_column: Mapped[str]            # String(100)
    target_column: Mapped[str]            # String(100), default "gid"
    relationship_type: Mapped[str]        # String(20), default "foreign_key"
    label: Mapped[str | None]

class AttributeMetadata(Base):
    __tablename__ = "attribute_metadata"
    dataset_id: Mapped[uuid.UUID]         # FK -> catalog.datasets.id
    field_name: Mapped[str]
    semantic_role: Mapped[str | None]     # 'identifier', 'foreign_key', etc.
```

From backend/app/datasets/service.py:
```python
async def create_dataset(session, *, table_name, title, ...) -> Dataset
async def create_relationship(session, dataset_id, rel)
```

From frontend DatasetMap:
```typescript
interface DatasetMapProps {
  bbox, tableName, geometryType, datasetId?, columnInfo?,
  containerRef?, canEdit?, recordType?, rasterTileUrl?,
  tileVersion?, onMapReady?, onTileError?
}
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: FK auto-detection on ingestion</name>
  <files>backend/app/datasets/service.py, backend/app/ingest/tasks.py</files>
  <action>
1. In `backend/app/datasets/service.py`, add `auto_detect_relationships()` after the existing relationship CRUD functions (~line 930):

```python
async def auto_detect_relationships(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    record_id: uuid.UUID,
    column_info: list[dict],
) -> list:
```

Logic:
- Extract candidate column names: columns from `column_info` whose name ends with `_id` (same pattern as `_infer_semantic_role` identifier detection), excluding `gid`, `ogc_fid`, `fid`, `objectid`, `id` (these are PKs, not FKs).
- For each candidate column, query `catalog.attribute_metadata` for rows where `field_name = candidate_column` AND `semantic_role = 'identifier'` AND the `dataset_id` belongs to a DIFFERENT record (join to Dataset to get record_id, ensure record_id != this record_id).
- For each match, create a `DatasetRelationship` with: `source_dataset_id=record_id`, `target_dataset_id=matched_record_id`, `source_column=candidate_column`, `target_column=candidate_column`, `label=None`.
- Use INSERT ... ON CONFLICT DO NOTHING (or check against the unique constraint) to be idempotent.
- Return the list of created relationships.

2. In `create_dataset()` (service.py ~line 211), after `generate_attribute_metadata`, add:

```python
# Auto-detect FK relationships based on column name matching
if column_info:
    await auto_detect_relationships(
        session, dataset.id, record.id, column_info
    )
```

3. In `backend/app/ingest/tasks.py`, no changes needed -- `create_dataset` already handles it.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && python -c "import ast; tree = ast.parse(open('backend/app/datasets/service.py').read()); funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]; assert 'auto_detect_relationships' in funcs, f'Missing function. Found: {funcs}'"</automated>
  </verify>
  <done>auto_detect_relationships() exists in service.py and is called from create_dataset() after generate_attribute_metadata. Candidate columns are filtered to exclude PK names. Self-references are skipped via record_id comparison. Duplicate relationships are handled gracefully.</done>
</task>

<task type="auto">
  <name>Task 2: Read-only feature click activates RelatedRecordsPanel + table guard fix</name>
  <files>frontend/src/components/dataset/DatasetMap.tsx, frontend/src/pages/DatasetPage.tsx</files>
  <action>
1. **DatasetMap.tsx** -- Add `onFeatureClick` prop and read-only click handler:

- Add to `DatasetMapProps`: `onFeatureClick?: (gid: number) => void`
- Destructure `onFeatureClick` in the component params.
- Add a new useEffect (after the existing select-mode click handler at ~line 211) for read-only feature clicks:

```typescript
// Read-only feature click handler (non-editing mode)
useEffect(() => {
  const map = mapInstance;
  if (!map || !onFeatureClick || !tableName) return;
  // Only active when NOT in drawing mode
  if (activeMode) return;

  const handleReadOnlyClick = (e: maplibregl.MapMouseEvent) => {
    const sourceLayer = getSourceLayerName(tableName);
    const features = map.queryRenderedFeatures(e.point, {
      layers: map.getStyle().layers
        ?.filter(l => (l as any)['source-layer'] === sourceLayer)
        .map(l => l.id) ?? [],
    });
    if (features.length > 0) {
      const gid = features[0].properties?.gid;
      if (gid != null) onFeatureClick(Number(gid));
    }
  };
  map.on('click', handleReadOnlyClick);
  return () => { map.off('click', handleReadOnlyClick); };
}, [activeMode, mapInstance, onFeatureClick, tableName]);
```

Note: `activeMode` is already available from `useDrawingStore`. When `activeMode` is set (drawing/select mode), the existing handler takes over. When null (read-only), this handler fires.

2. **DatasetPage.tsx** -- Add local state for read-only selection and fix guard:

- Add state: `const [readOnlyFeatureGid, setReadOnlyFeatureGid] = useState<number | null>(null)`
- Compute effective gid: `const effectiveGid = selectedFeatureGid ?? readOnlyFeatureGid`
- Pass callback to DatasetMap: `onFeatureClick={setReadOnlyFeatureGid}`
- Clear read-only selection when entering drawing mode: add a useEffect that sets `setReadOnlyFeatureGid(null)` when `selectedFeatureGid` becomes non-null (editing takes priority).
- Fix line 742 guard condition -- replace:
  ```tsx
  {selectedFeatureGid != null && (dataset.record_type === 'vector_dataset' || !dataset.record_type) && (
  ```
  with:
  ```tsx
  {effectiveGid != null && (dataset.record_type === 'vector_dataset' || dataset.record_type === 'table' || !dataset.record_type) && (
  ```
- Update featureGid prop: `<RelatedRecordsPanel datasetId={id!} featureGid={effectiveGid} />`
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -30</automated>
  </verify>
  <done>Clicking a vector feature in read-only mode (no active drawing) sets readOnlyFeatureGid and shows RelatedRecordsPanel. Guard condition includes record_type='table'. TypeScript compiles clean.</done>
</task>

</tasks>

<verification>
1. Backend: `auto_detect_relationships` function exists and is called from `create_dataset`
2. Frontend: TypeScript compiles with no errors
3. DatasetMap accepts `onFeatureClick` prop
4. DatasetPage merges editing and read-only feature gids
5. RelatedRecordsPanel guard includes `record_type === 'table'`
</verification>

<success_criteria>
- FK auto-detection creates DatasetRelationship rows when ingesting datasets with _id columns that match columns in other datasets
- Read-only map clicks on vector features activate RelatedRecordsPanel without entering edit mode
- Table-type datasets can show RelatedRecordsPanel when a feature gid is selected
- No TypeScript compilation errors
</success_criteria>

<output>
After completion, create `.planning/quick/260322-kec-address-all-follow-up-items-from-shipped/260322-kec-SUMMARY.md`
</output>
