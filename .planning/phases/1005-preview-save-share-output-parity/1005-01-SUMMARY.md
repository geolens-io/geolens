---
phase: 1005-preview-save-share-output-parity
plan: 01
subsystem: frontend-backend
tags: [map-builder, public-viewer, share, embed, openapi, vitest]

requires:
  - phase: 1002-kepler-guided-builder-workflow-audit-and-triage
    provides: F-1002-01, F-1002-05, F-1002-07 routed findings
  - phase: 1003-map-stack-inspector-interaction-polish
    provides: stable new add-layer ordering
  - phase: 1004-styling-and-cartography-control-polish
    provides: stable style/filter/label/popup contracts
provides:
  - Stable public viewer layer identity independent of sort_order
  - Shared-token API payloads include layer IDs
  - Builder save state distinguishes saved, unsaved, saving, failed, and retry
  - Share/embed dialog warns when public output is behind unsaved or failed saves
affects: [phase-1006-a11y-copy, phase-1007-qa-gate]

tech-stack:
  added: []
  patterns: [viewer layer identity helper, explicit builder save status]

key-files:
  created:
    - frontend/src/components/viewer/layer-identity.ts
    - frontend/src/components/viewer/__tests__/use-viewer-layers.test.ts
  modified:
    - backend/app/modules/catalog/maps/schemas.py
    - backend/app/modules/catalog/maps/service_public.py
    - backend/openapi.json
    - backend/tests/test_maps.py
    - frontend/src/components/viewer/LayerLegend.tsx
    - frontend/src/components/viewer/ViewerMap.tsx
    - frontend/src/components/viewer/hooks/use-viewer-layers.ts
    - frontend/src/components/builder/hooks/use-builder-save.ts
    - frontend/src/components/builder/MapTitleBar.tsx
    - frontend/src/components/builder/SharePanel.tsx
    - frontend/src/components/builder/BuilderDialogs.tsx
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/pages/PublicMapViewerPage.tsx
    - frontend/src/types/api.ts
    - frontend/src/i18n/locales/{en,es,fr,de}/builder.json

requirements-completed: [OUTPUT-01, OUTPUT-02, OUTPUT-03, OUTPUT-04, OUTPUT-05, OUTPUT-06]
duration: 51 min
completed: 2026-05-11T20:51:55Z
---

# Phase 1005 Plan 01: Save, Share, and Viewer Output Parity Summary

**Builder preview, saved state, shared-token output, authenticated public output, and embed output now share stable layer identity and clearer publication state.**

## Accomplishments

- Added stable viewer-layer keys and used them for legend list keys, visibility toggles, ViewerMap sync IDs, popup lookup, token refresh, and visibility sync.
- Added `id` to shared-token layer responses and refreshed `backend/openapi.json`.
- Preserved authenticated public map parity by carrying `MapLayerResponse.id` into `PublicMapViewerPage.toSharedLayer`.
- Added explicit save status from `useBuilderSave`: `saved`, `unsaved`, `saving`, `failed`, plus retryable state.
- Rendered save status in `MapTitleBar` and added share/embed warnings when output still reflects the last saved map.
- Added focused frontend and backend regression coverage for duplicate sort-order identity, save failure retry state, share output warnings, and shared-map layer IDs.

## Task Commits

1. **Task 1: Stabilize public viewer layer identity** - `36ed9f06` (fix)
2. **Task 2: Clarify save and share output state** - `be66fdca` (feat)

## Decisions Made

- Shared-token responses now include map-layer IDs because fallback identity cannot fully distinguish legacy duplicate-order layers without a server-side stable ID.
- Legacy shared payloads still get deterministic fallback keys based on order, dataset, table, and array position.
- Server-side thumbnails remain useful for long-term gallery parity but are not required for Phase 1005 builder/public-output parity; the existing client thumbnail capture remains unchanged.

## Deviations from Plan

None - plan executed as written.

## Issues Encountered

- Initial frontend tests needed expectation updates because legend accessible names omit the word "layer" and the title bar now intentionally renders "Saved" in both the status and button.

## Verification

- `cd frontend && npm run test -- LayerLegend use-viewer-layers ViewerMap.basemap-config PublicViewerPage PublicMapViewerPage MapTitleBar SharePanel use-builder-save --run` - passed, 8 files / 59 tests.
- `cd frontend && npm run lint` - passed.
- `cd backend && POSTGRES_PORT=5434 uv run pytest tests/test_maps.py -k "get_shared_map_success"` - passed, 1 test.
- `cd backend && uv run ruff check app/modules/catalog/maps/schemas.py app/modules/catalog/maps/service_public.py tests/test_maps.py` - passed.
- `cd backend && uv run ruff format --check app/modules/catalog/maps/schemas.py app/modules/catalog/maps/service_public.py tests/test_maps.py` - passed.
- `make openapi-check` - passed.

## Next Phase Readiness

Phase 1006 can focus on responsive, accessibility, and copy hardening on top of stable output identity and clearer save/share state.

## Self-Check: PASSED
