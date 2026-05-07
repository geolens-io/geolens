"""Tests for PersistentConfig generic class and centralized registry."""

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


# ---------------------------------------------------------------------------
# Unified settings API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def admin_auth_header(client: AsyncClient) -> dict:
    """Get admin auth header."""
    from app.core.config import settings as app_settings

    resp = await client.post(
        "/auth/login/",
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
# Enabled widgets endpoint + validator tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_enabled_widgets_endpoint_returns_list(client: AsyncClient):
    """GET /settings/enabled-widgets/ returns a list or null (public, no auth)."""
    resp = await client.get("/settings/enabled-widgets/")
    assert resp.status_code == 200
    data = resp.json()
    assert data is None or isinstance(data, list)


@pytest.mark.anyio
async def test_enabled_widgets_roundtrip(client: AsyncClient, admin_auth_header: dict):
    """PUT /settings/ with enabled_widgets persists and GET returns the list."""
    widget_ids = ["legend", "measurement"]
    resp = await client.put(
        "/settings/",
        json={"settings": {"enabled_widgets": widget_ids}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get("/settings/enabled-widgets/")
    assert resp.status_code == 200
    assert resp.json() == widget_ids


@pytest.mark.anyio
async def test_enabled_widgets_null_means_all(
    client: AsyncClient, admin_auth_header: dict
):
    """PUT /settings/ with enabled_widgets=null resets to 'all enabled'."""
    resp = await client.put(
        "/settings/",
        json={"settings": {"enabled_widgets": None}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get("/settings/enabled-widgets/")
    assert resp.status_code == 200
    assert resp.json() is None  # null = no restriction (all widgets enabled)


@pytest.mark.anyio
async def test_enabled_widgets_rejects_non_list(
    client: AsyncClient, admin_auth_header: dict
):
    """PUT /settings/ with enabled_widgets as a string returns 422."""
    resp = await client.put(
        "/settings/",
        json={"settings": {"enabled_widgets": "not-a-list"}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_enabled_widgets_rejects_empty_strings(
    client: AsyncClient, admin_auth_header: dict
):
    """PUT /settings/ with empty string in enabled_widgets returns 422."""
    resp = await client.put(
        "/settings/",
        json={"settings": {"enabled_widgets": ["valid", ""]}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_enabled_widgets_rejects_non_string_items(
    client: AsyncClient, admin_auth_header: dict
):
    """PUT /settings/ with non-string items in enabled_widgets returns 422."""
    resp = await client.put(
        "/settings/",
        json={"settings": {"enabled_widgets": [123, True]}},
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
    # Set CORS origins to allow http://example.com
    await client.put(
        "/settings/",
        json={"settings": {"cors_allowed_origins": "http://example.com"}},
        headers=admin_auth_header,
    )

    resp = await client.get("/health", headers={"Origin": "http://example.com"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://example.com"
    assert resp.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.anyio
async def test_cors_non_matching_origin_no_headers(
    client: AsyncClient, admin_auth_header: dict
):
    """Request with non-matching origin gets no CORS headers."""
    await client.put(
        "/settings/",
        json={"settings": {"cors_allowed_origins": "http://example.com"}},
        headers=admin_auth_header,
    )

    resp = await client.get("/health", headers={"Origin": "http://evil.com"})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.anyio
async def test_cors_preflight_returns_200(client: AsyncClient, admin_auth_header: dict):
    """OPTIONS preflight with matching origin returns 200 with CORS headers."""
    await client.put(
        "/settings/",
        json={"settings": {"cors_allowed_origins": "http://example.com"}},
        headers=admin_auth_header,
    )

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
async def test_cors_wildcard_rejected_with_credentials(
    client: AsyncClient, admin_auth_header: dict
):
    """Wildcard '*' is rejected — credentials=true requires explicit origins."""
    await client.put(
        "/settings/",
        json={"settings": {"cors_allowed_origins": "*"}},
        headers=admin_auth_header,
    )

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
        "/auth/login/",
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
    from app.core.persistent_config import _DEFAULT_LOGIN_RATE_LIMIT, LOGIN_RATE_LIMIT
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
        assert value == _DEFAULT_LOGIN_RATE_LIMIT

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
        _DEFAULT_LOGIN_RATE_LIMIT,
        AI_ENABLED,
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
        assert all_values["login_rate_limit"] == _DEFAULT_LOGIN_RATE_LIMIT
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
