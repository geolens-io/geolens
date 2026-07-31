"""FastAPI dependencies for JWT authentication and role-based access control."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from collections.abc import Mapping
from typing import Annotated

import jwt
import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.models import ApiKey, User
from app.modules.catalog.authorization import get_user_roles
from app.platform.extensions import get_identity_extension, get_permission_extension

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)
log = structlog.get_logger()


# fix(#875): HTTP methods a read_only API key may authenticate. Enforcement is
# method-based rather than capability-based on purpose: every read surface an
# API-key client actually uses (OGC Features, STAC, tiles, search, dataset and
# map reads) is a GET here, the STAC and OGC routers define no write routes at
# all, and classifying every capability in the permission matrix as read or
# write is a much larger change that is easy to get subtly wrong.
_READ_ONLY_SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

# fix(#875 codex r1): "safe method" is not the same as "no side effect" here.
# `GET /datasets/{dataset_id}/validate/?refresh=true` recomputes the quality
# score with a full table scan and PERSISTS it. It is gated on
# `check_dataset_write_access`, but that gate sees the owner identity the key
# resolved to and cannot tell a read_only key from the owner's own session, so
# the method check is the only place that can refuse it.
#
# Keyed by route template, valued by the QUERY PARAMETER that turns the read
# into a write, so the ordinary cached read of the same route keeps working.
# `backend/tests/test_api_key_scope_875.py` walks the route table and fails if
# any GET handler gains a write guard or a commit without being classified
# here or in that test's allowlist.
_READ_ONLY_KEY_WRITING_GET_ROUTES: dict[str, str] = {
    "/datasets/{dataset_id}/validate/": "refresh",
    "/datasets/{dataset_id}/validate": "refresh",
}

# Values FastAPI's bool parser reads as false. Anything else present — including
# an empty value — counts as triggering the write, so the check fails closed.
_FALSEY_QUERY_VALUES: frozenset[str] = frozenset({"false", "0", "off", "no", "f", "n"})

# fix(#875): the ONE carve-out, as exact (METHOD, route template) pairs.
#
# #565 adds POST /api/query/, a SELECT-only sandbox endpoint that is a pure
# read semantically and a POST only mechanically. A read_only key may call it,
# because it is a read — the maintainer decision is recorded in both #875 and
# #565. The general rule ("POST endpoints that are reads in spirit can trigger
# jobs and writes") holds for AI chat and analysis previews and does not hold
# for a raw SELECT through the sandbox rails.
#
# Pairs, not bare templates: exempting the PATH would also exempt a future
# DELETE /api/query/{id}. And an exact list rather than a "POST that looks
# like a read" category, so a future POST cannot inherit the exemption by
# resembling one. Matching is on the template Starlette resolved, never on the
# concrete path, so a caller-supplied path that merely spells the same
# characters cannot reach it; an unresolvable template is
# ``<unmatched-route>``, which is in no pair and so is refused.
#
# Both spellings, because ROUTE-01's dual-shape decorator registers the
# trailing-slash form and a hidden bare form for the same handler, and
# redirect_slashes is off — exempting only one would 403 half the callers of
# the same endpoint for no reason anyone could find.
#
# The route is not mounted yet. Whoever lands #565 owns re-reading this.
# fix(#875 codex r1): STAC Item Search is the second entry, and it is required
# rather than a widening. The issue's acceptance criteria say a read_only key
# must be able to hit OGC/STAC endpoints, and `POST /stac/search` IS the
# standard's JSON-body search surface — `search_post` delegates to the same
# `_execute_search` the GET form uses and writes nothing. Refusing it would
# have shipped a comment claiming STAC works next to code that broke it.
_READ_ONLY_KEY_EXEMPT_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/query/"),
        ("POST", "/api/query"),
        ("POST", "/stac/search"),
    }
)


def _route_template(request: Request) -> str:
    """The matched route's path template, or a generic placeholder.

    Never falls back to ``request.url.path``: concrete paths can contain UUIDs,
    tokens, or other tenant-controlled identifiers, and this value is both
    logged and compared against an exemption list.
    """
    scope = getattr(request, "scope", None)
    route = scope.get("route") if isinstance(scope, dict) else None
    route_template = getattr(route, "path", None)
    if not isinstance(route_template, str) or not route_template.startswith("/"):
        return "<unmatched-route>"
    return route_template


def _read_only_key_may_call(
    method: str,
    route_template: str,
    query_params: Mapping[str, str] | None = None,
) -> bool:
    """Whether a ``read_only`` API key may authenticate this request (#875)."""
    if method not in _READ_ONLY_SAFE_METHODS:
        return (method, route_template) in _READ_ONLY_KEY_EXEMPT_ROUTES
    trigger = _READ_ONLY_KEY_WRITING_GET_ROUTES.get(route_template)
    if trigger is None:
        return True
    value = (query_params or {}).get(trigger)
    if value is None:
        return True
    return value.strip().lower() in _FALSEY_QUERY_VALUES


def log_permission_denial(
    request: Request,
    user: Identity,
    capability: str,
    user_roles: set[str],
    *,
    resource_type: str | None = None,
) -> None:
    """Emit deliberately narrow telemetry for an authorization denial.

    Centralizing this shape keeps manual, resource-aware authorization checks
    aligned with ``require_permission``. Do not add request headers, query
    strings, bodies, resource identifiers, or resource objects here: those can
    contain credentials or tenant data.
    """
    route_template = _route_template(request)
    fields: dict[str, object] = {
        "user_id": str(user.id),
        "capability": capability,
        "user_roles": sorted(user_roles),
        "method": request.method,
        "path": route_template,
    }
    if resource_type is not None:
        fields["resource_type"] = resource_type
    log.warning("permission_denied", **fields)


async def _resolve_api_key(request: Request, db: AsyncSession) -> User | None:
    """Try to resolve a user from X-Api-Key header or api_key query parameter.

    The ``?api_key=`` query-parameter lane is DEPRECATED (#821): a credential
    in the URL is written into access logs and any upstream proxy logs. It is
    kept for external clients that cannot set headers (e.g. XYZ tile URLs in
    desktop GIS tools) but new integrations must use the ``X-Api-Key`` header.
    Resolution precedence is unchanged: header > query param.
    """
    api_key = request.headers.get("X-Api-Key")
    if not api_key:
        api_key = request.query_params.get("api_key")
    if not api_key:
        return None
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    result = await db.execute(
        select(ApiKey)
        .join(User, ApiKey.user_id == User.id)
        .where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)  # noqa: E712
    )
    api_key_obj = result.scalar_one_or_none()
    if api_key_obj is None:
        return None
    now = datetime.now(timezone.utc)
    # fix(#821): an expired key behaves exactly like an invalid one (and must
    # not bump last_used_at below).
    if api_key_obj.expires_at is not None and api_key_obj.expires_at <= now:
        return None
    # fix(#821): staleness gate on the owner's key_epoch — the API-key
    # analogue of the JWT token_version check (SEC-S15), but on a dedicated
    # counter bumped only by security events (password change, role change,
    # SAML-to-local conversion). Logout bumps token_version, NOT key_epoch,
    # so signing out of the web UI never kills long-lived API keys.
    user = api_key_obj.user
    if user is None or api_key_obj.key_epoch != user.key_epoch:
        return None
    if not user.is_active or user.status != "active":
        return None
    # Only update last_used_at if it's been more than 60 seconds (reduce write amplification).
    # Use a separate session so we don't flush the request-scoped session early —
    # an early commit on `db` would release advisory locks the route handler
    # may still need, and would persist any uncommitted state from prior
    # dependencies before the route's own logic decides whether to commit.
    if api_key_obj.last_used_at is None or (now - api_key_obj.last_used_at) > timedelta(
        seconds=60
    ):
        from app.core.db import async_session

        api_key_id = api_key_obj.id
        async with async_session() as side_session:
            await side_session.execute(
                update(ApiKey)
                .where(
                    ApiKey.id == api_key_id,
                    ApiKey.user_id.in_(select(User.id)),
                )
                .values(last_used_at=now)
            )
            await side_session.commit()
        api_key_obj.last_used_at = now
    # fix(#875): least-privilege scope, enforced HERE rather than in
    # require_permission or middleware, because this is the one chokepoint
    # every API-key lane passes through — header, deprecated ?api_key=, and
    # every router that resolves an optional user.
    #
    # It must RAISE, not return None: returning None falls through to the
    # anonymous/JWT path and turns a scope violation into a confusing 401.
    #
    # It sits AFTER the last_used_at bump on purpose. The key did
    # authenticate; the request is refused on what it asked to do, and usage
    # is recorded either way, so a client hammering writes with a read-only
    # key still shows a moving last_used_at instead of looking dormant.
    route_template = _route_template(request)
    if api_key_obj.scope == "read_only" and not _read_only_key_may_call(
        request.method, route_template, request.query_params
    ):
        log.warning(
            "api_key_scope_denied",
            user_id=str(user.id),
            method=request.method,
            path=route_template,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This API key is read-only",
        )
    return user


