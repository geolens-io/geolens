---
phase: quick
plan: 260331-azj
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/import/VrtCreateDialog.tsx
  - frontend/src/components/import/VrtCreatorForm.tsx
  - frontend/src/components/import/BulkTrackingList.tsx
autonomous: true
requirements: []

must_haves:
  truths:
    - "When 2+ raster files complete import, a Create VRT Mosaic button appears on the tracking page"
    - "Clicking the button opens VrtCreateDialog with completed raster datasets pre-selected"
    - "Single raster import or non-raster imports do not show the VRT button"
    - "VrtCreatorForm loads all pre-selected sources in parallel on mount"
  artifacts:
    - path: "frontend/src/components/import/BulkTrackingList.tsx"
      provides: "VRT button logic for completed raster jobs"
      contains: "Create VRT"
    - path: "frontend/src/components/import/VrtCreateDialog.tsx"
      provides: "Multi-source dialog prop"
      contains: "initialSourceIds"
    - path: "frontend/src/components/import/VrtCreatorForm.tsx"
      provides: "Multi-source pre-population via useQueries"
      contains: "initialSourceIds"
  key_links:
    - from: "BulkTrackingList.tsx"
      to: "VrtCreateDialog.tsx"
      via: "initialSourceIds prop with completed dataset IDs"
      pattern: "initialSourceIds.*completedRasterIds"
    - from: "VrtCreateDialog.tsx"
      to: "VrtCreatorForm.tsx"
      via: "initialSourceIds prop passthrough"
      pattern: "initialSourceIds"
    - from: "VrtCreatorForm.tsx"
      to: "/collections/datasets/items/"
      via: "useQueries fetching each source by ID"
      pattern: "useQueries"
---

<objective>
Add a "Create VRT Mosaic" button to BulkTrackingList that appears when 2+ raster file imports complete successfully. Clicking it opens VrtCreateDialog with those datasets pre-selected.

Purpose: Users importing multiple COGs should be able to immediately create a VRT mosaic without manually searching for each dataset.
Output: Modified BulkTrackingList with VRT button, VrtCreateDialog and VrtCreatorForm supporting multi-source pre-selection.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/components/import/BulkTrackingList.tsx
@frontend/src/components/import/VrtCreateDialog.tsx
@frontend/src/components/import/VrtCreatorForm.tsx
@frontend/src/components/import/JobProgress.tsx
@frontend/src/hooks/use-ingest.ts
@frontend/src/lib/query-keys.ts

<interfaces>
From frontend/src/types/api.ts:
```typescript
export interface FileEntry {
  id: string;
  file: File | null;
  fileName: string;
  status: FileEntryStatus;
  jobId: string | null;
  previewData: FilePreviewResponse | RasterPreviewResponse | null;
  error: string | null;
}

export interface JobStatusResponse {
  id: string;
  status: string;
  dataset_id: string | null;
  source_filename: string | null;
  error_message: string | null;
  warning_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}
```

From frontend/src/hooks/use-ingest.ts:
```typescript
export function useJobStatus(jobId: string | null): UseQueryResult<JobStatusResponse>;
```

