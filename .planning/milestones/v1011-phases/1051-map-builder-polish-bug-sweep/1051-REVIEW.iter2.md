---
phase: 1051-map-builder-polish-bug-sweep
reviewed: 2026-05-18T03:13:06Z
depth: standard
files_reviewed: 32
files_reviewed_list:
  - frontend/src/components/builder/BasemapGroupRow.tsx
  - frontend/src/components/builder/BasemapSublayerEditorScene.tsx
  - frontend/src/components/builder/BuilderMap.tsx
  - frontend/src/components/builder/FolderGroupRow.tsx
  - frontend/src/components/builder/SettingsEditorScene.tsx
  - frontend/src/components/builder/SublayerConfigIndicators.tsx
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx
  - frontend/src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx
  - frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx
  - frontend/src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx
  - frontend/src/components/builder/__tests__/SettingsEditorScene.test.tsx
  - frontend/src/components/builder/__tests__/SettingsEditorScene.widgets.test.tsx
  - frontend/src/components/builder/__tests__/SublayerConfigIndicators.test.tsx
  - frontend/src/components/builder/__tests__/UnifiedStackPanel.basemap-drag.test.tsx
  - frontend/src/components/builder/hooks/__tests__/use-builder-layers.delete.test.ts
  - frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.test.ts
  - frontend/src/components/builder/hooks/use-builder-layers.ts
  - frontend/src/components/builder/hooks/use-builder-save.ts
  - frontend/src/components/builder/hooks/use-layer-map-sync.ts
  - frontend/src/components/builder/layer-adapters/circle-adapter.ts
  - frontend/src/components/builder/layer-adapters/fill-adapter.ts
  - frontend/src/components/builder/layer-adapters/heatmap-adapter.ts
  - frontend/src/components/builder/layer-adapters/line-adapter.ts
  - frontend/src/components/builder/map-sync.ts
  - frontend/src/components/map/MapCoordReadout.tsx
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
  - frontend/src/pages/MapBuilderPage.tsx
  - frontend/src/types/api.ts
findings:
  critical: 4
  warning: 9
  info: 4
  total: 17
status: issues_found
---

# Phase 1051: Code Review Report

**Reviewed:** 2026-05-18T03:13:06Z
**Depth:** standard
**Files Reviewed:** 32
**Status:** issues_found

## Summary

Phase 1051 closes 11 user-reported Map Builder polish/bug items (BUG-01..03, UX-01..04, RESP-01..03) plus emergent findings. The implementation is broadly sound: BUG-01 (visibility toggle) has good defense-in-depth via `input.visible` honored at adapter-add time + companion-sweep, BUG-02 (delete-layer) follows the optimistic-update + rollback pattern from `handleBulkDelete`, BUG-03 (rename autofocus) uses requestAnimationFrame to outrun Radix's restoreFocus, and the UX-03 basemap drag wiring correctly threads `basemap_position` through the persistence + render pipelines.

However, the adversarial sweep surfaced **4 BLOCKER-tier defects** and **9 WARNINGs** worth fixing before tag. The most critical are:

- **CR-01**: `SublayerConfigIndicators` flags `line-dasharray` (a non-expression array) as "data-driven", producing false-positive UX indicators on every styled line layer.
- **CR-02**: `BasemapGroupRow` shows `cursor-not-allowed` during multi-selection but still fires `onSelectGroup` on row click — the visual signal lies about behavior.
- **CR-03**: `MapBuilderPage` `handleDragEnd` for basemap drag initializes `basemapConfig` from a default literal that **drops the existing `opacity` field** when `prev` is null, silently regressing master-opacity to 1.0 on first basemap reposition.
- **CR-04**: `heatmap-adapter.addLayers` always multiplies opacity by 0.8 at add-time but `syncPaint` reads `rawPaint['heatmap-opacity']` directly — a layer's persisted heatmap-opacity is overwritten on every add path (page load, render-mode swap), producing a visible visual flash and drift.

WARNINGs cluster around (a) ms-precision id generation (`group-${Date.now()}`) that can collide under bulk ops, (b) UX-incoherent disabled-state styling in `SettingsEditorScene.SliderRow`, (c) silent bulk-action-bar disappearance when any handler prop is undefined, and (d) the documented `autoCapturedMapIds` lifecycle limitation that cannot be reset without page reload.

