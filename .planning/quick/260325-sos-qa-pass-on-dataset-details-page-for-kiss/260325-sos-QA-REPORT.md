# QA Report: Dataset Details Page -- KISS, DRY, Best Practices

**Date:** 2026-03-25
**Scope:** DatasetPage.tsx + all dataset detail components, tabs, and tests
**Files audited:** 39 (27 components/tabs, 3 utilities referenced, 9 test files)

## Executive Summary

The dataset details page is well-structured after significant refactoring in v12.x. The original research findings (F1-F12) were calibrated against a prior codebase snapshot and require substantial correction. The detail panel boilerplate (F3) no longer exists, the "dead" components (F1) are all actively imported, and DatasetPage.tsx has been trimmed from ~825 lines to ~497 lines. The remaining issues center on: (1) DRY violations in type definitions and record-type branching, (2) a duplicated `formatBytes` utility, (3) hardcoded English strings bypassing i18n in several components, and (4) DatasetMap.tsx at 1146 lines being the largest component in the surface area.

## Research Finding Disposition

| Research ID | Status | Notes |
|-------------|--------|-------|
| F1 | **REJECTED** | DatasetHealthStrip, AccessSharingTab, PublishButton are all actively imported and used |
| F2 | **REFINED** | Type duplication exists but between `PendingDraftField` and `SourceQualityDraftField`, not the same name |
| F3 | **REJECTED** | The 4 detail panels (VectorDetailPanel, etc.) do not exist in the codebase; no `panels/` directory |
| F4 | **REFINED** | PublishButton is actively used; no duplication with DatasetPage since page delegates to PublishButton |
| F5 | **CONFIRMED** | `formatBytes` duplicated in OverviewTab.tsx (line 42) vs `@/lib/format.ts` (line 21) |
| F6 | **REFINED** | DatasetPage.tsx is 497 lines with ~8 useState, ~3 useEffect, ~7 useCallback -- well within acceptable limits |
| F7 | **CONFIRMED** | DatasetMap.tsx is 1146 lines with heavy complexity; largest file in the surface area |
| F8 | **CONFIRMED** | `isRaster` boolean computed independently in DatasetPage.tsx, ConnectDropdown.tsx, OverviewTab.tsx |
| F9 | **REJECTED** | The `statsLine` variable and inline `Sep` component do not exist in current DatasetPage.tsx |
| F10 | **REFINED** | Only `DatasetPage.edit-affordances.test.tsx` still mocks AccessSharingTab (line 67); other test files are clean |
| F11 | **REJECTED** | `parseDependentVrts` does not appear in DatasetDeleteDialog.tsx |
| F12 | **CONFIRMED** | AddToMapButton.tsx has 5 hardcoded English strings bypassing i18n |

## Findings by Priority

### Priority 1 -- High Impact

#### F7: DatasetMap.tsx Complexity [KISS]
- **Severity:** HIGH
- **Confidence:** HIGH
- **Files:** `frontend/src/components/dataset/DatasetMap.tsx`
- **Issue:** At 1146 lines, DatasetMap.tsx is the largest component in the dataset details surface area. It manages: map initialization, vector tile layers, raster tile layers, drawing/editing mode (TerraDraw integration), feature selection (edit + read-only), fullscreen toggle, keyboard shortcuts, basemap theme switching, two confirmation dialogs, an overlay source, and tile refresh logic. It has 6 useState hooks, 12 useEffect hooks, and 17+ useCallback hooks.
- **Fix:** Extract the tile refresh helper `refreshTileSource()` (lines 1096-1145) to a utility module. The two `AttributeForm` instances (new feature at line 1028 vs edit feature at line 1039) could share an `onSubmit` wrapper since they differ only in which mutation they invoke. The `addVectorLayers` / `addRasterLayers` / `addOverlaySource` callbacks (lines 595-758) could be grouped into a `useMapLayers` hook.
- **Effort:** Medium

#### NEW-1: ConnectDropdown.tsx Hardcoded English Strings [I18N]
- **Severity:** HIGH
- **Confidence:** HIGH
- **Files:** `frontend/src/components/dataset/ConnectDropdown.tsx`
- **Issue:** 6 hardcoded English strings bypass i18n: "Copy COG URL" (line 49), "Copy XYZ Tile URL" (line 61), "Copy S3 URI" (line 69), "Copy Feature URL" (line 80), "Copy Tile URL" (line 90), and "Copied: ..." toast message (line 21). The component already imports `useTranslation('dataset')` but doesn't use it for these strings.
- **Fix:** Add i18n keys: `connect.copyCogUrl`, `connect.copyXyzTileUrl`, `connect.copyS3Uri`, `connect.copyFeatureUrl`, `connect.copyTileUrl`, `connect.copied`. Replace hardcoded strings with `t()` calls.
- **Effort:** Low

