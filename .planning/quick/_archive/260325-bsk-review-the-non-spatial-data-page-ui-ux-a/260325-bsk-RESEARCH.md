# Quick Task 260325-bsk: Non-Spatial Data Page UI/UX Review - Research

**Researched:** 2026-03-25
**Domain:** Non-spatial dataset detail page (record_type='table')
**Confidence:** HIGH

## Summary

The non-spatial data page reuses the `VectorDetailPanel` component (same tabs: overview, metadata, data, structure, access) and replaces the hero map with a full-height `DataTab` rendering the `AttributeTable`. The page works but has several gaps compared to spatial dataset detail pages: missing RecordTypeBadge for 'table' type, irrelevant spatial controls shown (Connect dropdown with tile URLs, Add to Map button, geometry type field in overview), and the hero data grid is rendered twice (once as the hero element and again inside the Data tab and Structure tab).

**Primary recommendation:** Fix the table-specific gaps (badge, remove spatial controls, deduplicate data grid) and align the overview identity section for non-spatial datasets.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- General feel match: same design language, spacing, typography -- but non-spatial pages can differ where spatial features don't apply. Not pixel-perfect.
- Fix easy wins (styling, spacing, small UX improvements) and document larger items as recommendations in a review report.
- Focus review on the specific dataset at the provided URL as representative example. No need to test multiple dataset types.

### Claude's Discretion
- None -- all areas discussed.

### Deferred Ideas (OUT OF SCOPE)
- None specified.
</user_constraints>

## Findings

### Finding 1: RecordTypeBadge missing 'table' type (HIGH confidence)

`RecordTypeBadge` in `frontend/src/components/search/RecordTypeBadge.tsx` has configs for `vector_dataset`, `raster_dataset`, `vrt_dataset`, and `collection` but NOT `table`. When `record_type='table'`, the badge returns `null` -- no type indicator is shown in the stats line.

**Fix:** Add a `table` entry to `TYPE_CONFIG` (e.g., `Table` icon from lucide, orange/neutral color scheme).

### Finding 2: Hero data grid duplicated in Data tab (HIGH confidence)

In `DatasetPage.tsx` lines 613-619, when `isTable` is true, the hero section renders:
```tsx
<div className="h-[60vh]">
  <DataTab datasetId={id!} canEdit={isEditor} />
</div>
```

Then `VectorDetailPanel` also renders a Data tab (line 91-93) with the same `<DataTab datasetId={datasetId} canEdit={canEdit} />`. The user sees the identical attribute table twice -- once as the hero and again when clicking the "Data" tab.

Additionally, `StructureTab` (lines 61-68) renders yet another `<AttributeTable>` as a "Data Preview" section.

**Fix options:**
- A) Remove the Data tab from the tab bar for table datasets (hero IS the data view)
- B) Keep the Data tab but skip the hero data grid
- C) (Recommended) Keep hero data grid as the primary view, hide the redundant Data tab content for table record types

### Finding 3: ConnectDropdown shows irrelevant tile URL for tables (HIGH confidence)

`ConnectDropdown.tsx` lines 73-93: the `!isRaster && !isVrt` branch shows "Copy Feature URL" (fine) and "Copy Tile URL" (irrelevant -- non-spatial tables have no geometry for tile rendering). The tile URL `{origin}/tiles/data.{table_name}/{z}/{x}/{y}.pbf` would 404 for a table with no geometry column.

**Fix:** Conditionally hide "Copy Tile URL" when `dataset.geometry_type` is null/None.

### Finding 4: AddToMapButton shown for non-spatial datasets (MEDIUM confidence)

`AddToMapButton` is shown in `leadingContent` for ALL dataset types including tables. Adding a non-spatial table to a map builder would either fail silently or create a broken layer.

**Fix:** Hide `AddToMapButton` when `isTable` is true (or when `dataset.geometry_type` is null).

### Finding 5: Overview identity section shows irrelevant spatial fields (HIGH confidence)

