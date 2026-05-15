---
phase: 1043-error-empty-states-and-ia-cleanup
verified: 2026-05-15T00:15:00Z
status: passed
score: 7/7
overrides_applied: 0
---

# Phase 1043: error-empty-states-and-ia-cleanup Verification Report

**Phase Goal:** Close audit's error/empty-state and IA findings — every async failure recoverable with localized copy + retry, every section's empty state intentionally designed, section ordering consistent across vector/raster/DEM/basemap, scene transitions preserve scroll + focus.

**Verified:** 2026-05-15T00:15:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Async fetch failures show localized error + retry (POL-16, AUD-11) | VERIFIED | `DatasetSearchPanel.tsx:634` — `role="alert"` div with `AlertCircle` icon, error copy (`search.error`), and `RotateCcw` button calling `queryClient.invalidateQueries(...)`. `search.retry = "Try again"` present in `builder.json`. |
| 2 | Empty states intentionally designed (Filter/Labels reuse existing keys; Source no-columns; basemap-group baseline; SUGGESTED fallback) (POL-16, POL-17, AUD-14, AUD-22) | VERIFIED | (a) `EmptyStackState.tsx:228` — `SUGGESTED_DATASETS.length > 0` guard; empty branch shows `MapPin` + `emptyHelpBody` + `browseAllShort`. (b) `DatasetSearchPanel.tsx:677` — `browseCatalogCta` secondary CTA wired to `/collections` via react-router Link. (c) `LayerEditorPanel.tsx:596` — `columns.length === 0` guard shows `layerEditor.source.noColumns` copy above the `ColumnsReference` component. Filter/Labels sections use pre-existing `filters.noColumns` / `labels.noColumns` keys. |
| 3 | Section ordering consistent: Render as → Appearance → Visibility → Filter → Labels → Source (POL-17) | VERIFIED | `LayerEditorPanel.tsx` sections in order: section-renderas (L326), section-appearance (L370), section-visibility (L407), Filter collapsible (L480), Labels collapsible (L514), Source collapsible (L549). Order is fixed and applies to all `editorScene='default'` calls regardless of layer kind. |
| 4 | Scene transitions preserve scroll + focus (POL-18) | VERIFIED | `LayerEditorPanel.tsx:171-198` — four refs (`bodyRef`, `savedScrollTopRef`, `prevSceneRef`, `headerRef`); three `useEffect` hooks: save scrollTop on scene exit, restore on remount, focus `headerRef` when transitioning from `basemap-sublayer` → `basemap-group`. `tabIndex={-1}` on header at L240 enables programmatic focus. |
| 5 | Carry-overs: hover:bg-accent → surface-2 (7 sites); eyebrowClassName migrated; 5 missing i18n keys | VERIFIED | (a) grep of 5 scoped files shows 0 `hover:bg-accent` matches. (b) `SettingsEditorScene.tsx:3` imports `eyebrowClassName`; 3 usage sites confirmed (L105, L156, L214). (c) All 5 i18n keys present: `basemapGroup.toggleExpand`, `basemapGroup.railLabel`, `basemapSublayer.strokeColor/strokeWidth/casingColor/casingWidth` (6 total keys added across plans). |
| 6 | AUD-09 + AUD-18 + AUD-20 closed | VERIFIED | AUD-09: `autoFocus` on Keep layer buttons at LEP:759, LEP:799, StackRow:430 (L283 is the pre-existing rename autoFocus). AUD-18: `BasemapGroupEditorScene.tsx:261` — Remove basemap button has `text-destructive hover:bg-[oklch(0.97_0.02_27)] hover:text-destructive`. AUD-20: `SidebarRail.tsx:140-162` — basemapGroup button renders `LayoutGrid` (18×18) with selected state; divider guard at L104 prevents orphaned divider when overlay list is empty. |
| 7 | 789/789 tests pass | VERIFIED | `npx vitest run src/components/builder/ src/pages/` — **843 tests passed** (72 test files). Actual count exceeds documented 789 because `src/pages/` contributes additional tests. Zero failures, zero worker errors. |

