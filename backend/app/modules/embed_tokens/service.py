import asyncio
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import structlog
from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.edition import is_enterprise
from app.core.public_urls import (
    get_configured_public_app_url,
    is_loopback_host,
    is_usable_public_origin,
)
from app.core.tenancy import is_multi_tenant
from app.platform.cache import tenant_cache_context_available, tenant_cache_key
from app.platform.cache.provider import get_cache
from app.platform.cache.revocation import (
    UNKNOWN_GENERATION,
    bump_revocation_generation,
    current_revocation_generation,
    is_usable_generation,
)
from app.modules.embed_tokens.models import EmbedToken
from app.modules.embed_tokens.schemas import (
    ADVANCED_SHARING_ERROR,
    _normalize_origin,
)
from app.modules.catalog.maps.sharing import (
    find_map_ids_by_name,
    get_map_embed_scope,
    get_map_names,
    map_contains_dataset,
)
from app.platform.extensions import get_processing_port

logger = structlog.stdlib.get_logger(__name__)


# fix(#1778): codebase audit 2026-08-30, "Embed-token revocation invalidates the
# Redis positive cache BEFORE the caller's commit, so a concurrent request can
# re-cache the still-active token and keep it serving for 300s".
#
# Every revoke path here flips ``is_active`` and evicts the positive entry while
# its caller's transaction is still open; the caller commits later (a share
# revoke commits 17 lines further down router_sharing.py). In that window a tile
# or feature request for the same token misses the cache, SELECTs the row --
# which a plain READ COMMITTED read still sees as active, because it does not
# block on the revoking transaction -- and writes a fresh positive entry that
# outlives the commit. The cache-hit path re-checks only ``expires_at``
# (SEC-014), so every subsequent request off that entry is granted, for up to
# the full TTL. That is exactly what builder-audit #338 P0-01 set out to remove.
#
# Deleting the key cannot close that window from either side: the reader's write
# lands after the deleter's delete. So a revocation writes a DENIAL under the
# key instead of removing it, and the reader publishes its positive entry with
# ``set_if_absent`` rather than ``set``. Whichever of the two lands first, the
# denial is what survives: if the denial is already there the reader's NX write
# is refused, and if the reader got there first the denial overwrites it. The
# request that raced still completes -- it read a committed-active row and
# nothing about it was wrong at the time -- but it leaves nothing behind.
#
# The denial's TTL must cover the longest positive entry a racer could have
# tried to write, which is the 300s cap in validate_embed_token_access.
#
# The trade: a revoking transaction that ROLLS BACK leaves its denial in place,
# so a token that is still active is refused until the entry expires and the
# next request reads the database again. That direction is fail-closed and
# self-healing, and it is the one to be wrong in.
EMBED_TOKEN_REVOCATION_DENIAL_TTL_SECONDS = 300

# fix(#1778 codex r3): named because it is the bound on a residual rather than a
# tuning knob. A worker that took no traffic at all during a Redis outage never
# opened its circuit, so it never learns it should re-read the revocation
# generation, and it keeps trusting whatever Redis holds for a token until that
# entry expires. This number is how long that can last: five minutes. See the
# residual section of platform/cache/revocation.py. Lowering it shortens the
# exposure and costs a database read per token per interval; raising it does the
# reverse.
EMBED_TOKEN_POSITIVE_TTL_SECONDS = 300


def _embed_token_cache_key(token_hash: str) -> str:
    """Return the active tenant's validation-cache key.

    A token presented through the wrong hosted tenant must not populate a
    fleet-global negative entry that can deny the token's rightful tenant.
    ``tenant_cache_key`` preserves the historical key byte-for-byte in
    single-tenant mode and fails closed without a hosted tenant context.
    """
    return tenant_cache_key(f"embed_token:{token_hash}")


async def _deny_revoked_embed_tokens(db: AsyncSession, *token_hashes: str) -> None:
    """Stamp a denial over each revoked token's validation-cache entry.

    Best-effort, like the eviction it replaces: a cache failure must not break
    the revocation, which is what the database row records. See the module note
    on EMBED_TOKEN_REVOCATION_DENIAL_TTL_SECONDS for why this writes a denial
    rather than deleting the key.

    fix(#1778 codex r3): also advances the cluster-global revocation generation.
    The denial below is written through this worker's cache provider, and during
    a Redis outage that reaches no other worker; the generation is a database row
    every worker consults, so it is what carries the revocation across the
    process boundary.

    fix(#1778 codex r4): the bump shares the CALLER's transaction, so it becomes
    visible at the same instant as the ``is_active`` flip the caller has already
    made. An earlier draft advanced a non-transactional sequence and published it
    to Redis before the commit, which let a concurrent validator read the new
    generation, read the token row as still active, and cache a positive stamped
    with the new generation that then survived the commit. Ordering alone cannot
    fix that; sharing the transaction does, because there is no instant at which
    one is visible and the other is not.

    It is also why this raises nothing on failure but the bump is NOT wrapped in
    its own try/except: a bump that fails has poisoned the caller's transaction,
    and swallowing it would let the revocation commit without the generation
    that tells every other worker about it.
    """
    if not token_hashes:
        return
    await bump_revocation_generation(db)
    try:
        cache = get_cache()
        for token_hash in token_hashes:
            # fix(#1778 codex r1): set_authoritative, not set. `set` routes to
            # whichever store the circuit breaker says is live, so a positive
            # entry that landed in the in-memory fallback during a Redis outage
            # survived a denial written after Redis recovered, and the next
            # Redis error served the revoked token again. The denial has to
            # reach every store a later read could consult.
            await cache.set_authoritative(
                _embed_token_cache_key(token_hash),
                {"is_valid": False},
                ttl=EMBED_TOKEN_REVOCATION_DENIAL_TTL_SECONDS,
            )
    except Exception:  # broad: cache invalidation must not break callers; redis can throw varied pool/timeout errors
        logger.error("Cache invalidation failed for embed token", exc_info=True)


