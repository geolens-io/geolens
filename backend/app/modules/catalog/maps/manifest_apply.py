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

import uuid
from datetime import UTC, datetime
from collections.abc import Collection, Iterable, Mapping, Sequence
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
    expression_icons,
    named_columns,
    rename_layer_columns,
)
from app.modules.catalog.maps.manifest_layers import plan_layer_stack
from app.modules.catalog.maps.manifest_republish import (
    ManagedNotes,
    loss_lines,
    managed_notes,
    publish_line,
    store_manifest_thumbnail,
    styling_applies,
    styling_edited_since_publish,
    written_notes_digests,
    written_view_fields,
)
from app.modules.catalog.maps.manifest_messages import (
    NO_MAP_PERMISSION,
    TABLE_LAYER,
    STYLING_KEPT,
    NOTES_NOT_WRITTEN,
    THUMBNAIL_NOT_STORED,
    KEPT_LAYER_DATASET,
    KEY_NOT_WRITABLE,
    DATASET_NOT_READY,
    LAYER_REMOVED,
    STYLE_KEY_DROPPED,
    COLUMN_MISSING,
    OTHER_REFUSAL,
    MAX_ERROR_LENGTH as _MAX_ERROR_LENGTH,
    MAX_REPORTED_ERRORS as _MAX_REPORTED_ERRORS,
    error_result as _error_result,
    listed as _listed,
    message as _message,
    problem as _problem,
    short as _short,
)
from app.modules.catalog.maps.manifest_visibility import (
    judge_visibility,
    planned_public,
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
    lock_map_layers,
    record_map_history_event,
)
from app.modules.catalog.maps.service_groups import map_has_groups, map_visibility_for
from app.modules.catalog.maps.service_update import apply_map_create, apply_map_update
from app.modules.settings.basemaps import list_public_basemaps
from app.platform.catalog_locks import CatalogLockConflict
from app.platform.extensions import get_permission_extension
from app.platform.jobs.in_flight import (
    datasets_with_jobs_in_flight,
    manifest_keys_with_jobs_in_flight,
)
from app.platform.request_credential import is_publish_key

MAP_KEY_NOT_WRITABLE = "This map key belongs to a map you can't edit."
MAP_CHECK_FAILED = "This map could not be checked. Try again."
MAP_APPLY_FAILED = "This map could not be published. Try again."
MAP_BUSY = "Another change to this map is in progress. Try again shortly."

log = structlog.get_logger()
# One answer for a dataset that doesn't exist, isn't ready and can't be read,
# so the answer tells a caller nothing about datasets they can't see.
DATASET_UNAVAILABLE = (
    "Layer {layer}: its dataset doesn't exist, hasn't finished publishing, "
    "or you can't read it."
)

