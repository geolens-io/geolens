"""FastAPI dependencies for JWT authentication and role-based access control."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
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

    fix(#1455): the companion to the ``token_version`` check at both call
    sites. One helper rather than the pair of inline copies, so the two
    dependencies cannot drift apart on a security predicate.

    CONSTRAINT: the rounding below is only safe while ``revoke_all_tokens``
    bumps ``token_version`` in the SAME UPDATE that stamps the horizon. Anyone
    who removes or weakens that bump must tighten this back to
    ``issued_at <= int(...)`` in the same change.

    Why the coupling exists. ``iat`` is whole seconds (PyJWT truncates), so it
    names the interval ``[iat, iat+1)`` rather than an instant, and this
    rejects only when that WHOLE interval precedes the horizon — which leaves
    the same-second region covered by nothing on this line. The bump is what
    covers it: the horizon is the revoking transaction's ``now()``, so a token
    minted before that UPDATE commits necessarily read the pre-bump version
    under READ COMMITTED and dies on the version check, while one minted after
    it commits carries the new version and legitimately lives. The same
    composition covers API-vs-DB clock skew, where an API clock running ahead
    could lift a pre-revocation ``iat`` past the horizon: the bump still
    rejects it. This check is therefore added ALONGSIDE the version check and
    never replaces it.

    Rounding the other way is not free, which is why the constraint is worth
    keeping rather than pre-emptively tightening: it kills any token minted in
    the same second as a revocation, which breaks logging out and immediately
    logging back in, and it made
    ``test_a_rotation_racing_logout_never_leaves_a_live_session`` fail
    intermittently (``iat=1786618628`` against a horizon of ``1786618628.02``,
    a token minted AFTER the revocation and refused).

    A missing (or non-numeric) ``iat`` is treated as 0, which precedes every
    horizon and is therefore always rejected once one exists. That mirrors the
    missing-``token_version``-is-0 convention at the call sites. Coercing
    rather than comparing directly matters because PyJWT validates ``iat`` by
    casting a COPY, leaving a numeric STRING in the payload, and ``"1" < 1``
    raises rather than rejecting.
    """
    if user.sessions_revoked_at is None:
        return False
    issued_at = payload.get("iat", 0)
    if not isinstance(issued_at, (int, float)):
        issued_at = 0
    return issued_at + 1 <= user.sessions_revoked_at.timestamp()


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
# Spelled WITHOUT the `/api` prefix. The app is constructed with
# `root_path="/api"` (`api/main.py`), and an ASGI root_path never appears in a
# route template — starlette strips it before matching, and `api/main.py` says
# so where it mirrors that behaviour. Nothing in the route table starts with
# `/api/`, which is why the already-mounted `/stac/search` entry below is
# spelled that way too. An `/api/query/` entry would simply never match, and
# because the check fails closed that would silently defeat the maintainer
# decision rather than break loudly (fix(#875 codex r2)).
#
# Both spellings, because ROUTE-01's dual-shape decorator registers the
# trailing-slash form and a hidden bare form for the same handler, and
# redirect_slashes is off — exempting only one would 403 half the callers of
# the same endpoint for no reason anyone could find.
#
# NOT VERIFIABLE YET: the route does not exist, so the exact template is
# whatever router #565 mounts it on. `/query/` assumes a bare `api_router`
# path or a `prefix="/query"` router, matching every other entry here.
# Whoever lands #565 must confirm the real `route.path` and move the entry
# out of the pending list in `backend/tests/test_api_key_scope_875.py`, which
# then asserts it resolves.
# fix(#875 codex r1): STAC Item Search is the second entry, and it is required
# rather than a widening. The issue's acceptance criteria say a read_only key
# must be able to hit OGC/STAC endpoints, and `POST /stac/search` IS the
# standard's JSON-body search surface — `search_post` delegates to the same
# `_execute_search` the GET form uses and writes nothing. Refusing it would
# have shipped a comment claiming STAC works next to code that broke it.
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


