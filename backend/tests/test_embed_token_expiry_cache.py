"""Regression tests for SEC-014: embed-token positive-cache expiry re-check.

Without the fix, a token whose expires_at has passed is still allowed on
cache-hit because the cached dict does not include expires_at and the
cache-hit path never re-checks it.

Each test is a pure unit test that monkeypatches the cache and DB so no
running database is required.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


from app.modules.embed_tokens.service import validate_embed_token_access


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_raw_token() -> str:
    import secrets

    return "et_" + secrets.token_urlsafe(32)


def _token_cache_key(raw_token: str) -> str:
    return f"embed_token:{hashlib.sha256(raw_token.encode()).hexdigest()}"


class FakeCache:
    """In-process dict-backed cache with no TTL eviction (we control it)."""

    def __init__(self) -> None:
        self._store: dict = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value, ttl: int = 300) -> None:
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def delete_pattern(self, pattern: str) -> None:
        import fnmatch

        for k in list(self._store):
            if fnmatch.fnmatch(k, pattern):
                del self._store[k]

    async def health_check(self) -> None:
        pass


# ---------------------------------------------------------------------------
# SEC-014 regression: expired token denied even on cache hit
# ---------------------------------------------------------------------------


class TestEmbedTokenExpiryCacheHit:
    """SEC-014: expired token must be denied on the positive-cache-hit path."""

    async def _run(
        self,
        *,
        raw_token: str,
        dataset_id: uuid.UUID,
        cache: FakeCache,
        expires_at: datetime,
        now_for_check: datetime,
    ) -> bool:
        """
        Prime the positive cache with the token, then call
        validate_embed_token_access with *now_for_check* as the apparent wall-clock
        time.  The DB is never reached because the cache is pre-primed.
        """
        cache_key = _token_cache_key(raw_token)

        # Populate the positive-cache entry exactly as the current (unfixed) code
        # does — note: no expires_at is stored here, which is the bug.
        cache._store[cache_key] = {
            "is_valid": True,
            "scoped_dataset_ids": [str(dataset_id)],
            "allowed_origins": None,
            "map_id": str(uuid.uuid4()),
        }

        # Patch get_cache() to return our fake cache
        # Patch datetime.now inside the service module to return now_for_check
        with (
            patch("app.modules.embed_tokens.service.get_cache", return_value=cache),
            patch(
                "app.modules.embed_tokens.service.datetime",
                wraps=datetime,
            ) as mock_dt,
        ):
            mock_dt.now.return_value = now_for_check

            db = AsyncMock()
            result = await validate_embed_token_access(raw_token, dataset_id, db)

        return result

    async def test_expired_token_denied_on_cache_hit(self):
        """
        RED: Without the fix, this PASSES (cache hit returns True even though
        expires_at has elapsed). After the fix, the token's expires_at is stored
        in the cache and re-checked, so this must return False.

        The test primes the cache WITH expires_at set in the past (as the fixed
        code stores it) and verifies the hit path checks and denies the expired
        entry.
        """
        raw_token = _make_raw_token()
        dataset_id = uuid.uuid4()
        cache = FakeCache()

        expires_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        # Now is 1 second after expiry
        now_for_check = expires_at + timedelta(seconds=1)

        # Prime the cache with an expired expires_at (the fixed code stores this)
        cache_key = _token_cache_key(raw_token)
        cache._store[cache_key] = {
            "is_valid": True,
            "scoped_dataset_ids": [str(dataset_id)],
            "allowed_origins": None,
            "map_id": str(uuid.uuid4()),
            "expires_at": expires_at.isoformat(),
        }

        with (
            patch("app.modules.embed_tokens.service.get_cache", return_value=cache),
            patch(
                "app.modules.embed_tokens.service.datetime",
                wraps=datetime,
            ) as mock_dt,
        ):
            mock_dt.now.return_value = now_for_check
            db = AsyncMock()
            result = await validate_embed_token_access(raw_token, dataset_id, db)

        # After the fix: result MUST be False (expired token denied even on cache hit)
        assert result is False, (
            "SEC-014: expired embed token was allowed on cache hit — "
            "the fix must store expires_at in the cache and re-check it."
        )

    async def test_valid_token_allowed_on_cache_hit(self):
        """
        Fast-path must still work for a token that has NOT expired yet.
        A cache hit for an unexpired token must return True after the required
        live map-layer membership revalidation, without reloading the token row.
        """
        raw_token = _make_raw_token()
        dataset_id = uuid.uuid4()
        cache = FakeCache()

        expires_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        # Now is 1 hour BEFORE expiry
        now_for_check = expires_at - timedelta(hours=1)

        cache_key = _token_cache_key(raw_token)
        # Prime cache WITH expires_at (the fixed code stores it this way)
        cache._store[cache_key] = {
            "is_valid": True,
            "scoped_dataset_ids": [str(dataset_id)],
            "allowed_origins": None,
            "map_id": str(uuid.uuid4()),
            "expires_at": expires_at.isoformat(),
        }

        with (
            patch("app.modules.embed_tokens.service.get_cache", return_value=cache),
            patch(
                "app.modules.embed_tokens.service.map_contains_dataset",
                new=AsyncMock(return_value=True),
            ) as membership,
            patch(
                "app.modules.embed_tokens.service.datetime",
                wraps=datetime,
            ) as mock_dt,
        ):
            mock_dt.now.return_value = now_for_check
            db = AsyncMock()
            result = await validate_embed_token_access(raw_token, dataset_id, db)

        assert result is True, "Unexpired cached token must still fast-path to True."
        membership.assert_awaited_once()
        db.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# SEC-014: end-to-end service flow — cache miss populates expires_at, then
# second call (cache hit) still enforces expiry after time advances.
# ---------------------------------------------------------------------------


class TestEmbedTokenExpiryEndToEnd:
    """SEC-014 end-to-end: verify the full cache-miss→prime→hit cycle."""

    async def test_cache_miss_then_expired_hit_denied(self):
        """
        1. First call: cache miss → DB returns a valid token → cache is primed.
        2. Time advances past expires_at.
        3. Second call: cache hit → must return False (expired).

        This tests that the fix stores expires_at at cache-write time.
        """
        raw_token = _make_raw_token()
        dataset_id = uuid.uuid4()
        cache = FakeCache()

        expires_at = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        # DB token mock
        mock_token = MagicMock()
        mock_token.allowed_origins = None
        mock_token.scoped_dataset_ids = [str(dataset_id)]
        mock_token.map_id = uuid.uuid4()
        mock_token.id = uuid.uuid4()
        mock_token.expires_at = expires_at

        async def fake_db_execute(_stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = mock_token
            return result

        db = MagicMock()
        db.execute = fake_db_execute
        # begin_nested must return an async context manager (not a coroutine)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=None)
        cm.__aexit__ = AsyncMock(return_value=False)
        db.begin_nested = MagicMock(return_value=cm)
        db.commit = AsyncMock()

        time_before_expiry = expires_at - timedelta(hours=1)
        time_after_expiry = expires_at + timedelta(seconds=1)

        # --- Call 1: cache miss, time = before expiry ---
        with (
            patch("app.modules.embed_tokens.service.get_cache", return_value=cache),
            patch(
                "app.modules.embed_tokens.service.datetime",
                wraps=datetime,
            ) as mock_dt,
        ):
            mock_dt.now.return_value = time_before_expiry
            result1 = await validate_embed_token_access(raw_token, dataset_id, db)

        assert result1 is True, "First call (cache miss, token valid) should allow."

        # --- Call 2: cache hit, time = after expiry ---
        with (
            patch("app.modules.embed_tokens.service.get_cache", return_value=cache),
            patch(
                "app.modules.embed_tokens.service.datetime",
                wraps=datetime,
            ) as mock_dt,
        ):
            mock_dt.now.return_value = time_after_expiry
            result2 = await validate_embed_token_access(raw_token, dataset_id, db)

        assert result2 is False, (
            "SEC-014: second call after expiry must return False even though "
            "the cache entry still exists (fix must re-check expires_at on hit)."
        )

    async def test_cache_miss_then_valid_hit_allowed(self):
        """
        1. Cache miss → DB → token cached with expires_at.
        2. Second call within validity window → cache hit → allow.
        """
        raw_token = _make_raw_token()
        dataset_id = uuid.uuid4()
        cache = FakeCache()

        expires_at = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_token = MagicMock()
        mock_token.allowed_origins = None
        mock_token.scoped_dataset_ids = [str(dataset_id)]
        mock_token.map_id = uuid.uuid4()
        mock_token.id = uuid.uuid4()
        mock_token.expires_at = expires_at

        async def fake_db_execute(_stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = mock_token
            return result

        db = MagicMock()
        db.execute = fake_db_execute
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=None)
        cm.__aexit__ = AsyncMock(return_value=False)
        db.begin_nested = MagicMock(return_value=cm)
        db.commit = AsyncMock()

        time_valid = expires_at - timedelta(hours=1)

        # Call 1: cache miss
        with (
            patch("app.modules.embed_tokens.service.get_cache", return_value=cache),
            patch(
                "app.modules.embed_tokens.service.datetime",
                wraps=datetime,
            ) as mock_dt,
        ):
            mock_dt.now.return_value = time_valid
            result1 = await validate_embed_token_access(raw_token, dataset_id, db)

        assert result1 is True

        # Call 2: cache hit, still within valid window
        with (
            patch("app.modules.embed_tokens.service.get_cache", return_value=cache),
            patch(
                "app.modules.embed_tokens.service.datetime",
                wraps=datetime,
            ) as mock_dt,
        ):
            mock_dt.now.return_value = time_valid
            result2 = await validate_embed_token_access(raw_token, dataset_id, db)

        assert result2 is True, "Unexpired cached token must fast-path to True."
