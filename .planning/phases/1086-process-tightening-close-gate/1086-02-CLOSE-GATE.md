# Phase 1086-02 Close Gate Record

**Milestone:** v1019 Hygiene Tail — v1018 Frontend + xdist + Process
**Plan:** 1086-02 TD-14 Runtime Symmetry + Close Gate
**Date:** 2026-05-22

## TD-14 Runtime Symmetry Probe

### Step 1: Rebuild

- Command: `docker compose up -d --build api worker`
- Result: PASS — both images built cleanly from current source tree; geolens-api and geolens-worker images rebuilt (sha256 ea8ca72d and fafca570 respectively)
- api healthy at: 2026-05-22T03:48:08Z (Up 5 seconds, healthy)
- worker healthy at: 2026-05-22T03:48:08Z (Up 5 seconds, healthy)

### Step 2: Container Names

- api container: `geolens-api-1`
- worker container: `geolens-worker-1`

### Step 3: api Probe

- Command: `docker exec geolens-api-1 grep -n 'ssl.*=.*False' app/core/config.py`
- Output (verbatim):
  ```
  309:            connect_args["ssl"] = False
  317:                ssl_ctx.check_hostname = False
  ```
- Exit code: 0 (the `ssl=False` line is line 309 — matches planning-time target exactly)

### Step 4: worker Probe

- Command: `docker exec geolens-worker-1 grep -n 'ssl.*=.*False' app/core/config.py`
- Output (verbatim):
  ```
  309:            connect_args["ssl"] = False
  317:                ssl_ctx.check_hostname = False
  ```
- Exit code: 0 (identical line 309 match — same source baked into worker image)

### TD-14 Disposition

PASSED — the v1018 Phase 1080-02 `ssl=False` line is present in both the api and worker container images at line 309. Source-runtime symmetry confirmed. The 8-hour drift from v1018 audit time is closed.

## Close-Gate Results

### Sequential pytest

- Command: `cd backend && env $(grep -v '^#' ../.env.test | grep -v '^$' | xargs) uv run pytest -p no:cacheprovider`
- Result: **3036 passed, 0 failed, 38 skipped** in 532.51s (8 min 52s)
- Verdict: **PASSED** (failed == 0 AND passed >= 3025)
- vs v1018 baseline (3025/0/38): +11 passed, same skipped — sequential mode unaffected by Phase 1085 xdist changes
- vs v1085 new baseline (3032/0/38): +4 passed — Phase 1084 added new test coverage

Note: pytest must be run from `backend/` with `.env.test` env vars loaded. Running from repo root without env vars produces `alembic.util.exc.CommandError: No 'script_location' key found` errors — not a failure, just a cwd/env requirement.

### Frontend e2e:smoke:builder

- Command: `npm run e2e:smoke:builder` (from repo root, targets root `package.json`)
- Result: **25 passed, 0 failed, 1 skipped** in 1.5 min
- Verdict: **PASSED** (exit 0)
- vs v1017/v1018 baseline (25-26/0/1): matches exactly (25 passed / 1 skipped)

### Frontend typecheck (TD-09 close-gate spot-check)

- Command: `cd frontend && npm run typecheck`
- Result: exit 0 (tsc -b --noEmit produces no errors)
- Verdict: **PASSED** — TD-09 regression check clear; 0 TypeScript errors

## Playwright MCP Smoke Results (orchestrator-run, 2026-05-22)

Run via Playwright MCP against `http://localhost:8080` on the rebuilt container stack (api + worker freshly rebuilt earlier in this plan). **Aggregate verdict: 5/5 PASS.**

| # | Surface | URL | Result |
|---|---------|-----|--------|
| 1 | Landing / catalog list | `/` | PASS — 0 console errors, 0 `/api/api/` patterns, title "Search - GeoLens" |
| 2 | Maps list | `/maps` | PASS — 0 console errors, 0 `/api/api/` patterns, title "Maps - GeoLens" |
| 3 | Dataset detail | `/datasets/5e042341-c2de-45c9-b9c8-e6998d71b99e` (Wetlands) | PASS — 0 console errors, 0 `/api/api/` patterns, title "Wetlands - GeoLens" |
| 4 | TD-11 regression (`/maps/new` redirect) | `/maps/new` | PASS — URL redirected to `/maps`, 0 console errors, 0 `/api/maps/new` requests, 0 422 responses |
| 5 | Map builder editor | `/maps/a130c253-6776-4a59-b2dc-41915e11b13d` (temp map created + deleted during smoke) | PASS — 0 console errors, 0 `/api/api/` patterns, title "v1019-mcp-smoke-test - GeoLens", 247 successful requests |

### TD-11 + TD-12 regression checks (consolidated)

- **TD-11 (`/maps/new` 422 console-noise eliminated)**: Surface 4 confirmed `/maps/new` → `/maps` redirect fires before any backend hook mounts. Zero `/api/maps/new` requests. Zero 422 responses.
- **TD-12 (`/api/api/` doubled prefix eliminated)**: All 5 surfaces show zero `/api/api/` URL patterns in network logs.

### Smoke cleanup

- Temp map `a130c253-6776-4a59-b2dc-41915e11b13d` (created for surface 5) deleted at smoke end (DELETE returned `204 No Content`). No persistent test data left in the catalog.

### Close-gate aggregate verdict

**v1019 CLOSE-GATE: PASSED** — TD-14 runtime probe confirms ssl=False at config.py:309 in both api + worker images; sequential pytest 3036/0/38 (+11 over v1018 baseline); e2e:smoke:builder 25/0/1 (matches v1017/v1018); frontend typecheck exit 0; Playwright MCP 5/5 surfaces clean with TD-11 + TD-12 regressions verified. Ready to cut tags `v1019` + `v1.5.4`.

### TD-09/TD-11/TD-12 regression checks (called out specifically)

- TD-09: surface 4 + 5 must show 0 console errors of shape `TS<n>` or `TypeError` (the 37 TS-error fix must not have introduced runtime regressions).
- TD-11: surface 4's `/maps/new` path must show 0 `422` responses in the network log.
- TD-12: surface 2's network log must show 0 URL patterns containing `/api/api/`.
