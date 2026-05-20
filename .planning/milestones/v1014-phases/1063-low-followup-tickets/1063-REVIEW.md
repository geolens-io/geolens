---
phase: 1063-low-followup-tickets
reviewed: 2026-05-20T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - backend/app/processing/ingest/ogr.py
  - backend/app/modules/audit/router.py
  - backend/app/modules/audit/service.py
  - backend/app/modules/audit/schemas.py
  - backend/app/modules/catalog/maps/service_crud.py
  - backend/app/modules/catalog/features/service.py
  - backend/app/standards/stac/router.py
  - backend/app/api/router.py
  - backend/tests/conftest.py
  - backend/tests/test_audit_column_ddl_feed.py
  - backend/tests/test_demo_credentials_guard.py
  - backend/tests/test_ingest_ogr_pure.py
  - backend/tests/test_maps_search_ilike_escape.py
  - backend/tests/test_parse_bbox_isfinite.py
  - backend/tests/test_stac_search_validation.py
  - backend/tests/test_stac_visibility_5xx.py
  - frontend/eslint.config.js
  - frontend/nginx.conf
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: fixed
---

# Phase 1063: Code Review Report

**Reviewed:** 2026-05-20
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

Phase 1063 implements 10 LOW-severity security follow-ups: a base64url token sanitizer (SEC-FU-04), a column-DDL audit feed (SEC-FU-08), ILIKE wildcard escape (SEC-FU-07), bbox isfinite checks (SEC-FU-06), STAC intersects max_length cap (SEC-FU-05), a STAC 5xx regression fixture (SEC-FU-01), `react/no-danger` ESLint rule (SEC-FU-03), `server_tokens off` (SEC-FU-09), and `DATABASE_URL_OVERRIDE` docs (SEC-FU-10).

The core security intent of each fix is correct. The access-control layering on the column-DDL feed endpoint is sound — `check_dataset_access` is called before the query, `get_current_active_user` gates anonymous callers, and the router is properly registered. The base64url sanitizer correctly blocks CRLF injection, the bbox isfinite check covers NaN and ±Inf before PostGIS sees them, and the server_tokens directive is placed correctly in the server block.

Three warnings surface: the ILIKE fix misses escaping the backslash character itself (pre-existing pattern carried from `service_public.py` that the fix mirrors — but still broken), the audit service's `resource_type.ilike` remains unescaped (admin-only surface, correctness gap only), and the test comment for the POST STAC search is factually wrong about the body size limit (500MB via middleware, not 1MB via uvicorn).

---

## Warnings

### WR-01: SEC-FU-07 ILIKE escape misses backslash — search for `\` matches `%` instead

**File:** `backend/app/modules/catalog/maps/service_crud.py:143-144`

