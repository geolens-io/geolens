import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.audit.models import AuditLog


def _apply_filters(
    query,
    *,
    user_id: uuid.UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
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
    if date_from is not None:
        query = query.where(AuditLog.created_at >= date_from)
    if date_to is not None:
        query = query.where(AuditLog.created_at <= date_to)
    if search is not None:
        pattern = f"%{search}%"
        search_filter = (
            AuditLog.action.ilike(pattern)
            | AuditLog.resource_type.ilike(pattern)
            | AuditLog.user_id.in_(select(User.id).where(User.username.ilike(pattern)))
        )
        query = query.where(search_filter)
    return query


async def log_action(
    session: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Create an audit log entry. Does NOT commit -- caller's transaction handles it."""
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
            search=search,
        )
        count_result = await session.execute(count_query)
        return [], int(count_result.scalar_one())

    logs = [row[0] for row in rows]
    total = int(rows[0][1])
    return logs, total


async def stream_audit_logs(
    session: AsyncSession,
    *,
    action: str | None = None,
    resource_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
) -> AsyncIterator[AuditLog]:
    """Stream audit logs with filters, no pagination.

    Yields AuditLog rows one at a time from a server-side cursor
    for memory-efficient export of large result sets.
    """
    query = select(AuditLog).options(joinedload(AuditLog.user))
    query = _apply_filters(
        query,
        action=action,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    query = query.order_by(AuditLog.created_at.desc())

    result = await session.stream(query)
    async for row in result.scalars():
        yield row
