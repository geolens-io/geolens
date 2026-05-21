---
phase: 260318-twq
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/dataset/tabs/OverviewTab.tsx
  - frontend/src/components/dataset/tabs/SourceQualityTab.tsx
  - frontend/src/components/dataset/tabs/StructureTab.tsx
  - frontend/src/components/dataset/RelatedDatasets.tsx
  - frontend/src/components/dataset/AiAssistButton.tsx
  - frontend/src/components/dataset/panels/VectorDetailPanel.tsx
  - frontend/src/pages/DatasetPage.tsx
  - frontend/src/api/datasets.ts
  - backend/app/datasets/schemas.py
  - backend/app/datasets/service.py
autonomous: true
requirements: [TWQ-01, TWQ-02, TWQ-03, TWQ-04, TWQ-05, TWQ-06, TWQ-07]
must_haves:
  truths:
    - "Empty editable fields show 'No X added yet.' text + [Add X] button instead of inline placeholder"
    - "AI Assist buttons show contextual labels per field (Generate summary, Draft lineage, etc.)"
    - "Related dataset cards show RecordTypeBadge, a stat, subtler similarity, and deduped by ID"
    - "Table Name no longer appears in OverviewTab Identity; it appears in StructureTab"
    - "VRT OverviewTab shows merged Identity & Derivation section without duplicate fields"
    - "Raster datasets show a quick-facts strip below the map with bands, resolution, dimensions, format"
  artifacts:
    - path: "frontend/src/components/dataset/tabs/OverviewTab.tsx"
      provides: "Read-first empty states, VRT merged section, raster quick-facts"
    - path: "frontend/src/components/dataset/RelatedDatasets.tsx"
      provides: "Richer related cards with RecordTypeBadge and stats"
    - path: "frontend/src/components/dataset/tabs/StructureTab.tsx"
      provides: "Table name field for vector datasets"
  key_links:
    - from: "RelatedDatasets.tsx"
      to: "/datasets/{id}/related/"
      via: "useRelatedDatasets hook"
      pattern: "record_type.*feature_count.*band_count"
---

<objective>
Detail page round 3: Consistent read-first empty states across all editable fields, contextual AI Assist labels, richer related dataset cards, table name relocation to Structure tab, VRT identity/derivation merge, and raster quick-facts strip.

Purpose: Polish the detail page to feel professional and read-first -- empty fields communicate state clearly rather than showing raw edit placeholders, AI actions are contextual, and related cards carry more information at a glance.
Output: Updated OverviewTab, SourceQualityTab, StructureTab, RelatedDatasets, AiAssistButton, and supporting backend changes.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/components/dataset/tabs/OverviewTab.tsx
@frontend/src/components/dataset/tabs/SourceQualityTab.tsx
@frontend/src/components/dataset/tabs/StructureTab.tsx
@frontend/src/components/dataset/RelatedDatasets.tsx
@frontend/src/components/dataset/AiAssistButton.tsx
@frontend/src/components/dataset/panels/VectorDetailPanel.tsx
@frontend/src/pages/DatasetPage.tsx
@frontend/src/api/datasets.ts
@backend/app/datasets/schemas.py
@backend/app/datasets/service.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Read-first empty states, contextual AI labels, table name move, VRT merge, raster quick-facts</name>
  <files>
    frontend/src/components/dataset/tabs/OverviewTab.tsx
    frontend/src/components/dataset/tabs/SourceQualityTab.tsx
    frontend/src/components/dataset/tabs/StructureTab.tsx
    frontend/src/components/dataset/panels/VectorDetailPanel.tsx
    frontend/src/components/dataset/AiAssistButton.tsx
    frontend/src/pages/DatasetPage.tsx
  </files>
  <action>
**1. Read-first empty states (OverviewTab):**
- Replace the summary empty state: instead of a ghost button "Add summary..." that expands inline edit, show `<p class="text-sm text-muted-foreground italic">No summary added yet.</p>` followed by a small `<Button variant="outline" size="sm">` labeled "Add summary" that triggers `setSummaryExpanded(true)`. Keep the existing `summaryExpanded` state and `EditableFieldShell`/`InlineEdit` reveal pattern.
- Apply the same "No X added yet." + [Add X] button pattern consistently.

