---
phase: 1000-kepler-inspired-map-stack-and-basemap-layer-controls
plan: 04
subsystem: ui-api
tags: [map-builder, map-stack, basemap-config, maplibre, openapi, sdk]

# Dependency graph
requires:
  - phase: 1000-kepler-inspired-map-stack-and-basemap-layer-controls
    provides: Plan 1000-02 normalized Map Stack model and Plan 1000-03 unified stack inspector shell
provides:
  - Persisted map-level basemap_config API contract with strict curated fields
  - Basemap appearance controls inside the Map Stack Basemap group
  - Style JSON export/import round-trip for basemap appearance metadata
  - MapLibre basemap style transforms and explicit z-order policy helper
  - OpenAPI and SDK types for basemap_config
affects: [map-builder, basemap-controls, saved-maps, public-viewer, style-json, openapi, sdks]

# Tech tracking
tech-stack:
  added: []
  patterns: [nullable JSONB compatibility field, strict Pydantic appearance schema, safe MapLibre style transform, selective generated artifact staging]

key-files:
  created:
    - backend/alembic/versions/0011_map_basemap_config.py
    - frontend/src/components/builder/BasemapAppearanceControls.tsx
    - frontend/src/components/builder/__tests__/BasemapAppearanceControls.test.tsx
    - sdks/python/geolens/models/basemap_config.py
  modified:
    - backend/app/modules/catalog/maps/schemas.py
    - backend/app/modules/catalog/maps/router.py
    - backend/app/modules/catalog/maps/style_json.py
    - frontend/src/components/builder/BuilderMap.tsx
    - frontend/src/components/builder/MapStackPanel.tsx
    - frontend/src/components/builder/map-sync.ts
    - frontend/src/lib/basemap-utils.ts
    - backend/openapi.json

key-decisions:
  - "Persist basemap appearance as nullable map-level basemap_config while retaining show_basemap_labels for backward compatibility."
  - "Use a current Alembic revision id in the existing migration chain even though the plan-owned filename is 0011_map_basemap_config.py."
  - "Apply curated controls through tolerant style transforms that degrade safely for custom and raster basemaps."
  - "Commit only basemap-related OpenAPI and SDK output, leaving unrelated generated drift unstaged."

patterns-established:
  - "Basemap controls normalize null config to current behavior and keep legacy show_basemap_labels synchronized from label_mode."
  - "GeoLens style metadata can carry basemap_config through export/import without requiring older styles to include it."
  - "Map sync exposes MAP_STACK_Z_ORDER_POLICY so the stack order is documented and unit-testable."

requirements-completed: [MAPSTACK-03, MAPSTACK-04, MAPSTACK-06]

# Metrics
duration: 33min
completed: 2026-05-11
---

# Phase 1000 Plan 04: Persisted Basemap Appearance Summary

**Persisted basemap appearance controls with API, style JSON, SDK, and MapLibre z-order support.**

## Performance

- **Duration:** 33 min
- **Started:** 2026-05-11T13:18:00Z
- **Completed:** 2026-05-11T13:50:43Z
- **Tasks:** 5 completed
- **Files modified:** 40

## Accomplishments

- Added `basemap_config` storage, validation, create/update/detail/public response support, duplicate preservation, and history event coverage.
- Preserved `basemap_config` through GeoLens style JSON export/import.
- Added compact Map Stack controls for labels, roads, boundaries, land/water tone, relief contrast, and supported buildings.
- Wired builder load/save state so basemap changes persist while older maps without config keep current behavior.
- Added safe MapLibre style transforms plus an explicit `MAP_STACK_Z_ORDER_POLICY` for surface, relief, basemap detail, user data, basemap labels, and data labels.
- Refreshed OpenAPI plus Python and TypeScript SDK basemap contract types.

## Task Commits

Each task was committed atomically where feasible:

1. **Task 1 red tests: basemap_config persistence coverage** - `0cdf1203` (test)
2. **Task 1 implementation: map basemap_config contract** - `a5b80a8a` (feat)
3. **Task 2: style JSON basemap_config round-trip** - `b72408cc` (feat)
4. **Task 3: Map Stack basemap appearance controls** - `c94e8cac` (feat)
5. **Task 4: MapLibre style transforms and z-order policy** - `4b5634b1` (feat)
6. **Task 5: OpenAPI and SDK basemap artifacts** - `6a18ed2c` (chore)

## Files Created/Modified

- `backend/alembic/versions/0011_map_basemap_config.py` - Adds nullable `catalog.maps.basemap_config`.
- `backend/app/modules/catalog/maps/{models.py,schemas.py,router.py,service_crud.py,service_public.py,style_json.py}` - Persists, validates, returns, imports, exports, and duplicates basemap appearance config.
- `backend/tests/test_maps.py` and `backend/tests/test_maps_style_json.py` - Backend persistence and style JSON coverage.
- `frontend/src/components/builder/BasemapAppearanceControls.tsx` - Curated basemap sublayer controls.
- `frontend/src/components/builder/{BuilderMap.tsx,MapStackPanel.tsx,map-stack.ts,map-sync.ts}` - Builder rendering, stack metadata, controls, and z-order wiring.
- `frontend/src/components/builder/hooks/{use-builder-layers.ts,use-builder-save.ts}` and `frontend/src/pages/MapBuilderPage.tsx` - Builder load/save/page state wiring.
- `frontend/src/lib/basemap-utils.ts` - Config normalization and style transformation helpers.
- `frontend/src/components/builder/__tests__/*`, builder hook tests, and `MapBuilderPage.header-actions.test.tsx` - Focused UI and state coverage.
- `backend/openapi.json`, `frontend/src/types/api.ts`, `sdks/python/geolens/models/*`, and `sdks/typescript/src/client/*` - API and SDK type surface.

