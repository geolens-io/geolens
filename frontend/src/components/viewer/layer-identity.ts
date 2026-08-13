import { resolveTerrainSourceLayer } from '@/components/builder/map-stack';

export interface ViewerLayerIdentityInput {
  id?: string | null;
  dataset_id: string;
  table_name?: string | null;
  sort_order: number;
}

export interface ViewerLayerEntry<T extends ViewerLayerIdentityInput> {
  layer: T;
  key: string;
}

function legacyLayerKey(layer: ViewerLayerIdentityInput, index: number): string {
  const tableName = layer.table_name || 'layer';
  return `legacy-${layer.sort_order}-${layer.dataset_id}-${tableName}-${index}`;
}

export function getViewerLayerKey(
  layer: ViewerLayerIdentityInput,
  index: number,
): string {
  return layer.id || legacyLayerKey(layer, index);
}

export function createViewerLayerEntries<T extends ViewerLayerIdentityInput>(
  layers: T[] | undefined,
): ViewerLayerEntry<T>[] {
  return (layers ?? []).map((layer, index) => ({
    layer,
    key: getViewerLayerKey(layer, index),
  }));
}

/**
 * fix(#452): whether the DEM backing `terrain_config` is live-visible in the
 * viewer (legend eye toggle). The ONE definition both the mesh gate
 * (ViewerMap → useViewerTerrain) and the synthetic legend entry (LayerLegend)
 * must share — if they re-derived it independently, a future consumer that
 * filters `layers` differently would silently split legend and mesh.
 * Defaults to visible when no backing layer or entry resolves (those states
 * are governed by the saved-visibility/token gates, not the live toggle).
 */
export function isTerrainBackingLiveVisible<
  T extends ViewerLayerIdentityInput & {
    is_dem?: boolean | null;
    dataset_record_type?: string | null;
    visible?: boolean | null;
  },
>(
  layers: T[],
  terrainConfig: { source_dataset_id?: string | null } | null | undefined,
  visibleLayers: Set<string>,
): boolean {
  const backing = resolveTerrainSourceLayer(layers, terrainConfig);
  if (!backing) return true;
  const entry = createViewerLayerEntries(layers).find((e) => e.layer === backing);
  return entry ? visibleLayers.has(entry.key) : true;
}

/**
 * feat(#1472): the distinct credit lines the currently visible layers' datasets
 * require, in stacking order, for MapLibre's attribution control.
 *
 * Scoped to `visibleLayers` — the live eye-toggle state, the same set the
 * legend and the terrain-mesh gate read — rather than the saved `visible`
 * flag, so hiding a layer drops its credit and showing it again restores it.
 * A credit for data nobody can currently see is the wrong claim to make.
 *
 * Deduped by exact string: two layers ingested from one source carry the same
 * line and must credit it once. MapLibre additionally drops any entry that is
 * a substring of another and merges the result with the basemap's own credits,
 * so this returns the raw distinct set rather than trying to pre-compose it.
 */
export function collectLayerAttributions<
  T extends ViewerLayerIdentityInput & { dataset_attribution?: string | null },
>(layers: T[] | undefined, visibleLayers: Set<string>): string[] {
  const seen = new Set<string>();
  const credits: string[] = [];
  for (const { layer, key } of createViewerLayerEntries(layers)) {
    if (!visibleLayers.has(key)) continue;
    const credit = layer.dataset_attribution?.trim();
    if (!credit || seen.has(credit)) continue;
    seen.add(credit);
    credits.push(credit);
  }
  return credits;
}
