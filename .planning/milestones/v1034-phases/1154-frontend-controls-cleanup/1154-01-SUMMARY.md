---
phase: 1154-frontend-controls-cleanup
plan: 01
subsystem: ui
tags: [raster, maplibre, titiler, vitest, tdd, url-builder]

# Dependency graph
requires:
  - phase: 1153-backend-raster-stretch
    provides: pmin/pmax/sigma query params accepted by the raster tile route
provides:
  - buildColormapTileUrl forwards _pmin/_pmax/_sigma from builder paint dict to tile URL (non-default only)
affects:
  - 1154-02 (RasterEditor controls write _pmin/_pmax/_sigma via onPaintProp — this plan is the URL contract they wire to)
  - 1155 (Playwright MCP live verification of stretch controls)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Only-forward-non-default discipline for URL params (STRETCH_PMIN_DEFAULT=2, STRETCH_PMAX_DEFAULT=98, STRETCH_SIGMA_DEFAULT=2)"
    - "TDD RED/GREEN cycle: failing tests committed first, then implementation"

key-files:
  created: []
  modified:
    - frontend/src/components/builder/layer-adapters/raster-adapter.ts
    - frontend/src/components/builder/layer-adapters/__tests__/raster-adapter.test.ts

key-decisions:
  - "Append pmin/pmax/sigma AFTER stretch in URLSearchParams to preserve existing insertion-order assertions"
  - "Each bound param forwarded independently — pmin can be non-default while pmax is omitted"
  - "Cross-mode isolation enforced: pmin/pmax silenced when stretch !== 'percentile'; sigma silenced when stretch !== 'stddev'"
  - "Do NOT add _pmin/_pmax/_sigma to RASTER_OWNED_PAINT_PROPERTIES (Pitfall 6 — builder-private URL keys)"
  - "No client-side range validation here; Plan 02 RasterEditor validates, backend 422s as defense in depth"

patterns-established:
  - "Module-scope DEFAULT constants (STRETCH_PMIN_DEFAULT etc.) as named consts rather than inline literals — easier to diff against backend defaults"

requirements-completed:
  - RASTER-STRETCH-UI-01

# Metrics
duration: 2min
completed: 2026-05-30
---

# Phase 1154 Plan 01: buildColormapTileUrl pmin/pmax/sigma non-default forwarding

**`buildColormapTileUrl` now appends `pmin`/`pmax` for non-default percentile bounds and `sigma` for non-default stddev to the raster tile URL, with exact-string byte-identical default-case behavior proven by test**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-30T00:06:56Z
- **Completed:** 2026-05-30T00:08:43Z
- **Tasks:** 2 (TDD: RED commit + GREEN implementation commit)
- **Files modified:** 2

## Accomplishments
- Added `STRETCH_PMIN_DEFAULT=2`, `STRETCH_PMAX_DEFAULT=98`, `STRETCH_SIGMA_DEFAULT=2` constants at module scope
- Percentile branch: appends `pmin`/`pmax` after `stretch` only when value is finite and differs from its default; each forwarded independently
- Stddev branch: appends `sigma` only when value is finite and differs from default (2)
- Cross-mode isolation: pmin/pmax never emitted when stretch !== 'percentile'; sigma never emitted when stretch !== 'stddev'
- 8 new vitest cases covering all forwarding rules + default-unchanged invariant; all 29 tests pass; typecheck exits 0
- `RASTER_OWNED_PAINT_PROPERTIES` left unchanged (Pitfall 6)

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Failing tests for pmin/pmax/sigma forwarding** - `16327739` (test)
2. **Task 2 (GREEN): Implementation in buildColormapTileUrl** - `0f824459` (feat)

_TDD cycle: RED test commit first, then GREEN implementation._

## Files Created/Modified
- `frontend/src/components/builder/layer-adapters/raster-adapter.ts` - Added DEFAULT constants + percentile/stddev bound-forwarding branches; updated doc comment
- `frontend/src/components/builder/layer-adapters/__tests__/raster-adapter.test.ts` - 8 new test cases for non-default forwarding, cross-mode isolation, and byte-identical default invariant

## Decisions Made
- Append bound params AFTER stretch to keep existing URLSearchParams insertion-order assertions stable (no existing test required changes)
- Module-scope named constants for defaults rather than inline literals — makes the contract legible and easy to sync against backend defaults

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- URL contract for `_pmin`/`_pmax`/`_sigma` is locked and tested; Plan 02 (RasterEditor controls) can write these keys via `onPaintProp` against a stable, verified contract
- No blockers

---
*Phase: 1154-frontend-controls-cleanup*
*Completed: 2026-05-30*

## Self-Check: PASSED
- `frontend/src/components/builder/layer-adapters/raster-adapter.ts` — exists, contains `_pmin`
- `frontend/src/components/builder/layer-adapters/__tests__/raster-adapter.test.ts` — exists, contains `pmin`
- Commit `16327739` — present in git log
- Commit `0f824459` — present in git log
