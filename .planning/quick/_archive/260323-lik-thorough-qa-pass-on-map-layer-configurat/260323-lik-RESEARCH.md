# QA: Map Layer Configuration - Research

**Researched:** 2026-03-23
**Domain:** MapLibre GL JS layer configuration, map-sync imperative rendering
**Confidence:** HIGH

## Summary

The map layer configuration system is well-structured with a clear separation: `map-sync.ts` handles imperative MapLibre layer creation/sync, `use-builder-layers.ts` manages React state and live updates, `LayerStyleEditor`/`LayerFilterEditor`/`LabelEditor` provide UI controls, and `layer-capabilities.ts` centralizes the vector/raster/VRT classification logic.

The architecture follows KISS well -- it is imperative (matching MapLibre's model), avoids unnecessary abstraction layers, and keeps configuration as plain JSON objects. However, several correctness and consistency issues exist that deserve attention.

**Primary recommendation:** Fix the specific correctness issues identified below; do not add abstraction.

## Findings

### 1. Duplicated `getGeometryType` / `getLayerType` Logic (LOW severity)

The geometry-to-layer-type mapping is implemented in three places:
- `map-sync.ts:getLayerType()` (lines 42-47)
- `LayerStyleEditor.tsx:getGeometryType()` (lines 15-20)
- `layer-capabilities.ts:getLayerCapabilities()` (lines 39-52)

All three use the same pattern (`gt.includes('POINT')` -> circle, `gt.includes('LINE')` -> line, else fill). This is not a bug but creates drift risk. `getLayerType` from map-sync is already imported elsewhere; the local `getGeometryType` in `LayerStyleEditor` could use it instead.

**Recommendation:** Replace `LayerStyleEditor.getGeometryType` with import of `getLayerType` from `map-sync.ts`. Low priority.

### 2. `outline-width` is a Custom Property, Not a MapLibre Property (MEDIUM severity)

In `map-sync.ts` line 249, the outline width for fill layers is read from `paint['outline-width']`. This is NOT a standard MapLibre paint property -- it is a custom key stored in the paint JSON. The actual MapLibre outline for `type: 'fill'` layers uses `fill-outline-color` (1px only; fill layers do not support variable-width outlines natively).

The workaround (adding a separate `line` layer for outlines) is correct. However:
- The custom `outline-width` key lives in the `paint` object alongside real MapLibre properties
- This could confuse AI tools or future developers who expect `paint` to be a valid MapLibre paint spec
- The `LayerStyleEditor` stores it as `paint['outline-width']` (line 111), which gets synced to the backend

**Recommendation:** This is a pragmatic pattern that works. Document it with a comment in the paint type or map-sync. No code change needed unless a stricter schema is desired later.

### 3. Opacity Handling Inconsistency (MEDIUM severity)

Opacity is applied differently depending on code path:

**Initial layer creation (map-sync.ts):**
- Fill: only applies opacity if `< 1` (line 231-234), multiplies fill-opacity by master opacity
- Circle: only applies if `< 1` (line 175-177), sets `circle-opacity` directly
- Line: only applies if `< 1` (line 204-206), sets `line-opacity` directly

**Live updates (use-builder-layers.ts `handleOpacityChange`):**
- Fill: always applies, multiplies fill-opacity by master opacity (correct)
- Circle: always applies `circle-opacity` directly (correct)
- Line: always applies `line-opacity` directly (correct)

The `< 1` guard on initial creation means if a saved layer has `opacity: 0.5`, it renders correctly. But if a layer starts at `opacity: 1.0`, the opacity property is never explicitly set on the MapLibre layer. This is fine because MapLibre defaults to `1.0`, but it creates an inconsistency: after adjusting opacity via the slider and then saving/reloading, the initial-creation path might skip setting opacity if it's been restored to 1.0. In practice this works but the guard is unnecessary complexity.

**Recommendation:** Remove the `if (layer.opacity !== undefined && layer.opacity < 1)` guards and always set opacity. Simplifies logic.

### 4. Filter Sync on Label Layers is Inconsistent (MEDIUM severity)

When a filter changes via `handleFilterChange` in `use-builder-layers.ts` (line 242-265), it correctly syncs the filter to:
- Main data layer
- Outline layer
- Label layer

But in `map-sync.ts:syncLayersToMap`, the label layer filter is only applied on initial creation (line 327-329), not during the paint-sync path for existing sources (the `else` branch starting at line 260). If `syncLayersToMap` runs after a filter change but before the layer is fully rebuilt, the label filter could be stale.

**Recommendation:** Add filter sync for label layers in the existing-source sync path of `syncLayersToMap`.

### 5. `JSON.stringify` for Paint Property Comparison (LOW severity)

`map-sync.ts` line 269 uses `JSON.stringify(current) !== JSON.stringify(val)` to diff paint properties. This works but:
- `JSON.stringify` is sensitive to key ordering (not relevant for paint values which are arrays/primitives)
- Could be slow for deeply nested expression arrays on many layers
- Not wrong, just a note

**Recommendation:** Keep as-is. This is fine for the data shapes involved.

### 6. Missing Line Opacity on Outline Layer During Initial Creation (LOW severity)

In `map-sync.ts`, when creating a fill layer with `opacity < 1`, the outline line layer is created (line 242-251) but its opacity is only set afterward (line 252-254). This means the outline gets `line-opacity` applied correctly. Good.

However, the outline layer does NOT sync its opacity in the existing-source path (line 260+). If paint changes come through `syncLayersToMap` but opacity was changed externally, the outline opacity could be stale. The live update path in `use-builder-layers.ts` handles this correctly (line 458-461).

**Recommendation:** Low risk since `use-builder-layers` handles live opacity. No action needed.

### 7. Hardcoded Values That Could Be Configurable

Currently hardcoded:
| Value | Location | Current | Note |
|-------|----------|---------|------|
| Vector source minzoom | map-sync.ts:142 | 1 | Correct for ST_AsMVT constraint |
| Vector source maxzoom | map-sync.ts:143 | 22 | MapLibre default is 22, explicit is good |
| Default circle radius | map-sync.ts:162 | 5 | Reasonable default |
| Default line width | map-sync.ts:189 | 2 | Reasonable default |
| Default fill opacity | map-sync.ts:219 | MAP_COLORS.default.fillOpacity (0.3) | Good, centralized |
| Label text-max-width | map-sync.ts:319 | 10 | Standard for em-based wrapping |
| Label text-offset for points | map-sync.ts:320 | [0, -1.5] | Reasonable above-point placement |
| Label font | map-sync.ts:318 | 'Noto Sans Regular' | Must match basemap glyphs |
| Max categories warning | DataDrivenStyleEditor:144 | 20 | Good threshold |
| Class count range | DataDrivenStyleEditor:233-234 | 3-9 | GIS standard range |

**Recommendation:** These are all reasonable defaults. Do NOT make them configurable through UI -- that would over-engineer. The paint/layout JSON already allows overriding any of these per-layer via the API or AI chat.

### 8. `styleDiffing={false}` on BuilderMap (Correct)

BuilderMap.tsx line 353 sets `styleDiffing={false}`. This is correct because:
- The component manually manages all data layers imperatively
- Style diffing would conflict with imperative source/layer management
- Basemap switches are handled via `style.load` event listener

### 9. Layer Ordering Strategy (Correct)

BuilderMap.tsx lines 253-278 implements a two-pass ordering:
1. First pass: move data/outline layers (bottom of stack first)
2. Second pass: move label layers on top
3. Finally: reorder basemap labels above everything

This ensures labels are never obscured by data layers above them. The reverse iteration (`layers.length - 1` to `0`) with `moveLayer(id)` (no second arg = move to top) is correct for achieving array-order = visual-order.

### 10. Silent Error Swallowing in Expression Application

`map-sync.ts` lines 171-173, 198-200, etc. use `try { map.setPaintProperty(...) } catch { /* keep scalar fallback */ }`. The `catch` blocks are completely silent with no logging.

**Recommendation:** Add a `console.debug` or conditional warning in development mode. A fully silent catch makes debugging AI-generated bad expressions difficult.

## Common Pitfalls

### Pitfall 1: Raster Token URL Not Refreshing
**What:** Raster tile URLs use nginx auth subrequest, so the tile URL itself never changes. Vector tiles use signed URLs that rotate. The code correctly skips raster in the token-refresh effect (BuilderMap.tsx line 242).
**Risk:** None currently. Just documenting the asymmetry.

### Pitfall 2: Basemap Glyph Font Mismatch
**What:** Label layers use `'Noto Sans Regular'` (map-sync.ts:318). If a basemap does not serve this font via its glyph source, labels will fail silently.
**Risk:** Only affects custom basemaps that use different glyph stacks. CARTO positron includes Noto Sans.

### Pitfall 3: Fill-Outline-Color Limitations
**What:** MapLibre's `fill-outline-color` only renders at 1px width and does not support data-driven expressions when using the default fill layer. The separate outline `line` layer workaround handles this, but the UI stores the value as `fill-outline-color` in the paint object (which is then read by the outline line layer as `line-color`).
**Mapping:** `paint['fill-outline-color']` -> outline line layer `line-color`, `paint['outline-width']` -> outline line layer `line-width`.

## Architecture Assessment

The system is appropriately simple:
- **No over-engineering:** No custom layer abstraction, no style DSL, no layer state machine
- **Imperative where needed:** MapLibre is fundamentally imperative; the code embraces this
- **React state as source of truth:** `localLayers` in `use-builder-layers` is the authority; map is a render target
- **Clean separation:** `map-sync.ts` is pure functions (no React), testable independently
- **Capability model:** `layer-capabilities.ts` correctly centralizes vector/raster/VRT branching

**Verdict:** Well-designed, follows KISS. The issues found are minor consistency fixes, not architectural problems.

## Actionable Items (Priority Order)

1. **Add filter sync for label layers** in `map-sync.ts` existing-source path
2. **Remove `opacity < 1` guards** in `map-sync.ts` initial creation -- always set opacity
3. **Add debug logging** for silent expression catch blocks
4. **Replace duplicate `getGeometryType`** in LayerStyleEditor with `getLayerType` import
5. **Add comment** documenting the `outline-width` custom paint property convention

## Sources

### Primary (HIGH confidence)
- Direct code review of: `map-sync.ts`, `BuilderMap.tsx`, `use-builder-layers.ts`, `LayerStyleEditor.tsx`, `DataDrivenStyleEditor.tsx`, `LayerFilterEditor.tsx`, `LabelEditor.tsx`, `LayerItem.tsx`, `layer-capabilities.ts`, `map-colors.ts`, `color-ramps.ts`, `classification.ts`, `tile-utils.ts`
- Backend schema: `backend/app/maps/models.py`, `backend/app/maps/schemas.py`
- MapLibre GL JS v5 paint/layout property behavior (confirmed via project memory)

## Metadata

**Confidence breakdown:**
- Code correctness issues: HIGH - direct code analysis
- Architecture assessment: HIGH - comprehensive review of all layer-related files
- MapLibre behavior claims: HIGH - well-known library constraints (fill-outline 1px limit, style diffing behavior)

**Research date:** 2026-03-23
**Valid until:** 2026-04-23
