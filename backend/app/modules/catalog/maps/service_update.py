"""Map creates and updates with the checks, audit and history every caller needs."""

import math
import uuid
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.catalog.authorization import (
    check_public_visibility_allowed,
    get_user_roles,
)
from app.modules.catalog.maps._router_helpers import (
    _layer_patch_history_actions,
    _readable_terrain,
    _reject_non_public_datasets,
)
from app.modules.catalog.maps.author_key import map_author_key_id, refuse_map_author_key
from app.platform.map_bookmarks import stored_bookmarks
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.catalog.maps.schemas import MapCreate, MapUpdate, MapVisibility
from app.modules.catalog.maps.service import (
    LayerRow,
    RestrictedWithoutGroupsError,
    bulk_check_dataset_access,
    create_map,
    lock_map_layers,
    record_map_history_event,
    update_map,
    validate_public_visibility,
)
from app.modules.embed_tokens.service import revoke_embed_tokens_for_dropped_datasets
from app.platform.request_credential import api_key_audit_details

_HISTORY_FIELDS = ("name", "visibility", "terrain_config", "basemap_config")
# The map's view and basemap. The builder sends them on every save, so a
# settings event records which of them changed value, not only which were sent.
CAMERA_FIELDS = ("center_lng", "center_lat", "zoom", "bearing", "pitch")
VIEW_FIELDS = (*CAMERA_FIELDS, "basemap_style")
# The stored layer fields a save can change that the per-layer history
# actions count as styling, plus the dataset a keyed layer draws.
_LAYER_STYLE_FIELDS = (
    "display_name",
    "visible",
    "opacity",
    "filter",
    "label_config",
    "popup_config",
    "style_config",
    "paint",
    "layout",
    "layer_type",
    "show_in_legend",
)
_BUILDER_STEP = Decimal("0.000001")
# Room for any finite double at 6 decimals; the default 28 digits refuse a
# large one.
_EXACT = Context(prec=400)


def _as_the_builder_saves(value: float) -> Decimal:
    """``value`` as the builder stores it, ``Number(value.toFixed(6))``:
    the double's exact value rounded to 6 decimals, half away from zero."""
    return Decimal(value).quantize(
        _BUILDER_STEP, rounding=ROUND_HALF_UP, context=_EXACT
    )


def _view_moved(field: str, previous: Any, current: Any) -> bool:
    """Whether a save moved the stored view field.

    The builder saves the camera it shows, rounded to 6 decimals and with
    its bearing in (-180, 180], so values are compared as it would save
    them: a value that rounds to the same, or for longitude and bearing to
    a whole number of turns away, is unchanged. A value set where none was
    stored is a move.
    """
    if previous is None or current is None or field == "basemap_style":
        return current != previous
    if not (math.isfinite(previous) and math.isfinite(current)):
        return current != previous
    change = _EXACT.subtract(
        _as_the_builder_saves(current), _as_the_builder_saves(previous)
    )
    if field in ("bearing", "center_lng"):
        return _EXACT.remainder(change, 360) != 0
    return change != 0