async def get_optional_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db),
) -> Identity | None:
    """Try to extract the current user from an API key or JWT token.

    Returns None if no credentials are provided or they are invalid.
    Used on endpoints that should be accessible anonymously (public datasets)
    but can show additional data when authenticated.
    """
    # Try API key first
    user = await _resolve_api_key(request, db)
    if user is not None:
        return user

    # IdentityExtension hook (Phase 214 D-15): if an enterprise overlay
    # registered an alternate identity backend, give it a chance to resolve
    # the bearer token before the existing JWT decode path. Default impl
    # returns None -> falls through to JWT below. Extension is bearer-token
    # only (D-17 — API keys remain a community concern).
    if token is not None:
        ext_identity = await get_identity_extension().resolve_identity_from_token(
            token, request, db
        )
        if ext_identity is not None:
            return ext_identity

    if token is None:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            return None
    except jwt.PyJWTError:
        return None

    try:
        user_id = uuid.UUID(user_id_str)
    except (ValueError, AttributeError):
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active or user.status != "active":
        return None

    # SEC-S15 (Phase 1062-01): reject stale access JWTs.
    # A missing token_version claim (legacy / forged tokens) is treated as
    # version 0, which is always less than the minimum stored version of 1.
    jwt_token_version: int = payload.get("token_version", 0)
    if jwt_token_version < user.token_version:
        return None

    return user


