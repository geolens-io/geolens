import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { getBuilderStyleConfig, syncOwnedPaintProperties, syncSingleLayerVisibility, syncLayerFilter } from './shared';
// builder-audit #338 ADAPT-05: the radius/weight/intensity/opacity defaults come from the
// single builder-defaults source of truth (radius 30 / weight 1) instead of the magic
// literals that previously diverged from renderAs's heatmap default (radius 18 / weight 0.5).
import { DEFAULT_HEATMAP_PAINT as HEATMAP_PAINT_DEFAULTS } from './builder-defaults';
import { getRampColors } from '@/lib/color-ramps';

/** builder-audit #338 ADAPT-11: typed coercion so an out-of-range / string / expression
 *  heatmap-opacity cannot flow through a bare `as number` cast into NaN math
 *  (storedHeatmapOpacity * masterOpacity). Mirrors fill-adapter's finiteNumber. */
function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** Build the default heatmap-color interpolation expression using a named ramp.
 *  The expression has transparent (rgba 0,0,0,0) at density 0 so low-density
 *  areas are fully transparent. */
export function buildHeatmapColorExpression(rampName: string): unknown[] {
  const colors = getRampColors(rampName, 5);
  return [
    'interpolate', ['linear'], ['heatmap-density'],
    0,   'rgba(0,0,0,0)',
    0.2, colors[0],
    0.4, colors[1],
    0.6, colors[2],
    0.8, colors[3],
    1.0, colors[4],
  ];
}

const DEFAULT_RAMP = 'YlOrRd';
const HEATMAP_OWNED_PAINT_PROPERTIES = [
  'heatmap-radius',
  'heatmap-weight',
  'heatmap-intensity',
  'heatmap-color',
  'heatmap-opacity',
] as const;

/** Default paint properties for a new heatmap layer. The numeric defaults are the
 *  shared builder-defaults (radius/weight/intensity/opacity); only the ramp-derived
 *  heatmap-color is layered on here (it lives in this module to avoid a builder-defaults
 *  -> color-ramps circular import). */
export const DEFAULT_HEATMAP_PAINT: Record<string, unknown> = {
  ...HEATMAP_PAINT_DEFAULTS,
  'heatmap-color': buildHeatmapColorExpression(DEFAULT_RAMP),
};

export const heatmapAdapter: LayerAdapter = {
  type: 'heatmap',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, sourceId, sourceLayer, paint: rawPaint, filter, opacity, visible } = input;
    const builder = getBuilderStyleConfig(input);

    // Extract heatmap-specific props from paint, falling back to shared defaults.
    // radius/weight/intensity may legitimately be zoom expressions (arrays), so they
    // keep `?? default` rather than finiteNumber coercion.
    const heatmapRadius = rawPaint['heatmap-radius'] ?? HEATMAP_PAINT_DEFAULTS['heatmap-radius'];
    const heatmapWeight = rawPaint['heatmap-weight'] ?? HEATMAP_PAINT_DEFAULTS['heatmap-weight'];
    const heatmapIntensity = rawPaint['heatmap-intensity'] ?? HEATMAP_PAINT_DEFAULTS['heatmap-intensity'];
    // Phase 1051 CR-04: read stored heatmap-opacity (matching syncPaint formula
    // below) and compound with master opacity. Previously hard-coded 0.8 at
    // add-time, which overwrote persisted heatmap-opacity on every page load,
    // render-mode swap, or basemap switch — producing a visible flash and silent
    // drift until any subsequent paint sync.
    // builder-audit #338 ADAPT-11: finiteNumber rejects a string/array/NaN opacity that a
    // bare `as number` cast would have multiplied into NaN.
    const storedHeatmapOpacity = finiteNumber(rawPaint['heatmap-opacity']) ?? HEATMAP_PAINT_DEFAULTS['heatmap-opacity'];
    const heatmapOpacity = storedHeatmapOpacity * (opacity ?? 1);

    // Use stored color expression or build the default
    const heatmapColor: unknown = rawPaint['heatmap-color'] ?? buildHeatmapColorExpression(builder.heatmapRamp ?? DEFAULT_RAMP);

    try {
      map.addLayer({
        id: layerId,
        type: 'heatmap',
        source: sourceId,
        ...(input.sourceType !== 'geojson' && { 'source-layer': sourceLayer }),
        paint: {
          'heatmap-radius': heatmapRadius,
          'heatmap-weight': heatmapWeight,
          'heatmap-intensity': heatmapIntensity,
          'heatmap-color': heatmapColor,
          'heatmap-opacity': heatmapOpacity,
        } as Record<string, unknown>,
        // BUG-01: honor input.visible at initial add — see fill-adapter for rationale.
        ...(visible === false ? { layout: { visibility: 'none' as const } } : {}),
      });

      syncLayerFilter(map, layerId, filter);
    } catch (e) {
      if (import.meta.env.DEV) console.warn(`[map-sync] addLayer (heatmap) failed for ${layerId}:`, e);
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, paint: rawPaint, filter } = input;
    if (!map.getLayer(layerId)) return;
    const builder = getBuilderStyleConfig(input);

    syncOwnedPaintProperties(map, layerId, {
      'heatmap-radius': rawPaint['heatmap-radius'] ?? HEATMAP_PAINT_DEFAULTS['heatmap-radius'],
      'heatmap-weight': rawPaint['heatmap-weight'] ?? HEATMAP_PAINT_DEFAULTS['heatmap-weight'],
      'heatmap-intensity': rawPaint['heatmap-intensity'] ?? HEATMAP_PAINT_DEFAULTS['heatmap-intensity'],
      'heatmap-color': rawPaint['heatmap-color'] ?? buildHeatmapColorExpression(builder.heatmapRamp ?? DEFAULT_RAMP),
    }, { ownedProperties: HEATMAP_OWNED_PAINT_PROPERTIES.filter((prop) => prop !== 'heatmap-opacity') });

    // Compound stored heatmap-opacity with master opacity. Single source of truth.
    // builder-audit #338 ADAPT-11: finiteNumber guards the same NaN path as add-time.
    const storedOpacity = finiteNumber(rawPaint['heatmap-opacity']) ?? HEATMAP_PAINT_DEFAULTS['heatmap-opacity'];
    map.setPaintProperty(layerId, 'heatmap-opacity', storedOpacity * (input.opacity ?? 1));

    syncLayerFilter(map, layerId, filter);
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    syncSingleLayerVisibility(map, input.layerId, input.visible);
  },

  getLayerIds(layerId: string): string[] {
    return [layerId];
  },
};
