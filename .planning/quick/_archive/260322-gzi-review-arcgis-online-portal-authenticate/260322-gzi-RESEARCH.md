# Quick Task 260322-gzi: ArcGIS Online/Portal Auth Ingestion Review - Research

**Researched:** 2026-03-22
**Domain:** ArcGIS REST API authentication + GDAL ESRIJSON driver
**Confidence:** HIGH

## Summary

The current ArcGIS ingestion pipeline has several correctness issues around token handling that explain why authenticated AGOL layers may fail. The code sends `Authorization: Bearer {token}` as an httpx client header during probing, but ArcGIS does NOT use the standard `Authorization` header -- it uses either a `token=` query parameter or the proprietary `X-Esri-Authorization: Bearer {token}` header. Additionally, the ogr2ogr ingestion path for ArcGIS completely ignores the token for HTTP headers (only WFS gets `GDAL_HTTP_HEADERS`), relying solely on the token embedded in the ESRIJSON URL -- which is correct for the ESRIJSON driver but means the probe is using the wrong auth mechanism.

**Primary recommendation:** Fix the httpx probe to use `token=` query params (already done in `arcgis.py`) and remove the incorrect `Authorization: Bearer` header for ArcGIS requests. The ESRIJSON URL-embedded token approach for ogr2ogr is correct and should be kept.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Current token approach may not work correctly with ArcGIS Online -- verify what AGOL actually accepts
- Investigate whether username/password auth is feasible (ArcGIS generateToken endpoint)
- Persisting credentials is acceptable IF securely stored (encrypted at rest)
- Audit both URL query param token placement and header-based approaches
- Audit current gaps: document what auth types exist in AGOL ecosystem and which ones the current code handles vs doesn't
- Don't implement full OAuth -- focus on identifying gaps and documenting them
- Verify GDAL's FEATURE_SERVER_PAGING actually works correctly with ArcGIS server-imposed limits
- Confirm the ESRIJSON driver handles pagination properly during ogr2ogr ingestion
- Full UX audit of the import flow for an AGOL migration user persona
- Review error messages, token input discoverability, and guidance quality

### Claude's Discretion
- Specific code fix recommendations vs. documentation-only findings
- Priority ordering of issues found
</user_constraints>

## Finding 1: Probe Sends Wrong Auth Header (BUG -- HIGH)

**Location:** `backend/app/services/router.py` lines 57-59

```python
client_headers = {}
if request.token:
    client_headers["Authorization"] = f"Bearer {request.token}"
```

The httpx client is created with `Authorization: Bearer {token}` in its default headers. This header is sent on EVERY request the client makes, including to ArcGIS endpoints.

**The problem:** ArcGIS REST API does NOT recognize `Authorization: Bearer` headers. ArcGIS uses:
1. **Query parameter:** `?token={token}` (legacy, universally supported)
2. **Custom header:** `X-Esri-Authorization: Bearer {token}` (ArcGIS Server 10.5.1+, recommended)

The standard HTTP `Authorization: Bearer` header is ONLY used for OAuth2-based flows with ArcGIS identity platform, NOT for ArcGIS-generated tokens passed to service endpoints.

**Impact:** The Bearer header is silently ignored by ArcGIS servers. However, `arcgis.py:probe_arcgis_service()` already appends `&token={token}` to the query string (line 86), which IS correct. So the probe likely works despite the incorrect header -- the query param saves it. But the wrong header is wasteful and could cause issues with proxies or web-tier-secured ArcGIS servers that DO inspect `Authorization` headers for other auth schemes.

**Fix:** For ArcGIS probing, do NOT set the `Authorization` header. The query param approach in `arcgis.py` is already correct. For WFS, `Authorization: Bearer` may be appropriate depending on the WFS provider. The fix should be service-type-aware: only set the header for WFS, and rely on query params for ArcGIS.

