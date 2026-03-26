"""Audit log API endpoints: query and export audit logs (admin-only)."""

import csv
import io
import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.schemas import AuditLogListResponse, AuditLogResponse
from app.audit.service import query_audit_logs, stream_audit_logs
from app.auth.dependencies import require_permission
from app.auth.models import User
from app.dependencies import get_db
from app.extensions.guards import require_enterprise

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    user_id: uuid.UUID | None = Query(None),
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    search: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
) -> AuditLogListResponse:
    """Query audit logs with optional filters (admin only)."""
    logs, total = await query_audit_logs(
        db,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
        skip=skip,
        limit=limit,
    )
    return AuditLogListResponse(
        logs=[
            AuditLogResponse(
                id=log.id,
                user_id=log.user_id,
                username=log.user.username if log.user else None,
                action=log.action,
                resource_type=log.resource_type,
                resource_id=log.resource_id,
                details=log.details,
                ip_address=log.ip_address,
                created_at=log.created_at,
            )
            for log in logs
        ],
        total=total,
    )


# ---- Export endpoints (enterprise-only) ----

CSV_COLUMNS = [
    "timestamp", "username", "action", "resource_type",
    "resource_id", "ip_address", "details",
]


def _export_filename(fmt: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"audit-export-{today}.{fmt}"


def _log_to_row(log) -> dict[str, str]:
    """Convert an AuditLog ORM instance to a flat dict for export."""
    return {
        "timestamp": log.created_at.isoformat() if log.created_at else "",
        "username": log.user.username if log.user else "",
        "action": log.action or "",
        "resource_type": log.resource_type or "",
        "resource_id": str(log.resource_id) if log.resource_id else "",
        "ip_address": log.ip_address or "",
        "details": json.dumps(log.details) if log.details else "",
    }


async def _stream_csv(
    db: AsyncSession,
    **filter_kwargs,
) -> AsyncIterator[str]:
    """Yield CSV rows as strings for StreamingResponse."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    yield buf.getvalue()
    buf.seek(0)
    buf.truncate(0)

    async for log in stream_audit_logs(db, **filter_kwargs):
        writer.writerow(_log_to_row(log))
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)


async def _stream_json(
    db: AsyncSession,
    **filter_kwargs,
) -> AsyncIterator[str]:
    """Yield JSON array elements for StreamingResponse."""
    yield "["
    first = True
    async for log in stream_audit_logs(db, **filter_kwargs):
        row = _log_to_row(log)
        prefix = "\n" if first else ",\n"
        first = False
        yield prefix + json.dumps(row)
    yield "\n]"


@router.get("/audit-logs/export/csv")
async def export_audit_logs_csv(
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    search: str | None = Query(None),
    user: User = Depends(require_permission("manage_settings")),
    _enterprise: None = Depends(require_enterprise),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export audit logs as CSV (enterprise only)."""
    return StreamingResponse(
        _stream_csv(
            db, action=action, resource_type=resource_type,
            date_from=date_from, date_to=date_to, search=search,
        ),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{_export_filename("csv")}"',
        },
    )


@router.get("/audit-logs/export/json")
async def export_audit_logs_json(
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    search: str | None = Query(None),
    user: User = Depends(require_permission("manage_settings")),
    _enterprise: None = Depends(require_enterprise),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export audit logs as JSON (enterprise only)."""
    return StreamingResponse(
        _stream_json(
            db, action=action, resource_type=resource_type,
            date_from=date_from, date_to=date_to, search=search,
        ),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{_export_filename("json")}"',
        },
    )