async def apply_map_create(
    db: AsyncSession,
    body: MapCreate,
    user: Identity,
    *,
    record_history: bool,
    ip_address: str | None,
    manifest_key: str | None = None,
) -> Map:
    """Create a map owned by ``user`` from ``body`` and return it, flushed.

    Checks the map_author key's fields and the terrain DEM, emits the audit
    event, and records ``map.create`` history only with ``record_history``.
    The caller binds the credential, as for ``apply_map_update``, and commits.
    """
    refuse_map_author_key(db, user.id, body)
    terrain_config = (
        body.terrain_config.model_dump(mode="json")
        if body.terrain_config is not None
        else None
    )
    await _readable_terrain(db, user, terrain_config)
    basemap_config = (
        body.basemap_config.model_dump(mode="json")
        if body.basemap_config is not None
        else None
    )
    map_obj = await create_map(
        db,
        body.name,
        body.description,
        user.id,
        notes=body.notes,
        terrain_config=terrain_config,
        basemap_config=basemap_config,
        bookmarks=stored_bookmarks(body.bookmarks),
        created_by_api_key_id=map_author_key_id(db),
        manifest_key=manifest_key,
    )
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="map.create",
            resource_type="map",
            resource_id=map_obj.id,
            details={"name": body.name, **api_key_audit_details(db)},
            ip_address=ip_address,
        ),
    )
    if record_history:
        await record_map_history_event(
            db,
            map_id=map_obj.id,
            actor=user,
            target_type="map",
            target_id=map_obj.id,
            target_name=map_obj.name,
            action="map.create",
            summary=f"Created map {map_obj.name}",
            details={"name": map_obj.name},
        )
    return map_obj


async def apply_map_update(
    db: AsyncSession,
    map_obj: Map,
    body: MapUpdate,
    user: Identity,
    *,
    record_history: bool,
    ip_address: str | None,
    layer_keys: Sequence[str | None] | None = None,
    keep_layer_ids: Sequence[uuid.UUID] = (),
) -> tuple[Map, list[LayerRow], str | None, str | None]:
    """Apply ``body`` to ``map_obj`` for ``user`` and return ``update_map``'s tuple.

    Checks the map_author key's fields, the terrain DEM, the public-visibility
    opt-in and every replacement layer's dataset before writing; refuses a
    public map with non-public datasets; emits the audit event; records
    builder history only with ``record_history``; and revokes embed tokens
    whose dataset a layer replacement dropped. Narrowing the visibility
    revokes the map's share and embed links inside ``update_map``. Refusals
    raise ``HTTPException``.

    The caller must:

    - call ``check_map_ownership`` on ``db`` first. It admits the writer for
      this session, and the ownership recheck under the map row lock does
      nothing for a writer that wasn't admitted;
    - bind the request credential to ``db`` when there is one. The map_author
      key refusal and the audit's key id read it from the session, so a
      session without one is not held to a key's scope;
    - shape the returned layer rows for the reader (``_visible_map_response``)
      before they reach a client. They include layers ``user`` can't read;
    - commit.

    With ``record_history=False`` nothing keeps the previous and new values:
    the audit event records only the changed field names, so the caller
    records the change of visibility itself. ``layer_keys`` gives each of
    ``body.layers`` the ``manifest_key`` its row stores; without it no key
    changes. A stored layer in ``keep_layer_ids`` that ``body.layers`` leaves
    out is kept in its place, as a layer hidden from ``user`` is.
    """
    map_id = map_obj.id
    await _check_map_update(db, map_obj, body, user)

    changed_fields = list(body.model_dump(exclude_unset=True).keys())
    compares_view = any(getattr(body, f) is not None for f in VIEW_FIELDS)
    compares_layers = body.layers is not None
    if record_history and (compares_view or compares_layers):
        # The values compared with are read under the lock the save holds.
        await lock_map_layers(db, map_id)
    if record_history and compares_view:
        await db.refresh(map_obj, attribute_names=[*_HISTORY_FIELDS, *VIEW_FIELDS])
    previous = {f: getattr(map_obj, f) for f in (*_HISTORY_FIELDS, *VIEW_FIELDS)}
    keyed_before = (
        await _keyed_layers(db, map_id) if record_history and compares_layers else None
    )
    kwargs = {**_update_kwargs(body, layer_keys), "keep_layer_ids": keep_layer_ids}
    saved = await _save_map_update(db, map_id, body, user, kwargs)
    map_obj, layer_tuples = saved[0], saved[1]

    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="map.update",
            resource_type="map",
            resource_id=map_id,
            details={"changed_fields": changed_fields, **api_key_audit_details(db)},
            ip_address=ip_address,
        ),
    )
    if record_history:
        keyed_styling_changed = (
            _keyed_styling_changed(keyed_before, await _keyed_layers(db, map_id))
            if keyed_before is not None
            else None
        )
        await _record_update_history(
            db,
            map_obj,
            user,
            kwargs,
            previous,
            changed_fields,
            len(layer_tuples),
            keyed_styling_changed,
        )

    if body.layers is not None:
        await _reject_non_public_datasets(db, map_obj, user)
        # Replacing the layer set can drop a dataset an embed token is
        # scoped to; revoke orphaned tokens so they stop serving its tiles.
        await revoke_embed_tokens_for_dropped_datasets(db, map_id)
    return saved


