---
phase: 1036-settings-affordance
plan: "01"
subsystem: ui
tags: [react, builder, settings, collapsible, shadcn, vitest]

# Dependency graph
requires:
  - phase: 1035-basemap-group-folder-groups-and-dem-raster
    provides: DEMEditorScene pattern (memo, SliderRow, section collapsible chrome)
  - phase: 1034-unified-stack-rows-and-layer-editor-flyout
    provides: LayerEditorPanel collapsible pattern, Collapsible/CollapsibleTrigger/CollapsibleContent

provides:
  - SettingsEditorScene component with three collapsible sections (Terrain, Widgets, Projection)
  - SettingsEditorSceneProps interface locked for Plan 02 wiring

affects:
  - 1036-02 (wiring SettingsEditorScene into MapBuilderPage + LayerEditorPanel)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Props-driven, memoized scene component for LayerEditorPanel flyout (settings variant)
    - Collapsible section with collapsed hint per LayerEditorPanel pattern
    - Widget list from registry.getWidgets() resolved via useMemo([])
    - Projection pills as role=radiogroup with aria-checked on each role=radio button

key-files:
  created:
    - frontend/src/components/builder/SettingsEditorScene.tsx
    - frontend/src/components/builder/__tests__/SettingsEditorScene.test.tsx
  modified: []

key-decisions:
  - "WidgetDefinition uses labelKey (not label) — resolved via t(widget.labelKey, { defaultValue: widget.id })"
  - "No role/aria-label on outer div — plan specifies LayerEditorPanel owns the role=region wrapper"
  - "Switch mock in tests uses onChange→onCheckedChange bridge since shadcn Switch uses Radix UI onCheckedChange"

patterns-established:
  - "Settings scene follows exact DEMEditorScene structure: memo wrapper, SliderRow helper, no footer"
  - "Three useState(true) hooks for section open state — component-local, not persisted"

requirements-completed: [BSR-14, BSR-15]

# Metrics
duration: 18min
completed: 2026-05-13
---

# Phase 1036 Plan 01: SettingsEditorScene Component Summary

**Props-driven memoized Settings panel component with Terrain/Widgets/Projection collapsible sections, locked by 10 unit tests before MapBuilderPage wiring**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-05-13T17:00:00Z
- **Completed:** 2026-05-13T17:01:40Z
- **Tasks:** 2
- **Files modified:** 2 (created)

## Accomplishments
- Created `SettingsEditorScene.tsx` — purely presentational, memoized, props-driven; mirrors DEMEditorScene pattern exactly
- Three collapsible sections (TERRAIN, WIDGETS, PROJECTION) default to expanded; state is component-local
- Terrain section: exaggeration slider disabled with inactive hint when isTerrainActive=false; bound-layer hint when active
- Widgets section: one row per registered widget from `getWidgets()`, shadcn Switch, aria-labels reflect Enable/Disable state
- Projection section: Mercator/Globe pill radiogroup (role="radiogroup", role="radio", aria-checked); Globe disclaimer shown conditionally
- No footer — Settings has no destructive action
- 10/10 unit tests pass; TypeScript compiles clean; ESLint passes clean

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement SettingsEditorScene component** - `782a7352` (feat)
2. **Task 2: Unit-test SettingsEditorScene** - `831f274e` (test)

## Files Created/Modified
- `frontend/src/components/builder/SettingsEditorScene.tsx` — 268 lines; memoized component, SliderRow helper, SettingsEditorSceneProps interface
- `frontend/src/components/builder/__tests__/SettingsEditorScene.test.tsx` — 252 lines; 10 test cases covering all props-contract behaviors

## Decisions Made
- `WidgetDefinition.labelKey` (not `label`) — the actual types file uses `labelKey: string`; resolved via `t(widget.labelKey, { defaultValue: widget.id })`. The plan's interface block described a non-existent `label` field; using `labelKey` matches the real type and test mocks adapted accordingly.
- The plan specified `role="region"` on the outer div but also said "The wrapping LayerEditorPanel owns the role=region per 1036-UI-SPEC.md § Accessibility Contract." Followed the UI-SPEC: no role/aria-label on this component's outer div.
- Switch mock in tests uses `onChange` → `onCheckedChange` bridge (shadcn Switch uses Radix UI's `onCheckedChange` callback, not DOM `onChange`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test aria-label assertions corrected after first run**
- **Found during:** Task 2 (unit tests) — first run
- **Issue:** Test assertions used `widgets.measurement.label` (the labelKey string) as expected text, but the t() mock resolves `t(labelKey, { defaultValue: widget.id })` → renders the widget id ("measurement", "legend")
- **Fix:** Updated text assertions to match actual rendered strings; aria-label assertions corrected from `/Enable widgets\.measurement\.label widget/i` to `/Enable measurement widget/i`
- **Files modified:** `SettingsEditorScene.test.tsx`
- **Verification:** All 10 tests pass
- **Committed in:** `831f274e` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — test assertion bug)
**Impact on plan:** Minor; no source code changes. Tests correctly match the component behavior.

## Issues Encountered
- `--reporter=basic` flag not supported in this vitest version; used bare `vitest run` instead.

## Plan 02 Readiness

`SettingsEditorScene` and `SettingsEditorSceneProps` are ready to consume. Plan 02 can:
- Import `SettingsEditorScene` from `@/components/builder/SettingsEditorScene`
- Import `SettingsEditorSceneProps` for type-safe prop passing
- Wire all five callbacks (`onExaggerationChange`, `onToggleWidget`, `onSetProjection`, etc.) from `MapBuilderPage`
- The component contract is locked by tests — no ambiguity about behavior.

## Self-Check

- [x] `frontend/src/components/builder/SettingsEditorScene.tsx` exists (268 lines, min_lines=180 PASS)
- [x] `frontend/src/components/builder/__tests__/SettingsEditorScene.test.tsx` exists (252 lines, min_lines=150 PASS)
- [x] Commit `782a7352` exists (feat: implement SettingsEditorScene)
- [x] Commit `831f274e` exists (test: add 10 unit tests)
- [x] TSC clean, ESLint clean, 10/10 tests pass

## Self-Check: PASSED

---
*Phase: 1036-settings-affordance*
*Completed: 2026-05-13*
