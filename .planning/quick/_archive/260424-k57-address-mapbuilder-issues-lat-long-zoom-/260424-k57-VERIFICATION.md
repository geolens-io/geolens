---
phase: 260424-k57
verified: 2026-04-24T14:56:30Z
status: gaps_found
score: 5/6 must-haves verified
overrides_applied: 0
gaps:
  - truth: "Selecting blank basemap renders transparent canvas with data layers only (no basemap tiles)"
    status: failed
    reason: "BuilderMap.tsx passes basemapStyle through findBasemapById() first; 'blank' is not in the API basemaps list so basemapEntry is undefined, causing toMaplibreStyle(fallbackUrl) to be called instead of toMaplibreStyle('blank'). The transparent StyleSpecification in basemap-utils.ts is unreachable from BuilderMap or ViewerMap."
    artifacts:
      - path: "frontend/src/components/builder/BuilderMap.tsx"
        issue: "Line 86: findBasemapById(basemaps, 'blank') returns undefined; line 89: toMaplibreStyle(fallbackUrl) called instead of toMaplibreStyle('blank')"
      - path: "frontend/src/components/viewer/ViewerMap.tsx"
        issue: "Line 169: same pattern — findBasemapById(basemaps, 'blank') returns undefined; line 171: toMaplibreStyle(fallbackUrl) called"
    missing:
      - "BuilderMap.tsx must special-case BLANK_BASEMAP_ID before calling findBasemapById: if (basemapStyle === BLANK_BASEMAP_ID) use toMaplibreStyle(BLANK_BASEMAP_ID) directly, bypassing findBasemapById lookup"
      - "ViewerMap.tsx needs the same guard for consistency (shared maps with blank basemap will also render positron)"
      - "Import BLANK_BASEMAP_ID in both BuilderMap.tsx and ViewerMap.tsx"
---

# Quick Task 260424-k57: Map Builder Issues Verification Report

**Task Goal:** Address mapbuilder issues: lat/long/zoom pill overlap attribution, legend tighter to bottom-left, blank basemap option, measurement widget broken
**Verified:** 2026-04-24T14:56:30Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Coordinate pill (lat/lng/zoom) visible at top-right, not overlapping attribution | ✓ VERIFIED | `MapCoordReadout.tsx:73` — `className="absolute top-2 right-2 z-10 pointer-events-none"` |
| 2 | Legend widget positioned tighter to bottom-left corner, clearing ScaleControl | ✓ VERIFIED | `WidgetHost.tsx:17` — `bottom-left` anchor is `absolute bottom-10 left-4 z-10 flex flex-col gap-2` (40px, down from 80px) |
| 3 | Blank/None basemap option appears as first item in basemap picker grid | ✓ VERIFIED | `BasemapPicker.tsx:20-21` — synthetic `blankEntry` prepended; `options = [blankEntry, ...enabled]`; grid maps over `options` |
| 4 | Selecting blank basemap renders transparent canvas with data layers only | ✗ FAILED | `BuilderMap.tsx:86,89` — `findBasemapById(basemaps, 'blank')` returns `undefined`; `toMaplibreStyle(fallbackUrl)` called with positron URL instead of `'blank'`. Transparent style in `basemap-utils.ts` is unreachable. |
| 5 | Measurement widget correctly places points without interference from feature popup handler | ✓ VERIFIED | `BuilderMap.tsx:251` — `if (measureActiveRef.current) return` at top of `handleClick`; store subscription at lines 135-139 |
| 6 | Measurement widget shows crosshair cursor while active | ✓ VERIFIED | `MeasurementWidget.tsx:110` — `map.getCanvas().style.cursor = 'crosshair'` on activation; `BuilderMap.tsx:287` — `if (measureActiveRef.current) return` in mousemove rAF prevents cursor override |

