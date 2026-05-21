---
phase: 260424-lqy
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/builder/BuilderMap.tsx
  - frontend/src/lib/basemap-utils.ts
  - frontend/src/components/builder/BasemapPicker.tsx
  - frontend/src/components/builder/__tests__/BasemapPicker.test.tsx
autonomous: true
requirements: [BASEMAP-RACE-FIX, BASEMAP-UX-POLISH]

must_haves:
  truths:
    - "Rapid basemap toggling (4+ switches in <1s) never causes data layers to disappear"
    - "Blank basemap produces zero CORS errors in the browser console"
    - "Selected basemap shows a visible ring differentiated from the background"
    - "Basemap grid expands/collapses with a smooth animation, not an instant toggle"
    - "Labels toggle uses the project Switch component, visually consistent with the rest of the UI"
  artifacts:
    - path: "frontend/src/components/builder/BuilderMap.tsx"
      provides: "Persistent style.load listener (map.on, not map.once)"
      contains: "map.on('style.load'"
    - path: "frontend/src/lib/basemap-utils.ts"
      provides: "CORS-safe glyph URL using OpenFreeMap endpoint"
      contains: "tiles.openfreemap.org/fonts"
    - path: "frontend/src/components/builder/BasemapPicker.tsx"
      provides: "Polished basemap picker with animation, ring offset, Switch component"
      contains: "grid-rows"
  key_links:
    - from: "BuilderMap.tsx style.load handler"
      to: "syncLayersToMap"
      via: "persistent listener reads syncInputsRef.current"
      pattern: "map\\.on\\('style\\.load'"
    - from: "basemap-utils.ts FALLBACK_GLYPHS"
      to: "toMaplibreStyle inline styles"
      via: "constant reference"
      pattern: "openfreemap\\.org/fonts"
---

<objective>
Fix the map builder basemap race condition where rapid basemap toggling causes data layers to disappear, fix CORS glyph errors on blank basemap, and polish the BasemapPicker UX (selected ring, expand animation, Switch component for labels toggle).

Purpose: Users can freely switch basemaps without losing their data layers, and the basemap picker looks polished and consistent with the rest of the UI.
Output: Three modified source files, one updated test file.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260424-lqy-in-the-map-builder-when-toggling-the-bas/260424-lqy-CONTEXT.md
@.planning/quick/260424-lqy-in-the-map-builder-when-toggling-the-bas/260424-lqy-RESEARCH.md

<interfaces>
<!-- BuilderMap refs and sync pattern (lines 66-69, 126-127, 144-145) -->
From frontend/src/components/builder/BuilderMap.tsx:
```typescript
const managedSourcesRef = useRef<Set<string>>(new Set());
const lastOrderKeyRef = useRef('');
const [mapReady, setMapReady] = useState(false);
const syncInputsRef = useRef({ layers, tokenMap, tileConfig, showBasemapLabels });
syncInputsRef.current = { layers, tokenMap, tileConfig, showBasemapLabels };
const prevBasemapUrlRef = useRef<string | null>(null);
```

<!-- ViewerMap persistent listener pattern (lines 457-477) — the pattern to adopt -->
From frontend/src/components/viewer/ViewerMap.tsx:
```typescript
useEffect(() => {
  const map = mapRef.current;
  if (!map) return;
  const onStyleLoad = () => {
    managedSourcesRef.current = new Set();
    prevOrderKeyRef.current = '';
    if (syncInputsRef.current.layers.length > 0) {
      runSync(map);
    }
    reseedTerrainOnStyleLoad();
  };
  map.on('style.load', onStyleLoad);
  return () => { map.off('style.load', onStyleLoad); };
}, [mapReady, runSync, reseedTerrainOnStyleLoad]);
```

