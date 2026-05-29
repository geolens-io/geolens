---
audit: Builder Label & Raster/DEM QA Walkthrough
milestone: v1033 (proposed)
date: 2026-05-29
maps:
  - { id: 8dd6a129-8eb0-4ba9-b421-716c83b160dd, name: "Adirondack High Peaks — 3D Relief", visibility: private, layers: 9 }
  - { id: c39be324-6815-40e5-8143-00a2723827b2, name: "Adirondack High Peaks — Terrain & Trails", visibility: public, layers: 6 }
method: live Playwright MCP (orchestrator-driven) on localhost:8080, admin auth
---

# Builder Label & Raster/DEM QA — Walkthrough Audit (v1033)

Severity legend: **P0** = broken/data-loss/blocks core authoring · **P1** = wrong behavior or missing wiring a user will hit · **P2** = polish/enhancement.

## Map composition (from DB `catalog.map_layers`)

**Map A — ADK 3D Relief** (pitch 60, map-level `terrain_config.enabled=true`, source DEM `2931c262`):
| # | layer | type | visible | render_mode | labels |
|---|-------|------|---------|-------------|--------|
| 0 | ADK 46er peaks | vector (point) | ✓ | — | ✓ |
| 1 | Hiking trails | vector (line) | ✓ | — | — |
| 2 | NHD streams and rivers | vector (line) | ✗ | — | — |
| 3 | Blue Line (APA boundary) | vector (line) | ✗ | — | — |
| 4 | NHD lakes and ponds | vector (poly) | ✗ | — | — |
| 5 | Land classification | vector (poly) | ✓ | — | — |
| 6 | DEM hillshade (1m) | raster | ✗ | terrain | — |
| 7 | TNM/NY Orthos aerial | raster | ✓ | — | — |
| 8 | 3D terrain (DEM) | raster | ✓ | terrain | — |

**Map B — Terrain & Trails** (pitch 35, map-level `terrain_config.enabled=false`):
| # | layer | type | visible | render_mode |
|---|-------|------|---------|-------------|
| 2 | NHD streams and rivers | vector (line) | ✓ | — |
| 3 | Blue Line (APA boundary) | vector (line) | ✓ | — |
| 4 | NHD lakes and ponds | vector (poly) | ✓ | — |
| 5 | Land classification | vector (poly) | ✓ | — |
| 6 | DEM hillshade (1m) | raster | ✓ | hillshade |
| 7 | TNM/NY Orthos aerial | raster | ✓ | — |

---

## Root-cause family (validated in code BEFORE the live walkthrough)

The `RENDER_MODES` allowlist is the single choke point behind the terrain bug *and* the raster render-as save-revert bug.

- `frontend/src/lib/normalize-style-config.ts:92` — `RENDER_MODES = new Set(['heatmap','hillshade','symbol','arrow','cluster'])` — **omits `'terrain'` and `'image'`**.
- `normalizeRenderMode()` (`:174-188`) returns `undefined` for any value not in that set → `'terrain'` is discarded on every read.
- `frontend/src/types/api.ts:863` — `render_mode?: 'heatmap' | 'hillshade' | 'symbol' | 'arrow' | 'cluster'` — union also omits `'terrain'`/`'image'`.
- `DEMEditorScene.tsx:22-29` — `DemRenderMode = 'image' | 'hillshade' | 'terrain'`; explicit BSR-09 follow-up comment: "'terrain' is not currently in StyleConfig.render_mode union… should extend the union to include 'terrain'." Casts at the boundary.
- `BuilderMap.tsx:379-411` `applyTerrainConfig()` requires **both** map-level `terrainConfig.enabled` + `source_dataset_id` **AND** a layer with `style_config.render_mode === 'terrain'` (`:392`). Once the normalizer strips `'terrain'`, line 392 never matches → `map.setTerrain(null)`.

**Consequence chain:**
1. Terrain mesh never attaches (Map A reads as flat tilt, not 3D).
2. DEM falls through to plain raster adapter (`map-sync.ts:608`) → colorized elevation PNG drawn flat (the green→cyan bands, ×2 DEM layers).
3. "Render as → Terrain" save appears to revert: save persists `render_mode:'terrain'` correctly, but the next load strips it and the editor's `getRenderMode()` (`DEMEditorScene.tsx:53-56`) falls back to `'image'`.

---

## FINDINGS

### F1 — DEM `render_mode:'terrain'` stripped on load → no 3D terrain mesh  **[P0]**
**Status: CONFIRMED LIVE.** Map A fresh load: `map.getTerrain()` → `null`; no `terrain-dem` source present; pitch 60 with flat layers. DB has `terrain_config.enabled=true` + layers #6/#8 `render_mode='terrain'`. Re-selecting Terrain in the DEM editor (per user) restores `{source:'terrain-dem', exaggeration:1}` and a raster-dem source — proving the loss is the load-time strip, not the save serializer.
- **Fix:** add `'terrain'` (and `'image'`) to `RENDER_MODES`; extend `StyleConfig['render_mode']` union; drop the boundary cast + BSR-09 comment in `DEMEditorScene.tsx`. Regression-pin a normalize test that `render_mode:'terrain'` survives a round trip.

