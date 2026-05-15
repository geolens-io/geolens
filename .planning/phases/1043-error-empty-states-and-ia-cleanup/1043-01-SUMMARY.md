---
phase: 1043
plan: "01"
subsystem: builder
tags: [builder, error-states, a11y, destructive-confirm]
dependency_graph:
  requires: []
  provides:
    - DatasetSearchPanel recoverable error state with retry
    - LayerEditorPanel Keep layer autoFocus (default + legacy-tab branches)
    - StackRow Keep layer autoFocus (inline alertdialog)
  affects:
    - frontend/src/components/builder/DatasetSearchPanel.tsx
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/components/builder/StackRow.tsx
    - frontend/src/i18n/locales/en/builder.json
tech_stack:
  added: []
  patterns:
    - useQueryClient + invalidateQueries for retry affordance
    - autoFocus on Cancel-side button in role=alertdialog (AUD-09 pattern)
    - eslint-disable jsx-a11y/no-autofocus with rationale comment (established codebase precedent)
key_files:
  created: []
  modified:
    - frontend/src/components/builder/DatasetSearchPanel.tsx
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/components/builder/StackRow.tsx
    - frontend/src/i18n/locales/en/builder.json
decisions:
  - "eslint-disable jsx-a11y/no-autofocus per established codebase pattern (FolderGroupRow.tsx:260, BasemapSublayerEditorScene.tsx:338)"
  - "Error banner body uses text-foreground (not text-destructive) per UI-SPEC color discipline — icon carries destructive color"
  - "queryClient.invalidateQueries (not refetch()) for retry — matches invalidation pattern used across app"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-14"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 4
requirements:
  - POL-16
---

# Phase 1043 Plan 01: Error recovery banner + destructive-confirm autoFocus safety Summary

Surgical fixes for the two P0 audit findings in Phase 1043: AUD-11 (DatasetSearchPanel has no retry path on fetch failure — leaves users with a dead-end) and AUD-09 (destroy-confirm focus lands on Delete, so Enter keystroke deletes the layer).

## Tasks Completed

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 | Wire DatasetSearchPanel retry button (AUD-11 / POL-16) | e67d08e0 | DatasetSearchPanel.tsx, en/builder.json |
| 2 | AutoFocus + ghost variant on Keep layer buttons (AUD-09) | 304bd71d | LayerEditorPanel.tsx, StackRow.tsx |

## What Was Built

**Task 1 — AUD-11 retry pattern:**
- Added `AlertCircle` + `RotateCcw` to DatasetSearchPanel's lucide imports (alphabetical)
- Added `useQueryClient` to the `@tanstack/react-query` import
- Wired `queryClient = useQueryClient()` at component top
- Replaced the bare `<p className="text-sm text-destructive">` error block with a structured `role="alert"` container containing: AlertCircle icon (text-destructive, aria-hidden), message paragraph (text-foreground — icon carries the color, body does not per UI-SPEC), and a ghost/sm "Try again" Button with RotateCcw icon that calls `queryClient.invalidateQueries({ queryKey: queryKeys.datasetSearch.results(debouncedQuery, recordType) })`
- Added `"retry": "Try again"` to the `search` object in `en/builder.json`

**Task 2 — AUD-09 autoFocus safety:**
- LayerEditorPanel default branch (formerly `variant="secondary"`): changed to `variant="ghost"` + `autoFocus` on Keep layer button
- LayerEditorPanel legacy-tab branch (same change for symmetry)
- StackRow inline alertdialog (formerly `variant="outline"`): changed to `variant="ghost"` + `autoFocus` on Keep layer button
- All three sites use `// eslint-disable-next-line jsx-a11y/no-autofocus -- moves focus to safe action so Enter dismisses, not destroys (AUD-09)` per the established precedent in FolderGroupRow.tsx and BasemapSublayerEditorScene.tsx

## Verification Results

| Check | Result |
|-------|--------|
| `grep -c "invalidateQueries.*datasetSearch"` in DatasetSearchPanel | 1 (pass) |
| `grep -c '"retry"'` in en/builder.json | present (pass) |
| JSON.parse(en/builder.json) | valid (pass) |
| `grep -c autoFocus` in LayerEditorPanel | 2 — one per branch (pass) |
| `grep -c autoFocus` in StackRow | 2 — line 283 (rename input, pre-existing) + line 429 (Keep button, new) (pass) |
| ESLint all three modified files, --max-warnings 0 | clean (pass) |
| vitest StackRow.test.tsx | 27 passed (pass) |
| vitest LayerEditorPanel.test.tsx | 31 passed (pass) |
| vitest DatasetSearchPanel.test.tsx | 13 passed, 1 pre-existing failure (cursor-grab test — confirmed failing before this plan via git stash) |
| tsc --noEmit on modified files | no new errors (pre-existing TS2367 in LayerEditorPanel line 94 unchanged) |

## Deviations from Plan

None — plan executed exactly as written.

The pre-existing DatasetSearchPanel test failure (`Test 4 (cursor-grab): DraggableDatasetRow outer div has cursor-grab when not dragging`) is confirmed pre-existing via `git stash` verification. Not introduced by this plan.

## Known Stubs

None. All changes are wired to real behavior (invalidateQueries is live; autoFocus is a native HTML prop).

## Threat Flags

None. Changes are read-only refetch triggers and focus management only — no new auth paths, no new network endpoints, no schema changes.

## Self-Check: PASSED

- e67d08e0 exists in git log: confirmed
- 304bd71d exists in git log: confirmed
- `frontend/src/components/builder/DatasetSearchPanel.tsx` modified: confirmed
- `frontend/src/components/builder/LayerEditorPanel.tsx` modified: confirmed
- `frontend/src/components/builder/StackRow.tsx` modified: confirmed
- `frontend/src/i18n/locales/en/builder.json` has `search.retry = "Try again"`: confirmed
