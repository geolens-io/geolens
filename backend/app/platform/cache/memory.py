import fnmatch
import json
import time
from collections import OrderedDict
from typing import Any

# LRU-capped so a no-Redis deployment can't be OOM'd by
# unbounded distinct cache keys that are never re-requested (so never
# lazily evicted). Coldest entry evicts once full; Redis is unaffected.
_MAX_ENTRIES = 10_000

# Search payloads are keyed by arbitrary anonymous filters, so a count bound
# alone still lets large values add up to gigabytes. Sizes are the JSON length,
# which is what the Redis provider stores for the same value.
_MAX_BYTES = 64 * 1024 * 1024
_MAX_VALUE_BYTES = 1024 * 1024


class InMemoryCacheProvider:
    """In-memory LRU-bounded cache with a time.monotonic() TTL.

    ``security=`` is accepted but ignored. Safe as the layered
    provider's Redis fallback (never asked a security question there) or as
    the sole store in a single-process deployment; unsafe as the sole store
    under multiple workers, since a revoke in one worker won't reach the
    others until TTL expiry.
    """

    def __init__(
        self, max_entries: int = _MAX_ENTRIES, max_bytes: int = _MAX_BYTES
    ) -> None:
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._sizes: dict[str, int] = {}
        self._bytes = 0
        self._max_entries = max_entries
        self._max_bytes = max_bytes

    def _pop(self, key: str) -> None:
        self._store.pop(key, None)
        self._bytes -= self._sizes.pop(key, 0)

    def _put(self, key: str, value: Any, expires_at: float) -> None:
        """Store ``value``, or drop it silently when it is too large to cache."""
        size = len(json.dumps(value, default=str))
        if size > _MAX_VALUE_BYTES or size > self._max_bytes:
            self._pop(key)
            return
        self._pop(key)
        self._store[key] = (value, expires_at)
        self._sizes[key] = size
        self._bytes += size
        while len(self._store) > self._max_entries or self._bytes > self._max_bytes:
            self._pop(next(iter(self._store)))  # evict least-recently-used

    async def get(self, key: str, *, security: bool = False) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            self._pop(key)
            return None
        self._store.move_to_end(key)  # mark most-recently-used
        return value

    async def set(
        self, key: str, value: Any, ttl: int = 300, *, security: bool = False
    ) -> None:
        self._put(key, value, time.monotonic() + ttl)

    async def set_if_absent(
        self, key: str, value: Any, ttl: int = 300, *, security: bool = False
    ) -> bool:
        """Store only when the key is unset (or expired). True if stored.

        No await between the presence check and the write, so no coroutine
        can interleave on a single event loop.
        """
        entry = self._store.get(key)
        if entry is not None and time.monotonic() <= entry[1]:
            return False
        self._put(key, value, time.monotonic() + ttl)
        return key in self._store

    async def compare_and_set(
        self, key: str, expected: Any, value: Any, ttl: int = 300
    ) -> bool:
        # No await between comparison and mutation: another coroutine cannot
        # replace the token in the gap on this event loop.
        entry = self._store.get(key)
        if entry is None or time.monotonic() > entry[1] or entry[0] != expected:
            return False
        self._put(key, value, time.monotonic() + ttl)
        return key in self._store

    async def compare_and_delete(self, key: str, expected: Any) -> bool:
        # Keep comparison and eviction in one uninterrupted event-loop step.
        entry = self._store.get(key)
        if entry is None or time.monotonic() > entry[1] or entry[0] != expected:
            return False
        self._pop(key)
        return True

    async def set_authoritative(self, key: str, value: Any, ttl: int = 300) -> None:
        """One store, so this is ``set``. Named separately because
        the layered provider has to do more."""
        await self.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        self._pop(key)

    async def delete_many(self, *keys: str) -> None:
        # No await inside the loop, so on a single event loop there
        # is no instant at which some of `keys` are gone and the rest are not.
        for key in keys:
            self._pop(key)

    async def delete_pattern(self, pattern: str) -> bool:
        keys_to_delete = [k for k in self._store if fnmatch.fnmatch(k, pattern)]
        for k in keys_to_delete:
            self._pop(k)
        return True

    async def health_check(self) -> None:
        """In-memory cache is always healthy."""
        pass
