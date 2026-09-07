"""Map CRUD, listing, update, delete, and duplicate helpers."""

import re
import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
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
from app.modules.catalog.authorization import get_user_roles
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.catalog.maps.service_diff import _replace_layers
from app.modules.catalog.maps.service_layers import bulk_check_dataset_access
from app.core.text import escape_ilike
from app.modules.catalog.maps.service_shared import (
    LayerRow,
    _apply_map_visibility_filter,
    _fetch_layer_rows_ordered,
    _resolve_save_response_metadata,
)

logger = structlog.stdlib.get_logger(__name__)

_COPY_SUFFIX_RE = re.compile(r"\s*\(copy(?:\s+(\d+))?\)\s*$")
_UNSET = object()


def new_map_asset_key(prefix: str, map_id: uuid.UUID, ext: str) -> str:
    """A storage key for one map image that no later upload can reuse.

    fix(#1778): reused keys (``{prefix}/{map_id}.{ext}``) let a
    race outlive the row lock — request A re-reads a committed key as
    dead, request B writes and commits that same name, then A's delete
    lands on the object B just published (404). A fresh random component
    per write closes this by construction: once the row moves off a key,
    nothing can move it back.

    The extension stays last: ``get_thumbnail``/``get_og_image`` pick the
    media type with ``endswith(".jpg")``. Pre-existing unversioned keys
    keep working since the row holds the key verbatim.
    """
    return f"{prefix}/{map_id}-{uuid.uuid4().hex}.{ext}"


def _is_lock_timeout_error(exc: BaseException) -> bool:
    """True for the shared lock-conflict states (55P03, 40P01), in either shape."""
    return is_lock_conflict(exc)


