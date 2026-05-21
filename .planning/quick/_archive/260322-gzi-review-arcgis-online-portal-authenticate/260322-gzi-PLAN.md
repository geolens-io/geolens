---
phase: quick-260322-gzi
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/services/router.py
  - backend/app/services/arcgis.py
  - backend/app/services/schemas.py
  - backend/app/services/preview.py
  - backend/app/ingest/tasks.py
  - backend/app/datasets/router.py
  - frontend/src/i18n/locales/en/import.json
  - frontend/src/i18n/locales/es/import.json
  - frontend/src/i18n/locales/fr/import.json
  - frontend/src/i18n/locales/de/import.json
  - backend/tests/test_arcgis_auth.py
autonomous: true
requirements: [AGOL-REVIEW]

must_haves:
  truths:
    - "ArcGIS probe sends token as query parameter only, not Authorization Bearer header"
    - "ArcGIS probe detects error responses in JSON body (code 498/499/403)"
    - "OBJECTID field name is read from layer metadata, not hardcoded"
    - "UX help text accurately describes ArcGIS token generation paths"
  artifacts:
    - path: "backend/app/services/router.py"
      provides: "Service-type-aware auth header injection"
      contains: "X-Esri-Authorization"
    - path: "backend/app/services/arcgis.py"
      provides: "ArcGIS JSON error detection + objectIdField lookup"
      contains: "error"
    - path: "backend/app/services/schemas.py"
      provides: "object_id_field on LayerInfo and ServicePreviewRequest"
      contains: "object_id_field"
    - path: "backend/tests/test_arcgis_auth.py"
      provides: "Test coverage for auth fixes"
      min_lines: 40
  key_links:
    - from: "backend/app/services/router.py"
      to: "backend/app/services/arcgis.py"
      via: "httpx client without ArcGIS Bearer header"
      pattern: "client_headers"
    - from: "backend/app/services/arcgis.py"
      to: "ArcGIS REST API"
      via: "token query param"
      pattern: "token="
    - from: "backend/app/services/schemas.py"
      to: "backend/app/services/preview.py"
      via: "object_id_field threaded to build_gdal_source order_field param"
      pattern: "order_field"
---

<objective>
Fix ArcGIS Online/Portal authenticated layer ingestion bugs and gaps identified in research.

Purpose: Users migrating from ArcGIS Online currently hit silent auth failures because the probe sends incorrect `Authorization: Bearer` headers. ArcGIS error responses (HTTP 200 with error JSON body) go undetected. Help text misleads users about token generation.

Output: Corrected auth handling, ArcGIS error detection, dynamic objectIdField, accurate UX copy, test coverage.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260322-gzi-review-arcgis-online-portal-authenticate/260322-gzi-RESEARCH.md
@backend/app/services/router.py
@backend/app/services/arcgis.py
@backend/app/services/preview.py
@backend/app/services/schemas.py
@backend/app/ingest/tasks.py
@backend/app/datasets/router.py
@frontend/src/i18n/locales/en/import.json

<interfaces>
<!-- Key types and contracts the executor needs -->

From backend/app/services/schemas.py:
```python
class ProbeRequest(BaseModel):
    url: str
    token: str | None = None

class LayerInfo(BaseModel):
    name: str
    title: str | None = None
    geometry_type: str | None = None
    feature_count: int | None = None
    layer_type: str = "layer"
    layer_id: int | str | None = None

class ServicePreviewRequest(BaseModel):
    url: str
    service_type: str
    layer_name: str
    layer_title: str | None = None
    layer_id: int | str | None = None
    token: str | None = None

class ProbeResponse(BaseModel):
    service_type: str  # e.g. "WFS 2.0", "ArcGIS FeatureServer"
    url: str
    layers: list[LayerInfo]
    selected_layer_id: int | str | None = None
```

From backend/app/services/arcgis.py:
```python
async def probe_arcgis_service(base_url: str, client: httpx.AsyncClient, token: str | None = None) -> dict | None
async def enrich_arcgis_feature_counts(base_url: str, layers: list[dict], client: httpx.AsyncClient, token: str | None = None) -> list[dict]
```

From backend/app/services/preview.py:
```python
def build_gdal_source(service_type: str, base_url: str, layer_name: str, layer_id: int | str | None = None, token: str | None = None) -> tuple[str, str]
```

