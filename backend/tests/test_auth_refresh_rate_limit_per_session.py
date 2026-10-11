"""Token refresh is rate-limited per session, not per client address.

Every page load in the SPA spends one refresh, so a per-address budget runs
out for many people behind one NAT while each of their sessions is idle. The
session id only counts once the database accepts the presented token, so
made-up credentials keep sharing the caller's address bucket.

The conftest ``client`` disables the limiter; each test enables it and resets
its storage on the way in and out. Every request here comes from the same
ASGI client address.
"""

import secrets
from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.modules.auth.cookies import CSRF_COOKIE_NAME, REFRESH_COOKIE_NAME
from app.platform.ratelimit import limiter

pytestmark = pytest.mark.anyio

ADMIN_USER = settings.geolens_admin_username
ADMIN_PASS = settings.geolens_admin_password.get_secret_value()
SESSION_LIMIT = 30


@pytest.fixture
def refresh_limits() -> Iterator[None]:
    limiter._storage.reset()
    limiter.enabled = True
    try:
        yield
    finally:
        limiter.enabled = False
        limiter._storage.reset()


async def _session(client: AsyncClient) -> str:
    """Sign in with the limiter off, so creating sessions spends no budget."""
    enabled = limiter.enabled
    limiter.enabled = False
    try:
        resp = await client.post(
            "/auth/login", data={"username": ADMIN_USER, "password": ADMIN_PASS}
        )
    finally:
        limiter.enabled = enabled
    assert resp.status_code == 200, resp.text
    return resp.json()["refresh_token"]


async def _refresh(client: AsyncClient, token: str):
    client.cookies.clear()
    return await client.post("/auth/refresh/", json={"refresh_token": token})


async def test_distinct_sessions_from_one_address_exceed_the_session_limit(
    client: AsyncClient, refresh_limits: None
):
    tokens = [await _session(client), await _session(client)]
    per_session = SESSION_LIMIT - 5

    for _ in range(per_session):
        for i, token in enumerate(tokens):
            resp = await _refresh(client, token)
            assert resp.status_code == 200, resp.text
            tokens[i] = resp.json()["refresh_token"]


async def test_one_session_over_its_limit_gets_429(
    client: AsyncClient, refresh_limits: None
):
    token = await _session(client)
    for _ in range(SESSION_LIMIT):
        resp = await _refresh(client, token)
        assert resp.status_code == 200, resp.text
        token = resp.json()["refresh_token"]

    resp = await _refresh(client, token)
    assert resp.status_code == 429
    assert resp.headers["Retry-After"]

    other = await _refresh(client, await _session(client))
    assert other.status_code == 200, other.text


async def test_cookie_session_is_limited_on_its_own_bucket(
    client: AsyncClient, refresh_limits: None
):
    enabled = limiter.enabled
    limiter.enabled = False
    try:
        login = await client.post(
            "/auth/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASS},
            headers={"X-GeoLens-Auth-Mode": "cookie"},
        )
    finally:
        limiter.enabled = enabled
    assert login.status_code == 200, login.text
    refresh_cookie = login.cookies[REFRESH_COOKIE_NAME]
    csrf = login.cookies[CSRF_COOKIE_NAME]

    statuses = []
    for _ in range(SESSION_LIMIT + 1):
        client.cookies.clear()
        client.cookies.set(REFRESH_COOKIE_NAME, refresh_cookie)
        client.cookies.set(CSRF_COOKIE_NAME, csrf)
        resp = await client.post(
            "/auth/refresh/",
            headers={"X-GeoLens-Auth-Mode": "cookie", "X-CSRF-Token": csrf},
        )
        statuses.append(resp.status_code)
        if resp.status_code == 200:
            refresh_cookie = resp.cookies[REFRESH_COOKIE_NAME]
            csrf = resp.cookies[CSRF_COOKIE_NAME]

    assert statuses == [200] * SESSION_LIMIT + [429]

    body_session = await _refresh(client, await _session(client))
    assert body_session.status_code == 200, body_session.text


async def test_forged_tokens_share_the_address_bucket(
    client: AsyncClient, refresh_limits: None
):
    for _ in range(SESSION_LIMIT):
        resp = await _refresh(client, secrets.token_urlsafe(32))
        assert resp.status_code == 401, resp.text

    resp = await _refresh(client, secrets.token_urlsafe(32))
    assert resp.status_code == 429

    client.cookies.clear()
    no_credential = await client.post("/auth/refresh/")
    assert no_credential.status_code == 429

    valid = await _refresh(client, await _session(client))
    assert valid.status_code == 200, valid.text
