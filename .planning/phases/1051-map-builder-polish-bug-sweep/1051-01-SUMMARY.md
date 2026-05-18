---
phase: 1051
plan: 01
subsystem: builder/visibility-toggle
tags: [builder, bugfix, visibility-toggle, regression-test, tdd, mcp-deferred]
dependency_graph:
  requires: []
  provides:
    - regression-test: "use-layer-map-sync.test.ts pins the handleToggleVisibility dispatch contract"
  affects:
    - frontend/src/components/builder/hooks/use-layer-map-sync.ts (test coverage; no production diff)
tech_stack:
  added: []
  patterns:
    - vitest module-mock pattern (mirrored from use-layer-map-sync.raf.test.ts)
key_files:
  created:
    - frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.test.ts
  modified: []
decisions:
  - "TDD-first: regression test authored against current code; all 8 cases pass → static-analysis chain is intact"
  - "No production code change committed — the handleToggleVisibility chain (StackRow → SortableStackRow → MapBuilderPage → use-builder-layers → use-layer-map-sync) is wired correctly per code inspection"
  - "Live MCP repro + post-fix verify (plan Tasks 1 + 3) deferred to orchestrator — Playwright MCP is orchestrator-scoped per MEMORY.md v1010.1"
requirements: [BUG-01]
metrics:
  duration_minutes: 8
  completed_date: 2026-05-17
  task_count: 2
  file_count: 1
  test_count: 8
---

# Phase 1051 Plan 01: Layer Visibility Toggle (BUG-01) Summary

**One-liner:** Added 8-case vitest regression test that locks in the
`handleToggleVisibility` dispatch contract for `use-layer-map-sync.ts`;
no production code change — the static-analysis chain is intact and all
tests pass against current HEAD.

## Root-cause Analysis

Per PATTERNS.md the suspected break-points for BUG-01 were:

- **Hypothesis A**: stale `layersRef` (useLayoutEffect timing) — *not reproduced*; Test 6 confirms the guard does not block valid updates.
- **Hypothesis B**: downstream `syncFromState` overwriting the imperative dispatch (live integration race) — *cannot be falsified at unit-test level*; would require live MCP capture.
- **Hypothesis C**: `applyLayerUpdate` early-exit at line 51-52 firing for unknown ids — *not reproduced* for regular layers; Test 5/6 cover both the guard and the not-blocked-by-guard cases.

The full chain was traced and confirmed wired:

| Step | File | Line | Status |
|------|------|------|--------|
| Eye button onClick | `StackRow.tsx` | 243-246 | OK |
| onToggleVisibility prop forward | `UnifiedStackPanel.tsx` (SortableStackRow) | 200, 942, 972 | OK |
| handler injection | `MapBuilderPage.tsx` | 1023 | OK |
| handler delegation | `use-builder-layers.ts` | 156 (consumes useLayerMapSync) | OK |
| dispatch + state | `use-layer-map-sync.ts` | 68-93 | OK (6 companion setLayoutProperty calls present) |

The 6 companion suffixes (`''`, `-outline`, `-label`, `-extrusion`, `-cluster`, `-cluster-count`) are all dispatched via `if (map.getLayer(...)) map.setLayoutProperty(...)` exactly as the plan's `must_haves.artifacts.contains` requirement specifies.

## Fix Description

**No production code change.** The handler chain is correct as-shipped on HEAD. Added a comprehensive regression test that pins the dispatch contract so any future drift surfaces in CI.

### Test cases (8 total — all pass)

1. **Toggles a visible layer** → setLayoutProperty('visibility', 'none') dispatched on main layer id
2. **Visible → hidden → visible round-trip** → two dispatches with 'none' then 'visible'
3. **All 6 companion suffixes** receive setLayoutProperty when they exist on the map
4. **Companion guard**: suffixes that do NOT exist are skipped via `if (map.getLayer(...))`
5. **Unknown layerId**: applyLayerUpdate early-exit fires → no state mutation, no map dispatch
6. **Valid layerId regression guard**: the early-exit must NOT fire for valid ids → state and map both touched
7. **Explicit `visible=false` param** wins over toggle logic → idempotent 'none' dispatch
8. **Synchronous dispatch**: visibility does NOT route through requestAnimationFrame (rAF coalescing is paint-only, per PERF-04 design)

