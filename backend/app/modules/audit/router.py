"""Audit log API endpoints: query audit logs (admin-only).

# Streaming exports
# -----------------
# CSV and JSON exports use ASGI `StreamingResponse` with cursor-based pagination
# inside the underlying `stream_audit_logs` generator. This avoids loading the
# full result set into memory for large date ranges, which is critical because
# audit logs can grow to millions of rows on busy instances. Don't refactor
# the export endpoints to use `query_audit_logs` (which materializes a list)
# unless you also add a hard limit upstream.
#
# # Permissions
# All endpoints require `manage_settings` (admin role only). The audit log
# contains resource IDs and user IDs that would otherwise be hidden by RBAC,
# so it must never be exposed at lower roles. Note: an earlier draft named
# `view_audit`, but that key is not in the canonical `ALL_CAPABILITIES`
# registry — see backend/app/core/permissions.py.
"""

import csv
import io
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.modules.audit.schemas import (
    AuditLogListResponse,
    AuditLogResponse,
    ColumnDdlEntry,
    ColumnDdlFeedResponse,
)
from app.modules.audit.service import (
    query_audit_logs,
    query_column_ddl_history,
    stream_audit_logs,
)
from app.core.identity import Identity
from app.modules.auth.dependencies import get_current_active_user, require_permission
from app.core.dependencies import get_db
from app.platform.extensions import get_audit_extension
from app.platform.extensions.guards import require_enterprise
from app.processing.export.service import safe_content_disposition
from app.standards.ogc.errors import ERROR_RESPONSES_AUTH

# Shares /admin prefix with admin/router.py — kept separate for module organization.
router = APIRouter(prefix="/admin", tags=["Admin"], responses=ERROR_RESPONSES_AUTH)

# SEC-FU-08: Owner-facing column-DDL feed at /audit/* (separate prefix so it
# is accessible to non-admin dataset owners, not just superusers).
audit_datasets_router = APIRouter(
    prefix="/audit", tags=["Audit"], responses=ERROR_RESPONSES_AUTH
)


# Phase 279 ADMIN-04 (M-04): Unified format dispatch. The set of advertised
# formats is owned by the active AuditExtension. This dict registers the core
# implementations that ship in the OSS audit module. Enterprise extensions
# advertising additional formats are responsible for serving them via their
# own router; if such a format reaches THIS route, the gate below 502s.
#
# Adding a new core format: register {format: media_type} here AND extend the
# dispatch in export_audit_logs() below to actually serve it. Adding via the
# extension's get_export_formats() alone is not enough — that just advertises;
# implementation lives here for OSS or in the extension's own router for
# enterprise-specific formats.
FORMAT_HANDLERS: dict[str, str] = {
    "csv": "text/csv",
    "json": "application/json",
}


