---
phase: 260326-a07
verified: 2026-03-26T07:31:00Z
status: gaps_found
score: 4/5 must-haves verified
re_verification: false
gaps:
  - truth: "Default basemaps use only providers with MIT/open-source compatible licensing"
    status: failed
    reason: "Backend attribution strings for openfreemap-positron and openfreemap-dark still link to carto.com, implying CARTO provenance for tiles served by OpenFreeMap. This is factually wrong and directly contradicts the licensing goal."
    artifacts:
      - path: "backend/app/persistent_config.py"
        issue: "Lines 437 and 445: attribution reads '&copy; <a href='https://carto.com/'>CARTO</a>...' for openfreemap-positron and openfreemap-dark. Should be '&copy; <a href='https://openfreemap.org'>OpenFreeMap</a>, &copy; <a href='https://openmaptiles.org/'>OpenMapTiles</a>, &copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors' per the plan spec."
    missing:
      - "Fix attribution for openfreemap-positron: replace carto.com link with openfreemap.org + openmaptiles.org links"
      - "Fix attribution for openfreemap-dark: same correction"
---

# Quick Task 260326-a07: Bundle Default Basemaps Verification Report

**Task Goal:** Bundle default basemaps for public release with licensing review. Replace CARTO basemaps with OpenFreeMap equivalents, update frontend preset IDs and legacy key map, keep OSM as option.
**Verified:** 2026-03-26T07:31:00Z
**Status:** gaps_found — 1 gap blocking full goal achievement
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | Default basemaps use only providers with MIT/open-source compatible licensing | ✗ FAILED | `openfreemap-positron` and `openfreemap-dark` attribution strings still link to `carto.com` (lines 437, 445 in persistent_config.py). Plan specified OpenFreeMap/OpenMapTiles attribution. |
| 2 | CARTO tile URLs are removed from defaults (ToS restricts to enterprise customers) | ✓ VERIFIED | No `cartocdn` or CARTO tile URLs in backend defaults. Both entries use `tiles.openfreemap.org`. |
| 3 | Legacy basemap IDs (carto-positron, carto-dark-matter, positron, dark-matter, voyager) resolve to OpenFreeMap equivalents | ✓ VERIFIED | `LEGACY_KEY_MAP` in basemap-utils.ts maps all 5 keys. Tests confirm all resolve correctly. |
| 4 | Theme-aware basemap switching works with new OpenFreeMap preset IDs | ✓ VERIFIED | `LIGHT_PRESET_ID = 'openfreemap-positron'`, `DARK_PRESET_ID = 'openfreemap-dark'`. `getThemeBasemap` uses these. Tests pass. Backend IDs match. |
| 5 | OpenStreetMap raster remains as a default option | ✓ VERIFIED | `openstreetmap` entry present in `_DEFAULT_BASEMAPS` (third position), unchanged. |

**Score:** 4/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/persistent_config.py` | Default basemap config with OpenFreeMap replacements | ✗ PARTIAL | IDs and URLs correct. Attribution for positron and dark incorrectly credits `carto.com` instead of OpenFreeMap/OpenMapTiles. |
| `frontend/src/lib/basemap-utils.ts` | Updated preset IDs and legacy key mapping | ✓ VERIFIED | `LIGHT_PRESET_ID = 'openfreemap-positron'`, `DARK_PRESET_ID = 'openfreemap-dark'`, `LEGACY_KEY_MAP` has all 5 keys. `toMaplibreStyle` handles `/styles/` URLs. |
| `frontend/src/lib/__tests__/basemap-utils.test.ts` | Updated tests for new basemap IDs and legacy mappings | ✓ VERIFIED | 26 tests all pass. Covers resolveBasemapId (7 cases), getThemeBasemap (5), findBasemapById (5), toMaplibreStyle (6), preset IDs (2) + extras. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `frontend/src/lib/basemap-utils.ts` | `backend/app/persistent_config.py` | LIGHT_PRESET_ID and DARK_PRESET_ID must match backend default basemap IDs | ✓ WIRED | Frontend `openfreemap-positron` and `openfreemap-dark` exactly match backend `_DEFAULT_BASEMAPS` IDs. |
| `frontend/src/lib/basemap-utils.ts` | Saved maps with old CARTO IDs | LEGACY_KEY_MAP resolves old IDs to new ones | ✓ WIRED | `carto-positron` → `openfreemap-positron` and `carto-dark-matter` → `openfreemap-dark` present in LEGACY_KEY_MAP and tested. |

### Data-Flow Trace (Level 4)

Not applicable — this task modifies configuration constants and utility functions, not dynamic data-rendering components.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All 26 basemap-utils tests pass | `npx vitest run src/lib/__tests__/basemap-utils.test.ts` | 26 passed, 0 failed | ✓ PASS |
| Zero CARTO tile URLs in backend defaults | `grep -c "cartocdn\|carto-positron\|carto-dark-matter" backend/app/persistent_config.py` | 0 | ✓ PASS |
| No CARTO CDN fallbacks in map components | `grep -rn "cartocdn" frontend/src/components/` | 0 matches | ✓ PASS |
| Incorrect CARTO attribution still present | `grep -n "carto.com" backend/app/persistent_config.py` | Lines 437, 445 | ✗ FAIL |

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|------------|-------------|--------|---------|
| BASEMAP-01 | Replace CARTO defaults with OpenFreeMap in backend | ✗ PARTIAL | IDs/URLs replaced; attribution strings still reference carto.com |
| BASEMAP-02 | Update frontend preset IDs and legacy key mapping | ✓ SATISFIED | LIGHT_PRESET_ID, DARK_PRESET_ID, LEGACY_KEY_MAP all updated |
| BASEMAP-03 | Tests updated for new IDs and legacy mappings | ✓ SATISFIED | 26 tests all pass |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/app/persistent_config.py` | 437 | Attribution links to `carto.com` for OpenFreeMap Positron entry | ✗ Blocker | Public release attribution misrepresents tile source; the task goal was explicitly to remove CARTO provenance for licensing reasons |
| `backend/app/persistent_config.py` | 445 | Attribution links to `carto.com` for OpenFreeMap Dark entry | ✗ Blocker | Same issue — incorrect attribution for OpenFreeMap-served tiles |

### Human Verification Required

None — all required checks are automated.

### Gaps Summary

One gap blocks the licensing goal. The task's primary purpose was to remove CARTO provenance from defaults for public release. While tile URLs and IDs were correctly updated, the attribution strings for `openfreemap-positron` and `openfreemap-dark` still read:

```
&copy; <a href='https://carto.com/'>CARTO</a>, &copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors
```

The plan explicitly specified this should be:

```
&copy; <a href='https://openfreemap.org'>OpenFreeMap</a>, &copy; <a href='https://openmaptiles.org/'>OpenMapTiles</a>, &copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors
```

Note that `openfreemap-bright` (added previously) has the correct attribution — so this is a copy/paste omission for the two newly replaced entries. The fix is a two-line edit in `backend/app/persistent_config.py`.

---

_Verified: 2026-03-26T07:31:00Z_
_Verifier: Claude (gsd-verifier)_
