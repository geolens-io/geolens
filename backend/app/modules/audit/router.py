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
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass
from datetime import datetime, timezone

import anyio
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.modules.audit.schemas import (
    AuditLogListResponse,
    AuditLogResponse,
    ColumnDdlEntry,
    ColumnDdlFeedResponse,
)
from app.modules.audit.service import (
    AuditEvent,
    audit_emit,
    audit_emit_durable,
    query_audit_logs,
    query_column_ddl_history,
    stream_audit_logs,
)
from app.core.identity import Identity
from app.modules.auth.dependencies import get_current_active_user, require_permission
from app.core.dependencies import get_client_ip, get_db
from app.processing.export.service import safe_content_disposition
from app.standards.ogc.errors import ERROR_RESPONSES_AUTH

logger = structlog.stdlib.get_logger(__name__)

# Shares /admin prefix with admin/router.py — kept separate for module organization.
router = APIRouter(prefix="/admin", tags=["Admin"], responses=ERROR_RESPONSES_AUTH)

# SEC-FU-08: Owner-facing column-DDL feed at /audit/* (separate prefix so it
# is accessible to non-admin dataset owners, not just superusers).
audit_datasets_router = APIRouter(
    prefix="/audit", tags=["Audit"], responses=ERROR_RESPONSES_AUTH
)


# Community includes bounded CSV and JSON export. Enterprise automation uses
# separate extension sinks and routes.
FORMAT_HANDLERS: dict[str, str] = {
    "csv": "text/csv",
    "json": "application/json",
}
_EXPORT_OUTCOME_TIMEOUT_SECONDS = 5


def _safe_csv_cell(value: str) -> str:
    """Prevent spreadsheet formula execution for user-controlled CSV cells."""
    if value and value[0] in ("=", "+", "-", "@"):
        return "\t" + value
    return value


@dataclass(frozen=True)
class _AuditExportStream:
    """Own one audit export's fresh-session stream and outcome bookkeeping."""

    actor_id: uuid.UUID
    export_id: uuid.UUID
    ip_address: str | None
    audit_context: dict[str, object]
    user_id: uuid.UUID | None
    action: str | None
    resource_type: str | None
    resource_id: uuid.UUID | None
    date_from: datetime | None
    date_to: datetime | None
    search: str | None
    max_rows: int

    async def _record_outcome(self, outcome: str, selected_rows: int) -> None:
        details: dict[str, object] = {
            **self.audit_context,
            "outcome": outcome,
            "selected_rows": selected_rows,
        }
        if outcome == "failed":
            details["error_code"] = "stream_failed"
        # Shield terminal bookkeeping from level-triggered disconnect
        # cancellation, but cap it so a broken audit store cannot retain the
        # response task indefinitely.
        with anyio.move_on_after(_EXPORT_OUTCOME_TIMEOUT_SECONDS, shield=True):
            try:
                await audit_emit_durable(
                    AuditEvent(
                        user_id=self.actor_id,
                        action="audit.export",
                        resource_type="audit_log",
                        resource_id=self.export_id,
                        details=details,
                        ip_address=self.ip_address,
                    )
                )
            except Exception:  # broad: response bytes may already have been sent
                logger.exception(
                    "Failed to persist audit export stream outcome",
                    operation_id=str(self.export_id),
                    outcome=outcome,
                )

    async def _logs(self):
        from app.core.db import async_session

        async with async_session() as stream_db:
            async for log in stream_audit_logs(
                stream_db,
                user_id=self.user_id,
                action=self.action,
                resource_type=self.resource_type,
                resource_id=self.resource_id,
                exclude_resource_id=self.export_id,
                date_from=self.date_from,
                date_to=self.date_to,
                search=self.search,
            ):
                yield log

    async def csv_generator(self) -> AsyncGenerator[str, None]:
        """Yield hardened CSV chunks and record the actual emitted row count."""
        row_count = 0
        try:
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

            async with aclosing(self._logs()) as logs:
                async for log in logs:
                    if row_count >= self.max_rows:
                        break
                    writer.writerow(
                        [
                            _safe_csv_cell(
                                log.created_at.isoformat() if log.created_at else ""
                            ),
                            _safe_csv_cell(log.user.username if log.user else ""),
                            _safe_csv_cell(log.action),
                            _safe_csv_cell(log.resource_type),
                            _safe_csv_cell(
                                str(log.resource_id) if log.resource_id else ""
                            ),
                            _safe_csv_cell(log.ip_address or ""),
                            _safe_csv_cell(
                                json.dumps(log.details) if log.details else ""
                            ),
                        ]
                    )
                    yield buf.getvalue()
                    row_count += 1
                    buf.seek(0)
                    buf.truncate(0)
        except BaseException:  # record disconnects/cancellation as failed exports
            await self._record_outcome("failed", row_count)
            raise
        else:
            await self._record_outcome("completed", row_count)

    async def json_generator(self) -> AsyncGenerator[str, None]:
        """Yield JSON chunks and record the actual emitted row count."""
        row_count = 0
        try:
            yield "["
            first = True
            async with aclosing(self._logs()) as logs:
                async for log in logs:
                    if row_count >= self.max_rows:
                        break
                    row = {
                        "timestamp": (
                            log.created_at.isoformat() if log.created_at else None
                        ),
                        "username": log.user.username if log.user else None,
                        "action": log.action,
                        "resource_type": log.resource_type,
                        "resource_id": (
                            str(log.resource_id) if log.resource_id else None
                        ),
                        "ip_address": log.ip_address,
                        "details": log.details,
                    }
                    prefix = "" if first else ","
                    yield prefix + json.dumps(row)
                    row_count += 1
                    first = False
            yield "]"
        except BaseException:  # record disconnects/cancellation as failed exports
            await self._record_outcome("failed", row_count)
            raise
        else:
            await self._record_outcome("completed", row_count)


