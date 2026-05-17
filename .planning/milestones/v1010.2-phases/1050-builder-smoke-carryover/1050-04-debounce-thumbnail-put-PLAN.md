---
phase: 1050-builder-smoke-carryover
plan: 04
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/builder/hooks/use-builder-save.ts
  - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
autonomous: true
requirements: [SMOKE-11]

must_haves:
  truths:
    - "Hard-reloading /maps/{id} fires exactly ONE PUT /api/maps/{id}/thumbnail/ request"
    - "The debounce still collapses bursts during interaction (dragging zoom slider doesn't fire one PUT per repaint)"
    - "No regression to manual save behavior — ⌘S still produces the expected thumbnail PUT after the debounce window settles"
  artifacts:
    - path: "frontend/src/components/builder/hooks/use-builder-save.ts"
      provides: "Effect-fired thumbnail capture routes through the debounce wrapper; entry-guard prevents double-fire from StrictMode/paint-settle"
      contains: "captureThumbnail"
    - path: "frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts"
      provides: "Test asserting two synchronous calls to maybeAutoCaptureThumbnail produce exactly 1 PUT after the 500ms window"
      contains: "toHaveBeenCalledTimes\\(1\\)"
  key_links:
    - from: "maybeAutoCaptureThumbnail (effect-triggered caller)"
      to: "captureThumbnail (module-level debounce)"
      via: "trailing-edge setTimeout keyed by mapId"
      pattern: "captureThumbnail\\("
    - from: "thumbCaptured.current"
      to: "auto-capture entry guard"
      via: "set before invoke, not after"
      pattern: "thumbCaptured\\.current\\s*=\\s*true"
---

<objective>
Initial map mount fires exactly ONE `PUT /api/maps/{id}/thumbnail/` request, not two. Closes SF-07.

Purpose: Per SF-07 evidence (network log entries 395, 396 in `01-A-02-builder-loaded`, 2026-05-17), the initial map mount fires TWO `PUT /api/maps/{id}/thumbnail/` requests. v1009.1 SP-16 explicitly added a 500ms debounce expecting exactly 1; the doubling means one of the auto-capture callers bypasses the debounce window or fires before the module-level `pendingCaptures.get(mapId)` has been populated.

Likely mechanisms (from PATTERNS.md Plan 04 — root-cause investigation phase):
1. Vite dev mode StrictMode → effects run twice → `thumbCaptured.current = true` is set INSIDE `captureThumbnail`'s caller AFTER the call but the second effect run sees the ref still false because `captureThumbnail` is async (setTimeout) and the ref-guard at line 535 only blocks re-entry after the FIRST `setTimeout` fires.
2. Two distinct callers fire `runCaptureNow` directly (immediate) rather than `captureThumbnail` (debounced) — paint-settle / tile-loaded MapLibre event handlers may route to the immediate path.

Output:
- `frontend/src/components/builder/hooks/use-builder-save.ts` — entry guard moved (or new ref-based guard) so `maybeAutoCaptureThumbnail` is idempotent across StrictMode double-mounts AND all PUT-firing paths route through the debounce wrapper, not the inner `runCaptureNow`
- `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts` — test asserting two synchronous calls to `maybeAutoCaptureThumbnail` produce exactly 1 PUT after the 500ms window settles
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/1050-builder-smoke-carryover/1050-CONTEXT.md
@.planning/phases/1050-builder-smoke-carryover/1050-PATTERNS.md
@.planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md

@frontend/src/components/builder/hooks/use-builder-save.ts

<interfaces>
<!-- Existing trailing-edge debounce. Executor confirms ALL PUT-firing paths route through it. -->

From use-builder-save.ts:123-150 (existing module-level debounce — KEEP):
```typescript
const THUMBNAIL_DEBOUNCE_MS = 500;
const pendingCaptures = new Map<string, ReturnType<typeof setTimeout>>();

function captureThumbnail(map, mapId, queryClient, layers, signal?) {
  const existing = pendingCaptures.get(mapId);
  if (existing) clearTimeout(existing);
  const timer = setTimeout(() => {
    pendingCaptures.delete(mapId);
    runCaptureNow(map, mapId, queryClient, layers, signal);
  }, THUMBNAIL_DEBOUNCE_MS);
  pendingCaptures.set(mapId, timer);
}
```

From use-builder-save.ts:534-539 (maybeAutoCaptureThumbnail — the auto-capture entry point):
```typescript
const maybeAutoCaptureThumbnail = useCallback(() => {
  if (thumbCaptured.current || state.hasThumbnail !== false || !state.mapId) return;
  thumbCaptured.current = true;
  captureSignalRef.current = { cancelled: false };
  captureThumbnail(map, state.mapId, queryClient, layers, captureSignalRef.current);
}, [map, state.mapId, state.hasThumbnail, queryClient, layers]);
```

