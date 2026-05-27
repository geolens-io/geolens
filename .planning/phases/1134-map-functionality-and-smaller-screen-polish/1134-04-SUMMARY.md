---
phase: 1134-map-functionality-and-smaller-screen-polish
plan: "04"
subsystem: ui
tags: [builder, responsive, smaller-screen, maplibre, testing]

requires:
  - phase: 1133-audit-first-builder-walkthrough
    provides: BUILDER-WALKTHROUGH-AUDIT.md with MAP-07..MAP-20 findings

provides:
  - "mt-12 h-[calc(100%-3rem)] on both <800px SheetContent wrappers clears MapTitleBar (MAP-07)"
  - "max-h-[40vh] overflow-y-auto on ActiveFilterChips container prevents MeasurementWidget collision (MAP-20)"
  - "MapCoordReadout.test.tsx +2 MAP-08 tests: positive-form right-14/top-2/z-10 pin + RESP-02 docstring cross-context pin"
  - "MapBuilderPage.sheet-close-button.test.tsx +1 MAP-10 exhaustive SheetContent grep-guard via Vite ?raw import"
  - "ActiveFilterChips.test.tsx (NEW, 5 tests): MAP-20 class regression pin + render + callback + source-text guard"

affects:
  - 1134-05-PLAN
  - 1135-ai-staging
  - 1139-close-gate-smoke

tech-stack:
  added: []
  patterns:
    - "Vite ?raw import for source-text grep-guard tests (no node:fs / @types/node needed in tsconfig.app.json)"
    - "mt-12 h-[calc(100%-3rem)] as the standard <800px Sheet vertical-offset pattern below MapTitleBar"

key-files:
  created:
    - frontend/src/components/builder/__tests__/ActiveFilterChips.test.tsx
  modified:
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/components/builder/ActiveFilterChips.tsx
    - frontend/src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx
    - frontend/src/components/map/__tests__/MapCoordReadout.test.tsx

key-decisions:
  - "Used Vite ?raw import instead of node:fs for source-text grep-guard tests — avoids tsconfig.app.json node types dependency (same pattern as preserve-drawing-buffer.test.ts)"
  - "mt-12 on SheetContent (not on NavigationControl) per Pitfall #10 — sidebar-side fix, NavigationControl stays top-left"
  - "max-h-[40vh] chosen per UI-SPEC (≤800px height 600px → 40vh = 240px, well above bottom-left MeasurementWidget band)"

patterns-established:
  - "?raw-import grep-guard: use Vite ?raw import to read source text in tests rather than node:fs when tsconfig.app.json lacks node types"

requirements-completed:
  - MAP-07
  - MAP-08
  - MAP-09
  - MAP-10
  - MAP-20

duration: 12min
completed: 2026-05-27
---

# Phase 1134 Plan 04: Smaller-Screen Layout Collision Fixes Summary