**Score:** 5/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/map/MapCoordReadout.tsx` | Top-right position (top-2 right-2) | ✓ VERIFIED | Line 73 confirms `top-2 right-2` |
| `frontend/src/lib/basemap-utils.ts` | BLANK_BASEMAP_ID + transparent toMaplibreStyle branch | ✓ VERIFIED | Line 10: `export const BLANK_BASEMAP_ID = 'blank'`; lines 62-75: transparent branch with `rgba(0,0,0,0)` background + glyphs URL |
| `frontend/src/components/builder/BasemapPicker.tsx` | Synthetic blank entry prepended to grid | ✓ VERIFIED | Line 5 imports `BLANK_BASEMAP_ID`; lines 20-21 prepend blankEntry; line 22 current lookup uses `options` (includes blank) |
| `frontend/src/components/builder/BuilderMap.tsx` | useWidgetStore import + measureActiveRef gating | ✓ VERIFIED | Line 2: `import { useWidgetStore }`; line 133: `measureActiveRef`; lines 135-139: subscribe; lines 251, 287: early returns |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `BuilderMap.tsx` | `map-widget-store.ts` | `useWidgetStore.subscribe` for measurement-active | ✓ WIRED | Lines 135-139: `useWidgetStore.subscribe((state) => { measureActiveRef.current = state.activeWidgets.has('measurement') })` |
| `BasemapPicker.tsx` | `basemap-utils.ts` | `BLANK_BASEMAP_ID` import for synthetic entry | ✓ WIRED | Line 5: `import { basemapThumbnail, BLANK_BASEMAP_ID } from '@/lib/basemap-utils'`; used at line 20 |
| `basemap-utils.ts` → `BuilderMap.tsx` | MapLibre StyleSpecification | `toMaplibreStyle('blank')` returns transparent style | ✗ NOT_WIRED | `BuilderMap.tsx:86` calls `findBasemapById(basemaps, 'blank')` first — returns `undefined` since API list excludes synthetic blank entry. `toMaplibreStyle` is then called with `fallbackUrl` (positron), never with `'blank'` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `BuilderMap.tsx` | `styleValue` (MapLibre style for blank) | `toMaplibreStyle(basemapEntry?.url ?? fallbackUrl)` | No — blank triggers positron fallback | ✗ HOLLOW — wired but data disconnected (blank case) |

### Behavioral Spot-Checks

Step 7b: SKIPPED — no runnable entry points testable without starting dev server. Tests exercised directly below.

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `toMaplibreStyle('blank')` returns transparent StyleSpecification | vitest run basemap-utils.test.ts | 31/31 pass | ✓ PASS |
| `basemapThumbnail('blank')` returns defined string | vitest run basemap-utils.test.ts | 31/31 pass | ✓ PASS |

### Requirements Coverage

No requirement IDs declared in PLAN frontmatter (`requirements: []`). N/A.

### Anti-Patterns Found

No TODO/FIXME/placeholder/stub patterns found in any of the 10 modified files. No empty implementations, no console-only handlers.

### Human Verification Required

None beyond the gap identified above — gap is programmatically verifiable.

### Gaps Summary

One gap prevents must-have #4 from being achieved. The transparent blank basemap `StyleSpecification` is correctly implemented in `basemap-utils.ts` and passes all unit tests. However, neither `BuilderMap.tsx` nor `ViewerMap.tsx` can reach that code path: both components call `findBasemapById(basemaps, basemapStyle)` before calling `toMaplibreStyle`. Since `basemaps` comes from the API and the blank entry is only synthetic (added locally in `BasemapPicker`), `findBasemapById` returns `undefined` for `'blank'`, causing the fallback to positron. Selecting "None" in the picker will display the positron basemap rather than a transparent canvas.

**Fix required in `BuilderMap.tsx` (and `ViewerMap.tsx` for shared-map consistency):**

```typescript
import { findBasemapById, toMaplibreStyle, BLANK_BASEMAP_ID } from '@/lib/basemap-utils';

// Replace line 86-91:
const isBlank = basemapStyle === BLANK_BASEMAP_ID;
const basemapEntry = isBlank ? undefined : findBasemapById(basemaps ?? [], basemapStyle);
const fallbackUrl = 'https://tiles.openfreemap.org/styles/positron';
const styleValue = useMemo(
  () => isBlank ? toMaplibreStyle(BLANK_BASEMAP_ID) : toMaplibreStyle(basemapEntry?.url ?? fallbackUrl, basemapEntry?.attribution),
  [isBlank, basemapEntry?.url, basemapEntry?.attribution],
);
```

Same pattern needed in `ViewerMap.tsx` lines 163-171.

---

_Verified: 2026-04-24T14:56:30Z_
_Verifier: Claude (gsd-verifier)_
