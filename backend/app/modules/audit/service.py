import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.platform.audit import (
    AuditEvent,
    audit_emit,
)  # re-exported for ergonomic single-import
from app.modules.audit.models import AuditLog
from app.core.text import escape_ilike

__all__ = [
    "AuditEvent",
    "audit_emit",
    "audit_emit_durable",
    "log_action",
    "query_audit_logs",
    "query_column_ddl_history",
    "stream_audit_logs",
]


async def audit_emit_durable(event: AuditEvent) -> None:
    """Commit one audit event in a fresh, independently owned session.

    Streaming responses outlive their request handler and must not reuse the
    request-scoped ``AsyncSession`` for completion/failure bookkeeping. Keeping
    this helper session-owned also prevents concurrent access when a response
    generator is reading through its own cursor.
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
    """Apply common audit log filters to a query."""
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
        # ADMIN-02 (Phase 279 / M-02; fixed in T-1): rewrite ILIKE to
        # lower(catalog.immutable_unaccent(...)).like so the planner picks the
        # ix_audit_logs_action_trgm and ix_users_username_trgm functional GIN
        # indexes from migration 0001_baseline. Those indexes are built on
        # lower(catalog.immutable_unaccent(...)) (IMMUTABLE). The query expression
        # MUST use that exact schema-qualified function: bare ILIKE, OR a plain
        # func.unaccent() (which renders unqualified and resolves via search_path
        # to public.unaccent, STABLE), does NOT match the indexed expression and
        # the planner falls back to a seq scan that grows linearly with admin
        # activity. Same shape as catalog.search.service_filters.
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
        # resource_type stays ILIKE -- it is a fixed enum-like string column with
        # low cardinality and no trigram index; the optimizer handles it with the
        # existing composite index on (resource_type) when present.
        # WR-02: escape %, _, and \\ so admin searches for literal special chars
        # return the correct rows rather than acting as wildcards.
        search_filter = (
            action_match
            | AuditLog.resource_type.ilike(f"%{escape_ilike(search)}%", escape="\\")
            | username_match
        )
        query = query.where(search_filter)
    return query


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

    ``user_id=None`` is structurally accepted: the underlying ``audit_logs.user_id``
    column is nullable (ON DELETE SET NULL FK + SAML-JIT preexisting use case +
    KNOWN-01 anonymous-download closure).
    """
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
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
) -> tuple[list[AuditLog], int]:
    """Query audit logs with optional filters and pagination.

    Returns (logs, total_count) ordered by created_at descending.

    Uses ``COUNT(*) OVER ()`` so the total count rides along with the
    filtered slice in a single round trip, instead of running a
    sibling count query (PERF-4).
    """
    # Call _apply_filters directly with keyword args (not **unpack of a dict)
    # so mypy preserves the per-parameter type narrowing — unpacking a
    # heterogeneous dict drops each key's specific annotation.
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
    query = query.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit)

    result = await session.execute(query)
    rows = result.unique().all()
    if not rows:
        # Empty slice — fall back to a count-only query so callers still
        # see the correct total for "no results on this page" pagination.
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


# SEC-FU-08: Column DDL action strings emitted by the column-DDL endpoints
# (backend/app/modules/catalog/layers/router.py). These 4 values are the canonical
# set; do NOT add new strings here without also updating the router audit_emit calls.
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

    SEC-FU-08: Filters audit_logs to the 4 column-DDL action strings emitted
    by the column-DDL endpoints in Phase 1061 SEC-S03, ordered by created_at
    DESC. Returns a ``(rows, total_count)`` tuple matching the existing
    ``query_audit_logs`` shape for consistent pagination at the router layer.

    Eager-loads AuditLog.user (already ``lazy="joined"`` in the model) so
    the response can include the actor username without an N+1.

    No schema migration required — uses the existing audit_logs table.

    Args:
        session: Async SQLAlchemy session.
        dataset_id: The dataset whose column-DDL history to fetch.
        limit: Maximum rows to return (default 50).
        offset: Row offset for pagination (default 0).

    Returns:
        Tuple of (list[AuditLog], total_count).
    """
    where_clauses = [
        AuditLog.resource_type == "dataset",
        AuditLog.resource_id == dataset_id,
        AuditLog.action.in_(_COLUMN_DDL_ACTIONS),
    ]

    # Use window COUNT() to get total in the same round-trip as the row fetch
    # (mirrors the query_audit_logs pattern).
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
        # Empty slice — fall back to a count-only query (mirrors query_audit_logs).
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
