"""Map CRUD, listing, update, delete, and duplicate helpers."""

import re
import uuid
from collections.abc import Iterable, Sequence
from typing import cast

import structlog
from fastapi import HTTPException, status
from sqlalchemy import Row, Select, func, or_, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.db.sqlstate import is_lock_conflict
from app.core.identity import Identity
from app.modules.auth.models import User
from app.modules.catalog.authorization import (
    apply_map_visibility_filter,
    apply_visibility_filter,
    check_map_access,
)
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.catalog.maps.dashboard import (
    DashboardConfigInput,
    drop_repointed,
    fork_dashboard,
    merge_dashboard,
    shows_widgets,
)
from app.modules.catalog.maps.service_diff import (
    _coerce_uuid,
    _replace_layers,
    _unreadable_layer_ids,
)
from app.modules.catalog.maps.sharing import readable_thumbnail_urls
from app.modules.catalog.maps.service_layers import (
    MAP_WRITE_DENIED,
    bulk_check_dataset_access,
    lock_map_layers,
    recheck_map_ownership,
    terrain_dataset_ids_visible_to,
)
from app.modules.catalog.write_recheck import admit_writer
from app.core.text import escape_ilike
from app.modules.catalog.maps.style_json import project_terrain_config
from app.modules.catalog.maps.service_shared import (
    LayerRow,
    _fetch_layer_rows_ordered,
    _resolve_save_response_metadata,
)

logger = structlog.stdlib.get_logger(__name__)

_COPY_SUFFIX_RE = re.compile(r"\s*\(copy(?:\s+(\d+))?\)\s*$")
_UNSET = object()


def new_map_asset_key(prefix: str, map_id: uuid.UUID, ext: str) -> str:
    """A storage key for one map image that no later upload can reuse.

    A reused key (``{prefix}/{map_id}.{ext}``) lets a race outlive the row
    lock: request A re-reads a committed key as dead, request B writes and
    commits that same name, then A's delete removes the object B just
    published (404). A random component per write closes this: once the row
    moves off a key, nothing can move it back.

    The extension stays last: ``get_thumbnail``/``get_og_image`` pick the
    media type with ``endswith(".jpg")``. Unversioned keys already stored keep
    working since the row holds the key verbatim.
    """
    return f"{prefix}/{map_id}-{uuid.uuid4().hex}.{ext}"


def _is_lock_timeout_error(exc: BaseException) -> bool:
    """True for the shared lock-conflict states (55P03, 40P01), in either shape."""
    return is_lock_conflict(exc)


async def lock_map_for_asset_write(session: AsyncSession, map_id: uuid.UUID) -> Row:
    """Take the row lock that serializes one map's asset replacements.

    Callers take it after validating the payload, so no decode or image
    verification runs under the lock. Re-checks the writer
    ``check_map_ownership`` admitted.

    Overlapping uploads can race their cleanup and strand the row on an
    object the other just deleted (404 on read). Held through the caller's
    commit; ``discard_map_asset_objects`` re-reads the committed row as the
    other half, since a lock can't outlive the commit that releases it.
    Raises 404 centrally so all three callers agree, and selects columns (not
    ``Map``) so a stale identity-mapped instance can't shadow a fresh commit.

    ``SET LOCAL lock_timeout = '2s'`` bounds the wait, since a degraded
    storage backend could otherwise queue every writer behind this lock (a
    lost wait, 55P03, maps to 409).
    """
    await session.execute(text("SET LOCAL lock_timeout = '2s'"))
    try:
        result = await session.execute(
            select(Map.thumbnail_uri, Map.og_image_uri)
            .where(Map.id == map_id)
            .with_for_update()
        )
    except DBAPIError as exc:
        if not _is_lock_timeout_error(exc):
            raise
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "map_asset_write_locked",
                "message": "Another write to this map's assets is in progress. Retry shortly.",
            },
        ) from exc
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await recheck_map_ownership(session, map_id)
    return row


async def _live_map_asset_keys(
    session: AsyncSession, map_id: uuid.UUID
) -> frozenset[str]:
    """The asset keys the map row points at right now, as committed.

    Read after the caller's commit, so it starts a fresh transaction and sees
    whatever another request committed in the meantime. An empty set is the
    right answer for a deleted map: nothing references its objects any more.
    """
    result = await session.execute(
        select(Map.thumbnail_uri, Map.og_image_uri).where(Map.id == map_id)
    )
    row = result.one_or_none()
    return frozenset(key for key in (row or ()) if key)


