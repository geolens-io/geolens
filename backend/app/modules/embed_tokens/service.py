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
from app.core.tenancy import is_multi_tenant
from app.platform.cache.provider import get_cache
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

# BUG-028: urlparse(...).hostname strips IPv6 brackets, so the loopback literal
# stored here must be the UNBRACKETED form '::1' to match what
# _is_localhost_origin extracts. The previous '[::1]' entry was a dead branch.
_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# Phase 268 H-31: loopback IP set used to gate the localhost-Origin bypass.
# The Origin header alone is trivially forgeable from non-browser callers
# (curl, server-side scripts, CLIs) — they can simply set
# ``Origin: http://localhost`` and bypass any allowed_origins whitelist.
# To prevent that, the bypass now also requires ``request.client.host`` to
# be a loopback IP (which a remote attacker cannot forge — ``client.host``
# is the actual TCP peer address).
_LOOPBACK_CLIENT_IPS = frozenset({"127.0.0.1", "::1", "localhost"})


# BUG-028: storage (allowed_origins, via schemas._validate_origins) and
# request-origin extraction now share ONE bracket-preserving normalizer
# (schemas._normalize_origin), so an IPv6 literal like 'http://[::1]:8080'
# byte-matches between the stored allowlist and the live request origin.


def _is_localhost_origin(origin: str) -> bool:
    """Check if origin is a localhost address (http/https, IPv4/IPv6)."""
    parsed = urlparse(origin.lower().rstrip("/"))
    return (parsed.hostname or "") in _LOCALHOST_HOSTS


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
    if revoked_hashes:
        try:
            cache = get_cache()
            for h in revoked_hashes:
                await cache.delete(f"embed_token:{h}")
        except Exception:  # broad: cache invalidation must not break callers; redis can throw varied pool/timeout errors
            logger.error("Cache invalidation failed for embed token", exc_info=True)

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
    try:
        cache = get_cache()
        await cache.delete(f"embed_token:{token.token_hash}")
    except Exception:  # broad: cache invalidation must not break callers; redis can throw varied pool/timeout errors
        logger.error("Cache invalidation failed for embed token", exc_info=True)

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
    try:
        cache = get_cache()
        for token in tokens:
            await cache.delete(f"embed_token:{token.token_hash}")
    except Exception:  # broad: cache invalidation must not break callers; redis can throw varied pool/timeout errors
        logger.error("Cache invalidation failed for embed token", exc_info=True)

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


async def update_embed_token(
    db: AsyncSession,
    token_id: uuid.UUID,
    map_id: uuid.UUID,
    allowed_origins: list[str] | None,
) -> EmbedToken | None:
    """Update allowed_origins on an embed token. Invalidates cache."""
    if not is_enterprise() and bool(allowed_origins):
        raise ValueError(ADVANCED_SHARING_ERROR)

    result = await db.execute(
        select(EmbedToken).where(
            EmbedToken.id == token_id,
            EmbedToken.map_id == map_id,
            EmbedToken.is_active.is_(True),
        )
    )
    token = result.scalar_one_or_none()
    if token is None:
        return None

    token.allowed_origins = allowed_origins or None
    await db.flush()

    # Invalidate cache so changes take effect immediately
    try:
        cache = get_cache()
        await cache.delete(f"embed_token:{token.token_hash}")
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

    # Domain-locking check — mirrors validate_embed_token_access (H-31 rules).
    if token.allowed_origins:
        if request is None:
            return set()
        origin = extract_request_origin(request)
        if origin is None:
            return set()
        if _is_localhost_origin(origin) and _client_is_loopback(request):
            pass
        elif origin not in token.allowed_origins:
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
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    cache_key = f"embed_token:{token_hash}"

    cache = get_cache()
    token: EmbedToken | None = None

    # Check cache first
    cached = await cache.get(cache_key)
    if cached is not None:
        if not cached.get("is_valid", False):
            return False

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
            # Cache negative result
            await cache.set(cache_key, {"is_valid": False}, ttl=300)
            return False

        allowed_origins = token.allowed_origins
        scoped_dataset_ids = token.scoped_dataset_ids

        # Cache positive result — include expires_at so every cache hit can
        # re-check expiry (SEC-014). Include tenant_id for EMBED-02 cache-hit
        # path so validate_embed_token_access can check tenant equality without
        # re-querying the EmbedToken row (Phase 1212).
        seconds_until_expiry = (token.expires_at - now).total_seconds()
        cache_ttl = int(min(300, max(0, seconds_until_expiry)))
        await cache.set(
            cache_key,
            {
                "is_valid": True,
                "scoped_dataset_ids": scoped_dataset_ids,
                "allowed_origins": allowed_origins,
                "map_id": str(token.map_id),
                "expires_at": token.expires_at.isoformat(),
                "tenant_id": str(token.tenant_id) if token.tenant_id else None,
            },
            ttl=cache_ttl,
        )

    # Domain-locking check (before dataset scope check).
    # Phase 268 H-31: the legacy localhost-Origin bypass was trivially
    # forgeable by non-browser callers (curl, server-side scripts) — any
    # caller could set ``Origin: http://localhost`` and skip the allowlist.
    # The bypass is now gated on ``request.client.host`` being a loopback
    # IP (which is the actual TCP peer and cannot be forged remotely).
    if allowed_origins:
        if request is None:
            return False
        origin = extract_request_origin(request)
        if origin is None:
            return False
        if _is_localhost_origin(origin) and _client_is_loopback(request):
            # Local-development bypass: Origin claims localhost AND the TCP
            # peer is also loopback (only possible from same-host calls).
            pass
        elif origin not in allowed_origins:
            # Both origin (from extract_request_origin) and allowed_origins
            # (from create_embed_token) are pre-normalized.
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
        async with db.begin_nested():
            await db.execute(
                sa_update(EmbedToken)
                .where(EmbedToken.id == token.id)
                .values(
                    use_count=EmbedToken.use_count + 1,
                    last_used_at=datetime.now(timezone.utc),
                )
            )
        await db.commit()

    return True


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
    try:
        cache = get_cache()
        for token in tokens:
            await cache.delete(f"embed_token:{token.token_hash}")
    except Exception:  # broad: cache invalidation must not break callers; redis can throw varied pool/timeout errors
        logger.error("Cache invalidation failed for embed token", exc_info=True)

    return len(tokens)
