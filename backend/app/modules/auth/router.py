"""Auth API endpoints: login, register, me, and self-service API keys."""

import secrets
import uuid

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.security import OAuth2PasswordRequestForm
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.cookies import (
    AUTH_MODE_HEADER,
    COOKIE_AUTH_MODE,
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    REFRESH_COOKIE_NAME,
    api_path_is_cookie_scoped,
    clear_browser_session,
    enforce_csrf,
    issue_browser_session,
    read_refresh_cookie,
    wants_cookie_auth,
)
from app.modules.auth.dependencies import (
    get_current_active_user,
    get_optional_user,
    get_optional_user_fail_open,
    require_session_credential,
)
from app.modules.auth.login_throttle import (
    account_binding,
    device_cookie_fits,
    issue_device_cookie,
    redeem_trust_token,
    reserve_login_attempt,
    reserve_password_change_attempt,
    settle_login_failure,
    settle_login_success,
    settle_password_change_failure,
)
from app.modules.auth.models import ApiKey, Role, User, UserRole
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
from app.modules.quota.schemas import UserQuotaUsage
from app.modules.quota.service import get_user_quota_usage
from app.core.config import settings
from app.core.dependencies import get_client_ip, get_db
from app.core.public_urls import PublicUrlNotConfiguredError, get_public_api_url
from app.core.tenancy import is_multi_tenant
from app.core.persistent_config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALLOWED_EMAIL_DOMAINS,
    BANNER_COLOR,
    BANNER_ENABLED,
    BANNER_TEXT,
    EMAIL_VERIFICATION_REQUIRED,
    LANDING_FIRST,
    PASSWORD_LOGIN_ENABLED,
    REFRESH_TOKEN_EXPIRE_DAYS,
    REGISTRATION_DEFAULT_ROLE,
    REGISTRATION_ENABLED,
    get_cached_login_rate_limit,
)
from app.modules.auth.domain_policy import enforce_email_domain_gate
from app.platform.ratelimit import limiter
from app.standards.ogc.errors import (
    BAD_GATEWAY_RESPONSE,
    ERROR_RESPONSES_AUTH,
    PROBLEM_RESPONSE,
)

router = APIRouter(prefix="/auth", tags=["Auth"], responses=ERROR_RESPONSES_AUTH)


def _login_rate_limit(_request: Request | None = None) -> str:
    return f"{get_cached_login_rate_limit()}/minute"


# The browser cookie flow is negotiated via two request headers, declared here
# so generated SDKs/docs can express them. The parameters are DECLARED, not
# consumed: enforcement stays in cookies.py, which reads the headers off the
# Request directly. Each ``alias`` IS the cookies.py constant, and
# tests/test_api_contract_openapi.py derives the expected header set from the
# helper calls each handler actually makes.
#
# Neither header has a default/pattern/required flag, so a caller sending
# neither gets the token-in-body contract byte for byte.
_AUTH_MODE_PARAM_DESCRIPTION = (
    f"Browser session-transport negotiation. Send `{COOKIE_AUTH_MODE}` to carry "
    f"the refresh token in an httpOnly `{REFRESH_COOKIE_NAME}` cookie, paired "
    f"with a script-readable `{CSRF_COOKIE_NAME}` cookie, and receive a null "
    "`refresh_token` in the response body. When the header is absent (the "
    "default) the refresh token is returned in the response body, which is the "
    "contract every non-browser caller uses."
)

_CSRF_PARAM_DESCRIPTION = (
    "Double-submit CSRF token, enforced only when the refresh cookie is what "
    f"authenticates the call. Echo the value of the `{CSRF_COOKIE_NAME}` cookie "
    "issued alongside the refresh cookie. Callers presenting a refresh token in "
    "the request body do not send it."
)


