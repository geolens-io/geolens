"""What a map_author API key may set on a map, and which maps it may change."""

import uuid

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.schemas import (
    MapCreate,
    MapLayerDiffRequest,
    MapLayerInput,
    MapLayerPatch,
    MapUpdate,
)
from app.platform.request_credential import api_key_credential, api_key_scope_refusal

_LAYER_STYLE_FIELDS = frozenset({"paint", "style_config", "popup_config"})

# The fields each request body may carry from a map_author key. Sending any
# other field is refused, whatever its value, so a later field stays refused
# until it is listed here.
MAP_AUTHOR_SETTABLE_FIELDS: dict[type[BaseModel], frozenset[str]] = {
    MapCreate: frozenset({"name", "description", "basemap_config"}),
    MapUpdate: frozenset(
        {
            "center_lng",
            "center_lat",
            "zoom",
            "bearing",
            "pitch",
            "basemap_style",
            "basemap_config",
            "expected_updated_at",
        }
    ),
    MapLayerInput: frozenset({"dataset_id"}) | _LAYER_STYLE_FIELDS,
    MapLayerPatch: frozenset({"id"}) | _LAYER_STYLE_FIELDS,
    MapLayerDiffRequest: frozenset({"added", "updated"}),
}


def map_author_key_id(db: AsyncSession) -> uuid.UUID | None:
    """The id of the map_author key that authenticated this request, or None."""
    credential = api_key_credential(db)
    if credential is None or credential.scope != "map_author":
        return None
    return credential.id


def _unsettable_fields(body: BaseModel) -> set[str]:
    fields = set(body.model_fields_set) - MAP_AUTHOR_SETTABLE_FIELDS[type(body)]
    if isinstance(body, MapLayerDiffRequest):
        for layer in (*body.added, *body.updated):
            fields |= _unsettable_fields(layer)
    return fields


def refuse_map_author_key(
    db: AsyncSession, user_id: uuid.UUID, body: BaseModel, map_obj: Map | None = None
) -> None:
    """Refuse a map_author key a map it didn't create or a field it may not set.

    Other credentials pass. A map stays the key's only while the key's owner
    still owns it.
    """
    key_id = map_author_key_id(db)
    if key_id is None:
        return
    if map_obj is not None and (
        map_obj.created_by_api_key_id != key_id or map_obj.created_by != user_id
    ):
        raise api_key_scope_refusal(
            "A map_author key can change only the maps it created"
        )
    fields = _unsettable_fields(body)
    if fields:
        raise api_key_scope_refusal(
            f"A map_author key can't set {', '.join(sorted(fields))}"
        )
