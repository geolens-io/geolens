---
phase: 1050-builder-smoke-carryover
plan: 05
subsystem: ui
tags: [maplibre, react, sf-08, basemap, toast-suppression]

requires:
  - phase: 1049-mcp-smoke-verification
    provides: SF-08 root cause (false-positive Basemap connection issue toast on save when basemap had loaded successfully)
provides:
  - basemapLoadedAtRef latch in BuilderMap.tsx that suppresses transient 5xx tile-error toasts after the basemap style has successfully loaded
  - first-load failure path preserved (latch only set after fetch.then success branch)
  - basemap-change resets the latch so a new basemap's first-load failure surfaces correctly
affects: [v1010.2 CTRL-01 close gate, future builder polish]

tech-stack:
  added: []
  patterns:
    - "useRef-based latch pattern for cross-effect transient-error suppression (mirrors errorHandlerRef shape in same file)"

key-files:
  created:
    - .planning/phases/1050-builder-smoke-carryover/1050-05-SUMMARY.md
  modified:
    - frontend/src/components/builder/BuilderMap.tsx
    - frontend/src/components/builder/__tests__/BuilderMap.a11y.test.tsx

key-decisions:
  - "Latch reset at the START of the style-fetch effect (line 149) so basemap CHANGE re-arms first-load failure detection"
  - "Latch set only in the .then success branch (line 161) — the .catch path's setBasemapNotice('style') is NOT gated (latch never gets set on failure, so style notice still surfaces)"
  - "Suppression in errorHandlerRef gates only the 5xx/unknown branch (line 409) — the 401/403 auth-error branch above is untouched"

patterns-established:
  - "Cross-effect ref latch: declare next to errorHandlerRef, reset at effect start, set in success branch, consult in error path — fully imperative, no extra state churn or re-render"

requirements-completed: [SMOKE-12]

duration: ~15min
completed: 2026-05-17
---

# Phase 1050 Plan 05: Basemap Toast Latch (SF-08) Summary

**Suppress false-positive "Basemap connection issue" toast on save by latching basemap-loaded success in a useRef; transient 5xx tile errors after first load are now silent, while real first-load failures still surface.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-05-17T15:51:00Z
- **Completed:** 2026-05-17T15:56:11Z
- **Tasks:** 1 (TDD)
- **Files modified:** 2

## Accomplishments

- Added `basemapLoadedAtRef: useRef<number | null>(null)` next to `errorHandlerRef` in `BuilderMap.tsx`.
- Reset the latch to `null` at the start of the basemap style-fetch effect body, BEFORE `fetch()` is initiated — so a basemap change re-arms first-load failure detection.
- Set the latch to `Date.now()` in the `.then()` success branch — only after a basemap style has actually loaded.
- Gated the `errorHandlerRef` 5xx/unknown branch on `if (basemapLoadedAtRef.current !== null) return;` — transient post-load errors no longer fire either the inline banner or the `builder-map-error` toast.
- Wrote 3 new vitest cases covering (a) loaded-then-error suppressed, (b) never-loaded-then-error surfaces, (c) basemap-change resets latch.
- Existing baseline test (`surfaces a non-blocking basemap recovery notice when the basemap style fails`) still passes — the `setBasemapNotice('style')` first-load failure path is NOT gated (latch never gets set in that path).

## Task Commits

1. **Task 1: Add basemapLoadedAtRef latch and suppress transient tile-toast post-load** - to-be-committed (test+feat squashed; TDD RED→GREEN proven by 1 failing pre-impl test → 4 passing post-impl tests)

## Files Created/Modified

- `frontend/src/components/builder/BuilderMap.tsx` — added `basemapLoadedAtRef` declaration (line 91), reset at effect start (line 149), set in success branch (line 161), suppression check in `errorHandlerRef` body (line 409). Net +12 lines including comments.
- `frontend/src/components/builder/__tests__/BuilderMap.a11y.test.tsx` — added sonner toast mock, MapGL mock that calls `onLoad` with a fake map exposing `emit`, map-sync no-op mock, and a new `describe('BuilderMap basemap connection toast (SF-08)')` block with 3 tests. Net +180 lines.

