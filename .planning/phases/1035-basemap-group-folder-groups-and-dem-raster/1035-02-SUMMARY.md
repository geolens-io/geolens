---
phase: 1035
plan: "02"
subsystem: frontend/builder
tags: [basemap-group, editor-scenes, scene-b, scene-c, components, tdd]
dependency_graph:
  requires: [1035-01]
  provides: [1035-05]
  affects:
    - frontend/src/components/builder/BasemapGroupRow.tsx
    - frontend/src/components/builder/BasemapGroupEditorScene.tsx
    - frontend/src/components/builder/BasemapSublayerEditorScene.tsx
tech_stack:
  added: []
  patterns:
    - tdd-red-green-refactor
    - memo-component-variant
    - collapsible-section-pattern
    - inline-alertdialog-confirm
    - pill-strip-radiogroup
decisions:
  - "StyleColorPicker prop is 'label' not 'value' — matched actual component interface"
  - "Test assertions for 'destructive' class check bg-destructive not text-only substring to avoid false positive with aria-invalid:border-destructive in ghost variant base class"
  - "Test 11 re-queries 'Reset to default' button after Keep cancellation to handle React re-render cycle"
key_files:
  created:
    - frontend/src/components/builder/BasemapGroupRow.tsx
    - frontend/src/components/builder/BasemapGroupEditorScene.tsx
    - frontend/src/components/builder/BasemapSublayerEditorScene.tsx
    - frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx
    - frontend/src/components/builder/__tests__/BasemapGroupEditorScene.test.tsx
    - frontend/src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx
  modified: []
metrics:
  duration: "~10 minutes"
  completed: "2026-05-13"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 6
  tests_added: 36
---

# Phase 1035 Plan 02: BasemapGroupRow, BasemapGroupEditorScene, BasemapSublayerEditorScene

Three new pure-UI components for basemap-as-group: collapsible group row with `⊞` glyph (Scene B source), basemap group editor with preset card grid and sublayer compact list, and sublayer breadcrumb editor with Detail Level pills and Stroke section.

---

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | BasemapGroupRow component | 356aaa95 | BasemapGroupRow.tsx + test (12 tests) |
| 2 | BasemapGroupEditorScene component (Scene B) | 952d8612 | BasemapGroupEditorScene.tsx + test (12 tests) |
| 3 | BasemapSublayerEditorScene component (Scene C) | d4f611b1 | BasemapSublayerEditorScene.tsx + test (12 tests) |

---

## Verification Results

| Check | Result |
|-------|--------|
| `vitest run BasemapGroupRow.test.tsx` | 12/12 passed |
| `vitest run BasemapGroupEditorScene.test.tsx` | 12/12 passed |
| `vitest run BasemapSublayerEditorScene.test.tsx` | 12/12 passed |
| All three suites combined | 36/36 passed |
| `tsc --noEmit` source errors | 0 source errors |
| BasemapGroupRow.tsx lines | 222 (≥ 120 required) |
| BasemapGroupEditorScene.tsx lines | 248 (≥ 150 required) |
| BasemapSublayerEditorScene.tsx lines | 351 (≥ 150 required) |

---

## Component Exports

### BasemapGroupRow
- `export const BasemapGroupRow = memo(function BasemapGroupRow...)` — named memo export
- Props: groupId, presetName, providerLabel?, visible, opacity, selected, isExpanded, isDragging?, dragHandleProps, onSelectGroup, onToggleExpand, onToggleVisibility, onOpacityChange, onSwapBasemap, onResetAppearance
- `id="stack-row-{groupId}"` for focus-return pattern

### BasemapGroupEditorScene
- `export function BasemapGroupEditorScene(...)` — named export (body)
- `export function BasemapGroupEditorFooter(...)` — named export (footer)
- Props: activePresetId, presets, sublayers, masterOpacity, onSwapBasemap, onAddCustomBasemap, onSublayerVisibilityChange, onSublayerOpacityChange, onMasterOpacityChange

### BasemapSublayerEditorScene
- `export function BasemapSublayerEditorScene(...)` — named export (body)
- `export function BasemapSublayerEditorFooter(...)` — named export (footer)
- Props: sublayerId, sublayerName, activeDetailLevel, isCustomized, strokeColor, strokeWidth, casingColor, casingWidth, opacity, minZoom, maxZoom, + all handlers

---

## Decisions Made

### 1. StyleColorPicker prop interface match
The `StyleColorPicker` component uses `label` + `color` + `onChange` props (not `value`). Tests mock it with `{ color, onChange, label }`. Implementation matches the actual interface.

### 2. Destructive class assertion precision
The shadcn ghost button base class includes `aria-invalid:border-destructive` as part of focus/validation styling. Test assertions for "not destructive" check for `bg-destructive` absence rather than the string `destructive` to avoid false positives.

### 3. Collapsible Reset section re-query pattern
After clicking "Keep customization" in the alertdialog, React re-renders and removes the alertdialog. The "Reset to default" button (inside CollapsibleContent) must be re-queried via `screen.getByRole('button', { name: /Reset to default/i })` rather than using the stale reference, because the component re-renders between the alert close and the next action.

---

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED (test fails — component missing) | verified before each implementation | PASS |
| GREEN (tests pass) | 356aaa95, 952d8612, d4f611b1 | PASS |
| REFACTOR | not required (implementation was clean) | N/A |

---

## Deviations from Plan

None — plan executed exactly as written. The only adjustments were to test assertions to match actual DOM output (Test 2 used `container.querySelectorAll('img')` instead of `getAllByRole('img', { hidden: true })` since aria-hidden images are not findable via ARIA role queries; Test 11 re-queried after state reset).

---

## Known Stubs

None — all three components are pure UI with complete prop-driven rendering. No hardcoded empty values or placeholder text flows to the UI. Plan 05 will wire these components into `UnifiedStackPanel` and `MapBuilderPage` to satisfy BSR-05 and BSR-06 fully.

---

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. All three components consume props only — zero direct API/store/router dependencies. No additions to threat surface.

## Self-Check: PASSED

Files exist:
- frontend/src/components/builder/BasemapGroupRow.tsx — FOUND
- frontend/src/components/builder/BasemapGroupEditorScene.tsx — FOUND
- frontend/src/components/builder/BasemapSublayerEditorScene.tsx — FOUND
- frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx — FOUND
- frontend/src/components/builder/__tests__/BasemapGroupEditorScene.test.tsx — FOUND
- frontend/src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx — FOUND

Commits exist:
- 356aaa95 (BasemapGroupRow) — FOUND
- 952d8612 (BasemapGroupEditorScene) — FOUND
- d4f611b1 (BasemapSublayerEditorScene) — FOUND