# Phase 268 H-31: loopback IP set used to gate the localhost-Origin bypass.
# The Origin header alone is trivially forgeable from non-browser callers
# (curl, server-side scripts, CLIs) — they can simply set
# ``Origin: http://localhost`` and bypass any allowed_origins whitelist.
# To prevent that, the bypass now also requires ``request.client.host`` to
# be a loopback IP (which a remote attacker cannot forge — ``client.host``
# is the actual TCP peer address).
#
# fix(#1555): stays an exact set while _is_localhost_origin became a range
# check, and the asymmetry is the point. This one GATES the bypass, so its
# failure direction is to deny — a peer at 127.0.0.2 simply does not get the
# development shortcut. The other one decides whether a domain lock can be
# enforced, where the same miss ISSUES a lock that can never work. Widening
# this would hand the bypass to more callers, which is not what #1555 asks for.
_LOOPBACK_CLIENT_IPS = frozenset({"127.0.0.1", "::1", "localhost"})


# BUG-028: storage (allowed_origins, via schemas._validate_origins) and
# request-origin extraction now share ONE bracket-preserving normalizer
# (schemas._normalize_origin), so an IPv6 literal like 'http://[::1]:8080'
# byte-matches between the stored allowlist and the live request origin.


def _is_localhost_origin(origin: str) -> bool:
    """Is this origin one that only reaches the machine it is opened on?

    fix(#1555): the host set this used to consult named ``127.0.0.1`` and
    nothing else in ``127.0.0.0/8``, so ``http://127.0.0.2:8080`` was read as a
    routable public origin and ``assert_domain_lock_is_enforceable`` permitted a
    domain lock every recipient resolves to their own machine. Loopback is a
    RANGE; ``is_loopback_host`` (app/core/public_urls.py) states it once, and
    the frontend mirrors it in ``isLoopbackHostname``.
    """
    parsed = urlparse(origin.lower().rstrip("/"))
    return is_loopback_host(parsed.hostname or "")


def _client_is_loopback(request: Request) -> bool:
    """Phase 268 H-31: True iff the actual TCP peer is a loopback IP.

    ``request.client.host`` is the TCP-connection peer address, set by the
    ASGI server from the actual socket — it cannot be forged via headers.
    Used to gate the legacy localhost-Origin bypass so non-browser callers
    on a remote host can no longer trivially set ``Origin: http://localhost``
    to bypass the allowed_origins whitelist.
    """
    if request.client is None:
        return False
    return (request.client.host or "").lower() in _LOOPBACK_CLIENT_IPS


def extract_request_origin(request: Request) -> str | None:
    """Extract and normalize origin from Origin or Referer header.

    Uses the shared (bracket-preserving) schema normalizer so request origins
    byte-match the stored allowed_origins. That normalizer rejects wildcard /
    unparseable origins with ValueError; a forged header must fail closed
    (return None → the caller denies access) rather than raise.
    """
    origin = request.headers.get("origin")
    if origin:
        try:
            return _normalize_origin(origin)
        except ValueError:
            return None

    referer = request.headers.get("referer")
    if referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.hostname:
            try:
                return _normalize_origin(f"{parsed.scheme}://{parsed.netloc}")
            except ValueError:
                return None

    return None


async def _resolve_self_origins(db: AsyncSession, request: Request) -> set[str]:
    """Return the normalized origins that ARE this GeoLens deployment.

    fix(#1531): every candidate here is server-derived. The embedder's origin is
    deliberately NOT reconstructed from anything the caller sends — a
    client-forwarded embedder origin would replace a check that visibly fails
    with one that only appears to work.

    * The EXPLICITLY configured ``PUBLIC_APP_URL``, via
      ``get_configured_public_app_url``. Deliberately not ``get_public_app_url``:
      that one is a resolver, and both of its fallbacks name something other
      than the host our embed shell is served from — an ``/api``-stripped
      ``PUBLIC_API_URL``, or (fix #1531) the caller's own ``Origin`` / ``Referer``
      headers, which would make EVERY origin "self" and the allowlist vacuous.
      See its docstring for why an unset value is a legitimate answer here.
    * In hosted multi-tenant, the tenant origin that the tenant-context
      middleware derived from a Host that resolved against the tenant registry
      (``request.state.tenant_public_origin`` is set only after that lookup, and
      the request is rejected outright when the lookup cannot form a trusted
      origin). The fleet-wide public app URL cannot represent a tenant host, so
      without this a hosted domain-locked embed would stay broken.
    """
    origins: set[str] = set()

    # Gated on the mode that populates it: TenantContextMiddleware returns
    # early in single_tenant, so the attribute is never set there. Reading it
    # only under is_multi_tenant() keeps that invariant local rather than
    # depending on middleware ordering staying the way it is today.
    if is_multi_tenant():
        tenant_origin = getattr(request.state, "tenant_public_origin", None)
        if tenant_origin and is_usable_public_origin(tenant_origin):
            try:
                origins.add(_normalize_origin(tenant_origin))
            except ValueError:
                pass

    # fix(#1548 review P2): this lookup reads an AppSetting row on a 60s-cold
    # cache, so it is the one part of the domain-lock check that can fail for
    # reasons unrelated to the decision. An authorization helper must fail
    # CLOSED on that, not propagate: every other denial in this module returns
    # a bool, and letting a DB error escape would turn a routine deny into a
    # 500 on the tile path. Resolving no self-origins denies, which is correct.
    try:
        app_url = await get_configured_public_app_url(db)
    except Exception:  # broad: any lookup failure must deny, never raise
        logger.warning("embed_self_origin_lookup_failed", exc_info=True)
        return origins
    if app_url is None:
        return origins

    # fix(#1548 review r8): the shape gate runs BEFORE normalization, because
    # normalization is what hides the problem. `_normalize_origin` prepends
    # https:// to anything lacking an http(s) scheme, so an environment value of
    # `ftp://maps.example.com` arrives here as the plausible-looking, non-loopback
    # `https://ftp:` — and `assert_domain_lock_is_enforceable` then reads the
    # deployment as configured and issues a lock no embed shell can satisfy.
    # `is_usable_public_origin` is the single statement of that rule, mirrored by
    # parseUsablePublicUrl in frontend/src/lib/public-urls.ts.
    if is_usable_public_origin(app_url):
        try:
            origins.add(_normalize_origin(app_url))
        except ValueError:
            pass

    return origins


