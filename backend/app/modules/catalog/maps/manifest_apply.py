"""The maps section of a publish manifest: what a dry run reports and an apply writes.

One check serves both. Each map's key is looked up and its writer checked,
each layer's dataset must be one the caller can read and one a map can show,
each layer's styling goes through the map layer schema with its column names
rewritten to the stored ones, and the map's visibility is judged as a
dataset's is. A dry run writes nothing. An apply writes each map whose check
found no error in a transaction of its own, under a lock on its key, through
the map create and update services.
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, NamedTuple

import structlog
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.core.permissions import EDIT_METADATA
from app.core.record_types import capabilities
from app.modules.auth import permissions as auth_permissions
from app.modules.catalog.authorization import (
    apply_visibility_filter,
    check_public_visibility_allowed,
    get_user_roles,
)
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.modules.catalog.maps.arcgis_webmap.fields import FieldNames
from app.modules.catalog.maps.manifest_columns import (
    named_columns,
    rename_layer_columns,
)
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.catalog.maps.publish_vocabulary import (
    LABEL_METADATA_KEYS,
    STYLE_METADATA_KEYS,
)
from app.modules.catalog.maps.schemas import (
    _MAX_LAYERS_PER_MAP,
    MapCreate,
    MapLayerInput,
    MapUpdate,
)
from app.modules.catalog.maps.service import (
    bulk_check_dataset_access,
    check_map_ownership,
    record_map_history_event,
)
from app.modules.catalog.maps.service_update import apply_map_create, apply_map_update
from app.modules.settings.basemaps import list_public_basemaps
from app.platform.extensions import get_permission_extension
from app.platform.record_audience import PublicationRefused, effective_publication
from app.platform.request_credential import is_publish_key

NO_MAP_PERMISSION = "A003"
PUBLIC_REFUSED = "A020"
TABLE_LAYER = "A032"
KEY_NOT_WRITABLE = "A050"
DATASET_NOT_READY = "A052"
LAYER_REMOVED = "A059"
STYLE_KEY_DROPPED = "A062"
COLUMN_MISSING = "A063"
OTHER_REFUSAL = "A099"

MAP_KEY_NOT_WRITABLE = "This map key belongs to a map you can't edit."
MAP_CHECK_FAILED = "This map could not be checked. Try again."
MAP_APPLY_FAILED = "This map could not be published. Try again."

log = structlog.get_logger()
# One answer for a dataset that doesn't exist, isn't ready and can't be read,
# so the answer tells a caller nothing about datasets they can't see.
DATASET_UNAVAILABLE = (
    "Layer {layer}: its dataset doesn't exist, hasn't finished publishing, "
    "or you can't read it."
)

# Shape-checks a layer whose dataset didn't resolve; never stored.
_NO_DATASET = uuid.UUID(int=0)
_MAX_REPORTED_ERRORS = 5
# Names in a message come from the caller, so a message lists only so many.
_MAX_LISTED_NAMES = 20
_MAX_LISTED_NAME_LENGTH = 64
# A schema error may quote the caller's keys too.
_MAX_ERROR_LENGTH = 300
# A map has no record status: a public map is open to anonymous readers, as
# a public and published dataset is.
_MAP_STATUS = "published"
_PUBLIC_REFUSALS = {
    "key": (
        "A publish key can't make anything public",
        "Use Organization, or sign in.",
    ),
    "restriction": (
        "Public visibility is restricted on this server",
        "Use Organization, or ask the admin.",
    ),
    "datasets": (
        "A public map can't show datasets that aren't public",
        "Share the datasets publicly in GeoLens, or use Organization.",
    ),
}


class _Dataset(NamedTuple):
    """What the checks read of a dataset the caller can read."""

    columns: list[dict[str, Any]] | None
    record_type: str | None
    visibility: str
    record_status: str

    @property
    def public(self) -> bool:
        return (self.visibility, self.record_status) == ("public", "published")


@dataclass(frozen=True)
class _Request:
    """What every map of one request is checked against."""

    user: Identity
    dataset_ids_by_key: Mapping[str, uuid.UUID]
    pending_datasets: Mapping[str, tuple[str | None, str]]
    datasets: Mapping[uuid.UUID, _Dataset]
    basemap_ids: set[str]
    may_edit_maps: bool
    may_set_public: bool
    is_key: bool
    public_fallback: str | None
    client: Any
    ip_address: str | None


@dataclass
class _Plan:
    """One map's check, and what an apply writes when it found no error."""

    result: dict[str, Any]
    map_obj: Map | None = None
    layers: list[MapLayerInput] = field(default_factory=list)
    layer_keys: list[str | None] = field(default_factory=list)
    # None keeps the map's.
    write_visibility: str | None = None


