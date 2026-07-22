"""Admin API endpoints: user management and catalog stats (admin-only)."""

import asyncio
import csv
import io
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import NoReturn

import anyio
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.modules.admin.schemas import (
    AdminJobListResponse,
    AdminJobResponse,
    AdminUserCreate,
    AIStatusResponse,
    AIStatusUpdate,
    ApproveRequest,
    BackfillResponse,
    CatalogStatsResponse,
    EmbeddingStatsResponse,
    SamlToLocalConversion,
    UserListResponse,
    UserNameItem,
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
from app.modules.auth.router import limiter  # HARDEN-01: shared rate-limiter instance
from app.modules.auth.models import User
from app.modules.auth.schemas import UserResponse
from app.processing.export.service import safe_content_disposition
from app.core.config import settings as app_settings
from app.core.db.tenant_session import tenant_job_context
from app.core.dependencies import get_client_ip, get_db
from app.modules.admin.router_operations import router as operations_router
from app.platform.jobs.router import get_retry_capability
from app.standards.ogc.errors import (
    BAD_GATEWAY_RESPONSE,
    CONFLICT_RESPONSE,
    ERROR_RESPONSES_AUTH,
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
    # DOMAIN-04: enforce allowed_email_domains on admin-create.
    # Break-glass: the requesting admin (current_user) is exempt if they hold
    # manage_settings — a uniform "admin escape hatch" that mirrors the login
    # break-glass (T-1236-02: break-glass is server-side capability, not a
    # client header). A null/absent email is permitted (no address to gate on).
    if body.email:
        from app.core.persistent_config import ALLOWED_EMAIL_DOMAINS  # LAZY — per D-17
        from app.modules.auth.domain_validation import (
            is_email_allowed,
        )  # LAZY — per D-17
        from app.modules.auth.permissions import (  # LAZY — per D-17
            MANAGE_SETTINGS,
            user_has_capability,
        )

        # Cache-bypass: enforcement reads committed state (see auth login gate).
        domains = await ALLOWED_EMAIL_DOMAINS.get_uncached(db)
        if not is_email_allowed(body.email, domains):
            has_break_glass = await user_has_capability(
                db, current_user, MANAGE_SETTINGS
            )
            if not has_break_glass:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Email domain is not permitted",
                )

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
    db: AsyncSession = Depends(get_db),
) -> UserListResponse:
    """List all users with pagination and optional status/search filter (admin only)."""
    service = AdminService(db)
    users, total = await service.list_users(
        skip=skip, limit=limit, status=status_filter, search=search
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

    def _safe(val: str) -> str:
        """Prefix formula-injection trigger characters with a tab."""
        if val and val[0] in ("=", "+", "-", "@"):
            return "\t" + val
        return val

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
                                _safe(user.email or ""),
                                _safe(user.username or ""),
                                _safe(user.auth_provider or ""),
                                _safe(user.status or ""),
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
    db: AsyncSession = Depends(get_db),
) -> AdminJobListResponse:
    """List all ingestion jobs with optional status/user/search filters (admin only)."""
    service = AdminService(db)
    rows, total = await service.list_jobs(
        status=status, user_id=user_id, search=search, skip=skip, limit=limit
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
    responses={502: BAD_GATEWAY_RESPONSE},
)
@limiter.limit("30/minute")
async def trigger_backfill(
    request: Request,
    db: AsyncSession = Depends(get_db),
    force: bool = False,
    current_user: User = Depends(require_permission("manage_users")),
) -> BackfillResponse:
    """Trigger semantic-search embedding generation for records (admin only).

    Pass ?force=true to delete all existing embeddings and regenerate from
    scratch (required after changing the embedding model or dimensions).
    """
    from app.processing.embeddings.backfill import backfill_embeddings

    operation_id = str(uuid.uuid4())
    current_user_id = current_user.id
    ip_address = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user_id,
            action="embedding.backfill",
            resource_type="record_embedding",
            details={
                "force": force,
                "operation_id": operation_id,
                "outcome": "requested",
            },
            ip_address=ip_address,
        ),
    )
    # Force mode commits a destructive DELETE before provider work starts.
    # Make the operator's request durable before that first mutation.
    await db.commit()

    try:
        result = await backfill_embeddings(db, force=force)
    except Exception:  # broad: backfill spans embedding SDK + DB writes — diverse errors map to 502 without leaking traceback
        # RES-2: don't leak raw exception text (can contain asyncpg internals,
        # file paths, DB server info) to admin clients. Log full traceback,
        # return a generic 502.
        logger.exception(
            "Embedding backfill failed",
            user_id=str(current_user_id),
            force=force,
            operation_id=operation_id,
        )
        await db.rollback()
        try:
            await audit_emit_durable(
                AuditEvent(
                    user_id=current_user_id,
                    action="embedding.backfill",
                    resource_type="record_embedding",
                    details={
                        "force": force,
                        "operation_id": operation_id,
                        "outcome": "failed",
                        "error_code": "backfill_failed",
                    },
                    ip_address=ip_address,
                ),
            )
        except Exception:  # broad: preserve the generic operation failure response
            logger.exception(
                "Failed to persist embedding backfill failure audit",
                user_id=str(current_user_id),
                operation_id=operation_id,
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Embedding backfill failed. See server logs for details.",
        ) from None
    await audit_emit_durable(
        AuditEvent(
            user_id=current_user_id,
            action="embedding.backfill",
            resource_type="record_embedding",
            details={
                "force": force,
                "operation_id": operation_id,
                "outcome": "completed",
                **result,
            },
            ip_address=ip_address,
        ),
    )
    return BackfillResponse(**result)