async def get_optional_user_no_security_schema(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Identity | None:
    """``get_optional_user`` minus the OpenAPI security marker.

    fix(#430 codex): depending on ``oauth2_scheme_optional`` stamps a bearer
    ``security`` entry onto the operation, so generated SDKs type genuinely
    public endpoints (e.g. STAC collections) as requiring an authenticated
    client. This variant extracts the bearer token from the raw header —
    identical resolution semantics, zero schema footprint. Use ONLY on
    endpoints that must stay anonymous on the public OpenAPI surface.
    """
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    return await get_optional_user(request, token, db)


def request_carries_credentials(request: Request) -> bool:
    """True if the request supplied any user credential (Bearer / API key).

    Lets anonymous-capable endpoints tell a truly anonymous caller (serve
    public, 404 private) apart from one whose supplied credentials failed to
    resolve — e.g. an expired or revoked JWT that ``get_optional_user`` maps to
    ``None``. The latter should get 401, not 404, so the client's
    refresh-and-retry path fires instead of a misleading "not found". Mirrors
    the credential sources ``_resolve_api_key`` + the bearer scheme accept.
    """
    return bool(
        request.headers.get("Authorization")
        or request.headers.get("X-Api-Key")
        or request.query_params.get("api_key")
    )


async def get_optional_user_or_401(
    request: Request,
    user: Annotated[Identity | None, Depends(get_optional_user)],
) -> Identity | None:
    """``get_optional_user``, but supplied-yet-unresolvable credentials get 401.

    fix(#401): the OGC/STAC read handlers resolved a stale/revoked token to the
    anonymous path, so a credentialed caller's private dataset 404'd instead of
    401ing and the client's refresh-on-401 retry never fired. Use this on
    anonymous-capable read endpoints; truly credentialless requests still
    resolve to ``None`` and keep the public path.
    """
    if user is None and request_carries_credentials(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db),
) -> Identity:
    """Decode a JWT Bearer token (or API key) and return the corresponding User.

    Raises 401 if credentials are invalid, expired, or the user does not exist.
    Uses oauth2_scheme_optional so that X-Api-Key requests without a Bearer
    token are not rejected before the function body runs.
    """
    # Try API key first
    user = await _resolve_api_key(request, db)
    if user is not None:
        return user

    # IdentityExtension hook (Phase 214 D-15): same pattern as
    # get_optional_user. Duplicated across both deps to preserve the
    # expired-token UX (RFC 6750 silent-refresh hint at lines below)
    # rather than refactoring get_current_user to delegate to
    # get_optional_user (Pitfall 9 recommendation).
    if token is not None:
        ext_identity = await get_identity_extension().resolve_identity_from_token(
            token, request, db
        )
        if ext_identity is not None:
            return ext_identity

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if token is None:
        raise credentials_exception

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
    except jwt.ExpiredSignatureError:
        # Distinguish expired-token from invalid-token per RFC 6750 so the
        # frontend can drive a silent refresh instead of forcing re-login.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The access token expired",
            headers={
                "WWW-Authenticate": (
                    'Bearer error="invalid_token", '
                    'error_description="The access token expired"'
                )
            },
        )
    except jwt.PyJWTError:
        raise credentials_exception

    try:
        user_id = uuid.UUID(user_id_str)
    except (ValueError, AttributeError):
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active or user.status != "active":
        raise credentials_exception

    # SEC-S15 (Phase 1062-01): reject stale access JWTs.
    # A missing token_version claim (legacy / forged tokens) is treated as
    # version 0, which is always less than the minimum stored version of 1.
    jwt_token_version: int = payload.get("token_version", 0)
    if jwt_token_version < user.token_version:
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: Annotated[Identity, Depends(get_current_user)],
) -> Identity:
    """Ensure the current user is active."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )
    return current_user


async def get_cached_user_roles(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Identity | None = Depends(get_optional_user),
) -> set[str]:
    """Return user roles, cached for the lifetime of this request.

    Prevents repeated DB hits when require_role/require_permission are
    called multiple times on the same request path.
    """
    if user is None:
        return set()
    cached = getattr(request.state, "_user_roles", None)
    if cached is not None:
        return cached
    roles = await get_user_roles(db, user)
    request.state._user_roles = roles
    return roles


def require_role(*roles: str):
    """Factory that returns a dependency enforcing role-based access.

    Usage::

        @router.get("/admin", dependencies=[Depends(require_role("admin"))])
        async def admin_only(): ...

    The dependency resolves to the current User so endpoints can also
    consume it as a parameter.
    """

    async def _role_checker(
        request: Request,
        current_user: Annotated[Identity, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
    ) -> Identity:
        user_roles = await get_cached_user_roles(request, db, current_user)

        if not user_roles.intersection(roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _role_checker


def require_permission(*capabilities: str):
    """Factory that returns a dependency enforcing capability-based access.

    Checks the permission matrix to see if ANY of the user's roles grants
    the requested capabilities.

    Usage::

        @router.post("/upload", dependencies=[Depends(require_permission("upload"))])
        async def upload(): ...
    """

    async def _permission_checker(
        request: Request,
        current_user: Annotated[Identity, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
    ) -> Identity:
        from app.modules.auth.permissions import get_effective_permissions

        # Get user roles (cached per-request)
        user_roles = await get_cached_user_roles(request, db, current_user)

        # Get effective permission matrix (cached per-request)
        cached = getattr(request.state, "_effective_permissions", None)
        if cached is not None:
            matrix = cached
        else:
            matrix = await get_effective_permissions(db)
            request.state._effective_permissions = matrix

        permission_ext = get_permission_extension()

        # Check each requested capability
        for cap in capabilities:
            granted = await permission_ext.check_permission(
                db,
                current_user,
                cap,
                user_roles=user_roles,
                permission_matrix=matrix,
            )
            if not granted:
                log_permission_denial(request, current_user, cap, user_roles)
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Missing permission: {cap}",
                )

        return current_user

    return _permission_checker


def require_mode_permission(*, single_tenant: str, multi_tenant: str):
    """Require different capabilities for self-hosted and hosted operation.

    Some control-plane resources are deployment-global by design. A
    self-hosted admin may manage them with the ordinary domain capability, but
    a hosted tenant admin must not mutate or inspect fleet-wide state. Hosted
    access therefore requires an explicitly provisioned fleet capability.
    """
    single_checker = require_permission(single_tenant)
    multi_checker = require_permission(multi_tenant)

    async def _mode_permission_checker(
        request: Request,
        current_user: Annotated[Identity, Depends(get_current_active_user)],
        db: AsyncSession = Depends(get_db),
    ) -> Identity:
        from app.core.tenancy import is_multi_tenant

        checker = multi_checker if is_multi_tenant() else single_checker
        return await checker(request=request, current_user=current_user, db=db)

    return _mode_permission_checker
