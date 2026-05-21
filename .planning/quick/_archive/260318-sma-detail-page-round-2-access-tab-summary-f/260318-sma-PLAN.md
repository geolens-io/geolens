---
phase: 260318-sma
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/dataset/tabs/AccessTab.tsx
  - frontend/src/components/dataset/tabs/OverviewTab.tsx
  - frontend/src/components/dataset/tabs/AccessSharingTab.tsx
  - frontend/src/components/dataset/panels/VectorDetailPanel.tsx
  - frontend/src/components/dataset/panels/RasterDetailPanel.tsx
  - frontend/src/components/dataset/panels/VrtDetailPanel.tsx
  - frontend/src/components/dataset/panels/CollectionDetailPanel.tsx
  - frontend/src/pages/DatasetPage.tsx
  - frontend/src/components/dataset/DatasetMap.tsx
autonomous: true
requirements: [ACCESS-TAB, OVERVIEW-CLEANUP, MAP-FIT, HEALTH-GUIDANCE, STICKY-TABS]

must_haves:
  truths:
    - "Access Points, Export, and Visibility appear in a dedicated Access tab, not in Overview"
    - "Overview tab shows summary-first content: health, identity, summary, raster props, VRT derivation, collections, related, maps"
    - "Map auto-fits tighter to dataset extent on load with increased padding"
    - "Health block shows next priority field name when issues exist"
    - "Tabs stick to top of viewport when scrolled past"
  artifacts:
    - path: "frontend/src/components/dataset/tabs/AccessTab.tsx"
      provides: "Dedicated Access tab component"
      min_lines: 20
    - path: "frontend/src/components/dataset/tabs/OverviewTab.tsx"
      provides: "Cleaned overview without access/export/visibility sections"
    - path: "frontend/src/components/dataset/panels/VectorDetailPanel.tsx"
      provides: "Vector panel with Access tab and sticky TabsList"
    - path: "frontend/src/components/dataset/panels/RasterDetailPanel.tsx"
      provides: "Raster panel with Access tab and sticky TabsList"
    - path: "frontend/src/components/dataset/panels/VrtDetailPanel.tsx"
      provides: "VRT panel with Access tab and sticky TabsList"
  key_links:
    - from: "frontend/src/components/dataset/tabs/AccessTab.tsx"
      to: "frontend/src/components/dataset/tabs/AccessSharingTab.tsx"
      via: "Reuses existing AccessSharingTab content inline"
      pattern: "DistributionsList|ExportButton|TileUrlSection"
    - from: "frontend/src/components/dataset/panels/*DetailPanel.tsx"
      to: "frontend/src/components/dataset/tabs/AccessTab.tsx"
      via: "Tab import and TabsContent rendering"
      pattern: "import.*AccessTab"
    - from: "frontend/src/components/dataset/tabs/OverviewTab.tsx"
      to: "validation errors[0].field"
      via: "Next priority field display in health block"
      pattern: "validationData.*errors.*\\[0\\]"
---

<objective>
Detail page round 2: Create dedicated Access tab, clean Overview to summary-first, improve map fit, add health guidance, sticky tabs.

Purpose: Improve information architecture by separating access/export concerns from overview summary, and polish scroll/map UX.
Output: Restructured detail page tabs with Access tab, tighter overview, sticky tabs, better map fit, health guidance.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260318-sma-detail-page-round-2-access-tab-summary-f/260318-sma-CONTEXT.md

@frontend/src/pages/DatasetPage.tsx
@frontend/src/components/dataset/tabs/OverviewTab.tsx
@frontend/src/components/dataset/tabs/AccessSharingTab.tsx
@frontend/src/components/dataset/panels/VectorDetailPanel.tsx
@frontend/src/components/dataset/panels/RasterDetailPanel.tsx
@frontend/src/components/dataset/panels/VrtDetailPanel.tsx
@frontend/src/components/dataset/panels/CollectionDetailPanel.tsx
@frontend/src/components/dataset/DatasetMap.tsx

<interfaces>
From frontend/src/components/dataset/panels/VectorDetailPanel.tsx:
```typescript
export interface DetailPanelProps {
  dataset: DatasetResponse;
  canEdit: boolean;
  capabilities: DatasetEditCapabilities;
  datasetId: string;
  activeTab: string;
  onTabChange: (tab: string) => void;
  resolveDraftValue: (field: PendingDraftField) => string;
  stagePendingDraft: (field: PendingDraftField, value: string) => void;
  handleDraftDirtyChange: (field: PendingDraftField, isDirty: boolean) => void;
  onNavigateToValidationField: (field: string) => void;
}
```

From frontend/src/components/dataset/tabs/AccessSharingTab.tsx:
```typescript
interface AccessSharingTabProps {
  dataset: DatasetResponse;
  datasetId: string;
}
// Contains: DistributionsList, TileUrlSection, ExportButton, Visibility badge
// Currently rendered inside OverviewTab at line 499
```

From frontend/src/types/api.ts:
```typescript
export interface ValidationIssue {
  field: string;
  message: string;
  severity: 'error' | 'warning';
}
```

