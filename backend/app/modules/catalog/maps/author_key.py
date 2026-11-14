"""What a map_author API key may set on a map, and which maps it may change."""

import uuid
from collections.abc import Iterable

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

# The fields each request body may carry from a map_author key. Any other field
# sent is refused, so a later field stays refused until it is listed here.
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

# Bodies where an unlisted field sent at its default passes: a new layer or a
# request flag stores what leaving it out would, and the Python SDK sends them.
MAP_AUTHOR_DEFAULTS_ACCEPTED: tuple[type[BaseModel], ...] = (
    MapLayerInput,
    MapLayerDiffRequest,
)

NOT_ITS_MAP = "A map_author key can change only the maps it created"


def map_author_key_id(db: AsyncSession) -> uuid.UUID | None:
    """The id of the map_author key that authenticated this request, or None."""
    credential = api_key_credential(db)
    if credential is None or credential.scope != "map_author":
        return None
    return credential.id


def map_author_may_change(
    db: AsyncSession,
    user_id: uuid.UUID,
    created_by: uuid.UUID | None,
    created_by_api_key_id: uuid.UUID | None,
) -> bool:
    """Whether this request's credential may change a map with these owners.

    Anything but a map_author key may; that key only while it created the map
    and its owner still owns it, whatever the owner's roles.
    """
    key_id = map_author_key_id(db)
    return key_id is None or (created_by_api_key_id == key_id and created_by == user_id)


def map_author_append_orders(
    db: AsyncSession, layer_orders: Iterable[int], count: int
) -> list[int] | None:
    """Draw orders for a map_author key's ``count`` new layers, or None for others.

    The key may not order layers, so each new one goes above every existing
    layer, in request order. Call holding the map's layer lock.
    """
    if map_author_key_id(db) is None:
        return None
    start = max(layer_orders, default=-1) + 1
    return list(range(start, start + count))


def _sent_at_default(body: BaseModel, name: str) -> bool:
    if not isinstance(body, MAP_AUTHOR_DEFAULTS_ACCEPTED):
        return False
    default = type(body).model_fields[name].get_default(call_default_factory=True)
    return getattr(body, name) == default


def _unsettable_fields(body: BaseModel) -> set[str]:
    fields = {
        name
        for name in body.model_fields_set - MAP_AUTHOR_SETTABLE_FIELDS[type(body)]
        if not _sent_at_default(body, name)
    }
    if isinstance(body, MapLayerDiffRequest):
        for layer in (*body.added, *body.updated):
            fields |= _unsettable_fields(layer)
    return fields


def refuse_map_author_key(
    db: AsyncSession, user_id: uuid.UUID, body: BaseModel, map_obj: Map | None = None
) -> None:
    """Refuse a map_author key a map it didn't create or a field it may not set.

    Other credentials pass. The map row lock checks the map again with
    ``map_author_may_change``.
    """
    if map_author_key_id(db) is None:
        return
    if map_obj is not None and not map_author_may_change(
        db, user_id, map_obj.created_by, map_obj.created_by_api_key_id
    ):
        raise api_key_scope_refusal(NOT_ITS_MAP)
    fields = _unsettable_fields(body)
    if fields:
        raise api_key_scope_refusal(
            f"A map_author key can't set {', '.join(sorted(fields))}"
        )