def _query_key_may_authenticate(
    method: str,
    route_template: str,
    query_params: Mapping[str, str] | None = None,
) -> bool:
    """Whether a key that arrived in the QUERY STRING may authenticate this.

    fix(#1845): the deprecated ``?api_key=`` lane is documented as read-only
    ("kept for external clients that cannot set headers, e.g. XYZ tile URLs in
    desktop GIS tools") and nothing enforced it, so the same credential
    authorized admin mutations. This is the enforcement.

    The restriction is on the TRANSPORT, not on the key. A key in a URL is
    written into browser history, bookmarks, screen shares, an operator's
    upstream load balancer or CDN access log, and a cross-origin ``Referer``.
    It is a value that leaks by construction, so what it may do is bounded
    independently of what its owner may do.

    It composes with, rather than duplicates, the #875 scope rule: the same
    ``_READ_ONLY_KEY_WRITING_GET_ROUTES`` classification decides which GETs
    are really writes, so "which requests are reads" has one definition. The
    query lane is deliberately the stricter of the two and does NOT inherit
    ``_READ_ONLY_KEY_EXEMPT_ROUTES``. Those two POSTs are reads a key's OWNER
    chose to make with a scoped credential; a URL that ends up in a log is a
    credential nobody chose to hand out, and the tile-URL clients this lane
    exists for issue GETs.

    Header keys are untouched.
    """
    return method in _READ_ONLY_SAFE_METHODS and _read_only_key_may_call(
        method, route_template, query_params
    )


