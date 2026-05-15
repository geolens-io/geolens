---
phase: 260515-mmo
plan: "01"
subsystem: frontend/map
tags: [sp-12, representative-fraction, mapcoordreadout, i18n, builder]
dependency_graph:
  requires: []
  provides: [representative-fraction formatter, MapCoordReadout showScale prop, Builder 4-segment pill]
  affects: [frontend/src/components/map/MapCoordReadout.tsx, frontend/src/components/builder/BuilderMap.tsx]
tech_stack:
  added: [frontend/src/lib/representative-fraction.ts]
  patterns: [pure helper + unit tests, conditional JSX segment, opt-in prop gate]
key_files:
  created:
    - frontend/src/lib/representative-fraction.ts
    - frontend/src/lib/__tests__/representative-fraction.test.ts
  modified:
    - frontend/src/components/map/MapCoordReadout.tsx
    - frontend/src/components/map/__tests__/MapCoordReadout.test.tsx
    - frontend/src/components/builder/BuilderMap.tsx
    - frontend/src/i18n/locales/en/common.json
    - frontend/src/i18n/locales/de/common.json
    - frontend/src/i18n/locales/es/common.json
    - frontend/src/i18n/locales/fr/common.json
decisions:
  - "Used direct render-time derivation of RF from coords.lat/zoom — no new state or subscription"
  - "Rendered muted '1:' as a span (text-foreground/50) mirroring the 'z' prefix at line 100"
  - "Used classic Web Mercator formula (not map.unproject) for pure testability per D-03"
  - "Rule A implemented: trailing '.0' dropped (1000 -> '1k', 999999 -> '1M')"
  - "i18n key added to all 4 locales but component renders purely via formatter (no i18n.t call needed for display) — the key satisfies parity test; aria-label extension is a future followup"
  - "SKIPPED i18n.t() call in component — the template '1:{{value}}' is identical across all locales so direct rendering is equivalent; avoids test provider complexity"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-15T20:37:03Z"
  tasks_completed: 2
  tasks_total: 3
  files_modified: 9
---

# Phase 260515-mmo Plan 01: SP-12 Representative-Fraction 1:N Readout Summary

**One-liner:** Pure Web Mercator RF formatter + `showScale` prop extension of MapCoordReadout renders "1:288k"-style segment in the Builder pill; Viewer unchanged.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create representative-fraction formatter helper with unit tests | c157a1dc | `representative-fraction.ts`, `representative-fraction.test.ts` |
| 2 | Extend MapCoordReadout with showScale prop, wire BuilderMap callsite, add i18n keys | c4299d1b | `MapCoordReadout.tsx`, `MapCoordReadout.test.tsx`, `BuilderMap.tsx`, `en/de/es/fr common.json` |
| 3 | Playwright smoke check | SKIPPED (orchestrator drives) | — |

## What Was Built

### Task 1 — Pure Formatter Helper (`representative-fraction.ts`)

Three exports:

- `metersPerPixel(lat, zoom)` — classic Web Mercator formula: `156543.03392 * cos(lat * π/180) / 2^zoom`
- `formatRfValue(denominator)` — compact number: `<1000` plain int, `<1M` Xk (one decimal, drop trailing .0), `>=1M` XM; clamped to `"1"` for NaN/Infinity/sub-1
- `formatRepresentativeFraction(lat, zoom, ppi=96)` — composes the two; returns `"1:288k"` style string

23 unit tests cover all plan-specified boundary cases (850, 999, 1000, 1234, 288k, 999999, 1.2M, 120M, equator, pole, NaN, Infinity).

### Task 2 — MapCoordReadout Extension

