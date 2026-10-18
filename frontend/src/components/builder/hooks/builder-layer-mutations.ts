import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerInput, MapLayerResponse, MapTerrainConfig, StyleConfig } from '@/types/api';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import { isTerrainCapableDemLayer } from '@/components/builder/map-stack';
import { getCompanionLayerIds } from '@/components/builder/companion-ids';

/**
 * Decide whether deleting a layer must tear down active 3D terrain.
 *
 * Terrain is backed by a DEM dataset (terrain_config.source_dataset_id), not a
 * single layer id, so the teardown keys on dataset identity: terrain is cleared
 * only when, after the delete, no remaining layer is a DEM layer for the terrain
 * source dataset. It clears when the last DEM backing the dataset is removed,
 * and preserves terrain when an unrelated layer is deleted or another DEM layer
 * on the same dataset remains.
 *
 * @param remainingLayers - layers that survive the delete (already filtered)
 * @param terrainConfig - the current (local) terrain_config
 */
export function shouldClearTerrainOnDelete(
  remainingLayers: MapLayerResponse[],
  terrainConfig: MapTerrainConfig | null | undefined,
): boolean {
  if (!terrainConfig?.enabled || !terrainConfig.source_dataset_id) return false;
  const sourceDatasetId = terrainConfig.source_dataset_id;
  // "Still backed" means resolvable as a terrain source: use the canonical
  // isTerrainCapableDemLayer predicate (is_dem AND a DEM record type), as the
  // mesh resolver (BuilderMap/use-viewer-terrain) and the stack do. A bare
  // is_dem check could keep terrain_config alive for a layer the mesh resolver
  // can't attach, leaving a dangling config.
  const datasetStillBacked = remainingLayers.some(
    (layer) => layer.dataset_id === sourceDatasetId && isTerrainCapableDemLayer(layer),
  );
  return !datasetStillBacked;
}

/**
 * Derive the full set of MapLibre layer ids the adapter owns for a raw layer
 * id. Falls back to the canonical companion-id set (`getCompanionLayerIds`)
 * when the render mode is unknown, so legacy call sites and unregistered render
 * modes keep working.
 *
 * 'arrow' is not in the adapter registry: getAdapter('arrow') returns the
 * circleAdapter fallback (type === 'circle'), the `adapter.type === renderMode`
 * guard fails, and the companion-id fallback runs, which includes the '-arrow'
 * companion. If 'arrow' is ever registered, getLayerIds must return both the
 * base id and the '-arrow' companion.
 *
 * @param rawLayerId - the logical layer id (not prefixed with `layer-`)
 * @param renderMode - value from style_config.render_mode (or inferred adapter type)
 */
function deriveCompanionIds(rawLayerId: string, renderMode: string | null | undefined): string[] {
  const prefixedLayerId = `layer-${rawLayerId}`;
  if (renderMode) {
    try {
      // getAdapter returns circleAdapter as a fallback for unknown types; use
      // the adapter only when its registered type matches exactly.
      const adapter = getAdapter(renderMode);
      if (adapter.type === renderMode) {
        // The hillshade adapter declares its color-relief companion.
        return adapter.getLayerIds(prefixedLayerId);
      }
    } catch {
      // getAdapter should never throw; fall through to the canonical set.
    }
  }
  // Full companion set (base + outline + label + extrusion + arrow + colorrelief
  // + cluster + cluster-count) from the single source of truth, for an unknown
  // or absent render mode. Color-relief is included because DEM hillshade
  // layers can create it as a conditional companion on the same raster-dem source.
  const c = getCompanionLayerIds(rawLayerId);
  return [c.layer, c.outline, c.label, c.extrusion, c.arrow, c.colorRelief, c.cluster, c.clusterCount, c.mixedLines, c.mixedPoints];
}

/**
 * Imperatively remove per-layer companion MapLibre layers when a layer leaves
 * the builder draft. Sources are left for the normal sync prune because vector
 * sources may be shared by sibling layers.
 *
 * When `renderModeByLayerId` is provided, companion ids come from the
 * LayerAdapter.getLayerIds() contract instead of the static suffix list.
 */
export function removePerLayerCompanions(
  map: MaplibreMap | null,
  layerIds: Iterable<string>,
  renderModeByLayerId?: Map<string, string>,
): void {
  if (!map) return;
  // A delete can arrive during a basemap style swap. Retry on idle because no
  // later caller is guaranteed; materialize ids in case the iterable is single-pass.
  if (!map.isStyleLoaded()) {
    const pending = [...layerIds];
    map.once?.('idle', () => removePerLayerCompanions(map, pending, renderModeByLayerId));
    return;
  }
  for (const id of layerIds) {
    const renderMode = renderModeByLayerId?.get(id) ?? null;
    const companionIds = deriveCompanionIds(id, renderMode);
    for (const lid of companionIds) {
      if (map.getLayer(lid)) map.removeLayer(lid);
    }
  }
}

interface DuplicateRenderingLabels {
  layerFallback: string;
  duplicateName: (baseName: string) => string;
}

// Pure (no t() call), matching the English copy for callers that omit `labels`.
// Real call sites pass translated labels (useBuilderLayers'
// handleDuplicateRendering).
const DEFAULT_DUPLICATE_RENDERING_LABELS: DuplicateRenderingLabels = {
  layerFallback: 'Layer',
  duplicateName: (baseName) => `${baseName} rendering`,
};

export function buildDuplicateRenderingInput(
  layer: MapLayerResponse,
  labels: DuplicateRenderingLabels = DEFAULT_DUPLICATE_RENDERING_LABELS,
): MapLayerInput {
  // Place the duplicate adjacent to its source (source.sort_order + 1), not at
  // the stack bottom: a grouped source's copy must land next to it. This is a
  // backend hint only; handleDuplicateRendering's caller renumbers sort_order by
  // final local array index at splice time, and prepareLayersForPersistence
  // renumbers again at save time.
  const nextSortOrder = layer.sort_order + 1;
  const baseName = layer.display_name || layer.dataset_name || layer.dataset_table_name || labels.layerFallback;
  return {
    dataset_id: layer.dataset_id,
    sort_order: nextSortOrder,
    // Inherit source visibility so duplicating a hidden layer yields a hidden copy.
    visible: layer.visible ?? true,
    opacity: layer.opacity,
    paint: { ...(layer.paint ?? {}) },
    layout: { ...(layer.layout ?? {}) },
    display_name: labels.duplicateName(baseName),
    filter: layer.filter ?? null,
    label_config: layer.label_config ?? null,
    popup_config: layer.popup_config ?? null,
    style_config: layer.style_config ? ({ ...layer.style_config } as StyleConfig) : null,
    layer_type: layer.layer_type ?? null,
    show_in_legend: layer.show_in_legend ?? true,
  };
}