#### F12: AddToMapButton.tsx Hardcoded English Strings [I18N]
- **Severity:** HIGH
- **Confidence:** HIGH
- **Files:** `frontend/src/components/dataset/AddToMapButton.tsx`
- **Issue:** 5 hardcoded English strings: "Add to Map" (line 35), "Loading maps..." (line 40), "No maps available" (line 42), "+ New map" (line 52), and no i18n namespace import at all -- the component does not use `useTranslation`.
- **Fix:** Add `useTranslation('dataset')` and replace with i18n keys: `addToMap.button`, `addToMap.loading`, `addToMap.noMaps`, `addToMap.newMap`.
- **Effort:** Low

#### NEW-2: UsedInMaps.tsx Hardcoded English String [I18N]
- **Severity:** HIGH
- **Confidence:** HIGH
- **Files:** `frontend/src/components/dataset/UsedInMaps.tsx`
- **Issue:** "Used in Maps" title (line 23) is a hardcoded English string. The component does not import `useTranslation`. All sibling components in the surface area use i18n.
- **Fix:** Add `useTranslation('dataset')` and use a key like `usedInMaps.title`.
- **Effort:** Low

### Priority 2 -- Medium Impact

#### F2-REVISED: PendingDraftField / SourceQualityDraftField Type Overlap [DRY]
- **Severity:** MEDIUM
- **Confidence:** HIGH
- **Files:** `frontend/src/pages/DatasetPage.tsx` (lines 52-61), `frontend/src/components/dataset/tabs/SourceQualityTab.tsx` (lines 38-46)
- **Issue:** `PendingDraftField` in DatasetPage.tsx and `SourceQualityDraftField` in SourceQualityTab.tsx define the same 8 string literal union members. DatasetPage uses `PendingDraftField` plus `'summary'` (9 fields total). SourceQualityTab exports `SourceQualityDraftField` (8 fields). MetadataTab imports `SourceQualityDraftField`. The overlap is 8/9 fields -- only `'summary'` is unique to DatasetPage.
- **Fix:** Define a shared `DraftableMetadataField` type in a shared types file (e.g., `@/types/dataset-drafts.ts`) that both consumers import. DatasetPage can extend it with `| 'summary'`.
- **Effort:** Low

#### F5: formatBytes Duplicated [DRY]
- **Severity:** MEDIUM
- **Confidence:** HIGH
- **Files:** `frontend/src/components/dataset/tabs/OverviewTab.tsx` (lines 42-47), `frontend/src/lib/format.ts` (line 21)
- **Issue:** OverviewTab defines a local `formatBytes(bytes: number)` that handles GB/MB/KB/B conversion. The shared `@/lib/format.ts` exports `formatBytes(bytes: number | null)` that additionally handles `null` input and uses `toLocaleString` for formatting.
- **Fix:** Delete the local `formatBytes` from OverviewTab.tsx, import from `@/lib/format`. The shared version is strictly more capable.
- **Effort:** Low

#### F8: Record-Type Branching Pattern [DRY]
- **Severity:** MEDIUM
- **Confidence:** MEDIUM
- **Files:** `frontend/src/pages/DatasetPage.tsx` (line 334), `frontend/src/components/dataset/ConnectDropdown.tsx` (line 29), `frontend/src/components/dataset/tabs/OverviewTab.tsx` (line 106)
- **Issue:** `const isRaster = dataset.record_type === 'raster_dataset'` is computed independently in 3 files. DatasetPage also has tab-visibility logic based on `isRaster`. As more record types are added, each file must be updated independently.
- **Fix:** Create a small utility:
  ```typescript
  // lib/record-type.ts
  export function getRecordTypeFlags(recordType: string | null) {
    return {
      isRaster: recordType === 'raster_dataset',
      isVrt: recordType === 'vrt_dataset',
      isTable: recordType === 'table',
      isVector: recordType === 'vector_dataset' || !recordType,
      isSpatial: recordType !== 'table',
    };
  }
  ```
- **Effort:** Low

