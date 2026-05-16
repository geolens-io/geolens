---
phase: 1048
plan: 02
artifact: adddata-modal-audit
generated: 2026-05-16
total_findings: 13
p0: 0
p1: 5
p2: 8
---

# Add Data Modal Audit (Phase 1048 FOLLOWUP-02)

## Scope

Files audited (all in `frontend/src/components/builder/`):

| File | LOC | Description |
|------|-----|-------------|
| `BuilderDialogs.tsx` | 193 | Renders 4 dialogs (Add Data, Share, Info, Unsaved-changes leave warning); wraps DatasetSearchPanel in lazy Suspense |
| `DatasetSearchPanel.tsx` | 744 | Full modal body: search input, 4-tab filter bar (All/Vector/Raster/Basemap), DraggableDatasetRow + DraggableBasemapRow sub-components, source/keyword filter chips, state views (loading skeletons, progress band, empty-catalog, zero-result, error) |

Supporting test files reviewed (not audited for quality, used for coverage verification):

| File | LOC | Coverage target |
|------|-----|-----------------|
| `__tests__/DatasetSearchPanel.test.tsx` | 499 | DatasetSearchPanel (main search states + tab routing + basemap swap) |
| `__tests__/DatasetSearchPanel.dragdrop.test.tsx` | 244 | Drag-and-drop contract (useDraggable id namespacing, grip handle aria-labels) |

## Threshold

**File-size thresholds (inherited from Phase 1046 audit pattern):**

- **P0**: >1000 LOC (component has too many concerns for safe maintenance; split required)
- **P1**: 700–1000 LOC (approaching limit; structural improvement warranted)
- **P2**: 500–700 LOC (elevated; watch for growth)

Source: Phase 1046 severity rubric; CB-07 (1204 LOC) was P0, CB-08 (1037 LOC) was P1, CB-09 (906 LOC) was P1.

DatasetSearchPanel at 744 LOC falls in the P1 band. BuilderDialogs at 193 LOC is well within threshold.

---

## Findings

### Duplication

| ID | Sev | File | Line | Description | Recommended fix | Disposition |
|----|-----|------|------|-------------|-----------------|-------------|
| ADM-A-01 | P1 | DatasetSearchPanel.tsx | 484–545 | `renderDatasetAction` and `renderBasemapAction` are inline functions defined inside `DatasetSearchPanel` and passed as render-prop callbacks to `DraggableDatasetRow` and `DraggableBasemapRow`. Both follow the same `compact` boolean pattern (compact → default/outline variant, non-compact → ghost/icon variant). The two functions are structurally similar but not duplicates (different data shapes). However, defining them as inline non-memoized functions inside the parent defeats `memo()` on the child rows — on every parent re-render a new function reference is created, busting `DraggableDatasetRow`'s and `DraggableBasemapRow`'s memoization. | Wrap both with `useCallback` (dependencies: `isAdding`, `layerByDatasetId`, `onAddDataset`, `onDuplicateRendering`, `basemapStyle`, `onBasemapChange`, etc.) so child `memo()` wrappers can bail out on re-renders caused by unrelated state (e.g., `expandedRowId` changes). | defer — P1 quality/perf improvement; memoization gap is not user-visible today since re-renders are cheap, but should be addressed before the dataset list grows to 100+ rows. |
| ADM-A-02 | P2 | DatasetSearchPanel.tsx | 258, 348 | `aria-label` strings `"Collapse ${props.title}"` and `"Expand ${props.title}"` (DraggableDatasetRow) and `"Collapse ${entry.label}"` / `"Expand ${entry.label}"` (DraggableBasemapRow) are hardcoded English strings, not passed through the `t()` i18n function. All other ARIA labels in the file use `t(...)`. | Use `t('search.expandRow', { name: props.title, defaultValue: 'Expand {{name}}' })` / `t('search.collapseRow', ...)` to keep i18n parity. | defer — P2 i18n parity gap; English-only strings in ARIA labels but not visible text; low user impact. |

### File size

