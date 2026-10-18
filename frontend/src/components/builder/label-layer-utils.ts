import { MAP_COLORS } from '@/lib/map-colors';
import type { LabelConfig } from '@/types/api';
import type { AddLayerObject, Map as MaplibreMap } from 'maplibre-gl';
import {
  filterSpec,
  getLayerType,
  setDynamicLayoutProperty,
  setDynamicPaintProperty,
  sourceLayerSpec,
} from './layer-adapters/shared';
import type { AdapterLayerInput, LayerDrawing, LayerSpec } from './layer-adapters/types';

export const LABEL_FONT_STACK = [
  'Noto Sans Regular',
] as const;

/**
 * The offset a point label renders at when the user hasn't set one. Editor and
 * renderer both read this constant; if the renderer applied it implicitly while
 * the editor showed 0/0, the first X-drag would silently discard the -1.5 Y.
 */
export const DEFAULT_POINT_LABEL_OFFSET: [number, number] = [0, -1.5];

/** Resolve symbol-placement, enforcing point-only for fill geometries. */
function resolvePlacement(
  lc: Pick<LabelConfig, 'placement'>,
  geomType: string,
): 'point' | 'line' | 'line-center' {
  let placement = lc.placement ?? (geomType === 'line' ? 'line' : 'point');
  if (geomType === 'fill' && placement !== 'point') placement = 'point';
  return placement;
}

/**
 * The single canonical {layout, paint} mapping for a label layer, derived from
 * `LabelConfig` + geometry. `buildLabelLayerSpec` (add path) and
 * `syncLabelLayer` (update path) both consume this one object, so the GL
 * property list and its defaults exist once and a new label property reaches
 * both.
 *
 * `text-anchor`/`text-offset` are always present. For point placement they
 * carry the configured value; for line/line-center placement they are pinned to
 * the neutral `center` / `[0, 0]` so the update path resets them when a layer
 * leaves point placement (MapLibre keeps the previous value otherwise). On the
 * add path these equal MapLibre's defaults.
 */
export function buildLabelStyle(
  lc: LabelConfig,
  geomType: string,
  visibility?: 'visible' | 'none',
): { layout: Record<string, unknown>; paint: Record<string, unknown>; placement: 'point' | 'line' | 'line-center' } {
  const placement = resolvePlacement(lc, geomType);
  const layout: Record<string, unknown> = {
    'text-field': ['get', lc.column],
    'text-size': lc.fontSize ?? 12,
    'symbol-placement': placement,
    'text-allow-overlap': lc.allowOverlap ?? false,
    'text-font': [...LABEL_FONT_STACK],
    'text-max-width': 10,
    'text-anchor': placement === 'point' ? (lc.textAnchor ?? 'center') : 'center',
    'text-offset': placement === 'point'
      ? (lc.textOffset ?? (geomType === 'circle' ? DEFAULT_POINT_LABEL_OFFSET : [0, 0]))
      : [0, 0],
  };
  if (geomType === 'fill') layout['symbol-avoid-edges'] = true;
  if (visibility) layout['visibility'] = visibility;

  const paint: Record<string, unknown> = {
    'text-color': lc.textColor ?? MAP_COLORS.label.color,
    'text-halo-color': lc.haloColor ?? MAP_COLORS.label.halo,
    'text-halo-width': lc.haloWidth ?? 1.5,
    'text-opacity': lc.textOpacity ?? 1,
  };
  return { layout, paint, placement };
}

/**
 * Build a MapLibre addLayer spec for a symbol/label layer, shared across
 * map-sync.ts, use-builder-layers.ts and ViewerMap.tsx.
 */
export function buildLabelLayerSpec(opts: {
  labelId: string;
  sourceId: string;
  sourceLayer: string;
  lc: LabelConfig;
  geomType: string;
  visibility?: 'visible' | 'none';
}): AddLayerObject {
  const { labelId, sourceId, sourceLayer, lc, geomType, visibility } = opts;
  const { layout, paint } = buildLabelStyle(lc, geomType, visibility);

  return {
    id: labelId,
    type: 'symbol',
    source: sourceId,
    'source-layer': sourceLayer,
    minzoom: lc.minZoom ?? 0,
    maxzoom: lc.maxZoom ?? 22,
    layout,
    paint,
  } as AddLayerObject;
}

