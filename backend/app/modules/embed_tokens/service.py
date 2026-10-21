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
from app.modules.catalog.authorization import datasets_account_can_read
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


# Revoking a token evicts its positive cache entry before the caller's commit,
# so a concurrent reader can re-SELECT the still-active row and re-cache it as
# valid for the full TTL. A revoke therefore writes a DENIAL here instead of
# deleting the key, and readers publish positives with set_if_absent:
# whichever write lands first wins, so the denial always survives the race.
# TTL must cover the longest positive entry a racer could write
# (EMBED_TOKEN_POSITIVE_TTL_SECONDS). A rolled-back revoke leaves its denial in
# place until it expires: fail closed, the direction to be wrong in.
EMBED_TOKEN_REVOCATION_DENIAL_TTL_SECONDS = 300

# Bounds how long a worker that took no traffic during a Redis outage can keep
# trusting a stale positive: it never observes the revocation generation
# change, so it trusts a cached entry until this TTL expires. Lower = shorter
# exposure, more DB reads; see platform/cache/revocation.py.
EMBED_TOKEN_POSITIVE_TTL_SECONDS = 300


def _embed_token_cache_key(token_hash: str) -> str:
    """Return the active tenant's validation-cache key.

    Tenant-scoped so a token presented through the wrong hosted tenant
    cannot populate a fleet-global entry that denies its rightful tenant.
    """
    return tenant_cache_key(f"embed_token:{token_hash}")


async def _deny_revoked_embed_tokens(db: AsyncSession, *token_hashes: str) -> None:
    """Stamp a denial over each revoked token's validation-cache entry.

    Best-effort: a cache failure must not break the revocation (the DB row is
    authoritative). Also bumps the cluster-wide revocation generation in the
    SAME transaction as the caller's is_active flip -- that is what lets a
    worker cut off from Redis during the outage still see the revocation once
    it reads the generation. The bump is NOT wrapped in its own try/except: a
    failure there must poison the caller's transaction, not let the revocation
    commit without it.
    """
    if not token_hashes:
        return
    await bump_revocation_generation(db)
    try:
        cache = get_cache()
        for token_hash in token_hashes:
            # set_authoritative, not set: a positive entry stuck in the
            # in-memory fallback during a Redis outage must not survive a
            # denial written after Redis recovers.
            await cache.set_authoritative(
                _embed_token_cache_key(token_hash),
                {"is_valid": False},
                ttl=EMBED_TOKEN_REVOCATION_DENIAL_TTL_SECONDS,
            )
    except Exception:  # broad: cache invalidation must not break callers; redis can throw varied pool/timeout errors
        logger.error("Cache invalidation failed for embed token", exc_info=True)


# Gates the localhost-Origin bypass on the TCP peer also being loopback, since
# the Origin header alone is forgeable by non-browser callers.
#
# An exact set (not a range like _is_localhost_origin) on purpose: this only
# GATES a bypass, so a miss just denies the shortcut, and widening it would
# hand the bypass to more callers.
_LOOPBACK_CLIENT_IPS = frozenset({"127.0.0.1", "::1", "localhost"})


def _is_localhost_origin(origin: str) -> bool:
    """Is this origin one that only reaches the machine it is opened on?

    Loopback is a RANGE (127.0.0.0/8, ::1), not just 127.0.0.1: treating it
    as a single address would let http://127.0.0.2 read as a routable public
    origin and make a domain lock enforceable when it should not be. See
    is_loopback_host (app/core/public_urls.py) and the frontend mirror
    isLoopbackHostname.
    """
    parsed = urlparse(origin.lower().rstrip("/"))
    return is_loopback_host(parsed.hostname or "")


def _client_is_loopback(request: Request) -> bool:
    """True iff the actual TCP peer is a loopback IP.

    request.client.host is the ASGI server's socket peer address and
    cannot be forged via headers, unlike Origin.
    """
    if request.client is None:
        return False
    return (request.client.host or "").lower() in _LOOPBACK_CLIENT_IPS