async def _request_origin_is_allowed(
    db: AsyncSession,
    request: Request | None,
    allowed_origins: list[str] | None,
) -> bool:
    """Single reader for an embed token's domain lock.

    ``resolve_embed_scope_for_map`` and ``validate_embed_token_access`` both
    gate on ``allowed_origins``; they used to carry separate copies of this
    policy, so a change to one silently left the other on the old rules. They
    now share this one implementation.

    fix(#1531): domain locking was enforced in two layers that disagreed. The
    ``/m/{token}`` embed shell is served with ``frame-ancestors 'self'
    <allowed_origins>`` (see ``build_embed_frame_ancestors``) — a real,
    browser-enforced control keyed on the PARENT page's actual origin. This
    API-layer allowlist sat below it and accepted only ``<allowed_origins>``,
    with no ``'self'`` equivalent. But an API subresource request issued from
    inside the embed iframe carries the SHELL's origin, never the embedder's:
    the requesting document is our own shell, so a same-origin GET sends no
    ``Origin`` header at all and the ``Referer`` fallback is the shell's own
    URL. The parent's origin is simply not on a subresource request; it is
    visible only on the NAVIGATION that loads the iframe, which is exactly
    where ``frame-ancestors`` already enforces it. Every scoped-layer request
    from a domain-locked embed therefore resolved to our own origin, matched
    nothing in ``allowed_origins`` (the operator puts the CUSTOMER's domain
    there), and was denied — the feature was broken closed, delivering nothing
    to any iframe embed.

    Accepting our own origin restores the ``'self'`` half the CSP directive
    already had: by the time the shell can run a line of script, the browser
    has already enforced the domain lock at the document layer.

    The check is NOT removed, because it is correct on the other path: an embed
    token driven from the customer's own JavaScript rather than through the
    ``/m/`` iframe does arrive with ``Origin: https://customer.example.com``,
    and there the allowlist works as designed.

    Known and unavoidable consequence: a TOP-LEVEL navigation to the shell
    (not framed) sends byte-identical headers to the framed case, so it is
    accepted too. No header distinguishes them — ``Sec-Fetch-Site`` on the
    subresource is ``same-origin`` either way. Any fix that makes the iframe
    work makes direct navigation work; what still gates that path is possession
    of the token itself, which is the capability (SEC-022).
    """
    if not allowed_origins:
        return True
    if request is None:
        return False
    origin = extract_request_origin(request)
    if origin is None:
        return False
    if origin in allowed_origins:
        # Both sides are pre-normalized: allowed_origins by
        # schemas._validate_origins, origin by extract_request_origin.
        return True
    # Phase 268 H-31 localhost-development bypass, unchanged: the Origin header
    # alone is trivially forgeable, so it is gated on the actual TCP peer also
    # being loopback.
    if _is_localhost_origin(origin) and _client_is_loopback(request):
        return True

    self_origins = await _resolve_self_origins(db, request)
    if origin in self_origins:
        return True

    # fix(#1548 review P2): a deployment that never sets PUBLIC_APP_URL still
    # gets one. Both docker-compose.yml and docker-compose.prod.yml inject
    # ``${PUBLIC_APP_URL:-http://localhost:8080}``, and .env.example ships the
    # line commented out, so a self-hoster serving https://maps.example.com
    # resolves a self-origin of http://localhost:8080 and their domain-locked
    # embeds stay empty. The server cannot fix that for them: every
    # request-derived alternative (Host, X-Forwarded-Host, request.url) is
    # settable by anyone who can point a DNS name at the deployment, which
    # would make the lock bypassable by the exact parties it excludes. So log
    # the mismatch with the remediation instead of guessing, and keep the
    # denial. Fires only for a domain-locked token that already missed both
    # the allowlist and the loopback bypass, so this is not a hot path.
    logger.warning(
        "embed_token_domain_lock_denied",
        request_origin=origin,
        self_origins=sorted(self_origins),
        allowed_origins=sorted(allowed_origins),
        remediation=(
            "If this deployment serves the embed shell from request_origin, "
            "set PUBLIC_APP_URL (or the public_app_url setting) to it. The "
            "embed shell's own API calls carry the shell's origin, so they "
            "are only recognized as first-party when that value is correct."
        ),
    )
    return False


class DomainLockNotEnforceableError(Exception):
    """Raised when a domain lock is requested that this deployment cannot enforce.

    Deliberately NOT a ``ValueError``: both write handlers map ``ValueError`` to
    400 for the advanced-sharing edition gate, and this is a distinct condition
    with its own status code.
    """


