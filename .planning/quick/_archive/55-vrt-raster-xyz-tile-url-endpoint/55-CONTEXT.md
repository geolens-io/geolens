# Quick Task 55: VRT/Raster xyz tile url endpoint - Context

**Gathered:** 2026-03-15
**Status:** Ready for planning

<domain>
## Task Boundary

VRT/Raster xyz tile url endpoint — make XYZ tile URLs fully usable for external GIS tools (QGIS, etc.) with proper auth and consistent connect info for both raster and VRT datasets.

</domain>

<decisions>
## Implementation Decisions

### Auth for external consumers
- Include `?api_key={your_key}` placeholder in the copied XYZ tile URL
- URL becomes: `https://host/raster-tiles/{id}/tiles/{z}/{x}/{y}.png?api_key={your_key}`
- User replaces placeholder with their actual API key

### VRT connect object
- Add `connect` object for VRT datasets (same structure as rasters: tile_url, download_url if applicable)
- Unifies ConnectDropdown logic so VRTs and rasters use the same `connect` path

### URL source of truth
- Backend returns absolute URL using request host (not relative path)
- Frontend simply copies it — single source of truth
- This means `_build_raster_metadata()` needs access to the request to construct `https://{host}/...`

### Claude's Discretion
- None — all areas discussed

</decisions>

<specifics>
## Specific Ideas

- Current state: Raster `connect.tile_url` = `/raster-tiles/{id}/tiles/{z}/{x}/{y}.png` (relative). VRTs have no `connect` object.
- ConnectDropdown (line 73-83) has separate VRT path using `raster.tile_url` instead of `connect.tile_url`
- Backend `_build_raster_metadata()` at `datasets/router.py:147-194` builds the connect object — only for rasters, not VRTs
- `RasterConnect` schema at `datasets/schemas.py:57-60` needs no structural change, just add to VRT path
- API key auth already supported via `?api_key=<key>` in backend auth resolution

</specifics>
