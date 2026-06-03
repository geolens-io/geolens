import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AdapterLayerInput, LayerAdapter } from './types';
import { paintValueChanged } from './shared';

/** Default lower percentile bound for the raster stretch. Backend default is 2. */
const STRETCH_PMIN_DEFAULT = 2;
/** Default upper percentile bound for the raster stretch. Backend default is 98. */
const STRETCH_PMAX_DEFAULT = 98;
/** Default standard-deviation multiplier for stddev stretch. Backend default is 2. */
const STRETCH_SIGMA_DEFAULT = 2;

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

/**
 * The 4 user-facing raster paint properties exposed in RasterEditor.
 * Excludes raster-brightness-max (kept at default 1), raster-resampling,
 * raster-fade-duration (internal), and raster-opacity (routed separately
 * via buildRasterPaint). This is the single source of truth for which
 * properties the editor controls — no hard-coded keys outside this tuple.
 */
export const RASTER_OWNED_PAINT_PROPERTIES = [
  'raster-brightness-min',
  'raster-contrast',
  'raster-saturation',
  'raster-hue-rotate',
] as const;

/**
 * Build a raster tile URL with `colormap_name` and/or `stretch` query params.
 *
 * Called from syncRasterLayer BEFORE the tile-URL-diff comparison so that a
 * colormap or stretch change causes the existing source-teardown path to fire
 * and MapLibre re-fetches tiles with the new params.
 *
 * The `_colormap` and `_stretch` keys are builder-private paint keys (never
 * in RASTER_OWNED_PAINT_PROPERTIES — Pitfall 6) and mutate the tile URL, not
 * a MapLibre paint property.
 *
 * `colormap_name` is forwarded only for a non-gray colormap (gray is Titiler's
 * single-band default). `stretch` is forwarded independently of the colormap —
 * the api raster-proxy computes a stats-based rescale server-side that applies
 * to the grayscale render too, so `percentile`/`stddev` must work even when the
 * colormap is left at the default gray (RASTER-STRETCH-UI-02).
 *
 * Bound params follow the "only forward non-default" discipline:
 * - `pmin` / `pmax` are forwarded only when `_stretch === 'percentile'` AND the
 *   value is a finite number differing from its default (2 / 98). Each is
 *   forwarded independently, so one may be non-default while the other is omitted.
 * - `sigma` is forwarded only when `_stretch === 'stddev'` AND the value is a
 *   finite number differing from its default (2).
 * This ensures the default-case URL is byte-identical to prior behavior.
 *
 * `_pmin`, `_pmax`, and `_sigma` are builder-private paint keys (Pitfall 6) —
 * they must NOT appear in `RASTER_OWNED_PAINT_PROPERTIES`.
 *
 * @param baseUrl  Root-relative or absolute tile URL (e.g. `/api/raster-tiles/...`)
 * @param paint    The layer paint dict; reads `_colormap`, `_stretch`, `_pmin`,
 *                 `_pmax`, and `_sigma`.
 * @returns        `baseUrl` unmodified when no non-default params are set;
 *                 `baseUrl?<params>` otherwise (param order: colormap_name,
 *                 stretch, pmin, pmax, sigma).
 */
export function buildColormapTileUrl(
  baseUrl: string,
  paint: Record<string, unknown>,
): string {
  const colormap = paint['_colormap'];
  const stretch = paint['_stretch'];
  const params = new URLSearchParams();
  // gray is the Titiler single-band default — only forward a non-gray colormap.
  if (typeof colormap === 'string' && colormap && colormap !== 'gray') {
    params.set('colormap_name', colormap);
  }
  // minmax is the default (dtype) rescale; percentile/stddev compute a stats-based
  // rescale server-side that applies regardless of colormap — forward independently.
  if (typeof stretch === 'string' && stretch !== 'minmax') {
    params.set('stretch', stretch);
  }
  // Percentile bounds — forward each independently only when non-default.
  if (stretch === 'percentile') {
    const pmin = Number(paint['_pmin']);
    if (Number.isFinite(pmin) && pmin !== STRETCH_PMIN_DEFAULT) {
      params.set('pmin', String(pmin));
    }
    const pmax = Number(paint['_pmax']);
    if (Number.isFinite(pmax) && pmax !== STRETCH_PMAX_DEFAULT) {
      params.set('pmax', String(pmax));
    }
  }
  // Stddev sigma — forward only when non-default.
  if (stretch === 'stddev') {
    const sigma = Number(paint['_sigma']);
    if (Number.isFinite(sigma) && sigma !== STRETCH_SIGMA_DEFAULT) {
      params.set('sigma', String(sigma));
    }
  }
  const qs = params.toString();
  return qs ? `${baseUrl}?${qs}` : baseUrl;
}

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
    // WALK-R-05: split source guard from layer guard so that when a style swap
    // removes layers but retains sources (raster basemap reload scenario), the
    // layer is re-added without re-adding the already-existing source.
    if (!map.getSource(sourceId)) {
      const normalizedBounds = normalizeRasterBounds(bounds);
      map.addSource(sourceId, {
        type: 'raster',
        tiles: [`${window.location.origin}${tileUrl}`],
        tileSize: tileSize ?? 256,
        minzoom: minzoom ?? 0,
        maxzoom: maxzoom ?? 18,
        ...(normalizedBounds ? { bounds: normalizedBounds } : {}),
      });
    }
    if (map.getLayer(layerId)) return;
    // BUG-01: honor input.visible at initial add so callers that don't
    // immediately follow up with syncVisibility still produce a layer in the
    // correct visual state (mirrors fill/circle/heatmap/line adapter pattern).
    map.addLayer({
      id: layerId,
      type: 'raster',
      source: sourceId,
      paint: buildRasterPaint(input),
      ...(visible === false ? { layout: { visibility: 'none' as const } } : {}),
    });
    // Defense-in-depth: ensure visibility even if addLayer layout block is missed.
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