def extract_request_origin(request: Request) -> str | None:
    """Extract and normalize the Origin (or Referer) header.

    Uses the bracket-preserving schema normalizer that also stores
    allowed_origins, so an IPv6 literal byte-matches. A forged/unparseable
    header fails closed (None) rather than raising.
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

    Every candidate is server-derived, never reconstructed from the caller's
    own Origin/Referer, which would make every origin "self" and the
    allowlist vacuous. Sources: the configured PUBLIC_APP_URL (via
    get_configured_public_app_url, not get_public_app_url, whose fallbacks
    include caller-supplied headers), and in hosted multi-tenant, the tenant
    origin the tenant-context middleware already resolved against the
    registry.
    """
    origins: set[str] = set()

    # Set only in multi_tenant: TenantContextMiddleware returns early in
    # single_tenant, so the attribute never exists there.
    if is_multi_tenant():
        tenant_origin = getattr(request.state, "tenant_public_origin", None)
        if tenant_origin and is_usable_public_origin(tenant_origin):
            try:
                origins.add(_normalize_origin(tenant_origin))
            except ValueError:
                pass

    # Fails CLOSED on lookup errors like every other denial here: an
    # authorization helper must not turn a 60s-cache DB miss into a 500 on the
    # tile path.
    try:
        app_url = await get_configured_public_app_url(db)
    except Exception:  # broad: any lookup failure must deny, never raise
        logger.warning("embed_self_origin_lookup_failed", exc_info=True)
        return origins
    if app_url is None:
        return origins

    # Shape-check BEFORE normalization, which hides the problem: it prepends
    # https:// to any schemeless value, so a misconfigured
    # `ftp://maps.example.com` would look like a plausible non-loopback origin
    # and issue a lock nothing can satisfy. is_usable_public_origin is the one
    # statement of this rule (mirrored by parseUsablePublicUrl in
    # public-urls.ts).
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

    A domain-locked embed's own API calls (tiles/features) run from inside
    the /m/{token} iframe, so they carry the SHELL's own origin, never the
    embedder's; the embedder's origin is only visible on the iframe's
    navigation, which frame-ancestors (build_embed_frame_ancestors) enforces
    at the browser layer. So this accepts the shell's resolved self-origin as
    well as allowed_origins (the 'self' half CSP already grants), while
    allowed_origins stays the only enforcement for tokens driven by the
    customer's own JS (Origin: https://customer.example.com).

    Known consequence: a top-level (unframed) navigation to the shell
    sends identical headers to the framed case and is accepted too;
    nothing distinguishes them, and possession of the token itself is what
    still gates that path.
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
    # Origin alone is forgeable, so the localhost bypass also requires the TCP
    # peer to be loopback.
    if _is_localhost_origin(origin) and _client_is_loopback(request):
        return True

    self_origins = await _resolve_self_origins(db, request)
    if origin in self_origins:
        return True

    # An unconfigured self-hoster resolves a localhost self-origin (see
    # assert_domain_lock_is_enforceable). The shell's origin is not inferred
    # from Host/X-Forwarded-Host/request.url, which anyone who can point DNS
    # at the deployment can set. Log and deny instead of guessing.
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

    Deliberately not a ValueError: both write handlers map ValueError to
    400 for the advanced-sharing edition gate; this needs its own status
    code.
    """


async def assert_domain_lock_is_enforceable(
    db: AsyncSession, request: Request, allowed_origins: list[str] | None
) -> None:
    """Refuse to issue a domain lock this deployment could never enforce.

    The embed shell's own API calls carry the SHELL's origin (see
    _request_origin_is_allowed), which comes from configuration
    (PUBLIC_APP_URL), and compose's `:-http://localhost:8080` default plus a
    commented-out .env.example line means an unconfigured self-hoster
    silently resolves a self-origin of localhost, so every domain-locked
    embed they issue stays empty. Not inferred from
    Host/X-Forwarded-Host/request.url: those are settable by anyone who can
    point DNS at the deployment, which would make the lock satisfiable by the
    exact parties it excludes.

    Refuses only when the creating request reached a real, non-loopback
    origin while every self-origin this deployment knows resolves to
    loopback: a proof of unenforceability, not a guess. "Configured value is
    absent" is undetectable (the compose default masks unset), and "creating
    origin differs from configured" would refuse a correctly configured
    deployment administered from a different hostname than its public one. A
    typo'd (not defaulted) PUBLIC_APP_URL is NOT caught here by choice; it
    surfaces via the embed_token_domain_lock_denied warning in
    _request_origin_is_allowed instead.

    The comparison reads the creating request's own Origin, caller
    controlled but sound here because it is diagnostic only: it can refuse a
    mint but never grant access, and forging it only denies yourself. Skipped
    entirely when the request carries no browser origin, or when that origin
    is itself loopback (a local dev caller).
    """
    if not allowed_origins:
        return

    if not is_enterprise():
        # Community is about to be rejected with ADVANCED_SHARING_ERROR
        # anyway; returning here keeps that the message shown, rather than
        # misdirecting them to fix PUBLIC_APP_URL.
        return

    origin = extract_request_origin(request)
    if origin is None or _is_localhost_origin(origin):
        return

    self_origins = await _resolve_self_origins(db, request)
    if any(not _is_localhost_origin(o) for o in self_origins):
        return

    # Keep this wording stable -- frontend/src/lib/error-map.ts matches it
    # to render the remediation; an unmapped 422 falls back to a generic toast.
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
    """Build the CSP frame-ancestors directive for the /m/{token} embed shell.

    Domain restrictions cover the shell's own HTML document, not only the
    tile/data calls, or any site could frame it. Invalid/revoked/expired ->
    'none' (fail closed). Valid with allowed_origins -> 'self' + origins.
    Valid without -> '' (intentional open Community embed; never emits the
    forbidden wildcard '*').

    CRLF/wildcard entries in allowed_origins are dropped here too, in
    addition to the schema-layer 422 rejection, so a stale DB row cannot
    header-split or reopen clickjacking.
    """
    if not is_valid:
        return "frame-ancestors 'none'"
    safe: list[str] = []
    for o in allowed_origins or []:
        if not o or "\r" in o or "\n" in o or "*" in o or not o.strip():
            continue
        safe.append(o.strip())
    if not safe:
        return ""
    return f"frame-ancestors 'self' {' '.join(safe)}"


class EmbedScopeNotVisibleError(Exception):
    """The minter cannot currently see every dataset the map is scoped to.

    Distinct from this module's ValueError refusals so the router can answer
    with 403 (matching the maps router's shape for "you can't use these
    datasets") rather than the 400 licensing-refusal shape.
    """


async def _assert_scope_visible_to_minter(
    db: AsyncSession, dataset_ids: tuple[uuid.UUID, ...], user_id: uuid.UUID
) -> None:
    """Refuse a mint whose scope reaches past what the minter can see."""
    readable = await datasets_account_can_read(db, dataset_ids, user_id)
    if any(dataset_id not in readable for dataset_id in dataset_ids):
        raise EmbedScopeNotVisibleError()


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

    Revokes any existing active token for the map first (one active token
    per map). Returns (token_record, raw_token); the raw token is only
    available at creation.
    """
    if not is_enterprise() and (expires_in_days != 30 or bool(allowed_origins)):
        raise ValueError(ADVANCED_SHARING_ERROR)

    # Order is load-bearing. _deny_revoked_embed_tokens writes a cache denial
    # that is NOT rolled back with this transaction, so scope must be checked
    # and the mint accepted/refused BEFORE any revoke: a refusal raised after
    # revoking would leave the caller's still-valid token dead in cache while
    # the DB rolled the revoke back.
    map_scope = await get_map_embed_scope(db, map_id)
    scoped_ids = map_scope.dataset_ids if map_scope else ()

    if not scoped_ids:
        raise ValueError("Map has no layers to scope")

    await _assert_scope_visible_to_minter(db, scoped_ids, user_id)
    dataset_ids = [str(dataset_id) for dataset_id in scoped_ids]

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

    await _deny_revoked_embed_tokens(db, *revoked_hashes)

    raw_token = "et_" + secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    token_hint = "et_..." + raw_token[-8:]

    # tenant_id is derived server-side from Map.tenant_id, never from a client
    # header or argument. Inert (None) in single_tenant.
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

    await _deny_revoked_embed_tokens(db, token.token_hash)

    return token


async def revoke_embed_tokens_by_map(
    db: AsyncSession,
    map_id: uuid.UUID,
) -> int:
    """Revoke ALL active embed tokens for a map and purge their cache.

    Wired into the share-revoke, public->non-public downgrade, and
    layer-change paths, so a copied embed token stops serving tiles there
    too. Writes a denial over the positive cache entry, so the 5-minute TTL
    cannot extend access past revocation. Returns the number of tokens
    revoked.
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

    await _deny_revoked_embed_tokens(db, *(token.token_hash for token in tokens))

    return len(tokens)


async def revoke_embed_tokens_for_dropped_datasets(
    db: AsyncSession,
    map_id: uuid.UUID,
) -> int:
    """Revoke tokens orphaned by a layer change.

    A token is scoped to the dataset ids that were layers when it was
    minted. If any active token now references a dataset no longer a layer
    on the map, ALL of the map's embed tokens are revoked via
    revoke_embed_tokens_by_map (also purges the positive cache). Pure
    additions/reorders that keep every scoped dataset present revoke
    nothing. Returns the number revoked.
    """
    map_scope = await get_map_embed_scope(db, map_id)
    current_ids = (
        {str(dataset_id) for dataset_id in map_scope.dataset_ids}
        if map_scope is not None
        else set()
    )
    if await embed_tokens_reach_beyond(db, map_id, current_ids):
        return await revoke_embed_tokens_by_map(db, map_id)
    return 0


async def embed_tokens_reach_beyond(
    db: AsyncSession, map_id: uuid.UUID, dataset_ids: set[str]
) -> bool:
    """Whether a live token on the map is scoped to a dataset outside ``dataset_ids``.

    An expired token serves nothing, and every token's datasets are rechecked
    against the map's layers when it is used, so only live ones count.
    """
    result = await db.execute(
        select(EmbedToken.scoped_dataset_ids).where(
            EmbedToken.map_id == map_id,
            EmbedToken.is_active.is_(True),
            EmbedToken.expires_at > func.now(),
        )
    )
    return any(
        not {str(d) for d in (scoped or [])} <= dataset_ids
        for scoped in result.scalars()
    )


async def get_active_embed_token(
    db: AsyncSession,
    token_id: uuid.UUID,
    map_id: uuid.UUID,
) -> EmbedToken | None:
    """Load the active token a write targets, or None if there is none.

    Shared by the router's initial 404 check and update_embed_token's
    write-time check, so "which token does this PATCH mean" cannot drift
    between them.
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
    """Update allowed_origins on an embed token.

    Advances the revocation generation with the update, so after commit no
    worker trusts a validation entry cached under the old policy.
    """
    if not is_enterprise() and bool(allowed_origins):
        raise ValueError(ADVANCED_SHARING_ERROR)

    token = await get_active_embed_token(db, token_id, map_id)
    if token is None:
        return None

    token.allowed_origins = allowed_origins or None
    await db.flush()
    await bump_revocation_generation(db)

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
    """Resolve the dataset ids an embed token authorizes for map_id.

    Embed tokens are a private-dataset capability. This lets get_shared_map
    widen its visibility filter to the token's snapshot scope, so a valid
    scoped token can construct the layers its tiles serve.

    Fail-closed: returns an empty set (never raises) for an unknown,
    inactive, expired, wrong-map, or origin-denied token, the same rules as
    validate_embed_token_access. No caching or usage tracking: this
    endpoint is low-QPS, called once per viewer load.

    The ``map_id`` equality pins the tenant: map ids are globally unique and
    callers resolve ``map_id`` from their own share token, so there is no
    separate tenant re-check.
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

    # Domain-locking check: one policy reader shared with
    # validate_embed_token_access, so the two cannot drift.
    if not await _request_origin_is_allowed(db, request, token.allowed_origins):
        return set()

    scoped: set[uuid.UUID] = set()
    for raw_id in token.scoped_dataset_ids or []:
        try:
            scoped.add(uuid.UUID(str(raw_id)))
        except ValueError:
            continue
    return await datasets_account_can_read(db, scoped, token.created_by)


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
    # Hosted validation needs a verified tenant context; deny generically
    # rather than let cache-key construction raise and become an error oracle.
    if is_multi_tenant() and not tenant_cache_context_available():
        return False

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    cache_key = _embed_token_cache_key(token_hash)

    cache = get_cache()
    token: EmbedToken | None = None

    # Read the revocation generation before the cache so a hit can be compared
    # in one round-trip (see platform/cache/revocation.py for why a
    # process-local answer isn't enough).
    generation = await current_revocation_generation(db)
    # An unreadable counter yields a SENTINEL rather than a generation; two
    # sentinel-stamped entries would compare EQUAL, so a positive cached while
    # the counter was down would stay trusted through a later revocation. When
    # unusable, the cache is skipped entirely in both directions and every
    # validation costs a DB read instead.
    generation_usable = is_usable_generation(generation)

    # Check cache first. security=True: a positive here decides access to
    # private data, so it may only come from the store every worker shares.
    cached = await cache.get(cache_key, security=True)
    if cached is not None and not cached.get("is_valid", False):
        return False

    # An entry stamped with an older generation than the DB's current one is
    # not evidence about the token now: this is what makes a revoke performed
    # while this worker couldn't reach Redis visible to it. An entry with no
    # stamp fails the same way, since trusting it would trust exactly what
    # this can't vouch for.
    if cached is not None and (
        not generation_usable
        or not is_usable_generation(cached.get("generation", UNKNOWN_GENERATION))
        or cached.get("generation") != generation
    ):
        await cache.delete(cache_key)
        cached = None

    if cached is not None:
        # Re-check expiry on every cache hit so a token can't stay valid past
        # its real expires_at for up to the positive-TTL window. An entry
        # without expires_at or the minter is treated as a miss.
        now = datetime.now(timezone.utc)
        cached_expires_at_str = cached.get("expires_at")
        if cached_expires_at_str is None or "created_by" not in cached:
            await cache.delete(cache_key)
            cached = None
        else:
            cached_expires_at = datetime.fromisoformat(cached_expires_at_str)
            if now >= cached_expires_at:
                await cache.delete(cache_key)
                return False
            allowed_origins = cached.get("allowed_origins")
            scoped_dataset_ids = cached.get("scoped_dataset_ids", [])

    if cached is None:
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
            # security=True keeps the negative out of the process-local
            # fallback too, for symmetry with the positive path.
            await cache.set(cache_key, {"is_valid": False}, ttl=300, security=True)
            return False

        allowed_origins = token.allowed_origins
        scoped_dataset_ids = token.scoped_dataset_ids

        # Cache positive: include expires_at (for the re-check) and tenant_id
        # (for the cache-hit path).
        #
        # set_if_absent, not set. This row read as committed-active, but a
        # revocation may be mid-flight on it right now (plain READ COMMITTED
        # doesn't block on the revoker's lock) and may have already stamped a
        # denial under this key. Overwriting it would restore the token for
        # the rest of this entry's TTL.
        seconds_until_expiry = (token.expires_at - now).total_seconds()
        cache_ttl = int(
            min(EMBED_TOKEN_POSITIVE_TTL_SECONDS, max(0, seconds_until_expiry))
        )
        # Only publish an entry that carries a generation a future reader can
        # actually check it against.
        if generation_usable:
            await cache.set_if_absent(
                cache_key,
                {
                    "is_valid": True,
                    "scoped_dataset_ids": scoped_dataset_ids,
                    "allowed_origins": allowed_origins,
                    "map_id": str(token.map_id),
                    "created_by": str(token.created_by) if token.created_by else None,
                    "expires_at": token.expires_at.isoformat(),
                    "tenant_id": str(token.tenant_id) if token.tenant_id else None,
                    # The generation this decision was made under.
                    "generation": generation,
                },
                ttl=cache_ttl,
                security=True,
            )

    # Domain-locking check, before dataset scope. Shares ONE reader with
    # resolve_embed_scope_for_map so the two cannot drift.
    if not await _request_origin_is_allowed(db, request, allowed_origins):
        return False

    if str(dataset_id) not in scoped_dataset_ids:
        return False

    # Fail-closed tenant-equality check, inert in single_tenant.
    if is_multi_tenant():
        if token is not None:
            token_tenant = token.tenant_id
        else:
            raw_tid = cached.get("tenant_id") if cached else None  # type: ignore[union-attr]
            token_tenant = uuid.UUID(raw_tid) if raw_tid else None

        # The dataset's tenant from a fresh query (no re-mint, no cache).
        dataset = await get_processing_port().get_dataset(db, dataset_id)
        dataset_tenant = getattr(dataset, "tenant_id", None) if dataset else None

        # Explicit NULL guard. `None != None` is False, so without this a
        # legacy NULL-tenant token would pass the equality check against any
        # NULL-tenant dataset.
        if token_tenant is None or dataset_tenant is None:
            return False
        if token_tenant != dataset_tenant:
            return False

    # Fail-closed live layer-membership re-check. scoped_dataset_ids is a
    # creation-time snapshot; if the dataset's layer was later removed (or the
    # map deleted), a cached positive could keep granting tile access until
    # expiry. Runs on both cache-hit and cache-miss paths. Does NOT recheck
    # Map.visibility: embed tokens are a private-dataset capability, so a
    # private map must still serve via an active token; visibility downgrades
    # are handled by revoke_embed_tokens_by_map instead.
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
        minter_id = token.created_by
    else:
        raw_minter = cached.get("created_by") if cached else None  # type: ignore[union-attr]
        minter_id = uuid.UUID(raw_minter) if raw_minter else None
    if dataset_id not in await datasets_account_can_read(db, [dataset_id], minter_id):
        return False

    if token is not None:
        # Separate session: this authorization helper must not commit the
        # caller's request-scoped `db` (as with _resolve_api_key's
        # last_used_at bump).
        #
        # Fired detached, not awaited: access is already decided, so the bump
        # is pure telemetry that must never delay or fail it. A burst of
        # simultaneous cache-miss bumps could contend for the side pool, and
        # even a bounded await here would stall every cache-miss authorization
        # for up to the timeout. _usage_bump_tasks holds a strong ref so the
        # task can't be GC'd mid-flight.
        task = asyncio.create_task(_bump_embed_token_usage_detached(token.id))
        _usage_bump_tasks.add(task)
        task.add_done_callback(_usage_bump_tasks.discard)

    return True


# Strong refs for detached usage-bump tasks -- see
# validate_embed_token_access for why they're fired this way.
_usage_bump_tasks: set[asyncio.Task] = set()


async def _bump_embed_token_usage_detached(token_id: uuid.UUID) -> None:
    """Best-effort use_count/last_used_at bump, isolated from the caller.

    Bounded with a timeout so a starved pool doesn't leave the task running
    indefinitely; any failure (pool contention or otherwise) is logged and
    swallowed, since there is no caller left to catch it.
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

    if map_id:
        base = base.where(EmbedToken.map_id == map_id)

    # Tenant filter so a tenant-A admin cannot list tenant-B tokens via the
    # admin endpoint.
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

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

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
    """Bulk-revoke embed tokens. Returns the count actually revoked.

    When tenant_id is supplied, only that tenant's tokens are revoked, so a
    tenant-A admin cannot revoke tenant-B tokens by UUID. Inert in
    single_tenant.
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

    await _deny_revoked_embed_tokens(db, *(token.token_hash for token in tokens))

    return len(tokens)
