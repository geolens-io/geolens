---
phase: 1052
plan: 01
subsystem: builder
tags: [builder, dead-code-removal, basemap-sublayer, path-a-remove, emrg-fn-01]
dependency_graph:
  requires: []
  provides: [EMRG-FN-01-surface-deleted]
  affects: [BasemapSublayerEditorScene, MapBuilderPage]
tech_stack:
  added: []
  patterns: [inline-disposition-comment, remove-over-fix]
key_files:
  modified:
    - frontend/src/components/builder/BasemapSublayerEditorScene.tsx
    - frontend/src/pages/MapBuilderPage.tsx
decisions:
  - "Path A REMOVE (not Path B FIX) — mirrors v1011 INV-01 precedent; dead stubs since v1008"
  - "3 remaining TODO(BUILDER-SUBLAYER-PERSIST) in live logic code preserved — they document intentional markDirty() omissions, not dead stubs"
metrics:
  duration: "~12 minutes"
  completed: "2026-05-18T17:31:52Z"
  tasks_completed: 3
  files_changed: 2
---

# Phase 1052 Plan 01: EMRG-FN-01 Path A REMOVE — Basemap Sublayer Dead-Stub Surface Deletion

**One-liner:** Removed STROKE section + zoom inputs + 5 no-op TODO(BUILDER-SUBLAYER-PERSIST) callbacks from BasemapSublayerEditorScene; opacity slider + Reset section (live consumers) preserved.

## What Shipped

Surface deletion of the 5 dead-stub callbacks and their corresponding JSX from `BasemapSublayerEditorScene.tsx`, plus removal of the 11 hardcoded literal props and 5 no-op callback props from the `MapBuilderPage.tsx` call site.

### Files Changed

**`frontend/src/components/builder/BasemapSublayerEditorScene.tsx`** (-141 lines net)
- Removed `StyleColorPicker` and `Input` imports (no longer referenced)
- Extended the Phase 1051 Plan 11 INV-01 disposition comment block with a second paragraph covering EMRG-FN-01 closure
- Removed 11 props from `BasemapSublayerEditorSceneProps` interface: `strokeColor`, `strokeWidth`, `casingColor`, `casingWidth`, `minZoom`, `maxZoom`, `onStrokeColorChange`, `onStrokeWidthChange`, `onCasingColorChange`, `onCasingWidthChange`, `onZoomChange`
- Removed same 11 identifiers from function signature destructure
- Removed entire STROKE section JSX block (`{/* 1. Stroke section */}` — color picker, width slider, casing color picker, casing width slider)
- Removed zoom range inputs from VISIBILITY section (`{/* Zoom range */}` — min/max zoom `<Input>` fields with Phase 1051 WR-05 clamp logic)
- Re-numbered section comments: "1. Visibility section — opacity only" and "2. Reset section"
- Surviving sections: Visibility (opacity slider only) + Reset (collapsible with confirm flow)
- Surviving props: `sublayerId`, `sublayerName`, `opacity`, `onOpacityChange`, `onResetSublayer`

**`frontend/src/pages/MapBuilderPage.tsx`** (-12 lines net)
- Removed 6 hardcoded literal props: `strokeColor="#888888"`, `strokeWidth={1}`, `casingColor="#FFFFFF"`, `casingWidth={0}`, `minZoom={0}`, `maxZoom={22}`
- Removed 5 no-op callback props with TODO comments: `onStrokeColorChange`, `onStrokeWidthChange`, `onCasingColorChange`, `onCasingWidthChange`, `onZoomChange`
- Removed inner TODO comment from `onResetSublayer` body (the live handler itself preserved)
- `editorScene === 'basemap-sublayer'` branch preserved (opacity + reset still live)
- Surviving props at call site: `sublayerId`, `sublayerName`, `opacity`, `onOpacityChange`, `onResetSublayer`

### Pre/Post Grep Counts

| Target | Pre | Post |
|--------|-----|------|
| `onStrokeColorChange\|onStrokeWidthChange\|onCasingColorChange\|onCasingWidthChange` in `frontend/src/` (excl. tests) | 8 hits in 2 files | 2 hits (disposition comment only) |
| `TODO(BUILDER-SUBLAYER-PERSIST)` in call-site JSX | 5 | 0 |
| `TODO(BUILDER-SUBLAYER-PERSIST)` total in `frontend/src/` | 9 | 4 (1 in disposition comment + 3 in live logic) |

### Surviving JSX Sections

After removal, `BasemapSublayerEditorScene` renders:
1. **Visibility section** — opacity `<Slider>` only (live, wired to `onOpacityChange → handleSublayerOpacityChange`)
2. **Reset section** — collapsible with destructive confirm flow (live, wired to `onResetSublayer → setSublayerState mutation`)

