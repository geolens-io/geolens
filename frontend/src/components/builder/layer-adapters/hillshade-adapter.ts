import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { paintValueChanged } from './shared';

export const HILLSHADE_PAINT_DEFAULTS = {
  'hillshade-illumination-direction': 335,
  'hillshade-illumination-anchor': 'viewport',
  'hillshade-exaggeration': 0.5,
  'hillshade-shadow-color': '#000000',
  'hillshade-highlight-color': '#ffffff',
  'hillshade-accent-color': '#000000',
} as const;

type HillshadePaintProperty = keyof typeof HILLSHADE_PAINT_DEFAULTS;

const HILLSHADE_PAINT_PROPERTIES = Object.keys(HILLSHADE_PAINT_DEFAULTS) as HillshadePaintProperty[];

function getSupportedHillshadePaint(
  paint: Record<string, unknown>,
): Partial<Record<HillshadePaintProperty, number | string>> {
  const nextPaint: Partial<Record<HillshadePaintProperty, number | string>> = {};
  for (const property of HILLSHADE_PAINT_PROPERTIES) {
    const value = paint[property];
    if (property === 'hillshade-illumination-anchor') {
      if (value === 'map' || value === 'viewport') {
        nextPaint[property] = value;
      }
      continue;
    }
    if (property.endsWith('-color')) {
      if (typeof value === 'string') {
        nextPaint[property] = value;
      }
      continue;
    }
    if (typeof value === 'number') {
      nextPaint[property] = value;
    }
  }
  return nextPaint;
}

function hasHillshadePaintValue(
  paint: Partial<Record<HillshadePaintProperty, number | string>>,
  property: HillshadePaintProperty,
): boolean {
  return Object.prototype.hasOwnProperty.call(paint, property);
}

function buildHillshadePaint(input: AdapterLayerInput): Record<string, number | string> {
  return {
    ...HILLSHADE_PAINT_DEFAULTS,
    ...getSupportedHillshadePaint(input.paint),
  };
}

export const hillshadeAdapter: LayerAdapter = {
  type: 'hillshade',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, sourceId, tileUrl, tileSize, minzoom, maxzoom, visible } = input;
    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, {
        type: 'raster-dem',
        tiles: [`${window.location.origin}${tileUrl}`],
        tileSize: tileSize ?? 256,
        minzoom: minzoom ?? 0,
        maxzoom: maxzoom ?? 18,
        encoding: 'mapbox',
      });
    }
    if (!map.getLayer(layerId)) {
      map.addLayer({
        id: layerId,
        type: 'hillshade',
        source: sourceId,
        paint: buildHillshadePaint(input),
      });
    }
    if (!visible) {
      map.setLayoutProperty(layerId, 'visibility', 'none');
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, visible } = input;
    if (!map.getLayer(layerId)) return;

    const supportedPaint = getSupportedHillshadePaint(input.paint);
    for (const property of HILLSHADE_PAINT_PROPERTIES) {
      const current = map.getPaintProperty(layerId, property);
      const desired = hasHillshadePaintValue(supportedPaint, property)
        ? supportedPaint[property]
        : HILLSHADE_PAINT_DEFAULTS[property];
      if ((hasHillshadePaintValue(supportedPaint, property) || current !== undefined) && paintValueChanged(current, desired)) {
        map.setPaintProperty(layerId, property, desired);
      }
    }

    const vis = visible ? 'visible' : 'none';
    if (map.getLayoutProperty(layerId, 'visibility') !== vis) {
      map.setLayoutProperty(layerId, 'visibility', vis);
    }
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, visible } = input;
    const vis = visible ? 'visible' : 'none';
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, 'visibility', vis);
    }
  },

  getLayerIds(layerId: string): string[] {
    return [layerId];
  },
};