def _supplied_api_key(request: Request) -> str | None:
    """The API key this request may authenticate with, header first.

    fix(#1845): ONE place decides whether a query-string key counts, so the
    resolver and ``request_carries_credentials`` cannot answer differently and
    turn an ignored credential into a confusing 401. When the query lane is
    refused the key is treated as absent, exactly as if it had never been
    supplied: the caller gets the 401/403/404 the request would have earned
    anonymously, not a new error shape that tells an attacker their key parsed.
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
        # No key material and no key identifier: resolving one would need the
        # database lookup this refusal deliberately skips, and would turn an
        # unauthenticated request into an oracle for whether a key is live.
        # Once per request, because the resolver and
        # ``request_carries_credentials`` both ask this question on an
        # optional-auth route and one refusal is one event.
        if not getattr(request.state, "api_key_query_lane_refused", False):
            request.state.api_key_query_lane_refused = True
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

    fix(#1845): that read-only justification is now enforced rather than
    merely stated. ``_supplied_api_key`` drops a query-string key on anything
    but a read, so the deprecated lane can no longer authorize a mutation.
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


def request_carries_credentials(request: Request) -> bool:
    """True if the request supplied any user credential (Bearer / API key).

    Lets anonymous-capable endpoints tell a truly anonymous caller (serve
    public, 404 private) apart from one whose supplied credentials failed to
    resolve — e.g. an expired or revoked JWT that ``_resolve_optional_identity``
    maps to ``None``. The latter should get 401, not 404, so the client's
    refresh-and-retry path fires instead of a misleading "not found". Mirrors
    the credential sources ``_resolve_api_key`` + the bearer scheme accept.

    fix(#1845): "mirrors" is load-bearing, hence the shared
    ``_supplied_api_key``. A query-string key the resolver refuses to read is
    not a credential that failed to resolve; it is a credential that was never
    accepted, and reporting it here would answer 401 where the request would
    otherwise have been served anonymously.
    """
    return bool(request.headers.get("Authorization") or _supplied_api_key(request))


def reject_unresolvable_credentials(request: Request, user: Identity | None) -> None:
    """Apply the #1518 fail-closed rule at a point the CALLER chooses.

    The single implementation of the rule, so the dependency and the handlers
    that have to sequence it themselves cannot drift into two answers — which
    is the shape of the bug #1518 reported in the first place.

    ``get_optional_user`` calls this immediately, which is right for the ~62
    endpoints whose only authorization input is the caller's identity. A
    handler in the CAPABILITY category (see ``get_optional_user_fail_open``)
    calls it later instead: after its capability check has declined to
    authorize the request, and never before.

    Deliberately NOT capability-aware itself. It would have to be handed the
    verdict, and a header-presence proxy for that verdict is worse than
    useless: it would let any caller suppress the 401 by sending a junk
    ``X-Embed-Token``, restoring the silent downgrade through a header anyone
    can set.
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

    fix(#1518 codex P2 round 3): the rule was applied at ONE exit point per
    handler, but a CAPABILITY handler has SEVERAL paths on which no capability
    authorized. An invalid embed token raised 403 and a missing signed template
    raised 403 without the rule ever running, so a caller with a dead bearer got
    a resource-status answer and a refresh-on-401 client never fired.

    Calling this instead of ``raise`` makes the ordering structural rather than
    positional: the credential rule cannot be skipped by adding another exit,
    because the exit itself goes through here. That is also what makes it
    checkable — a test can require every capability-declined raise in these
    handlers to route through this function, which it could not do for "the
    handler calls the helper somewhere".

    ``exc`` is the answer for a caller whose credential is fine: an invalid
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

    The raw resolution shared by both optional-identity dependencies below.
    ``None`` here means "no identity resolved", which is NOT the same as "no
    credential was supplied" — an expired, revoked, or mistyped credential
    lands on the same ``None``. Deciding what that means is the caller's job:
    ``get_optional_user`` refuses it, ``get_optional_user_fail_open`` does not.
    Splitting the resolution out is what stops the #1518 answer from being
    duplicated alongside a copy of the resolution logic, which is how the two
    answers drifted apart the first time.
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

    # fix(#1455): a matching token_version is not proof the token postdates the
    # last revocation — a rotation racing that revocation reads the pre-bump
    # value and mints a token carrying it. The horizon is the check that does
    # not depend on when the claim was read.
    if _predates_revocation_horizon(payload, user):
        return None

    return user


async def get_optional_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db),
) -> Identity | None:
    """Resolve the caller on an anonymous-capable endpoint. FAIL-CLOSED.

    A credentialless request resolves to ``None`` and keeps the public path
    (public datasets served, private ones absent). A request that SUPPLIED a
    credential which does not resolve — expired, revoked, mistyped — gets 401.

    fix(#401): the OGC/STAC read handlers resolved a stale/revoked token to the
    anonymous path, so a credentialed caller's private dataset 404'd instead of
    401ing and the client's refresh-on-401 retry never fired.

    fix(#1518): that reasoning was never specific to OGC and STAC, but the fix
    was. It lived in a separate ``get_optional_user_or_401`` and reached the 8
    handlers whose routers were in scope; the other 58 kept this dependency and
    kept silently downgrading. Seen through a list endpoint the same bug is
    quieter than the 404 #401 describes and worse: the caller gets 200 and the
    public subset, with no way to tell "my key expired last night" from "this
    catalog holds nothing else". Which answer a caller got was decided by which
    router happened to get patched, so it could be neither predicted nor
    documented.

    The rule lives HERE now, so every site inherits it instead of opting in.
    ``get_optional_user_fail_open`` is the one sanctioned way out, and its
    users are pinned by ``tests/test_optional_auth_failure_mode_1518.py``.
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

    This dependency does not judge the credential. A supplied-but-unresolvable
    one resolves to ``None`` here and the handler decides what that means.

    There are exactly TWO sanctioned categories, stated so a future entry is
    judged against a bar rather than against how inconvenient a 401 would be.

    **RECOVERY** — an endpoint whose job is to recover from a dead credential.
    Refusing the caller because the very credential they are trying to discard
    is dead is circular: it makes the broken state permanent. ``/auth/logout``
    is the case. It accepts the refresh cookie or a body token when the access
    JWT has aged out (fix(#1446)) and raises its own 401 when nothing presented
    resolves, so it stays fail-closed on its own terms.

    **CAPABILITY** — an endpoint that can be authorized by something OTHER than
    the caller's identity, currently an embed token. A capability authorizes a
    specific resource on its own and does not depend on who is asking, so a
    stale session bearer sent alongside it is noise rather than a failed
    authorization attempt. The rule is not waived for these, only RESEQUENCED:
    the handler evaluates the capability first and calls
    ``reject_unresolvable_credentials`` on the path where no capability
    authorized the request. A CAPABILITY entry that does not call it is a hole,
    so the structural test requires the call rather than trusting the label.

    Why the resequencing lives in the handlers and not in
    ``request_carries_credentials``: deciding whether a capability is VALID
    needs a DB session and the resource id (``validate_embed_token_access``
    takes both, and ``/tiles/tokens/`` resolves many ids in a loop), neither of
    which a header predicate has. Degrading it to "an embed header is present"
    would let any caller suppress the 401 with a junk header, which is #1518
    again wearing a different hat.

    Every user of this dependency must be listed in ``FAIL_OPEN_ALLOWLIST`` in
    ``tests/test_optional_auth_failure_mode_1518.py`` with its category and
    justification. That test walks the route table and fails on an unlisted
    one, which is what keeps the exception list from growing by accident — the
    way the 8/58 split grew in the first place.
    """
    return await _resolve_optional_identity(request, token, db)


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

    fix(#1518): it delegates to ``get_optional_user`` rather than to the raw
    resolver, so it inherits the fail-closed rule. What this variant opts out
    of is the SCHEMA marker, never the failure mode — pointing it at
    ``_resolve_optional_identity`` would silently restore the split on the
    public STAC routes without tripping the fail-open allowlist.
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

    # fix(#1455): a matching token_version is not proof the token postdates the
    # last revocation — a rotation racing that revocation reads the pre-bump
    # value and mints a token carrying it. The horizon is the check that does
    # not depend on when the claim was read.
    if _predates_revocation_horizon(payload, user):
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