<!-- BasemapPicker imports and Switch component -->
From frontend/src/components/ui/switch.tsx:
```typescript
// Radix-based Switch with size="sm" | "default" variants
function Switch({ className, size = "default", ...props }: 
  React.ComponentProps<typeof SwitchPrimitive.Root> & { size?: "sm" | "default" })
export { Switch }
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix race condition and CORS glyphs</name>
  <files>frontend/src/components/builder/BuilderMap.tsx, frontend/src/lib/basemap-utils.ts</files>
  <action>
**BuilderMap.tsx — Replace the buggy style.load effect (lines 205-234) with a persistent listener matching the ViewerMap pattern.**

Replace the entire `useEffect` block at lines 205-234 with:

```typescript
// Re-add data layers after basemap switch (persistent listener).
// Unlike the previous map.once() approach that re-registered per URL change,
// this listener survives any number of rapid style swaps — fixing the race
// where cleanup removed the listener before style.load fired.
useEffect(() => {
  const map = mapRef.current;
  if (!map) return;

  const onStyleLoad = () => {
    const { layers: l, tokenMap: t, tileConfig: tc, showBasemapLabels: sbl } = syncInputsRef.current;
    managedSourcesRef.current = new Set();
    lastOrderKeyRef.current = '';
    const tileBaseUrl = getEnvConfig().TILE_BASE_URL || tc?.cdn_base_url || undefined;
    syncLayersToMap(map, l.map(toSyncInput), t, tileBaseUrl, managedSourcesRef, lastOrderKeyRef);
    reorderBasemapLabels(map, sbl);
    refreshQueryLayerIds();
  };

  map.on('style.load', onStyleLoad);
  return () => {
    map.off('style.load', onStyleLoad);
  };
}, [mapReady]);
```

Key changes from the old code:
- `map.on` instead of `map.once` — survives multiple rapid style changes
- Dependency is `[mapReady]` only, NOT `[basemapEntry?.url]` — no teardown/re-register per switch
- Resets `lastOrderKeyRef` to `''` so layer order is always fully re-applied
- Removes the synchronous `isStyleLoaded()` fallback (lines 227-230) — the persistent listener is already registered before any basemap switch occurs
- Removes the `prevBasemapUrlRef` guard check (lines 209-213) — the persistent listener handles all cases

Also remove the `prevBasemapUrlRef` declaration at line 145 (`const prevBasemapUrlRef = useRef<string | null>(null);`) since it is no longer referenced.

**basemap-utils.ts — Fix CORS glyph URL.**

Line 13: Change `FALLBACK_GLYPHS` from `'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf'` to `'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf'`.

Line 76 (blank basemap): Remove the `glyphs: FALLBACK_GLYPHS` property entirely from the blank basemap style object. The blank basemap has zero symbol/text layers, so it never requests glyphs. Omitting the property prevents any glyph fetch attempts.

Line 94 (raster basemap): Replace the hardcoded `'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf'` with `FALLBACK_GLYPHS` (the constant). Data layers with labels placed on raster basemaps need a valid glyph endpoint.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx vitest run frontend/src/components/builder/__tests__/BasemapPicker.test.tsx --reporter=verbose 2>&1 | tail -20</automated>
  </verify>
  <done>
    - BuilderMap uses `map.on('style.load', ...)` with `[mapReady]` dependency (persistent listener)
    - No `map.once('style.load', ...)` remains in BuilderMap.tsx
    - No `prevBasemapUrlRef` remains in BuilderMap.tsx
    - No `isStyleLoaded()` fallback remains in the style.load effect
    - FALLBACK_GLYPHS uses `tiles.openfreemap.org/fonts/` (CORS-safe)
    - Blank basemap style object has no `glyphs` property
    - Raster basemap style uses `FALLBACK_GLYPHS` constant (not hardcoded duplicate)
  </done>
</task>

<task type="auto">
  <name>Task 2: Polish BasemapPicker UX</name>
  <files>frontend/src/components/builder/BasemapPicker.tsx, frontend/src/components/builder/__tests__/BasemapPicker.test.tsx</files>
  <action>
**BasemapPicker.tsx — Apply four UX improvements.**

1. **Selected state ring** (line 62-66): Change the selected-state classes from `'ring-2 ring-primary bg-accent'` to `'ring-2 ring-primary ring-offset-2 ring-offset-background bg-accent'`. The `ring-offset-2` creates visual separation between the ring and the thumbnail, and `ring-offset-background` ensures the offset color is theme-aware.

2. **Grid expand animation** (lines 51-80): Replace the binary `{open && (...)}` toggle with a CSS grid-rows transition. Wrap the grid content:

```tsx
{/* Expanded: grid of options */}
<div className={cn(
  "grid transition-[grid-template-rows] duration-200 ease-out",
  open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
)}>
  <div className="overflow-hidden">
    <div className="grid grid-cols-4 gap-2 pt-2">
      {options.map((b) => (
        <button
          key={b.id}
          data-testid="basemap-option"
          aria-pressed={value === b.id}
          onClick={() => {
            onChange(b.id);
            setOpen(false);
          }}
          className={cn(
            'flex flex-col items-center gap-0.5 rounded-md p-1 transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
            value === b.id
              ? 'ring-2 ring-primary ring-offset-2 ring-offset-background bg-accent'
              : 'hover:bg-accent/50',
          )}
        >
          <img
            src={basemapThumbnail(b.id)}
            alt={b.label}
            className="w-full aspect-square rounded object-cover max-h-14"
          />
          <span className="text-[11px] text-center leading-tight truncate w-full">
            {b.label}
          </span>
        </button>
      ))}
    </div>
  </div>
