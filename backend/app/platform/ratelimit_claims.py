"""Single-use paired-request claims, shared across workers when a store exists.

fix(#2018): the claim a paired request redeems is consumed inside slowapi's
SYNCHRONOUS ``exempt_when``, so this is a sync client with a short timeout
rather than the async cache provider. Every store error answers ``None`` so
the caller falls back to its process-local registry, which is the behaviour
before this module existed; "exempt" is never the fallback.
"""

from __future__ import annotations

import hashlib
from typing import Any

import structlog

from app.platform.ratelimit import STORAGE_SOCKET_TIMEOUT_SECONDS, shared_storage_uri

logger = structlog.stdlib.get_logger(__name__)

CLAIM_TTL_SECONDS = 5
_KEY_PREFIX = "geolens:paired-claim:"


def claim_key(parts: tuple[str, ...]) -> str:
    """Hash a length-prefixed join of *parts* into one store key.

    fix(#2018): length-prefixed, because a component is an IPv6 address and
    another is caller-supplied text, so a plain separator lets a /64 holder
    pick low bits that shift the split and collide with a neighbour's key.
    """
    joined = "".join(f"{len(part)}:{part}" for part in parts)
    digest = hashlib.blake2s(joined.encode("utf-8"), digest_size=16).hexdigest()
    return f"{_KEY_PREFIX}{digest}"


class SharedClaimStore:
    """``SET NX EX`` to record a claim, ``GETDEL`` to consume it once."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._unavailable_logged = False

    def record(self, parts: tuple[str, ...], route: str) -> bool | None:
        """Claim *parts* for *route*. None means the store did not answer.

        ``NX`` so a claim already standing for these *parts* keeps its own
        route and deadline: a second writer must not extend someone else's
        window.
        """
        try:
            self._client.set(claim_key(parts), route, nx=True, ex=CLAIM_TTL_SECONDS)
        except Exception:  # broad: any client or transport error must degrade
            self._degraded("record")
            return None
        self._unavailable_logged = False
        return True

    def consume(self, parts: tuple[str, ...], route: str) -> bool | None:
        """True when ANOTHER route holds the claim, consuming it. None: no answer.

        ``GETDEL`` is one round trip, so two workers cannot both redeem one
        claim. A same-route caller reads its own claim and destroys it, where
        the process-local registry would leave it standing; that can only cost
        an exemption the sibling would have had, never grant an extra one.
        """
        try:
            claimant = self._client.getdel(claim_key(parts))
        except Exception:  # broad: any client or transport error must degrade
            self._degraded("consume")
            return None
        self._unavailable_logged = False
        return claimant is not None and claimant != route

    def _degraded(self, operation: str) -> None:
        if self._unavailable_logged:
            return
        self._unavailable_logged = True
        logger.warning(
            "paired_claim_store_unavailable",
            operation=operation,
            consequence="paired search requests each spend their own token",
            exc_info=True,
        )


_store: SharedClaimStore | None = None
_store_resolved = False


def get_shared_claim_store() -> SharedClaimStore | None:
    """The process's claim store, or None when no shared store is configured."""
    global _store, _store_resolved
    if not _store_resolved:
        _store = _build_store()
        _store_resolved = True
    return _store


def _build_store() -> SharedClaimStore | None:
    uri = shared_storage_uri()
    if uri is None:
        return None
    import redis

    try:
        client = redis.Redis.from_url(
            uri,
            decode_responses=True,
            socket_timeout=STORAGE_SOCKET_TIMEOUT_SECONDS,
            socket_connect_timeout=STORAGE_SOCKET_TIMEOUT_SECONDS,
        )
    except Exception:  # broad: a URL the client rejects must not fail boot
        logger.warning(
            "paired_claim_store_unconfigurable",
            consequence="paired search requests each spend their own token",
            exc_info=True,
        )
        return None
    return SharedClaimStore(client)
