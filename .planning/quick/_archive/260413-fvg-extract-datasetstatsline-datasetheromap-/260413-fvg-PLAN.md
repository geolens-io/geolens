---
phase: 260413-fvg
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/pages/components/DatasetStatsLine.tsx
  - frontend/src/pages/components/DatasetHeroMap.tsx
  - frontend/src/pages/components/BuilderSidebar.tsx
  - frontend/src/pages/DatasetPage.tsx
  - frontend/src/pages/MapBuilderPage.tsx
autonomous: true
requirements: [EXTRACT-STATSLINE, EXTRACT-HEROMAP, EXTRACT-SIDEBAR]

must_haves:
  truths:
    - "DatasetPage renders identically before and after extraction (no visual or behavioral change)"
    - "MapBuilderPage renders identically before and after extraction (no visual or behavioral change)"
    - "All three existing test suites pass without modification"
    - "TypeScript compiles with zero errors"
  artifacts:
    - path: "frontend/src/pages/components/DatasetStatsLine.tsx"
      provides: "Stats bar component (record type badge, geometry, feature count, EPSG, 3D, raster/VRT stats, visibility, status, updated date)"
      exports: ["DatasetStatsLine"]
    - path: "frontend/src/pages/components/DatasetHeroMap.tsx"
      provides: "Hero map container with skeleton, error overlay, retry, no-tile badge"
      exports: ["DatasetHeroMap"]
    - path: "frontend/src/pages/components/BuilderSidebar.tsx"
      provides: "Desktop sidebar with resize handle, collapse, header inputs, button tray, SidebarContent"
      exports: ["BuilderSidebar", "SidebarContent"]
  key_links:
    - from: "frontend/src/pages/DatasetPage.tsx"
      to: "frontend/src/pages/components/DatasetStatsLine.tsx"
      via: "<DatasetStatsLine dataset={dataset} rasterGsd={rasterGsd} />"
      pattern: "DatasetStatsLine"
    - from: "frontend/src/pages/DatasetPage.tsx"
      to: "frontend/src/pages/components/DatasetHeroMap.tsx"
      via: "<DatasetHeroMap ... />"
      pattern: "DatasetHeroMap"
    - from: "frontend/src/pages/MapBuilderPage.tsx"
      to: "frontend/src/pages/components/BuilderSidebar.tsx"
      via: "<BuilderSidebar ... /> and SidebarContent import for mobile Sheet"
      pattern: "BuilderSidebar|SidebarContent"
---

<objective>
Extract three large JSX blocks into standalone components to reduce DatasetPage.tsx (~720 lines) and MapBuilderPage.tsx (~697 lines) by ~250+ lines combined.

Purpose: Pure refactor for maintainability. No behavior changes. All existing tests must continue to pass.
Output: Three new component files in `frontend/src/pages/components/`, two slimmed parent pages.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@docs-internal/audits/post-impl-20260413-deferred-plans.md
@frontend/src/pages/DatasetPage.tsx
@frontend/src/pages/MapBuilderPage.tsx
@frontend/src/types/api.ts (for DatasetResponse type)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Extract DatasetStatsLine component</name>
  <files>frontend/src/pages/components/DatasetStatsLine.tsx, frontend/src/pages/DatasetPage.tsx</files>
  <action>
1. Create directory `frontend/src/pages/components/` if it does not exist.

2. Create `frontend/src/pages/components/DatasetStatsLine.tsx`:
   - Define a local `Sep` component: `const Sep = () => <span className="text-muted-foreground/50">·</span>;`
   - Define props interface: `{ dataset: DatasetResponse; rasterGsd: number | null }`
   - Derive `isTable` internally: `const isTable = dataset.record_type === 'table'`
   - Move the entire `statsLine` JSX block (DatasetPage.tsx lines 348-445) into the component's return.
   - The component returns a fragment containing the two divs (stats row + status/visibility/updated row).
   - Import everything the block needs: `useTranslation` (namespace `'dataset'`), `Eye`/`EyeOff`/`ShieldAlert` from lucide, `RecordTypeBadge`, `Badge`, `cn`, `visibilityColors`, `formatRelativeDate`/`formatNumber`, `getRecordStatusLabel`/`getGeometryTypeLabel`.
   - Export as named export: `export function DatasetStatsLine(...)`.

