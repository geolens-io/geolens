# Quick Task 260318-qla: Detail Page UX Overhaul - Research

**Researched:** 2026-03-18
**Domain:** Frontend detail page component architecture
**Confidence:** HIGH

## Summary

The detail page (`DatasetPage.tsx`) has a clear component hierarchy that makes this overhaul tractable. The header, health strip, action buttons, and type-specific panels are already modular. The main work is restructuring existing components rather than building new ones.

**Primary recommendation:** Restructure `DatasetDetailHeader` to include a type-aware stats line, move all action buttons into its `actions` array (with primary/overflow partitioning already built-in), collapse the contacts form behind an "Add contact" button, and replace `DatasetHealthStrip` with a compact inline block inside overview tab content.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Execute only top 5 priorities: header hierarchy, action bar rationalization, read-first metadata, dataset health redesign, VRT framing
- Do NOT tackle: Access section polish, tab standardization, empty states, related dataset cards, AI Assist placement
- Keep current tab structure unchanged (Vector: Overview/Metadata/Data/Structure; Raster: Overview/Metadata; VRT: Overview/Metadata/Sources)
- Primary actions visible: Add to Map, Download/Export, Connect, Edit Features (vector), Regenerate (VRT)
- Secondary/admin actions behind kebab: Re-upload, Unpublish/Publish, Create VRT, Delete
- Metadata read-first: empty fields show "Not set" + edit button; populated fields show values with inline edit; forms expand on interaction
- Contact form hidden behind "Add contact" button
- Empty textareas collapsed to placeholder buttons

### Claude's Discretion
- Exact visual design of kebab menu component
- Dataset Health progress calculation and display
- VRT derivation summary layout details
- Specific component naming and file organization

### Deferred Ideas (OUT OF SCOPE)
- Access section polish, tab standardization, empty states, related dataset cards, AI Assist placement
</user_constraints>

## Current Component Architecture

### File Map

| File | Purpose | Changes Needed |
|------|---------|----------------|
| `pages/DatasetPage.tsx` | Page shell, routes to panels, holds action bar logic | Move action buttons into `headerActions` array, relocate health strip |
| `dataset/DatasetDetailHeader.tsx` | Breadcrumb + title + actions | Add stats line slot, restructure action partitioning |
| `dataset/DatasetHealthStrip.tsx` | Standalone card between map and tabs | Replace with compact block inside overview content |
| `dataset/panels/VectorDetailPanel.tsx` | Tab container for vector | No structural changes |
| `dataset/panels/RasterDetailPanel.tsx` | Tab container for raster | No structural changes |
| `dataset/panels/VrtDetailPanel.tsx` | Tab container for VRT | No structural changes |
| `dataset/tabs/OverviewTab.tsx` | Identity card, raster props, collections, access | Add health block, VRT derivation summary |
| `dataset/tabs/MetadataTab.tsx` | Contacts, keywords, source quality, validation, history | Make contacts collapsible |
| `dataset/ContactsEditor.tsx` | Always-visible form with inline add | Collapse form behind "Add contact" button |
| `dataset/EditableFieldShell.tsx` | Editable field wrapper with pencil icon | Already supports read-first; no changes needed |
| `dataset/InlineEdit.tsx` | Click-to-edit text fields | Already shows placeholder when empty; minor refinement for "Not set" |
| `dataset/PendingEditsBar.tsx` | Sticky save/discard bar | No changes needed |
| `search/RecordTypeBadge.tsx` | Colored type badge (blue/emerald/violet/amber) | Reuse on detail page header |

### Current Action Button Layout (DatasetPage.tsx lines 350-412)

Currently, buttons are split between two locations:
1. **`headerActions` array** (lines 350-371): Only Re-upload and Delete -- shown as primary/overflow buttons
2. **`leadingContent` prop** (lines 382-411): PublishButton, AddToMapButton, Download COG, ConnectDropdown, Create VRT -- rendered as inline JSX

This is inverted from what the UX review wants. The "leading content" buttons are the primary actions, while the `headerActions` are secondary/destructive.

### Action Button Permission Gates

| Button | Condition | Target Placement |
|--------|-----------|-----------------|
| AddToMapButton | Always shown | Primary |
| Download COG | `isRaster && dataset.raster?.connect` | Primary (raster only) |
| ConnectDropdown | Always shown | Primary |
| PublishButton | `isEditor` | Secondary (kebab) |
| Re-upload | `isEditor && !isVrt` | Secondary (kebab) |
| Create VRT | `isRaster && isEditor` | Secondary (kebab) |
| Delete | `isAdmin` | Secondary (kebab) |

### Overflow Menu Pattern (Already Built)

`DatasetDetailHeader.tsx` already has a working kebab overflow menu using `DropdownMenu` from shadcn/radix. The `partitionActions()` function splits actions by priority into primary (shown as buttons) and overflow (shown in "..." dropdown). Desktop shows 2 primary, mobile shows 1. This can be extended to handle all actions.

**Key insight:** The `DatasetDetailHeaderAction` interface supports `variant`, `icon`, `visible`, `disabled`, and `priority`. All current inline buttons can be converted to this action interface. However, some actions (AddToMapButton, ConnectDropdown) are themselves dropdowns -- these need to remain as custom rendered elements, not simple onClick actions.

**Recommendation:** Keep AddToMapButton and ConnectDropdown as custom `leadingContent` (they are dropdown triggers). Move PublishButton, Re-upload, Create VRT, Delete into the `headerActions` array with appropriate priorities.

## Header Identity Band Data Availability

All data needed for the stats line is already on the `DatasetResponse` object:

| Stat | Field | Available For |
|------|-------|---------------|
| Record type | `dataset.record_type` | All |
| Geometry type | `dataset.geometry_type` | Vector |
| Feature count | `dataset.feature_count` | Vector |
| CRS/SRID | `dataset.srid` (vector), `dataset.raster.epsg` (raster/VRT) | All |
| Band count | `dataset.raster.band_count` | Raster, VRT |
| Resolution | `dataset.raster.res_x`, `dataset.raster.res_y` | Raster, VRT |
| VRT type | `dataset.raster.vrt_type` | VRT |
| Source count | `dataset.raster.source_count` | VRT |
| Record status | `dataset.record_status` | All |
| Updated at | `dataset.updated_at` | All |
| VRT status | `dataset.raster.status` | VRT |

**RecordTypeBadge** at `search/RecordTypeBadge.tsx` provides colored type badges already used on search cards. Import and reuse on detail header.

### Stats Line Examples (from data)

```
Vector:  [RecordTypeBadge: Vector] . MultiPolygon . 252 features . EPSG:4326
Raster:  [RecordTypeBadge: Raster] . 4 bands . 0.3 m . EPSG:6527
VRT:     [RecordTypeBadge: Virtual Raster] . Mosaic . 2 sources . 4 bands . EPSG:6527
```

Status line below: `Published . Updated 3 days ago` -- use `dataset.record_status` + relative time from `dataset.updated_at`.

## Dataset Health Redesign

### Current Implementation (DatasetHealthStrip.tsx)

- Uses `useValidation(datasetId)` hook returning `{ errors: ValidationIssue[], warnings: ValidationIssue[] }`
- Renders as a full-width `Card` between map and tabs
- Shows error count badge + warning count badge + up to 4 action buttons
- Each action button uses `getValidationNavigationActions()` to navigate to specific fields

### Redesign Approach

Replace with compact block inside OverviewTab content (after summary, before raster properties). Show:
- "5 required . 4 recommended . 62% complete" as inline text
- Percentage = `(total_fields - errors - warnings) / total_fields` (need total field count -- derive from validation response or hardcode known fields)
- Single "Review issues" button that navigates to Metadata tab validation section
- When all clear, show compact "All checks passed" with check icon

**Validation data shape** (`ValidationIssue`): `{ field: string, message: string, severity: string }` -- errors array and warnings array.

## Read-First Metadata Pattern

### Current Behavior
- `InlineEdit` already shows placeholder text when value is empty (line 176: `<span className="text-foreground/70 italic">{placeholder}</span>`)
- `EditableFieldShell` wraps fields with pencil icon and editable styling
- `ContactsEditor` always renders the full add-contact form when `canEdit=true` (lines 112-167)
- `SourceQualityTab` fields (lineage, source_url, etc.) use `InlineEdit` with `EditableFieldShell`

### Changes Needed

1. **ContactsEditor**: When no contacts exist and `canEdit`, show just "No contacts" + "Add contact" button. On click, expand to show the form. Currently the form is always visible.

2. **SourceQualityTab fields**: Already use `InlineEdit` with placeholders. The placeholder text should change from current `t('inline.noDescription')` style to "Not set" consistently. The `EditableFieldShell` border styling (`border-primary/20 bg-primary/5`) makes empty fields look like active form controls -- should be toned down for empty-state display.

3. **Summary in OverviewTab**: Already has `InlineEdit` with placeholder. Just needs "Not set" text instead of current placeholder.

## VRT Framing

### Currently Available VRT Data

| Data | Source | Currently Displayed |
|------|--------|-------------------|
| VRT type (mosaic/band_stack) | `dataset.raster.vrt_type` | Badge in overview identity section |
| Source count | `dataset.raster.source_count` | MetadataField in overview |
| Resolution strategy | `dataset.raster.resolution_strategy` | MetadataField in overview |
| Generation status | `dataset.raster.status` | Only in SourcesTab banners |
| Source health | via `useVrtStatus()` hook | Only in SourcesTab |
| Generation history | via `useVrtGenerations()` hook | Only in SourcesTab |
| Last generation timestamp | `generationsData.generations[0].started_at` | Only in SourcesTab table |

### Needed for VRT Overview Summary

Add a "Derivation Summary" card/section to OverviewTab (VRT only) showing:
- Source count + VRT type prominently
- Resolution strategy
- Generation status badge (ready/regenerating/failed)
- Last regenerated timestamp (from generations API)
- Link to Sources tab for full detail

The `useVrtStatus` and `useVrtGenerations` hooks exist and can be called from OverviewTab when `isVrt`.

## Bug Fixes

1. **`undefined` band color**: In OverviewTab line 342, `band.color_interp ?? '-'` -- the `-` fallback should become "Not specified". Also check if `color_interp` can be the literal string "undefined" from backend.

2. **Dash `-` empty states**: Multiple locations use `-` as empty state (raster properties grid, band table). Replace with "Not available" or "Not specified".

## Common Pitfalls

### Pitfall 1: Breaking Action Dropdown Nesting
AddToMapButton and ConnectDropdown are themselves DropdownMenu components. Nesting them inside the header's overflow DropdownMenu would break (Radix doesn't support nested dropdown menus). Keep these as direct button elements, not inside the kebab.

### Pitfall 2: VRT Hook Dependencies
`useVrtStatus` and `useVrtGenerations` are currently only used in SourcesTab. Adding them to OverviewTab means they fire on initial page load. Ensure they're conditionally enabled (`enabled: isVrt`) to avoid unnecessary API calls for non-VRT datasets.

### Pitfall 3: ContactsEditor State Reset
When collapsing the contact form, form state (name, email, org, role) should be reset. The current implementation uses `useState` for each field, so unmounting the form via conditional render will auto-reset.

## Sources

### Primary (HIGH confidence)
- Direct code inspection of all listed component files
- TypeScript type definitions in `frontend/src/types/api.ts`
