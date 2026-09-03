"""Admin API endpoints: user management and catalog stats (admin-only)."""

import asyncio
import csv
import io
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any, NoReturn

import anyio
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.modules.admin.schemas import (
    AdminJobListResponse,
    AdminJobResponse,
    AdminPasswordReset,
    AdminUserCreate,
    AIStatusResponse,
    AIStatusUpdate,
    ApproveRequest,
    BackfillResponse,
    CatalogStatsResponse,
    EmbeddingStatsResponse,
    JobSortField,
    SamlToLocalConversion,
    SortDirection,
    UserListResponse,
    UserNameItem,
    UserSortField,
    UserUpdate,
)
from app.modules.admin.service import (
    AdminService,
    PendingUserMutationError,
    PendingUserTransitionConflict,
)
from app.modules.quota.service import get_user_quota_usage_bulk
from app.modules.audit.service import AuditEvent, audit_emit, audit_emit_durable
from app.modules.auth.dependencies import require_mode_permission, require_permission
from app.platform.ratelimit import limiter  # HARDEN-01: shared rate-limiter instance
from app.modules.auth.models import User
from app.modules.auth.schemas import UserResponse
from app.processing.export.service import safe_content_disposition
from app.core.config import settings as app_settings
from app.core.db.tenant_session import defer_async_with_tenant, tenant_job_context
from app.core.csv_safety import escape_csv_formula
from app.core.dependencies import get_client_ip, get_db
from app.modules.admin.router_operations import router as operations_router
from app.platform.extensions import get_catalog_port
from app.platform.jobs.defer_guard import (
    DeferFailed,
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)
from app.platform.jobs.models import (
    ACTIVE_BACKFILL_INDEX_NAME,
    EMBEDDING_BACKFILL_METADATA_KEY,
)
from app.platform.jobs.router import get_retry_capability
from app.standards.ogc.errors import (
    CONFLICT_RESPONSE,
    ERROR_RESPONSES_AUTH,
    NOT_FOUND_RESPONSE,
    QUEUE_UNAVAILABLE_RESPONSE,
)

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"], responses=ERROR_RESPONSES_AUTH)
router.include_router(operations_router)

require_ai_status_reader = require_mode_permission(
    single_tenant="manage_users", multi_tenant="manage_tenants"
)
require_ai_status_writer = require_mode_permission(
    single_tenant="manage_settings", multi_tenant="manage_tenants"
)
_EXPORT_OUTCOME_TIMEOUT_SECONDS = 5


def _user_response(user: User) -> UserResponse:
    """Convert a User ORM object to a UserResponse schema."""
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        status=user.status,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        roles=sorted(r.name for r in user.roles),
    )


def _refuse_backfill_in_flight(
    *,
    active_job_id: str | None,
    user_id: str,
    force: bool,
    detected_by: str,
) -> NoReturn:
    """Refuse a backfill because one is already in flight.

    Shared by the two halves of the guard so they cannot drift into telling an
    operator two different stories about the same state: the pre-flight query,
    which answers the ordinary retry, and the partial unique index, which is
    what actually holds when two requests arrive together. ``detected_by`` is
    logged, not returned — which half caught it is an operational detail, and
    the caller's situation is identical either way.

    ``active_job_id`` can be None only on the index path, when the winning run
    finished between the violation and the re-read. Say less rather than
    guessing an id.
    """
    logger.info(
        "embedding_backfill_refused_run_in_flight",
        user_id=user_id,
        force=force,
        active_job_id=active_job_id,
        detected_by=detected_by,
    )
    if active_job_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An embedding backfill is already running. Retry shortly.",
        )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"An embedding backfill is already running (job {active_job_id}). "
            f"Wait for it to finish, or poll /jobs/{active_job_id} for its status."
        ),
    )


def _raise_on_error(exc: ValueError, default_status: int) -> NoReturn:
    """Map a service-layer ValueError to an HTTPException.

    'not found' messages map to 404; everything else uses default_status.
    """
    detail = str(exc)
    if "not found" in detail.lower():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    raise HTTPException(status_code=default_status, detail=detail)