**2. Read-first empty states (SourceQualityTab):**
- Update the `renderReadFirstField` helper: change from the ghost button "Add {field}..." to a two-line pattern:
  - Line 1: `<p className="text-sm text-muted-foreground italic">No {label.toLowerCase()} added yet.</p>`
  - Line 2: `<Button variant="outline" size="sm" onClick={() => toggleExpanded(fieldName)}>Add {label.toLowerCase()}</Button>`
- This applies to lineage_summary, source_url, source_organization, quality_statement, usage_constraints, access_constraints -- all fields already using `renderReadFirstField`.

**3. Contextual AI Assist labels:**
- AiAssistButton already accepts `label` prop -- good. Pass contextual labels from call sites:
  - OverviewTab summary: `label="Generate summary"`
  - SourceQualityTab lineage: `label="Draft lineage"`
  - SourceQualityTab quality_statement: `label="Draft quality statement"`
- No component change needed since `label` prop already exists.

**4. Table Name move:**
- In OverviewTab: Remove the `tableName` MetadataField block (lines ~199-208) from the Identity section for vector datasets. It's the block guarded by `!isRaster && !isVrt` that renders `dataset.table_name`.
- In StructureTab: Add a `tableName` prop (`tableName?: string`). When provided, render a small info row above the AttributeMetadata card:
  ```
  <div className="flex items-center gap-2 text-sm">
    <span className="text-muted-foreground">Table:</span>
    <code className="font-mono text-xs bg-muted px-2 py-1 rounded">{tableName}</code>
    <CopyButton value={tableName} />
  </div>
  ```
- In VectorDetailPanel: Pass `tableName={dataset.table_name}` to StructureTab.

**5. VRT Identity + Derivation merge:**
- In OverviewTab, when `isVrt`:
  - Change the Identity card title to "Identity & Derivation" (use `t('sections.identityAndDerivation', { defaultValue: 'Identity & Derivation' })`)
  - Move the derivation summary fields (VRT Type, Status, Last Regenerated) INTO the Identity card's `<dl>` grid, after the existing VRT fields (source count, resolution strategy).
  - Remove the standalone "Derivation Summary" Card (lines ~326-398) since its fields are now in the merged Identity card.
  - Ensure no duplicate fields: source_count and resolution_strategy already appear in the Identity section for VRT, so the Derivation Summary section just adds vrt_type, status, and last_regenerated.

**6. Raster quick-facts strip:**
- In DatasetPage.tsx, after the hero map div and before the type-specific panels, add a raster quick-facts strip visible only when `dataset.record_type === 'raster_dataset'`:
  ```tsx
  {dataset.record_type === 'raster_dataset' && dataset.raster && (
    <div className="flex items-center gap-3 px-3 py-2 rounded-lg border bg-muted/30 text-sm overflow-x-auto">
      {dataset.raster.band_count != null && (
        <div><span className="text-muted-foreground">Bands</span> <span className="font-medium">{dataset.raster.band_count}</span></div>
      )}
      {(dataset.raster.res_x != null || dataset.raster.gsd != null) && (
        <div><span className="text-muted-foreground">Resolution</span> <span className="font-medium">{dataset.raster.gsd ? `${dataset.raster.gsd} m` : `${dataset.raster.res_x?.toFixed(6)}`}</span></div>
      )}
      {dataset.raster.width != null && dataset.raster.height != null && (
        <div><span className="text-muted-foreground">Dimensions</span> <span className="font-medium">{dataset.raster.width} x {dataset.raster.height} px</span></div>
      )}
      {dataset.raster.compression && (
        <div><span className="text-muted-foreground">Format</span> <span className="font-medium">{dataset.raster.compression}</span></div>
      )}
    </div>
  )}
  ```
  Use `Sep` dots between items or just spacing via gap. Place between the map container and the `RasterDetailPanel`.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>
- Summary empty state shows "No summary added yet." + [Add summary] button
- All SourceQualityTab empty fields show "No X added yet." + [Add X] instead of "Add X..." ghost button
- AI Assist buttons show "Generate summary", "Draft lineage", "Draft quality statement"
- Table Name removed from OverviewTab Identity, appears in StructureTab
- VRT shows merged "Identity & Derivation" card with no duplicate source_count/resolution_strategy
- Raster shows quick-facts strip below map
  </done>
