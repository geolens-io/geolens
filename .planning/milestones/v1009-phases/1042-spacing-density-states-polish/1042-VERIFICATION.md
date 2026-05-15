---
phase: 1042-spacing-density-states-polish
verified: 2026-05-15T00:45:00Z
status: human_needed
score: 10/10
overrides_applied: 0
human_verification:
  - test: "Inspect UnifiedStackPanel + LayerEditorPanel side-by-side at 340px sidebar width"
    expected: "Spacing and density feel normalized — no cramped or over-padded sections. BulkActionBar labels remain accessible via Tooltip at narrow width."
    why_human: "Perceived spacing uniformity and sidebar density at narrow widths cannot be verified programmatically — requires visual inspection in a running browser."
  - test: "Trigger a dataset search in DatasetSearchPanel while the catalog is loading (first fetch)"
    expected: "Exactly 5 skeleton rows appear at h-[58px] each — no spinner, no blank space. On refetch (filter change), a thin progress band appears above the dimmed stale list."
    why_human: "Skeleton visibility and animation require a live browser — cannot run Playwright without a running stack."
  - test: "Add a dataset from the catalog to the map stack"
    expected: "The new StackRow slides in with a fade-in entry animation (animate-in fade-in at --motion-fast timing) and settles normally. Animation completes and the isFresh class is gone after 200ms."
    why_human: "Entry animation is a transient visual behavior tied to timing — requires a running browser to observe."
  - test: "Hover, tab-focus, click, and release on all builder controls (StackRow, SidebarRail button, BulkActionBar actions, section carets, DatasetSearchPanel rows)"
    expected: "Every control uses --surface-2 hover, ring focus-visible, --primary-50 pressed state. All section carets animate at the same speed (--motion-fast = 150ms)."
    why_human: "State vocabulary consistency and perceived animation timing require visual/interactive confirmation in a browser."
---

# Phase 1042: spacing-density-states-polish — Verification Report

**Phase Goal:** Apply Phase 1039's P0/P1 audit findings as a coordinated spacing/density/typography/state pass across UnifiedStackPanel, LayerEditorPanel, AddDatasetModal, and Settings — sketch-findings tokens only, unified hover/focus-visible/pressed/active states, consistent loading affordances.
**Verified:** 2026-05-15T00:45:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Motion tokens `--motion-fast: 150ms` and `--motion-base: 250ms` defined in `:root` | VERIFIED | `frontend/src/index.css:141-142` — exact values present in `:root` block, commit `abdcad44` |
| 2 | Insertion line 25% bloom shadow + 9999px radius on `[data-dnd-over]` | VERIFIED | `index.css:520-523` — `border-radius: 9999px; box-shadow: 0 0 0 2px oklch(0.55 0.18 250 / 25%)` |
| 3 | BulkActionBar: gap-2, ghost Cancel, rAF mount transition, label visibility at narrow widths | VERIFIED | `BulkActionBar.tsx:119` gap-2; line 153 ghost Cancel; line 122-123 translate-y/opacity mount via rAF; lines 213/259/282/311/362 `hidden sm:inline` + Tooltip wrappers; 23/23 tests pass |
| 4 | DatasetSearchPanel: 5x skeleton on `isLoading`, progress band on refetch, full-row cursor-grab | VERIFIED | `DatasetSearchPanel.tsx:643-648` 5 Skeleton rows at h-[58px]; line 652 `h-0.5 animate-pulse` progress band; lines 235-236 `cursor-grab`/`cursor-grabbing` on outer row div; 14/14 tests pass |
| 5 | LayerEditorPanel header `px-4 py-3` + 4 scenes normalized to `py-2` | VERIFIED | `LayerEditorPanel.tsx:209` header `px-4 py-3`; grep confirms zero `px-4 py-3` in all 4 scene files; `px-4 py-2` confirmed in BasemapGroupEditorScene (3), BasemapSublayerEditorScene (5), SettingsEditorScene (5), DEMEditorScene (3); 35/35 + 15/15 tests pass |
| 6 | State vocabulary consistent — `--surface-2` hover across StackRows, SidebarRail layer buttons, FolderGroupRow; `duration-[--motion-fast]` on all carets | VERIFIED | `UnifiedStackPanel.tsx:435` `hover:bg-[var(--surface-2,...)]`; `SidebarRail.tsx:121` `hover:bg-[var(--surface-2)]`; `LayerEditorPanel.tsx:456,491,525` all carets use `duration-[--motion-fast]`; `BasemapGroupRow.tsx:104` and `FolderGroupRow.tsx:180` same |
| 7 | i18n duplicate-key block deleted (`builder.json` lines 715-826) | VERIFIED | Python validation confirms 51 unique top-level keys, zero duplicates; `listboxLabel: "Map layers"` present at line 782; file is 885 lines (was ~999 before dedup); commit `7bba3694` |
| 8 | `freshLayerId` entry animation on new stack rows | VERIFIED | `use-builder-layers.ts:82-83` state+ref; lines 653-655 set + 200ms timeout; `StackRow.tsx:55,121,183` `isFresh` prop + `animate-in fade-in duration-[--motion-fast]`; `UnifiedStackPanel.tsx:936,967` wired at both render sites; 11/11 freshLayerId lifecycle tests pass |
| 9 | EmptyStackState polish: `--surface-0` suggest card, `transition-colors duration-[--motion-fast]` | VERIFIED | `EmptyStackState.tsx:86` `bg-[var(--surface-0)]`; line 200 `transition-colors duration-[--motion-fast]`; line 212 search icon button also has it; `eyebrowClassName` exported at line 17; 14/14 tests pass |
| 10 | All 843 builder/pages tests pass — no regressions | VERIFIED | `npx vitest run src/components/builder/ src/pages/` → 72 test files, 843 tests, 0 failures |

