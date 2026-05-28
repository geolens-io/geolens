---
phase: 1136
slug: per-render-mode-editor-polish
status: draft
shadcn_initialized: true
preset: not applicable (existing project — components.json present)
created: 2026-05-27
---

# Phase 1136 — UI Design Contract

> Visual and interaction contract for Phase 1136: Per-Render-Mode Editor Polish.
> This phase introduces 5 editor-control surfaces inside existing LayerStyleEditor
> sub-components. No new design tokens, no new component variants, no new typographic
> decisions. No new shadcn blocks. All design decisions derive from existing tokens
> in `frontend/src/index.css`, the shadcn Slider + Select primitives already present,
> and the 1134-/1135-UI-SPEC precedent chain.

---

## Design System

| Property | Value | Source |
|----------|-------|--------|
| Tool | shadcn (via Radix primitives) | components.json present |
| Preset | existing project — no init required | components.json |
| Component library | Radix UI (via shadcn) | frontend/src/components/ui/ |
| Icon library | Lucide React | existing |
| Font (sans) | IBM Plex Sans Variable | frontend/src/index.css line 262 |
| Font (mono) | IBM Plex Mono | frontend/src/index.css line 263 |

---

## Spacing Scale

Standard 8-point scale in use project-wide. No new spacing values introduced in this phase.

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | Icon gaps, tight inline padding |
| sm | 8px | Slider row gap, control-row padding |
| md | 16px | Section padding (px-4), editor section body padding |
| lg | 24px | Not used in new surfaces |
| xl | 32px | Not used in new surfaces |
| 2xl | 48px | Not used in new surfaces |
| 3xl | 64px | Not used in new surfaces |

Exceptions for this phase: none. Every Tailwind value in new code MUST be a multiple of 4
(`px-2`, `px-4`, `py-1`, `py-2`, `gap-2`, `gap-4`). Prohibited: `*-0.5`, `*-1.5`,
`*-2.5`, `mt-0.5`, `space-y-1.5`.

---

## Typography

No new sizes or weights introduced in this phase. All type from the existing scale.
Inherited from 1135-UI-SPEC verbatim.

| Role | Size | Weight | Line Height | Usage |
|------|------|--------|-------------|-------|
| Body / label | 14px (`text-sm`) | 400 | 1.43 | Section body text, default editor labels |
| Micro / caption | 12px (`text-xs`) | 400 | 1.33 | Slider value readouts, dropdown labels, section headings (see note) |
| Section cap label | 10px (`text-[10px]`) | 600 | implicit | `STROKE` / `PRESET` / `APPEARANCE` caps (existing `BasemapSublayerEditorScene` pattern) |
| Muted hint | 12px (`text-xs`) | 400 | 1.33 | FillEditor range hint, basemap section copy |

**Note on section headings:** The existing `BasemapSublayerEditorScene` uses
`text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground` for section
cap labels. RasterEditor new sections use the same pattern.

**Rule:** No new `text-*` class beyond this set is introduced in this phase.

---

## Color

All tokens from `frontend/src/index.css`. No new tokens.

| Role | Token | Value (light mode) | Usage |
|------|-------|--------------------|-------|
| Dominant (60%) | `--background` | `oklch(0.985 0.003 85)` | Editor panel bg, section bg |
| Secondary (30%) | `--muted` / `--card` | `oklch(0.97 0.003 85)` | Slider track bg, section hover, range-hint container |
| Accent (10%) | `--primary` | `oklch(0.55 0.18 250)` | See reserved-for list below |
| Destructive | `--destructive` | `oklch(0.577 0.245 27.325)` | Not used in this phase |
| Muted foreground | `--muted-foreground` | `oklch(0.45 0.005 250)` | Section cap labels, slider value readouts, control labels, range hint text |
| Warning | `--warning` | `oklch(0.75 0.15 85)` | Existing FillEditor height-column-missing warning (unchanged) |

**Accent (`--primary` OKLCH blue) reserved for (this phase, exhaustive additions):**
1. Slider thumb (`border-primary bg-background` — existing shadcn Slider primitive)
2. Slider fill track (`bg-primary` — existing shadcn Slider primitive)
3. Active basemap preset card ring (`ring-2 ring-primary ring-offset-2` — existing BasemapPicker pattern)
4. Focus ring (`--ring`) — existing

