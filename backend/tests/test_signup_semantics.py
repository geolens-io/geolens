"""Password sign-up rules and provider role validation.

Covers the role a verified sign-up receives, the switches /auth/register
obeys, and the 409/422 answers the provider endpoints give for slug clashes
and unknown roles.
"""

from __future__ import annotations

import re
import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.persistent_config import (
    EMAIL_VERIFICATION_REQUIRED,
    PASSWORD_LOGIN_ENABLED,
    REGISTRATION_DEFAULT_ROLE,
    REGISTRATION_ENABLED,
)
from app.modules.auth.models import User
from app.modules.auth.oauth.models import OAuthProvider

pytestmark = pytest.mark.anyio

_PASSWORD = "StrongPass1234!"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    from app.platform.ratelimit import limiter

    monkeypatch.setattr(limiter, "enabled", False)


@pytest.fixture
async def config(test_db_session):
    """Commit config overrides for one test and remove them afterwards."""
    touched = []

    async def _set(cfg, value) -> None:
        if cfg not in touched:
            touched.append(cfg)
        await cfg.set(test_db_session, value)

    yield _set

    await test_db_session.rollback()
    for cfg in reversed(touched):
        await cfg.reset(test_db_session)


@pytest.fixture
def sent_emails(monkeypatch) -> list:
    from app.core.config import settings

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com", raising=False)
    calls: list = []

    async def _fake_send(notification) -> None:
        calls.append(notification)

    monkeypatch.setattr(
        "app.platform.notifications.smtp_channel.send_email", _fake_send
    )
    return calls


@pytest.fixture
async def provider_slugs(test_db_session):
    """Slugs this test creates; their rows are deleted afterwards."""
    slugs: list[str] = []
    yield slugs
    await test_db_session.rollback()
    if slugs:
        await test_db_session.execute(
            delete(OAuthProvider).where(OAuthProvider.slug.in_(slugs))
        )
        await test_db_session.commit()


def _signup_body() -> dict:
    suffix = uuid.uuid4().hex[:8]
    return {
        "username": f"signup_{suffix}",
        "password": _PASSWORD,
        "email": f"signup_{suffix}@example.com",
    }


def _provider_body(slug: str, **overrides) -> dict:
    body = {
        "slug": slug,
        "display_name": "Role Check",
        "provider_type": "oidc",
        "client_id": "role-check-client",
        "client_secret": "role-check-secret",
        "authorize_url": "https://idp.example.com/authorize",
        "token_url": "https://idp.example.com/token",
        "userinfo_url": "https://idp.example.com/userinfo",
    }
    body.update(overrides)
    return body