### Disposition Comment Final Text (lines 16-30)

```
// Phase 1051 Plan 11 (INV-01): DETAIL LEVEL pill strip removed — dead wiring.
// The activeDetailLevel/isCustomized/onDetailLevelChange props were always passed
// hardcoded defaults from MapBuilderPage; no consumer ever implemented sublayer
// detail-level style mutation. Removed rather than fix because a real consumer
// requires a multi-day MapLibre style-mutation implementation (out of v1011 scope
// per REQUIREMENTS.md Out-of-Scope row 1).
//
// Phase 1052 Plan 01 (EMRG-FN-01): STROKE section + zoom range inputs + 5
// stub callbacks removed. Same Phase 1038 root cause — onStrokeColorChange,
// onStrokeWidthChange, onCasingColorChange, onCasingWidthChange, and
// onZoomChange were all `TODO(BUILDER-SUBLAYER-PERSIST)` no-ops. Path A
// REMOVE chosen for v1011.1 hygiene close (Path B FIX is a 3-5 day feature
// phase per REQUIREMENTS.md Out of Scope). Live consumers preserved:
// opacity slider (onOpacityChange → handleSublayerOpacityChange) and Reset
// section (onResetSublayer → setSublayerState mutation).
```

## Commit

| Hash | Subject |
|------|---------|
| `3629ec04` | `refactor(1052): EMRG-FN-01 Path A REMOVE — basemap sublayer dead-stub surface deletion` |

Files in commit: `BasemapSublayerEditorScene.tsx` + `MapBuilderPage.tsx` (+ `.planning/PROJECT.md` which was pre-staged by GSD init — see Deviations).

## Deviations from Plan

### Deviation 1 — grep verification condition overconstrained

**Plan claimed:** "`git grep` for `TODO(BUILDER-SUBLAYER-PERSIST)` returns 0 hits"

**Actual:** 4 hits remain after the removal:
- 1 hit in `BasemapSublayerEditorScene.tsx` (the new disposition comment, which intentionally names the TODO pattern)
- 3 hits in `MapBuilderPage.tsx` at lines 270, 466, 477 — these are in live business logic:
  - Line 270: tracks that `sublayerState` is not yet included in the save payload
  - Line 466: tracks that `markDirty()` is intentionally omitted from `handleSublayerVisibilityChange`
  - Line 477: tracks that `markDirty()` is intentionally omitted from `handleSublayerOpacityChange`

**Assessment:** These 3 are NOT dead stubs — they document active implementation constraints (why markDirty() is omitted). Removing them would lose critical maintenance context about why the unsaved-changes badge is deliberately suppressed for sublayer state. The plan's grep check targeted the 5 JSX prop stubs; the live-logic TODOs were a pre-existing broader set not identified as in-scope for Plan 01. All 5 call-site JSX stubs are confirmed gone. **Rule 2 does not apply — removing the live-logic TODOs would delete load-bearing comments.**

### Deviation 2 — .planning/PROJECT.md included in commit

**Cause:** `.planning/PROJECT.md` was pre-staged by the GSD orchestrator init before this plan ran. `git status --short` showed it with `M ` (staged, not modified) prior to my `git add` call.

**Impact:** Commit touches 3 files instead of 2. The extra file is planning infrastructure (not source code). No correctness impact.

## Verification

- `npx tsc --noEmit`: 0 errors
- `git grep` for `onStrokeColorChange|onStrokeWidthChange|onCasingColorChange|onCasingWidthChange` in non-test `frontend/src/`: only 2 hits in the disposition comment block (expected)
- All 5 `TODO(BUILDER-SUBLAYER-PERSIST)` no-op callback props at the call site: removed
- Live opacity slider (`onOpacityChange → handleSublayerOpacityChange`): preserved
- Live Reset section (`onResetSublayer → setSublayerState`): preserved
- `editorScene === 'basemap-sublayer'` branch in MapBuilderPage: preserved
- `BasemapSublayerEditorFooter` (Back to basemap button): preserved

## Self-Check: PASSED

- [x] `frontend/src/components/builder/BasemapSublayerEditorScene.tsx` modified and committed
- [x] `frontend/src/pages/MapBuilderPage.tsx` modified and committed
- [x] Commit `3629ec04` exists on main
- [x] TypeScript typecheck: 0 errors
- [x] Disposition comment block: 2 paragraphs (INV-01 + EMRG-FN-01)
- [x] All 5 dead-stub callback props removed from interface, destructure, and call site
