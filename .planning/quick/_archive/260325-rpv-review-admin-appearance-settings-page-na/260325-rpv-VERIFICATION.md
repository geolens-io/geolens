---
phase: 260325-rpv
verified: 2026-03-25T20:28:00Z
status: gaps_found
score: 5/6 must-haves verified
gaps:
  - truth: "All maps display basemap attribution text via MapLibre AttributionControl"
    status: failed
    reason: "SpatialFilterPanel.tsx still has attributionControl={false} and does not pass attribution to toMaplibreStyle(). The summary and key-decisions claimed this file 'does not exist in codebase' but the file exists at frontend/src/components/search/SpatialFilterPanel.tsx."
    artifacts:
      - path: "frontend/src/components/search/SpatialFilterPanel.tsx"
        issue: "attributionControl={false} on line 331; toMaplibreStyle() called at lines 97-102 without attribution argument"
    missing:
      - "Remove attributionControl={false} from the MapGL component at line 331"
      - "Pass themeBasemap.attribution to toMaplibreStyle() at line 97 (mirror the pattern in BboxMapPicker.tsx line 27)"
---

# Quick Task 260325-rpv: Admin Map Settings Verification

**Task Goal:** Rename "Appearance" tab to "Map", replace Stamen Terrain preset with OpenFreeMap Bright, add basemap attribution field + re-enable MapLibre AttributionControl.
**Verified:** 2026-03-25T20:28:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | Admin sidebar shows "Map" instead of "Appearance" for the basemap/map-defaults settings page | VERIFIED | `AdminSidebar.tsx` line 59: `labelKey: 'admin:settings.tabs.map', to: '/admin/settings/map', icon: Globe`; test passes |
| 2  | Stamen Terrain preset is replaced with OpenFreeMap Bright in backend defaults | VERIFIED | `persistent_config.py` lines 456-462: `openfreemap-bright` entry present; no stamen references in backend |
| 3  | All maps display basemap attribution text via MapLibre AttributionControl | FAILED | `SpatialFilterPanel.tsx:331` still has `attributionControl={false}`; 4/5 map components fixed, 1 missed |
| 4  | BasemapEntry type includes an attribution field populated for all presets | VERIFIED | `api/settings.ts` line 11: `attribution?: string`; all 4 presets have attribution strings in `persistent_config.py` |
| 5  | Custom basemap form includes an optional Attribution text input | VERIFIED | `SettingsAppearanceTab.tsx` lines 172-181: Attribution Input with label, placeholder, help text; `handleAdd()` includes attribution in entry |
| 6  | Custom basemap URL help text mentions GL style JSON support | VERIFIED | `en/admin.json` line 445: `"customDescription": "Add custom XYZ/TMS tile URLs or MapLibre GL style JSON URLs."` |

**Score:** 5/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/admin/settings/SettingsAppearanceTab.tsx` | Map settings tab with attribution field in custom basemap form | VERIFIED | Attribution input with state, handler, reset, i18n keys at lines 53, 83, 88, 172-181 |
| `backend/app/persistent_config.py` | Updated preset basemaps with OpenFreeMap Bright and attribution strings | VERIFIED | All 4 presets have attribution; OpenFreeMap Bright replaces Stamen; `tab="map"` on both BASEMAPS and MAP_DEFAULTS |
| `frontend/src/api/settings.ts` | BasemapEntry interface with optional attribution field | VERIFIED | Line 11: `attribution?: string` present |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `backend/app/persistent_config.py` | `frontend/src/api/settings.ts` | BasemapEntry shape with attribution field | VERIFIED | Both define `attribution`; backend has strings in presets; frontend interface accepts them |
| `frontend/src/api/settings.ts` | `frontend/src/lib/basemap-utils.ts` | BasemapEntry type import | VERIFIED | `basemap-utils.ts` line 2: `import type { BasemapEntry } from '@/api/settings'` |
| `frontend/src/lib/basemap-utils.ts` | BuilderMap/DatasetMap/ViewerMap | toMaplibreStyle consumed by map components | VERIFIED | All three call `toMaplibreStyle(url, basemap.attribution)` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `SpatialFilterPanel.tsx` | `basemapStyle` | `toMaplibreStyle(themeBasemap.url)` (no attribution) | No — attribution dropped at call site | HOLLOW_PROP |
| `BboxMapPicker.tsx` | `basemapStyle` | `toMaplibreStyle(themeBasemap.url, themeBasemap.attribution)` | Yes | FLOWING |
| `BuilderMap.tsx` | `mapStyle` | `toMaplibreStyle(basemapEntry?.url, basemapEntry?.attribution)` line 53 | Yes | FLOWING |
| `DatasetMap.tsx` | `basemapStyle` | `toMaplibreStyle(themeBasemap.url, themeBasemap.attribution)` lines 88-89 | Yes | FLOWING |
| `ViewerMap.tsx` | `styleValue` | `toMaplibreStyle(url, effectiveBasemap?.attribution)` lines 113, 513 | Yes | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| AdminSidebar renders "Map" with correct route | `npx vitest run src/components/admin/__tests__/AdminSidebar.test.tsx` | 6/6 tests passed | PASS |
| TypeScript compiles cleanly | `npx tsc --noEmit` | No output (no errors) | PASS |
| No stamen references in backend defaults | `grep -r "stamen\|Stamen" backend/app/persistent_config.py` | No matches | PASS |
| No legacy `tab="appearance"` in backend | `grep tab="appearance" backend/app/persistent_config.py` | No matches | PASS |
| attributionControl={false} still present | `grep -r "attributionControl" frontend/src` | Match in SpatialFilterPanel.tsx:331 | FAIL |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| RPV-01 | 260325-rpv-PLAN.md | Review admin appearance settings page — rename, replace Stamen preset, attribution support | PARTIAL | 5/6 success criteria met; SpatialFilterPanel.tsx attribution not fixed |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `frontend/src/components/search/SpatialFilterPanel.tsx` | 331 | `attributionControl={false}` | Blocker | AttributionControl is suppressed on the Spatial Filter Panel map; OSM/provider attribution is not displayed to users of that panel, violating OSM terms of service |
| `frontend/src/components/search/SpatialFilterPanel.tsx` | 97 | `toMaplibreStyle(themeBasemap.url)` — attribution argument omitted | Warning | Even after removing `attributionControl={false}`, the raster source won't carry the attribution string for XYZ basemaps unless attribution is passed |

### Human Verification Required

None — all checks are automatable for this task.

### Gaps Summary

One gap blocks full goal achievement: **SpatialFilterPanel.tsx was not updated**.

The task summary and key-decisions documented that "SpatialFilterPanel.tsx does not exist in the codebase — skipped", but the file exists at `/Users/ishiland/Code/geolens/frontend/src/components/search/SpatialFilterPanel.tsx`. This was a false negative: the agent either checked the wrong path or resolved a wrong import. The file still carries `attributionControl={false}` on line 331 and does not pass `themeBasemap.attribution` to `toMaplibreStyle()`.

The fix is small (2 lines):
1. Remove `attributionControl={false}` from the `<MapGL>` component at line 331.
2. Change `toMaplibreStyle(themeBasemap.url)` at line 97 to `toMaplibreStyle(themeBasemap.url, themeBasemap.attribution)` (matching the pattern already used in `BboxMapPicker.tsx`).

All other success criteria are fully met. Backend presets are correct, BasemapEntry type is correct, 4 of 5 map components are fixed, all i18n keys are present, routing is correct, and TypeScript compiles cleanly.

---
_Verified: 2026-03-25T20:28:00Z_
_Verifier: Claude (gsd-verifier)_
