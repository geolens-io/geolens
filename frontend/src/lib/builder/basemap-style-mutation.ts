/**
 * Basemap sublayer override application helper (Phase 1059 BSE-01).
 *
 * Exports `applySublayerOverrides(map, overrides, sourcePrefix?)` — a pure
 * function that imperatively applies per-sublayer style overrides to a live
 * MapLibre map. Called from BuilderMap.tsx (on style load + on override change)
 * and ViewerMap.tsx (on style load, read-only).
 *
 * Uses `map.setPaintProperty` and `map.setLayerZoomRange` directly per the
 * project's @vis.gl/react-maplibre v8 imperative pattern memory (declarative
 * <Layer> props are silently ignored for basemap layers).
 *
 * Implements the idle-retry pattern from `project_maplibre_idle_retry_pattern.md`
 * so fresh-add scenarios where `map.isStyleLoaded()` returns false do not
 * silently drop overrides.
 */
import type { Map as MaplibreMap, StyleSpecification } from 'maplibre-gl';
import type { MapSublayerOverride } from '@/types/api';
import {
  SUBLAYER_CLASSIFIERS,
  type StyleLayer,
} from '@/lib/basemap-utils';

// Mirror frontend/src/lib/basemap-utils.ts OPACITY_PAINT_KEYS_BY_TYPE.
// Plan B duplicates this table rather than exporting it from basemap-utils
// because the helper applies per-sublayer opacity, not master opacity, and
// the semantics differ (no prominence stamps to compose).
const OPACITY_PAINT_KEYS_BY_TYPE: Record<string, readonly string[]> = {
  raster: ['raster-opacity'],
  fill: ['fill-opacity'],
  'fill-extrusion': ['fill-extrusion-opacity'],
  line: ['line-opacity'],
  symbol: ['text-opacity', 'icon-opacity'],
  circle: ['circle-opacity'],
  heatmap: ['heatmap-opacity'],
};

/**
 * Apply per-sublayer style overrides to a live MapLibre map.
 *
 * @param map - MapLibre map instance (must have a loaded style for mutations to apply).
 * @param overrides - Record mapping sublayer ID → override object. Null/undefined/empty = no-op.
 * @param sourcePrefix - Optional source prefix used to scope mutations to basemap-owned
 *   layers only (pass VIEWER_SOURCE_PREFIX in viewer contexts). When undefined, all
 *   classified basemap layers are targeted (appropriate for builder context).
 *
 * Order of operations per D-07: this helper is called AFTER `applyBasemapConfigToMap`
 * so sublayer-specific overrides sit on top of visibility-mode mutations. If a layer is
 * hidden by visibility mode the override still updates paint but the layer stays invisible.
 */
export function applySublayerOverrides(
  map: MaplibreMap,
  overrides: Record<string, MapSublayerOverride> | null | undefined,
  sourcePrefix?: string,
): void {
  if (!overrides || Object.keys(overrides).length === 0) return;

  // Idle-retry: project_maplibre_idle_retry_pattern.md
  // Without this recovery, fresh-add scenarios (basemap style not yet loaded)
  // silently drop all overrides on first paint — the SP-03 B-01-followup bug shape.
  if (!map.isStyleLoaded()) {
    const retry = () => applySublayerOverrides(map, overrides, sourcePrefix);
    map.once('idle', retry);
    return;
  }

  const style = map.getStyle() as StyleSpecification | undefined;
  if (!style?.layers) return;

  for (const [sublayerId, override] of Object.entries(overrides)) {
    const classifier = SUBLAYER_CLASSIFIERS[sublayerId];
    if (!classifier) continue; // opaque key set; unknown ID = no-op per D-01

    for (const layer of style.layers) {
      const styleLayer = layer as StyleLayer;
      if (!classifier(styleLayer)) continue;

      // sourcePrefix scoping: when a prefix is provided (viewer context), skip layers
      // whose source is a string NOT starting with the prefix. Background layers and
      // layers without a string source always pass through (they are basemap-owned).
      if (
        sourcePrefix &&
        typeof styleLayer.source === 'string' &&
        styleLayer.source.startsWith(sourcePrefix)
      ) {
        // Layer's source is one of the viewer's data-layer sources — skip it so
        // user data layers are not misclassified as basemap sublayers.
        continue;
      }

      applyOverrideToLayer(map, styleLayer, override);
    }
  }
}

function applyOverrideToLayer(
  map: MaplibreMap,
  layer: StyleLayer,
  override: MapSublayerOverride,
): void {
  const layerId = layer.id;
  const layerType = (layer.type ?? '') as string;

  // STROKE — applies to line layers
  if (override.stroke_color != null && layerType === 'line') {
    safeSetPaint(map, layerId, 'line-color', override.stroke_color);
  }
  if (override.stroke_width != null && layerType === 'line') {
    safeSetPaint(map, layerId, 'line-width', override.stroke_width);
  }

  // CASING — line-gap-width (visual casing width in MapLibre) + casing color on
  // layers whose id contains 'casing' (openfreemap-positron convention:
  // 'road-primary-casing' lives next to 'road-primary'). Best-effort heuristic —
  // falls through gracefully when the basemap doesn't carry a casing sibling layer.
  if (override.casing_width != null && layerType === 'line') {
    safeSetPaint(map, layerId, 'line-gap-width', override.casing_width);
  }
  if (override.casing_color != null && layerId.includes('casing')) {
    safeSetPaint(map, layerId, 'line-color', override.casing_color);
  }

  // ZOOM RANGE — applies to all classified layers regardless of type
  if (override.min_zoom != null || override.max_zoom != null) {
    const minZoom = override.min_zoom ?? 0;
    const maxZoom = override.max_zoom ?? 24;
    safeSetZoomRange(map, layerId, minZoom, maxZoom);
  }

  // OPACITY — multiplexed across layer types per OPACITY_PAINT_KEYS_BY_TYPE.
  // Symbol layers get both text-opacity and icon-opacity set simultaneously.
  if (override.opacity != null) {
    const keys = OPACITY_PAINT_KEYS_BY_TYPE[layerType];
    if (keys) {
      for (const key of keys) {
        safeSetPaint(map, layerId, key, override.opacity);
      }
    }
  }
}

function safeSetPaint(map: MaplibreMap, layerId: string, key: string, value: unknown): void {
  try {
    if (map.getLayer(layerId)) {
      map.setPaintProperty(layerId, key, value);
    }
  } catch (err) {
    if (import.meta.env.DEV) {
      console.warn('[basemap-style-mutation] setPaintProperty failed', layerId, key, err);
    }
  }
}

function safeSetZoomRange(map: MaplibreMap, layerId: string, min: number, max: number): void {
  try {
    if (map.getLayer(layerId)) {
      map.setLayerZoomRange(layerId, min, max);
    }
  } catch (err) {
    if (import.meta.env.DEV) {
      console.warn('[basemap-style-mutation] setLayerZoomRange failed', layerId, err);
    }
  }
}
