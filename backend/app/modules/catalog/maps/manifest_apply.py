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
from app.core.processing_port import MINTED_SHARE_KEY, PendingManifestDataset
from app.core.record_types import capabilities
from app.modules.auth import permissions as auth_permissions
from app.modules.auth.schemas import GroupRef
from app.modules.catalog.authorization import (
    ANONYMOUS_MAP_VISIBILITIES,
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
    styling_kept_message,
    written_notes_digests,
)
from app.modules.catalog.maps.manifest_messages import (
    NO_MAP_PERMISSION,
    TABLE_LAYER,
    STYLING_KEPT,
    NOTES_NOT_WRITTEN,
    THUMBNAIL_NOT_STORED,
    SHARE_LINK_NOT_CREATED,
    SHARE_LINK_WITHHELD,
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
from app.modules.catalog.maps.manifest_moves import (
    Target,
    move_kept_layers,
    unsettled_sources,
    widening_moves,
)
from app.modules.catalog.maps.manifest_share import ShareMint, mint_share_link
from app.modules.catalog.maps.manifest_visibility import (
    judge_visibility,
    planned_public,
)
from app.modules.catalog.maps.manifest_sharing import (
    ShownDataset,
    group_messages,
    layer_sharing_gaps,
    lock_entry_groups,
    more_visible,
    plan_map_groups,
    planned_dataset,
    share_map,
    with_groups,
)
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.catalog.group_sharing import SharePlan
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
    clear_map_images,
    discard_map_asset_objects,
    lock_map_for_asset_write,
    check_map_ownership,
    links_retired_last,
    lock_map_layers,
    record_map_history_event,
)
from app.modules.catalog.maps.service_groups import map_groups
from app.modules.catalog.maps.service_update import apply_map_create, apply_map_update
from app.modules.settings.basemaps import list_public_basemaps
from app.platform.catalog_locks import CatalogLockConflict
from app.platform.extensions import get_catalog_port, get_permission_extension
from app.platform.jobs.in_flight import (
    datasets_with_jobs_in_flight,
    manifest_keys_with_jobs_in_flight,
)
from app.platform.record_audience import widens_audience
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

KEY_THUMBNAIL_REFUSED = (
    "The thumbnail wasn't stored: A publish key can't replace a map's thumbnail"
)

# Shape-checks a layer whose dataset didn't resolve; never stored.
_NO_DATASET = uuid.UUID(int=0)


class _Dataset(NamedTuple):
    """What the checks read of a dataset the caller can read."""

    columns: list[dict[str, Any]] | None
    record_type: str | None
    visibility: str
    record_status: str
    geometry_type: str | None
    # A raster's, None for any other dataset.
    is_dem: bool | None
    band_count: int | None
    # The columns its vector tiles carry; None for the per-zoom default.
    tile_columns: list[str] | None
    title: str = ""

    @property
    def public(self) -> bool:
        return (self.visibility, self.record_status) == ("public", "published")


@dataclass(frozen=True)
class _Request:
    """What every map of one request is checked against."""

    user: Identity
    dry_run: bool
    dataset_ids_by_key: Mapping[str, uuid.UUID]
    pending_datasets: Mapping[str | uuid.UUID, PendingManifestDataset]
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
    # The groups the apply shares the map with; None keeps its groups.
    share: SharePlan | None = None
    # Whether the caller shares as an admin, read in the map's transaction:
    # never through a publish key.
    is_admin: bool = False
    # Moved layers whose dashboard widgets fit their new dataset.
    keep_widgets_of: list[uuid.UUID] = field(default_factory=list)
    # Whether a layer the map keeps shows another dataset after the apply.
    moves_dataset: bool = False


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
    RasterAsset = get_catalog_port().raster_asset_orm_class()
    stmt = (
        select(
            Dataset.id,
            Dataset.column_info,
            Record.record_type,
            Record.visibility,
            Record.record_status,
            Dataset.geometry_type,
            RasterAsset.is_dem,
            RasterAsset.band_count,
            Dataset.tile_columns,
            Record.title,
        )
        .join(Record, Dataset.record_id == Record.id)
        .outerjoin(RasterAsset, RasterAsset.dataset_id == Dataset.id)
        .where(Dataset.id.in_(wanted))
    )
    roles = await get_user_roles(session, user)
    stmt = apply_visibility_filter(stmt, user, roles, Record, DatasetGrant)
    rows = await session.execute(stmt)
    return {
        row[0]: _Dataset(list(row[1]) if isinstance(row[1], list) else None, *row[2:])
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
) -> tuple[list[tuple[MapLayer, _Dataset | None]], set[uuid.UUID]]:
    """The map's layers in draw order, each with its dataset when the caller
    can read it, as stored now rather than as the session last loaded them,
    and which of those datasets a pending or running job still writes."""
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
    # Asked before the datasets are read: a job commits its dataset before it
    # is marked finished, so one finished by now left the dataset read below.
    busy = await datasets_with_jobs_in_flight(
        session, {layer.dataset_id for layer in layers}
    )
    datasets = await _readable_datasets(
        session, (layer.dataset_id for layer in layers), user
    )
    return [(layer, datasets.get(layer.dataset_id)) for layer in layers], busy


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


