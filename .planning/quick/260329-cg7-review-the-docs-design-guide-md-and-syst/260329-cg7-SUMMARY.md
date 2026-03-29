---
phase: 260329-cg7
plan: 01
subsystem: frontend
tags: [design-system, tokens, accessibility, dark-mode]
dependency_graph:
  requires: []
  provides: [design-token-compliance]
  affects: [all-frontend-components]
tech_stack:
  added: []
  patterns: [status-colors.ts centralization, semantic token usage]
key_files:
  created: []
  modified:
    - frontend/src/lib/status-colors.ts
    - frontend/src/components/search/RecordTypeBadge.tsx
    - frontend/src/components/search/DatasetCard.tsx
    - frontend/src/components/search/SearchResultCard.tsx
    - frontend/src/components/dataset/tabs/OverviewTab.tsx
    - frontend/src/components/dataset/tabs/SourcesTab.tsx
    - frontend/src/components/dataset/QualityScoreCard.tsx
    - frontend/src/components/import/ImportPreview.tsx
    - frontend/src/components/import/FileDropzone.tsx
    - frontend/src/components/map/FeaturePopup.tsx
    - frontend/src/components/maps/MapCreateDialog.tsx
    - frontend/src/components/maps/VisibilityIcon.tsx
    - frontend/src/components/builder/SharePanel.tsx
    - frontend/src/components/builder/DatasetSearchPanel.tsx
    - frontend/src/components/builder/EphemeralBadge.tsx
    - frontend/src/components/builder/BasemapPicker.tsx
    - frontend/src/components/error/MapErrorBoundary.tsx
    - frontend/src/components/admin/StatsOverview.tsx
    - frontend/src/components/admin/AIStatusCard.tsx
    - frontend/src/components/admin/settings/SettingsAITab.tsx
    - frontend/src/components/admin/settings/EnvOnlyBanner.tsx
    - frontend/src/components/viewer/LayerLegend.tsx
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/pages/admin/AdminConfigOpsPage.tsx
    - frontend/src/pages/admin/AdminSharedMapsPage.tsx
decisions:
  - "Synthetic keyword Test Data badge uses hardcoded violet palette classes (same as vrt_dataset pattern) since no violet CSS token exists in the design system"
  - "RecordTypeBadge switched from variant=secondary to variant=outline to allow full border+bg+text badge coloring via status-colors.ts maps"
  - "vrtRasterStatusColors added to status-colors.ts for VRT status badge in OverviewTab"
metrics:
  duration: 20min
  completed_date: "2026-03-29"
  tasks: 2
  files_modified: 25
---

# Phase 260329-cg7 Plan 01: Design Guide Compliance Audit Summary

Design token compliance sweep across 25 frontend files — replaced all hardcoded Tailwind palette colors used for UI semantics with semantic tokens or status-colors.ts maps, and eliminated all transition-all usages.

## What Was Built

Extended `status-colors.ts` with 5 new exports (`recordTypeColors`, `ingestionStatusColors`, `validationLevelColors`, `healthDotColors`, `vrtRasterStatusColors`) and updated 25 component/page files to use them. Zero hardcoded palette colors remain in component files for status/semantic purposes. Zero `transition-all` remain anywhere in components or pages.

## Tasks Completed

### Task 1: Extend status-colors.ts and fix search/dataset/import components (13 files)

- **status-colors.ts**: Added `recordTypeColors`, `ingestionStatusColors`, `validationLevelColors`, `healthDotColors`, `vrtRasterStatusColors`
- **RecordTypeBadge**: Replaced inline `TYPE_CONFIG.className` entries with `recordTypeColors[type]` from status-colors.ts; switched to `variant="outline"` for proper border rendering
- **DatasetCard / SearchResultCard**: Inline `statusStyles` maps replaced with `ingestionStatusColors.{draft,ready,internal}`; synthetic Test Data badge uses violet pattern (no token available)
- **OverviewTab**: `text-green-*` all-checks-passed message → `text-success`; VRT status badge ternary → `vrtRasterStatusColors[status]`
- **SourcesTab**: Blue regenerating banner → `border-info/30 bg-info/5`; health dot `bg-green-500/bg-red-500/bg-gray-300` → `healthDotColors.*`
- **QualityScoreCard**: `transition-all` → `transition-[width] duration-300 ease-out`
- **ImportPreview**: Raster badge `bg-emerald-*` → `semanticBadgeColors.success`; geometry detected badge `bg-blue-*` → `semanticBadgeColors.info`
- **FileDropzone**: `transition-all` → `transition-[color,background-color,border-color]`
- **FeaturePopup**: `text-green-500` copy check icon → `text-success`
- **MapCreateDialog**: `text-amber-*` AI badge → `text-warning border-warning/50`
- **VisibilityIcon**: `text-amber-500` → `text-warning`
- **Commit**: `1239a880`

