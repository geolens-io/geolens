# Quick Task 260316-bgd: Position Raster/VRT Models for Future STAC Compliance - Context

**Gathered:** 2026-03-16
**Status:** Ready for planning

<domain>
## Task Boundary

Refactor the Raster/VRT data model to position it for future STAC (SpatioTemporal Asset Catalog) compliance. This is a backend-only schema refactor — no frontend changes. The goal is asset-centric schema, lineage-aware metadata, and clean separation of descriptive vs. processing metadata, without implementing STAC serialization or API yet.

</domain>

<decisions>
## Implementation Decisions

### Asset Modeling
- Create a new `dataset_assets` table with STAC-aligned columns: key, media_type, roles[], href
- Each COG, VRT file, thumbnail, and quicklook becomes a separate asset row
- RasterAsset retains internal processing fields only (job status, generation IDs, internal paths)
- Stable asset keys: `data`, `vrt`, `thumbnail`, `overview`, `metadata`

### Metadata Separation
- Column-level separation on the existing RasterAsset model (no new descriptive table)
- Document/group columns clearly as "STAC-facing descriptive" vs. "internal processing"
- Add a `to_stac_properties()` method that extracts only descriptive fields (epsg, bands, nodata, resolution, bbox, datetime)
- Pragmatic approach — avoid extra JOINs, keep migration simple

### Collection Mapping
- Workspace = STAC Collection (natural mapping)
- Workspaces already have extent, metadata, and membership
- No new entity needed — just document this mapping decision in code
- Future STAC export will serialize workspace as Collection

### UI/UX Scope
- Backend only — schema refactor, migrations, API response enrichment
- Frontend continues using existing fields
- New asset data available via API but not surfaced in UI yet

</decisions>

<specifics>
## Specific Ideas

- Auditor's STAC-ready checklist as reference (STAC 1.1.0 spec)
- `position` field already exists on `vrt_source_links` ✓
- Stable asset keys: `data`, `vrt`, `thumbnail`, `overview`, `metadata`
- Roles should use STAC conventions: `data`, `thumbnail`, `metadata`, `overview`
- Band metadata should persist: data_type, nodata, statistics, unit (STAC 1.1 `bands` construct)
- Provider/license/keywords fields should be captured where sensible (workspace-level)

</specifics>

<canonical_refs>
## Canonical References

- STAC Spec 1.1.0: https://github.com/radiantearth/stac-spec
- STAC Asset Best Practices: https://github.com/radiantearth/stac-best-practices/blob/main/best-practices-asset-and-link.md
- STAC Projection Extension: https://github.com/stac-extensions/projection
- STAC Raster Extension: https://github.com/stac-extensions/raster
- STAC Alternate Assets Extension: https://github.com/stac-extensions/alternate-assets

</canonical_refs>