| ID | Sev | File | Line | Description | Recommended fix | Disposition |
|----|-----|------|------|-------------|-----------------|-------------|
| ADM-B-01 | P1 | DatasetSearchPanel.tsx | 1–744 | 744 LOC — falls in the P1 band (700–1000 LOC). The file combines: (a) module-level utility functions (`makeBlankBasemap`, `tabRecordType`, `isRasterRecord`, `typeMeta`, `featureMeta`, `uniqueValues`), (b) two inner sub-components (`DatasetPreview`, `DatasetMetadata`, `BasemapMetadata`), (c) two DnD wrapper components (`DraggableDatasetRow`, `DraggableBasemapRow`) each with their own prop interfaces, and (d) the main exported `DatasetSearchPanel` component (385–744). | Extract the inner sub-components and module-level utilities to a `DatasetSearchPanel.helpers.tsx` (or a `DatasetSearchPanel/` directory with `index.tsx` + `components.tsx` + `utils.ts`). Target: main export file ~400 LOC, utilities ~100 LOC, sub-components ~250 LOC. | defer — P1 structural improvement; file is within threshold but approaching P0 territory. Should be addressed before adding new features to this surface. |

### Dead code

| ID | Sev | File | Line | Description | Recommended fix | Disposition |
|----|-----|------|------|-------------|-----------------|-------------|
| ADM-C-01 | P2 | DatasetSearchPanel.tsx | 20 | `useDraggable` is imported from `@dnd-kit/core` at the file top level. This import is used (in `DraggableDatasetRow` and `DraggableBasemapRow`), so the import itself is NOT dead. However, the `Shuffle` icon (line 18) from `lucide-react` is used in `renderBasemapAction` (line 541), `RotateCcw` (line 14) is used in the error retry button (line 647). All imports are live. No dead imports found. | No action — confirmed all imports are used. | resolved (not reproducible) |
| ADM-C-02 | P2 | DatasetSearchPanel.tsx | 581–631 | The filter-chip section (source + keyword chips) is conditionally rendered only when `activeTab !== 'basemap' && (sourceOptions.length > 0 || keywordOptions.length > 0 || sourceOrganization || keyword)`. The active-filter display (lines 585–597) shows the selected `sourceOrganization` as a clearable chip. When `sourceOrganization` is set, the options list (`!sourceOrganization && sourceOptions.map(...)`) is suppressed. Similarly for `keyword`. This is correct behavior and not dead code, but the condition nesting is complex enough to warrant a comment. | Add a comment above the filter chip section explaining the show/hide semantics (active chip hides alternatives). No functional change required. | defer — P2 clarity improvement; condition is functionally correct. |

### Complexity

| ID | Sev | File | Line | Description | Recommended fix | Disposition |
|----|-----|------|------|-------------|-----------------|-------------|
| ADM-D-01 | P1 | DatasetSearchPanel.tsx | 547–742 | The main render function of `DatasetSearchPanel` (line 547 onward) uses 7 separate conditional JSX blocks for loading/error/empty states, all gated by `activeTab !== 'basemap'` repeated verbatim 5 times (lines 635, 654, 661, 667, 688). This repeated guard suggests the dataset-mode vs basemap-mode branching is not abstracted — the component has two significant operational modes but the mode split leaks across the entire render body as repeated guards. | Extract dataset-mode state views (loading, refetch, error, empty, zero-result, results list) into a `<DatasetResultsView>` sub-component. The outer render becomes a simple tab switch: `activeTab === 'basemap' ? <BasemapList ... /> : <DatasetResultsView ... />`. | defer — P1 complexity; refactor is M effort and involves extracting state views; do after the file-size refactor (ADM-B-01) since they are the same structural concern. |
| ADM-D-02 | P2 | DatasetSearchPanel.tsx | 421–437 | The query key construction and `searchParams` build are inline in the component body without a comment explaining why `sourceOrganization` and `keyword` are appended as extra query-key segments beyond `queryKeys.datasetSearch.results(...)`. The intent (unique cache key per filter combination) is clear in context but could trip up future authors. | Add a comment: `// Extend queryKey so each filter combination gets its own cache slot.` | defer — P2 documentation; no functional concern. |

### Test coverage