## Files Modified

| File | Change | Diff |
|------|--------|------|
| `frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.test.ts` | created | +307 lines |

## Test Result

```
 RUN  v4.1.5 /Users/ishiland/Code/geolens/frontend
 Test Files  1 passed (1)
      Tests  8 passed (8)
   Duration  788ms
```

Combined with the existing `use-layer-map-sync.raf.test.ts`:
```
 Test Files  2 passed (2)
      Tests  11 passed (11)
```

TypeScript: `npx tsc --noEmit` → 0 errors.

## MCP Verification (Deferred to Orchestrator)

Plan Tasks 1 and 3 require live Playwright MCP runs against `http://localhost:8080/maps/c868cc3a-a3a0-4714-b559-67b3f2b478e2`. Per MEMORY.md v1010.1, Playwright MCP is **orchestrator-scoped** — it cannot be driven from a sequential-executor agent. These steps are deferred to the orchestrator's follow-up gate.

**For the orchestrator continuation:**

1. **Pre-fix repro (Task 1):** navigate to the repro URL, locate Layer 1 row, click eye twice, capture:
   - `aria-pressed` value on the eye button before/after each click
   - `map.getLayoutProperty('layer-{layerId}', 'visibility')` via `mcp_browser_evaluate`
   - Console output (especially any `[builder]` debug logs)
   - Whether tiles actually disappear from the map canvas

2. **If MCP confirms the bug still reproduces on live (i.e. tiles do NOT change despite the test contract being correct):**
   - The bug is in the **integration layer** (Hypothesis B), not the unit-tested hook.
   - Most likely candidate: `BuilderMap.tsx` `useEffect` at line 723 calls `syncLayersToMap` on every `layers` change. If state propagates to `localLayers` but the map ref or token gate causes early-return, `runSync(map)` skips. But the IMPERATIVE dispatch in `handleToggleVisibility` should still have fired first — UNLESS `mapInstanceRef.current` differs from `mapRef` in BuilderMap (separate refs!).
   - **Targeted next step:** confirm `mapInstanceRef` in `useBuilderLayers` and `mapRef` in `BuilderMap` point to the same MapLibre instance. If they diverge (e.g. one is stale after a basemap switch), the imperative dispatch fires on a dead map.

3. **Post-fix verify (Task 3):** if Task 1 confirms a real live bug, the targeted fix lands on top of this commit, then MCP re-verify proves the fix.

## Deviations from Plan

### Task scope

**Plan Task 1 (orchestrator MCP pre-fix repro)** — deferred. MCP is orchestrator-scoped; cannot be driven from this executor.

**Plan Task 2 (auto+tdd)** — completed as test-only commit. Static analysis + 8 passing tests show the hook is correct; no production diff written. The commit message uses the plan-prescribed `fix(builder):` subject because the commit is the symptom-fix gate (regression-test-as-spec) regardless of whether code changed.

**Plan Task 3 (orchestrator MCP post-fix verify + atomic commit)** — partial. The atomic commit landed (Task 2 commit subsumes Task 3 commit per minimal-diff principle). MCP re-verify is deferred to orchestrator as above.

### Sub-finding

None of the cross-cutting v1010.2 SF-04..08 surfaces were touched.

## Known Stubs

None.

## Self-Check: PASSED

- Created file exists: `frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.test.ts` — FOUND
- Commit `ea56ae78` exists: FOUND
- All 8 regression tests pass: VERIFIED
- TypeScript check: 0 errors VERIFIED
- `grep -n 'setLayoutProperty' use-layer-map-sync.ts` returns 6 matches (plan acceptance criterion): VERIFIED