def _short(name: object, limit: int = _MAX_LISTED_NAME_LENGTH) -> str:
    text_ = str(name)
    if len(text_) <= limit:
        return text_
    return text_[: limit - 3] + "..."


def _problem(error: Mapping[str, Any]) -> str:
    where = ".".join(_short(part) for part in error["loc"]) or "layer"
    return f"{where}: {_short(error['msg'], _MAX_ERROR_LENGTH)}"


def _listed(names: Sequence[str]) -> str:
    shown = ", ".join(_short(name) for name in names[:_MAX_LISTED_NAMES])
    rest = len(names) - _MAX_LISTED_NAMES
    return f"{shown} and {rest} more" if rest > 0 else shown


def _message(
    code: str,
    severity: str,
    message: str,
    *,
    fix: str | None = None,
    layer: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "fix": fix,
        "layer": layer,
    }


def _error_result(key: str, message: str) -> dict[str, Any]:
    return {
        "map_key": key,
        "action": "error",
        "map_id": None,
        "messages": [_message(OTHER_REFUSAL, "error", message)],
    }


async def _readable_datasets(
    session: AsyncSession,
    dataset_ids: Iterable[uuid.UUID],
    user: Identity,
) -> dict[uuid.UUID, _Dataset]:
    """What the checks read of each dataset the caller can read, in one query.

    Columns None means they were never recorded; an empty list is a dataset
    with no attribute columns, such as a geometry-only table. A dataset the
    caller can't read is left out exactly like a missing one. The query runs
    even with no ids, so a dataset key that resolved costs the same queries
    as one that didn't.
    """
    wanted = sorted(set(dataset_ids))
    stmt = (
        select(
            Dataset.id,
            Dataset.column_info,
            Record.record_type,
            Record.visibility,
            Record.record_status,
        )
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id.in_(wanted))
    )
    roles = await get_user_roles(session, user)
    stmt = apply_visibility_filter(stmt, user, roles, Record, DatasetGrant)
    rows = await session.execute(stmt)
    return {
        row[0]: _Dataset(
            list(row[1]) if isinstance(row[1], list) else None, row[2], row[3], row[4]
        )
        for row in rows
    }


async def _known_basemap_ids(session: AsyncSession) -> set[str]:
    """The basemap ids ``GET /capabilities`` lists."""
    return {
        basemap.id for basemap in await list_public_basemaps(session) if basemap.enabled
    }


async def _may_edit_maps(session: AsyncSession, user: Identity) -> bool:
    """The check ``require_permission("edit_metadata")`` makes on the map
    routes, recorded the same way so the map row lock makes it again.

    It reads the caller's full roles: a publish key narrows which maps its
    owner's admin role reaches, which the ownership check applies, not which
    capabilities the owner holds.
    """
    matrix = await auth_permissions.get_effective_permissions(session)
    granted = await get_permission_extension().check_permission(
        session,
        user,
        EDIT_METADATA,
        user_roles=await auth_permissions.get_user_roles(session, user),
        permission_matrix=matrix,
    )
    if granted:
        auth_permissions.admit_capabilities(session, user.id, (EDIT_METADATA,), matrix)
    return granted


async def _may_set_public(session: AsyncSession, user: Identity) -> bool:
    """Whether the gate every visibility write goes through lets ``user``
    make something public."""
    try:
        await check_public_visibility_allowed(session, user, "public")
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        return False
    return True


