---
phase: 1139-quality-sweep-and-playwright-close-gate
plan: "02"
subsystem: api
tags: [openapi, sdk, changelog, pitfall-15, maps-access]

requires:
  - phase: 1134-map-functionality-and-smaller-screen-polish
    provides: delete-layer/visibility/rename/layout fixes
  - phase: 1135-ai-chat-confirm-before-apply-and-analysis-polish
    provides: AI Shape B staging buffer, preview chips, data-analysis card
  - phase: 1136-per-render-mode-editor-polish
    provides: RasterEditor 7 controls, LineEditor line-cap/join, FillEditor 3D hint, BasemapEditor no-basemap
  - phase: 1137-sharing-and-embed-polish
    provides: share chips, expiration presets, Powered by GeoLens, legend+title, iframe preview
  - phase: 1138-easy-win-sweep
    provides: Cmd/Ctrl+S save, popup URL/media, empty-layer hint

provides:
  - CHANGELOG [Unreleased] populated with measured v1030 numbers alongside v1029 entries
  - OpenAPI snapshot refreshed — GET /maps/{map_id}/access/ and MapAccessResponse now in backend/openapi.json
  - Python + TypeScript SDKs updated for MapAccessResponse endpoint
  - 1139-OPENAPI-DECISION.md recording Pitfall #15 proof (verdict: CHANGED)

affects:
  - 1139-quality-sweep-and-playwright-close-gate
  - getgeolens.com sibling docs repo (npm run fetch-openapi required downstream)

tech-stack:
  added: []
  patterns:
    - "Pitfall #15 contract: non-empty openapi diff → CHANGELOG bullet + sibling docs follow-up note; empty diff → explicit Verification line"
    - "make openapi (geolens) BEFORE npm run fetch-openapi (sibling) — dual-snapshot order"

key-files:
  created:
    - .planning/phases/1139-quality-sweep-and-playwright-close-gate/1139-OPENAPI-DECISION.md
    - sdks/python/geolens/api/maps/get_map_access_endpoint_maps_map_id_access_get.py
    - sdks/python/geolens/models/map_access_response.py
  modified:
    - CHANGELOG.md
    - backend/openapi.json
    - sdks/python/geolens/models/__init__.py
    - sdks/typescript/src/client/index.ts
    - sdks/typescript/src/client/sdk.gen.ts
    - sdks/typescript/src/client/types.gen.ts

key-decisions:
  - "OpenAPI verdict CHANGED: GET /maps/{map_id}/access/ + MapAccessResponse were missing from committed snapshot (added in 3ed5ceb3, not regenerated at that commit)"
  - "sdks-check failure pre-commit is expected and correct — make sdks-check = make sdks + git diff --exit-code; must commit generated files first, then re-run to confirm"
  - "Sibling docs npm run fetch-openapi is a required manual downstream follow-up (out of scope for geolens plan)"

patterns-established:
  - "OpenAPI drift can originate in commits that touch router+schema but skip snapshot regeneration — the DCAT-US refresh (33b9a9a1) ran after but didn't pick up the earlier maps/access endpoint"
  - "Pitfall #15 decision doc format: starting state → commands with exit codes → diff verdict → schema paths changed → root cause explanation → SDK changes → downstream follow-up"

requirements-completed: [QA-04]

duration: 5min
completed: 2026-05-28
---

# Phase 1139 Plan 02: CHANGELOG [Unreleased] + OpenAPI/SDK Refresh Summary

**CHANGELOG populated with 16 v1030 builder-polish bullets; OpenAPI drift caught and fixed (MapAccessResponse + GET /maps/{map_id}/access/ from commit 3ed5ceb3 not in snapshot); make openapi-check and make sdks-check both exit 0**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-28T11:00:08Z
- **Completed:** 2026-05-28T11:05:15Z
- **Tasks:** 3
- **Files modified:** 9 (CHANGELOG.md, backend/openapi.json, 4 SDK files, 1 decision doc, 2 new SDK files)

## Accomplishments

- CHANGELOG `[Unreleased]` now carries all v1030 builder-polish entries with measured numbers (7 raster controls, line-cap/join, AI Shape B, 5 expiration presets, "Powered by GeoLens" branding, etc.) alongside the preserved v1029 DCAT-US entries.
- `make openapi` found genuine schema drift: `GET /maps/{map_id}/access/` and `MapAccessResponse` were absent from the committed snapshot. Backend endpoint was added in `3ed5ceb3`; snapshot was not regenerated at that commit. Drift committed and SDKs updated.
- Pitfall #15 closed in both directions: the non-empty diff produced a CHANGELOG Changed bullet and explicit Verification note; `1139-OPENAPI-DECISION.md` records the full evidence trail.

## Task Commits

