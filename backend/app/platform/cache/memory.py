import fnmatch
import time
from collections import OrderedDict
from typing import Any

# fix(#430 BA-35): bound the store so a no-Redis deployment can't be OOM'd by an
# attacker issuing many distinct search queries — each writes a unique key that is
# never re-requested (so never lazily evicted). An LRU cap evicts the coldest
# entry once full; the Redis backend is unaffected (server-side TTL).
_MAX_ENTRIES = 10_000


class InMemoryCacheProvider:
    """In-memory cache using an LRU-bounded dict + time.monotonic() TTL.

    Replaces the previous module-level _cache dict pattern in settings/service.py.
    """

    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_entries = max_entries

    async def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)  # mark most-recently-used
        return value

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        self._store[key] = (value, time.monotonic() + ttl)
        self._store.move_to_end(key)
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)  # evict least-recently-used

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def delete_pattern(self, pattern: str) -> None:
        keys_to_delete = [k for k in self._store if fnmatch.fnmatch(k, pattern)]
        for k in keys_to_delete:
            self._store.pop(k, None)

    async def health_check(self) -> None:
        """In-memory cache is always healthy."""
        pass