Tests are thorough and follow established patterns (selective `vi.mock`, `importActual`, `afterEach` cleanup). i18n parity is intact across en/de/es/fr (955 lines each, all `indicators.*`, `basemapGroup.*`, `basemapSublayer.*`, `settings.*` keys present in all four locales).

---

## Critical Issues

### CR-01: SublayerConfigIndicators flags non-expression arrays as data-driven (false positive)

**File:** `frontend/src/components/builder/SublayerConfigIndicators.tsx:60`

**Issue:** The dataDriven detection uses `Object.values(paint).some((value) => Array.isArray(value))`. This treats **any** array value as a data-driven expression, but MapLibre paint properties can be plain numeric arrays for non-expression reasons:

- `line-dasharray: [2, 2]` — a plain dash pattern
- `circle-translate: [0, 0]` — a static offset pair
- `fill-translate: [10, -5]` — a static offset pair
- `icon-offset: [0, 0]` — symbol layer offset

Result: the lightning-bolt "data-driven" indicator (`Zap` icon) renders on every styled line layer that happens to have a dash pattern set, falsely advertising the layer as expression-styled. This defeats the whole UX-02 surface (indicators are meant to be a precise status surface, not a noisy approximation).

A correct expression detector checks that the array's first element is one of the MapLibre expression operators (`get`, `step`, `interpolate`, `case`, `match`, `has`, `coalesce`, `to-number`, `literal`, etc.) — or, more pragmatically, that `value[0]` is a string (every expression form starts with a string operator name; plain numeric arrays start with a number).

**Fix:**
```typescript
// Pragmatic detector: expressions start with a string operator name.
// Plain numeric arrays (line-dasharray, circle-translate, icon-offset) start with a number.
function isExpressionValue(value: unknown): boolean {
  return Array.isArray(value) && typeof value[0] === 'string';
}

// ...
const dataDriven = Object.values(paint).some(isExpressionValue);
```

This matches the same heuristic used elsewhere in the codebase (e.g., `lineGradientNeededFor` in `map-sync.ts:457-480` distinguishes object intent from array intent for the same reason).

---

### CR-02: BasemapGroupRow shows cursor-not-allowed during multi-selection but row click still selects

**File:** `frontend/src/components/builder/BasemapGroupRow.tsx:61-86, 78-79`

**Issue:** When `isMultiSelectionActive` is true, the basemap row applies `cursor-not-allowed` (line 78) signaling that the row is non-interactable in multi-select mode. However, the `onClick={handleRowClick}` on line 80 unconditionally calls `onSelectGroup(groupId)` regardless of `isMultiSelectionActive`. The keyboard handler at lines 81-86 does the same.

The grip listeners are correctly suppressed (line 122: `{...(isMultiSelectionActive ? {} : dragHandleProps.listeners)}`), but the row body click is not. A user who has a multi-selection going and accidentally clicks the basemap row will:

1. See `cursor-not-allowed` (indicating no action)
2. Trigger `onSelectGroup('basemap-group')`, which opens the basemap-group editor scene
3. The opened editor unmounts the BulkActionBar (which is gated on `!isSettingsOpen`)
4. The multi-selection set persists in state, but the user has been silently navigated away

This is a UX contract violation that will confuse users mid-bulk-operation. The visual signal must match the behavior — either suppress the row click during multi-selection or remove the `cursor-not-allowed` styling.

**Fix:**
```typescript
function handleRowClick(_e: React.MouseEvent) {
  // Multi-selection boundary: basemap row is non-interactable while a selection is in flight.
  // Mirror the grip-listener suppression at line 122 + the cursor-not-allowed signal at line 78.
  if (isMultiSelectionActive) return;
  onSelectGroup(groupId);
}

// And in onKeyDown:
onKeyDown={(e) => {
  if (isMultiSelectionActive) return;
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    onSelectGroup(groupId);
  }
}}
```

---

### CR-03: handleDragEnd basemap fallback object drops opacity field when basemapConfig is null

**File:** `frontend/src/pages/MapBuilderPage.tsx:687-699`

**Issue:** When the user drags the basemap row for the first time on a map that has never had its appearance customized, `layers.basemapConfig` is `null`. The drag handler does:

