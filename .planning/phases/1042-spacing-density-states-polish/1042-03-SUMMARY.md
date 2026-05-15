---
phase: 1042-spacing-density-states-polish
plan: "03"
subsystem: builder
tags:
  - builder
  - layer-editor
  - settings
  - density
  - state-vocabulary
dependency_graph:
  requires:
    - 1042-01 (motion tokens in index.css)
  provides:
    - LayerEditorPanel header px-4 py-3 normalization
    - Type-pill color-by-kind (vector/raster/basemap/fallback)
    - Caret duration-[--motion-fast] across LEP + BasemapGroupRow + FolderGroupRow
    - Four scene components px-4 py-2 section padding
    - Scene-B sublayer canonical 7-cell grid
    - BasemapGroupRow grip hidden (AUD-04)
    - SidebarRail hover token aligned to --surface-2
  affects:
    - 1042-02 (parallel, no file overlap)
    - 1042-04 (parallel, no file overlap)
tech_stack:
  added: []
  patterns:
    - cn() conditional driven by caps.kind for type-pill colorization
    - Canonical 7-cell grid grid-cols-[16px_14px_22px_22px_1fr_60px_22px] in sublayer list
    - aria-hidden span replacing misleading drag grip
key_files:
  created: []
  modified:
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/components/builder/BasemapGroupEditorScene.tsx
    - frontend/src/components/builder/BasemapSublayerEditorScene.tsx
    - frontend/src/components/builder/SettingsEditorScene.tsx
    - frontend/src/components/builder/DEMEditorScene.tsx
    - frontend/src/components/builder/BasemapGroupRow.tsx
    - frontend/src/components/builder/FolderGroupRow.tsx
    - frontend/src/components/builder/SidebarRail.tsx
    - frontend/src/components/builder/__tests__/LayerEditorPanel.test.tsx
    - frontend/src/components/builder/__tests__/BasemapGroupEditorScene.test.tsx
decisions:
  - "Keep dragHandleProps in BasemapGroupRow interface (parent still passes it); prefix with _ in destructuring to satisfy lint after grip JSX removal"
  - "Replace entire grip button with aria-hidden span rather than opacity-0 approach — cleaner a11y, removes interactive element"
  - "Replace inline-style flex <li> with Tailwind grid-cols-[...] className for sublayer rows in BasemapGroupEditorScene"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-14"
  tasks: 3
  files: 10
requirements_satisfied:
  - POL-13
  - POL-14
---

# Phase 1042 Plan 03: LayerEditorPanel + 4 Scenes Spacing/Density + State Vocabulary Unification Summary

LayerEditorPanel header normalized to px-4 py-3, type-pill colorized per record kind via cn(), three section carets updated to duration-[--motion-fast]; four scene components normalized from py-3 to py-2; Scene-B sublayer rows migrated to canonical 7-cell grid; BasemapGroupRow grip replaced with aria-hidden span; FolderGroupRow caret duration unified; SidebarRail hover token aligned to --surface-2.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | LayerEditorPanel header, type-pill, caret (AUD-05/06/07) | af0f50e5 | LayerEditorPanel.tsx, LayerEditorPanel.test.tsx |
| 2 | Four scene py-2 + Scene-B 7-cell grid (AUD-16/17) | cbd691ca | BasemapGroupEditorScene.tsx + 3 scene files + test |
| 3 | Row carets, grip hide, SidebarRail hover (AUD-04/07/21) | 742d88cc | BasemapGroupRow.tsx, FolderGroupRow.tsx, SidebarRail.tsx |
| 3b | Lint fix: _dragHandleProps prefix | 5252531c | BasemapGroupRow.tsx |

## Implementation Details

### Task 1 — LayerEditorPanel (AUD-05/06/07)

**AUD-05:** `LayerEditorPanel.tsx:203` — header className changed from `px-2 py-2` → `px-4 py-3`.

**AUD-06:** `LayerEditorPanel.tsx:89-97` (LayerEditorTypePill) — replaced constant `bg-[var(--surface-2)] text-muted-foreground` with cn() driven by `caps.kind`:
- `vector` → `bg-[var(--type-vector-bg)] text-[var(--type-vector)]`
- `raster|vrt` → `bg-[var(--type-raster-bg)] text-[var(--type-raster)]`
- `basemap` → `bg-[var(--primary-50)] text-[var(--primary-700)]`
- fallback → `bg-[var(--surface-2)] text-muted-foreground`

Token presence verified in `frontend/src/index.css`:
- `--type-vector-bg` at line 91 (`oklch(0.94 0.04 155)`)
- `--type-raster-bg` at line 93 (`oklch(0.94 0.05 55)`)
- `--primary-50` at line 29 (`oklch(0.97 0.02 250)`)
- `--primary-700` at line 36 (`oklch(0.46 0.16 250)`)
- `--motion-fast` at line 141 (`150ms`)

