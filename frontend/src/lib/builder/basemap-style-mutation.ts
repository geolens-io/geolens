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
  OPACITY_PAINT_KEYS_BY_TYPE,
  SUBLAYER_CLASSIFIERS,
  isBasemapOwnedLayer,
  type StyleLayer,
} from '@/lib/basemap-utils';

// builder-audit #338 DUP-01: the opacity-key table is now imported from
// basemap-utils (single source of truth) rather than re-declared here. The
// per-sublayer semantics (no prominence stamps to compose) live in
// applyOverrideToLayer below, not in the table itself.

/**
 * Apply per-sublayer style overrides to a live MapLibre map.
 *
 * @param map - MapLibre map instance (must have a loaded style for mutations to apply).
 * @param overrides - Record mapping sublayer ID → override object. Null/undefined/empty = no-op.
 * @param sourcePrefix - Optional source prefix used to scope mutations to basemap-owned
 *   layers only (pass VIEWER_SOURCE_PREFIX in viewer contexts). When undefined, all
 *   classified basemap layers are targeted (appropriate for builder context).
 * @param masterOpacity - The whole-basemap master opacity (BasemapConfig.opacity, 0-1).
 *   builder-audit #338 CORR-01: a per-sublayer opacity override COMPOSES on top of master
 *   (override * master) so the documented "additive on top of the master opacity"
 *   contract holds and the master slider is never silently clobbered. Defaults to 1.
 *
 * Order of operations per D-07: this helper is called AFTER `applyBasemapConfigToMap`
 * so sublayer-specific overrides sit on top of visibility-mode mutations. If a layer is
 * hidden by visibility mode the override still updates paint but the layer stays invisible.
 */
export function applySublayerOverrides(
  map: MaplibreMap,
  overrides: Record<string, MapSublayerOverride> | null | undefined,
  sourcePrefix?: string,
  masterOpacity = 1,
): void {
  if (!overrides || Object.keys(overrides).length === 0) return;

  // Idle-retry: project_maplibre_idle_retry_pattern.md
  // Without this recovery, fresh-add scenarios (basemap style not yet loaded)
  // silently drop all overrides on first paint — the SP-03 B-01-followup bug shape.
  if (!map.isStyleLoaded()) {
    const retry = () => applySublayerOverrides(map, overrides, sourcePrefix, masterOpacity);
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

      // sourcePrefix scoping: when a prefix is provided (viewer context), skip
      // layers that are NOT basemap-owned (their source is a data-layer source).
      // builder-audit #338 DUP-02: classification is delegated to the shared
      // isBasemapOwnedLayer predicate so the missing/non-string-source edge
      // cases are defined once.
      if (sourcePrefix && !isBasemapOwnedLayer(styleLayer, sourcePrefix)) {
        // user data layers are not misclassified as basemap sublayers.
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

  // ZOOM RANGE — applies to all classified layers regardless of type.
  // WR-01: only call setLayerZoomRange when at least one zoom bound is explicitly set.
  // When only one side is set, default the other to 0 (min) or 22 (max) — matching the
  // UI's displayed default of 22 for max_zoom (BasemapSublayerEditorScene.tsx:198).
  // Using 24 here would silently extend layers two stops beyond what the UI shows.
  if (override.min_zoom != null || override.max_zoom != null) {
    const minZoom = override.min_zoom ?? 0;
    const maxZoom = override.max_zoom ?? 22;
    safeSetZoomRange(map, layerId, minZoom, maxZoom);
  }

  // OPACITY — multiplexed across layer types per OPACITY_PAINT_KEYS_BY_TYPE.
  // Symbol layers get both text-opacity and icon-opacity set simultaneously.
  // builder-audit #338 CORR-01: compose the per-sublayer override with the master
  // opacity (override * master) instead of writing the override absolutely.
  // applyBasemapConfigToMap wrote absolute master opacity onto these same keys
  // just before this call; writing override.opacity raw would clobber master,
  // contradicting the schema's "additive on top of the master opacity" contract.
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
