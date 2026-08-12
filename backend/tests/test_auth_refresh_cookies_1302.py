"""GH-1302: browser refresh tokens in httpOnly cookies with CSRF protection.

The compatibility contract these tests pin down: without the explicit
``X-GeoLens-Auth-Mode: cookie`` opt-in every response is byte-identical to the
pre-GH-1302 shape, which is what keeps the CLI, the generated SDKs, and CI
logins working. With it, the refresh token leaves the JSON body entirely.

The test client talks to the ASGI app directly, so it never traverses the
``/api`` rewrite that nginx and the Vite dev proxy apply. The cookie's ``Path``
is derived from ``root_path`` (``/api``) and therefore does NOT match the
client's request path, so httpx's own jar would never replay it. Tests read the
``Set-Cookie`` attributes directly (asserting the real values) and re-arm the
jar by hand via ``_arm_cookies``.
"""

from httpx import AsyncClient

from app.core.config import settings
from app.modules.auth.cookies import (
    CSRF_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    is_same_origin_as_request,
)

ADMIN_USER = settings.geolens_admin_username
ADMIN_PASS = settings.geolens_admin_password.get_secret_value()

COOKIE_MODE = {"X-GeoLens-Auth-Mode": "cookie"}


async def _login(client: AsyncClient, *, cookie_mode: bool):
    headers = dict(COOKIE_MODE) if cookie_mode else {}
    resp = await client.post(
        "/auth/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASS},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp


def _cookie_attrs(resp, name: str) -> dict[str, str]:
    """Parse the Set-Cookie header for *name* into a lowercased attribute map."""
    for header in resp.headers.get_list("set-cookie"):
        if not header.startswith(f"{name}="):
            continue
        parts = [p.strip() for p in header.split(";")]
        attrs: dict[str, str] = {"value": parts[0].split("=", 1)[1]}
        for part in parts[1:]:
            key, _, value = part.partition("=")
            attrs[key.lower()] = value
        return attrs
    raise AssertionError(
        f"no Set-Cookie for {name!r} in {resp.headers.get_list('set-cookie')}"
    )


def _arm_cookies(client: AsyncClient, refresh: str | None, csrf: str | None) -> None:
    """Load the jar as a browser would, replacing anything already there.

    Set on the client rather than per-request: httpx deprecated per-request
    ``cookies=`` because its persistence semantics are ambiguous.
    """
    client.cookies.clear()
    if refresh is not None:
        client.cookies.set(REFRESH_COOKIE_NAME, refresh)
    if csrf is not None:
        client.cookies.set(CSRF_COOKIE_NAME, csrf)


class TestProgrammaticCallersUnchanged:
    """Compat guard for the CLI / SDK / CI JSON path (no opt-in header)."""

    async def test_login_without_optin_returns_body_token_and_no_cookies(
        self, client: AsyncClient
    ):
        resp = await _login(client, cookie_mode=False)
        assert resp.json()["refresh_token"]
        assert not resp.headers.get_list("set-cookie")

    async def test_refresh_without_optin_returns_body_token_and_no_cookies(
        self, client: AsyncClient
    ):
        refresh_token = (await _login(client, cookie_mode=False)).json()[
            "refresh_token"
        ]
        client.cookies.clear()

        resp = await client.post(
            "/auth/refresh/", json={"refresh_token": refresh_token}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["refresh_token"]
        assert data["refresh_token"] != refresh_token
        assert not resp.headers.get_list("set-cookie")

    async def test_refresh_without_optin_needs_no_csrf(self, client: AsyncClient):
        """A CSRF token must never become mandatory for the JSON path — that
        would break every non-browser caller."""
        refresh_token = (await _login(client, cookie_mode=False)).json()[
            "refresh_token"
        ]
        client.cookies.clear()

        resp = await client.post(
            "/auth/refresh/", json={"refresh_token": refresh_token}
        )
        assert resp.status_code == 200


class TestBrowserCookieFlow:
    async def test_login_sets_httponly_refresh_cookie_and_nulls_body_token(
        self, client: AsyncClient
    ):
        resp = await _login(client, cookie_mode=True)

        assert resp.json()["refresh_token"] is None
        refresh = _cookie_attrs(resp, REFRESH_COOKIE_NAME)
        assert "httponly" in refresh
        assert refresh["path"] == "/api/auth/refresh"
        assert refresh["samesite"].lower() == "lax"
        assert refresh["value"]

    async def test_csrf_cookie_is_readable_and_not_a_credential(
        self, client: AsyncClient
    ):
        """The double-submit token must be script-readable (the SPA echoes it
        back), unlike the refresh cookie."""
        resp = await _login(client, cookie_mode=True)
        csrf = _cookie_attrs(resp, CSRF_COOKIE_NAME)
        assert "httponly" not in csrf
        assert csrf["path"] == "/"
        assert csrf["value"]

    async def test_cookie_refresh_rotates_and_keeps_token_out_of_body(
        self, client: AsyncClient
    ):
        login = await _login(client, cookie_mode=True)
        refresh_value = _cookie_attrs(login, REFRESH_COOKIE_NAME)["value"]
        csrf_value = _cookie_attrs(login, CSRF_COOKIE_NAME)["value"]
        _arm_cookies(client, refresh_value, csrf_value)

        resp = await client.post(
            "/auth/refresh/",
            headers={**COOKIE_MODE, "X-CSRF-Token": csrf_value},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["access_token"]
        assert data["refresh_token"] is None

        rotated = _cookie_attrs(resp, REFRESH_COOKIE_NAME)
        assert rotated["value"] != refresh_value
        assert "httponly" in rotated

    async def test_cookie_refresh_needs_no_request_body(self, client: AsyncClient):
        """The browser sends no body at all — the credential is the cookie."""
        login = await _login(client, cookie_mode=True)
        refresh_value = _cookie_attrs(login, REFRESH_COOKIE_NAME)["value"]
        csrf_value = _cookie_attrs(login, CSRF_COOKIE_NAME)["value"]
        _arm_cookies(client, refresh_value, csrf_value)

        resp = await client.post(
            "/auth/refresh/",
            headers={**COOKIE_MODE, "X-CSRF-Token": csrf_value},
        )
        assert resp.status_code == 200, resp.text


class TestCsrfEnforcement:
    """AC: a state-changing request carrying the session cookie but no CSRF
    token is rejected."""

    async def test_cookie_without_csrf_header_is_rejected(self, client: AsyncClient):
        login = await _login(client, cookie_mode=True)
        refresh_value = _cookie_attrs(login, REFRESH_COOKIE_NAME)["value"]
        csrf_value = _cookie_attrs(login, CSRF_COOKIE_NAME)["value"]
        _arm_cookies(client, refresh_value, csrf_value)

        resp = await client.post("/auth/refresh/", headers=COOKIE_MODE)
        assert resp.status_code == 403
        assert "CSRF" in resp.json()["detail"]

    async def test_mismatched_csrf_header_is_rejected(self, client: AsyncClient):
        login = await _login(client, cookie_mode=True)
        refresh_value = _cookie_attrs(login, REFRESH_COOKIE_NAME)["value"]
        csrf_value = _cookie_attrs(login, CSRF_COOKIE_NAME)["value"]
        _arm_cookies(client, refresh_value, csrf_value)

        resp = await client.post(
            "/auth/refresh/",
            headers={**COOKIE_MODE, "X-CSRF-Token": "not-the-right-token"},
        )
        assert resp.status_code == 403

    async def test_rejected_csrf_leaves_the_refresh_token_usable(
        self, client: AsyncClient
    ):
        """A forged cross-site refresh must not burn the victim's session."""
        login = await _login(client, cookie_mode=True)
        refresh_value = _cookie_attrs(login, REFRESH_COOKIE_NAME)["value"]
        csrf_value = _cookie_attrs(login, CSRF_COOKIE_NAME)["value"]
        _arm_cookies(client, refresh_value, csrf_value)

        forged = await client.post("/auth/refresh/", headers=COOKIE_MODE)
        assert forged.status_code == 403

        legitimate = await client.post(
            "/auth/refresh/",
            headers={**COOKIE_MODE, "X-CSRF-Token": csrf_value},
        )
        assert legitimate.status_code == 200


class TestTransitionFromBodyTokens:
    """Sessions established before this shipped hold a localStorage refresh
    token. Their first post-deploy refresh must migrate them to the cookie
    rather than logging them out."""

    async def test_body_token_under_cookie_mode_migrates_to_cookie(
        self, client: AsyncClient
    ):
        legacy_token = (await _login(client, cookie_mode=False)).json()["refresh_token"]
        client.cookies.clear()

        resp = await client.post(
            "/auth/refresh/",
            headers=COOKIE_MODE,
            json={"refresh_token": legacy_token},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["refresh_token"] is None

        migrated = _cookie_attrs(resp, REFRESH_COOKIE_NAME)
        assert "httponly" in migrated
        assert migrated["value"] != legacy_token

    async def test_cookie_wins_over_a_stale_body_token(self, client: AsyncClient):
        """Once the cookie exists it is authoritative, so a stale localStorage
        value left behind by the migration cannot resurrect an old family."""
        stale = (await _login(client, cookie_mode=False)).json()["refresh_token"]
        login = await _login(client, cookie_mode=True)
        refresh_value = _cookie_attrs(login, REFRESH_COOKIE_NAME)["value"]
        csrf_value = _cookie_attrs(login, CSRF_COOKIE_NAME)["value"]
        _arm_cookies(client, refresh_value, csrf_value)

        resp = await client.post(
            "/auth/refresh/",
            headers={**COOKIE_MODE, "X-CSRF-Token": csrf_value},
            json={"refresh_token": stale},
        )
        assert resp.status_code == 200

        # The stale body token was never presented, so it still rotates cleanly.
        client.cookies.clear()
        still_valid = await client.post("/auth/refresh/", json={"refresh_token": stale})
        assert still_valid.status_code == 200

    async def test_missing_credential_entirely_is_401_not_422(
        self, client: AsyncClient
    ):
        client.cookies.clear()
        resp = await client.post("/auth/refresh/", headers=COOKIE_MODE)
        assert resp.status_code == 401


class TestLogoutClearsCookies:
    async def test_logout_expires_both_cookies(self, client: AsyncClient):
        login = await _login(client, cookie_mode=True)
        access = login.json()["access_token"]

        resp = await client.post(
            "/auth/logout/", headers={"Authorization": f"Bearer {access}"}
        )
        assert resp.status_code == 204

        for name, path in (
            (REFRESH_COOKIE_NAME, "/api/auth/refresh"),
            (CSRF_COOKIE_NAME, "/"),
        ):
            cleared = _cookie_attrs(resp, name)
            assert cleared["path"] == path
            assert cleared["value"] in ("", '""')

    async def test_logout_revokes_the_cookie_token_server_side(
        self, client: AsyncClient
    ):
        """Clearing the cookie is cosmetic on its own; the row must die too."""
        login = await _login(client, cookie_mode=True)
        refresh_value = _cookie_attrs(login, REFRESH_COOKIE_NAME)["value"]
        csrf_value = _cookie_attrs(login, CSRF_COOKIE_NAME)["value"]
        access = login.json()["access_token"]

        await client.post(
            "/auth/logout/", headers={"Authorization": f"Bearer {access}"}
        )
        _arm_cookies(client, refresh_value, csrf_value)

        resp = await client.post(
            "/auth/refresh/",
            headers={**COOKIE_MODE, "X-CSRF-Token": csrf_value},
        )
        assert resp.status_code == 401


class TestOriginComparison:
    """fix(#1446): the OAuth callback decides cookie-vs-fragment delivery from
    this. Spelling out a default port is the same origin to a browser, and
    comparing raw netlocs silently dropped such deployments back to putting the
    refresh token in the URL fragment."""

    @staticmethod
    def _request(url: str):
        from starlette.datastructures import URL

        class _FakeRequest:
            def __init__(self, value: str) -> None:
                self.url = URL(value)

        return _FakeRequest(url)

    def test_explicit_default_port_matches_an_omitted_one(self):
        req = self._request("https://example.com/auth/callback")
        assert is_same_origin_as_request(req, "https://example.com:443")
        assert is_same_origin_as_request(
            self._request("http://example.com/auth/callback"), "http://example.com:80"
        )

    def test_plain_match_and_case_insensitive_host(self):
        req = self._request("https://Example.COM/auth/callback")
        assert is_same_origin_as_request(req, "https://example.com")

    def test_genuinely_different_origins_do_not_match(self):
        req = self._request("https://example.com/auth/callback")
        assert not is_same_origin_as_request(req, "https://elsewhere.example")
        assert not is_same_origin_as_request(req, "http://example.com")
        assert not is_same_origin_as_request(req, "https://example.com:8443")

    def test_unusable_values_are_not_same_origin(self):
        req = self._request("https://example.com/auth/callback")
        assert not is_same_origin_as_request(req, "/relative/path")
        assert not is_same_origin_as_request(req, "")


class TestSecureFlagFollowsProductionPosture:
    """SEC-005: same switch that hides the docs and sets SessionMiddleware's
    https_only. Dev/test have no TLS terminator, so a Secure cookie there would
    be dropped silently."""

    async def test_secure_absent_in_development(self, client: AsyncClient):
        resp = await _login(client, cookie_mode=True)
        assert "secure" not in _cookie_attrs(resp, REFRESH_COOKIE_NAME)

    async def test_secure_set_in_production(self, client: AsyncClient, monkeypatch):
        monkeypatch.setattr(
            type(settings), "is_production", property(lambda self: True)
        )
        resp = await _login(client, cookie_mode=True)
        assert "secure" in _cookie_attrs(resp, REFRESH_COOKIE_NAME)
        assert "secure" in _cookie_attrs(resp, CSRF_COOKIE_NAME)
