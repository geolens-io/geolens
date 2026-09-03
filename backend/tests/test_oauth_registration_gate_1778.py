"""fix(#1778): turning on an OAuth provider must not turn on signup.

Codebase audit 2026-08-30, "Enabling any OAuth provider silently overrides the
operator's 'registration disabled' switch and auto-provisions active accounts".

``registration_enabled`` ships False and the password path honours it
(POST /auth/register/ returns 403), but JIT provisioning never read it: an
unknown subject reaching /auth/oauth/{slug}/login was created with
status="active" and the provider's ``default_role``, which defaults to
``viewer`` -- a role that can list and export every ``internal`` dataset. The
admin Settings screen still read "Registration enabled: off".

Counterfactual: remove the REGISTRATION_ENABLED check from
find_or_create_oauth_user and test_an_unknown_identity_is_refused fails with a
provisioned user instead of the refusal.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.modules.auth.models import User
from app.modules.auth.oauth import service as oauth_service
from app.modules.auth.oauth.schemas import OAuthProviderCreate
from app.modules.auth.oauth.service import (
    OAuthRegistrationDisabledError,
    create_provider,
    find_or_create_oauth_user,
)

pytestmark = pytest.mark.anyio


def _registration(monkeypatch, enabled: bool) -> None:
    monkeypatch.setattr(
        oauth_service.REGISTRATION_ENABLED,
        "get_uncached",
        AsyncMock(return_value=enabled),
    )


async def _provider(db):
    suffix = uuid.uuid4().hex[:6]
    return await create_provider(
        db,
        OAuthProviderCreate(
            slug=f"gate-provider-{suffix}",
            display_name="Gate Provider",
            provider_type="oidc",
            client_id=f"client-{suffix}",
            client_secret="test-secret",
            enabled=True,
            default_role="viewer",
        ),
    )


def _userinfo(**overrides) -> dict:
    info = {
        "sub": f"sub-{uuid.uuid4().hex[:8]}",
        "email": f"gate-{uuid.uuid4().hex[:8]}@example.com",
        "email_verified": True,
        "name": "Gate User",
    }
    info.update(overrides)
    return info


async def test_an_unknown_identity_is_refused(client, test_db_session, monkeypatch):
    _registration(monkeypatch, False)
    provider = await _provider(test_db_session)
    await test_db_session.commit()

    info = _userinfo()
    before = await test_db_session.scalar(select(func.count()).select_from(User))

    with pytest.raises(OAuthRegistrationDisabledError):
        await find_or_create_oauth_user(test_db_session, provider, info, {})

    await test_db_session.rollback()
    after = await test_db_session.scalar(select(func.count()).select_from(User))
    assert after == before, "a refused OAuth sign-in must create no account"


async def test_a_returning_user_still_signs_in(client, test_db_session, monkeypatch):
    """The gate is about creating accounts, not about locking anyone out."""
    _registration(monkeypatch, True)
    provider = await _provider(test_db_session)
    await test_db_session.commit()

    info = _userinfo()
    created = await find_or_create_oauth_user(test_db_session, provider, info, {})
    await test_db_session.commit()
    created_id = created.id

    _registration(monkeypatch, False)
    returning = await find_or_create_oauth_user(test_db_session, provider, info, {})
    assert returning.id == created_id


async def test_an_existing_account_still_links_by_verified_email(
    client, test_db_session, admin_auth_header, monkeypatch
):
    """An admin-created account is what "an administrator creates it first"
    means, so the email-match link must survive the gate."""
    _registration(monkeypatch, False)
    provider = await _provider(test_db_session)
    await test_db_session.commit()

    username = f"preseeded_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    resp = await client.post(
        "/admin/users/",
        json={
            "username": username,
            "password": "TestPass1234!",
            "email": email,
            "role": "viewer",
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text

    linked = await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(email=email), {}
    )
    assert linked.username == username


async def test_the_switch_being_on_still_provisions(
    client, test_db_session, monkeypatch
):
    _registration(monkeypatch, True)
    provider = await _provider(test_db_session)
    await test_db_session.commit()

    user = await find_or_create_oauth_user(test_db_session, provider, _userinfo(), {})
    await test_db_session.commit()
    assert user.auth_provider == "oauth"
    assert user.is_active is True
