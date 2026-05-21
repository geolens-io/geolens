---
phase: quick-54
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/pages/DatasetPage.tsx
  - frontend/src/components/dataset/ConnectDropdown.tsx
  - frontend/src/components/dataset/tabs/OverviewTab.tsx
autonomous: false
requirements: [UX-SWEEP-01]

must_haves:
  truths:
    - "VRT datasets show a Connect dropdown with Copy XYZ Tile URL option"
    - "Raster datasets show a type badge (Raster) in the header like VRT does"
    - "Raster Properties card uses consistent CardHeader/CardContent layout matching other cards"
    - "VRT Identity section shows source count and resolution strategy"
  artifacts:
    - path: "frontend/src/components/dataset/ConnectDropdown.tsx"
      provides: "VRT-aware connect dropdown with tile URL copy"
    - path: "frontend/src/components/dataset/tabs/OverviewTab.tsx"
      provides: "Consistent Raster Properties card, VRT metadata fields in Identity"
    - path: "frontend/src/pages/DatasetPage.tsx"
      provides: "Raster type badge in header, ConnectDropdown shown for VRT"
  key_links:
    - from: "frontend/src/pages/DatasetPage.tsx"
      to: "ConnectDropdown"
      via: "isVrt condition allowing ConnectDropdown to render"
      pattern: "isVrt.*ConnectDropdown"
    - from: "frontend/src/components/dataset/ConnectDropdown.tsx"
      to: "dataset.raster.tile_url"
      via: "isVrt check for tile URL copy option"
      pattern: "isVrt.*tile_url"
---

<objective>
Fix UI/UX gaps and inconsistencies across raster and VRT dataset detail pages to achieve uniformity with the vector detail page patterns.

Purpose: Quick task 53 added basic isVrt guards but left several functional and visual gaps — VRT has no Connect dropdown, raster has no type badge, Raster Properties card uses non-standard layout, and VRT-specific metadata is missing from the Identity section.

Output: Polished, uniform detail pages for all three record types.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@frontend/src/pages/DatasetPage.tsx
@frontend/src/components/dataset/ConnectDropdown.tsx
@frontend/src/components/dataset/tabs/OverviewTab.tsx
@frontend/src/types/api.ts
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix ConnectDropdown for VRT and add raster type badge</name>
  <files>frontend/src/pages/DatasetPage.tsx, frontend/src/components/dataset/ConnectDropdown.tsx</files>
  <action>
**ConnectDropdown.tsx:**
- Add `const isVrt = dataset.record_type === 'vrt_dataset';` alongside existing `isRaster`.
- Add VRT section: when `isVrt && dataset.raster?.tile_url`, show "Copy XYZ Tile URL" menu item that copies `${window.location.origin}${dataset.raster.tile_url}`. VRT has no COG download or S3 URI, so only tile URL is relevant.
- Also add VRT tile URL for raster datasets alongside existing options (the raster connect section already handles COG URL, tile URL, and S3 URI — confirm these all work for `isRaster`).
- The `!isRaster` fallback that shows vector Feature URL and Tile URL should become `!isRaster && !isVrt` to prevent vector URLs from showing for VRT datasets.

**DatasetPage.tsx:**
- In the `leadingContent` section (around line 380-401), change the ConnectDropdown rendering logic:
  - Currently: `isRaster && dataset.raster?.connect` shows Download COG + ConnectDropdown for raster; `!isRaster && !isVrt` shows ConnectDropdown for vector.
  - Change to: Show `<ConnectDropdown>` for VRT datasets too. Add `isVrt && dataset.raster?.tile_url` condition that shows ConnectDropdown (no Download COG button for VRT — this is intentional per decision).
  - Simplest fix: replace `{!isRaster && !isVrt && <ConnectDropdown dataset={dataset} />}` with `{(!isRaster || isVrt) && <ConnectDropdown dataset={dataset} />}` — but actually since ConnectDropdown now handles VRT internally, just render it for all non-raster types plus VRT. Cleaner: render ConnectDropdown unconditionally and let the dropdown itself decide what to show per record_type.
