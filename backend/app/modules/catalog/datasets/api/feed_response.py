"""Catalog feed rendering off the event loop, with a short anonymous cache."""

import hashlib
import json
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import Response
from starlette.concurrency import run_in_threadpool

from app.core.identity import Identity
from app.platform.cache import (
    get_cache,
    tenant_cache_context_available,
    tenant_cache_key,
)

FEED_CACHE_TTL = 30  # seconds, matches the search cache

# Distinct limit/offset values mint distinct keys, so oversized bodies skip the
# cache and only the most recent keys stay stored: at most
# _FEED_CACHE_MAX_KEYS * _FEED_CACHE_MAX_BYTES (128 MiB) per process.
_FEED_CACHE_MAX_BYTES = 4 * 1024 * 1024
_FEED_CACHE_MAX_KEYS = 32
_stored_keys: OrderedDict[str, None] = OrderedDict()

T = TypeVar("T")


def _encode(content: dict) -> str:
    return json.dumps(
        content, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )


async def serve_feed(
    name: str,
    user: Identity | None,
    key: dict,
    load: Callable[[], Awaitable[T]],
    build: Callable[[T], tuple[dict, dict[str, str]]],
    *,
    media_type: str = "application/ld+json",
) -> Response:
    """Load feed inputs on the loop, then build and serialize them in a thread.

    ``load`` must fully populate the ORM objects ``build`` reads and detach
    them from the session, which is not usable from the worker thread. Only anonymous responses are cached;
    their visibility is the same for every caller, so ``key`` needs no roles.
    """
    cache_key: str | None = None
    if user is None and tenant_cache_context_available():
        digest = hashlib.sha1(
            json.dumps({"feed": name, **key}, sort_keys=True, default=str).encode(),
            usedforsecurity=False,
        ).hexdigest()
        cache_key = tenant_cache_key(f"catalog:feed:{name}:{digest}")
        cached = await get_cache().get(cache_key)
        if cached is not None:
            return Response(
                cached["body"], media_type=media_type, headers=cached["headers"]
            )

    inputs = await load()

    def render() -> tuple[str, int, dict[str, str]]:
        content, headers = build(inputs)
        body = _encode(content)
        return body, len(body.encode()), headers

    body, size, headers = await run_in_threadpool(render)
    if cache_key is not None and size <= _FEED_CACHE_MAX_BYTES:
        cache = get_cache()
        await cache.set(
            cache_key, {"body": body, "headers": headers}, ttl=FEED_CACHE_TTL
        )
        _stored_keys[cache_key] = None
        _stored_keys.move_to_end(cache_key)
        while len(_stored_keys) > _FEED_CACHE_MAX_KEYS:
            evicted, _ = _stored_keys.popitem(last=False)
            await cache.delete(evicted)
    return Response(body, media_type=media_type, headers=headers)