```typescript
layers.setBasemapConfig((prev) => ({
  ...(prev ?? {
    label_mode: 'full' as const,
    road_visibility: 'full' as const,
    boundary_visibility: 'full' as const,
    building_visibility: true,
    land_water_tone: 'default' as const,
  }),
  basemap_position: nextPosition,
}));
```

The fallback literal (when `prev === null`) is missing the `opacity` field. `MapBasemapConfig.opacity` is optional in the type, but `basemapGroup.opacity` (used by `BasemapGroupEditorScene` master-opacity slider at `MapBuilderPage.tsx:288`) reads `layers.basemapConfig?.opacity ?? 1`. After this drag, basemapConfig is no longer null — but `opacity` is still absent (not `undefined` via spread, just literally not in the object). On the surface this looks identical (both produce `?? 1`), so the visible state doesn't change immediately.

The real bug is in the **reverse path**: a user who has explicitly set master-opacity to 0.5 via the basemap editor (which writes `basemapConfig.opacity = 0.5`) and THEN drags the basemap row to flip position will hit `prev ?? {…}` where `prev` is the existing config (so `opacity: 0.5` is preserved). That works.

But the case where `basemapConfig` is shaped via `normalizeBasemapConfig(null, …)` (e.g. through `handleResetBasemapAppearance` → `setBasemapConfig(null)` → next interaction) reverts opacity to 1 silently. The user's "Reset appearance" loses any subsequent partial state.

More importantly, the default-literal object is **duplicated** between this drag handler (line 691-697) and `normalizeBasemapConfig` (called at line 624, 810). Drift between these two sources is a fragile maintenance trap — the next time a field is added to `MapBasemapConfig` (e.g., the planned `relief_contrast`), the drag-handler defaults will silently fall behind, producing inconsistent persisted shapes.

**Fix:** Reuse the existing normalizer instead of re-typing the default literal:
```typescript
import { normalizeBasemapConfig } from '@/lib/basemap-utils';

// ...
layers.setBasemapConfig((prev) => ({
  ...(prev ?? normalizeBasemapConfig(null, layers.showBasemapLabels)),
  basemap_position: nextPosition,
}));
```

This collapses the duplication, picks up the canonical defaults (including any future fields), and removes the drift surface.

---

### CR-04: heatmap-adapter.addLayers overwrites persisted heatmap-opacity on every add (visual flash + drift)

**File:** `frontend/src/components/builder/layer-adapters/heatmap-adapter.ts:44, 60`

**Issue:** The `addLayers` path computes:

```typescript
const heatmapOpacity = (opacity ?? 1) * 0.8;
// ...
paint: {
  // ...
  'heatmap-opacity': heatmapOpacity,
}
```

This ignores `rawPaint['heatmap-opacity']` entirely at add-time, hard-coding a 0.8 multiplier. Meanwhile `syncPaint` on line 91 reads from rawPaint:

```typescript
const storedOpacity = (rawPaint['heatmap-opacity'] as number) ?? 0.8;
map.setPaintProperty(layerId, 'heatmap-opacity', storedOpacity * (input.opacity ?? 1));
```

So a layer with persisted `heatmap-opacity: 0.5` will:

1. **On initial add** (page load, render-mode switch, basemap switch triggering re-add): get rendered at `master_opacity * 0.8` — discarding the user's saved 0.5.
2. **On any subsequent paint sync** (e.g., user adjusts another property): jump to `master_opacity * 0.5` — the correct value.

The user sees a visible flash on every re-add, and any code path that triggers add (e.g., `swapLayerOnMap` in `use-builder-layers.ts:851`) silently mutates the visible state. Worse, since paint sync sees the new value as a no-op (cache check), the layer can stay at the wrong opacity until any unrelated paint edit forces a sync.

Compare to the correct pattern already in the same file: `heatmap-radius`, `heatmap-weight`, `heatmap-intensity` all use `rawPaint['heatmap-radius'] ?? 30` (line 41-43) — read from rawPaint, fall back to default. Only `heatmap-opacity` is broken.

**Fix:**
```typescript
const storedHeatmapOpacity = (rawPaint['heatmap-opacity'] as number) ?? 0.8;
const heatmapOpacity = storedHeatmapOpacity * (opacity ?? 1);
```

This matches the syncPaint formula and respects persisted state on every code path.

---

## Warnings

