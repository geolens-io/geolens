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
from app.platform.cache.provider import get_cache
from app.modules.embed_tokens.models import EmbedToken
from app.modules.embed_tokens.schemas import ADVANCED_SHARING_ERROR
from app.modules.catalog.maps.models import MapLayer

logger = structlog.stdlib.get_logger(__name__)

_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})


def _normalize_origin(origin: str) -> str:
    """Lowercase, strip trailing slash, strip default ports."""
    origin = origin.lower().rstrip("/")
    if not origin.startswith(("http://", "https://")):
        origin = f"https://{origin}"
    parsed = urlparse(origin)
    host = parsed.hostname or ""
    port = parsed.port
    scheme = parsed.scheme or "http"
    # Strip default ports
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    if port:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def _is_localhost_origin(origin: str) -> bool:
    """Check if origin is a localhost address (http/https, IPv4/IPv6)."""
    parsed = urlparse(origin.lower().rstrip("/"))
    return (parsed.hostname or "") in _LOCALHOST_HOSTS


def extract_request_origin(request: Request) -> str | None:
    """Extract and normalize origin from Origin or Referer header."""
    origin = request.headers.get("origin")
    if origin:
        return _normalize_origin(origin)

    referer = request.headers.get("referer")
    if referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.hostname:
            return _normalize_origin(f"{parsed.scheme}://{parsed.netloc}")

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
        except Exception:
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
    except Exception:
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
    except Exception:
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
        allowed_origins = cached.get("allowed_origins")
        scoped_dataset_ids = cached.get("scoped_dataset_ids", [])
    else:
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

        # Cache positive result
        await cache.set(
            cache_key,
            {
                "is_valid": True,
                "scoped_dataset_ids": scoped_dataset_ids,
                "allowed_origins": allowed_origins,
                "map_id": str(token.map_id),
            },
            ttl=300,
        )

    # Domain-locking check (before dataset scope check).
    # NOTE: Localhost origins (localhost, 127.0.0.1, [::1]) bypass domain
    # restrictions intentionally to support local development. This does NOT
    # affect production security because embed tokens still require valid
    # token hash + active status + dataset scope + expiration.
    if allowed_origins:
        if request is None:
            return False
        origin = extract_request_origin(request)
        if origin is None:
            return False
        if not _is_localhost_origin(origin):
            # Both origin (from extract_request_origin) and allowed_origins
            # (from create_embed_token) are pre-normalized
            if origin not in allowed_origins:
                return False

    # Dataset scope check
    if str(dataset_id) not in scoped_dataset_ids:
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

    if map_search:
        escaped = map_search.replace("%", "\\%").replace("_", "\\_")
        base = base.where(Map.name.ilike(f"%{escaped}%"))

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
) -> int:
    """Bulk-revoke embed tokens. Returns count of tokens actually revoked."""
    result = await db.execute(
        select(EmbedToken).where(
            EmbedToken.id.in_(token_ids),
            EmbedToken.is_active.is_(True),
        )
    )
    tokens = list(result.scalars().all())

    for token in tokens:
        token.is_active = False

    await db.flush()

    # Best-effort cache invalidation
    try:
        cache = get_cache()
        for token in tokens:
            await cache.delete(f"embed_token:{token.token_hash}")
    except Exception:
        logger.error("Cache invalidation failed for embed token", exc_info=True)

    return len(tokens)