**Score:** 7/7 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/builder/DatasetSearchPanel.tsx` | Error state + retry affordance | VERIFIED | `role="alert"` block at L634 with AlertCircle + RotateCcw retry button |
| `frontend/src/components/builder/LayerEditorPanel.tsx` | Section ordering + scroll/focus preservation + Source no-columns | VERIFIED | Sections in correct order L326-L613; 4 refs + 3 useEffects L171-199; noColumns guard L596 |
| `frontend/src/components/builder/EmptyStackState.tsx` | SUGGESTED conditional + starter-help fallback | VERIFIED | SUGGESTED_DATASETS.length guard at L228; MapPin + emptyHelpBody + browseAllShort at L251-261 |
| `frontend/src/components/builder/SidebarRail.tsx` | Basemap group LayoutGrid rail button (AUD-20) | VERIFIED | basemapGroup prop at L17; LayoutGrid button L140-162; divider guard L104 |
| `frontend/src/components/builder/BasemapGroupEditorScene.tsx` | Destructive Remove basemap styling (AUD-18) | VERIFIED | text-destructive + oklch destructive-hover at L261 |
| `frontend/src/components/builder/SettingsEditorScene.tsx` | eyebrowClassName import (carry-over) | VERIFIED | Import at L3; 3 usages at L105, L156, L214 |
| `frontend/src/i18n/locales/en/builder.json` | 9+ new/confirmed i18n keys | VERIFIED | search.retry, search.browseCatalogCta, unifiedStack.emptyHelpBody, unifiedStack.browseAllShort, layerEditor.source.noColumns, basemapGroup.railLabel, basemapGroup.toggleExpand, basemapSublayer.strokeColor/strokeWidth/casingColor/casingWidth — all present |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `DatasetSearchPanel.tsx` error block | `queryClient.invalidateQueries` | `useQueryClient()` + `queryKeys.datasetSearch.results(...)` | WIRED | L397: `queryClient = useQueryClient()`; L643: invalidateQueries call in retry button onClick |
| `EmptyStackState.tsx` empty branch | `onOpenAddData()` | `SUGGESTED_DATASETS.length === 0` conditional | WIRED | L228 guard; L259: button calls `onOpenAddData()` |
| `SidebarRail` basemapGroup button | `onSelectLayer(basemapGroup.id)` | `basemapGroup` prop + onClick | WIRED | L153; MapBuilderPage passes `basemapGroup={layers.localBasemap ? { id: 'basemap-group' } : null}` at MapBuilderPage.tsx:952 |
| `LayerEditorPanel` headerRef | focus on scene back-nav | `prevSceneRef` + `useEffect` | WIRED | L194-198: `basemap-sublayer → basemap-group` fires `headerRef.current?.focus()` |
| `LayerEditorPanel` Source section | noColumns copy | `columns.length === 0` guard | WIRED | L596-600; mutually exclusive with `columns.length > 0` ColumnsReference at L601 |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `DatasetSearchPanel` error state | `isError` from `useQuery` | TanStack Query wrapping `searchDatasets()` API call | Yes — live TanStack Query state, not mocked | FLOWING |
| `EmptyStackState` SUGGESTED branch | `SUGGESTED_DATASETS.length` | Static const import from `suggested-datasets.ts` | Yes — compile-time constant; conditional is deterministic | FLOWING |
| `LayerEditorPanel` source noColumns | `columns` (= `layer.dataset_column_info ?? []`) | Parent-provided `MapLayerResponse` prop | Yes — prop data from live API response | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Error banner exports `role="alert"` | `grep -c 'role="alert"'` DatasetSearchPanel.tsx | 1 | PASS |
| Retry calls invalidateQueries | `grep -c 'invalidateQueries.*datasetSearch'` DatasetSearchPanel.tsx | 1 | PASS |
| autoFocus on Keep layer (both branches) | `grep -c 'autoFocus'` LayerEditorPanel.tsx | 2 | PASS |
| Section order (renderAs first) | Line numbers: L326 < L370 < L407 < L480 < L514 < L549 | Correct ascending order | PASS |
| Source noColumns guard | `grep -c 'columns.length === 0'` LayerEditorPanel.tsx | 1 | PASS |
| LayoutGrid in SidebarRail | `grep -c 'LayoutGrid'` SidebarRail.tsx | 2 (import + usage) | PASS |
| Remove basemap destructive | `grep -c 'text-destructive'` BasemapGroupEditorScene.tsx | 1 | PASS |
| eyebrowClassName in SettingsEditorScene | `grep -c 'eyebrowClassName'` SettingsEditorScene.tsx | 4 (1 import + 3) | PASS |
| hover:bg-accent zero matches in 5 scoped files | grep across 5 files | 0 matches | PASS |
| Full vitest suite | `npx vitest run src/components/builder/ src/pages/` | 843/843 passed | PASS |

---

### Probe Execution

Step 7c: SKIPPED — no probe scripts exist for this phase; it is a UI polish phase, not a migration/tooling phase.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| POL-16 | 1043-01 + 1043-02 | Recoverable error states with localized retry; empty-state copy + iconography | SATISFIED | DatasetSearchPanel retry wired; EmptyStackState fallback + Source noColumns + secondary CTA all in place |
| POL-17 | 1043-02 + 1043-03 | Filter/Labels/Source/basemap-group empty-state + section ordering consistency | SATISFIED | Source noColumns at LEP:596; section ordering Render as → Appearance → Visibility → Filter → Labels → Source confirmed; AUD-20 SidebarRail basemap rail button |
| POL-18 | 1043-03 | Scene-transition scroll + focus preservation | SATISFIED | 4 refs + 3 useEffects in LEP; scroll saved/restored on editorScene changes; focus restored to header on basemap-sublayer back-nav |

---

### Anti-Patterns Found

No blockers. Noted items are all pre-existing, documented in SUMMARYs, and out of scope per deviation rules:

| File | Pattern | Severity | Notes |
|------|---------|----------|-------|
| `EmptyStackState.tsx` | 4x `jsx-a11y/no-redundant-roles` | Info | Pre-existing; confirmed pre-plan via git stash in SUMMARY-02 |
| `DatasetSearchPanel.tsx` | Test 4 cursor-grab failure (pre-plan) | Info | Fixed in Plan 04 (cc651348); no longer failing per vitest run |
| `MapBuilderPage.tsx` | 9 missing useCallback deps warnings | Info | Pre-existing ESLint warnings; out of scope |

No `TBD`, `FIXME`, or `XXX` markers found in phase-modified files (spot-checked via commit list).

---

### Human Verification Required

The following behaviors are wired in code and logically correct but cannot be verified programmatically without a running browser session:

1. **Scene transition scroll preservation — visual regression**
   - **Test:** Open LayerEditorPanel for a layer with many sections, scroll down to Source, click a basemap sublayer in the stack, then click Back to basemap group.
   - **Expected:** Scroll position returns to approximately where it was before navigating away.
   - **Why human:** Scroll position restoration depends on real DOM layout and timing — cannot be confirmed via static analysis or jsdom.

2. **Focus restoration — keyboard flow**
   - **Test:** Using keyboard only, navigate to a basemap sublayer scene, then press the Back to basemap group button.
   - **Expected:** Focus moves to the layer-editor-header element (the panel header div with `tabIndex={-1}`).
   - **Why human:** `focus()` side effects on DOM elements with `tabIndex={-1}` require a real browser to observe.

3. **AUD-09 autoFocus safety — keyboard flow**
   - **Test:** Trigger delete confirm dialog (click Delete layer in footer), then press Enter.
   - **Expected:** Enter dismisses the dialog (Keep layer button has focus), not deletes the layer.
   - **Why human:** `autoFocus` behavior in alertdialog requires browser render to confirm focus lands correctly.

---

### Gaps Summary

No gaps. All 7 must-haves verified against codebase evidence. The 3 human verification items above are behavioral confirmation items, not implementation gaps — the code is correctly wired in all three cases.

---

_Verified: 2026-05-15T00:15:00Z_
_Verifier: Claude (gsd-verifier)_