**Accent NOT used for:** slider label text, dropdown trigger borders, Reset button (use
`variant="ghost"`), range hint text, `line-cap`/`line-join` dropdown containers.

---

## Surface 1: RasterEditor — 4 Sliders + Reset (EDITOR-RASTER-01..04)

Current state: stub rendering `text-xs text-muted-foreground` placeholder string.
Target state: 4 slider rows + collapsible Reset, mirroring `BasemapSublayerEditorScene`
section anatomy exactly.

### Slider Shape (all 4 sliders use this pattern)

The existing `grid grid-cols-[auto_1fr_auto] gap-2 items-center` pattern from
`BasemapSublayerEditorScene` (stroke-width row) is the precise template to follow.

```
[ Label (w-28 shrink-0) ] [ <Slider /> ] [ value display (w-12 text-end) ]
```

| Property | Value | Rationale |
|----------|-------|-----------|
| Row container | `grid grid-cols-[auto_1fr_auto] gap-2 items-center` | Matches existing BasemapSublayerEditorScene slider row |
| Label | `text-xs text-muted-foreground w-28 shrink-0` (wider than BSE's `w-20` to fit longer labels) | Avoids wrapping on "Saturation" / "Hue-rotate" |
| Slider component | `<Slider>` from `frontend/src/components/ui/slider.tsx` | Existing shadcn primitive |
| Value display | `text-xs tabular-nums text-muted-foreground w-12 shrink-0 text-end` | Matches BSE pattern |

### Slider Ranges and Defaults

MapLibre raster paint property defaults (from `RASTER_PAINT_DEFAULTS` in `raster-adapter.ts`):

| Control | MapLibre property | min | max | step | Default | Value format |
|---------|-------------------|-----|-----|------|---------|--------------|
| Brightness | `raster-brightness-min` / `raster-brightness-max` — presented as single "Brightness" control mapped to `raster-brightness-min` (low end); `raster-brightness-max` defaults to 1 and is not exposed as a separate slider for simplicity | 0 | 1 | 0.05 | 0 (min) | `"0.00"` (2 decimal places) |
| Contrast | `raster-contrast` | -1 | 1 | 0.05 | 0 | `"0.00"` (2 decimal places) |
| Saturation | `raster-saturation` | -1 | 1 | 0.05 | 0 | `"0.00"` (2 decimal places) |
| Hue-rotate | `raster-hue-rotate` | 0 | 360 | 1 | 0 | `"0°"` (integer + degree symbol) |

**Brightness design note:** The MapLibre `raster-brightness-min` + `raster-brightness-max`
pair models a contrast-stretch range. Exposing both as separate sliders is noisy. Phase 1136
exposes a single "Brightness" slider that maps to `raster-brightness-min` (the lower bound),
keeping `raster-brightness-max` at its default of 1. This matches the common "brightness"
mental model (0 = darkest, 1 = brightest). The CONTEXT.md spec says "brightness/contrast each
0–1"; this spec overrides that with the MapLibre-accurate range above.

### Section Structure

RasterEditor renders 4 sections matching `BasemapSublayerEditorScene` anatomy:

```
┌──────────────────────────────────────┐
│ APPEARANCE  (cap label)              │
│   Brightness   [===●====]    0.00    │
│   Contrast     [====●===]    0.00    │
│   Saturation   [====●===]    0.00    │
│   Hue-rotate   [====●===]    0°      │
├──────────────────────────────────────┤
│ ▶ RESET  Reset to defaults           │  ← collapsible, closed by default
│     [Reset to defaults] button       │
└──────────────────────────────────────┘
```

Section container: `px-4 py-2` with `space-y-3` between slider rows (matching BSE STROKE
section spacing).

Cap label: `text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2`
(exact match to BSE cap label).

### Reset Button

The Reset control follows the existing BSE collapsible pattern exactly:

- Collapsible trigger: `<Collapsible>` + `<CollapsibleTrigger>` with `border-b` bottom border
- Trigger row: `flex items-center gap-2 px-4 py-2 hover:bg-[var(--surface-2,...)] border-b`
- Collapsed hint text: `ml-auto text-xs text-muted-foreground` — "Reset to defaults"
- Inside the collapsible content: a single `Button variant="ghost" className="w-full"` with
  label "Reset to defaults"
- No confirm-step needed for Reset (non-destructive — restores to MapLibre defaults)
- Behavior: clicking Reset sets all 4 sliders back to `RASTER_PAINT_DEFAULTS` values
  (brightness-min 0, contrast 0, saturation 0, hue-rotate 0) and calls the corresponding
  `onPaintProp` for each in a single batched dispatch via `coalesceFrame`

**Reset button position:** Anchored as the last section in RasterEditor, after the 4 sliders.

### Debounce Contract

All 4 sliders route through `coalesceFrame` (v1010 `raf-coalesce.ts`):
- opacity-class properties (brightness): 100ms debounce
- color+filter-class properties (contrast, saturation, hue-rotate): 200ms debounce
- No direct `map.setPaintProperty` callsites in the editor component (Pitfall #9)

### Interaction Contract

- Each slider calls `onPaintProp(key, value)` via its `onValueChange` handler
- Value display updates synchronously (uncontrolled display tied to local `value` state)
- Slider `aria-label` = translated property name (e.g., "Brightness")
- Slider `aria-valuetext` = formatted value string (e.g., "0.50" or "45°")

---

## Surface 2: LineEditor — line-cap / line-join Dropdowns (EDITOR-LINE-01, EDITOR-LINE-02)

Current state: `LineEditor.tsx` has no `line-cap` or `line-join` control. Both are hardcoded
to `round` in `line-adapter.ts addLayers` layout block.

Target state: two `<Select>` dropdowns inserted below the existing dash-pattern row, using
the existing shadcn Select primitive already imported in `FillEditor.tsx`.

### Dropdown Shape

Use the existing Select usage pattern from `FillEditor.tsx` as the template:
`<SelectTrigger className="h-8 text-xs w-36">` with `size` at default (h-8 via className).

**IMPORTANT:** Both `line-cap` and `line-join` are MapLibre **layout** properties, NOT paint
properties. They route through `onLayoutChange(layer.id, { 'line-cap': value, ...})`. Do NOT
route through `onPaintProp`. Adapter extends `LINE_OWNED_LAYOUT_PROPERTIES`.

### line-cap Dropdown

```
[ Cap  ] [ <Select w-36 h-8 text-xs> ]
```

| Property | Value |
|----------|-------|
| Row container | `flex items-center justify-between gap-2` |
| Label | `text-xs text-muted-foreground` — "Cap" |
| Select trigger | `<SelectTrigger className="h-8 text-xs w-36">` |
| Default value | `"round"` (MapLibre default) |
| Options | `butt` → "Butt", `round` → "Round", `square` → "Square" |
| Placement in LineEditor | After the dash-pattern row, before line-join |

### line-join Dropdown

```
[ Join ] [ <Select w-36 h-8 text-xs> ]
```

| Property | Value |
|----------|-------|
| Row container | `flex items-center justify-between gap-2` |
| Label | `text-xs text-muted-foreground` — "Join" |
| Select trigger | `<SelectTrigger className="h-8 text-xs w-36">` |
| Default value | `"miter"` (MapLibre default) |
| Options | `bevel` → "Bevel", `round` → "Round", `miter` → "Miter" |
| Placement in LineEditor | After the cap dropdown |

### Section Heading

Insert a section heading between the dash-pattern row and the cap/join dropdowns:

```tsx
<div className="text-xs font-medium mt-2">{t('style.lineEnds', { defaultValue: 'Line ends' })}</div>
```

This mirrors the existing `<div className="text-xs font-medium">{t('style.pattern')}</div>`
heading above the dash row.

### Read Source for Current Value

Current `line-cap`/`line-join` values are stored in `layer.layout` (not `layer.paint`). Read
with: `(layer.layout as Record<string,unknown>)?.['line-cap'] as string ?? 'round'`.

---

## Surface 3: FillEditor — 3D Extrusion Range Hint (EDITOR-FILL-04)

Current state: when `currentHeightCol` is set, FillEditor shows the height column selector
and a missing-column warning. No range hint exists.

Target state: when `currentHeightCol` is non-empty AND `dataset_sample_values` contains
data for that column, render a range hint below the height column selector.

### When to Render

Show the range hint when ALL of the following are true:
1. `isPolygon === true`
2. `currentHeightCol` is a non-empty string
3. `layer.dataset_sample_values?.[currentHeightCol]` is an array with length > 0

Hide silently (no placeholder, no "data unavailable" message) when conditions are not met
— the selector remains; only the hint is absent.

### Range Computation

`dataset_sample_values[currentHeightCol]` is typed as `unknown[]`. Treat each element as a
number (filter `typeof v === 'number'`). Derive:
- `min` = `Math.min(...numericValues)`
- `max` = `Math.max(...numericValues)`
- `count` = `numericValues.length`

If `numericValues.length === 0` after filtering, hide the hint.

### Visual Spec

```
Range: 12–340, 1,247 features
```

| Property | Value |
|----------|-------|
| Position | Immediately below the height column `<Select>` row, inside the same `isPolygon && currentHeightCol` guard block |
| Container | `text-xs text-muted-foreground` (no border, no background — inline text) |
| Format | `Range: {min}–{max}, {count.toLocaleString()} features` |
| Number format (min/max) | Integer if the values are whole numbers; 1 decimal place if fractional (`Number.isInteger(v) ? v.toString() : v.toFixed(1)`) |
| Separator | En-dash `–` (U+2013) between min and max |
| Count format | `toLocaleString()` — 1247 renders as `1,247` in en-US |
| Aria | No special aria needed — the text is descriptive, not interactive |

**Solution-path requirement:** the hint always shows data derived from actual sample values.
When sample values are absent (null, empty, or non-numeric), the hint is simply hidden — no
"Range: N/A" or "No data available" text. This satisfies the D1 solution-path rule: there
is nothing to action on an absent hint.

---

## Surface 4: BasemapGroupEditorScene — "No basemap" Preset (EDITOR-BASEMAP-02)

Current state: `BasemapGroupEditorScene` renders a `grid-cols-2` preset card grid from
`presets[]`. The "blank" basemap already has first-class support in `BasemapPicker.tsx`
(the flat dropdown picker used in non-editor contexts), where it uses `BLANK_BASEMAP_ID =
'blank'` and renders a blank thumbnail via `basemapThumbnail('blank')`.

The `BasemapGroupEditorScene` preset card grid does NOT yet include a "No basemap" entry.

Target state: "No basemap" appears as the FIRST entry in the preset card grid, before all
provider presets.

### Sentinel Value

`basemap_id: 'blank'` — the existing `BLANK_BASEMAP_ID` constant from
`frontend/src/lib/basemap-utils.ts`. No new sentinel value; reuse existing.

### Preset Card Shape (mirrors existing cards)

The existing card button class:
```
'flex flex-col rounded-[var(--radius-md)] border p-2 text-left transition-colors',
isActive
  ? 'border-primary shadow-[0_0_0_1px_var(--primary)]'
  : 'border-[var(--border)] hover:bg-[var(--surface-2)]',
```

"No basemap" uses the same card button class. Active state uses `border-primary shadow`.

| Property | Value |
|----------|-------|
| Card label | "No basemap" — from i18n key `basemapGroup.noBasemap` |
| Provider sub-label | None (no provider for blank) |
| Thumbnail | `basemapThumbnail('blank')` — returns the existing inline SVG data-URI (checkered pattern) from `basemap-utils.ts:BLANK_THUMBNAIL` |
| Thumbnail height | `style={{ height: '56px' }}` — same as all other preset cards |
| Position in grid | First cell (index 0) — before all provider presets |
| `aria-pressed` | Not applicable (card uses `onClick` + active border; no explicit `aria-pressed`) |

### Thumbnail Image Alt Text

```tsx
<img
  src={basemapThumbnail('blank')}
  alt=""
  aria-hidden="true"
  className="w-full rounded-[var(--radius-sm)] object-cover"
  style={{ height: '56px' }}
/>
```

`alt=""` with `aria-hidden="true"` — the card button itself carries the label text; the
thumbnail is decorative.

### Persistence Round-Trip

`basemap_id: 'blank'` persists through save → reload → viewer/embed. The existing
`basemap-utils.ts` function `hasBasemap(id)` already gates to `false` for `BLANK_BASEMAP_ID`,
so the basemap layer init path correctly skips style loading for the blank preset.

---

## Surface 5: DETAIL LEVEL Stays-Gone Regression Pin (EDITOR-BASEMAP-03)

This is a pure-negative-control test deliverable. No UI change. The surface is already
absent from `BasemapSublayerEditorScene` (confirmed PASS in Phase 1133 audit WALK-B-02).

The regression pin asserts this stays absent.

### What to Pin

File: `frontend/src/components/builder/__tests__/BasemapSublayerEditor.test.tsx` (create if
it does not exist).

Test: render `BasemapSublayerEditorScene` with a full props fixture. Assert that no element
with text matching `/detail level/i` is present in the rendered output.

```tsx
// Positive-form regression pin: DETAIL LEVEL surface stays gone (v1011 INV-01)
it('does not render any DETAIL LEVEL control', () => {
  render(<BasemapSublayerEditorScene {...fixture} />);
  expect(screen.queryByText(/detail level/i)).not.toBeInTheDocument();
});
```

This is the only deliverable for EDITOR-BASEMAP-03. No UI code changes.

---

## Interaction Contracts Summary

| Surface | Trigger | Adapter path | Timing |
|---------|---------|--------------|--------|
| RasterEditor brightness slider | `onValueChange` | `onPaintProp('raster-brightness-min', v)` → RasterAdapter OWNED_PAINT_PROPERTIES | 100ms `coalesceFrame` |
| RasterEditor contrast slider | `onValueChange` | `onPaintProp('raster-contrast', v)` → RasterAdapter | 200ms `coalesceFrame` |
| RasterEditor saturation slider | `onValueChange` | `onPaintProp('raster-saturation', v)` → RasterAdapter | 200ms `coalesceFrame` |
| RasterEditor hue-rotate slider | `onValueChange` | `onPaintProp('raster-hue-rotate', v)` → RasterAdapter | 200ms `coalesceFrame` |
| RasterEditor Reset button | click | calls `onPaintProp` for all 4 defaults in batched `coalesceFrame` | immediate (single frame) |
| LineEditor line-cap select | `onValueChange` | `onLayoutChange(layer.id, { 'line-cap': v })` → LineAdapter OWNED_LAYOUT | synchronous |
| LineEditor line-join select | `onValueChange` | `onLayoutChange(layer.id, { 'line-join': v })` → LineAdapter OWNED_LAYOUT | synchronous |
| FillEditor range hint | render only | read from `layer.dataset_sample_values[currentHeightCol]` | static derivation at render time |
| BasemapGroupEditorScene "No basemap" | click | `onSwapBasemap('blank')` | synchronous |

---

## Copywriting Contract

| Element | Copy | i18n Key |
|---------|------|----------|
| RasterEditor section cap | "APPEARANCE" | `builder:style.rasterAppearanceSection` |
| RasterEditor: Brightness label | "Brightness" | `builder:style.rasterBrightness` |
| RasterEditor: Contrast label | "Contrast" | `builder:style.rasterContrast` |
| RasterEditor: Saturation label | "Saturation" | `builder:style.rasterSaturation` |
| RasterEditor: Hue-rotate label | "Hue-rotate" | `builder:style.rasterHueRotate` |
| RasterEditor reset trigger hint | "Reset to defaults" | `builder:style.rasterResetHint` |
| RasterEditor reset button | "Reset to defaults" | `builder:style.rasterResetAction` |
| LineEditor section heading | "Line ends" | `builder:style.lineEnds` |
| LineEditor cap label | "Cap" | `builder:style.lineCap` |
| LineEditor cap option: butt | "Butt" | `builder:style.lineCapButt` |
| LineEditor cap option: round | "Round" | `builder:style.lineCapRound` |
| LineEditor cap option: square | "Square" | `builder:style.lineCapSquare` |
| LineEditor join label | "Join" | `builder:style.lineJoin` |
| LineEditor join option: bevel | "Bevel" | `builder:style.lineJoinBevel` |
| LineEditor join option: round | "Round" | `builder:style.lineJoinRound` |
| LineEditor join option: miter | "Miter" | `builder:style.lineJoinMiter` |
| FillEditor range hint | "Range: {min}–{max}, {count} features" | `builder:style.extrusionRange` (interpolated) |
| BasemapGroupEditorScene no-basemap label | "No basemap" | `builder:basemapGroup.noBasemap` |

**Note on empty states:**
- FillEditor range hint: hidden when data absent — no copy needed. This is correct per D1
  solution-path rule (there is nothing for the user to action without the data).
- RasterEditor: no empty state — sliders always show for raster layers.
- LineEditor: no empty state — dropdowns always show for line layers.
- BasemapGroupEditorScene: "No basemap" is a preset entry, not an empty state.

**Destructive actions in this phase:** none. The RasterEditor Reset restores to MapLibre
defaults (non-destructive, reversible). No confirmation modal or dialog required.

**i18n parity required in:** en, de, es, fr (same 4-language requirement as all builder
strings in prior phases).

---

## Component Inventory

| Component | File | Type | Modification |
|-----------|------|------|-------------|
| `RasterEditor` | `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx` | Modify | Replace stub with 4 slider rows + Reset collapsible |
| `LineEditor` | `frontend/src/components/builder/LayerStyleEditor/LineEditor.tsx` | Modify | Add "Line ends" section heading + line-cap Select + line-join Select |
| `FillEditor` | `frontend/src/components/builder/LayerStyleEditor/FillEditor.tsx` | Modify | Add range hint below height column selector |
| `BasemapGroupEditorScene` | `frontend/src/components/builder/BasemapGroupEditorScene.tsx` | Modify | Add "No basemap" as first entry in preset card grid |
| `raster-adapter.ts` | `frontend/src/components/builder/layer-adapters/raster-adapter.ts` | Modify | Extend `RASTER_OWNED_PAINT_PROPERTIES` (or equivalent export) to expose the 4 new properties for `syncPaint` routing |
| `line-adapter.ts` | `frontend/src/components/builder/layer-adapters/line-adapter.ts` | Modify | Add `LINE_OWNED_LAYOUT_PROPERTIES` (or extend existing) to include `line-cap` and `line-join`; add `syncLayout` path |

Components **read-only** in this phase (verified, not modified):
- `BasemapSublayerEditorScene.tsx` — DETAIL LEVEL already absent; no code change, only regression pin added in tests
- `BasemapPicker.tsx` — already includes `BLANK_BASEMAP_ID` in options list; the picker is separate from the `BasemapGroupEditorScene` preset grid. No change.
- `slider.tsx` — existing shadcn primitive, no modification
- `select.tsx` — existing shadcn primitive, no modification

---

## Layout Invariants Inherited from 1134-UI-SPEC (unchanged)

| Invariant | Contract |
|-----------|----------|
| INV-01 | NavigationControl stays `top-left`. Not touched by editor polish. |
| INV-02 | MapCoordReadout `top-2 right-14`. Not touched by editor polish. |
| INV-03 | Every `<SheetContent>` in builder canvas uses `showCloseButton={false}`. No new Sheet instances in this phase. |

---

## Regression Test Contracts

Named test files the executor MUST create or extend. Each ties to a specific requirement.

| Test File | Requirement | What to Pin |
|-----------|-------------|-------------|
| `frontend/src/components/builder/LayerStyleEditor/__tests__/RasterEditor.test.tsx` | EDITOR-RASTER-01..04 | (1) All 4 sliders render; (2) each slider `onValueChange` calls `onPaintProp` with the correct MapLibre key; (3) Reset button calls `onPaintProp` 4× with `RASTER_PAINT_DEFAULTS` values; (4) save→reload round-trip: serialize → deserialize → all 4 values match |
| `frontend/src/components/builder/LayerStyleEditor/__tests__/LineEditor.test.tsx` | EDITOR-LINE-01/02 | (1) line-cap Select renders with options butt/round/square; (2) selecting "square" calls `onLayoutChange(layer.id, { 'line-cap': 'square' })`; (3) line-join Select renders with options bevel/round/miter; (4) selecting "bevel" calls `onLayoutChange(layer.id, { 'line-join': 'bevel' })`; (5) default values read from `layer.layout['line-cap']` / `layer.layout['line-join']` |
| `frontend/src/components/builder/LayerStyleEditor/__tests__/FillEditor.test.tsx` | EDITOR-FILL-04 | (1) With `currentHeightCol="height"` and `dataset_sample_values={{ height: [10, 50, 200] }}`: range hint renders "Range: 10–200, 3 features"; (2) With `dataset_sample_values: null`: range hint NOT present; (3) With empty array `dataset_sample_values={{ height: [] }}`: range hint NOT present |
| `frontend/src/components/builder/__tests__/BasemapSublayerEditor.test.tsx` | EDITOR-BASEMAP-03 | Positive-form: `queryByText(/detail level/i)` returns null after rendering `BasemapSublayerEditorScene` with full props fixture |
| `frontend/src/components/builder/__tests__/BasemapGroupEditorScene.test.tsx` | EDITOR-BASEMAP-02 | (1) "No basemap" entry renders as first preset card; (2) clicking it calls `onSwapBasemap('blank')`; (3) when `activePresetId === 'blank'`, the "No basemap" card has active ring classes |

**Style-JSON round-trip pin (Pitfall #2):**
Each new adapter property extension must include a test that:
1. Sets the property via `onPaintProp` / `onLayoutChange`
2. Serializes to JSON (e.g., `JSON.stringify(layer.paint)` / `JSON.stringify(layer.layout)`)
3. Deserializes and passes through the adapter's `syncPaint` / `syncLayout`
4. Asserts that the rendered MapLibre property equals the original value (no property leaked
   or dropped)

**Pitfall #9 grep guard:**
`grep -nE 'map\.setPaintProperty|map\.setLayoutProperty' frontend/src --include="*.ts*" -r`
must return zero new hits outside `layer-adapters/` and `map-sync.ts`. The executor must
run this grep after completing all code changes and confirm no regressions.

---

## Registry Safety

No new shadcn blocks or third-party registries introduced in this phase.

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | Slider, Select — already present in project | not required — no new blocks |
| Third-party | none | not applicable |

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending

---

## Pre-Populated From

| Source | Decisions Used |
|--------|---------------|
| 1136-CONTEXT.md | 6 (Pitfall #9 no-setPaintProperty, Pitfall #2 save→reload, INV-01 DETAIL LEVEL stays gone, line-cap/join LAYOUT not paint, no new contracts, coalesceFrame debounce) |
| 1133-BUILDER-WALKTHROUGH-AUDIT.md | 9 (WALK-R-01..04, WALK-L-01/02, WALK-F-03, WALK-B-01, WALK-B-02) |
| 1135-UI-SPEC.md | 7 (design system, spacing scale, typography table, color table + accent reserved-for, layout invariants INV-01..03, SpacingScale prohibitions) |
| 1134-UI-SPEC.md | 4 (OKLCH primary token, SliderRow anatomy, FillEditor Select trigger pattern, SheetContent INV-03) |
| REQUIREMENTS.md | 9 (EDITOR-RASTER-01..04, EDITOR-LINE-01/02, EDITOR-FILL-04, EDITOR-BASEMAP-02/03) |
| frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx | 1 (current stub confirmed) |
| frontend/src/components/builder/LayerStyleEditor/LineEditor.tsx | 2 (existing SliderRow + dash pattern; no cap/join present) |
| frontend/src/components/builder/LayerStyleEditor/FillEditor.tsx | 3 (Select trigger pattern `h-8 text-xs w-36`, height column guard, dataset_column_info warning pattern) |
| frontend/src/components/builder/BasemapGroupEditorScene.tsx | 4 (preset card grid anatomy, active ring classes, thumbnail `style={{ height: '56px' }}`, footer button layout) |
| frontend/src/components/builder/BasemapSublayerEditorScene.tsx | 5 (slider row grid pattern, section cap label pattern, Reset collapsible pattern, INV-01 comment confirmed) |
| frontend/src/components/builder/BasemapPicker.tsx | 2 (BLANK_BASEMAP_ID usage, `blankEntry` pattern confirms 'blank' sentinel is already used in parallel picker) |
| frontend/src/lib/basemap-utils.ts | 2 (BLANK_BASEMAP_ID = 'blank', BLANK_THUMBNAIL inline SVG data-URI already defined) |
| frontend/src/components/builder/layer-adapters/raster-adapter.ts | 3 (RASTER_PAINT_DEFAULTS exact values, RASTER_PAINT_PROPERTIES list, syncPaint routing confirmed) |
| frontend/src/types/api.ts | 1 (dataset_sample_values: Record<string, unknown[]> | null) |
| frontend/src/components/ui/slider.tsx | 1 (Slider API: value, min, max, step, onValueChange, aria-label, aria-valuetext) |
| frontend/src/components/ui/select.tsx | 1 (SelectTrigger size="sm" for h-8; className override for width + text-xs) |
| sketch-findings-geolens SKILL.md | 2 (no new tokens invariant, 380px flyout confirmed) |
| User input | 0 (discuss phase skipped; all decisions from upstream artifacts) |
