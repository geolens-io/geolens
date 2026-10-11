"""Tests for PersistentConfig generic class and centralized registry."""

import asyncio
import time
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.config import settings


@pytest.fixture(autouse=True)
async def _clean_settings(client: AsyncClient):
    """Clean up any DB settings overrides after each test."""
    yield
    # Remove any settings rows inserted during tests
    from app.core.dependencies import get_db
    from app.api.main import app
    from app.core.db.models import AppSetting

    async for db in app.dependency_overrides[get_db]():
        await db.execute(delete(AppSetting))
        await db.commit()

    # Invalidate cache for all config keys
    from app.platform.cache import get_cache

    try:
        cache = get_cache()
        from app.core.persistent_config import _registry

        for cfg in _registry:
            await cache.delete(f"config:{cfg.key}")
    except RuntimeError:
        pass

    # BUG-008: the per-process sync rate-limit cache is now warmed on
    # set()/reset(); clear it between tests so a warmed value never leaks into
    # an unrelated case.
    from app.core.persistent_config import _sync_rate_limit_cache

    _sync_rate_limit_cache.clear()


# ---------------------------------------------------------------------------
# Unit / Integration tests for PersistentConfig class
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_returns_env_default_when_no_db_row(client: AsyncClient):
    """get() returns env_default when no DB row exists."""
    from app.core.persistent_config import REGISTRATION_ENABLED

    from app.core.dependencies import get_db
    from app.api.main import app

    async for db in app.dependency_overrides[get_db]():
        value = await REGISTRATION_ENABLED.get(db)
        # env_default for registration_enabled comes from settings.registration_enabled (False)
        assert value is False


@pytest.mark.anyio
async def test_get_returns_db_value_when_row_exists(client: AsyncClient):
    """get() returns DB value when row exists and ENV_ONLY_CONFIG is not set."""
    from app.core.persistent_config import REGISTRATION_ENABLED

    from app.core.dependencies import get_db
    from app.api.main import app

    async for db in app.dependency_overrides[get_db]():
        # Set a value in DB
        await REGISTRATION_ENABLED.set(db, True)
        value = await REGISTRATION_ENABLED.get(db)
        assert value is True

        # Clean up
        await REGISTRATION_ENABLED.set(db, False)


@pytest.mark.anyio
async def test_get_returns_env_default_when_env_only(client: AsyncClient):
    """get() returns env_default (ignoring DB) when ENV_ONLY_CONFIG=true."""
    from app.core.persistent_config import REGISTRATION_ENABLED

    from app.core.dependencies import get_db
    from app.api.main import app

    async for db in app.dependency_overrides[get_db]():
        # Set value in DB first
        await REGISTRATION_ENABLED.set(db, True)

        # Now enable ENV_ONLY mode
        with patch.object(settings, "env_only_config", True):
            value = await REGISTRATION_ENABLED.get(db)
            assert value is False  # Should return env_default, not DB value


@pytest.mark.anyio
async def test_set_raises_when_env_only(client: AsyncClient):
    """set() raises error (403-style) when ENV_ONLY_CONFIG=true."""
    from app.core.persistent_config import REGISTRATION_ENABLED

    from app.core.dependencies import get_db
    from app.api.main import app

    async for db in app.dependency_overrides[get_db]():
        with patch.object(settings, "env_only_config", True):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await REGISTRATION_ENABLED.set(db, True)
            assert exc_info.value.status_code == 403


@pytest.mark.anyio
async def test_set_creates_audit_log_entry(client: AsyncClient):
    """set() creates audit log entry with {setting_key, old_value, new_value}."""
    from sqlalchemy import select

    from app.modules.audit.models import AuditLog
    from app.modules.auth.models import User
    from app.core.config import settings as app_settings
    from app.core.persistent_config import REGISTRATION_ENABLED

    from app.core.dependencies import get_db
    from app.api.main import app

    async for db in app.dependency_overrides[get_db]():
        # Get the real admin user id
        result = await db.execute(
            select(User).where(User.username == app_settings.geolens_admin_username)
        )
        admin_user = result.scalar_one()

        await REGISTRATION_ENABLED.set(
            db, True, user_id=admin_user.id, ip_address="127.0.0.1"
        )

        # Check audit log
        result = await db.execute(
            select(AuditLog)
            .where(AuditLog.resource_type == "setting")
            .where(AuditLog.user_id == admin_user.id)
            .order_by(AuditLog.created_at.desc())
        )
        entry = result.scalars().first()
        assert entry is not None
        assert entry.action == "update"
        assert entry.details["setting_key"] == "registration_enabled"
        assert entry.details["new_value"] is True
        assert entry.ip_address == "127.0.0.1"

        # Clean up
        await REGISTRATION_ENABLED.set(db, False)


@pytest.mark.anyio
async def test_set_invalidates_cache(client: AsyncClient):
    """set() invalidates cache after write."""
    from app.platform.cache import init_cache, get_cache
    from app.core.persistent_config import REGISTRATION_ENABLED

    from app.core.dependencies import get_db
    from app.api.main import app

    # Ensure cache is initialized (may have been cleared by other tests)
    init_cache()

    async for db in app.dependency_overrides[get_db]():
        # Prime cache via get
        await REGISTRATION_ENABLED.get(db)
        cache = get_cache()
        cached = await cache.get("config:registration_enabled")
        # Cache should have a value now
        assert cached is not None

        # Set new value should invalidate
        await REGISTRATION_ENABLED.set(db, True)
        cached_after = await cache.get("config:registration_enabled")
        assert cached_after is None

        # Clean up
        await REGISTRATION_ENABLED.set(db, False)


@pytest.mark.anyio
async def test_get_uncached_bypasses_stale_cache(client: AsyncClient):
    """Codex P2: get_uncached returns the committed DB value, ignoring a cache
    entry holding a different value.

    The SSO lockout guards rely on this: a concurrent password-disable
    invalidates the cache BEFORE its commit, so another reader can repopulate
    the cache with the pre-commit value. A guard reading the cached flag would
    resume on a stale value and skip the last-provider check. get_uncached reads
    straight from the DB so it observes the committed value under the held lock.
    """
    from app.core.persistent_config import PASSWORD_LOGIN_ENABLED
    from app.platform.cache import get_cache, init_cache

    from app.core.dependencies import get_db
    from app.api.main import app

    init_cache()
    async for db in app.dependency_overrides[get_db]():
        try:
            # Commit the real DB value = False (set() invalidates the cache).
            await PASSWORD_LOGIN_ENABLED.set(db, False)
            # Poison the cache with a STALE True, simulating a reader that
            # repopulated it during a writer's invalidate -> commit window.
            await get_cache().set("config:password_login_enabled", True, ttl=30)

            # The cached read returns the stale value...
            assert await PASSWORD_LOGIN_ENABLED.get(db) is True
            # ...but get_uncached returns the committed DB value.
            assert await PASSWORD_LOGIN_ENABLED.get_uncached(db) is False
        finally:
            await PASSWORD_LOGIN_ENABLED.set(db, True)


@pytest.mark.anyio
async def test_set_public_url_invalidates_public_url_cache(client: AsyncClient):
    """BUG-025: writing a public-URL key invalidates the public_urls module cache.

    public_urls._PUBLIC_URL_CACHE is a SEPARATE 60s memoization from the
    config: cache. Before the fix, PUBLIC_APP_URL.set() cleared only the
    config: key, so get_public_urls() kept returning the OLD value for up to
    60s — the PUT /settings response and tile-config appeared to ignore the
    save. After the fix, the next read reflects the new value immediately.
    """
    from unittest.mock import patch

    from app.core import public_urls
    from app.core.persistent_config import PUBLIC_APP_URL

    from app.core.dependencies import get_db
    from app.api.main import app

    public_urls._PUBLIC_URL_CACHE = None
    # ENV_ONLY_CONFIG must be off for DB overrides to flow through.
    with patch.object(public_urls.settings, "env_only_config", False):
        async for db in app.dependency_overrides[get_db]():
            try:
                await PUBLIC_APP_URL.set(db, "https://old.example.com")
                # Prime the public_urls module cache with the OLD value.
                app_url, _ = await public_urls.get_public_urls(db)
                assert app_url == "https://old.example.com"
                assert public_urls._PUBLIC_URL_CACHE is not None

                # Writing the key must clear the module cache (the fix).
                await PUBLIC_APP_URL.set(db, "https://new.example.com")
                assert public_urls._PUBLIC_URL_CACHE is None

                # And the next read must reflect the NEW value, not the stale one.
                app_url_after, _ = await public_urls.get_public_urls(db)
                assert app_url_after == "https://new.example.com"
            finally:
                await PUBLIC_APP_URL.reset(db)
                public_urls._PUBLIC_URL_CACHE = None


