---
phase: 1041
plan: "02"
subsystem: builder
tags:
  - mapbuilder
  - bulk-actions
  - i18n
  - shadcn
dependency_graph:
  requires:
    - 1041-01 (selectedIds + handlers lifted to MapBuilderPage)
  provides:
    - BulkActionBar component with confirmation state machine
    - bulkActions i18n namespace (22 keys) in en/builder.json
    - BulkActionBar rendered in UnifiedStackPanel when selectedIds.size >= 2
    - 5 stub bulk handlers + handleClearSelection in MapBuilderPage
  affects:
    - 1041-03 (replaces stub handlers with real implementations)
    - 1041-04 (BulkActionBar tests target the component shipped here)
    - 1044 (i18n: de/fr/es need real translations for all 22 bulkActions keys)
tech_stack:
  added: []
  patterns:
    - Inline confirmation state machine (confirmingDelete) — no modal, bar-level UX
    - autoFocus on Cancel per AUD-09 safe-choice pattern
    - Tooltip-wrapped disabled buttons (opacity-40 + pointer-events-none)
    - useMemo for derived canGroup/canUngroup from selectedLayers
    - Stub handlers with [Phase 1041 Plan 03] console.warn prefix
key_files:
  created:
    - frontend/src/components/builder/BulkActionBar.tsx
  modified:
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
    - frontend/src/components/builder/UnifiedStackPanel.tsx
    - frontend/src/pages/MapBuilderPage.tsx
decisions:
  - "BulkActionBar placed outside scrollable list div (sibling of it, inside outer flex container): sticky bottom-0 inside overflow-y-auto would only be sticky within the scroll viewport — placing it outside makes it truly sticky at the panel footer."
  - "BulkActionBar props are optional in UnifiedStackPanel (onBulk* props marked ?): the bar renders only when all 5 handlers are provided AND selectedIds.size >= 2, avoiding null-access at the call site for tests that don't pass bulk handlers."
  - "[Rule 2] bulkActions namespace added to de/es/fr builder.json with English placeholder strings: the i18n parity test (resources.test.ts) enforces key presence across all supported languages, so adding to en alone caused a test failure. Placeholder English strings satisfy the parity gate; Phase 1044 provides real translations."
metrics:
  duration: "22m"
  completed_date: "2026-05-14"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 6
  files_created: 1
---

# Phase 1041 Plan 02: BulkActionBar component + i18n bulkActions namespace + UnifiedStackPanel render

**One-liner:** BulkActionBar sticky-footer component with 5-action layout, inline 2-step delete confirmation, canGroup/canUngroup disable rules, Tooltip explanations, and ARIA toolbar/alertdialog roles — wired into UnifiedStackPanel behind a `selectedIds.size >= 2` guard with stub handlers in MapBuilderPage.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add bulkActions i18n namespace to en/builder.json | cad5392b | frontend/src/i18n/locales/en/builder.json |
| 2 | Create BulkActionBar + wire into UnifiedStackPanel + stub handlers | fe014f66 | BulkActionBar.tsx, UnifiedStackPanel.tsx, MapBuilderPage.tsx, de/es/fr builder.json |

## What Was Built

### Task 1: bulkActions i18n namespace

Inserted 22 keys into `frontend/src/i18n/locales/en/builder.json` at file line 862 (between the `styleJson` close and the duplicate `unifiedStack` block that starts at line ~887). The insertion is in the FIRST occurrence position, which is what i18next reads.

**Insertion location:** After `"styleJson": { ... }` closing at line 859, before the duplicate block at line ~887. The exact anchor used in the Edit was the `styleJson.summary.skipped_*` keys immediately preceding the `"unifiedStack"` duplicate.