**AUD-07:** Three carets at lines 450, 485, 519 changed `duration-150` → `duration-[--motion-fast]`.

### Task 2 — Four Scenes (AUD-16/17)

**AUD-16:** `px-4 py-3` → `px-4 py-2` across all section wrappers. Post-edit grep of non-comment lines returns zero matches in all four files.

Counts changed per file:
- `BasemapGroupEditorScene.tsx`: 3 occurrences (lines 78, 128, 207)
- `BasemapSublayerEditorScene.tsx`: 5 occurrences (lines 92, 136, 208, 285-button, 302)
- `SettingsEditorScene.tsx`: 5 occurrences (lines 98-button, 115, 149-button, 167-p, 207-button, 226)
- `DEMEditorScene.tsx`: 3 occurrences (lines 163, 203, 359)

**AUD-17:** Sublayer `<li>` in `BasemapGroupEditorScene.tsx` (~line 143) migrated from:
```
style={{ height: '32px', display: 'flex', alignItems: 'center', gap: '8px', padding: '0 4px' }}
```
to canonical 7-cell grid:
```
className="group/row grid grid-cols-[16px_14px_22px_22px_1fr_60px_22px] gap-2 items-center py-2 px-2"
```
Cell mapping:
- Col 1 (16px): `<span style={{ visibility: 'hidden' }} className="h-[14px] w-[14px]" aria-hidden="true" />`
- Col 2 (14px): `<span className="opacity-0 pointer-events-none h-[14px] w-[14px]" aria-hidden="true" />`
- Col 3 (22px): Eye toggle button (unchanged)
- Col 4 (22px): SublayerTypeIcon (unchanged)
- Col 5 (1fr): Name span (unchanged)
- Col 6 (60px): Opacity slider (unchanged)
- Col 7 (22px): `<span aria-hidden="true" />` spacer

### Task 3 — Row Carets, Grip Hide, Hover Token

**AUD-07 row-side:**
- `BasemapGroupRow.tsx:104` — appended `duration-[--motion-fast]` to `transition-transform` string
- `FolderGroupRow.tsx:180` — same

**AUD-04:**
- `BasemapGroupRow.tsx:113-127` — entire grip button replaced with `<span aria-hidden="true" className="h-[14px] w-[14px]" />`
- `GripVertical` import removed
- `dragHandleProps` renamed to `_dragHandleProps` in destructuring (interface preserved for parent compatibility)

**AUD-21:**
- `SidebarRail.tsx:121` — `hover:bg-accent` → `hover:bg-[var(--surface-2)]`

## Verification Results

### Automated Tests

- `LayerEditorPanel.test.tsx`: 35/35 pass (4 new: AUD-05/06/07)
- `BasemapGroupEditorScene.test.tsx`: 15/15 pass (3 new: AUD-16/17 + updated Test 7)
- `BasemapGroupRow.test.tsx`: 12/12 pass
- `FolderGroupRow.test.tsx`: 11/11 pass
- `BuilderRail.test.tsx`: 10/10 pass
- **Total: 83/83**

### Grep Gate

```
grep -c 'px-4 py-3' (4 scene files, non-comment lines) = 0
```

### Lint

Zero errors in this plan's 8 modified files.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test 7 in BasemapGroupEditorScene.test.tsx checked inline style height**
- **Found during:** Task 2 RED phase
- **Issue:** Existing Test 7 asserted `style.height === '32px'` which breaks after grid migration
- **Fix:** Updated Test 7 to drop the height check (grid layout doesn't use inline height), kept the onclick null check
- **Files modified:** `BasemapGroupEditorScene.test.tsx`
- **Commit:** cbd691ca

**2. [Rule 2 - Missing critical functionality] GripVertical unused after grip removal**
- **Found during:** Task 3 lint gate
- **Issue:** Removing the grip button left `GripVertical` as an unused import, and `dragHandleProps` as an unused variable (lint error)
- **Fix:** Removed `GripVertical` from imports; prefixed `dragHandleProps` with `_` in destructuring while keeping the interface prop for parent compatibility
- **Files modified:** `BasemapGroupRow.tsx`
- **Commit:** 5252531c

## Known Stubs

None. All changes are structural/styling only with no data stubs.

## Threat Flags

None. All changes are presentation-layer className/structure modifications with no new network boundaries, auth paths, or data sinks.

## Self-Check: PASSED

Files exist:
- `frontend/src/components/builder/LayerEditorPanel.tsx` — FOUND
- `frontend/src/components/builder/BasemapGroupEditorScene.tsx` — FOUND
- `frontend/src/components/builder/BasemapGroupRow.tsx` — FOUND
- `frontend/src/components/builder/SidebarRail.tsx` — FOUND

Commits exist:
- af0f50e5 — FOUND
- cbd691ca — FOUND
- 742d88cc — FOUND
- 5252531c — FOUND