@pytest.mark.anyio
async def test_get_uses_cache_with_ttl(client: AsyncClient):
    """get() uses cache with 30s TTL -- second call within TTL returns cached value."""
    from app.platform.cache import init_cache, get_cache
    from app.core.persistent_config import REGISTRATION_ENABLED

    from app.core.dependencies import get_db
    from app.api.main import app

    # Ensure cache is initialized (may have been cleared by other tests)
    init_cache()

    async for db in app.dependency_overrides[get_db]():
        # First call populates cache
        val1 = await REGISTRATION_ENABLED.get(db)
        cache = get_cache()
        cached = await cache.get("config:registration_enabled")
        assert cached is not None

        # Second call should use cache (we just verify it returns same value)
        val2 = await REGISTRATION_ENABLED.get(db)
        assert val1 == val2


@pytest.mark.anyio
async def test_registry_contains_all_declared_instances(client: AsyncClient):
    """Registry list contains all declared PersistentConfig instances."""
    from app.core.persistent_config import _registry

    # Should have at least 15 instances
    assert len(_registry) >= 15

    # Check key ones exist
    keys = {cfg.key for cfg in _registry}
    expected_keys = {
        "registration_enabled",
        "public_app_url",
        "public_api_url",
        "public_base_url",
        "log_level",
        "log_json",
        "access_token_expire_minutes",
        "refresh_token_expire_days",
        "login_rate_limit",
        "ai_enabled",
        "llm_provider",
        "llm_model",
        "cors_allowed_origins",
        "upload_max_size_mb",
        "upload_allowed_extensions",
        "tile_cache_ttl",
        "basemaps",
        "map_defaults",
    }
    assert expected_keys.issubset(keys), f"Missing keys: {expected_keys - keys}"


@pytest.mark.anyio
async def test_log_level_side_effect(client: AsyncClient):
    """LOG_LEVEL set() propagates to root logger."""
    import logging

    from app.core.persistent_config import LOG_LEVEL

    from app.core.dependencies import get_db
    from app.api.main import app

    original_level = logging.getLogger().level
    try:
        async for db in app.dependency_overrides[get_db]():
            await LOG_LEVEL.set(db, "DEBUG")
            assert logging.getLogger().level == logging.DEBUG

            # Restore
            await LOG_LEVEL.set(db, "INFO")
            assert logging.getLogger().level == logging.INFO
    finally:
        logging.getLogger().setLevel(original_level)


@pytest.mark.anyio
async def test_log_level_side_effect_raises_httpx_floor_too(client: AsyncClient):
    """fix(#1746 codex r8): a runtime LOG_LEVEL change must raise httpx's floor.

    `apply_http_logger_levels()` keeps httpx/httpcore at least WARNING, but
    that floor has to track root upward too: a LOG_LEVEL=CRITICAL change made
    through the admin settings UI at runtime (not just LOG_LEVEL set at boot)
    must not leave httpx sitting at WARNING -- MORE verbose than the
    deployment just asked for. The round 5/6 test guards already restore
    httpx/httpcore's level around every test, so no manual cleanup is needed
    for those two here; only root's own level is restored, matching the
    sibling test above.
    """
    import logging

    from app.core.persistent_config import LOG_LEVEL

    from app.core.dependencies import get_db
    from app.api.main import app

    original_level = logging.getLogger().level
    try:
        async for db in app.dependency_overrides[get_db]():
            await LOG_LEVEL.set(db, "CRITICAL")
            assert logging.getLogger().level == logging.CRITICAL
            assert logging.getLogger("httpx").level == logging.CRITICAL
            assert logging.getLogger("httpcore").level == logging.CRITICAL

            # Dropping back below WARNING restores the WARNING floor.
            await LOG_LEVEL.set(db, "INFO")
            assert logging.getLogger("httpx").level == logging.WARNING
            assert logging.getLogger("httpcore").level == logging.WARNING
    finally:
        logging.getLogger().setLevel(original_level)


@pytest.mark.anyio
async def test_sync_rate_limit_accessor(client: AsyncClient):
    """Sync rate limit accessor returns cached value or default."""
    from app.core.persistent_config import LOGIN_RATE_LIMIT, get_cached_login_rate_limit

    from app.core.dependencies import get_db
    from app.api.main import app

    async for db in app.dependency_overrides[get_db]():
        # Prime the sync cache by reading the value
        val = await LOGIN_RATE_LIMIT.get(db)

        # Sync accessor should return same value
        sync_val = get_cached_login_rate_limit()
        assert sync_val == val


@pytest.mark.anyio
async def test_set_warms_sync_cache_with_new_value(client: AsyncClient):
    """BUG-008: set() must warm the sync rate-limit cache with the NEW value.

    On main, set() warmed the sync cache only with the OLD value (via the
    get(db) at the top of set()) and never the new one, so slowapi kept
    enforcing the previous limit until the 30s TTL expired — and because no
    request-path code ever calls .get() for these keys, the admin's new value
    was effectively never applied in this process. This test fails on main (the
    accessor still returns the old default right after set()).
    """
    from app.core.persistent_config import (
        _sync_rate_limit_cache,
        LOGIN_RATE_LIMIT,
        get_cached_login_rate_limit,
    )

    from app.api.main import app
    from app.core.dependencies import get_db

    _sync_rate_limit_cache.pop("login_rate_limit", None)
    new_value = LOGIN_RATE_LIMIT.env_default + 7

    async for db in app.dependency_overrides[get_db]():
        await LOGIN_RATE_LIMIT.set(db, new_value)
        # Immediately (well within the TTL) the slowapi accessor must observe
        # the value just set, not the old default.
        assert get_cached_login_rate_limit() == new_value

        # reset() must warm the sync cache back to env_default.
        await LOGIN_RATE_LIMIT.reset(db)
        assert get_cached_login_rate_limit() == LOGIN_RATE_LIMIT.env_default