def _shown_datasets(
    plan: _Plan,
    datasets: Mapping[uuid.UUID, _Dataset],
    stored: Sequence[tuple[MapLayer, _Dataset | None]],
    unsettled: Collection[uuid.UUID],
    request: _Request,
    named_pending: Mapping[str, ShownDataset],
) -> list[ShownDataset]:
    """Each layer the planned map shows, by key (None for one added in
    GeoLens), with its dataset: one this request publishes as its entry
    leaves it, and any other when the caller reads it, which keeps its own
    audience whatever the map's. ``named_pending`` holds, by layer key, the
    dataset the manifest names when this request publishes it. A layer shows
    that dataset once the publish is done, a kept layer still on another
    dataset in the plan included, since it moves there when the maps are
    sent again. Any other layer the apply keeps shows its stored dataset."""
    readable = {
        **{layer.dataset_id: dataset for layer, dataset in stored if dataset},
        **datasets,
    }
    shown = []
    for layer, key in zip(plan.layers, plan.layer_keys, strict=False):
        if key in named_pending:
            shown.append(named_pending[key])
            continue
        dataset = readable.get(layer.dataset_id)
        planned = request.pending_datasets.get(layer.dataset_id)
        if planned is not None:
            shown.append(planned_dataset(key, layer.dataset_id, dataset, planned))
        elif dataset is not None and layer.dataset_id not in unsettled:
            shown.append(
                ShownDataset(
                    key,
                    layer.dataset_id,
                    dataset.title,
                    dataset.visibility,
                    dataset.record_status,
                )
            )
    return shown


async def _plan_sharing(
    session: AsyncSession,
    entry: Any,
    request: _Request,
    plan: _Plan,
    shows_non_public: bool,
    shown: Sequence[ShownDataset],
    messages: list[dict[str, Any]],
) -> tuple[str, list[GroupRef]]:
    """Plan who reads the map: the visibility it stores and its groups,
    with the sharing messages added to ``messages``. Only a dry run warns
    that the map reaches more people (A057); the apply that follows it
    widens the map as the dry run said."""
    map_obj = plan.map_obj
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
    plan.is_admin = "admin" in await get_user_roles(session, request.user)
    groups, plan.share = await plan_map_groups(
        session,
        entry,
        map_obj,
        request.user,
        is_admin=plan.is_admin,
        is_key=request.is_key,
        level=plan.write_visibility or now or "private",
    )
    messages.extend(group_messages(entry, plan.share))
    visibility = with_groups(plan.write_visibility or now or "private", groups)
    shares = plan.share is not None and not plan.share.unchanged
    if now is not None and plan.write_visibility in (None, now) and not shares:
        # Nothing writes the level or the grants, so a private map stays
        # private whatever grants it kept from before.
        visibility = now
    if request.dry_run and widens_audience(
        now, visibility, added_groups=bool(plan.share and plan.share.added)
    ):
        messages.append(more_visible(entry, visibility, groups))
    messages.extend(
        await layer_sharing_gaps(session, shown, visibility, groups, request.user.id)
    )
    return visibility, groups


