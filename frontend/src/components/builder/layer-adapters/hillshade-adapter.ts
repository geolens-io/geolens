import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { normalizeRasterBounds, paintValueChanged, syncSingleLayerVisibility } from './shared';
import { DEFAULT_HILLSHADE_PAINT } from './builder-defaults';
import { COLOR_RELIEF_SUFFIX } from '../companion-ids';
import { MAP_COLORS } from '@/lib/map-colors';

// builder-audit #338 ADAPT-06: re-export the single hillshade default from builder-defaults
// (was a byte-identical local copy that diverged from renderAs's DEFAULT_HILLSHADE_PAINT).
export const HILLSHADE_PAINT_DEFAULTS = DEFAULT_HILLSHADE_PAINT;

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
  if (color.trim().toLowerCase() === 'transparent') return MAP_COLORS.transparent;
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
      // builder-audit #338 ADAPT-01: shared normalizeRasterBounds, computed once instead
      // of the prior double-call inside the spread ternary.
      const normalizedBounds = normalizeRasterBounds(bounds);
      map.addSource(sourceId, {
        type: 'raster-dem',
        tiles: [`${window.location.origin}${tileUrl}`],
        tileSize: tileSize ?? 256,
        minzoom: minzoom ?? 0,
        maxzoom: maxzoom ?? 18,
        ...(normalizedBounds ? { bounds: normalizedBounds } : {}),
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

    // builder-audit #338 ADAPT-09: reconcile visibility through the SAME shared helper the
    // vector adapters use, instead of a hand-rolled setLayoutProperty. syncRasterLayer
    // (map-sync) calls syncPaint without a following syncVisibility for the raster/DEM
    // path, so visibility must still be reconciled here — but now uniformly.
    syncSingleLayerVisibility(map, layerId, visible);
  },

  syncVisibility(map: MaplibreMap, input: AdapterLayerInput): void {
    syncSingleLayerVisibility(map, input.layerId, input.visible);
    // fix(#452): the hypso color-relief companion shares the raster-dem source
    // and must follow the DEM's visibility. The full sync path recreates it via
    // syncColorReliefLayer, but visibility-only diffs (the viewer legend's live
    // eye toggle) only call syncVisibility — without this the unshaded tint
    // kept painting after the DEM was hidden.
    syncSingleLayerVisibility(map, `${input.layerId}${COLOR_RELIEF_SUFFIX}`, input.visible);
  },

  getLayerIds(layerId: string): string[] {
    // fix(#452): the conditional color-relief companion belongs to this adapter;
    // consumers (zoom-range sync, teardown) must see it. syncSingleLayerVisibility
    // and removal both no-op when the companion doesn't exist.
    return [layerId, `${layerId}${COLOR_RELIEF_SUFFIX}`];
  },
};