async def _user(db, username: str) -> User | None:
    db.expire_all()
    return (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Verified sign-ups get the configured role
# ---------------------------------------------------------------------------


async def test_verified_signup_gets_registration_default_role(
    client: AsyncClient, test_db_session, config, sent_emails: list
) -> None:
    await config(REGISTRATION_ENABLED, True)
    await config(EMAIL_VERIFICATION_REQUIRED, True)
    await config(REGISTRATION_DEFAULT_ROLE, "editor")
    body = _signup_body()

    resp = await client.post("/auth/register/", json=body)
    assert resp.status_code == 201, resp.text
    assert (await _user(test_db_session, body["username"])).roles == []
    token = re.search(r"token=([A-Za-z0-9_\-]+)", sent_emails[0].body).group(1)

    verify = await client.post("/auth/verify-email/", json={"token": token})
    assert verify.status_code == 200, verify.text

    user = await _user(test_db_session, body["username"])
    assert user.status == "active"
    assert [role.name for role in user.roles] == ["editor"]


# ---------------------------------------------------------------------------
# /auth/register switches
# ---------------------------------------------------------------------------


async def test_register_refused_while_password_login_is_off(
    client: AsyncClient, test_db_session, config
) -> None:
    await config(REGISTRATION_ENABLED, True)
    await config(PASSWORD_LOGIN_ENABLED, False)
    body = _signup_body()

    resp = await client.post("/auth/register/", json=body)

    assert resp.status_code == 403, resp.text
    assert await _user(test_db_session, body["username"]) is None
    public = (await client.get("/auth/config/")).json()
    assert public["registration_enabled"] is True
    assert public["allow_signup"] is False


async def test_register_ignores_a_stale_cached_registration_switch(
    client: AsyncClient, test_db_session, config, monkeypatch
) -> None:
    await config(REGISTRATION_ENABLED, False)
    monkeypatch.setattr(REGISTRATION_ENABLED, "get", AsyncMock(return_value=True))
    body = _signup_body()

    resp = await client.post("/auth/register/", json=body)

    assert resp.status_code == 403, resp.text
    assert await _user(test_db_session, body["username"]) is None


async def test_register_ignores_a_stale_cached_verification_switch(
    client: AsyncClient, config, monkeypatch, sent_emails: list
) -> None:
    await config(REGISTRATION_ENABLED, True)
    await config(EMAIL_VERIFICATION_REQUIRED, True)
    monkeypatch.setattr(
        EMAIL_VERIFICATION_REQUIRED, "get", AsyncMock(return_value=False)
    )

    resp = await client.post("/auth/register/", json=_signup_body())

    assert resp.status_code == 201, resp.text
    assert resp.json()["next_step"] == "verify_email"
    assert len(sent_emails) == 1


# ---------------------------------------------------------------------------
# registration_default_role setting
# ---------------------------------------------------------------------------


async def test_registration_default_role_setting_rejects_unknown_roles(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    bad = await client.put(
        "/settings/",
        json={"settings": {"registration_default_role": "superuser"}},
        headers=admin_auth_header,
    )
    assert bad.status_code == 422, bad.text

    try:
        good = await client.put(
            "/settings/",
            json={"settings": {"registration_default_role": "admin"}},
            headers=admin_auth_header,
        )
        assert good.status_code == 200, good.text
        current = await client.get("/settings/all/", headers=admin_auth_header)
        auth_values = {
            item["key"]: item["value"] for item in current.json()["tabs"]["auth"]
        }
        assert auth_values["registration_default_role"] == "admin"
    finally:
        await REGISTRATION_DEFAULT_ROLE.reset(test_db_session)


# ---------------------------------------------------------------------------
# Provider slugs and roles
# ---------------------------------------------------------------------------


async def test_duplicate_provider_slug_is_a_conflict(
    client: AsyncClient, admin_auth_header: dict, provider_slugs: list
) -> None:
    taken = f"dup-{uuid.uuid4().hex[:8]}"
    other = f"dup-{uuid.uuid4().hex[:8]}"
    provider_slugs.extend([taken, other])
    first = await client.post(
        "/settings/oauth-providers/",
        json=_provider_body(taken),
        headers=admin_auth_header,
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        "/settings/oauth-providers/",
        json=_provider_body(other),
        headers=admin_auth_header,
    )
    assert second.status_code == 201, second.text

    create = await client.post(
        "/settings/oauth-providers/",
        json=_provider_body(taken),
        headers=admin_auth_header,
    )
    assert create.status_code == 409, create.text
    assert taken in create.json()["detail"]

    rename = await client.put(
        f"/settings/oauth-providers/{second.json()['id']}",
        json={"slug": taken},
        headers=admin_auth_header,
    )
    assert rename.status_code == 409, rename.text


@pytest.mark.parametrize(
    "overrides",
    [{"default_role": "superuser"}, {"default_role": "Admin"}],
)
async def test_provider_create_rejects_unknown_default_role(
    client: AsyncClient, admin_auth_header: dict, provider_slugs: list, overrides
) -> None:
    slug = f"role-{uuid.uuid4().hex[:8]}"
    provider_slugs.append(slug)

    resp = await client.post(
        "/settings/oauth-providers/",
        json=_provider_body(slug, **overrides),
        headers=admin_auth_header,
    )

    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    "change",
    [{"default_role": "owner"}, {"default_role": None}],
)
async def test_provider_update_rejects_unknown_default_role(
    client: AsyncClient, admin_auth_header: dict, provider_slugs: list, change
) -> None:
    slug = f"role-{uuid.uuid4().hex[:8]}"
    provider_slugs.append(slug)
    created = await client.post(
        "/settings/oauth-providers/",
        json=_provider_body(slug),
        headers=admin_auth_header,
    )
    assert created.status_code == 201, created.text

    resp = await client.put(
        f"/settings/oauth-providers/{created.json()['id']}",
        json=change,
        headers=admin_auth_header,
    )

    assert resp.status_code == 422, resp.text


@pytest.mark.usefixtures("enterprise_edition")
async def test_provider_group_mapping_rejects_unknown_roles(
    client: AsyncClient, admin_auth_header: dict, provider_slugs: list
) -> None:
    slug = f"map-{uuid.uuid4().hex[:8]}"
    provider_slugs.append(slug)
    mapping_body = _provider_body(
        slug,
        group_claim="groups",
        group_role_mapping={"GIS Admins": "admin", "Analysts": "analyst"},
    )

    create = await client.post(
        "/settings/oauth-providers/", json=mapping_body, headers=admin_auth_header
    )
    assert create.status_code == 422, create.text

    created = await client.post(
        "/settings/oauth-providers/",
        json=_provider_body(slug, group_claim="groups"),
        headers=admin_auth_header,
    )
    assert created.status_code == 201, created.text
    update = await client.put(
        f"/settings/oauth-providers/{created.json()['id']}",
        json={"group_role_mapping": {"Analysts": ["editor"]}},
        headers=admin_auth_header,
    )
    assert update.status_code == 422, update.text
