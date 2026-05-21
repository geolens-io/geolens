---
plan: 1065-03
requirement: IA-P1-02
status: complete
phase: 1065
shipped: 2026-05-20
---

# Plan 1065-03 SUMMARY — Reupload Service-URL Record-Type Guard

## Outcome

`reupload_service_preview` now calls `_assert_compatible_record_type` immediately after `check_dataset_access`, surfacing cross-record-type swaps (VRT, vector→raster) as HTTP 400 before any pipeline execution. The helper was extended with a keyword-only `service_type` parameter; the existing file-path callers (`reupload_dataset` and `request_presigned_reupload`) are untouched and still pass `(dataset, filename)`.

## Diff shape

- `backend/app/modules/catalog/datasets/api/router_reupload.py`:
  - `_assert_compatible_record_type(dataset, filename, *, service_type=None)` — new keyword-only `service_type` arg. New `raster_dataset + service_type` rejection branch added at the bottom (existing branches unchanged).
  - `reupload_service_preview` — one new call after `check_dataset_access`:
    ```python
    _assert_compatible_record_type(dataset, None, service_type=request.service_type)
    ```
- `backend/tests/test_reupload_record_type_guard.py` (new, 96 LOC, 11 tests):
  - 6 service-URL tests (VRT, raster+WFS, raster+ArcGIS, raster+OGC API, vector happy path, table happy path)
  - 5 file-path regression tests (vector+geojson, vector+tif rejected, raster+tif, raster+geojson rejected, VRT-rejected-regardless)

## Service-type coverage rationale

All supported service types in this codebase are vector sources, pinned by `tasks_common._classify_service_type` which only accepts strings starting with `WFS`, `ArcGIS`, or `OGC API`. The new rejection branch fires when `service_type is not None` (only set by the service-URL path) AND `record_type == "raster_dataset"`. This catches the seed's "vector→raster swap" case at the HTTP boundary instead of deep in the pipeline.

## Commits

| SHA | Message |
|-----|---------|
| (current) | `feat(1065-03): cross-record-type guard on service-URL reupload preview` |

## Verification

- **`pytest backend/tests/test_reupload_record_type_guard.py`** — **11/11 passed in 0.92s** ✓
- Pre-existing callers of `_assert_compatible_record_type` (`reupload_dataset` at `:130`, `request_presigned_reupload` at `:595`) unchanged — keyword-only addition is backwards-compatible.

## Threat-mitigation summary

- **Vector→raster service-URL swap**: now rejected at the HTTP boundary with a clear message naming the actual problem. Previously, the pipeline would proceed and explode on a deeper assumption violation (e.g., GDAL VRT driver, COG writer).
- **Any→VRT service-URL swap**: now rejected via the existing VRT branch (filename=None still triggers it because the VRT branch doesn't read the extension).
- **Defense-in-depth**: this is a usability/clarity fix, not a security-critical one. The downstream pipeline would still fail eventually — this just gives users the right error message at the right step.

## Verification deferred to Phase 1070 close-gate

- Backend pytest full suite (will include the 11 new tests).
- Live MCP smoke that exercises a service-URL reupload from the builder UI is out of scope for this minor plan — the unit tests pin the behavior at the function boundary.
