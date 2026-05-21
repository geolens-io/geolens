---
phase: 260318-qla
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/dataset/DatasetDetailHeader.tsx
  - frontend/src/pages/DatasetPage.tsx
  - frontend/src/components/dataset/DatasetHealthStrip.tsx
  - frontend/src/components/dataset/tabs/OverviewTab.tsx
  - frontend/src/components/dataset/tabs/SourceQualityTab.tsx
  - frontend/src/components/dataset/ContactsEditor.tsx
  - frontend/src/components/dataset/panels/VectorDetailPanel.tsx
  - frontend/src/components/dataset/panels/RasterDetailPanel.tsx
  - frontend/src/components/dataset/panels/VrtDetailPanel.tsx
  - frontend/src/components/dataset/panels/CollectionDetailPanel.tsx
autonomous: true
requirements: [DPX-01, DPX-02, DPX-03, DPX-04, DPX-05]

must_haves:
  truths:
    - "Detail page header shows RecordTypeBadge + type-specific key stats inline below the title"
    - "Primary actions (Add to Map, Download, Connect) are visible buttons; secondary actions (Publish, Re-upload, Create VRT, Delete) are in a kebab overflow menu"
    - "Contact form is hidden behind an 'Add contact' button when no contacts exist"
    - "Empty metadata textareas (summary, lineage, quality statement, etc.) show collapsed 'Not set' placeholder with edit button instead of expanded empty form fields"
    - "DatasetHealthStrip is removed from between map and tabs; compact health block appears inside OverviewTab"
    - "VRT overview shows derivation summary with source count, VRT type, generation status, and last regenerated date"
    - "Band color 'undefined' shows 'Not specified' instead; dash '-' empty states replaced with 'Not available'"
  artifacts:
    - path: "frontend/src/components/dataset/DatasetDetailHeader.tsx"
      provides: "Stats line slot below title, restructured for new action flow"
    - path: "frontend/src/pages/DatasetPage.tsx"
      provides: "Reorganized action buttons into actions array with proper priority, health strip removed"
    - path: "frontend/src/components/dataset/tabs/OverviewTab.tsx"
      provides: "Compact health block, VRT derivation summary, bug fixes for empty states, read-first summary field"
    - path: "frontend/src/components/dataset/tabs/SourceQualityTab.tsx"
      provides: "Read-first empty state for lineage, source URL, source org, quality statement, usage/access constraints"
    - path: "frontend/src/components/dataset/ContactsEditor.tsx"
      provides: "Collapsible contact form behind 'Add contact' button"
  key_links:
    - from: "frontend/src/pages/DatasetPage.tsx"
      to: "frontend/src/components/dataset/DatasetDetailHeader.tsx"
      via: "statsLine prop with type-specific stats, actions array with all actions"
      pattern: "statsLine.*RecordTypeBadge"
    - from: "frontend/src/components/dataset/tabs/OverviewTab.tsx"
      to: "frontend/src/hooks/use-vrt.ts"
      via: "useVrtGenerations hook for last regenerated date"
      pattern: "useVrtGenerations"
    - from: "frontend/src/components/dataset/tabs/OverviewTab.tsx"
      to: "frontend/src/hooks/use-dataset.ts"
      via: "useValidation hook for compact health block"
      pattern: "useValidation"
---

<objective>
Overhaul detail page UX across 5 priority areas: header hierarchy with type badge and stats, action bar rationalization into primary/secondary, read-first metadata with collapsible contacts, dataset health redesign as compact inline block, and VRT derivation framing.

Purpose: Transform detail pages from "capable admin screens" into a polished geospatial product experience.
Output: Restructured detail page components with improved information hierarchy.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260318-qla-detail-page-ux-overhaul-header-hierarchy/260318-qla-CONTEXT.md
@.planning/quick/260318-qla-detail-page-ux-overhaul-header-hierarchy/260318-qla-RESEARCH.md

