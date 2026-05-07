---
phase: 258-line-gradient-ui-closeout
plan: 02
subsystem: frontend/builder
tags: [ui-polish, line-gradient, stable-keys, uuid, vitest]
dependency_graph:
  requires: [258-01]
  provides: [stable-stop-keys, uuid-hydration, legacy-stop-migration]
  affects: [frontend/src/types/api.ts, frontend/src/components/builder/LineGradientControls.tsx]
tech_stack:
  added: []
  patterns: [crypto.randomUUID, useRef-memoized-hydration, WorkingStop-type]
key_files:
  created: []
  modified:
    - frontend/src/types/api.ts
    - frontend/src/components/builder/LineGradientControls.tsx
    - frontend/src/components/builder/__tests__/LineGradientControls.test.tsx
decisions:
  - "Memoize UUID assignment via useRef (hydratedStopsRef) keyed on source array reference identity — preserves ids across re-renders without useMemo or useEffect"
  - "WorkingStop type (id: string required) enforces at compile time that liveStops always have ids; BuilderStyleConfig keeps id?: string for JSONB backward compat"
  - "Pre-existing test at line 91 (GRAD-04 activateGradient) updated to use expect.arrayContaining + expect.objectContaining to accommodate id fields — GRAD-04 invariant preserved"
  - "stopsToLineGradientExpression() unchanged — structural subtyping means WorkingStop[] is accepted; id field is never read"
metrics:
  duration: "~6 minutes"
  completed_date: "2026-05-07"
  tasks_completed: 2
  files_changed: 3
---

# Phase 258 Plan 02: Stable Per-Stop UUID Keys (POLISH-06) Summary

One-liner: Per-stop UUIDs in BuilderStyleConfig with ref-memoized hydration give stable React keys and eliminate wrong-popover artifacts on midpoint addStop insertion.

## REQ-ID Landing Notes

### POLISH-06 — Stable per-stop React keys

**Type extension — `frontend/src/types/api.ts` line 746:**

```typescript
stops: Array<{ position: number; color: string; id?: string }>;
```

Added `id?: string` to `BuilderStyleConfig.lineGradient.stops` element shape. Optional for backward compat with legacy JSONB (saved maps without IDs). Comment documents GRAD-05/06 contract: id is JSONB-only, never emitted to canonical paint expression.

**WorkingStop type — `frontend/src/components/builder/LineGradientControls.tsx` line 21:**

```typescript
type WorkingStop = { position: number; color: string; id: string };
```

Required `id` (non-optional) enforces the runtime invariant that `liveStops` always has ids post-hydration.

**ensureStopIds() helper — line 23:**

```typescript
function ensureStopIds(stops: ReadonlyArray<{ position: number; color: string; id?: string }>): WorkingStop[] {
  return stops.map((s) => ({ position: s.position, color: s.color, id: s.id ?? crypto.randomUUID() }));
}
```

First `crypto.randomUUID()` call site — assigns UUID only when `id` is absent (legacy stops).

**liveStops hydration with memoized ref — lines 146-171:**

`hydratedStopsRef` tracks `{ source: array-reference, hydrated: WorkingStop[] }`. When `liveStopsSource === hydratedStopsRef.current.source` and lengths match, the previous hydrated array is reused (IDs preserved across re-renders). New source reference triggers a fresh `ensureStopIds()` call.

**activateGradient fallback — line 206:**

```typescript
const stops: WorkingStop[] =
  liveStops && liveStops.length >= 2
    ? liveStops
    : ensureStopIds([...DEFAULT_GRADIENT_STOPS]);
```

DEFAULT_GRADIENT_STOPS are id-less; `ensureStopIds()` assigns fresh UUIDs before use.

**addStop UUID generation — line 245:**

```typescript
{ position: newPosition, color: last.color, id: crypto.randomUUID() }
```

Second `crypto.randomUUID()` call site — fresh UUID for the inserted stop.

**React key change — line 385:**

```tsx
<div key={stop.id} className="space-y-1">
```

Changed from `key={idx}` (index-based, unstable on sorted insertion) to `key={stop.id}` (stable UUID). Eliminates DOM node reuse across index shifts when a midpoint stop is inserted.

**commitStops parameter type — line 175:**

```typescript
function commitStops(nextStops: WorkingStop[]) {
```

Changed from `Array<{ position: number; color: string }>`. `stopsToLineGradientExpression(nextStops)` continues to work via structural subtyping — the function only reads `position` and `color`, the `id` field is transparently ignored. GRAD-05/06 byte-identity preserved.

## stopsToLineGradientExpression — UNCHANGED (GRAD-05/06 contract)

Function body at lines 75-81 reads only `s.position` and `s.color` via `tail.push(s.position, s.color)`. The `id` field is never accessed. Canonical paint output is byte-identical to v13.9 regardless of whether stops carry ids.

