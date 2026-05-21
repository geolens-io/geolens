---
phase: quick-57
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/raster/cog.py
  - backend/app/raster/vrt.py
  - backend/app/ingest/tasks.py
autonomous: true
requirements: [CLEANUP-01]

must_haves:
  truths:
    - "No duplicate float_dtypes sets exist in cog.py"
    - "VRT build functions share a single implementation with a separate flag"
    - "No unused variables in raster module"
    - "No redundant imports in tasks.py"
    - "No identical code branches in extract_raster_metadata"
  artifacts:
    - path: "backend/app/raster/cog.py"
      provides: "COG processing with DRY float dtype check and clean metadata extraction"
    - path: "backend/app/raster/vrt.py"
      provides: "Unified VRT build function with dispatch helper"
    - path: "backend/app/ingest/tasks.py"
      provides: "Clean task imports with no redundant local re-imports"
  key_links:
    - from: "backend/app/ingest/tasks.py"
      to: "backend/app/raster/vrt.py"
      via: "build_vrt dispatch helper"
      pattern: "build_vrt"
    - from: "backend/app/raster/cog.py"
      to: "backend/app/raster/cog.py"
      via: "_is_float_dtype helper"
      pattern: "_is_float_dtype"
---

<objective>
Clean up dead code, DRY violations, and unnecessary complexity in the raster and VRT backend modules.

Purpose: Reduce maintenance burden and improve readability of the raster/VRT codebase after rapid v10.0/v10.1 feature development.
Output: Cleaner cog.py, vrt.py, and tasks.py with no behavioral changes.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@backend/app/raster/cog.py
@backend/app/raster/vrt.py
@backend/app/ingest/tasks.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: DRY up cog.py — float dtype helper, dead variable, collapsed branches</name>
  <files>backend/app/raster/cog.py</files>
  <action>
Three targeted fixes in cog.py — no behavioral changes:

1. **Extract `_is_float_dtype(dtype: str) -> bool` helper** (module-level, private).
   The set `{"float32", "float64", "float16", "float", "complex"}` and the `any(f in dtype.lower() for f in ...)` pattern appears identically on lines 182-183 and 213-214. Create:
   ```python
   _FLOAT_DTYPES = {"float32", "float64", "float16", "float", "complex"}

   def _is_float_dtype(dtype: str) -> bool:
       return any(f in dtype.lower() for f in _FLOAT_DTYPES)
   ```
   Replace both usages in `prepare_with_overviews` (line 183) and `_predictor_for_dtype` (line 214).

2. **Remove unused `res` variable** on line 56 of `extract_raster_metadata`.
   `res = src.res` is assigned but never read — `res_x` and `res_y` are computed from `src.transform` instead. Delete the line.

3. **Collapse duplicate branches** in `extract_raster_metadata` (lines 33-48).
   The `elif crs:` branch (lines 35-40) and the `else:` branch (lines 41-48) have identical code — both return raw `src.bounds`. Collapse into a single `else:` branch:
   ```python
   if crs and crs.to_epsg() != 4326:
       bounds_wgs84 = transform_bounds(crs, "EPSG:4326", *src.bounds)
   else:
       bounds_wgs84 = (
           src.bounds.left, src.bounds.bottom,
           src.bounds.right, src.bounds.top,
       )
   ```
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/backend && python -c "from app.raster.cog import extract_raster_metadata, check_and_prepare_cog, _is_float_dtype, _predictor_for_dtype, _FLOAT_DTYPES; assert _is_float_dtype('float32'); assert not _is_float_dtype('uint8'); print('OK')" && python -m pytest tests/test_raster_ingest.py -x -q 2>&1 | tail -5</automated>
  </verify>
  <done>
  - `_FLOAT_DTYPES` constant and `_is_float_dtype()` helper exist and are used in both `prepare_with_overviews` and `_predictor_for_dtype`
  - No `res = src.res` line in `extract_raster_metadata`
  - Only two branches (if/else) for bounds_wgs84 computation, not three
  - All existing raster tests pass
  </done>
</task>

<task type="auto">
  <name>Task 2: DRY up vrt.py — unified build function, and clean up tasks.py imports</name>
  <files>backend/app/raster/vrt.py, backend/app/ingest/tasks.py</files>
  <action>
Two targeted fixes across vrt.py and tasks.py — no behavioral changes:

**vrt.py: Unify `build_spatial_mosaic_vrt` and `build_band_stack_vrt`**

These two functions are nearly identical — they differ only by the `-separate` flag. Create a single private `_build_vrt` and a public dispatch function:

```python
def _build_vrt(
    source_paths: list[str],
    output_path: str,
    resolution_strategy: str,
    *,
    separate: bool = False,
) -> str:
    gdal_res = _RES_MAP[resolution_strategy]
    cmd = ["gdalbuildvrt"]
    if separate:
        cmd.append("-separate")
    cmd.extend(["-resolution", gdal_res, output_path, *source_paths])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gdalbuildvrt failed: {result.stderr}")
    return output_path


def build_vrt(
    vrt_type: str,
    source_paths: list[str],
    output_path: str,
    resolution_strategy: str,
) -> str:
    """Build a VRT file. Dispatches to mosaic or band-stack based on vrt_type."""
    return _build_vrt(
        source_paths, output_path, resolution_strategy,
        separate=(vrt_type == "band_stack"),
    )
```

Keep the original `build_spatial_mosaic_vrt` and `build_band_stack_vrt` as thin wrappers calling `_build_vrt` to maintain backward compatibility (other callers or tests may use them directly):
```python
def build_spatial_mosaic_vrt(source_paths, output_path, resolution_strategy):
    return _build_vrt(source_paths, output_path, resolution_strategy, separate=False)

def build_band_stack_vrt(source_paths, output_path, resolution_strategy):
    return _build_vrt(source_paths, output_path, resolution_strategy, separate=True)
```

Also remove the redundant `env={**os.environ}` from the subprocess.run call — the default `env=None` inherits the parent environment.

**tasks.py: Remove redundant local imports in `ingest_vrt`**

In `ingest_vrt` (starting line 1307), these imports duplicate module-level imports at lines 14-20:
- `from app.raster.cog import extract_raster_metadata, sha256_file` (line 1317, duplicates line 14)
- `from app.raster.quicklook import generate_quicklook` (line 1319, duplicates line 15)
- `from app.raster.vrt import build_band_stack_vrt, build_spatial_mosaic_vrt, resolve_vrt_source_path` (lines 1320-1324, duplicates lines 16-20)

Remove these 4 redundant local import lines from `ingest_vrt`. The module-level imports are sufficient.

Additionally, in both `ingest_vrt` and `regenerate_vrt`, replace the duplicated VRT-type dispatch pattern:
```python
# Before (duplicated in both functions):
if vrt_type == "band_stack":
    await asyncio.to_thread(build_band_stack_vrt, source_paths, vrt_path, resolution_strategy)
else:
    await asyncio.to_thread(build_spatial_mosaic_vrt, source_paths, vrt_path, resolution_strategy)

# After (single call using new build_vrt):
from app.raster.vrt import build_vrt
await asyncio.to_thread(build_vrt, vrt_type, source_paths, vrt_path, resolution_strategy)
```

Update the module-level import in tasks.py to import `build_vrt` instead of (or in addition to) the individual functions, if the individual functions are still needed by any other part of tasks.py. Grep first to confirm — if only the dispatch pattern uses them, replace the import entirely.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/backend && python -c "from app.raster.vrt import build_vrt, build_spatial_mosaic_vrt, build_band_stack_vrt, resolve_vrt_source_path; print('imports OK')" && python -m pytest tests/test_vrt_creation_173.py tests/test_vrt_source_management_174.py -x -q 2>&1 | tail -5</automated>
  </verify>
  <done>
  - `build_vrt()` dispatch function exists in vrt.py and is used by both `ingest_vrt` and `regenerate_vrt` in tasks.py
  - No duplicated VRT-type dispatch if/else blocks in tasks.py
  - No redundant local imports in `ingest_vrt` that shadow module-level imports
  - No `env={**os.environ}` in vrt.py subprocess calls
  - All existing VRT tests pass
  </done>
</task>

</tasks>

<verification>
1. `cd backend && python -m pytest tests/test_raster_ingest.py tests/test_raster_validation.py tests/test_vrt_creation_173.py tests/test_vrt_source_management_174.py -x -q` — all pass
2. `python -c "from app.raster.cog import _FLOAT_DTYPES, _is_float_dtype; from app.raster.vrt import build_vrt"` — new exports importable
3. No behavioral changes — refactor only
</verification>

<success_criteria>
- Zero test regressions in raster and VRT test suites
- float_dtypes defined once as module constant, used via helper
- VRT build logic consolidated into single `_build_vrt` with `separate` flag
- No unused variables in cog.py
- No redundant imports in tasks.py ingest_vrt
- No identical code branches in extract_raster_metadata
</success_criteria>

<output>
After completion, create `.planning/quick/57-review-raster-and-vrt-features-for-dead-/57-SUMMARY.md`
</output>
