---
phase: 260331-izv
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/services/preview.py
  - backend/app/services/router.py
  - backend/app/datasets/router_reupload.py
autonomous: true
requirements: [FIX-502-PREVIEW]

must_haves:
  truths:
    - "ArcGIS preview queries request only 5 features via resultRecordCount, not the full maxRecordCount"
    - "Preview timeout is 120s instead of 60s for extra resilience against slow ArcGIS services"
    - "Full ingestion paths (ingest_service, reupload_service) are NOT affected -- they still fetch all features"
  artifacts:
    - path: "backend/app/services/preview.py"
      provides: "build_gdal_source with optional result_limit param, run_service_preview with 120s default timeout"
      contains: "resultRecordCount"
    - path: "backend/app/services/router.py"
      provides: "preview_service_layer passes result_limit=5 to build_gdal_source"
      contains: "result_limit=5"
    - path: "backend/app/datasets/router_reupload.py"
      provides: "reupload_service_preview passes result_limit=5 to build_gdal_source"
      contains: "result_limit=5"
  key_links:
    - from: "backend/app/services/router.py"
      to: "backend/app/services/preview.py"
      via: "build_gdal_source(result_limit=5)"
      pattern: "build_gdal_source.*result_limit"
    - from: "backend/app/datasets/router_reupload.py"
      to: "backend/app/services/preview.py"
      via: "build_gdal_source(result_limit=5)"
      pattern: "build_gdal_source.*result_limit"
    - from: "backend/app/ingest/tasks.py"
      to: "backend/app/services/preview.py"
      via: "build_gdal_source() with NO result_limit (full fetch)"
      pattern: "build_gdal_source\\("
---

<objective>
Fix 502 errors on ArcGIS service imports triggered by seed-ago-data.py.

Purpose: ArcGIS preview requests fetch up to maxRecordCount features (1000-2000) because the ESRIJSON query URL has no `resultRecordCount` limit. With complex geometries or slow services, ogrinfo exceeds the 60s timeout, causing 502 errors. Adding `resultRecordCount=5` to preview queries and increasing the timeout to 120s fixes this without affecting full ingestion.

Output: Patched preview.py, router.py, and router_reupload.py
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@backend/app/services/preview.py
@backend/app/services/router.py
@backend/app/datasets/router_reupload.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add result_limit parameter to build_gdal_source and increase preview timeout</name>
  <files>backend/app/services/preview.py</files>
  <action>
In `build_gdal_source()` (line 14):
- Add parameter `result_limit: int | None = None` after the existing `order_field` parameter.
- In the ArcGIS branch (line 30-36), after building `query_url` with the existing `&orderByFields=` and before the token append, add:
  ```python
  if result_limit is not None:
      query_url += f"&resultRecordCount={result_limit}"
  ```
  Place this BEFORE the token append (`if token: query_url += ...`) so the URL parameter order is: f=json, where, orderByFields, resultRecordCount, token.

In `run_service_preview()` (line 41):
- Change the `timeout` default from `60.0` to `120.0`.

Do NOT change the WFS branch -- `resultRecordCount` is ArcGIS-specific.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && python -c "
from backend.app.services.preview import build_gdal_source
# Test with result_limit
src, _ = build_gdal_source('ArcGIS', 'https://example.com/server/rest/services/Test/FeatureServer', 'TestLayer', 0, result_limit=5)
assert 'resultRecordCount=5' in src, f'Missing resultRecordCount in: {src}'
# Test without result_limit (ingestion path)
src2, _ = build_gdal_source('ArcGIS', 'https://example.com/server/rest/services/Test/FeatureServer', 'TestLayer', 0)
assert 'resultRecordCount' not in src2, f'Unexpected resultRecordCount in: {src2}'
# Test with token and result_limit (token should come after)
src3, _ = build_gdal_source('ArcGIS', 'https://example.com/server/rest/services/Test/FeatureServer', 'TestLayer', 0, token='abc', result_limit=5)
assert 'resultRecordCount=5' in src3 and 'token=abc' in src3, f'Bad URL: {src3}'
print('All preview.py checks passed')
"</automated>
  </verify>
  <done>build_gdal_source accepts result_limit and appends resultRecordCount for ArcGIS URLs when set. run_service_preview defaults to 120s timeout. Existing callers without result_limit are unaffected.</done>
</task>

<task type="auto">
  <name>Task 2: Pass result_limit=5 from all preview callers</name>
  <files>backend/app/services/router.py, backend/app/datasets/router_reupload.py</files>
  <action>
In `backend/app/services/router.py`, function `preview_service_layer()`:

1. First call to `build_gdal_source` (line ~228): add `result_limit=5`:
   ```python
   gdal_source, layer_arg = build_gdal_source(
       request.service_type,
       request.url,
       request.layer_name,
       request.layer_id,
       token=request.token,
       order_field=request.object_id_field or "OBJECTID",
       result_limit=5,
   )
   ```

2. Retry call to `build_gdal_source` (line ~273): add `result_limit=5`:
   ```python
   retry_source, retry_layer = build_gdal_source(
       request.service_type,
       request.url,
       unqualified,
       request.layer_id,
       token=request.token,
       order_field=request.object_id_field or "OBJECTID",
       result_limit=5,
   )
   ```

In `backend/app/datasets/router_reupload.py`, function `reupload_service_preview()`:

1. The call to `build_gdal_source` (line ~140): add `result_limit=5`:
   ```python
   gdal_source, layer_arg = build_gdal_source(
       request.service_type,
       request.url,
       request.layer_name,
       request.layer_id,
       token=request.token,
       order_field=request.object_id_field or "OBJECTID",
       result_limit=5,
   )
   ```

Do NOT modify `backend/app/ingest/tasks.py` -- those calls are for full ingestion and must fetch all features.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && grep -n "result_limit=5" backend/app/services/router.py backend/app/datasets/router_reupload.py && echo "---" && grep -c "result_limit" backend/app/ingest/tasks.py | grep -q "^0$" && echo "ingest/tasks.py correctly has NO result_limit" || echo "FAIL: ingest/tasks.py should not have result_limit"</automated>
  </verify>
  <done>All three preview call sites pass result_limit=5. Ingestion call sites in ingest/tasks.py remain unchanged (no result_limit, fetching all features).</done>
</task>

</tasks>

<verification>
1. `grep -n "resultRecordCount" backend/app/services/preview.py` -- confirms the URL parameter is appended
2. `grep -n "result_limit=5" backend/app/services/router.py backend/app/datasets/router_reupload.py` -- confirms both callers pass the limit
3. `grep -n "result_limit" backend/app/ingest/tasks.py` -- confirms ingestion paths are NOT modified (should return 0 matches)
4. `grep -n "timeout.*120" backend/app/services/preview.py` -- confirms increased timeout
</verification>

<success_criteria>
- ArcGIS preview GDAL source URLs include `resultRecordCount=5`
- Preview timeout increased from 60s to 120s
- Full ingestion paths remain unmodified (no result_limit)
- No regressions in existing function signatures (result_limit defaults to None)
</success_criteria>

<output>
After completion, create `.planning/quick/260331-izv-fix-502-errors-on-imports-using-seed-ago/260331-izv-SUMMARY.md`
</output>