def _name_pending(
    named_pending: dict[str, ShownDataset],
    key: str,
    dataset_id: uuid.UUID | None,
    dataset: _Dataset | None,
    planned: PendingManifestDataset | None,
) -> None:
    """Record the dataset a layer names when this request publishes it."""
    if planned is not None:
        named_pending[key] = planned_dataset(key, dataset_id, dataset, planned)


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
            session,
            map_obj.id,
            view=entry.view is not None,
            basemap=entry.basemap_style is not None,
            bookmarks=entry.bookmarks is not None,
        )
        styling_applied = styling_applies(entry.styling, edited=edited is not None)
        if not styling_applied and entry.styling == "replace_if_unedited":
            messages.append(
                _message(
                    STYLING_KEPT,
                    "info",
                    styling_kept_message(
                        # The history route's own gate: edit_metadata on a map
                        # the caller owns or administers.
                        edited if request.may_edit_maps else None
                    ),
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
    named_pending: dict[str, ShownDataset] = {}
    targets: dict[str, Target] = {}
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
        layer_messages, stored_layer = _check_layer(
            layer, dataset_id, dataset, pending=planned is not None
        )
        messages.extend(layer_messages)
        if dataset is not None or planned is not None:
            non_public_by_key[layer.key] = not planned_public(dataset, planned)
        if stored_layer is not None:
            layers.append(stored_layer)
            keys.append(layer.key)
            targets[layer.key] = Target(dataset_id, dataset, stored_layer)
            _name_pending(named_pending, layer.key, dataset_id, dataset, planned)
    plan = _Plan(result={}, map_obj=map_obj, styling_applied=styling_applied)
    plan.notes = managed_notes(
        map_obj.notes if map_obj is not None else None,
        [
            publish_line(request.client, datetime.now(UTC).date()),
            *(loss_lines(entry.loss_report) if styling_applied else ()),
        ],
        (
            await written_notes_digests(session, map_obj.id, map_obj.notes)
            if map_obj is not None
            else frozenset()
        ),
    )
    if plan.notes.digest is None:
        messages.append(_no_room_for_notes(plan.notes))
    removed: list[MapLayer] = []
    stored: list[tuple[MapLayer, _Dataset | None]] = []
    retained_non_public = False
    if map_obj is not None:
        stored, busy = await _stored_layers(session, map_obj.id, user)
        listed = {layer.key for layer in entry.layers}
        # The stored layers the map goes on showing with their own dataset; a
        # listed one shows the manifest's, counted below.
        retained_non_public = any(
            not planned_public(dataset, request.pending_datasets.get(layer.dataset_id))
            for layer, dataset in stored
            if dataset is not None
            and (
                layer.manifest_key is None
                or (layer.manifest_key not in listed and entry.styling == "keep")
            )
        )
        # Only a job that is running or queued: an entry that failed queued
        # none, so the dataset it would have replaced is settled.
        waiting = unsettled_sources(stored, targets, busy, request.pending_datasets)
        messages.extend(waiting)
        # A move that waits for its source's job is judged once it can be made.
        movable = {
            key: target
            for key, target in targets.items()
            if key not in {m["layer"] for m in waiting}
        }
        try:
            moves = move_kept_layers(
                stored,
                movable,
                map_obj.dashboard_config,
                kept=not styling_applied,
                widening=await widening_moves(
                    session,
                    stored,
                    movable,
                    map_obj.dashboard_config,
                    kept=not styling_applied,
                ),
            )
            messages.extend([*moves.errors, *moves.warnings])
            if not styling_applied:
                taking_manifest = {
                    layer.manifest_key
                    for layer, _ in stored
                    if layer.id in moves.layers
                    and layer.id not in moves.keep_widgets_of
                }
                keeping = {
                    layer.manifest_key for layer, _ in stored if layer.manifest_key
                } - taking_manifest
                # These layers keep the styling they have, not the one the
                # manifest sent, which the two checks read.
                messages[:] = [
                    m
                    for m in messages
                    if not (
                        m["code"] in (STYLE_KEY_DROPPED, COLUMN_MISSING)
                        and m["layer"] in keeping
                    )
                ]
            plan.keep_widgets_of = moves.keep_widgets_of
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
                moved=moves.layers,
            )
            plan.moves_dataset = _moves_a_dataset(stored, plan.layers)
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
    # A manifest layer counts only where the map takes it; a kept layer on a
    # dataset the caller can't read stays there.
    unmoved = {layer.manifest_key for layer, dataset in stored if dataset is None}
    shows_non_public = retained_non_public or any(
        non_public
        for key, non_public in non_public_by_key.items()
        if styling_applied or key not in unmoved
    )
    shown = _shown_datasets(plan, datasets, stored, unsettled, request, named_pending)
    stored_visibility, groups = await _plan_sharing(
        session, entry, request, plan, shows_non_public, shown, messages
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
        "groups": [] if failed else [group.name for group in groups],
        "styling": None if failed else "applied" if styling_applied else "kept",
        "removed_layers": []
        if failed
        else [
            {
                "key": layer.manifest_key,
                "dataset_id": layer.dataset_id,
                "layer_id": layer.id,
            }
            for layer in removed
        ],
    }
    return plan


def _moves_a_dataset(
    stored: Iterable[tuple[MapLayer, Any]], layers: Iterable[MapLayerInput]
) -> bool:
    before = {layer.id: layer.dataset_id for layer, _ in stored}
    return any(
        layer.id in before and before[layer.id] != layer.dataset_id for layer in layers
    )


def _no_room_for_notes(notes: ManagedNotes) -> dict[str, Any]:
    removed = (
        ", and an earlier publish's notes at the top were removed. The rest "
        "of the notes is kept as it was."
        if notes.replaced
        else ". The notes in GeoLens are kept as they were."
    )
    return _message(
        NOTES_NOT_WRITTEN,
        "info",
        "The map's notes leave no room for the publish notes, so none were "
        f"written{removed}",
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
    """Write a map whose check passed, through the map services, and give a
    map it leaves public a share link through the share service. Flushes."""
    user = request.user
    map_obj = plan.map_obj
    created = map_obj is None
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
    # The view, basemap and bookmarks are styling; a kept publish leaves them.
    view = entry.view if plan.styling_applied else None
    bookmarks = entry.bookmarks if plan.styling_applied else None
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
        **({} if bookmarks is None else {"bookmarks": bookmarks}),
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
        keep_widgets_of=plan.keep_widgets_of,
    )
    if plan.share is not None:
        await share_map(
            session,
            map_obj,
            plan.share,
            user,
            is_admin=plan.is_admin,
            ip_address=request.ip_address,
            audience_before=None if created else before,
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
            "view_written": view is not None,
            "basemap_written": basemap_style is not None,
            "bookmarks_written": bookmarks is not None,
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
    share = (
        await mint_share_link(session, map_obj.id, user, request.ip_address)
        if after in ANONYMOUS_MAP_VISIBILITIES
        else ShareMint(None)
    )
    withheld = [_message(SHARE_LINK_NOT_CREATED, "info", SHARE_LINK_WITHHELD)]
    return {
        **plan.result,
        "messages": [*plan.result["messages"], *(withheld if share.withheld else ())],
        "map_id": map_obj.id,
        "visibility": after,
        "groups": [group.name for group in await map_groups(session, map_obj.id)],
        **(
            {}
            if share.token is None
            else {MINTED_SHARE_KEY: {"token": share.token, "title": map_obj.name}}
        ),
    }


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
        await lock_entry_groups(session, entry)
        plan = await _check_map(session, entry, request)
        if plan.result["action"] == "error":
            await session.rollback()
            return plan.result
        # The share step and the image lock can refuse after the map narrows.
        async with links_retired_last(session):
            result = await _write_map(session, entry, request, plan)
            cleared: list[str] = []
            had_thumbnail = False
            if plan.moves_dataset:
                locked = await lock_map_for_asset_write(session, result["map_id"])
                had_thumbnail = locked.thumbnail_uri is not None
                cleared = await clear_map_images(session, result["map_id"], locked)
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
    try:
        await discard_map_asset_objects(session, result["map_id"], cleared)
    except Exception:  # broad: the map is written; its old images are only orphaned
        await session.rollback()
        log.exception("manifest_map_image_cleanup_failed", map_key=entry.key)
    # A thumbnail shows the manifest's styling, so it goes with it. A publish
    # key may not replace a thumbnail, judged on the one the move cleared.
    if entry.thumbnail is not None and plan.styling_applied:
        refused = (
            KEY_THUMBNAIL_REFUSED
            if request.is_key and had_thumbnail
            else await store_manifest_thumbnail(
                session,
                result["map_id"],
                entry.thumbnail,
                request.user,
                plan.published_at,
            )
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
    pending_datasets: Mapping[str | uuid.UUID, PendingManifestDataset],
    unsettled_dataset_ids: Collection[uuid.UUID],
    public_fallback: str | None,
    client: Any,
    ip_address: str | None,
) -> list[dict[str, Any]]:
    """Check each manifest map, and outside a dry run create or update it.

    ``dataset_ids_by_key`` holds the dataset each layer's ``dataset_key``
    names; an absent key reads like a missing dataset. ``pending_datasets``
    are the request's own dataset entries that will change their dataset, by
    key and by the dataset's id, each with the visibility, status, title and
    groups it publishes: a layer naming one whose dataset it can't read is
    checked without columns instead of refused, and the map's visibility and
    its readers' access to the layer are judged on what the entry publishes.
    A layer on a dataset in ``unsettled_dataset_ids`` and not pending reads
    like a missing dataset. ``client`` is the request's ``ManifestClient``.

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
