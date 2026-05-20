---
phase: 1061-security-audit-2026-05-19-remediation
plan: "04"
subsystem: backend/security
tags:
  - ssrf
  - httpx
  - gdal
  - security
  - CVE-high
dependency_graph:
  requires:
    - backend/app/modules/catalog/sources/security.py (existing SSRF validation)
  provides:
    - make_safe_client factory + _revalidate_redirect event hook
    - Per-hop SSRF revalidation on all user-supplied URL fetches
    - GDAL_HTTP_FOLLOWLOCATION=NO on ogr2ogr service-ingest subprocess
  affects:
    - backend/app/modules/catalog/sources/router.py
    - backend/app/modules/catalog/sources/adapters/stac.py
    - backend/app/processing/ingest/ogr.py
    - backend/app/processing/ingest/manifest_service.py
tech_stack:
  added: []
  patterns:
    - httpx event_hooks for per-hop response interception
    - Factory pattern for safe HTTP client construction
    - GDAL env-var override for subprocess redirect control
key_files:
  created:
    - backend/tests/test_ssrf_redirect.py
  modified:
    - backend/app/modules/catalog/sources/security.py (+42 lines)
    - backend/app/modules/catalog/sources/router.py (2 sites refactored, import updated)
    - backend/app/modules/catalog/sources/adapters/stac.py (_make_client refactored, import added)
    - backend/app/processing/ingest/ogr.py (env block updated +11 lines)
    - backend/app/processing/ingest/manifest_service.py (Rule 2 fix, _download_http_source)
decisions:
  - "manifest_service.py _download_http_source had a raw AsyncClient(follow_redirects=True, timeout=60.0) fetching user-supplied manifest source URIs — Rule 2 auto-fix applied (not in plan's explicit scope but same SSRF gap)"
  - "manifest_sources.py inspected: no subprocess spawns, no GDAL calls — documented as non-spawning consumer, no action required"
  - "stac_router.py _fetch_cog_info uses AsyncClient without follow_redirects=True, targeting fixed internal Titiler host — not in scope"
  - "Pre-resolve HTTP-redirected sources to final URL before ogr2ogr spawn — deferred as SEC-FU (Phase 1063 candidate)"
metrics:
  duration: "3m 28s"
  completed_date: "2026-05-20"
  tasks_completed: 4
  files_changed: 6
---

# Phase 1061 Plan 04: SEC-S04 SSRF Redirect-Bypass Remediation Summary

Closed SEC-S04 (CVSS 8.5 HIGH) — `_revalidate_redirect` httpx event hook + `make_safe_client` factory providing per-hop SSRF revalidation; `GDAL_HTTP_FOLLOWLOCATION=NO` on ogr2ogr service-ingest subprocess.

## Tasks Completed

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 | _revalidate_redirect hook + make_safe_client factory | 09628707 | security.py |
| 2 | Refactor 4 raw httpx sites to use make_safe_client | 2658e8ac | router.py, stac.py, manifest_service.py |
| 3 | GDAL_HTTP_FOLLOWLOCATION=NO on ogr2ogr service-ingest | 49116056 | ogr.py |
| 4 | pytest regression coverage for SSRF redirect-revalidation | 1ceebaa1 | test_ssrf_redirect.py |

## What Was Built

### Task 1: _revalidate_redirect + make_safe_client

Added to `backend/app/modules/catalog/sources/security.py`:

- `async def _revalidate_redirect(response: httpx.Response) -> None` — httpx response event hook. Intercepts every 3xx response, resolves the `Location` header (relative or absolute) via `httpx.URL(response.url).join(location)`, then calls `validate_url_for_ssrf(target)`. Raises `SSRFError` if the redirect target is a private IP, loopback, link-local, reserved, or multicast address.

- `def make_safe_client(timeout=PROBE_TIMEOUT) -> httpx.AsyncClient` — factory that returns an `httpx.AsyncClient` with `follow_redirects=True`, `max_redirects=5`, and `event_hooks={"response": [_revalidate_redirect]}`. All user-supplied URL fetches must use this factory.

### Task 2: Refactored 4 raw httpx sites

Sites updated (3 from plan + 1 Rule 2 auto-fix):

1. `sources/router.py:_fetch_ogcapi_collection_srid` (~line 99) — `make_safe_client(timeout=PROBE_TIMEOUT)`
2. `sources/router.py:probe_service_url` (~line 188) — `make_safe_client(timeout=PROBE_TIMEOUT)`
3. `sources/adapters/stac.py:_make_client` — delegates to `make_safe_client(timeout=STAC_TIMEOUT)`
4. `processing/ingest/manifest_service.py:_download_http_source` — `make_safe_client(timeout=60.0)` [Rule 2]

Grep gate: 0 raw `AsyncClient(follow_redirects=True)` sites outside `security.py` in `backend/app/`.

### Task 3: GDAL_HTTP_FOLLOWLOCATION=NO

Modified `run_ogr2ogr_service` in `backend/app/processing/ingest/ogr.py`. Both env branches of the service-ingest subprocess spawn now set `GDAL_HTTP_FOLLOWLOCATION=NO`:

```python
if token and service_type in ("wfs", "ogcapi_features"):
    env = {
        **os.environ,
        "GDAL_HTTP_HEADERS": f"Authorization: Bearer {token}",
        "GDAL_HTTP_FOLLOWLOCATION": "NO",
    }
else:
    env = {**os.environ, "GDAL_HTTP_FOLLOWLOCATION": "NO"}
```

File-ingest `run_ogr2ogr` left unmodified — it operates on local file paths, not HTTP.

