---
phase: quick-260325-bsk
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/search/RecordTypeBadge.tsx
  - frontend/src/components/dataset/ConnectDropdown.tsx
  - frontend/src/pages/DatasetPage.tsx
  - frontend/src/components/dataset/tabs/OverviewTab.tsx
  - frontend/src/components/dataset/panels/VectorDetailPanel.tsx
  - frontend/src/components/dataset/ExportButton.tsx
  - frontend/src/components/dataset/tabs/AccessTab.tsx
  - frontend/src/components/dataset/tabs/AccessSharingTab.tsx
  - frontend/src/i18n/locales/en/search.json
  - frontend/src/i18n/locales/fr/search.json
  - frontend/src/i18n/locales/es/search.json
  - frontend/src/i18n/locales/de/search.json
autonomous: true
requirements: [QUICK-BSK]

must_haves:
  truths:
    - "Non-spatial table datasets show a 'Table' type badge in stats line and search cards"
    - "No spatial-only UI controls appear for table datasets (no tile URL, no Add to Map, no geometry type field)"
    - "Stats line and overview use 'rows' terminology instead of 'features' for table datasets"
    - "Data tab in VectorDetailPanel is hidden for table datasets since the hero IS the data view"
    - "Export formats for table datasets exclude Shapefile (geometry-dependent format)"
  artifacts:
    - path: "frontend/src/components/search/RecordTypeBadge.tsx"
      provides: "Table type badge config"
      contains: "table"
    - path: "frontend/src/pages/DatasetPage.tsx"
      provides: "Table-aware stats line, hidden AddToMap, hidden ConnectDropdown"
    - path: "frontend/src/components/dataset/tabs/OverviewTab.tsx"
      provides: "Hidden geometry field for tables, row count label"
    - path: "frontend/src/components/dataset/panels/VectorDetailPanel.tsx"
      provides: "Conditional Data tab visibility"
    - path: "frontend/src/components/dataset/ExportButton.tsx"
      provides: "Filtered export formats for non-spatial"
  key_links:
    - from: "DatasetPage.tsx"
      to: "RecordTypeBadge.tsx"
      via: "isTable condition in statsLine"
      pattern: "record_type.*table"
    - from: "DatasetPage.tsx"
      to: "ConnectDropdown.tsx"
      via: "conditional rendering gated on isTable"
      pattern: "!isTable.*ConnectDropdown"
---

<objective>
Fix non-spatial data page UI/UX gaps: add missing table type badge, remove irrelevant spatial controls, fix terminology, deduplicate data grid, and filter export formats.

Purpose: Table (non-spatial) datasets currently show broken/misleading spatial UI elements (tile URLs, Add to Map button, geometry type fields, "features" label) because the detail page was built for vector datasets and the table path was not fully differentiated.

Output: Clean table dataset detail page with appropriate controls, terminology, and no duplicate data views.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260325-bsk-review-the-non-spatial-data-page-ui-ux-a/260325-bsk-CONTEXT.md
@.planning/quick/260325-bsk-review-the-non-spatial-data-page-ui-ux-a/260325-bsk-RESEARCH.md

@frontend/src/pages/DatasetPage.tsx
@frontend/src/components/search/RecordTypeBadge.tsx
@frontend/src/components/dataset/ConnectDropdown.tsx
@frontend/src/components/dataset/AddToMapButton.tsx
@frontend/src/components/dataset/tabs/OverviewTab.tsx
@frontend/src/components/dataset/panels/VectorDetailPanel.tsx
@frontend/src/components/dataset/ExportButton.tsx
@frontend/src/components/dataset/tabs/AccessTab.tsx
@frontend/src/components/dataset/tabs/AccessSharingTab.tsx

<interfaces>
From RecordTypeBadge.tsx:
```typescript
const TYPE_CONFIG = {
  vector_dataset: { icon: Layers, labelKey: 'card.vector', className: '...' },
  raster_dataset: { icon: Grid3X3, labelKey: 'card.raster', className: '...' },
  vrt_dataset: { icon: Combine, labelKey: 'card.vrt', className: '...' },
  collection: { icon: FolderOpen, labelKey: 'card.collection', className: '...' },
} as const;
```

From DatasetPage.tsx:
```typescript
const isTable = dataset.record_type === 'table';
const isRaster = dataset.record_type === 'raster_dataset';
const isVrt = dataset.record_type === 'vrt_dataset';
```

From VectorDetailPanel.tsx:
```typescript
export interface DetailPanelProps {
  dataset: DatasetResponse;
  canEdit: boolean;
  capabilities: DatasetEditCapabilities;
  datasetId: string;
  activeTab: string;
  onTabChange: (tab: string) => void;
  // ...draft fields
}
```

