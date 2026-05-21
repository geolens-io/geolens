---
status: complete
commit: 8e625822
date: 2026-04-19
---

# Quick Task 260419-pi8: Clean up redundant data on dataset details page

## What changed

Removed redundant data displays where the same field appeared in 2-3 locations across the dataset details page.

### DatasetPage.tsx (-115 lines)
- **RecordTypeStats**: Stripped down from ~110 lines to ~14 lines. Now shows only RecordTypeBadge + record status + visibility badge. Removed: feature count, geometry type, CRS/EPSG, 3D info, elevation, raster band/resolution/EPSG, VRT type/sources/bands/EPSG, updated date.
- **TableHero**: Removed feature_count Badge (stats bar shows rows).
- Cleaned up unused imports: `Mountain`, `computeRasterGsd`, `findElevationColumn`, `getGeometryTypeLabel`, `formatNumber`, `formatRelativeDate`.

### DatasetStatsBar.tsx (-18 lines)
- Removed compression, dimensions, and file size cells from raster/VRT section. Stats bar now shows only: bands, resolution, CRS, sources (VRT), updated.
- Removed unused `formatBytes` import.

### OverviewTab.tsx (-5 lines)
- Removed Updated row from sidebar metadata card.
- Removed SRID row from sidebar metadata card.
- Removed unused `formatRelativeDate` import.

## Result

| Field | Before | After |
|-------|--------|-------|
| Feature count | header + stats bar + TableHero (3x) | stats bar only |
| Geometry type | header + stats bar (2x) | stats bar only |
| CRS/EPSG | header + stats bar + sidebar (3x) | stats bar only |
| Updated | header + stats bar + sidebar (3x) | stats bar only |
| Bands (raster) | header + stats bar + raster card (3x) | stats bar + raster card |
| Resolution (raster) | header + stats bar + raster card (3x) | stats bar + raster card |
| Compression (raster) | stats bar + raster card (2x) | raster card only |
| Dimensions (raster) | stats bar + raster card (2x) | raster card only |
| File size (raster) | stats bar + raster card (2x) | raster card only |

Net: 3 files changed, 5 insertions, 133 deletions.
