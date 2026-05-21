# Quick Task 260318-sma: Detail Page Round 2 - Context

**Gathered:** 2026-03-19
**Status:** Ready for planning

<domain>
## Task Boundary

Second round of detail page UX improvements based on third-party review of the round 1 changes. Focus on information architecture: what goes where, not styling.

</domain>

<decisions>
## Implementation Decisions

### Scope
- All 5 items in scope:
  1. Create dedicated Access tab (move endpoints/export/tile services out of Overview)
  2. Tighten Overview to be summary-first (remove access/export sections)
  3. Improve map preview fit (auto-fit to extent, tighter container)
  4. Refine Dataset Health with next-step guidance
  5. Sticky tabs on scroll

### Access Tab
- Single shared AccessTab component used across all types (vector, raster, VRT, collection)
- Content adapts based on what's available (downloads, tiles, API, export)
- Tab ordering:
  - Vector: Overview / Metadata / Data / Structure / Access
  - Raster: Overview / Metadata / Access
  - VRT: Overview / Metadata / Sources / Access

### Identity Fields
- Keep all identity fields in Overview including Table Name, Source Format
- Do NOT demote technical fields — they are useful for the target audience

### Claude's Discretion
- Access tab internal layout and grouping
- Map container height adjustment details
- Sticky tab implementation approach (CSS sticky vs intersection observer)
- Health block "next priority" field selection logic

</decisions>

<specifics>
## Specific Ideas

### Access Tab Content (moved from Overview)
- Downloads section (gpkg, geojson, shp, csv for vector; geotiff for raster)
- API Endpoints section (OGC API Features for vector)
- Tile Services section (vector tiles / XYZ tiles)
- Export section (format picker + export button)
- Auth note ("These endpoints accept an X-Api-Key or Authorization: Bearer header")

### Overview After Cleanup
Should contain only:
- Health block (compact)
- Identity section
- Summary (with AI Assist)
- Raster Properties (raster/VRT only)
- Derivation Summary (VRT only)
- Visibility
- Related Datasets
- Used in Maps

### Map Improvements
- Auto-fit to dataset extent more aggressively on load
- Consider slightly smaller default height (h-72 instead of h-80/h-96)

### Health Block Enhancement
- Add "Next priority: [field name]" line
- Show which specific field to fill next

### Sticky Tabs
- Tabs should stick to top when scrolling past them
- Use CSS `position: sticky` with appropriate z-index

</specifics>