**22 keys added** (18 from UI-SPEC Copywriting Contract + 2 extra for checkbox aria-labels):
- 18 UI-SPEC keys: `selectedCount`, `toolbarLabel`, `liveAnnouncement`, `visibility`, `visibilityAriaLabel`, `opacity`, `opacityAriaLabel`, `group`, `groupAriaLabel`, `groupDisabledTooltip`, `ungroup`, `ungroupAriaLabel`, `ungroupDisabledTooltip`, `delete`, `deleteAriaLabel`, `deleteConfirmLabel`, `deleteConfirmAction`, `deleteConfirmCancel`, `errorUpdateRolledBack`, `errorDeleteRolledBack`
- 2 extra for checkbox ARIA (Plan 01 referenced these with defaultValue fallbacks): `selectRow`, `selectGroup`

**Phase 1044 i18n note:** All 22 keys need real translations for de/fr/es. Currently all 4 locale files have English placeholder strings.

### Task 2: BulkActionBar component

**`frontend/src/components/builder/BulkActionBar.tsx`** (new file, 252 lines):

- `memo` wrapped, named export `BulkActionBar`
- Props: `selectedIds: Set<string>`, `layers: MapLayerResponse[]`, `onClearSelection`, 5 `onBulk*` handlers
- Derived values per render: `N`, `selectedLayers` (memoized), `avgOpacity`, `majorityVisible`, `canGroup`, `canUngroup`
- **Normal state (5-button layout):**
  - Count label: "N selected" (`text-[13px] font-medium text-muted-foreground`)
  - Visibility button: Eye/EyeOff based on `majorityVisible` (toggle-to-hide cue)
  - Opacity: compact Slider `w-20`, value=`Math.round(avgOpacity * 100)`
  - Group: disabled when any selected layer is in a group, IS a group, or not `vector_dataset`; Tooltip: "Select only loose layers to group"
  - Ungroup: disabled when not all selected are `group:folder` rows; Tooltip: "Select only groups to ungroup"
  - Delete: `text-destructive`, always enabled when bar is visible
- **Confirmation state:**
  - Triggered by clicking Delete
  - `role="alertdialog"`, `aria-labelledby={confirmId}` (stable per-mount ID via `useId()`)
  - "Delete N layers? This cannot be undone." label in `text-destructive`
  - Cancel button: `autoFocus` (AUD-09 safe-choice), `variant="secondary"`
  - Confirm button: `variant="ghost" className="text-destructive"`, calls `onBulkDelete(selectedIds)`
  - Escape inside confirmation state: stops propagation (preserves selection), resets to normal state
- **Container:** `role="toolbar"`, `aria-label`, `aria-live="polite"`, `sticky bottom-0 h-12 bg-[var(--surface-2)] border-t border-[var(--border)] rounded-bl-[var(--radius-md)] rounded-br-[var(--radius-md)] transition-all duration-150`
- stopPropagation on container `onPointerDown` and `onClick` prevents row selection interference

**`frontend/src/components/builder/UnifiedStackPanel.tsx`** changes:
- Added `BulkActionBar` import
- Added 5 optional bulk handler props to `UnifiedStackPanelProps` interface
- Added those props to the component destructuring
- Inserted conditional render OUTSIDE the scrollable list div (sibling), inside the outer `flex flex-col` container: `{selectedIds.size >= 2 && onBulkVisibility && ... && (<BulkActionBar ... />)}`

**`frontend/src/pages/MapBuilderPage.tsx`** changes:
- `handleClearSelection` — replaces the inline `() => { setSelectedIds(new Set()); lastToggleAnchor.current = null; }` lambda in the JSX with a stable `useCallback`
- 5 stub handlers: `handleBulkVisibility`, `handleBulkOpacity`, `handleBulkGroup`, `handleBulkUngroup`, `handleBulkDelete` — each has `console.warn('[Phase 1041 Plan 03] ...')` prefix
- All 6 passed to `UnifiedStackPanel` JSX

## Decisions Made

