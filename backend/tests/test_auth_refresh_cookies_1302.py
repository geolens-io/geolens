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
    is_same_origin,
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


def _path_matches(request_path: str, cookie_path: str) -> bool:
    """RFC 6265 5.1.4 path-match, so tests reason the way a browser does.

    fix(#1446): `_arm_cookies` loads the jar with an UNSCOPED cookie, which is
    convenient for exercising handlers but structurally blind to `Path=` being
    wrong. The cookie-authenticated logout route was unreachable in a real
    browser while its handler test passed. Assert the scope explicitly.
    """
    if request_path == cookie_path:
        return True
    if not request_path.startswith(cookie_path):
        return False
    if cookie_path.endswith("/"):
        return True
    return request_path[len(cookie_path)] == "/"


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
        assert refresh["path"] == "/api/auth"
        assert refresh["samesite"].lower() == "lax"
        assert refresh["value"]

    async def test_cookie_scope_reaches_refresh_and_logout_but_not_the_data_plane(
        self, client: AsyncClient
    ):
        """The Path must cover BOTH routes that consume the cookie. Scoped to
        /auth/refresh alone, a browser never sent it to /auth/logout and the
        cookie-authenticated logout path could not fire (fix(#1446))."""
        resp = await _login(client, cookie_mode=True)
        cookie_path = _cookie_attrs(resp, REFRESH_COOKIE_NAME)["path"]

        assert _path_matches("/api/auth/refresh/", cookie_path)
        assert _path_matches("/api/auth/logout/", cookie_path)
        # Still off the data plane: no catalog, tile, upload, or export traffic
        # ever carries the refresh credential.
        for hot_path in (
            "/api/datasets/",
            "/api/maps/",
            "/api/tiles/1/2/3.pbf",
            "/api/collections/",
        ):
            assert not _path_matches(hot_path, cookie_path)

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
            (REFRESH_COOKIE_NAME, "/api/auth"),
            (CSRF_COOKIE_NAME, "/"),
        ):
            cleared = _cookie_attrs(resp, name)
            assert cleared["path"] == path
            assert cleared["value"] in ("", '""')

    # fix(#1446): a user returning after their 15-minute access token expired
    # would otherwise get a 401 here while their multi-day refresh cookie
    # stayed valid — the UI reports a clean logout and the session survives it.
    async def test_the_cookie_alone_can_authenticate_logout(self, client: AsyncClient):
        login = await _login(client, cookie_mode=True)
        refresh_value = _cookie_attrs(login, REFRESH_COOKIE_NAME)["value"]
        csrf_value = _cookie_attrs(login, CSRF_COOKIE_NAME)["value"]
        _arm_cookies(client, refresh_value, csrf_value)

        # No Authorization header at all — as if the access token had expired.
        resp = await client.post(
            "/auth/logout/", headers={**COOKIE_MODE, "X-CSRF-Token": csrf_value}
        )
        assert resp.status_code == 204, resp.text

        _arm_cookies(client, refresh_value, csrf_value)
        after = await client.post(
            "/auth/refresh/",
            headers={**COOKIE_MODE, "X-CSRF-Token": csrf_value},
        )
        assert after.status_code == 401

    async def test_cookie_authenticated_logout_still_requires_csrf(
        self, client: AsyncClient
    ):
        """Otherwise a cross-site page could force-logout any signed-in user."""
        login = await _login(client, cookie_mode=True)
        refresh_value = _cookie_attrs(login, REFRESH_COOKIE_NAME)["value"]
        csrf_value = _cookie_attrs(login, CSRF_COOKIE_NAME)["value"]
        _arm_cookies(client, refresh_value, csrf_value)

        resp = await client.post("/auth/logout/", headers=COOKIE_MODE)
        assert resp.status_code == 403

        # The session must survive the rejected attempt.
        _arm_cookies(client, refresh_value, csrf_value)
        still_alive = await client.post(
            "/auth/refresh/",
            headers={**COOKIE_MODE, "X-CSRF-Token": csrf_value},
        )
        assert still_alive.status_code == 200

    async def test_logout_without_any_credential_is_401(self, client: AsyncClient):
        client.cookies.clear()
        resp = await client.post("/auth/logout/")
        assert resp.status_code == 401

    # fix(#1446): a split-origin deployment has no usable cookie and keeps its
    # refresh token in the store. Without a body transport, an expired access
    # token there means logout 401s and the session outlives it.
    async def test_a_body_refresh_token_can_authenticate_logout(
        self, client: AsyncClient
    ):
        refresh_token = (await _login(client, cookie_mode=False)).json()[
            "refresh_token"
        ]
        client.cookies.clear()

        resp = await client.post("/auth/logout/", json={"refresh_token": refresh_token})
        assert resp.status_code == 204, resp.text

        after = await client.post(
            "/auth/refresh/", json={"refresh_token": refresh_token}
        )
        assert after.status_code == 401

    async def test_a_bogus_body_refresh_token_is_401(self, client: AsyncClient):
        client.cookies.clear()
        resp = await client.post(
            "/auth/logout/", json={"refresh_token": "not-a-real-token"}
        )
        assert resp.status_code == 401

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


