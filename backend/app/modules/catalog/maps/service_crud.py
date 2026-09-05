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

    fix(#1778 round 3): the keys used to be ``{prefix}/{map_id}.{ext}``, one of
    two names per map, chosen by the payload's encoding. Reusing them left a
    window the row lock cannot close, because the lock is released by the commit
    that records the URI and the cleanup runs after that: request A re-reads the
    committed row, decides its old key is dead, and is then descheduled;
    request B takes the lock, writes that same name again and commits the row
    back onto it; A's delete lands on the object B just published. The row then
    names a key with nothing behind it and the image endpoint answers 404.

    A fresh random component per write removes it by construction rather than by
    timing. A key is written once and named by the row once, so once the row
    moves off a key nothing can move it back, and a delete decided against a
    stale read can only ever remove an object nothing points at.

    The extension stays last: ``get_thumbnail`` and ``get_og_image`` pick the
    response media type with ``endswith(".jpg")``. Keys already stored in the
    unversioned shape keep working, since the row holds the key verbatim and the
    first replacement deletes the old one, so nothing has to be migrated.
    """
    return f"{prefix}/{map_id}-{uuid.uuid4().hex}.{ext}"


def _is_lock_timeout_error(exc: BaseException) -> bool:
    """True when another transaction holds the map row this write needs.

    fix(#1778 round 8): asyncpg raises ``LockNotAvailableError`` directly;
    ``AsyncSession.execute`` wraps it in SQLAlchemy's ``DBAPIError`` with
    ``.orig`` pointing at that same exception. Both shapes have to be checked.

    fix(#1847): the check moved to ``app.core.db.sqlstate``, and widened with
    it to match 40P01 too, so a deadlock victim answers 409 rather than 500.
    """
    return is_lock_conflict(exc)


async def lock_map_for_asset_write(session: AsyncSession, map_id: uuid.UUID) -> Row:
    """Take the row lock that serializes one map's asset replacements.

    fix(#1778 round 2): the thumbnail and OG-image keys end in ``.jpg`` or
    ``.png`` after the payload's encoding, so two overlapping uploads of one map
    write two different objects and then race each other's cleanup. The losing
    interleave: A puts ``.jpg``; B reads ``.jpg`` as the previous key, commits
    its URI at ``.png`` and deletes ``.jpg``; A then commits its URI at ``.jpg``,
    pointing the row at the object B just deleted. Both requests answer 204 and
    the thumbnail endpoint answers 404 from then on.

    Held from here to the caller's commit, which is where PostgreSQL releases a
    row lock, so the read of the previous key, the object write and the URI
    update are one serialized unit per map. Callers take it AFTER validating the
    payload, so no decode or image verification happens under the lock.

    This is one half of the fix. A row lock cannot outlive the commit that
    releases it, so the cleanup that follows the commit is guarded separately,
    by ``discard_map_asset_objects`` re-reading the committed row. Both halves
    are needed: the lock stops the bad interleave from being produced, the
    re-read stops a cleanup that was queued before it from acting on it.

    Raises 404 when the map is gone, because a concurrent delete may have
    committed while this request waited here. The raise lives in this helper
    rather than at each of the three call sites so the three cannot drift, the
    way ``check_map_ownership`` above owns the 403 for the same reason.

    Selects the two columns rather than the ``Map`` entity, and that is
    load-bearing rather than a matter of taste. Every caller has already loaded
    the map through ``get_map`` for its 404 and ownership check, so the entity
    is in the session's identity map; a ``select(Map)`` returns that same
    instance with the attributes it was loaded with, and the keys read back
    would be the ones from BEFORE the wait on the lock. Whatever the other
    request committed while this one waited is exactly what this read exists to
    see. A column select never consults the identity map, so it cannot go stale.

    fix(#1778 round 8): a ``SET LOCAL lock_timeout`` bounds the wait.
    The lock used to be held from here through the caller's commit with no
    engine-side timeout, which is fine for the lock's own purpose (serializing
    replacements) but not for what got layered on top later: the write this
    lock guards awaits ``storage.put`` before the commit, and the S3 provider's
    connect/read timeouts plus its adaptive retries can take on the order of a
    minute (``app/platform/storage/s3.py``). A degraded backend held every
    other writer to the same map (the other image upload, a rename, a delete)
    queued behind it with no bound, instead of failing fast. ``'2s'`` matches
    the budget ``lock_map_for_asset_write``'s callers can already spend before
    they answer (a row lock that is still contended after two seconds is
    contended by another live request, not by network latency inside this one),
    and matches the timeout the same pattern already uses in
    ``app.platform.jobs.router`` (``SET LOCAL lock_timeout = '2s'`` there too).
    A losing wait raises 55P03, mapped below to 409 rather than 500: nothing
    was written, and the client's retry is the correct next action.
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

    fix(#1778): nothing in the backend ever called ``storage.delete`` for a
    ``maps/`` key. Deleting a map dropped the row and left both images behind,
    and because no code enumerates that prefix the orphan was undiscoverable
    rather than merely unreclaimed. The builder captures a thumbnail and an OG
    image on first open of every map, so essentially every map that has been
    opened owns two objects.

    Three callers share this, and all three hold
    ``lock_map_for_asset_write`` from before their write until their commit:
    ``delete_map_endpoint``, ``upload_thumbnail`` and ``upload_og_image``. The
    two upload handlers reach it because a re-upload in the other encoding
    writes ``.png`` beside the stored ``.jpg``, repoints the column, and strands
    the old key in place.

    fix(#1778 round 2): a key still named by the committed row is never
    deleted. The lock is released by the commit that precedes this call, so a
    request that read its previous key before another request committed can
    arrive here holding a key that is live again. Re-reading the row is what
    makes the outcome consistent with whatever committed last, rather than with
    what this request saw on the way in.

    fix(#1778 round 3): that re-read is not atomic with the delete below, and
    making it atomic would mean holding a second row lock across a storage call.
    ``new_map_asset_key`` closes the window at the other end instead: keys are
    never reused, so a candidate here can never become live again between the
    re-read and the delete. The re-read stays as the cheap invariant that says
    what this function will not do, and it is what makes a key still named by an
    older row shape safe during the changeover.

    Always best effort. The object is a cached picture; a storage backend that
    is refusing calls must not be able to stop an owner deleting their map, and
    a delete that already committed cannot be undone by raising here. Failures
    are logged with the key, which is derived from the map id and carries
    nothing secret.

    The provider import stays function-local, matching ``_reap_managed_storage``
    in the dataset lifecycle, so tests keep patching the provider attribute.
    """
    from app.platform.storage.provider import get_storage
    from app.platform.storage.titiler_url import resolve_current_storage_key

    candidates = {key for key in storage_keys if key}
    if not candidates:
        return
    try:
        live = await _live_map_asset_keys(session, map_id)
    except Exception:  # broad: any failure of the post-commit read
        # fix(#1778 round 4): the liveness read is a database call made after the
        # caller has already committed, so a transient failure here used to
        # escape as a 500 for a delete or an upload that had durably succeeded,
        # and the client would retry a thing that already happened. It is part
        # of the best-effort cleanup, not part of the request's outcome. Without
        # the read there is no way to tell a dead key from a live one, so the
        # deletes are skipped: an object nothing points at costs storage, while
        # deleting one the row still names costs the image.
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

    fix(#1778 round 5): the rollback used to be keyed on "did the block raise",
    which is not the same question as "did the row commit". Anything after a
    successful commit but still inside the scope, such as the icon route's
    ``session.refresh``, would fail and take an object the committed row
    references. Settling is what ends the tracking, so the boundary is the
    commit itself rather than the last statement someone happened to leave in
    the block.
    """

    def __init__(self) -> None:
        self._pending: list[str] = []
        self._outcome_known = True

    def record(self, physical_key: str) -> None:
        """Note an object that exists but is not named by a committed row yet.

        PHYSICAL, not logical: the writers resolve their keys differently (map
        images cross ``resolve_current_storage_key`` into the tenant prefix,
        sprite icons are deliberately global), and the rollback deletes what it
        is given rather than resolving anything itself.

        fix(#1778 round 7): call this BEFORE awaiting the write, not after.
        Object storage can durably accept a PUT and still fail the client with a
        timeout or a dropped connection, so a raise from the write says nothing
        about whether the bytes landed; recording afterwards left the ledger
        empty and the object unreferenced and unreclaimed, one more per retry.
        Recording first costs nothing, because the key is freshly generated and
        never reused: the rollback either deletes an object this request wrote,
        or no-ops on a key nothing ever wrote, which every provider treats as
        success (local "no error if missing", S3 silently ignores, Azure catches
        ResourceNotFoundError).
        ``test_every_object_write_records_before_putting_1778`` fails the build
        if a writer puts before it records.
        """
        self._pending.append(physical_key)

    def committing(self) -> None:
        """A commit is about to be awaited, so its outcome stops being knowable.

        fix(#1778 round 6): a lost connection between PostgreSQL making the
        commit durable and the acknowledgement arriving raises out of the await
        for a transaction that DID commit. Settling never runs, the exception
        path treats the write as unpublished, and the object a committed row now
        references is deleted. From this mark until ``settled``, an exception
        says nothing about whether the row landed, so nothing is deleted.

        The cost of that is one object left behind when the commit genuinely
        failed, on a path that is already rare. The alternative, verifying from
        an independent session before deleting, buys back that object at the
        price of a database call on an error path, on a connection that has just
        proven unreliable, to decide a deletion. This module already answers
        that trade the same way twice (the liveness read in
        ``discard_map_asset_objects``, and skipping rather than guessing): an
        orphan costs storage, a wrongly deleted object costs the image.

        Call it as the statement immediately before the commit:
        ``test_every_publication_marks_before_committing_1778`` fails the build
        otherwise.
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

    fix(#1778 round 4): the upload handlers write the image and then record its
    key on the map row. A failure between those two, in the update or in the
    commit, left the object behind with nothing pointing at it, and since keys
    stopped being reused every retry added another. Nothing in the backend
    enumerates the ``maps/`` prefix, so those are not merely unreclaimed, they
    are undiscoverable.

    Cleanup runs on any exception, including an HTTPException the handler raises
    itself, and never replaces it: a failure to tidy up is logged and dropped so
    the caller still sees what actually went wrong. It runs only on what is
    still pending, so a settled publication rolls nothing back, and it does not
    run at all while a commit's outcome is indeterminate (see ``committing``).
    """
    from app.platform.storage.provider import get_storage

    publication = MapAssetPublication()
    try:
        yield publication
    except BaseException:
        if publication.outcome_unknown:
            # fix(#1778 round 6): the exception arrived while a commit was in
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

    Returns (map, [(layer, dataset_name, geometry_type, table_name, extent, column_info, feature_count, sample_values, record_type, is_3d), ...], forked_from_name, owner_username)
    or (None, [], None, None).

    Read path uses a single combined Map+ForkedMap+User LEFT JOIN to keep
    the public GET /maps/{id} hot path at 2 queries total (matches
    pre-PERF-6 behavior; the helper-based pattern is reserved for the
    save path where map_obj is already in-session).
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

    fix(#1778): the listing used to read its counts from an uncorrelated
    ``GROUP BY map_id`` subquery LEFT JOINed onto the page. PostgreSQL has no
    limit-pushdown through a left join, so every gallery request aggregated
    every row of ``catalog.map_layers`` to produce at most ``limit`` numbers,
    and the cost grew with the total layer count rather than with the page.

    A correlated scalar subquery fixes the common case but not the general one:
    measured on 5000 maps x 8 layers, the subplan ran 50 times at OFFSET 0
    (2.5 ms against 12.3 ms for the join) but 4050 times at OFFSET 4000, where
    it lost to the thing it replaced. OFFSET discards rows above the
    projection, so the only form that is bounded by the page at every offset is
    a second query keyed on the ids the page actually returned. That one plans
    as a bitmap index scan on ``map_layers.map_id`` and measured 0.5-1.0 ms at
    both offsets.
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
            # SEC-FU-07 (sec-audit-20260519.md + WR-01): escape \, %, and _ before
            # composing the ILIKE pattern. Backslash must be escaped FIRST so later
            # replacements do not double-escape already-escaped sequences.
            # escape_ilike() centralises the logic; escape="\\" makes the ESCAPE
            # character explicit in the emitted SQL.
            # T-2: lower() BOTH column and pattern so the predicate matches the
            # functional trigram indexes (ix_maps_name_trgm on lower(name);
            # ix_maps_description_trgm on lower(coalesce(description,''))). A bare
            # ILIKE on the raw column emits `name ~~* pattern`, which the planner
            # cannot match to lower(name) and falls back to a Seq Scan. Lowering
            # the pattern is safe: escape_ilike()'s backslash/%/_ escapes are
            # unaffected by .lower(). escape="\\" keeps the ESCAPE clause explicit.
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
        # fix(#430 BA-19): batch-seeded rows share a server-default timestamp; add a
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
        )  # fix(#430 BA-21): deterministic tie-break
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