#### F10-REVISED: Stale Test Mock [TEST-HYGIENE]
- **Severity:** MEDIUM
- **Confidence:** HIGH
- **Files:** `frontend/src/pages/__tests__/DatasetPage.edit-affordances.test.tsx` (lines 67-69)
- **Issue:** The test file mocks `@/components/dataset/tabs/AccessSharingTab` with a stub component. AccessSharingTab exists and IS used (it's imported by OverviewTab), so the mock is technically correct but misleading -- the mock replaces the real component with a stub, meaning the test does not exercise AccessSharingTab rendering within OverviewTab. The mock succeeds silently. This is a test fidelity concern, not a dead code issue.
- **Fix:** Either remove the mock if OverviewTab rendering of AccessSharingTab should be tested, or document why the mock is intentional (likely to isolate the edit-affordances test from AccessSharingTab network requests).
- **Effort:** Low

#### NEW-3: SourceQualityTab.tsx Size [KISS]
- **Severity:** MEDIUM
- **Confidence:** MEDIUM
- **Files:** `frontend/src/components/dataset/tabs/SourceQualityTab.tsx`
- **Issue:** At 529 lines, SourceQualityTab is the second-largest component in the tab hierarchy. It renders 6 cards (Spatial Extent, Temporal Extent, Source Information, Quality, Quality Score, Theme Category, Governance) with 5 inline callback handlers and 3 AI draft flows. The spatial/temporal sections are read-only presentation that could be separate small components.
- **Fix:** Consider extracting `SpatialExtentCard` and `TemporalExtentCard` as standalone components (~40-50 lines each). This would drop SourceQualityTab to ~440 lines and improve testability.
- **Effort:** Low

### Priority 3 -- Low Impact / Nice-to-Have

#### NEW-4: ReuploadDialog.tsx State Machine Complexity [KISS]
- **Severity:** LOW
- **Confidence:** MEDIUM
- **Files:** `frontend/src/components/dataset/ReuploadDialog.tsx`
- **Issue:** At 719 lines with 11-state state machine (`ReuploadStep`), 10 useState hooks, and 9 useCallback hooks. The step-based rendering switch (`step === 'source-select'`, `step === 'file-select'`, etc.) is clear but verbose. Not currently a maintainability problem since the state machine is linear and well-documented.
- **Fix:** No immediate action needed. If features are added (e.g., new source types), consider extracting a `useReuploadStateMachine` hook to encapsulate the state transitions and handlers.
- **Effort:** N/A (deferred)

#### NEW-5: DatasetMap.tsx Large-Extent Zoom Calculation Duplication [DRY]
- **Severity:** LOW
- **Confidence:** HIGH
- **Files:** `frontend/src/components/dataset/DatasetMap.tsx` (lines 505-515 and lines 908-922)
- **Issue:** The large-extent zoom calculation (`Math.log2(360 / lonSpan)`, clamped center latitude, zoom floor) is implemented twice: once in `handleZoomToExtent` (line 501) and once in `initialViewState` setup (line 900). Both compute the same values with the same formula.
- **Fix:** Extract a `computeLargeExtentView(bbox)` helper that returns `{ center, zoom }`. Use in both locations.
- **Effort:** Low

#### NEW-6: AttributeTable and AttributeMetadataTable Inline Cell Editor Pattern [DRY]
- **Severity:** LOW
- **Confidence:** MEDIUM
- **Files:** `frontend/src/components/dataset/AttributeTable.tsx` (lines 35-78), `frontend/src/components/dataset/AttributeMetadataTable.tsx` (lines 115-151)
- **Issue:** Both tables implement an inline cell editing pattern with: (1) tracking `editingCell` state, (2) Input with Enter/Escape key handlers, (3) onBlur save, (4) mutation call with toast feedback. The `InlineCellEditor` in AttributeTable (lines 35-78) and the `renderCell` function in AttributeMetadataTable (lines 115-151) share the same behavior.
- **Fix:** Consider a shared `useInlineCellEdit` hook or a shared `InlineCellEditor` component. Currently the duplication is modest (each is ~40 lines) and the tables have different data shapes, so the benefit is marginal.
- **Effort:** Low

#### NEW-7: SchemaEditor.tsx Variable Shadowing [BEST-PRACTICE]
- **Severity:** LOW
- **Confidence:** HIGH
- **Files:** `frontend/src/components/dataset/SchemaEditor.tsx` (lines 203-208)
- **Issue:** In the `SelectContent` for column types, the `.map()` callback uses `(t)` as the iterator variable (line 204), which shadows the `t` from `useTranslation`. This is not a bug because the `t` translator is not used inside the callback, but it reduces readability.
- **Fix:** Rename the iterator variable: `{ALLOWED_TYPES.map((type) => (...))}`.
- **Effort:** Low

#### NEW-8: DistributionsList.tsx Legacy Clipboard Fallback [BEST-PRACTICE]
- **Severity:** LOW
- **Confidence:** HIGH
- **Files:** `frontend/src/components/dataset/DistributionsList.tsx` (lines 73-87)
- **Issue:** The `CopyableUrl` component's `handleCopy` function falls back to `document.execCommand('copy')` (line 84) when `navigator.clipboard.writeText` fails. `execCommand('copy')` is deprecated. All modern browsers support `navigator.clipboard.writeText`. The fallback adds DOM manipulation complexity for a case that effectively never triggers.
- **Fix:** Remove the `catch` fallback and let the clipboard API handle the error. Or if paranoid, show a toast with the URL for manual copying.
- **Effort:** Low

#### NEW-9: SectionCapabilityHint Hardcoded "read_only_field" Reason [BEST-PRACTICE]
- **Severity:** LOW
- **Confidence:** MEDIUM
- **Files:** `frontend/src/components/dataset/SectionCapabilityHint.tsx` (line 23)
- **Issue:** `SectionCapabilityHint` always passes `reason="read_only_field"` to `RoleCapabilityHint`, regardless of the actual capability reason. The component ignores `capability.reason` and hardcodes a reason. This means the hint message always says "read only" even if the actual reason is `insufficient_role`.
- **Fix:** Pass `capability.reason ?? 'read_only_field'` to `RoleCapabilityHint` to preserve the actual reason.
- **Effort:** Low

## Metrics Summary

| Metric | Value |
|--------|-------|
| Files audited | 39 |
| Total findings | 13 |
| HIGH severity | 4 |
| MEDIUM severity | 5 |
| LOW severity | 4 |
| Dead code files | 0 |
| DRY violations | 4 (F2-REVISED, F5, F8, NEW-5) |
| KISS violations | 3 (F7, NEW-3, NEW-4) |
| I18N violations | 3 (NEW-1, F12, NEW-2) |
| BEST-PRACTICE violations | 3 (NEW-7, NEW-8, NEW-9) |
| TEST-HYGIENE issues | 1 (F10-REVISED) |
| Estimated total cleanup effort | Low-Medium |

## Recommended Refactoring Sequence

1. **I18N sweep (NEW-1, F12, NEW-2)** -- Lowest effort, highest consistency impact. Add i18n keys to ConnectDropdown, AddToMapButton, UsedInMaps. These are standalone changes with no cross-file dependencies. Add locale entries to `en`, `de`, `fr`, `es` translation files.

2. **Delete duplicate formatBytes (F5)** -- One-line import change in OverviewTab.tsx. Remove local function, import from `@/lib/format`. No risk.

3. **Consolidate draft field types (F2-REVISED)** -- Create a shared `DraftableMetadataField` type. Update DatasetPage.tsx and SourceQualityTab.tsx imports. Low risk since these are type-only changes.

4. **Record-type flags utility (F8)** -- Create `lib/record-type.ts` and update 3 consuming files. No behavior change.

5. **Extract large-extent zoom helper (NEW-5)** -- Extract shared helper from DatasetMap.tsx. Pure function, easy to test.

6. **Fix SectionCapabilityHint reason passthrough (NEW-9)** -- One-line fix. Pass through the actual capability reason.

7. **Fix SchemaEditor variable shadowing (NEW-7)** -- Rename iterator variable. Cosmetic.

8. **SourceQualityTab card extraction (NEW-3)** -- Extract SpatialExtentCard and TemporalExtentCard. Medium effort but improves testability.

9. **DatasetMap.tsx refactoring (F7)** -- Extract `refreshTileSource` to utility, consider `useMapLayers` hook. Largest effort, save for a dedicated refactoring pass.

10. **Address stale test mock (F10-REVISED)** -- Evaluate whether the AccessSharingTab mock in edit-affordances test is intentional or stale.

Items 1-7 can each be done independently in under 30 minutes. Items 8-9 should be planned as a dedicated refactoring task. Item 10 requires test understanding before acting.