# ROUTE-01 (Phase 1092): dual-shape decorator — both trailing-slash and
# no-trailing-slash variants register against the same handler. Slash form
# stays canonical (already in OpenAPI); no-slash is a hidden alias closing
# the 404 regression introduced by redirect_slashes=False (api/main.py).
@router.get(
    "/audit-logs",
    response_model=AuditLogListResponse,
    include_in_schema=False,
)
@router.get("/audit-logs/", response_model=AuditLogListResponse)
async def list_audit_logs(
    user_id: uuid.UUID | None = Query(None),
    action: str | None = Query(None, max_length=200),
    resource_type: str | None = Query(None, max_length=200),
    resource_id: uuid.UUID | None = Query(None),
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
        resource_id=resource_id,
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


@router.get(
    "/audit-logs/export/{format}",
    response_class=StreamingResponse,
)
async def export_audit_logs(
    format: str,
    request: Request,
    user_id: uuid.UUID | None = Query(None),
    action: str | None = Query(None, max_length=200),
    resource_type: str | None = Query(None, max_length=200),
    resource_id: uuid.UUID | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    search: str | None = Query(None, max_length=200),
    max_rows: int = Query(100_000, ge=1, le=100_000),
    user: Identity = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export up to 100,000 audit log rows as CSV or JSON."""
    if format not in FORMAT_HANDLERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"audit-export-{timestamp}.{format}"

    # Correlate both audit rows and exclude them from the export. The fresh
    # streaming SELECT's PostgreSQL MVCC statement snapshot is the authoritative
    # row boundary; no application-clock fence is needed.
    export_id = uuid.uuid4()
    actor_id = user.id
    ip_address = get_client_ip(request)
    filters = {
        "user_id": str(user_id) if user_id else None,
        "action": action,
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id else None,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "search": search,
    }
    audit_context = {
        "operation_id": str(export_id),
        "format": format,
        "mode": "stream",
        "filters": filters,
        "row_limit": max_rows,
    }
    await audit_emit(
        db,
        AuditEvent(
            user_id=actor_id,
            action="audit.export",
            resource_type="audit_log",
            resource_id=export_id,
            details={**audit_context, "outcome": "requested"},
            ip_address=ip_address,
        ),
    )
    # Persist authorization + intent before the response body is released.
    await db.commit()

    export_stream = _AuditExportStream(
        actor_id=actor_id,
        export_id=export_id,
        ip_address=ip_address,
        audit_context=audit_context,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        max_rows=max_rows,
    )
    if format == "csv":
        return StreamingResponse(
            export_stream.csv_generator(),
            media_type="text/csv",
            headers={"Content-Disposition": safe_content_disposition(filename)},
        )

    return StreamingResponse(
        export_stream.json_generator(),
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
    skip: int = Query(
        0,
        ge=0,
        description="Number of audit entries to skip.",
    ),
    offset: int | None = Query(
        None,
        ge=0,
        deprecated=True,
        description="Deprecated alias for skip; takes precedence when supplied.",
    ),
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
    from app.platform.extensions import get_processing_port

    port = get_processing_port()

    # Step 1: load dataset (404 if not found)
    dataset = await port.get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )

    # Step 2: enforce visibility / ownership gate
    # check_dataset_access raises HTTPException(404) for non-owners of private datasets,
    # consistent with the column-DDL write endpoints from Phase 1061 Plan 02.
    await port.check_dataset_access(db, dataset, dataset_id, user)

    # Step 3: fetch DDL history. Preserve the old offset parameter while new
    # clients converge on the repository-wide skip/limit convention.
    pagination_offset = offset if offset is not None else skip
    rows, total = await query_column_ddl_history(
        db, dataset_id, limit=limit, offset=pagination_offset
    )

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
        offset=pagination_offset,
    )
