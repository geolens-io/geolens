import { Color } from '@maplibre/maplibre-gl-style-spec';
import type { AdapterLayerInput, LayerAdapter, LayerDrawing, LayerSpec } from './types';
import { normalizeRasterBounds, paintValueChanged } from './shared';
import { DEFAULT_HILLSHADE_PAINT } from './builder-defaults';
import { COLOR_RELIEF_SUFFIX } from '../companion-ids';
import { buildElevationExpression } from '../color-relief-sync';
import { writeDescribedLayer, writeDescribedVisibility } from '../layer-writer';
import { effectiveDemRenderMode } from '@/lib/dem-render-mode';
import { MAP_COLORS } from '@/lib/map-colors';

// Re-export the single hillshade default from builder-defaults.
export const HILLSHADE_PAINT_DEFAULTS = DEFAULT_HILLSHADE_PAINT;

type HillshadePaintProperty = keyof typeof HILLSHADE_PAINT_DEFAULTS;

export const HILLSHADE_EXAGGERATION_MIN = 0;
export const HILLSHADE_EXAGGERATION_MAX = 1;

export const HILLSHADE_PAINT_PROPERTIES = Object.keys(HILLSHADE_PAINT_DEFAULTS) as HillshadePaintProperty[];
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

function normalizeOpacity(value: number | null | undefined): number {
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value as number)) : 1;
}

function formatAlpha(value: number): string {
  return Number(value.toFixed(4)).toString();
}

/** The colour with its alpha multiplied by `opacity`, read by the same parser MapLibre paints with. */
function compoundColorAlpha(color: string, opacity: number): string {
  if (opacity === 1) return color;
  const parsed = Color.parse(color);
  if (!parsed) return color;
  if (parsed.a === 0) return MAP_COLORS.transparent;
  // Channels come back multiplied by alpha.
  const channel = (value: number) => Math.round((value / parsed.a) * 255);
  return `rgba(${channel(parsed.r)}, ${channel(parsed.g)}, ${channel(parsed.b)}, ${formatAlpha(parsed.a * opacity)})`;
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

export const COLOR_RELIEF_OWNED_PAINT_PROPERTIES = ['color-relief-color', 'color-relief-opacity'] as const;

/**
 * The hypsometric tint under a DEM's hillshade, when the layer turns it on. A new
 * ramp rebuilds it in a paint write that can run outside map-sync's zoom-range
 * pass, so it carries the layer's saved zoom range itself.
 */
function colorReliefSpec(input: AdapterLayerInput): LayerSpec | null {
  if (input.is_dem !== true || input.paint['_hypso-enabled'] !== true) return null;
  const ramp = input.paint['_hypso-ramp'];
  // A transient factor from a viewer fade; the saved paint never carries it.
  const fade = input.paint['_hypso-fade'];
  return {
    layer: {
      id: `${input.layerId}${COLOR_RELIEF_SUFFIX}`,
      type: 'color-relief',
      source: input.sourceId,
      ...(input.zoom ? { minzoom: input.zoom.minzoom, maxzoom: input.zoom.maxzoom } : {}),
      layout: { visibility: input.visible ? 'visible' : 'none' },
      paint: {
        'color-relief-color': buildElevationExpression(
          typeof ramp === 'string' ? ramp : 'Viridis',
          undefined,
          undefined,
          input.paint['_hypso-reversed'] === true,
        ),
        'color-relief-opacity': 0.7 * (typeof fade === 'number' ? fade : 1),
      },
    },
    ownedPaint: COLOR_RELIEF_OWNED_PAINT_PROPERTIES,
    ownedLayout: ['visibility'],
  };
}

/** The hillshade, and its colour relief below it when the layer turns one on. A terrain-mode DEM draws neither. */
function describeHillshade(input: AdapterLayerInput): LayerDrawing {
  if (effectiveDemRenderMode(input.style_config, input.is_dem) === 'terrain') return { specs: [], images: [] };
  const hillshade: LayerSpec = {
    layer: {
      id: input.layerId,
      type: 'hillshade',
      source: input.sourceId,
      layout: { visibility: input.visible ? 'visible' : 'none' },
      paint: buildHillshadePaint(input),
    },
    ownedPaint: HILLSHADE_PAINT_PROPERTIES,
    // map-sync's raster path calls syncPaint with no syncVisibility after it.
    ownedLayout: ['visibility'],
  };
  const relief = colorReliefSpec(input);
  return { specs: relief ? [relief, hillshade] : [hillshade], images: [] };
}

export const hillshadeAdapter: LayerAdapter = {
  type: 'hillshade',
  describe: describeHillshade,

  addLayers(map, input) {
    const { sourceId, tileUrl, tileSize, minzoom, maxzoom, bounds, attribution } = input;
    if (!map.getSource(sourceId)) {
      // Shared normalizeRasterBounds, computed once.
      const normalizedBounds = normalizeRasterBounds(bounds);
      map.addSource(sourceId, {
        type: 'raster-dem',
        tiles: [`${window.location.origin}${tileUrl}`],
        tileSize: tileSize ?? 256,
        minzoom: minzoom ?? 0,
        maxzoom: maxzoom ?? 18,
        ...(normalizedBounds ? { bounds: normalizedBounds } : {}),
        // The dataset's required credit line, read by
        // MapLibre's attribution control off the source it renders from.
        ...(attribution ? { attribution } : {}),
        encoding: 'mapbox',
      });
    }
    writeDescribedLayer(map, describeHillshade(input));
  },

  syncPaint(map, input) {
    if (!map.getLayer(input.layerId)) return;
    const drawing = describeHillshade(input);
    // setPaintProperty does not reliably rebuild the relief's colour-ramp texture, so a
    // new ramp removes the relief here and the write adds it back below the hillshade.
    // Each rebuild reloads the DEM source, so an unchanged relief stays in place.
    const reliefId = `${input.layerId}${COLOR_RELIEF_SUFFIX}`;
    const relief = drawing.specs.find(({ layer }) => layer.id === reliefId)?.layer;
    if (map.getLayer(reliefId)
      && (!relief || paintValueChanged(map.getPaintProperty(reliefId, 'color-relief-color'), relief.paint['color-relief-color']))) {
      map.removeLayer(reliefId);
    }
    writeDescribedLayer(map, drawing);
  },

  syncVisibility(map, input) {
    writeDescribedVisibility(map, describeHillshade(input));
  },

  getLayerIds(layerId: string): string[] {
    // The colour relief is conditional but belongs to this adapter, so zoom-range
    // sync and teardown see it; both skip it when it is not on the map.
    return [layerId, `${layerId}${COLOR_RELIEF_SUFFIX}`];
  },
};