### WR-01: group-${Date.now()} id collision under rapid bulk operations

**File:** `frontend/src/components/builder/hooks/use-builder-layers.ts:376, 550`

**Issue:** Both `handleCreateGroupWithLayer` (line 376) and `handleBulkGroup` (line 550) generate group IDs via `` `group-${Date.now()}` ``. `Date.now()` has millisecond precision, so two group creations within the same millisecond produce identical IDs. With React batching and async user input, the realistic-but-narrow collision window matters:

- User Cmd-clicks two loose layers, hits "Group" (bulk handler creates `group-X`)
- React batch boundary; same ms tick
- User immediately uses kebab → "Add to new group" on a third layer (single handler creates `group-X` again)
- Two groups now share the same ID; the second's children inherit the first's `parent_group_id`, scrambling the stack

This is unlikely under typical UX but trivially testable under stress (e.g., a Playwright spec firing two group creations back-to-back). The same pattern in v1009 used a counter + Date.now() suffix to avoid collisions; reverting to ms-only is a regression.

**Fix:** Use a monotonic counter combined with the timestamp, or use `crypto.randomUUID()` (available in all evergreen browsers):
```typescript
const groupId = `group-${crypto.randomUUID()}`;
```

---

### WR-02: BulkActionBar silently disappears when any of 5 handler props is undefined

**File:** `frontend/src/components/builder/UnifiedStackPanel.tsx:1106`

**Issue:** The BulkActionBar gate is:
```typescript
{!isSettingsOpen && selectedIds.size >= 2 && onBulkVisibility && onBulkOpacity && onBulkGroup && onBulkUngroup && onBulkDelete && (
  <BulkActionBar ... />
)}
```

If any of the five handler props is `undefined` (e.g., partial wiring in a future variant, a test setup that omits one handler, or refactor regression), the bar silently vanishes while selection state is non-empty. The user sees their multi-selection highlights but no toolbar — no error, no console warning, no toast. This is a debugging hazard: a single dropped prop kills the entire feature with zero feedback.

**Fix:** Validate handler presence with a `useEffect` in dev mode, or fall back to safe noop refs and rely on TypeScript (the props are typed as required `(ids: ...) => void | (ids: ..., opacity: number) => void` — undefined satisfies the optional shape but not the contract). Better: drop the runtime guards and make the props non-optional in `UnifiedStackPanelProps`:

```typescript
// In the interface:
onBulkVisibility: (ids: Set<string>) => void;  // remove `?`
onBulkOpacity: (ids: Set<string>, opacity: number) => void;
onBulkGroup: (ids: Set<string>) => void;
onBulkUngroup: (ids: Set<string>) => void;
onBulkDelete: (ids: Set<string>) => void;

// In the render:
{!isSettingsOpen && selectedIds.size >= 2 && (
  <BulkActionBar ... />
)}
```

This pushes the validation to TypeScript compile-time and removes the silent-disappear failure mode.

---

### WR-03: SettingsEditorScene SliderRow disabled state — only slider visually muted, label/value unchanged

**File:** `frontend/src/components/builder/SettingsEditorScene.tsx:41-61`

**Issue:** When the terrain SliderRow is disabled (no DEM layer bound), only the `<Slider>` element receives the `disabled` attribute and `cursor-not-allowed` is applied to the wrapper. The `<Label>` and the value span continue rendering at full opacity — they look interactive but aren't. The user has to physically attempt to drag the slider to discover it's locked.

The wrapper grid does get `cursor-not-allowed` (line 43), which is a partial fix, but visual hierarchy isn't adjusted: text-muted-foreground stays muted, the value span stays muted, the layout doesn't communicate disabled state.

**Fix:** Apply visual disabled treatment to the entire row:
```typescript
<div className={cn(
  'grid grid-cols-[110px_1fr_auto] gap-2 items-center',
  disabled && 'cursor-not-allowed opacity-50',
)}>
```

The opacity-50 is the standard shadcn disabled-state convention used elsewhere in the codebase.

---

### WR-04: MapCoordReadout reads mapRef.current directly during render (re-render dependency on mapReady)

**File:** `frontend/src/components/builder/BuilderMap.tsx:939`

