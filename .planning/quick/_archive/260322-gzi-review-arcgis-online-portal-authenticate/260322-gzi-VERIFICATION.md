---
phase: quick-260322-gzi
verified: 2026-03-22T17:00:00Z
status: passed
score: 4/4 must-haves verified
---

# Quick Task 260322-gzi: Verification Report

**Task Goal:** Review ArcGIS Online/Portal authenticated layer ingestion for correctness, completeness, and best practices
**Verified:** 2026-03-22T17:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | ArcGIS probe sends token as query parameter only, not Authorization Bearer header | VERIFIED | `arcgis.py:86` builds `?f=json&token={token}`; `router.py:56-58` comment confirms no default auth header on httpx client; `wfs.py:87` adds Bearer header only for WFS per-request |
| 2 | ArcGIS probe detects error responses in JSON body (code 498/499/403) | VERIFIED | `arcgis.py:99-110` checks `"error"` key in response JSON, raises `httpx.HTTPStatusError` for codes 498/499; router catches this at line 84-103 and surfaces as 403 to user |
| 3 | OBJECTID field name is read from layer metadata, not hardcoded | VERIFIED | `arcgis.py:130-139` reads `layer.get("objectIdField") or service_oid or "OBJECTID"`; `probe.py:69` threads `object_id_field` into `LayerInfo`; `preview.py:20` accepts `order_field` param; all 4 call sites pass dynamic value |
| 4 | UX help text accurately describes ArcGIS token generation paths | VERIFIED | All 4 locales contain `generateToken` path, expiry warning, and "not stored" note; no "Bearer" terminology in placeholder text |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/services/router.py` | Service-type-aware auth header injection | VERIFIED | No blanket Bearer header on httpx client (lines 56-64); `order_field=request.object_id_field or "OBJECTID"` passed at lines 214 and 259; `object_id_field` stored in job metadata at line 341 |
| `backend/app/services/arcgis.py` | ArcGIS JSON error detection + objectIdField lookup | VERIFIED | `"error"` key checked at line 99; `objectIdField` extracted at lines 130-139; 196 lines, substantive |
| `backend/app/services/schemas.py` | `object_id_field` on LayerInfo and ServicePreviewRequest | VERIFIED | `LayerInfo.object_id_field: str \| None = None` at line 20; `ServicePreviewRequest.object_id_field: str \| None = None` at line 48 |
| `backend/tests/test_arcgis_auth.py` | Test coverage for auth fixes | VERIFIED | 133 lines, 7 tests covering: no Bearer header, 498 raises, 499 raises, OID extraction with layer/service/default fallback, `build_gdal_source` custom OID, default OID |

**Note on plan artifact `contains` mismatch:** The PLAN listed `contains: "X-Esri-Authorization"` for `router.py`. This string does not exist in the codebase — the implementation correctly avoids ALL ArcGIS-specific auth headers rather than replacing Bearer with a custom header. The actual implementation (no auth headers on the httpx client, per-service handling) is correct and superior to the plan's expected pattern. This is a plan artifact spec issue, not an implementation defect.

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `services/router.py` | `services/arcgis.py` | httpx client without ArcGIS Bearer header | VERIFIED | `router.py:60-64` creates `httpx.AsyncClient` with no `headers=` argument; delegates to `detect_service_type()` which calls `probe_arcgis_service()` |
| `services/arcgis.py` | ArcGIS REST API | token query param | VERIFIED | `arcgis.py:86`: `query = f"{base_url}?f=json" + (f"&token={token}" if token else "")` |
| `services/schemas.py` | `services/preview.py` | `object_id_field` threaded to `build_gdal_source` `order_field` param | VERIFIED | `router.py:214` and `datasets/router.py:1343` both call `build_gdal_source(..., order_field=request.object_id_field or "OBJECTID")`; `ingest/tasks.py:336-340` reads `um.get("object_id_field", "OBJECTID")` and passes as `order_field`; second ingest code path at `tasks.py:836-845` also correct |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| AGOL-REVIEW | 260322-gzi-PLAN.md | ArcGIS Online/Portal authenticated layer ingestion review | SATISFIED | All 6 success criteria from plan met: token via query param, JSON error detection, dynamic OID field, schema threading, help text, tests pass |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/app/services/arcgis.py` | 143-151 | Tables appended without `object_id_field` | Info | Tables are non-spatial; OID field irrelevant for GDAL orderByFields. Not a bug. |

No blockers or warnings found. The one info item is intentional — non-spatial tables do not need `object_id_field` for the `orderByFields` ArcGIS query parameter.

### Human Verification Required

#### 1. End-to-end ArcGIS authenticated layer import

**Test:** Connect to a real ArcGIS Online FeatureServer with a valid API key token. Verify the layer list populates, preview shows sample data, and import completes.
**Expected:** No auth errors; feature data ingested correctly using the dynamic OID field.
**Why human:** Requires a live ArcGIS Online account and service URL; cannot mock the full GDAL/ogr2ogr pipeline locally.

#### 2. 498/499 error surfaced to UI

**Test:** Connect to an ArcGIS FeatureServer with an expired or invalid token.
**Expected:** UI shows "This service requires authentication. Provide an access token and try again." (403 response from backend).
**Why human:** Requires triggering a real ArcGIS 498/499 JSON response body; mock verification confirms code path exists but UI display needs visual confirmation.

#### 3. generateToken help text visible in UI

**Test:** Open the Service URL import tab and inspect the token field help text.
**Expected:** Both API Keys path AND generateToken URL path are visible in the help text, along with expiry warning.
**Why human:** i18n string content verified, but rendering in the UI needs visual check to ensure the field is visible and not truncated.

### Gaps Summary

No gaps. All 4 must-have truths are verified with substantive, wired implementations. The codebase correctly implements:

1. ArcGIS token delivery via query parameter only — no Bearer headers sent to ArcGIS endpoints
2. ArcGIS JSON error body detection with HTTPStatusError propagation for codes 498/499
3. Dynamic `objectIdField` extracted from layer metadata (layer-level preferred, service-level fallback, "OBJECTID" default)
4. Full pipeline threading: schemas -> probe response -> preview endpoint -> ingest tasks (both initial and re-upload code paths)
5. UX copy updated in all 4 locales (en, es, fr, de) with generateToken path, expiry warning, and no "Bearer" terminology

Three human verification items are noted for completeness but do not block goal achievement — the automated evidence is conclusive.

---

_Verified: 2026-03-22T17:00:00Z_
_Verifier: Claude (gsd-verifier)_
