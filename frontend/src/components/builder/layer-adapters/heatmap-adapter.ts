import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { CUSTOM_PAINT_PROPS, paintValueChanged, syncSingleLayerVisibility } from './shared';
import { getRampColors } from '@/lib/color-ramps';

/** Build the default heatmap-color interpolation expression using a named ramp.
 *  The expression has transparent (rgba 0,0,0,0) at density 0 so low-density
 *  areas are fully transparent. */
export function buildHeatmapColorExpression(rampName: string): unknown[] {
  const colors = getRampColors(rampName, 6);
  return [
    'interpolate', ['linear'], ['heatmap-density'],
    0,   'rgba(0,0,0,0)',
    0.2, colors[1],
    0.4, colors[2],
    0.6, colors[3],
    0.8, colors[4],
    1.0, colors[5],
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
  '_heatmap-ramp': DEFAULT_RAMP,
};

export const heatmapAdapter: LayerAdapter = {
  type: 'heatmap',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, sourceId, sourceLayer, paint: rawPaint, filter, opacity } = input;

    // Extract heatmap-specific props from paint, falling back to defaults
    const heatmapRadius = rawPaint['heatmap-radius'] ?? 30;
    const heatmapWeight = rawPaint['heatmap-weight'] ?? 1;
    const heatmapIntensity = rawPaint['heatmap-intensity'] ?? 1;
    const heatmapOpacity = (opacity ?? 1) * 0.8;

    // Use stored color expression or build the default
    const heatmapColor: unknown = rawPaint['heatmap-color'] ?? buildHeatmapColorExpression(DEFAULT_RAMP);

    try {
      map.addLayer({
        id: layerId,
        type: 'heatmap',
        source: sourceId,
        'source-layer': sourceLayer,
        paint: {
          'heatmap-radius': heatmapRadius,
          'heatmap-weight': heatmapWeight,
          'heatmap-intensity': heatmapIntensity,
          'heatmap-color': heatmapColor,
          'heatmap-opacity': heatmapOpacity,
        } as Record<string, unknown>,
      });

      if (filter && Array.isArray(filter) && filter.length > 0) {
        map.setFilter(layerId, filter);
      }
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

    if (filter && Array.isArray(filter) && filter.length > 0) {
      map.setFilter(layerId, filter);
    } else {
      map.setFilter(layerId, null);
    }
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    syncSingleLayerVisibility(map, input.layerId, input.visible);
  },

  getLayerIds(layerId: string): string[] {
    return [layerId];
  },
};
