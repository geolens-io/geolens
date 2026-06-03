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

export const HILLSHADE_EXAGGERATION_MIN = 0;
export const HILLSHADE_EXAGGERATION_MAX = 1;

const HILLSHADE_PAINT_PROPERTIES = Object.keys(HILLSHADE_PAINT_DEFAULTS) as HillshadePaintProperty[];
const HILLSHADE_COLOR_PROPERTIES = [
  'hillshade-shadow-color',
  'hillshade-highlight-color',
  'hillshade-accent-color',
] as const;

export function normalizeHillshadeExaggeration(value: number | null | undefined): number {
  if (!Number.isFinite(value)) return HILLSHADE_PAINT_DEFAULTS['hillshade-exaggeration'];
  return Math.min(Math.max(value as number, HILLSHADE_EXAGGERATION_MIN), HILLSHADE_EXAGGERATION_MAX);
}

function normalizeRasterBounds(bounds: number[] | null | undefined) {
  if (!Array.isArray(bounds) || bounds.length !== 4) return undefined;
  if (!bounds.every((value) => Number.isFinite(value))) return undefined;
  return [bounds[0], bounds[1], bounds[2], bounds[3]] as [number, number, number, number];
}

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
    if (typeof value === 'number' && Number.isFinite(value)) {
      nextPaint[property] = property === 'hillshade-exaggeration'
        ? normalizeHillshadeExaggeration(value)
        : value;
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

function normalizeOpacity(value: number | null | undefined): number {
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value as number)) : 1;
}

function formatAlpha(value: number): string {
  return Number(value.toFixed(4)).toString();
}

function compoundHexColorAlpha(color: string, opacity: number): string | null {
  const hex = color.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i)?.[1];
  if (!hex) return null;

  const expand = (value: string) => value.length === 1 ? `${value}${value}` : value;
  const hasShortChannels = hex.length === 3 || hex.length === 4;
  const red = parseInt(expand(hasShortChannels ? hex[0] : hex.slice(0, 2)), 16);
  const green = parseInt(expand(hasShortChannels ? hex[1] : hex.slice(2, 4)), 16);
  const blue = parseInt(expand(hasShortChannels ? hex[2] : hex.slice(4, 6)), 16);
  const alphaHex = hasShortChannels ? hex[3] : hex.slice(6, 8);
  const baseAlpha = alphaHex ? parseInt(expand(alphaHex), 16) / 255 : 1;
  return `rgba(${red}, ${green}, ${blue}, ${formatAlpha(baseAlpha * opacity)})`;
}

function compoundRgbColorAlpha(color: string, opacity: number): string | null {
  const match = color.trim().match(/^rgba?\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)(?:\s*,\s*([0-9.]+)\s*)?\)$/i);
  if (!match) return null;
  const red = Number(match[1]);
  const green = Number(match[2]);
  const blue = Number(match[3]);
  if (![red, green, blue].every(Number.isFinite)) return null;
  const baseAlpha = match[4] === undefined ? 1 : Number(match[4]);
  if (!Number.isFinite(baseAlpha)) return null;
  return `rgba(${red}, ${green}, ${blue}, ${formatAlpha(Math.min(1, Math.max(0, baseAlpha)) * opacity)})`;
}

function compoundColorAlpha(color: string, opacity: number): string {
  if (opacity === 1) return color;
  if (color.trim().toLowerCase() === 'transparent') return 'rgba(0, 0, 0, 0)';
  return compoundHexColorAlpha(color, opacity)
    ?? compoundRgbColorAlpha(color, opacity)
    ?? color;
}

function buildHillshadePaint(input: AdapterLayerInput): Record<string, number | string> {
  const opacity = normalizeOpacity(input.opacity);
  const paint = {
    ...HILLSHADE_PAINT_DEFAULTS,
    ...getSupportedHillshadePaint(input.paint),
  };
  for (const property of HILLSHADE_COLOR_PROPERTIES) {
    const color = paint[property];
    if (typeof color === 'string') {
      paint[property] = compoundColorAlpha(color, opacity);
    }
  }
  return paint;
}

export const hillshadeAdapter: LayerAdapter = {
  type: 'hillshade',

  addLayers(map: MaplibreMap, input: AdapterLayerInput): void {
    const { layerId, sourceId, tileUrl, tileSize, minzoom, maxzoom, visible, bounds } = input;
    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, {
        type: 'raster-dem',
        tiles: [`${window.location.origin}${tileUrl}`],
        tileSize: tileSize ?? 256,
        minzoom: minzoom ?? 0,
        maxzoom: maxzoom ?? 18,
        ...(normalizeRasterBounds(bounds) ? { bounds: normalizeRasterBounds(bounds) } : {}),
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
    const desiredPaint = buildHillshadePaint(input);
    const hasOpacityOverride = normalizeOpacity(input.opacity) !== 1;
    for (const property of HILLSHADE_PAINT_PROPERTIES) {
      const current = map.getPaintProperty(layerId, property);
      const desired = desiredPaint[property];
      const shouldSync = hasHillshadePaintValue(supportedPaint, property)
        || current !== undefined
        || (hasOpacityOverride && HILLSHADE_COLOR_PROPERTIES.includes(property as typeof HILLSHADE_COLOR_PROPERTIES[number]));
      if (shouldSync && paintValueChanged(current, desired)) {
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
