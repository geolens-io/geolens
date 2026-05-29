---
phase: 1154
type: UI-SPEC
status: ready
scope: incremental controls within existing RasterEditor + DEMEditorScene cleanup
---

# Phase 1154 — UI Design Contract

**Surface:** `RasterEditor` (LayerEditorPanel flyout, 380px) — an existing per-render-mode editor. This phase adds controls within the established COLORMAP/STRETCH section; it does NOT introduce a new surface. Design tokens, type scale, and OKLCH theme already match `frontend/src/index.css` (see `sketch-findings-geolens` skill). Reuse existing RasterEditor anatomy verbatim.

## Components

### 1. Stretch control gating (RASTER-STRETCH-03)
- **Today:** COLORMAP + STRETCH live in one `band_count === 1` block.
- **Contract:** Split. STRETCH `<Select>` (minmax / percentile / stddev) renders for `band_count >= 1` (single AND multi-band). COLORMAP `<Select>` stays `band_count === 1` only.
- **Multi-band view:** stretch selector visible; NO colormap row. Single-band view: both, unchanged order (colormap above stretch).

### 2. Percentile bounds inputs (RASTER-STRETCH-UI-01) — visible when `_stretch === 'percentile'`
- Two compact numeric inputs in a single row below the stretch select: **Low %** (`_pmin`, default 2) and **High %** (`_pmax`, default 98).
- Shape: shadcn input or `<input type="number">` styled `h-8 text-xs`, two-column row (`flex gap-2`), each with a small `<Label>` (`style.raster.pminLabel` / `style.raster.pmaxLabel`), `min={0} max={100} step={1}`.
- Validation (client): clamp/guard `0 <= pmin < pmax <= 100`; on invalid, do not write the paint key (or revert) — never emit an out-of-range value to the tile URL. (Backend also 422s, but the UI should not send garbage.)
- Empty/at-default: when both equal defaults (2/98), `buildColormapTileUrl` omits `pmin`/`pmax` (URL identical to today).

### 3. Sigma segmented control (RASTER-STRETCH-UI-01) — visible when `_stretch === 'stddev'`
- A 3-option segmented control (buttons 1 / 2 / 3) for `_sigma`, default 2, below the stretch select.
- Shape: row of 3 buttons (reuse the existing builder segmented pattern, e.g. the render-as / point render pills), `h-8 text-xs`, active state uses the established selected-token treatment. `<Label>` `style.raster.sigmaLabel`.
- At default (2): `buildColormapTileUrl` omits `sigma` (URL identical to today).

### 4. Stretch↔colormap hint (RASTER-STRETCH-UI-02) — copy only
- `<p>` below the stretch control, shown ONLY when `band_count === 1 && _stretch !== 'minmax' && _colormap !== 'gray'`.
- Copy (i18n `style.raster.stretchColormapHint`): "Stretch sets the input range for the colormap."
- Style: `text-[11px] leading-snug text-muted-foreground` (mirror the existing DEM `imageHint` muted-note treatment). `role="note"`. No interactivity, no behavior change.

### 5. CLEANUP — DEMEditorScene hillshade note removal (CLEANUP-01)
- Remove the unreachable `{isTerrainBound && (<p role="note" ...>hillshadeTerrainNote</p>)}` block at `DEMEditorScene.tsx:~280-288` and the 4 `demEditor.hillshadeTerrainNote` i18n strings. No visual replacement — the note never rendered in the natural flow, so removal is invisible to users. Leave the rest of the hillshade sub-section (SUN POSITION etc.) intact.

## States
- **minmax stretch:** no extra controls (current behavior).
- **percentile:** Low%/High% inputs appear. Changing them updates the tile URL (debounced via the existing paint-write coalescing).
- **stddev:** sigma 1/2/3 appears.
- **multi-band:** stretch + its sub-controls visible; colormap + hint absent.
- **single-band + non-gray colormap + non-minmax stretch:** hint visible.

## Accessibility
- All inputs have associated `<Label>`; segmented buttons have `aria-pressed`. Hint is `role="note"`. Maintain 4-locale i18n parity (`test:i18n` green) — add new keys to en/de/es/fr, remove `hillshadeTerrainNote` from all 4.

## Out of scope
- Histogram/visual preview, manual per-band raw min/max, colormap for multi-band.
