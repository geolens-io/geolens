---
phase: 1050
plan: 04
subsystem: frontend/builder/hooks
tags: [smoke-carryover, sf-07, debounce, thumbnail, strict-mode]
requires: []
provides: [single-PUT-per-initial-map-mount]
affects:
  - frontend/src/components/builder/hooks/use-builder-save.ts
tech-stack:
  added: []
  patterns: [module-level-per-entity-guard]
key-files:
  created: []
  modified:
    - frontend/src/components/builder/hooks/use-builder-save.ts
    - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
decisions:
  - "Fix Option C (module-level guard) — per-instance `thumbCaptured` ref + module-level `pendingCaptures` Map alone do NOT survive Vite-dev StrictMode hook remount; need an additional module-scoped Set keyed by mapId"
metrics:
  duration: "~15 min"
  completed: 2026-05-17
---

# Phase 1050 Plan 04: Debounce thumbnail PUT — SF-07 closure

**One-liner:** Add module-level per-mapId auto-capture guard in `use-builder-save.ts` so a StrictMode-driven hook remount cannot bypass the per-instance `thumbCaptured` ref and trigger a second `PUT /thumbnail/`.

## Diagnosis

### Phase 1 — grep audit (read-only)

**`runCaptureNow` call sites** in `use-builder-save.ts` (pre-fix):
- Line 146: inside `captureThumbnail`'s `setTimeout` body — the legitimate debounced fire path.
- Line 113: the function declaration itself.

Result: **2 mentions total, 1 call site, no bypass.** Every PUT-firing path routes through `captureThumbnail` first. No paint-settle or `map.on('idle' | 'sourcedataloading' | 'styledata')` direct-fire path exists (Fix Option B ruled out).

**`captureThumbnail` call sites** in `use-builder-save.ts` (pre-fix):
- Line 427: `handleSave` fallback-replacement path (when patchMapLayers fails with unsupported error → updateMap full replacement)
- Line 442: `handleSave` success path
- Line 538: `maybeAutoCaptureThumbnail` (the auto-capture entry point invoked from `MapBuilderPage.handleMapRef` at `MapBuilderPage.tsx:213`)