async def assert_domain_lock_is_enforceable(
    db: AsyncSession, request: Request, allowed_origins: list[str] | None
) -> None:
    """Refuse to issue a domain lock this deployment could never enforce.

    fix(#1548 review P2). Domain locking only works when the deployment knows
    its own public origin, because the embed shell's API calls carry the
    SHELL's origin (see ``_request_origin_is_allowed``). That value comes from
    configuration, and the configuration has a default that is wrong for almost
    every real install: ``docker-compose.yml`` and ``docker-compose.prod.yml``
    both inject ``${PUBLIC_APP_URL:-http://localhost:8080}``, and
    ``.env.example`` ships the line commented out. So a self-hoster reached at
    https://maps.example.com who never set it resolves a self-origin of
    ``http://localhost:8080``, and the #1531 fix that makes domain-locked
    embeds work is inert for them: their embeds stay empty, with nothing said
    at the moment they made the mistake.

    We do not infer the serving origin to paper over that. Every unconfigured
    source (``Host``, ``X-Forwarded-Host``, ``request.url``) is settable by
    anyone who can point a DNS name at the deployment, so an inferred
    self-origin would be satisfiable by exactly the parties a domain lock
    excludes — a control any caller can satisfy is not a control. The operator
    has to tell us; this makes them tell us when they turn the lock on rather
    than silently on every later viewer request.

    THE REFUSAL CONDITION is deliberately narrow: the creating request arrived
    at a real, non-loopback origin, and every origin this deployment believes
    is itself is a loopback one. That pair is a *proof* of unenforceability
    rather than a guess — an embed shell served from a routable hostname can
    never present ``http://localhost:8080`` as its origin, so the lock could
    only ever deny. Two weaker predicates were rejected:

    * "the configured value is absent" cannot be detected at all. Compose
      injects the localhost default into the environment, so
      ``settings.public_app_url`` is a non-empty string and ``unset`` and
      ``deliberately localhost`` are byte-identical here.
    * "the creating origin differs from the configured one" refuses a
      deployment that is configured correctly. An operator whose GeoLens is
      public at https://maps.example.com but administered over an internal
      hostname has a working lock — the embed snippet, like every other public
      link, is built from ``PUBLIC_APP_URL``, so viewers load the shell from
      the configured origin and the runtime check passes. Blocking them would
      trade codex's silent failure for a loud one on a healthy install.

    A typo'd (rather than defaulted) ``PUBLIC_APP_URL`` is therefore NOT caught
    here, by choice; the ``embed_token_domain_lock_denied`` warning logged by
    ``_request_origin_is_allowed`` carries that case with the same remediation.

    The comparison reads the creating request's own ``Origin``, which IS a
    caller-controlled header. Sound here because it is a *diagnostic*, not an
    authorization decision: it can only refuse to mint a token, never grant
    access, and the caller is an already-authenticated map owner. Forging it
    only denies yourself.

    Skipped when the request carries no browser origin at all (a CLI or SDK
    caller sends neither ``Origin`` nor ``Referer``), and when that origin is
    itself loopback (a developer on ``localhost``/Vite is not the install this
    is aimed at, and their runtime check passes either through the H-31
    loopback bypass or through the localhost self-origin).
    """
    if not allowed_origins:
        # Clearing or omitting a domain lock is always allowed.
        return

    if not is_enterprise():
        # Domain locking is an advanced-sharing control, so create/update is
        # about to reject this with ADVANCED_SHARING_ERROR regardless. Returning
        # here keeps that the message the operator sees: telling a Community
        # deployment to go fix PUBLIC_APP_URL would point at the wrong problem.
        return

    origin = extract_request_origin(request)
    if origin is None or _is_localhost_origin(origin):
        return

    self_origins = await _resolve_self_origins(db, request)
    if any(not _is_localhost_origin(o) for o in self_origins):
        return

    # Keep this wording stable: frontend/src/lib/error-map.ts matches it to
    # render the remediation, since an unmapped 422 detail collapses to the
    # generic "validation failed" toast and the point of this refusal is the
    # prose.
    resolved = ", ".join(sorted(self_origins)) or "nothing usable"
    raise DomainLockNotEnforceableError(
        "Domain locking cannot be enforced by this deployment: its public app "
        f"URL resolves to {resolved}, but this request reached it at {origin}. "
        "An embed shell's own API calls carry the shell's origin, so a "
        "domain-locked token issued now would load an empty map. Set "
        f"PUBLIC_APP_URL (or the public_app_url setting) to {origin} and try "
        "again."
    )


def build_embed_frame_ancestors(
    *, is_valid: bool, allowed_origins: list[str] | None
) -> str:
    """Build the CSP ``frame-ancestors`` directive for the /m/{token} embed shell.

    builder-audit #338 P0-02: domain restrictions previously protected only the
    tile/data calls, not the embeddable HTML document itself, so any site could
    frame the shell. The validated edge route emits a per-token frame-ancestors
    policy derived from ``EmbedToken.allowed_origins``:

    - Invalid / revoked / expired token  -> ``frame-ancestors 'none'`` (fail
      closed: the shell cannot be framed anywhere).
    - Valid token WITH allowed_origins    -> ``frame-ancestors 'self' <origins>``
      (only the configured domains may frame; the browser blocks all others
      before app bootstrap).
    - Valid token WITHOUT allowed_origins -> ``""`` (unrestricted Community
      embed: open framing is intentional and explicit — no directive is emitted
      so the shell stays frameable on any site; we never emit the forbidden
      ``frame-ancestors *``, preserving the codebase no-wildcard invariant).

    CRLF / wildcard entries are dropped (defense-in-depth on top of the
    schema-layer _validate_origins 422 rejection) to prevent header splitting and
    accidental clickjacking-protection bypass from any stale DB row.
    """
    if not is_valid:
        return "frame-ancestors 'none'"
    safe: list[str] = []
    for o in allowed_origins or []:
        if not o or "\r" in o or "\n" in o or "*" in o or not o.strip():
            continue
        safe.append(o.strip())
    if not safe:
        # Unrestricted Community embed -> intentional, explicit open framing.
        return ""
    return f"frame-ancestors 'self' {' '.join(safe)}"


