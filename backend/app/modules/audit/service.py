import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, func, nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, joinedload

from app.platform.audit import (
    AuditEvent,
    audit_emit,
    extension_audit_sinks,
)  # re-exported for ergonomic single-import
from app.modules.audit.models import AuditLog
from app.core.text import escape_ilike

__all__ = [
    "AuditEvent",
    "audit_emit",
    "audit_emit_durable",
    "audit_emit_required",
    "extension_audit_sinks",
    "log_action",
    "prune_audit_logs",
    "recently_audited",
    "query_audit_logs",
    "query_column_ddl_history",
    "resolve_resource_names",
    "stream_audit_logs",
]


async def audit_emit_durable(event: AuditEvent) -> None:
    """Commit one audit event in a fresh, independently owned session.

    Streaming responses outlive their request handler, so this must not reuse
    the request-scoped session; a fresh one also avoids concurrent access
    while a response generator reads through its own cursor.
    """
    # Resolve lazily so tests/embedders that replace the application session
    # factory do not leave this streaming helper pinned to a stale engine.
    from app.core.db import async_session
    from app.modules.auth.models import User

    async with async_session() as session:
        try:
            durable_event = event
            if event.user_id is not None:
                # Resolve the actor under a key-share lock in the same
                # transaction as the insert. If deletion already won, emit an
                # anonymous historical event; if the actor still exists, the
                # lock holds a concurrent DELETE until the FK row is committed.
                actor_id = await session.scalar(
                    select(User.id)
                    .where(User.id == event.user_id)
                    .with_for_update(read=True, key_share=True)
                )
                if actor_id is None:
                    durable_event = replace(event, user_id=None)
            await audit_emit(session, durable_event)
            await session.commit()
        except BaseException:  # includes stream-task cancellation during shutdown
            await session.rollback()
            raise


# Nullable members of the audit sort allowlist. Postgres puts NULLs first on
# DESC, which would fill the top of a descending "IP address" or "User" view
# with the rows that have neither. Pinned last in both directions.
_NULLABLE_AUDIT_SORT_COLUMNS = frozenset({"ip_address", "username"})


def _audit_sort_columns(sort_user: Any) -> dict[str, Any]:
    """Map an allowlisted audit sort key to the expression that orders it.

    Inner half of a two-layer allowlist; the outer half is the AuditSortField
    Literal in schemas.py, which FastAPI enforces at the boundary. Resolution
    here is a dict lookup, so a caller-supplied string never reaches SQL.

    `resource_name` is deliberately absent (see AuditSortField): a header for
    it would sort the visible page only.
    """
    return {
        "created_at": AuditLog.created_at,
        "action": AuditLog.action,
        "resource_type": AuditLog.resource_type,
        "ip_address": AuditLog.ip_address,
        "username": sort_user.username,
    }


def _audit_ordering(sort: str, order: str, sort_user: Any) -> list[Any]:
    """Resolve a sort key/direction pair to ORDER BY clauses.

    Raises ValueError outside the allowlist rather than falling back to the
    default ordering, so a bad key fails loudly instead of silently serving a
    differently-ordered page.
    """
    column = _audit_sort_columns(sort_user).get(sort)
    if column is None:
        raise ValueError(f"Unsupported sort field: {sort!r}")
    if order not in ("asc", "desc"):
        raise ValueError(f"Unsupported sort order: {order!r}")

    clause = column.desc() if order == "desc" else column.asc()
    if sort in _NULLABLE_AUDIT_SORT_COLUMNS:
        clause = nulls_last(clause)

    # Every sortable audit column admits duplicates, created_at included: one
    # request can write several rows inside a single transaction. OFFSET paging
    # over a non-unique key lets Postgres hand back a row on two consecutive
    # pages; the id tiebreak makes the ordering total.
    return [clause, AuditLog.id]


def _apply_filters(
    query,
    *,
    user_id: uuid.UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    exclude_resource_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    snapshot_at: datetime | None = None,
    search: str | None = None,
):
    from app.modules.auth.models import User

    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
    if action is not None:
        query = query.where(AuditLog.action == action)
    if resource_type is not None:
        query = query.where(AuditLog.resource_type == resource_type)
    if resource_id is not None:
        query = query.where(AuditLog.resource_id == resource_id)
    if exclude_resource_id is not None:
        query = query.where(AuditLog.resource_id.is_distinct_from(exclude_resource_id))
    if date_from is not None:
        query = query.where(AuditLog.created_at >= date_from)
    if date_to is not None:
        query = query.where(AuditLog.created_at <= date_to)
    if snapshot_at is not None:
        query = query.where(AuditLog.created_at <= snapshot_at)
    if search is not None:
        # lower(catalog.immutable_unaccent(...)).like, not ILIKE, so the
        # planner uses ix_audit_logs_action_trgm / ix_users_username_trgm,
        # which are built on that exact schema-qualified expression. Bare
        # ILIKE, or func.unaccent() (resolves via search_path to
        # public.unaccent, STABLE not IMMUTABLE), misses the index and falls
        # back to a seq scan. Same shape as catalog.search.service_filters.
        unaccented_like = func.concat(
            "%", func.catalog.immutable_unaccent(search.lower()), "%"
        )
        action_match = func.lower(
            func.catalog.immutable_unaccent(AuditLog.action)
        ).like(unaccented_like)
        username_match = AuditLog.user_id.in_(
            select(User.id).where(
                func.lower(func.catalog.immutable_unaccent(User.username)).like(
                    unaccented_like
                )
            )
        )
        # resource_type stays ILIKE: a low-cardinality, enum-like column with
        # no trigram index. Escaping %, _ and \\ makes admin searches for
        # those characters literal rather than wildcards.
        search_filter = (
            action_match
            | AuditLog.resource_type.ilike(f"%{escape_ilike(search)}%", escape="\\")
            | username_match
        )
        query = query.where(search_filter)
    return query