**Source:** [Esri HTTP Authorization Headers docs](https://developers.arcgis.com/documentation/security-and-authentication/reference/http-authorization-headers/), [Esri Community thread](https://community.esri.com/t5/arcgis-rest-apis-and-services-questions/http-header-authentication-vs-token-parameter/td-p/1312385)

## Finding 2: ogr2ogr Token Handling Is Correct for ArcGIS, Missing for Edge Cases (MEDIUM)

**Location:** `backend/app/ingest/ogr.py` lines 347-354

```python
if service_type == "wfs":
    cmd.extend(["--config", "OGR_WFS_PAGE_SIZE", "1000"])
elif service_type == "arcgis_featureserver":
    cmd.extend(["-oo", "FEATURE_SERVER_PAGING=YES"])

env = None
if token and service_type == "wfs":
    env = {**os.environ, "GDAL_HTTP_HEADERS": f"Authorization: Bearer {token}"}
```

For ArcGIS, the token is NOT passed via `GDAL_HTTP_HEADERS`. This is actually **correct** because `build_gdal_source()` already embeds `&token={token}` in the ESRIJSON URL (preview.py line 36). The ESRIJSON driver fetches pages by modifying the URL's `resultOffset` parameter, preserving any existing query params including `token=`.

**However:** If GDAL's ESRIJSON driver ever needs to make additional HTTP requests (e.g., for metadata about the layer), those requests would NOT carry the token. This is an edge case unlikely to cause issues in practice since the ESRIJSON driver operates on a single query URL.

**No code change needed for the primary path.** The URL-embedded token approach is the correct pattern for ESRIJSON.

## Finding 3: FEATURE_SERVER_PAGING Works But Needs `orderByFields` (MEDIUM)

**Location:** `backend/app/services/preview.py` line 33

```python
query_url = (
    f"{base_url}/{layer_id}/query?f=json&where=1%3D1&orderByFields=OBJECTID+ASC"
)
```

The code already includes `orderByFields=OBJECTID+ASC`, which is the correct pattern. GDAL's ESRIJSON driver documentation states: "For paged requests to work properly, it is generally necessary to add a sort clause on a field, typically the OBJECTID."

**ArcGIS maxRecordCount defaults:**
- Points: default 1,000-2,000, max 16,000
- Lines/Polygons: default 1,000-2,000, max 2,000
- The ESRIJSON driver auto-detects the server's `maxRecordCount` and uses it as page size

The `-oo FEATURE_SERVER_PAGING=YES` in `run_ogr2ogr_service` is correct for ArcGIS servers >= 10.3. GDAL handles the pagination loop automatically.

**Known GDAL bug (fixed):** GDAL had a paging bug with `f=pjson` URLs (GitHub issue #10094, fixed in GDAL 3.9.1+). The current code uses `f=json` which avoids this bug.

**Source:** [GDAL ESRIJSON driver docs](https://gdal.org/en/latest/drivers/vector/esrijson.html), [GDAL issue #10094](https://github.com/OSGeo/gdal/issues/10094)

## Finding 4: Dual Token Sending on Probe (LOW)

**Location:** `backend/app/services/router.py` lines 57-68

During probing, the token is sent BOTH as:
1. `Authorization: Bearer {token}` in httpx default headers (line 59)
2. `&token={token}` in the query URL (arcgis.py line 86)

For ArcGIS, only #2 is effective. Sending the Bearer header is harmless in most cases but adds noise. In rare cases where an ArcGIS server sits behind a reverse proxy that validates `Authorization` headers, this could cause 401 errors.

**Fix:** Make header injection service-type-aware. Since `detect_service_type()` determines the service type, the httpx client should be created without the default header, and each probe function should handle auth its own way (query param for ArcGIS, header for WFS).

## Finding 5: ArcGIS Auth Types -- Gap Analysis (HIGH)

### What ArcGIS Online supports:
| Auth Type | How It Works | Current Code Support |
|-----------|-------------|---------------------|
| **Token (query param)** | `?token={generated_token}` appended to URL | YES -- used in ESRIJSON URL and probe |
| **X-Esri-Authorization header** | `X-Esri-Authorization: Bearer {token}` | NO -- not used anywhere |
| **OAuth2 app token** | Client ID/secret -> token endpoint -> short-lived token | NO -- would need client_id/secret flow |
| **ArcGIS API Key** | Long-lived key from developer dashboard, used as token | PARTIAL -- works if user pastes it as "token" |
| **Username/password -> generateToken** | POST to `/sharing/rest/generateToken` with credentials | NO |
| **PKI/IWA (web-tier)** | Certificate or Windows auth | NO (out of scope) |

### generateToken endpoint:
- URL: `https://www.arcgis.com/sharing/rest/generateToken` (AGOL) or `https://{portal}/sharing/rest/generateToken` (Portal)
- POST body: `username={user}&password={pass}&client=referer&referer={url}&expiration=60&f=json`
- Returns: `{ "token": "...", "expires": 1234567890 }`
- Tokens are short-lived (default 60 min, max 21600 min / 15 days)

**Gap:** Users must manually generate a token before importing. The UI help text mentions "API Keys" from the AGOL settings page, which is correct for API keys but doesn't cover the more common case of username/password token generation.

**Source:** [Esri generateToken docs](https://developers.arcgis.com/rest/users-groups-and-items/generate-token/)

## Finding 6: UX Gaps for AGOL Migration Users (MEDIUM)

### Current UX:
1. Token field label: "Access Token (optional)"
2. Token placeholder: "Bearer token or API key for protected services"
3. Help text: "For ArcGIS, generate a token at *your-org*.maps.arcgis.com > Settings > API Keys..."

### Issues:
1. **"Bearer token" terminology is misleading** -- ArcGIS doesn't use Bearer tokens in the standard HTTP sense. Users should paste raw ArcGIS tokens, not prepend "Bearer".
2. **API Keys path is not the only/main path** -- Many AGOL users have username/password credentials, not API Keys. The help text should mention the generateToken approach or link to the AGOL token generation page.
3. **No validation feedback for token format** -- If a user pastes an expired token or an invalid string, they get a generic "Failed to connect to service" error with no token-specific guidance.
4. **Token not stored** -- The help text says "Token is not stored" which is good for security, but means users must re-enter it if they import multiple layers from the same service. For an AGOL migration user importing many layers, this is painful.
5. **No generateToken integration** -- A username/password form that calls the ArcGIS generateToken endpoint would be significantly more user-friendly for AGOL migrations.

## Finding 7: No Dedicated ArcGIS GDAL Driver Needed (LOW)

There is no separate GDAL driver for ArcGIS FeatureServer beyond ESRIJSON. The ESRIJSON driver IS the driver for ArcGIS REST API feature services. OAPIF is for OGC API Features, not ArcGIS. The current approach of using `ESRIJSON:` prefix is correct and standard.

## Recommended Priority Order

1. **P0 (Bug):** Remove `Authorization: Bearer` header from ArcGIS probes -- currently sends wrong auth type
2. **P1 (Correctness):** Improve error messaging when token auth fails -- detect ArcGIS `error.code` in JSON responses
3. **P2 (UX):** Update help text to accurately describe ArcGIS token generation (not just API Keys)
4. **P3 (UX):** Consider adding generateToken integration for username/password auth
5. **P4 (UX):** Consider session-scoped token caching for multi-layer imports from same service

## Common Pitfalls

### Pitfall 1: ArcGIS Error Responses Are 200 OK
**What goes wrong:** ArcGIS servers return HTTP 200 with error details in the JSON body: `{"error": {"code": 498, "message": "Invalid token"}}`
**Why it happens:** ArcGIS REST API convention -- errors are in the response body, not HTTP status codes
**How to avoid:** Parse response JSON and check for `error` key before treating as success
**Warning signs:** Probe succeeds but returns no layers; `layers` key missing from response

### Pitfall 2: Token Expiry During Large Ingestion
**What goes wrong:** Token expires mid-way through ogr2ogr pagination of a large dataset
**Why it happens:** ArcGIS tokens default to 60-minute expiry; large datasets may take longer to page through
**How to avoid:** Request tokens with longer expiry (up to 21600 minutes); document recommended expiry for users
**Warning signs:** ogr2ogr fails partway through with auth errors after initial pages succeed

### Pitfall 3: OBJECTID Not Always Present
**What goes wrong:** `orderByFields=OBJECTID+ASC` fails because the layer uses a different OID field name
**Why it happens:** Some ArcGIS services use `FID`, `OID`, or custom names instead of `OBJECTID`
**How to avoid:** Query the layer metadata to get `objectIdField` name, use that for ordering
**Warning signs:** ESRIJSON paging returns duplicate or missing features

## Sources

### Primary (HIGH confidence)
- [GDAL ESRIJSON driver docs](https://gdal.org/en/latest/drivers/vector/esrijson.html) - paging, open options, driver behavior
- [Esri HTTP Authorization Headers](https://developers.arcgis.com/documentation/security-and-authentication/reference/http-authorization-headers/) - X-Esri-Authorization vs Authorization
- [Esri generateToken](https://developers.arcgis.com/rest/users-groups-and-items/generate-token/) - token generation flow
- [Esri Access Tokens reference](https://developers.arcgis.com/documentation/security-and-authentication/reference/access-tokens/) - token types

### Secondary (MEDIUM confidence)
- [GDAL issue #10094](https://github.com/OSGeo/gdal/issues/10094) - paging bug with f=pjson (fixed)
- [Esri Community: header vs token param](https://community.esri.com/t5/arcgis-rest-apis-and-services-questions/http-header-authentication-vs-token-parameter/td-p/1312385) - community confirmation of auth patterns

## Metadata

**Confidence breakdown:**
- Token auth mechanism: HIGH - verified against Esri official docs
- GDAL ESRIJSON behavior: HIGH - verified against GDAL docs + issue tracker
- UX recommendations: MEDIUM - based on code review and user persona analysis
- generateToken flow: HIGH - verified against Esri REST API reference

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable domain, ArcGIS REST API is mature)
