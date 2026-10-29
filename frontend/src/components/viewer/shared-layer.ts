import type { MapLayerResponse, SharedLayerResponse } from '@/types/api';

/**
 * Transform a MapLayerResponse (from GET /maps/{id}) into the SharedLayerResponse
 * format that ViewerMap consumes.
 */
export function toSharedLayer(layer: MapLayerResponse): SharedLayerResponse {
  return {
    id: layer.id,
    dataset_id: layer.dataset_id,
    dataset_name: layer.dataset_name,
    display_name: layer.display_name,
    table_name: layer.dataset_table_name,
    geometry_type: layer.dataset_geometry_type,
    column_info: layer.dataset_column_info,
    sort_order: layer.sort_order,
    visible: layer.visible,
    opacity: layer.opacity,
    paint: layer.paint,
    layout: layer.layout,
    filter: layer.filter,
    label_config: layer.label_config ?? null,
    popup_config: layer.popup_config ?? null,
    style_config: layer.style_config ?? null,
    show_in_legend: layer.show_in_legend,
    layer_type: layer.layer_type ?? undefined,
    dataset_record_type: layer.dataset_record_type ?? undefined,
    is_dem: layer.is_dem ?? undefined,
    dem_vertical_units: layer.dem_vertical_units ?? null,
    is_3d: layer.is_3d ?? null,
    feature_count: layer.dataset_feature_count ?? null,
    // Without the stamp, tile URLs carry no _v= cache-buster and in-place
    // dataset refreshes keep serving stale cached tiles.
    tile_version: layer.tile_version ?? null,
    // The adapter drops unlisted fields; without this copy /maps/{id} renders
    // no attribution while the share link does.
    dataset_attribution: layer.dataset_attribution ?? null,
    tile_url: '',
  };
}