1. **Task 1: Populate CHANGELOG [Unreleased] with v1030 measured numbers** - `65b4297a` (docs)
2. **Task 2: OpenAPI snapshot + SDK refresh (CHANGED)** - `41a57488` (chore)
3. **Task 2+3: CHANGELOG reconciliation + 1139-OPENAPI-DECISION.md** - `1a51f27f` (docs)

## Files Created/Modified

- `/Users/ishiland/Code/geolens/CHANGELOG.md` — 16 new v1030 bullets (9 Added, 7 Fixed) + 1 Changed + 1 Verification entry
- `/Users/ishiland/Code/geolens/backend/openapi.json` — +136 lines: MapAccessResponse schema + GET /maps/{map_id}/access/ path
- `/Users/ishiland/Code/geolens/sdks/python/geolens/api/maps/get_map_access_endpoint_maps_map_id_access_get.py` — new Python SDK endpoint file
- `/Users/ishiland/Code/geolens/sdks/python/geolens/models/map_access_response.py` — new Python SDK model
- `/Users/ishiland/Code/geolens/sdks/python/geolens/models/__init__.py` — MapAccessResponse import/export
- `/Users/ishiland/Code/geolens/sdks/typescript/src/client/types.gen.ts` — MapAccessResponse types + request/response types
- `/Users/ishiland/Code/geolens/sdks/typescript/src/client/sdk.gen.ts` — getMapAccessEndpointMapsMapIdAccessGet function
- `/Users/ishiland/Code/geolens/sdks/typescript/src/client/index.ts` — re-exports new function
- `/Users/ishiland/Code/geolens/.planning/phases/1139-quality-sweep-and-playwright-close-gate/1139-OPENAPI-DECISION.md` — full Pitfall #15 evidence trail

## Decisions Made

- Verdict CHANGED rather than UNCHANGED: the plan's `<backend_change_inventory>` anticipated UNCHANGED (docstring/validator/header changes don't move schema), but the `GET /maps/{map_id}/access/` endpoint added in `3ed5ceb3` was never captured in the snapshot. This is correct behavior — the plan explicitly says "PROVE which case is true via Task 2" rather than assuming.
- Committing the SDK updates before re-running `make sdks-check` is the correct sequence (sdks-check runs `make sdks` + `git diff --exit-code`; must stage and commit generated files first so the subsequent regeneration produces a clean diff).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] OpenAPI snapshot drift: GET /maps/{map_id}/access/ missing from backend/openapi.json**
- **Found during:** Task 2 (make openapi regeneration)
- **Issue:** Commit `3ed5ceb3` added `MapAccessResponse` + `GET /maps/{map_id}/access/` to the FastAPI router/schemas but skipped snapshot regeneration. Subsequent DCAT-US refresh (`33b9a9a1`) regenerated the snapshot but didn't pick up the maps/access endpoint.
- **Fix:** Committed the regenerated `backend/openapi.json` (+136 lines) plus all SDK artifacts (2 new Python files, 4 modified TypeScript/Python files).
- **Files modified:** backend/openapi.json, sdks/python/geolens/api/maps/get_map_access_endpoint_maps_map_id_access_get.py, sdks/python/geolens/models/map_access_response.py, sdks/python/geolens/models/__init__.py, sdks/typescript/src/client/types.gen.ts, sdks/typescript/src/client/sdk.gen.ts, sdks/typescript/src/client/index.ts
- **Committed in:** `41a57488`

---

**Total deviations:** 1 auto-fixed (Rule 1 — genuine schema drift caught by regeneration)
**Impact on plan:** Correct behavior — the Pitfall #15 protocol exists precisely to surface this. The deviation is the proof that the gate works.

## Issues Encountered

None beyond the expected OpenAPI CHANGED verdict.

## Downstream Follow-Up Required

The sibling docs repo (`~/Code/getgeolens.com`) requires `npm run fetch-openapi` to pull the updated geolens OpenAPI snapshot before the next docs deploy. This is outside this plan's scope and is documented in `1139-OPENAPI-DECISION.md`.

## Next Phase Readiness

- QA-04 satisfied: CHANGELOG documented, OpenAPI + SDKs proven in-sync
- `make openapi-check` exit 0, `make sdks-check` exit 0
- Pitfall #15 closed in both directions with documented evidence
- Ready for Phase 1139 Plan 03 (Playwright close-gate)

## Self-Check

- [ ] CHANGELOG.md exists and contains "Raster layer editor" and "line-cap" and "Powered by GeoLens"
- [ ] 1139-OPENAPI-DECISION.md exists and contains "OpenAPI surface verdict:"
- [ ] Commits 65b4297a, 41a57488, 1a51f27f exist

---
*Phase: 1139-quality-sweep-and-playwright-close-gate*
*Completed: 2026-05-28*
