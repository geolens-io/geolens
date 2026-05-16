---
phase: 1047-perf-and-code-quality-fixes
plan: 03
subsystem: builder/perf
tags: [perf-04, raf-coalescing, debounce, maplibre, paint-updates, pb-02, pb-04, pb-06]

requires:
  - phase: 1047-01
    provides: syncLayerFilter helper, perf fixture scaffold
  - phase: 1047-02
    provides: lazy-load editor scenes, SceneSpinnerFallback

provides:
  - coalesceFrame rAF utility at frontend/src/lib/builder/raf-coalesce.ts (last-write-wins, shared rAF tick, SSR fallback)
  - 100ms debounce on LayerStyleEditor master opacity slider (PB-02)
  - 200ms debounce on DataDrivenStyleEditor per-category/per-class color pickers (PB-04)
  - 200ms debounce on LayerFilterEditor value input (bumped from 180ms) (PB-04)
  - StyleColorPicker 100ms debounce confirmed unchanged (PB-06)
  - use-layer-map-sync.handlePaintChange routes through coalesceFrame (PERF-04)

affects:
  - 1047-04 (bulk-op batching — PERF-03)
  - 1047-05 (LayerStyleEditor split — CB-07 — builds on same file)
  - 1047-06 (final e2e gate verifies paint frame rate)

tech-stack:
  added: []
  patterns:
    - "coalesceFrame(key, fn): last-write-wins rAF queue; shared requestAnimationFrame flush per tick"
    - "local-state + ref + setTimeout debounce pattern (mirrors StyleColorPicker) for opacity slider"
    - "opacityFromPropRef guard: skip debounce emit if localOpacity === last prop value (no spurious mount call)"
    - "200ms clearTimeout debounce for color picker drags in DataDrivenStyleEditor via colorDebounceRef"

key-files:
  created:
    - frontend/src/lib/builder/raf-coalesce.ts
    - frontend/src/lib/builder/__tests__/raf-coalesce.test.ts
    - frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.raf.test.ts
  modified:
    - frontend/src/components/builder/LayerStyleEditor.tsx
    - frontend/src/components/builder/LayerFilterEditor.tsx
    - frontend/src/components/builder/DataDrivenStyleEditor.tsx
    - frontend/src/components/builder/hooks/use-layer-map-sync.ts
    - frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx
    - frontend/src/components/builder/__tests__/LayerFilterEditor.test.ts
    - frontend/src/components/builder/__tests__/DataDrivenStyleEditor.test.tsx

key-decisions:
  - "coalesceFrame key semantics: same key = overwrite (last write wins); different keys = both fire on same rAF tick (one shared requestAnimationFrame call)"
  - "Opacity debounce uses opacityFromPropRef guard: only emits when localOpacity diverges from prop to prevent spurious onOpacityChange call on mount"
  - "Visibility/filter/order handlers stay synchronous in use-layer-map-sync — they are idempotent, cheap, and synchronous semantics make toggle latency 0"
  - "DataDrivenStyleEditor color picker uses colorDebounceRef + clearTimeout pattern (not local state) because the component already manages color state externally via style_config"
  - "LayerFilterEditor debounce bumped 180ms -> 200ms to align with PB-04 200ms target"

requirements-completed: [PERF-04, PERF-06]

duration: ~35 minutes
completed: "2026-05-16"
tasks_completed: 3
tasks_total: 3
files_changed: 10
---

# Phase 1047 Plan 03: rAF Coalescing + Debounce Summary

**rAF coalescing utility + 100ms/200ms debounce wiring collapses MapLibre paint updates from 50-100 setPaintProperty/sec to 1 per animation frame (PERF-04).**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-05-16T20:18:00Z
- **Completed:** 2026-05-16T20:53:00Z
- **Tasks:** 3 of 3
- **Files modified:** 10

## Accomplishments

- `coalesceFrame(key, fn)` utility with last-write-wins semantics: N rapid calls for same key within one rAF tick collapse to 1 call (the last fn). 6 unit tests verify the contract.
- `handlePaintChange` in `use-layer-map-sync.ts` now routes through `coalesceFrame('paint:layerId', ...)` — 10 rapid calls produce exactly 1 `syncPaint` call per rAF tick. Integration test proves 10:1 coalescing; Test 3 confirms visibility stays synchronous.
- Master opacity slider in `LayerStyleEditor` debounces at 100ms via `localOpacity` local state + `opacityFromPropRef` guard. PB-02 closed.
- `DataDrivenStyleEditor` per-category and per-class color pickers debounce at 200ms. PB-04 closed.
- `LayerFilterEditor` value-input debounce bumped from 180ms to 200ms. PB-04 closed.
- `StyleColorPicker` existing 100ms debounce unchanged. PB-06 confirmed.

## coalesceFrame Contract Summary

Key collision semantics: `pending.set(key, fn)` overwrites any prior `fn` for the same `key`, so the last queued write wins for each `(layerId)` pair within a frame. Different keys share one `requestAnimationFrame` call but do NOT suppress each other — both fire on the next tick. After flush, `rafHandle = null` so a subsequent call schedules a fresh rAF (no sticking across frames). SSR / no-rAF: falls back to synchronous invocation.

