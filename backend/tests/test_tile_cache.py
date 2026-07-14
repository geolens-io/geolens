"""Tests for TileCacheProvider and pool settings externalization."""

import gzip
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from app.platform.cache.tile_cache import TileCacheProvider


# --- Fixtures ---


def _read_label_counter(counter, label_value: str) -> float:
    """Read the per-label-set value of a labeled Prometheus Counter (PERF-11).

    Labeled Counters do not expose ``._value`` at the parent level —
    each label combination has its own underlying child. ``.labels(...)``
    returns the child, whose ``._value.get()`` gives the cumulative tally.
    """
    return counter.labels(table_name=label_value)._value.get()


def _reset_label_counter(counter, label_value: str) -> None:
    """Zero a per-label-set Counter for test isolation."""
    counter.labels(table_name=label_value)._value.set(0)


@pytest.fixture
def tile_cache():
    """Create TileCacheProvider backed by fakeredis (binary mode)."""
    provider = TileCacheProvider.__new__(TileCacheProvider)
    provider._client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    # Reset Prometheus counters for isolation. PERF-11 — counters are now
    # labeled by table_name; reset the labels we use in this fixture's
    # downstream tests.
    from app.platform.cache.tile_cache import tile_cache_hits, tile_cache_misses

    for label in ("test_table", "t", "_other"):
        _reset_label_counter(tile_cache_hits, label)
        _reset_label_counter(tile_cache_misses, label)
    return provider


# --- TileCacheProvider get/set tests ---


@pytest.mark.asyncio
async def test_tile_cache_get_miss(tile_cache):
    """Cache miss returns None and increments miss counter."""
    from app.platform.cache.tile_cache import tile_cache_misses

    result = await tile_cache.get("test_table", 5, 10, 15)
    assert result is None
    assert _read_label_counter(tile_cache_misses, "test_table") == 1


@pytest.mark.asyncio
async def test_tile_cache_set_and_get(tile_cache):
    """Binary round-trip: set stores bytes, get returns exact bytes."""
    from app.platform.cache.tile_cache import tile_cache_hits

    raw = b"\x00\x01\x02\x03binary tile data"
    compressed = gzip.compress(raw)
    await tile_cache.set("test_table", 5, 10, 15, compressed, ttl=60)
    result = await tile_cache.get("test_table", 5, 10, 15)
    assert result == compressed
    assert _read_label_counter(tile_cache_hits, "test_table") == 1


@pytest.mark.asyncio
async def test_tile_cache_hit_increments_counter(tile_cache):
    """Successive hits increment the hit counter."""
    from app.platform.cache.tile_cache import tile_cache_hits

    data = gzip.compress(b"tile")
    await tile_cache.set("t", 1, 2, 3, data, ttl=60)
    await tile_cache.get("t", 1, 2, 3)
    await tile_cache.get("t", 1, 2, 3)
    assert _read_label_counter(tile_cache_hits, "t") == 2


@pytest.mark.asyncio
async def test_tile_cache_miss_increments_counter(tile_cache):
    """Successive misses increment the miss counter."""
    from app.platform.cache.tile_cache import tile_cache_misses

    await tile_cache.get("t", 1, 2, 3)
    await tile_cache.get("t", 4, 5, 6)
    assert _read_label_counter(tile_cache_misses, "t") == 2


# --- Graceful degradation tests ---


@pytest.mark.asyncio
async def test_tile_cache_get_returns_none_on_redis_failure():
    """Redis failure on get returns None (graceful degradation)."""
    from app.platform.cache.tile_cache import tile_cache_misses

    _reset_label_counter(tile_cache_misses, "t")

    provider = TileCacheProvider.__new__(TileCacheProvider)
    mock_client = AsyncMock()
    mock_client.get.side_effect = ConnectionError("Redis unavailable")
    provider._client = mock_client

    result = await provider.get("t", 1, 2, 3)
    assert result is None
    assert _read_label_counter(tile_cache_misses, "t") == 1