async def _writable_map(
    session: AsyncSession, key: str, user: Identity
) -> tuple[Map | None, bool]:
    """The map ``key`` names and whether the caller may write it.

    ``(None, True)`` when no map has the key, and ``(None, False)`` for a map
    the caller can't write, so nothing of it reaches the caller.
    """
    map_obj = (
        await session.execute(select(Map).where(Map.manifest_key == key))
    ).scalar_one_or_none()
    if map_obj is None:
        return None, True
    try:
        await check_map_ownership(map_obj, user, session)
    except HTTPException:
        return None, False
    return map_obj, True


async def _stored_layers(
    session: AsyncSession, map_id: uuid.UUID, user: Identity
) -> list[tuple[MapLayer, _Dataset | None]]:
    """The map's layers in draw order, each with its dataset when the caller
    can read it."""
    layers = (
        (
            await session.execute(
                select(MapLayer)
                .where(MapLayer.map_id == map_id)
                .order_by(MapLayer.sort_order, MapLayer.id)
            )
        )
        .scalars()
        .all()
    )
    datasets = await _readable_datasets(
        session, (layer.dataset_id for layer in layers), user
    )
    return [(layer, datasets.get(layer.dataset_id)) for layer in layers]


async def _lock_map_key(session: AsyncSession, key: str) -> None:
    """Serialize the applies of one map key until the transaction ends."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"manifest_map:{key}"},
    )


def _known_keys(
    value: dict[str, Any] | None, known: frozenset[str]
) -> tuple[dict[str, Any] | None, list[str]]:
    if value is None:
        return None, []
    dropped = sorted(key for key in value if key not in known)
    return {k: v for k, v in value.items() if k in known}, dropped


def _layout(layer: Any) -> dict[str, Any] | None:
    """The layer's layout with its zoom range where the builder keeps it."""
    zooms = {
        key: value
        for key, value in (("_minzoom", layer.min_zoom), ("_maxzoom", layer.max_zoom))
        if value is not None
    }
    if layer.layout is None and not zooms:
        return None
    return {**(layer.layout or {}), **zooms}


def _check_layer(
    layer: Any,
    dataset_id: uuid.UUID | None,
    dataset: _Dataset | None,
    *,
    pending: bool,
) -> tuple[list[dict[str, Any]], MapLayerInput | None]:
    """The messages for one layer, and the layer as it is stored.

    ``dataset`` is the readable dataset, None when the caller can't read it.
    A ``pending`` layer names a dataset the same request publishes, so an
    unreadable dataset is no error for it, and there are no columns to check.
    Column names are rewritten to the stored ones; a name the dataset lacks,
    or a dataset whose columns were never recorded, keeps the name it had.
    """
    messages: list[dict[str, Any]] = []
    if dataset is None and not pending:
        messages.append(
            _message(
                DATASET_NOT_READY,
                "error",
                DATASET_UNAVAILABLE.format(layer=layer.key),
                fix="Wait for its job.",
                layer=layer.key,
            )
        )
    elif (
        dataset is not None and capabilities(dataset.record_type).map_layer_type is None
    ):
        messages.append(
            _message(
                OTHER_REFUSAL,
                "error",
                f"Layer {layer.key}: its dataset is a kind a map can't show, "
                "such as 3D Tiles or a point cloud.",
                fix="Remove the layer.",
                layer=layer.key,
            )
        )
    elif dataset is not None and dataset.record_type == "table":
        messages.append(
            _message(
                TABLE_LAYER,
                "info",
                f"Layer {layer.key}: its dataset is a table without geometry, "
                "so the layer draws nothing on the map.",
                layer=layer.key,
            )
        )
    style_config, dropped_style = _known_keys(layer.style_config, STYLE_METADATA_KEYS)
    label_config, dropped_label = _known_keys(layer.label_config, LABEL_METADATA_KEYS)
    for name, dropped in (
        ("style_config", dropped_style),
        ("label_config", dropped_label),
    ):
        if dropped:
            messages.append(
                _message(
                    STYLE_KEY_DROPPED,
                    "info",
                    f"Unknown {name} keys were dropped: {_listed(dropped)}.",
                    layer=layer.key,
                )
            )
    try:
        checked = MapLayerInput(
            dataset_id=dataset_id or _NO_DATASET,
            visible=layer.visible,
            opacity=layer.opacity,
            paint=layer.paint,
            layout=_layout(layer),
            display_name=layer.display_name,
            filter=layer.filter,
            label_config=label_config,
            popup_config=layer.popup_config,
            style_config=style_config,
            show_in_legend=layer.show_in_legend,
        )
        named = named_columns(checked)
    except ValidationError as exc:
        problems = "; ".join(
            _problem(error)
            for error in exc.errors(include_input=False)[:_MAX_REPORTED_ERRORS]
        )
        messages.append(
            _message(
                OTHER_REFUSAL,
                "error",
                f"Layer {layer.key} can't be saved: {problems}",
                layer=layer.key,
            )
        )
        return messages, None
    except RecursionError:
        messages.append(
            _message(
                OTHER_REFUSAL,
                "error",
                f"Layer {layer.key} can't be saved: its styling is nested too deeply.",
                layer=layer.key,
            )
        )
        return messages, None
    if dataset is None or dataset.columns is None:
        return messages, checked
    columns = dataset.columns
    # FieldNames reads an empty list as "columns unknown" and accepts every
    # name; a recorded empty list has none.
    stored = FieldNames(columns)
    missing = sorted(
        name for name in named if not columns or stored.stored(name) is None
    )
    if missing:
        messages.append(
            _message(
                COLUMN_MISSING,
                "warning",
                f"The dataset has no single column named {_listed(missing)}.",
                fix="Fix the field name.",
                layer=layer.key,
            )
        )
    return messages, rename_layer_columns(
        checked, lambda name: stored.stored(name) or name
    )


