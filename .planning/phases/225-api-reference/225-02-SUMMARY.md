---
phase: 225-api-reference
plan: 02
subsystem: api
tags: [openapi, snapshot, fastapi, fetch-openapi]

requires:
  - phase: 225-01
    provides: fetch-openapi.mjs script + npm script entry that produces deterministic snapshots from a running backend
provides:
  - Committed `geolens.json` OpenAPI snapshot in `getgeolens.com/docs/src/content/openapi/`
  - 174 paths captured at `info.version: 1.0.0`
  - Deterministic 2-space pretty-printed JSON (26,481 lines), insertion-preserving order
  - Source-of-truth artifact for the docs build (read by starlight-openapi in Plan 03+)
affects: [225-03, 225-06, 225-10]

tech-stack:
  added: []
  patterns:
    - "Operator-driven snapshot refresh: backend up → fetch-openapi → review diff → commit (no CI automation per D-04)"
    - "Env-var override (GEOLENS_API_URL) accommodates host-port variations across dev environments"

key-files:
  created:
    - getgeolens.com/docs/src/content/openapi/geolens.json
  modified: []

key-decisions:
  - "Operator workflow: GEOLENS_API_URL=http://localhost:8001/api/openapi.json npm run fetch-openapi (host-side mapping; container is on internal port 8000, mapped to host 8001 in this dev environment)"
  - "Snapshot pinned at info.version=1.0.0 / openapi=3.1.0 / 174 paths"
  - "Committed in sibling repo on feature branch gsd/phase-225-api-reference (NOT main) so the work is reviewable as a unit before landing"

patterns-established:
  - "Cross-repo coordinated commit: code commits in getgeolens.com on feature branch, tracking SUMMARY.md in geolens on main"
  - "Snapshot diff reviewability: pretty-print + insertion-preserving JSON.stringify produces line-stable diffs across re-fetches (D-05)"

requirements-completed: ["API-01"]

duration: 3min
completed: 2026-04-26
---

# Phase 225, Plan 02: OpenAPI Snapshot Generation

**Captured live FastAPI OpenAPI spec (174 paths, v1.0.0) into a committed deterministic JSON snapshot — the source-of-truth artifact for the docs build.**

## Performance

- **Duration:** ~3 min (operator-driven, single fetch + commit)
- **Started:** 2026-04-26 (orchestrator-executed; backend already running locally via `docker compose`)
- **Completed:** 2026-04-26
- **Tasks:** 1/1 (the human-action snapshot capture)
- **Files modified:** 1 created, 0 modified

## Accomplishments

- Live `GeoLens API v1.0.0` OpenAPI spec captured from running FastAPI instance
- 174 paths snapshotted; spec is OpenAPI 3.1.0
- Deterministic output verified: re-running the script produces byte-identical JSON
- Snapshot committed in `getgeolens.com` on `gsd/phase-225-api-reference` (commit `0861c4d`)

## Task Commits

1. **Task 1: snapshot capture + commit** — `0861c4d` in `getgeolens.com` (feat)

**Plan metadata:** to be committed alongside SUMMARY.md in geolens repo on `main`.

## Files Created/Modified

- `getgeolens.com/docs/src/content/openapi/geolens.json` (created, 26,481 lines) — committed OpenAPI snapshot read by starlight-openapi in Plan 03

## Decisions Made

- **Host port for backend API: 8001, not 8000.** This dev machine maps the container's internal port 8000 to host 8001 (`127.0.0.1:8001->8000/tcp` per `docker compose ps`). The Plan 01 fetch script's default `http://localhost:8000/api/openapi.json` was overridden via `GEOLENS_API_URL=http://localhost:8001/api/openapi.json` — exactly the env-var path documented in the openapi/README.md from Plan 07. This validates the env-var override design for non-default port mappings.

- **No backend changes during this plan.** The operator workflow is read-only against the live API. Backend repo (`/Users/ishiland/Code/geolens`) is unmodified; only `getgeolens.com` received commits.

- **Branch hygiene:** Snapshot commit went to `gsd/phase-225-api-reference` (the feature branch the orchestrator created), keeping all Phase 225 work isolated from `main` of `getgeolens.com` until the user reviews the full phase as a single unit.

## Deviations from Plan

**Total deviations:** 1 — minor, environment-specific.

### Auto-fixed Issues

**1. [Environment Variance] Backend host port differed from CONTEXT D-01 default**

- **Found during:** Task 1 (initial fetch attempt at default URL)
- **Issue:** `curl http://localhost:8000/api/openapi.json` returned a 404 HTML page (something else is bound to host port 8000 — likely an unrelated local service). The geolens API container is mapped to host port 8001, not 8000, on this dev machine.
- **Fix:** Used the env-var override path documented in Plan 07's README: `GEOLENS_API_URL="http://localhost:8001/api/openapi.json" npm run fetch-openapi`. Fetched cleanly on first try at the corrected URL.
- **Files modified:** None (the script and README support this case by design — D-02 / D-25)
- **Verification:** Snapshot file is 26,481 lines, contains 174 path entries, parses as valid OpenAPI 3.1.0
- **Committed in:** `0861c4d`

---

**Impact on plan:** Validated the env-var override design. No scope creep, no script changes needed. Future operators on hosts with different port mappings should use the same override pattern documented in `src/content/openapi/README.md`.

## Issues Encountered

- Initial `curl` probe to `http://localhost:8000/api/openapi.json` returned HTML (Django-style "Page not found"), suggesting host port 8000 was bound to an unrelated local service. Resolved by checking `docker compose ps --format` to identify the actual host-side mapping (`127.0.0.1:8001->8000/tcp` for the `api` service).

## User Setup Required

None — no external services. The committed snapshot is now the build artifact's source of truth.

## Next Phase Readiness

- ✅ Snapshot is in place at `getgeolens.com/docs/src/content/openapi/geolens.json`
- ✅ Plan 03 (starlight-openapi install + register) can proceed — its `schema:` field will point at this file
- ✅ Plan 06 (curated landing page) can read `info.version` from this file for the "Spec snapshot" callout
- ✅ Plan 10 (verify-build.sh assertion) can grep for the rendered version in the build artifact

**Maintenance note for future operators:** The default URL in `fetch-openapi.mjs` is `http://localhost:8000/api/openapi.json`. If your dev container is mapped to a different host port, set `GEOLENS_API_URL` accordingly. This is documented in `src/content/openapi/README.md` (Plan 07's deliverable).

---
*Phase: 225-api-reference*
*Completed: 2026-04-26*