# ROUTE-01 (Phase 1092): dual-shape decorator — both trailing-slash and
# no-trailing-slash variants register against the same handler. Slash form
# stays canonical (already in OpenAPI); no-slash is a hidden alias closing
# the 404 regression introduced by redirect_slashes=False (api/main.py).
@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/users/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: CONFLICT_RESPONSE},
)
@limiter.limit("30/minute")
async def create_user(
    body: AdminUserCreate,
    request: Request,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Create a new user with the specified role (admin only)."""
    # DOMAIN-04: enforce allowed_email_domains on admin-create. Break-glass:
    # the requesting admin is exempt when they hold manage_settings (see the
    # shared gate, fix(#836)).
    from app.modules.auth.domain_policy import (  # LAZY — per D-17
        enforce_email_domain_gate,
    )

    await enforce_email_domain_gate(db, body.email, break_glass_user=current_user)

    service = AdminService(db)
    try:
        user = await service.create_user(
            username=body.username,
            password=body.password,
            email=body.email,
            role_name=body.role,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    ip = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="user.create",
            resource_type="user",
            resource_id=user.id,
            details={"username": body.username, "role": body.role},
            ip_address=ip,
        ),
    )
    await db.commit()
    return _user_response(user)


# ROUTE-01 (Phase 1092): dual-shape decorator — see /users above.
@router.get(
    "/users",
    response_model=UserListResponse,
    dependencies=[Depends(require_permission("manage_users"))],
    include_in_schema=False,
)
@router.get(
    "/users/",
    response_model=UserListResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status", max_length=50),
    search: str | None = Query(None, max_length=200),
    sort: UserSortField = Query(
        "created_at",
        description=(
            "Column to order by. Roles and storage are not sortable: roles is a "
            "many-to-many and storage is aggregated per page after the query."
        ),
    ),
    order: SortDirection = Query("asc", description="Sort direction."),
    db: AsyncSession = Depends(get_db),
) -> UserListResponse:
    """List all users with pagination and optional status/search/sort filter (admin only).

    `sort` and `order` are closed enums, so an unrecognised value is refused
    with a 422 and never reaches the query.
    """
    service = AdminService(db)
    users, total = await service.list_users(
        skip=skip,
        limit=limit,
        status=status_filter,
        search=search,
        sort=sort,
        order=order,
    )
    # QUOTA-04: quota usage for the page. fix(#435): genuinely batched now — this
    # said "batch" but ran one three-table aggregate per user, 200 users per page.
    usage_by_user = await get_user_quota_usage_bulk(db, [u.id for u in users])
    user_responses = [
        UserResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            is_active=u.is_active,
            status=u.status,
            last_login_at=u.last_login_at,
            created_at=u.created_at,
            roles=sorted(r.name for r in u.roles),
            quota_usage=usage_by_user[u.id],
        )
        for u in users
    ]
    return UserListResponse(users=user_responses, total=total)


@router.get(
    "/users/export.csv",
    response_class=StreamingResponse,
    summary="Export registered users as CSV",
    tags=["Admin"],
)
async def export_users_csv(
    request: Request,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export all registered users as a hardened CSV file (admin only).

    Columns: email, display_name, auth_provider, status, created_at.
    Rows are ordered by created_at ASC and streamed without full materialisation.
    Cells starting with =, +, -, or @ are tab-prefixed (CSV injection hardening).
    """

    operation_id = uuid.uuid4()
    actor_id = current_user.id
    ip_address = get_client_ip(request)
    tenant_id = getattr(getattr(request, "state", None), "tenant_id", None)
    audit_context = {
        "operation_id": str(operation_id),
        "format": "csv",
        "mode": "stream",
        "filters": {},
    }
    await audit_emit(
        db,
        AuditEvent(
            user_id=actor_id,
            action="user.export",
            resource_type="user",
            resource_id=operation_id,
            details={**audit_context, "outcome": "requested"},
            ip_address=ip_address,
        ),
    )
    # The response body executes after this handler returns. Persist the request
    # before releasing the stream, then use fresh sessions for stream outcome
    # bookkeeping so the request-scoped session is never reused concurrently.
    await db.commit()

    async def record_outcome(outcome: str, selected_rows: int) -> None:
        details: dict[str, object] = {
            **audit_context,
            "outcome": outcome,
            "selected_rows": selected_rows,
        }
        if outcome == "failed":
            details["error_code"] = "stream_failed"
        # AnyIO cancellation is level-triggered: after a client disconnect,
        # an unshielded await is cancelled immediately and cannot persist the
        # promised terminal event. Bound the shield so disconnect cleanup can
        # never hold a response task indefinitely.
        with tenant_job_context(tenant_id):
            with anyio.move_on_after(_EXPORT_OUTCOME_TIMEOUT_SECONDS, shield=True):
                try:
                    await audit_emit_durable(
                        AuditEvent(
                            user_id=actor_id,
                            action="user.export",
                            resource_type="user",
                            resource_id=operation_id,
                            details=details,
                            ip_address=ip_address,
                        )
                    )
                except Exception:  # broad: response bytes may already have been sent
                    logger.exception(
                        "Failed to persist user export stream outcome",
                        operation_id=str(operation_id),
                        outcome=outcome,
                    )

    async def csv_generator() -> AsyncGenerator[str, None]:
        row_count = 0
        try:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(
                ["email", "display_name", "auth_provider", "status", "created_at"]
            )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

            from app.core.db import async_session

            with tenant_job_context(tenant_id):
                async with async_session() as stream_db:
                    stmt = select(User).order_by(User.created_at.asc())
                    result = await stream_db.stream(stmt)
                    async for (user,) in result:
                        writer.writerow(
                            [
                                escape_csv_formula(user.email or ""),
                                escape_csv_formula(user.username or ""),
                                escape_csv_formula(user.auth_provider or ""),
                                escape_csv_formula(user.status or ""),
                                user.created_at.isoformat() if user.created_at else "",
                            ]
                        )
                        yield buf.getvalue()
                        # Reaching this line means the preceding body chunk was
                        # accepted by the ASGI send loop.
                        row_count += 1
                        buf.seek(0)
                        buf.truncate(0)
        except BaseException:  # record disconnects/cancellation as failed exports
            await record_outcome("failed", row_count)
            raise
        else:
            await record_outcome("completed", row_count)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"users-export-{ts}.csv"
    return StreamingResponse(
        csv_generator(),
        media_type="text/csv",
        headers={"Content-Disposition": safe_content_disposition(filename)},
    )


# ROUTE-01 (Phase 1092): dual-shape decorator — see /users above.
@router.get(
    "/users/names",
    response_model=list[UserNameItem],
    dependencies=[Depends(require_permission("manage_users"))],
    include_in_schema=False,
)
@router.get(
    "/users/names/",
    response_model=list[UserNameItem],
    dependencies=[Depends(require_permission("manage_users"))],
)
async def list_user_names(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
) -> list[UserNameItem]:
    """Return lightweight id+username list for filter dropdowns.

    Paginated to bound response size on deployments with many users. Default
    page size of 500 is enough for typical admin dropdowns; the limit cap of
    1000 matches the previous hard cap. Clients needing the full list should
    page by incrementing ``skip``.
    """
    result = await db.execute(
        select(User.id, User.username).order_by(User.username).offset(skip).limit(limit)
    )
    return [UserNameItem(id=row.id, username=row.username) for row in result.all()]


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Get a specific user by ID (admin only)."""
    service = AdminService(db)
    try:
        user = await service.get_user(user_id)
    except ValueError as exc:
        _raise_on_error(exc, status.HTTP_404_NOT_FOUND)
    return _user_response(user)


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
)
@limiter.limit("30/minute")
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    request: Request,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Update a user's fields and/or role (admin only)."""
    if user_id == current_user.id and (
        body.role is not None
        or body.is_active is False
        or body.status in {"suspended", "deactivated"}
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot change your own role or disable your own account",
        )
    service = AdminService(db)
    try:
        user, before, after = await service.update_user_with_snapshot(
            user_id, body, current_user_id=current_user.id
        )
    except PendingUserMutationError as exc:
        _raise_on_error(exc, status.HTTP_422_UNPROCESSABLE_ENTITY)
    except ValueError as exc:
        _raise_on_error(exc, status.HTTP_409_CONFLICT)
    ip = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="user.update",
            resource_type="user",
            resource_id=user_id,
            details={"before": before, "after": after},
            ip_address=ip,
        ),
    )
    await db.commit()
    return _user_response(user)