### Task 4: pytest regression tests

7 tests in `backend/tests/test_ssrf_redirect.py`, all passing:

1. `test_redirect_to_private_ip_blocked` — 302 → 127.0.0.1 raises SSRFError
2. `test_redirect_to_link_local_blocked` — 302 → 169.254.169.254 raises SSRFError
3. `test_redirect_to_public_allowed` — 302 → example.com succeeds
4. `test_relative_redirect_resolution` — `Location: /admin` resolves against internal base, blocked
5. `test_non_http_scheme_redirect_blocked` — 302 → file:// raises SSRFError
6. `test_non_redirect_status_passthrough` — 200 with Location header passes through (no false positive)
7. `test_make_safe_client_has_event_hook` — factory wiring verified (follow_redirects, max_redirects, hook present)

## Grep Gate Confirmation

```
# Gate 1: no raw AsyncClient(follow_redirects=True) outside security.py
grep -rnE "httpx\.AsyncClient.*follow_redirects=True" backend/app/ | grep -v 'security.py'
# Result: 0 matches

# Gate 2: GDAL_HTTP_FOLLOWLOCATION=NO present in ogr.py
grep -nE "GDAL_HTTP_FOLLOWLOCATION" backend/app/processing/ingest/ogr.py
# 639: (comment)
# 645: "GDAL_HTTP_FOLLOWLOCATION": "NO",
# 648: "GDAL_HTTP_FOLLOWLOCATION": "NO"
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] manifest_service.py _download_http_source used raw AsyncClient(follow_redirects=True)**

- **Found during:** Task 2 full app-wide grep scan (`grep -rnE "httpx\.AsyncClient.*follow_redirects=True" backend/app/`)
- **Issue:** `_download_http_source` in `manifest_service.py` fetched user-supplied manifest source URIs with `httpx.AsyncClient(follow_redirects=True, timeout=60.0)` — same SSRF redirect bypass as S04. Not in plan's explicit scope (plan named 3 sites in `catalog/sources/`) but the plan's verification section targeted `backend/app/` globally.
- **Fix:** Replaced with `make_safe_client(timeout=60.0)` and added the import.
- **Files modified:** `backend/app/processing/ingest/manifest_service.py`
- **Commit:** 2658e8ac

## manifest_sources.py Decision

`manifest_sources.py` inspected per plan's Task 3 instruction. It contains zero subprocess spawns and zero GDAL calls. It is a pure URL-validation + source-preparation consumer that hands validated URLs to downstream consumers. No fix required. The `validate_url_for_ssrf` call it already contains is appropriate.

## Deferred: Pre-resolve Final URL before ogr2ogr Spawn

The audit's secondary recommendation (pre-flight HEAD request via `make_safe_client` to resolve the final URL before ogr2ogr spawn) is deferred as SEC-FU per the plan's explicit OUT OF SCOPE disposition. `GDAL_HTTP_FOLLOWLOCATION=NO` is the lower-cost first-line defense. Tracked as Phase 1063 candidate.

## e2e SEC-S04 Note

The `e2e/sec-audit.spec.ts` S04 test requires `SEC_AUDIT_EDITOR_A_TOKEN` + `SEC_AUDIT_SSRF_TEST_REDIRECTOR` env vars. The latter is a publicly-accessible URL that 302-redirects to `169.254.169.254`.

**Fixture-provisioning recipe for SEC_AUDIT_SSRF_TEST_REDIRECTOR:**

```python
# redirect_server.py — minimal 302 redirector for S04 e2e testing
from http.server import BaseHTTPRequestHandler, HTTPServer

class RedirectHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", "http://169.254.169.254/latest/meta-data/iam/security-credentials/")
        self.end_headers()

HTTPServer(("0.0.0.0", 9999), RedirectHandler).serve_forever()
```

Run: `python3 redirect_server.py` then expose via ngrok: `ngrok http 9999`
Set: `export SEC_AUDIT_SSRF_TEST_REDIRECTOR=https://<ngrok-id>.ngrok.io/redirect`
Set: `export SEC_AUDIT_EDITOR_A_TOKEN=<jwt-from-login>`

With this fix in place, the test should return 400/422/502 (SSRFError raised by the hook) rather than 200 with IMDS content in the body.

## Self-Check

### Created files exist

- [x] `backend/tests/test_ssrf_redirect.py` — exists
- [x] `backend/app/modules/catalog/sources/security.py` — modified (make_safe_client + _revalidate_redirect appended)
- [x] `backend/app/modules/catalog/sources/router.py` — modified (2 sites + import)
- [x] `backend/app/modules/catalog/sources/adapters/stac.py` — modified (_make_client + import)
- [x] `backend/app/processing/ingest/ogr.py` — modified (GDAL_HTTP_FOLLOWLOCATION)
- [x] `backend/app/processing/ingest/manifest_service.py` — modified (Rule 2 fix)

### Commits exist

- [x] 09628707 feat(1061-04): SEC-S04 — _revalidate_redirect hook + make_safe_client factory
- [x] 2658e8ac fix(1061-04): SEC-S04 — refactor 4 httpx sites to use make_safe_client
- [x] 49116056 fix(1061-04): SEC-S04 — GDAL_HTTP_FOLLOWLOCATION=NO on ogr2ogr service-ingest
- [x] 1ceebaa1 test(1061-04): regression coverage for SSRF redirect-revalidation

### Tests pass

- [x] `backend/tests/test_ssrf_redirect.py` — 7/7 PASS (0.57s)

## Self-Check: PASSED
