---
phase: 58-re-evaluate-the-placement-of-the-virtual
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/pages/VrtNewPage.tsx
  - frontend/src/App.tsx
  - frontend/src/pages/ImportPage.tsx
  - frontend/src/components/layout/Navbar.tsx
  - frontend/src/pages/DatasetPage.tsx
  - frontend/src/i18n/locales/en/common.json
  - frontend/src/i18n/locales/en/import.json
autonomous: false
requirements: [QT-58]

must_haves:
  truths:
    - "VRT creation is no longer on the Import page"
    - "Create dropdown in navbar has a Virtual Raster option distinct from Dataset"
    - "Clicking Virtual Raster in Create dropdown navigates to /vrt/new"
    - "/vrt/new renders the existing VrtCreatorForm at full page width"
    - "Raster dataset detail pages show a Create VRT button"
    - "Create VRT button on detail page navigates to /vrt/new?source={datasetId}"
    - "VrtCreatorForm pre-selects the source when ?source param is present"
    - "Mobile nav Create section includes Virtual Raster option"
  artifacts:
    - path: "frontend/src/pages/VrtNewPage.tsx"
      provides: "Dedicated VRT creation page with query param support"
    - path: "frontend/src/App.tsx"
      provides: "Route /vrt/new under EditorRoute"
    - path: "frontend/src/components/layout/Navbar.tsx"
      provides: "Virtual Raster item in CreateMenu and MobileNav"
    - path: "frontend/src/pages/DatasetPage.tsx"
      provides: "Create VRT button on raster dataset detail pages"
  key_links:
    - from: "frontend/src/components/layout/Navbar.tsx"
      to: "/vrt/new"
      via: "Link navigation from Create dropdown"
      pattern: "to=.*vrt/new"
    - from: "frontend/src/pages/DatasetPage.tsx"
      to: "/vrt/new?source="
      via: "Link with dataset ID query param"
      pattern: "vrt/new\\?source="
    - from: "frontend/src/pages/VrtNewPage.tsx"
      to: "VrtCreatorForm"
      via: "import and render with initialSourceId prop"
      pattern: "VrtCreatorForm"
---

<objective>
Move the Virtual Raster creation flow from the Import page tab to a dedicated route (`/vrt/new`) accessible from the navbar Create dropdown and raster dataset detail pages.

Purpose: VRT creation is a "compose" action combining existing rasters, not an "import" action. Moving it to its own route with contextual entry points improves discoverability and semantic correctness.
Output: New VRT page, updated navbar, updated import page (tab removed), contextual button on raster detail.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/58-re-evaluate-the-placement-of-the-virtual/58-CONTEXT.md

<interfaces>
<!-- From frontend/src/components/import/VrtCreatorForm.tsx -->
```typescript
export function VrtCreatorForm()  // Currently takes no props
// Uses useCreateVrt hook, internal state for sources, title, summary, vrtType, resolutionStrategy
// Search uses searchDatasets({ record_type: 'raster_dataset', ... })
```

<!-- From frontend/src/App.tsx route structure -->
```typescript
// EditorRoute wraps /import, /maps, /maps/:id
<Route element={<EditorRoute />}>
  <Route path="import" element={<ImportPage />} />
  <Route path="maps" element={<MapsPage />} />
  <Route path="maps/:id" element={<MapBuilderPage />} />
</Route>
```

<!-- From frontend/src/components/layout/Navbar.tsx CreateMenu -->
```typescript
function CreateMenu() {
  // DropdownMenu with items: Dataset (dialog), Collection (dialog), Map (dialog)
  // Each opens a dialog via useState
}
function MobileNav() {
  // Sheet with nav links + Create section (Dataset, Collection, Map buttons)
}
```

<!-- From frontend/src/pages/DatasetPage.tsx -->
```typescript
const isRaster = dataset.record_type === 'raster_dataset';
const isVrt = dataset.record_type === 'vrt_dataset';
// leadingContent div contains badges, PublishButton, AddToMapButton, Download COG, ConnectDropdown
```

