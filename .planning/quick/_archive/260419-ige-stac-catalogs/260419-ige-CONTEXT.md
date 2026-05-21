# Quick Task 260419-ige: STAC Catalog Import — Context

**Gathered:** 2026-04-19
**Status:** Ready for planning

<domain>
## Task Boundary

Research and design how STAC catalogs should be ingested/imported into GeoLens, including UI/UX patterns and integration with the existing data catalog.

</domain>

<decisions>
## Implementation Decisions

### Import Mode
- **Remote reference only** — register external STAC Items as datasets pointing to remote COG URLs
- Titiler already serves remote COGs via `/cog/tiles/...?url=` — no download/copy needed
- Lowest storage cost, fastest time to value

### Discovery & Connection
- **URL-based connect** — user pastes a STAC API URL, GeoLens fetches collections, user browses/searches items, selects items to import
- Similar to existing WFS/ArcGIS service import flow in concept
- No preconfigured catalog registry needed initially

### Catalog Integration
- **As raster datasets** — each STAC Item becomes a raster Dataset record with `source_format='stac'`
- STAC Collection maps to a GeoLens Collection (create or assign)
- Metadata maps to existing fields: bbox→spatial_extent, datetime→temporal_start/end, proj:epsg→srid
- `source_url` stores the STAC API endpoint + item ID for provenance

### UI Approach
- **Dedicated STAC import page** — accessible from catalog's "Add Data" flow
- Richer than a dialog tab (STAC needs spatial preview) but focused on import workflow
- Steps: URL input → Collection picker (cards) → Item browser (list + map footprints + date filter) → Preview + bulk import

### Claude's Discretion
- Python STAC client library choice (pystac-client recommended — handles pagination, auth, search)
- Exact metadata field mapping details
- Error handling for unreachable/malformed STAC endpoints

</decisions>

<specifics>
## Specific Ideas

- Titiler's `/cog/tiles/{z}/{x}/{y}?url={remote_cog_url}` enables zero-copy visualization
- pystac-client handles STAC API pagination and cross-collection search
- STAC providers array maps to RecordContact rows (producer→originator, host→distributor)
- STAC Item `datetime` may be null with `start_datetime`/`end_datetime` range — handle both cases
- Consider storing `stac_item_id` and `stac_collection_id` in dataset metadata for round-trip reference

</specifics>

<canonical_refs>
## Canonical References

- STAC Spec: https://stacspec.org/
- STAC API Spec: https://github.com/radiantearth/stac-api-spec
- pystac-client: https://pystac-client.readthedocs.io/
- Existing GeoLens STAC export: backend/app/standards/stac/
- Existing service import: backend/app/processing/ingest/router.py (service/preview, service/commit)

</canonical_refs>