@frontend/src/pages/DatasetPage.tsx
@frontend/src/components/dataset/DatasetDetailHeader.tsx
@frontend/src/components/dataset/DatasetHealthStrip.tsx
@frontend/src/components/dataset/tabs/OverviewTab.tsx
@frontend/src/components/dataset/tabs/SourceQualityTab.tsx
@frontend/src/components/dataset/ContactsEditor.tsx
@frontend/src/components/dataset/InlineEdit.tsx
@frontend/src/components/dataset/PublishButton.tsx
@frontend/src/components/search/RecordTypeBadge.tsx
@frontend/src/hooks/use-vrt.ts
@frontend/src/components/dataset/panels/VectorDetailPanel.tsx
@frontend/src/components/dataset/panels/RasterDetailPanel.tsx
@frontend/src/components/dataset/panels/VrtDetailPanel.tsx
@frontend/src/components/dataset/panels/CollectionDetailPanel.tsx

<interfaces>
From frontend/src/components/dataset/DatasetDetailHeader.tsx:
```typescript
export interface DatasetDetailHeaderAction {
  id: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  onSelect: () => void;
  priority: number;
  visible: boolean;
  disabled?: boolean;
  variant?: ActionVariant;
}

interface DatasetDetailHeaderProps {
  title: string;
  onTitleSave?: (newTitle: string) => Promise<void>;
  canEditTitle?: boolean;
  actions?: DatasetDetailHeaderAction[];
  breadcrumbs?: DatasetDetailHeaderBreadcrumb[];
  leadingContent?: React.ReactNode;
  className?: string;
}
```

From frontend/src/components/dataset/PublishButton.tsx:
```typescript
// PublishButton uses Popover (for validation blockers) and AlertDialog (for unpublish confirmation).
// It is NOT a DropdownMenu trigger, so it CAN be replaced with a kebab menu item
// that calls the same mutation logic inline.
interface PublishButtonProps {
  datasetId: string;
  currentStatus: string | null;
  className?: string;
}
```

From frontend/src/components/search/RecordTypeBadge.tsx:
```typescript
export function RecordTypeBadge({ recordType, className }: RecordTypeBadgeProps): JSX.Element | null;
```

From frontend/src/hooks/use-vrt.ts:
```typescript
export function useVrtStatus(datasetId: string, isRegenerating: boolean);
export function useVrtGenerations(datasetId: string, params?: { limit?: number; offset?: number });
```