### F2 — Raster "Render as" change reverts after save  **[P0, same root cause as F1]**
Save terrain (or any non-allowlisted mode) → reload strips render_mode → editor shows `Image` again. Single fix with F1 closes both. *To verify live in the walkthrough below.*

### F3 — DEM `hillshade` emits "dem dimension mismatch" (×5) on this DEM  **[P1]**
Per user: setting DEM to Hillshade throws 5× MapLibre `backfillBorder` "dem dimension mismatch" — this DEM's tiles aren't uniformly sized. Map B ships with DEM `render_mode='hillshade'` **visible**, so Map B load is the live repro. *To verify in Map B section.* Needs a graceful path (detect/guard, or surface a clear editor warning instead of console error spam).

### F2 — UPDATE: CONFIRMED LIVE
Opened "3D terrain (DEM)" (DB `render_mode='terrain'`) → DEM editor shows **▦ Image [checked]**, not Terrain. Then clicked **◬ Terrain** → `getTerrain()` = `{source:'terrain-dem', exaggeration:1}`, `terrain-dem` source attaches, map renders pronounced 3D relief (evidence `mapA-02-terrain-reselected-3d.jpeg` vs flat `mapA-01-initial-load.jpeg`). Confirms: terrain works whenever `render_mode='terrain'` is present in layer state; the *only* defect is the load-time strip. DEM Terrain mode also exposes an exaggeration slider + correctly disables hypsometric tint.

### F4 — No label indicator in the layer list  **[P1 / enhancement]**
**Status: CONFIRMED.** DOM-compared the "ADK 46er peaks" row (labels enabled, `label_config` present) vs "Hiking trails" row (no labels): structurally identical (drag handle + visibility toggle + single type-glyph + name + options ⋯). No badge/icon signals that a layer has labels on. Checklist item #2 is unmet — add a small label indicator (e.g. an "A"/tag glyph) on rows whose `label_config.enabled` is true, derived purely from layer state (mirror the v1011 `SublayerConfigIndicators` pure-derivation pattern).

### Item #1 (labels) — PASS
Label editor controls (Enable, Column, Font size fixed/zoom, Text color, Text opacity fixed/zoom, Halo color/width, Placement, Anchor, Offset X/Y, Allow overlap, Zoom Range min/max) all present AND round-trip to MapLibre: live symbol layer `layer-…-label` has `text-field:["get","name"]`, `text-size:13`, `text-anchor:"top"`, `text-offset:[0,0.9]`, `text-allow-overlap:false`, `minzoom:12.2`, `maxzoom:22`, `text-color:"#102033"`, `text-halo-width:2`. Labels visible on map (peak names).

### Items #3/#4/#5 — Render-as types + styling wiring (per geometry)
All render-as modes and styling controls are **present and comprehensive**:
- **Point** (ADK 46er peaks): Render-as = Point / Symbols / Heatmap / Cluster. Styling: data-driven, color, opacity (fixed/zoom), radius (fixed/zoom), stroke (toggle/color/width), layer opacity, zoom range, Advanced JSON. **PASS** (modes are in `RENDER_MODES` allowlist → not subject to the strip bug).
- **Line** (Hiking trails): Render-as = Line / Arrow. Styling: data-driven, line color (solid/gradient + advanced expression), opacity (fixed/zoom), width (fixed/zoom), gap, blur, offset, Pattern (Solid/Dashed/Dotted/Dash-dot), Line ends Cap + Join, layer opacity, zoom range. **PASS**.
- **Polygon** (Land classification): Render-as = Fill / Stroke / Fill + Stroke / 3D extrusion. Styling: data-driven, fill (toggle/color/opacity), Fill Pattern (None/Hatch/Cross-hatch/Diagonal/Dots/Grid), stroke (toggle/color/width), Height column (extrusion), layer opacity, zoom range. **PASS**.
- **Raster non-DEM** (TNM/NY Orthos aerial): Render-as = Image. Styling: Brightness min/max, Contrast, Saturation, Hue, Fade, Opacity, Resampling, Reset. **PASS**.
- **Raster DEM** (3D terrain / DEM hillshade): Render-as = Image / Hillshade / Terrain + mode-specific Appearance (terrain→exaggeration; image→hypsometric tint; hillshade→azimuth/etc.). **Render-as defect = F1/F2 (terrain/image stripped on load).**

### F5 — Point editor shows two "Render as" controls  **[P2 / polish]**
The Point Style tab renders **both** a segmented "Render as" button group (Point / Symbols / Heatmap / Cluster) **and** a second "Render as" combobox ("Points", help text "Choose how this point layer should draw."). Line and Polygon editors show only the segmented control. The combobox appears to be a pre-segmented-control leftover — redundant and confusing. Recommend consolidating to the single segmented control (or confirm the combobox drives a distinct sub-variant and relabel it).