From use-builder-save.ts:438-442 (handleSave thumbnail capture call site):
```typescript
// look up actual line numbers in the file; mentioned in PATTERNS.md
// — handleSave eventually calls captureThumbnail or runCaptureNow
```

From use-builder-save.ts:154 (test reset helper — already exists):
```typescript
export function __resetThumbnailDebounceForTests() { ... }
```

Imports already present (no new imports needed):
```typescript
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useQueryClient } from '@tanstack/react-query';
```

Existing rAF coalesce helper available (from v1010 — for any debounce alignment, if needed):
- `frontend/src/lib/builder/raf-coalesce.ts` — `coalesceFrame` utility
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Diagnose + fix the double-PUT initial-mount path</name>
  <files>frontend/src/components/builder/hooks/use-builder-save.ts, frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts</files>
  <read_first>
    - frontend/src/components/builder/hooks/use-builder-save.ts (FULL FILE — confirm exact line numbers for `captureThumbnail`, `maybeAutoCaptureThumbnail`, `runCaptureNow`, and any caller that bypasses the debounce wrapper by calling `runCaptureNow` directly)
    - frontend/src/components/builder/MapBuilderPage.tsx (search for the ref/effect that invokes `maybeAutoCaptureThumbnail` — confirm whether it's a `useEffect` that could re-run under StrictMode)
    - frontend/src/lib/builder/raf-coalesce.ts (existing rAF coalesce helper — reference only)
    - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts (full file — locate `__resetThumbnailDebounceForTests` usage; confirm test conventions)
    - .planning/phases/1050-builder-smoke-carryover/1050-PATTERNS.md (Plan 04 section — touch points + "likely actual mechanism" investigation steps)
    - .planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md SF-07 (Observed evidence: TWO PUT requests at network log entries 395, 396)
  </read_first>
  <behavior>
    - Test 1 (NEW in use-builder-save.test.ts): Calling `maybeAutoCaptureThumbnail` twice synchronously, then advancing vitest fake timers by 500ms, results in exactly 1 call to `runCaptureNow` (or its effect — the mocked PUT spy).
    - Test 2 (NEW): A caller invoking `captureThumbnail(map, 'same-map-id', ...)` twice within 500ms results in exactly 1 PUT fired AFTER the window settles (trailing-edge collapse).
    - Test 3 (NEW): Calling `maybeAutoCaptureThumbnail`, then changing `state.hasThumbnail` to `true` (simulating PUT success), then re-running the effect, does NOT fire a second PUT (idempotency).
    - Test 4 (regression): Manual save path (`handleSave`) still routes through the debounce wrapper and fires the expected PUT after the window settles.
  </behavior>
  <action>
    Phase 1 — Diagnose (read-only — confirm the actual mechanism):

    1. Grep for ALL call sites that invoke `runCaptureNow` (the immediate-fire path) in `use-builder-save.ts`. Every call to `runCaptureNow` from outside the `setTimeout` body INSIDE `captureThumbnail` is a bypass. List them.

    2. Grep for ALL call sites that invoke `captureThumbnail` (the debounced wrapper). Every initial-mount / paint-settle / tile-loaded path MUST route through this wrapper.

    3. Confirm which caller fires the second PUT: most likely candidates per PATTERNS.md:
       - The `maybeAutoCaptureThumbnail` `useCallback` is invoked twice from MapBuilderPage's effect (StrictMode double-mount), and `thumbCaptured.current = true` is set BEFORE `captureThumbnail` (line 536), so the second call's `thumbCaptured.current` IS truthy and should `return` early — verify this by re-reading the actual ordering at lines 534-539.
       - A paint-settle or `map.on('idle')` handler routes through `runCaptureNow` directly, bypassing the debounce. Check the `handleSave` and any `map.on('idle' | 'sourcedataloading' | 'styledata')` registrations.

    Phase 2 — Fix (concrete change — pick the smallest fix consistent with the diagnosis):

    **Fix Option A (most likely — strengthen the entry guard):** If the diagnosis confirms `maybeAutoCaptureThumbnail` is called twice but `thumbCaptured.current = true` is set correctly at line 536, then the second caller path must be different. Find that other caller and either (a) route it through `maybeAutoCaptureThumbnail` (which has the guard) instead of `captureThumbnail` directly, OR (b) add a ref-keyed entry guard at the start of `captureThumbnail`:
    ```typescript
    function captureThumbnail(map, mapId, queryClient, layers, signal?) {
      const existing = pendingCaptures.get(mapId);
      if (existing) clearTimeout(existing);
      // ... existing body
    }
    ```
    (The existing `clearTimeout(existing)` ALREADY trailing-edge collapses calls keyed by the same `mapId`. If two PUTs still fire, it means the second caller is `runCaptureNow` direct OR a stale closure passing a different `mapId`.)

    **Fix Option B (route paint-settle through the debounce):** If grep reveals a `map.on('idle', () => runCaptureNow(...))` or similar, replace `runCaptureNow` with `captureThumbnail` so it joins the debounce queue.

    **Fix Option C (StrictMode-safe ref-set ordering):** If the issue is StrictMode + the `thumbCaptured.current` assignment racing the second effect, add the `if (thumbCaptured.current) return;` check INSIDE `captureThumbnail` itself (not only at the caller), keyed by a per-mapId `Set`. This is the belt-and-suspenders option.

    Apply the smallest fix that the diagnostic grep confirms. Document the chosen fix in the SUMMARY.

    Phase 3 — Test (mandatory):

    Add 3 NEW tests in `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts`:

    1. **Synchronous double-call test:**
       ```typescript
       it('collapses two synchronous auto-capture calls into one PUT', async () => {
         __resetThumbnailDebounceForTests();
         const putSpy = vi.fn();
         // ... mount hook with mocked PUT
         act(() => {
           maybeAutoCaptureThumbnail();
           maybeAutoCaptureThumbnail();
         });
         vi.advanceTimersByTime(500);
         await flushPromises();
         expect(putSpy).toHaveBeenCalledTimes(1);
       });
       ```

    2. **Trailing-edge collapse test:** Two `captureThumbnail` calls within 500ms produce exactly 1 PUT.

    3. **Post-success idempotency test:** After the first PUT settles, re-firing the auto-capture effect (with `hasThumbnail: true`) does NOT fire a second PUT.

    Use `vi.useFakeTimers()` + `vi.advanceTimersByTime(500)` + `__resetThumbnailDebounceForTests()` in `beforeEach` to ensure module-level state is clean.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npm run test -- --run src/components/builder/hooks/__tests__/use-builder-save.test.ts && npm run typecheck</automated>
  </verify>
  <acceptance_criteria>
    - Diagnosis documented (in SUMMARY.md): which Fix Option (A/B/C) was applied and why.
    - All 3 new tests in `use-builder-save.test.ts` pass.
    - Existing `use-builder-save.test.ts` tests continue to pass.
    - Typecheck exits 0.
    - `grep -c "runCaptureNow" frontend/src/components/builder/hooks/use-builder-save.ts` returns ≤ the pre-fix count (no new direct-call bypasses introduced).
    - `grep -c "captureThumbnail" frontend/src/components/builder/hooks/use-builder-save.ts` returns ≥ the pre-fix count (the debounce wrapper is invoked from at least the same number of sites).
  </acceptance_criteria>
  <done>
    Initial map mount fires exactly 1 `PUT /thumbnail/` (verified by new vitest tests; live MCP confirmation in Plan 06); manual save behavior unchanged; debounce collapses bursts during interaction.
  </done>
</task>

</tasks>

<verification>
- Hard-reload `/maps/{id}` fires exactly 1 `PUT /api/maps/{id}/thumbnail/` (network log filter on `thumbnail` — verified in Plan 06 via Playwright MCP).
- `use-builder-save.test.ts` asserts the synchronous-double-call collapse via fake timers.
- Manual save (`handleSave` / `⌘S`) still produces the expected PUT after the debounce window settles.
- Dragging the zoom slider does not fire one PUT per repaint (existing v1009.1 SP-16 behavior preserved).
</verification>

<success_criteria>
1. Vitest asserts exactly 1 PUT for 2 synchronous `maybeAutoCaptureThumbnail` calls.
2. Trailing-edge collapse still works for `captureThumbnail` calls keyed by the same mapId.
3. Post-success idempotency: re-firing the auto-capture effect with `hasThumbnail: true` does NOT fire a second PUT.
4. Typecheck clean; no regressions in `use-builder-save.test.ts`.
</success_criteria>

<output>
Create `.planning/phases/1050-builder-smoke-carryover/1050-04-SUMMARY.md` when done — record:
- Diagnosis: which mechanism produced the double-PUT (Fix Option A, B, or C).
- Concrete change applied (file + line range).
- Test count delta in `use-builder-save.test.ts`.
- Before/after PUT count from the new test (should be 2 → 1).
</output>