async def create_embed_token(
    db: AsyncSession,
    map_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    expires_in_days: int = 30,
    name: str | None = None,
    allowed_origins: list[str] | None = None,
) -> tuple[EmbedToken, str]:
    """Create an embed token with a frozen dataset scope snapshot.

    If an active, non-expired token already exists for this map, it is
    revoked before creating a new one (one active token per map).

    Returns (token_record, raw_token). The raw token is only available at creation.
    """
    if not is_enterprise() and (expires_in_days != 30 or bool(allowed_origins)):
        raise ValueError(ADVANCED_SHARING_ERROR)

    # Revoke any existing active tokens for this map
    existing = await db.execute(
        select(EmbedToken)
        .where(
            EmbedToken.map_id == map_id,
            EmbedToken.is_active.is_(True),
        )
        .with_for_update()
    )
    revoked_hashes: list[str] = []
    for old_token in existing.scalars().all():
        old_token.is_active = False
        revoked_hashes.append(old_token.token_hash)

    # Best-effort cache invalidation for revoked tokens
    await _deny_revoked_embed_tokens(db, *revoked_hashes)

    # Generate raw token
    raw_token = "et_" + secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    token_hint = "et_..." + raw_token[-8:]

    # Snapshot dataset_ids from map layers
    map_scope = await get_map_embed_scope(db, map_id)
    dataset_ids = (
        [str(dataset_id) for dataset_id in map_scope.dataset_ids] if map_scope else []
    )

    if not dataset_ids:
        raise ValueError("Map has no layers to scope")

    # EMBED-01 (Phase 1212): stamp tenant_id from Map.tenant_id — derived
    # server-side, NEVER from a client header or function argument.
    # Inert (None) in single_tenant so behavior is byte-identical.
    map_tenant_id = map_scope.tenant_id if map_scope else None
    token_tenant_id = map_tenant_id if is_multi_tenant() else None

    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    token = EmbedToken(
        map_id=map_id,
        token_hash=token_hash,
        token_hint=token_hint,
        name=name,
        scoped_dataset_ids=dataset_ids,
        allowed_origins=allowed_origins or None,
        expires_at=expires_at,
        created_by=user_id,
        tenant_id=token_tenant_id,
    )
    db.add(token)
    await db.flush()

    return token, raw_token


async def list_embed_tokens(
    db: AsyncSession,
    map_id: uuid.UUID,
) -> list[EmbedToken]:
    """List all embed tokens for a map, ordered by created_at desc."""
    result = await db.execute(
        select(EmbedToken)
        .where(EmbedToken.map_id == map_id)
        .order_by(EmbedToken.created_at.desc())
        .limit(100)
    )
    return list(result.scalars().all())


async def revoke_embed_token(
    db: AsyncSession,
    token_id: uuid.UUID,
    map_id: uuid.UUID,
) -> EmbedToken | None:
    """Revoke an embed token by setting is_active=False."""
    result = await db.execute(
        select(EmbedToken).where(
            EmbedToken.id == token_id,
            EmbedToken.map_id == map_id,
        )
    )
    token = result.scalar_one_or_none()
    if token is None:
        return None

    token.is_active = False
    await db.flush()

    # Best-effort cache invalidation
    await _deny_revoked_embed_tokens(db, token.token_hash)

    return token


async def revoke_embed_tokens_by_map(
    db: AsyncSession,
    map_id: uuid.UUID,
) -> int:
    """Revoke ALL active embed tokens for a map and purge their Redis cache.

    builder-audit #338 P0-01: embed tokens survived share revocation and visibility
    downgrades because the maps router's revoke / public->non-public paths only
    flipped ``MapShareToken.is_active`` (via ``revoke_share_token_by_map``) and
    never touched ``EmbedToken``. A copied embed token therefore kept serving
    tiles until its natural expiry. The maps router wires THIS function into the
    share-revoke, public->non-public visibility-downgrade, and layer-change
    paths so a revoked map's embed tokens stop validating immediately.

    Deactivates every active token for the map AND deletes its positive-cache
    entry so the 5-minute cache TTL cannot extend access past revocation.

    Returns the number of tokens revoked.
    """
    result = await db.execute(
        select(EmbedToken).where(
            EmbedToken.map_id == map_id,
            EmbedToken.is_active.is_(True),
        )
    )
    tokens = list(result.scalars().all())
    if not tokens:
        return 0

    for token in tokens:
        token.is_active = False
    await db.flush()

    # Best-effort cache invalidation — a cached positive entry must not outlive
    # the revocation (builder-audit #338 P0-01 acceptance: Redis positive cache does
    # not extend access).
    await _deny_revoked_embed_tokens(db, *(token.token_hash for token in tokens))

    return len(tokens)


async def revoke_embed_tokens_for_dropped_datasets(
    db: AsyncSession,
    map_id: uuid.UUID,
) -> int:
    """builder-audit #338 P0-01: revoke embed tokens orphaned by a layer change.

    An embed token is scoped to a fixed set of dataset ids that were layers on
    the map when it was minted. After a layer replacement/removal, a token scoped
    to a dataset that is no longer a layer on the map would keep serving tiles for
    content the map no longer exposes. We compare each active token's
    ``scoped_dataset_ids`` against the map's current layer dataset ids; if any
    active token references a dropped dataset we revoke ALL embed tokens for the
    map via ``revoke_embed_tokens_by_map`` (the map-scoped revoke primitive, which
    also purges the Redis positive cache). Pure additions/reorders that keep every
    scoped dataset present do not revoke anything. Returns the number revoked.
    """
    map_scope = await get_map_embed_scope(db, map_id)
    current_ids = (
        {str(dataset_id) for dataset_id in map_scope.dataset_ids}
        if map_scope is not None
        else set()
    )

    result = await db.execute(
        select(EmbedToken).where(
            EmbedToken.map_id == map_id,
            EmbedToken.is_active.is_(True),
        )
    )
    for token in result.scalars().all():
        scoped = {str(d) for d in (token.scoped_dataset_ids or [])}
        if not scoped.issubset(current_ids):
            return await revoke_embed_tokens_by_map(db, map_id)
    return 0