async def _keyed_layers(db: AsyncSession, map_id: uuid.UUID) -> dict[uuid.UUID, dict]:
    """Each stored layer that has a manifest key, by id, with the fields a
    styling edit changes and the dataset it draws."""
    columns = [getattr(MapLayer, field) for field in _LAYER_STYLE_FIELDS]
    rows = await db.execute(
        select(MapLayer.id, MapLayer.dataset_id, *columns).where(
            MapLayer.map_id == map_id, MapLayer.manifest_key.is_not(None)
        )
    )
    return {
        row.id: {
            "dataset_id": row.dataset_id,
            **{f: getattr(row, f) for f in _LAYER_STYLE_FIELDS},
        }
        for row in rows
    }


def _keyed_styling_changed(
    before: dict[uuid.UUID, dict], after: dict[uuid.UUID, dict]
) -> bool:
    """Whether a save added or removed a keyed layer, or changed what a
    per-layer edit would record as styling on one that stayed."""
    if before.keys() != after.keys():
        return True
    for layer_id, was in before.items():
        now = after[layer_id]
        if was["dataset_id"] != now["dataset_id"]:
            return True
        patch = {f: now[f] for f in _LAYER_STYLE_FIELDS if now[f] != was[f]}
        if _layer_patch_history_actions(patch):
            return True
    return False


async def _check_map_update(
    db: AsyncSession, map_obj: Map, body: MapUpdate, user: Identity
) -> None:
    """Refuse a write ``user`` may not make before anything is written."""
    refuse_map_author_key(db, user.id, body, map_obj)
    await _readable_terrain(db, user, body.terrain_config, map_obj.terrain_config)

    # A non-admin may not move a map to public when restrict_public_visibility
    # is on. None (untouched) passes through.
    await check_public_visibility_allowed(db, user, body.visibility)

    # RBAC: when replacing layers, verify access to every dataset, or an owner
    # could insert MapLayer rows at restricted datasets (render-time RBAC hides
    # them, but the rows would be a leakage hazard).
    if body.layers:
        user_roles = await get_user_roles(db, user)
        requested_ids = [layer.dataset_id for layer in body.layers]
        accessible = await bulk_check_dataset_access(
            db, requested_ids, user, user_roles
        )
        inaccessible = [str(did) for did in requested_ids if did not in accessible]
        if inaccessible:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": "Cannot access one or more layer datasets",
                    "datasets": inaccessible,
                },
            )


def _update_kwargs(
    body: MapUpdate, layer_keys: Sequence[str | None] | None = None
) -> dict:
    """``update_map`` keyword arguments for the fields the client sent.

    Explicit ``plugins=null`` survives, which restores client-default plugin
    behavior.
    """
    kwargs = body.model_dump(exclude_unset=True)
    if "terrain_config" in kwargs and body.terrain_config is not None:
        kwargs["terrain_config"] = body.terrain_config.model_dump(mode="json")
    if "basemap_config" in kwargs and body.basemap_config is not None:
        kwargs["basemap_config"] = body.basemap_config.model_dump(mode="json")
    if "bookmarks" in kwargs:
        kwargs["bookmarks"] = stored_bookmarks(body.bookmarks)
    if "layers" in kwargs and body.layers is not None:
        kwargs["layers"] = [
            {
                **layer.model_dump(),
                "sort_order": index if layer.sort_order is None else layer.sort_order,
                **({} if layer_keys is None else {"manifest_key": layer_keys[index]}),
            }
            for index, layer in enumerate(body.layers)
        ]
    kwargs["expected_updated_at"] = body.expected_updated_at
    return kwargs