<!-- From frontend/src/api/search.ts -->
```typescript
export function searchDatasets(params: Record<string, string>): Promise<OGCFeatureCollectionResponse>
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create /vrt/new page, update VrtCreatorForm for pre-selection, remove VRT tab from Import</name>
  <files>
    frontend/src/pages/VrtNewPage.tsx,
    frontend/src/components/import/VrtCreatorForm.tsx,
    frontend/src/pages/ImportPage.tsx,
    frontend/src/App.tsx
  </files>
  <action>
1. **Add optional `initialSourceId` prop to VrtCreatorForm:**
   - Add prop `initialSourceId?: string` to VrtCreatorForm.
   - In a useEffect, when `initialSourceId` is truthy and `selectedSources` is empty, fetch the dataset by calling `searchDatasets({ q: '', record_type: 'raster_dataset', ids: initialSourceId, limit: '1' })` — OR simpler: use TanStack Query's `useQuery` to fetch `/api/ogc/collections/${initialSourceId}` (the OGC record endpoint) directly. Check how `useDataset` works in `use-dataset.ts` for the correct API call pattern. Once fetched, call `setSelectedSources([record])` to pre-populate.
   - If the search API does not support `ids` filter, use the existing `searchDatasets` with the dataset title or just fetch the single record from the catalog API. The simplest approach: use the existing `useDataset(initialSourceId)` hook pattern to fetch the OGCRecordResponse, then auto-add it as a source on mount. Check the response shape matches OGCRecordResponse used in selectedSources.

2. **Create `frontend/src/pages/VrtNewPage.tsx`:**
   ```typescript
   import { useSearchParams } from 'react-router';
   import { useTranslation } from 'react-i18next';
   import { PageShell } from '@/components/layout/PageShell';
   import { PageHeader } from '@/components/layout/PageHeader';
   import { VrtCreatorForm } from '@/components/import/VrtCreatorForm';

   export function VrtNewPage() {
     const { t } = useTranslation('import');
     const [searchParams] = useSearchParams();
     const sourceId = searchParams.get('source') ?? undefined;

     return (
       <PageShell>
         <PageHeader title={t('vrt.pageTitle')} />
         <VrtCreatorForm initialSourceId={sourceId} />
       </PageShell>
     );
   }
   ```

3. **Add route in App.tsx:**
   - Add lazy import: `const VrtNewPage = lazy(() => import('./pages/VrtNewPage').then(m => ({ default: m.VrtNewPage })));`
   - Add `<Route path="vrt/new" element={<VrtNewPage />} />` inside the `<Route element={<EditorRoute />}>` block, alongside import and maps.

4. **Remove VRT tab from ImportPage.tsx:**
   - Remove the `VrtCreatorForm` import.
   - Remove `'vrt'` from the `Tab` type union.
   - Remove the `<TabsTrigger value="vrt">` and `<TabsContent value="vrt">` elements.

5. **Add i18n key** in `frontend/src/i18n/locales/en/import.json`:
   - Add `"pageTitle": "Create Virtual Raster"` inside the `"vrt"` object.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>
    - /vrt/new route exists and renders VrtCreatorForm in a full-page layout
    - VrtCreatorForm accepts optional initialSourceId prop and pre-selects source
    - ImportPage no longer has VRT tab (only upload, register, service)
    - TypeScript compiles without errors
  </done>
</task>

<task type="auto">
  <name>Task 2: Add Virtual Raster to Create dropdown and raster detail page button</name>
  <files>
    frontend/src/components/layout/Navbar.tsx,
    frontend/src/pages/DatasetPage.tsx,
    frontend/src/i18n/locales/en/common.json
  </files>
  <action>
1. **Update Navbar.tsx CreateMenu:**
   - Import `Link` from `react-router` and `Layers` from `lucide-react` (Layers icon visually represents composing/stacking rasters).
   - After the existing Map `<DropdownMenuItem>`, add a `<DropdownMenuSeparator />` then:
     ```tsx
     <DropdownMenuItem asChild>
       <Link to="/vrt/new">
         <Layers className="h-4 w-4" />
         {t('nav.virtualRaster')}
       </Link>
     </DropdownMenuItem>
     ```
   - The separator visually distinguishes VRT (compose action) from Dataset/Collection/Map (create-new actions).

2. **Update MobileNav Create section:**
   - After the Map button in the Create section, add a `<Separator className="my-1" />` and:
     ```tsx
     <NavLink to="/vrt/new" className={mobileNavLinkClass} onClick={() => setOpen(false)}>
       <Layers className="h-4 w-4 mr-2" />
       {t('nav.virtualRaster')}
     </NavLink>
     ```

3. **Add i18n key** in `frontend/src/i18n/locales/en/common.json`:
   - Add `"virtualRaster": "Virtual Raster"` inside the `"nav"` object.

4. **Update DatasetPage.tsx** to add a "Create VRT" button on raster detail pages:
   - Import `Layers` from `lucide-react` and `Link` from `react-router` (Link already imported).
   - In the `leadingContent` div, after the ConnectDropdown, add:
     ```tsx
     {isRaster && isEditor && (
       <Button asChild variant="outline" size="sm">
         <Link to={`/vrt/new?source=${dataset.id}`}>
           <Layers className="mr-1 size-3.5" />
           {t('actions.createVrt', { defaultValue: 'Create VRT' })}
         </Link>
       </Button>
     )}
     ```
   - Only show for `isRaster` (not VRT) and `isEditor` (need edit permissions to create VRT).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>
    - Create dropdown shows Virtual Raster item with Layers icon, separated from other items
    - Mobile nav Create section includes Virtual Raster link
    - Raster dataset detail pages show "Create VRT" button linking to /vrt/new?source={id}
    - VRT dataset detail pages do NOT show the Create VRT button
    - TypeScript compiles without errors
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 3: Verify VRT creation placement and entry points</name>
  <action>
    Human verifies the VRT creation flow has been properly relocated from Import to its own route with correct entry points.
  </action>
  <done>User confirms all entry points work correctly and pre-selection functions as expected.</done>
  <what-built>
    Moved VRT creation from Import page tab to dedicated /vrt/new route. Added Virtual Raster option to navbar Create dropdown (desktop and mobile). Added contextual "Create VRT" button on raster dataset detail pages that pre-selects the dataset as a source.
  </what-built>
  <how-to-verify>
    1. Visit http://localhost:8080/import -- verify only 3 tabs: Upload File, Register Table, Service URL (no Virtual Raster tab)
    2. Click the "Create" dropdown in the navbar -- verify "Virtual Raster" appears with a Layers icon, visually separated from Dataset/Collection/Map
    3. Click "Virtual Raster" in the dropdown -- verify it navigates to /vrt/new with the full VRT creator form
    4. Navigate to a raster dataset detail page -- verify a "Create VRT" button appears in the header actions
    5. Click "Create VRT" on a raster detail page -- verify it navigates to /vrt/new?source={datasetId} and the dataset is pre-selected as a source
    6. On mobile viewport, open the hamburger menu -- verify Virtual Raster appears in the Create section
  </how-to-verify>
  <resume-signal>Type "approved" or describe issues</resume-signal>
</task>

</tasks>

<verification>
- `cd frontend && npx tsc --noEmit` passes
- /import page has exactly 3 tabs (no VRT)
- /vrt/new renders VrtCreatorForm
- /vrt/new?source={validRasterId} pre-selects the source
- Create dropdown has 4 items: Dataset, Collection, Map, Virtual Raster
- Raster detail page has Create VRT button; VRT detail page does not
</verification>

<success_criteria>
- VRT creation semantically moved from "import" to "compose" concept
- Two entry points: navbar Create dropdown and raster detail page
- Pre-selection via query param works for contextual navigation
- Import page simplified to actual import actions only
</success_criteria>

<output>
After completion, create `.planning/quick/58-re-evaluate-the-placement-of-the-virtual/58-SUMMARY.md`
</output>