Verified: `stopsToLineGradientExpression([{position:0,color:'#000',id:'aaa'},{position:1,color:'#fff',id:'bbb'}])` equals `['interpolate',['linear'],['line-progress'],0,'#000',1,'#fff']` — same as without ids.

## New Vitest Tests — All 4 POLISH-06 Tests PASS

Full test run output: `Tests  42 passed (42)` — 38 pre-existing + 4 new.

New tests in `describe('LineGradientControls — stable stop keys (Phase 258)')`:

| Test | Status |
|------|--------|
| polish-06: stopsToLineGradientExpression strips id from canonical paint output | PASS |
| polish-06: addStop assigns a fresh id to the new stop and preserves existing ids | PASS |
| polish-06: legacy builder stops without ids get assigned ids at first hydration | PASS |
| polish-06: midpoint insertion preserves React identity of pre-existing stop rows (key=stop.id) | PASS |

## v13.9 Invariant Test Confirmation — All Pre-Existing Tests PASS

All 38 pre-existing tests continue to pass including:

| Invariant | Test | Status |
|-----------|------|--------|
| GRAD-04 (expression-identity) | `ui: clicking Gradient commits a default 2-stop line-gradient to BOTH paint and builder (with next paint)` | PASS |
| GRAD-05/06 (byte-identity) | `parser: stops -> line-gradient expression -> stops round-trips bit-for-bit` | PASS |
| WR-02 (pendingPositionEdits clears) | `ui: pendingPositionEdits clears on commitStops...` | PASS |
| WR-03 (savedGradientExprRef) | `ui: Solid -> Gradient toggle restores a previously-preserved non-canonical expression` | PASS |
| WR-04 (atomic solid transition) | `ui: activateSolid is atomic — single onPaintProp(line-gradient, undefined) + composed onBuilderChange` | PASS |
| IN-02 (customExpression hint) | `ui: non-canonical line-gradient paint expression renders customExpression hint instead of stops` | PASS |
| IN-03 (monotonic warning uses pending position) | `ui: monotonic warning uses displayed (pending) position` | PASS |

All Plan 258-01 tests (9 POLISH tests) also pass.

## CI Gate Results (Task 2)

- `pnpm tsc --noEmit`: exit 0
- `pnpm lint` (`eslint .`): exit 0 (1 pre-existing warning about unused eslint-disable directive at line 220 — existed before this plan, same as 258-01)
- `pnpm test` (full vitest suite): exit 0 — **130 test files, 1183 tests passed, 8 todo**

## Backend and SDK

No backend files modified. No SDK regen required. The `id?: string` addition lives in `BuilderStyleConfig.lineGradient.stops` element shape — a frontend-only TypeScript interface. The backend keeps `style_config` as opaque JSONB (`dict[str, Any]`).

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | `cc5a7138` | feat(builder): stable per-stop UUID keys for line-gradient stops (POLISH-06) |
| Task 2 | no-op | Full CI gate green; no uncommitted changes |

## Deviations from Plan

### Auto-adjusted: Pre-existing GRAD-04 test assertion updated for id-bearing stops

- **Found during:** Task 1 (test run after implementation)
- **Issue:** The pre-existing test `ui: clicking Gradient commits a default 2-stop line-gradient to BOTH paint and builder (with next paint)` asserted `{ stops: [...DEFAULT_GRADIENT_STOPS] }` (stops without `id`). After POLISH-06, `commitStops` passes `WorkingStop[]` with UUIDs — `toHaveBeenCalledWith` deep-equality check failed because actual stops had extra `id` fields.
- **Fix:** Updated assertion to `expect.arrayContaining([expect.objectContaining({position,color})])` pattern. The GRAD-04 invariant (gradient activation commits correct expression + nextPaint) remains fully tested — only the stop-shape assertion was relaxed to accommodate the new optional `id` field.
- **Classification:** Rule 1 auto-fix (test was failing due to the plan's own type change; assertion needed updating to reflect new stop shape without losing the invariant lock)
- **Files modified:** `LineGradientControls.test.tsx` (1 assertion block, lines 91-94)

## Self-Check

Created files:
- [x] `.planning/phases/258-line-gradient-ui-closeout/258-02-SUMMARY.md` — this file

Commits:
- [x] `cc5a7138` exists in git log

Modified files (verified present):
- [x] `frontend/src/types/api.ts` — `id?: string` in lineGradient.stops (line 746)
- [x] `frontend/src/components/builder/LineGradientControls.tsx` — `type WorkingStop`, `ensureStopIds`, `hydratedStopsRef`, `key={stop.id}`, 2x `crypto.randomUUID()`
- [x] `frontend/src/components/builder/__tests__/LineGradientControls.test.tsx` — `describe('LineGradientControls — stable stop keys (Phase 258)')` with 4 new tests