@pytest.mark.asyncio
async def test_tile_cache_set_silent_on_redis_failure():
    """Redis failure on set is silent (no exception)."""
    provider = TileCacheProvider.__new__(TileCacheProvider)
    mock_client = AsyncMock()
    mock_client.set.side_effect = ConnectionError("Redis unavailable")
    provider._client = mock_client

    # Should not raise
    await provider.set("t", 1, 2, 3, b"data", ttl=60)


# --- invalidate_table tests ---


@pytest.mark.asyncio
async def test_invalidate_table_removes_all_tiles_for_table(tile_cache):
    """invalidate_table removes all cached tiles for the specified table."""
    data = gzip.compress(b"tile")
    # Cache tiles for two tables
    await tile_cache.set("target", 1, 0, 0, data, ttl=60)
    await tile_cache.set("target", 2, 1, 1, data, ttl=60)
    await tile_cache.set("target", 3, 2, 2, data, ttl=60)
    await tile_cache.set("other", 1, 0, 0, data, ttl=60)

    await tile_cache.invalidate_table("target")

    # All target tiles should be gone
    assert await tile_cache.get("target", 1, 0, 0) is None
    assert await tile_cache.get("target", 2, 1, 1) is None
    assert await tile_cache.get("target", 3, 2, 2) is None
    # Other table's tiles should remain
    assert await tile_cache.get("other", 1, 0, 0) == data


@pytest.mark.asyncio
async def test_invalidate_table_noop_when_no_tiles(tile_cache):
    """invalidate_table is a no-op when the table has no cached tiles."""
    # Should not raise
    await tile_cache.invalidate_table("nonexistent")


@pytest.mark.asyncio
async def test_invalidate_table_silent_on_redis_failure():
    """Redis failure on invalidate_table is silent (graceful degradation)."""
    provider = TileCacheProvider.__new__(TileCacheProvider)
    mock_client = AsyncMock()
    mock_client.scan.side_effect = ConnectionError("Redis unavailable")
    provider._client = mock_client

    # Should not raise
    await provider.invalidate_table("test_table")


# --- get_tile_cache singleton tests ---


def test_get_tile_cache_returns_in_memory_provider_when_redis_not_set():
    """get_tile_cache() returns InMemoryTileCacheProvider fallback (PERF-01).

    Before Phase 274, an unset REDIS_URL meant ``get_tile_cache()``
    returned ``None`` and the tile router silently bypassed caching.
    PERF-01 wires a bounded LRU fallback so smaller deployments still
    benefit from caching without Redis.
    """
    from unittest.mock import patch

    from app.platform.cache import provider as cache_provider
    from app.platform.cache.tile_cache import InMemoryTileCacheProvider

    old = cache_provider._tile_cache
    try:
        cache_provider._tile_cache = None
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.redis_url = None
            cache_provider.init_tile_cache()
            result = cache_provider.get_tile_cache()
            assert isinstance(result, InMemoryTileCacheProvider)
    finally:
        cache_provider._tile_cache = old


def test_get_tile_cache_returns_provider_when_redis_set():
    """get_tile_cache() returns TileCacheProvider when redis_url is configured."""
    from unittest.mock import patch

    from app.platform.cache import provider as cache_provider

    old = cache_provider._tile_cache
    try:
        cache_provider._tile_cache = None
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379"
            cache_provider.init_tile_cache()
            result = cache_provider.get_tile_cache()
            assert isinstance(result, TileCacheProvider)
    finally:
        cache_provider._tile_cache = old


# --- Pool settings tests ---


def test_settings_db_pool_size_default():
    """Settings.db_pool_size defaults to 10."""
    from app.core.config import settings

    assert settings.db_pool_size == 10


def test_settings_tile_pool_max_size_default():
    """Settings.tile_pool_max_size defaults to 10."""
    from app.core.config import settings

    assert settings.tile_pool_max_size == 10


def test_settings_db_pool_size_env_override(monkeypatch):
    """DB_POOL_SIZE env var overrides db_pool_size default."""
    monkeypatch.setenv("DB_POOL_SIZE", "25")
    # Re-create settings to pick up env var
    from app.core.config import Settings

    s = Settings(
        postgres_password="test",
        jwt_secret_key="test-jwt-secret-padding-to-32-chars",
        geolens_admin_username="admin",
        geolens_admin_password="admin",
    )
    assert s.db_pool_size == 25


