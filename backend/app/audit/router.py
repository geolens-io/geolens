"""Audit log API endpoints: query audit logs (admin-only)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.schemas import AuditLogListResponse, AuditLogResponse
from app.audit.service import query_audit_logs
from app.auth.dependencies import require_permission
from app.auth.models import User
from app.dependencies import get_db

# Shares /admin prefix with admin/router.py — kept separate for module organization.
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
