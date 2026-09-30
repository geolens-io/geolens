import type { AddLayerObject, FilterSpecification, Map as MaplibreMap } from 'maplibre-gl';
import {
  setDynamicLayoutProperty,
  setDynamicPaintProperty,
  simplifyPaint,
  syncOwnedLayoutProperties,
  syncOwnedPaintProperties,
} from './layer-adapters/shared';
import { FULL_ZOOM_RANGE } from './layer-adapters/builder-defaults';
import type { ZoomRange } from './layer-description';
import type { ImageSpec, LayerDrawing, LayerSpec } from './layer-adapters/types';

/** The map calls a write makes. A MapLibre map provides them, and so does the recording fake in the tests. */
export type LayerWriteTarget = Pick<
  MaplibreMap,
  | 'removeLayer'
  | 'getLayer'
  | 'addLayer'
  | 'getFilter'
  | 'setFilter'
  | 'getPaintProperty'
  | 'setPaintProperty'
  | 'getLayoutProperty'
  | 'setLayoutProperty'
  | 'setLayerZoomRange'
  | 'hasImage'
  | 'addImage'
  | 'getSprite'
  | 'addSprite'
>;

/** Paint keys MapLibre accepts only as an expression, so no scalar can stand in for one. */
const EXPRESSION_ONLY_PAINT = new Set(['heatmap-color', 'line-gradient', 'color-relief-color']);

function hasFilter(filter: FilterSpecification | undefined): filter is FilterSpecification {
  return Array.isArray(filter) && filter.length > 0;
}

/** A URL resolved against the page, since MapLibre fetches a sprite sheet itself. */
function pageUrl(url: string): string {
  return typeof window !== 'undefined' && window.location?.origin
    ? new URL(url, window.location.origin).toString()
    : url;
}

function registerImage(map: LayerWriteTarget, image: ImageSpec): void {
  try {
    if (image.kind === 'sprite') {
      if ((map.getSprite?.() ?? []).some((sprite) => sprite.id === image.id)) return;
      map.addSprite(image.id, pageUrl(image.url));
    } else if (!map.hasImage?.(image.id)) {
      map.addImage(image.id, image.data(), image.options);
    }
  } catch (e) {
    if (import.meta.env.DEV) console.warn(`[map-sync] registering image ${image.id} failed:`, e);
  }
}

/** The paint to add a layer with: each array swapped for its scalar fallback, or left out when it has none. */
function standInPaint(paint: Record<string, unknown>): Record<string, unknown> {
  const simplified = simplifyPaint(paint);
  return Object.fromEntries(Object.entries(simplified).filter(([key, value]) =>
    value !== undefined && !(EXPRESSION_ONLY_PAINT.has(key) && Array.isArray(paint[key]))));
}

function reconcilePaint(map: LayerWriteTarget, spec: LayerSpec): void {
  syncOwnedPaintProperties(map, spec.layer.id, spec.layer.paint, { ownedProperties: spec.ownedPaint });
}

/**
 * MapLibre validates a layer as a whole, so one expression it rejects would lose
 * the layer. It goes on with scalar stand-ins, and the arrays and the filter
 * follow as separate writes that can fail on their own.
 */