def test_settings_tile_pool_max_size_env_override(monkeypatch):
    """TILE_POOL_MAX_SIZE env var overrides tile_pool_max_size default."""
    monkeypatch.setenv("TILE_POOL_MAX_SIZE", "20")
    from app.core.config import Settings

    s = Settings(
        postgres_password="test",
        jwt_secret_key="test-jwt-secret-padding-to-32-chars",
        geolens_admin_username="admin",
        geolens_admin_password="admin",
    )
    assert s.tile_pool_max_size == 20


# --- H-10: tile pool drops privileges to geolens_reader ---


def test_parse_dsn_uses_dedicated_tile_url(monkeypatch):
    from app.processing.tiles import pool as pool_module

    monkeypatch.setattr(
        pool_module,
        "settings",
        SimpleNamespace(
            tile_database_url="postgresql+asyncpg://tile:secret@db/geolens"
        ),
    )

    assert pool_module._parse_dsn() == "postgresql://tile:secret@db/geolens"


def test_multi_tenant_tile_pool_requires_explicit_override(monkeypatch):
    from app.processing.tiles import pool as pool_module

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    monkeypatch.setattr(
        pool_module,
        "settings",
        SimpleNamespace(
            tile_database_url_override=None,
            tile_database_url="postgresql+asyncpg://app:secret@db/geolens",
            database_url="postgresql+asyncpg://app:secret@db/geolens",
        ),
    )

    with pytest.raises(RuntimeError, match="TILE_DATABASE_URL_OVERRIDE is required"):
        pool_module._validate_tile_database_isolation()


def test_multi_tenant_tile_pool_rejects_runtime_login_reuse(monkeypatch):
    from app.processing.tiles import pool as pool_module

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    monkeypatch.setattr(
        pool_module,
        "settings",
        SimpleNamespace(
            tile_database_url_override="postgresql://app:other@db/geolens",
            tile_database_url="postgresql+asyncpg://app:other@db/geolens",
            database_url="postgresql+asyncpg://app:secret@db/geolens",
        ),
    )

    with pytest.raises(RuntimeError, match="dedicated Postgres login"):
        pool_module._validate_tile_database_isolation()


def test_multi_tenant_tile_pool_accepts_distinct_login(monkeypatch):
    from app.processing.tiles import pool as pool_module

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    monkeypatch.setattr(
        pool_module,
        "settings",
        SimpleNamespace(
            tile_database_url_override="postgresql://tile:secret@db/geolens",
            tile_database_url="postgresql+asyncpg://tile:secret@db/geolens",
            database_url="postgresql+asyncpg://app:secret@db/geolens",
        ),
    )

    pool_module._validate_tile_database_isolation()


@pytest.mark.asyncio
async def test_setup_tile_connection_issues_set_role():
    """_setup_tile_connection runs ``SET ROLE geolens_reader`` on every fresh
    pool checkout so tile-path queries cannot mutate or drop tables (H-10)."""
    from app.processing.tiles.pool import _setup_tile_connection

    conn = AsyncMock()
    await _setup_tile_connection(conn)

    conn.execute.assert_awaited_once_with("SET ROLE geolens_reader")


@pytest.mark.asyncio
async def test_setup_tile_connection_logs_and_continues_on_postgres_error(monkeypatch):
    """If geolens_reader doesn't exist (e.g. legacy upgrade pre-v6.0), the
    setup callback logs a warning and lets the connection serve requests
    rather than crashing the pool (H-10)."""
    import asyncpg

    from app.processing.tiles.pool import _setup_tile_connection

    conn = AsyncMock()
    conn.execute.side_effect = asyncpg.PostgresError("role does not exist")

    # Should not raise — the warning path is the contract.
    await _setup_tile_connection(conn)
    conn.execute.assert_awaited_once_with("SET ROLE geolens_reader")


