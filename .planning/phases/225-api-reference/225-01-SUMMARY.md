---
phase: 225-api-reference
plan: 01
subsystem: docs
tags: [openapi, node, mjs, fetch, snapshot, docs]

# Dependency graph
requires:
  - phase: 224-brand-shell-search
    provides: Docs shell, scripts/ convention (verify-shell-layout.mjs), package.json structure
provides:
  - fetch-openapi.mjs operator script — HTTP-fetch + validate + write OpenAPI snapshot
  - npm run fetch-openapi entry in docs/package.json
affects: [225-02, 225-03, 225-04, 225-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Native Node 22+ fetch (no tsx/undici) for operator scripts in docs subtree"
    - "Graduated exit codes: 0=success, 2=network, 3=invalid spec"
    - "FAIL: prefix on all error log lines (matches verify-build.sh / check-token-sync.sh)"

key-files:
  created:
    - getgeolens.com/docs/scripts/fetch-openapi.mjs
  modified:
    - getgeolens.com/docs/package.json

key-decisions:
  - "Used .mjs extension (not .ts) per repo precedent from verify-shell-layout.mjs — native Node fetch makes tsx unnecessary"
  - "Default URL is http://localhost:8000/api/openapi.json; GEOLENS_API_URL env overrides for staging/prod"
  - "Script does NOT run in CI — manual operator workflow only (D-04)"

patterns-established:
  - "fetch-openapi.mjs: structural validation before any write — refuses to overwrite snapshot with garbage"
  - "Deterministic output: JSON.parse + JSON.stringify(_, null, 2) + newline; no timestamps"

requirements-completed: [API-01]

# Metrics
duration: 8min
completed: 2026-04-26
---

# Phase 225 Plan 01: fetch-openapi.mjs Operator Snapshot Script Summary

**Node 22+ native-fetch operator script that HTTP-fetches /api/openapi.json, validates required OpenAPI 3.x fields, and writes a deterministic 2-space-indented snapshot to src/content/openapi/geolens.json — wired as `npm run fetch-openapi`**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-26T00:54:00Z
- **Completed:** 2026-04-26T01:02:42Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created `docs/scripts/fetch-openapi.mjs` with HTTP fetch, structural OpenAPI validation, graduated exit codes, and FAIL: prefix error reporting
- Wired `fetch-openapi` npm script in `docs/package.json` between `verify` and `astro` entries
- Script uses native Node 22+ fetch — no new dependencies added to the docs subtree

## Task Commits

Each task was committed atomically in the sibling repo on `gsd/phase-225-api-reference`:

1. **Task 1: Create fetch-openapi.mjs operator HTTP-fetch script** - `835beec` (feat)
2. **Task 2: Wire fetch-openapi npm script in docs/package.json** - `529213f` (feat)

## Files Created/Modified
- `getgeolens.com/docs/scripts/fetch-openapi.mjs` — Operator-run script: fetches /api/openapi.json, validates spec fields, writes deterministic JSON snapshot
- `getgeolens.com/docs/package.json` — Added `"fetch-openapi": "node scripts/fetch-openapi.mjs"` script entry

## Decisions Made
- **File extension `.mjs` vs `.ts`:** REQUIREMENTS API-01 says `.ts` literally, but the repo has zero TypeScript tooling for scripts — only `verify-shell-layout.mjs` as precedent. Used `.mjs` per planning_context correction #3. Native Node 22+ fetch makes `tsx` unnecessary, and the script behavior (fetch + validate + write) is identical regardless of extension.
- **No new dependencies:** `tsx`, `undici`, and any other runners were explicitly excluded. Native fetch is available at `>=22.12.0` (already in `engines.node`).

## Deviations from Plan

None — plan executed exactly as written. The `.mjs` extension choice was pre-decided in the plan itself (planning_context correction #3), not a runtime deviation.

## Issues Encountered
None.

## User Setup Required
None — no external service configuration required for this tooling-only plan.

## Next Phase Readiness
- Plan 02 can now run `npm run fetch-openapi` against a live geolens backend to produce and commit `src/content/openapi/geolens.json`
- The snapshot directory (`src/content/openapi/`) is created automatically by the script's `mkdir({ recursive: true })` call
- Plan 02 dependency: must run the script against a live backend and commit the output before Plan 03 can install and wire `starlight-openapi@0.25.0`

---
*Phase: 225-api-reference*
*Completed: 2026-04-26*