# ROUTE-01 (Phase 1092): dual-shape decorator — see /users above.
@router.post(
    "/users/{user_id}/deactivate",
    response_model=UserResponse,
    include_in_schema=False,
)
@router.post(
    "/users/{user_id}/deactivate/",
    response_model=UserResponse,
)
@limiter.limit("30/minute")
async def deactivate_user(
    user_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Deactivate a user (admin only)."""
    service = AdminService(db)
    try:
        user = await service.deactivate_user(user_id, current_user.id)
    except PendingUserTransitionConflict as exc:
        _raise_on_error(exc, status.HTTP_409_CONFLICT)
    except ValueError as exc:
        _raise_on_error(exc, status.HTTP_400_BAD_REQUEST)
    ip = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="user.deactivate",
            resource_type="user",
            resource_id=user_id,
            details={"username": user.username},
            ip_address=ip,
        ),
    )
    await db.commit()
    return _user_response(user)


# ROUTE-01 (Phase 1092): dual-shape decorator — see /users above.
@router.post(
    "/users/{user_id}/reset-password",
    response_model=UserResponse,
    include_in_schema=False,
)
@router.post(
    "/users/{user_id}/reset-password/",
    response_model=UserResponse,
    responses={404: NOT_FOUND_RESPONSE},
)
@limiter.limit("30/minute")
async def reset_user_password(
    user_id: uuid.UUID,
    body: AdminPasswordReset,
    request: Request,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Set a user's password (admin only).

    feat(#1715): the login page tells a locked-out user to ask an
    administrator, and there was nothing for the administrator to do. This is
    the recovery path, so it asks for no current password -- holding
    manage_users is the whole authorization, and the audit row is what makes
    the action answerable for. The submitted value reaches the hash column and
    nowhere else: not the audit details, not a log line, not the response.

    422 when the target signs in through an identity provider (no local
    password to replace), 404 when no such user exists -- both via the shared
    _raise_on_error mapping the sibling lifecycle routes use.

    Resetting your own password is permitted and ends every session the
    account holds, including the one making this request, because the reset
    revokes the account's credentials. That is the same consequence
    POST /auth/change-password/ has for the caller who invokes it.
    """
    service = AdminService(db)
    try:
        user = await service.reset_user_password(user_id, body.password)
    except ValueError as exc:
        _raise_on_error(exc, status.HTTP_422_UNPROCESSABLE_ENTITY)
    ip = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="user.password_reset",
            resource_type="user",
            resource_id=user_id,
            details={"username": user.username},
            ip_address=ip,
        ),
    )
    await db.commit()
    return _user_response(user)