# /login is canonical (in OpenAPI) and /login/ a hidden alias; both register
# because api/main.py sets redirect_slashes=False. Elsewhere in this router the
# trailing-slash form is canonical and the no-slash form the hidden alias.
@router.post("/login/", response_model=TokenResponse, include_in_schema=False)
@router.post("/login", response_model=TokenResponse)
@limiter.limit(_login_rate_limit)
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
    # Declared for the contract, read via wants_cookie_auth below.
    auth_mode: str | None = Header(
        default=None,
        alias=AUTH_MODE_HEADER,
        description=_AUTH_MODE_PARAM_DESCRIPTION,
    ),
) -> TokenResponse:
    """Authenticate with username and password, receive a JWT token.

    GH-1302: a caller sending ``X-GeoLens-Auth-Mode: cookie`` receives the
    refresh token as an httpOnly cookie and a null ``refresh_token`` in the
    body. Without that header the response is unchanged, which is what keeps
    the CLI, the generated SDKs, Postman, and CI logins working.
    """
    from app.modules.audit.service import (
        AuditEvent,
        audit_emit,
    )

    # OAuth2PasswordRequestForm applies no length limit to username, so an
    # unauthenticated caller could otherwise persist an unbounded string in
    # JSONB on every failed attempt (storage exhaustion). Bound it to
    # User.username's column width (String(150)) before it reaches an audit
    # row.
    attempted_username = form_data.username[:150]

    async def _audit_login_failure(reason: str, *, user_id: uuid.UUID | None) -> None:
        """Audit every denial path, not just bad credentials: pending or
        deactivated accounts, disallowed email domain, and password login
        disabled. Never includes the submitted password."""
        await audit_emit(
            db,
            AuditEvent(
                user_id=user_id,
                action="user.login.failure",
                resource_type="user",
                details={"username": attempted_username, "reason": reason},
                ip_address=get_client_ip(request),
            ),
        )
        await db.commit()

    throttle = await reserve_login_attempt(db, request, form_data.username)
    provider = LocalAuthProvider(db)
    try:
        identity = await provider.authenticate(
            username=form_data.username, password=form_data.password
        )
    except AuthenticationError:
        # user_id stays None: LocalAuthProvider deliberately doesn't disclose
        # whether the username exists (both branches raise identically, a
        # timing-attack guard), and the audit row must not either.
        await settle_login_failure(db, request, throttle)
        await _audit_login_failure("invalid_credentials", user_id=None)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Denials past this point follow a correct password, so they don't count.
    await settle_login_success(db, throttle)

    # Check user status before issuing token
    result = await db.execute(select(User).where(User.id == identity.user_id))
    user = result.scalar_one_or_none()
    if user is not None:
        if user.status == "pending":
            await _audit_login_failure("pending_approval", user_id=user.id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is awaiting approval",
            )
        if user.status != "active" or not user.is_active:
            await _audit_login_failure("account_not_active", user_id=user.id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account not active",
            )

    # Enforce allowed_email_domains on password login. Null-email skip,
    # get_uncached cache-bypass, and the manage_settings break-glass all live
    # in the shared gate.
    if user is not None:
        try:
            await enforce_email_domain_gate(db, user.email, break_glass_user=user)
        except HTTPException:
            await _audit_login_failure("email_domain_not_allowed", user_id=user.id)
            raise

    # When password_login_enabled is False, reject password login for
    # non-admins (manage_settings break-glass, same as the domain gate).
    # Cache-bypass: a stale `true` during a disable's invalidate->commit window
    # would let non-admins keep logging in for up to 30s.
    if user is not None and not await PASSWORD_LOGIN_ENABLED.get_uncached(db):
        from app.modules.auth.permissions import (
            MANAGE_SETTINGS,
            user_has_capability,
        )

        has_break_glass = await user_has_capability(db, user, MANAGE_SETTINGS)
        if not has_break_glass:
            await _audit_login_failure("password_login_disabled", user_id=user.id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Password login is disabled; sign in with your SSO provider",
            )

    user.last_login_at = func.now()

    # Read token lifetimes from PersistentConfig (hot-reloadable)
    expire_minutes = await ACCESS_TOKEN_EXPIRE_MINUTES.get(db)
    expire_days = await REFRESH_TOKEN_EXPIRE_DAYS.get(db)

    service = AuthService(db)
    family_id = uuid.uuid4()
    token = await service.create_access_token(
        identity, expire_minutes=expire_minutes, family_id=family_id
    )
    refresh_token = service.create_refresh_token(
        user.id, expire_days=expire_days, family_id=family_id
    )

    # Password-login success audit row, mirroring oauth.login.success.
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="user.login.success",
            resource_type="user",
            ip_address=get_client_ip(request),
        ),
    )
    await db.commit()

    if wants_cookie_auth(request):
        issue_browser_session(response, request, refresh_token, expire_days)
        issue_device_cookie(
            response,
            request,
            throttle.account_key,
            account_binding(user.id, user.key_epoch),
        )
        return TokenResponse(
            access_token=token,
            refresh_token=None,
            expires_in=expire_minutes * 60,
        )
    return TokenResponse(
        access_token=token,
        refresh_token=refresh_token,
        expires_in=expire_minutes * 60,
    )


