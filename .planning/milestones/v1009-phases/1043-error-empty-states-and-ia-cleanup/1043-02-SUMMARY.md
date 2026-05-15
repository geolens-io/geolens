---
phase: 1043-error-empty-states-and-ia-cleanup
plan: 02
subsystem: builder
tags:
  - builder
  - empty-states
  - copywriting
  - a11y
dependency_graph:
  requires:
    - 1043-01
  provides:
    - AUD-22 EmptyStackState SUGGESTED conditional + starter-help fallback
    - AUD-14 DatasetSearchPanel secondary Browse public catalog CTA
    - POL-17 LayerEditorPanel Source section no-columns empty state
  affects:
    - frontend/src/components/builder/EmptyStackState.tsx
    - frontend/src/components/builder/DatasetSearchPanel.tsx
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/i18n/locales/en/builder.json
tech_stack:
  added: []
  patterns:
    - SUGGESTED_DATASETS.length guard on conditional JSX branch
    - react-router Link asChild on Button variant=link for secondary catalog CTA
    - mutually exclusive columns.length === 0 / > 0 sibling conditionals
key_files:
  created: []
  modified:
    - frontend/src/components/builder/EmptyStackState.tsx
    - frontend/src/components/builder/DatasetSearchPanel.tsx
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/i18n/locales/en/builder.json
decisions:
  - AUD-22 P0: replaced orphan SUGGESTED eyebrow (always rendered on fresh install) with conditional branch on SUGGESTED_DATASETS.length; empty case shows MapPin + emptyHelpBody + Browse catalog button
  - AUD-14 P1: secondary catalog CTA uses variant=link + text-muted-foreground text-xs to be visually subordinate to the Upload CTA; routes to /collections via react-router Link
  - POL-17: Source section no-columns sentence placed above ColumnsReference as a sibling conditional; Filter and Labels sections NOT touched (they already own their own no-columns copy)
  - Four new English-only i18n keys added; de/es/fr untouched (Phase 1044 scope)
metrics:
  duration: ~8 minutes
  completed: 2026-05-15T01:35:00Z
  tasks_completed: 3
  files_modified: 4
---

# Phase 1043 Plan 02: Empty-state matrix (SUGGESTED fallback + secondary catalog CTA + Source no-columns) Summary

Empty-state matrix for three builder surfaces: AUD-22 P0 starter-help block in EmptyStackState when SUGGESTED_DATASETS is empty, AUD-14 P1 secondary Browse public catalog link in DatasetSearchPanel empty-catalog state, and POL-17 Source section "no queryable columns" sentence in LayerEditorPanel.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | AUD-22 EmptyStackState SUGGESTED conditional + starter-help fallback | 309b7890 | EmptyStackState.tsx, builder.json |
| 2 | AUD-14 DatasetSearchPanel secondary Browse public catalog CTA | aef3aaba | DatasetSearchPanel.tsx, builder.json |
| 3 | POL-17 LayerEditorPanel Source section no-columns empty state | dd8b68fa | LayerEditorPanel.tsx, builder.json |

## What Was Built

**AUD-22 (P0) — EmptyStackState starter-help fallback:**
- `SUGGESTED_DATASETS.length > 0` branch: renders existing eyebrow + `<ul>` unchanged
- `SUGGESTED_DATASETS.length === 0` branch (fresh install): renders `MapPin` icon + `emptyHelpBody` body copy + `Browse catalog →` button calling `onOpenAddData()`
- The existing page-level `Browse all datasets →` button below the conditional remains unchanged

**AUD-14 (P1) — DatasetSearchPanel secondary CTA:**
- Appended `<Button variant="link" size="sm" className="text-muted-foreground text-xs" asChild>` wrapping `<Link to="/collections">` after the Upload CTA in the empty-catalog State A block
- Visually subordinate to the Upload CTA; routes to existing /collections catalog route
- Only the unfiltered empty-catalog branch is modified; State B (zero-result) and error branches are unchanged

**POL-17 — LayerEditorPanel Source section:**
- Added `{columns.length === 0 && <p className="text-xs text-muted-foreground">{t('layerEditor.source.noColumns', ...)}</p>}` directly above the existing `{columns.length > 0 && <ColumnsReference ... />}` conditional
- Mutually exclusive: no double-render risk
- Filter and Labels sections NOT touched; they already own `filters.noColumns` and `labels.noColumns`

**New i18n keys (en only):**
- `unifiedStack.emptyHelpBody`: "Search the catalog to find datasets, or use the Upload button to add your own."
- `unifiedStack.browseAllShort`: "Browse catalog →"
- `search.browseCatalogCta`: "Browse public catalog →"
- `layerEditor.source.noColumns`: "No queryable columns indexed for this layer."

## Verification Results

- EmptyStackState vitest: 19/19 passed (2 test files)
- LayerEditorPanel vitest: 35/35 passed
- DatasetSearchPanel vitest: 19/20 passed — Test 4 (cursor-grab) fails; confirmed pre-existing before Phase 1043 (noted in execution context)
- TS error at LayerEditorPanel.tsx:94 (`LayerKind` vs `'basemap'` comparison): confirmed pre-existing before this plan's changes
- ESLint errors on EmptyStackState.tsx (4 `no-redundant-roles`): confirmed pre-existing in SuggestCard + ul at lines 82/93/112/236
- JSON valid: all 4 new keys present and correctly nested

## Deviations from Plan

None — plan executed exactly as written. All pre-existing issues (Test 4, TS error at line 94, 4 ESLint errors) confirmed pre-existing against stash diff.

## Known Stubs

None. All three empty-state surfaces are fully wired with copy, icon (where applicable), and CTAs.

## Threat Flags

No new threat surface introduced. All changes are conditional render guards on static data (SUGGESTED_DATASETS const), same-origin react-router Links, and a plain text sentence reading a column count from authenticated prop data.

## Self-Check: PASSED

- EmptyStackState.tsx modified: confirmed (MapPin + conditional branch)
- DatasetSearchPanel.tsx modified: confirmed (Browse public catalog CTA at /collections)
- LayerEditorPanel.tsx modified: confirmed (columns.length === 0 conditional)
- builder.json modified: confirmed (4 new keys, JSON valid)
- Commits exist: 309b7890, aef3aaba, dd8b68fa — all present in git log