DatasetMap initial view state (line 928):
```typescript
initialViewState = { bounds, fitBoundsOptions: { padding: 40 } };
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create AccessTab and clean OverviewTab</name>
  <files>
    frontend/src/components/dataset/tabs/AccessTab.tsx
    frontend/src/components/dataset/tabs/OverviewTab.tsx
  </files>
  <action>
1. **Create `AccessTab.tsx`** — a new dedicated tab component that consolidates access-related content currently living in `AccessSharingTab.tsx` (which is rendered inside OverviewTab at line 499). The new AccessTab renders the same content as AccessSharingTab: Distributions card (with `DistributionsList` + `TileUrlSection` for raster/VRT), Export card (vector only, using `ExportButton`), Visibility card, and the auth note about X-Api-Key. Props: `{ dataset: DatasetResponse; datasetId: string }`. This is a shared component used across all record types.

2. **Clean `OverviewTab.tsx`** — Remove the `<AccessSharingTab>` render at line 499 and its import. The Overview tab should now contain only: Health block, Identity card, Summary (with AI Assist), VRT Derivation Summary (VRT only), Raster Properties (raster/VRT), Collections, Related Datasets, Used in Maps. Also remove the Visibility card since it moves to Access tab.

3. **Enhance health block with "next priority" guidance** — In the health block (lines 135-159), when there are issues, add a "Next priority" indicator showing the first error's field name (or first warning if no errors). Use `validationData.errors[0]?.field ?? validationData.warnings[0]?.field` to get the field name. Display as: `"Next: fill in [field]"` after the completion percentage, styled as a clickable link that calls `onNavigateToValidationField(field)`. This gives users clear guidance on what to fix next.
  </action>
  <verify>
    Build passes: cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | tail -5
  </verify>
  <done>
    - AccessTab.tsx exists with distributions, export, visibility, auth note sections
    - OverviewTab no longer renders AccessSharingTab or any access/export/visibility content
    - Health block shows "Next: fill in [field]" with clickable navigation when issues exist
  </done>
</task>

<task type="auto">
  <name>Task 2: Wire Access tab into panels, sticky tabs, and map fit</name>
  <files>
    frontend/src/components/dataset/panels/VectorDetailPanel.tsx
    frontend/src/components/dataset/panels/RasterDetailPanel.tsx
    frontend/src/components/dataset/panels/VrtDetailPanel.tsx
    frontend/src/components/dataset/panels/CollectionDetailPanel.tsx
    frontend/src/pages/DatasetPage.tsx
    frontend/src/components/dataset/DatasetMap.tsx
  </files>
  <action>
1. **Add Access tab to all panels** — Import `AccessTab` in each panel component. Add a new `TabsTrigger` with `value="access"` labeled "Access" as the LAST tab in each panel. Add corresponding `TabsContent` rendering `<AccessTab dataset={dataset} datasetId={datasetId} />`. Tab ordering per CONTEXT.md:
   - Vector: Overview / Metadata / Data / Structure / Access
   - Raster: Overview / Metadata / Access
   - VRT: Overview / Metadata / Sources / Access
   - Collection: keep existing tabs + Access at end

2. **Update VALID_TABS** in `DatasetPage.tsx` (line 47) — Add `'access'` to the `VALID_TABS` array. Also update the legacy hash normalization: change `if (hash === 'access-sharing') return 'overview'` at line 53 to `return 'access'` so old links redirect to the new Access tab.

3. **Sticky tabs** — In each panel component, add `sticky top-0 z-10 bg-background` classes to the `<TabsList>` element. The TabsList already has `className="overflow-x-auto w-full"`, extend it to `className="overflow-x-auto w-full sticky top-0 z-10 bg-background border-b"`. The `bg-background` ensures content scrolling behind doesn't show through. The `border-b` provides visual separation when stuck.

4. **Tighter map fit** — In `DatasetMap.tsx`, increase the fitBounds padding from `40` to `60` for a better visual fit at line 928 (`fitBoundsOptions: { padding: 60 }`) and line 518 (`{ padding: 60 }`). In `DatasetPage.tsx`, reduce map container height from `h-80 lg:h-96` (line 562) to `h-64 lg:h-80` for a more compact default size that still shows the dataset extent clearly.
  </action>
  <verify>
    Build passes: cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | tail -5
  </verify>
  <done>
    - All 4 panel components render an Access tab as their last tab
    - VALID_TABS includes 'access', legacy 'access-sharing' hash redirects to 'access'
    - TabsList in all panels has sticky positioning classes
    - Map container is h-64/lg:h-80, fitBounds padding is 60
  </done>
</task>

</tasks>

<verification>
1. `cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit` — zero type errors
2. `cd /Users/ishiland/Code/geolens/frontend && npx vite build 2>&1 | tail -3` — build succeeds
3. Manual check: navigate to any dataset, confirm Access tab appears last, Overview has no access/export sections, tabs stick on scroll
</verification>

<success_criteria>
- Access tab exists as dedicated tab in all panel types with distributions, export (vector), visibility, auth note
- Overview tab is summary-first: health, identity, summary, raster props, VRT derivation, collections, related, maps
- Health block shows "Next: fill in [field]" guidance when validation issues exist
- Tabs stick to viewport top on scroll with bg-background and border-b
- Map container is smaller (h-64/lg:h-80) with increased fitBounds padding (60)
- TypeScript builds clean, no regressions
</success_criteria>

<output>
After completion, create `.planning/quick/260318-sma-detail-page-round-2-access-tab-summary-f/260318-sma-SUMMARY.md`
</output>