3. Update `frontend/src/pages/DatasetPage.tsx`:
   - Add import: `import { DatasetStatsLine } from './components/DatasetStatsLine';`
   - Remove the `Sep` component definition (line 59).
   - Replace the `const statsLine = (...)` block (lines 348-445) with: `const statsLine = <DatasetStatsLine dataset={dataset} rasterGsd={rasterGsd} />;`
   - Remove now-unused imports from DatasetPage.tsx: `RecordTypeBadge`, `visibilityColors`, `getRecordStatusLabel`, `getGeometryTypeLabel`, `formatRelativeDate`. Keep `Eye`/`EyeOff`/`ShieldAlert` ONLY if still used elsewhere in the file (check before removing). Keep `formatNumber` ONLY if still used elsewhere. Keep `Badge`, `cn` ONLY if still used elsewhere.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit 2>&1 | tail -5</automated>
  </verify>
  <done>DatasetStatsLine.tsx exists with correct props and JSX. DatasetPage.tsx imports and renders it. Sep removed from DatasetPage. No TypeScript errors.</done>
</task>

<task type="auto">
  <name>Task 2: Extract DatasetHeroMap component</name>
  <files>frontend/src/pages/components/DatasetHeroMap.tsx, frontend/src/pages/DatasetPage.tsx</files>
  <action>
1. Create `frontend/src/pages/components/DatasetHeroMap.tsx`:
   - Define props interface with all needed values:
     ```
     interface DatasetHeroMapProps {
       dataset: DatasetResponse;
       datasetId: string | undefined;
       bbox: [number, number, number, number] | null;
       isEditor: boolean;
       isDrawing: boolean;
       mapContainerRef: React.RefObject<HTMLDivElement | null>;
       onFeatureClick: (gid: number) => void;
       isRasterOrVrt: boolean;
       heroState: 'idle' | 'loading' | 'loaded' | 'error';
       retryCount: number;
       mapKey: number;
       handleRetry: () => void;
       onMapReady?: () => void;
       onTileError?: () => void;
     }
     ```
   - Derive `isRaster`, `isVrt`, `isTable` internally from `dataset.record_type`.
   - Move the hero map container JSX (DatasetPage.tsx lines 574-621, the inner content of the conditional render). The component renders the outer div with `ref`, `data-field-anchor`, `tabIndex`, `className`, and all children (Skeleton, DatasetMap, no-tile badge, error overlay).
   - The `!isDataTabExpanded && !isTable` guard stays in DatasetPage.tsx (it controls whether DatasetHeroMap renders at all).
   - Import: `useTranslation` (namespace `'dataset'`), `AlertTriangle` from lucide, `DatasetMap`, `Button`, `Skeleton`, `cn`, `DatasetResponse` type.
   - Export as named export.

2. Update `frontend/src/pages/DatasetPage.tsx`:
   - Add import: `import { DatasetHeroMap } from './components/DatasetHeroMap';`
   - Replace lines 573-621 with:
     ```tsx
     {!isDataTabExpanded && !isTable && (
       <DatasetHeroMap
         dataset={dataset}
         datasetId={id}
         bbox={bbox}
         isEditor={isEditor}
         isDrawing={isDrawing}
         mapContainerRef={mapContainerRef}
         onFeatureClick={setReadOnlyFeatureGid}
         isRasterOrVrt={isRasterOrVrt}
         heroState={heroState}
         retryCount={retryCount}
         mapKey={mapKey}
         handleRetry={handleRetry}
         onMapReady={onMapReady}
         onTileError={onTileError}
       />
     )}
     ```
   - Remove now-unused imports from DatasetPage.tsx: `AlertTriangle`, `DatasetMap`, `Skeleton`. Keep `cn`, `Button` ONLY if still used elsewhere (check before removing).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit 2>&1 | tail -5 && npx vitest run frontend/src/pages/__tests__/DatasetPage.hero.test.tsx frontend/src/pages/__tests__/DatasetPage.edit-affordances.test.tsx --reporter=verbose 2>&1 | tail -20</automated>
  </verify>
  <done>DatasetHeroMap.tsx exists with correct props. DatasetPage.tsx uses it. Hero and edit-affordances tests pass. No TypeScript errors.</done>