From frontend/src/lib/query-keys.ts:
```typescript
ogcRecords: {
  detail: (id: string) => ['ogc-record', id] as const,
}
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add initialSourceIds to VrtCreateDialog and VrtCreatorForm</name>
  <files>frontend/src/components/import/VrtCreateDialog.tsx, frontend/src/components/import/VrtCreatorForm.tsx</files>
  <action>
**VrtCreateDialog.tsx:**
- Add `initialSourceIds?: string[]` to `VrtCreateDialogProps` (keep existing `initialSourceId` for backward compat).
- Pass `initialSourceIds` through to `VrtCreatorForm`.

**VrtCreatorForm.tsx:**
- Add `initialSourceIds?: string[]` to `VrtCreatorFormProps`.
- Import `useQueries` from `@tanstack/react-query`.
- Add a `useQueries` call that fetches `/collections/datasets/items/{id}` for each ID in `initialSourceIds`, enabled only when `initialSourceIds` has items and `initialSourceId` is NOT set (avoid conflict with single-source flow). Use `queryKeys.ogcRecords.detail(id)` for each query key.
- Add a `useEffect` that watches the `useQueries` results: when all queries have loaded successfully and `selectedSources` is still empty, call `setSelectedSources` with the fetched `OGCRecordResponse[]` objects (filter to only `record_type === 'raster_dataset'`). Use a ref to ensure this runs only once (same pattern as existing `initialSource` effect).
- The existing single `initialSourceId` flow remains untouched.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -30</automated>
  </verify>
  <done>VrtCreateDialog accepts initialSourceIds and passes to VrtCreatorForm. VrtCreatorForm fetches all sources in parallel via useQueries and pre-populates selectedSources on mount. TypeScript compiles clean.</done>
</task>

<task type="auto">
  <name>Task 2: Add VRT button to BulkTrackingList for completed raster imports</name>
  <files>frontend/src/components/import/BulkTrackingList.tsx</files>
  <action>
- Import `useState` from react, `useJobStatus` from `@/hooks/use-ingest`, `VrtCreateDialog` from `./VrtCreateDialog`, and `Layers` icon from `lucide-react`.
- Identify raster entries: filter `trackable` entries where `/\.tiff?$/i.test(entry.fileName)` and `entry.jobId` is set. Store as `rasterEntries`.
- Create a small inner component `useCompletedRasterDatasetIds(rasterEntries)` (or inline the logic):
  - For each raster entry, call `useJobStatus(entry.jobId)`. Since hooks must be called unconditionally and the number of entries is dynamic, use a different approach: create a child component `VrtButtonSection` that receives `rasterEntries` and renders the button. This component calls `useJobStatus` for each entry. BUT hooks-in-loops is not allowed.
  - **Better approach**: Instead of calling useJobStatus per-entry (hooks rules issue), leverage the fact that BulkTrackingList already renders `JobProgress` for each entry which polls job status. The job status data is already in TanStack Query cache under `queryKeys.ingest.jobStatus(jobId)`. Use `useQueries` from `@tanstack/react-query` to read the cached job status for each raster entry:
    ```typescript
    const rasterJobQueries = useQueries({
      queries: rasterEntries.map((entry) => ({
        queryKey: queryKeys.ingest.jobStatus(entry.jobId),
        queryFn: () => getJobStatus(entry.jobId!),
        enabled: !!entry.jobId,
        // Don't poll here — JobProgress already polls. Just read cache.
        staleTime: Infinity,
        refetchInterval: false as const,
      })),
    });
    ```
  - Import `getJobStatus` from `@/api/ingest` and `queryKeys` from `@/lib/query-keys`. Check existing imports in `use-ingest.ts` to find the correct import path for `getJobStatus`.
  - Derive `completedRasterIds`: filter `rasterJobQueries` results where `data?.status === 'complete'` and `data?.dataset_id` is truthy, map to `dataset_id`.
  - Add `const [vrtDialogOpen, setVrtDialogOpen] = useState(false)` state.
  - After the list of JobProgress cards and before the "Upload More" button, conditionally render when `completedRasterIds.length >= 2`:
    ```tsx
    <div className="flex items-center gap-2 rounded-md border border-dashed p-3">
      <Layers className="size-4 text-muted-foreground" />
      <span className="text-sm text-muted-foreground flex-1">
        {completedRasterIds.length} raster datasets ready
      </span>
      <Button variant="secondary" size="sm" onClick={() => setVrtDialogOpen(true)}>
        Create VRT Mosaic
      </Button>
    </div>
    ```
  - Render `<VrtCreateDialog open={vrtDialogOpen} onOpenChange={setVrtDialogOpen} initialSourceIds={completedRasterIds} />` at the end of the component.
  - Note: check `queryKeys.ingest.jobStatus` exists. If the query key helper is named differently, use the exact name from `query-keys.ts`.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -30</automated>
  </verify>
  <done>BulkTrackingList shows "Create VRT Mosaic" button when 2+ raster imports complete. Button opens VrtCreateDialog with completed dataset IDs. Non-raster imports and single raster imports do not show the button.</done>
</task>

</tasks>

<verification>
1. TypeScript compiles without errors
2. Manual test: upload 2+ .tif files, wait for completion, verify VRT button appears
3. Click VRT button, verify dialog opens with datasets pre-selected in the source list
4. Upload 1 .tif + 1 .shp, verify no VRT button appears
</verification>

<success_criteria>
- "Create VRT Mosaic" button renders in BulkTrackingList when 2+ raster jobs complete
- VrtCreateDialog opens with initialSourceIds and VrtCreatorForm shows pre-selected sources
- Existing single-source VRT flow (initialSourceId) still works unchanged
- TypeScript compiles clean
</success_criteria>

<output>
After completion, create `.planning/quick/260331-azj-add-create-vrt-button-for-multiple-impor/260331-azj-SUMMARY.md`
</output>
