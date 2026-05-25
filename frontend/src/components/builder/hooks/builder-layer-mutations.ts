import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerInput, MapLayerResponse, StyleConfig } from '@/types/api';

/**
 * Imperatively remove per-layer companion MapLibre layers when a layer leaves
 * the builder draft. Sources are left for the normal sync prune because vector
 * sources may be shared by sibling layers.
 */
export function removePerLayerCompanions(
  map: MaplibreMap | null,
  layerIds: Iterable<string>,
): void {
  if (!map || !map.isStyleLoaded()) return;
  const suffixes = ['', '-outline', '-label', '-extrusion', '-arrow', '-cluster', '-cluster-count'];
  for (const id of layerIds) {
    for (const suffix of suffixes) {
      const lid = `layer-${id}${suffix}`;
      if (map.getLayer(lid)) map.removeLayer(lid);
    }
  }
}

export function buildDuplicateRenderingInput(
  layer: MapLayerResponse,
  currentLayers: MapLayerResponse[],
): MapLayerInput {
  const nextSortOrder = currentLayers.reduce((max, candidate) => Math.max(max, candidate.sort_order), -1) + 1;
  const baseName = layer.display_name || layer.dataset_name || layer.dataset_table_name || 'Layer';
  return {
    dataset_id: layer.dataset_id,
    sort_order: nextSortOrder,
    visible: true,
    opacity: layer.opacity,
    paint: { ...(layer.paint ?? {}) },
    layout: { ...(layer.layout ?? {}) },
    display_name: `${baseName} rendering`,
    filter: layer.filter ?? null,
    label_config: layer.label_config ?? null,
    popup_config: layer.popup_config ?? null,
    style_config: layer.style_config ? ({ ...layer.style_config } as StyleConfig) : null,
    layer_type: layer.layer_type ?? null,
    show_in_legend: layer.show_in_legend ?? true,
  };
}