async def discard_map_asset_objects(
    session: AsyncSession,
    map_id: uuid.UUID,
    storage_keys: Iterable[str | None],
) -> None:
    """Remove obsolete thumbnail and OG-image objects after commit, best effort.

    Callers hold lock_map_for_asset_write through commit. Re-read the committed
    row before deleting, and rely on unique upload keys because the read and
    delete are not atomic. A failed liveness read skips cleanup to protect live
    objects; storage failures must not fail an already-committed request.
    """
    from app.platform.storage.reap import delete_objects_best_effort
    from app.platform.storage.titiler_url import resolve_current_storage_key

    candidates = {key for key in storage_keys if key}
    if not candidates:
        return
    try:
        live = await _live_map_asset_keys(session, map_id)
    except Exception:  # broad: any failure of the post-commit read
        # The read runs after commit, so a transient failure shouldn't 500 an
        # already-succeeded request. Skip the deletes: an orphan costs less
        # than deleting a live object.
        logger.warning(
            "map_asset_liveness_read_failed", map_id=str(map_id), exc_info=True
        )
        return

    await delete_objects_best_effort(
        [resolve_current_storage_key(key) for key in sorted(candidates - live)],
        "map_asset_object_delete_failed",
    )
    for key in sorted(candidates & live):
        logger.info("map_asset_object_delete_skipped_still_referenced", storage_key=key)


async def check_map_ownership(
    map_obj: Map, user: Identity, db: AsyncSession
) -> set[str]:
    """Verify user owns the map or is admin and return the user's roles.

    Raises 404 when the user can't read the map, like a missing one, and 403
    when they read it but neither own it nor are admin. The map row locks
    check the caller again; see ``recheck_map_ownership``.
    """
    roles = await check_map_access(db, map_obj, user)
    if map_obj.created_by != user.id and "admin" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=MAP_WRITE_DENIED
        )
    admit_writer(db, ("map", map_obj.id), user)
    return roles


async def create_map(
    session: AsyncSession,
    name: str,
    description: str | None,
    created_by: uuid.UUID,
    notes: str | None = None,
    terrain_config: dict | None = None,
    basemap_config: dict | None = None,
) -> Map:
    """Create a map. Does NOT commit."""
    map_obj = Map(
        name=name,
        description=description,
        notes=notes,
        terrain_config=terrain_config,
        basemap_config=basemap_config,
        created_by=created_by,
    )
    session.add(map_obj)
    await session.flush()
    return map_obj


async def get_map(
    session: AsyncSession,
    map_id: uuid.UUID,
) -> Map | None:
    """Fetch single map by ID."""
    result = await session.execute(select(Map).where(Map.id == map_id))
    return result.scalar_one_or_none()


async def get_map_with_layers(
    session: AsyncSession,
    map_id: uuid.UUID,
) -> tuple[Map | None, list[LayerRow], str | None, str | None]:
    """Fetch map and its layers with dataset info, forked_from_name, and owner_username.

    Returns (map, layer_rows, forked_from_name, owner_username), or
    (None, [], None, None) if not found. One Map+ForkedMap+User LEFT JOIN
    keeps GET /maps/{id} at 2 queries; the save path uses helpers because
    map_obj is already in-session.
    """
    ForkedMap = aliased(Map)
    map_stmt = (
        select(
            Map,
            ForkedMap.name.label("forked_from_name"),
            User.username.label("owner_username"),
        )
        .outerjoin(ForkedMap, Map.forked_from == ForkedMap.id)
        .outerjoin(User, Map.created_by == User.id)
        .where(Map.id == map_id)
    )
    map_row = (await session.execute(map_stmt)).one_or_none()
    if map_row is None:
        return None, [], None, None
    map_obj, forked_from_name, owner_username = map_row
    layer_rows = await _fetch_layer_rows_ordered(session, map_id)
    return map_obj, layer_rows, forked_from_name, owner_username