def _public_refused(entry: Any, severity: str, reason: str) -> dict[str, Any]:
    refusal, fix = _PUBLIC_REFUSALS[reason]
    outcome = (
        "was not published"
        if severity == "error"
        else "is shared with the organization instead"
    )
    return _message(
        PUBLIC_REFUSED,
        severity,
        f"{refusal}, so the map {_short(entry.name)!r} {outcome}.",
        fix=fix,
    )


def _judge_visibility(
    entry: Any, now: str | None, shows_non_public: bool, request: _Request
) -> tuple[str | None, list[dict[str, Any]]]:
    """The visibility a map's apply writes (None keeps the map's) and its
    messages, by the rules a manifest dataset's visibility follows.

    A public map that would show a dataset that isn't public and published is
    refused as public is, and so falls back like it.
    """
    try:
        publication = effective_publication(
            entry.visibility,
            _MAP_STATUS,
            request.public_fallback,
            may_set_public=request.may_set_public,
            is_key=request.is_key,
            now=None if now is None else (now, _MAP_STATUS),
        )
    except PublicationRefused as refused:
        if refused.reason == "widening":
            return None, [
                _message(
                    OTHER_REFUSAL,
                    "error",
                    "A publish key can't widen a map's visibility.",
                    fix="Keep the current Sharing level, or sign in.",
                )
            ]
        return None, [_public_refused(entry, "error", refused.reason)]
    visibility, fell_back_for = publication.visibility, publication.fell_back_for
    if (visibility or now or "private") == "public" and shows_non_public:
        if request.public_fallback != "internal":
            return None, [_public_refused(entry, "error", "datasets")]
        visibility, fell_back_for = "internal", "datasets"
    messages = []
    if fell_back_for is not None:
        messages.append(_public_refused(entry, "warning", fell_back_for))
    return visibility, messages


def _planned_public(
    dataset: _Dataset | None, planned: tuple[str | None, str] | None
) -> bool:
    """Whether a layer's dataset is public and published once the request's
    own entry for it, ``planned``, has published it."""
    if planned is None:
        return dataset is not None and dataset.public
    visibility = planned[0] or (dataset.visibility if dataset else None) or "private"
    return (visibility, planned[1]) == ("public", "published")