### Task 2: Fix builder, admin, viewer, error, and page-level components (13 files)

- **SharePanel**: `text-amber-500` internal icon → `text-warning`; blue info box → `border-info/30 bg-info/5 text-info/text-foreground`
- **DatasetSearchPanel**: Raster badge `text-emerald-*` → `semanticBadgeColors.success`
- **EphemeralBadge**: `bg-orange-500` status dot → `bg-warning`
- **BasemapPicker**: `transition-all` → targeted property list
- **MapErrorBoundary**: `text-amber-*` unsaved warning → `text-warning`
- **StatsOverview**: `bg-emerald-500` / `text-emerald-500` status → `bg-success` / `text-success`
- **AIStatusCard**: `transition-all` progress bar → `transition-[width]`
- **SettingsAITab**: Two amber warning boxes → `border-warning/30 bg-warning/5 text-warning`; `transition-all` → `transition-[width]`; `text-green-500` check icons → `text-success`
- **EnvOnlyBanner**: Complete rewrite — all `border-blue-*/bg-blue-*/text-blue-*` → `border-info/30`, `bg-info/5`, `bg-info/10`, `text-info`, `text-foreground`, `text-muted-foreground`
- **LayerLegend**: `transition-all` → `transition-[opacity,transform]`
- **MapBuilderPage**: Sidebar `transition-all` → `transition-[width,border-width]`; local `VisibilityIcon` `text-emerald-500/text-amber-500` → `text-success/text-warning`; unsaved dot `bg-amber-500` → `bg-warning`
- **AdminConfigOpsPage**: `text-green-600` service status → `text-success`; green import success box → `border-success/30 bg-success/5 text-success`
- **AdminSharedMapsPage**: Active/expiring embed token badges `bg-green-600/bg-amber-500 text-white` → `semanticBadgeColors.success/warning`; share token active badge → `semanticBadgeColors.success`
- **Commit**: `27fd1147`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing] `vrtRasterStatusColors` added to status-colors.ts**
- **Found during:** Task 1
- **Issue:** OverviewTab VRT status badge used a ternary with `border-green-500/border-yellow-500/border-red-500` but no named export existed for VRT raster status
- **Fix:** Added `vrtRasterStatusColors` map to status-colors.ts (`ready`, `regenerating`, `failed`)
- **Files modified:** `frontend/src/lib/status-colors.ts`, `frontend/src/components/dataset/tabs/OverviewTab.tsx`
- **Commit:** 1239a880

**2. [Rule 1 - Bug] RecordTypeBadge variant changed from secondary to outline**
- **Found during:** Task 1
- **Issue:** `variant="secondary"` overrides the badge background color with the secondary token, making custom bg-* classes fight specificity. Using `variant="outline"` allows the full border+bg+text class string from `recordTypeColors` to render correctly
- **Fix:** Changed to `variant="outline"` in RecordTypeBadge
- **Files modified:** `frontend/src/components/search/RecordTypeBadge.tsx`
- **Commit:** 1239a880

**3. [Rule 1 - Bug] MapBuilderPage unsaved dot `bg-amber-500` not in plan**
- **Found during:** Task 2 verification grep
- **Issue:** An additional `bg-amber-500` unsaved-changes dot in MapBuilderPage (line 326) was found that was not listed in the plan
- **Fix:** Replaced with `bg-warning`
- **Files modified:** `frontend/src/pages/MapBuilderPage.tsx`
- **Commit:** 27fd1147

## Known Stubs

None. All changes are behavioral replacements of CSS class strings; no data flow stubs introduced.

## Self-Check: PASSED

- FOUND: frontend/src/lib/status-colors.ts
- FOUND: frontend/src/components/search/RecordTypeBadge.tsx
- FOUND commit: 1239a880
- FOUND commit: 27fd1147
