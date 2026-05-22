---
phase: 1084-frontend-hygiene-tail
plan: "01"
subsystem: frontend
tags:
  - typescript
  - test-hygiene
  - typecheck
dependency_graph:
  requires: []
  provides:
    - "npm run typecheck gate (tsc -b --noEmit exit 0)"
  affects:
    - frontend/package.json
tech_stack:
  added: []
  patterns:
    - "Non-null assertion (result!) after expect().not.toBeNull() for union narrowing"
    - "Cast-at-source pattern ([arr as T[]).method()) for mock.calls tuple types"
    - "Underscore-prefix (_param) for intentionally unused destructured params"
key_files:
  created: []
  modified:
    - frontend/package.json
    - frontend/src/api/__tests__/maps.normalize.test.ts
    - frontend/src/components/builder/__tests__/map-sync.data-driven-cols.test.ts
    - frontend/src/components/builder/__tests__/sublayer-overrides.round-trip.test.ts
    - frontend/src/lib/builder/__tests__/basemap-style-mutation.test.ts
    - frontend/src/__tests__/sec-fu-03-react-no-danger-regression.skip.tsx
    - frontend/src/components/builder/__tests__/DataDrivenStyleEditor.test.tsx
    - frontend/src/components/builder/__tests__/StackRow.test.tsx
    - frontend/src/components/builder/__tests__/UnifiedStackPanel.render-perf.test.tsx
    - frontend/src/components/builder/hooks/__tests__/use-builder-layers.bulk-ops.test.ts
    - frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.raf.test.ts
    - frontend/src/components/dataset/__tests__/DatasetDetailHeader.test.tsx
    - frontend/src/components/import/__tests__/StacImportForm.sizeEstimate.test.tsx
    - frontend/src/components/import/__tests__/UploadForm.multiLayerFanOut.test.tsx
    - frontend/src/lib/__tests__/tile-utils.test.ts
    - frontend/src/pages/__tests__/RegisterPage.alreadySignedIn.test.tsx
decisions:
  - "Used non-null assertion (result!) over optional chaining (result?.) for SharedMapResponse narrowing — the tests assert the happy path, not defensive null handling"
  - "Used 'YlOrRd' as ramp default in StyleConfig fixtures, matching the normalize-style-config.ts fallback value"
  - "Deleted unused user = userEvent.setup() in DatasetDetailHeader test (no interaction in that test case)"
  - "Deleted unused const mockToken in tile-utils extraCols describe block (all calls use null token)"
  - "Removed id: overrides.id before spread in StacImportForm makeItem — id already provided by ...overrides"
  - "Replaced is_approved (not in UserResponse) with status + last_login_at in RegisterPage fixtures"
metrics:
  duration: "~12 minutes"
  completed: "2026-05-22T01:19:38Z"
  tasks_completed: 3
  files_modified: 16
---

# Phase 1084 Plan 01: Frontend TypeScript Hygiene Summary

**One-liner:** Resolved 37 pre-existing TypeScript errors across 15 test files at root cause, restoring `npm run typecheck` as a zero-error gate.

## What Was Done

Added the missing `typecheck` script to `frontend/package.json` and fixed all 37 TS errors across 15 test files in three task commits. Zero `@ts-expect-error` or `@ts-ignore` directives added. Production code (`src/api/`, `src/types/`, `src/lib/`, `src/components/builder/` non-test paths) is untouched.

## Task-by-Task Delta

### Task 1 — typecheck script + 14 null-narrowing errors (2 files)

**Errors cleared:** 14  
**Files:** `frontend/package.json`, `src/api/__tests__/maps.normalize.test.ts`  
**Commit:** `c828def8`

| File | Change |
|------|--------|
| `package.json` | Added `"typecheck": "tsc -b --noEmit"` between `test` and `test:i18n` scripts |
| `maps.normalize.test.ts` | Added `expect(result).not.toBeNull(); const r = result!;` narrowing before all 14 TS18047-flagged field accesses on `SharedMapResponse | null` results |

**Narrowing pattern used:** `expect().not.toBeNull()` + `const r = result!` rebind for multi-field tests; inline `result!.field` for single-field accesses. Non-null assertion `!` is a TypeScript narrowing operator — not a suppression directive.

### Task 2 — StyleConfig.ramp + tuple-destructure cluster (3 files, 9 errors)

**Errors cleared:** 9  
**Files:** `map-sync.data-driven-cols.test.ts`, `sublayer-overrides.round-trip.test.ts`, `basemap-style-mutation.test.ts`  
**Commit:** `6127d2e9`

