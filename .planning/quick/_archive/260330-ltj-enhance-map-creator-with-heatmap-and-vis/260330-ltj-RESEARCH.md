# Quick Task: Heatmap Visualization - Research

**Researched:** 2026-03-30
**Domain:** MapLibre GL JS heatmap layers + layer adapter integration
**Confidence:** HIGH

## Summary

MapLibre GL JS natively supports `heatmap` layer types with five paint properties: `heatmap-weight`, `heatmap-intensity`, `heatmap-color`, `heatmap-radius`, and `heatmap-opacity`. The existing layer adapter architecture (`LayerAdapter` interface, registry pattern, circle-adapter as template) maps cleanly to a new `heatmap-adapter.ts`. The main integration points are: (1) adapter registry gains a `heatmap` entry, (2) `map-sync.ts` resolves adapter type using a `render_mode` field from `style_config` instead of only geometry type, (3) `LayerStyleEditor` conditionally shows heatmap controls when render mode is heatmap, (4) existing `ColorRampPicker` and `getRampColors` from `color-ramps.ts` generate the `heatmap-color` interpolation expression.

**Primary recommendation:** Store `render_mode: 'points' | 'heatmap'` inside the existing `style_config` JSONB column. This requires zero backend schema changes and preserves backward compatibility (absent field defaults to `'points'`).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Heatmap only -- no clusters, 3D extrusions, or other viz types
- Use MapLibre's native `heatmap` layer type for point data
- Simple controls: weight column picker, color ramp selector, radius slider, intensity slider
- Auto-tune sensible defaults so heatmaps look good out of the box
- No advanced controls (kernel type, per-zoom interpolation curves, custom opacity stops)
- "Render as" dropdown (Points / Heatmap) at top of style tab
- Same layer object, different rendering mode -- not a separate layer type
- When switched to heatmap, point style controls replaced with heatmap controls
- Paint/style state for each mode preserved when toggling back and forth

### Claude's Discretion
- Heatmap color ramp selection -- reuse existing sequential/diverging ramps
- Default radius/intensity values
- Zoom-based interpolation for radius

### Deferred Ideas (OUT OF SCOPE)
- Clusters, 3D extrusions, other visualization types
- Advanced controls (kernel type, per-zoom interpolation curves, custom opacity stops)
</user_constraints>

## Architecture Patterns

### Adapter Integration

The `LayerAdapter` interface (`types.ts`) currently supports types `'fill' | 'line' | 'circle' | 'raster'`. Add `'heatmap'` to this union. The new `heatmap-adapter.ts` follows the same shape as `circle-adapter.ts`:

```typescript
// heatmap-adapter.ts -- follows circle-adapter pattern exactly
export const heatmapAdapter: LayerAdapter = {
  type: 'heatmap',
  addLayers(map, input) { /* map.addLayer({ type: 'heatmap', ... }) */ },
  syncPaint(map, input) { /* setPaintProperty for each heatmap-* prop */ },
  syncVisibility(map, input) { /* setLayoutProperty visibility */ },
  getLayerIds(layerId) { return [layerId]; },
};
```

Register in `registry.ts` alongside existing adapters. No compound layers (no outline companion like fill has).

### Adapter Resolution Change

Currently `map-sync.ts` line 103-104 resolves adapter type purely from geometry:
```typescript
const type = getLayerType(layer.dataset_geometry_type); // always 'circle' for points
const adapter = getAdapter(type);
```

With heatmap support, this must check `style_config.render_mode` first:
```typescript
function resolveAdapterType(layer: MapLayerResponse): string {
  if (
    layer.style_config?.render_mode === 'heatmap' &&
    getLayerType(layer.dataset_geometry_type) === 'circle'
  ) {
    return 'heatmap';
  }
  return getLayerType(layer.dataset_geometry_type);
}
```

This resolution function must be used in **both** `map-sync.ts` (builder) and `ViewerMap.tsx` (shared/public viewer) -- both files currently call `getLayerType()` + `getAdapter()`.

### Layer Switching: Remove-and-Re-add

