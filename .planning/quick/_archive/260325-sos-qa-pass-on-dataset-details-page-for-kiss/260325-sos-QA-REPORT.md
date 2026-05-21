# QA Report: Dataset Details Page -- KISS, DRY, Best Practices

**Date:** 2026-03-25 (corrected after verification)
**Scope:** DatasetPage.tsx + all dataset detail components, tabs, panels, and tests
**Files audited:** 39+ (27 components/tabs, 4 panels, 3 utilities referenced, 9 test files)

## Executive Summary

The dataset details page has significant technical debt across KISS, DRY, and best-practice dimensions. DatasetPage.tsx is 824 lines with 16 useState, 9 useEffect, and 10 useCallback hooks — a clear KISS violation. Four near-identical detail panels (`panels/` directory) share ~90% boilerplate. Three components are dead code with zero runtime imports. Multiple components have hardcoded English strings bypassing i18n. The issues fall into actionable categories: (1) dead code removal, (2) panel boilerplate consolidation, (3) i18n gaps, (4) DRY violations in types and utilities, (5) DatasetPage/DatasetMap complexity.

## Research Finding Disposition

| Research ID | Status | Notes |
|-------------|--------|-------|
| F1 | **CONFIRMED** | DatasetHealthStrip, AccessSharingTab, PublishButton have zero runtime imports — dead code |
| F2 | **REFINED** | Type duplication exists but between `PendingDraftField` and `SourceQualityDraftField`, not the same name |
| F3 | **CONFIRMED** | The 4 detail panels in `panels/` directory share ~90% boilerplate (PendingDraftField, DetailPanelProps) |
| F4 | **REFINED** | PublishButton is dead code (no runtime imports); F4 moot |
| F5 | **CONFIRMED** | `formatBytes` duplicated in OverviewTab.tsx (line 44) vs `@/lib/format.ts` (line 53) |
| F6 | **CONFIRMED** | DatasetPage.tsx is 824 lines with 16 useState, 9 useEffect, 10 useCallback — exceeds complexity threshold |
| F7 | **CONFIRMED** | DatasetMap.tsx is 975 lines with heavy complexity; largest file in the surface area |
| F8 | **CONFIRMED** | `isRaster` boolean computed independently in DatasetPage.tsx, ConnectDropdown.tsx, OverviewTab.tsx |
| F9 | **CONFIRMED** | `Sep` component (line 463) and `statsLine` block (line 465) defined inline in DatasetPage.tsx |
| F10 | **REFINED** | Both `DatasetPage.edit-affordances.test.tsx` and `DatasetPage.hero.test.tsx` mock AccessSharingTab |
| F11 | **CONFIRMED** | `parseDependentVrts` called twice on same error object (lines 86, 90) in DatasetDeleteDialog.tsx |
| F12 | **CONFIRMED** | AddToMapButton.tsx has 5 hardcoded English strings bypassing i18n |

## Findings by Priority

### Priority 1 -- High Impact

#### F1: Dead Code Components [BEST-PRACTICE]
- **Severity:** HIGH
- **Confidence:** HIGH
- **Files:** `frontend/src/components/dataset/DatasetHealthStrip.tsx`, `frontend/src/components/dataset/tabs/AccessSharingTab.tsx`, `frontend/src/components/dataset/PublishButton.tsx`
- **Issue:** Three components have zero runtime imports. `DatasetHealthStrip` is only imported in its own test file. `AccessSharingTab` is only referenced in test mocks (vi.mock), never imported as an actual dependency. `PublishButton` has no imports anywhere outside its own file. All three are dead code adding maintenance burden.
- **Fix:** Delete all three component files and their associated test files. Remove stale vi.mock references from `DatasetPage.edit-affordances.test.tsx` and `DatasetPage.hero.test.tsx`.
- **Effort:** Low

#### F3: Near-Identical Detail Panels [DRY]
- **Severity:** HIGH
- **Confidence:** HIGH
- **Files:** `frontend/src/components/dataset/panels/VectorDetailPanel.tsx` (113 lines), `frontend/src/components/dataset/panels/RasterDetailPanel.tsx` (66 lines), `frontend/src/components/dataset/panels/VrtDetailPanel.tsx` (72 lines), `frontend/src/components/dataset/panels/CollectionDetailPanel.tsx` (72 lines)
- **Issue:** All four panels share ~90% boilerplate: `PendingDraftField` type and `DetailPanelProps` are exported from VectorDetailPanel and imported by the other three. Each panel wires the same tab structure (OverviewTab, MetadataTab, AccessTab) with the same draftValues object and the same event handlers. The only meaningful difference is which tabs are shown per record type.
- **Fix:** Create a single `DetailPanel` component that accepts record type as a prop and conditionally renders tabs. Remove the four individual panel files. This eliminates ~200 lines of duplication.
- **Effort:** Medium