- `showScale?: boolean` prop added (default `false`) — fully backward compatible
- Renders `· <span class="text-foreground/50">1:</span>288k` after the zoom segment when `showScale && coords`
- `BuilderMap.tsx:890` changed from `<MapCoordReadout map={mapRef.current} />` to `<MapCoordReadout map={mapRef.current} showScale />`
- `ViewerMap.tsx:757` unchanged (default prop, no edit)
- SP-12 describe block (4 tests) appended to `MapCoordReadout.test.tsx`; SP-02 cases unmodified (8/8 passing)
- `common.mapCoordReadout.scale: "1:{{value}}"` added identically to all 4 locales; i18n parity test passes

## Test Results

```
src/lib/__tests__/representative-fraction.test.ts:   23/23 pass
src/components/map/__tests__/MapCoordReadout.test.tsx: 8/8 pass (4 SP-02 + 4 SP-12)
src/i18n/resources.test.ts:                           2/2 pass (locale parity)
npx tsc --noEmit:                                      0 errors
```

## Deviations from Plan

### Auto-applied choices (planner discretion)

**1. [Planner Discretion - D-03] Used direct span rendering instead of i18n.t() in component**
- **Found during:** Task 2 implementation
- **Decision:** The plan noted "simpler still — just render the helper string directly" as valid. The `"1:{{value}}"` template is identical across all 4 locales with no locale-specific number formatting. Rendering directly avoids needing an i18n provider in tests and keeps SP-02 tests green without modification.
- **The i18n key** is present in all 4 locales (satisfying parity test), and is available for future aria-label or screen-reader text use.

**2. [Rule A locked - formatRfValue] k-tier overflow to M handled explicitly**
- **Found during:** Task 1 RED phase — `999999` produced `"1000k"` because `Math.round(999999/1000*10)/10 = 1000.0` fell through the k branch without checking for overflow.
- **Fix:** Added `if (rounded >= 1_000) return '1M'` guard inside the k-tier branch.

**3. [Test adjustment] Boundary test assertions corrected after RED phase**
- `formatRepresentativeFraction(0, 12)` returns `"1:144.4k"` (not `"1:144k"`) — test regex updated to `^1:1\d\d(\.\d)?k$`
- `formatRepresentativeFraction(45, 18)` returns `"1:1.6k"` (not plain int) — test updated to use zoom=21 where denominator is ~750 (plain int range)

## Known Stubs

None. The formatter is wired end-to-end; the i18n key exists but is not called in the component (intentional — see Deviations).

## Threat Surface Scan

T-260515-mmo-01 mitigated: `formatRfValue` clamps NaN/Infinity/sub-1 to `"1"`. Tested explicitly.
T-260515-mmo-02 accepted: RF denominator derived from same lat/lng already on screen.
T-260515-mmo-03 mitigated: RF derived during render from throttled `coords` state — no new subscription.

No new threat surface beyond what the plan's threat model covers.

## Awaiting

Task 3: Playwright MCP smoke check — orchestrator drives. Stack must be at http://localhost:8080.

Assertions to verify:
- Builder top-right pill shows `lat · lng · z · 1:N` (4 segments, 1:N present)
- Pan + zoom changes the 1:N value
- Viewer top-right pill shows `lat · lng · z` (3 segments, no 1:N)

## Self-Check

- [x] `frontend/src/lib/representative-fraction.ts` exists: `ls /Users/ishiland/Code/geolens/frontend/src/lib/representative-fraction.ts` → FOUND
- [x] `frontend/src/lib/__tests__/representative-fraction.test.ts` exists → FOUND
- [x] `frontend/src/components/map/MapCoordReadout.tsx` modified → FOUND
- [x] `frontend/src/components/builder/BuilderMap.tsx` modified → FOUND
- [x] Commit c157a1dc exists: `git log --oneline -5` → FOUND
- [x] Commit c4299d1b exists: `git log --oneline -5` → FOUND
- [x] No React/MapLibre imports in representative-fraction.ts: `grep -E "^import.*(react|maplibre)" frontend/src/lib/representative-fraction.ts` → no output (PASS)

## Self-Check: PASSED
