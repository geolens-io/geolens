# QA Pass: Dataset Details Page - Research

**Researched:** 2026-03-25
**Domain:** DatasetPage.tsx + 30 related components/hooks
**Confidence:** HIGH

## Summary

The dataset details page (`DatasetPage.tsx`) is a functional and well-organized page but has accumulated several KISS/DRY violations across its 825-line main component, 975-line DatasetMap component, and 4 nearly-identical detail panel wrappers. The most impactful findings are: (1) duplicated type definitions and boilerplate across the 4 detail panels, (2) 3 dead/orphaned components, (3) publish/unpublish logic duplicated between DatasetPage and the unused PublishButton component, (4) a `formatBytes` utility duplicated locally when it already exists in `@/lib/format`, and (5) DatasetPage.tsx carrying too much state (16 useState, 9 useEffect, 10 useCallback).

**Primary recommendation:** Extract draft-editing state management into a custom hook, consolidate the 4 detail panels into a single data-driven component, and delete dead code.

## Findings

### F1: Dead / Orphaned Components (HIGH confidence)

Three components exist in the codebase but are never imported by any runtime code:

| Component | File | Status |
|-----------|------|--------|
| `DatasetHealthStrip` | `components/dataset/DatasetHealthStrip.tsx` | Only imported by its own test file. The OverviewTab has its own inline health/QA block that replaced this. |
| `AccessSharingTab` | `components/dataset/tabs/AccessSharingTab.tsx` | Not imported anywhere (only mocked in test files via stale vi.mock). Replaced by `AccessTab.tsx`. |
| `PublishButton` | `components/dataset/PublishButton.tsx` | Not imported anywhere. DatasetPage inlines the same publish/unpublish logic. |

**Action:** Delete all three files and their orphaned test stubs. Remove the stale `vi.mock` references in `DatasetPage.hero.test.tsx` and `DatasetPage.edit-affordances.test.tsx`.

### F2: DRY Violation -- PendingDraftField Type Duplicated (HIGH confidence)

`PendingDraftField` is defined identically in two places:
- `pages/DatasetPage.tsx` (lines 72-81)
- `components/dataset/panels/VectorDetailPanel.tsx` (lines 11-20)

Both are the exact same 9-field union type. The VectorDetailPanel exports it and the other 3 panels import it from there, but DatasetPage.tsx defines its own private copy.

**Action:** Keep the export in `VectorDetailPanel.tsx` (or move to a shared types file) and import it in DatasetPage.tsx.

### F3: DRY Violation -- Detail Panel Boilerplate (HIGH confidence)

The 4 detail panels (`VectorDetailPanel`, `RasterDetailPanel`, `VrtDetailPanel`, `CollectionDetailPanel`) share ~90% identical code:
- Same prop interface (`DetailPanelProps`)
- Same Tabs/TabsList/TabsContent wrapper
- Identical OverviewTab rendering (lines 30-39 in each)
- Identical MetadataTab rendering with the same 8-field `draftValues` object copy-pasted verbatim 4 times
- Identical AccessTab rendering

The only differences: which tabs to show and one unique tab per panel (Data/Structure for vector, Sources for VRT, Members for collection).

**Action:** Consolidate into a single `DatasetDetailPanel` component that receives a `tabConfig` array. The MetadataTab draftValues object should be built once, not copy-pasted.

### F4: DRY Violation -- Publish/Unpublish Logic (HIGH confidence)

The publish lifecycle transition (`['ready', 'internal', 'published']` / `['internal', 'ready', 'draft']`) is implemented in three places:
1. `DatasetPage.tsx` `handlePublishToggle` (lines 427-446)
2. `DatasetPage.tsx` `handleUnpublish` (lines 448-461)
3. `PublishButton.tsx` `handleClick` + `handleUnpublish` (lines 45-82)

PublishButton is dead code (see F1), but the two survivors in DatasetPage.tsx are also split across two inline functions that share the same pattern. The unpublish confirmation dialog in DatasetPage (lines 806-821) duplicates the same dialog from PublishButton.

**Action:** Since PublishButton is deleted (F1), extract the transition logic into a helper function like `transitionPublicationStatus(updateMutation, datasetId, steps[])`.

### F5: DRY Violation -- formatBytes Duplicated (HIGH confidence)

`formatBytes` is defined locally in `OverviewTab.tsx` (lines 44-48) when an identical utility already exists in `@/lib/format.ts` (line 53). The lib version also handles `null` input.

**Action:** Delete the local `formatBytes` from OverviewTab.tsx, import from `@/lib/format`.

### F6: KISS Violation -- DatasetPage.tsx State Overload (HIGH confidence)

DatasetPage.tsx has **16 useState hooks**, **9 useEffect hooks**, and **10 useCallback hooks** in a single component. This creates:
- Difficult-to-follow state interactions
- Large dependency arrays
- Hard-to-test render behavior

Key state clusters that could be extracted:

| Cluster | States | Effects | Extract To |
|---------|--------|---------|------------|
| Draft editing | `pendingDrafts`, `dirtyFields`, `isSavingPendingEdits`, `pendingNavigationAnchor` | blur+save, navigation anchor focus | `usePendingDrafts()` hook |
| Hero state machine | `heroState`, `retryCount`, `mapKey` | 10s timeout, id reset, no-tile skip | `useHeroState()` hook |
| Publish flow | `unpublishConfirmOpen` | (none) | Inline in PublishButton if revived, or keep simple |

