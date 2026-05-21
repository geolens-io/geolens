# Quick Task 260316-c8k: Address STAC readiness and raster/VRT discovery UX - Context

**Gathered:** 2026-03-16
**Status:** Ready for planning

<domain>
## Task Boundary

Address the current state of STAC readiness. Understand from a UI/UX perspective how raster items/collections can be discovered without overwhelming the main search of the catalog which includes vector data. Follow KISS principles and best UI/UX practices.

</domain>

<decisions>
## Implementation Decisions

### STAC Scope
- Audit & document only: produce a gap analysis of what exists vs. what's needed for STAC 1.1 compliance, with prioritized next steps
- No new STAC endpoints or API changes in this task
- Existing infrastructure: DatasetAsset model, to_stac_properties(), backfill migration

### Discovery Model
- Type filter chips above search results (All / Vector / Raster / VRT)
- Mixed results by default, user narrows by type
- Minimal UI change, leverages existing record_type field

### Search Filtering
- Explicit user-driven chips only — no smart defaults or auto-filtering
- "All" selected by default
- Simple, predictable behavior

### Claude's Discretion
- None — all areas discussed

</decisions>

<specifics>
## Specific Ideas

- User emphasized KISS principles — STAC data should not overwhelm the geospatial catalog
- Filter chips should use existing record_type values from OGC API Records
- Gap analysis should be actionable with clear priority ordering

</specifics>