`OverviewTab.tsx` lines 186-199: The identity section shows "Geometry Type" and "Feature Count" for both `vector_dataset` AND `table` (the `!isRaster && !isVrt` condition). For non-spatial tables:
- "Geometry Type" shows "Not available" (since `geometry_type` is null)
- "Feature Count" label says "features" (should say "rows" or "records" for tables)

**Fix:** Hide geometry type field when `dataset.geometry_type` is null. Change "features" to "rows" for table record types.

### Finding 6: Stats line shows "features" for tables (HIGH confidence)

`DatasetPage.tsx` line 477: `{dataset.feature_count.toLocaleString()} features` is shown for tables. "Features" is GIS terminology inappropriate for non-spatial data.

**Fix:** Use "rows" or "records" when `isTable` is true.

### Finding 7: Export formats include spatial-only formats (MEDIUM confidence)

`ExportButton.tsx` offers GeoPackage, GeoJSON, Shapefile, and CSV exports for `!isRaster && !isVrt` datasets, which includes tables. GeoPackage and GeoJSON may work (they support non-spatial), but Shapefile export will fail for tables with no geometry since shapefiles require a geometry column.

**Fix:** Filter export formats for table datasets to show only CSV (and optionally GeoPackage if the backend handles it gracefully).

### Finding 8: DatasetDetailSkeleton shows map placeholder for tables (LOW confidence)

`DatasetDetailSkeleton.tsx` always renders a `Skeleton className="h-80 lg:h-96"` for the hero map. Since we don't know the record type during loading, this is a minor layout shift when the skeleton resolves to a table view (hero data grid is 60vh vs skeleton 80/96).

**Fix:** Minor -- could be addressed later. Layout shift is brief.

### Finding 9: SRID shown in stats line for tables (HIGH confidence)

`DatasetPage.tsx` line 479-484: SRID (EPSG code) is shown in the stats line for `vector_dataset || table`. Non-spatial tables have no CRS/SRID.

**Fix:** Conditionally hide SRID when `dataset.srid` is null (already handled by the conditional, but `dataset.geometry_type` null check would be more semantically correct).

### Finding 10: Edit capabilities allow geometry editing guard but no geometry (LOW confidence)

`DatasetPage.tsx` line 643: `canEdit={isEditor && !isRaster && !isVrt && !isTable}` -- correctly prevents geometry editing for tables. This is already handled properly.

## Priority Summary (Easy Wins vs Recommendations)

### Easy Wins (fix directly)
| # | Issue | Effort | Impact |
|---|-------|--------|--------|
| 1 | Add 'table' to RecordTypeBadge | 5 min | Missing type indicator |
| 3 | Hide tile URL in ConnectDropdown for geometry_type=null | 5 min | Broken/misleading URL |
| 4 | Hide AddToMapButton for table datasets | 2 min | Prevents broken workflow |
| 6 | Change "features" to "rows" in stats line for tables | 5 min | Terminology accuracy |
| 5 | Hide geometry type in overview when null | 5 min | Removes "Not available" noise |
| 9 | SRID conditional (already works, minor) | 0 min | Already gated by null check |

### Larger Items (document as recommendations)
| # | Issue | Effort | Impact |
|---|-------|--------|--------|
| 2 | Deduplicate hero data grid vs Data tab + Structure tab | 30 min | UX confusion -- data shown 3x |
| 7 | Filter export formats for non-spatial | 15 min | Prevents failed shapefile exports |

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection of all components in the rendering path
- `DatasetPage.tsx`, `VectorDetailPanel.tsx`, `DataTab.tsx`, `AttributeTable.tsx`, `ConnectDropdown.tsx`, `AddToMapButton.tsx`, `RecordTypeBadge.tsx`, `OverviewTab.tsx`, `AccessTab.tsx`, `ExportButton.tsx`, `StructureTab.tsx`, `DatasetDetailSkeleton.tsx`