async def _visible_layer_ids(
    session: AsyncSession,
    map_ids: Sequence[uuid.UUID],
    user: Identity | None,
    user_roles: set[str],
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """The ids of the layers map reads show ``user``, by map, for one page of maps.

    A query keyed by page IDs bounds work at every offset and uses the
    map_layers.map_id index without reading unrelated maps.
    """
    if not map_ids:
        return {}
    stmt = (
        select(MapLayer.map_id, MapLayer.id)
        .join(Dataset, MapLayer.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(MapLayer.map_id.in_(map_ids))
    )
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
    shown: dict[uuid.UUID, list[uuid.UUID]] = {}
    for map_id, layer_id in (await session.execute(stmt)).all():
        shown.setdefault(map_id, []).append(layer_id)
    return shown


async def maps_with_dashboards(
    session: AsyncSession,
    maps: Sequence[Map],
    user: Identity | None,
    user_roles: set[str] | None,
    shown: dict[uuid.UUID, list[uuid.UUID]] | None = None,
) -> set[uuid.UUID]:
    """The ids of the maps that show ``user`` at least one dashboard widget.

    ``shown`` is the layers the caller sees by map, when the caller has read
    them already; otherwise they are read here for the maps with a dashboard.
    """
    with_config = [m for m in maps if m.dashboard_config is not None]
    if shown is None:
        shown = await _visible_layer_ids(
            session, [m.id for m in with_config], user, user_roles or set()
        )
    return {
        m.id
        for m in with_config
        if shows_widgets(m.dashboard_config, shown.get(m.id, []))
    }


async def list_maps(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 20,
    user: Identity | None = None,
    user_roles: set[str] | None = None,
    search: str | None = None,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
    visibilities: Sequence[str] | None = None,
    owned_only: bool = False,
) -> tuple[list[dict], int]:
    """List maps with layer counts, filtered by visibility rules.

    - Admins can see every map; explicit filters still apply.
    - Authenticated non-admin users see: their own maps + all internal + all public,
      and restricted maps shared with one of their groups.
    - If user_roles is omitted, treats user as non-admin.
    - search: ILIKE filter on name and description.
    - sort_by: name, created_at, updated_at (default). Unknown values fall back to updated_at.
    - sort_dir: asc or desc.
    - visibilities: additional filter on Map.visibility (additive on top of RBAC).
    - owned_only: restrict to the caller's maps; anonymous callers get no maps.
    - layer_count counts only the layers whose dataset map reads show the caller,
      and has_dashboard is true when such a read shows a dashboard widget.

    Returns (list of dicts with map fields + layer_count + created_by_username, total).
    """
    user_id = user.id if user is not None else None
    if owned_only and user_id is None:
        return [], 0
    if user_roles is None:
        user_roles = set()

    is_admin = "admin" in user_roles

    def _apply_vis_filter(stmt: Select) -> Select:
        return apply_map_visibility_filter(stmt, user_id, is_admin)

    def _apply_extra_filters(stmt: Select) -> Select:
        if owned_only:
            stmt = stmt.where(Map.created_by == user_id)
        if search:
            # escape_ilike() escapes \, % and _ (backslash first, or later
            # replacements double-escape). Lowercase both column and pattern
            # to match the functional trigram indexes (ix_maps_name_trgm,
            # ix_maps_description_trgm); a bare ILIKE on the raw column falls
            # back to a Seq Scan.
            pattern = f"%{escape_ilike(search)}%".lower()
            stmt = stmt.where(
                or_(
                    func.lower(Map.name).like(pattern, escape="\\"),
                    func.lower(func.coalesce(Map.description, "")).like(
                        pattern, escape="\\"
                    ),
                )
            )
        if visibilities:
            stmt = stmt.where(Map.visibility.in_(visibilities))
        return stmt

    sort_column_map = {
        "name": Map.name,
        "created_at": Map.created_at,
        "updated_at": Map.updated_at,
    }
    col = sort_column_map.get(sort_by, Map.updated_at)
    order_clause = col.asc() if sort_dir == "asc" else col.desc()

    count_base = select(func.count()).select_from(Map)
    count_base = _apply_vis_filter(count_base)
    count_base = _apply_extra_filters(count_base)
    total_result = await session.execute(count_base)
    total = total_result.scalar_one()

    # Paginated maps with author username. The layers the caller sees are
    # fetched separately, scoped to this page — see _visible_layer_ids.
    stmt = (
        select(
            Map,
            User.username.label("created_by_username"),
        )
        .outerjoin(User, Map.created_by == User.id)
        # Batch-seeded rows share a server-default timestamp; add a
        # unique tiebreaker so pagination is stable.
        .order_by(order_clause, Map.id)
        .offset(skip)
        .limit(limit)
    )
    stmt = _apply_vis_filter(stmt)
    stmt = _apply_extra_filters(stmt)

    result = await session.execute(stmt)
    rows = result.all()
    page = [row[0] for row in rows]
    shown = await _visible_layer_ids(session, [m.id for m in page], user, user_roles)
    dashboards = await maps_with_dashboards(session, page, user, user_roles, shown)
    thumbnail_urls = await readable_thumbnail_urls(session, page, user)

    maps = []
    for row in rows:
        map_obj = row[0]
        maps.append(
            {
                "id": map_obj.id,
                "name": map_obj.name,
                "description": map_obj.description,
                "visibility": map_obj.visibility,
                "thumbnail_url": thumbnail_urls.get(map_obj.id),
                "thumbnail_updated_at": map_obj.thumbnail_updated_at,
                "layer_count": len(shown.get(map_obj.id, [])),
                "has_dashboard": map_obj.id in dashboards,
                "created_by": map_obj.created_by,
                "created_by_username": row[1],
                "created_at": map_obj.created_at,
                "updated_at": map_obj.updated_at,
            }
        )

    return maps, total


async def _keeps_hidden_terrain(
    session: AsyncSession, stored: object, requested: object, user: Identity | None
) -> bool:
    """Whether a request naming no DEM keeps a stored DEM ``user`` can't read."""
    if not isinstance(stored, dict) or stored.get("source_dataset_id") is None:
        return False
    if isinstance(requested, dict) and requested.get("source_dataset_id") is not None:
        return False
    visible = await terrain_dataset_ids_visible_to(session, stored, (), user)
    return str(stored["source_dataset_id"]) not in visible


async def update_map(
    session: AsyncSession,
    map_id: uuid.UUID,
    *,
    name: str | None = None,
    description: str | None = None,
    notes: str | None | object = _UNSET,
    center_lng: float | None = None,
    center_lat: float | None = None,
    zoom: float | None = None,
    bearing: float | None = None,
    pitch: float | None = None,
    basemap_style: str | None = None,
    show_basemap_labels: bool | None = None,
    basemap_config: dict | None | object = _UNSET,
    terrain_config: dict | None | object = _UNSET,
    dashboard_config: dict | None | object = _UNSET,
    visibility: str | None = None,
    plugins: list[str] | None | object = _UNSET,
    legend_title: str | None | object = _UNSET,
    layers: list[dict] | None = None,
    user: Identity | None = None,
) -> tuple[Map, list[LayerRow], str | None, str | None]:
    """Update map fields. If 'layers' key present, replace all layers.

    ``user`` is the caller the save acts for (None reads as anonymous). Layers
    whose dataset map reads hide from it survive a replacement, and a stored
    terrain binding to a DEM hidden from it survives a request naming no DEM.
    A ``dashboard_config`` is checked against the layers the map has after the
    save (``merge_dashboard``).

    A ``visibility`` goes through ``prepare_map_visibility``, which may make it
    restricted, revoke the map's links, or raise ``RestrictedWithoutGroupsError``.

    Raises ValueError if not found. Flushes but does NOT commit --
    callers must own the commit lifecycle.

    Returns the same 4-tuple shape as ``get_map_with_layers``:
    ``(Map, layer_rows, forked_from_name, owner_username)``. Built from
    in-session ORM state so callers don't need a post-save re-fetch.
    """
    if layers is not None or dashboard_config is not _UNSET:
        await lock_map_layers(session, map_id)
    # The caller loaded this map before any lock; the merges below need the
    # stored values as they are now, not the identity map's copy.
    result = await session.execute(
        select(Map).where(Map.id == map_id).execution_options(populate_existing=True)
    )
    map_obj = result.scalar_one_or_none()
    if map_obj is None:
        raise ValueError(f"Map {map_id} not found")
    if visibility is not None:
        from app.modules.catalog.maps.service_groups import prepare_map_visibility

        visibility = await prepare_map_visibility(session, map_id, visibility)

    # Update scalar fields (skip None values, except explicit notes=null which
    # clears private builder notes, and explicit plugins=null which restores
    # client-default plugin behavior).
    scalar_fields = {
        "name": name,
        "description": description,
        "center_lng": center_lng,
        "center_lat": center_lat,
        "zoom": zoom,
        "bearing": bearing,
        "pitch": pitch,
        "basemap_style": basemap_style,
        "show_basemap_labels": show_basemap_labels,
        "visibility": visibility,
    }
    for key, value in scalar_fields.items():
        if value is not None:
            setattr(map_obj, key, value)
    if notes is not _UNSET:
        map_obj.notes = cast(str | None, notes)
    if basemap_config is not _UNSET:
        map_obj.basemap_config = cast(dict | None, basemap_config)
    if terrain_config is not _UNSET and not await _keeps_hidden_terrain(
        session, map_obj.terrain_config, terrain_config, user
    ):
        map_obj.terrain_config = cast(dict | None, terrain_config)
    if plugins is not _UNSET:
        map_obj.plugins = cast(list[str] | None, plugins)
    if legend_title is not _UNSET:
        # Treat empty/whitespace-only titles as "no custom title" so the
        # legend falls back to the default heading on the read path.
        title = cast(str | None, legend_title)
        map_obj.legend_title = title.strip() if title and title.strip() else None

    # Replace layers if provided
    datasets_before: dict[uuid.UUID, uuid.UUID] = {}
    if layers is not None:
        if map_obj.dashboard_config is not None:
            datasets_before = await _layer_datasets(session, map_id)
        created_ids = await _replace_layers(session, map_id, layers, user)
        dashboard_config = _with_created_layer_ids(dashboard_config, created_ids)
    if dashboard_config is not _UNSET or datasets_before:
        map_obj.dashboard_config = await _saved_dashboard(
            session, map_obj, dashboard_config, user, datasets_before
        )

    await session.flush()
    # The flush's UPDATE holds the map row when there was one to write.
    await recheck_map_ownership(session, map_id)
    # One LEFT JOIN reads forked_name, owner_username and the DB-side
    # updated_at, so no ``session.refresh(map_obj)`` is needed.
    layer_rows = await _fetch_layer_rows_ordered(session, map_obj.id)
    forked_name, owner_username, db_updated_at = await _resolve_save_response_metadata(
        session, map_obj
    )
    if db_updated_at is not None:
        map_obj.updated_at = db_updated_at
    return map_obj, layer_rows, forked_name, owner_username


def _with_created_layer_ids(
    dashboard: object, created_ids: dict[uuid.UUID, uuid.UUID]
) -> object:
    """``dashboard`` with each widget's layer id swapped for the id the server
    gave the layer this request created under it."""
    if not created_ids or not isinstance(dashboard, dict):
        return dashboard
    widgets = dashboard.get("widgets")
    if not isinstance(widgets, list):
        return dashboard
    remapped = []
    for widget in widgets:
        sent_id = (
            _coerce_uuid(widget.get("layer_id")) if isinstance(widget, dict) else None
        )
        if sent_id in created_ids:
            widget = {**widget, "layer_id": str(created_ids[sent_id])}
        remapped.append(widget)
    return {**dashboard, "widgets": remapped}


async def _layer_datasets(
    session: AsyncSession, map_id: uuid.UUID
) -> dict[uuid.UUID, uuid.UUID]:
    rows = await session.execute(
        select(MapLayer.id, MapLayer.dataset_id).where(MapLayer.map_id == map_id)
    )
    return {layer_id: dataset_id for layer_id, dataset_id in rows.all()}


async def _saved_dashboard(
    session: AsyncSession,
    map_obj: Map,
    sent: object,
    user: Identity | None,
    datasets_before: dict[uuid.UUID, uuid.UUID],
) -> dict | None:
    """The dashboard after a save that sent one (``sent`` is a dict or None),
    or that replaced the layers (``sent`` is ``_UNSET``)."""
    layers = list(
        (
            await session.scalars(select(MapLayer).where(MapLayer.map_id == map_obj.id))
        ).all()
    )
    repointed = {
        layer.id
        for layer in layers
        if datasets_before.get(layer.id, layer.dataset_id) != layer.dataset_id
    }
    stored = drop_repointed(map_obj.dashboard_config, repointed)
    if sent is _UNSET:
        return stored
    return merge_dashboard(
        None if sent is None else DashboardConfigInput.model_validate(sent),
        stored,
        layer_ids={layer.id for layer in layers},
        hidden_layer_ids=await _unreadable_layer_ids(session, layers, user),
    )


async def delete_map(
    session: AsyncSession,
    map_id: uuid.UUID,
) -> str:
    """Delete map by ID. CASCADE handles map_layers cleanup.

    Raises ValueError if not found. Returns map name for audit.
    Does NOT commit.
    """
    result = await session.execute(select(Map).where(Map.id == map_id))
    map_obj = result.scalar_one_or_none()
    if map_obj is None:
        raise ValueError(f"Map {map_id} not found")

    name = map_obj.name
    await session.delete(map_obj)
    await session.flush()
    return name


async def _generate_fork_name(
    session: AsyncSession, source_name: str, user_id: uuid.UUID
) -> str:
    """Generate a collision-safe fork name.

    Strips existing '(copy)' / '(copy N)' suffix to avoid chaining, then
    finds the next available numeric suffix scoped to the user's maps.
    """
    base = _COPY_SUFFIX_RE.sub("", source_name).rstrip()

    # Find existing copies owned by this user
    result = await session.execute(
        select(Map.name).where(
            Map.created_by == user_id,
            Map.name.like(f"{base} (copy%"),
        )
    )
    existing_names = {row[0] for row in result.all()}

    candidate = f"{base} (copy)"
    if candidate not in existing_names:
        return candidate

    n = 2
    while True:
        candidate = f"{base} (copy {n})"
        if candidate not in existing_names:
            return candidate
        n += 1


async def duplicate_map(
    session: AsyncSession,
    map_id: uuid.UUID,
    user: Identity,
) -> tuple[Map, list[LayerRow], str | None, str | None, int]:
    """Deep-copy a map with RBAC-filtered layers. Does NOT commit.

    Returns the 4-tuple shape from ``get_map_with_layers`` plus
    ``excluded_layer_count`` appended:
    ``(new_map, layer_rows, forked_from_name, owner_username,
       excluded_layer_count)``. Built from in-session ORM state so callers
    don't need a post-save re-fetch.
    """
    source = await get_map(session, map_id)
    if source is None:
        raise ValueError(f"Map {map_id} not found")

    user_roles = await check_map_access(session, source, user)

    fork_name = await _generate_fork_name(session, source.name, user.id)

    # Copy layers, filtering by RBAC
    layers_result = await session.execute(
        select(MapLayer)
        .where(MapLayer.map_id == map_id)
        .order_by(MapLayer.sort_order, MapLayer.id)  # Deterministic tie-break
    )
    layers = layers_result.scalars().all()

    # Bulk-fetch dataset visibility info to avoid N+1 queries
    layer_dataset_ids = list({layer.dataset_id for layer in layers})
    accessible_ids = await bulk_check_dataset_access(
        session, layer_dataset_ids, user, user_roles
    )

    copied_layers = {
        layer.id: uuid.uuid4() for layer in layers if layer.dataset_id in accessible_ids
    }
    new_map = Map(
        name=fork_name,
        description=source.description,
        # Notes are private to the source's owner, so only the owner's fork keeps them.
        notes=source.notes if source.created_by == user.id else None,
        center_lng=source.center_lng,
        center_lat=source.center_lat,
        zoom=source.zoom,
        bearing=source.bearing,
        pitch=source.pitch,
        basemap_style=source.basemap_style,
        show_basemap_labels=source.show_basemap_labels,
        basemap_config=source.basemap_config,
        # The fork's owner may not see the source's DEM, and every later read of
        # the fork would return the id stored here.
        terrain_config=project_terrain_config(
            source.terrain_config,
            await terrain_dataset_ids_visible_to(
                session, source.terrain_config, accessible_ids, user
            ),
        ),
        # Widgets follow their layers, so one on a layer the fork skips goes too.
        dashboard_config=fork_dashboard(source.dashboard_config, copied_layers),
        plugins=source.plugins,
        legend_title=source.legend_title,
        thumbnail_uri=None,
        visibility="private",
        forked_from=source.id,
        created_by=user.id,
    )
    session.add(new_map)
    await session.flush()

    excluded_count = 0
    for layer in layers:
        if layer.id not in copied_layers:
            excluded_count += 1
            continue
        new_layer = MapLayer(
            id=copied_layers[layer.id],
            map_id=new_map.id,
            dataset_id=layer.dataset_id,
            sort_order=layer.sort_order,
            visible=layer.visible,
            opacity=layer.opacity,
            paint=layer.paint,
            layout=layer.layout,
            layer_type=layer.layer_type,
            display_name=layer.display_name,
            filter=layer.filter,
            label_config=layer.label_config,
            popup_config=layer.popup_config,
            style_config=layer.style_config,
            show_in_legend=layer.show_in_legend,
        )
        session.add(new_layer)

    await session.flush()
    layer_rows = await _fetch_layer_rows_ordered(session, new_map.id)
    forked_name, owner_username, _ = await _resolve_save_response_metadata(
        session, new_map
    )
    return new_map, layer_rows, forked_name, owner_username, excluded_count
