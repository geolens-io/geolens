import fnmatch
import time
from collections import OrderedDict
from typing import Any

# fix(#430): LRU-capped so a no-Redis deployment can't be OOM'd by
# unbounded distinct cache keys that are never re-requested (so never
# lazily evicted). Coldest entry evicts once full; Redis is unaffected.
_MAX_ENTRIES = 10_000


class InMemoryCacheProvider:
    """In-memory LRU-bounded cache with a time.monotonic() TTL.

    fix(#1778): ``security=`` is accepted but ignored. Safe as the layered
    provider's Redis fallback (never asked a security question there) or as
    the sole store in a single-process deployment; unsafe as the sole store
    under multiple workers, since a revoke in one worker won't reach the
    others until TTL expiry.
    """

    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_entries = max_entries

    async def get(self, key: str, *, security: bool = False) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)  # mark most-recently-used
        return value

    async def set(
        self, key: str, value: Any, ttl: int = 300, *, security: bool = False
    ) -> None:
        self._store[key] = (value, time.monotonic() + ttl)
        self._store.move_to_end(key)
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)  # evict least-recently-used

    async def set_if_absent(
        self, key: str, value: Any, ttl: int = 300, *, security: bool = False
    ) -> bool:
        """fix(#1778): store only when the key is unset (or expired). True if stored.

        No await between the presence check and the write, so no coroutine
        can interleave on a single event loop.
        """
        entry = self._store.get(key)
        if entry is not None and time.monotonic() <= entry[1]:
            return False
        self._store[key] = (value, time.monotonic() + ttl)
        self._store.move_to_end(key)
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)
        return True

    async def set_authoritative(self, key: str, value: Any, ttl: int = 300) -> None:
        """fix(#1778): one store, so this is ``set``. Named separately because
        the layered provider has to do more."""
        await self.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def delete_many(self, *keys: str) -> None:
        # fix(#1543): no await inside the loop, so on a single event loop there
        # is no instant at which some of `keys` are gone and the rest are not.
        for key in keys:
            self._store.pop(key, None)

    async def delete_pattern(self, pattern: str) -> None:
        keys_to_delete = [k for k in self._store if fnmatch.fnmatch(k, pattern)]
        for k in keys_to_delete:
            self._store.pop(k, None)

    async def health_check(self) -> None:
        """In-memory cache is always healthy."""
        pass