def _kept_layer(layer: MapLayer) -> MapLayerInput:
    """A layer added in GeoLens, as the builder's full save sends it back."""
    return MapLayerInput.model_validate(
        {
            "id": layer.id,
            "dataset_id": layer.dataset_id,
            "sort_order": layer.sort_order,
            "visible": layer.visible,
            "opacity": layer.opacity,
            "paint": layer.paint,
            "layout": layer.layout,
            "display_name": layer.display_name,
            "filter": layer.filter,
            "label_config": layer.label_config,
            "popup_config": layer.popup_config,
            "style_config": layer.style_config,
            "layer_type": layer.layer_type,
            "show_in_legend": layer.show_in_legend,
        }
    )


def _plan_stack(
    entry: Any,
    stored: list[tuple[MapLayer, _Dataset | None]],
    layers: list[MapLayerInput],
    keys: list[str],
) -> tuple[list[MapLayerInput], list[str | None], list[MapLayer], int]:
    """The layers an apply sends, their keys, the keyed layers it removes,
    and how many layers the map then has.

    A keyed layer keeps its row. A layer added in GeoLens keeps its slot, and
    so does a keyed layer the caller can't read, which the save keeps; the
    manifest's layers take the other slots in manifest order, the first on
    top. A readable keyed layer the manifest no longer lists is removed.
    """
    listed = {layer.key for layer in entry.layers}
    by_key = {layer.manifest_key: layer for layer, _ in stored if layer.manifest_key}
    kept = [
        (layer, dataset)
        for layer, dataset in stored
        if layer.manifest_key is None
        or (dataset is None and layer.manifest_key not in listed)
    ]
    removed = [
        layer
        for layer, dataset in stored
        if layer.manifest_key is not None
        and dataset is not None
        and layer.manifest_key not in listed
    ]
    reserved = {layer.sort_order for layer, _ in kept}
    free = (order for order in itertools.count() if order not in reserved)
    sent = [
        layer.model_copy(
            update={
                "id": by_key[key].id if key in by_key else None,
                "sort_order": next(free),
            }
        )
        for layer, key in zip(layers, keys, strict=True)
    ]
    readable_kept = [layer for layer, dataset in kept if dataset is not None]
    sent += [_kept_layer(layer) for layer in readable_kept]
    sent_keys: list[str | None] = [*keys, *(None for _ in readable_kept)]
    return sent, sent_keys, removed, len(entry.layers) + len(kept)


async def _check_map(session: AsyncSession, entry: Any, request: _Request) -> _Plan:
    """Check one map and plan its apply. Writes nothing."""
    user = request.user
    map_obj, writable = await _writable_map(session, entry.key, user)
    messages: list[dict[str, Any]] = []
    if not request.may_edit_maps:
        messages.append(
            _message(
                NO_MAP_PERMISSION,
                "error",
                "Publishing a map needs the edit_metadata permission.",
                fix="Ask an admin.",
            )
        )
    if not writable:
        messages.append(
            _message(
                KEY_NOT_WRITABLE,
                "error",
                MAP_KEY_NOT_WRITABLE,
                fix="Publish as a new map.",
            )
        )
    if (
        entry.basemap_style is not None
        and entry.basemap_style not in request.basemap_ids
    ):
        messages.append(
            _message(
                OTHER_REFUSAL,
                "error",
                f"{entry.basemap_style!r} isn't a basemap on this server.",
                fix="Choose a basemap from GET /capabilities.",
            )
        )
    layers: list[MapLayerInput] = []
    keys: list[str] = []
    shows_non_public = False
    for layer in entry.layers:
        dataset_id = (
            layer.dataset_id
            if layer.dataset_id is not None
            else request.dataset_ids_by_key.get(layer.dataset_key)
        )
        dataset = request.datasets.get(dataset_id) if dataset_id else None
        planned = (
            request.pending_datasets.get(layer.dataset_key)
            if layer.dataset_key is not None
            else None
        )
        layer_messages, stored_layer = _check_layer(
            layer, dataset_id, dataset, pending=planned is not None
        )
        messages.extend(layer_messages)
        if dataset is not None or planned is not None:
            shows_non_public |= not _planned_public(dataset, planned)
        if stored_layer is not None:
            layers.append(stored_layer)
            keys.append(layer.key)
    plan = _Plan(result={}, map_obj=map_obj)
    removed: list[MapLayer] = []
    if map_obj is not None:
        stored = await _stored_layers(session, map_obj.id, user)
        shows_non_public |= any(
            dataset is not None and not dataset.public
            for layer, dataset in stored
            if layer.manifest_key is None
        )
        try:
            plan.layers, plan.layer_keys, removed, total = _plan_stack(
                entry, stored, layers, keys
            )
        except ValidationError:
            messages.append(
                _message(
                    OTHER_REFUSAL,
                    "error",
                    "A layer added to this map in GeoLens can't be saved as it "
                    "is, so the map can't be republished.",
                    fix="Open the map in GeoLens and save it once.",
                )
            )
            total = 0
    else:
        plan.layers, plan.layer_keys = _plan_stack(entry, [], layers, keys)[:2]
        total = len(entry.layers)
    if total > _MAX_LAYERS_PER_MAP:
        messages.append(
            _message(
                OTHER_REFUSAL,
                "error",
                f"The map would have {total} layers, more than {_MAX_LAYERS_PER_MAP}.",
                fix="Remove layers from the map in GeoLens, or publish fewer.",
            )
        )
    now = map_obj.visibility if map_obj is not None else None
    plan.write_visibility, visibility_messages = _judge_visibility(
        entry, now, shows_non_public, request
    )
    messages.extend(visibility_messages)
    messages.extend(
        _message(
            LAYER_REMOVED,
            "info",
            f"Layer {_short(layer.manifest_key)} is no longer in the map. Its "
            "dataset stays on the server.",
            fix="Open the dataset in GeoLens to delete it.",
            layer=layer.manifest_key,
        )
        for layer in removed
    )
    failed = any(message["severity"] == "error" for message in messages)
    plan.result = {
        "map_key": entry.key,
        "action": "error" if failed else "create" if map_obj is None else "update",
        "map_id": map_obj.id if map_obj is not None else None,
        "messages": messages,
        "visibility": None if failed else plan.write_visibility or now or "private",
        "styling": None if failed else "applied",
        "removed_layers": []
        if failed
        else [
            {"key": layer.manifest_key, "dataset_id": layer.dataset_id}
            for layer in removed
        ],
    }
    return plan