- Add a raster type badge in the `leadingContent` div, matching the VRT badge pattern. When `isRaster`, show `<Badge variant="outline">Raster</Badge>` using i18n: `t('raster.badge', { defaultValue: 'Raster' })`. Place it alongside the existing VRT badge logic.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -20</automated>
  </verify>
  <done>VRT datasets display a Connect dropdown with tile URL copy. Raster datasets show a "Raster" badge in the header. ConnectDropdown shows appropriate options per record type (raster: COG URL + tile URL + S3 URI; VRT: tile URL; vector: Feature URL + Tile URL).</done>
</task>

<task type="auto">
  <name>Task 2: Standardize Raster Properties card and add VRT metadata to Identity</name>
  <files>frontend/src/components/dataset/tabs/OverviewTab.tsx</files>
  <action>
**Raster Properties card layout fix (around line 238-335):**
- Replace the raw `<Card className="p-4">` with proper `<Card>` + `<CardHeader>` + `<CardContent>` structure to match every other card on the page (Identity, Collections, etc.).
- Move the `<h3>` title into `<CardHeader><CardTitle className="text-base">` and the grid + band details into `<CardContent>`.
- This is a styling-only change — no logic changes to what's rendered inside.

**VRT-specific fields in Identity card (around line 117-182):**
- After the existing metadata fields and before the Created/Last Updated fields, add VRT-specific fields that are conditionally rendered when `isVrt`:
  1. Source Count: `<MetadataField icon={Layers} label={t('metadata.sourceCount', { defaultValue: 'Source Count' })}>{dataset.raster?.source_count ?? t('common:notAvailable')}</MetadataField>` — show when `isVrt && dataset.raster?.source_count != null`.
  2. Resolution Strategy: `<MetadataField label={t('metadata.resolutionStrategy', { defaultValue: 'Resolution Strategy' })}><Badge variant="outline">{dataset.raster?.resolution_strategy}</Badge></MetadataField>` — show when `isVrt && dataset.raster?.resolution_strategy`.
- These use the same MetadataField component and grid layout as existing fields.
- Import `Database` icon is already imported; `Layers` is already imported. No new imports needed.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -20</automated>
  </verify>
  <done>Raster Properties card uses CardHeader/CardContent like all other cards. VRT datasets show source count and resolution strategy in the Identity section.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>
    Raster and VRT dataset detail page UI/UX improvements:
    1. VRT datasets now have a Connect dropdown with tile URL copy
    2. Raster datasets show a "Raster" type badge in the header
    3. Raster Properties card uses standard card layout
    4. VRT Identity section shows source count and resolution strategy
  </what-built>
  <how-to-verify>
    1. Visit http://localhost:8080 and navigate to a VRT dataset detail page
       - Verify "Connect" dropdown appears and contains "Copy XYZ Tile URL"
       - Verify source count and resolution strategy appear in the Identity card
       - Verify Raster Properties card looks consistent with other cards
    2. Navigate to a raster (COG) dataset detail page
       - Verify "Raster" badge appears in the header area
       - Verify Connect dropdown still shows COG URL, Tile URL, S3 URI options
       - Verify Raster Properties card layout matches other cards
    3. Navigate to a vector dataset detail page
       - Verify nothing changed — Connect dropdown shows Feature URL and Tile URL as before
       - Verify no raster-specific UI elements appear
  </how-to-verify>
  <resume-signal>Type "approved" or describe issues</resume-signal>
</task>

</tasks>

<verification>
- TypeScript compiles without errors
- All three record types (vector, raster, VRT) render their detail pages correctly
- ConnectDropdown shows appropriate options per record type
- Visual consistency across all detail pages
</verification>

<success_criteria>
- VRT detail page has a working Connect dropdown with tile URL
- Raster detail page has a type badge matching VRT's badge pattern
- Raster Properties card layout is consistent with all other cards
- VRT Identity section displays source count and resolution strategy
- No regressions on vector dataset detail pages
</success_criteria>

<output>
After completion, create `.planning/quick/54-in-depth-ui-ux-sweep-of-raster-and-vrt-d/54-SUMMARY.md`
</output>