# Shape-checks a layer whose dataset didn't resolve; never stored.
_NO_DATASET = uuid.UUID(int=0)


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
    dry_run: bool
    dataset_ids_by_key: Mapping[str, uuid.UUID]
    pending_datasets: Mapping[str | uuid.UUID, tuple[str | None, str]]
    unsettled_dataset_ids: Collection[uuid.UUID]
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
    styling_applied: bool = True
    notes: ManagedNotes | None = None
    # The map's updated_at as the apply committed it.
    published_at: datetime | None = None
    # Stored rows the apply leaves out of its layer list and must not delete.
    keep_layer_ids: list[uuid.UUID] = field(default_factory=list)


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
    session: AsyncSession, key: str, user: Identity, *, lock: bool = False
) -> tuple[Map | None, bool]:
    """The map ``key`` names and whether the caller may write it.

    ``(None, True)`` when no map has the key, and ``(None, False)`` for a map
    the caller can't write or doesn't own, so nothing of it reaches the
    caller. Keys are global, so an admin's write access alone would let a key
    someone else created steer the admin's publish into that person's map;
    only the owner writes a map through its key, as for dataset keys. With
    ``lock`` the writer's map is returned as read under its row lock, which
    the builder and sharing writes take too, held until the transaction
    ends.
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
    if lock:
        await lock_map_layers(session, map_obj.id)
        map_obj = (
            await session.execute(
                select(Map)
                .where(Map.id == map_obj.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
    if map_obj.created_by != user.id:
        return None, False
    return map_obj, True


async def _stored_layers(
    session: AsyncSession, map_id: uuid.UUID, user: Identity
) -> list[tuple[MapLayer, _Dataset | None]]:
    """The map's layers in draw order, each with its dataset when the caller
    can read it, as stored now rather than as the session last loaded them."""
    layers = (
        (
            await session.execute(
                select(MapLayer)
                .where(MapLayer.map_id == map_id)
                .order_by(MapLayer.sort_order, MapLayer.id)
                .execution_options(populate_existing=True)
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


def _layer_refused(layer: Any, exc: ValidationError) -> dict[str, Any]:
    problems = "; ".join(
        _problem(error)
        for error in exc.errors(include_input=False)[:_MAX_REPORTED_ERRORS]
    )
    return _message(
        OTHER_REFUSAL,
        "error",
        f"Layer {layer.key} can't be saved: {problems}",
        layer=layer.key,
    )


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
    if expression_icons(style_config):
        messages.append(
            _message(
                OTHER_REFUSAL,
                "error",
                f"Layer {layer.key}: a symbol icon must be an icon name, not an "
                "expression.",
                fix="Send the name of an icon in the GeoLens sprite.",
                layer=layer.key,
            )
        )
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
        messages.append(_layer_refused(layer, exc))
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
    renamed = rename_layer_columns(checked, lambda name: stored.stored(name) or name)
    try:
        # The stored names can be longer than the source names the size caps
        # were checked against.
        return messages, MapLayerInput.model_validate(renamed.model_dump())
    except ValidationError as exc:
        messages.append(_layer_refused(layer, exc))
        return messages, None


async def _check_map(session: AsyncSession, entry: Any, request: _Request) -> _Plan:
    """Check one map and plan its apply. Writes nothing.

    An apply takes the map's row lock before it reads anything else of the
    map, and plans from what it reads under the lock.
    """
    user = request.user
    map_obj, writable = await _writable_map(
        session, entry.key, user, lock=not request.dry_run
    )
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
    styling_applied = True
    if map_obj is not None:
        edited = await styling_edited_since_publish(
            session, map_obj.id, written_view_fields(entry)
        )
        styling_applied = styling_applies(entry.styling, edited=edited)
        if not styling_applied and entry.styling == "replace_if_unedited":
            messages.append(
                _message(
                    STYLING_KEPT,
                    "info",
                    "The map's styling was edited in GeoLens since the last "
                    "publish that replaced it, so its styling was kept.",
                    fix='Send styling "replace" to replace it.',
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
    non_public_by_key: dict[str, bool] = {}
    dataset_by_key: dict[str, uuid.UUID | None] = {}
    datasets, unsettled = request.datasets, request.unsettled_dataset_ids
    if not request.dry_run:
        dataset_ids = _layer_dataset_ids([entry], request.dataset_ids_by_key)
        datasets = await _readable_datasets(session, dataset_ids, user)
        # Read again under this map's locks: a replacement queued while the
        # apply waited for them is not the dataset the publish describes.
        unsettled = {
            *unsettled,
            *await _settling_now(session, entry, set(datasets), request),
        }
    for layer in entry.layers:
        dataset_id = (
            layer.dataset_id
            if layer.dataset_id is not None
            else request.dataset_ids_by_key.get(layer.dataset_key)
        )
        planned = request.pending_datasets.get(
            layer.dataset_key if layer.dataset_key is not None else layer.dataset_id
        )
        # A dataset a job is still replacing isn't the one the publish
        # describes yet, by key or by id.
        dataset = (
            datasets.get(dataset_id)
            if dataset_id and (planned is not None or dataset_id not in unsettled)
            else None
        )
        dataset_by_key[layer.key] = dataset_id
        layer_messages, stored_layer = _check_layer(
            layer, dataset_id, dataset, pending=planned is not None
        )
        messages.extend(layer_messages)
        if dataset is not None or planned is not None:
            non_public_by_key[layer.key] = not planned_public(dataset, planned)
        if stored_layer is not None:
            layers.append(stored_layer)
            keys.append(layer.key)
    plan = _Plan(result={}, map_obj=map_obj, styling_applied=styling_applied)
    plan.notes = managed_notes(
        map_obj.notes if map_obj is not None else None,
        [
            publish_line(request.client, datetime.now(UTC).date()),
            *(loss_lines(entry.loss_report) if styling_applied else ()),
        ],
        (
            await written_notes_digests(session, map_obj.id)
            if map_obj is not None
            else frozenset()
        ),
    )
    if plan.notes.digest is None:
        messages.append(
            _message(
                NOTES_NOT_WRITTEN,
                "info",
                "The map's notes leave no room for the publish notes, so none "
                "were written. The notes in GeoLens are kept whole.",
            )
        )
    removed: list[MapLayer] = []
    stored: list[tuple[MapLayer, _Dataset | None]] = []
    retained_non_public = False
    if map_obj is not None:
        stored = await _stored_layers(session, map_obj.id, user)
        listed = {layer.key for layer in entry.layers}
        # The stored layers the map goes on showing with their own dataset.
        retained_non_public = any(
            not planned_public(dataset, request.pending_datasets.get(layer.dataset_id))
            for layer, dataset in stored
            if dataset is not None
            and (
                layer.manifest_key is None
                or (layer.manifest_key in listed and not styling_applied)
                or (layer.manifest_key not in listed and entry.styling == "keep")
            )
        )
        try:
            (
                plan.layers,
                plan.layer_keys,
                removed,
                total,
                plan.keep_layer_ids,
            ) = plan_layer_stack(
                entry,
                stored,
                layers,
                keys,
                keep_styling=not styling_applied,
                remove_missing=entry.styling != "keep",
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
        messages.extend(
            _kept_datasets(stored, dataset_by_key, kept=not styling_applied)
        )
    else:
        plan.layers, plan.layer_keys = plan_layer_stack(entry, [], layers, keys)[:2]
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
    # A manifest layer counts only where the map takes it; a kept matched
    # layer goes on showing its stored dataset, counted above.
    stored_keys = {layer.manifest_key for layer, _ in stored if layer.manifest_key}
    shows_non_public = retained_non_public or any(
        non_public
        for key, non_public in non_public_by_key.items()
        if styling_applied or key not in stored_keys
    )
    now = map_obj.visibility if map_obj is not None else None
    plan.write_visibility, visibility_messages = judge_visibility(
        entry,
        now,
        shows_non_public,
        public_fallback=request.public_fallback,
        may_set_public=request.may_set_public,
        is_key=request.is_key,
    )
    messages.extend(visibility_messages)
    stored_visibility = now or "private"
    if plan.write_visibility is not None:
        stored_visibility = map_visibility_for(
            plan.write_visibility,
            map_obj is not None and await map_has_groups(session, map_obj.id),
        )
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
        "visibility": None if failed else stored_visibility,
        "styling": None if failed else "applied" if styling_applied else "kept",
        "removed_layers": []
        if failed
        else [
            {"key": layer.manifest_key, "dataset_id": layer.dataset_id}
            for layer in removed
        ],
    }
    return plan


def _kept_datasets(
    stored: Iterable[tuple[MapLayer, _Dataset | None]],
    dataset_by_key: Mapping[str, uuid.UUID | None],
    *,
    kept: bool,
) -> Iterable[dict[str, Any]]:
    """When the styling is ``kept``, a warning for each matched keyed layer
    whose manifest dataset, None for one the request creates, it leaves
    unshown."""
    if not kept:
        return
    for layer, _ in stored:
        key = layer.manifest_key
        if key in dataset_by_key and dataset_by_key[key] != layer.dataset_id:
            yield _message(
                KEPT_LAYER_DATASET,
                "warning",
                f"Layer {_short(key)} still shows its earlier dataset, because "
                "the map's styling was kept.",
                fix='Send styling "replace" to show the new dataset.',
                layer=key,
            )


async def _settling_now(
    session: AsyncSession,
    entry: Any,
    readable_ids: set[uuid.UUID],
    request: _Request,
) -> set[uuid.UUID]:
    """Which of ``readable_ids``, the map's layer datasets the caller can
    read, a pending or running job writes into now, by the dataset or by the
    key that names it. No job is returned."""
    keys = {layer.dataset_key for layer in entry.layers if layer.dataset_key}
    busy_keys = await manifest_keys_with_jobs_in_flight(session, keys)
    busy = await datasets_with_jobs_in_flight(session, readable_ids)
    busy |= {
        request.dataset_ids_by_key[key]
        for key in busy_keys
        if key in request.dataset_ids_by_key
    } & readable_ids
    return busy


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
    # The view and the basemap are styling; a kept publish leaves them.
    view = entry.view if plan.styling_applied else None
    basemap_style = entry.basemap_style if plan.styling_applied else None
    body = MapUpdate(
        name=entry.name,
        layers=plan.layers,
        notes=plan.notes.text,
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
        **({} if basemap_style is None else {"basemap_style": basemap_style}),
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
        keep_layer_ids=plan.keep_layer_ids,
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
            "styling_applied": plan.styling_applied,
            "notes_digest": plan.notes.digest,
            "layer_keys": [layer.key for layer in entry.layers],
            **(
                {}
                if after == before
                else {"visibility": {"previous": before, "current": after}}
            ),
        },
    )
    plan.published_at = map_obj.updated_at
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
    except HTTPException as exc:
        await session.rollback()
        return _error_result(entry.key, _refusal(exc))
    except CatalogLockConflict:
        await session.rollback()
        return _error_result(entry.key, MAP_BUSY)
    except Exception:  # broad: one map's failure must not fail the other maps
        await session.rollback()
        log.exception("manifest_map_apply_failed", map_key=entry.key)
        return _error_result(entry.key, MAP_APPLY_FAILED)
    # A thumbnail shows the manifest's styling, so it goes with it.
    if entry.thumbnail is not None and plan.styling_applied:
        refused = await store_manifest_thumbnail(
            session, result["map_id"], entry.thumbnail, request.user, plan.published_at
        )
        if refused is not None:
            warning = _message(THUMBNAIL_NOT_STORED, "warning", refused)
            result = {**result, "messages": [*result["messages"], warning]}
    return result


def _layer_dataset_ids(
    maps: Iterable[Any], dataset_ids_by_key: Mapping[str, uuid.UUID]
) -> set[uuid.UUID]:
    return {
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


async def apply_manifest_maps(
    session: AsyncSession,
    maps: Sequence[Any],
    user: Identity,
    *,
    dry_run: bool,
    dataset_ids_by_key: Mapping[str, uuid.UUID],
    pending_datasets: Mapping[str | uuid.UUID, tuple[str | None, str]],
    unsettled_dataset_ids: Collection[uuid.UUID],
    public_fallback: str | None,
    client: Any,
    ip_address: str | None,
) -> list[dict[str, Any]]:
    """Check each manifest map, and outside a dry run create or update it.

    ``dataset_ids_by_key`` holds the dataset each layer's ``dataset_key``
    names; an absent key reads like a missing dataset. ``pending_datasets``
    are the request's own dataset entries that will change their dataset, by
    key and by the dataset's id, each with the visibility (None keeps the
    dataset's) and status it publishes: a layer naming one whose dataset it
    can't read is checked without columns instead of refused, and the map's
    visibility is judged on what the entry publishes. A layer on a dataset in
    ``unsettled_dataset_ids`` and not pending reads like a missing dataset.
    ``client`` is the request's ``ManifestClient``.

    A dry run writes nothing; the caller rolls the session back. An apply
    commits each map that checked clean, and rolls back a map with an error
    or one whose write failed, so nothing of it is written. A map whose
    check or write fails unexpectedly is that map's error alone.
    """
    request = _Request(
        user=user,
        dry_run=dry_run,
        dataset_ids_by_key=dataset_ids_by_key,
        pending_datasets=pending_datasets,
        unsettled_dataset_ids=unsettled_dataset_ids,
        # An apply reads each map's datasets again in the map's transaction.
        datasets=(
            await _readable_datasets(
                session, _layer_dataset_ids(maps, dataset_ids_by_key), user
            )
            if dry_run
            else {}
        ),
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