# ROUTE-01 (Phase 1092): dual-shape decorator — see /users above.
@router.post(
    "/users/{user_id}/convert-saml-to-local",
    response_model=UserResponse,
    include_in_schema=False,
)
@router.post(
    "/users/{user_id}/convert-saml-to-local/",
    response_model=UserResponse,
    include_in_schema=False,
)
@limiter.limit("30/minute")
async def convert_saml_to_local(
    user_id: uuid.UUID,
    body: SamlToLocalConversion,
    request: Request,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Convert a SAML-authenticated user to local-password (admin only).

    Phase 221 LIFECYCLE-06. The conversion happens in a single DB transaction:
    validate -> set password -> flip auth_provider -> delete SAML oauth_accounts
    row -> write audit_log row. The audit_log write is the LAST step before
    commit (per D-05) so failed conversions never leave an orphan audit entry.

    Audit details are an explicit allow-list ({"from", "to", "provider_slug"})
    -- password material is never logged.

    Self-conversion is blocked with 422 to prevent admin self-lockout when an
    admin fat-fingers the new password (Phase 221 Risk Surfaces / Pitfall 7).
    """
    # Self-conversion guard -- mirrors update_user's self-action guard at
    # router.py:180-184. 422 (NOT 400/403) per the existing convention.
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot convert your own account; use a different admin account",
        )

    service = AdminService(db)
    try:
        user, provider_slug = await service.convert_saml_user_to_local(
            user_id, body.password
        )
    except ValueError as exc:
        # All non-"not found" ValueErrors (auth_provider mismatch, no SAML linkage) -> 422
        _raise_on_error(exc, status.HTTP_422_UNPROCESSABLE_ENTITY)

    ip = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="user.convert_saml_to_local",
            resource_type="user",
            resource_id=user_id,
            details={"from": "saml", "to": "local", "provider_slug": provider_slug},
            ip_address=ip,
        ),
    )
    try:
        await db.commit()
    except Exception:  # broad: commit can fail with diverse asyncpg/transaction errors; log and bubble for handler
        # Service mutations + audit_log row written but commit failed --
        # leaves no persisted record. Log with request_id correlation so
        # operators can reconcile against client-side state.
        logger.exception(
            "convert_saml_to_local commit failed",
            user_id=str(user_id),
            admin_id=str(current_user.id),
            provider_slug=provider_slug,
        )
        raise
    return _user_response(user)


# ROUTE-01 (Phase 1092): dual-shape decorator — see /users above.
@router.post(
    "/users/{user_id}/approve",
    response_model=UserResponse,
    include_in_schema=False,
)
@router.post(
    "/users/{user_id}/approve/",
    response_model=UserResponse,
)
@limiter.limit("30/minute")
async def approve_user(
    user_id: uuid.UUID,
    body: ApproveRequest,
    request: Request,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Approve a pending user with the specified role (admin only)."""
    service = AdminService(db)
    try:
        user = await service.approve_user(user_id, body.role)
    except PendingUserTransitionConflict as exc:
        _raise_on_error(exc, status.HTTP_409_CONFLICT)
    except ValueError as exc:
        _raise_on_error(exc, status.HTTP_400_BAD_REQUEST)
    ip = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="user.approve",
            resource_type="user",
            resource_id=user_id,
            details={"username": user.username, "role": body.role},
            ip_address=ip,
        ),
    )
    await db.commit()
    return _user_response(user)


