"""Anonymous response cache for search hot-path endpoints (PERF-2, PERF-7)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import time
from typing import Literal

import structlog

from app.core.identity import Identity
from app.modules.catalog.search.service import SearchFilters
from app.platform.cache import (
    get_cache,
    tenant_cache_context_available,
    tenant_cache_key,
)

logger = structlog.stdlib.get_logger(__name__)

SEARCH_CACHE_TTL = 30  # seconds — CONTEXT.md decision
_COLLECTION_META_CACHE: dict[str, tuple[float, dict]] = {}
_COLLECTION_META_TTL = 60
_COLLECTION_META_MAX_SIZE = 200

EndpointKind = Literal["search", "facets"]


def is_anon_cacheable(user: Identity | None) -> bool:
    """True if ``user`` should use the anon cache: ``user is None`` and the
    tenant cache context is available. API-key-authed users with empty role
    sets are NOT anon and must bypass the cache (RESEARCH.md §1)."""
    return user is None and tenant_cache_context_available()


def collection_metadata_cache_key(identity: str) -> str | None:
    """Return a tenant-scoped metadata key, or disable cache on unscoped hosts."""
    if not tenant_cache_context_available():
        return None
    return tenant_cache_key(identity)


def get_collection_metadata_cached(key: str | None) -> dict | None:
    """Return a fresh copy of cached collection metadata."""
    if key is None:
        return None
    cached = _COLLECTION_META_CACHE.get(key)
    if cached is None:
        return None
    timestamp, data = cached
    if time.monotonic() - timestamp >= _COLLECTION_META_TTL:
        _COLLECTION_META_CACHE.pop(key, None)
        return None
    return dict(data)


def set_collection_metadata_cached(key: str | None, data: dict) -> None:
    """Store bounded collection metadata when a verified cache key exists."""
    if key is None:
        return
    _COLLECTION_META_CACHE[key] = (time.monotonic(), data)
    if len(_COLLECTION_META_CACHE) > _COLLECTION_META_MAX_SIZE:
        oldest_key = min(
            _COLLECTION_META_CACHE, key=lambda item: _COLLECTION_META_CACHE[item][0]
        )
        _COLLECTION_META_CACHE.pop(oldest_key, None)


def build_cache_key(
    *,
    endpoint: EndpointKind,
    filters: SearchFilters,
    user_roles: set[str],
    public_api_url: str | None = None,
    public_app_url: str | None = None,
    semantic_enabled: bool | None = None,
    preferred_languages: tuple[str, ...] = (),
) -> str:
    """Build a deterministic ``catalog:search:<endpoint>:<sha1 of canonical JSON>`` key.

    ``default=str`` silently swallows non-determinism outside date/UUID —
    audit ``SearchFilters`` when adding fields. ``semantic_enabled`` is keyed
    so facets match the results' candidate set (fix(#1855)); ``public_app_url``
    is keyed because raster_tiles hrefs use the app origin (fix(#315)).
    ``filters.keywords`` order is preserved — do NOT sort it here.
    """
    payload: dict[str, object] = {
        "filters": dataclasses.asdict(filters),
        "endpoint": endpoint,
        "roles": sorted(user_roles),
        "public_api_url": public_api_url or "",
        "public_app_url": public_app_url or "",
        "preferred_languages": preferred_languages,
    }
    if semantic_enabled is not None:
        payload["semantic_enabled"] = bool(semantic_enabled)
    digest = hashlib.sha1(
        json.dumps(payload, default=str, sort_keys=True).encode(),
        usedforsecurity=False,
    ).hexdigest()
    return tenant_cache_key(f"catalog:search:{endpoint}:{digest}")


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