@pytest.mark.asyncio
async def test_init_tile_pool_passes_setup_callback(monkeypatch):
    """init_tile_pool wires ``setup=_setup_tile_connection`` into
    asyncpg.create_pool so every fresh connection drops privileges."""
    from app.processing.tiles import pool as pool_module

    captured_kwargs: dict = {}

    async def _fake_create_pool(**kwargs):
        captured_kwargs.update(kwargs)
        # Return a sentinel; caller stores it in _tile_pool but we'll
        # tear it down at the end of the test.
        return AsyncMock()

    monkeypatch.setattr(pool_module.asyncpg, "create_pool", _fake_create_pool)

    try:
        await pool_module.init_tile_pool()
    finally:
        # Ensure module-level state is reset so other tests don't see a fake.
        pool_module._tile_pool = None

    assert captured_kwargs.get("setup") is pool_module._setup_tile_connection
    assert captured_kwargs.get("init") is pool_module._init_tile_connection


def _tile_role_row(**overrides):
    row = {
        "login_name": "geolens_tile",
        "effective_name": "geolens_tile",
        "is_superuser": False,
        "bypasses_rls": False,
        "creates_roles": False,
        "creates_databases": False,
        "replicates": False,
        "can_assume_powerful_role": False,
        "has_forbidden_membership": False,
        "can_assume_catalog_table_owner": False,
        "can_assume_tenant_schema_owner": False,
        "can_create_in_protected_schema": False,
        "has_tile_gateway": True,
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_live_tile_role_guard_accepts_only_gateway_member(monkeypatch):
    from app.processing.tiles.pool import _assert_multi_tenant_tile_role

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    conn = AsyncMock()
    conn.fetchrow.return_value = _tile_role_row()
    await _assert_multi_tenant_tile_role(conn)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_field",
    [
        "is_superuser",
        "bypasses_rls",
        "creates_roles",
        "creates_databases",
        "replicates",
        "can_assume_powerful_role",
        "has_forbidden_membership",
        "can_assume_catalog_table_owner",
        "can_assume_tenant_schema_owner",
        "can_create_in_protected_schema",
    ],
)
async def test_tile_role_guard_rejects_each_privilege_path(monkeypatch, unsafe_field):
    from app.processing.tiles.pool import _assert_multi_tenant_tile_role

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    conn = AsyncMock()
    conn.fetchrow.return_value = _tile_role_row(**{unsafe_field: True})
    with pytest.raises(RuntimeError, match="least-privilege LOGIN"):
        await _assert_multi_tenant_tile_role(conn)


@pytest.mark.asyncio
async def test_tile_role_guard_rejects_missing_tile_gateway(monkeypatch):
    from app.processing.tiles.pool import _assert_multi_tenant_tile_role

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    conn = AsyncMock()
    conn.fetchrow.return_value = _tile_role_row(has_tile_gateway=False)
    with pytest.raises(RuntimeError, match="geolens_tile_gateway"):
        await _assert_multi_tenant_tile_role(conn)