</task>

<task type="auto">
  <name>Task 3: Extract BuilderSidebar component</name>
  <files>frontend/src/pages/components/BuilderSidebar.tsx, frontend/src/pages/MapBuilderPage.tsx</files>
  <action>
1. Create `frontend/src/pages/components/BuilderSidebar.tsx`:
   - Move `SIDEBAR_WIDTH_KEY`, `SIDEBAR_MIN`, `SIDEBAR_MAX` constants.
   - Move `SidebarContent` function component (MapBuilderPage.tsx lines 105-151). Export it as named export (mobile Sheet in MapBuilderPage still needs it).
   - Create `BuilderSidebar` component with props. Use individual props (not the `dialogs` object) for a cleaner API:
     ```
     interface BuilderSidebarProps {
       layers: ReturnType<typeof useBuilderLayers>;
       save: ReturnType<typeof useBuilderSave>;
       localName: string;
       setLocalName: (v: string) => void;
       localDescription: string;
       setLocalDescription: (v: string) => void;
       mapData: MapResponse | undefined;
       mapInstanceRef: React.RefObject<MaplibreMap | null>;
       aiAvailable: boolean;
       mapId: string | undefined;
       inspectorMode: boolean;
       saveShortcut: string;
       sidebarCollapsed: boolean;
       setSidebarCollapsed: (v: boolean) => void;
       showChat: boolean;
       setShowChat: React.Dispatch<React.SetStateAction<boolean>>;
       onShowAddData: () => void;
       onShowShare: () => void;
       onShowInfo: () => void;
     }
     ```
   - Move sidebar resize state into the component: `sidebarWidth` useState with localStorage init, `sidebarWidthRef`, `isDraggingRef`, `handleDragStart` callback. These are fully self-contained.
   - Move the desktop sidebar JSX (MapBuilderPage.tsx lines 344-528): the outer div with `data-testid="builder-sidebar"`, resize handle, collapse button, header (name/description inputs, visibility badge, button tray with AI chat/share/more/save), and `<SidebarContent>`.
   - Import all needed dependencies: `useState`, `useRef`, `useCallback` from React, `useTranslation` (namespace `'builder'`), lucide icons (`Save`, `Loader2`, `Download`, `MessageSquare`, `PanelLeftClose`, `Share2`, `Copy`, `Info`, `MoreHorizontal`, `GripVertical`), `Tooltip`/`TooltipContent`/`TooltipProvider`/`TooltipTrigger`, `DropdownMenu`/`DropdownMenuContent`/`DropdownMenuItem`/`DropdownMenuTrigger`, `Button`, `Badge`, `cn`, `VisibilityIcon`, `getVisibilityLabel`, `LayerPanel`, `BasemapPicker`, `useBuilderLayers` (type-only for ReturnType), `useBuilderSave` (type-only for ReturnType).
   - Export both `BuilderSidebar` and `SidebarContent` as named exports.

