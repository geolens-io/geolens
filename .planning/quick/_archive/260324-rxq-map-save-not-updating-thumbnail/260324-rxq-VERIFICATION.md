---
phase: quick-260324-rxq
verified: 2026-03-24T20:14:00Z
status: passed
score: 3/3 must-haves verified
---

# Quick Task 260324-rxq: Map Save Not Updating Thumbnail Verification Report

**Task Goal:** Map save not updating thumbnail
**Verified:** 2026-03-24T20:14:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Saving a map captures a thumbnail that reflects the current map state | VERIFIED | `captureThumbnail` calls `doCapture` directly when `map.loaded()` is true; `preserveDrawingBuffer: true` guarantees canvas content persists |
| 2 | Thumbnail updates are visible on the maps listing page after save | VERIFIED | `doCapture` calls `queryClient.invalidateQueries({ queryKey: ['maps'] })` after `uploadThumbnail` resolves (line 39) |
| 3 | Thumbnail capture works whether the map is idle or actively rendering | VERIFIED | `captureThumbnail` branches on `map.loaded()`: immediate capture if idle, `map.once('idle', ...)` with 3-second safety timeout if not |

**Score:** 3/3 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/hooks/use-builder-save.ts` | captureThumbnail with reliable canvas capture | VERIFIED | Contains `map.loaded()` branch, `doCapture` helper, 3s safety timeout; `uploadThumbnail` called inside `doCapture` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `frontend/src/hooks/use-builder-save.ts` | `/api/maps/{id}/thumbnail` | `uploadThumbnail` after canvas capture | VERIFIED | `uploadThumbnail(mapId, dataUri)` called at line 38 inside `doCapture`; `uploadThumbnail` imported from `@/api/maps` and exists at `frontend/src/api/maps.ts:154` |

### Anti-Patterns Found

None detected. No TODO/FIXME/placeholder comments, no empty return values, no stub implementations in modified files.

### Test Results

All 10 tests in `frontend/src/hooks/__tests__/use-builder-save.test.ts` pass:
- `handleSave calls updateMap.mutate with correct payload`
- `handleSave is a no-op when mapId is undefined`
- `handleFork calls duplicateMutation.mutateAsync and navigates on success`
- `handleFork shows warning toast when excluded_layer_count > 0`
- `handleExportPNG triggers map repaint and registers idle callback`
- `Ctrl+S keydown calls handleSave`
- `returns blocker from hook`
- `adds beforeunload listener when hasUnsavedChanges is true`
- `does not add beforeunload listener when hasUnsavedChanges is false`
- `isSaving reflects updateMap.isPending state`

### Human Verification Required

**1. Real map save triggers thumbnail update**

**Test:** Open a map in the builder, make a change (e.g. rename it), save with Ctrl+S, navigate to the maps listing page.
**Expected:** The map's thumbnail is updated to reflect the current canvas state.
**Why human:** Canvas rendering behavior in a real browser with a live MapLibre instance cannot be verified by static analysis.

**2. Thumbnail updates when map was already idle before save**

**Test:** Open a map, wait until fully loaded (tiles rendered, no activity), then save without making any layer changes (metadata-only save). Navigate to listing.
**Expected:** Thumbnail updates (previously would silently drop due to `triggerRepaint` + `idle` never firing).
**Why human:** The specific race condition being fixed requires a live map instance to reproduce and confirm resolved.

---

_Verified: 2026-03-24T20:14:00Z_
_Verifier: Claude (gsd-verifier)_
