---
phase: 1037
plan: "01"
subsystem: builder-ui
tags: [empty-state, unified-stack-panel, i18n, wiring]
dependency_graph:
  requires: [1037-01 Task 1 — EmptyStackState component (commit 50717146)]
  provides: [EmptyStackState wired into UnifiedStackPanel, i18n keys for all locales]
  affects: [frontend/src/components/builder/UnifiedStackPanel.tsx]
tech_stack:
  added: []
  patterns: [renderBasemapDockRow helper extraction, optional-prop onAddDataset fallback]
key_files:
  created:
    - frontend/src/components/builder/__tests__/UnifiedStackPanel.empty-state.test.tsx
  modified:
    - frontend/src/components/builder/UnifiedStackPanel.tsx
    - frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/fr/builder.json
    - frontend/src/i18n/locales/es/builder.json
decisions:
  - isEmpty changed from layers.length === 0 && !basemapGroup to layers.length === 0 so EmptyStackState renders even when basemapGroup is present
  - renderBasemapDockRow(showEyebrow) helper extracts basemap dock rendering so it appears in both empty and populated states without duplication
  - BASEMAP eyebrow label only shown in empty state (showEyebrow=true); absent in populated state per UI-SPEC
  - onAddDataset defaults to NOOP inline rather than NOOP module-level constant since it is a leaf call with no child memo() dependencies
metrics:
  duration: "~15 minutes"
  completed: "2026-05-13T22:01:11Z"
  tasks_completed: 2
  files_changed: 7
---

# Phase 1037 Plan 01: Wire EmptyStackState into UnifiedStackPanel Summary

Wire EmptyStackState component into UnifiedStackPanel with basemap dock always visible, onAddDataClick/onAddDataset routing, and i18n keys in all four locales.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | Add EmptyStackState component, SuggestCard, and suggested-datasets module | 50717146 | EmptyStackState.tsx, suggested-datasets.ts, EmptyStackState.test.tsx |
| 2 | Wire EmptyStackState into UnifiedStackPanel and add i18n keys | 04a434f4 | UnifiedStackPanel.tsx, UnifiedStackPanel.test.tsx, UnifiedStackPanel.empty-state.test.tsx, en/de/fr/es builder.json |

## What Was Built

**UnifiedStackPanel wiring (Task 2):**
- Added `onAddDataset?: (datasetId: string) => void` prop
- Changed `onAddDataClick` signature from `() => void` to `(initialQuery?: string) => void`
- `isEmpty` now equals `layers.length === 0` — basemapGroup presence no longer suppresses the empty state
- `EmptyStackState` renders with `onOpenAddData={(q) => onAddDataClick(q)}` and `onAddDataset` routing
- Extracted `renderBasemapDockRow(showEyebrow: boolean)` helper — basemap dock renders in both empty and populated states
- In empty state: basemap dock appears below `EmptyStackState` with "BASEMAP" eyebrow label and `border-t` separator
- In populated state: basemap dock renders at the top of `DndContext` without eyebrow

**i18n keys added to en/de/fr/es builder.json:**
- `unifiedStack.basemapEyebrow` — "BASEMAP"
- `unifiedStack.emptyHeading` — "Add your first layer"
- `unifiedStack.emptyBody` — "Search the catalog or pick a starter dataset below."
- `unifiedStack.emptySearchPlaceholder` — "Search datasets, URLs, or files…"
- `unifiedStack.suggestedLabel` — "SUGGESTED"
- `unifiedStack.browseAll` — "Browse all datasets →"

de/fr/es use English defaults; Phase 1038 closeout will add translations.

**Tests:**
- Updated `UnifiedStackPanel.test.tsx`: added `EmptyStackState` mock, updated empty-state test to expect `data-testid="empty-stack-state"`, updated basemap-empty-state test to verify both EmptyStackState and basemap dock render together
- Created `UnifiedStackPanel.empty-state.test.tsx`: 6 wiring tests covering search submit routing, add-dataset routing, basemap dock visibility, BASEMAP eyebrow, browse-all no-args, and non-empty suppression

## Decisions Made

1. **isEmpty logic change**: `layers.length === 0 && !basemapGroup` → `layers.length === 0`. The UI-SPEC requires basemap dock to always be visible; having basemapGroup suppress the empty state was incorrect.

2. **renderBasemapDockRow helper**: Extracted to avoid duplicating the basemap group/sublayer JSX. Takes `showEyebrow: boolean` to conditionally render the "BASEMAP" label and border-top separator.

3. **onAddDataset fallback**: Uses `onAddDataset ?? (() => {})` inline. The prop is optional; callers that don't yet wire direct-add will see a silent no-op.

## Deviations from Plan

None — plan executed exactly as specified in the objective.

## Known Stubs

None — EmptyStackState properly routes through `onOpenAddData` (→ `onAddDataClick`) and `onAddDataset`. SuggestCard availability checks use live API queries (not stubs).

## Threat Flags

None — no new network endpoints, auth paths, or trust boundary changes introduced.

## Self-Check: PASSED

- frontend/src/components/builder/UnifiedStackPanel.tsx: EXISTS (modified)
- frontend/src/components/builder/__tests__/UnifiedStackPanel.empty-state.test.tsx: EXISTS (created)
- frontend/src/i18n/locales/en/builder.json: EXISTS (modified, contains unifiedStack.basemapEyebrow)
- Commit 04a434f4: FOUND in worktree git log
- Commit 50717146 (Task 1): FOUND in worktree git log