#### F6: DatasetPage.tsx Excessive Complexity [KISS]
- **Severity:** HIGH
- **Confidence:** HIGH
- **Files:** `frontend/src/pages/DatasetPage.tsx` (824 lines)
- **Issue:** DatasetPage.tsx has 16 useState, 9 useEffect, and 10 useCallback hooks in 824 lines. The draft-editing state machine (tracking pending fields, save/cancel/submit across multiple tabs) and the hero section state (edit mode, image upload, description editing) are interleaved with routing, data fetching, and tab management. This exceeds reasonable complexity for a single component.
- **Fix:** Extract draft-editing logic into a `useDraftEditing` hook. Extract hero state management into a `useHeroState` hook. This would reduce DatasetPage.tsx to ~400 lines of orchestration and rendering.
- **Effort:** Medium

#### F7: DatasetMap.tsx Complexity [KISS]
- **Severity:** HIGH
- **Confidence:** HIGH
- **Files:** `frontend/src/components/dataset/DatasetMap.tsx`
- **Issue:** At 975 lines, DatasetMap.tsx is the largest component in the dataset details surface area. It manages: map initialization, vector tile layers, raster tile layers, drawing/editing mode (TerraDraw integration), feature selection (edit + read-only), fullscreen toggle, keyboard shortcuts, basemap theme switching, two confirmation dialogs, an overlay source, and tile refresh logic. It has 7 useState hooks, 12 useEffect hooks, and 17+ useCallback hooks.
- **Fix:** Extract the tile refresh helper `refreshTileSource()` (lines 1096-1145) to a utility module. The two `AttributeForm` instances (new feature at line 1028 vs edit feature at line 1039) could share an `onSubmit` wrapper since they differ only in which mutation they invoke. The `addVectorLayers` / `addRasterLayers` / `addOverlaySource` callbacks (lines 595-758) could be grouped into a `useMapLayers` hook.
- **Effort:** Medium

#### NEW-1: ConnectDropdown.tsx Hardcoded English Strings [I18N]
- **Severity:** HIGH
- **Confidence:** HIGH
- **Files:** `frontend/src/components/dataset/ConnectDropdown.tsx`
- **Issue:** 6 hardcoded English strings bypass i18n: "Copy COG URL", "Copy XYZ Tile URL", "Copy S3 URI", "Copy API URL", "Copy Tile URL", and "Copied: ..." toast message. The component imports `useTranslation('dataset')` but doesn't use `t()` for any of these strings.
- **Fix:** Add i18n keys: `connect.copyCogUrl`, `connect.copyXyzTileUrl`, `connect.copyS3Uri`, `connect.copyApiUrl`, `connect.copyTileUrl`, `connect.copied`. Replace hardcoded strings with `t()` calls.
- **Effort:** Low

#### F12: AddToMapButton.tsx Hardcoded English Strings [I18N]
- **Severity:** HIGH
- **Confidence:** HIGH
- **Files:** `frontend/src/components/dataset/AddToMapButton.tsx`
- **Issue:** 5 hardcoded English strings: "Add to Map", "Loading maps...", "No maps available", "+ New map", and no i18n namespace import at all -- the component does not use `useTranslation`.
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

#### F9: Inline Sep Component and statsLine Block [KISS]
- **Severity:** MEDIUM
- **Confidence:** HIGH
- **Files:** `frontend/src/pages/DatasetPage.tsx` (lines 463-480)
- **Issue:** `Sep` is defined as a component inside the render body (`const Sep = () => <span ...>`) at line 463, meaning it's recreated on every render. `statsLine` (line 465) is an inline JSX block that builds a metadata stats line. Both are defined inside the component body rather than extracted.
- **Fix:** Move `Sep` outside the component as a module-level constant (it has no props or closure dependencies). Consider extracting `statsLine` to a `DatasetStatsLine` component if it grows.
- **Effort:** Low

