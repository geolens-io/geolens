"""PERF-01 / PERF-09 / PERF-11 regression tests (Phase 274).

PERF-01 — InMemoryTileCacheProvider LRU fallback when REDIS_URL is unset.
PERF-09 — Tile pool DSN parsed via sqlalchemy.engine.url.make_url, not str.replace.
PERF-11 — tile_cache_hits / tile_cache_misses counters carry a `table_name`
          label, with cardinality bounded by the `_safe_label` regex guard.
"""

import pytest

from app.platform.cache.tile_cache import (
    InMemoryTileCacheProvider,
    _SAFE_TABLE_RE,
    _safe_label,
    tile_cache_hits,
    tile_cache_misses,
)


# --- PERF-11: Prometheus label cardinality protection ---------------------


def test_safe_label_passes_data_table_names():
    assert _safe_label("ne_countries_v1") == "ne_countries_v1"
    assert _safe_label("data_layer_42") == "data_layer_42"


def test_safe_label_falls_back_for_unsafe_input():
    assert _safe_label("Drop;") == "_other"
    assert _safe_label("UPPER") == "_other"
    assert _safe_label("") == "_other"
    assert _safe_label("a" * 100) == "_other"  # too long


def test_counters_have_table_name_label():
    # Counter._labelnames is a tuple under prometheus_client.
    assert "table_name" in tile_cache_hits._labelnames
    assert "table_name" in tile_cache_misses._labelnames


def test_safe_table_re_anchors_pattern():
    """_SAFE_TABLE_RE must anchor to start AND end (PERF-11 cardinality)."""
    assert _SAFE_TABLE_RE.match("valid_table_99") is not None
    assert _SAFE_TABLE_RE.match("Invalid") is None  # uppercase rejected
    assert _SAFE_TABLE_RE.match("9_starts_digit") is None  # must start with letter
    assert _SAFE_TABLE_RE.match("has spaces") is None
    assert _SAFE_TABLE_RE.match("has;semicolon") is None


# --- PERF-01: InMemoryTileCacheProvider behavior --------------------------


@pytest.mark.asyncio
async def test_in_memory_tile_cache_set_then_get_returns_bytes():
    cache = InMemoryTileCacheProvider(max_entries=10)
    await cache.set("foo", 0, 0, 0, b"tile-bytes", ttl=300)
    assert await cache.get("foo", 0, 0, 0) == b"tile-bytes"


@pytest.mark.asyncio
async def test_in_memory_tile_cache_miss_returns_none():
    cache = InMemoryTileCacheProvider(max_entries=10)
    assert await cache.get("never-set", 0, 0, 0) is None


@pytest.mark.asyncio
async def test_in_memory_tile_cache_lru_eviction():
    cache = InMemoryTileCacheProvider(max_entries=2)
    await cache.set("a", 0, 0, 0, b"A", ttl=300)
    await cache.set("b", 0, 0, 0, b"B", ttl=300)
    # touch 'a' so 'b' becomes least-recently-used
    await cache.get("a", 0, 0, 0)
    await cache.set("c", 0, 0, 0, b"C", ttl=300)
    assert await cache.get("b", 0, 0, 0) is None  # evicted
    assert await cache.get("a", 0, 0, 0) == b"A"
    assert await cache.get("c", 0, 0, 0) == b"C"


@pytest.mark.asyncio
async def test_in_memory_tile_cache_ttl_expiry():
    cache = InMemoryTileCacheProvider(max_entries=10)
    await cache.set("foo", 0, 0, 0, b"x", ttl=0)
    # ttl=0 means immediately expired on next monotonic tick.
    # The expires_at_monotonic stored is `now + 0` so any subsequent
    # monotonic() reading will be >=, triggering miss-path.
    import time

    time.sleep(0.001)
    assert await cache.get("foo", 0, 0, 0) is None


@pytest.mark.asyncio
async def test_in_memory_tile_cache_invalidate_table():
    cache = InMemoryTileCacheProvider(max_entries=10)
    await cache.set("foo", 0, 0, 0, b"X", ttl=300)
    await cache.set("foo", 1, 0, 0, b"Y", ttl=300)
    await cache.set("bar", 0, 0, 0, b"Z", ttl=300)
    await cache.invalidate_table("foo")
    assert await cache.get("foo", 0, 0, 0) is None
    assert await cache.get("foo", 1, 0, 0) is None
    assert await cache.get("bar", 0, 0, 0) == b"Z"


# --- Provider wiring: redis_url-absent branch -----------------------------


def test_init_tile_cache_falls_back_to_in_memory_when_redis_url_unset(
    monkeypatch,
):
    from app.platform.cache import provider as cache_provider
    from app.core import config as cfg

    # Reset module-level singleton + stub settings
    saved = cache_provider._tile_cache
    cache_provider._tile_cache = None
    # Avoid mutating the real Settings instance; replace just the attribute.
    monkeypatch.setattr(cfg.settings, "redis_url", None, raising=False)

    try:
        cache_provider.init_tile_cache()
        provider_obj = cache_provider.get_tile_cache()
        assert provider_obj is not None
        assert provider_obj.__class__.__name__ == "InMemoryTileCacheProvider"
    finally:
        cache_provider._tile_cache = saved


# --- PERF-09: DSN parsing via make_url ------------------------------------
#
# settings.database_url is a computed property (no setter), so we cannot
# monkeypatch it directly on the Settings instance. Instead we substitute
# the whole `settings` reference inside the pool module with a stub that
# exposes the database_url attribute we want to test.


class _FakeSettings:
    """Minimal stand-in for the Settings instance used by pool._parse_dsn."""

    def __init__(self, database_url: str | None) -> None:
        self.database_url = database_url


def test_parse_dsn_strips_asyncpg_dialect(monkeypatch):
    from app.processing.tiles import pool

    monkeypatch.setattr(
        pool, "settings", _FakeSettings("postgresql+asyncpg://u:p@h:5432/db")
    )
    got = pool._parse_dsn()
    assert got.startswith("postgresql://")
    assert "+asyncpg" not in got


def test_parse_dsn_preserves_query_string(monkeypatch):
    from app.processing.tiles import pool

    monkeypatch.setattr(
        pool,
        "settings",
        _FakeSettings("postgresql+asyncpg://u:p@h:5432/db?sslmode=require"),
    )
    got = pool._parse_dsn()
    assert "sslmode=require" in got


def test_parse_dsn_preserves_url_encoded_password(monkeypatch):
    from app.processing.tiles import pool

    # Password contains an @ which would break naive str.split
    monkeypatch.setattr(
        pool,
        "settings",
        _FakeSettings("postgresql+asyncpg://u:p%40ss@h:5432/db"),
    )
    got = pool._parse_dsn()
    assert "p%40ss" in got or "p@ss" in got, got


def test_parse_dsn_raises_when_database_url_unset(monkeypatch):
    from app.processing.tiles import pool

    monkeypatch.setattr(pool, "settings", _FakeSettings(None))
    with pytest.raises(ValueError, match="database_url"):
        pool._parse_dsn()


def test_parse_dsn_uses_make_url_not_string_replace():
    """Static check: implementation imports make_url and does not contain str.replace."""
    import inspect
    from app.processing.tiles import pool

    src = inspect.getsource(pool._parse_dsn)
    assert "make_url" in src, src
    assert ".replace(" not in src, src
