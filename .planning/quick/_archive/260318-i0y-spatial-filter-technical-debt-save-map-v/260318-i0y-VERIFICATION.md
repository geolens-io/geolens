---
phase: 260318-i0y
verified: 2026-03-18T17:30:00Z
status: gaps_found
score: 4/5 must-haves verified
gaps:
  - truth: "Drawing a polygon sends actual GeoJSON geometry to backend, not just its bbox"
    status: partial
    reason: "Geometry is cleared in only 1 of 3 bbox-clear locations in FilterPanel.tsx. When bbox is cleared via the mobile filter chip (line 304) or the 'Clear location' button inside the sheet (line 752), geometry stays in the store and continues to be sent to the backend."
    artifacts:
      - path: "frontend/src/components/search/FilterPanel.tsx"
        issue: "Lines 302-306 and 749-754 clear bbox and spatial_predicate but not geometry; only line 218-221 clears all three"
    missing:
      - "Add `store.setFilter('geometry', '');` to the onRemove handler at line 304 (mobile filter chip)"
      - "Add `store.setFilter('geometry', '');` to the onClick at line 752 (Clear location button in sheet)"
---

# Quick Task 260318-i0y: Spatial Filter Technical Debt Verification

**Task Goal:** Spatial filter technical debt: (1) Save map viewport across open/close using module-level variable, restore on map load. (2) Backend arbitrary geometry support — accept `geometry` GeoJSON param, use ST_GeomFromGeoJSON at all 3 spatial filter locations, geometry takes precedence over bbox. (3) Frontend sends actual polygon GeoJSON instead of extracting bbox, rectangles still use bbox. (4) Remove dashed bbox overlay since polygon precision is no longer misleading.

**Verified:** 2026-03-18T17:30:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth                                                               | Status      | Evidence                                                                          |
|----|---------------------------------------------------------------------|-------------|-----------------------------------------------------------------------------------|
| 1  | Panel map restores previous viewport (center + zoom) when reopened | VERIFIED    | `let savedViewport = { longitude: 0, latitude: 20, zoom: 1 }` at module scope (line 23); `initialViewState={savedViewport}` (line 327); `onMoveEnd` writes to it (lines 331-334) |
| 2  | Drawing a polygon sends actual GeoJSON geometry to backend         | PARTIAL     | handleApply extracts geometry correctly; FilterPanel wires it at onApply. BUT clearing bbox at lines 304 and 752 does NOT clear geometry — stale geometry leaks to backend |
| 3  | Drawing a rectangle still sends bbox (no geometry param)           | VERIFIED    | `geom` only set when `drawMode === 'polygon'`; rectangle path passes `undefined` as third arg, storing `''` in geometry field |
| 4  | Backend filters using ST_GeomFromGeoJSON when geometry param provided | VERIFIED | All 3 service.py locations updated (lines 258-261, 383-386, 652-655); geometry takes precedence over bbox in all router parse paths |
| 5  | Dashed bbox overlay is removed for polygon mode                    | VERIFIED    | No `bbox-indicator` or `dashed` patterns in SpatialFilterPanel.tsx                |

**Score:** 4/5 truths verified (Truth 2 is partial — core path works but stale-geometry bug on clear)

### Required Artifacts

| Artifact                                            | Expected                                 | Status   | Details                                                              |
|-----------------------------------------------------|------------------------------------------|----------|----------------------------------------------------------------------|
| `backend/app/search/service.py`                     | ST_GeomFromGeoJSON spatial filtering     | VERIFIED | `geometry_geojson` param added; all 3 spatial filter blocks updated  |
| `backend/app/search/router.py`                      | geometry query parameter parsing         | VERIFIED | `geometry: str | None` in all 4 endpoints; parse + validate in `_handle_search` and `search_facets_endpoint` |
| `frontend/src/stores/search-store.ts`               | geometry field in search state           | VERIFIED | `geometry: string` in interface + initialState; serialized in toParams/restoreParams |
| `frontend/src/components/search/SpatialFilterPanel.tsx` | Viewport persistence via module-level var, polygon GeoJSON extraction | VERIFIED | `savedViewport` module var; `onApply` signature takes optional `GeoJSON.Geometry`; handleApply extracts from TerraDraw snapshot |

### Key Link Verification

| From                          | To                                          | Via                                            | Status      | Details                                                          |
|-------------------------------|---------------------------------------------|------------------------------------------------|-------------|------------------------------------------------------------------|
| SpatialFilterPanel.tsx        | search-store.ts                             | onApply callback passes geometry GeoJSON       | VERIFIED    | FilterPanel line 890-895: `store.setFilter('geometry', geometry ? JSON.stringify(geometry) : '')` |
| search-store.ts               | backend/app/search/router.py                | toParams serializes geometry as query param    | VERIFIED    | line 77: `if (state.geometry) params.geometry = state.geometry`  |
| backend/app/search/router.py  | backend/app/search/service.py               | parsed geometry passed to search functions     | VERIFIED    | `geometry_geojson=geometry_geojson` passed at call sites (lines 194, 466) |

### Anti-Patterns Found

| File                                    | Line     | Pattern                                 | Severity | Impact                                                                                        |
|-----------------------------------------|----------|-----------------------------------------|----------|-----------------------------------------------------------------------------------------------|
| `frontend/src/components/search/FilterPanel.tsx` | 302-306 | bbox cleared without clearing geometry | Blocker  | Mobile "Area selected" chip remove leaves stale geometry in store; backend receives old polygon |
| `frontend/src/components/search/FilterPanel.tsx` | 749-754 | bbox cleared without clearing geometry | Blocker  | "Clear location" button in sheet leaves stale geometry; backend receives old polygon on next search |

### Human Verification Required

None — the gap is verifiable programmatically and clearly structural.

### Gaps Summary

The core implementation is correct: viewport persistence works via a module-level variable, polygon draws extract TerraDraw GeoJSON and pass it through, rectangle draws omit geometry, the backend handles ST_GeomFromGeoJSON at all 3 service locations, and the dashed overlay is gone.

One bug was introduced by incomplete application of the "clear geometry alongside bbox" requirement. The plan called for clearing geometry at 3 locations, but only 1 of 3 clear-bbox paths was updated (line 220). The other two paths — the mobile filter chip onRemove (line 304) and the "Clear location" button in the sheet panel (line 752) — clear `bbox` and `spatial_predicate` but leave `geometry` populated. After clearing via those paths, the next search will still send the old polygon GeoJSON to the backend, returning filtered results despite the user having cleared the spatial filter.

Fix: add `store.setFilter('geometry', '');` immediately after `store.setFilter('bbox', '');` at both lines 304 and 752.

---

_Verified: 2026-03-18T17:30:00Z_
_Verifier: Claude (gsd-verifier)_