class TestRotationRevocationRace:
    """fix(#1446): a rotation that read its row before a concurrent logout must
    not commit a still-active replacement afterwards. Client-side guards cannot
    help here — the browser applies the late Set-Cookie and the row is already
    in the database — so rotation and revocation serialize on the owner row."""

    async def test_a_rotation_racing_logout_never_leaves_a_live_session(
        self, client: AsyncClient, monkeypatch
    ):
        import anyio

        from app.modules.auth.service import AuthService

        # Force the interleaving instead of hoping for it. Firing both requests
        # and hoping to land in the window passes with or without the fix, which
        # would make this test decorative. Stalling rotation right after it has
        # read its row and taken the owner lock puts logout squarely inside the
        # danger window: unserialized, logout commits its revocation first and
        # rotation then inserts a live successor; serialized, logout blocks on
        # the lock and its revocation sees the successor.
        original_create_access_token = AuthService.create_access_token

        async def _stalled_create_access_token(self, *args, **kwargs):
            await anyio.sleep(0.75)
            return await original_create_access_token(self, *args, **kwargs)

        login = await _login(client, cookie_mode=True)
        refresh_value = _cookie_attrs(login, REFRESH_COOKIE_NAME)["value"]
        csrf_value = _cookie_attrs(login, CSRF_COOKIE_NAME)["value"]
        access = login.json()["access_token"]

        results: dict[str, int] = {}

        async def _refresh() -> None:
            resp = await client.post(
                "/auth/refresh/",
                headers={
                    **COOKIE_MODE,
                    "X-CSRF-Token": csrf_value,
                    "Cookie": (
                        f"{REFRESH_COOKIE_NAME}={refresh_value}; "
                        f"{CSRF_COOKIE_NAME}={csrf_value}"
                    ),
                },
            )
            results["refresh"] = resp.status_code
            if resp.status_code == 200:
                results["rotated"] = 1
                attrs = _cookie_attrs(resp, REFRESH_COOKIE_NAME)
                results["rotated_value"] = attrs["value"]  # type: ignore[assignment]

        async def _logout() -> None:
            # Let rotation reach the stall (and take the lock) first.
            await anyio.sleep(0.2)
            resp = await client.post(
                "/auth/logout/", headers={"Authorization": f"Bearer {access}"}
            )
            results["logout"] = resp.status_code

        client.cookies.clear()
        monkeypatch.setattr(
            AuthService, "create_access_token", _stalled_create_access_token
        )
        async with anyio.create_task_group() as tg:
            tg.start_soon(_refresh)
            tg.start_soon(_logout)
        monkeypatch.undo()

        assert results["logout"] == 204

        # Whatever the interleaving, no refresh credential may survive: neither
        # the original nor any replacement the rotation managed to mint.
        client.cookies.clear()
        original = await client.post(
            "/auth/refresh/", json={"refresh_token": refresh_value}
        )
        assert original.status_code == 401, "original token outlived logout"

        rotated_value = results.get("rotated_value")
        if rotated_value:
            client.cookies.clear()
            rotated = await client.post(
                "/auth/refresh/", json={"refresh_token": rotated_value}
            )
            assert rotated.status_code == 401, "rotated token outlived logout"


class TestOriginComparison:
    """fix(#1446): the OAuth callback decides cookie-vs-fragment delivery from
    this, comparing the deployment's two CONFIGURED public URLs. Deriving one
    side from the live request was wrong under any Host-rewriting proxy (the
    shipped Vite dev proxy sets changeOrigin: true), and spelling out a default
    port must not read as a different origin."""

    def test_the_shipped_topology_is_same_origin(self):
        # SPA at the root, API under /api on the same host.
        assert is_same_origin("https://geo.example.com", "https://geo.example.com/api")

    def test_explicit_default_port_matches_an_omitted_one(self):
        assert is_same_origin("https://example.com:443", "https://example.com")
        assert is_same_origin("http://example.com:80", "http://example.com")

    def test_host_comparison_is_case_insensitive(self):
        assert is_same_origin("https://Example.COM", "https://example.com/api")

    def test_genuinely_different_origins_do_not_match(self):
        assert not is_same_origin("https://example.com", "https://elsewhere.example")
        assert not is_same_origin("https://example.com", "http://example.com")
        assert not is_same_origin("https://example.com", "https://example.com:8443")

    def test_unusable_values_are_not_same_origin(self):
        assert not is_same_origin("https://example.com", "/relative/path")
        assert not is_same_origin("https://example.com", "")


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