@router.get("/audit-logs/", response_model=AuditLogListResponse)
async def list_audit_logs(
    user_id: uuid.UUID | None = Query(None),
    action: str | None = Query(None, max_length=200),
    resource_type: str | None = Query(None, max_length=200),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    search: str | None = Query(None, max_length=200),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: Identity = Depends(require_permission("manage_settings")),
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


@router.get("/audit-logs/export/{format}", response_class=StreamingResponse)
async def export_audit_logs(
    format: str,
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    search: str | None = Query(None),
    max_rows: int = Query(100_000, ge=1, le=1_000_000),
    user: Identity = Depends(require_permission("manage_settings")),
    _ent: None = Depends(require_enterprise),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export audit logs as CSV or JSON.

    Available formats are defined by the active ``AuditExtension`` — community
    advertises none (404 via ``require_enterprise``); enterprise overlays
    advertise ``csv``/``json`` (or additional formats) by registering an
    extension whose ``get_export_formats()`` returns the format list. Unknown
    formats also 404 to prevent leaking which formats exist in other editions.
    """
    allowed = set(get_audit_extension().get_export_formats())
    if format not in allowed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if format not in FORMAT_HANDLERS:
        # Phase 279 ADMIN-04 (M-04): The active AuditExtension advertised this
        # format but the OSS audit router does not implement it. Enterprise
        # extensions advertising additional formats are responsible for
        # registering their own route to serve them. Reaching this branch
        # means the operator has an extension overlay that is mis-wired
        # (route not registered, prefix collision, etc.). 502 surfaces "I
        # can't fulfil this; upstream is mis-configured" more accurately
        # than 501 ("never gonna build this") which the prior implementation
        # used.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Format '{format}' is advertised by the active audit "
                "extension but not implemented by the core audit router. "
                "The enterprise overlay must register its own route to "
                "serve this format."
            ),
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"audit-export-{timestamp}.{format}"

    if format == "csv":

        async def csv_generator():
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(
                [
                    "timestamp",
                    "username",
                    "action",
                    "resource_type",
                    "resource_id",
                    "ip_address",
                    "details",
                ]
            )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

            row_count = 0
            async for log in stream_audit_logs(
                db,
                action=action,
                resource_type=resource_type,
                date_from=date_from,
                date_to=date_to,
                search=search,
            ):
                if row_count >= max_rows:
                    break
                writer.writerow(
                    [
                        log.created_at.isoformat() if log.created_at else "",
                        log.user.username if log.user else "",
                        log.action,
                        log.resource_type,
                        str(log.resource_id) if log.resource_id else "",
                        log.ip_address or "",
                        json.dumps(log.details) if log.details else "",
                    ]
                )
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)
                row_count += 1

        return StreamingResponse(
            csv_generator(),
            media_type="text/csv",
            headers={"Content-Disposition": safe_content_disposition(filename)},
        )

    # JSON format
    async def json_generator():
        yield "["
        first = True
        row_count = 0
        async for log in stream_audit_logs(
            db,
            action=action,
            resource_type=resource_type,
            date_from=date_from,
            date_to=date_to,
            search=search,
        ):
            if row_count >= max_rows:
                break
            row = {
                "timestamp": log.created_at.isoformat() if log.created_at else None,
                "username": log.user.username if log.user else None,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": str(log.resource_id) if log.resource_id else None,
                "ip_address": log.ip_address,
                "details": log.details,
            }
            prefix = "" if first else ","
            yield prefix + json.dumps(row)
            first = False
            row_count += 1
        yield "]"

    return StreamingResponse(
        json_generator(),
        media_type="application/json",
        headers={"Content-Disposition": safe_content_disposition(filename)},
    )


# ---------------------------------------------------------------------------
# SEC-FU-08: Owner-facing column-DDL feed
# ---------------------------------------------------------------------------


@audit_datasets_router.get(
    "/datasets/{dataset_id}/column-ddl",
    response_model=ColumnDdlFeedResponse,
)
async def get_column_ddl_feed(
    dataset_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ColumnDdlFeedResponse:
    """Return the column-DDL audit history for a dataset.

    SEC-FU-08: Surfaces the column-DDL events written by SEC-S03 (Phase 1061)
    to dataset owners so they can detect editor-initiated schema changes.

    Access control (AGENTS.md Pre-Commit Checklist Rule 1):
    - Owner + granted roles: 200 with their own dataset's DDL history
    - Non-owner editor (no grant): 404 (check_dataset_access raises 404 for
      private datasets)
    - Admin: 200 (admin access is always allowed)
    - Anonymous: 401 (get_current_active_user dependency)

    The dataset 404-before-auth-query ordering ensures non-existent datasets
    return 404 without leaking audit log details.
    """
    from app.modules.catalog.authorization import check_dataset_access
    from app.modules.catalog.datasets.domain.service import get_dataset

    # Step 1: load dataset (404 if not found)
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )

    # Step 2: enforce visibility / ownership gate
    # check_dataset_access raises HTTPException(404) for non-owners of private datasets,
    # consistent with the column-DDL write endpoints from Phase 1061 Plan 02.
    await check_dataset_access(db, dataset, dataset_id, user)

    # Step 3: fetch DDL history
    rows, total = await query_column_ddl_history(db, dataset_id, limit=limit, offset=offset)

    return ColumnDdlFeedResponse(
        items=[
            ColumnDdlEntry(
                action=row.action,
                created_at=row.created_at,
                details=row.details,
                user_id=row.user_id,
                username=row.user.username if row.user else None,
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