# ROUTE-01 (Phase 1092): dual-shape decorator — see /users above.
@router.post(
    "/users/{user_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
@router.post(
    "/users/{user_id}/reject/",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit("30/minute")
async def reject_user(
    user_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Reject a pending user by hard-deleting them (admin only)."""
    service = AdminService(db)
    try:
        await service.reject_user(user_id)
    except PendingUserTransitionConflict as exc:
        _raise_on_error(exc, status.HTTP_409_CONFLICT)
    except ValueError as exc:
        _raise_on_error(exc, status.HTTP_400_BAD_REQUEST)
    ip = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="user.reject",
            resource_type="user",
            resource_id=user_id,
            ip_address=ip,
        ),
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit("30/minute")
async def delete_user(
    user_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Hard-delete a user (admin only). Returns 400 for self-deletion or last-admin."""
    service = AdminService(db)
    try:
        deleted_username = await service.delete_user(user_id, current_user.id)
    except ValueError as exc:
        _raise_on_error(exc, status.HTTP_400_BAD_REQUEST)
    ip = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="user.delete",
            resource_type="user",
            resource_id=user_id,
            details={"username": deleted_username},
            ip_address=ip,
        ),
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ROUTE-01 (Phase 1092): dual-shape decorator — see /users above.
@router.get(
    "/stats",
    response_model=CatalogStatsResponse,
    include_in_schema=False,
)
@router.get(
    "/stats/",
    response_model=CatalogStatsResponse,
)
async def get_catalog_stats(
    user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> CatalogStatsResponse:
    """Return catalog statistics: counts, storage, breakdowns (admin only)."""
    service = AdminService(db)
    return await service.get_catalog_stats()


# ROUTE-01 (Phase 1092): dual-shape decorator — see /users above.
@router.get(
    "/jobs",
    response_model=AdminJobListResponse,
    dependencies=[Depends(require_permission("manage_users"))],
    include_in_schema=False,
)
@router.get(
    "/jobs/",
    response_model=AdminJobListResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def list_admin_jobs(
    status: str | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    search: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    sort: JobSortField = Query(
        "created_at",
        description=(
            "Column to order by. Duration orders by the completed_at - "
            "started_at interval, so unfinished jobs sort last either way."
        ),
    ),
    order: SortDirection = Query("desc", description="Sort direction."),
    db: AsyncSession = Depends(get_db),
) -> AdminJobListResponse:
    """List all ingestion jobs with optional status/user/search/sort filters (admin only).

    `sort` and `order` are closed enums, so an unrecognised value is refused
    with a 422 and never reaches the query.
    """
    service = AdminService(db)
    rows, total = await service.list_jobs(
        status=status,
        user_id=user_id,
        search=search,
        skip=skip,
        limit=limit,
        sort=sort,
        order=order,
    )
    retry_capabilities = await asyncio.gather(
        *(get_retry_capability(job) for job, _username in rows)
    )
    jobs = [
        AdminJobResponse(
            id=job.id,
            status=job.status,
            source_filename=job.source_filename,
            dataset_id=job.dataset_id,
            error_message=job.error_message,
            can_retry=can_retry,
            retry_reason=retry_reason,
            user_metadata=job.user_metadata,
            created_by=job.created_by,
            username=username,
            started_at=job.started_at,
            completed_at=job.completed_at,
            created_at=job.created_at,
        )
        for (job, username), (can_retry, retry_reason) in zip(
            rows, retry_capabilities, strict=True
        )
    ]
    return AdminJobListResponse(jobs=jobs, total=total)


# ---------------------------------------------------------------------------
# AI Status endpoints
# ---------------------------------------------------------------------------


def _ai_status(
    enabled: bool,
    provider: str,
    semantic_search_enabled: bool = False,
    has_embeddings: bool = False,
) -> AIStatusResponse:
    """Build AIStatusResponse from the SELECTED provider + DB toggle.

    builder-audit #338 P1-12: ``configured`` reports readiness of the SELECTED
    ``LLM_PROVIDER`` only — not "any key exists". The chat route
    (``_check_ai_available``) gates on the selected provider's key, so admin
    status and chat readiness must agree: if the operator selects ``anthropic``
    but only an OpenAI key is set, ``configured`` is False even though a key
    exists. The presence of the OTHER provider's key is treated as metadata
    only (it never flips ``configured``/``provider``, which gate chat).
    """
    keys = {
        "anthropic": app_settings.anthropic_api_key,
        "openai_compatible": app_settings.openai_api_key,
    }
    models = {
        "anthropic": app_settings.llm_model,
        "openai_compatible": app_settings.openai_model,
    }
    # Normalize the internal provider id ("openai_compatible") to the public
    # display name ("openai") the AIStatusResponse contract already uses.
    display_names = {"anthropic": "anthropic", "openai_compatible": "openai"}

    selected_key = keys.get(provider)
    configured = bool(selected_key)
    return AIStatusResponse(
        provider=display_names.get(provider) if configured else None,
        model=models.get(provider) if configured else None,
        enabled=enabled,
        configured=configured,
        semantic_search_enabled=semantic_search_enabled,
        has_embeddings=has_embeddings,
    )


# ROUTE-01 (Phase 1092): dual-shape decorator — see /users above.
# fix(#627): exclude_unset so the `probe` field appears ONLY when the caller
# opted in — the default response keeps its exact pre-probe JSON shape.
# Safe because _ai_status passes every other field explicitly.
@router.get(
    "/ai-status",
    response_model=AIStatusResponse,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_ai_status_reader)],
    include_in_schema=False,
)
@router.get(
    "/ai-status/",
    response_model=AIStatusResponse,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_ai_status_reader)],
)
# fix(#627, codex P2): probe=true spends real provider quota and can hold a
# worker for up to the probe timeouts — same 30/minute cap as the PATCH
# sibling. The plain status read shares the limit; dashboards fetch it once
# per view, nowhere near 30/minute.
@limiter.limit("30/minute")
async def get_ai_status(
    request: Request,
    probe: bool = Query(
        default=False,
        description="When true, run a minimal LIVE provider call per purpose "
        "(chat + embeddings) to verify the configured key actually works. "
        "Costs a real provider API call — never enabled by dashboards.",
    ),
    db: AsyncSession = Depends(get_db),
) -> AIStatusResponse:
    """Return single-deployment AI status; no provider-routing policy controls (admin only)."""
    from app.core.persistent_config import (
        AI_ENABLED,
        LLM_PROVIDER,
        SEMANTIC_SEARCH_ENABLED,
    )

    from app.processing.embeddings.helpers import has_embeddings

    enabled = await AI_ENABLED.get(db)
    provider = await LLM_PROVIDER.get(db)
    semantic = await SEMANTIC_SEARCH_ENABLED.get(db)
    has_embeds = await has_embeddings(db)
    result = _ai_status(
        enabled, provider, semantic_search_enabled=semantic, has_embeddings=has_embeds
    )
    if probe:
        from app.processing.ai.probe import run_ai_probe

        result.probe = await run_ai_probe(db)
    return result


