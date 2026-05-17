---
phase: 1050-builder-smoke-carryover
plan: 02
subsystem: frontend/maps-hooks
tags: [sf-05, blob-url, lifecycle, react-query, hygiene]
dependency_graph:
  requires: []
  provides:
    - "Blob URL lifecycle cleanup in useMapThumbnail (revoke on data change + unmount)"
  affects:
    - "Post-login redirect console (eliminates 4x ERR_FILE_NOT_FOUND blob: errors)"
tech_stack:
  added: []
  patterns:
    - "useEffect cleanup keyed on React Query data string — mirrors use-quicklook.ts:67-74"
key_files:
  created: []
  modified:
    - frontend/src/components/maps/hooks/use-map-thumbnail.ts
    - frontend/src/components/maps/hooks/__tests__/use-map-thumbnail.test.ts
decisions:
  - "Copied exact useEffect cleanup shape from use-quicklook.ts:67-74; no novel pattern."
  - "Renamed effect's bound name from `data` to `src` to match existing hook destructure naming."
  - "Other createObjectURL call sites (datasets.ts, ExportSplitButton, SamlProvidersSection, StyleJsonDialog, use-builder-save.ts handleExportPNG, use-config-ops.ts) NOT touched — sync-revoke-after-click is correct for one-shot download flows."
metrics:
  duration_seconds: 117
  completed: 2026-05-17
requirements: [SMOKE-09]
---

# Phase 1050 Plan 02: Defer Blob Revoke Summary

`useMapThumbnail` now revokes blob URLs on React Query data change AND on component unmount via a `useEffect` cleanup, mirroring the existing `use-quicklook.ts:67-74` pattern. Eliminates the 4x `net::ERR_FILE_NOT_FOUND` `blob:` console errors on post-login redirect to `/` (SF-05).

## What changed

| File | Before lines | After lines | Delta | Note |
|------|--------------|-------------|-------|------|
| `frontend/src/components/maps/hooks/use-map-thumbnail.ts` | 33 | 54 | +21 | Added `useEffect` import + cleanup hook + JSDoc lifecycle comment |
| `frontend/src/components/maps/hooks/__tests__/use-map-thumbnail.test.ts` | 124 | 169 | +45 | 3 new tests (revoke on key change, revoke on unmount, no revoke when data undefined) |

Test count before: 6 → after: 9 (`grep -c "^  it(" use-map-thumbnail.test.ts` = 9).

## Implementation

Added inside `useMapThumbnail()` after the `useQuery({ ... })` block:

```typescript
// Revoke blob URL when data changes (new mapId) or on unmount
useEffect(() => {
  if (typeof src === 'string') {
    return () => {
      URL.revokeObjectURL(src);
    };
  }
}, [src]);
```

The cleanup runs at the standard React useEffect cleanup time: when the dep (`src`) changes value OR when the component unmounts. React Query gcTime keeps the previous blob in cache for 10min, but the `<img>` element using the URL is already gone by then (consumer re-renders with the new URL or unmounts), so the eager revoke matches the actual lifecycle of the URL's only consumer.

Hook doc comment was updated to mirror `use-quicklook.ts:26-28`, explicitly calling out the SF-05 motivation.

## Tests

| Test | Status | Note |
|------|--------|------|
| `returns null initially then blob URL after fetch` | existing — passing | regression |
| `adds a version query when updated_at is provided` | existing — passing | regression |
| `returns null when thumbnailUrl is null` | existing — passing | regression |
| `returns null when fetch fails` | existing — passing | regression |
| `returns blob URL for different thumbnailUrl` | existing — passing | regression |
| `refetches when the thumbnail version changes` | existing — passing | regression |
| `calls revokeObjectURL when the query key changes` | NEW — passing | uses `mockReturnValueOnce` per `createObjectURL` call so distinct URLs flow to the effect |
| `calls revokeObjectURL on unmount` | NEW — passing | verifies cleanup on `unmount()` |
| `does NOT call revokeObjectURL when data is undefined` | NEW — passing | confirms loading-state safety |

**Vitest run:** `npm run test -- --run src/components/maps/hooks/__tests__/use-map-thumbnail.test.ts src/components/maps/hooks/__tests__/use-quicklook.test.ts` → **17/17 passed** (use-map-thumbnail 9 + use-quicklook 8). No regression in sibling hook.