async def get_active_embed_token(
    db: AsyncSession,
    token_id: uuid.UUID,
    map_id: uuid.UUID,
) -> EmbedToken | None:
    """Load the active token a write targets, or None if there is none.

    fix(#1548 review r2): exists so a caller can settle whether the resource is
    THERE before applying a precondition about the deployment. The router asks
    first and 404s; ``update_embed_token`` asks again when it goes to write.
    Both go through this one query so the "which token does this PATCH mean"
    rule cannot drift between them.
    """
    result = await db.execute(
        select(EmbedToken).where(
            EmbedToken.id == token_id,
            EmbedToken.map_id == map_id,
            EmbedToken.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def update_embed_token(
    db: AsyncSession,
    token_id: uuid.UUID,
    map_id: uuid.UUID,
    allowed_origins: list[str] | None,
) -> EmbedToken | None:
    """Update allowed_origins on an embed token. Invalidates cache."""
    if not is_enterprise() and bool(allowed_origins):
        raise ValueError(ADVANCED_SHARING_ERROR)

    token = await get_active_embed_token(db, token_id, map_id)
    if token is None:
        return None

    token.allowed_origins = allowed_origins or None
    await db.flush()

    # Invalidate cache so changes take effect immediately
    try:
        cache = get_cache()
        await cache.delete(_embed_token_cache_key(token.token_hash))
    except Exception:  # broad: cache invalidation must not break callers; redis can throw varied pool/timeout errors
        logger.error("Cache invalidation failed for embed token", exc_info=True)

    return token


async def resolve_embed_scope_for_map(
    db: AsyncSession,
    raw_token: str,
    map_id: uuid.UUID,
    request: Request | None = None,
) -> set[uuid.UUID]:
    """Resolve the dataset ids an embed token authorizes for ``map_id``.

    fix(#394) SH-01/B-023: embed tokens are a private-dataset capability
    (SEC-022 posture) — the tile path has always honored them, but the
    shared-map metadata endpoint dropped non-visible datasets, so an embed
    with a valid scoped token could never even construct those layers.
    This helper lets ``get_shared_map`` widen its visibility filter to the
    token's snapshot scope.

    Fail-closed: returns an empty set (never raises) when the token is
    unknown, inactive, expired, bound to a different map, or fails the
    origin allowlist — the same rules as ``validate_embed_token_access``.
    The ``map_id`` equality also pins the tenant implicitly (map ids are
    globally unique; callers resolved ``map_id`` from their own share
    token), so no separate tenant-equality re-check is needed here.
    Unlike the per-tile validator there is no caching or usage tracking:
    the metadata endpoint is low-QPS and called once per viewer load.
    """
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    result = await db.execute(
        select(EmbedToken).where(
            EmbedToken.token_hash == token_hash,
            EmbedToken.map_id == map_id,
            EmbedToken.is_active.is_(True),
            EmbedToken.expires_at > datetime.now(timezone.utc),
        )
    )
    token = result.scalar_one_or_none()
    if token is None:
        return set()

    # Domain-locking check — shares ONE policy reader with
    # validate_embed_token_access so the two cannot drift (fix #1531).
    if not await _request_origin_is_allowed(db, request, token.allowed_origins):
        return set()

    scoped: set[uuid.UUID] = set()
    for raw_id in token.scoped_dataset_ids or []:
        try:
            scoped.add(uuid.UUID(str(raw_id)))
        except ValueError:
            continue
    return scoped


async def validate_embed_token_access(
    raw_token: str,
    dataset_id: uuid.UUID,
    db: AsyncSession,
    request: Request | None = None,
) -> bool:
    """Validate an embed token grants access to a specific dataset.

    Uses cache with 5-min TTL, falling back to DB lookup.
    Checks allowed_origins when domain-locking is enabled.
    Tracks usage on cache miss with explicit commit.
    """
    # Hosted validation is meaningful only inside a verified tenant request or
    # worker context.  Return a generic denial instead of letting cache-key
    # construction raise, so an unscoped host cannot become an error oracle.
    if is_multi_tenant() and not tenant_cache_context_available():
        return False

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    cache_key = _embed_token_cache_key(token_hash)

    cache = get_cache()
    token: EmbedToken | None = None

    # fix(#1778 codex r3): the generation every positive entry is stamped with.
    # Read before the cache so a hit can be compared without a second
    # round-trip; platform/cache/revocation.py says why a process-local answer
    # is not enough here.
    generation = await current_revocation_generation(db)
    # fix(#1778 codex r5): an unreadable counter yields a SENTINEL, not a
    # generation. Stamping it on an entry, or comparing two entries by it, made
    # them compare EQUAL -- so a positive cached while the counter was
    # unreadable stayed trusted through a later revocation whose denial could
    # not reach shared Redis. When the generation is unusable the cache is
    # simply not used, in either direction: nothing is trusted and nothing is
    # written. Every validation then costs a database read, which is the right
    # price for not knowing whether anything has been revoked.
    generation_usable = is_usable_generation(generation)

    # Check cache first. security=True: a positive here decides access to
    # private data, so it may only come from the store every worker shares.
    cached = await cache.get(cache_key, security=True)
    if cached is not None and not cached.get("is_valid", False):
        return False

    # fix(#1778 codex r3): an entry minted before the latest revocation is not
    # evidence about the token now. A revoke performed while THIS worker could
    # not reach Redis is invisible to it in every other way; this comparison is
    # what makes it visible, because the generation advanced in the database,
    # which is the store that stayed up.
    #
    # An entry with NO stamp fails this too, which is what an entry written by a
    # pre-upgrade process looks like. The cost is one database re-validation per
    # live token in the minutes after a rolling deploy, and the alternative
    # (treating a missing stamp as current) would trust exactly the entries this
    # cannot vouch for.
    if cached is not None and (
        not generation_usable
        or not is_usable_generation(cached.get("generation", UNKNOWN_GENERATION))
        or cached.get("generation") != generation
    ):
        await cache.delete(cache_key)
        cached = None

    if cached is not None:
        # SEC-014: re-check expiry on every cache hit so a token cannot stay
        # valid for up to the 5-minute positive-cache TTL past its real
        # expires_at.  The cached dict now stores expires_at as an ISO string;
        # if the entry pre-dates the fix (no expires_at key) treat it as a
        # miss so the token is re-validated from the DB.
        now = datetime.now(timezone.utc)
        cached_expires_at_str = cached.get("expires_at")
        if cached_expires_at_str is None:
            # Stale cache entry without expiry info — evict and fall through.
            await cache.delete(cache_key)
            cached = None
        else:
            cached_expires_at = datetime.fromisoformat(cached_expires_at_str)
            if now >= cached_expires_at:
                # Token has expired since it was cached — evict and deny.
                await cache.delete(cache_key)
                return False
            allowed_origins = cached.get("allowed_origins")
            scoped_dataset_ids = cached.get("scoped_dataset_ids", [])

    if cached is None:
        # Cache miss -- query DB
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(EmbedToken).where(
                EmbedToken.token_hash == token_hash,
                EmbedToken.is_active.is_(True),
                EmbedToken.expires_at > now,
            )
        )
        token = result.scalar_one_or_none()

        if token is None:
            # Cache negative result. security=True keeps it out of the
            # process-local fallback for symmetry with the positive; a denial
            # would be safe there, but a store that only ever holds denials is
            # one fewer thing for a future reader to reason about.
            await cache.set(cache_key, {"is_valid": False}, ttl=300, security=True)
            return False

        allowed_origins = token.allowed_origins
        scoped_dataset_ids = token.scoped_dataset_ids

        # Cache positive result — include expires_at so every cache hit can
        # re-check expiry (SEC-014). Include tenant_id for EMBED-02 cache-hit
        # path so validate_embed_token_access can check tenant equality without
        # re-querying the EmbedToken row (Phase 1212).
        #
        # fix(#1778): set_if_absent, not set. The row this was read from is
        # committed-active, but a revocation may be open on it right now (a
        # plain READ COMMITTED select does not block on the revoking
        # transaction's lock), and that revocation has already stamped its
        # denial under this key. Overwriting it would restore the token for the
        # rest of this entry's TTL, which is the window builder-audit #338
        # P0-01 exists to close. See the module note on
        # EMBED_TOKEN_REVOCATION_DENIAL_TTL_SECONDS.
        seconds_until_expiry = (token.expires_at - now).total_seconds()
        cache_ttl = int(
            min(EMBED_TOKEN_POSITIVE_TTL_SECONDS, max(0, seconds_until_expiry))
        )
        # fix(#1778 codex r5): only publish an entry that carries a generation a
        # future reader can actually check it against.
        if generation_usable:
            await cache.set_if_absent(
                cache_key,
                {
                    "is_valid": True,
                    "scoped_dataset_ids": scoped_dataset_ids,
                    "allowed_origins": allowed_origins,
                    "map_id": str(token.map_id),
                    "expires_at": token.expires_at.isoformat(),
                    "tenant_id": str(token.tenant_id) if token.tenant_id else None,
                    # fix(#1778 codex r3): the generation this decision was made
                    # under. A later read compares it and refuses an entry that
                    # predates a revocation, which is how a revoke performed on
                    # another worker during a Redis outage reaches this one.
                    "generation": generation,
                },
                ttl=cache_ttl,
                security=True,
            )

    # Domain-locking check (before dataset scope check). Shares ONE policy
    # reader with resolve_embed_scope_for_map so the two cannot drift; the
    # H-31 localhost gating and the #1531 self-origin rule both live there.
    if not await _request_origin_is_allowed(db, request, allowed_origins):
        return False

    # Dataset scope check
    if str(dataset_id) not in scoped_dataset_ids:
        return False

    # EMBED-02 (Phase 1212): fail-closed tenant-equality predicate.
    # Inserted AFTER dataset scope check and BEFORE usage tracking.
    # Inert in single_tenant (is_multi_tenant() == False → guard skipped).
    # Denies on mismatch with no error-leak (return False, not raise).
    # SEC-022 invariant: private-serving is preserved — this is the ONLY new
    # check; there is NO public/published recheck introduced here.
    if is_multi_tenant():
        # Resolve token's tenant: DB-miss path uses the ORM object; cache-hit
        # path reads from the cached dict set above.
        if token is not None:
            token_tenant = token.tenant_id
        else:
            # Cache-hit path: tenant_id was stored in the positive-cache payload.
            raw_tid = cached.get("tenant_id") if cached else None  # type: ignore[union-attr]
            token_tenant = uuid.UUID(raw_tid) if raw_tid else None

        # Resolve dataset's tenant via a fresh query (no re-mint, no cache).
        dataset = await get_processing_port().get_dataset(db, dataset_id)
        dataset_tenant = getattr(dataset, "tenant_id", None) if dataset else None

        # CR-01 (Phase 1212): fail-closed guard — legacy tokens (pre-EMBED-01,
        # NULL tenant_id) and NULL-tenant datasets are denied in multi_tenant mode.
        # Without this, `None != None` evaluates to False and PASSES the equality
        # check, granting a NULL-tenant token access to any NULL-tenant dataset.
        if token_tenant is None or dataset_tenant is None:
            return False
        if token_tenant != dataset_tenant:
            return False

    # builder-audit #338 P0-01: fail-closed live layer-membership re-check.
    # scoped_dataset_ids is a creation-time snapshot. If the dataset's layer was
    # later removed from the map (or the whole map deleted), the snapshot is
    # stale and would still grant tile access until token expiry. Re-query the
    # map's CURRENT layer membership and deny if the requested dataset no longer
    # belongs to a live layer on the token's map. Runs on BOTH the cache-hit and
    # cache-miss paths so a cached positive entry cannot outlive a layer removal.
    # Note: this deliberately does NOT recheck Map.visibility — embed tokens are
    # a private-dataset capability (SEC-022), so a private map with private
    # layers must still serve via an active token. Share-revoke /
    # visibility-downgrade invalidation is enforced by revoke_embed_tokens_by_map.
    if token is not None:
        live_map_id: uuid.UUID | None = token.map_id
    else:
        raw_map_id = cached.get("map_id") if cached else None  # type: ignore[union-attr]
        live_map_id = uuid.UUID(raw_map_id) if raw_map_id else None
    if live_map_id is None:
        return False
    if not await map_contains_dataset(db, live_map_id, dataset_id):
        return False

    if token is not None:
        # Use a separate session so we don't commit the caller's request-scoped
        # `db` from inside this authorization helper — mirrors _resolve_api_key's
        # last_used_at bump in auth/dependencies.py. An early commit on `db`
        # would persist whatever uncommitted state the caller's transaction was
        # carrying before it decided to commit, and every caller today is a
        # read path (features/router.py, tiles/router.py), but that would stop
        # being true the moment a write endpoint gates on an embed token.
        #
        # fix(#1436 codex review): fired detached (asyncio.create_task), not
        # awaited. Authorization is already decided by this point, so the
        # bump is pure telemetry — it must never delay or fail an
        # already-valid access. A side session needs its own pool checkout
        # while the caller's connection is still held for the rest of this
        # request, and a burst of simultaneous cache-miss bumps (e.g. right
        # after a cache flush) could contend for the pool; even bounded with
        # a timeout, AWAITING that checkout here would still stall every
        # cache-miss authorization for up to the timeout. _usage_bump_tasks
        # holds a strong reference so asyncio cannot garbage-collect the task
        # mid-flight; its done-callback discards the reference once finished.
        task = asyncio.create_task(_bump_embed_token_usage_detached(token.id))
        _usage_bump_tasks.add(task)
        task.add_done_callback(_usage_bump_tasks.discard)

    return True


# fix(#1436 codex review): strong references for detached usage-bump tasks —
# see the comment in validate_embed_token_access for why they're fired this
# way instead of awaited.
_usage_bump_tasks: set[asyncio.Task] = set()


async def _bump_embed_token_usage_detached(token_id: uuid.UUID) -> None:
    """Best-effort use_count/last_used_at bump, isolated from the caller.

    Bounded with a timeout so a starved pool doesn't leave the task running
    indefinitely; any failure (pool contention or otherwise) is logged and
    swallowed rather than propagated — there is no caller left to catch it.
    """
    try:
        await asyncio.wait_for(_bump_embed_token_usage(token_id), timeout=3.0)
    except Exception:  # broad: detached telemetry task must never raise
        logger.warning("embed_token_usage_bump_failed", token_id=str(token_id))


async def _bump_embed_token_usage(token_id: uuid.UUID) -> None:
    """Increment use_count/last_used_at on a dedicated side session."""
    from app.core.db import async_session

    async with async_session() as side_session:
        await side_session.execute(
            sa_update(EmbedToken)
            .where(EmbedToken.id == token_id)
            .values(
                use_count=EmbedToken.use_count + 1,
                last_used_at=datetime.now(timezone.utc),
            )
        )
        await side_session.commit()


async def list_admin_embed_tokens(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    map_search: str | None = None,
    creator: str | None = None,
    status_filter: str | None = None,
    *,
    map_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
) -> tuple[list, int]:
    """List all embed tokens with map name and creator username (admin).

    Returns list of (EmbedToken, map_name, creator_username) tuples and total count.
    """
    from app.modules.auth.models import User

    now = datetime.now(timezone.utc)

    matching_map_ids: set[uuid.UUID] | None = None
    if map_search:
        matching_map_ids = await find_map_ids_by_name(db, map_search)
        if not matching_map_ids:
            return [], 0

    base = select(
        EmbedToken,
        User.username.label("creator_username"),
    ).outerjoin(User, EmbedToken.created_by == User.id)

    # Apply filters
    if map_id:
        base = base.where(EmbedToken.map_id == map_id)

    # EMBED-03 (Phase 1212): tenant filter so a tenant-A admin cannot list
    # tenant-B tokens via the admin endpoint.
    if tenant_id is not None:
        base = base.where(EmbedToken.tenant_id == tenant_id)

    if matching_map_ids is not None:
        base = base.where(EmbedToken.map_id.in_(matching_map_ids))

    if creator:
        base = base.where(User.username == creator)

    if status_filter == "active":
        base = base.where(EmbedToken.is_active.is_(True), EmbedToken.expires_at > now)
    elif status_filter == "revoked":
        base = base.where(EmbedToken.is_active.is_(False))
    elif status_filter == "expired":
        base = base.where(EmbedToken.is_active.is_(True), EmbedToken.expires_at <= now)
    elif status_filter == "expiring_soon":
        base = base.where(
            EmbedToken.is_active.is_(True),
            EmbedToken.expires_at > now,
            EmbedToken.expires_at <= now + timedelta(days=7),
        )

    # Count
    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Fetch
    result = await db.execute(
        base.order_by(EmbedToken.created_at.desc()).offset(skip).limit(limit)
    )
    token_rows = result.all()
    map_names = await get_map_names(db, {row[0].map_id for row in token_rows})
    rows = [
        (token, map_names.get(token.map_id), creator_username)
        for token, creator_username in token_rows
    ]

    return rows, total


async def bulk_revoke_embed_tokens(
    db: AsyncSession,
    token_ids: list[uuid.UUID],
    *,
    tenant_id: uuid.UUID | None = None,
) -> int:
    """Bulk-revoke embed tokens. Returns count of tokens actually revoked.

    WR-01 (Phase 1212): when tenant_id is supplied (multi_tenant), only tokens
    belonging to that tenant are revoked — preventing a tenant-A admin from
    revoking tenant-B tokens by UUID.  Inert (None) in single_tenant.
    """
    filters = [
        EmbedToken.id.in_(token_ids),
        EmbedToken.is_active.is_(True),
    ]
    if tenant_id is not None:
        filters.append(EmbedToken.tenant_id == tenant_id)
    result = await db.execute(select(EmbedToken).where(*filters))
    tokens = list(result.scalars().all())

    for token in tokens:
        token.is_active = False

    await db.flush()

    # Best-effort cache invalidation
    await _deny_revoked_embed_tokens(db, *(token.token_hash for token in tokens))

    return len(tokens)