When toggling between Points and Heatmap, the MapLibre layer type changes (`circle` vs `heatmap`). MapLibre does NOT support changing a layer's `type` after creation. The toggle must:

1. Remove the existing MapLibre layer (`map.removeLayer(layerId)`)
2. Add a new layer with the new type via the appropriate adapter's `addLayers()`
3. Keep the source intact (source stays, only layer changes)

This is the critical implementation detail. The `handlePaintChange` path in `use-builder-layers.ts` (which does incremental `setPaintProperty` calls) cannot handle a type change -- a full re-add is needed when `render_mode` changes.

### State Preservation Across Toggles

The user expects to toggle Points <-> Heatmap and retain settings for each mode. Store both sets of paint in `style_config`:

```typescript
// Inside style_config JSONB
{
  render_mode: 'heatmap',
  // existing data-driven style fields (mode, column, ramp, etc.) still here
  heatmap_paint: {
    'heatmap-radius': 30,
    'heatmap-weight': ['get', 'population'],
    'heatmap-intensity': 1,
    'heatmap-color': [/* interpolation expression */],
    'heatmap-opacity': 1,
  },
  saved_circle_paint: { /* snapshot of circle paint when switching away */ },
}
```

When switching TO heatmap: save current `layer.paint` into `style_config.saved_circle_paint`, apply `style_config.heatmap_paint` to `layer.paint`. When switching BACK: restore `saved_circle_paint` to `layer.paint`.

Alternatively, keep `heatmap_paint` in `style_config` and `layer.paint` always holds the active mode's paint. The adapter reads from `layer.paint` regardless of mode. This is simpler and consistent with how all adapters work today.

## MapLibre Heatmap Paint Properties