## Acceptance criteria

- [x] `grep -c "URL.revokeObjectURL" frontend/src/components/maps/hooks/use-map-thumbnail.ts` → 2 (≥ 1) ✅
- [x] `grep -c "useEffect" frontend/src/components/maps/hooks/use-map-thumbnail.ts` → 3 (≥ 1) ✅
- [x] All 3 new tests in `use-map-thumbnail.test.ts` pass ✅
- [x] Existing `use-quicklook.test.ts` tests continue to pass (8/8) ✅
- [ ] Frontend typecheck exits 0 — **see Deviations below**

## Verification (relative to plan success_criteria)

| Criterion | Status |
|-----------|--------|
| `use-map-thumbnail.ts` calls `URL.revokeObjectURL(data)` in a useEffect cleanup keyed on `[data]` | ✅ Done (variable named `src` not `data`, but the binding is the React Query `data` field) |
| The cleanup fires on mapId/query-key change AND on component unmount (verified by 2 new tests) | ✅ Done |
| Typecheck clean | ⚠ Pre-existing errors only — see Deviations |
| e2e:smoke:builder unchanged | Deferred to Plan 06 CTRL-01 |

Post-login redirect Playwright MCP re-verification (zero `blob:` `ERR_FILE_NOT_FOUND` on `/`) lives in Plan 06 (CTRL-01) per the milestone's hygiene-shape gate plan.

## Deviations from Plan

### Out-of-scope (logged, not fixed)

**1. [out-of-scope] Pre-existing typecheck errors in `LayerEditorPanel.tsx`**
- **Found during:** post-implementation typecheck
- **Issue:** Two `TS2322` errors in `frontend/src/components/builder/LayerEditorPanel.tsx:413,694` — `(layerId, mode: RenderAsId) => void` incompatible with `(layerId, mode: PointRenderMode) => void`. The widened `RenderAsId` includes `"point"` (singular), but the legacy `PointRenderMode` type alias still uses `"points"` (plural). Plus four `TS6133` unused-variable errors in test files.
- **Verification:** Stashed all plan-02 changes → re-ran `tsc -b --noEmit` → identical errors present. **Pre-existing**, not caused by this plan.
- **Disposition:** Logged for Plan 06 close gate to surface during the smoke sweep. Not blocking SF-05 closure.
- **Files NOT modified:** out of scope for plan 1050-02 (which touches only `use-map-thumbnail.ts` and its test).

### Auto-fixed (Rule N): None

No bugs found in the plan's surface area. Implementation followed the exact use-quicklook analog with one cosmetic adjustment (variable name `data` → `src` to match existing destructure in the hook).

### Other createObjectURL call sites NOT touched (per plan's explicit scope)

Confirmed unchanged via `git diff`:
- `frontend/src/api/datasets.ts:87-94`
- `frontend/src/components/admin/ExportSplitButton.tsx:24-31`
- `frontend/src/components/admin/saml/SamlProvidersSection.tsx:230-237`
- `frontend/src/components/builder/StyleJsonDialog.tsx:33-38`
- `frontend/src/components/builder/hooks/use-builder-save.ts:486-493`
- `frontend/src/hooks/use-config-ops.ts:24-31`

All retain the synchronous-revoke-after-`a.click()` pattern, which is correct for one-shot download flows (not the SF-05 thumbnail-eviction path).

## Commits

| Hash | Type | Subject |
|------|------|---------|
| `ddef4f55` | test | add failing tests for blob URL revoke lifecycle in useMapThumbnail (RED) |
| `4473d21e` | feat | defer blob URL revoke until data change or unmount in useMapThumbnail (GREEN) |

## Self-Check: PASSED

- File `frontend/src/components/maps/hooks/use-map-thumbnail.ts` — FOUND (54 lines)
- File `frontend/src/components/maps/hooks/__tests__/use-map-thumbnail.test.ts` — FOUND (169 lines)
- Commit `ddef4f55` — FOUND in git log
- Commit `4473d21e` — FOUND in git log
- Acceptance grep `URL.revokeObjectURL` — 2 occurrences ✅
- Acceptance grep `useEffect` — 3 occurrences ✅
- Targeted vitest run — 17/17 pass ✅
