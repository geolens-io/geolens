/**
 * Imperatively applies per-sublayer style overrides to a live MapLibre map,
 * through `map.setPaintProperty` and `map.setLayerZoomRange`: declarative
 * <Layer> props are silently ignored for basemap layers. Retries on `idle` when
 * the style is not yet loaded, so a fresh add does not drop overrides.
 */
import type { Map as MaplibreMap, StyleSpecification } from 'maplibre-gl';
import type { MapSublayerOverride } from '@/types/api';
import {
  OPACITY_PAINT_KEYS_BY_TYPE,
  SUBLAYER_CLASSIFIERS,
  isBasemapOwnedLayer,
  type StyleLayer,
} from '@/lib/basemap-utils';
import { setDynamicPaintProperty } from '@/components/builder/layer-adapters/shared';

/**
 * Apply per-sublayer style overrides to a live MapLibre map.
 *
 * @param map - MapLibre map instance (must have a loaded style for mutations to apply).
 * @param overrides - Record mapping sublayer ID → override object. Null/undefined/empty = no-op.
 * @param sourcePrefix - Optional source prefix used to scope mutations to basemap-owned
 *   layers only (pass VIEWER_SOURCE_PREFIX in viewer contexts). When undefined, all
 *   classified basemap layers are targeted (appropriate for builder context).
 * @param masterOpacity - The whole-basemap master opacity (BasemapConfig.opacity, 0-1).
 *   A per-sublayer opacity override composes on top of it (override * master),
 *   so the master slider is never clobbered. Defaults to 1.
 *
 * Called AFTER `applyBasemapConfigToMap`, so overrides sit on top of
 * visibility-mode mutations: a layer hidden by visibility mode still gets the
 * paint update but stays invisible.
 */
export function applySublayerOverrides(
  map: MaplibreMap,
  overrides: Record<string, MapSublayerOverride> | null | undefined,
  sourcePrefix?: string,
  masterOpacity = 1,
): void {
  if (!overrides || Object.keys(overrides).length === 0) return;

  // Fresh-add: the basemap style is not loaded yet; retry once idle.
  if (!map.isStyleLoaded()) {
    const retry = () => applySublayerOverrides(map, overrides, sourcePrefix, masterOpacity);
    map.once('idle', retry);
    return;
  }

  const style = map.getStyle() as StyleSpecification | undefined;
  if (!style?.layers) return;

  for (const [sublayerId, override] of Object.entries(overrides)) {
    const classifier = SUBLAYER_CLASSIFIERS[sublayerId];
    if (!classifier) continue; // opaque key set; unknown ID = no-op

    for (const layer of style.layers) {
      const styleLayer = layer as StyleLayer;
      if (!classifier(styleLayer)) continue;

      // With a prefix (viewer context), skip layers that are not basemap-owned
      // so user data layers are not misclassified as basemap sublayers.
      if (sourcePrefix && !isBasemapOwnedLayer(styleLayer, sourcePrefix)) {
        continue;
      }

      applyOverrideToLayer(map, styleLayer, override, masterOpacity);
    }
  }
}

function applyOverrideToLayer(
  map: MaplibreMap,
  layer: StyleLayer,
  override: MapSublayerOverride,
  masterOpacity: number,
): void {
  const layerId = layer.id;
  const layerType = (layer.type ?? '') as string;

  if (override.stroke_color != null && layerType === 'line') {
    safeSetPaint(map, layerId, 'line-color', override.stroke_color);
  }
  if (override.stroke_width != null && layerType === 'line') {
    safeSetPaint(map, layerId, 'line-width', override.stroke_width);
  }

  // Casing: line-gap-width plus a color on layers whose id contains 'casing'
  // (openfreemap-positron convention: 'road-primary-casing'). Best effort; a
  // basemap without casing sibling layers is a no-op.
  if (override.casing_width != null && layerType === 'line') {
    safeSetPaint(map, layerId, 'line-gap-width', override.casing_width);
  }
  if (override.casing_color != null && layerId.includes('casing')) {
    safeSetPaint(map, layerId, 'line-color', override.casing_color);
  }

  // The unset bound defaults to 0 / 22, matching the UI's displayed max_zoom;
  // 24 would extend layers two stops beyond what the UI shows.
  if (override.min_zoom != null || override.max_zoom != null) {
    const minZoom = override.min_zoom ?? 0;
    const maxZoom = override.max_zoom ?? 22;
    safeSetZoomRange(map, layerId, minZoom, maxZoom);
  }

  // Symbol layers get both text-opacity and icon-opacity. Composed with master
  // because applyBasemapConfigToMap just wrote absolute master opacity onto
  // these keys; writing override.opacity raw would clobber it.
  if (override.opacity != null) {
    const keys = OPACITY_PAINT_KEYS_BY_TYPE[layerType];
    if (keys) {
      const composedOpacity = override.opacity * masterOpacity;
      for (const key of keys) {
        safeSetPaint(map, layerId, key, composedOpacity);
      }
    }
  }
}

function safeSetPaint(map: MaplibreMap, layerId: string, key: string, value: unknown): void {
  try {
    if (map.getLayer(layerId)) {
      // Dynamic key and untyped API JSON value; see setDynamicPaintProperty.
      setDynamicPaintProperty(map, layerId, key, value);
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