2. Update `frontend/src/pages/MapBuilderPage.tsx`:
   - Add import: `import { BuilderSidebar, SidebarContent } from './components/BuilderSidebar';`
   - Remove `SIDEBAR_WIDTH_KEY`, `SIDEBAR_MIN`, `SIDEBAR_MAX` constants.
   - Remove `SidebarContent` function definition.
   - Remove `sidebarWidth`, `sidebarWidthRef`, `isDraggingRef`, `handleDragStart` state/refs/callback from `MapBuilderPage`.
   - Replace the desktop sidebar JSX (lines 344-528) with:
     ```tsx
     {!isMobile && (
       <BuilderSidebar
         layers={layers}
         save={save}
         localName={localName}
         setLocalName={setLocalName}
         localDescription={localDescription}
         setLocalDescription={setLocalDescription}
         mapData={mapData}
         mapInstanceRef={mapInstanceRef}
         aiAvailable={aiAvailable}
         mapId={id}
         inspectorMode={useInspector}
         saveShortcut={saveShortcut}
         sidebarCollapsed={dialogs.sidebarCollapsed}
         setSidebarCollapsed={dialogs.setSidebarCollapsed}
         showChat={dialogs.showChat}
         setShowChat={dialogs.setShowChat}
         onShowAddData={() => dialogs.setShowAddData(true)}
         onShowShare={() => dialogs.setShowShare(true)}
         onShowInfo={() => dialogs.setShowInfo(true)}
       />
     )}
     ```
   - Mobile Sheet still renders `<SidebarContent>` imported from the new file.
   - Remove now-unused imports: `Download`, `MessageSquare`, `PanelLeftClose`, `Share2`, `Copy`, `Info`, `MoreHorizontal`, `GripVertical`, `Tooltip`/`TooltipContent`/`TooltipProvider`/`TooltipTrigger`, `DropdownMenu`/`DropdownMenuContent`/`DropdownMenuItem`/`DropdownMenuTrigger`, `LayerPanel`, `BasemapPicker`, `VisibilityIcon`, `getVisibilityLabel`. Keep `Badge`, `cn`, `Button` ONLY if still used elsewhere (check before removing).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit 2>&1 | tail -5 && npx vitest run frontend/src/pages/__tests__/MapBuilderPage.header-actions.test.tsx --reporter=verbose 2>&1 | tail -20</automated>
  </verify>
  <done>BuilderSidebar.tsx exists with BuilderSidebar and SidebarContent exports. MapBuilderPage.tsx is ~185 lines shorter. Sidebar resize, collapse, header inputs, button tray all work via the extracted component. Header-actions test passes. No TypeScript errors.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

No new trust boundaries introduced. This is a pure refactor — no new data flows, no new inputs, no API changes.

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-fvg-01 | N/A | All | accept | Pure component extraction; no new attack surface. Existing auth, validation, and input handling unchanged. |
</threat_model>

<verification>
```bash
# Full type check
cd /Users/ishiland/Code/geolens && npx tsc --noEmit

# All affected tests
npx vitest run frontend/src/pages/__tests__/DatasetPage.hero.test.tsx frontend/src/pages/__tests__/DatasetPage.edit-affordances.test.tsx frontend/src/pages/__tests__/MapBuilderPage.header-actions.test.tsx --reporter=verbose

# Verify new files exist
ls frontend/src/pages/components/DatasetStatsLine.tsx frontend/src/pages/components/DatasetHeroMap.tsx frontend/src/pages/components/BuilderSidebar.tsx

# Verify line count reduction
wc -l frontend/src/pages/DatasetPage.tsx frontend/src/pages/MapBuilderPage.tsx
```
</verification>

<success_criteria>
- Three new component files exist in `frontend/src/pages/components/`
- DatasetPage.tsx reduced from ~720 to ~550 lines
- MapBuilderPage.tsx reduced from ~697 to ~510 lines
- `npx tsc --noEmit` passes with zero errors
- All three test suites pass without modification
- No visual or behavioral changes to either page
</success_criteria>

<output>
After completion, create `.planning/quick/260413-fvg-extract-datasetstatsline-datasetheromap-/260413-fvg-01-SUMMARY.md`
</output>
