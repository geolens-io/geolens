---
phase: 1136-per-render-mode-editor-polish
plan: "04"
subsystem: ui
tags: [builder, basemap, blank-preset, i18n, tdd]

requires:
  - phase: 1136-03
    provides: FillEditor extrusionRange i18n key (en only; de/es/fr parity closed here)

provides:
  - "BasemapGroupEditorScene 'No basemap' preset card as first entry in the preset grid"
  - "Clicks 'No basemap' → onSwapBasemap('blank') → existing swapBasemapPreset path → hasVisibleBasemap=false"
  - "i18n key basemapGroup.noBasemap in en/de/es/fr"
  - "i18n key style.extrusionRange in de/es/fr (parity fix for Plan 03 omission)"
  - "5 new vitest tests for the No-basemap card (Tests 13-17)"

affects: [1136-05, 1136-07, 1139-quality-sweep]

tech-stack:
  added: []
  patterns:
    - "BLANK_BASEMAP_ID sentinel reuse: no new sentinel value; existing 'blank' constant imported + wired to card onClick"
    - "vi.mock BLANK_BASEMAP_ID: when a module exports both a function and a constant, vi.mock must export both"

key-files:
  created: []
  modified:
    - frontend/src/components/builder/BasemapGroupEditorScene.tsx
    - frontend/src/components/builder/__tests__/BasemapGroupEditorScene.test.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json

key-decisions:
  - "No controller change: onSwapBasemap('blank') routes through existing swapBasemapPreset(state, 'blank') path; basemap-state-controller.ts unchanged"
  - "No provider sub-label on the No-basemap card: consistent with existing optional provider rendering (blank has no provider)"
  - "vi.mock requires BLANK_BASEMAP_ID export: when component imports a constant from a mocked module, mock must re-export it"
  - "extrusionRange de/es/fr added as Rule 3 auto-fix: Plan 03 added the en key but left de/es/fr without it, breaking the i18n parity test"

patterns-established:
  - "vi.mock constant re-export: when vi.mock() partially mocks a module, ALL imported names (functions + constants) must be listed in the factory return"

requirements-completed:
  - EDITOR-BASEMAP-02

duration: 3min
completed: 2026-05-27
---

# Phase 1136 Plan 04: BasemapGroupEditorScene "No Basemap" Preset Card

**"No basemap" preset card inserted as the first entry in BasemapGroupEditorScene's preset grid, wired to existing BLANK_BASEMAP_ID sentinel and swapBasemapPreset path with no controller changes.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-27T20:46:44Z
- **Completed:** 2026-05-27T20:49:54Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 6

## Accomplishments

- "No basemap" card renders as the FIRST entry in the preset grid before all provider presets
- Clicking the card dispatches `onSwapBasemap('blank')`, which routes through the existing `swapBasemapPreset(state, 'blank')` path at `MapBuilderPage.tsx:879` → `basemap-state-controller.ts:140-150` → `hasVisibleBasemap: false`
- Card uses `basemapThumbnail('blank')` (existing inline SVG checkered pattern), height 56px, matching card shape
- Active ring (`border-primary shadow-[0_0_0_1px_var(--primary)]`) when `activePresetId='blank'`
- 5 new vitest tests (Tests 13-17), all passing; existing 15 tests unbroken
- 1 new `basemapGroup.noBasemap` i18n key in all 4 locales (en/de/es/fr)
- Pitfall #9 clean: zero `map.setPaintProperty` / `map.setLayoutProperty` calls in the component

## Task Commits

1. **Task 1: Add "No basemap" card + tests + i18n** - `a0d3aacd` (feat)

## Files Created/Modified

- `frontend/src/components/builder/BasemapGroupEditorScene.tsx` - Import `BLANK_BASEMAP_ID`; insert "No basemap" button as first child of preset grid `<div>`
- `frontend/src/components/builder/__tests__/BasemapGroupEditorScene.test.tsx` - Add `BLANK_BASEMAP_ID: 'blank'` to `vi.mock`; update Test 2 thumbnail count 4→5; add Tests 13-17
- `frontend/src/i18n/locales/en/builder.json` - Add `basemapGroup.noBasemap`
- `frontend/src/i18n/locales/de/builder.json` - Add `basemapGroup.noBasemap` + `style.extrusionRange` (parity fix)
- `frontend/src/i18n/locales/es/builder.json` - Add `basemapGroup.noBasemap` + `style.extrusionRange` (parity fix)
- `frontend/src/i18n/locales/fr/builder.json` - Add `basemapGroup.noBasemap` + `style.extrusionRange` (parity fix)

