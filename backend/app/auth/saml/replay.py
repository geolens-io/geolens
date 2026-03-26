"""In-memory TTL-based assertion ID replay cache for SAML."""

import time
from threading import Lock


class ReplayCache:
    """Prevents SAML assertion replay by tracking seen assertion IDs with TTL."""

    def __init__(self, ttl_seconds: int = 600):
        self._seen: dict[str, float] = {}
        self._ttl = ttl_seconds
        self._lock = Lock()

    def check_and_record(self, assertion_id: str) -> bool:
        """Return True if assertion_id is new (not replayed). Record it."""
        now = time.monotonic()
        with self._lock:
            self._evict(now)
            if assertion_id in self._seen:
                return False
            self._seen[assertion_id] = now
            return True

    def _evict(self, now: float) -> None:
        """Remove entries older than TTL."""
        expired = [k for k, t in self._seen.items() if now - t > self._ttl]
        for k in expired:
            del self._seen[k]


# Module-level singleton
replay_cache = ReplayCache()
