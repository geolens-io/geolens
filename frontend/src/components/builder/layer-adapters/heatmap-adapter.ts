import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { CUSTOM_PAINT_PROPS, getBuilderStyleConfig, paintValueChanged, syncSingleLayerVisibility, syncLayerFilter } from './shared';
import { getRampColors } from '@/lib/color-ramps';

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

/** Default paint properties for a new heatmap layer. */
export const DEFAULT_HEATMAP_PAINT: Record<string, unknown> = {
  'heatmap-radius': 30,
  'heatmap-weight': 1,
  'heatmap-intensity': 1,
  'heatmap-color': buildHeatmapColorExpression(DEFAULT_RAMP),
  'heatmap-opacity': 0.8,
};

export const heatmapAdapter: LayerAdapter = {
  type: 'heatmap',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, sourceId, sourceLayer, paint: rawPaint, filter, opacity, visible } = input;
    const builder = getBuilderStyleConfig(input);

    // Extract heatmap-specific props from paint, falling back to defaults
    const heatmapRadius = rawPaint['heatmap-radius'] ?? 30;
    const heatmapWeight = rawPaint['heatmap-weight'] ?? 1;
    const heatmapIntensity = rawPaint['heatmap-intensity'] ?? 1;
    // Phase 1051 CR-04: read stored heatmap-opacity (matching syncPaint formula
    // at line 91) and compound with master opacity. Previously hard-coded 0.8 at
    // add-time, which overwrote persisted heatmap-opacity on every page load,
    // render-mode swap, or basemap switch — producing a visible flash and silent
    // drift until any subsequent paint sync. Mirrors the rawPaint['heatmap-*']
    // ?? default pattern used for radius/weight/intensity above.
    const storedHeatmapOpacity = (rawPaint['heatmap-opacity'] as number) ?? 0.8;
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

    // Sync only heatmap-* properties, skip custom props
    for (const [prop, val] of Object.entries(rawPaint)) {
      if (CUSTOM_PAINT_PROPS.has(prop)) continue;
      if (!prop.startsWith('heatmap-')) continue;
      try {
        const current = map.getPaintProperty(layerId, prop);
        if (paintValueChanged(current, val)) {
          map.setPaintProperty(layerId, prop, val);
        }
      } catch (e) {
        if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set ${prop} on ${layerId}:`, e);
      }
    }

    // Compound stored heatmap-opacity with master opacity
    const storedOpacity = (rawPaint['heatmap-opacity'] as number) ?? 0.8;
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