## Decisions Made

- Kept `show_basemap_labels` as a compatibility field and derived it from `label_mode` during builder saves.
- Used `extra="forbid"` on the backend Pydantic `BasemapConfig` model to keep the API contract curated.
- Implemented style transforms by classifying common layer ids/types/source-layer names rather than exposing raw style-layer editing.
- Kept unsupported controls harmless for raster/custom basemaps by preserving unrecognized layers.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Used the current Alembic chain revision**
- **Found during:** Task 1 (migration implementation)
- **Issue:** The plan-owned migration filename was `0011_map_basemap_config.py`, but the repository already had later migration revisions.
- **Fix:** Kept the requested filename but used revision id `0017_map_basemap_config` with `down_revision = "0016_drop_redundant_data_gid_indexes"`.
- **Files modified:** `backend/alembic/versions/0011_map_basemap_config.py`
- **Verification:** Backend map tests passed against the compose Postgres database.
- **Committed in:** `a5b80a8a`

**2. [Rule 1 - Bug] Added required builder state wiring outside the narrow ownership list**
- **Found during:** Task 3 (save/load integration)
- **Issue:** The controls could not persist through real builder load/save paths by editing only the component files named in the ownership list.
- **Fix:** Added `basemapConfig` to builder load/save/page state and updated the affected focused tests.
- **Files modified:** `frontend/src/components/builder/hooks/use-builder-layers.ts`, `frontend/src/components/builder/hooks/use-builder-save.ts`, `frontend/src/pages/MapBuilderPage.tsx`, and related focused tests.
- **Verification:** `cd frontend && npm run test -- BasemapAppearanceControls MapStackPanel --run`; `cd frontend && npm run test -- BuilderMap basemap-utils --run`; final focused frontend test command passed.
- **Committed in:** `c94e8cac`

**3. [Rule 1 - Bug] Selectively staged generated artifacts amid unrelated drift**
- **Found during:** Task 5 (SDK generation)
- **Issue:** Regeneration also surfaced unrelated generated changes for dataset `tile_columns` and the map-layer route description.
- **Fix:** Committed only basemap_config OpenAPI and SDK hunks; left unrelated generated drift unstaged for its owning work.
- **Files modified:** `backend/openapi.json`, `sdks/python/geolens/models/*`, `sdks/typescript/src/client/index.ts`, `sdks/typescript/src/client/types.gen.ts`
- **Verification:** Cached diff was checked for `tile_columns`, route-description drift, and patch-layer doc churn before committing.
- **Committed in:** `6a18ed2c`

---

**Total deviations:** 3 auto-fixed (3 Rule 1 bugs)
**Impact on plan:** All deviations were required to preserve migration correctness, real persistence behavior, and ownership boundaries in a dirty shared worktree.

## Issues Encountered

- `tests/test_maps.py` initially failed on the default `localhost:5432` database port. The compose database for this workspace is exposed on `5434`; rerunning with `POSTGRES_PORT=5434` passed.
- `make sdks-check` failed after regeneration because unrelated generated SDK drift remains in the worktree: dataset `tile_columns` models/types and the `/maps/{map_id}/layers` route description. Basemap SDK artifacts were generated and committed separately.
- Vitest emitted the existing warning ``--localstorage-file` was provided without a valid path`; targeted tests still passed.

## User Setup Required

None - no external service configuration required.

## Verification

- `cd backend && uv run pytest tests/test_maps_style_json.py -q -k 'basemap_config'` - failed before implementation as the expected red test.
- `cd backend && POSTGRES_PORT=5434 uv run pytest tests/test_maps.py -q -k 'basemap_config'` - passed, 5 tests.
- `cd backend && uv run pytest tests/test_maps_style_json.py -q` - passed, 27 tests.
- `cd backend && uv run ruff check app/modules/catalog/maps/models.py app/modules/catalog/maps/schemas.py app/modules/catalog/maps/router.py app/modules/catalog/maps/service_crud.py app/modules/catalog/maps/service_public.py app/modules/catalog/maps/style_json.py tests/test_maps.py tests/test_maps_style_json.py` - passed.
- `cd frontend && npm run test -- BasemapAppearanceControls MapStackPanel --run` - passed, 2 files / 6 tests.
- `cd frontend && npm run test -- BuilderMap basemap-utils --run` - passed, 2 files / 49 tests.
- `cd backend && POSTGRES_PORT=5434 uv run pytest tests/test_maps.py tests/test_maps_style_json.py -q` - passed, 158 tests / 1 warning.
- `cd frontend && npm run test -- BasemapAppearanceControls BuilderMap --run` - passed, 2 files / 19 tests.
- `cd frontend && npm run lint` - passed.
- `make openapi` - completed and wrote `backend/openapi.json`.
- `make sdks` - completed and regenerated SDK output.
- `make openapi-check` - passed.
- `make sdks-check` - failed on unrelated generated drift listed above.

## Next Phase Readiness

Plan 1000-04 is complete. Plan 1000-05 can polish relief/marketing outputs and run Playwright MCP validation on top of persisted basemap appearance controls and the explicit z-order policy.

---
*Phase: 1000-kepler-inspired-map-stack-and-basemap-layer-controls*
*Completed: 2026-05-11*