# ROUTE-01 (Phase 1092): dual-shape decorator — see /users above.
# fix(#627): exclude_unset for shape parity with GET (probe is never set here).
@router.patch(
    "/ai-status",
    response_model=AIStatusResponse,
    response_model_exclude_unset=True,
    include_in_schema=False,
)
@router.patch(
    "/ai-status/",
    response_model=AIStatusResponse,
    response_model_exclude_unset=True,
)
@limiter.limit("30/minute")
async def update_ai_status(
    body: AIStatusUpdate,
    request: Request,
    user: User = Depends(require_ai_status_writer),
    db: AsyncSession = Depends(get_db),
) -> AIStatusResponse:
    """Toggle base AI features on/off at runtime; no provider-routing policy controls (admin only)."""
    from app.processing.embeddings.helpers import has_embeddings
    from app.core.persistent_config import (
        AI_ENABLED,
        LLM_PROVIDER,
        SEMANTIC_SEARCH_ENABLED,
    )

    await AI_ENABLED.set(
        db,
        body.enabled,
        user_id=user.id,
        ip_address=get_client_ip(request),
    )
    provider = await LLM_PROVIDER.get(db)
    semantic = await SEMANTIC_SEARCH_ENABLED.get(db)
    has_embeds = await has_embeddings(db)
    return _ai_status(
        body.enabled,
        provider,
        semantic_search_enabled=semantic,
        has_embeddings=has_embeds,
    )


