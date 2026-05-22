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

## Playwright MCP Smoke Checklist (for orchestrator)

The orchestrator runs this checklist via Playwright MCP against `http://localhost:8080` after this plan's automated close-gate passes. Five surfaces, zero console errors per surface, zero failed network requests per surface. Aggregate verdict: 5/5 PASS.

| Surface | URL | Pass Criteria |
|---------|-----|---------------|
| 1. Landing / catalog list | `http://localhost:8080/` | Page renders; 0 console errors; 0 failed network requests |
| 2. Maps list | `http://localhost:8080/maps` | Page renders; auth gate works or anonymous view loads; 0 console errors; 0 failed network requests; NO `/api/api/` patterns in network log (TD-12 regression check) |
| 3. Dataset detail | `http://localhost:8080/datasets/<any-existing-uuid>` | Pick any uuid from a `/datasets` API response; page renders; 0 console errors |
| 4. Map builder | `http://localhost:8080/maps/<any-existing-uuid>` (or `/maps/new` after login) | Editor scene loads; 0 console errors; NO 422 console-noise on the path `/maps/new` (TD-11 regression check) |
| 5. Map viewer | `http://localhost:8080/maps/<any-existing-uuid>` (viewer mode if separate URL, otherwise same as 4) | Viewer renders the saved map state; 0 console errors |

### Orchestrator instructions

After this plan's SUMMARY commit lands, the orchestrator should:
1. Confirm the stack is up (`docker compose ps` shows api + worker + frontend healthy).
2. Run the 5-surface Playwright MCP smoke with `--use-playwright-mcp`.
3. Append the result (5/5 PASS or N/5 with details) to this file as a new `## MCP Smoke Result` section.
4. If 5/5 PASS, proceed to tag-cutting (`git tag v1019 <SHA>` + `git tag v1.5.4 <SHA>` — same SHA, the post-baseline commit).
5. If any surface fails with 422s or `/api/api/` patterns, that indicates a TD-11 or TD-12 regression — block tag-cutting and surface to user.

### TD-09/TD-11/TD-12 regression checks (called out specifically)

- TD-09: surface 4 + 5 must show 0 console errors of shape `TS<n>` or `TypeError` (the 37 TS-error fix must not have introduced runtime regressions).
- TD-11: surface 4's `/maps/new` path must show 0 `422` responses in the network log.
- TD-12: surface 2's network log must show 0 URL patterns containing `/api/api/`.
