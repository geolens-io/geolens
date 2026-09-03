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

    fix(#1778 codex r3): ``security=`` is accepted and ignored here, and both
    halves of that are deliberate.

    As the LAYERED provider's fallback it is never asked a security question at
    all: ``RedisCacheProvider`` refuses to route one here, because a positive
    authorization decision held in one Uvicorn worker's memory is not the
    deployment's view and cannot see a revoke another worker performed.

    As the WHOLE cache -- ``REDIS_URL`` unset -- it is the only store there is,
    so serving a security positive from it is exactly as correct as the
    deployment is single-process. It is not correct under ``uvicorn --workers N``
    without Redis: each worker then caches independently and a revoke in one is
    invisible to the others until the entry's TTL expires. That is a property of
    running a multi-process deployment without a shared cache rather than
    something this class can fix, and it is the same reason ``init_tile_cache``
    warns about an unset ``REDIS_URL`` in the worker.
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
        """fix(#1778): store only when the key is unset. True if stored.

        No await between the presence check and the write, so on a single event
        loop no other coroutine can interleave -- the same reasoning
        ``delete_many`` relies on. An entry whose TTL has passed counts as
        absent: ``get`` would evict it anyway.
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
        """fix(#1778 codex r1): one store, so this is ``set``. Named separately
        because the layered provider has to do more."""
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