/**
 * Apply label layout/paint properties to an existing label layer, shared across
 * map-sync.ts, use-builder-layers.ts and ViewerMap.tsx. Iterates the same
 * canonical {layout, paint} object `buildLabelLayerSpec` spreads, so add and
 * update stay in lockstep.
 */
export function syncLabelLayer(
  // Derived from the real Map type: maplibre-gl v6 made
  // setPaintProperty/setLayoutProperty generic, and a generic method isn't
  // assignable to a plain one, so a live Map stopped satisfying a hand-written
  // shape. `Pick` keeps the contract as narrow as what this function touches
  // (so tests can pass a plain mock) with the Map as the source of the
  // signatures.
  map: Pick<MaplibreMap, 'setLayoutProperty' | 'setPaintProperty' | 'setLayerZoomRange'>,
  labelId: string,
  lc: LabelConfig,
  geomType: string,
) {
  const { layout, paint } = buildLabelStyle(lc, geomType);
  for (const [prop, value] of Object.entries(layout)) {
    setDynamicLayoutProperty(map, labelId, prop, value);
  }
  for (const [prop, value] of Object.entries(paint)) {
    setDynamicPaintProperty(map, labelId, prop, value);
  }
  map.setLayerZoomRange(labelId, lc.minZoom ?? 0, lc.maxZoom ?? 22);
}

/** The label companion's id for a layer, matching the arrow companion's
 *  `${layerId}-arrow` convention (both equal what `getCompanionLayerIds`
 *  derives, since `input.layerId` is already its prefixed `layer` id). */
export function labelLayerId(layerId: string): string {
  return `${layerId}-label`;
}

// 'visibility' is absent on purpose: syncPaint's owned-layout reconciliation
// runs from an input a coalesced write can carry stale, and visibility must not
// roll back to it. writeDescribedVisibility is the only writer of this layer's
// visibility after the initial add, as for every other family.
const LABEL_OWNED_LAYOUT_PROPERTIES = [
  'text-field',
  'text-size',
  'symbol-placement',
  'text-allow-overlap',
  'text-font',
  'text-max-width',
  'text-anchor',
  'text-offset',
  'symbol-avoid-edges',
] as const;

const LABEL_OWNED_PAINT_PROPERTIES = [
  'text-color',
  'text-halo-color',
  'text-halo-width',
  'text-opacity',
] as const;

/**
 * The label companion spec for a layer, or null when it has none. Symbol
 * carries its own inline text and heatmap has no per-feature labels, so neither
 * calls `withLabelCompanion`. The zoom range comes from the label config
 * through the writer's minzoom/maxzoom.
 */
function labelSpec(input: AdapterLayerInput): LayerSpec | null {
  const lc = input.label_config;
  if (!lc?.column) return null;
  const geomType = getLayerType(input.dataset_geometry_type);
  const { layout, paint } = buildLabelStyle(lc, geomType, input.visible ? 'visible' : 'none');
  return {
    layer: {
      id: labelLayerId(input.layerId),
      type: 'symbol',
      source: input.sourceId,
      ...sourceLayerSpec(input),
      ...filterSpec(input.filter),
      layout,
      paint,
      minzoom: lc.minZoom ?? 0,
      maxzoom: lc.maxZoom ?? 22,
    },
    ownedPaint: LABEL_OWNED_PAINT_PROPERTIES,
    ownedLayout: LABEL_OWNED_LAYOUT_PROPERTIES,
  };
}

/** Append a labelled family's label spec to its own drawing, or return the
 *  drawing unchanged when the layer has none. Call it last in `describe()`, so
 *  the label renders on top (bottom-first spec order) and `addLayers`/
 *  `syncPaint`/`syncVisibility` carry it. */
export function withLabelCompanion(input: AdapterLayerInput, drawing: LayerDrawing): LayerDrawing {
  const spec = labelSpec(input);
  return spec ? { specs: [...drawing.specs, spec], images: drawing.images } : drawing;
}