## Acceptance criteria verification

- `grep -c "basemapLoadedAtRef" frontend/src/components/builder/BuilderMap.tsx` → 4 (≥ 3 required).
- `grep -n "if (basemapLoadedAtRef.current !== null) return;"` → 1 hit at line 409 inside `errorHandlerRef` body.
- All 4 tests in `BuilderMap.a11y.test.tsx` pass (1 baseline + 3 new).
- `BuilderMap.unit.test.ts` 16/16 pass — no regression.
- `tsc --noEmit` reports no new errors in `BuilderMap.tsx` or `BuilderMap.a11y.test.tsx`. Pre-existing `LayerEditorPanel.tsx:413,694` errors are out of scope per success criteria.

## Decisions Made

- **Latch placement:** Declared next to `errorHandlerRef` (line 91) — mirrors the existing cross-effect ref pattern in the same file; `useRef` not `useState` because the latch is not a render input.
- **Reset location:** At the START of the style-fetch effect body, AFTER setting the placeholder background style but BEFORE `fetch()` — guarantees the latch is null at the moment the new fetch begins, regardless of basemap source (the `.then` path is the only thing that ever sets it back to non-null).
- **Success-branch placement:** AFTER `setMapStyle(sanitizeMaplibreStyle(style))` and `setBasemapNotice(null)` — only confirm the latch when the style is actually applied.
- **Suppression scope:** Only the `if (!status || status >= 500)` branch in `errorHandlerRef` is gated. The `if (status === 401 || status === 403)` auth-error branch above it is untouched — auth errors are user-actionable and should always surface.
- **`setBasemapNotice('style')` path NOT gated:** That's the first-load `.catch` branch — by design the latch hasn't been set yet at that point, so the gate would be a no-op anyway. Leaving it ungated documents the contract and avoids reader confusion.

## Deviations from Plan

None — plan executed exactly as written. Test mocks expanded slightly from the plan's minimal sketch (added `setTerrain`, `getSource`, `getLayer`, `getStyle`, `fitBounds`, `getZoom`, `setZoom` to the fake map, and a `vi.mock('@/components/builder/map-sync', ...)` no-op) so the BuilderMap's downstream effects don't crash on the fake map — this is conventional vitest jsdom hygiene, not a deviation in scope.

## Issues Encountered

- Initial test run hit `TypeError: map.getStyle is not a function` from `syncLayersToMap` because the fake map only modeled `on`/`off`/`emit` for the error-handler test. Fixed by adding a `vi.mock('@/components/builder/map-sync')` no-op (matches the pattern in `ViewerMap.basemap-config.test.tsx`) and expanding the fake map to cover the BuilderMap effects that fire on mount (`setTerrain`, `getSource`, `fitBounds`, etc.). Once added, RED phase showed exactly 1 failing test (Test 1 "suppresses transient tile error toast when basemap loaded successfully") with 3 passing — proving the suppression was not present pre-impl. Post-impl all 4 pass.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- SMOKE-12 (SF-08) closed. Ready for Plan 06 CTRL-01 close gate (CHANGELOG + full smoke gate + Playwright MCP re-verify).
- No blockers; no concerns.

## Self-Check: PASSED

- `frontend/src/components/builder/BuilderMap.tsx` modified — FOUND (4 `basemapLoadedAtRef` refs).
- `frontend/src/components/builder/__tests__/BuilderMap.a11y.test.tsx` modified — FOUND (4 tests, all passing).
- `.planning/phases/1050-builder-smoke-carryover/1050-05-SUMMARY.md` created — FOUND (this file).

---
*Phase: 1050-builder-smoke-carryover*
*Plan: 05*
*Completed: 2026-05-17*