| File | Errors | Fix |
|------|--------|-----|
| `map-sync.data-driven-cols.test.ts` | 7 (TS2741 + TS2345) | Added `ramp: 'YlOrRd'` to all 7 StyleConfig literals missing the required field |
| `sublayer-overrides.round-trip.test.ts` | 1 (TS2345) | Cast `calls` to `[string, string, unknown][]` at the source before `.map()` |
| `basemap-style-mutation.test.ts` | 1 (TS2769) | Cast `mock.calls` to `[string, string][]` at the source before `.filter()` |

**Ramp default:** `'YlOrRd'` — matches `normalize-style-config.ts` fallback (`raw.ramp ?? ... ?? 'YlOrRd'`).

### Task 3 — Unused-symbol + RegisterPage cluster (11 files, 14 errors)

**Errors cleared:** 14 (plan said 14; actual fix resolved 16 counting the 2 extra TS2353 errors discovered during typecheck)  
**Files:** 11 files  
**Commit:** `821707df`

| File | Error(s) | Fix |
|------|----------|-----|
| `sec-fu-03-react-no-danger-regression.skip.tsx` | TS6133 unused `React` import | Removed import; React 19 JSX transform doesn't require it |
| `DataDrivenStyleEditor.test.tsx` | TS6133 unused `act` import | Removed `act` from `@/test/test-utils` import |
| `StackRow.test.tsx` | TS18047 `row` possibly null | Added `row!.querySelector(...)` after existing `expect(row).not.toBeNull()` |
| `UnifiedStackPanel.render-perf.test.tsx` | TS6133 unused `onRenderCountChange` | Renamed to `_onRenderCountChange` in destructure |
| `use-builder-layers.bulk-ops.test.ts` | TS6133 unused `removeLayerFromMapApi` import | Removed from import; `bulkDeleteLayersApi` retained |
| `use-layer-map-sync.raf.test.ts` | TS6133 unused `paint` param | Renamed to `_paint` in mock fn signature |
| `DatasetDetailHeader.test.tsx` | TS6133 unused `user` declaration | Deleted `const user = userEvent.setup()` (no interaction in that test case) |
| `StacImportForm.sizeEstimate.test.tsx` | TS2783 `id` specified twice | Removed explicit `id: overrides.id` before `...overrides` spread |
| `UploadForm.multiLayerFanOut.test.tsx` | TS6133 unused `ns` destructure | Renamed to `_ns` in `useTranslation` mock |
| `tile-utils.test.ts` | TS6133 unused `mockToken` | Deleted unused `const mockToken` declaration |
| `RegisterPage.alreadySignedIn.test.tsx` | TS6192 + TS6133 + TS2322×2 + TS2353×2 | Removed unused `renderHook`/`act` import; prefixed `_children`; changed `id: 1` → `id: '1'`; replaced `is_approved` with `status` + `last_login_at` per `UserResponse` |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] RegisterPage fixture had 2 extra TS2353 errors beyond plan's 4**

- **Found during:** Task 3 typecheck run
- **Issue:** After fixing `id: 1` → `id: '1'`, tsc revealed `is_approved: true` is not in `UserResponse` (the type has `status: string` and `last_login_at: string | null` instead)
- **Fix:** Replaced `is_approved: true` with `status: 'active', last_login_at: null` in both user fixtures
- **Files modified:** `frontend/src/pages/__tests__/RegisterPage.alreadySignedIn.test.tsx`
- **Commit:** `821707df`

This was a pre-existing type mismatch in the test fixture — the plan's error count (4) did not include these because tsc deferred them until other errors in the file were resolved.

### Deviation: ramp value uses 'YlOrRd' not 'viridis'

Plan said "check `normalize-style-config.ts` first; if it picks a different default, use that one." The file uses `'YlOrRd'` as the fallback ramp value (lines 190, 209). Used `'YlOrRd'` accordingly.

## Verification Results

| Gate | Result |
|------|--------|
| `npm run typecheck` exit code | 0 |
| `error TS` count | 0 |
| Vitest test count | 2105/2105 PASS |
| ESLint `lint:sec-fu-03-regression` | EXIT=0 (rule fires as expected) |
| `@ts-expect-error` / `@ts-ignore` in test dirs | 0 |
| Production code diff (`maps.ts`, `client.ts`, `api.ts`) | 0 lines changed |

## Known Stubs

None.

## Threat Flags

None — test files only, no new network endpoints or auth paths.

## Self-Check: PASSED

- All 16 files modified exist on disk
- Commits c828def8, 6127d2e9, 821707df verified in git log
- `npm run typecheck` exits 0, `error TS` count = 0
- Vitest 2105/2105 passes