All verified from MapLibre Style Spec (https://maplibre.org/maplibre-style-spec/layers/).

| Property | Type | Default | Range | Transitionable | Notes |
|----------|------|---------|-------|----------------|-------|
| `heatmap-radius` | number | 30 | [1, inf) px | Yes | Influence zone per point |
| `heatmap-weight` | number | 1 | [0, inf) | No | Per-feature weight multiplier |
| `heatmap-intensity` | number | 1 | [0, inf) | Yes | Global intensity multiplier |
| `heatmap-color` | color | blue-to-red ramp | N/A | No | Interpolation on `["heatmap-density"]` |
| `heatmap-opacity` | number | 1 | [0, 1] | Yes | Global layer opacity |

### heatmap-color Expression

This is the only non-scalar property. It uses `["heatmap-density"]` (a value from 0 to 1) as input:

```typescript
// Build from a chroma-js color ramp
function buildHeatmapColorExpr(rampName: string): unknown[] {
  const colors = getRampColors(rampName, 6);
  return [
    'interpolate', ['linear'], ['heatmap-density'],
    0,   'rgba(0,0,0,0)',   // transparent at zero density
    0.2, colors[0],
    0.4, colors[1],
    0.6, colors[2],
    0.8, colors[3],
    1.0, colors[4],
  ];
}
```

The first stop at 0 should be transparent so low-density areas don't paint over the basemap. The remaining 5 stops sample the ramp evenly.

### heatmap-weight Expression

When a weight column is selected, use `["get", column]`. When no column is selected, use constant `1`:

```typescript
const weight = weightColumn
  ? ['interpolate', ['linear'], ['get', weightColumn], minVal, 0, maxVal, 1]
  : 1;
```

Normalizing to 0-1 via interpolation requires knowing the column min/max. The existing `ColumnStatsResponse` endpoint (`/api/datasets/{id}/columns/{col}/stats`) already returns min/max.

### Zoom-Based Radius Interpolation

Sensible default that scales radius with zoom:
```typescript
['interpolate', ['linear'], ['zoom'],
  0,  2,    // small at world view
  9,  20,   // medium at city level
  15, 30    // large at street level
]
```

This can be the default when `heatmap-radius` is not explicitly set. The user's radius slider sets a base value; the zoom interpolation scales proportionally from it.

### Source Compatibility

Heatmap layers work with vector tile sources AND support `source-layer` (required for vector sources). This is confirmed by the MapLibre spec: `source-layer` is "required for vector tile sources; prohibited for all other source types." Since GeoLens uses vector tile sources with `source-layer: 'data.{table_name}'`, heatmap layers will work with the existing source setup.

Filter is a general layer property available to all layer types including heatmap.

## UI Integration

### "Render as" Dropdown

Place at the top of `LayerStyleEditor` when `geomType === 'circle'`:

```tsx
{geomType === 'circle' && (
  <Select value={renderMode} onValueChange={handleRenderModeChange}>
    <SelectItem value="points">Points</SelectItem>
    <SelectItem value="heatmap">Heatmap</SelectItem>
  </Select>
)}
```

When `renderMode === 'heatmap'`, hide all circle controls and show heatmap controls instead.

### Heatmap Controls

Four controls when in heatmap mode:
1. **Weight column** -- dropdown of numeric columns from `layer.dataset_column_info` (filter to numeric types). "None" option uses constant weight.
2. **Color ramp** -- reuse `ColorRampPicker` with `mode="graduated"` (shows sequential + diverging ramps). Build `heatmap-color` expression from selected ramp.
3. **Radius slider** -- range 1-100px, default 30. Maps to `heatmap-radius`.
4. **Intensity slider** -- range 0.1-5, default 1. Maps to `heatmap-intensity`.

### ColorRampPicker Reuse

`ColorRampPicker` accepts `mode: 'categorical' | 'graduated'`. For heatmaps, use `mode="graduated"` which shows `SEQUENTIAL_RAMPS` + `DIVERGING_RAMPS`. The `onChange` callback returns a ramp name string. Use `getRampColors(rampName, 6)` to generate the color stops for the `heatmap-color` expression.

One consideration: `ColorRampPicker` could accept a third mode `'heatmap'` if we want to filter ramps differently, but `'graduated'` already provides the right palette set.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Color ramps | Custom color arrays | `getRampColors()` from `color-ramps.ts` + chroma-js |
| Column statistics | Manual min/max calculation | Existing `/datasets/{id}/columns/{col}/stats` API |
| Layer type switching | Incremental paint updates | Remove layer + re-add via adapter |

## Common Pitfalls

### Pitfall 1: Attempting to change layer type in-place
**What goes wrong:** Calling `setPaintProperty` with heatmap properties on a circle layer (or vice versa) throws errors.
**How to avoid:** Always remove the layer and re-add with the correct type when `render_mode` changes.

### Pitfall 2: Missing transparent stop at density 0
**What goes wrong:** Heatmap paints solid color over entire map extent.
**How to avoid:** First stop in `heatmap-color` must be `rgba(0,0,0,0)` at density 0.

### Pitfall 3: Forgetting ViewerMap.tsx
**What goes wrong:** Heatmaps work in builder but render as circles in shared/public views.
**How to avoid:** The adapter resolution change must apply in both `map-sync.ts` and `ViewerMap.tsx`.

### Pitfall 4: Data-driven styles conflict
**What goes wrong:** If a layer has both a `style_config` with data-driven graduated/categorical styling AND `render_mode: 'heatmap'`, the expression-based circle paint conflicts with heatmap paint.
**How to avoid:** When switching to heatmap mode, clear data-driven circle style (or save it for restoration). Heatmap has its own weight-based "data-driven" mechanism via `heatmap-weight`.

### Pitfall 5: Label layer orphaning
**What goes wrong:** When switching to heatmap, label layers (text labels attached to the circle layer) may become orphaned or positioned incorrectly.
**How to avoid:** Hide or remove label layers when in heatmap mode. Labels on a heatmap don't make sense -- they reference individual features, but heatmap aggregates them.

## Code Examples

### Building heatmap paint from UI state

```typescript
import { getRampColors } from '@/lib/color-ramps';

interface HeatmapConfig {
  radius: number;          // e.g. 30
  intensity: number;       // e.g. 1
  rampName: string;        // e.g. 'YlOrRd'
  weightColumn: string | null;
  weightMin?: number;
  weightMax?: number;
}

function buildHeatmapPaint(config: HeatmapConfig): Record<string, unknown> {
  const colors = getRampColors(config.rampName, 6);
  const paint: Record<string, unknown> = {
    'heatmap-radius': [
      'interpolate', ['linear'], ['zoom'],
      0,  Math.max(1, config.radius * 0.1),
      9,  config.radius * 0.7,
      15, config.radius,
    ],
    'heatmap-intensity': [
      'interpolate', ['linear'], ['zoom'],
      0,  config.intensity * 0.3,
      9,  config.intensity,
      15, config.intensity * 1.5,
    ],
    'heatmap-color': [
      'interpolate', ['linear'], ['heatmap-density'],
      0,   'rgba(0,0,0,0)',
      0.2, colors[1],
      0.4, colors[2],
      0.6, colors[3],
      0.8, colors[4],
      1.0, colors[5],
    ],
    'heatmap-opacity': 0.8,
  };

  if (config.weightColumn && config.weightMin != null && config.weightMax != null) {
    paint['heatmap-weight'] = [
      'interpolate', ['linear'], ['get', config.weightColumn],
      config.weightMin, 0,
      config.weightMax, 1,
    ];
  }

  return paint;
}
```

### Heatmap adapter addLayers

```typescript
addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
  const { layerId, sourceId, sourceLayer, paint: rawPaint, filter } = input;
  try {
    map.addLayer({
      id: layerId,
      type: 'heatmap',
      source: sourceId,
      'source-layer': sourceLayer,
      paint: {
        'heatmap-radius': rawPaint['heatmap-radius'] ?? 30,
        'heatmap-weight': rawPaint['heatmap-weight'] ?? 1,
        'heatmap-intensity': rawPaint['heatmap-intensity'] ?? 1,
        'heatmap-color': rawPaint['heatmap-color'] ?? [
          'interpolate', ['linear'], ['heatmap-density'],
          0, 'rgba(0,0,0,0)', 0.2, '#ffffb2', 0.4, '#fecc5c',
          0.6, '#fd8d3c', 0.8, '#f03b20', 1, '#bd0026',
        ],
        'heatmap-opacity': rawPaint['heatmap-opacity'] ?? 0.8,
      },
    });
    if (filter && Array.isArray(filter) && filter.length > 0) {
      map.setFilter(layerId, filter);
    }
  } catch (e) {
    console.warn(`[map-sync] addLayer failed for heatmap ${layerId}:`, e);
  }
}
```

## Sensible Defaults

| Property | Default | Rationale |
|----------|---------|-----------|
| `heatmap-radius` | 30 | MapLibre default; good for moderate density at z9-12 |
| `heatmap-intensity` | 1 | Neutral; zoom interpolation handles scaling |
| `heatmap-opacity` | 0.8 | Slightly transparent so basemap shows through |
| `heatmap-weight` | 1 (constant) | Equal weight until user selects a column |
| `heatmap-color` ramp | `YlOrRd` | Classic heat color scheme, first in `SEQUENTIAL_RAMPS` |

## Backend Impact

**None.** The `style_config` column is already JSONB. Adding `render_mode` and `heatmap_paint` fields inside it requires zero schema or migration changes. The backend passes `style_config` through as opaque JSON -- all interpretation is frontend-only.

## Sources

### Primary (HIGH confidence)
- MapLibre Style Spec layers page: https://maplibre.org/maplibre-style-spec/layers/ -- heatmap paint properties, defaults, value ranges
- MapLibre heatmap example: https://maplibre.org/maplibre-gl-js/docs/examples/create-a-heatmap-layer/ -- confirmed expression patterns
- Project source code: `layer-adapters/`, `map-sync.ts`, `color-ramps.ts`, `LayerStyleEditor.tsx`, `ViewerMap.tsx` -- existing patterns and integration points

## Metadata

**Confidence breakdown:**
- Heatmap API: HIGH -- verified against official MapLibre style spec
- Adapter integration: HIGH -- pattern is well-established in codebase, direct code review
- State preservation approach: HIGH -- JSONB column allows arbitrary structure
- Zoom interpolation defaults: MEDIUM -- sensible values but may need tuning per dataset density

**Research date:** 2026-03-30
**Valid until:** 2026-04-30
