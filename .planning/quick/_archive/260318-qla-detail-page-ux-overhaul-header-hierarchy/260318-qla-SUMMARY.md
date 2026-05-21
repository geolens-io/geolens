---
phase: 260318-qla
plan: 01
subsystem: frontend/detail-page
tags: [ux, detail-page, header, actions, metadata, health, vrt]
dependency_graph:
  requires: [RecordTypeBadge, useValidation, useVrtGenerations, useUpdatePublicationStatus]
  provides: [statsLine-header, compact-health-block, vrt-derivation-summary, read-first-metadata, collapsible-contacts]
  affects: [DatasetPage, DatasetDetailHeader, OverviewTab, SourceQualityTab, ContactsEditor, all-detail-panels]
tech_stack:
  added: []
  patterns: [read-first-metadata, kebab-overflow-actions, compact-health-block]
key_files:
  created: []
  modified:
    - frontend/src/pages/DatasetPage.tsx
    - frontend/src/components/dataset/DatasetDetailHeader.tsx
    - frontend/src/components/dataset/tabs/OverviewTab.tsx
    - frontend/src/components/dataset/tabs/SourceQualityTab.tsx
    - frontend/src/components/dataset/ContactsEditor.tsx
    - frontend/src/components/dataset/panels/VectorDetailPanel.tsx
    - frontend/src/components/dataset/panels/RasterDetailPanel.tsx
    - frontend/src/components/dataset/panels/VrtDetailPanel.tsx
    - frontend/src/components/dataset/panels/CollectionDetailPanel.tsx
    - frontend/src/pages/__tests__/DatasetPage.edit-affordances.test.tsx
decisions:
  - "Publish/Unpublish moved to kebab with toast error for validation blocking (simplified from popover)"
  - "VRT derivation summary uses 'See Sources tab' text instead of interactive button"
  - "SourceQualityTab uses renderReadFirstField helper with expandedFields Set for all 6 collapsible fields"
  - "Health block uses 12 as total validatable fields constant for completion percentage"
metrics:
  duration: 7min
  completed: "2026-03-18T23:39:40Z"
  tasks: 2
  files: 10
---

# Quick Task 260318-qla: Detail Page UX Overhaul Summary

Header hierarchy with RecordTypeBadge + type-specific stats, action bar rationalization into primary/kebab, read-first metadata with collapsible contacts, compact health block in OverviewTab, and VRT derivation framing.

## Changes Made

### Task 1: Header hierarchy + action bar rationalization (3beaced1)

- Added `statsLine` prop to `DatasetDetailHeader` rendered below the title
- Built type-specific stats lines: vector (geometry type, feature count, SRID), raster (bands, GSD, EPSG), VRT (type, sources, bands, EPSG), plus status + relative updated_at
- Reorganized action buttons: AddToMapButton, Download COG, ConnectDropdown remain as primary visible buttons in `leadingContent`
- Moved Publish/Unpublish, Re-upload, Create VRT, Delete into the kebab overflow `actions` array with proper priority ordering
- Implemented publish/unpublish logic inline with toast error for validation blocking and AlertDialog for unpublish confirmation
- Removed `PublishButton` import, type badges from leadingContent, and `DatasetHealthStrip` from page layout

### Task 2: Health block + VRT derivation + read-first metadata + bug fixes (8e8c0be0)

- Added compact health/QA block at top of OverviewTab showing required/recommended issue counts, completion percentage, and "Review issues" button
- Added VRT Derivation Summary card showing VRT type badge, source count, resolution strategy, generation status with semantic colors, and last regenerated date
- Made summary field read-first: empty state shows collapsed "Add summary..." button, expands to InlineEdit on click
- Made 6 SourceQualityTab fields (lineage, source URL, source org, quality statement, usage/access constraints) read-first with collapsible "Add {field}..." placeholders
- Collapsed contact form behind "Add contact" button when no contacts exist
- Fixed band color "undefined" display to show "Not specified"
- Replaced all dash "-" empty states with "Not available" in raster properties grid and band table
- Forwarded `datasetId` and `onNavigateToValidationField` props to OverviewTab from all four detail panels
- Updated test mocks for new hook dependencies (useUpdatePublicationStatus, useValidation, useAllSettings, useVrtGenerations)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated test mocks for DatasetPage**
- **Found during:** Task 2 verification
- **Issue:** Tests failed because DatasetPage now imports useUpdatePublicationStatus, useValidation, useAllSettings from hooks, and RecordTypeBadge -- none were mocked
- **Fix:** Added mocks for the new hooks and RecordTypeBadge, removed obsolete DatasetHealthStrip and PublishButton mocks
- **Files modified:** frontend/src/pages/__tests__/DatasetPage.edit-affordances.test.tsx
- **Commit:** 8e8c0be0

## Verification

- TypeScript compiles without errors
- All DatasetPage tests pass (5 pre-existing tests)
- 1 pre-existing i18n key parity test failure (nav.importData) unrelated to changes

## Self-Check: PASSED
