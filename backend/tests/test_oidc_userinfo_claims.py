"""Generic OIDC sign-in reads claims the ID token omits from a same-subject UserInfo."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.modules.auth.oauth import service as oauth_service
from app.modules.auth.oauth.router import _oidc_identity_claims


def _provider(provider_type="oidc", group_claim=None):
    return SimpleNamespace(
        provider_type=provider_type, group_claim=group_claim, slug="idp"
    )


def _client(userinfo):
    if isinstance(userinfo, Exception):
        return SimpleNamespace(userinfo=AsyncMock(side_effect=userinfo))
    return SimpleNamespace(userinfo=AsyncMock(return_value=userinfo))


ID_CLAIMS = {"sub": "okta-sub", "email": "ana@example.com", "name": "Ana"}


async def test_userinfo_fills_only_claims_the_id_token_lacks():
    client = _client(
        {
            "sub": "okta-sub",
            "email": "ana@example.com",
            "email_verified": True,
            "name": "Ana Userinfo",
            "locale": "en-US",
        }
    )

    claims = await _oidc_identity_claims(
        client, _provider(), {"userinfo": dict(ID_CLAIMS)}
    )

    assert claims == {**ID_CLAIMS, "email_verified": True, "locale": "en-US"}
    client.userinfo.assert_awaited_once()


@pytest.mark.parametrize(
    "response",
    [
        {"sub": "okta-sub", "email": "other@example.com", "email_verified": True},
        {"sub": "okta-sub", "email_verified": True},
        {"sub": "okta-sub", "email": None, "email_verified": True},
    ],
)
async def test_userinfo_verification_for_another_address_is_dropped(response):
    claims = await _oidc_identity_claims(
        _client(response), _provider(), {"userinfo": dict(ID_CLAIMS)}
    )

    assert "email_verified" not in claims
    assert claims["email"] == "ana@example.com"


async def test_userinfo_verification_matches_the_address_ignoring_case():
    client = _client(
        {"sub": "okta-sub", "email": "Ana@Example.COM", "email_verified": True}
    )

    claims = await _oidc_identity_claims(
        client, _provider(), {"userinfo": dict(ID_CLAIMS)}
    )

    assert claims["email_verified"] is True
    assert claims["email"] == "ana@example.com"


async def test_id_token_without_email_takes_email_and_verification_together():
    client = _client(
        {"sub": "okta-sub", "email": "ana@example.com", "email_verified": True}
    )

    claims = await _oidc_identity_claims(
        client, _provider(), {"userinfo": {"sub": "okta-sub"}}
    )

    assert claims == {
        "sub": "okta-sub",
        "email": "ana@example.com",
        "email_verified": True,
    }


async def test_id_token_verification_does_not_vouch_for_a_userinfo_email():
    client = _client({"sub": "okta-sub", "email": "ana@example.com", "groups": []})

    claims = await _oidc_identity_claims(
        client,
        _provider(group_claim="groups"),
        {"userinfo": {"sub": "okta-sub", "email_verified": True}},
    )

    assert "email_verified" not in claims


@pytest.mark.parametrize(
    "response",
    [
        {"sub": "someone-else", "email_verified": True},
        {"email_verified": True},
        ["sub", "okta-sub"],
    ],
)
async def test_userinfo_for_another_subject_is_ignored(response):
    claims = await _oidc_identity_claims(
        _client(response), _provider(), {"userinfo": dict(ID_CLAIMS)}
    )

    assert claims == ID_CLAIMS


async def test_failed_userinfo_keeps_the_id_token_claims():
    claims = await _oidc_identity_claims(
        _client(RuntimeError("boom")), _provider(), {"userinfo": dict(ID_CLAIMS)}
    )

    assert claims == ID_CLAIMS


@pytest.mark.parametrize(
    ("provider", "id_claims"),
    [
        (_provider(), {**ID_CLAIMS, "email_verified": False}),
        (
            _provider(group_claim="groups"),
            {**ID_CLAIMS, "email_verified": True, "groups": []},
        ),
        (_provider("google"), ID_CLAIMS),
        (_provider("microsoft"), ID_CLAIMS),
    ],
)
async def test_no_userinfo_call_when_not_needed(provider, id_claims):
    client = _client({"sub": "okta-sub", "email_verified": True})

    claims = await _oidc_identity_claims(client, provider, {"userinfo": id_claims})

    assert claims == id_claims
    client.userinfo.assert_not_awaited()


async def test_missing_group_claim_is_filled_from_userinfo():
    client = _client({"sub": "okta-sub", "groups": ["gis-editors"]})
    id_claims = {**ID_CLAIMS, "email_verified": True}

    claims = await _oidc_identity_claims(
        client, _provider(group_claim="groups"), {"userinfo": id_claims}
    )

    assert claims["groups"] == ["gis-editors"]
    client.userinfo.assert_awaited_once()


async def test_without_an_id_token_userinfo_is_the_claim_source():
    client = _client({"sub": "s", "email_verified": True})

    claims = await _oidc_identity_claims(client, _provider(), {"access_token": "a"})

    assert claims == {"sub": "s", "email_verified": True}


async def _sign_in(client, db, monkeypatch, *, userinfo, allowlist):
    """Run a full OIDC callback whose ID token omits email_verified."""
    from app.modules.auth.oauth.schemas import OAuthProviderCreate
    from app.modules.auth.oauth.service import create_provider
    from tests.test_sso_sign_in_exchange import Browser, _idp_app, _pin_public_urls

    _pin_public_urls(monkeypatch, "http://app.test", "http://api.test/api")
    suffix = uuid.uuid4().hex[:6]
    provider = await create_provider(
        db,
        OAuthProviderCreate(
            slug=f"okta-{suffix}",
            display_name="Okta",
            provider_type="oidc",
            client_id=f"client-{suffix}",
            client_secret="test-secret",
            enabled=True,
            default_role="viewer",
        ),
    )
    await db.commit()
    sub = f"okta-sub-{suffix}"
    email = f"ana-{suffix}@example.com"
    idp = _idp_app()
    idp.fetch_access_token = AsyncMock(
        return_value={
            "access_token": "idp",
            "token_type": "bearer",
            "userinfo": {"sub": sub, "email": email},
        }
    )
    if isinstance(userinfo, Exception):
        idp.userinfo = AsyncMock(side_effect=userinfo)
    else:
        idp.userinfo = AsyncMock(
            return_value={"email": email, **userinfo, "sub": userinfo["sub"] or sub}
        )
    client.cookies.clear()
    browser = Browser(client)
    monkeypatch.setattr(
        oauth_service.ALLOWED_EMAIL_DOMAINS,
        "get_uncached",
        AsyncMock(return_value=allowlist),
    )
    monkeypatch.setattr(
        oauth_service.REGISTRATION_ENABLED, "get_uncached", AsyncMock(return_value=True)
    )
    with patch(
        "app.modules.auth.oauth.router.build_oauth_client",
        AsyncMock(return_value=(idp, provider)),
    ):
        started = await browser.request(
            "GET", f"/auth/oauth/sso/login?nonce={'n' * 43}", follow_redirects=False
        )
        state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
        response = await browser.request(
            "GET",
            f"/auth/oauth/sso/callback?code=idp-code&state={state}",
            follow_redirects=False,
        )
    assert response.status_code == 302
    return parse_qs(urlsplit(response.headers["location"]).fragment), sub


async def _linked_user(db, sub):
    from app.modules.auth.models import User
    from app.modules.auth.oauth.models import OAuthAccount

    db.expire_all()
    return (
        await db.execute(
            select(User)
            .join(OAuthAccount, OAuthAccount.user_id == User.id)
            .where(OAuthAccount.subject == sub)
        )
    ).scalar_one_or_none()


async def test_allowlisted_identity_verified_by_userinfo_is_provisioned(
    client, test_db_session, monkeypatch
):
    fragment, sub = await _sign_in(
        client,
        test_db_session,
        monkeypatch,
        userinfo={"sub": None, "email_verified": True},
        allowlist=["example.com"],
    )

    assert "error" not in fragment
    user = await _linked_user(test_db_session, sub)
    assert user is not None and user.email_verified is True


async def test_userinfo_for_another_subject_leaves_the_identity_unverified(
    client, test_db_session, monkeypatch
):
    fragment, sub = await _sign_in(
        client,
        test_db_session,
        monkeypatch,
        userinfo={"sub": "someone-else", "email_verified": True},
        allowlist=["example.com"],
    )

    assert fragment["error"] == ["email_not_verified"]
    assert await _linked_user(test_db_session, sub) is None


async def test_userinfo_verifying_another_address_is_refused_by_the_allowlist(
    client, test_db_session, monkeypatch
):
    fragment, sub = await _sign_in(
        client,
        test_db_session,
        monkeypatch,
        userinfo={"sub": None, "email": "other@example.com", "email_verified": True},
        allowlist=["example.com"],
    )

    assert fragment["error"] == ["email_not_verified"]
    assert await _linked_user(test_db_session, sub) is None


async def test_failed_userinfo_still_signs_in_without_an_allowlist(
    client, test_db_session, monkeypatch
):
    fragment, sub = await _sign_in(
        client,
        test_db_session,
        monkeypatch,
        userinfo=RuntimeError("userinfo down"),
        allowlist=[],
    )

    assert "error" not in fragment
    user = await _linked_user(test_db_session, sub)
    assert user is not None and user.email_verified is False