**Issue:** The escape sequence `search.replace("%", r"\%").replace("_", r"\_")` only escapes `%` and `_`, but not backslash itself. When a user searches for a map whose name contains a literal backslash (e.g., `foo\`), the pattern becomes `%foo\%`. PostgreSQL ILIKE uses backslash as the default escape character (even with `standard_conforming_strings=on` for string literals, the LIKE/ILIKE escape character defaults to backslash independently). So `\%` in the pattern is interpreted as an escaped `%`, meaning "literal percent sign." The search for `foo\` therefore matches maps named `foo%` — the wrong rows.

This is the same pre-existing bug in `service_public.py:408-409` that SEC-FU-07 explicitly mirrors, but it was not caught by either implementation. The three tests in `test_maps_search_ilike_escape.py` do not cover the `search="\\"` case.

**Fix:** Escape the backslash before `%` and `_`:
```python
escaped = search.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
pattern = f"%{escaped}%"
stmt = stmt.where(
    or_(
        Map.name.ilike(pattern, escape="\\"),
        Map.description.ilike(pattern, escape="\\"),
    )
)
```
The `escape="\\"` kwarg emits `ESCAPE '\'` in the SQL, making the escape character explicit and independent of any future PostgreSQL default changes. Apply the same fix to `service_public.py:408-409` and `embed_tokens/service.py:367-368`.

---

### WR-02: Audit `_apply_filters` `resource_type.ilike` is unescaped

**File:** `backend/app/modules/audit/service.py:70`

**Issue:** `AuditLog.resource_type.ilike(f"%{search}%")` passes the user-supplied `search` string directly into the pattern without escaping `%` or `_`. An admin searching for `%` gets a pattern `%%` which PostgreSQL treats as "match any string," returning all rows regardless of `resource_type`. Similarly `_` acts as a single-character wildcard.

This endpoint (`GET /admin/audit-logs/`) requires `manage_settings` (admin-only), so the blast radius is limited: an admin receives more audit rows than intended, not rows they should not see. No confidential data is exposed that the admin does not already have access to. It is a correctness bug, not a privilege-escalation issue.

**Fix:**
```python
escaped_search = search.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
search_filter = (
    action_match
    | AuditLog.resource_type.ilike(f"%{escaped_search}%", escape="\\")
    | username_match
)
```

---

### WR-03: `test_stac_search_validation.py` documents wrong body size limit for POST `/stac/search`

**File:** `backend/tests/test_stac_search_validation.py:9,108-109`

**Issue:** The docstrings at lines 9 and 108–109 state that `POST /stac/search` body is "bounded by uvicorn's 1MB request-body size limit." Neither claim is accurate:
- uvicorn has no built-in body size limit.
- `RequestBodyLimitMiddleware` applies to all routes and defaults to `upload_max_size_mb * 1024 * 1024` = 500 MB.
- The nginx proxy also sets `client_max_body_size 500m`.

A multi-megabyte `intersects` GeoJSON dict is therefore accepted and passed to `ST_GeomFromGeoJSON`. The stated rationale for why POST is "safe" is factually wrong. The test itself passes correctly (it verifies `max_length` does not apply to POST — true), but the written justification misleads future readers about the actual size boundary.

**Fix:** Update the test docstring to accurately describe the bound:
```python
"""
The POST handler accepts StacSearchBody.intersects: dict — bounded by
the application-wide RequestBodyLimitMiddleware (default 500 MB) and the
nginx proxy (client_max_body_size 500m), NOT by a 1MB uvicorn limit
(uvicorn has no built-in body size cap).
"""
```

Consider whether the STAC POST intersects size bound should be tightened separately (performance scope, out of v1 review).

---

## Info

### IN-01: `_sanitize_authorization_token` blocks tokens shorter than 8 characters unconditionally

**File:** `backend/app/processing/ingest/ogr.py:43-47`

**Issue:** The guard raises `ValueError` for any token with `len(token) < 8`, even a 7-character value that passes the charset check. All tokens generated by GeoLens (JWT via `create_access_token`, API keys via `secrets.token_urlsafe(32)`) are well above 8 characters, so no known regression exists. However, if a third-party WFS or OGC API service issues an unusually short bearer token (e.g., a 6-char opaque token), the ingest job will fail with a `ValueError: SEC-FU-04: Authorization token is empty or implausibly short` message — with no option for the operator to override the minimum.

The docstring says this "prevents single-char attack payloads" but any single-char payload that passes the charset check (e.g., `"A"`) is not a CRLF injection risk, so the minimum-length check guards something different (implausibly misconfigured tokens). This is acceptable defense-in-depth, but the 8-char floor is an arbitrary constant not documented in a named config constant.

**Fix:** No immediate action required. If a real-world service failure is reported, lower the minimum to 4 or document it as a constant:
```python
_MIN_TOKEN_LENGTH = 8  # JWT and standard API keys are always >= 40 chars
```

---

### IN-02: `StacSearchBody` has no Pydantic validation on `limit`/`offset` — clamping is silent

**File:** `backend/app/standards/stac/router.py:1147-1148`

**Issue:** `StacSearchBody.limit` and `StacSearchBody.offset` are plain `int` with no `ge`/`le` Pydantic constraints. The POST handler silently clamps them: `limit=max(1, min(body.limit, 200))`, `offset=max(0, body.offset)`. A caller passing `limit=99999` or `offset=-5` receives a 200 with clamped behavior — no indication that their request was modified.

The GET `/stac/search` handler uses `Query(10, ge=1, le=200)` and `Query(0, ge=0)`, returning 422 on violations. The inconsistency means POST callers can silently submit out-of-range values while GET callers receive explicit validation errors for the same inputs.

**Fix:** Add Pydantic field constraints for consistency:
```python
from pydantic import Field

class StacSearchBody(BaseModel):
    ...
    limit: int = Field(10, ge=1, le=200)
    offset: int = Field(0, ge=0)
```
Remove the manual clamping in the POST handler, which becomes redundant. Alternatively, document in the schema that clamping is intentional for POST compatibility.

---

_Reviewed: 2026-05-20_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