| ID | Sev | File | Line | Description | Recommended fix | Disposition |
|----|-----|------|------|-------------|-----------------|-------------|
| ADM-E-01 | P2 | BuilderDialogs.tsx | 1–193 | No co-located test file for `BuilderDialogs.tsx`. The component renders 4 dialogs and manages the lazy Suspense boundary for DatasetSearchPanel. The dialogs themselves are tested indirectly (DatasetSearchPanel tests, SharePanel tests), but the dialog open/close prop wiring for Info dialog and the Unsaved Changes dialog (blocker state → buttons) has no unit-level isolation test. | Create `__tests__/BuilderDialogs.test.tsx` covering: (1) Info dialog renders map metadata fields; (2) Unsaved-changes dialog renders when `blockerState === 'blocked'`; (3) `onBlockerReset` / `onBlockerProceed` fire on Stay/Leave. | defer — P2 test isolation gap; dialogs are low-risk static-render components; acceptable via integration coverage for now. |
| ADM-E-02 | P1 | DatasetSearchPanel.tsx | 484–523 | `renderDatasetAction` has 3 rendering branches: (A) dataset already added → "Added" badge + "another rendering" button; (B) dataset not added, compact=false → icon button; (C) dataset not added, compact=true → text button. Branch B is tested (Test 1 in dragdrop test + main test). Branch A is tested (route 2 in main test). Branch C (compact=true in expanded row footer) is NOT directly asserted by any test — `expanded row footer` path (line 285: `{renderDatasetAction(record, true)}`) has no test verifying the compact=true rendering variant. | Add a test expanding a row and asserting the footer renders the full-text "Add to map" button (compact=true variant). | defer — P1 test-coverage gap; the branch is low-complexity and low-risk; add when building DatasetSearchPanel test polish pass. |

### Accessibility

| ID | Sev | File | Line | Description | Recommended fix | Disposition |
|----|-----|------|------|-------------|-----------------|-------------|
| ADM-F-01 | P2 | BuilderDialogs.tsx | 87–109 | The Add Data dialog uses `<Dialog open={showAddData} onOpenChange={onShowAddDataChange}>` which delegates to Radix `DialogPrimitive.Root`. Radix Dialog natively provides `aria-modal="true"`, `role="dialog"`, and focus trap via the `DialogPrimitive.Content` wrapper. The `DialogTitle` and `DialogDescription` from Radix also provide the required accessible name linkage. Accessibility primitives are handled correctly by the UI library layer. No missing aria attributes. | No action — Radix Dialog handles focus trap, aria-modal, and aria-labelledby automatically. | resolved (not reproducible) |
| ADM-F-02 | P1 | DatasetSearchPanel.tsx | 709–713 | When `isFetching && !isLoading`, the result list is dimmed with `pointer-events-none opacity-50` (line 712). This visually signals "loading" but does not announce to assistive technology users that the list is being refreshed. An `aria-busy="true"` attribute on the list container would inform screen reader users that content is being updated. The progress band (line 663) has no aria-label either. | Add `aria-busy={isFetching && !isLoading}` to the list container div (line 709). Optionally add `aria-label={t('search.refreshing', ...)}` to the progress band div. | defer — P1 accessibility gap; no keyboard-only or screen reader test coverage for this state; low user impact in practice but a correctness gap per WCAG 2.1 §4.1.3 (Status Messages). |
| ADM-F-03 | P2 | DatasetSearchPanel.tsx | 258, 348 | `aria-label` on the expand/collapse buttons contains hardcoded "Expand"/"Collapse" English strings (also flagged as ADM-A-02 for i18n). Separately as an accessibility finding: the expand button does not use `aria-expanded="true/false"` — it uses an aria-label swap pattern instead. The aria-label pattern works for screen readers but `aria-expanded` is more semantic and better supported across AT. | Prefer `aria-expanded={expanded}` + a stable `aria-label` (e.g. `t('search.rowDetails', { name: props.title })`). | defer — P2 accessibility improvement; current aria-label swap is functionally correct but aria-expanded is more canonical. |

### Performance