async def _refuse_unreadable_layers(
    session: AsyncSession, layers: Sequence[MapLayerInput], user: Identity
) -> None:
    wanted = [layer.dataset_id for layer in layers]
    readable = await bulk_check_dataset_access(
        session, wanted, user, await get_user_roles(session, user)
    )
    if any(dataset_id not in readable for dataset_id in wanted):
        raise HTTPException(
            status_code=403, detail="Cannot access one or more layer datasets"
        )


async def _write_map(
    session: AsyncSession, entry: Any, request: _Request, plan: _Plan
) -> dict[str, Any]:
    """Write a map whose check passed, through the map services. Flushes."""
    user = request.user
    map_obj = plan.map_obj
    if map_obj is None:
        # Every layer's dataset is checked before the map row exists.
        await _refuse_unreadable_layers(session, plan.layers, user)
        map_obj = await apply_map_create(
            session,
            MapCreate(name=entry.name, description=entry.description),
            user,
            record_history=False,
            ip_address=request.ip_address,
            manifest_key=entry.key,
        )
        await check_map_ownership(map_obj, user, session)
    before = map_obj.visibility
    view = entry.view
    body = MapUpdate(
        name=entry.name,
        layers=plan.layers,
        **({} if entry.description is None else {"description": entry.description}),
        **(
            {}
            if view is None
            else {
                "center_lng": view.center[0],
                "center_lat": view.center[1],
                "zoom": view.zoom,
                "bearing": view.bearing,
                "pitch": view.pitch,
            }
        ),
        **(
            {}
            if entry.basemap_style is None
            else {"basemap_style": entry.basemap_style}
        ),
        **(
            {}
            if plan.write_visibility in (None, before)
            else {"visibility": plan.write_visibility}
        ),
    )
    map_obj, _, _, _ = await apply_map_update(
        session,
        map_obj,
        body,
        user,
        record_history=False,
        ip_address=request.ip_address,
        layer_keys=plan.layer_keys,
    )
    after = map_obj.visibility
    await record_map_history_event(
        session,
        map_id=map_obj.id,
        actor=user,
        target_type="map",
        target_id=map_obj.id,
        target_name=map_obj.name,
        action="manifest.publish",
        summary=f"Published from {request.client.id} {request.client.version}",
        details={
            "client_id": request.client.id,
            "client_version": request.client.version,
            "styling_applied": True,
            "layer_keys": [layer.key for layer in entry.layers],
            **(
                {}
                if after == before
                else {"visibility": {"previous": before, "current": after}}
            ),
        },
    )
    return {**plan.result, "map_id": map_obj.id, "visibility": after}


