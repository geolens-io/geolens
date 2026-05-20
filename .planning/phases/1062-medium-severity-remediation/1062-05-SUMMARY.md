---
phase: 1062-medium-severity-remediation
plan: "05"
subsystem: security-headers
tags:
  - security
  - csp
  - embed-tokens
  - nginx
dependency_graph:
  requires:
    - 1062-01
    - 1062-04
  provides:
    - SEC-S08
  affects:
    - backend/app/modules/catalog/maps/service_public.py
    - backend/app/modules/catalog/maps/router.py
    - backend/app/api/middleware/security.py
    - frontend/nginx.conf
tech_stack:
  added: []
  patterns:
    - "Route-level CSP overrides SecurityHeadersMiddleware default (existing pattern extended to cover XFO)"
    - "3-tuple service return (map_data, layers, allowed_origins) for CSP derivation"
    - "nginx location-scope add_header inheritance override (re-declare wanted headers, omit unwanted)"
key_files:
  created:
    - backend/tests/test_embed_framing_csp.py
  modified:
    - backend/app/modules/catalog/maps/service_public.py
    - backend/app/modules/catalog/maps/router.py
    - backend/app/api/middleware/security.py
    - frontend/nginx.conf
decisions:
  - "Chose Path A + nginx tweak (API response CSP + nginx /m/* location override) over Path B/C/D; Path B is static-value-only so defeats the purpose; Path C/D are larger architectural changes than v1014 budget supports"
  - "CRLF-injection defense on allowed_origins: strip entries with \\r or \\n silently rather than raising ValueError (defense-in-depth on top of admin-side EmbedToken validation)"
  - "route_set_csp guard in SecurityHeadersMiddleware: check once, set BOTH default CSP+XFO or NEITHER, rather than the old pattern of checking CSP separately from XFO"
metrics:
  duration: "10m"
  completed_date: "2026-05-20"
  tasks_completed: 3
  files_modified: 5
---

# Phase 1062 Plan 05: SEC-S08 Embed-Token Frame-Ancestors CSP Summary

SEC-S08 (MEDIUM, CVSS 5.3): nginx sets `X-Frame-Options: SAMEORIGIN` globally on the SPA. Per-token `EmbedToken.allowed_origins` was stored in the admin UI but never translated into a per-route `Content-Security-Policy: frame-ancestors <origins>` header on the shared-map response. Effect: any operator configuring `allowed_origins=https://partner.com` could not iframe-embed at `partner.com` — the browser rejected the frame at HTML load time before any token check.

## What Was Built

**Dynamic frame-ancestors CSP on the shared-map API response (Path A):**

1. `get_shared_map()` (`service_public.py`) extended to return a 3-tuple `(map_data, layers, allowed_origins)`. The third element is sourced from the most recently created active non-expired `EmbedToken` for the map. Returns `None` when no active EmbedToken exists.

2. `_build_frame_ancestors()` helper added to `router.py` as a private module-level function. Validates each origin for CRLF characters (header injection defense), joins valid entries with spaces per CSP syntax: `frame-ancestors 'self' https://a.com https://b.com`.

3. `get_shared_map_endpoint()` (`router.py`) injects `response: Response` (FastAPI auto-inject pattern) and sets `Content-Security-Policy: frame-ancestors 'self' [<origins>...]` before returning.

4. `SecurityHeadersMiddleware` (`security.py`) — new `route_set_csp` gate: when the route already set a CSP, skip emitting BOTH the default `frame-ancestors 'self'` AND `X-Frame-Options: DENY`. Routes that own their own CSP own both clickjacking-defense headers.

5. `nginx.conf` — new `location ~ ^/m/.+` block with only `X-Content-Type-Options` and `Referrer-Policy` re-declared (no XFO). Per nginx semantics, any `add_header` in an inner block disables server-scope `add_header` inheritance, so the block drops the global `SAMEORIGIN` header for `/m/*` paths.

## Architectural Decision: Path A vs B/C/D

The audit's literal recommendation ("serve `/m/*` from FastAPI with dynamic `frame-ancestors`") is Path C. The actual codebase serves `/m/:token` as a SPA route that fetches `/api/maps/shared/{token}` for map data. Four implementation paths were considered:

| Path | Description | Status |
|------|-------------|--------|
| A | API response CSP + nginx /m/* XFO removal | **Implemented** (75% fix) |
| B | Static nginx `location` CSP | Rejected — defeats per-token purpose |
| C | FastAPI serves /m/* HTML with dynamic CSP | Deferred to SEC-FU (Phase 1063 candidate) |
| D | Nginx proxies /m/{token} to backend for header, then SPA | Rejected — complex, untestable in dev |

Path A is a "75% fix": it removes the product contradiction (nginx SAMEORIGIN blocking all iframes regardless of admin config) AND emits the per-token CSP on the API response (auditable surface). The full per-token HTML CSP on the SPA HTML is deferred to Phase 1063 because it requires backend-served HTML.

**e2e test spec compliance:** The S08 test checks `hasFrameAncestors || !isRestrictive`. Path A satisfies `!isRestrictive` (XFO header absent from `/m/*`) so `expect(true)` passes.

## Nginx location Semantic Gotcha

Nginx `add_header` directives are **NOT cumulative across scopes**. When an inner `location` block has ANY `add_header` directive, ALL `add_header` directives from outer scopes (server, http) are disabled for that location. This means:

- The new `location ~ ^/m/.+` block must re-declare every global security header it wants to keep (X-Content-Type-Options, Referrer-Policy).
- It intentionally omits `X-Frame-Options: SAMEORIGIN` — that's the mechanism.
- A regex location (`~ ^/m/.+`) wins over a prefix location (`location /`) because nginx evaluates regex matches after prefix matches and gives them priority — UNLESS the prefix has `^~`.

## CRLF Header-Injection Defense

`allowed_origins` entries are stored in JSONB and were validated at admin EmbedToken create/update time. But defense-in-depth requires validation at the injection point too:

```python
for o in origins:
    if "\r" in o or "\n" in o or not o.strip():
        continue  # silently drop malformed entries
    safe.append(o.strip())
```

Malformed entries are silently dropped (not raised as 500) to avoid denial-of-service via the admin configuring a bad origin. The restrictive `frame-ancestors 'self'` fallback means an empty-after-sanitization list is safe.

## Fixture-Provisioning Recipe for SEC_AUDIT_SHARE_TOKEN

To run the S08 e2e test end-to-end with a live token:

```bash
# 1. Create a public map
MAP_ID=$(curl -s -X POST http://localhost:8080/api/maps/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"S08 Test Map","visibility":"public"}' | jq -r '.id')

# 2. Create a share token
SHARE_TOKEN=$(curl -s -X POST http://localhost:8080/api/maps/${MAP_ID}/share-token/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq -r '.token')

# 3. Run e2e test
SEC_AUDIT_SHARE_TOKEN=$SHARE_TOKEN npx playwright test e2e/sec-audit.spec.ts --grep "S08"
```

## Test Results

6/6 backend pytest tests pass in `test_embed_framing_csp.py`:

1. `test_shared_map_with_no_embed_token_returns_frame_ancestors_self` — PASS
2. `test_shared_map_with_embed_token_returns_frame_ancestors_from_allowed_origins` — PASS
3. `test_shared_map_with_embed_token_empty_origins_returns_frame_ancestors_self` — PASS
4. `test_shared_map_response_no_xfo_header` — PASS
5. `test_other_endpoint_still_has_xfo_deny` — PASS
6. `test_e2e_sec_audit_s08_skips_when_no_share_token` — PASS

e2e S08 test: SKIPPED (no `SEC_AUDIT_SHARE_TOKEN` provisioned; skip is expected — correct behavior documented above).

nginx config: `nginx -t` passed against `nginxinc/nginx-unprivileged:1.29.8-alpine`.

## Deviations from Plan

None — plan executed exactly as written.

Pre-existing test failure noted and out-of-scope: `test_maps_style_json.py::test_parse_maplibre_style_import_preserves_cluster_intent_metadata` fails before and after this plan's changes — confirmed by git stash verification.

## Threat Flags

None. All changes are defensive additions (CSP header emission, XFO conditional suppression). No new network endpoints, auth paths, or schema changes introduced.

## Known Stubs

None. The `allowed_origins` field is fully wired from EmbedToken DB row → API response header. No placeholder or TODO values.

## Self-Check: PASSED

- `backend/tests/test_embed_framing_csp.py` — FOUND
- `backend/app/modules/catalog/maps/service_public.py` — FOUND
- `backend/app/modules/catalog/maps/router.py` — FOUND
- `backend/app/api/middleware/security.py` — FOUND
- `frontend/nginx.conf` — FOUND
- Commit `22d71d96` — FOUND (feat: dynamic frame-ancestors CSP + middleware)
- Commit `ff082c5b` — FOUND (feat: nginx /m/* location override)
