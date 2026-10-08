"""An SSO callback hands the SPA a one-time code; only its exchange sets the session cookie."""

import asyncio
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from sqlalchemy import select, update

from app.modules.auth.cookies import sso_exchange_cookie_name
from app.modules.auth.models import RefreshToken, User
from app.modules.auth.service import AuthService
from tests.factories import create_user

COOKIE_MODE = {"X-GeoLens-Auth-Mode": "cookie"}
PASSWORD = "TestPass1234!"


class Browser:
    """One browser's cookie jar.

    The app sets cookie paths under its ``/api`` root path while the test
    client calls the unmounted routes, so httpx would never send them back.
    Every route used here sits under every such path, so one flat jar is what
    the browser would send.
    """

    def __init__(self, client):
        self.client = client
        self.jar: dict[str, str] = {}
        self.nonces: dict[str, str] = {}

    async def request(self, method: str, path: str, *, headers=None, **kwargs):
        sent = dict(headers or {})
        if self.jar:
            sent["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.jar.items())
        self.client.cookies.clear()
        response = await self.client.request(method, path, headers=sent, **kwargs)
        for header in response.headers.get_list("set-cookie"):
            for name, morsel in SimpleCookie(header).items():
                if morsel["max-age"] == "0" or not morsel.value:
                    self.jar.pop(name, None)
                else:
                    self.jar[name] = morsel.value
        return response

    async def sso_callback(self, user_id: uuid.UUID, nonce: str | None = None):
        """Start sign-in with *nonce* and complete an IdP round-trip as *user_id*.

        A real app keeps the flow's state in the signed session; only the
        IdP's token response is stubbed.
        """
        nonce = nonce or secrets.token_urlsafe(32)
        provider = MagicMock(provider_type="oidc", discovery_url=None)

        async def resolve_user(db, *_args):
            query = select(User).where(User.id == user_id)
            return (await db.execute(query)).scalar_one()

        with (
            patch(
                "app.modules.auth.oauth.router.build_oauth_client",
                AsyncMock(side_effect=lambda *_: (_idp_app(), provider)),
            ),
            patch(
                "app.modules.auth.oauth.service.find_or_create_oauth_user",
                side_effect=resolve_user,
            ),
        ):
            started = await self.request(
                "GET", f"/auth/oauth/sso/login?nonce={nonce}", follow_redirects=False
            )
            assert started.status_code == 302, started.text
            state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
            response = await self.request(
                "GET",
                f"/auth/oauth/sso/callback?code=idp-code&state={state}",
                follow_redirects=False,
            )
        fragment = parse_qs(urlsplit(response.headers.get("location", "")).fragment)
        if "code" in fragment:
            self.nonces[fragment["code"][0]] = nonce
        return response

    async def exchange(self, code: str, headers=COOKIE_MODE, nonce: str | None = None):
        body = {"code": code, "nonce": nonce or self.nonces.get(code, "n" * 43)}
        return await self.request(
            "POST", "/auth/oauth/exchange/", json=body, headers=headers
        )

    async def refresh(self):
        headers = {**COOKIE_MODE, "X-CSRF-Token": self.jar.get("geolens_csrf", "")}
        return await self.request("POST", "/auth/refresh/", headers=headers)


def _idp_app():
    from authlib.integrations.starlette_client import OAuth

    from app.modules.auth.oauth.router import _SSRFSafeOAuth2App

    oauth = OAuth()
    oauth.register(
        name="sso",
        client_cls=_SSRFSafeOAuth2App,
        client_id="client",
        client_secret="secret",
        authorize_url="https://idp.example/authorize",
        access_token_url="https://idp.example/token",
        client_kwargs={"scope": "openid email", "code_challenge_method": "S256"},
    )
    app = oauth.create_client("sso")
    app.fetch_access_token = AsyncMock(
        return_value={
            "access_token": "idp",
            "token_type": "bearer",
            "userinfo": {"sub": "s"},
        }
    )
    return app


def _pin_public_urls(monkeypatch, app_url: str, api_url: str) -> None:
    """Pin the URLs the callback resolves, whatever other tests left configured."""
    import app.modules.auth.oauth.router as oauth_router
    import app.modules.auth.oauth.sign_in_redirect as sign_in_redirect

    monkeypatch.setattr(
        oauth_router, "get_public_app_url", AsyncMock(return_value=app_url)
    )
    monkeypatch.setattr(
        oauth_router, "get_public_api_url", AsyncMock(return_value=api_url)
    )
    monkeypatch.setattr(
        sign_in_redirect, "get_public_api_url", AsyncMock(return_value=api_url)
    )


@pytest.fixture
def same_origin_urls(monkeypatch):
    _pin_public_urls(monkeypatch, "http://test", "http://test/api")


@pytest.fixture
async def browser(client):
    client.cookies.clear()
    return Browser(client)


async def _viewer(client, admin_auth_header) -> uuid.UUID:
    headers, _ = await create_user(client, admin_auth_header, "viewer")
    return _subject(headers["Authorization"].removeprefix("Bearer "))


@pytest.fixture
async def viewer_id(client, admin_auth_header) -> uuid.UUID:
    return await _viewer(client, admin_auth_header)


def _code(response) -> str:
    assert response.status_code == 302, response.text
    fragment = parse_qs(urlsplit(response.headers["location"]).fragment)
    assert set(fragment) == {"code", "nonce"}, fragment
    return fragment["code"][0]


def _subject(access_token: str) -> uuid.UUID:
    payload = jwt.decode(access_token, options={"verify_signature": False})
    return uuid.UUID(payload["sub"])


@pytest.mark.anyio
async def test_callback_redirects_with_a_code_and_no_session_cookie(
    browser, viewer_id, same_origin_urls
):
    nonce = secrets.token_urlsafe(32)
    response = await browser.sso_callback(viewer_id, nonce)

    assert response.headers["referrer-policy"] == "no-referrer"
    code = _code(response)
    assert parse_qs(urlsplit(response.headers["location"]).fragment)["nonce"] == [nonce]
    assert len(code) == 43
    set_cookies = response.headers.get_list("set-cookie")
    assert not any(
        c.startswith(("geolens_refresh=", "geolens_csrf=")) for c in set_cookies
    )
    name = sso_exchange_cookie_name(code)
    [binding] = [c for c in set_cookies if c.startswith(f"{name}=")]
    attributes = {part.strip().lower() for part in binding.split(";")}
    assert {"httponly", "samesite=lax", "max-age=120"} <= attributes
    assert "path=/api/auth/oauth/exchange" in attributes


@pytest.mark.anyio
async def test_exchange_sets_the_session_cookie_once(
    browser, viewer_id, same_origin_urls
):
    code = _code(await browser.sso_callback(viewer_id))

    response = await browser.exchange(code)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["refresh_token"] is None
    assert _subject(body["access_token"]) == viewer_id
    assert {"geolens_refresh", "geolens_csrf"} <= set(browser.jar)
    assert sso_exchange_cookie_name(code) not in browser.jar

    assert (await browser.exchange(code)).status_code == 401
    refreshed = await browser.refresh()
    assert refreshed.status_code == 200, refreshed.text
    assert _subject(refreshed.json()["access_token"]) == viewer_id


@pytest.mark.anyio
async def test_two_pending_sign_ins_in_one_browser_both_redeem(
    browser, client, admin_auth_header, viewer_id, same_origin_urls
):
    first = _code(await browser.sso_callback(viewer_id))
    other_id = await _viewer(client, admin_auth_header)
    second = _code(await browser.sso_callback(other_id))

    first_session = await browser.exchange(first)
    assert first_session.status_code == 200, first_session.text
    assert _subject(first_session.json()["access_token"]) == viewer_id
    second_session = await browser.exchange(second)
    assert second_session.status_code == 200, second_session.text
    assert _subject(second_session.json()["access_token"]) == other_id


@pytest.mark.anyio
async def test_concurrent_exchanges_redeem_one_code_once(
    browser, viewer_id, same_origin_urls
):
    code = _code(await browser.sso_callback(viewer_id))

    results = await asyncio.gather(*(browser.exchange(code) for _ in range(3)))

    assert sorted(r.status_code for r in results) == [200, 401, 401]


@pytest.mark.anyio
async def test_expired_code_is_refused(
    browser, test_db_session, viewer_id, same_origin_urls
):
    code = _code(await browser.sso_callback(viewer_id))
    await test_db_session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == viewer_id,
            RefreshToken.token_hash.startswith("sso-exchange:"),
        )
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await test_db_session.commit()

    assert (await browser.exchange(code)).status_code == 401


