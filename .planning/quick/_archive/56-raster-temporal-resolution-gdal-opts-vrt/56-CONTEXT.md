# Quick Task 56: Raster temporal resolution, GDAL opts, VRT help text - Context

**Gathered:** 2026-03-15
**Status:** Ready for planning

<domain>
## Task Boundary

Three related raster import improvements:
1. Temporal resolution for raster searching and metadata
2. GDAL options exposed at import time
3. Help text on Virtual Raster import tab

</domain>

<decisions>
## Implementation Decisions

### Temporal Metadata
- Extract dates from raster metadata (TIFFTAG_DATETIME, etc) via GDAL/rasterio during ingest
- Pre-fill temporal_start/temporal_end if dates found in metadata
- Let user override/enter dates manually in the import preview/review form
- Record.temporal_start and temporal_end fields already exist, just not populated for rasters

### GDAL Import Options (Kitchen Sink)
- **CRS assign**: Allow user to specify EPSG when raster has no CRS (currently rejected)
- **Reprojection**: Allow user to reproject to a target CRS via gdalwarp
- **Resampling method**: Let user choose (nearest, bilinear, cubic, cubicspline, lanczos, average, mode) — used for both reprojection and overview generation
- **Compression**: Let user choose (DEFLATE, ZSTD, LZW, JPEG, WEBP, LERC) — currently hardcoded to DEFLATE
- **NoData override**: Let user assign/override nodata value
- All options should be optional with sensible defaults matching current behavior

### VRT Help Text
- Inline descriptions below each control (mode selector, resolution strategy)
- Short text explaining what each option does and when to use it
- No collapsible guide or separate documentation section

### Claude's Discretion
- UI layout/placement of GDAL options in the import form
- Exact wording of VRT help text

</decisions>

<specifics>
## Specific Ideas

- Current `validate_raster_crs()` rejects missing CRS — should allow it when user provides CRS assign option
- COG conversion in `cog.py` uses hardcoded DEFLATE/512 — needs to accept user-chosen compression/resampling
- `extract_raster_metadata()` should also pull TIFFTAG_DATETIME and other temporal tags
- Search already supports vintage_start/vintage_end params — just need rasters to populate temporal_start/end

</specifics>
