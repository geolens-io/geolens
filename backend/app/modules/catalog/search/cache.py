"""Anonymous response cache for search hot-path endpoints (PERF-2, PERF-7)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Literal

import structlog

from app.modules.auth.models import User
from app.modules.catalog.search.service import SearchFilters
from app.platform.cache import get_cache

logger = structlog.stdlib.get_logger(__name__)

SEARCH_CACHE_TTL = 30  # seconds — CONTEXT.md decision

EndpointKind = Literal["search", "facets"]


def is_anon_cacheable(user: User | None) -> bool:
    """Single source of truth for "should this request use the anon cache?".

    Anonymous = ``user is None``. API-key-authed users with empty role sets are
    NOT anon and must bypass the cache (RESEARCH.md §1 edge case).
    """
    return user is None


def build_cache_key(
    *,
    endpoint: EndpointKind,
    filters: SearchFilters,
    user_roles: set[str],
    public_api_url: str | None = None,
    semantic_enabled: bool | None = None,
) -> str:
    """Build a deterministic cache key for the given request shape.

    The key is ``catalog:search:<endpoint>:<sha1_hex>`` where the SHA-1 is
    computed over a canonical JSON dump of the request inputs. ``default=str``
    handles ``date``/``UUID`` fields on the dataclass; ``sort_keys=True`` makes
    the digest stable across Python versions.

    ``public_api_url`` and ``semantic_enabled`` are included only for the
    "search" endpoint — facets responses carry no URLs and do not run semantic
    ranking, so passing ``None`` keeps facet keys stable.
    """
    payload = {
        "filters": dataclasses.asdict(filters),
        "endpoint": endpoint,
        "roles": sorted(user_roles),
        "public_api_url": public_api_url or "",
        "semantic_enabled": (
            bool(semantic_enabled) if semantic_enabled is not None else False
        ),
    }
    digest = hashlib.sha1(
        json.dumps(payload, default=str, sort_keys=True).encode()
    ).hexdigest()
    return f"catalog:search:{endpoint}:{digest}"


async def get_cached(key: str) -> dict | None:
    """Return the cached payload for ``key`` or ``None`` on miss."""
    cache = get_cache()
    cached = await cache.get(key)
    if cached is None:
        logger.debug("search_cache_miss", key=key)
    else:
        logger.debug("search_cache_hit", key=key)
    return cached


async def set_cached(key: str, payload: dict) -> None:
    """Store ``payload`` under ``key`` with the search-cache TTL."""
    cache = get_cache()
    await cache.set(key, payload, ttl=SEARCH_CACHE_TTL)