@pytest.mark.asyncio
async def test_tile_role_guard_rejects_live_superuser_session(monkeypatch):
    """A renamed/distinct superuser cannot pass the live DSN validation."""
    import asyncpg

    from app.core.config import settings
    from app.processing.tiles.pool import _assert_multi_tenant_tile_role

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    dsn = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        if not await conn.fetchval(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ):
            pytest.skip("Live negative requires the test database superuser")
        with pytest.raises(RuntimeError, match="least-privilege LOGIN"):
            await _assert_multi_tenant_tile_role(conn)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_tile_role_guard_rejects_live_tenant_schema_owner(monkeypatch):
    """Gateway membership cannot make a tile login safe if it owns data."""
    import asyncpg
    from sqlalchemy.engine import make_url

    from app.core.config import settings
    from app.processing.tiles.pool import _assert_multi_tenant_tile_role

    suffix = uuid.uuid4().hex
    login = f"oc_tile_owner_{suffix[:12]}"
    password = f"OcTileOwner{suffix}"
    schema = f"data_t_{uuid.uuid4().hex[:8]}_0000_0000_0000_000000000000"
    gateway = "geolens_tile_gateway"
    admin_dsn = settings.test_database_url.replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    admin = await asyncpg.connect(admin_dsn)
    tile_conn = None
    gateway_created = False
    try:
        if not await admin.fetchval(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ):
            pytest.skip("Live ownership regression requires the test DB superuser")
        if not await admin.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = $1)", gateway
        ):
            await admin.execute(
                f"CREATE ROLE {gateway} NOLOGIN NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
            )
            gateway_created = True
        await admin.execute(
            f"CREATE ROLE {login} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            f"NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD '{password}'"
        )
        await admin.execute(f"GRANT {gateway} TO {login} WITH INHERIT FALSE, SET TRUE")
        await admin.execute(f"CREATE SCHEMA {schema} AUTHORIZATION {login}")

        login_dsn = (
            make_url(settings.test_database_url)
            .set(username=login, password=password, drivername="postgresql")
            .render_as_string(hide_password=False)
        )
        tile_conn = await asyncpg.connect(login_dsn)
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        with pytest.raises(RuntimeError, match="protected-object ownership"):
            await _assert_multi_tenant_tile_role(tile_conn)
    finally:
        if tile_conn is not None:
            await tile_conn.close()
        await admin.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        await admin.execute(f"DROP ROLE IF EXISTS {login}")
        if gateway_created:
            await admin.execute(f"DROP ROLE IF EXISTS {gateway}")
        await admin.close()


@pytest.mark.asyncio
async def test_invalidate_table_purges_only_active_tenant_keys(tile_cache, monkeypatch):
    """A tenant mutation must not evict a peer's same-named tile cache."""
    from app.core.config import settings
    from app.core.db.tenant_session import current_tenant_var

    tenant_a = "11111111-2222-3333-4444-555555555555"
    tenant_b = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    monkeypatch.setattr(settings, "geolens_tenancy_mode", "multi_tenant")
    data = gzip.compress(b"tile")
    await tile_cache.set("target", 1, 0, 0, data, ttl=60)
    await tile_cache.set(f"{tenant_a}:target", 1, 0, 0, data, ttl=60)
    await tile_cache.set(f"{tenant_b}:target", 1, 0, 0, data, ttl=60)
    await tile_cache.set("other", 1, 0, 0, data, ttl=60)

    token = current_tenant_var.set(tenant_a)
    try:
        await tile_cache.invalidate_table("target")
    finally:
        current_tenant_var.reset(token)

    assert await tile_cache.get(f"{tenant_a}:target", 1, 0, 0) is None
    assert await tile_cache.get(f"{tenant_b}:target", 1, 0, 0) == data
    assert await tile_cache.get("target", 1, 0, 0) == data
    assert await tile_cache.get("other", 1, 0, 0) == data


@pytest.mark.asyncio
async def test_in_memory_invalidate_table_is_tenant_scoped(monkeypatch):
    """The in-memory fallback applies the same active-tenant boundary."""
    from app.core.config import settings
    from app.core.db.tenant_session import current_tenant_var
    from app.platform.cache.tile_cache import InMemoryTileCacheProvider

    tenant_a = "11111111-2222-3333-4444-555555555555"
    tenant_b = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    monkeypatch.setattr(settings, "geolens_tenancy_mode", "multi_tenant")
    cache = InMemoryTileCacheProvider(max_entries=10)
    await cache.set("target", 1, 0, 0, b"a", ttl=60)
    await cache.set(f"{tenant_a}:target", 1, 0, 0, b"b", ttl=60)
    await cache.set(f"{tenant_b}:target", 1, 0, 0, b"d", ttl=60)
    await cache.set("other", 1, 0, 0, b"c", ttl=60)

    token = current_tenant_var.set(tenant_a)
    try:
        await cache.invalidate_table("target")
    finally:
        current_tenant_var.reset(token)

    assert await cache.get(f"{tenant_a}:target", 1, 0, 0) is None
    assert await cache.get(f"{tenant_b}:target", 1, 0, 0) == b"d"
    assert await cache.get("target", 1, 0, 0) == b"a"
    assert await cache.get("other", 1, 0, 0) == b"c"
