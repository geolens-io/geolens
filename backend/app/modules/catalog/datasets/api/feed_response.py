"""Catalog feed rendering off the event loop, with a short anonymous cache."""

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.identity import Identity
from app.platform.cache import (
    get_cache,
    tenant_cache_context_available,
    tenant_cache_key,
)

FEED_CACHE_TTL = 30  # seconds, matches the search cache

# Distinct limit/offset values mint distinct keys, so oversized bodies skip the
# cache and a process stores at most _FEED_CACHE_MAX_KEYS live keys: at most
# _FEED_CACHE_MAX_KEYS * _FEED_CACHE_MAX_BYTES (128 MiB) per process. Entries
# are never deleted early because the store may be shared with other workers.
_FEED_CACHE_MAX_BYTES = 4 * 1024 * 1024
_FEED_CACHE_MAX_KEYS = 32
_stored_keys: dict[str, float] = {}  # key -> expiry (monotonic)
_in_flight: dict[str, list] = {}  # key -> [lock, waiters]

# Cold renders are CPU-bound; without a cap they would all run at once in the
# shared thread pool and starve everything else that uses it.
_MAX_CONCURRENT_RENDERS = 2
_render_slots = asyncio.Semaphore(_MAX_CONCURRENT_RENDERS)

T = TypeVar("T")


def _prune_stored_keys() -> None:
    now = time.monotonic()
    for key in [k for k, expires in _stored_keys.items() if expires <= now]:
        del _stored_keys[key]


def _encode(content: dict) -> str:
    return json.dumps(
        content, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )


async def serve_feed(
    name: str,
    user: Identity | None,
    db: AsyncSession,
    key: dict,
    load: Callable[[], Awaitable[T]],
    build: Callable[[T], tuple[dict, dict[str, str]]],
    *,
    media_type: str = "application/ld+json",
) -> Response:
    """Load feed inputs on the loop, then build and serialize them in a thread.

    ``load`` must fully populate the ORM objects ``build`` reads and detach
    them from the session, which is not usable from the worker thread. Only
    anonymous responses are cached; their visibility is the same for every
    caller, so ``key`` needs no roles.
    """
    cache_key: str | None = None
    if user is None and tenant_cache_context_available():
        digest = hashlib.sha1(
            json.dumps({"feed": name, **key}, sort_keys=True, default=str).encode(),
            usedforsecurity=False,
        ).hexdigest()
        cache_key = tenant_cache_key(f"catalog:feed:{name}:{digest}")
        if (hit := await _cached_response(cache_key, media_type)) is not None:
            return hit

    # Only the cache miss waits below; the read transaction opened for the
    # public URLs must not pin a pooled connection meanwhile. Detached first,
    # since a rollback expires the caller's already-loaded user.
    db.expunge_all()
    await db.rollback()
    if cache_key is None:
        async with _render_slots:
            return await _render(None, load, build, media_type)

    # One render per key: identical requests queue on the key's lock and find
    # the first one's stored body.
    entry = _in_flight.setdefault(cache_key, [asyncio.Lock(), 0])
    entry[1] += 1
    try:
        async with entry[0]:
            if (hit := await _cached_response(cache_key, media_type)) is not None:
                return hit
            async with _render_slots:
                return await _render(cache_key, load, build, media_type)
    finally:
        entry[1] -= 1
        if entry[1] == 0:
            _in_flight.pop(cache_key, None)


async def _cached_response(cache_key: str, media_type: str) -> Response | None:
    cached = await get_cache().get(cache_key)
    if cached is None:
        return None
    payload = await run_in_threadpool(cached["body"].encode)
    return Response(payload, media_type=media_type, headers=cached["headers"])


async def _render(
    cache_key: str | None,
    load: Callable[[], Awaitable[T]],
    build: Callable[[T], tuple[dict, dict[str, str]]],
    media_type: str,
) -> Response:
    inputs = await load()

    def render() -> tuple[str, bytes, dict[str, str]]:
        content, headers = build(inputs)
        body = _encode(content)
        return body, body.encode(), headers

    text, payload, headers = await run_in_threadpool(render)
    if cache_key is not None and len(payload) <= _FEED_CACHE_MAX_BYTES:
        _prune_stored_keys()
        if len(_stored_keys) < _FEED_CACHE_MAX_KEYS:
            _stored_keys[cache_key] = time.monotonic() + FEED_CACHE_TTL
            await get_cache().set(
                cache_key, {"body": text, "headers": headers}, ttl=FEED_CACHE_TTL
            )
    return Response(payload, media_type=media_type, headers=headers)