**Action:** Extract `usePendingDrafts(dataset, updateDataset)` hook to encapsulate all draft state, staging, save, discard, and navigation logic. Extract `useHeroState(id, dataset)` hook for the raster/VRT hero loading state machine.

### F7: KISS Violation -- DatasetMap.tsx Complexity (MEDIUM confidence)

DatasetMap.tsx is 975 lines with 7 useState, 12 useEffect, and 17 useCallback hooks. It manages:
- Map initialization
- Vector tile layer management
- Raster tile layer management
- Drawing/editing mode (TerraDraw integration)
- Feature selection (editing + read-only)
- Fullscreen toggle
- Keyboard shortcuts
- Basemap theme switching
- Multiple confirmation dialogs

The drawing/editing concerns could be further separated, but this component was already refactored in v12.3 (extracting `useFeatureEditing` and `useTerraDraw`). The current complexity is partly inherent to the map interaction domain. The component is at the edge but not egregiously over the line.

**Action:** No immediate extraction needed, but the two `AttributeForm` instances (new feature + edit feature) could share more code -- their `onSubmit` handlers differ only in which function they call.

### F8: Inline Record-Type Branching Pattern (MEDIUM confidence)

The `isRaster` / `isVrt` / `isTable` / `isRasterOrVrt` boolean pattern is computed independently in 6+ files:
- `DatasetPage.tsx` (3 booleans + 1 derived)
- `ConnectDropdown.tsx` (3 booleans)
- `OverviewTab.tsx` (2 booleans)
- `AccessTab.tsx` (2 booleans)
- `AccessSharingTab.tsx` (2 booleans -- dead)
- `VectorDetailPanel.tsx` (1 boolean)

**Action:** Consider a small utility or shared type guard:
```typescript
// lib/record-type.ts
export function getRecordTypeFlags(recordType: string | null) {
  return {
    isRaster: recordType === 'raster_dataset',
    isVrt: recordType === 'vrt_dataset',
    isTable: recordType === 'table',
    isVector: recordType === 'vector_dataset' || !recordType,
    isRasterOrVrt: recordType === 'raster_dataset' || recordType === 'vrt_dataset',
    isSpatial: recordType !== 'table',
  };
}
```

### F9: statsLine Inline JSX Complexity (LOW confidence)

The `statsLine` variable (lines 465-551 in DatasetPage.tsx) is an 86-line inline JSX block with 3-way branching on record type and a local `Sep` component defined per render. While it works, it is dense and could be a small `<DatasetStatsLine dataset={dataset} />` component.

The `Sep` component (`const Sep = () => <span ...>`) is redefined on every render. This is harmless performance-wise but would be cleaner as a module-level const.

**Action:** Move `Sep` to module scope. Optionally extract `statsLine` to a `DatasetStatsLine` component.

### F10: Test Mock Drift (MEDIUM confidence)

Test files `DatasetPage.hero.test.tsx` and `DatasetPage.edit-affordances.test.tsx` still mock `AccessSharingTab` which no longer exists in production code. The mocks succeed because vi.mock does not validate the target module exists. This means tests pass but are testing against stale component wiring.

**Action:** Remove stale mocks when deleting `AccessSharingTab`.

### F11: parseDependentVrts Double-Call (LOW confidence)

In `DatasetDeleteDialog.tsx`, `parseDependentVrts(deleteDataset.error)` is called twice on the same error object (line 86 for the check, line 90 for the data). The function does `JSON.parse` on each call.

**Action:** Store result in a variable: `const vrts = parseDependentVrts(...)`.

### F12: Hardcoded Strings in AddToMapButton (LOW confidence)

`AddToMapButton.tsx` has several hardcoded English strings that bypass i18n: "Add to Map", "Loading maps...", "No maps available", "+ New map", "Creating...", "Failed to create map". All other components in the dataset details page use `useTranslation('dataset')`.

**Action:** Add i18n keys for these strings.

## Priority Summary

| Priority | Finding | Effort | Impact |
|----------|---------|--------|--------|
| 1 | F1: Delete 3 dead components | Low | Reduces confusion, removes dead code |
| 2 | F6: Extract usePendingDrafts hook | Medium | Drops DatasetPage from 825 to ~600 lines |
| 3 | F3: Consolidate 4 detail panels | Medium | Eliminates ~200 lines of duplicated boilerplate |
| 4 | F2: Deduplicate PendingDraftField | Low | Single source of truth for type |
| 5 | F5: Use shared formatBytes | Low | Remove local copy |
| 6 | F4: Extract publish transition helper | Low | DRY the state machine steps |
| 7 | F8: Record-type flag utility | Low | Centralizes branching logic |
| 8 | F10: Fix stale test mocks | Low | Test hygiene |
| 9 | F11: Cache parseDependentVrts | Low | Micro-optimization, cleaner code |
| 10 | F12: i18n for AddToMapButton | Low | Consistency |
| 11 | F9: Extract statsLine / module-scope Sep | Low | Readability |

## Project Constraints (from CLAUDE.md)

- Prefer simple, readable code over clever abstractions
- Follow existing project conventions when editing files
- Never indicate AI/Bot activity in commit messages