**Issue:** `<MapCoordReadout map={mapRef.current} showScale />` passes a ref's `.current` directly as a prop. Refs don't trigger re-renders, so `MapCoordReadout` only sees the updated map instance when something else causes BuilderMap to re-render. This works today because `setMapReady(true)` (line 366) fires after `mapRef.current = map` (line 365), forcing a re-render in the same render cycle.

The hidden fragility: if a future refactor moves the `setMapReady(true)` call away from `mapRef.current = map`, or if the map is reassigned later (e.g., on style swap), MapCoordReadout will hold a stale prop. The pattern is also inconsistent with how `MapBuilderPage` consumes the same map (line 99: `const [mapInstance, setMapInstance] = useState`), which correctly uses state.

**Fix:** Promote `mapRef.current` to a `useState` mirror, similar to MapBuilderPage:
```typescript
const [mapInstance, setMapInstance] = useState<MaplibreMap | null>(null);

// In handleLoad:
mapRef.current = map;
setMapInstance(map);
setMapReady(true);

// In cleanup:
setMapInstance(null);

// In JSX:
<MapCoordReadout map={mapInstance} showScale />
```

This makes the dependency explicit and removes the implicit coupling to `mapReady`.

---

### WR-05: BasemapSublayerEditorScene zoom min/max constraints can lock user in inconsistent state

**File:** `frontend/src/components/builder/BasemapSublayerEditorScene.tsx:192-213`

**Issue:** The min/max zoom inputs use interdependent `max`/`min` HTML attributes:
- Min input: `max={Math.max(0, maxZoom - 1)}`
- Max input: `min={Math.min(22, minZoom + 1)}`

If a user wants to set both to a specific value (e.g., both to 10), they cannot: typing `minZoom=10` is rejected when `maxZoom=8` (constrained to `max=7`), and `maxZoom=10` is rejected when `minZoom=12` (constrained to `min=13`). The constraints assume the user always moves the bounds outward, never inward across a target.

Additionally, the `onChange` handler calls `onZoomChange(Number(e.target.value), maxZoom)` without validating that the new value satisfies the constraint. Since the input's `max` attribute is enforced by the browser, valid changes go through — but **paste** or **programmatic input** can bypass HTML constraints, producing inverted bounds (min > max) that the handler accepts and propagates to the consumer.

**Fix:** Validate in the handler and clamp inverted values; relax the HTML constraints to allow free entry with a footnote about the validation:
```typescript
onChange={(e) => {
  const newMin = Number(e.target.value);
  // Allow equal min/max (single zoom level); reject inversion only on commit.
  if (Number.isFinite(newMin) && newMin >= 0 && newMin <= 22) {
    onZoomChange(newMin, Math.max(newMin, maxZoom));
  }
}}
```

---

### WR-06: BuilderMap basemap fetch fallback shows raw URL string as styleValue

**File:** `frontend/src/components/builder/BuilderMap.tsx:170-177`

**Issue:** When the basemap style fetch fails, the catch block at line 170 sets `setBasemapNotice('style')` and calls `setMapStyle(styleValue)`. But `styleValue` is the raw URL string (a `string`, not a `StyleSpecification` object). The downstream `<MapGL mapStyle={mapStyle}>` receives a URL string, which @vis.gl/react-maplibre will attempt to fetch a second time. This is functional (MapLibre handles string mapStyle by fetching), but:

1. The retry happens through MapLibre's internal fetch (no `signal: controller.signal`), so a user navigating away mid-retry can't cancel it.
2. The previously-displayed "background black" placeholder style (set at line 140-150) gets replaced by whatever MapLibre's second fetch produces, which may flash a different placeholder.
3. If MapLibre's fetch also fails, the user sees a blank canvas with no error UI — the toast was already shown by `errorHandlerRef`, but that handler is gated on 5xx-only.

**Fix:** On fetch failure, keep the placeholder style instead of replacing it with the URL:
```typescript
.catch((error: unknown) => {
  if (controller.signal.aborted) return;
  if (import.meta.env.DEV) console.warn('[BuilderMap] Basemap style fetch failed:', error);
  if (!cancelled) {
    setBasemapNotice('style');
    // Keep the placeholder style — don't pass the raw URL through to MapLibre,
    // which triggers a second (uncancelable) fetch and may flash a different state.
  }
});
```

---

### WR-07: use-builder-save autoCapturedMapIds module guard cannot be reset in-app