async def lock_map_for_asset_write(session: AsyncSession, map_id: uuid.UUID) -> Row:
    """Take the row lock that serializes one map's asset replacements.

    fix(#1778): overlapping uploads can race their cleanup and
    strand the row on an object the other just deleted (404 on read).
    Held through the caller's commit; ``discard_map_asset_objects``
    re-reads the committed row as the other half, since a lock can't
    outlive the commit that releases it. Raises 404 centrally so all
    three callers agree, and selects columns (not ``Map``) so a stale
    identity-mapped instance can't shadow a fresh commit.

    fix(#1778): ``SET LOCAL lock_timeout = '2s'`` bounds the
    wait, since a degraded storage backend could otherwise queue every
    writer behind this lock (a losing wait, 55P03, maps to 409).
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
    """Best-effort removal of a map's stored thumbnail / OG-image objects.

    fix(#1778): nothing ever called ``storage.delete`` for a ``maps/``
    key, so deleted/re-uploaded images were orphaned undiscoverably.
    Shared by delete/upload handlers, all holding
    ``lock_map_for_asset_write`` from write to commit.

    fix(#1778): re-reads the row rather than trusting the
    caller's previous-key read (consistent with whatever committed
    last), and relies on ``new_map_asset_key`` never reusing keys since
    the re-read isn't atomic with the delete below.

    Always best effort — a refusing backend must not block a delete,
    and an already-committed delete can't be undone by raising. Import
    stays function-local, matching ``_reap_managed_storage``.
    """
    from app.platform.storage.provider import get_storage
    from app.platform.storage.titiler_url import resolve_current_storage_key

    candidates = {key for key in storage_keys if key}
    if not candidates:
        return
    try:
        live = await _live_map_asset_keys(session, map_id)
    except Exception:  # broad: any failure of the post-commit read
        # fix(#1778): the liveness read runs after commit, so a
        # transient failure here shouldn't 500 an already-succeeded
        # request — skip the deletes; an orphan costs less than a live delete.
        logger.warning(
            "map_asset_liveness_read_failed", map_id=str(map_id), exc_info=True
        )
        return

    for key in sorted(candidates - live):
        try:
            await get_storage().delete(resolve_current_storage_key(key))
        except Exception:  # broad: storage backends raise varied SDK/I/O errors
            logger.warning(
                "map_asset_object_delete_failed", storage_key=key, exc_info=True
            )
    for key in sorted(candidates & live):
        logger.info("map_asset_object_delete_skipped_still_referenced", storage_key=key)


class MapAssetPublication:
    """The objects written for a row that has not committed yet.

    fix(#1778): the rollback used to be keyed on "did the block
    raise", not "did the row commit" — anything after a successful commit
    but still in scope (e.g. the icon route's ``session.refresh``) could
    fail and delete an object the committed row references. Settling ends
    the tracking, so the boundary is the commit itself, not the last
    statement left in the block.
    """

    def __init__(self) -> None:
        self._pending: list[str] = []
        self._outcome_known = True

    def record(self, physical_key: str) -> None:
        """Note an object that exists but is not named by a committed row yet.

        PHYSICAL, not logical: writers resolve keys differently (tenant
        prefix vs deliberately-global sprite icons), and rollback deletes
        what it's given rather than resolving anything.

        fix(#1778): call BEFORE awaiting the write — a PUT can
        land and still fail the client, so recording after left orphaned
        objects per retry. Recording first is free: rollback either
        deletes what this request wrote or no-ops on an unwritten key.
        ``test_every_object_write_records_before_putting_1778`` enforces this.
        """
        self._pending.append(physical_key)

    def committing(self) -> None:
        """A commit is about to be awaited, so its outcome stops being knowable.

        fix(#1778): a lost connection between Postgres committing
        and the ack arriving raises out of the await for a transaction
        that DID commit — from this mark until ``settled``, an exception
        says nothing about whether the row landed, so nothing is deleted.

        Costs one object left behind on the rare true-failure case; the
        alternative (verifying from an independent session, on a
        connection that just proved unreliable) costs more. Same trade as
        the liveness read in ``discard_map_asset_objects``.

        Call immediately before the commit:
        ``test_every_publication_marks_before_committing_1778`` enforces this.
        """
        self._outcome_known = False

    def settled(self) -> None:
        """The row naming every recorded object is committed. Stop tracking.

        Call this as the next statement after the commit, and as the last
        statement of the block: ``test_every_publication_settles_at_the_commit``
        fails the build otherwise.
        """
        self._pending.clear()
        self._outcome_known = True

    @property
    def pending(self) -> tuple[str, ...]:
        return tuple(self._pending)

    @property
    def outcome_unknown(self) -> bool:
        """True between ``committing`` and ``settled``: nothing may be deleted."""
        return not self._outcome_known


@asynccontextmanager
async def map_asset_publication() -> AsyncIterator[MapAssetPublication]:
    """Undo object writes when the row that would name them never commits.

    fix(#1778): the upload handlers write the image, then record
    its key on the map row. A failure between those two left the object
    behind with nothing pointing at it, and since keys are never reused,
    every retry added another — undiscoverable, since nothing enumerates
    the ``maps/`` prefix.

    Cleanup runs on any exception (including one the handler raises
    itself) and never replaces it — a tidy-up failure is logged and
    dropped so the caller still sees the real error. Runs only on what's
    still pending (a settled publication rolls nothing back), and not at
    all while a commit's outcome is indeterminate (see ``committing``).
    """
    from app.platform.storage.provider import get_storage

    publication = MapAssetPublication()
    try:
        yield publication
    except BaseException:
        if publication.outcome_unknown:
            # fix(#1778): the exception arrived while a commit was in
            # flight, so it does not say whether the row landed. Deleting here
            # is the one irreversible option available.
            logger.warning(
                "map_asset_publication_rollback_skipped_indeterminate_commit",
                storage_keys=list(publication.pending),
            )
            raise
        for physical_key in publication.pending:
            try:
                await get_storage().delete(physical_key)
            except Exception:  # broad: storage backends raise varied errors
                logger.warning(
                    "map_asset_publication_rollback_failed",
                    storage_key=physical_key,
                    exc_info=True,
                )
        raise


async def check_map_ownership(map_obj: Map, user: Identity, db: AsyncSession) -> None:
    """Verify user owns the map or is admin. Raises 403 if neither."""
    if map_obj.created_by == user.id:
        return
    user_roles = await get_user_roles(db, user)
    if "admin" in user_roles:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized to modify this map",
    )


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
    (None, [], None, None) if not found. Uses a single combined
    Map+ForkedMap+User LEFT JOIN to keep GET /maps/{id} at 2 queries total
    (the helper-based pattern is for the save path, where map_obj is
    already in-session).
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


async def _layer_counts_for_maps(
    session: AsyncSession, map_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Layer counts for exactly the maps on one page of the gallery listing.

    fix(#1778): the listing used to read counts from an uncorrelated
    ``GROUP BY map_id`` subquery LEFT JOINed onto the page — Postgres has no
    limit-pushdown through a left join, so every request aggregated all of
    ``catalog.map_layers``, cost growing with total layer count, not page size.

    A correlated scalar subquery fixes the common case but not the general
    one: measured on 5000 maps x 8 layers, the subplan ran 50 times at
    OFFSET 0 (2.5ms vs 12.3ms for the join) but 4050 times at OFFSET 4000,
    losing to what it replaced. The only form bounded by the page at every
    offset is a second query keyed on the ids the page returned — a bitmap
    index scan on ``map_layers.map_id``, measured 0.5-1.0ms at both offsets.
    """
    if not map_ids:
        return {}
    result = await session.execute(
        select(MapLayer.map_id, func.count(MapLayer.id))
        .where(MapLayer.map_id.in_(map_ids))
        .group_by(MapLayer.map_id)
    )
    return {map_id: count for map_id, count in result.all()}


async def list_maps(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 20,
    user_id: uuid.UUID | None = None,
    user_roles: set[str] | None = None,
    search: str | None = None,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
    visibility: str | None = None,
) -> tuple[list[dict], int]:
    """List maps with layer counts, filtered by visibility rules.

    - Admins see ALL maps (no filter).
    - Authenticated non-admin users see: their own private maps + all internal + all public.
    - If user_roles is omitted, treats user as non-admin (still sees own + internal + public).
    - search: ILIKE filter on name and description.
    - sort_by: name, created_at, updated_at (default). Unknown values fall back to updated_at.
    - sort_dir: asc or desc.
    - visibility: additional filter on Map.visibility (additive on top of RBAC).

    Returns (list of dicts with map fields + layer_count + created_by_username, total).
    """
    if user_roles is None:
        user_roles = set()

    is_admin = "admin" in user_roles

    def _apply_vis_filter(stmt: Select) -> Select:
        return _apply_map_visibility_filter(stmt, user_id, is_admin)

    # Build search/visibility filters (applied to both count and data queries)
    def _apply_extra_filters(stmt: Select) -> Select:
        if search:
            # SEC-FU-07 (sec-audit-20260519.md + WR-01): escape \, %, _ via
            # escape_ilike() before composing the pattern (backslash
            # escaped FIRST or later replacements double-escape).
            # T-2: lower() both column and pattern to match the functional
            # trigram indexes (ix_maps_name_trgm, ix_maps_description_trgm)
            # — a bare ILIKE on the raw column falls back to a Seq Scan.
            pattern = f"%{escape_ilike(search)}%".lower()
            stmt = stmt.where(
                or_(
                    func.lower(Map.name).like(pattern, escape="\\"),
                    func.lower(func.coalesce(Map.description, "")).like(
                        pattern, escape="\\"
                    ),
                )
            )
        if visibility:
            stmt = stmt.where(Map.visibility == visibility)
        return stmt

    # Resolve sort column
    sort_column_map = {
        "name": Map.name,
        "created_at": Map.created_at,
        "updated_at": Map.updated_at,
    }
    col = sort_column_map.get(sort_by, Map.updated_at)
    order_clause = col.asc() if sort_dir == "asc" else col.desc()

    # Total count (with RBAC + search/visibility filters)
    count_base = select(func.count()).select_from(Map)
    count_base = _apply_vis_filter(count_base)
    count_base = _apply_extra_filters(count_base)
    total_result = await session.execute(count_base)
    total = total_result.scalar_one()

    # Paginated maps with author username. The layer counts are fetched
    # separately, scoped to this page — see _layer_counts_for_maps.
    stmt = (
        select(
            Map,
            User.username.label("created_by_username"),
        )
        .outerjoin(User, Map.created_by == User.id)
        # fix(#430): batch-seeded rows share a server-default timestamp; add a
        # unique tiebreaker so pagination is stable.
        .order_by(order_clause, Map.id)
        .offset(skip)
        .limit(limit)
    )
    stmt = _apply_vis_filter(stmt)
    stmt = _apply_extra_filters(stmt)

    result = await session.execute(stmt)
    rows = result.all()
    layer_counts = await _layer_counts_for_maps(session, [row[0].id for row in rows])

    maps = []
    for row in rows:
        map_obj = row[0]
        maps.append(
            {
                "id": map_obj.id,
                "name": map_obj.name,
                "description": map_obj.description,
                "visibility": map_obj.visibility,
                "thumbnail_url": f"/maps/{map_obj.id}/thumbnail/"
                if map_obj.thumbnail_uri
                else None,
                "thumbnail_updated_at": map_obj.thumbnail_updated_at,
                "layer_count": layer_counts.get(map_obj.id, 0),
                "created_by_username": row[1],
                "created_at": map_obj.created_at,
                "updated_at": map_obj.updated_at,
            }
        )

    return maps, total


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
    visibility: str | None = None,
    plugins: list[str] | None | object = _UNSET,
    legend_title: str | None | object = _UNSET,
    layers: list[dict] | None = None,
) -> tuple[Map, list[LayerRow], str | None, str | None]:
    """Update map fields. If 'layers' key present, replace all layers.

    Raises ValueError if not found. Flushes but does NOT commit --
    callers must own the commit lifecycle.

    Returns the same 4-tuple shape as ``get_map_with_layers``:
    ``(Map, layer_rows, forked_from_name, owner_username)``. Built from
    in-session ORM state so callers don't need a post-save re-fetch.
    """
    result = await session.execute(select(Map).where(Map.id == map_id))
    map_obj = result.scalar_one_or_none()
    if map_obj is None:
        raise ValueError(f"Map {map_id} not found")

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
    if terrain_config is not _UNSET:
        map_obj.terrain_config = cast(dict | None, terrain_config)
    if plugins is not _UNSET:
        map_obj.plugins = cast(list[str] | None, plugins)
    if legend_title is not _UNSET:
        # Treat empty/whitespace-only titles as "no custom title" so the
        # legend falls back to the default heading on the read path.
        title = cast(str | None, legend_title)
        map_obj.legend_title = title.strip() if title and title.strip() else None

    # Replace layers if provided
    if layers is not None:
        await _replace_layers(session, map_id, layers)

    await session.flush()
    # Combined LEFT JOIN reads forked_name + owner_username + DB-side
    # updated_at in one round-trip — eliminates the explicit
    # ``session.refresh(map_obj)`` previously needed for ``updated_at``.
    layer_rows = await _fetch_layer_rows_ordered(session, map_obj.id)
    forked_name, owner_username, db_updated_at = await _resolve_save_response_metadata(
        session, map_obj
    )
    if db_updated_at is not None:
        map_obj.updated_at = db_updated_at
    return map_obj, layer_rows, forked_name, owner_username


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

    user_roles = await get_user_roles(session, user)
    is_admin = "admin" in user_roles
    if not (
        source.visibility == "public"
        or source.visibility == "internal"
        or source.created_by == user.id
        or is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    fork_name = await _generate_fork_name(session, source.name, user.id)

    # Create new map - always private, no thumbnail, track lineage
    new_map = Map(
        name=fork_name,
        description=source.description,
        notes=source.notes,
        center_lng=source.center_lng,
        center_lat=source.center_lat,
        zoom=source.zoom,
        bearing=source.bearing,
        pitch=source.pitch,
        basemap_style=source.basemap_style,
        show_basemap_labels=source.show_basemap_labels,
        basemap_config=source.basemap_config,
        terrain_config=source.terrain_config,
        plugins=source.plugins,
        legend_title=source.legend_title,
        thumbnail_uri=None,
        visibility="private",
        forked_from=source.id,
        created_by=user.id,
    )
    session.add(new_map)
    await session.flush()

    # Copy layers, filtering by RBAC
    layers_result = await session.execute(
        select(MapLayer)
        .where(MapLayer.map_id == map_id)
        .order_by(
            MapLayer.sort_order, MapLayer.id
        )  # fix(#430): deterministic tie-break
    )
    layers = layers_result.scalars().all()

    # Bulk-fetch dataset visibility info to avoid N+1 queries
    layer_dataset_ids = list({layer.dataset_id for layer in layers})
    accessible_ids = await bulk_check_dataset_access(
        session, layer_dataset_ids, user, user_roles
    )

    excluded_count = 0
    for layer in layers:
        if layer.dataset_id not in accessible_ids:
            excluded_count += 1
            continue
        new_layer = MapLayer(
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