From backend/app/datasets/router.py (line 1337):
```python
gdal_source, layer_arg = build_gdal_source(
    request.service_type, request.url, request.layer_name, request.layer_id, token=request.token,
)
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix ArcGIS auth header bug and add JSON error detection</name>
  <files>backend/app/services/router.py, backend/app/services/arcgis.py, backend/app/services/schemas.py, backend/app/services/preview.py, backend/app/ingest/tasks.py, backend/app/datasets/router.py, backend/tests/test_arcgis_auth.py</files>
  <action>
**1. Fix service-type-aware auth in router.py (lines 57-59):**

Remove the blanket `Authorization: Bearer {token}` from the httpx client default headers. The token should NOT be set on the httpx client at all -- each probe function handles auth its own way:
- ArcGIS: uses `&token={token}` query param (already correct in `arcgis.py:86`)
- WFS: uses `Authorization: Bearer {token}` header (set per-request or via env)

Change the httpx client creation to NOT include any default auth headers. Instead, for WFS probing, pass the token header at the individual request level. The simplest approach: create the httpx client without headers, and let `probe_wfs()` and `probe_arcgis_service()` handle auth themselves (they already do via query params for ArcGIS). For WFS, check `backend/app/services/wfs.py` to see if it already handles token via headers -- if not, add `headers={"Authorization": f"Bearer {token}"}` to WFS probe requests.

**2. Add ArcGIS JSON error detection in arcgis.py `probe_arcgis_service()`:**

After `data = response.json()` (line 94), BEFORE checking for `layers`/`tables`, check for ArcGIS error responses:
```python
# ArcGIS returns HTTP 200 with error in JSON body
if "error" in data:
    error_info = data["error"]
    code = error_info.get("code", 0)
    message = error_info.get("message", "Unknown ArcGIS error")
    logger.warning("ArcGIS error response", url=base_url, code=code, message=message)
    if code in (498, 499):  # Invalid/expired token
        raise httpx.HTTPStatusError(
            f"ArcGIS token error ({code}): {message}",
            request=response.request,
            response=response,
        )
    return None
```

This ensures token errors (498=invalid token, 499=token required) propagate up as auth errors that the router catches at line 86-104, giving users the "requires authentication" message.

**3. Add objectIdField detection in arcgis.py:**

In `probe_arcgis_service()`, extract and return `objectIdField` from the service metadata. ArcGIS services declare which field is the OID via `data.get("objectIdField")` at the service level, or per-layer at `layer.get("objectIdField")`. Fall back to "OBJECTID" if not present.

Add an `objectIdField` key to each layer dict in the returned result:
```python
for layer in data.get("layers", []):
    layers.append({
        "id": layer["id"],
        "name": layer["name"],
        "geometry_type": _normalize_esri_geom_type(layer.get("geometryType")),
        "type": "layer",
        "object_id_field": layer.get("objectIdField") or data.get("objectIdField") or "OBJECTID",
    })
```

**4. Add `object_id_field` to schemas in schemas.py:**

Add `object_id_field: str | None = None` to both `LayerInfo` and `ServicePreviewRequest` models:

```python
class LayerInfo(BaseModel):
    name: str
    title: str | None = None
    geometry_type: str | None = None
    feature_count: int | None = None
    layer_type: str = "layer"
    layer_id: int | str | None = None
    object_id_field: str | None = None  # ArcGIS OID field name

class ServicePreviewRequest(BaseModel):
    url: str
    service_type: str
    layer_name: str
    layer_title: str | None = None
    layer_id: int | str | None = None
    token: str | None = None
    object_id_field: str | None = None  # ArcGIS OID field name for orderByFields