# ROUTE-01 (Phase 1092): dual-shape decorator — see /users above.
@router.get(
    "/embedding-stats",
    response_model=EmbeddingStatsResponse,
    dependencies=[Depends(require_permission("manage_users"))],
    include_in_schema=False,
)
@router.get(
    "/embedding-stats/",
    response_model=EmbeddingStatsResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def get_embedding_stats(
    db: AsyncSession = Depends(get_db),
) -> EmbeddingStatsResponse:
    """Return semantic-search embedding coverage statistics (admin only)."""
    service = AdminService(db)
    return await service.get_embedding_stats()


# ROUTE-01 (Phase 1092): dual-shape decorator — see /users above.
@router.post(
    "/backfill-embeddings",
    response_model=BackfillResponse,
    include_in_schema=False,
)
@router.post(
    "/backfill-embeddings/",
    response_model=BackfillResponse,
    responses={409: CONFLICT_RESPONSE, 503: QUEUE_UNAVAILABLE_RESPONSE},
)
@limiter.limit("30/minute")
async def trigger_backfill(
    request: Request,
    db: AsyncSession = Depends(get_db),
    force: bool = False,
    current_user: User = Depends(require_permission("manage_users")),
) -> BackfillResponse:
    """Queue semantic-search embedding generation for records (admin only).

    Pass ?force=true to delete all existing embeddings and regenerate from
    scratch (required after changing the embedding model or dimensions).

    fix(#1542): the run happens on the job queue, not in this request. A full
    regenerate is provider-bound and linear in catalog size, so it outgrew the
    600s edge timeout somewhere below 59,000 records — and the request dying at
    the proxy never stopped the work, it only hid it. Returns the job id;
    poll ``GET /jobs/{job_id}`` for the outcome.
    """
    from app.modules.admin.backfill_jobs import (
        UNRESOLVED_OUTCOME,
        find_active_embedding_backfill,
        run_embedding_backfill,
        settle_undispatched_run,
    )

    operation_id = str(uuid.uuid4())
    current_user_id = current_user.id
    ip_address = get_client_ip(request)

    # The guard that makes the retry safe. Before #1542 a 504'd operator
    # retried and started a second full regenerate alongside the first, which
    # on the force path meant a second DELETE — #1519's pre-flight guards do
    # not see it, because each run passes its own pre-flight independently.
    # This refusal happens before the job row exists, so nothing destructive
    # has been queued, let alone run.
    #
    # fix(#1542 review P1): the SELECT is the FRIENDLY half, not the guard. It
    # answers the common case (an operator retrying seconds later) with a
    # message naming the run to poll. The guard itself is the partial unique
    # index from migration 0050 — a check followed by an insert is a TOCTOU,
    # and two requests arriving together would both pass this and both create a
    # job. Nothing in the application layer can serialize two transactions in
    # two API processes; the database can, so it does.
    active = await find_active_embedding_backfill(db)
    if active is not None:
        _refuse_backfill_in_flight(
            active_job_id=str(active.id),
            user_id=str(current_user_id),
            force=force,
            detected_by="preflight_query",
        )

    # The whole insert is inside the guard, not just the commit: the row goes in
    # with a null `user_metadata` and only becomes a backfill row when the marker
    # is set, so the index rejects it at the UPDATE that flushes that marker —
    # which happens as soon as anything else on this session flushes, well before
    # the commit.
    try:
        job = await get_catalog_port().create_ingest_job(
            db, "embedding-backfill", "", current_user_id
        )
        job.user_metadata = {
            EMBEDDING_BACKFILL_METADATA_KEY: {
                "force": force,
                "operation_id": operation_id,
            }
        }
        # ux(#698), as analysis does: a pending job that says "queued" reads as
        # waiting rather than as a job with nothing to say for itself.
        job.current_step = "queued"
        await audit_emit(
            db,
            AuditEvent(
                user_id=current_user_id,
                action="embedding.backfill",
                resource_type="record_embedding",
                details={
                    "force": force,
                    "operation_id": operation_id,
                    "job_id": str(job.id),
                    "outcome": "requested",
                },
                ip_address=ip_address,
            ),
        )
        # One commit for the job row and the operator's request: the row is what
        # a concurrent request is refused against, and it must be durable before
        # anything can pick the run up.
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if ACTIVE_BACKFILL_INDEX_NAME not in str(getattr(exc, "orig", exc)):
            # Some other constraint. Dressing it up as a concurrency refusal
            # would be a fabricated answer of exactly the kind this endpoint
            # has already been corrected for once.
            raise
        # The index refused it: another request won the race between the SELECT
        # above and this write. The whole transaction rolled back — job row and
        # `requested` audit entry together — so the loser leaves no trace of a
        # run that never started, which is the same state the friendly refusal
        # produces.
        winner = await find_active_embedding_backfill(db)
        _refuse_backfill_in_flight(
            active_job_id=str(winner.id) if winner is not None else None,
            user_id=str(current_user_id),
            force=force,
            detected_by="unique_index",
        )

    async def _defer() -> None:
        await defer_async_with_tenant(
            run_embedding_backfill,
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            force=force,
            user_id=str(current_user_id),
            ip_address=ip_address,
            operation_id=operation_id,
        )

    job_id = str(job.id)
    try:
        await defer_with_orphan_guard(
            _defer,
            rollback=make_ingest_job_failed_rollback(
                job, message_prefix="Failed to queue embedding backfill"
            ),
            db=db,
            job=job,
        )
    except DeferFailed as dispatch_exc:
        # fix(#1550 review P2, round 1): the orphan guard has already marked the
        # job failed and committed, then raised 503. No worker will ever pick
        # this run up, so nothing else can close the trail — without this, the
        # already-committed "requested" entry is the last word and the
        # operation reads as perpetually in flight. The job row and the audit
        # trail are two records of one state, and every path that terminates a
        # run has to write both.
        #
        # fix(#1550 review P2, round 2): condition on whether the rollback
        # actually landed. When the queue AND the rollback both fail, the row is
        # still `pending` — recording "failed" there would be the same lie in a
        # nastier place, because `audit_emit_durable` uses its own session and
        # can succeed after the request's has gone. A pending row keeps
        # blocking later backfills through the guard above, so an operator
        # chasing "why is every backfill refused" would be reading an audit
        # trail that says this one is over.
        if dispatch_exc.rolled_back:
            details: dict[str, Any] = {
                "force": force,
                "operation_id": operation_id,
                "job_id": job_id,
                "outcome": "failed",
                "error_code": "dispatch_failed",
            }
        else:
            details = {
                "force": force,
                "operation_id": operation_id,
                "job_id": job_id,
                "outcome": UNRESOLVED_OUTCOME,
                "error_code": "dispatch_rollback_failed",
                "intended_outcome": "failed",
            }
            logger.error(
                "embedding_backfill_dispatch_rollback_failed",
                user_id=str(current_user_id),
                operation_id=operation_id,
                job_id=job_id,
            )
        try:
            await audit_emit_durable(
                AuditEvent(
                    user_id=current_user_id,
                    action="embedding.backfill",
                    resource_type="record_embedding",
                    details=details,
                    ip_address=ip_address,
                ),
            )
        except Exception:  # broad: the audit write must not mask the 503
            logger.exception(
                "embedding_backfill_dispatch_audit_failed",
                user_id=str(current_user_id),
                operation_id=operation_id,
                job_id=job_id,
            )
        raise
    except asyncio.CancelledError:
        # fix(#1550 review): the orphan guard catches `Exception`, so a
        # cancellation here bypasses it and the `DeferFailed` handler above.
        # The job row is already committed and the queue hop may or may not
        # have landed, so the cleanup is fenced on `pending` and shielded, and
        # the cancellation is re-raised so shutdown still works.
        try:
            await asyncio.shield(
                asyncio.wait_for(
                    settle_undispatched_run(
                        job.id,
                        audit_context={
                            "user_id": str(current_user_id),
                            "ip_address": ip_address,
                            "operation_id": operation_id,
                            "job_id": job_id,
                            "force": force,
                        },
                    ),
                    timeout=15,
                )
            )
        except (
            BaseException
        ):  # broad: best-effort during shutdown; the raise below preserves the abort
            logger.warning(
                "embedding_backfill_dispatch_cancel_cleanup_failed",
                job_id=job_id,
                exc_info=True,
            )
        raise
    return BackfillResponse(job_id=job.id, status="pending")