**Score:** 10/10 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/index.css` | Motion tokens + bloom + wash rules | VERIFIED | Lines 141-142 tokens; 519-524 bloom; 558-562 wash |
| `frontend/src/components/builder/BulkActionBar.tsx` | gap-2, ghost Cancel, rAF mount, label Tooltips | VERIFIED | All 4 changes confirmed; 23/23 tests |
| `frontend/src/components/builder/DatasetSearchPanel.tsx` | Skeleton, progress band, cursor-grab, ChevronRight rotate | VERIFIED | All changes confirmed; 14/14 tests |
| `frontend/src/components/builder/LayerEditorPanel.tsx` | px-4 py-3 header, type-pill color, caret duration-[--motion-fast] | VERIFIED | Lines 209, 89-97, 456/491/525; 35/35 tests |
| `frontend/src/components/builder/BasemapGroupEditorScene.tsx` | px-4 py-2 sections, canonical 7-cell sublayer grid | VERIFIED | 3 py-2 sections; grid-cols at line 143; 15/15 tests |
| `frontend/src/components/builder/BasemapSublayerEditorScene.tsx` | px-4 py-2 sections | VERIFIED | 5 py-2 sections confirmed |
| `frontend/src/components/builder/SettingsEditorScene.tsx` | px-4 py-2 sections | VERIFIED | 5 py-2 sections confirmed |
| `frontend/src/components/builder/DEMEditorScene.tsx` | px-4 py-2 sections | VERIFIED | 3 py-2 sections confirmed |
| `frontend/src/components/builder/BasemapGroupRow.tsx` | Grip replaced with aria-hidden span, caret duration-[--motion-fast] | VERIFIED | Line 113 aria-hidden span; line 104 duration token |
| `frontend/src/components/builder/FolderGroupRow.tsx` | Caret duration-[--motion-fast] | VERIFIED | Line 180 confirmed |
| `frontend/src/components/builder/SidebarRail.tsx` | Layer buttons `hover:bg-[var(--surface-2)]` | VERIFIED | Line 121 confirmed; settings cog at line 72 retains `hover:bg-accent` per spec (AUD-21 targeted layer buttons, not settings cog) |
| `frontend/src/components/builder/StackRow.tsx` | `isFresh` prop + `animate-in fade-in duration-[--motion-fast]` | VERIFIED | Lines 55, 121, 183 confirmed |
| `frontend/src/components/builder/EmptyStackState.tsx` | `eyebrowClassName` export, `--surface-0` card, `duration-[--motion-fast]` | VERIFIED | Lines 17, 86, 200, 212 confirmed; 14/14 tests |
| `frontend/src/components/builder/UnifiedStackPanel.tsx` | h-8 header buttons, eyebrowClassName usage, freshLayerId wired | VERIFIED | Lines 119, 633, 936, 967 confirmed; 29/29 tests |
| `frontend/src/components/builder/hooks/use-builder-layers.ts` | freshLayerId state + timeout lifecycle | VERIFIED | Lines 82-83, 129-131, 649-655, 952; 11/11 tests |
| `frontend/src/i18n/locales/en/builder.json` | 51 unique keys, zero duplicates, listboxLabel present | VERIFIED | Python validated; commit 7bba3694 |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `use-builder-layers.ts` freshLayerId | `UnifiedStackPanel.tsx` prop | return object + prop drilling | WIRED | Hook returns `freshLayerId`; USP accepts `freshLayerId?` prop; passed at both loose-layer and folder-group-children render sites (lines 936, 967) |
| `UnifiedStackPanel.tsx` freshLayerId prop | `StackRow.tsx` isFresh | SortableStackRow → StackRow | WIRED | `isFresh={layer.id === freshLayerId}` passed through SortableStackRowProps → StackRow at both render sites |
| `EmptyStackState.tsx` eyebrowClassName | `UnifiedStackPanel.tsx` | named export + import | WIRED | `export const eyebrowClassName` at EmptyStackState:17; used in USP basemap dock eyebrow via `cn(eyebrowClassName, 'px-3 pt-1 pb-0')` |
| `index.css` `--motion-fast` | All caret `duration-[--motion-fast]` usages | CSS custom property + Tailwind arbitrary value | WIRED | Token at line 141; consumed by LayerEditorPanel (3 carets), BasemapGroupRow, FolderGroupRow, DatasetSearchPanel (2 carets), BulkActionBar mount, StackRow entry animation, EmptyStackState transitions |
| `[data-dnd-over="true"]` bloom | Insertion line CSS | CSS attribute selector | WIRED | `index.css:520-523` targets the existing DnD insertion line element |
| DatasetSearchPanel `isLoading` | 5x Skeleton render | conditional JSX | WIRED | `isLoading && Array.from({ length: 5 }).map(...)` at line 643-648 |
| DatasetSearchPanel `isFetching && !isLoading` | progress band + dimmed list | conditional JSX + className | WIRED | Progress band at line 651-653; opacity-50 pointer-events-none at line 696 |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `DatasetSearchPanel.tsx` — skeleton/progress | `isLoading`, `isFetching` | `useQuery` at line 427 (real API fetch) | Yes — query fetches from real search API; loading states come from TanStack Query's actual fetch lifecycle | FLOWING |
| `StackRow.tsx` — isFresh animation | `isFresh` prop | `freshLayerId` from `use-builder-layers.ts` useState, set by real `handleAddDataset` onSuccess | Yes — set to real layer ID from API response | FLOWING |
| `EmptyStackState.tsx` — suggest cards | `SUGGESTED_DATASETS` + `useQuery(getDataset)` | Hand-curated static list + real API query per card | Yes — cards query real dataset IDs via `getDataset()` API | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Motion tokens in :root | `grep -c "motion-fast: 150ms" frontend/src/index.css` | 1 match | PASS |
| Bloom shadow on insertion line | `grep "9999px" frontend/src/index.css` | Line 522: `border-radius: 9999px` | PASS |
| BulkActionBar gap-2 | `grep "gap-2" frontend/src/components/builder/BulkActionBar.tsx` | Line 119 confirmed | PASS |
| builder.json uniqueness | `python3` duplicate-key check | 0 duplicates, 51 keys | PASS |
| 843 builder/pages tests | `npx vitest run src/components/builder/ src/pages/` | 843/843 pass | PASS |
| resources.test.ts parity | `npx vitest run src/i18n/resources.test.ts` | 1 failed (pre-existing — DE/FR/ES missing newer keys; Phase 1044 owns locale fill; not in 843 count) | INFO |

---

### Probe Execution

Step 7c: SKIPPED — no probe scripts exist for this phase. Phase 1042 is a pure UI polish pass with no migration probes.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| POL-13 | 1042-01, 1042-03 | Spacing/density token normalization across builder surfaces | SATISFIED | py-3→py-2 across 4 scene files (zero residual py-3 in scenes); LayerEditorPanel header px-4 py-3; all tokens from sketch-findings-geolens set |
| POL-14 | 1042-01, 1042-02, 1042-03, 1042-04 | Hover/focus/pressed/active state unification + motion tokens | SATISFIED | --surface-2 hover consistent across StackRows, SidebarRail layer buttons; --motion-fast on all carets; BulkActionBar mount animation; freshLayerId entry animation |
| POL-15 | 1042-02, 1042-04 | Loading affordances everywhere async occurs | SATISFIED | 5x skeleton on first fetch; progress band on refetch; optimistic freshLayerId entry animation on add; cursor-grab on draggable rows |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `SidebarRail.tsx` | 72 | `hover:bg-accent` on settings cog button (non-layer rail element) | Info | Settings cog retains `hover:bg-accent`; only the layer icon buttons were targeted by AUD-21 (`SidebarRail.tsx:121`). The spec specifies line 121. The settings cog at line 72 is a separate interactive element with a different visual role — this is intentional per UI-SPEC §Color AUD-21 |
| `frontend/src/i18n/resources.test.ts` | — | Pre-existing parity test failure: DE/FR/ES locales missing newer keys from Phases 1040-1042 | Info (pre-existing) | 1 test fails in resources.test.ts — not in builder/pages 843-test suite. Phase 1044 owns locale fill. Confirmed pre-existing before Phase 1042 (keys from 1040 `c7f6874e` are absent from non-EN locales) |

No TBD, FIXME, or XXX markers found in any Phase 1042 modified files.

---

### Human Verification Required

#### 1. Spacing/Density Visual Parity

**Test:** Open the map builder. Compare the UnifiedStackPanel (layer list), LayerEditorPanel (open any vector layer), Add Dataset modal, and Settings scene at 340px sidebar width.
**Expected:** Sections feel normalized — no cramped py-1 sections or over-padded py-4 anomalies. The header row of LayerEditorPanel has more breathing room (py-3) than section content rows (py-2).
**Why human:** Perceived density uniformity requires visual inspection in a running browser.

#### 2. BulkActionBar Narrow-Viewport Label Accessibility

**Test:** Select 2+ layers in the stack. With the sidebar at default width (~340px), verify the BulkActionBar action buttons (Visibility, Group, Ungroup, Delete) are usable.
**Expected:** At 340px sidebar width, `sm:inline` labels are hidden (viewport < 640px), but Tooltip labels appear on hover/focus, ensuring AT reachability. The bar slides up from `translate-y-2 opacity-0` on mount.
**Why human:** Tooltip behavior at narrow widths requires a live browser interaction. The `sm:inline` breakpoint triggers at 640px viewport, not 340px sidebar — this behavior can only be confirmed visually.

#### 3. Skeleton Loading and Progress Band

**Test:** Open the Add Data panel. Observe the initial load state, then change record-type filter tabs.
**Expected:** First load shows 5 skeleton placeholder rows at consistent height (~58px). Switching tabs shows a thin primary-colored progress band above the dimmed stale list.
**Why human:** Loading state animations require a running stack — cannot verify without live API responses.

#### 4. freshLayerId Entry Animation

**Test:** From an empty or populated map, drag a dataset from the catalog into the map stack (or use the Add button).
**Expected:** The new StackRow appears with a brief fade-in animation (approximately 150ms) and settles. The row looks normal after the animation completes.
**Why human:** Entry animation is transient visual behavior that requires a running browser at the correct zoom level.

---

### Gaps Summary

No blocking gaps found. All 10 must-haves are VERIFIED by code inspection and automated tests (843/843 pass). The 4 human verification items above are standard visual/interactive checks that require a running browser — they are expected for a UI polish phase.

The resources.test.ts parity failure is pre-existing and explicitly deferred to Phase 1044 (locale fill) — it does not affect the 843-test builder/pages suite and was present before Phase 1042.

---

_Verified: 2026-05-15T00:45:00Z_
_Verifier: Claude (gsd-verifier)_