From ExportButton.tsx:
```typescript
const EXPORT_FORMATS = [
  { value: 'gpkg', labelKey: 'export.gpkg', ext: 'gpkg' },
  { value: 'geojson', labelKey: 'export.geojson', ext: 'geojson' },
  { value: 'shp', labelKey: 'export.shp', ext: 'zip' },
  { value: 'csv', labelKey: 'export.csv', ext: 'csv' },
] as const;
```

From AccessTab.tsx (line 101) and AccessSharingTab.tsx (line 101):
```typescript
<ExportButton datasetId={datasetId} datasetName={dataset.title} />
```
Both components have `dataset` in scope and need the new `recordType` prop.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix table type badge and spatial control visibility</name>
  <files>
    frontend/src/components/search/RecordTypeBadge.tsx
    frontend/src/pages/DatasetPage.tsx
    frontend/src/components/dataset/ConnectDropdown.tsx
    frontend/src/i18n/locales/en/search.json
    frontend/src/i18n/locales/fr/search.json
    frontend/src/i18n/locales/es/search.json
    frontend/src/i18n/locales/de/search.json
  </files>
  <action>
    1. **RecordTypeBadge.tsx** -- Add `table` entry to `TYPE_CONFIG`:
       - icon: `Table2` from lucide-react (import it)
       - labelKey: `'card.table'`
       - className: `'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400'`
       This makes the table badge appear in stats lines and search result cards.

    2. **All 4 search i18n locale files** (en, fr, es, de) -- Add `"table": "Table"` (or translated equivalent: fr="Table", es="Tabla", de="Tabelle") inside the `"card"` object, after the `"collection"` entry.

    3. **DatasetPage.tsx** -- In the `leadingContent` prop of `DatasetDetailHeader` (around line 596-609):
       - Wrap `<AddToMapButton>` in `{!isTable && (...)}` to hide it for table datasets
       - Wrap `<ConnectDropdown>` in `{!isTable && (...)}` to hide it for table datasets (tile URL and feature URL are irrelevant for non-spatial data; the API endpoint still works via the Features/OGC tab)

    4. **DatasetPage.tsx** -- In the `statsLine` const (around line 476):
       - Change `{dataset.feature_count.toLocaleString()} features` to use conditional text:
         `{dataset.feature_count.toLocaleString()} {isTable ? 'rows' : 'features'}`
       - Note: `isTable` is defined at line 417 and is in scope for the statsLine JSX block.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>Table datasets show orange "Table" badge, no Add to Map button, no Connect dropdown, and stats line says "rows" instead of "features"</done>
</task>

<task type="auto">
  <name>Task 2: Fix overview fields, deduplicate data tab, filter exports</name>
  <files>
    frontend/src/components/dataset/tabs/OverviewTab.tsx
    frontend/src/components/dataset/panels/VectorDetailPanel.tsx
    frontend/src/components/dataset/ExportButton.tsx
    frontend/src/components/dataset/tabs/AccessTab.tsx
    frontend/src/components/dataset/tabs/AccessSharingTab.tsx
  </files>
  <action>
    1. **OverviewTab.tsx** -- In the identity section (lines 186-200):
       - Change the geometry type field condition from `{!isRaster && !isVrt && (` to `{!isRaster && !isVrt && dataset.geometry_type && (` -- this hides the "Geometry Type: Not available" row for table datasets instead of showing noise.
       - For the feature count field (lines 196-200), the label `t('metadata.featureCount')` says "Feature Count". Add a conditional: if `dataset.record_type === 'table'`, use a hardcoded label "Row Count" (or add an i18n key if a dataset.json key like `metadata.rowCount` is easy to add). Keep the formatting with `formatNumber(dataset.feature_count)`.
       - Note: `isRaster` and `isVrt` are already defined in OverviewTab. Check if `dataset.record_type` is accessible from props (it should be via `dataset` prop).

    2. **VectorDetailPanel.tsx** -- Hide the Data tab for table datasets since the hero section already shows the full data grid:
       - Accept `isTable` as a prop OR derive it: `const isTable = dataset.record_type === 'table';`
       - Wrap the Data tab trigger in a conditional: `{!isTable && <TabsTrigger value="data">...</TabsTrigger>}`
       - Wrap the Data tab content in a conditional: `{!isTable && <TabsContent value="data">...</TabsContent>}`
       - This prevents the duplicate rendering where users see the exact same attribute table in both the hero and the Data tab.

    3. **ExportButton.tsx** -- Accept an optional `recordType?: string` prop. Filter `EXPORT_FORMATS` for table datasets:
       - If `recordType === 'table'`, filter out `shp` (Shapefile requires geometry column and will fail).
       - Keep gpkg, geojson, csv (these handle non-spatial tables).
       - Use: `const formats = recordType === 'table' ? EXPORT_FORMATS.filter(f => f.value !== 'shp') : EXPORT_FORMATS;`
       - Then map over `formats` instead of `EXPORT_FORMATS` in the select element.

    4. **AccessTab.tsx** -- Update the ExportButton call site (line 101) to pass the new prop:
       - Change `<ExportButton datasetId={datasetId} datasetName={dataset.title} />` to
         `<ExportButton datasetId={datasetId} datasetName={dataset.title} recordType={dataset.record_type} />`
       - The `dataset` object is already in scope in this component.

    5. **AccessSharingTab.tsx** -- Same change as AccessTab.tsx (line 101):
       - Change `<ExportButton datasetId={datasetId} datasetName={dataset.title} />` to
         `<ExportButton datasetId={datasetId} datasetName={dataset.title} recordType={dataset.record_type} />`
       - The `dataset` object is already in scope in this component.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>Overview tab hides geometry type for tables and says "Row Count" instead of "Feature Count"; Data tab hidden from tab bar for table datasets; Shapefile export option removed for table datasets; all ExportButton call sites pass recordType prop</done>