## Decisions Made

- Reused `BLANK_BASEMAP_ID` constant from `basemap-utils.ts` with no new sentinel value, confirming the "blank" sentinel already round-trips through `MapBasemapConfig.basemap_id` → `basemap-state-controller.ts` → `hasVisibleBasemapStyle()`.
- No provider sub-label for the "No basemap" card — the existing card renders `preset.provider` only when truthy; blank has no provider.
- No change to `basemap-state-controller.ts`, `MapBuilderPage.tsx`, or `swapBasemapPreset` — the existing path already handles `'blank'`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] vi.mock missing BLANK_BASEMAP_ID export**
- **Found during:** Task 1, GREEN phase (tests failed after implementation)
- **Issue:** `vi.mock('@/lib/basemap-utils', ...)` only exported `basemapThumbnail`. After adding `import { BLANK_BASEMAP_ID }` to the component, Vitest threw `No "BLANK_BASEMAP_ID" export is defined on the mock`.
- **Fix:** Added `BLANK_BASEMAP_ID: 'blank'` to the mock factory return object.
- **Files modified:** `BasemapGroupEditorScene.test.tsx`
- **Verification:** All 20 tests pass after fix.
- **Committed in:** `a0d3aacd`

**2. [Rule 1 - Bug] Test 2 thumbnail count 4→5**
- **Found during:** Task 1, GREEN phase
- **Issue:** Test 2 asserted `thumbImages.length` to be 4 (written before the "No basemap" card existed). Adding the card increased the count to 5.
- **Fix:** Updated `toBe(4)` → `toBe(5)` with an explanatory comment.
- **Files modified:** `BasemapGroupEditorScene.test.tsx`
- **Verification:** 20/20 tests pass.
- **Committed in:** `a0d3aacd`

**3. [Rule 3 - Blocking] i18n parity: add noBasemap + extrusionRange to de/es/fr**
- **Found during:** Task 1, i18n test run post-commit
- **Issue:** `npm run test:i18n` failed: (a) `basemapGroup.noBasemap` missing from de/es/fr; (b) `style.extrusionRange` was added by Plan 03 to en but not de/es/fr — both gaps were caught by the key-parity test.
- **Fix:** Added `basemapGroup.noBasemap` (translated) and `style.extrusionRange` (translated) to de/es/fr locale files.
- **Files modified:** `de/builder.json`, `es/builder.json`, `fr/builder.json`
- **Verification:** `npm run test:i18n` 2/2 PASS.
- **Committed in:** `a0d3aacd` (part of the same feat commit)

---

**Total deviations:** 3 auto-fixed (2 Rule 1 bug fixes, 1 Rule 3 blocking fix)
**Impact on plan:** All fixes necessary for test correctness and i18n parity. No scope creep; the `extrusionRange` parity fix was a pre-existing Plan 03 gap.

## Issues Encountered

None beyond the deviations documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- EDITOR-BASEMAP-02 closed; "No basemap" card ships in Plan 04.
- Plan 05 owns the DETAIL LEVEL stays-gone regression pin (`BasemapSublayerEditorScene`).
- Plan 06 handles any remaining i18n copywriting for de/es/fr (lineEnds, lineCap, etc. remain in English fallback).
- i18n parity test is GREEN; no carry-forward for de/es/fr `noBasemap` or `extrusionRange`.

## Self-Check

- `BasemapGroupEditorScene.tsx` contains `BLANK_BASEMAP_ID`: 4 hits (import + onClick + className conditional + src) — PASS
- `grep -cE "map\.set(Paint|Layout)Property" BasemapGroupEditorScene.tsx` → 0 — PASS
- `npm test -- BasemapGroupEditorScene --run` → 20/20 PASS
- `npm run typecheck` → 0 errors PASS
- `npm run test:i18n` → 2/2 PASS
- `git diff basemap-state-controller.ts` → empty (controller unchanged) PASS

## Self-Check: PASSED

---
*Phase: 1136-per-render-mode-editor-polish*
*Completed: 2026-05-27*