async def recently_audited(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    action: str,
    resource_id: uuid.UUID,
    within: timedelta,
) -> bool:
    """Whether ``user_id`` already has an ``action`` row for the resource in the window.

    Reads ``audit_logs`` rather than a cache, so a cache flush can never cause a
    row to be skipped. Two concurrent callers can both see ``False``.
    """
    found = await session.scalar(
        select(AuditLog.id)
        .where(
            AuditLog.resource_id == resource_id,
            AuditLog.user_id == user_id,
            AuditLog.action == action,
            AuditLog.created_at > func.now() - within,
        )
        .limit(1)
    )
    return found is not None


async def audit_emit_required(session: AsyncSession, event: AuditEvent) -> None:
    """Write ``event``'s audit row in the caller's transaction, then the other sinks.

    Unlike :func:`audit_emit`, a failed insert raises, so the write it records
    rolls back with it instead of committing unrecorded.
    """
    await log_action(
        session,
        user_id=event.user_id,
        action=event.action,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        details=event.details,
        ip_address=event.ip_address,
    )
    await session.flush()
    await audit_emit(session, event, sinks=extension_audit_sinks())


async def prune_audit_logs(
    session: AsyncSession, *, cutoff: datetime, batch_size: int, retention_days: int
) -> int:
    """Delete every audit row created before ``cutoff``, committing per batch.

    Each batch commits together with an ``audit.prune`` row recording it, so
    no deletion is ever left without its record; a failed insert aborts the
    batch. Rows another transaction holds are skipped and picked up by a later
    run. Returns the number deleted.
    """
    deleted = 0
    while True:
        batch = (
            select(AuditLog.id)
            .where(AuditLog.created_at < cutoff)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(delete(AuditLog).where(AuditLog.id.in_(batch)))
        count = result.rowcount
        if count:
            event = AuditEvent(
                user_id=None,
                action="audit.prune",
                resource_type="audit_log",
                details={
                    "deleted": count,
                    "cutoff": cutoff.isoformat(),
                    "retention_days": retention_days,
                },
            )
            await audit_emit_required(session, event)
        await session.commit()
        deleted += count
        if count < batch_size:
            return deleted


async def log_action(
    session: AsyncSession,
    user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Create an audit log entry. Does NOT commit -- caller's transaction handles it.

    ``user_id=None`` is structurally accepted (nullable FK: ON DELETE SET
    NULL, SAML-JIT, anonymous downloads).

    ``details`` is normalized through ``jsonable_encoder`` first: the JSONB
    column has no ``json_serializer`` registered and stdlib ``json.dumps``
    cannot take a ``date``/``UUID``/``Decimal``, so normalizing here keeps the
    row from carrying that fault and ``audit_emit()``'s savepoint is a second
    line of defence. ``None`` stays SQL NULL; an absent payload and an empty
    one are different rows.
    """
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=jsonable_encoder(details) if details is not None else None,
        ip_address=ip_address,
    )
    session.add(entry)


async def query_audit_logs(
    session: AsyncSession,
    user_id: uuid.UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    snapshot_at: datetime | None = None,
    search: str | None = None,
    skip: int = 0,
    limit: int = 50,
    sort: str = "created_at",
    order: str = "desc",
) -> tuple[list[AuditLog], int]:
    """Query audit logs with optional filters and pagination.

    Returns (logs, total_count), ordered by created_at descending unless
    `sort`/`order` say otherwise (must be a key of _audit_sort_columns() /
    one of asc/desc; anything else raises ValueError).

    The CSV/JSON export doesn't sort: it runs through stream_audit_logs, a
    cursor-based generator with its own created_at DESC ordering (see
    export_audit_logs in router.py).

    Uses ``COUNT(*) OVER ()`` so the total rides along with the filtered
    slice in one round trip instead of a sibling count query.
    """
    # Keyword args rather than a **dict unpack, so mypy keeps each
    # parameter's type.
    total_col = func.count().over().label("total_count")
    query = select(AuditLog, total_col).options(joinedload(AuditLog.user))
    query = _apply_filters(
        query,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_at=snapshot_at,
        search=search,
    )
    # A dedicated alias, not the bare User entity, so this ORDER BY join can
    # never interact with the `users` reference in _apply_filters' username
    # search. The bare entity compiles to the same SQL today (SQLAlchemy only
    # auto-correlates when another FROM remains); the alias keeps ordering
    # independent of how the filter is written.
    from app.modules.auth.models import User

    sort_user = aliased(User, name="audit_sort_user")
    if sort == "username":
        query = query.outerjoin(sort_user, AuditLog.user_id == sort_user.id)
    query = (
        query.order_by(*_audit_ordering(sort, order, sort_user))
        .offset(skip)
        .limit(limit)
    )

    result = await session.execute(query)
    rows = result.unique().all()
    if not rows:
        # Empty slice: fall back to a count-only query so callers still see
        # the correct total for "no results on this page" pagination.
        count_query = select(func.count()).select_from(AuditLog)
        count_query = _apply_filters(
            count_query,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            date_from=date_from,
            date_to=date_to,
            snapshot_at=snapshot_at,
            search=search,
        )
        count_result = await session.execute(count_query)
        return [], int(count_result.scalar_one())

    logs = [row[0] for row in rows]
    total = int(rows[0][1])
    return logs, total


async def resolve_resource_names(
    session: AsyncSession, logs: list[AuditLog]
) -> dict[tuple[str, uuid.UUID], str]:
    """Batch-resolve display names for one page of audit rows.

    Returns ``{(resource_type, resource_id): name}`` for the resource types
    with a canonical display name (dataset, map, collection, user, group). Deleted
    resources and other types are absent; callers fall back to None.

    Cross-module imports are function-scoped (test_layering allowlist: SQL
    InstrumentedAttribute use only).
    """
    from app.modules.auth.models import Group, User
    from app.modules.catalog.collections.models import Collection
    from app.modules.catalog.datasets.domain.models import Dataset, Record
    from app.modules.catalog.maps.sharing import get_map_names

    ids_by_type: dict[str, set[uuid.UUID]] = {}
    for log in logs:
        if log.resource_id is not None:
            ids_by_type.setdefault(log.resource_type, set()).add(log.resource_id)

    lookups = {
        "dataset": select(Dataset.id, Record.title).join(
            Record, Dataset.record_id == Record.id
        ),
        "collection": select(Collection.id, Collection.name),
        "user": select(User.id, User.username),
        "group": select(Group.id, Group.name),
    }
    names: dict[tuple[str, uuid.UUID], str] = {}
    for resource_type, query in lookups.items():
        type_ids = ids_by_type.get(resource_type)
        if not type_ids:
            continue
        id_col = query.selected_columns[0]
        rows = await session.execute(query.where(id_col.in_(type_ids)))
        names.update({(resource_type, rid): name for rid, name in rows})

    map_ids = ids_by_type.get("map")
    if map_ids:
        # The stable sharing API, not catalog map ORM internals
        # (test_layering.py::test_open_core_decomposition_boundaries_stay_clean).
        map_names = await get_map_names(session, map_ids)
        names.update({("map", mid): name for mid, name in map_names.items()})
    return names


# The action strings the column-DDL endpoints emit
# (backend/app/modules/catalog/layers/router.py).
_COLUMN_DDL_ACTIONS = (
    "layer.add_column",
    "layer.rename_column",
    "layer.alter_column_type",
    "layer.drop_column",
)


async def query_column_ddl_history(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AuditLog], int]:
    """Return column-DDL audit history for a single dataset.

    Filters to the column-DDL actions, ordered by created_at DESC. Returns
    (rows, total_count), matching query_audit_logs's shape for consistent
    pagination at the router layer. Eager-loads AuditLog.user so the actor
    username needs no N+1.
    """
    where_clauses = [
        AuditLog.resource_type == "dataset",
        AuditLog.resource_id == dataset_id,
        AuditLog.action.in_(_COLUMN_DDL_ACTIONS),
    ]

    total_col = func.count().over().label("total_count")
    query = (
        select(AuditLog, total_col)
        .options(joinedload(AuditLog.user))
        .where(*where_clauses)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await session.execute(query)
    rows = result.unique().all()

    if not rows:
        # Empty slice: fall back to a count-only query for the total.
        count_query = select(func.count()).select_from(AuditLog).where(*where_clauses)
        count_result = await session.execute(count_query)
        return [], int(count_result.scalar_one())

    logs = [row[0] for row in rows]
    total = int(rows[0][1])
    return logs, total


async def stream_audit_logs(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    exclude_resource_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    snapshot_at: datetime | None = None,
    search: str | None = None,
) -> AsyncIterator[AuditLog]:
    """Stream audit logs with filters, no pagination.

    Yields AuditLog rows one at a time from a server-side cursor
    for memory-efficient export of large result sets.
    """
    query = select(AuditLog).options(joinedload(AuditLog.user))
    query = _apply_filters(
        query,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        exclude_resource_id=exclude_resource_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_at=snapshot_at,
        search=search,
    )
    query = query.order_by(AuditLog.created_at.desc())

    result = await session.stream(query)
    async for row in result.scalars():
        yield row