**Five ≤800px layout-collision requirements closed via two className edits and three test extensions: mt-12 Sheet offset, max-h-[40vh] filter chips, and exhaustive grep-guard + positioning regression pins.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-05-27T12:29:00Z
- **Completed:** 2026-05-27T12:34:30Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- MAP-07: Added `mt-12 h-[calc(100%-3rem)]` to both `<800px SheetContent wrappers in MapBuilderPage.tsx, pushing each Sheet 48px below the MapTitleBar so it does not overlap the top-left NavigationControl at 800×600. NavigationControl stays `top-left` (Pitfall #10 honored).
- MAP-08: Extended MapCoordReadout.test.tsx with 2 new MAP-08 tests: positive-form `toHaveClass('right-14')` / `top-2` / `z-10` render assertion, and a source-text pin confirming the RESP-02 docstring references both BuilderMap and ViewerMap contexts.
- MAP-09: Cross-referenced in MapCoordReadout.test.tsx comment — covered by existing sheet-close-button.test.tsx Tests 1-7.
- MAP-10: Extended MapBuilderPage.sheet-close-button.test.tsx with an exhaustive grep-guard test (new describe block) that reads MapBuilderPage.tsx source via Vite `?raw` import and asserts every `<SheetContent` opening tag declares `showCloseButton={false}` (Pitfall #11 enforcement gate).
- MAP-20: Added `max-h-[40vh] overflow-y-auto` to ActiveFilterChips container div; created 5-test ActiveFilterChips.test.tsx pinning the classes, null-render, label/name render, callback, and source-text guard.

## Task Commits

1. **Task 1: MAP-07 sidebar offset + MAP-10 SheetContent grep guard** - `5a52148b` (feat)
2. **Task 2: MAP-08 MapCoordReadout regression + MAP-09 cross-ref** - `45e58381` (test)
3. **Task 3: MAP-20 ActiveFilterChips max-height + tests** - `81d48401` (feat)

## Source Changes (Before/After)

**MapBuilderPage.tsx — SheetContent className (line 1265):**
- Before: `className="w-full max-w-[380px] p-0 flex flex-col"`
- After: `className="mt-12 h-[calc(100%-3rem)] w-full max-w-[380px] p-0 flex flex-col"`

**MapBuilderPage.tsx — SheetContent className (line 1377):**
- Before: `className="w-[22rem] max-w-[calc(100vw-5rem)] p-0 flex flex-col"`
- After: `className="mt-12 h-[calc(100%-3rem)] w-[22rem] max-w-[calc(100vw-5rem)] p-0 flex flex-col"`

**ActiveFilterChips.tsx — chip container (line 124):**
- Before: `<div className="flex flex-wrap gap-1.5 pointer-events-none">`
- After: `<div className="flex flex-wrap gap-1.5 max-h-[40vh] overflow-y-auto pointer-events-none">`

## Files Created/Modified

- `frontend/src/pages/MapBuilderPage.tsx` — `mt-12 h-[calc(100%-3rem)]` on both SheetContent wrappers (MAP-07, MAP-10 contract preserved)
- `frontend/src/components/builder/ActiveFilterChips.tsx` — `max-h-[40vh] overflow-y-auto` on chip container (MAP-20)
- `frontend/src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx` — +1 MAP-10 describe block (exhaustive grep-guard via ?raw import)
- `frontend/src/components/map/__tests__/MapCoordReadout.test.tsx` — +2 MAP-08 tests (right-14 render pin + RESP-02 docstring source-text pin)
- `frontend/src/components/builder/__tests__/ActiveFilterChips.test.tsx` — NEW, 5 tests (MAP-20 class pin, null render, label, callback, source guard)

## Decisions Made

- Used Vite `?raw` import instead of `node:fs` for source-text grep-guard tests in both MAP-10 and MAP-20 test files. The tsconfig.app.json does not include `node` types; the `?raw` pattern avoids this dependency and is already established by `preserve-drawing-buffer.test.ts`.
- Applied the Sheet offset as `mt-12` on the SheetContent className (sidebar-side fix per UI-SPEC §Smaller-Screen ≤800px Contract). NavigationControl position was not changed (Pitfall #10 non-negotiable).
- Used `max-h-[40vh]` per UI-SPEC §Filter-Pill vs Measure-Widget Collision Avoidance: at 600px viewport height, 40vh = 240px, which keeps the chip column well above the bottom-left measurement widget band.

## Deviations from Plan

None — plan executed exactly as written, with one inline fix:

**[Rule 3 - Blocking] Replaced `node:fs` / `__dirname` with Vite `?raw` import in MAP-10 grep-guard test**
- **Found during:** Task 1 (typecheck after adding the test)
- **Issue:** `node:fs` import + `__dirname` caused TS2591/TS2304 errors because tsconfig.app.json lacks `node` types. The plan's example body used `node:fs` but the project has an established `?raw` pattern.
- **Fix:** Replaced the `fs.readFileSync(filePath)` approach with `import mapBuilderPageSrc from '../../../pages/MapBuilderPage.tsx?raw'`. Same test logic, no behavioral change.
- **Files modified:** `MapBuilderPage.sheet-close-button.test.tsx`
- **Verification:** typecheck 0, 9/9 tests pass.

## Issues Encountered

None.

## Next Phase Readiness

- MAP-07..10 + MAP-20 closed; Phase 1134 Plans 05 and 06 can proceed independently.
- Phase 1139 close-gate Playwright MCP smoke has stable smaller-screen layout contracts to verify against.
- Pitfall #10 (NavigationControl top-left) and Pitfall #11 (showCloseButton={false}) are now protected by automated tests.

---
*Phase: 1134-map-functionality-and-smaller-screen-polish*
*Completed: 2026-05-27*