</div>
```

Note: also add `max-h-14` to the grid thumbnail `<img>` className to prevent oversized thumbnails on wide sidebars.

3. **Labels toggle** (lines 82-95): Replace the native `<input type="checkbox">` with the project's `Switch` component for visual consistency. Import `Switch` from `@/components/ui/switch`. Replace the existing toggle markup:

```tsx
{/* Basemap labels toggle */}
{onToggleLabels && (
  <label className="flex items-center gap-2 px-2 pt-2 pb-1 text-xs text-muted-foreground cursor-pointer select-none">
    <Switch
      size="sm"
      checked={showLabels}
      onCheckedChange={onToggleLabels}
      aria-label={t('basemap.showLabels')}
    />
    {t('basemap.showLabels')}
  </label>
)}
```

Remove the wrapping `<div role="group">` since the Switch has its own aria-label and the group wrapper is unnecessary for a single control.

4. **Add import**: Add `import { Switch } from '@/components/ui/switch';` to the imports section.

**BasemapPicker.test.tsx — Update test for animation wrapper.**

The "expands grid on click" test (line 35-43) currently asserts `screen.getAllByTestId('basemap-option')`. With the animation wrapper, the options are always in the DOM (hidden via `grid-rows-[0fr]` + `overflow-hidden`). The test still works because `getAllByTestId` finds DOM elements regardless of visibility. However, the "calls onChange and closes on basemap selection" test (line 53) asserts `screen.queryAllByTestId('basemap-option')).toHaveLength(0)` after closing — this will now find 5 elements since they remain in the DOM. 

Fix: Change line 53 from checking length 0 to verifying the grid has collapsed. Replace `expect(screen.queryAllByTestId('basemap-option')).toHaveLength(0)` with a check that the outer animation wrapper has the collapsed class:

```typescript
// After closing, the animation container should have the collapsed class
const gridWrapper = screen.getAllByTestId('basemap-option')[0].closest('[class*="grid-rows"]');
expect(gridWrapper).toHaveClass('grid-rows-[0fr]');
```
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx vitest run frontend/src/components/builder/__tests__/BasemapPicker.test.tsx --reporter=verbose 2>&1 | tail -20</automated>
  </verify>
  <done>
    - Selected basemap options show `ring-offset-2 ring-offset-background` for visual separation
    - Grid expands/collapses with `grid-rows-[1fr]`/`grid-rows-[0fr]` transition (200ms ease-out)
    - Grid thumbnails have `max-h-14` to constrain size
    - Labels toggle uses the `Switch` component from `@/components/ui/switch` with `size="sm"`
    - No native `<input type="checkbox">` remains in BasemapPicker
    - All BasemapPicker tests pass
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

No new trust boundaries introduced. All changes are client-side UI and style-switching logic.

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-lqy-01 | T (Tampering) | FALLBACK_GLYPHS URL | accept | URL is a public CDN endpoint (OpenFreeMap) serving font glyphs; no auth data passes through it; same origin already used by the project's basemap styles |
</threat_model>

<verification>
1. Open map builder with multiple data layers
2. Toggle basemaps rapidly (click 4-5 different basemaps in quick succession)
3. Verify all data layers remain visible after the final basemap loads
4. Switch to blank basemap — verify zero CORS errors in browser console
5. Verify selected basemap shows a ring with visible offset from the thumbnail
6. Verify basemap grid slides open/closed smoothly (not instant toggle)
7. Verify labels toggle uses a Switch component matching the rest of the UI
</verification>

<success_criteria>
- Rapid basemap toggling never loses data layers
- Blank basemap produces no CORS glyph errors
- BasemapPicker grid animates open/closed
- Selected state has ring-offset for visual clarity
- Labels toggle uses Switch component
- All existing BasemapPicker tests pass
</success_criteria>

<output>
After completion, create `.planning/quick/260424-lqy-in-the-map-builder-when-toggling-the-bas/260424-lqy-SUMMARY.md`
</output>
