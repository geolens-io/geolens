---
phase: 260325-rpv
plan: 01
subsystem: ui
tags: [maplibre, basemaps, attribution, admin, i18n]

requires: []
provides:
  - "Admin settings tab renamed from Appearance to Map with Globe icon"
  - "Stamen Terrain preset replaced with OpenFreeMap Bright (no API key required)"
  - "Attribution field on BasemapEntry and in custom basemap form"
  - "MapLibre AttributionControl re-enabled on all 4 map components"
  - "toMaplibreStyle() accepts optional attribution for XYZ raster sources"
affects: [admin-settings, map-components, basemap-utils]

tech-stack:
  added: []
  patterns:
    - "Attribution flows from backend preset defaults through BasemapEntry to toMaplibreStyle() to MapLibre source"

key-files:
  created: []
  modified:
    - backend/app/persistent_config.py
    - frontend/src/api/settings.ts
    - frontend/src/lib/basemap-utils.ts
    - frontend/src/components/admin/settings/SettingsAppearanceTab.tsx
    - frontend/src/components/admin/AdminSidebar.tsx
    - frontend/src/pages/admin/AdminSettingsPage.tsx
    - frontend/src/App.tsx
    - frontend/src/components/builder/BuilderMap.tsx
    - frontend/src/components/dataset/DatasetMap.tsx
    - frontend/src/components/viewer/ViewerMap.tsx
    - frontend/src/components/search/BboxMapPicker.tsx
    - frontend/src/i18n/locales/en/admin.json
    - frontend/src/i18n/locales/es/admin.json
    - frontend/src/i18n/locales/fr/admin.json
    - frontend/src/i18n/locales/de/admin.json
    - frontend/src/components/admin/__tests__/AdminSidebar.test.tsx

key-decisions:
  - "SpatialFilterPanel.tsx does not exist in codebase -- skipped (plan referenced it but file was removed)"
  - "Attribution for GL style JSON basemaps handled natively by MapLibre -- no modification needed for .json URLs"

patterns-established: []

requirements-completed: [RPV-01]

duration: 4min
completed: 2026-03-25
---

# Quick Task 260325-rpv: Admin Map Settings -- Rename, Free Basemap, Attribution

**Renamed admin Appearance tab to Map, replaced Stamen Terrain with OpenFreeMap Bright, added basemap attribution field and re-enabled MapLibre AttributionControl on all maps**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-26T00:17:45Z
- **Completed:** 2026-03-26T00:22:08Z
- **Tasks:** 2
- **Files modified:** 16

## Accomplishments
- Renamed admin settings tab from "Appearance" to "Map" across backend, frontend, all 4 locale files, sidebar, routes
- Replaced Stamen Terrain preset (requires Stadia Maps API key) with OpenFreeMap Bright (free, no auth, no rate limits)
- Added attribution strings to all 4 preset basemaps in backend defaults
- Added optional `attribution` field to `BasemapEntry` interface and custom basemap add form
- Updated `toMaplibreStyle()` to pass attribution to raster source for XYZ basemaps
- Removed `attributionControl={false}` from all 4 map components (BuilderMap, DatasetMap, ViewerMap, BboxMapPicker)
- Added legacy redirect from `/admin/settings/appearance` to `/admin/settings/map`

## Task Commits

Each task was committed atomically:

1. **Task 1: Rename Appearance to Map + replace Stamen Terrain preset** - `2508bc68` (feat)
2. **Task 2: Add attribution field to BasemapEntry and re-enable AttributionControl** - `dadbec64` (feat)

## Files Created/Modified
- `backend/app/persistent_config.py` - tab="map", OpenFreeMap Bright preset, attribution strings on all presets
- `frontend/src/api/settings.ts` - Added optional attribution field to BasemapEntry
- `frontend/src/lib/basemap-utils.ts` - toMaplibreStyle() accepts optional attribution parameter
- `frontend/src/components/admin/settings/SettingsAppearanceTab.tsx` - Attribution input in custom basemap form
- `frontend/src/components/admin/AdminSidebar.tsx` - Map label with Globe icon at /admin/settings/map
- `frontend/src/pages/admin/AdminSettingsPage.tsx` - TAB_KEYS/LABELS/COMPONENTS use "map" key
- `frontend/src/App.tsx` - Redirects for old basemaps/map-defaults/appearance routes to /admin/settings/map
- `frontend/src/components/builder/BuilderMap.tsx` - Removed attributionControl={false}, pass attribution
- `frontend/src/components/dataset/DatasetMap.tsx` - Removed attributionControl={false}, pass attribution
- `frontend/src/components/viewer/ViewerMap.tsx` - Removed attributionControl={false}, pass attribution
- `frontend/src/components/search/BboxMapPicker.tsx` - Removed attributionControl={false}, pass attribution
- `frontend/src/i18n/locales/en/admin.json` - "map" tab key, attribution i18n keys, updated help text
- `frontend/src/i18n/locales/es/admin.json` - "Mapa" tab label
- `frontend/src/i18n/locales/fr/admin.json` - "Carte" tab label
- `frontend/src/i18n/locales/de/admin.json` - "Karte" tab label
- `frontend/src/components/admin/__tests__/AdminSidebar.test.tsx` - Updated mock and assertion for "Map"

## Decisions Made
- SpatialFilterPanel.tsx does not exist in the codebase -- skipped (plan referenced 5 map components but only 4 exist)
- GL style JSON basemaps (.json URLs) do not need explicit attribution -- MapLibre reads it from the style spec automatically

## Deviations from Plan

None - plan executed exactly as written (with the exception of SpatialFilterPanel.tsx not existing).

## Issues Encountered
None

## Known Stubs
None

## User Setup Required
None - no external service configuration required.

---
## Self-Check: PASSED

All 16 modified files verified present. Both task commits (2508bc68, dadbec64) verified in git log.

---
*Plan: 260325-rpv*
*Completed: 2026-03-25*
