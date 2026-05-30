---
slug: builder-qa-smoke
status: complete
date: 2026-05-30
type: qa-smoke
code_changes: true
---

# SUMMARY — Map Builder QA Smoke Pass + Fixes

Live Playwright-MCP QA sweep across all 4 current maps (raster, vector+DEM marketing,
9-layer 3D terrain, empty), then fixed every actionable finding. Orchestrator-driven
(subagents lack MCP access).

## Findings & resolution

- **F1 (blocker symptom, environmental — resolved by restart):** raster colormap/stretch
  reverted to grayscale on reload — traced to a **stale Vite bundle** (frontend container
  predated today's fix `de9d1f8d`), NOT a code defect. `docker compose restart frontend`
  fixed it; round-trip then verified end-to-end. Memory note added so it doesn't recur.
- **F2 (minor bug — FIXED):** Settings widget toggles didn't mark the map dirty. Added
  `handleToggleWidget` that calls `setHasUnsavedChanges(true)`. Verified: Measure toggle now
  shows "Unsaved changes".
- **F3 (was runtime-only — now PERSISTED):** projection (Mercator/Globe) now persists on
  `basemap_config.projection` — seeded on load, applied to the live map when ready, and
  marks dirty. Verified globe → save → reload round-trip (map + Settings + DB).
- **F4 (latent bug found while fixing F3 — FIXED):** the backend `BasemapConfig`
  (`extra="forbid"`) lacked `basemap_position`, so saving a map with the basemap dragged
  above data 422'd silently (frontend has sent the field wholesale since Phase 1051; no map
  ever persisted it). Added `basemap_position` + `projection` to the schema (jsonb-additive,
  no migration). Verified PUT → 200 + round-trip.

## Changes

Backend: `app/modules/catalog/maps/schemas.py` (+ `BasemapPosition`/`BasemapProjection`
enums, 2 fields). Frontend: `MapBuilderPage.tsx`, `basemap-utils.ts`,
`basemap-state-controller.ts`, `SettingsEditorScene.tsx`, `types/api.ts`. Tests:
`test_maps.py` (+2 regression), `test_maps_style_json.py`, `BuilderMap.unit.test.ts`.
`backend/openapi.json` regenerated.

## Verification

Frontend typecheck 0; vitest 1473/1473 (touched areas); backend maps suites green incl. new
regression tests; ruff + eslint clean. Live MCP confirmed F2/F3 fixed; F4 confirmed at API
level. All QA-induced map mutations restored.
