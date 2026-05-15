---
phase: 1043-error-empty-states-and-ia-cleanup
plan: "04"
subsystem: builder-ui
tags:
  - builder
  - polish
  - tokens
  - i18n
  - carry-over
dependency_graph:
  requires:
    - 1043-03
  provides:
    - hover:bg-[var(--surface-2)] token contract at all 7 1042-audit call sites
    - eyebrowClassName single source of truth for all builder section headers
    - five English i18n keys for basemapGroup and basemapSublayer
  affects:
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/components/builder/StackRow.tsx
    - frontend/src/components/builder/DatasetSearchPanel.tsx
    - frontend/src/components/builder/BasemapGroupRow.tsx
    - frontend/src/components/builder/FolderGroupRow.tsx
    - frontend/src/components/builder/SettingsEditorScene.tsx
    - frontend/src/i18n/locales/en/builder.json
tech_stack:
  added: []
  patterns:
    - eyebrowClassName imported across sibling components for tracking-wide uniformity
    - hover:bg-[var(--surface-2)] as canonical interactive surface hover token
key_files:
  modified:
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/components/builder/StackRow.tsx
    - frontend/src/components/builder/DatasetSearchPanel.tsx
    - frontend/src/components/builder/BasemapGroupRow.tsx
    - frontend/src/components/builder/FolderGroupRow.tsx
    - frontend/src/components/builder/SettingsEditorScene.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/components/builder/__tests__/DatasetSearchPanel.test.tsx
    - frontend/src/pages/MapBuilderPage.tsx
decisions:
  - Removed dead `basemap` branch from LayerCapsBadge cn() in LayerEditorPanel — LayerKind is 'vector'|'raster'|'vrt' only; the basemap path was unreachable and caused TS2367
  - cursor-grab test fixed by querying subtree (div.querySelector('.cursor-grab')) since the class lives on inner flex div, not outer .group/row wrapper
metrics:
  duration: "~5 minutes"
  completed: "2026-05-14"
  tasks_completed: 3
  files_modified: 9
---

# Phase 1043 Plan 04: Phase 1042 Carry-Over Polish + i18n Keys + Pre-Existing Fixes Summary

Close three Phase 1042 UI-REVIEW carry-overs: hover:bg-[var(--surface-2)] at 7 builder call sites, eyebrowClassName migration in SettingsEditorScene, and 5 new English i18n keys — plus four pre-existing fixes (TS error, ESLint whitespace, cursor-grab test, WR-03 verify).

## Completed Tasks

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 | hover:bg-accent → hover:bg-[var(--surface-2)] sweep (7 sites) | d4516f0a | LayerEditorPanel, StackRow, DatasetSearchPanel, BasemapGroupRow, FolderGroupRow |
| 2 | SettingsEditorScene eyebrow migration to eyebrowClassName | da92b392 | SettingsEditorScene.tsx |
| 3 | Five new English i18n keys + WR-03 verify | 6fd25f44 | en/builder.json |
| — | Pre-existing fixes (TS, ESLint, cursor-grab test) | cc651348 | LayerEditorPanel, DatasetSearchPanel.test, MapBuilderPage |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed pre-existing TS2367 at LayerEditorPanel.tsx:94**
- **Found during:** Acceptance verification
- **Issue:** `caps.kind === 'basemap'` comparison always false — `LayerKind` is `'vector'|'raster'|'vrt'`, never `'basemap'`; also `!['vector','raster','vrt','basemap'].includes(caps.kind)` always false. Dead branches.
- **Fix:** Removed the dead `'basemap'` and catch-all branches from the `cn()` call in `LayerCapsBadge`. All three `LayerKind` values are covered by the two remaining arms.
- **Files modified:** `frontend/src/components/builder/LayerEditorPanel.tsx`
- **Commit:** cc651348

**2. [Rule 1 - Bug] Fixed pre-existing cursor-grab vitest failure in DatasetSearchPanel.test.tsx**
- **Found during:** Full vitest run (pre-existing, noted in dependency context)
- **Issue:** Test queried `.group/row` outer div for `cursor-grab` class, but the class is on an inner flex div (`line 239`). The assertion `div.className.includes('cursor-grab')` always returned false.
- **Fix:** Changed filter to `div.querySelector('.cursor-grab') !== null` to check the subtree.
- **Files modified:** `frontend/src/components/builder/__tests__/DatasetSearchPanel.test.tsx`
- **Commit:** cc651348

**3. [Rule 3 - Blocking] Fixed pre-existing ESLint no-irregular-whitespace at MapBuilderPage:106**
- **Found during:** ESLint sweep (pre-existing, noted in dependency context)
- **Issue:** Comment contained a literal U+200B zero-width space character explaining the `​` trick; the character itself in the comment triggered `no-irregular-whitespace`.
- **Fix:** Rewrote the comment to remove the zero-width space literal.
- **Files modified:** `frontend/src/pages/MapBuilderPage.tsx`
- **Commit:** cc651348

### WR-03 Verification Result (verify-only)

`freshLayerTimeoutRef.current = null` self-null is present at `use-builder-layers.ts:657` inside the setTimeout callback, after `setFreshLayerId(null)`. No edit needed. Already shipped in Phase 1042 as expected.

### Out-of-scope hover:bg-accent Instances (not modified)

The following files in `src/components/builder/` retain `hover:bg-accent` — they were NOT on the canonical 7-site list and are deferred to future audit scope:
- `MentionDropdown.tsx:38` (`hover:bg-accent/50`)
- `BasemapPicker.tsx:33,66` (`hover:bg-accent/50`)
- `MapToolbar.tsx:86,115,138`
- `ColorRampPicker.tsx:56` (`hover:bg-accent/50`)
- `IconPicker.tsx:74`
- `ChatPanel.tsx:443`
- `SharePanel.tsx:533` (`hover:bg-accent/50`)
- `BuilderRail.tsx:94,129`
- `MapTitleBar.tsx:108,123` (`hover:bg-accent/40`)
- `PopupConfigEditor.tsx:295`

These are noted for a future token-sweep audit milestone.

### Pre-existing ESLint Warnings (not in scope)

`EmptyStackState.tsx` (4× `jsx-a11y/no-redundant-roles`) and `UnifiedStackPanel.tsx` (2× unused eslint-disable) have pre-existing lint issues not caused by this plan. Deferred per scope boundary rules.

## Verification Results

| Check | Result |
|-------|--------|
| `hover:bg-accent` in 5 scope files | 0 matches |
| `tracking-[0.08em]` in SettingsEditorScene | 0 matches |
| `eyebrowClassName` occurrences in SettingsEditorScene | 4 (1 import + 3 usages) |
| `basemapGroup.toggleExpand` in builder.json | OK |
| `basemapSublayer.strokeColor/strokeWidth/casingColor/casingWidth` | OK |
| `freshLayerTimeoutRef.current = null` after setFreshLayerId | Present (line 657) |
| TypeScript (`npx tsc --noEmit`) | Clean |
| Vitest builder suite | 789/789 passed |
| ESLint on modified files | Clean |

## Self-Check: PASSED

All files modified, commits recorded, no missing artifacts.