**File:** `frontend/src/components/builder/hooks/use-builder-save.ts:154-156, 184-188`

**Issue:** Per the WR-03 comment at line 145, `autoCapturedMapIds` is intentionally write-only to preserve StrictMode safety. The documented trade-off is "server-side thumbnail deletion or admin re-trigger requires the user to reload the editor."

This is a legitimate trade-off, BUT the implementation amplifies the impact unnecessarily:
- The guard is keyed by `mapId` only — not by `mapId + thumbnail_url + auth_session`. If a user opens map A, captures a thumbnail, logs out, and re-logs in as a different user with access to map A but who needs a fresh thumbnail, the new session is blocked by the previous user's guard entry.
- The guard persists across React Query refetches that legitimately invalidate `hasThumbnail` (e.g., admin deletes thumbnail in another tab → next refetch returns `hasThumbnail: false` → auto-capture should fire → guard blocks it).

The "in-app recovery path is a hard reload" claim is correct only for the same user/session — cross-session leakage is undocumented.

**Fix:** Either (a) document that the guard intentionally outlives auth state and is only cleared by full page reload, or (b) tie the guard key to the current auth token's user id so cross-user sessions get fresh attempts:
```typescript
const autoCapturedKeys = new Set<string>();

function shouldAutoCapture(mapId: string, userId: string | null): boolean {
  const key = `${userId ?? 'anon'}:${mapId}`;
  if (autoCapturedKeys.has(key)) return false;
  autoCapturedKeys.add(key);
  return true;
}
```

---

### WR-08: BuilderMap structuralKey omits dataset_table_name from cluster signature

**File:** `frontend/src/components/builder/BuilderMap.tsx:700-709`

**Issue:** The structural key includes `${l.id}:${l.visible}:${l.dataset_id}` plus `clusterKey` for cluster mode. But it does NOT include `dataset_table_name`. Two layers can share the same `dataset_id` but render different `dataset_table_name` (e.g., a temp dataset rename mid-session), and the structural key won't invalidate. This is a low-likelihood race but the fix is one character; current implementation is fragile by omission.

More concerning: the structural key includes `clusterRadius` and `clusterMaxZoom` only for `render_mode === 'cluster'` but not for other modes that depend on `style_config.builder` (e.g., `heatmapRamp`, `heightColumn`). A change to `heatmapRamp` won't invalidate `structuralKey`, so the popup-clear effect on line 712 won't fire — popups stay open after heatmap ramp changes when they should arguably reset.

**Fix:** Either be explicit about what structuralKey covers (rename to `structuralLayerKey` and document scope) or include the relevant style_config fields:
```typescript
const structuralKey = useMemo(
  () => layers.map((l) => {
    const builder = l.style_config?.builder;
    const renderMode = l.style_config?.render_mode;
    const extras = renderMode === 'cluster'
      ? `:cl:${builder?.clusterRadius ?? ''}:${builder?.clusterMaxZoom ?? ''}`
      : renderMode === 'heatmap'
        ? `:hm:${builder?.heatmapRamp ?? ''}`
        : '';
    return `${l.id}:${l.visible}:${l.dataset_id}:${l.dataset_table_name}${extras}`;
  }).join(','),
  [layers],
);
```

---

### WR-09: BUG-03 test 21 uses fragile source-text assertion against Function.prototype.toString

**File:** `frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx:387-407`

**Issue:** Test 21 ("kebab onSelect for Rename no longer calls preventDefault()") reads the component's source via `Function.prototype.toString()` and asserts the rendered code doesn't contain `.preventDefault(`. This is fragile for three reasons:

1. **Minification**: production builds via Vite/Terser may inline `e.preventDefault()` into shorter forms (e.g., `e.preventDefault()` could survive but the regex `/\.preventDefault\(/` still matches). However, if the bundler renames `e` to a single character, the match still works — but if it inlines the call differently (e.g., function reference assignment), the test could miss the actual call.

2. **Coverage tooling**: Istanbul/V8 coverage instrumentation wraps function bodies in `cov_xxx.s[i]++` calls. The source-text inspection sees the instrumented form, not the original. False positives or negatives are possible.

3. **Pattern brittleness**: The regex `/\.preventDefault\(/` would NOT catch `e['preventDefault']()` or `(e.preventDefault)()` — both equivalent. A maintainer "fixing" the test by adding bracket notation would silently re-introduce the bug.