function addSpec(map: LayerWriteTarget, spec: LayerSpec, beforeId: string | undefined): void {
  const { filter, ...layer } = spec.layer;
  map.addLayer({ ...layer, paint: standInPaint(layer.paint) } as AddLayerObject, beforeId);
  if (!map.getLayer(layer.id)) return;
  const owned = new Set<string>(spec.ownedPaint);
  for (const [key, value] of Object.entries(layer.paint)) {
    if (!Array.isArray(value) || owned.has(key)) continue;
    try {
      setDynamicPaintProperty(map, layer.id, key, value);
    } catch (e) {
      if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set ${key} on ${layer.id}:`, e);
    }
  }
  reconcilePaint(map, spec);
  if (hasFilter(filter)) map.setFilter(layer.id, filter);
}

/** MapLibre's maximum zoom for a layer that sets none. */
export const DEFAULT_LAYER_MAXZOOM = 24;

function updateSpec(map: LayerWriteTarget, spec: LayerSpec): void {
  const { id, layout, filter, minzoom, maxzoom } = spec.layer;
  reconcilePaint(map, spec);
  syncOwnedLayoutProperties(map, id, layout, { ownedProperties: spec.ownedLayout });
  // MapLibre reloads the source even when it clears a filter the layer never had.
  if (hasFilter(filter)) map.setFilter(id, filter);
  else if (map.getFilter(id)) map.setFilter(id, null);
  if (minzoom !== undefined || maxzoom !== undefined) {
    map.setLayerZoomRange(id, minzoom ?? 0, maxzoom ?? DEFAULT_LAYER_MAXZOOM);
  }
}

/**
 * Write each spec in order. A spec the map lacks goes below the next spec of the
 * drawing already on the map, so a layer added back keeps its place in the drawing.
 */
function writeSpecs(
  map: LayerWriteTarget,
  drawing: LayerDrawing,
  write: (spec: LayerSpec, beforeId: string | undefined) => void,
): void {
  for (const image of drawing.images) registerImage(map, image);
  drawing.specs.forEach((spec, index) => {
    const beforeId = drawing.specs.slice(index + 1).find(({ layer }) => map.getLayer(layer.id))?.layer.id;
    try {
      write(spec, beforeId);
    } catch (e) {
      if (import.meta.env.DEV) console.warn(`[map-sync] writing ${spec.layer.id} failed:`, e);
    }
  });
}

/**
 * Register the drawing's images, add each spec the map lacks, and bring the
 * owned keys and filter of every other spec in step with it. Prospective owned
 * layer IDs also retire companions absent from the drawing.
 */
export function writeDescribedLayer(
  map: LayerWriteTarget,
  drawing: LayerDrawing,
  ownedLayerIds: readonly string[] = [],
): void {
  retireAbsentLayers(map, drawing, ownedLayerIds);
  writeSpecs(map, drawing, (spec, beforeId) => (map.getLayer(spec.layer.id) ? updateSpec(map, spec) : addSpec(map, spec, beforeId)));
}

/** Register the drawing's images and add every spec, for a caller that has removed the old layers. */
export function addDescribedLayer(map: LayerWriteTarget, drawing: LayerDrawing): void {
  writeSpecs(map, drawing, (spec, beforeId) => addSpec(map, spec, beforeId));
}

/** Set the visibility of each spec already on the map, leaving the rest of the layer alone. */
export function writeDescribedVisibility(
  map: Pick<MaplibreMap, 'getLayer' | 'setLayoutProperty'>,
  drawing: LayerDrawing,
): void {
  for (const { layer } of drawing.specs) {
    const { visibility } = layer.layout;
    if (visibility !== undefined && map.getLayer(layer.id)) {
      setDynamicLayoutProperty(map, layer.id, 'visibility', visibility);
    }
  }
}

/** Remove the owned map layers that the drawing no longer describes. */
function retireAbsentLayers(
  map: Pick<MaplibreMap, 'getLayer' | 'removeLayer'>,
  drawing: LayerDrawing,
  ownedLayerIds: readonly string[],
): void {
  const desired = new Set(drawing.specs.map(({ layer }) => layer.id));
  removeDescribedLayers(map, ownedLayerIds.filter((id) => !desired.has(id)));
}

/** Remove the prospective drawing layers, including companions absent from its current specs. */
export function removeDescribedLayers(
  map: Pick<MaplibreMap, 'getLayer' | 'removeLayer'>,
  ownedLayerIds: readonly string[],
): void {
  for (const id of ownedLayerIds) {
    if (map.getLayer(id)) map.removeLayer(id);
  }
}

/** Finish a drawing without replaying paint: retire absent companions, apply zooms and visibility. */
export function finishDescribedLayer(
  map: Pick<MaplibreMap, 'getLayer' | 'removeLayer' | 'setLayerZoomRange' | 'setLayoutProperty'>,
  drawing: LayerDrawing,
  ownedLayerIds: readonly string[],
  savedZoom: ZoomRange | null,
): void {
  retireAbsentLayers(map, drawing, ownedLayerIds);
  // Raster drawings without a saved range retain MapLibre's native maximum zoom.
  const raster = drawing.specs.some(({ layer }) => layer.type === 'raster' || layer.type === 'hillshade');
  const zoom = savedZoom ?? (raster ? null : FULL_ZOOM_RANGE);
  for (const { layer: spec } of drawing.specs) {
    const layer = map.getLayer(spec.id);
    if (!layer) continue;
    if (zoom) {
      map.setLayerZoomRange(spec.id, spec.minzoom ?? zoom.minzoom, spec.maxzoom ?? zoom.maxzoom);
    } else if ((layer.minzoom ?? 0) > 0 || (layer.maxzoom ?? DEFAULT_LAYER_MAXZOOM) < DEFAULT_LAYER_MAXZOOM) {
      map.setLayerZoomRange(spec.id, 0, DEFAULT_LAYER_MAXZOOM);
    }
  }
  writeDescribedVisibility(map, drawing);
}
