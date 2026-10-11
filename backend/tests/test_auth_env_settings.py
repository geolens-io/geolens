"""Environment variables for the sign-up and sign-in settings."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core import config as config_module
from app.core.auth_settings import AuthSettings
from app.core.config import settings
from tests.test_config import BASE_ENV, _make_settings

_ENV_VARS = (
    "EMAIL_VERIFICATION_REQUIRED",
    "PASSWORD_LOGIN_ENABLED",
    "LOGIN_RATE_LIMIT",
    "ALLOWED_EMAIL_DOMAINS",
)


@pytest.fixture
def clean_auth_env(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_defaults_match_the_previous_constants():
    defaults = AuthSettings()
    assert defaults.email_verification_required is True
    assert defaults.password_login_enabled is True
    assert defaults.login_rate_limit == 5
    assert defaults.allowed_email_domains_list == []


def test_each_env_var_reaches_settings(clean_auth_env):
    clean_auth_env.setenv("EMAIL_VERIFICATION_REQUIRED", "false")
    clean_auth_env.setenv("PASSWORD_LOGIN_ENABLED", "false")
    clean_auth_env.setenv("LOGIN_RATE_LIMIT", "20")
    clean_auth_env.setenv(
        "ALLOWED_EMAIL_DOMAINS", " Example.com, *.Corp.example ,example.com,"
    )

    s = _make_settings()

    assert s.email_verification_required is False
    assert s.password_login_enabled is False
    assert s.login_rate_limit == 20
    assert s.allowed_email_domains_list == ["example.com", "*.corp.example"]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LOGIN_RATE_LIMIT", "0"),
        ("LOGIN_RATE_LIMIT", "1001"),
        ("LOGIN_RATE_LIMIT", "five"),
        ("PASSWORD_LOGIN_ENABLED", "maybe"),
        ("EMAIL_VERIFICATION_REQUIRED", "maybe"),
        ("ALLOWED_EMAIL_DOMAINS", "*"),
        ("ALLOWED_EMAIL_DOMAINS", "example.com,com"),
        ("ALLOWED_EMAIL_DOMAINS", "*.com"),
    ],
)
def test_invalid_env_value_is_refused(clean_auth_env, name, value):
    clean_auth_env.setenv(name, value)
    with pytest.raises(ValidationError):
        _make_settings()


def test_invalid_env_value_stops_startup_naming_the_variable(clean_auth_env, capsys):
    for field, value in BASE_ENV.items():
        clean_auth_env.setenv(field.upper(), value)
    clean_auth_env.setenv("ALLOWED_EMAIL_DOMAINS", "example.com,not a domain")

    with pytest.raises(SystemExit):
        config_module._create_settings()

    assert "ALLOWED_EMAIL_DOMAINS" in capsys.readouterr().err


_ENV_ONLY_CASES = [
    ("email_verification_required", False, False),
    ("password_login_enabled", False, False),
    ("login_rate_limit", 17, 17),
    (
        "allowed_email_domains",
        "example.com,*.corp.example",
        ["example.com", "*.corp.example"],
    ),
]


@pytest.mark.anyio
@pytest.mark.parametrize(("key", "env_value", "effective"), _ENV_ONLY_CASES)
async def test_env_value_is_the_env_managed_setting_in_env_only_mode(
    client: AsyncClient, admin_auth_header, key, env_value, effective
):
    from app.api.main import app
    from app.core.dependencies import get_db
    from app.core.persistent_config import _registry

    cfg = next(c for c in _registry if c.key == key)

    with (
        patch.object(settings, key, env_value),
        patch.object(settings, "env_only_config", True),
    ):
        async for db in app.dependency_overrides[get_db]():
            assert await cfg.get(db) == effective
            assert await cfg.get_uncached(db) == effective

        resp = await client.get("/settings/all/", headers=admin_auth_header)
        assert resp.status_code == 200
        item = next(s for s in resp.json()["tabs"]["auth"] if s["key"] == key)
        assert item["value"] == effective
        assert item["source"] == "env_only"


@pytest.mark.anyio
async def test_env_login_rate_limit_is_enforced_in_env_only_mode(client: AsyncClient):
    from app.api.main import app
    from app.core.dependencies import get_db
    from app.core.persistent_config import (
        LOGIN_RATE_LIMIT,
        _sync_rate_limit_cache,
        get_cached_login_rate_limit,
    )
    from app.modules.auth.router import _login_rate_limit

    _sync_rate_limit_cache.pop("login_rate_limit", None)
    with (
        patch.object(settings, "login_rate_limit", 17),
        patch.object(settings, "env_only_config", True),
    ):
        async for db in app.dependency_overrides[get_db]():
            await LOGIN_RATE_LIMIT.get(db)
        assert get_cached_login_rate_limit() == 17
        assert _login_rate_limit() == "17/minute"


@pytest.mark.anyio
async def test_env_password_login_off_reaches_the_public_auth_config(
    client: AsyncClient,
):
    with (
        patch.object(settings, "registration_enabled", True),
        patch.object(settings, "password_login_enabled", False),
        patch.object(settings, "env_only_config", True),
    ):
        resp = await client.get("/auth/config/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["password_login_enabled"] is False
    assert body["allow_signup"] is False
