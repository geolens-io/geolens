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
