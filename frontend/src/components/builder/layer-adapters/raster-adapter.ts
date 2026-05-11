import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { paintValueChanged } from './shared';

export const RASTER_PAINT_DEFAULTS = {
  'raster-brightness-min': 0,
  'raster-brightness-max': 1,
  'raster-contrast': 0,
  'raster-saturation': 0,
  'raster-hue-rotate': 0,
  'raster-resampling': 'linear',
  'raster-fade-duration': 300,
} as const;

type RasterPaintProperty = keyof typeof RASTER_PAINT_DEFAULTS;

const RASTER_PAINT_PROPERTIES = Object.keys(RASTER_PAINT_DEFAULTS) as RasterPaintProperty[];

function normalizeRasterBounds(bounds: number[] | null | undefined) {
  if (!Array.isArray(bounds) || bounds.length !== 4) return undefined;
  if (!bounds.every((value) => Number.isFinite(value))) return undefined;
  return [bounds[0], bounds[1], bounds[2], bounds[3]] as [number, number, number, number];
}

function buildRasterPaint(input: AdapterLayerInput): Record<string, number | string> {
  return {
    ...getSupportedRasterPaint(input.paint),
    'raster-opacity': input.opacity ?? 1,
  };
}

function getSupportedRasterPaint(paint: Record<string, unknown>): Partial<Record<RasterPaintProperty, number | string>> {
  const nextPaint: Partial<Record<RasterPaintProperty, number | string>> = {};
  for (const property of RASTER_PAINT_PROPERTIES) {
    const value = paint[property];
    if (property === 'raster-resampling') {
      if (value === 'linear' || value === 'nearest') {
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

function hasRasterPaintValue(
  paint: Partial<Record<RasterPaintProperty, number | string>>,
  property: RasterPaintProperty,
): boolean {
  return Object.prototype.hasOwnProperty.call(paint, property);
}

export const rasterAdapter: LayerAdapter = {
  type: 'raster',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, sourceId, tileUrl, tileSize, minzoom, maxzoom, visible, bounds } = input;
    if (map.getSource(sourceId)) return;
    map.addSource(sourceId, {
      type: 'raster',
      tiles: [`${window.location.origin}${tileUrl}`],
      tileSize: tileSize ?? 256,
      minzoom: minzoom ?? 0,
      maxzoom: maxzoom ?? 18,
      ...(normalizeRasterBounds(bounds) ? { bounds: normalizeRasterBounds(bounds) } : {}),
    });
    map.addLayer({
      id: layerId,
      type: 'raster',
      source: sourceId,
      paint: buildRasterPaint(input),
    });
    if (!visible) {
      map.setLayoutProperty(layerId, 'visibility', 'none');
    }
  },

  syncPaint(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, opacity, visible } = input;
    if (!map.getLayer(layerId)) return;

    const supportedPaint = getSupportedRasterPaint(input.paint);
    for (const property of RASTER_PAINT_PROPERTIES) {
      const current = map.getPaintProperty(layerId, property);
      const desired = hasRasterPaintValue(supportedPaint, property)
        ? supportedPaint[property]
        : RASTER_PAINT_DEFAULTS[property];
      if ((hasRasterPaintValue(supportedPaint, property) || current !== undefined) && paintValueChanged(current, desired)) {
        map.setPaintProperty(layerId, property, desired);
      }
    }

    const currentOpacity = map.getPaintProperty(layerId, 'raster-opacity');
    if (currentOpacity !== (opacity ?? 1)) {
      map.setPaintProperty(layerId, 'raster-opacity', opacity ?? 1);
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