</task>

<task type="auto">
  <name>Task 2: Richer related dataset cards with backend support</name>
  <files>
    backend/app/datasets/schemas.py
    backend/app/datasets/service.py
    frontend/src/api/datasets.ts
    frontend/src/components/dataset/RelatedDatasets.tsx
  </files>
  <action>
**1. Backend -- add record_type and feature_count to RelatedDatasetItem:**
- In `backend/app/datasets/schemas.py`, add to `RelatedDatasetItem`:
  - `record_type: str | None = None`
  - `feature_count: int | None = None`
  - `band_count: int | None = None`
- In `backend/app/datasets/service.py` `get_related_datasets()`, update the item dict construction (~line 834-841) to include:
  - `"record_type": ds.record.record_type if ds.record else None`
  - `"feature_count": ds.feature_count`
  - `"band_count": ds.raster.band_count if hasattr(ds, 'raster') and ds.raster else None`

  Note: The `ds` is a Dataset model with `joinedload(Dataset.record)`. Check if the Dataset model has `raster` relationship available. If not, add `.options(joinedload(Dataset.raster_metadata))` or similar, OR just skip band_count and only include feature_count (which is directly on Dataset).

  Simpler approach if raster relationship is complex: just add `record_type` and `feature_count` (both directly accessible), skip `band_count` for now.

**2. Frontend API types:**
- In `frontend/src/api/datasets.ts`, update `RelatedDatasetItem`:
  - Add `record_type: string | null`
  - Add `feature_count: number | null`
  - Add `band_count: number | null`

**3. Frontend RelatedDatasets component:**
- Import `RecordTypeBadge` from `@/components/search/RecordTypeBadge`
- Deduplicate items by dataset ID: `const uniqueItems = data.items.filter((item, i, arr) => arr.findIndex(x => x.id === item.id) === i);`
- Update the section header to say "Similar datasets" instead of using `t('relatedDatasets.title')` -- or change the i18n key. Use `t('relatedDatasets.similarDatasets', { defaultValue: 'Similar datasets' })`.
- Update each card:
  - Add `<RecordTypeBadge recordType={item.record_type ?? 'vector_dataset'} />` below the name
  - Add one stat line: if `item.feature_count`, show `{formatNumber(item.feature_count)} features`; else if `item.band_count`, show `{item.band_count} bands`
  - Make similarity score subtler: change from `{Math.round(item.similarity * 100)}%` with direct text to a small muted badge or just smaller text: `<span className="text-[10px] text-muted-foreground/60">{Math.round(item.similarity * 100)}% match</span>`
- Import `formatNumber` from `@/lib/format`
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>
- Related datasets endpoint returns record_type, feature_count, band_count
- Cards show RecordTypeBadge, one stat (feature count or band count), subtler similarity score
- Items deduped by ID
- Header says "Similar datasets"
  </done>
</task>

</tasks>

<verification>
- `npx tsc --noEmit` passes with no errors
- Visit a vector dataset detail page: summary shows "No summary added yet." + button when empty; Table Name gone from Identity, visible in Structure tab
- Visit a raster dataset: quick-facts strip shows below map with bands, resolution, dimensions, format
- Visit a VRT dataset: Identity & Derivation merged, no duplicate source count or resolution strategy
- Related datasets cards show type badge, stats, subtler similarity
- AI Assist buttons show contextual labels
</verification>

<success_criteria>
- All empty editable fields across OverviewTab and SourceQualityTab use "No X added yet." + [Add X] pattern
- AI Assist labels are field-specific (Generate summary, Draft lineage, Draft quality statement)
- Related cards have RecordTypeBadge, stats, deduplication, "Similar datasets" header
- Table Name moved from Overview Identity to Structure tab
- VRT shows single merged "Identity & Derivation" card
- Raster shows quick-facts strip below map
- TypeScript compiles clean
</success_criteria>

<output>
After completion, create `.planning/quick/260318-twq-detail-page-round-3-read-first-empty-sta/260318-twq-SUMMARY.md`
</output>