async def _save_map_update(
    db: AsyncSession,
    map_id: uuid.UUID,
    body: MapUpdate,
    user: Identity,
    kwargs: dict,
) -> tuple[Map, list[LayerRow], str | None, str | None]:
    """Run ``update_map`` and refuse publishing a map with non-public datasets."""
    try:
        saved = await update_map(db, map_id, user=user, **kwargs)
    except RestrictedWithoutGroupsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    # Asked once update_map holds the layers' datasets. A layer replacement is
    # checked on what it leaves, after the save.
    if body.visibility == MapVisibility.public and body.layers is None:
        non_public = await validate_public_visibility(db, map_id, user)
        if non_public:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Cannot set visibility to public: map contains non-public datasets",
                    "datasets": ", ".join(non_public),
                },
            )
    return saved


async def _record_update_history(
    db: AsyncSession,
    map_obj: Map,
    user: Identity,
    kwargs: dict,
    previous: dict,
    changed_fields: list[str],
    layer_count: int,
    keyed_styling_changed: bool | None = None,
) -> None:
    """Record one builder history event per kind of change the update made.

    A layer replacement's event says whether it changed the styling of the
    layers that have a manifest key, or which of them there are.
    """
    new_visibility = map_obj.visibility
    config_fields = sorted(set(changed_fields) - {*_HISTORY_FIELDS, "layers"})
    history_events = [
        (
            "name" in kwargs
            and bool(kwargs["name"])
            and kwargs["name"] != previous["name"],
            "map.rename",
            f"Renamed map to {map_obj.name}",
            {
                "field": "name",
                "previous": previous["name"],
                "current": map_obj.name,
            },
        ),
        (
            "visibility" in kwargs
            and kwargs["visibility"] is not None
            and new_visibility != previous["visibility"],
            "map.visibility_update",
            f"Changed visibility to {new_visibility}",
            {
                "field": "visibility",
                "previous": previous["visibility"],
                "current": new_visibility,
            },
        ),
        (
            "terrain_config" in kwargs
            and map_obj.terrain_config != previous["terrain_config"],
            "map.terrain_update",
            "Updated terrain settings",
            {
                "field": "terrain_config",
                "previous": previous["terrain_config"],
                "current": map_obj.terrain_config,
            },
        ),
        (
            "basemap_config" in kwargs
            and kwargs["basemap_config"] != previous["basemap_config"],
            "map.basemap_update",
            "Updated basemap appearance",
            {
                "field": "basemap_config",
                "previous": previous["basemap_config"],
                "current": map_obj.basemap_config,
            },
        ),
        (
            "layers" in kwargs,
            "layer.replace",
            f"Replaced map layers with {layer_count} layer(s)",
            {
                "layer_count": layer_count,
                **(
                    {}
                    if keyed_styling_changed is None
                    else {"keyed_styling_changed": keyed_styling_changed}
                ),
            },
        ),
        (
            bool(config_fields),
            "map.config_update",
            "Updated map settings",
            {
                "changed_fields": config_fields,
                "view_changed": [
                    f
                    for f in VIEW_FIELDS
                    if f in kwargs and _view_moved(f, previous[f], getattr(map_obj, f))
                ],
            },
        ),
    ]
    for changed, action, summary, details in history_events:
        if not changed:
            continue
        await record_map_history_event(
            db,
            map_id=map_obj.id,
            actor=user,
            target_type="map",
            target_id=map_obj.id,
            target_name=map_obj.name,
            action=action,
            summary=summary,
            details=details,
        )