The intent (verify Radix's restoreFocus doesn't fire) is better expressed via a behavioral test that exercises the actual Radix DropdownMenu + onSelect flow. Test 19 already does this with the double-click path; test 21 is redundant defense that adds brittleness.

**Fix:** Delete test 21; rely on tests 19, 20, and 25 (rAF source assertion is also fragile but at least asserts presence of a specific token rather than absence). Or, replace with a behavioral test that drives the actual menu open + select flow even if it's flaky in jsdom (skip on jsdom, run on Playwright).

---

## Info

### IN-01: BasemapGroupRow.tsx has unused `rowName` parameter pattern for keys

**File:** `frontend/src/components/builder/BasemapGroupRow.tsx:59, 159-163`

**Issue:** Line 59 computes `const rowName = `Basemap · ${presetName}`;` for use in two `t()` calls (line 161, 211). However, line 195 separately renders the SAME string inline: `Basemap · {presetName}`. There are now THREE places where this string is constructed — drift between them is possible (e.g., one gets internationalized via a future `t()` key but others don't). Extract to a derived constant or single t() key.

**Fix:**
```typescript
const rowName = t('basemapGroup.rowName', {
  defaultValue: 'Basemap · {{name}}',
  name: presetName,
});

// Then reuse in display, aria-label, and kebab label.
```

---

### IN-02: TODO comments referencing Phase 1038 work that may not be tracked

**File:** `frontend/src/pages/MapBuilderPage.tsx:270, 466, 477, 845-857`

**Issue:** Multiple `TODO(Phase 1038)` markers exist for sublayer state persistence work. Phase 1038 shipped 2026-05-14 per MEMORY.md (v1008 milestone), so these TODOs are outdated — the work either was deferred (and needs to be tracked in a different phase) or completed (and the TODOs are dead text).

Per skill rules: TODOs should reference an open issue/phase, not a closed one. Audit these markers against the actual Phase 1038 deliverables and either remove or re-target.

**Fix:** Audit each TODO; remove if implemented, retarget to current phase/issue if deferred:
```typescript
// TODO(BUILDER-SUBLAYER-PERSIST): include sublayerState in the save payload via basemap_config round-trip.
```

---

### IN-03: SettingsEditorScene magic-number max for exaggeration slider (3.0)

**File:** `frontend/src/components/builder/SettingsEditorScene.tsx:121`

**Issue:** The exaggeration slider uses `max={3.0}` as a magic number. The map-sync `normalizeTerrainExaggeration` (map-sync.ts:47-50) clamps to 0-10 range, but the UI restricts to 0.1-3.0. The mismatch between UI clamp and backend clamp means values 3.1-10 are unreachable from the UI but accepted from the API/AI. Document or align.

**Fix:** Extract the cap as a named constant in a shared module, e.g.:
```typescript
export const TERRAIN_EXAGGERATION_UI_MAX = 3.0;
// And in the Slider:
max={TERRAIN_EXAGGERATION_UI_MAX}
```

Then either tighten `normalizeTerrainExaggeration` to match or document the intentional UI/backend asymmetry.

---

### IN-04: Comment-only references "WR-02" / "WR-03" without phase qualifier across files

**File:** `frontend/src/components/builder/hooks/use-builder-layers.ts:108-119`, `frontend/src/components/builder/hooks/use-builder-save.ts:144-154`, plus several other files

**Issue:** Many inline comments reference "WR-01", "WR-02", "WR-03", "CR-01", "CR-02", "SF-01..08", "B-01", "SP-XX" etc. without consistent phase qualifiers. A reader 6 months from now will not be able to find the context for "WR-02 (quick-260516-9g9 followup)" without grepping `.planning/`.

The phase ID prefix pattern (e.g., "Phase 1050-rev WR-01") is used in some places but not others. Standardize to always include the phase ID.

**Fix:** Codify a comment convention in CONTRIBUTING.md or skill rules:
```
// {PHASE-ID} {FINDING-ID}: <one-line context>
// Phase 1050-rev WR-01: imperative companion sweep — getSourceIdForLayer …
```

This is a style consistency issue, not a bug; consider adding a lint rule (e.g., regex check in pre-commit).

---

_Reviewed: 2026-05-18T03:13:06Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