def _refusal(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        detail = detail.get("message", "")
    return f"This map could not be published: {_short(detail, _MAX_ERROR_LENGTH)}"


async def _dry_run_map(session: AsyncSession, entry: Any, request: _Request) -> dict:
    try:
        # A database error inside one map's checks rolls back to here and
        # leaves the transaction usable for the next map.
        async with session.begin_nested():
            plan = await _check_map(session, entry, request)
        return plan.result
    except Exception:  # broad: one map's failure must not fail the other maps
        log.exception("manifest_map_check_failed", map_key=entry.key)
        return _error_result(entry.key, MAP_CHECK_FAILED)


async def _apply_map(session: AsyncSession, entry: Any, request: _Request) -> dict:
    """Check and write one map in a transaction of its own, which commits
    only when everything for the map was written."""
    try:
        await _lock_map_key(session, entry.key)
        plan = await _check_map(session, entry, request)
        if plan.result["action"] == "error":
            await session.rollback()
            return plan.result
        result = await _write_map(session, entry, request, plan)
        await session.commit()
        return result
    except HTTPException as exc:
        await session.rollback()
        return _error_result(entry.key, _refusal(exc))
    except Exception:  # broad: one map's failure must not fail the other maps
        await session.rollback()
        log.exception("manifest_map_apply_failed", map_key=entry.key)
        return _error_result(entry.key, MAP_APPLY_FAILED)


async def apply_manifest_maps(
    session: AsyncSession,
    maps: Sequence[Any],
    user: Identity,
    *,
    dry_run: bool,
    dataset_ids_by_key: Mapping[str, uuid.UUID],
    pending_datasets: Mapping[str, tuple[str | None, str]],
    public_fallback: str | None,
    client: Any,
    ip_address: str | None,
) -> list[dict[str, Any]]:
    """Check each manifest map, and outside a dry run create or update it.

    ``dataset_ids_by_key`` holds the dataset each layer's ``dataset_key``
    names; an absent key reads like a missing dataset. ``pending_datasets``
    are the request's own dataset entries that will supply a dataset, by key,
    each with the visibility (None keeps the dataset's) and status it
    publishes: a layer naming one whose dataset it can't read is checked
    without columns instead of refused, and the map's visibility is judged on
    what the entry publishes. ``client`` is the request's ``ManifestClient``.

    A dry run writes nothing; the caller rolls the session back. An apply
    commits each map that checked clean, and rolls back a map with an error
    or one whose write failed, so nothing of it is written. A map whose
    check or write fails unexpectedly is that map's error alone.
    """
    layer_dataset_ids = {
        dataset_id
        for entry in maps
        for layer in entry.layers
        if (
            dataset_id := (
                layer.dataset_id
                if layer.dataset_id is not None
                else dataset_ids_by_key.get(layer.dataset_key)
            )
        )
        is not None
    }
    request = _Request(
        user=user,
        dataset_ids_by_key=dataset_ids_by_key,
        pending_datasets=pending_datasets,
        datasets=await _readable_datasets(session, layer_dataset_ids, user),
        basemap_ids=(
            await _known_basemap_ids(session)
            if any(entry.basemap_style is not None for entry in maps)
            else set()
        ),
        may_edit_maps=await _may_edit_maps(session, user),
        may_set_public=(
            await _may_set_public(session, user)
            if any(entry.visibility == "public" for entry in maps)
            else False
        ),
        is_key=is_publish_key(session),
        public_fallback=public_fallback,
        client=client,
        ip_address=ip_address,
    )
    run = _dry_run_map if dry_run else _apply_map
    return [await run(session, entry, request) for entry in maps]
