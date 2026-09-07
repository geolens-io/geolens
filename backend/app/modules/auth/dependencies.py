"""FastAPI dependencies for JWT authentication and role-based access control."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from time import monotonic
from collections.abc import Mapping
from typing import Annotated, NoReturn

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
from app.modules.auth.permissions import get_user_roles
from app.platform.extensions import get_identity_extension, get_permission_extension

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)
log = structlog.get_logger()


def _predates_revocation_horizon(payload: Mapping, user: User) -> bool:
    """True when this access JWT was certainly issued before the user's horizon.

    fix(#1455): companion to the ``token_version`` check at both call sites,
    kept in one place so they cannot drift apart.

    CONSTRAINT: safe only while ``revoke_all_tokens`` bumps ``token_version``
    in the SAME UPDATE that stamps the horizon — a token minted before that
    commit reads the pre-bump version and fails the version check instead. If
    that coupling is ever removed, tighten this to ``issued_at <= int(...)``.

    ``iat`` is whole seconds, so this rejects only the interval strictly
    before the horizon and relies on the version bump to cover the
    same-second case; rounding the other way breaks logout-then-immediate
    re-login.

    Missing/non-numeric ``iat`` is treated as 0 (always rejected). Coerced
    rather than compared directly because PyJWT leaves ``iat`` as a numeric
    STRING after validation, and ``"1" < 1`` raises instead of comparing.
    """
    if user.sessions_revoked_at is None:
        return False
    issued_at = payload.get("iat", 0)
    if not isinstance(issued_at, (int, float)):
        issued_at = 0
    return issued_at + 1 <= user.sessions_revoked_at.timestamp()


# fix(#875): read_only API keys authenticate only these methods. Method-based
# rather than capability-based: every read surface a key client uses is GET,
# and classifying the whole permission matrix as read/write would be a much
# larger, easier-to-get-subtly-wrong change.
_READ_ONLY_SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

# fix(#875): "safe method" != "no side effect" — e.g. a GET with
# ?refresh=true persists a recomputed quality score, and the write-access gate
# can't tell a read_only key from the owner's own session, so this table is
# the only place that can refuse it. Keyed by route template -> the query
# param that turns the read into a write; `test_api_key_scope_875.py` walks
# the route table and fails if a GET gains a write guard uncatalogued here.
_READ_ONLY_KEY_WRITING_GET_ROUTES: dict[str, str] = {
    "/datasets/{dataset_id}/validate/": "refresh",
    "/datasets/{dataset_id}/validate": "refresh",
}

# Values FastAPI's bool parser reads as false. Anything else present — including
# an empty value — counts as triggering the write, so the check fails closed.
_FALSEY_QUERY_VALUES: frozenset[str] = frozenset({"false", "0", "off", "no", "f", "n"})

# fix(#875): the ONE carve-out, as exact (METHOD, route template) pairs, not
# bare templates — a bare template would exempt any future method on that
# path. Matching is on the template Starlette resolved, never the concrete
# path, so a caller cannot spoof the exemption by mirroring its characters; an
# unresolved template is ``<unmatched-route>``, refused by default (fix(#875
# codex r2)).
#
# POST /query/ (#565) is a read-only SELECT sandbox exempted despite being a
# POST. POST /stac/search is STAC's required JSON-body search surface,
# delegating to the same read-only `_execute_search` the GET form uses.
#
# Spelled WITHOUT the `/api` prefix: the app uses `root_path="/api"`, which
# Starlette strips before route matching, so no route template starts with
# `/api/`.
#
# Both trailing-slash and bare spellings, because the routes register both
# forms for the same handler and `redirect_slashes` is off.
_READ_ONLY_KEY_EXEMPT_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/query/"),
        ("POST", "/query"),
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
    if method not in _READ_ONLY_SAFE_METHODS:
        return (method, route_template) in _READ_ONLY_KEY_EXEMPT_ROUTES
    trigger = _READ_ONLY_KEY_WRITING_GET_ROUTES.get(route_template)
    if trigger is None:
        return True
    value = (query_params or {}).get(trigger)
    if value is None:
        return True
    return value.strip().lower() in _FALSEY_QUERY_VALUES


def _query_key_may_authenticate(
    method: str,
    route_template: str,
    query_params: Mapping[str, str] | None = None,
) -> bool:
    """Whether a key that arrived in the QUERY STRING may authenticate this.

    fix(#1845): the deprecated ``?api_key=`` lane was documented read-only but
    unenforced, so the same credential could authorize mutations. Restriction
    is on the TRANSPORT, not the key: a URL-borne key leaks into browser
    history, logs, and ``Referer`` headers by construction, so what it may do
    is bounded independently of what its owner may do.

    Reuses the ``_READ_ONLY_KEY_WRITING_GET_ROUTES`` classification but is
    deliberately stricter than the #875 scope rule — it does NOT inherit
    ``_READ_ONLY_KEY_EXEMPT_ROUTES``, since those POSTs are reads a key owner
    chose to make while a logged URL is a credential nobody chose to expose.
    Header keys are untouched.
    """
    return method in _READ_ONLY_SAFE_METHODS and _read_only_key_may_call(
        method, route_template, query_params
    )


# fix(#1845): reachable by an unauthenticated caller at the rate limit, so
# refusal logging is throttled to one line per route template per interval,
# bounding log volume by route-table size rather than request volume. Keyed
# by route template only (never caller-supplied), so the key space cannot be
# grown by a caller. Left unsynchronized: a lost race costs one extra log
# line, cheaper than a lock on the request path.
_QUERY_LANE_LOG_INTERVAL_SECONDS = 60.0
_query_lane_log_last: dict[str, float] = {}


def _should_log_query_lane_refusal(route_template: str) -> bool:
    now = monotonic()
    last = _query_lane_log_last.get(route_template)
    if last is not None and now - last < _QUERY_LANE_LOG_INTERVAL_SECONDS:
        return False
    _query_lane_log_last[route_template] = now
    return True


def _supplied_api_key(request: Request) -> str | None:
    """The API key this request may authenticate with, header first.

    fix(#1845): the sole place deciding whether a query-string key counts, so
    this resolver and ``request_carries_credentials`` cannot disagree. A
    refused query-lane key is treated as absent, not surfaced as a new error
    shape that would tell an attacker their key parsed.
    """
    header_key = request.headers.get("X-Api-Key")
    if header_key:
        return header_key
    query_key = request.query_params.get("api_key")
    if not query_key:
        return None
    route_template = _route_template(request)
    if not _query_key_may_authenticate(
        request.method, route_template, request.query_params
    ):
        # No DB lookup here: it would turn an unauthenticated request into an
        # oracle for whether a key is live. Throttled since an anonymous
        # caller controls how often this refusal path runs.
        if _should_log_query_lane_refusal(route_template):
            log.warning(
                "api_key_query_lane_refused",
                method=request.method,
                path=route_template,
            )
        return None
    return query_key


def log_permission_denial(
    request: Request,
    user: Identity,
    capability: str,
    user_roles: set[str],
    *,
    resource_type: str | None = None,
) -> None:
    """Emit deliberately narrow telemetry for an authorization denial.

    Do not add request headers, query strings, bodies, or resource
    identifiers/objects here: they can carry credentials or tenant data.
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

    fix(#821): the ``?api_key=`` query lane is DEPRECATED (leaks into access
    logs); kept for clients that cannot set headers, e.g. desktop GIS XYZ tile
    URLs. Precedence: header > query param.

    fix(#1845): that read-only justification is now enforced, not just
    documented — ``_supplied_api_key`` drops a query-string key on anything
    but a read.
    """
    api_key = _supplied_api_key(request)
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
    # fix(#821): an expired key behaves like an invalid one (must not bump
    # last_used_at below).
    if api_key_obj.expires_at is not None and api_key_obj.expires_at <= now:
        return None
    # fix(#821): staleness gate on the owner's key_epoch, the API-key analogue
    # of the JWT token_version check (SEC-S15) — a dedicated counter bumped
    # only by security events. Logout bumps token_version, not key_epoch, so
    # long-lived API keys survive a web UI sign-out.
    user = api_key_obj.user
    if user is None or api_key_obj.key_epoch != user.key_epoch:
        return None
    if not user.is_active or user.status != "active":
        return None
    # Only bump last_used_at every 60s (reduce write amplification), via a
    # separate session: committing on `db` here would flush/release advisory
    # locks or uncommitted state the route handler still needs.
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
    # fix(#875): least-privilege scope enforced HERE — the one chokepoint
    # every API-key lane passes through (header, deprecated query, every
    # optional-user router). Must RAISE, not return None, or a scope
    # violation falls through to the anonymous/JWT path as a confusing 401.
    # Runs AFTER the last_used_at bump so a read-only key hammering writes
    # still shows activity instead of looking dormant.
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


def request_carries_credentials(request: Request) -> bool:
    """True if the request supplied any user credential (Bearer / API key).

    Lets an anonymous-capable endpoint tell a truly anonymous caller (serve
    public, 404 private) apart from one whose credential failed to resolve
    (expired/revoked JWT), which should get 401 instead so refresh-on-401
    fires. Mirrors the credential sources ``_resolve_api_key`` + bearer accept.

    fix(#1845): a query-string key the resolver refuses to read is NOT a
    credential that failed to resolve — reporting it here would wrongly 401 a
    request that should have been served anonymously.
    """
    return bool(request.headers.get("Authorization") or _supplied_api_key(request))


def reject_unresolvable_credentials(request: Request, user: Identity | None) -> None:
    """Apply the #1518 fail-closed rule at a point the CALLER chooses.

    The single implementation, so dependencies and handlers that must
    sequence it themselves cannot drift into two answers (the original #1518
    bug). ``get_optional_user`` calls this immediately; a CAPABILITY handler
    (see ``get_optional_user_fail_open``) calls it only after its own
    capability check has declined, never before.

    Deliberately NOT capability-aware: it would need the verdict handed in,
    and a header-presence proxy would let any caller suppress the 401 by
    sending a junk header.
    """
    if user is None and request_carries_credentials(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )


def capability_declined(
    request: Request, user: Identity | None, exc: HTTPException
) -> NoReturn:
    """Report a capability that did not authorize — after the #1518 rule.

    fix(#1518): a CAPABILITY handler has several exit paths where
    no capability authorized; calling this instead of a bare ``raise`` makes
    the #1518 ordering structural rather than positional, and checkable — a
    test can require every capability-declined raise to route through here.

    ``exc`` is the answer once the credential itself is fine: an invalid
    capability really is 403, a missing resource really is 404.
    """
    reject_unresolvable_credentials(request, user)
    raise exc


async def _resolve_optional_identity(
    request: Request,
    token: str | None,
    db: AsyncSession,
) -> Identity | None:
    """Resolve a caller identity from an API key or JWT, or ``None``.

    Shared by both optional-identity dependencies below. ``None`` means "no
    identity resolved" — not "no credential supplied"; an expired, revoked, or
    mistyped credential lands on the same ``None``. Deciding what that means
    is the caller's job (``get_optional_user`` refuses it,
    ``get_optional_user_fail_open`` does not).
    """
    user = await _resolve_api_key(request, db)
    if user is not None:
        return user

    # IdentityExtension hook: lets an enterprise overlay
    # resolve the bearer token before the JWT decode path; default impl
    # returns None. Bearer-token only (API keys stay community).
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

    # Reject stale access JWTs; missing token_version
    # (legacy/forged tokens) is treated as 0, always below the min stored 1.
    jwt_token_version: int = payload.get("token_version", 0)
    if jwt_token_version < user.token_version:
        return None

    # fix(#1455): matching token_version alone doesn't prove the token
    # postdates revocation (rotation racing revocation) — see helper docstring.
    if _predates_revocation_horizon(payload, user):
        return None

    return user


async def get_optional_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db),
) -> Identity | None:
    """Resolve the caller on an anonymous-capable endpoint. FAIL-CLOSED.

    A credentialless request resolves to ``None`` (public path). A request
    that SUPPLIED a credential which fails to resolve — expired, revoked,
    mistyped — gets 401.

    fix(#401): a stale/revoked token used to resolve to anonymous, so a
    credentialed caller's private dataset 404'd instead of 401ing.

    fix(#1518): that fix was router-scoped and left most endpoints silently
    downgrading a bad credential to the anonymous/public subset instead of
    401ing. The rule now lives HERE so every site inherits it;
    ``get_optional_user_fail_open`` is the one sanctioned way out, pinned by
    ``tests/test_optional_auth_failure_mode_1518.py``.
    """
    user = await _resolve_optional_identity(request, token, db)
    reject_unresolvable_credentials(request, user)
    return user


async def get_optional_user_fail_open(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db),
) -> Identity | None:
    """The named exceptions to the fail-closed rule above (#1518).

    Does not judge the credential: a supplied-but-unresolvable one resolves to
    ``None`` here, and the handler decides what that means. Exactly TWO
    sanctioned categories:

    **RECOVERY** — an endpoint that recovers from a dead credential (e.g.
    ``/auth/logout``, which accepts the refresh cookie or a body token once
    the access JWT has aged out, fix(#1446)) and raises its own 401 if nothing
    presented resolves.

    **CAPABILITY** — an endpoint authorizable by something other than the
    caller's identity (an embed token). The rule is RESEQUENCED, not waived:
    the handler evaluates the capability first, then calls
    ``reject_unresolvable_credentials`` only on the path where no capability
    authorized the request. Resequencing lives in the handler, not in
    ``request_carries_credentials``, because validating a capability needs a
    DB session and the resource id — degrading it to "a header is present"
    would let any caller suppress the 401 with a junk header (#1518 again).

    Every user of this dependency must be listed in ``FAIL_OPEN_ALLOWLIST`` in
    ``tests/test_optional_auth_failure_mode_1518.py`` with its category; that
    test walks the route table and fails on an unlisted one.
    """
    return await _resolve_optional_identity(request, token, db)


async def get_optional_user_no_security_schema(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Identity | None:
    """``get_optional_user`` minus the OpenAPI security marker.

    fix(#430): ``oauth2_scheme_optional`` stamps a bearer ``security``
    entry onto the operation, mistyping genuinely public endpoints (e.g. STAC
    collections) as requiring auth in generated SDKs. This extracts the bearer
    token from the raw header instead — identical resolution semantics, zero
    schema footprint. Use ONLY where the public OpenAPI surface must stay
    anonymous.

    fix(#1518): delegates to ``get_optional_user``, so it still inherits the
    fail-closed rule; only the schema marker is opted out of.
    """
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    return await get_optional_user(request, token, db)


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
    user = await _resolve_api_key(request, db)
    if user is not None:
        return user

    # IdentityExtension hook, same pattern as
    # get_optional_user. Duplicated here (not delegated) to preserve the
    # expired-token 401 UX below (RFC 6750 silent-refresh hint).
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

    # Reject stale access JWTs; missing token_version
    # (legacy/forged tokens) is treated as 0, always below the min stored 1.
    jwt_token_version: int = payload.get("token_version", 0)
    if jwt_token_version < user.token_version:
        raise credentials_exception

    # fix(#1455): matching token_version alone doesn't prove the token
    # postdates revocation (rotation racing revocation) — see helper docstring.
    if _predates_revocation_horizon(payload, user):
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: Annotated[Identity, Depends(get_current_user)],
) -> Identity:
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

        user_roles = await get_cached_user_roles(request, db, current_user)

        cached = getattr(request.state, "_effective_permissions", None)
        if cached is not None:
            matrix = cached
        else:
            matrix = await get_effective_permissions(db)
            request.state._effective_permissions = matrix

        permission_ext = get_permission_extension()

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
