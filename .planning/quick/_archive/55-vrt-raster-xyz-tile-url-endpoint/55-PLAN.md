---
phase: quick-55
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/datasets/router.py
  - backend/app/datasets/schemas.py
  - frontend/src/components/dataset/ConnectDropdown.tsx
autonomous: true
requirements: [TILE-URL-01, TILE-URL-02, TILE-URL-03]

must_haves:
  truths:
    - "Raster tile URLs in connect object are absolute with api_key placeholder"
    - "VRT datasets return a connect object with tile_url (same structure as rasters)"
    - "ConnectDropdown uses connect.tile_url for both raster and VRT datasets"
    - "Copied tile URL is ready to paste into QGIS with api_key substitution"
  artifacts:
    - path: "backend/app/datasets/router.py"
      provides: "Absolute tile URLs with api_key placeholder in _build_raster_metadata"
      contains: "api_key={your_key}"
    - path: "backend/app/datasets/schemas.py"
      provides: "RasterConnect with optional download_url for VRT support"
      contains: "download_url: str | None"
    - path: "frontend/src/components/dataset/ConnectDropdown.tsx"
      provides: "Unified connect-based dropdown for raster and VRT"
      contains: "connect?.tile_url"
  key_links:
    - from: "backend/app/datasets/router.py"
      to: "RasterConnect schema"
      via: "_build_raster_metadata builds absolute URLs using request base_url"
      pattern: "base_url.*raster-tiles"
    - from: "frontend/src/components/dataset/ConnectDropdown.tsx"
      to: "dataset.raster.connect.tile_url"
      via: "Direct copy of backend-provided absolute URL"
      pattern: "connect.*tile_url"
---

<objective>
Make XYZ tile URLs fully usable for external GIS tools by returning absolute URLs with api_key placeholder from the backend, and unify ConnectDropdown so VRT datasets use the same connect object as rasters.

Purpose: Users copying tile URLs get a ready-to-use absolute URL with auth placeholder, and VRT datasets get first-class connect support.
Output: Backend returns absolute tile URLs with `?api_key={your_key}`, VRTs get connect object, frontend simplified.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@backend/app/datasets/router.py (lines 147-230 — _build_raster_metadata and _dataset_to_response)
@backend/app/datasets/schemas.py (lines 57-79 — RasterConnect and RasterMetadata)
@frontend/src/components/dataset/ConnectDropdown.tsx

<interfaces>
<!-- Current schemas and functions the executor needs -->

From backend/app/datasets/schemas.py:
```python
class RasterConnect(BaseModel):
    download_url: str
    tile_url: str
    s3_uri: str | None = None
```

From backend/app/datasets/router.py:
```python
def _build_raster_metadata(dataset, raster_asset, is_admin: bool = False, source_count: int | None = None) -> RasterMetadata | None:
    # Called from _dataset_to_response (line 229)
    # Builds connect with relative URLs currently

def _dataset_to_response(dataset, *, collections=None, actors_by_id=None, raster_asset=None, is_admin: bool = False, source_count: int | None = None) -> DatasetResponse:
    # Callers:
    #   line 338 — list_all_datasets (no request param currently)
    #   line 423 — create_empty_dataset_endpoint (no request param, body param named `request`)
    #   line 520 — get_single_dataset (has request)
    #   line 791 — update_dataset_metadata (has request)
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Backend — absolute tile URLs with api_key and VRT connect object</name>
  <files>backend/app/datasets/schemas.py, backend/app/datasets/router.py</files>
  <action>
1. In `schemas.py`, make `RasterConnect.download_url` optional (`str | None = None`) so VRT datasets can omit it (VRTs are generated artifacts, not downloadable as single COG).

2. In `router.py`, add `base_url: str | None = None` parameter to both `_build_raster_metadata` and `_dataset_to_response`.

3. In `_build_raster_metadata`:
   - When `base_url` is provided, build absolute tile URL: `{base_url}/raster-tiles/{dataset.id}/tiles/{{z}}/{{x}}/{{y}}.png?api_key={{your_key}}`
   - When `base_url` is provided, build absolute download URL: `{base_url}/api/datasets/{dataset.id}/download/cog` (only for non-VRT)
   - When `base_url` is None, keep current relative URLs (backward compat for callers without request)
   - Build `connect` for ALL record types (not just rasters). For VRT datasets, set `download_url=None` in RasterConnect. The `tile_url` and `s3_uri` fields apply to both.
   - The top-level `tile_url` on RasterMetadata (line 187) should also become absolute when base_url provided.
   - The `quicklook_url` (line 186) should also become absolute when base_url provided.

4. In `_dataset_to_response`, pass `base_url` through to `_build_raster_metadata`.

5. Update callers to pass `base_url`:
   - `get_single_dataset` (line 520): has `request` — pass `base_url=str(request.base_url).rstrip("/")`
   - `list_all_datasets` (line 280): add `request: Request` parameter, pass `base_url=str(request.base_url).rstrip("/")`
   - `update_dataset_metadata` (line 791): has `request` — pass `base_url=str(request.base_url).rstrip("/")`
   - `create_empty_dataset_endpoint` (line 406): the existing body parameter is named `request` (type `CreateEmptyDatasetRequest`) which conflicts with Starlette's `Request`. First rename the body parameter from `request` to `body` throughout the function (parameter declaration and all references within the function body). Then add `request: Request` (from `starlette.requests import Request`) as a new parameter. Pass `base_url=str(request.base_url).rstrip("/")`.

Note: `request.base_url` in Starlette returns the scheme+host (e.g., `https://localhost:8080`). Use `str(request.base_url).rstrip("/")` to get clean base.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && python -c "
from app.datasets.schemas import RasterConnect, RasterMetadata
# Verify download_url is optional
c = RasterConnect(tile_url='http://host/tiles', download_url=None)
assert c.download_url is None
print('Schema OK')
"</automated>
  </verify>
  <done>