| ID | Sev | File | Line | Description | Recommended fix | Disposition |
|----|-----|------|------|-------------|-----------------|-------------|
| ADM-G-01 | P2 | DatasetSearchPanel.tsx | 484–545 | `renderDatasetAction` and `renderBasemapAction` are plain inline functions (not `useCallback`), passed as props to `memo()`-wrapped child rows. On every state change in the parent (e.g., `expandedRowId` change on row expand, or `isFetching` flag change), new function references are created, which causes all visible `DraggableDatasetRow` and `DraggableBasemapRow` to re-render even if their data hasn't changed. With a default result cap of 20 rows (`limit: '20'`), this is not perceptible today. If the cap grows (e.g., infinite scroll) this will become a frame-time issue. Overlaps with ADM-A-01. | Same fix as ADM-A-01: wrap both with `useCallback`. | defer — P2 perf risk (today the list is capped at 20; no perceived jank); promote to P1 if `limit` grows. |
| ADM-G-02 | P2 | DatasetSearchPanel.tsx | 654–660 | Loading skeleton uses `Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} .../>)`. Using array index as key is acceptable for a static skeleton list, but the array is re-created on every render during the loading phase. Extract as a constant outside the component body. | `const LOADING_SKELETONS = Array.from({ length: 5 }, (_, i) => i);` at module level; map over that constant. | defer — P2 micro-optimization; negligible in practice. |

---

## v1008 Unified-Stack Alignment

**Verdict: ALIGNED — no leftover six-section or pre-v1008 sidebar model assumptions found.**

### Evidence

Grep for `section`, `sections`, `SECTION_`, `six` inside both audited files returns zero matches:

```
rg -n "section|sections|six|SECTION_" \
  frontend/src/components/builder/DatasetSearchPanel.tsx \
  frontend/src/components/builder/BuilderDialogs.tsx
→ 0 matches
```

### Structural analysis

The pre-v1008 sidebar had a "six-section" structure (basemap / DEM / catalog / layers / settings / share or similar). After v1008, that structure was collapsed into the unified layer stack (basemap-as-group, DEM-as-raster-layer). The Add Data modal is a **separate surface** — it was never structurally part of the sidebar section model.

Specifically:

- `DatasetSearchPanel` organizes its UI around **4 content-type tabs** (`all | vector | raster | basemap`), controlled by `DatasetSearchTab` type (line 49). These are data-type filters for the search results — they are content-organizational, not sidebar-structural.
- The tab count of 4 is not related to the legacy six-section count (6). No hardcoded 6-element array, no `SECTION_` enum, no switch on a section identifier.
- `BuilderDialogs` renders 4 dialogs (Add Data, Share, Info, Unsaved-changes). This is a UI orchestration concern, not a sidebar model.
- Neither file references `UnifiedStackPanel`, `SidebarSection`, `SIDEBAR_SECTIONS`, or any pre-v1008 structural constant.

**Conclusion:** The Add Data modal surface is fully aligned with the v1008 unified-stack model. No migration work required.

---

## Disposition Summary

| Status | Count |
|--------|-------|
| resolved (not reproducible) | 2 (ADM-C-01, ADM-F-01) |
| deferred (rationale present) | 11 |
| shipped (1048-02 T2) | 0 |
| **Total** | **13** |

---

## Inline-Ship Budget

Phase 1048 budget: P0 inline if ≤1 hour each.

**0 P0 findings identified — no inline work.**

The audit found zero P0 findings across all seven dimensions (Duplication, File size, Dead code, Complexity, Test coverage, Accessibility, Performance). All findings are P1 or P2 with clear defer rationale. No blocking bugs, security issues, broken behavior, or pre-v1008 alignment failures were found.

**Deferred P1 findings with recommended follow-on priority:**

| ID | Dimension | Summary | Recommended timing |
|----|-----------|---------|-------------------|
| ADM-A-01 + ADM-G-01 | Duplication + Performance | `useCallback` wrapping for render-prop functions passed to memo() child rows | Before `limit: '20'` result cap is increased |
| ADM-B-01 | File size | DatasetSearchPanel 744 LOC — extract utilities + sub-components | Before adding new Add Data features |
| ADM-D-01 | Complexity | Repeated `activeTab !== 'basemap'` guards — extract DatasetResultsView | Bundle with ADM-B-01 refactor |
| ADM-E-02 | Test coverage | `renderDatasetAction` compact=true branch untested | Next DatasetSearchPanel test pass |
| ADM-F-02 | Accessibility | Missing `aria-busy` on list during refetch | Next a11y audit sweep |