## Debounce Sites

| Site | File | ms | Pattern |
|------|------|----|---------|
| Master opacity slider | LayerStyleEditor.tsx | 100ms | localOpacity state + setTimeout + opacityFromPropRef guard |
| Per-category color picker | DataDrivenStyleEditor.tsx | 200ms | colorDebounceRef + clearTimeout |
| Per-class color picker | DataDrivenStyleEditor.tsx | 200ms | shared colorDebounceRef + clearTimeout |
| Filter value input | LayerFilterEditor.tsx | 200ms | debounceTimerRef (existing, bumped 180→200) |
| StyleColorPicker | StyleColorPicker.tsx | 100ms | timerRef (existing, unchanged) |

## Visibility/Filter/Order: Confirmed STAYED Synchronous

`handleToggleVisibility`, `handleFilterChange`, `handleLayoutChange`, `handleLabelChange`, `handlePopupChange` all remain synchronous in `use-layer-map-sync.ts`. Code comment added: "Paint writes coalesce via rAF (PERF-04); visibility/filter/order remain synchronous because they're idempotent and cheap, and synchronous semantics let UI toggles feel instant."

## Integration Test Result

```
Test 1: 10 paint updates → 1 syncPaint call
  expect(mockSyncPaint).toHaveBeenCalledTimes(1);  // PASS
```

## Task Commits

| Task | Name | Commit | Type |
|------|------|--------|------|
| 1 | coalesceFrame utility + unit test | `df585a50` | feat |
| 2 | Debounce opacity slider, color pickers, filter editor | `ce731464` | feat |
| 3 | TDD RED — failing rAF integration test | `3d7cfb50` | test |
| 3 | Route handlePaintChange through coalesceFrame | `f73307be` | feat |

## Verification Results

| Check | Result |
|-------|--------|
| TypeScript typecheck (`tsc --noEmit`) | CLEAN |
| raf-coalesce.test.ts (6 tests) | 6/6 PASS |
| LayerStyleEditor.test.tsx (51 tests) | 51/51 PASS |
| LayerFilterEditor.test.ts (24 tests) | 24/24 PASS |
| DataDrivenStyleEditor.test.tsx (13 tests) | 13/13 PASS |
| use-layer-map-sync.raf.test.ts (3 tests) | 3/3 PASS |
| Full vitest suite (1828 tests, 186 files) | 1828/1828 PASS |
| PERF-04 unit-level rAF coalescing test | PASS |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] DataDrivenStyleEditor existing tests expected synchronous color change emission**

- **Found during:** Task 2 (debounce wiring)
- **Issue:** Two existing tests (`handleCategoryColorChange sets ramp to custom`, `handleGraduatedColorChange sets ramp to custom`) used `expect(onStyleConfigChange).toHaveBeenCalled()` immediately after a click, but the new 200ms debounce deferred the call.
- **Fix:** Updated both tests to use `waitFor(() => ..., { timeout: 1000 })` instead of synchronous assertion. This correctly models the async debounce behavior.
- **Files modified:** `frontend/src/components/builder/__tests__/DataDrivenStyleEditor.test.tsx`
- **Committed in:** `ce731464` (Task 2 commit)

**2. [Rule 1 - Bug] LayerFilterEditor debounce was 180ms (pre-existing near-miss)**

- **Found during:** Task 2 (reading LayerFilterEditor source)
- **Issue:** The existing debounce was already implemented at 180ms (close to the 200ms target), but used a slightly different timeout value than what PERF-04 specifies.
- **Fix:** Updated from 180ms to 200ms for consistency with the PB-04 target.
- **Files modified:** `frontend/src/components/builder/LayerFilterEditor.tsx`
- **Committed in:** `ce731464` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (Rule 1 — bugs)
**Impact on plan:** Both fixes necessary for test correctness and spec alignment. No scope creep.

## Known Stubs

None — no placeholder values or stub patterns introduced.

## Threat Flags

No new network endpoints, auth paths, file access patterns, or schema changes. T-1047-03-02 (DoS, rAF coalescing) is mitigated: `coalesceFrame` overwrites pending fn per key, bounding queue size by unique key count (= layer count). T-1047-03-03 (Tampering, stale paint after unmount) is accepted for v1 per plan decision — the worst case is one stale `setPaintProperty` on an unmounted map, caught by try/catch in flush.

## Self-Check: PASSED

- `frontend/src/lib/builder/raf-coalesce.ts` — FOUND
- `frontend/src/lib/builder/__tests__/raf-coalesce.test.ts` — FOUND
- `frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.raf.test.ts` — FOUND
- Commit `df585a50` — FOUND
- Commit `ce731464` — FOUND
- Commit `3d7cfb50` — FOUND
- Commit `f73307be` — FOUND
- Full vitest suite 1828/1828 PASS — CONFIRMED