### Aside — non-DEM raster reports "1 band" for RGB ortho  **[P2 / peripheral]**
`band_count` shows "1 band" for the RGB aerial; consistent with the v1032 note that `band_count=None` on the `get_dataset_meta` path. Colormap section is (correctly) hidden for imagery, so no functional break, but the band count label is misleading. Out of core scope; logged for awareness.

### F3 — UPDATE: did NOT reproduce on Map B; downgraded to **[P2]**
Map B ships DEM `render_mode='hillshade'` visible. On live load + zoom z12.5→15→16.5 + pan + an interactive Image→Hillshade toggle: **0 console errors/warnings**; hillshade renders cleanly (relief texture visible). Editor correctly shows ⛰ Hillshade checked (hillshade is allowlisted, so not stripped — contrast with terrain).
- The user's "dem dimension mismatch ×5" was on **Map A**, where the *same* DEM (`2931c262`) is consumed simultaneously by a **terrain** source (`terrain-dem`) and a **hillshade** attempt — likely a dual-consumer DEM-tile-size `backfillBorder` conflict, not a general hillshade defect. Intended Map A end-state is hillshade layer hidden + terrain on (per user), so this is a narrow edge.
- **Recommendation:** add a graceful guard — when a DEM is already bound to a terrain source, either reuse the same DEM-source tileSize for a hillshade consumer or surface a one-line editor note ("Hillshade unavailable while Terrain is active on this DEM") instead of letting MapLibre spam `backfillBorder` errors. Low priority; main hillshade path is healthy.

### Item #6 — Reorder + visibility: PASS
- **Visibility:** toggled "NHD streams and rivers" hidden→visible; button `aria-pressed` flipped true and the map line layer flipped `visibility:visible`. Clean.
- **Reorder:** dnd-kit keyboard drag (focus handle → Space → ArrowDown → Space) moved "Hiking trails" down one slot (swapped with "NHD streams and rivers"). Clean, 0 errors.
- **Unsaved-nav guard:** navigating away with unsaved edits fires a `beforeunload` confirmation (good UX).

---

## SUMMARY & RECOMMENDED v1033 SCOPE

**Checklist results:**
| # | Check | Verdict |
|---|-------|---------|
| 1 | Labels visible + all options (placement/styling/zoom) | ✅ PASS (controls comprehensive, round-trip verified) |
| 2 | Label-toggle indicator in layer list | ❌ GAP → **F4** |
| 3 | Point/line/polygon render-as types work | ✅ PASS (vector modes allowlisted, not stripped) |
| 4 | Each render-as: styling wired | ✅ PASS (point/line/polygon comprehensive); ⚠ **F5** point duplicate control |
| 5 | Raster render-as configs work | ⚠ DEM terrain/image **broken on load → F1/F2**; non-DEM image PASS |
| 6 | Reorder + visibility toggle | ✅ PASS |
| — | Raster "render as" save-revert bug | ❌ **F2** (confirmed; same root cause as F1) |
| — | Terrain render_mode strip + hillshade | ❌ **F1** (P0); ⚠ **F3** (P2 narrow) |

**Findings → fix plan:**
- **F1 + F2 [P0] — one fix:** add `'terrain'` (and `'image'`) to `RENDER_MODES` (`normalize-style-config.ts:92`); extend `StyleConfig['render_mode']` union (`api.ts:863`) to include `'terrain' | 'image'`; remove the boundary cast + BSR-09 comment in `DEMEditorScene.tsx`; confirm `api.ts` is hand-maintained vs generated (style_config is opaque jsonb on the backend, so likely a frontend type). Regression-pin a normalize round-trip test for each DEM mode. Verifies: Map A loads with `getTerrain()` non-null + 3D relief; DEM render-as no longer reverts.
- **F4 [P1] — label indicator:** add a pure-derived badge/glyph on layer rows whose `label_config.enabled` is true (mirror v1011 `SublayerConfigIndicators` derivation pattern); 4-locale i18n; a11y label.
- **F3 [P2] — hillshade dual-consumer guard:** graceful handling when a DEM is bound to terrain + hillshade simultaneously.
- **F5 [P2] — point editor:** consolidate the duplicate "Render as" combobox.
- **Related carry-forward [P2 hygiene]:** bound `_band_stats_cache` (`tiles/router.py`) with an LRU/TTL (raster-render-adjacent; from v1032 deferred).
- **Out of scope (kept tight):** multi-band stretch (RASTER-STRETCH-03), configurable percentile/σ, seeding a non-DEM single-band raster, the band_count "1 band" display fix. These are not related to the terrain/label defects; leave as Future.

**Close-gate:** orchestrator-driven Playwright MCP re-verify on both maps (terrain renders on Map A fresh load; render-as persists across reload; label indicator visible; reorder/visibility clean; 0 console errors) + typecheck/vitest/e2e:smoke:builder/i18n/pytest(raster·tile)/openapi-check.