def _trust_refusal(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


@router.post(
    "/login/device-trust",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
@limiter.limit("10/minute")
async def trust_login_device(
    request: Request,
    token: str = Query(default="", max_length=128),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Remember this browser for one account, from a link minted on the host.

    The link is single use, and grants only what a past sign-in would: this
    browser may try a password while the account refuses unknown clients.
    The SPA's own page posts here, so the request is same-site and, under
    the device cookies' path, carries them for the cap check. The deletion
    commits last, so any refusal or failure leaves the link usable.
    """
    # The cookie-mode header proves the app's own script sent this: a
    # cross-site form can't set it, and would arrive without the device
    # cookies the cap check needs.
    if not wants_cookie_auth(request):
        raise _trust_refusal(
            status.HTTP_400_BAD_REQUEST,
            "device_trust_unavailable",
            "Open the link in the browser to remember.",
        )
    try:
        api_url = await get_public_api_url(db, request=request, for_external_use=True)
    except PublicUrlNotConfiguredError:
        api_url = None
    if api_url is not None and not api_path_is_cookie_scoped(request, api_url):
        raise _trust_refusal(
            status.HTTP_409_CONFLICT,
            "device_trust_unavailable",
            "This deployment's API address can't hold a remembered browser.",
        )
    redeemed = await redeem_trust_token(db, token)
    if redeemed is None:
        await db.commit()
        raise _trust_refusal(
            status.HTTP_404_NOT_FOUND,
            "device_trust_link_invalid",
            "This link is invalid, expired or already used.",
        )
    if not device_cookie_fits(request, redeemed[0]):
        await db.rollback()
        raise _trust_refusal(
            status.HTTP_409_CONFLICT,
            "device_trust_browser_full",
            "This browser already remembers as many accounts as it can.",
        )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    issue_device_cookie(response, request, *redeemed)
    await db.commit()
    return response


# Every page load in the SPA spends one refresh, so many users behind one
# address need far more than one session's budget. This bounds that total, and
# runs before the session lookup so a flood of made-up tokens can't turn into
# unbounded database reads.
@limiter.limit("300/minute")
async def _limit_refresh_address(request: Request) -> None:
    # slowapi skips later checks once a request is marked; the route's
    # per-session limit still has to run.
    request.state._rate_limiting_complete = False


async def _resolve_refresh_session(
    request: Request,
    body: RefreshRequest | None = None,
    _address_limit: None = Depends(_limit_refresh_address),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Stash the presented token's session id for ``_refresh_session_key``.

    Dependencies resolve before the route's slowapi wrapper checks its limit.
    Only a token the database accepts yields an id, so a forged or stale
    credential stays on the caller's address bucket instead of opening a new
    one.
    """
    token = read_refresh_cookie(request) if wants_cookie_auth(request) else None
    token = token or (body.refresh_token if body is not None else None)
    if token:
        session_id = await AuthService(db).get_refresh_session_id(token)
        request.state.refresh_session_id = session_id


def _refresh_session_key(request: Request) -> str:
    session_id = getattr(request.state, "refresh_session_id", None)
    if session_id is None:
        return get_remote_address(request)
    return f"refresh-session:{session_id}"


@router.post("/refresh", response_model=TokenResponse, include_in_schema=False)
@router.post("/refresh/", response_model=TokenResponse)
@limiter.limit("30/minute", key_func=_refresh_session_key)
async def refresh(
    request: Request,
    response: Response,
    body: RefreshRequest | None = None,
    _session: None = Depends(_resolve_refresh_session),
    db: AsyncSession = Depends(get_db),
    # Declared for the contract, read via wants_cookie_auth /
    # enforce_csrf below.
    auth_mode: str | None = Header(
        default=None,
        alias=AUTH_MODE_HEADER,
        description=_AUTH_MODE_PARAM_DESCRIPTION,
    ),
    csrf_token: str | None = Header(
        default=None,
        alias=CSRF_HEADER_NAME,
        description=_CSRF_PARAM_DESCRIPTION,
    ),
) -> TokenResponse:
    """Exchange a valid refresh token for a new access + refresh token pair.

    Multi-tenant clients must call this endpoint on their tenant host. Refresh
    tokens are opaque and carry no bearer ``tid`` claim, so tenant middleware
    binds the database transaction from that same-origin host before the user
    row is resolved and the next tenant-bound access token is minted.

    GH-1302: with ``X-GeoLens-Auth-Mode: cookie`` the presented token is read
    from the httpOnly cookie (falling back to the body once, so a session
    established before the cookie flow shipped migrates on its next refresh
    instead of being logged out), the double-submit CSRF token is enforced, and
    the rotated token goes back out as a cookie with a null body
    ``refresh_token``. Without the header this endpoint behaves exactly as
    before.
    """
    cookie_mode = wants_cookie_auth(request)
    body_token = body.refresh_token if body is not None else None

    if cookie_mode:
        cookie_token = read_refresh_cookie(request)
        # CSRF is enforced only when the cookie is what authenticates the call.
        # A migrating caller presenting a body token holds a bearer-equivalent
        # secret no cross-site page can read, so gating that path on a CSRF
        # cookie it does not have yet would strand every pre-upgrade session.
        if cookie_token is not None:
            enforce_csrf(request)
        presented_token = cookie_token or body_token
    else:
        presented_token = body_token

    if not presented_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Read token lifetimes from PersistentConfig (hot-reloadable)
    expire_minutes = await ACCESS_TOKEN_EXPIRE_MINUTES.get(db)
    expire_days = await REFRESH_TOKEN_EXPIRE_DAYS.get(db)

    service = AuthService(db)

    # Enforce allowed_email_domains at refresh time too, so tightening the
    # allowlist after login rejects the next refresh. Peeks at the user
    # WITHOUT revoking the token first, so a blocked user's old token stays
    # intact. Break-glass for a returning manage_settings admin, same as
    # login. PASSWORD_LOGIN_ENABLED is intentionally NOT checked here: it's a
    # login-METHOD policy and must not gate session continuation for users who
    # authenticated via SSO.
    user = await service.get_user_from_refresh_token(presented_token)
    if user is not None:
        await enforce_email_domain_gate(db, user.email, break_glass_user=user)

    try:
        access_token, refresh_token = await service.rotate_refresh_token(
            presented_token,
            expire_minutes=expire_minutes,
            expire_days=expire_days,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if cookie_mode:
        issue_browser_session(response, request, refresh_token, expire_days)
        return TokenResponse(
            access_token=access_token,
            refresh_token=None,
            expires_in=expire_minutes * 60,
        )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expire_minutes * 60,
    )


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/register/",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    responses={502: BAD_GATEWAY_RESPONSE},
)
@limiter.limit("5/minute")
async def register(
    request: Request,
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """Create a password account.

    Needs both self-registration and password login enabled; otherwise 403.
    When the allowed email domains list is set, an email address in one of
    those domains is required.

    If email verification is required, the request includes an email address
    and the server has SMTP configured, the account activates when its owner
    follows the emailed link and gets the default self-registration role.
    Otherwise it stays pending until an administrator approves it with a role.
    The response is the same whether or not the username or email was taken.
    """
    # Runtime-extension gate: a deployment with its own tenant-scoped signup
    # path must keep the global self-signup endpoint closed, so users aren't
    # created outside the deployment's isolation boundary. Fires before
    # REGISTRATION_ENABLED so the standard self-hosted path is unchanged.
    from app.platform.extensions import has_extension

    if has_extension("cloud"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-registration is disabled for this deployment.",
        )

    reg_enabled = await REGISTRATION_ENABLED.get_uncached(db)
    if not reg_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is disabled",
        )
    # A password account could never sign in; SSO sign-up still follows
    # registration_enabled alone.
    if not await PASSWORD_LOGIN_ENABLED.get_uncached(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password sign-up is disabled; sign in with a single sign-on provider",
        )

    # Enforce allowed_email_domains on self-serve signup. No principal exists
    # at signup, so no break-glass user is passed.
    await enforce_email_domain_gate(db, body.email)
    if not body.email and await ALLOWED_EMAIL_DOMAINS.get_uncached(db):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An email address in an allowed domain is required to sign up",
        )

    # user.register audit event for funnel visibility (count and IP).
    from app.modules.audit.service import (
        AuditEvent,
        audit_emit,
    )

    # Admin signup notification, emitted AFTER db.commit() and ONLY in the
    # non-collision branch, so a notification failure can't roll back the
    # user row and the collision path stays byte-identical regardless of
    # toggle state.
    from app.platform.notifications.events import (
        build_event_notification,
        emit_event_safe,
    )

    service = AuthService(db)
    # On a collision the service raises ValueError without creating a
    # duplicate row; it is swallowed and the response is the SAME one a
    # genuine registration gets, to prevent enumeration.
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

    # Outcome depends on CONFIG + submitted email only, never on whether this
    # was a genuine signup or a swallowed collision (enumeration safety).
    verification_required = await EMAIL_VERIFICATION_REQUIRED.get_uncached(db)
    smtp_configured = bool(settings.smtp_host)
    wants_email_verification = bool(
        verification_required and body.email and smtp_configured
    )

    if not collision:
        # The registrant is the actor; resource_id == user_id == the new
        # pending user.
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

        if verification_required and body.email and not smtp_configured:
            # No SMTP configured despite verification required: fall back to
            # admin-approval, but surface the mismatch rather than
            # degrading silently, so an operator can see why.
            import structlog

            structlog.stdlib.get_logger(__name__).warning(
                "register.verification_required_but_smtp_unconfigured",
                detail=(
                    "EMAIL_VERIFICATION_REQUIRED is on but smtp_host is unset; "
                    "falling back to admin-approval. Configure SMTP to enable "
                    "email-verified self-serve signup."
                ),
            )

    if wants_email_verification:
        # Send for both genuine registrations and swallowed collisions: a
        # collision gets a decoy token so delivery stays uniform and can't
        # reveal whether the username/email existed.
        if new_user_id is not None:
            from app.modules.auth.verification import (
                issue_verification_token,
            )

            raw_token = await issue_verification_token(db, new_user_id)
            await db.commit()
        else:
            raw_token = secrets.token_urlsafe(32)

        # Map an SMTP/OSError to HTTP 502; never expose the exception repr
        # (may include an SMTP password), only the exception type name.
        import smtplib

        from app.modules.auth.verification_email import (
            send_verification_email,
        )

        try:
            await send_verification_email(
                db,
                to_email=body.email,
                raw_token=raw_token,
                request=request,
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

    # IDENTICAL for a genuine new user and a swallowed collision given the
    # same (config, email), so neither path reveals account existence.
    if wants_email_verification:
        return RegisterResponse(
            message=(
                "Registration submitted. "
                "Please check your email to verify your address and activate your account."
            ),
            next_step="verify_email",
        )
    return RegisterResponse(
        message="Registration submitted. Your account is awaiting admin approval.",
        next_step="await_approval",
    )


async def _grant_registration_role(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Give a just-activated account the self-registration role unless it has one."""
    if await db.scalar(select(UserRole.role_id).where(UserRole.user_id == user_id)):
        return
    role_name = await REGISTRATION_DEFAULT_ROLE.get_uncached(db)
    role_id = await db.scalar(select(Role.id).where(Role.name == role_name))
    if role_id is not None:
        db.add(UserRole(user_id=user_id, role_id=role_id))


async def _email_link_activates(db: AsyncSession) -> bool:
    """Whether following a verification link may activate a pending sign-up.

    Only while sign-ups are open and verification is how they activate;
    otherwise a pending account waits for an administrator, whatever link
    its owner holds.
    """
    return bool(
        await EMAIL_VERIFICATION_REQUIRED.get_uncached(db)
        and await REGISTRATION_ENABLED.get_uncached(db)
    )


@router.post(
    "/verify-email",
    response_model=RegisterResponse,
    include_in_schema=False,
)
@router.post(
    "/verify-email/",
    response_model=RegisterResponse,
    responses={
        409: {**PROBLEM_RESPONSE, "description": "The account can't be activated yet"}
    },
)
@limiter.limit("10/minute")
async def verify_email(
    request: Request,
    body: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """Redeem a verification token, confirming the address.

    A valid single-use expiring token sets email_verified=True. While
    self-registration is on and requires email verification, it also
    activates a pending account with the default self-registration role.
    Otherwise a pending account stays pending and the response carries
    ``next_step="await_approval"``.

    Expired, unknown, and already-consumed tokens all return the same
    "Invalid or expired" error (enumeration-safe).
    """
    from app.modules.audit.service import (
        AuditEvent,
        audit_emit,
    )
    from app.modules.auth.verification import (
        redeem_verification_token,
    )
    from sqlalchemy import update

    user_id = await redeem_verification_token(db, body.token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification link. Please request a new one.",
        )

    from app.modules.auth.models import User

    # Flip is_active + status so the auth gate in dependencies.py lets the
    # user through (redeem_verification_token already flipped email_verified).
    # Only accounts still PENDING: an admin may have suspended the account
    # within the token's validity window, and the link must NOT undo that.
    async def activate() -> None:
        activated = await db.scalar(
            update(User)
            .where(
                User.id == user_id,
                User.status == "pending",
                User.is_active.is_(False),
            )
            .values(is_active=True, status="active", key_epoch=User.key_epoch + 1)
            .returning(User.id)
        )
        if activated is not None:
            await _grant_registration_role(db, user_id)
            await db.flush()

    from app.modules.catalog.group_access import reactivate_member_access

    if await _email_link_activates(db):
        try:
            await reactivate_member_access(db, user_id, activate)
        except HTTPException as exc:
            # The refusal names datasets; this caller is not signed in.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This account can't be activated yet. Contact an administrator.",
            ) from exc

    awaiting_approval = (
        await db.scalar(select(User.status).where(User.id == user_id))
    ) == "pending"
    await audit_emit(
        db,
        AuditEvent(
            user_id=user_id,
            action="user.verify_email",
            resource_type="user",
            resource_id=user_id,
            details={"method": "email_link", "awaiting_approval": awaiting_approval},
            ip_address=get_client_ip(request),
        ),
    )
    await db.commit()
    if awaiting_approval:
        return RegisterResponse(
            message="Email verified. Your account is awaiting admin approval.",
            next_step="await_approval",
        )
    return RegisterResponse(message="Email verified successfully. You can now log in.")


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

    Sends nothing unless self-registration is on and requires email
    verification, since only then can the link activate an account.

    Enumeration-safe: ALWAYS returns the same 200 body
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
    )
    from app.modules.auth.verification_email import (
        send_verification_email,
    )
    from sqlalchemy import select

    from app.modules.auth.models import User

    # Look up an unverified user by email (case-insensitive).
    result = await db.execute(
        select(User).where(
            func.lower(User.email) == func.lower(body.email),
            User.email_verified.is_(False),
        )
    )
    user = result.scalar_one_or_none()

    if user is not None and await _email_link_activates(db):
        # Swallow send errors so the response stays identical to the
        # unknown-email path (enumeration-safe); log at WARNING so operators
        # can diagnose SMTP misconfiguration without surfacing it to clients.
        import smtplib
        import structlog

        _log = structlog.stdlib.get_logger(__name__)

        try:
            raw_token = await issue_verification_token(db, user.id)
            await db.commit()
            await send_verification_email(
                db,
                to_email=body.email,
                raw_token=raw_token,
                request=request,
            )
        except (smtplib.SMTPException, OSError) as exc:
            # Log the error type only — never the SMTP password or full repr.
            _log.warning(
                "resend_verification.send_failed",
                error_type=type(exc).__name__,
                user_id=str(user.id),
            )
        except Exception as exc:  # broad: resend must return the generic response even if sending fails
            _log.warning(
                "resend_verification.unexpected_error",
                error_type=type(exc).__name__,
                user_id=str(user.id),
            )

    return _GENERIC_RESPONSE


@router.post(
    "/logout/session", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False
)
@router.post("/logout/session/", status_code=status.HTTP_204_NO_CONTENT)
async def logout_current_session(
    request: Request,
    body: RefreshRequest | None = None,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    csrf_token: str | None = Header(
        default=None,
        alias=CSRF_HEADER_NAME,
        description=_CSRF_PARAM_DESCRIPTION,
    ),
) -> Response:
    """Revoke only the presented session's refresh-token family.

    Other devices and API keys survive. Access JWTs remain usable until their
    normal expiry; /logout/ still immediately revokes every access and refresh
    session. A valid signed access JWT with sid, a refresh body token, or a
    refresh cookie authorizes this operation. Legacy JWTs without sid must use
    the refresh credential. Cookie authorization requires double-submit CSRF.

    Bearer/body revocation does not change cookies, allowing a captured old
    session to be discarded safely after a newer login. Cookie authorization
    clears the browser's refresh and CSRF cookies.
    """
    cookie_authorized = False
    access_token = None
    refresh_token = body.refresh_token if body is not None else None
    if authorization is not None:
        scheme, _, access_token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not access_token:
            raise HTTPException(status_code=401, detail="Invalid session credential")
    elif refresh_token is None:
        refresh_token = read_refresh_cookie(request)
        if refresh_token is not None:
            enforce_csrf(request)
            cookie_authorized = True
    try:
        await AuthService(db).revoke_session(
            access_token=access_token,
            refresh_token=refresh_token,
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid session credential")
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if cookie_authorized:
        clear_browser_session(response, request)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
@router.post("/logout/", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    # The ONE fail-open exception. Every other anonymous-capable
    # handler 401s a supplied-but-unresolvable credential; logout must not,
    # since the credential being discarded is often the one that expired.
    # See get_optional_user_fail_open's docstring and FAIL_OPEN_ALLOWLIST in
    # tests/test_optional_auth_failure_mode_1518.py. 401 still fires below
    # when NOTHING presented resolves.
    identity: Identity | None = Depends(get_optional_user_fail_open),
    body: RefreshRequest | None = None,
    db: AsyncSession = Depends(get_db),
    # Declared for the contract, read via enforce_csrf below. No
    # auth-mode parameter here: unlike login/refresh, logout never calls
    # wants_cookie_auth — it accepts the refresh cookie and clears both
    # cookies unconditionally.
    csrf_token: str | None = Header(
        default=None,
        alias=CSRF_HEADER_NAME,
        description=_CSRF_PARAM_DESCRIPTION,
    ),
) -> Response:
    """Revoke all refresh tokens and bump token_version for the current user.

    Logout invalidates the access JWT used for this call and all other active
    browser sessions.

    API keys remain valid because they are independent of browser sessions.
    Password and role changes still revoke them.

    A refresh cookie can authenticate logout after the access token expires.
    Cookie-authenticated requests require CSRF validation.
    """
    from app.modules.audit.service import (
        AuditEvent,
        audit_emit,
    )

    service = AuthService(db)
    user_id: uuid.UUID | None = identity.id if identity is not None else None
    if user_id is None:
        # Fall back to a presented refresh token when the access token has
        # aged out, so logout doesn't 401 while a multi-day refresh credential
        # stays valid. Two transports, cookie (same-origin) and body token
        # (split-origin), since topology decides which one a browser has. CSRF
        # is enforced only for the cookie, the transport a cross-site page can
        # attach; a body token is bearer-equivalent and unreadable cross-site
        # (same as /auth/refresh).
        cookie_token = read_refresh_cookie(request)
        if cookie_token is not None:
            enforce_csrf(request)
        # Try every presented credential, cookie first. Unlike /auth/refresh
        # (cookie is authoritative), logout is best-effort revocation: a dead
        # cookie must not shadow a live body token (a split-origin install can
        # hold both), since failing leaves the session alive.
        body_token = body.refresh_token if body is not None else None
        for presented in (cookie_token, body_token):
            if presented is None:
                continue
            token_user = await service.get_user_from_refresh_token(presented)
            if token_user is not None:
                user_id = token_user.id
                break
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # commit=False: fold the token revocation and the audit row into one
    # transaction, mirroring change_password below, so logout joins the
    # login-failure and login-success audit trail.
    await service.revoke_all_tokens(user_id, commit=False)
    await audit_emit(
        db,
        AuditEvent(
            user_id=user_id,
            action="user.logout",
            resource_type="user",
            ip_address=get_client_ip(request),
        ),
    )
    await db.commit()
    logout_response = Response(status_code=status.HTTP_204_NO_CONTENT)
    # Revocation above already kills the server-side row; clearing cookies
    # stops the browser replaying a dead credential or holding a stale CSRF
    # value. Unconditional: a non-browser caller has none to clear.
    clear_browser_session(logout_response, request)
    return logout_response


@router.post("/download-token/{dataset_id}", response_model=DownloadTokenResponse)
@limiter.limit("60/minute")
async def create_download_token_endpoint(
    request: Request,
    dataset_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> DownloadTokenResponse:
    """Mint a short-lived download-scoped JWT for a single dataset.

    The COG download URL path requires a
    ``typ='download'`` JWT on the ``?token=`` query parameter — session JWTs
    are rejected. This endpoint issues that token after verifying the caller
    has read access to the dataset.

    Anonymous callers are allowed for public datasets. The returned token has
    ``typ='download'``, ``scope='dataset:{dataset_id}'``, and a TTL of 120s.
    """
    from datetime import UTC, datetime, timedelta

    import jwt as _jwt

    from app.modules.catalog.authorization import (
        check_dataset_access_or_anonymous,
    )
    from app.modules.catalog.datasets.domain.service import (
        get_dataset,
    )

    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )

    # Raises 404 if the caller cannot read the dataset; allows anonymous
    # callers on public datasets.
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    # Authenticated users get create_download_token (with a sub claim);
    # anonymous users on a public dataset get a token with no sub:
    # _resolve_download_user returns None for sub-less tokens, and
    # download_cog branches on user-None for public visibility + a NULL
    # user_id audit row.
    download_tenant_id = getattr(dataset, "tenant_id", None)
    if is_multi_tenant() and download_tenant_id is None:
        # Hosted records without durable tenant ownership are invalid and must
        # never mint an unbound signed capability.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )

    if user is not None:
        from app.modules.auth.providers import AuthenticatedIdentity

        identity = AuthenticatedIdentity(
            user_id=user.id,
            username=user.username,  # type: ignore[attr-defined]
        )
        service = AuthService(db)
        token = await service.create_download_token(
            identity,
            dataset_id,
            tenant_id=download_tenant_id,
        )
    else:
        # Anonymous download token for public dataset — no sub claim.
        now = datetime.now(UTC)
        payload = {
            "typ": "download",
            "scope": f"dataset:{dataset_id}",
            "exp": now + timedelta(seconds=120),
            "iat": now,
        }
        if is_multi_tenant():
            payload["tid"] = str(download_tenant_id)
        token = _jwt.encode(
            payload,
            settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )

    return DownloadTokenResponse(token=token, expires_in=120)


@router.get("/config", response_model=ConfigResponse, include_in_schema=False)
@router.get("/config/", response_model=ConfigResponse)
async def config(
    db: AsyncSession = Depends(get_db),
) -> ConfigResponse:
    """Return public auth configuration (no authentication required)."""
    from app.platform.extensions import get_auth_extension

    reg_enabled = await REGISTRATION_ENABLED.get(db)
    landing_first = await LANDING_FIRST.get(db)
    banner_enabled = await BANNER_ENABLED.get(db)
    # This endpoint is unauthenticated: never expose staged (disabled)
    # announcement text.
    banner_text = await BANNER_TEXT.get(db) if banner_enabled else ""
    banner_color = await BANNER_COLOR.get(db)
    email_verification_required = await EMAIL_VERIFICATION_REQUIRED.get(db)
    # Expose the SSO-only flag so the login page can hide the password
    # form on first render (no flash).
    password_login_enabled = await PASSWORD_LOGIN_ENABLED.get(db)
    return ConfigResponse(
        registration_enabled=reg_enabled,
        allow_signup=reg_enabled and password_login_enabled,
        email_verification_required=email_verification_required,
        auth_methods=list(get_auth_extension().get_auth_methods()),
        landing_first=landing_first,
        banner_enabled=banner_enabled,
        banner_text=banner_text,
        banner_color=banner_color,
        password_login_enabled=password_login_enabled,
    )


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
        can_reset_password=current_user.auth_provider == "local",
    )


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
    from app.modules.auth.permissions import get_user_effective_permissions

    effective = await get_user_effective_permissions(db, current_user)
    return PermissionsResponse(permissions=effective)


@router.get("/me/usage", response_model=UserQuotaUsage, include_in_schema=False)
@router.get("/me/usage/", response_model=UserQuotaUsage)
async def me_usage(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UserQuotaUsage:
    """Return the authenticated user's own storage and dataset quota usage."""
    return await get_user_quota_usage(db, current_user.id)


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
                fingerprint=k.fingerprint,
                is_active=k.is_active,
                expires_at=k.expires_at,
                scope=k.scope,
                dataset_id=k.dataset_id,
                created_at=k.created_at,
                last_used_at=k.last_used_at,
            )
            for k in keys
        ],
        total=total,
    )


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
    current_user: User = Depends(require_session_credential),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreateResponse:
    """Create an API key for the current user.

    The raw key is returned only in this response and cannot be retrieved again.
    Requires a signed-in session: a request that presents an API key gets 403.
    """
    from app.modules.audit.service import (
        AuditEvent,
        audit_emit,
    )
    from app.modules.auth.service import create_api_key_for_user

    api_key, raw_key = await create_api_key_for_user(
        db, current_user.id, body.name, expires_at=body.expires_at, scope=body.scope
    )

    ip = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="api_key.create",
            resource_type="api_key",
            resource_id=api_key.id,
            details={
                "name": body.name,
                "fingerprint": api_key.fingerprint,
                "expires_at": (
                    api_key.expires_at.isoformat() if api_key.expires_at else None
                ),
                "scope": api_key.scope,
            },
            ip_address=ip,
        ),
    )
    await db.commit()

    assert api_key.fingerprint is not None  # New keys always receive a fingerprint.
    return ApiKeyCreateResponse(
        id=api_key.id,
        key=raw_key,
        fingerprint=api_key.fingerprint,
        name=api_key.name,
        expires_at=api_key.expires_at,
        scope=api_key.scope,
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
    )

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
            details={"name": api_key.name, "fingerprint": api_key.fingerprint},
            ip_address=ip,
        ),
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    )
    from app.modules.auth.providers.local import (
        hash_password_async,
        verify_password_async,
    )

    # Reserving commits, so it comes before the row lock below.
    throttle = await reserve_password_change_attempt(
        db, current_user.id, current_user.username
    )

    # Lock and reload the row before reading it. An admin reset takes the same
    # row lock, so verify runs against the hash a concurrent reset committed
    # instead of reverting that reset with a write based on the old hash.
    #
    # The reset never takes the throttle's lock, and this path holds that lock
    # only after the row lock, so the two cannot deadlock.
    await db.refresh(current_user, with_for_update=True)

    if current_user.auth_provider != "local":
        await settle_login_success(db, throttle)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password change only available for local accounts",
        )
    if not current_user.password_hash or not await verify_password_async(
        body.current_password, current_user.password_hash
    ):
        await settle_password_change_failure(db, request, throttle, current_user.id)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.password_hash = await hash_password_async(body.new_password)
    await settle_login_success(db, throttle)

    # Bump token_version so all outstanding access JWTs for this user are
    # invalidated on their next request, forcing re-auth on every other
    # device. bump_key_epoch=True: a password change is a credential reset, so
    # previously minted API keys are invalidated too (plain logout leaves
    # them alone).
    #
    # commit=False folds token revocation into the same transaction as the
    # password hash mutation and audit row, so a crash between commits can't
    # bump token_version without recording the new password (lockout).
    service = AuthService(db)
    await service.revoke_all_tokens(current_user.id, commit=False, bump_key_epoch=True)

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
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
