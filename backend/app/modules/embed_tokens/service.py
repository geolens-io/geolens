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
from app.modules.catalog._ilike import escape_ilike
from app.modules.embed_tokens.models import EmbedToken
from app.modules.embed_tokens.schemas import (
    ADVANCED_SHARING_ERROR,
    _normalize_origin,
)
from app.modules.catalog.maps.models import Map, MapLayer

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
    result = await db.execute(
        select(MapLayer.dataset_id).where(MapLayer.map_id == map_id)
    )
    dataset_ids = [str(row[0]) for row in result.all()]

    if not dataset_ids:
        raise ValueError("Map has no layers to scope")

    # EMBED-01 (Phase 1212): stamp tenant_id from Map.tenant_id — derived
    # server-side, NEVER from a client header or function argument.
    # Inert (None) in single_tenant so behavior is byte-identical.
    map_tenant_result = await db.execute(select(Map.tenant_id).where(Map.id == map_id))
    map_tenant_id = map_tenant_result.scalar_one_or_none()
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
        from app.modules.catalog.datasets.domain.models import Dataset

        ds_tenant_result = await db.execute(
            select(Dataset.tenant_id).where(Dataset.id == dataset_id)
        )
        dataset_tenant = ds_tenant_result.scalar_one_or_none()

        # CR-01 (Phase 1212): fail-closed guard — legacy tokens (pre-EMBED-01,
        # NULL tenant_id) and NULL-tenant datasets are denied in multi_tenant mode.
        # Without this, `None != None` evaluates to False and PASSES the equality
        # check, granting a NULL-tenant token access to any NULL-tenant dataset.
        if token_tenant is None or dataset_tenant is None:
            return False
        if token_tenant != dataset_tenant:
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
    from app.modules.catalog.maps.models import Map

    now = datetime.now(timezone.utc)

    base = (
        select(
            EmbedToken,
            Map.name.label("map_name"),
            User.username.label("creator_username"),
        )
        .outerjoin(Map, EmbedToken.map_id == Map.id)
        .outerjoin(User, EmbedToken.created_by == User.id)
    )

    # Apply filters
    if map_id:
        base = base.where(EmbedToken.map_id == map_id)

    # EMBED-03 (Phase 1212): tenant filter so a tenant-A admin cannot list
    # tenant-B tokens via the admin endpoint.
    if tenant_id is not None:
        base = base.where(EmbedToken.tenant_id == tenant_id)

    if map_search:
        # T-2: lower() column + pattern to hit ix_maps_name_trgm (on lower(name));
        # a bare ILIKE emits `name ~~* pattern` which the planner cannot match.
        base = base.where(
            func.lower(Map.name).like(
                f"%{escape_ilike(map_search)}%".lower(), escape="\\"
            )
        )

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
    rows = result.all()

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