# ---------------------------------------------------------------------------
# Unified settings API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def admin_auth_header(client: AsyncClient) -> dict:
    """Get admin auth header."""
    from app.core.config import settings as app_settings

    resp = await client.post(
        "/auth/login",
        data={
            "username": app_settings.geolens_admin_username,
            "password": app_settings.geolens_admin_password.get_secret_value(),
        },
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_get_all_settings_returns_grouped(
    client: AsyncClient, admin_auth_header: dict
):
    """GET /settings/all/ returns grouped settings with source indicators."""
    resp = await client.get("/settings/all/", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "env_only" in data
    assert data["env_only"] is False
    assert "tabs" in data

    # Check expected tabs exist
    tabs = data["tabs"]
    assert "general" in tabs
    assert "auth" in tabs
    assert "ai" in tabs
    assert "storage" in tabs
    assert "map" in tabs

    # Check each setting has required fields
    for tab_name, items in tabs.items():
        for item in items:
            assert "key" in item
            assert "value" in item
            assert "source" in item
            assert "label" in item
            assert item["source"] in ("default", "overridden", "env_only")


@pytest.mark.anyio
async def test_get_all_settings_env_only_shows_env_default_not_db_override(
    client: AsyncClient, admin_auth_header: dict
):
    """BUG-030: GET /settings/all in ENV_ONLY_CONFIG mode shows the effective
    env_default, not the stale DB override.

    PersistentConfig.get short-circuits to env_default when env_only is set, so
    any DB override is dead data at runtime. Before the fix, get_all_settings
    still resolved the value from the DB row (labeled env_only), showing config
    that is NOT in effect. After the fix it shows env_default.
    """
    from app.core.persistent_config import REGISTRATION_ENABLED

    from app.core.dependencies import get_db
    from app.api.main import app

    # registration_enabled env_default is False; write a True DB override.
    async for db in app.dependency_overrides[get_db]():
        await REGISTRATION_ENABLED.set(db, True)
        break

    # Sanity: with env_only OFF, the override IS reflected (overridden source).
    resp = await client.get("/settings/all/", headers=admin_auth_header)
    auth = resp.json()["tabs"]["auth"]
    reg = next(s for s in auth if s["key"] == "registration_enabled")
    assert reg["value"] is True
    assert reg["source"] == "overridden"

    # With env_only ON, the running system uses env_default (False) — the
    # screen must show that, not the dead DB override.
    with patch.object(settings, "env_only_config", True):
        resp = await client.get("/settings/all/", headers=admin_auth_header)
        assert resp.json()["env_only"] is True
        auth = resp.json()["tabs"]["auth"]
        reg = next(s for s in auth if s["key"] == "registration_enabled")
        assert reg["value"] is False, (
            "ENV_ONLY_CONFIG must show env_default, not the stale DB override"
        )
        assert reg["source"] == "env_only"

    # Clean up the override.
    async for db in app.dependency_overrides[get_db]():
        await REGISTRATION_ENABLED.set(db, False)
        break


@pytest.mark.anyio
async def test_put_settings_updates_value_with_audit(
    client: AsyncClient, admin_auth_header: dict
):
    """PUT /settings/ with {registration_enabled: true} updates value and creates audit entry."""
    resp = await client.put(
        "/settings/",
        json={"settings": {"registration_enabled": True}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()

    # Find registration_enabled in the auth tab
    auth = data["tabs"]["auth"]
    reg_setting = next(s for s in auth if s["key"] == "registration_enabled")
    assert reg_setting["value"] is True
    assert reg_setting["source"] == "overridden"

    # Reset
    await client.put(
        "/settings/",
        json={"settings": {"registration_enabled": False}},
        headers=admin_auth_header,
    )


@pytest.mark.anyio
async def test_put_settings_returns_403_when_env_only(
    client: AsyncClient, admin_auth_header: dict
):
    """PUT /settings/ returns 403 when ENV_ONLY_CONFIG=true."""
    with patch.object(settings, "env_only_config", True):
        resp = await client.put(
            "/settings/",
            json={"settings": {"registration_enabled": True}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 403


@pytest.mark.anyio
async def test_get_config_mode_reports_env_only(client: AsyncClient):
    """GET /settings/config-mode/ returns {env_only: false} normally."""
    resp = await client.get("/settings/config-mode/")
    assert resp.status_code == 200
    assert resp.json()["env_only"] is False

    with patch.object(settings, "env_only_config", True):
        resp = await client.get("/settings/config-mode/")
        assert resp.status_code == 200
        assert resp.json()["env_only"] is True


@pytest.mark.anyio
async def test_public_basemaps_endpoint(client: AsyncClient):
    """GET /settings/basemaps/ still works (public, no auth)."""
    resp = await client.get("/settings/basemaps/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "id" in data[0]


@pytest.mark.anyio
async def test_basemaps_api_key_interpolation(
    client: AsyncClient, admin_auth_header: dict
):
    """Basemaps with {api_key} have the placeholder resolved in public response."""
    # Save basemaps with an api_key entry
    basemaps_with_key = [
        {
            "id": "openfreemap-positron",
            "label": "OpenFreeMap Positron",
            "url": "https://tiles.openfreemap.org/styles/positron",
            "enabled": True,
            "is_preset": True,
        },
        {
            "id": "maptiler-streets",
            "label": "MapTiler Streets",
            "url": "https://api.maptiler.com/maps/streets-v2/style.json?key={api_key}",
            "enabled": True,
            "is_preset": False,
            "api_key": "test_key_123",
        },
    ]
    resp = await client.put(
        "/settings/",
        json={"settings": {"basemaps": basemaps_with_key}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    # Public endpoint should resolve the placeholder
    resp = await client.get("/settings/basemaps/")
    assert resp.status_code == 200
    data = resp.json()

    maptiler = next((b for b in data if b["id"] == "maptiler-streets"), None)
    assert maptiler is not None
    assert "test_key_123" in maptiler["url"]
    assert "{api_key}" not in maptiler["url"]
    assert "api_key" not in maptiler  # Key excluded from public response


@pytest.mark.anyio
async def test_basemaps_api_key_unresolved_filtered(
    client: AsyncClient, admin_auth_header: dict
):
    """Basemaps with {api_key} but no key configured are filtered from public response."""
    basemaps_no_key = [
        {
            "id": "openfreemap-positron",
            "label": "OpenFreeMap Positron",
            "url": "https://tiles.openfreemap.org/styles/positron",
            "enabled": True,
            "is_preset": True,
        },
        {
            "id": "maptiler-no-key",
            "label": "MapTiler No Key",
            "url": "https://api.maptiler.com/maps/streets-v2/style.json?key={api_key}",
            "enabled": True,
            "is_preset": False,
            # No api_key set
        },
    ]
    resp = await client.put(
        "/settings/",
        json={"settings": {"basemaps": basemaps_no_key}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    # Public endpoint should NOT include the unresolved basemap
    resp = await client.get("/settings/basemaps/")
    assert resp.status_code == 200
    data = resp.json()

    ids = [b["id"] for b in data]
    assert "maptiler-no-key" not in ids
    assert "openfreemap-positron" in ids


@pytest.mark.anyio
async def test_basemaps_api_key_never_leaked(
    client: AsyncClient, admin_auth_header: dict
):
    """api_key is never present in public basemaps response."""
    basemaps = [
        {
            "id": "custom-no-placeholder",
            "label": "Custom Basemap",
            "url": "https://tiles.example.com/{z}/{x}/{y}.png",
            "enabled": True,
            "is_preset": False,
            "api_key": "should_not_appear",
        },
    ]
    resp = await client.put(
        "/settings/",
        json={"settings": {"basemaps": basemaps}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get("/settings/basemaps/")
    assert resp.status_code == 200
    data = resp.json()

    for entry in data:
        assert "api_key" not in entry, f"api_key leaked for {entry['id']}"


@pytest.mark.anyio
async def test_public_map_defaults_endpoint(client: AsyncClient):
    """GET /settings/map-defaults/ still works (public, no auth)."""
    resp = await client.get("/settings/map-defaults/")
    assert resp.status_code == 200
    data = resp.json()
    assert "center_lat" in data
    assert "center_lng" in data
    assert "zoom" in data


# ---------------------------------------------------------------------------
# Enabled plugins endpoint + validator tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_enabled_plugins_endpoint_returns_list(client: AsyncClient):
    """GET /settings/enabled-plugins/ returns a list or null (public, no auth)."""
    resp = await client.get("/settings/enabled-plugins/")
    assert resp.status_code == 200
    data = resp.json()
    assert data is None or isinstance(data, list)


@pytest.mark.anyio
async def test_enabled_plugins_roundtrip(client: AsyncClient, admin_auth_header: dict):
    """PUT /settings/ with enabled_plugins persists and GET returns the list."""
    plugin_ids = ["legend", "measurement"]
    resp = await client.put(
        "/settings/",
        json={"settings": {"enabled_plugins": plugin_ids}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get("/settings/enabled-plugins/")
    assert resp.status_code == 200
    assert resp.json() == plugin_ids


@pytest.mark.anyio
async def test_enabled_plugins_null_means_all(
    client: AsyncClient, admin_auth_header: dict
):
    """PUT /settings/ with enabled_plugins=null resets to 'all enabled'."""
    resp = await client.put(
        "/settings/",
        json={"settings": {"enabled_plugins": None}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get("/settings/enabled-plugins/")
    assert resp.status_code == 200
    assert resp.json() is None  # null = no restriction (all plugins enabled)


@pytest.mark.anyio
async def test_enabled_plugins_rejects_non_list(
    client: AsyncClient, admin_auth_header: dict
):
    """PUT /settings/ with enabled_plugins as a string returns 422."""
    resp = await client.put(
        "/settings/",
        json={"settings": {"enabled_plugins": "not-a-list"}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_enabled_plugins_rejects_empty_strings(
    client: AsyncClient, admin_auth_header: dict
):
    """PUT /settings/ with empty string in enabled_plugins returns 422."""
    resp = await client.put(
        "/settings/",
        json={"settings": {"enabled_plugins": ["valid", ""]}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_enabled_plugins_rejects_non_string_items(
    client: AsyncClient, admin_auth_header: dict
):
    """PUT /settings/ with non-string items in enabled_plugins returns 422."""
    resp = await client.put(
        "/settings/",
        json={"settings": {"enabled_plugins": [123, True]}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# CORS dynamic middleware tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cors_matching_origin_gets_headers(
    client: AsyncClient, admin_auth_header: dict
):
    """Request with matching origin gets CORS headers in response."""
    from app.api.middleware import cors as cors_middleware

    # Set CORS origins to allow http://example.com
    await client.put(
        "/settings/",
        json={"settings": {"cors_allowed_origins": "http://example.com"}},
        headers=admin_auth_header,
    )
    # Same guard, same reason, as test_cors_preflight_returns_200 below: any
    # request in the previous 30s left an allowlist in the module-global cache,
    # and the PUT above does not invalidate it, so this positive assertion would
    # be read against a neighbour's origins rather than the one just written.
    cors_middleware._origins_cache = (0.0, set())

    resp = await client.get("/health", headers={"Origin": "http://example.com"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://example.com"
    assert resp.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.anyio
async def test_cors_non_matching_origin_no_headers(
    client: AsyncClient, admin_auth_header: dict
):
    """Request with non-matching origin gets no CORS headers."""
    from app.api.middleware import cors as cors_middleware

    await client.put(
        "/settings/",
        json={"settings": {"cors_allowed_origins": "http://example.com"}},
        headers=admin_auth_header,
    )
    # Same guard as test_cors_preflight_returns_200 below, and here it is what
    # gives the assertion teeth rather than what keeps it passing: a stale-empty
    # cache denies every origin, so the deny path would look correct without the
    # written allowlist ever being consulted.
    cors_middleware._origins_cache = (0.0, set())

    resp = await client.get("/health", headers={"Origin": "http://evil.com"})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.anyio
async def test_cors_preflight_returns_200(client: AsyncClient, admin_auth_header: dict):
    """OPTIONS preflight with matching origin returns 200 with CORS headers."""
    from app.api.middleware import cors as cors_middleware

    await client.put(
        "/settings/",
        json={"settings": {"cors_allowed_origins": "http://example.com"}},
        headers=admin_auth_header,
    )
    # Same guard as test_cors_wildcard_from_env_is_rejected below, for the same
    # reason: the allowlist cache is a module global with a 30s TTL and no
    # write-through invalidation, so the origin this test just saved is invisible
    # while an earlier test's entry is still warm. Under `pytest -n 4` that made
    # this test 405 on a sibling's cache (#1470 CI run 1).
    cors_middleware._origins_cache = (0.0, set())

    resp = await client.options(
        "/health",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://example.com"
    assert "GET" in resp.headers.get("access-control-allow-methods", "")


@pytest.mark.anyio
async def test_cors_wildcard_rejected_at_settings_write(
    client: AsyncClient, admin_auth_header: dict
):
    """A wildcard is refused on save, naming the setting, so the admin sees why.

    Without this the middleware silently denies every origin (including valid
    ones listed alongside the '*') up to _ORIGINS_CACHE_TTL later.
    """
    resp = await client.put(
        "/settings/",
        json={
            "settings": {
                "cors_allowed_origins": "https://example.com, *",
            }
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 422
    assert "cors_allowed_origins" in resp.json()["detail"]


@pytest.mark.anyio
async def test_cors_wildcard_rejected_with_credentials(
    client: AsyncClient, test_db_session
):
    """Middleware still denies a wildcard reaching it via env, not the settings API.

    validate_cors_allowed_origins guards the settings write path only; the env
    var flows straight into PersistentConfig, so this guard stays load-bearing.
    PersistentConfig.set bypasses SETTING_VALIDATORS (those run in the settings
    router), which is exactly the env-supplied path this covers.
    """
    from app.api.middleware import cors as cors_middleware
    from app.core.persistent_config import CORS_ALLOWED_ORIGINS

    await CORS_ALLOWED_ORIGINS.set(test_db_session, "*")
    # The allowlist cache is a module global with a 30s TTL and no write-through
    # invalidation, so a stale entry from an earlier test would mask the result.
    cors_middleware._origins_cache = (0.0, set())

    resp = await client.get("/health", headers={"Origin": "http://anything.com"})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.anyio
async def test_cors_no_origin_header_no_processing(client: AsyncClient):
    """No origin header in request means no CORS processing."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


# ---------------------------------------------------------------------------
# Token lifetime PersistentConfig tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_token_lifetime_from_persistent_config(
    client: AsyncClient, admin_auth_header: dict
):
    """Changing ACCESS_TOKEN_EXPIRE_MINUTES via settings produces tokens with new expiry."""
    import jwt as pyjwt
    from app.core.config import settings as app_settings

    # Set custom token lifetime (2 minutes)
    await client.put(
        "/settings/",
        json={"settings": {"access_token_expire_minutes": 2}},
        headers=admin_auth_header,
    )

    # Login and get a token
    resp = await client.post(
        "/auth/login",
        data={
            "username": app_settings.geolens_admin_username,
            "password": app_settings.geolens_admin_password.get_secret_value(),
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["expires_in"] == 120  # 2 minutes * 60

    # Decode the token and verify expiry
    decoded = pyjwt.decode(
        data["access_token"],
        app_settings.jwt_secret_key.get_secret_value(),
        algorithms=[app_settings.jwt_algorithm],
    )
    # Token exp should be within ~2 minutes of iat
    assert (decoded["exp"] - decoded["iat"]) == 120


@pytest.mark.anyio
async def test_llm_provider_from_persistent_config(
    client: AsyncClient, admin_auth_header: dict
):
    """LLM_PROVIDER and LLM_MODEL are readable/writable via PersistentConfig."""
    from app.core.persistent_config import LLM_PROVIDER, LLM_MODEL
    from app.core.dependencies import get_db
    from app.api.main import app

    # Set provider and model
    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai", "llm_model": "gpt-4o"}},
        headers=admin_auth_header,
    )

    # Read back via PersistentConfig
    async for db in app.dependency_overrides[get_db]():
        provider = await LLM_PROVIDER.get(db)
        model = await LLM_MODEL.get(db)
        assert provider == "openai"
        assert model == "gpt-4o"


@pytest.mark.anyio
async def test_model_reads_skip_the_shared_cache(
    client: AsyncClient, admin_auth_header: dict
):
    """Older releases read and evict only config:llm_model, so model reads go to
    the database: a stale shared entry is ignored and none is written."""
    from app.api.main import app
    from app.core.dependencies import get_db
    from app.core.persistent_config import LLM_MODEL
    from app.platform.cache import get_cache, init_cache

    init_cache()
    cache = get_cache()
    await client.put(
        "/settings/",
        json={"settings": {"llm_model": "db-model"}},
        headers=admin_auth_header,
    )
    for key in ("config:llm_model", "config:llm_model:follows-provider"):
        await cache.set(key, "stale-model", ttl=60)
    async for db in app.dependency_overrides[get_db]():
        assert await LLM_MODEL.get(db) == "db-model"
    await cache.delete("config:llm_model")
    await cache.delete("config:llm_model:follows-provider")
    async for db in app.dependency_overrides[get_db]():
        await LLM_MODEL.get(db)
    assert await cache.get("config:llm_model") is None


@pytest.mark.anyio
async def test_model_update_evicts_the_plain_key_older_releases_cache(
    client: AsyncClient, admin_auth_header: dict
):
    from app.platform.cache import get_cache, init_cache

    init_cache()
    cache = get_cache()
    await cache.set("config:llm_model", "claude-old-model", ttl=60)
    await client.put(
        "/settings/",
        json={"settings": {"llm_model": "gpt-new-model"}},
        headers=admin_auth_header,
    )
    assert await cache.get("config:llm_model") is None


@pytest.fixture
def _both_ai_keys(monkeypatch):
    """Both provider keys set, with recognisable env model names."""
    from app.core.persistent_config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(settings, "openai_api_key", "sk-openai")
    monkeypatch.setattr(settings, "llm_model", "anthropic-chat-env")
    monkeypatch.setattr(settings, "openai_model", "openai-chat-env")
    monkeypatch.setattr(settings, "openai_model_light", "openai-light-env")


@pytest.mark.anyio
async def test_model_defaults_follow_the_selected_provider(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    """Switching the provider moves both model defaults to that provider at once."""
    from app.core.persistent_config import LLM_MODEL, LLM_MODEL_LIGHT
    from app.core.dependencies import get_db
    from app.api.main import app

    async def models() -> tuple[str, str]:
        async for db in app.dependency_overrides[get_db]():
            return await LLM_MODEL.get(db), await LLM_MODEL_LIGHT.get(db)
        raise AssertionError("no session")

    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "anthropic"}},
        headers=admin_auth_header,
    )
    assert await models() == ("anthropic-chat-env", "claude-haiku-4-5-20251001")

    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai_compatible"}},
        headers=admin_auth_header,
    )
    assert await models() == ("openai-chat-env", "openai-light-env")


@pytest.mark.anyio
async def test_a_switch_after_the_provider_read_keeps_that_providers_model(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    """A request that read the provider before a switch committed is not handed
    the new provider's model."""
    from app.api.main import app
    from app.core.dependencies import get_db
    from app.core.persistent_config import LLM_PROVIDER
    from app.processing.ai.llm_loop import resolve_provider

    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai_compatible"}},
        headers=admin_auth_header,
    )
    real_get = LLM_PROVIDER.get
    reads = iter(["anthropic"])

    async def first_read_before_the_switch(db):
        return next(reads, None) or await real_get(db)

    with patch.object(LLM_PROVIDER, "get", first_read_before_the_switch):
        async for db in app.dependency_overrides[get_db]():
            name, model, _ = await resolve_provider(db)
    assert (name, model) == ("anthropic", "anthropic-chat-env")


@pytest.mark.anyio
async def test_model_override_survives_a_provider_switch(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    from app.core.persistent_config import LLM_MODEL
    from app.core.dependencies import get_db
    from app.api.main import app

    await client.put(
        "/settings/",
        json={
            "settings": {
                "llm_provider": "openai_compatible",
                "llm_model": "my-deployment",
            }
        },
        headers=admin_auth_header,
    )
    async for db in app.dependency_overrides[get_db]():
        assert await LLM_MODEL.get(db) == "my-deployment"


@pytest.mark.anyio
async def test_settings_and_status_show_the_model_requests_use(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai_compatible"}},
        headers=admin_auth_header,
    )

    listing = await client.get("/settings/all/", headers=admin_auth_header)
    ai = {item["key"]: item for item in listing.json()["tabs"]["ai"]}
    assert ai["llm_model"]["value"] == "openai-chat-env"
    assert ai["llm_model"]["source"] == "default"
    assert ai["llm_model_light"]["value"] == "openai-light-env"

    status = await client.get("/admin/ai-status/", headers=admin_auth_header)
    assert status.json()["model"] == "openai-chat-env"


@pytest.mark.anyio
async def test_model_reset_and_import_state_use_the_provider_default(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    """The reset audit and config-import state show the model the key resolves to."""
    from sqlalchemy import select

    from app.api.main import app
    from app.core.config import settings as app_settings
    from app.core.dependencies import get_db
    from app.core.persistent_config import LLM_MODEL, _registry
    from app.modules.audit.models import AuditLog
    from app.modules.auth.models import User
    from app.platform.config_ops.service import _load_setting_state

    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai_compatible"}},
        headers=admin_auth_header,
    )
    async for db in app.dependency_overrides[get_db]():
        admin = (
            await db.execute(
                select(User).where(User.username == app_settings.geolens_admin_username)
            )
        ).scalar_one()
        await LLM_MODEL.set(db, "my-deployment", user_id=admin.id)
        await LLM_MODEL.reset(db, user_id=admin.id)

        entry = (
            (
                await db.execute(
                    select(AuditLog)
                    .where(AuditLog.resource_type == "setting")
                    .where(AuditLog.action == "reset")
                    .order_by(AuditLog.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        assert entry.details["setting_key"] == "llm_model"
        assert entry.details["new_value"] == "openai-chat-env"

        current, overridden, _ = await _load_setting_state(db, _registry)
        assert "llm_model" not in overridden
        assert current["llm_model"] == "openai-chat-env"
        assert current["llm_model_light"] == "openai-light-env"


@pytest.mark.anyio
async def test_overwrite_preview_resolves_models_against_the_imported_provider(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    """Omitted model settings preview the provider the overwrite leaves in place."""
    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "anthropic"}},
        headers=admin_auth_header,
    )
    switched = await client.post(
        "/config-ops/dry-run/?mode=overwrite",
        json={"settings": {"llm_provider": "openai_compatible"}},
        headers=admin_auth_header,
    )
    assert switched.status_code == 200, switched.text
    changes = {c["key"]: c for c in switched.json()["settings"]["changes"]}
    assert changes["llm_model"]["current"] == "anthropic-chat-env"
    assert changes["llm_model"]["imported"] == "openai-chat-env"
    assert changes["llm_model_light"]["imported"] == "openai-light-env"

    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai_compatible"}},
        headers=admin_auth_header,
    )
    provider_reset = await client.post(
        "/config-ops/dry-run/?mode=overwrite",
        json={"settings": {"log_level": "INFO"}},
        headers=admin_auth_header,
    )
    assert provider_reset.status_code == 200, provider_reset.text
    changes = {c["key"]: c for c in provider_reset.json()["settings"]["changes"]}
    assert changes["llm_model"]["current"] == "openai-chat-env"
    assert changes["llm_model"]["imported"] == "anthropic-chat-env"


async def _latest_model_audit(action: str) -> dict:
    from sqlalchemy import select

    from app.api.main import app
    from app.core.dependencies import get_db
    from app.modules.audit.models import AuditLog

    async for db in app.dependency_overrides[get_db]():
        entries = (
            (
                await db.execute(
                    select(AuditLog)
                    .where(AuditLog.resource_type == "setting")
                    .where(AuditLog.action == action)
                    .order_by(AuditLog.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return next(
            e.details for e in entries if e.details["setting_key"] == "llm_model"
        )
    raise AssertionError("no session")


async def _latest_model_reset_value() -> str:
    return (await _latest_model_audit("reset"))["new_value"]


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/settings/", "/config-ops/import/?mode=merge"])
async def test_a_batch_audits_the_model_in_effect_before_it(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys, path
):
    """Switching the provider and setting a model in one batch records the
    previous provider's model as the old value."""
    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "anthropic"}},
        headers=admin_auth_header,
    )
    payload = {"settings": {"llm_provider": "openai_compatible", "llm_model": "m"}}
    if path == "/settings/":
        resp = await client.put(path, json=payload, headers=admin_auth_header)
    else:
        resp = await client.post(path, json=payload, headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    audit = await _latest_model_audit("update")
    assert (audit["old_value"], audit["new_value"]) == ("anthropic-chat-env", "m")


@pytest.mark.anyio
async def test_batch_reset_audits_the_model_under_the_reset_provider(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    """Resetting the model with the provider records the model that results."""
    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai_compatible", "llm_model": "x"}},
        headers=admin_auth_header,
    )
    # Warm the cache with the overridden provider first.
    await client.get("/settings/all/", headers=admin_auth_header)
    reset = await client.post(
        "/settings/reset/",
        json={"keys": ["llm_model", "llm_provider"]},
        headers=admin_auth_header,
    )
    assert reset.status_code == 200, reset.text
    assert await _latest_model_reset_value() == "anthropic-chat-env"


@pytest.mark.anyio
async def test_overwrite_import_audits_the_model_under_the_imported_provider(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "anthropic", "llm_model": "x"}},
        headers=admin_auth_header,
    )
    payload = {"settings": {"llm_provider": "openai_compatible"}}
    preview = await client.post(
        "/config-ops/dry-run/?mode=overwrite", json=payload, headers=admin_auth_header
    )
    applied = await client.post(
        "/config-ops/import/?mode=overwrite",
        json=payload,
        headers={
            **admin_auth_header,
            "X-Config-Preview-Token": preview.json()["preview_token"],
        },
    )
    assert applied.status_code == 200, applied.text
    assert await _latest_model_reset_value() == "openai-chat-env"


@pytest.mark.anyio
async def test_overwrite_blank_model_resets_after_the_omitted_provider(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    """A blank model in an overwrite resolves against the provider's reset value."""
    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai_compatible", "llm_model": "x"}},
        headers=admin_auth_header,
    )
    payload = {"settings": {"llm_model": ""}}
    preview = await client.post(
        "/config-ops/dry-run/?mode=overwrite", json=payload, headers=admin_auth_header
    )
    applied = await client.post(
        "/config-ops/import/?mode=overwrite",
        json=payload,
        headers={
            **admin_auth_header,
            "X-Config-Preview-Token": preview.json()["preview_token"],
        },
    )
    assert applied.status_code == 200, applied.text
    assert await _latest_model_reset_value() == "anthropic-chat-env"


@pytest.mark.anyio
async def test_empty_model_is_stored_as_no_override(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai_compatible", "llm_model": "x"}},
        headers=admin_auth_header,
    )
    await client.put(
        "/settings/",
        json={"settings": {"llm_model": ""}},
        headers=admin_auth_header,
    )
    listing = await client.get("/settings/all/", headers=admin_auth_header)
    ai = {item["key"]: item for item in listing.json()["tabs"]["ai"]}
    assert ai["llm_model"]["source"] == "default"
    assert ai["llm_model"]["value"] == "openai-chat-env"


@pytest.mark.anyio
async def test_blank_model_in_a_put_resets_against_the_new_provider(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "anthropic", "llm_model": "x"}},
        headers=admin_auth_header,
    )
    await client.get("/settings/all/", headers=admin_auth_header)
    await client.put(
        "/settings/",
        json={"settings": {"llm_model": "", "llm_provider": "openai_compatible"}},
        headers=admin_auth_header,
    )
    assert await _latest_model_reset_value() == "openai-chat-env"


@pytest.mark.anyio
async def test_blank_model_import_plans_and_applies_a_reset(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    """A blank imported model previews and applies as a reset to the new default."""
    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "anthropic", "llm_model": "x"}},
        headers=admin_auth_header,
    )
    payload = {"settings": {"llm_model": "", "llm_provider": "openai_compatible"}}
    preview = await client.post(
        "/config-ops/dry-run/?mode=merge", json=payload, headers=admin_auth_header
    )
    changes = {c["key"]: c for c in preview.json()["settings"]["changes"]}
    assert changes["llm_model"]["action"] == "reset"
    assert changes["llm_model"]["imported"] == "openai-chat-env"

    applied = await client.post(
        "/config-ops/import/?mode=merge", json=payload, headers=admin_auth_header
    )
    assert applied.status_code == 200, applied.text
    assert await _latest_model_reset_value() == "openai-chat-env"
    listing = await client.get("/settings/all/", headers=admin_auth_header)
    ai = {item["key"]: item for item in listing.json()["tabs"]["ai"]}
    assert ai["llm_model"]["source"] == "default"


@pytest.mark.anyio
async def test_import_preview_resolves_a_blank_model_against_the_imported_endpoint(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys, monkeypatch
):
    """One import that repairs the endpoint and blanks the model previews the
    overlay's own default, not the community fallback a stale endpoint yields."""
    from app.api.main import app
    from app.core.ai_credentials import bind_openai_credential_base_url
    from app.core.db.models import AppSetting
    from app.core.dependencies import get_db
    from app.core.persistent_config import OPENAI_BASE_URL, settings

    approved = "https://llm.example.com/v1"
    monkeypatch.setattr(settings, "openai_base_url", approved)

    class _Overlay:
        async def resolve_runtime_config(self, db, settings=None):
            configured = (
                settings[OPENAI_BASE_URL.key]
                if settings and OPENAI_BASE_URL.key in settings
                else await OPENAI_BASE_URL.get(db)
            )
            base_url = bind_openai_credential_base_url(configured, purpose="chat")
            return {"base_url": base_url, "default_model": "overlay-deployment"}

    async for db in app.dependency_overrides[get_db]():
        db.add(
            AppSetting(key="openai_base_url", value={"v": "https://stale.example/v1"})
        )
        await db.commit()

    payload = {
        "settings": {
            "llm_provider": "overlay",
            "llm_model": "",
            "openai_base_url": approved,
        }
    }
    with patch("app.platform.extensions.get_ai_provider", return_value=_Overlay()):
        preview = await client.post(
            "/config-ops/dry-run/?mode=merge", json=payload, headers=admin_auth_header
        )
    assert preview.status_code == 200, preview.text
    changes = {c["key"]: c for c in preview.json()["settings"]["changes"]}
    assert changes["llm_model"]["imported"] == "overlay-deployment"


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/settings/", "/config-ops/import/?mode=merge"])
async def test_a_reset_audits_the_model_resolved_against_the_batch_endpoint(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys, monkeypatch, path
):
    """A batch that repairs the endpoint and clears the model override audits
    the overlay's default, not the one the stale committed endpoint yields."""
    from app.api.main import app
    from app.core.ai_credentials import bind_openai_credential_base_url
    from app.core.db.models import AppSetting
    from app.core.dependencies import get_db
    from app.core.persistent_config import OPENAI_BASE_URL, settings

    approved = "https://llm.example.com/v1"
    monkeypatch.setattr(settings, "openai_base_url", approved)

    class _Overlay:
        async def resolve_runtime_config(self, db, settings=None):
            configured = (
                settings[OPENAI_BASE_URL.key]
                if settings and OPENAI_BASE_URL.key in settings
                else await OPENAI_BASE_URL.get(db)
            )
            base_url = bind_openai_credential_base_url(configured, purpose="chat")
            return {"base_url": base_url, "default_model": "overlay-deployment"}

    async for db in app.dependency_overrides[get_db]():
        db.add(
            AppSetting(key="openai_base_url", value={"v": "https://stale.example/v1"})
        )
        db.add(AppSetting(key="llm_model", value={"v": "pinned"}))
        await db.commit()

    payload = {
        "settings": {
            "llm_provider": "overlay",
            "llm_model": "",
            "openai_base_url": approved,
        }
    }
    with patch("app.platform.extensions.get_ai_provider", return_value=_Overlay()):
        if path == "/settings/":
            resp = await client.put(path, json=payload, headers=admin_auth_header)
        else:
            resp = await client.post(path, json=payload, headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    assert await _latest_model_reset_value() == "overlay-deployment"


@pytest.mark.anyio
@pytest.mark.parametrize("change", [{"log_level": "DEBUG"}, {"openai_base_url": ""}])
async def test_a_put_that_clears_no_model_persists_when_the_provider_cannot_load(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys, change
):
    """A provider whose committed config can't load must not stop a PUT that
    touches neither model setting, such as one repairing the endpoint, from
    persisting. Rendering the response may still hit the broken provider."""
    from sqlalchemy import select

    from app.api.main import app
    from app.core.db.models import AppSetting
    from app.core.dependencies import get_db

    class _Broken:
        async def resolve_runtime_config(self, db, settings=None):
            raise RuntimeError("committed config can't load")

    (key,) = change
    async for db in app.dependency_overrides[get_db]():
        db.add(AppSetting(key="llm_provider", value={"v": "overlay"}))
        await db.commit()

    with patch("app.platform.extensions.get_ai_provider", return_value=_Broken()):
        with pytest.raises(RuntimeError):
            await client.put(
                "/settings/", json={"settings": change}, headers=admin_auth_header
            )

    async for db in app.dependency_overrides[get_db]():
        stored = await db.scalar(select(AppSetting.value).where(AppSetting.key == key))
        assert stored == {"v": change[key]}


@pytest.mark.anyio
async def test_import_preview_works_for_an_overlay_that_ignores_settings(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    """A provider whose resolver predates the ``settings`` parameter still
    previews, resolving against committed configuration."""

    class _Legacy:
        async def resolve_runtime_config(self, db):
            return {"base_url": None, "default_model": "legacy-deployment"}

    payload = {"settings": {"llm_provider": "overlay", "llm_model": ""}}
    with patch("app.platform.extensions.get_ai_provider", return_value=_Legacy()):
        preview = await client.post(
            "/config-ops/dry-run/?mode=merge", json=payload, headers=admin_auth_header
        )
    assert preview.status_code == 200, preview.text
    changes = {c["key"]: c for c in preview.json()["settings"]["changes"]}
    assert changes["llm_model"]["imported"] == "legacy-deployment"


@pytest.mark.anyio
async def test_an_overlay_under_a_built_in_name_chats_with_the_reported_model(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    """Chat, the settings default and SQL agree on the overlay's default model
    for a replaced built-in provider."""
    from app.api.main import app
    from app.core.dependencies import get_db
    from app.core.persistent_config import LLM_MODEL, LLM_PROVIDER
    from app.processing.ai.llm_loop import resolve_provider

    class _Overlay:
        async def resolve_runtime_config(self, _db):
            return {"base_url": None, "default_model": "overlay-deployment"}

    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "anthropic"}},
        headers=admin_auth_header,
    )
    with patch("app.platform.extensions.get_ai_provider", return_value=_Overlay()):
        async for db in app.dependency_overrides[get_db]():
            _, chat_model, _ = await resolve_provider(db)
            assert chat_model == await LLM_MODEL.resolved_default(db)
            assert chat_model == await LLM_MODEL.for_provider(
                db, await LLM_PROVIDER.get(db)
            )
            assert chat_model == "overlay-deployment"


@pytest.mark.anyio
async def test_a_reset_audits_the_model_in_effect_before_it(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    """Resetting the provider with a legacy blank model row records the model
    the old provider resolved as the old value."""
    from app.api.main import app
    from app.core.db.models import AppSetting
    from app.core.dependencies import get_db

    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai_compatible"}},
        headers=admin_auth_header,
    )
    async for db in app.dependency_overrides[get_db]():
        db.add(AppSetting(key="llm_model", value={"v": ""}))
        await db.commit()
    reset = await client.post(
        "/settings/reset/",
        json={"keys": ["llm_model", "llm_provider"]},
        headers=admin_auth_header,
    )
    assert reset.status_code == 200, reset.text
    audit = await _latest_model_audit("reset")
    assert (audit["old_value"], audit["new_value"]) == (
        "openai-chat-env",
        "anthropic-chat-env",
    )


@pytest.mark.anyio
async def test_a_legacy_blank_model_row_reads_as_the_provider_default(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    from app.api.main import app
    from app.core.db.models import AppSetting
    from app.core.dependencies import get_db
    from app.core.persistent_config import LLM_MODEL_LIGHT, _registry
    from app.platform.config_ops.service import _load_setting_state

    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai_compatible"}},
        headers=admin_auth_header,
    )
    async for db in app.dependency_overrides[get_db]():
        db.add(AppSetting(key="llm_model", value={"v": ""}))
        db.add(AppSetting(key="llm_model_light", value={"v": "   "}))
        await db.commit()
        assert await LLM_MODEL_LIGHT.get(db) == "openai-light-env"
        assert await LLM_MODEL_LIGHT.get_uncached(db) == "openai-light-env"
        current, overridden, _ = await _load_setting_state(db, _registry)
        assert "llm_model" not in overridden
        assert "llm_model_light" not in overridden
        assert current["llm_model"] == "openai-chat-env"

    listing = await client.get("/settings/all/", headers=admin_auth_header)
    ai = {item["key"]: item for item in listing.json()["tabs"]["ai"]}
    assert ai["llm_model"]["source"] == "default"
    assert ai["llm_model"]["value"] == "openai-chat-env"
    assert ai["llm_model_light"]["value"] == "openai-light-env"


# ---------------------------------------------------------------------------
# Log level propagation tests (CFG-06)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_log_level_propagation_via_api(
    client: AsyncClient, admin_auth_header: dict
):
    """Setting log_level via PUT /settings/ propagates immediately to root logger."""
    import logging

    original_level = logging.getLogger().level
    try:
        # Set to DEBUG
        resp = await client.put(
            "/settings/",
            json={"settings": {"log_level": "DEBUG"}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert logging.getLogger().level == logging.DEBUG

        # Set to WARNING
        resp = await client.put(
            "/settings/",
            json={"settings": {"log_level": "WARNING"}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert logging.getLogger().level == logging.WARNING

        # Reset to INFO
        await client.put(
            "/settings/",
            json={"settings": {"log_level": "INFO"}},
            headers=admin_auth_header,
        )
        assert logging.getLogger().level == logging.INFO
    finally:
        logging.getLogger().setLevel(original_level)


# ---------------------------------------------------------------------------
# Tile cache TTL tests (CFG-07)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_tile_cache_ttl_round_trip(client: AsyncClient, admin_auth_header: dict):
    """Setting tile_cache_ttl via PUT /settings/ and reading back via GET /settings/all/."""
    # Set TTL to 600
    resp = await client.put(
        "/settings/",
        json={"settings": {"tile_cache_ttl": 600}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    # Read back via GET /settings/all/
    resp = await client.get("/settings/all/", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()

    # Find tile_cache_ttl in storage tab
    storage_items = data["tabs"]["storage"]
    ttl_setting = next(s for s in storage_items if s["key"] == "tile_cache_ttl")
    assert ttl_setting["value"] == 600
    assert ttl_setting["source"] == "overridden"


@pytest.mark.anyio
async def test_tile_cache_ttl_available_via_persistent_config(
    client: AsyncClient, admin_auth_header: dict
):
    """TILE_CACHE_TTL PersistentConfig instance returns the configured value."""
    from app.core.persistent_config import TILE_CACHE_TTL
    from app.core.dependencies import get_db
    from app.api.main import app

    await client.put(
        "/settings/",
        json={"settings": {"tile_cache_ttl": 900}},
        headers=admin_auth_header,
    )

    async for db in app.dependency_overrides[get_db]():
        ttl = await TILE_CACHE_TTL.get(db)
        assert ttl == 900


# ---------------------------------------------------------------------------
# Audit trail completeness tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_bulk_settings_update_creates_per_field_audit_entries(
    client: AsyncClient, admin_auth_header: dict
):
    """Changing 3 settings in one PUT /settings/ creates 3 separate audit log entries."""
    from sqlalchemy import select, func
    from app.modules.audit.models import AuditLog
    from app.core.dependencies import get_db
    from app.api.main import app

    # Count existing audit entries for settings
    async for db in app.dependency_overrides[get_db]():
        result = await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.resource_type == "setting")
        )
        before_count = result.scalar()

    # Bulk update 3 settings at once
    resp = await client.put(
        "/settings/",
        json={
            "settings": {
                "registration_enabled": True,
                "log_level": "DEBUG",
                "tile_cache_ttl": 999,
            }
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    # Verify 3 new audit entries were created
    async for db in app.dependency_overrides[get_db]():
        result = await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.resource_type == "setting")
        )
        after_count = result.scalar()

    assert after_count - before_count == 3, (
        f"Expected 3 new audit entries, got {after_count - before_count}"
    )

    # Reset
    await client.put(
        "/settings/",
        json={
            "settings": {
                "registration_enabled": False,
                "log_level": "INFO",
            }
        },
        headers=admin_auth_header,
    )


# ---------------------------------------------------------------------------
# Phase 222: TypeAdapter runtime validation at JSONB unwrap boundary (D-06)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_validates_unwrapped_value_against_type_adapter(
    client: AsyncClient,
):
    """get() runs unwrapped value through TypeAdapter and returns the validated value.

    Happy path: an int-typed config with an int-stored row returns the int.
    """
    from app.core.dependencies import get_db
    from app.api.main import app
    from app.core.persistent_config import LOGIN_RATE_LIMIT

    async for db in app.dependency_overrides[get_db]():
        # Write a valid int via set() — goes through the JSONB wrap
        await LOGIN_RATE_LIMIT.set(db, 42)
        value = await LOGIN_RATE_LIMIT.get(db)
        assert value == 42
        assert isinstance(value, int)


@pytest.mark.anyio
async def test_get_falls_back_to_env_default_on_validation_error(
    client: AsyncClient,
):
    """get() logs a warning and falls back to env_default when DB row fails validation."""
    from sqlalchemy import delete

    from app.platform.cache import get_cache
    from app.core.dependencies import get_db
    from app.api.main import app
    from app.core.persistent_config import LOGIN_RATE_LIMIT
    from app.core.db.models import AppSetting

    async for db in app.dependency_overrides[get_db]():
        # Inject a corrupt row: LOGIN_RATE_LIMIT expects int, but we write a
        # string that LAX mode cannot coerce.
        await db.execute(delete(AppSetting).where(AppSetting.key == "login_rate_limit"))
        db.add(AppSetting(key="login_rate_limit", value={"v": "not_an_int"}))
        await db.commit()

        # Invalidate cache so the next get() hits the DB
        cache = get_cache()
        await cache.delete("config:login_rate_limit")

        with patch("app.core.persistent_config.logger") as mock_logger:
            value = await LOGIN_RATE_LIMIT.get(db)

        # Returned the env_default, not the corrupt value
        assert value == LOGIN_RATE_LIMIT.env_default

        # Warning was logged with the expected structured payload
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        # First positional arg is the event name
        assert call_args.args[0] == "persistent_config.validation_failed"
        # kwargs include key and errors
        assert call_args.kwargs["key"] == "login_rate_limit"
        assert "errors" in call_args.kwargs
        assert call_args.kwargs["action"] == "fell_back_to_env_default"


@pytest.mark.anyio
async def test_get_does_not_cache_fallback_value(client: AsyncClient):
    """When validation fails and get() falls back to env_default, the cache is NOT written.

    This ensures the next read re-hits the DB and re-logs, rather than masking
    the corruption with a cached fallback.
    """
    from sqlalchemy import delete

    from app.platform.cache import get_cache
    from app.core.dependencies import get_db
    from app.api.main import app
    from app.core.persistent_config import LOGIN_RATE_LIMIT
    from app.core.db.models import AppSetting

    async for db in app.dependency_overrides[get_db]():
        # Inject corrupt row
        await db.execute(delete(AppSetting).where(AppSetting.key == "login_rate_limit"))
        db.add(AppSetting(key="login_rate_limit", value={"v": "still_not_an_int"}))
        await db.commit()

        # Ensure cache is clean
        cache = get_cache()
        await cache.delete("config:login_rate_limit")

        # Read — should fall back, NOT write to cache
        await LOGIN_RATE_LIMIT.get(db)

        # Assert cache was not populated with the fallback value
        cached = await cache.get("config:login_rate_limit")
        assert cached is None, (
            "Cache should NOT be written on validation fallback — the next "
            "read must re-hit DB and re-log"
        )


@pytest.mark.anyio
async def test_log_level_config_subclass_validates_str(client: AsyncClient):
    """_LogLevelConfig (subclass) validates values via the same TypeAdapter path.

    Confirms that the subclass correctly passes type_=str to super().__init__
    and participates in the same validate-or-fallback behavior.
    """
    from sqlalchemy import delete

    from app.platform.cache import get_cache
    from app.core.dependencies import get_db
    from app.api.main import app
    from app.core.persistent_config import LOG_LEVEL
    from app.core.db.models import AppSetting

    async for db in app.dependency_overrides[get_db]():
        # Inject a row with a non-string value — dict is LAX-rejected for str
        await db.execute(delete(AppSetting).where(AppSetting.key == "log_level"))
        db.add(AppSetting(key="log_level", value={"v": {"not": "a_string"}}))
        await db.commit()

        cache = get_cache()
        await cache.delete("config:log_level")

        with patch("app.core.persistent_config.logger") as mock_logger:
            value = await LOG_LEVEL.get(db)

        # Returned the env_default (a string like "INFO" or "DEBUG")
        assert isinstance(value, str)
        # Warning was logged for the subclass instance
        mock_logger.warning.assert_called_once()
        assert mock_logger.warning.call_args.kwargs["key"] == "log_level"


@pytest.mark.anyio
async def test_the_settings_list_resolves_models_against_its_own_provider_read(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    """A provider switch committed after the list's bulk read can't pair the
    listed provider with the other provider's model."""
    from app.core.persistent_config import LLM_PROVIDER

    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai_compatible"}},
        headers=admin_auth_header,
    )
    with patch.object(LLM_PROVIDER, "get", return_value="anthropic"):
        listing = await client.get("/settings/all/", headers=admin_auth_header)
    ai = {item["key"]: item["value"] for item in listing.json()["tabs"]["ai"]}
    assert (ai["llm_provider"], ai["llm_model"]) == (
        "openai_compatible",
        "openai-chat-env",
    )


@pytest.mark.anyio
async def test_import_state_resolves_models_against_its_own_provider_read(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    from app.api.main import app
    from app.core.dependencies import get_db
    from app.core.persistent_config import LLM_PROVIDER, _registry
    from app.platform.config_ops.service import _load_setting_state

    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai_compatible"}},
        headers=admin_auth_header,
    )
    with patch.object(LLM_PROVIDER, "get", return_value="anthropic"):
        async for db in app.dependency_overrides[get_db]():
            current, _, _ = await _load_setting_state(db, _registry)
    assert (current["llm_provider"], current["llm_model"]) == (
        "openai_compatible",
        "openai-chat-env",
    )


@pytest.mark.anyio
async def test_import_state_resolves_a_malformed_model_row_to_the_default(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    from app.api.main import app
    from app.core.db.models import AppSetting
    from app.core.dependencies import get_db
    from app.core.persistent_config import _registry
    from app.platform.config_ops.service import _load_setting_state

    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai_compatible"}},
        headers=admin_auth_header,
    )
    async for db in app.dependency_overrides[get_db]():
        db.add(AppSetting(key="llm_model", value={"v": 123}))
        await db.commit()
        current, overridden, valid = await _load_setting_state(db, _registry)
    assert current["llm_model"] == "openai-chat-env"
    assert "llm_model" in overridden and "llm_model" not in valid


@pytest.mark.anyio
async def test_an_export_pairs_models_with_the_exported_provider(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    from app.api.main import app
    from app.core.dependencies import get_db
    from app.core.persistent_config import LLM_PROVIDER
    from app.platform.config_ops.service import export_config

    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai_compatible"}},
        headers=admin_auth_header,
    )
    reads = iter(["openai_compatible"])

    async def switch_after_the_first_read(db):
        return next(reads, None) or "anthropic"

    with patch.object(LLM_PROVIDER, "get", switch_after_the_first_read):
        async for db in app.dependency_overrides[get_db]():
            exported = (await export_config(db))["settings"]
    assert (exported["llm_provider"], exported["llm_model"]) == (
        "openai_compatible",
        "openai-chat-env",
    )


@pytest.mark.anyio
async def test_get_all_registry_values_resolves_unset_models(
    client: AsyncClient, admin_auth_header: dict, _both_ai_keys
):
    from app.api.main import app
    from app.core.dependencies import get_db
    from app.core.persistent_config import get_all_registry_values

    await client.put(
        "/settings/",
        json={"settings": {"llm_provider": "openai_compatible"}},
        headers=admin_auth_header,
    )
    async for db in app.dependency_overrides[get_db]():
        values = await get_all_registry_values(db)
        assert (values["llm_model"], values["llm_model_light"]) == (
            "openai-chat-env",
            "openai-light-env",
        )


@pytest.mark.anyio
async def test_get_all_registry_values_applies_validation(client: AsyncClient):
    """get_all_registry_values() validates each row through the registered TypeAdapter.

    Happy path: all DB-stored values are valid and batch-returned unchanged.
    """
    from app.core.dependencies import get_db
    from app.api.main import app
    from app.core.persistent_config import (
        AI_ENABLED,
        LOGIN_RATE_LIMIT,
        get_all_registry_values,
    )

    async for db in app.dependency_overrides[get_db]():
        # Write known-good values via set()
        await LOGIN_RATE_LIMIT.set(db, 20)
        await AI_ENABLED.set(db, False)

        all_values = await get_all_registry_values(db)
        assert all_values["login_rate_limit"] == 20
        assert all_values["ai_enabled"] is False


@pytest.mark.anyio
async def test_get_all_registry_values_falls_back_on_bad_row(client: AsyncClient):
    """get_all_registry_values() falls back to env_default for a single corrupt row
    while returning normal values for other registered keys."""
    from sqlalchemy import delete

    from app.core.dependencies import get_db
    from app.api.main import app
    from app.core.persistent_config import (
        AI_ENABLED,
        LOGIN_RATE_LIMIT,
        get_all_registry_values,
    )
    from app.core.db.models import AppSetting

    async for db in app.dependency_overrides[get_db]():
        # Good row for ai_enabled
        await AI_ENABLED.set(db, True)

        # Corrupt row for login_rate_limit
        await db.execute(delete(AppSetting).where(AppSetting.key == "login_rate_limit"))
        db.add(AppSetting(key="login_rate_limit", value={"v": "not_an_int"}))
        await db.commit()

        with patch("app.core.persistent_config.logger") as mock_logger:
            all_values = await get_all_registry_values(db)

        # Corrupt key returned env_default
        assert all_values["login_rate_limit"] == LOGIN_RATE_LIMIT.env_default
        # Good key returned DB value
        assert all_values["ai_enabled"] is True
        # Warning was logged for the corrupt key
        mock_logger.warning.assert_called()
        # Check that at least one warning call included login_rate_limit
        keys_logged = [
            call.kwargs.get("key") for call in mock_logger.warning.call_args_list
        ]
        assert "login_rate_limit" in keys_logged


@pytest.mark.anyio
@pytest.mark.parametrize(
    "type_,good_value,bad_value",
    [
        (bool, True, "not_a_bool"),  # CORRECTED from D-06: "yes" coerces in LAX
        (str, "hi", 42),
        (int, 5, "five"),
        (list, [1, 2], {"k": "v"}),
        (dict, {"a": 1}, [1, 2]),
    ],
    ids=["bool", "str", "int", "list", "dict"],
)
async def test_validation_across_all_registered_types(
    client: AsyncClient,
    type_: type,
    good_value,
    bad_value,
):
    """Parameterized smoke test: TypeAdapter accepts good values and rejects bad ones
    for every type variant present in the registry (bool, str, int, list, dict).

    This is a pure-Python test of the TypeAdapter wrapper — it doesn't hit the DB
    or the PersistentConfig get() pathway. For DB-integrated coverage see the
    per-type tests above.
    """
    from pydantic import TypeAdapter, ValidationError

    adapter = TypeAdapter(type_)

    # Happy path: good value validates to itself (or a coerced equivalent)
    validated = adapter.validate_python(good_value)
    assert validated == good_value

    # Bad value raises
    with pytest.raises(ValidationError):
        adapter.validate_python(bad_value)


class _UrlOverlay:
    """An overlay whose default model names the endpoint it resolved against.

    With ``release`` set, the first resolution waits on it, holding the batch
    open between reading its snapshot and committing.
    """

    def __init__(self, release: asyncio.Event | None = None) -> None:
        self.entered = asyncio.Event()
        self.release = release

    async def resolve_runtime_config(self, db, settings=None):
        from app.core.persistent_config import OPENAI_BASE_URL

        configured = (
            settings[OPENAI_BASE_URL.key]
            if settings and OPENAI_BASE_URL.key in settings
            else await OPENAI_BASE_URL.get(db)
        )
        if self.release is not None and not self.release.is_set():
            self.entered.set()
            await self.release.wait()
        return {"default_model": f"model-for-{configured}"}


async def _seed_overlay_with_a_pinned_model(session) -> None:
    from app.core.db.models import AppSetting

    session.add(AppSetting(key="llm_provider", value={"v": "overlay"}))
    session.add(AppSetting(key="llm_model", value={"v": "pinned"}))
    await session.commit()


async def _clear_the_model(client: AsyncClient, headers: dict, path: str):
    if path == "/settings/":
        return await client.put(
            path, json={"settings": {"llm_model": ""}}, headers=headers
        )
    return await client.post(path, json={"keys": ["llm_model"]}, headers=headers)


async def _waits_on_session(session, task) -> bool:
    """Whether ``task`` blocks on a lock ``session`` holds before it finishes."""
    from sqlalchemy import text

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if task.done():
            return False
        # The activity view is snapshotted once per transaction.
        await session.execute(text("SELECT pg_stat_clear_snapshot()"))
        blocked = await session.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE pg_backend_pid() = ANY(pg_blocking_pids(pid))"
            )
        )
        if blocked:
            return True
        await asyncio.sleep(0.05)
    pytest.fail("the model reset neither finished nor waited")


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/settings/", "/settings/reset/"])
async def test_a_model_reset_waits_for_a_concurrent_endpoint_write(
    client: AsyncClient, admin_auth_header: dict, test_db_session, path
):
    """A model reset that starts while another transaction writes the endpoint
    resolves the audited default against the endpoint that transaction commits.
    The endpoint has no row before the write, so only a lock that covers inserts
    serializes the two."""
    from app.core.db.models import AppSetting

    new_url = "https://new.example/v1"
    await _seed_overlay_with_a_pinned_model(test_db_session)
    test_db_session.add(AppSetting(key="openai_base_url", value={"v": new_url}))
    await test_db_session.flush()

    with patch("app.platform.extensions.get_ai_provider", return_value=_UrlOverlay()):
        reset = asyncio.create_task(_clear_the_model(client, admin_auth_header, path))
        try:
            waited = await _waits_on_session(test_db_session, reset)
        finally:
            await test_db_session.commit()
        resp = await reset

    assert resp.status_code == 200, resp.text
    assert await _latest_model_reset_value() == f"model-for-{new_url}"
    assert waited


@pytest.mark.anyio
async def test_an_endpoint_write_waits_for_a_model_reset_in_progress(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """An endpoint write that starts while a model reset is between reading the
    provider configuration and committing waits for the reset to finish."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.core.db.models import AppSetting

    await _seed_overlay_with_a_pinned_model(test_db_session)
    release = asyncio.Event()
    overlay = _UrlOverlay(release)

    with patch("app.platform.extensions.get_ai_provider", return_value=overlay):
        reset = asyncio.create_task(
            _clear_the_model(client, admin_auth_header, "/settings/reset/")
        )
        try:
            await asyncio.wait_for(overlay.entered.wait(), timeout=30)
            await test_db_session.execute(text("SET LOCAL lock_timeout = '1s'"))
            test_db_session.add(
                AppSetting(key="openai_base_url", value={"v": "https://new.example/v1"})
            )
            with pytest.raises(DBAPIError, match="lock timeout"):
                await test_db_session.flush()
        finally:
            await test_db_session.rollback()
            release.set()
            resp = await reset

    assert resp.status_code == 200, resp.text