#### F10-REVISED: Stale Test Mocks [TEST-HYGIENE]
- **Severity:** MEDIUM
- **Confidence:** HIGH
- **Files:** `frontend/src/pages/__tests__/DatasetPage.edit-affordances.test.tsx` (line 74), `frontend/src/pages/__tests__/DatasetPage.hero.test.tsx` (line 92)
- **Issue:** Both test files mock `@/components/dataset/tabs/AccessSharingTab` with a stub component. Since AccessSharingTab is dead code (F1), these mocks reference a component that has no runtime consumers. The mocks succeed silently and add confusion about whether AccessSharingTab is actually used.
- **Fix:** Remove the vi.mock calls for AccessSharingTab from both test files when AccessSharingTab is deleted (F1).
- **Effort:** Low

#### F11: parseDependentVrts Double-Call [DRY/PERF]
- **Severity:** MEDIUM
- **Confidence:** HIGH
- **Files:** `frontend/src/components/dataset/DatasetDeleteDialog.tsx` (lines 86, 90)
- **Issue:** `parseDependentVrts` is called twice on the same error object — once at line 86 for a condition check and again at line 90 for data extraction. Each call parses the same JSON string via `JSON.parse`. This is a minor DRY violation and unnecessary double-parse.
- **Fix:** Cache the result: `const dependentVrts = parseDependentVrts(error); if (dependentVrts) { /* use dependentVrts */ }`.
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
| Files audited | 39+ |
| Total findings | 18 |
| HIGH severity | 7 (F1, F3, F6, F7, NEW-1, F12, NEW-2) |
| MEDIUM severity | 6 (F2-REVISED, F5, F8, F9, F10-REVISED, F11) |
| LOW severity | 5 (NEW-3, NEW-4, NEW-5, NEW-6, NEW-7, NEW-8, NEW-9) |
| Dead code files | 3 (DatasetHealthStrip, AccessSharingTab, PublishButton) |
| DRY violations | 5 (F2-REVISED, F3, F5, F8, F11, NEW-5) |
| KISS violations | 4 (F6, F7, F9, NEW-3, NEW-4) |
| I18N violations | 3 (NEW-1, F12, NEW-2) |
| BEST-PRACTICE violations | 4 (F1, NEW-7, NEW-8, NEW-9) |
| TEST-HYGIENE issues | 1 (F10-REVISED) |
| Estimated total cleanup effort | Medium |

## Recommended Refactoring Sequence

1. **Delete dead code (F1)** -- Remove DatasetHealthStrip, AccessSharingTab, PublishButton and their test files. Remove stale vi.mock references (F10). Zero risk, immediate reduction in maintenance burden.

2. **I18N sweep (NEW-1, F12, NEW-2)** -- Low effort, high consistency impact. Add i18n keys to ConnectDropdown, AddToMapButton, UsedInMaps. Standalone changes with no cross-file dependencies. Add locale entries to `en`, `de`, `fr`, `es`.

3. **Delete duplicate formatBytes (F5)** -- One-line import change in OverviewTab.tsx. Remove local function, import from `@/lib/format`. No risk.

4. **Fix parseDependentVrts double-call (F11)** -- Cache result in a variable. One-line change.

5. **Move Sep component outside render body (F9)** -- Move to module scope. No behavior change.

6. **Consolidate draft field types (F2-REVISED)** -- Create shared `DraftableMetadataField` type. Type-only changes, low risk.

7. **Record-type flags utility (F8)** -- Create `lib/record-type.ts` and update 3 consuming files. No behavior change.

8. **Extract large-extent zoom helper (NEW-5)** -- Extract shared helper from DatasetMap.tsx. Pure function, easy to test.

9. **Fix SectionCapabilityHint reason passthrough (NEW-9)** -- One-line fix. Pass through actual capability reason.

10. **Fix SchemaEditor variable shadowing (NEW-7)** -- Rename iterator variable. Cosmetic.

11. **Consolidate detail panels (F3)** -- Create single `DetailPanel` component, remove 4 panel files. Medium effort, ~200 lines removed.

12. **Extract DatasetPage hooks (F6)** -- Extract `useDraftEditing` and `useHeroState` hooks. Medium effort, reduces DatasetPage.tsx by ~50%.

13. **SourceQualityTab card extraction (NEW-3)** -- Extract SpatialExtentCard and TemporalExtentCard. Medium effort.

14. **DatasetMap.tsx refactoring (F7)** -- Extract `refreshTileSource` to utility, consider `useMapLayers` hook. Largest effort, save for a dedicated refactoring pass.

Items 1-10 can each be done independently in under 30 minutes. Items 11-14 should be planned as dedicated refactoring tasks.