@pytest.mark.anyio
async def test_staging_sweeps_expired_staged_sign_ins(
    browser, test_db_session, viewer_id, same_origin_urls
):
    _code(await browser.sso_callback(viewer_id))
    staged = (
        RefreshToken.user_id == viewer_id,
        RefreshToken.token_hash.startswith("sso-exchange:"),
    )
    await test_db_session.execute(
        update(RefreshToken)
        .where(*staged)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await test_db_session.commit()

    _code(await Browser(browser.client).sso_callback(viewer_id))

    rows = (
        await test_db_session.execute(select(RefreshToken.expires_at).where(*staged))
    ).scalars()
    assert [expires_at > datetime.now(UTC) for expires_at in rows] == [True]


@pytest.mark.anyio
async def test_code_is_bound_to_the_browser_the_callback_redirected(
    client, admin_auth_header, viewer_id, same_origin_urls
):
    own, other = Browser(client), Browser(client)
    own_code = _code(await own.sso_callback(viewer_id))
    other_code = _code(
        await other.sso_callback(await _viewer(client, admin_auth_header))
    )

    assert (await other.exchange(own_code)).status_code == 401
    assert (await own.exchange(other_code)).status_code == 401
    assert (await Browser(client).exchange(own_code)).status_code == 401

    # A refused pairing spends neither code.
    response = await own.exchange(own_code)
    assert response.status_code == 200, response.text
    assert _subject(response.json()["access_token"]) == viewer_id
    assert (await other.exchange(other_code)).status_code == 200


@pytest.mark.anyio
async def test_exchange_refuses_a_request_a_cross_site_page_could_send(
    browser, viewer_id, same_origin_urls
):
    code = _code(await browser.sso_callback(viewer_id))
    name = sso_exchange_cookie_name(code)
    nonce = browser.jar[name]

    assert (await browser.exchange(code, headers={})).status_code == 400
    # A sibling host can add a parent-domain cookie of the same name but never
    # remove this host's, so a duplicate is refused.
    browser.jar.clear()
    duplicated = {
        **COOKIE_MODE,
        "Cookie": f"{name}=x; {name}={nonce}",
    }
    assert (await browser.exchange(code, headers=duplicated)).status_code == 401

    browser.jar[name] = nonce
    assert (await browser.exchange(code)).status_code == 200


@pytest.mark.anyio
async def test_code_and_refresh_token_are_not_interchangeable(
    browser, viewer_id, same_origin_urls
):
    code = _code(await browser.sso_callback(viewer_id))
    nonce = browser.jar[sso_exchange_cookie_name(code)]

    for candidate in (code, f"{code}.{nonce}", f"sso-exchange:{code}.{nonce}"):
        response = await browser.request(
            "POST", "/auth/refresh/", json={"refresh_token": candidate}
        )
        assert response.status_code == 401

    assert (await browser.exchange(code)).status_code == 200
    refresh_token = browser.jar["geolens_refresh"]
    browser.jar[sso_exchange_cookie_name(refresh_token)] = nonce
    assert (await browser.exchange(refresh_token)).status_code == 401


@pytest.mark.anyio
async def test_logout_everywhere_before_the_exchange_voids_the_code(
    browser, test_db_session, viewer_id, same_origin_urls
):
    code = _code(await browser.sso_callback(viewer_id))

    await AuthService(test_db_session).revoke_all_tokens(viewer_id)

    assert (await browser.exchange(code)).status_code == 401


@pytest.mark.anyio
async def test_a_refresh_landing_after_the_callback_does_not_win(
    browser, client, test_db_session, admin_auth_header, viewer_id, same_origin_urls
):
    """The previous session's refresh lands after the redirect, before the exchange."""
    previous_id = await _viewer(client, admin_auth_header)
    previous_username = (
        await test_db_session.execute(
            select(User.username).where(User.id == previous_id)
        )
    ).scalar_one()
    signed_in = await browser.request(
        "POST",
        "/auth/login",
        data={"username": previous_username, "password": PASSWORD},
        headers=COOKIE_MODE,
    )
    assert signed_in.status_code == 200, signed_in.text
    # The tab that will refresh read the CSRF cookie before the redirect.
    late_refresh_headers = {**COOKIE_MODE, "X-CSRF-Token": browser.jar["geolens_csrf"]}

    code = _code(await browser.sso_callback(viewer_id))
    late = await browser.request("POST", "/auth/refresh/", headers=late_refresh_headers)
    assert late.status_code == 200, late.text
    assert _subject(late.json()["access_token"]) == previous_id
    assert (await browser.exchange(code)).status_code == 200

    next_refresh = await browser.refresh()
    assert next_refresh.status_code == 200, next_refresh.text
    assert _subject(next_refresh.json()["access_token"]) == viewer_id


@pytest.mark.anyio
async def test_cross_origin_spa_still_receives_fragment_tokens(
    browser, viewer_id, monkeypatch
):
    _pin_public_urls(monkeypatch, "http://app.test", "http://api.test/api")

    nonce = secrets.token_urlsafe(32)
    response = await browser.sso_callback(viewer_id, nonce)

    location = urlsplit(response.headers["location"])
    assert location.netloc == "app.test"
    fragment = parse_qs(location.fragment)
    assert {"token", "refresh_token", "expires_in", "nonce"} == set(fragment)
    assert fragment["nonce"] == [nonce]
    assert not any(
        c.startswith("geolens_") for c in response.headers.get_list("set-cookie")
    )


@pytest.mark.anyio
@pytest.mark.parametrize("query", ["", "?nonce=", "?nonce=short", f"?nonce={'!' * 43}"])
async def test_sign_in_cannot_start_without_a_nonce(browser, same_origin_urls, query):
    with patch(
        "app.modules.auth.oauth.router.build_oauth_client",
        AsyncMock(side_effect=lambda *_: (_idp_app(), MagicMock())),
    ):
        response = await browser.request(
            "GET", f"/auth/oauth/sso/login{query}", follow_redirects=False
        )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_exchange_needs_the_nonce_the_sign_in_started_with(
    browser, viewer_id, same_origin_urls
):
    code = _code(await browser.sso_callback(viewer_id))

    wrong = await browser.exchange(code, nonce=secrets.token_urlsafe(32))
    assert wrong.status_code == 401
    assert (await browser.exchange(code)).status_code == 200


@pytest.mark.anyio
async def test_a_code_from_another_browser_redeems_nothing_in_this_tab(
    client, admin_auth_header, viewer_id, same_origin_urls
):
    """Another account's code and binding cookie, presented with this tab's nonce."""
    other, own = Browser(client), Browser(client)
    other_code = _code(
        await other.sso_callback(await _viewer(client, admin_auth_header))
    )
    own_nonce = secrets.token_urlsafe(32)
    _code(await own.sso_callback(viewer_id, own_nonce))
    binding = sso_exchange_cookie_name(other_code)
    own.jar[binding] = other.jar[binding]

    assert (await own.exchange(other_code, nonce=own_nonce)).status_code == 401


@pytest.mark.anyio
@pytest.mark.parametrize("nonce", ["", "short", "!" * 43])
async def test_the_sign_in_redirect_refuses_a_malformed_nonce(nonce):
    from app.modules.auth.oauth.sign_in_redirect import sso_sign_in_redirect

    with pytest.raises(ValueError):
        await sso_sign_in_redirect(
            MagicMock(),
            MagicMock(),
            MagicMock(),
            frontend_url="http://test",
            sign_in_nonce=nonce,
        )