1. **BulkActionBar placed outside the scrollable list div** — `sticky bottom-0` inside `overflow-y-auto` would only be sticky within the scroll viewport (not the panel bottom). Placing as a sibling after the scrollable div gives true panel-footer stickiness.
2. **Optional bulk handler props in UnifiedStackPanel** — marked `?` so existing test call sites that don't pass bulk handlers still compile. The render guard requires ALL 5 to be defined.
3. **[Rule 2] bulkActions keys added to de/es/fr** — the `i18n/resources.test.ts` parity check enforces all keys exist across all supported languages. Adding to `en` alone caused 1 test failure. English placeholder strings satisfy the gate; Phase 1044 fills real translations.

## Deviations from Plan

**[Rule 2 - Missing critical functionality] Added bulkActions namespace to de/es/fr locale files**
- **Found during:** Task 1 completion (vitest run)
- **Issue:** `resources.test.ts` enforces i18n key parity across all supported languages (en/de/es/fr). Adding bulkActions only to `en/builder.json` caused 1 test failure.
- **Fix:** Added the same 22 English-placeholder strings to `de/builder.json`, `es/builder.json`, `fr/builder.json` at the same structural position (after styleJson, before the duplicate unifiedStack block).
- **Files modified:** frontend/src/i18n/locales/de/builder.json, es/builder.json, fr/builder.json
- **Commit:** fe014f66
- **Note:** The pre-existing test failure (1 fail = missing keys like `a11y.*`, `search.dragHandle`, `toasts.basemapChanged` in de/es/fr) was present before this plan and was NOT caused by our changes (verified via git stash).

**handleClearSelection extracted to stable useCallback**
- The plan showed an inline `() => { setSelectedIds(new Set()); lastToggleAnchor.current = null; }` at the JSX call site. This was extracted to `handleClearSelection` useCallback for stable reference (prevents unnecessary UnifiedStackPanel re-renders) and to pass it to both `onClearSelection` and `onBulkVisibility` as a shared handler.

## Notes for Downstream Plans

- **Plan 03 (bulk op implementations):** Replace the 5 stub `handleBulk*` callbacks in `MapBuilderPage.tsx`. The `console.warn('[Phase 1041 Plan 03] ...')` prefix identifies all stub call sites.
- **Plan 04 (tests):** BulkActionBar test behavior contract defined in Plan 02 PLAN.md `<behavior>` block (Tests 1-11).
- **Phase 1044 i18n:** Translate all 22 `bulkActions.*` keys for de/fr/es. Currently placeholder English strings. The key `selectRow` and `selectGroup` were added beyond the UI-SPEC's 18-string list (needed for StackRow and FolderGroupRow checkbox aria-labels shipped in Plan 01).

## Known Stubs

- `handleBulkVisibility`, `handleBulkOpacity`, `handleBulkGroup`, `handleBulkUngroup`, `handleBulkDelete` in `MapBuilderPage.tsx` — each logs `console.warn('[Phase 1041 Plan 03] ...')`. These are intentional stubs; clicking any bulk action in the app fires the warn and does nothing. Plan 03 replaces them with real implementations.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced. BulkActionBar is a pure client-side component operating on in-memory state.

## Self-Check: PASSED

- `frontend/src/components/builder/BulkActionBar.tsx` exists and contains `role="toolbar"`, `aria-live="polite"`, `confirmingDelete`, `autoFocus`, all 5 `onBulk*` handler references
- `frontend/src/components/builder/UnifiedStackPanel.tsx` exists and contains `BulkActionBar` import, `selectedIds.size >= 2` guard
- `frontend/src/pages/MapBuilderPage.tsx` contains `handleBulkVisibility`, `handleBulkOpacity`, `handleBulkGroup`, `handleBulkUngroup`, `handleBulkDelete`, `handleClearSelection`
- `frontend/src/i18n/locales/en/builder.json` contains `bulkActions` key with 22 sub-keys; `grep -c '"bulkActions":' en/builder.json` returns 1
- Commits `cad5392b` and `fe014f66` exist in git log
- tsc: 0 errors; vitest: 1630 passed (1 pre-existing failure in de/es/fr parity, not caused by this plan); build: success
