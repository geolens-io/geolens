---
phase: quick-53
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/dataset/tabs/OverviewTab.tsx
  - frontend/src/components/dataset/tabs/AccessSharingTab.tsx
autonomous: true
requirements: [VRT-UI-01, VRT-UI-02, VRT-UI-03, VRT-UI-04]

must_haves:
  truths:
    - "VRT dataset detail page does NOT show vector export dropdown (GeoPackage, GeoJSON, etc.)"
    - "VRT dataset detail page does NOT show Geometry Type, Feature Count, or Table Name fields"
    - "VRT dataset detail page shows the Raster Properties card (resolution, CRS, bands, etc.)"
    - "VRT dataset detail page hides Source Format field (VRTs have no meaningful source format)"
    - "Raster dataset detail page continues to work identically (no regression)"
    - "Vector dataset detail page continues to work identically (no regression)"
  artifacts:
    - path: "frontend/src/components/dataset/tabs/OverviewTab.tsx"
      provides: "VRT-aware identity card and raster properties rendering"
      contains: "isVrt"
    - path: "frontend/src/components/dataset/tabs/AccessSharingTab.tsx"
      provides: "VRT-aware export section hiding"
      contains: "isVrt"
  key_links:
    - from: "frontend/src/components/dataset/tabs/OverviewTab.tsx"
      to: "dataset.record_type"
      via: "isVrt boolean derived from record_type === 'vrt_dataset'"
      pattern: "isVrt.*vrt_dataset"
    - from: "frontend/src/components/dataset/tabs/AccessSharingTab.tsx"
      to: "dataset.record_type"
      via: "isVrt boolean derived from record_type === 'vrt_dataset'"
      pattern: "isVrt.*vrt_dataset"
---

<objective>
Fix VRT dataset detail pages to hide vector-specific UI elements and show raster-specific UI elements.

Purpose: VRT datasets currently leak vector-only UI (export dropdown, geometry type, feature count, table name) and miss raster UI (Raster Properties card). Both OverviewTab and AccessSharingTab only check `isRaster` but not `isVrt`, so VRTs fall through to the vector rendering path.

Output: Two corrected component files with proper VRT guards.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/components/dataset/tabs/OverviewTab.tsx
@frontend/src/components/dataset/tabs/AccessSharingTab.tsx
@frontend/src/pages/DatasetPage.tsx (reference for isVrt pattern)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix OverviewTab VRT guards — hide vector fields, show raster properties, hide source format</name>
  <files>frontend/src/components/dataset/tabs/OverviewTab.tsx</files>
  <action>
Add `isVrt` constant after the existing `isRaster` const on line 106:

```typescript
const isVrt = dataset.record_type === 'vrt_dataset';
```

Then apply these four changes:

1. **Lines 117, 127, 133** — Geometry Type, Feature Count, Table Name fields: Change the guard from `!isRaster` to `!isRaster && !isVrt` on all three conditional blocks. VRTs have no vector geometry, features, or table.

2. **Line 144** — Source Format field: Wrap in a conditional. Change from always-visible to `{!isVrt && (` ... `)}`. VRTs have no meaningful source_format (it is null). Rasters show "Geotiff" correctly, vectors show their format.

3. **Line 235** — Raster Properties card: Change the guard from `isRaster && dataset.raster` to `(isRaster || isVrt) && dataset.raster`. VRTs populate `dataset.raster` with resolution, CRS, bands, etc. and should display identically to raster datasets.

Do NOT change any other lines. Preserve all existing formatting and structure.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -20</automated>
  </verify>
  <done>
    - isVrt const added
    - Geometry Type, Feature Count, Table Name hidden for VRTs
    - Source Format hidden for VRTs
    - Raster Properties card visible for VRTs
    - No TypeScript errors
  </done>
</task>

<task type="auto">
  <name>Task 2: Fix AccessSharingTab — hide vector export section for VRTs</name>
  <files>frontend/src/components/dataset/tabs/AccessSharingTab.tsx</files>
  <action>
Add `isVrt` constant after the existing `isRaster` const on line 18:

```typescript
const isVrt = dataset.record_type === 'vrt_dataset';
```

Then on line 45, change the export section guard from `!isRaster` to `!isRaster && !isVrt`. The vector export dropdown (GeoPackage, GeoJSON, Shapefile, CSV) is meaningless for VRT datasets.

Do NOT change any other lines. Preserve all existing formatting.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -20</automated>
  </verify>
  <done>
    - isVrt const added
    - Export card hidden for VRT datasets
    - Export card still visible for vector datasets
    - No TypeScript errors
  </done>
</task>

</tasks>

<verification>
1. `npx tsc --noEmit` passes with no errors
2. Manual spot check: Open a VRT dataset detail page — no export section, no Geometry Type / Feature Count / Table Name / Source Format fields, Raster Properties card is visible
3. Manual spot check: Open a raster dataset detail page — unchanged behavior
4. Manual spot check: Open a vector dataset detail page — unchanged behavior
</verification>

<success_criteria>
- VRT detail pages show raster properties and hide all vector-specific UI
- Raster and vector detail pages are unaffected (no regression)
- TypeScript compiles cleanly
</success_criteria>

<output>
After completion, create `.planning/quick/53-review-vrt-export-and-ui-ux-sweep-of-ras/53-SUMMARY.md`
</output>