</task>

<task type="auto">
  <name>Task 3: Write review report with remaining recommendations</name>
  <files>
    .planning/quick/260325-bsk-review-the-non-spatial-data-page-ui-ux-a/260325-bsk-REVIEW.md
  </files>
  <action>
    Write a concise review report documenting:

    **Fixed items** (from Tasks 1-2):
    - Added 'table' RecordTypeBadge (orange, Table2 icon)
    - Hidden AddToMapButton and ConnectDropdown for table datasets
    - Changed "features" to "rows" in stats line for tables
    - Hidden geometry type field in overview when null
    - Changed "Feature Count" to "Row Count" label in overview for tables
    - Hidden redundant Data tab in VectorDetailPanel for table datasets
    - Filtered Shapefile from export formats for table datasets
    - Passed recordType prop to ExportButton in AccessTab and AccessSharingTab

    **Already handled (no fix needed):**
    - **SRID in stats line for tables** -- The existing `{dataset.srid && (...)}` null-check in DatasetPage.tsx (line 479) already suppresses the SRID display for table datasets, since tables have `srid: null`. No code change required. (RESEARCH Finding 9 -- resolved by existing guard.)

    **Remaining recommendations** (larger items for future work):
    1. **StructureTab data preview duplication** -- StructureTab renders an `<AttributeTable>` as "Data Preview" section. For table datasets with the hero data grid, this is a third rendering. Consider removing the preview from StructureTab for tables, or making it a collapsed/expandable section.
    2. **DatasetDetailSkeleton layout shift** -- Skeleton shows map-height placeholder (h-80/h-96) but table hero is 60vh. Minor layout shift on load. Could detect record_type from URL params or accept a hint prop.
    3. **ConnectDropdown for tables** -- Currently fully hidden. Could show just "Copy API URL" (the OGC Features endpoint) without tile URL. Low priority since the Access tab already has API info.
    4. **Search card terminology** -- Search result cards use `card.featureCount_one/other` ("X features"). Non-spatial datasets in search results also show "features". Could add `card.rowCount_one/other` and switch based on record_type.
  </action>
  <verify>
    <automated>test -f /Users/ishiland/Code/geolens/.planning/quick/260325-bsk-review-the-non-spatial-data-page-ui-ux-a/260325-bsk-REVIEW.md && echo "PASS"</automated>
  </verify>
  <done>Review report exists with fixed items checklist, SRID finding resolved note, and future recommendations documented</done>
</task>

</tasks>

<verification>
- `npx tsc --noEmit` passes with no errors
- Navigate to http://localhost:8080/datasets/97fafb8a-8eaa-4a70-a46b-3193bca792fd#data and confirm:
  - Orange "Table" badge visible in stats line
  - No "Add to Map" button
  - No "Connect" dropdown
  - Stats line says "X rows" not "X features"
  - Overview tab has no "Geometry Type" field
  - Overview tab shows "Row Count" label
  - No "Data" tab in tab bar (hero shows the data)
  - Export dropdown does not offer Shapefile
</verification>

<success_criteria>
- All 7 easy-win fixes applied and TypeScript compiles clean
- Non-spatial table detail page shows only relevant controls and terminology
- No duplicate data grid rendering (hero only, no Data tab for tables)
- Review report documents 4 remaining recommendations for future work
</success_criteria>

<output>
After completion, create `.planning/quick/260325-bsk-review-the-non-spatial-data-page-ui-ux-a/260325-bsk-SUMMARY.md`
</output>