Result: **3 call sites, all routing through the debounce wrapper.** Per-instance `thumbCaptured.current = true` is set on line 536 BEFORE the `captureThumbnail` call on line 538 (Fix Option A's hypothesis — "set after instead of before" — also ruled out by inspection).

### Phase 1 — caller-side audit

`MapBuilderPage.tsx:210-215`:
```typescript
const handleMapRef = useCallback((map: MaplibreMap | null) => {
  mapInstanceRef.current = map;
  setMapInstance(map);
  if (map) save.maybeAutoCaptureThumbnail(map);
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [save.maybeAutoCaptureThumbnail]);
```

This is a **ref callback**, not a `useEffect`. React invokes ref callbacks twice in StrictMode dev: `callback(map)` → `callback(null)` (unmount) → `callback(map)` (remount). Combined with the `useCallback` dep `save.maybeAutoCaptureThumbnail`, which itself depends on `state.hasThumbnail, state.mapId, queryClient` — the callback identity changes when `mapData?.thumbnail_url` flips (e.g. when the GET /maps/{id} response resolves), so the ref-callback may also be re-invoked even outside StrictMode.

### Phase 1 — root cause (the actual mechanism)

**Module-level `pendingCaptures` is NOT enough.** It is cleared the moment the trailing-edge `setTimeout` body fires (line 145: `pendingCaptures.delete(mapId)`). So the sequence that produces the double-PUT is:

1. `useBuilderSave` mounts (instance #1). `thumbCaptured.current === false`.
2. `MapBuilderPage.handleMapRef` fires with the map → calls `maybeAutoCaptureThumbnail(map)`.
3. Per-instance guard passes (`thumbCaptured.current === false`, `hasThumbnail === false`, `mapId === 'X'`).
4. `thumbCaptured.current = true`. `captureThumbnail('X', ...)` schedules a setTimeout for `t = 500ms`. `pendingCaptures.set('X', timer)`.
5. At `t = 500ms`: setTimeout body fires. `pendingCaptures.delete('X')`. `runCaptureNow(...)` → `doCapture(...)` → `uploadThumbnail(...)` — **PUT #1 issued**.
6. **StrictMode unmounts `useBuilderSave` instance #1.** All `useRef`s go away. The cleanup `useEffect` runs (`captureSignalRef.current.cancelled = true`).
7. **StrictMode remounts `useBuilderSave` instance #2.** `thumbCaptured.current === false` again (fresh ref). `localLayersRef`, `captureSignalRef` also fresh.
8. `MapBuilderPage.handleMapRef` fires again (same `map` ref) → calls `maybeAutoCaptureThumbnail(map)` on instance #2.
9. Per-instance guard passes AGAIN because `thumbCaptured.current === false` on the new instance.
10. `thumbCaptured.current = true`. `captureThumbnail('X', ...)` checks `pendingCaptures.get('X')` — it's `undefined` (was deleted in step 5). Schedules a NEW setTimeout for `t' = 500ms`.
11. At `t' = 500ms`: setTimeout fires. `runCaptureNow(...)` → `doCapture(...)` → `uploadThumbnail(...)` — **PUT #2 issued.**

This reproduces the smoke evidence "consecutive PUTs at network log entries 395, 396" perfectly: two PUTs separated by ~500ms (= the gap between the first capture's debounce fire and the second capture's debounce fire, which itself starts shortly after the StrictMode remount).

**Why Fix Option A (move `thumbCaptured.current = true` earlier) doesn't help:** it's already set before `captureThumbnail` in the original code. The ref doesn't survive across hook instances regardless of where it's set.

**Why Fix Option B (route paint-settle through `captureThumbnail`) doesn't apply:** there's no direct-call `runCaptureNow` path. All PUT-firing paths already go through `captureThumbnail`.

## Fix applied — Fix Option C (module-level guard)

### Change: `frontend/src/components/builder/hooks/use-builder-save.ts`

Added a module-scoped `Set<string>` named `autoCapturedMapIds` and a helper `shouldAutoCapture(mapId)` (lines 138-167 in post-fix file). The helper returns `true` on the FIRST call for a given mapId (and adds the id to the set), `false` on every subsequent call until the set is cleared.

`maybeAutoCaptureThumbnail` now consults `shouldAutoCapture(state.mapId)` BEFORE calling `captureThumbnail` (line 547 post-fix):

```typescript
const maybeAutoCaptureThumbnail = useCallback((map: MaplibreMap) => {
  if (thumbCaptured.current || state.hasThumbnail !== false || !state.mapId) return;
  // SF-07: per-instance ref doesn't survive StrictMode unmount/remount.
  // Module-level shouldAutoCapture owns the "already initiated for this
  // mapId this session" invariant.
  if (!shouldAutoCapture(state.mapId)) {
    thumbCaptured.current = true; // keep the instance ref consistent
    return;
  }
  thumbCaptured.current = true;
  captureSignalRef.current = { cancelled: false };
  captureThumbnail(map, state.mapId, queryClient, localLayersRef.current, captureSignalRef.current);
}, [state.hasThumbnail, state.mapId, queryClient]);
```

`__resetThumbnailDebounceForTests()` was extended to also clear `autoCapturedMapIds`, preserving test isolation.

**Line ranges modified:** `use-builder-save.ts:123-181` (was `:123-157` pre-fix; +24 lines for new module-level guard + helper + docstring; +5 lines for the new gate inside `maybeAutoCaptureThumbnail`).

### Test deltas: `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts`

- **Pre-fix:** 1124 lines, 40 tests, 40 passing.
- **Post-fix:** 1259 lines, 43 tests, 43 passing.

New `describe('SF-07 — single PUT per initial map mount', ...)` block with 3 cases inside the existing `describe('maybeAutoCaptureThumbnail', ...)`:

1. **Synchronous double-call collapses to one PUT** — sanity test for the existing per-instance guard + module-level debounce. **Passed pre-fix and post-fix** (existing behavior preserved).
2. **StrictMode-style hook remount does NOT fire a second PUT** — the bug reproducer. Mounts a hook, fires auto-capture, advances 500ms, drives the first PUT, unmounts the hook, mounts a fresh hook with the same `mapId`, fires auto-capture again. Asserts the render-frame registration count is unchanged. **Failed pre-fix** (`expected 2 to be 1` on render-frame registration count); **passes post-fix**.
3. **`__resetThumbnailDebounceForTests` also clears the new guard** — verifies the reset helper's contract; ensures that after the reset, a fresh hook instance for the same `mapId` may auto-capture again (the "page navigation / fresh session" scenario). **Passes post-fix.**

## Before/after PUT counts (from new test 2)

| Scenario | Pre-fix render-frame registrations | Post-fix render-frame registrations |
|---|---|---|
| First hook instance auto-capture | 1 | 1 |
| Second hook instance (StrictMode remount) auto-capture for same mapId | **2 (BUG)** | **1 (FIXED)** |

Each render-frame registration corresponds 1:1 to a `PUT /api/maps/{mapId}/thumbnail/` (via `doCapture` → `uploadThumbnail`). The fix collapses the two-PUT case to one PUT.

## Acceptance criteria (from PLAN.md)

| Criterion | Result |
|---|---|
| Diagnosis documented (which Fix Option, why) | ✓ Fix Option C — module-level guard. Per-instance ref + module-level debounce alone are not StrictMode-safe. |
| All 3 new tests pass | ✓ 3/3 |
| Existing `use-builder-save.test.ts` tests continue to pass | ✓ 43/43 |
| Typecheck exits 0 | ✓ `npx tsc --noEmit` clean |
| `grep -c "runCaptureNow"` ≤ pre-fix count | ✓ 2 → 2 |
| `grep -c "captureThumbnail"` ≥ pre-fix count | ✓ 6 → 8 (added 2 mentions in new comments/docstring) |

## Verification gates

- `npx vitest run src/components/builder/hooks/__tests__/use-builder-save.test.ts` → 43/43 ✓
- `npx vitest run src/components/builder/hooks/ src/components/builder/__tests__/preserve-drawing-buffer.test.ts` → 144/144 ✓ (no regressions in adjacent hook tests)
- `npx vitest run src/pages/__tests__/MapBuilderPage.header-actions.test.tsx src/components/builder/__tests__/MapBuilderPage.a11y.test.tsx` → 7/7 ✓ (no regressions in the consumer)
- `npx tsc --noEmit` → 0 errors ✓
- `npx eslint src/components/builder/hooks/use-builder-save.ts src/components/builder/hooks/__tests__/use-builder-save.test.ts` → clean ✓

Live MCP confirmation (hard-reload of `/maps/{id}` fires exactly 1 PUT) is gated to Plan 06 CTRL-01 per the milestone shape.

## Deviations from plan

None — plan executed exactly as written. The "Phase 1 Diagnose" grep audit ruled out Fix Options A and B; Fix Option C was applied per the plan's third option.

## Threat Flags

None — no new network endpoints, no auth-path changes, no schema changes. The fix is purely a client-side idempotency guard.

## Commits

| Type | Hash | Message |
|---|---|---|
| test | `90b349b3` | test(1050-04): add failing test for SF-07 double-PUT on StrictMode remount |
| feat | `37fee435` | feat(1050-04): module-level guard for auto-thumbnail capture (SF-07) |

## Self-Check: PASSED

- frontend/src/components/builder/hooks/use-builder-save.ts: FOUND (modified)
- frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts: FOUND (modified)
- Commit 90b349b3: FOUND
- Commit 37fee435: FOUND
