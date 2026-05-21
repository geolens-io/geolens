# Non-Spatial Data Page UI/UX Review

## Fixed Items

1. **Table type badge** -- Added `table` entry to `RecordTypeBadge` TYPE_CONFIG with `Table2` icon and orange styling. Added `card.table` i18n key in all 4 locales (en: "Table", fr: "Table", es: "Tabla", de: "Tabelle").

2. **AddToMapButton hidden** -- Wrapped in `{!isTable && (...)}` in DatasetPage leadingContent. Table datasets have no spatial data to render on a map.

3. **ConnectDropdown hidden** -- Wrapped in `{!isTable && (...)}` in DatasetPage leadingContent. Tile URL and feature tile URL are irrelevant for non-spatial data.

4. **Stats line terminology** -- Changed `{dataset.feature_count.toLocaleString()} features` to use conditional text: `{isTable ? 'rows' : 'features'}`.

5. **Geometry type field hidden** -- Changed OverviewTab condition from `{!isRaster && !isVrt && (` to `{!isRaster && !isVrt && dataset.geometry_type && (` so table datasets (which have `geometry_type: null`) no longer show "Geometry Type: Not available".

6. **Row Count label** -- Changed OverviewTab feature count field to display "Row Count" instead of "Feature Count" when `dataset.record_type === 'table'`.

7. **Data tab deduplication** -- Hidden the Data tab trigger and content in VectorDetailPanel when `isTable` is true. The hero section already shows the full data grid, so the Data tab was a redundant duplicate.

8. **Export format filtering** -- ExportButton now accepts optional `recordType` prop. When `recordType === 'table'`, Shapefile is filtered out (requires geometry column). Updated both AccessTab and AccessSharingTab call sites to pass `recordType={dataset.record_type}`.

## Already Handled (No Fix Needed)

- **SRID in stats line** -- The existing `{dataset.srid && (...)}` null-check in DatasetPage.tsx already suppresses SRID display for table datasets, since tables have `srid: null`. No code change required.

## Remaining Recommendations

### 1. StructureTab data preview duplication
StructureTab renders an `<AttributeTable>` as a "Data Preview" section. For table datasets where the hero is already the data grid, this creates a third rendering of the same data. Consider removing the preview from StructureTab for tables, or making it a collapsed/expandable section.

### 2. DatasetDetailSkeleton layout shift
The skeleton shows a map-height placeholder (`h-80`/`h-96`) but the table hero uses `60vh`. This causes a minor layout shift when loading completes. Could detect `record_type` from URL params or accept a hint prop to size the skeleton correctly.

### 3. ConnectDropdown partial visibility for tables
Currently fully hidden. An alternative would be to show just "Copy API URL" (the OGC Features endpoint) without tile URL. Low priority since the Access tab already surfaces API connection info.

### 4. Search card terminology
Search result cards use `card.featureCount_one/other` ("X features"). Non-spatial datasets in search results also display "features". Could add `card.rowCount_one/other` and switch based on `record_type` for consistency with the detail page.
