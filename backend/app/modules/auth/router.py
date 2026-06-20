"""Auth API endpoints: login, register, me, and self-service API keys."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.dependencies import get_current_active_user, get_optional_user
from app.modules.auth.models import ApiKey, User
from app.core.identity import Identity
from app.modules.auth.providers import AuthenticationError
from app.modules.auth.providers.local import LocalAuthProvider
from app.modules.auth.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyListItem,
    ApiKeyListResponse,
    ChangePasswordRequest,
    ConfigResponse,
    DownloadTokenResponse,
    PermissionsResponse,
    RefreshRequest,
    RegisterResponse,
    ResendVerificationRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
    VerifyEmailRequest,
)
from app.modules.auth.service import AuthService
from app.core.config import settings
from app.core.dependencies import get_client_ip, get_db
from app.core.persistent_config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    DEMO_MODE,
    EMAIL_VERIFICATION_REQUIRED,
    LANDING_FIRST,
    REFRESH_TOKEN_EXPIRE_DAYS,
    REGISTRATION_ENABLED,
    get_cached_global_rate_limit,
    get_cached_login_rate_limit,
)
from app.standards.ogc.errors import ERROR_RESPONSES_AUTH

router = APIRouter(prefix="/auth", tags=["Auth"], responses=ERROR_RESPONSES_AUTH)


def _global_rate_limit(_request: Request | None = None) -> str:
    return f"{get_cached_global_rate_limit()}/second"


limiter = Limiter(key_func=get_remote_address, default_limits=[_global_rate_limit])


def _login_rate_limit(_request: Request | None = None) -> str:
    return f"{get_cached_login_rate_limit()}/minute"


# SP-11 (v1009.1) superseded by ROUTE-01 (Phase 1092): both slash and
# no-slash variants register the same handler directly. Canonical
# OpenAPI-published form is /login; /login/ is a hidden alias for callers
# that send it. Mirrors Phase 280 dual-shape pattern in
# catalog/maps/router.py. SP-11's original closure (no-trailing-slash-only
# registration to prevent FastAPI's 307 from stripping the POST body for
# OAuth2 form callers) is now structurally impossible because
# redirect_slashes=False at the app level (see api/main.py). Keep
# ``SP-11`` as the grep-anchor prefix so future maintainers searching the
# repo for that audit ID land on this load-bearing context rather than
# just hitting the in-prose mention.
@router.post("/login/", response_model=TokenResponse, include_in_schema=False)
@router.post("/login", response_model=TokenResponse)
@limiter.limit(_login_rate_limit)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate with username and password, receive a JWT token."""
    provider = LocalAuthProvider(db)
    try:
        identity = await provider.authenticate(
            username=form_data.username, password=form_data.password
        )
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check user status before issuing token
    result = await db.execute(select(User).where(User.id == identity.user_id))
    user = result.scalar_one_or_none()
    if user is not None:
        if user.status == "pending":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is awaiting approval",
            )
        if user.status != "active" or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account not active",
            )

    # Record login timestamp
    user.last_login_at = func.now()

    # Read token lifetimes from PersistentConfig (hot-reloadable)
    expire_minutes = await ACCESS_TOKEN_EXPIRE_MINUTES.get(db)
    expire_days = await REFRESH_TOKEN_EXPIRE_DAYS.get(db)

    service = AuthService(db)
    token = await service.create_access_token(identity, expire_minutes=expire_minutes)
    refresh_token = service.create_refresh_token(user.id, expire_days=expire_days)
    await db.commit()
    return TokenResponse(
        access_token=token,
        refresh_token=refresh_token,
        expires_in=expire_minutes * 60,
    )