```

This lets the frontend pass the detected OID field name from the probe response through to preview/commit.

**5. Use dynamic objectIdField in preview.py `build_gdal_source()`:**

Add an optional `order_field: str = "OBJECTID"` parameter to `build_gdal_source()` and use it:
```python
def build_gdal_source(service_type: str, base_url: str, layer_name: str, layer_id: int | str | None = None, token: str | None = None, order_field: str = "OBJECTID") -> tuple[str, str]:
```
```python
query_url = f"{base_url}/{layer_id}/query?f=json&where=1%3D1&orderByFields={order_field}+ASC"
```

**6. Thread `object_id_field` through all `build_gdal_source()` call sites:**

There are 3 call sites that need the new `order_field` kwarg:

- **backend/app/services/router.py** (service preview endpoint): pass `order_field=request.object_id_field or "OBJECTID"` to `build_gdal_source()`
- **backend/app/datasets/router.py** (line 1337): pass `order_field=request.object_id_field or "OBJECTID"` to `build_gdal_source()`
- **backend/app/ingest/tasks.py** (lines 336 and 835, plus retry at line 365): thread `object_id_field` from the job's user_meta or service preview request through to `build_gdal_source()`. The job metadata should carry the OID field; read it from `um.get("object_id_field", "OBJECTID")` and pass as `order_field=` kwarg.

Since the default is `"OBJECTID"`, existing calls without the kwarg remain backward-compatible.

**7. Write tests in backend/tests/test_arcgis_auth.py:**

Test cases:
- `test_arcgis_probe_no_bearer_header`: Mock httpx client, verify no `Authorization` header is sent to ArcGIS URLs
- `test_arcgis_error_498_raises`: Mock ArcGIS JSON error response `{"error": {"code": 498, "message": "Invalid token"}}`, verify HTTPStatusError is raised
- `test_arcgis_error_499_raises`: Same for code 499
- `test_arcgis_object_id_field_extraction`: Verify `object_id_field` is extracted from layer metadata
- `test_build_gdal_source_custom_oid`: Verify `build_gdal_source` uses custom OID field in orderByFields

Use pytest + httpx mocking (respx or unittest.mock).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && python -m pytest backend/tests/test_arcgis_auth.py -x -v</automated>
  </verify>
  <done>
    - ArcGIS probe does NOT send Authorization Bearer header on httpx client
    - ArcGIS JSON error responses (code 498/499) raise HTTPStatusError caught by router as auth errors
    - objectIdField read from service metadata, not hardcoded as OBJECTID
    - LayerInfo and ServicePreviewRequest schemas include object_id_field
    - build_gdal_source uses dynamic OID field in orderByFields
    - All 3 call sites (services/router.py, datasets/router.py, ingest/tasks.py) thread object_id_field
    - 5 tests pass covering all fixes
  </done>
</task>

<task type="auto">
  <name>Task 2: Fix UX help text for ArcGIS token guidance</name>
  <files>frontend/src/i18n/locales/en/import.json, frontend/src/i18n/locales/es/import.json, frontend/src/i18n/locales/fr/import.json, frontend/src/i18n/locales/de/import.json</files>
  <action>
Update the token-related i18n strings in all 4 locale files. The current text is misleading ("Bearer token" terminology, only mentions API Keys path).

**Changes to make in each locale file:**

1. `serviceUrl.tokenPlaceholder`: Remove "Bearer token" phrasing. Change to "ArcGIS token or API key" (no mention of Bearer since ArcGIS does not use Bearer auth).

2. `serviceUrl.tokenHelpText`: Rewrite to cover BOTH token generation paths:
   - API Keys path (existing): your-org.maps.arcgis.com > Settings > API Keys
   - generateToken path (NEW): For username/password, visit your-org.maps.arcgis.com/sharing/rest/generateToken
   - Note about token expiry: tokens expire (default 60 min), request longer expiry for large datasets
   - Keep "Token is not stored" note

**English (en/import.json):**
```json
"tokenPlaceholder": "ArcGIS token, API key, or WFS access token",
"tokenHelpText": "For ArcGIS Online: use an API Key from your-org.maps.arcgis.com > Settings, or generate a token at your-org.maps.arcgis.com/sharing/rest/generateToken. Tokens expire (default 60 min) -- request longer expiry for large datasets. For WFS, use your provider's access token. Not stored."
```

**Spanish (es/import.json):**
Translate the English text to Spanish, following the existing tone/style in that file.

**French (fr/import.json):**
Translate the English text to French, following the existing tone/style in that file.

**German (de/import.json):**
Translate the English text to German, following the existing tone/style in that file.

Do NOT change `tokenLabel` -- "Access Token (optional)" is accurate and clear.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && node -e "const en = require('./frontend/src/i18n/locales/en/import.json'); const hp = en.serviceUrl.tokenHelpText; if (!hp.includes('generateToken')) { process.exit(1); } if (hp.includes('Bearer')) { process.exit(1); } console.log('OK');"</automated>
  </verify>
  <done>
    - tokenPlaceholder no longer mentions "Bearer" in any locale
    - tokenHelpText mentions both API Keys AND generateToken paths in all 4 locales
    - tokenHelpText includes token expiry warning
    - tokenHelpText retains "not stored" security note
  </done>
</task>

</tasks>

<verification>
1. `cd /Users/ishiland/Code/geolens && python -m pytest backend/tests/test_arcgis_auth.py -x -v` -- all auth fix tests pass
2. `cd /Users/ishiland/Code/geolens && python -m pytest backend/tests/ -x -q --timeout=60` -- no regressions in existing tests
3. Verify no `Authorization.*Bearer` in arcgis.py or router.py default headers for ArcGIS paths
4. Verify `generateToken` appears in all 4 locale tokenHelpText strings
</verification>

<success_criteria>
- ArcGIS authenticated layer probing sends token ONLY via query parameter, never as Authorization Bearer header
- ArcGIS 200-with-error JSON responses (token invalid/expired) are detected and surfaced as auth errors to users
- OBJECTID field name is dynamically read from service metadata, not hardcoded
- object_id_field threaded through schemas, preview, datasets router, and ingest tasks
- Help text accurately guides AGOL migration users to generate tokens via both API Keys and generateToken paths
- All new tests pass, no regressions in existing test suite
</success_criteria>

<output>
After completion, create `.planning/quick/260322-gzi-review-arcgis-online-portal-authenticate/260322-gzi-SUMMARY.md`
</output>
