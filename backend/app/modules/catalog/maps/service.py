"""Public maps service facade.

The maps service implementation is split across focused sibling modules while
this module preserves the stable import path used by routers, admin, dataset,
embed-token, ProcessingPort, and test callers.
"""

from app.modules.catalog.maps.service_crud import (
    check_map_ownership,
    create_map,
    delete_map,
    discard_map_asset_objects,
    duplicate_map,
    get_map,
    get_map_with_layers,
    list_maps,
    lock_map_for_asset_write,
    map_asset_publication,
    new_map_asset_key,
    update_map,
)
from app.modules.catalog.maps.service_diff import apply_layer_diff
from app.modules.catalog.maps.service_history import (
    list_map_history,
    record_map_history_event,
)
from app.modules.catalog.maps.service_layers import (
    add_layer,
    bulk_check_dataset_access,
    remove_layer,
    remove_layers_bulk,
)
from app.modules.catalog.maps.service_public import (
    _validate_share_token,
    create_share_token,
    find_maps_broken_by_dataset_visibility,
    get_active_share_token,
    get_maps_for_dataset,
    get_shared_map,
    list_share_tokens,
    revoke_share_token,
    revoke_share_token_by_map,
    update_share_token,
    validate_public_visibility,
)
from app.modules.catalog.maps.service_shared import (
    DatasetMeta,
    LayerRow,
    _apply_map_visibility_filter,
    _fetch_layer_rows_ordered,
    _infer_layer_type,
    _resolve_save_response_metadata,
    filter_layer_rows_by_dataset_visibility,
    generate_default_style,
    get_dataset_meta,
)

__all__ = [
    "DatasetMeta",
    "LayerRow",
    "check_map_ownership",
    "get_dataset_meta",
    "generate_default_style",
    "create_map",
    "get_map",
    "get_map_with_layers",
    "list_maps",
    "update_map",
    "delete_map",
    "discard_map_asset_objects",
    "lock_map_for_asset_write",
    "map_asset_publication",
    "new_map_asset_key",
    "record_map_history_event",
    "list_map_history",
    "bulk_check_dataset_access",
    "duplicate_map",
    "add_layer",
    "apply_layer_diff",
    "remove_layer",
    "remove_layers_bulk",
    "validate_public_visibility",
    "find_maps_broken_by_dataset_visibility",
    "create_share_token",
    "update_share_token",
    "get_active_share_token",
    "get_shared_map",
    "list_share_tokens",
    "revoke_share_token",
    "get_maps_for_dataset",
    "revoke_share_token_by_map",
    "_fetch_layer_rows_ordered",
    "_resolve_save_response_metadata",
    "filter_layer_rows_by_dataset_visibility",
    "_apply_map_visibility_filter",
    "_infer_layer_type",
    "_validate_share_token",
]