# ROUTE-01 (Phase 1092): dual-shape decorator — both trailing-slash and
# no-trailing-slash variants register against the same handler. The slash
# form stays canonical (already published in OpenAPI); the no-slash form
# is a hidden alias closing the 404 regression introduced by
# redirect_slashes=False (see api/main.py).
@router.post("/refresh", response_model=TokenResponse, include_in_schema=False)
@router.post("/refresh/", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh(
    request: Request,
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a valid refresh token for a new access + refresh token pair."""
    # Read token lifetimes from PersistentConfig (hot-reloadable)
    expire_minutes = await ACCESS_TOKEN_EXPIRE_MINUTES.get(db)
    expire_days = await REFRESH_TOKEN_EXPIRE_DAYS.get(db)

    service = AuthService(db)
    try:
        access_token, refresh_token = await service.rotate_refresh_token(
            body.refresh_token,
            expire_minutes=expire_minutes,
            expire_days=expire_days,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expire_minutes * 60,
    )


# ROUTE-01 (Phase 1092): dual-shape decorator — see /refresh above.
@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/register/", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED
)
@limiter.limit("5/minute")
async def register(
    request: Request,
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """Register a new user. Account requires admin approval before login."""
    # CLOUD-03 / T-1211-22: when the cloud overlay is active, the ONLY valid
    # signup path is the tenant-scoped POST /cloud/signup/register.  A global,
    # un-tenant-scoped self-signup would bypass tenant isolation and create a
    # user without a tenant_id — a privilege-escalation hole in multi_tenant.
    # This gate fires BEFORE REGISTRATION_ENABLED so that community/enterprise
    # deployments (where cloud is ABSENT) remain byte-identical.
    # Lazy import — matching the established LAZY pattern (preserved per D-17).
    from app.platform.extensions import has_extension  # LAZY — preserved per D-17

    if has_extension("cloud"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Global self-registration is disabled in cloud mode. "
                "Use POST /cloud/signup/register to create a tenant account."
            ),
        )

    reg_enabled = await REGISTRATION_ENABLED.get(db)
    if not reg_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is disabled",
        )

    # Phase 279 ADMIN-05 (L-02): emit user.register audit event for funnel
    # visibility (how many users register and from which IP). Lazy import
    # follows the established LAZY pattern (preserved per D-17) used by the
    # other audit-emitting routes in this file.
    from app.modules.audit.service import (
        AuditEvent,
        audit_emit,
    )  # LAZY — preserved per D-17

    # Phase 1230 EVENT-01: admin signup notification. Lazy import per D-17;
    # emit is placed AFTER db.commit() and ONLY in the non-collision branch so
    # (a) a notification failure cannot roll back the user row, and (b) the
    # collision path stays byte-identical regardless of toggle state (SEC-012 /
    # T-1230-05 enumeration-safety).
    from app.platform.notifications.events import (
        build_event_notification,
        emit_event_safe,
    )  # LAZY — preserved per D-17

    service = AuthService(db)
    # SEC-012: on a username/email collision the service raises ValueError and
    # does NOT create a duplicate row (register_user flushes only on success).
    # We silently swallow the collision and return the SAME pending-approval
    # response a genuine new registration returns — this prevents username/email
    # enumeration via distinguishable error codes or messages.
    collision = False
    new_user_id: uuid.UUID | None = None
    try:
        new_user_id = await service.register_user(
            username=body.username,
            password=body.password,
            email=body.email,
        )
    except ValueError:
        collision = True

    if not collision:
        # Phase 279 ADMIN-05 (L-02): the registrant is the actor (no acting admin
        # exists yet). resource_id == user_id == the new pending user. ip_address
        # is captured for funnel + abuse-detection visibility.
        ip = get_client_ip(request)
        await audit_emit(
            db,
            AuditEvent(
                user_id=new_user_id,
                action="user.register",
                resource_type="user",
                resource_id=new_user_id,
                details={"username": body.username, "email": body.email},
                ip_address=ip,
            ),
        )
        await db.commit()
        # Phase 1230 EVENT-01: notify admin of new signup AFTER commit so a
        # notification error can never roll back the user row (T-1230-07).
        # emit_event_safe is itself fail-safe (swallows all errors).
        # body.username / body.email are already audit-logged above (non-secret).
        _username = body.username
        _email = body.email or ""
        await emit_event_safe(
            event_key="signup",
            build=lambda: build_event_notification(
                "signup",
                subject=f"New signup: {_username}",
                body=f"A new user signed up.\n\nUsername: {_username}\nEmail: {_email}",
                extra={"username": _username, "email": _email},
            ),
        )

        # SIGNUP-03 (Phase 1231): When email verification is required AND the
        # registrant provided an email AND SMTP is configured, issue a
        # verification token and email it.
        # Fires only when ALL of:
        #   1. This was a genuine non-collision registration (new_user_id is set), AND
        #   2. EMAIL_VERIFICATION_REQUIRED is True, AND
        #   3. body.email is provided (without an address we can't verify;
        #      fall back to admin-approval so no-email registrations remain valid
        #      for deployments that don't require email — SIGNUP-06 backward compat), AND
        #   4. SMTP is configured (smtp_host is set); if not configured, fall back
        #      to admin-approval rather than failing with 502 for non-SMTP setups.
        # The signup-OFF path (REGISTRATION_ENABLED=False) never reaches here,
        # so this block cannot affect the OFF-path byte-identical contract (SIGNUP-06).
        verification_required = await EMAIL_VERIFICATION_REQUIRED.get(db)
        smtp_configured = bool(settings.smtp_host)
        if verification_required and body.email and smtp_configured:
            # Issue the verification token; commit it to the DB so the subsequent
            # send attempt can reference the persisted token row even if the SMTP
            # call raises.
            from app.modules.auth.verification import (
                issue_verification_token,
            )  # LAZY — per D-17

            raw_token = await issue_verification_token(db, new_user_id)  # type: ignore[arg-type]
            await db.commit()

            # Send the verification email. If send_email raises a SMTP/OSError,
            # map it to a clear HTTP 502 — never expose the exception repr (which
            # may include the SMTP password), only the exception type name
            # (mirrors env_sink's secret-free aggregation, T-1231-07).
            import smtplib  # LAZY — per D-17

            from app.modules.auth.verification_email import (
                send_verification_email,
            )  # LAZY — per D-17

            try:
                await send_verification_email(
                    db, to_email=body.email, raw_token=raw_token
                )
            except (smtplib.SMTPException, OSError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        f"Could not send the verification email "
                        f"({type(exc).__name__}); "
                        "please check the mail server configuration and try again."
                    ),
                ) from None

            return RegisterResponse(
                message=(
                    "Registration submitted. "
                    "Please check your email to verify your address and activate your account."
                )
            )

    # Default: admin-approval path (verification off, no email provided, or collision swallow).
    return RegisterResponse(
        message="Registration submitted. Your account is awaiting admin approval."
    )


# ---------------------------------------------------------------------------
# Email verification endpoints (Phase 1231 SIGNUP-03/05)
# ---------------------------------------------------------------------------


# ROUTE-01 (Phase 1092): dual-shape decorator — see /refresh above.
@router.post(
    "/verify-email",
    response_model=RegisterResponse,
    include_in_schema=False,
)
@router.post("/verify-email/", response_model=RegisterResponse)
@limiter.limit("10/minute")
async def verify_email(
    request: Request,
    body: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """Redeem a verification token to activate the account.

    SIGNUP-03: a valid single-use expiring token flips email_verified=True,
    is_active=True, and status="active" so the user can log in via the
    existing auth gate in dependencies.py.

    Expired, unknown, and already-consumed tokens all return the same
    "Invalid or expired" error (enumeration-safe, SIGNUP-05 / T-1231-06).
    """
    from app.modules.audit.service import (
        AuditEvent,
        audit_emit,
    )  # LAZY — per D-17
    from app.modules.auth.verification import (
        redeem_verification_token,
    )  # LAZY — per D-17
    from sqlalchemy import update  # LAZY — per D-17

    user_id = await redeem_verification_token(db, body.token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification link. Please request a new one.",
        )

    # Activate the account: flip is_active + status so the auth gate in
    # dependencies.py (which checks is_active AND status == 'active') lets
    # the user through.  redeem_verification_token already flipped email_verified.
    from app.modules.auth.models import User  # LAZY — per D-17

    await db.execute(
        update(User).where(User.id == user_id).values(is_active=True, status="active")
    )

    await audit_emit(
        db,
        AuditEvent(
            user_id=user_id,
            action="user.verify_email",
            resource_type="user",
            resource_id=user_id,
            details={"method": "email_link"},
            ip_address=get_client_ip(request),
        ),
    )
    await db.commit()
    return RegisterResponse(message="Email verified successfully. You can now log in.")


# ROUTE-01 (Phase 1092): dual-shape decorator — see /refresh above.
@router.post(
    "/resend-verification",
    response_model=RegisterResponse,
    include_in_schema=False,
)
@router.post("/resend-verification/", response_model=RegisterResponse)
@limiter.limit("5/minute")
async def resend_verification(
    request: Request,
    body: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """Re-issue and re-send a verification email.

    SIGNUP-05 / T-1231-05 (enumeration-safe): ALWAYS returns the same 200 body
    regardless of whether the email exists, is unknown, or is already verified.
    Send errors are logged server-side only and never branch the HTTP response.
    """
    # Generic response returned in ALL cases — known, unknown, already-verified,
    # send-failure — to prevent email-existence enumeration.
    _GENERIC_RESPONSE = RegisterResponse(
        message=(
            "If an unverified account with that email exists, "
            "a new verification link has been sent."
        )
    )

    from app.modules.auth.verification import (
        issue_verification_token,
    )  # LAZY — per D-17
    from app.modules.auth.verification_email import (
        send_verification_email,
    )  # LAZY — per D-17
    from sqlalchemy import select  # LAZY — per D-17

    from app.modules.auth.models import User  # LAZY — per D-17

    # Look up an unverified user by email (case-insensitive).
    result = await db.execute(
        select(User).where(
            User.email == body.email,
            User.email_verified.is_(False),
        )
    )
    user = result.scalar_one_or_none()

    if user is not None:
        # Issue a fresh token and attempt to send. Swallow send errors
        # server-side so the response stays identical to the unknown-email path
        # (enumeration-safe). Still log at WARNING so operators can diagnose
        # SMTP misconfiguration without surfacing it to the client.
        import smtplib  # LAZY — per D-17
        import structlog  # LAZY — per D-17

        _log = structlog.stdlib.get_logger(__name__)

        try:
            raw_token = await issue_verification_token(db, user.id)
            await db.commit()
            await send_verification_email(db, to_email=body.email, raw_token=raw_token)
        except (smtplib.SMTPException, OSError) as exc:
            # Log the error type only — never the SMTP password or full repr.
            _log.warning(
                "resend_verification.send_failed",
                error_type=type(exc).__name__,
                user_id=str(user.id),
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "resend_verification.unexpected_error",
                error_type=type(exc).__name__,
                user_id=str(user.id),
            )

    return _GENERIC_RESPONSE


# ROUTE-01 (Phase 1092): dual-shape decorator — see /refresh above.
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
@router.post("/logout/", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke all refresh tokens and bump token_version for the current user.

    SEC-S15 (Phase 1062-01): revoke_all_tokens bumps User.token_version so the
    access JWT used for this logout call (and any other outstanding access JWTs)
    are rejected on the next authenticated request — closing the
    "logout doesn't invalidate the access JWT" gap.
    """
    service = AuthService(db)
    await service.revoke_all_tokens(current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/download-token/{dataset_id}", response_model=DownloadTokenResponse)
@limiter.limit("60/minute")
async def create_download_token_endpoint(
    request: Request,
    dataset_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> DownloadTokenResponse:
    """Mint a short-lived download-scoped JWT for a single dataset.

    IA-P0-01 / SEC-04: the existing COG download URL path requires a
    ``typ='download'`` JWT on the ``?token=`` query parameter — session JWTs
    are rejected. This endpoint issues that token after verifying the caller
    has read access to the dataset.

    Anonymous callers are allowed for public datasets. The returned token has
    ``typ='download'``, ``scope='dataset:{dataset_id}'``, and a TTL of 120s.
    """
    from datetime import UTC, datetime, timedelta  # LAZY — stdlib, per D-17 ordering

    import jwt as _jwt  # LAZY — per D-17

    from app.modules.catalog.authorization import (  # LAZY — per D-17
        check_dataset_access_or_anonymous,
    )
    from app.modules.catalog.datasets.domain.service import (  # LAZY — per D-17
        get_dataset,
    )

    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )

    # check_dataset_access_or_anonymous raises 404 if the caller cannot read
    # the dataset (private dataset, no access). Allows anonymous on public datasets.
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    # Issue the download-scoped token.
    # - Authenticated user: use AuthService.create_download_token (includes sub claim).
    # - Anonymous user on public dataset: issue a token without sub. The COG download
    #   endpoint's _resolve_download_user returns None for sub-less tokens, and
    #   download_cog branches on user-None to enforce public visibility + emit the
    #   audit row with user_id=NULL. (KNOWN-01 closure in Phase 1071; v1015
    #   Phase 1065 left this consumer gap behind — the consumer used to reject
    #   any sub-less token with 401, breaking the end-to-end anonymous flow.)
    if user is not None:
        from app.modules.auth.providers import AuthenticatedIdentity  # LAZY — per D-17

        identity = AuthenticatedIdentity(
            user_id=user.id,
            username=user.username,  # type: ignore[attr-defined]
        )
        service = AuthService(db)
        token = service.create_download_token(identity, dataset_id)
    else:
        # Anonymous download token for public dataset — no sub claim.
        now = datetime.now(UTC)
        payload = {
            "typ": "download",
            "scope": f"dataset:{dataset_id}",
            "exp": now + timedelta(seconds=120),
            "iat": now,
        }
        token = _jwt.encode(
            payload,
            settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )

    return DownloadTokenResponse(token=token, expires_in=120)


# ROUTE-01 (Phase 1092): dual-shape decorator — see /refresh above.
@router.get("/config", response_model=ConfigResponse, include_in_schema=False)
@router.get("/config/", response_model=ConfigResponse)
async def config(
    db: AsyncSession = Depends(get_db),
) -> ConfigResponse:
    """Return public auth configuration (no authentication required)."""
    from app.platform.extensions import get_auth_extension

    reg_enabled = await REGISTRATION_ENABLED.get(db)
    landing_first = await LANDING_FIRST.get(db)
    demo_mode = await DEMO_MODE.get(db)
    email_verification_required = await EMAIL_VERIFICATION_REQUIRED.get(db)
    return ConfigResponse(
        registration_enabled=reg_enabled,
        allow_signup=reg_enabled,
        email_verification_required=email_verification_required,
        auth_methods=list(get_auth_extension().get_auth_methods()),
        landing_first=landing_first,
        demo_mode=demo_mode,
    )


# ROUTE-01 (Phase 1092): dual-shape decorator — see /refresh above.
@router.get("/me", response_model=UserResponse, include_in_schema=False)
@router.get("/me/", response_model=UserResponse)
async def me(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Return the currently authenticated user's profile and roles."""
    service = AuthService(db)
    roles = await service.get_user_roles(current_user.id)
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        is_active=current_user.is_active,
        status=current_user.status,
        last_login_at=current_user.last_login_at,
        created_at=current_user.created_at,
        roles=sorted(roles),
    )


# ROUTE-01 (Phase 1092): dual-shape decorator — see /refresh above.
@router.get(
    "/me/permissions",
    response_model=PermissionsResponse,
    include_in_schema=False,
)
@router.get("/me/permissions/", response_model=PermissionsResponse)
async def me_permissions(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PermissionsResponse:
    """Return the effective permissions for the currently authenticated user."""
    from app.modules.auth.permissions import ALL_CAPABILITIES, get_effective_permissions

    service = AuthService(db)
    user_roles = await service.get_user_roles(current_user.id)
    matrix = await get_effective_permissions(db)

    # Merge: user has capability if ANY of their roles grants it
    effective: dict[str, bool] = {}
    for cap in ALL_CAPABILITIES:
        effective[cap] = any(
            matrix.get(role, {}).get(cap, False) for role in user_roles
        )

    return PermissionsResponse(permissions=effective)


# ---------------------------------------------------------------------------
# Self-service API key management
# ---------------------------------------------------------------------------


# ROUTE-01 (Phase 1092): dual-shape decorator — see /refresh above.
@router.get("/api-keys", response_model=ApiKeyListResponse, include_in_schema=False)
@router.get("/api-keys/", response_model=ApiKeyListResponse)
async def list_my_api_keys(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyListResponse:
    """List the current user's API keys."""
    base_stmt = select(ApiKey).where(ApiKey.user_id == current_user.id)
    total = (
        await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    ).scalar_one()
    result = await db.execute(base_stmt.offset(skip).limit(limit))
    keys = result.scalars().all()
    return ApiKeyListResponse(
        items=[
            ApiKeyListItem(
                id=k.id,
                name=k.name,
                is_active=k.is_active,
                created_at=k.created_at,
                last_used_at=k.last_used_at,
            )
            for k in keys
        ],
        total=total,
    )


# ROUTE-01 (Phase 1092): dual-shape decorator — see /refresh above.
@router.post(
    "/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/api-keys/",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_my_api_key(
    body: ApiKeyCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreateResponse:
    """Create an API key for the current user.

    The raw key is returned only in this response and cannot be retrieved again.
    """
    from app.modules.audit.service import (
        AuditEvent,
        audit_emit,
    )  # LAZY — preserved per D-17
    from app.modules.auth.service import create_api_key_for_user

    api_key, raw_key = await create_api_key_for_user(db, current_user.id, body.name)

    ip = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="api_key.create",
            resource_type="api_key",
            resource_id=api_key.id,
            details={"name": body.name},
            ip_address=ip,
        ),
    )
    await db.commit()

    return ApiKeyCreateResponse(
        id=api_key.id,
        key=raw_key,
        name=api_key.name,
        created_at=api_key.created_at,
    )


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_api_key(
    key_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke (soft-delete) one of the current user's API keys."""
    from app.modules.audit.service import (
        AuditEvent,
        audit_emit,
    )  # LAZY — preserved per D-17

    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == current_user.id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
    api_key.is_active = False
    ip = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="api_key.revoke",
            resource_type="api_key",
            resource_id=key_id,
            details={"name": api_key.name},
            ip_address=ip,
        ),
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Password change
# ---------------------------------------------------------------------------


# ROUTE-01 (Phase 1092): dual-shape decorator — see /refresh above.
@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
@router.post("/change-password/", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Change the current user's password (requires current password)."""
    from app.modules.audit.service import (
        AuditEvent,
        audit_emit,
    )  # LAZY — preserved per D-17
    from app.modules.auth.providers.local import hash_password, verify_password

    if current_user.auth_provider != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password change only available for local accounts",
        )
    if not current_user.password_hash or not verify_password(
        body.current_password, current_user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.password_hash = hash_password(body.new_password)

    # SEC-S15 (Phase 1062-01): bump token_version so all outstanding access JWTs
    # for this user are invalidated on their next request. Password rotation
    # should force re-auth on every other device.
    #
    # commit=False: fold the token revocation into the same transaction as the
    # password hash mutation and audit row so all three land atomically. A crash
    # between commits would otherwise leave the user with bumped token_version
    # (all tokens rejected) but the new password not recorded, locking them out.
    service = AuthService(db)
    await service.revoke_all_tokens(current_user.id, commit=False)

    ip = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="user.change_password",
            resource_type="user",
            resource_id=current_user.id,
            ip_address=ip,
        ),
    )
    # Single commit: password_hash mutation + token revocation + audit row are
    # all in the same transaction. Either all succeed or none do.
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
