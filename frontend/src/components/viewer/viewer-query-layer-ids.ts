import type { SharedLayerResponse } from '@/types/api';
import type { ViewerLayerEntry } from '@/components/viewer/layer-identity';
import { clusterInteractiveLayerIds } from '@/components/map/cluster-interactions';
import { isClusterRenderMode } from '@/components/builder/cluster-source';
import { isGenericGeometryType } from '@/components/builder/layer-adapters/shared';
import { mixedInteractiveLayerIds } from '@/components/builder/layer-adapters/mixed-adapter';
import { prefixed } from '@/components/builder/map-sync';

export const VIEWER_PREFIX = 'viewer-';

export function viewerManagedLayerIds(
  layer: SharedLayerResponse,
  key: string,
): string[] {
  const layerId = prefixed('layer', key, VIEWER_PREFIX);
  if (isClusterRenderMode(layer)) return clusterInteractiveLayerIds(layerId);
  if (isGenericGeometryType(layer.geometry_type)) return mixedInteractiveLayerIds(layerId);
  return [layerId];
}

export function viewerQueryLayerIds(
  entries: ViewerLayerEntry<SharedLayerResponse>[],
  visibleLayers: Set<string>,
  options: { includeHeatmaps: boolean },
): string[] {
  return entries
    .filter(({ key }) => visibleLayers.has(key))
    .filter(({ layer }) => (
      options.includeHeatmaps || layer.style_config?.render_mode !== 'heatmap'
    ))
    .flatMap(({ layer, key }) => viewerManagedLayerIds(layer, key));
}
