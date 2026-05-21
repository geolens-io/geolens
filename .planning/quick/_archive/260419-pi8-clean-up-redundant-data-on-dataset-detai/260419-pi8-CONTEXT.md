# Quick Task 260419-pi8: Clean up redundant data on dataset details page - Context

**Gathered:** 2026-04-19
**Status:** Ready for planning

<domain>
## Task Boundary

Remove redundant data displays on the dataset details page where the same field appears in 2-3 places (header stats line, stats bar, overview sidebar, raster properties card).

</domain>

<decisions>
## Implementation Decisions

### Primary quick-reference display
- **Stats bar is primary** — strip inline stats from `RecordTypeStats` header component
- Header keeps only: RecordTypeBadge, record status badge, visibility badge
- Remove from header: feature count, geometry type, CRS/EPSG, 3D info, elevation, updated date
- Remove from header (raster): band count, resolution, EPSG
- Remove from header (VRT): vrt_type, source count, band count, EPSG

### Overview sidebar metadata card
- **Strip duplicates** — remove Updated and SRID from sidebar
- Keep unique-to-sidebar fields: license, source, source format, maintainer, created, cadence, bbox

### Raster stats bar vs Raster Properties card
- **Raster Properties card is primary** for full detail
- Remove from stats bar (raster/VRT): compression, dimensions, file size
- Stats bar keeps only top-level summary: bands, resolution, CRS

### TableHero badge
- Remove feature_count badge from TableHero — stats bar already shows it

</decisions>

<specifics>
## Specific Ideas

No specific requirements — straightforward removal of duplicate displays per decisions above.

</specifics>