From frontend/src/components/dataset/tabs/OverviewTab.tsx:
```typescript
interface OverviewTabProps {
  dataset: DatasetResponse;
  canEdit: boolean;
  capabilities: DatasetEditCapabilities;
  summaryValue: string;
  onSummaryDraftSave: (value: string) => void;
  onSummaryDirtyChange: (isDirty: boolean) => void;
}
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Header hierarchy + action bar rationalization</name>
  <files>frontend/src/components/dataset/DatasetDetailHeader.tsx, frontend/src/pages/DatasetPage.tsx</files>
  <action>
**DatasetDetailHeader.tsx:**
1. Add a new `statsLine` prop (`React.ReactNode`) to `DatasetDetailHeaderProps`.
2. Render `statsLine` below the `<h1>` title inside the left column (`min-w-0` div). Add it as a div with `flex items-center gap-1.5 text-sm text-muted-foreground flex-wrap` styling.
3. Keep `leadingContent` prop working as-is (used for AddToMapButton and ConnectDropdown which are dropdown triggers and CANNOT go in the kebab overflow).

**DatasetPage.tsx:**
1. Import `RecordTypeBadge` from `@/components/search/RecordTypeBadge`.
2. Import `formatDate` from `@/lib/format` and `getRecordStatusLabel` from `@/i18n/labels` at the top of DatasetPage.tsx (these are NOT already imported -- they must be added).
3. Build a `statsLine` JSX node based on `dataset.record_type`:
   - Vector: `<RecordTypeBadge recordType={dataset.record_type} /> <Sep/> {geometryType} <Sep/> {feature_count} features <Sep/> EPSG:{srid}`
   - Raster: `<RecordTypeBadge recordType={dataset.record_type} /> <Sep/> {band_count} bands <Sep/> {gsd} m <Sep/> EPSG:{epsg}`
   - VRT: `<RecordTypeBadge recordType={dataset.record_type} /> <Sep/> {vrt_type} <Sep/> {source_count} sources <Sep/> {band_count} bands <Sep/> EPSG:{epsg}`
   - Use a `<span className="text-muted-foreground/50">·</span>` as separator between stats.
   - Below the stats line, add a status line: `{record_status label} · Updated {relative time from updated_at}`. Use the newly imported `getRecordStatusLabel()` and `formatDate()`.
4. Pass `statsLine` to `DatasetDetailHeader`.
5. Reorganize action buttons per CONTEXT.md locked decision -- primary actions visible as buttons, secondary/admin/destructive behind kebab:
   - `leadingContent`: AddToMapButton, Download COG button (raster only), ConnectDropdown. Remove type badges (now in statsLine) and PublishButton from leadingContent.
   - `actions` array (the prop is named `actions`, not `headerActions`): Add Publish/Unpublish as a simple `DropdownMenuItem`-compatible action. PublishButton currently uses Popover + AlertDialog but is NOT a nested DropdownMenu, so the publish/unpublish toggle CAN be implemented as a plain action item in the kebab. Create the action inline:
     - `id: 'publish'`, `label`: toggle based on `dataset.record_status === 'published'` ("Unpublish" vs "Publish"), `icon`: `GlobeLock` or `Globe`, `visible: isEditor`, `priority: 5`.
     - `onSelect`: call `useUpdatePublicationStatus` mutation with the same multi-step transition logic currently in PublishButton (draft->ready->internal->published or reverse). For validation blocking, check `requireMetadata && hasErrors` before proceeding -- if blocked, show a toast error with "Resolve validation issues before publishing" instead of the popover (acceptable simplification for kebab context). For unpublish, show the AlertDialog confirmation (reuse the same AlertDialog pattern already in DatasetPage).
   - Also in `actions` array: Re-upload (priority 10), Create VRT (priority 11, raster+editor only), Delete (priority 20, admin only).
   - Remove the standalone `<PublishButton>` import and usage from DatasetPage.tsx.
6. Remove the old inline type badges (`<Badge variant="outline">Raster</Badge>` etc.) from `leadingContent` -- replaced by RecordTypeBadge in statsLine.
7. Remove `<DatasetHealthStrip>` render from DatasetPage.tsx entirely (it moves to OverviewTab in Task 2). Remove the import.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -30</automated>
  </verify>
  <done>Header shows RecordTypeBadge + type-specific stats below title. Primary action buttons (Add to Map, Download, Connect) visible. Publish/Unpublish, Re-upload, Create VRT, Delete ALL in kebab overflow menu per user decision. Health strip removed from page layout. No type errors.</done>
</task>

<task type="auto">
  <name>Task 2: Health block + VRT derivation + metadata read-first + bug fixes + panel prop forwarding</name>
  <files>frontend/src/components/dataset/tabs/OverviewTab.tsx, frontend/src/components/dataset/tabs/SourceQualityTab.tsx, frontend/src/components/dataset/ContactsEditor.tsx, frontend/src/components/dataset/DatasetHealthStrip.tsx, frontend/src/components/dataset/panels/VectorDetailPanel.tsx, frontend/src/components/dataset/panels/RasterDetailPanel.tsx, frontend/src/components/dataset/panels/VrtDetailPanel.tsx, frontend/src/components/dataset/panels/CollectionDetailPanel.tsx</files>
  <action>
**OverviewTab.tsx:**
1. Add `datasetId` and `onNavigateToValidationField` as OPTIONAL props to `OverviewTabProps`:
   ```typescript
   datasetId?: string;
   onNavigateToValidationField?: (field: string) => void;
   ```
   These MUST be optional (using `?`) so that existing call sites compile without changes. The panels that have these values available will forward them; panels that don't will simply omit them.
2. Add a compact health/QA block at the TOP of the OverviewTab (before the Identity card). Import `useValidation` from `@/hooks/use-dataset`. Render a compact inline block:
   - When issues exist: `<div>` with flex row, showing `AlertCircle` icon + "N required · M recommended" text + a single "Review issues" `<Button variant="outline" size="sm">` that calls `onNavigateToValidationField?.('title')` (note optional chaining) to navigate to first issue.
   - Calculate completion: `const totalFields = requiredCount + recommendedCount + passedCount` where passedCount can be estimated (use a reasonable constant like 12 total validatable fields minus errors+warnings). Display "NN% complete" inline.
   - When all clear: `<div>` with `CheckCircle2` icon + "All checks passed" text in muted green.
   - Style: compact single line with `flex items-center gap-2 p-3 rounded-lg border bg-muted/30 text-sm`.
   - Use `datasetId ?? dataset.id` when calling `useValidation` so the hook works whether or not the prop is provided.
3. Add VRT Derivation Summary section (after Identity card, before Raster Properties, only when `isVrt`):
   - Import `useVrtGenerations` from `@/hooks/use-vrt`.
   - Call `useVrtGenerations(dataset.id, { limit: 1 })` with `enabled: isVrt` option.
   - Render a Card with title "Derivation Summary":
     - VRT type badge (Mosaic / Band Stack)
     - Source count
     - Resolution strategy
     - Generation status: use `dataset.raster?.status` -- show badge with "Ready"/"Regenerating"/"Failed" with semantic colors
     - Last regenerated: from `generationsData?.generations?.[0]?.started_at` formatted with `formatDate()`, or "Never" if no generations
     - A link/button "View sources" that could navigate to Sources tab (hint: the parent panel passes `onTabChange`)
   - NOTE: `onTabChange` is not currently a prop of OverviewTab. Instead of adding it, use a simple text note "See Sources tab for full detail" rather than an interactive button. Keep scope contained.
4. **Read-first summary field:** Update the `InlineEdit` for the summary field (around line 217) so that when the value is empty and `canEdit` is true, it renders as a collapsed placeholder button showing "Not set" / "Add summary..." instead of an empty expanded textarea. Approach: wrap the existing `InlineEdit` in a conditional -- if `!summaryValue && capabilities.summary.editable`, render a `<Button variant="ghost" size="sm" className="text-muted-foreground italic">` with text "Add summary..." that on click sets a local `summaryExpanded` state to true, which then renders the full `InlineEdit`. If `summaryValue` is truthy, render the `InlineEdit` directly (existing behavior).
5. Fix bug: band color `undefined` display. On line 341, change `{band.color_interp ?? '-'}` to `{band.color_interp && band.color_interp !== 'undefined' ? band.color_interp : t('common:notSpecified', { defaultValue: 'Not specified' })}`.
6. Fix bug: dash `-` empty states in raster properties grid. Replace all `?? '-'` patterns with `?? t('common:notAvailable', { defaultValue: 'Not available' })`. Specifically:
   - Line 279: `band_count ?? '-'` -> use notAvailableLabel
   - Line 290: `compression ?? '-'` -> use notAvailableLabel
   - Line 298: fileSize `-` -> use notAvailableLabel
   - Line 340: `band.nodata ?? '-'` -> use notAvailableLabel (in band table)

**Panel prop forwarding (VectorDetailPanel, RasterDetailPanel, VrtDetailPanel, CollectionDetailPanel):**
7. In each of the four panel files, update the `<OverviewTab>` call site to forward `datasetId` and `onNavigateToValidationField` props IF those values are available in the panel's own props/scope:
   - Check each panel's own props interface for `datasetId` (or `dataset.id`) and `onNavigateToValidationField`.
   - If the panel already has `dataset` as a prop (which all do), pass `datasetId={dataset.id}`.
   - If the panel has `onNavigateToValidationField` in its own props, forward it: `onNavigateToValidationField={onNavigateToValidationField}`. If the panel does NOT have this prop, simply omit it (the OverviewTab prop is optional so this is safe).
   - Do NOT modify the panel props interfaces -- only forward what's already available.

**SourceQualityTab.tsx:**
8. **Read-first metadata fields:** Apply the same collapsed-when-empty pattern to the following `InlineEdit` fields: lineage_summary, source_url, source_organization, quality_statement, usage_constraints, access_constraints. For each:
   - When the field value (from `draftValues`) is empty/falsy AND the capability is editable: render a collapsed `<Button variant="ghost" size="sm" className="text-muted-foreground italic h-auto py-1 px-2">` showing "Not set" / "Add {field name}..." text. On click, set a local expanded state (`expandedFields` Set or individual booleans) that then renders the existing `InlineEdit`.
   - When the field value is populated: render the `InlineEdit` directly (existing behavior, unchanged).
   - When `!capability.editable` and value is empty: show static "Not set" text (no button).
   - Add a `useState<Set<string>>` named `expandedFields` initialized to empty set. Toggle membership on button click. Check `expandedFields.has(fieldName)` to decide rendering.
   - This preserves the existing `EditableFieldShell` wrapper, `onDirtyChange`, and draft save patterns. Only the empty-state rendering changes.

**ContactsEditor.tsx:**
9. Add a `showForm` state, initialized to `false`.
10. When `canEdit && contacts.length === 0 && !showForm`: show the "No contacts" message + an "Add contact" `<Button variant="outline" size="sm">` that sets `showForm(true)`.
11. When `canEdit && (contacts.length > 0 || showForm)`: show the existing contact list + the add form (current behavior).
12. When `!canEdit && contacts.length === 0`: show just "No contacts" text (existing behavior, unchanged).
13. After successfully adding a contact (in `handleAdd` success path), set `showForm(false)` -- the contact list will now be non-empty so the form stays visible via the `contacts.length > 0` condition.

**DatasetHealthStrip.tsx:**
Keep the file but it is no longer imported anywhere. Leave it in place for now (can be cleaned up later). No changes needed to this file.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -30</automated>
  </verify>
  <done>Compact health block renders at top of OverviewTab with issue counts and completion percentage. VRT pages show derivation summary with source count, type, generation status, and last regenerated date. Contact form hidden behind "Add contact" button when no contacts exist. Empty summary field shows collapsed "Add summary..." placeholder. Empty SourceQualityTab fields (lineage, source URL, source org, quality statement, usage/access constraints) show collapsed "Not set" placeholder buttons expanding on click. Band color "undefined" shows "Not specified". Dash empty states replaced with "Not available". All four panel files forward datasetId to OverviewTab. No type errors.</done>
</task>

</tasks>

<verification>
1. TypeScript compiles without errors: `cd frontend && npx tsc --noEmit`
2. Visit a vector dataset detail page -- header shows RecordTypeBadge + geometry type + feature count + SRID below title
3. Visit a raster dataset detail page -- header shows RecordTypeBadge + band count + resolution + EPSG
4. Visit a VRT dataset detail page -- header shows RecordTypeBadge + VRT type + source count + bands + EPSG; derivation summary card visible in overview
5. Action buttons: Add to Map, Download COG, Connect visible as buttons; Publish/Unpublish, Re-upload, Create VRT, Delete ALL in kebab overflow menu
6. Health block appears as compact inline element in overview tab, not between map and tabs
7. ContactsEditor shows "Add contact" button when no contacts exist, not the full form
8. Empty summary field on OverviewTab shows "Add summary..." collapsed placeholder, expands to textarea on click
9. Empty fields on SourceQualityTab (lineage, source URL, etc.) show "Not set" collapsed placeholders, expand on click
10. No "undefined" or bare "-" empty states in raster properties or band table
</verification>

<success_criteria>
- Detail page header shows type badge + 2-4 key stats inline below title for all record types
- Action bar has clear primary vs secondary separation with kebab overflow -- Publish/Unpublish is in the kebab, NOT a visible button
- Metadata sections are read-first: contacts collapsed behind button, empty textareas collapsed to "Not set" / "Add..." placeholder buttons
- Dataset health is a compact QA block inside overview tab content
- VRT pages clearly communicate derived nature with derivation summary
- Bug fixes: no "undefined" band colors, no bare "-" empty states
</success_criteria>

<output>
After completion, create `.planning/quick/260318-qla-detail-page-ux-overhaul-header-hierarchy/260318-qla-SUMMARY.md`
</output>