- `_build_raster_metadata` returns absolute URLs when base_url provided
- tile_url includes `?api_key={your_key}` placeholder
- VRT datasets get connect object with tile_url (download_url=None)
- All 4 callers of `_dataset_to_response` pass base_url from request
- `create_empty_dataset_endpoint` body param renamed from `request` to `body` to avoid shadowing Starlette Request
  </done>
</task>

<task type="auto">
  <name>Task 2: Frontend — simplify ConnectDropdown to use unified connect object</name>
  <files>frontend/src/components/dataset/ConnectDropdown.tsx</files>
  <action>
Simplify ConnectDropdown now that backend returns absolute URLs in connect for both raster and VRT datasets:

1. Remove the separate VRT path (lines 73-84 that use `dataset.raster?.tile_url`). VRTs now use `connect.tile_url` just like rasters.

2. For raster AND VRT tile URL copy: use `dataset.raster?.connect?.tile_url` directly (no `window.location.origin` prefix — URL is already absolute from backend).

3. For raster COG download URL: use `dataset.raster?.connect?.download_url` directly (already absolute). Only show when `download_url` is truthy (VRTs won't have it).

4. For S3 URI: keep as-is (already a direct value, not a URL).

5. The condition for showing tile URL should be `(isRaster || isVrt) && dataset.raster?.connect?.tile_url` — unified for both types.

6. The condition for showing COG download should be `isRaster && dataset.raster?.connect?.download_url` — raster only.

7. Remove `window.location.origin` prefix from all raster/VRT URLs since backend now provides absolute URLs.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit --pretty 2>&1 | head -30</automated>
  </verify>
  <done>
- ConnectDropdown uses `connect.tile_url` for both raster and VRT
- No `window.location.origin` prefix on raster/VRT URLs
- VRT tile URL shown via same connect path as raster
- COG download URL only shown for raster_dataset (not VRT)
- TypeScript compiles without errors
  </done>
</task>

</tasks>

<verification>
1. Backend returns absolute tile URL with api_key placeholder for raster dataset
2. Backend returns absolute tile URL with api_key placeholder for VRT dataset
3. VRT dataset response has `raster.connect.tile_url` (not just `raster.tile_url`)
4. VRT dataset response has `raster.connect.download_url` as null
5. ConnectDropdown shows XYZ Tile URL for both raster and VRT datasets
6. Copied URL is absolute and contains `?api_key={your_key}`
</verification>

<success_criteria>
- GET /api/datasets/{raster_id} returns `raster.connect.tile_url` as absolute URL with `?api_key={your_key}`
- GET /api/datasets/{vrt_id} returns `raster.connect.tile_url` as absolute URL with `?api_key={your_key}`
- GET /api/datasets/{vrt_id} returns `raster.connect.download_url` as null
- ConnectDropdown copies absolute tile URL for both raster and VRT datasets
- Frontend TypeScript compiles clean
</success_criteria>

<output>
After completion, create `.planning/quick/55-vrt-raster-xyz-tile-url-endpoint/55-SUMMARY.md`
</output>