"""Password sign-in is throttled per account, and remembered browsers keep their own budget."""

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select, text, update
from starlette.requests import Request

from app.core.config import settings
from app.core.db.tenant_session import current_tenant_var
from app.modules.auth.login_throttle import (
    LOGIN_FAILURE_LIMIT,
    _device_mac,
    _presented_device_key,
    create_trust_token,
    device_cookie_name,
    login_account_key,
    mint_device_cookie,
    reserve_login_attempt,
)
from app.modules.auth.models import LoginAttempt, LoginTrustToken
from app.modules.auth.providers import local
from tests.conftest import get_auth_header

PASSWORD = "TestPass1234!"
COOKIE_MODE = {"X-GeoLens-Auth-Mode": "cookie"}


async def _new_user(client: AsyncClient) -> str:
    admin = await get_auth_header(
        client,
        settings.geolens_admin_username,
        settings.geolens_admin_password.get_secret_value(),
    )
    username = f"throttle_{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": PASSWORD, "role": "viewer"},
        headers=admin,
    )
    assert resp.status_code == 201, resp.text
    return username


async def _login(
    client: AsyncClient,
    username: str,
    password: str,
    *,
    device: str | None = None,
    cookie_mode: bool = False,
):
    headers = dict(COOKIE_MODE) if cookie_mode else {}
    if device is not None:
        headers["Cookie"] = (
            f"{device_cookie_name(login_account_key(username))}={device}"
        )
    return await client.post(
        "/auth/login",
        data={"username": username, "password": password},
        headers=headers,
    )


async def _fail(client: AsyncClient, username: str, times: int, **kwargs) -> list[int]:
    return [
        (await _login(client, username, "wrong-password", **kwargs)).status_code
        for _ in range(times)
    ]


def _set_cookie(resp, name: str) -> dict[str, str]:
    for header in resp.headers.get_list("set-cookie"):
        if header.startswith(f"{name}="):
            parts = [p.strip() for p in header.split(";")]
            attrs = {"value": parts[0].split("=", 1)[1]}
            for part in parts[1:]:
                key, _, value = part.partition("=")
                attrs[key.lower()] = value
            return attrs
    raise AssertionError(f"no Set-Cookie for {name!r}")


async def _remembered_device(client: AsyncClient, username: str) -> str:
    resp = await _login(client, username, PASSWORD, cookie_mode=True)
    assert resp.status_code == 200, resp.text
    name = device_cookie_name(login_account_key(username))
    return _set_cookie(resp, name)["value"]


def _request(cookie: str = "") -> Request:
    headers = [(b"cookie", cookie.encode())] if cookie else []
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/login",
            "headers": headers,
            "query_string": b"",
            "client": ("203.0.113.9", 1234),
        }
    )


async def test_untrusted_clients_are_refused_after_the_limit(client: AsyncClient):
    username = await _new_user(client)

    assert await _fail(client, username, LOGIN_FAILURE_LIMIT) == [401] * 10

    refused = await _login(client, username, "wrong-password")
    assert refused.status_code == 429
    assert refused.json()["detail"]["code"] == "login_throttled"
    retry_after = int(refused.headers["retry-after"])
    assert 0 < retry_after <= 3600


async def test_a_correct_password_from_an_unknown_client_is_refused_while_throttled(
    client: AsyncClient,
):
    username = await _new_user(client)
    await _fail(client, username, LOGIN_FAILURE_LIMIT)

    assert (await _login(client, username, PASSWORD)).status_code == 429
    assert (
        await _login(client, username, PASSWORD, cookie_mode=True)
    ).status_code == 429


async def test_a_remembered_browser_signs_in_while_unknown_clients_are_refused(
    client: AsyncClient,
):
    username = await _new_user(client)
    device = await _remembered_device(client, username)
    await _fail(client, username, LOGIN_FAILURE_LIMIT)

    assert (await _login(client, username, PASSWORD)).status_code == 429
    resp = await _login(client, username, PASSWORD, device=device)
    assert resp.status_code == 200, resp.text


async def test_a_remembered_browser_spends_a_budget_of_its_own(client: AsyncClient):
    username = await _new_user(client)
    device = await _remembered_device(client, username)

    assert (
        await _fail(client, username, LOGIN_FAILURE_LIMIT, device=device) == [401] * 10
    )
    # Its failures leave the shared budget alone...
    assert (await _login(client, username, PASSWORD)).status_code == 200
    # ...and once spent, the browser is one more unknown client.
    await _fail(client, username, LOGIN_FAILURE_LIMIT)
    assert (await _login(client, username, PASSWORD, device=device)).status_code == 429


async def test_existing_and_unknown_usernames_are_refused_alike(
    client: AsyncClient, monkeypatch
):
    real = await _new_user(client)
    ghost = f"nobody_{uuid.uuid4().hex[:8]}"
    checks: list[str] = []

    real_verify = local.verify_password_async

    async def counting_verify(plain, hashed):
        checks.append("bcrypt")
        return await real_verify(plain, hashed)

    monkeypatch.setattr(local, "verify_password_async", counting_verify)

    outcomes = {}
    for username in (real, ghost):
        statuses = await _fail(client, username, LOGIN_FAILURE_LIMIT)
        checks.clear()
        refused = await _login(client, username, "wrong-password")
        outcomes[username] = (
            statuses,
            refused.status_code,
            refused.json(),
            "retry-after" in refused.headers,
            list(checks),
        )
    assert outcomes[real] == outcomes[ghost]
    assert outcomes[real][1] == 429
    assert outcomes[real][4] == []


async def test_parallel_attempts_cannot_exceed_the_limit(client: AsyncClient):
    import app.core.db as db_module

    username = f"parallel_{uuid.uuid4().hex[:8]}"

    async def attempt() -> bool:
        async with db_module.async_session() as db:
            try:
                await reserve_login_attempt(db, _request(), username)
            except HTTPException as exc:
                assert exc.status_code == 429
                return False
            return True

    results = await asyncio.gather(*(attempt() for _ in range(LOGIN_FAILURE_LIMIT + 2)))
    assert results.count(True) == LOGIN_FAILURE_LIMIT


async def test_only_wrong_passwords_count(client: AsyncClient, test_db_session):
    username = await _new_user(client)
    await test_db_session.execute(
        text(
            "UPDATE catalog.users SET status = 'pending', is_active = false "
            "WHERE username = :username"
        ),
        {"username": username},
    )
    await test_db_session.commit()

    statuses = [
        (await _login(client, username, PASSWORD)).status_code
        for _ in range(LOGIN_FAILURE_LIMIT + 2)
    ]
    assert statuses == [403] * (LOGIN_FAILURE_LIMIT + 2)


async def test_filling_a_budget_writes_one_audit_row(
    client: AsyncClient, test_db_session
):
    username = await _new_user(client)
    device = await _remembered_device(client, username)
    await _fail(client, username, LOGIN_FAILURE_LIMIT + 3)
    # The oldest failure slides out of the window and a new one refills it,
    # still inside the window that already tripped.
    await test_db_session.execute(
        update(LoginAttempt)
        .where(
            LoginAttempt.account_key == login_account_key(username),
            LoginAttempt.id
            == select(LoginAttempt.id)
            .where(LoginAttempt.account_key == login_account_key(username))
            .order_by(LoginAttempt.attempted_at)
            .limit(1)
            .scalar_subquery(),
        )
        .values(attempted_at=datetime.now(tz=UTC) - timedelta(hours=2))
    )
    await test_db_session.commit()
    assert await _fail(client, username, 2) == [401, 429]
    await _fail(client, username, LOGIN_FAILURE_LIMIT, device=device)

    rows = (
        await test_db_session.execute(
            text(
                "SELECT details, ip_address FROM catalog.audit_logs "
                "WHERE action = 'user.login.throttled' "
                "AND details->>'username' = :username ORDER BY created_at"
            ),
            {"username": username},
        )
    ).all()
    assert [row.details["scope"] for row in rows] == ["untrusted", "device"]
    assert rows[0].details == {
        "username": username,
        "scope": "untrusted",
        "failures": LOGIN_FAILURE_LIMIT,
        "window_seconds": 3600,
    }


async def test_sessions_api_keys_and_refresh_keep_working_while_throttled(
    client: AsyncClient,
):
    username = await _new_user(client)
    signed_in = await _login(client, username, PASSWORD)
    tokens = signed_in.json()
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
    created = await client.post(
        "/auth/api-keys/", json={"name": "automation"}, headers=bearer
    )
    assert created.status_code == 201, created.text
    await _fail(client, username, LOGIN_FAILURE_LIMIT)
    assert (await _login(client, username, PASSWORD)).status_code == 429

    assert (await client.get("/auth/me", headers=bearer)).status_code == 200
    by_key = await client.get("/auth/me", headers={"X-Api-Key": created.json()["key"]})
    assert by_key.status_code == 200
    refreshed = await client.post(
        "/auth/refresh/", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200, refreshed.text


def test_only_the_password_handler_consults_the_throttle():
    """SSO, refresh, API keys and sessions never reach it by construction."""
    from pathlib import Path

    app_root = Path(__file__).resolve().parents[1] / "app"
    callers = sorted(
        str(path.relative_to(app_root))
        for path in app_root.rglob("*.py")
        if "reserve_login_attempt(" in path.read_text()
        and path.name != "login_throttle.py"
    )
    assert callers == ["modules/auth/router.py"]


async def test_device_cookie_attributes(client: AsyncClient, monkeypatch):
    username = await _new_user(client)
    resp = await _login(client, username, PASSWORD, cookie_mode=True)
    attrs = _set_cookie(resp, device_cookie_name(login_account_key(username)))
    assert "httponly" in attrs
    assert attrs["samesite"].lower() == "strict"
    assert attrs["path"] == "/api/auth/login"
    assert attrs["max-age"] == str(180 * 24 * 3600)
    assert "domain" not in attrs
    assert "secure" not in attrs

    monkeypatch.setattr(type(settings), "is_production", property(lambda self: True))
    resp = await _login(client, username, PASSWORD, cookie_mode=True)
    assert "secure" in _set_cookie(
        resp, device_cookie_name(login_account_key(username))
    )


async def test_login_without_cookie_mode_sets_no_cookie(client: AsyncClient):
    username = await _new_user(client)
    resp = await _login(client, username, PASSWORD)
    assert resp.status_code == 200
    assert resp.headers.get_list("set-cookie") == []
    assert set(resp.json()) == {
        "access_token",
        "refresh_token",
        "token_type",
        "expires_in",
    }


def test_forged_expired_and_foreign_device_cookies_are_ignored():
    key = login_account_key("alice")
    name = device_cookie_name(key)
    good = mint_device_cookie(key)
    assert _presented_device_key(_request(f"{name}={good}"), key) is not None

    version, nonce, issued_at, mac = good.split(".")
    forged = f"{version}.{nonce}.{issued_at}.{'0' * len(mac)}"
    stale_at = int(time.time()) - 181 * 24 * 3600
    expired = f"v1.{nonce}.{stale_at}.{_device_mac(key, nonce, stale_at)}"
    other_account = mint_device_cookie(login_account_key("bob"))
    for value in (forged, expired, other_account, "v1.x", "", "v2" + good[2:]):
        assert _presented_device_key(_request(f"{name}={value}"), key) is None

    token = current_tenant_var.set(str(uuid.uuid4()))
    try:
        tenant_key = login_account_key("alice")
        assert tenant_key != key
        assert (
            _presented_device_key(
                _request(f"{device_cookie_name(tenant_key)}={good}"), tenant_key
            )
            is None
        )
    finally:
        current_tenant_var.reset(token)


def test_any_valid_occurrence_of_a_duplicated_device_cookie_counts():
    key = login_account_key("alice")
    name = device_cookie_name(key)
    good = mint_device_cookie(key)
    request = _request(f"{name}=v1.planted.1.bad; {name}={good}")
    assert _presented_device_key(request, key) is not None


async def test_a_device_cookie_is_not_a_bearer_token(client: AsyncClient):
    username = await _new_user(client)
    device = await _remembered_device(client, username)
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {device}"})
    assert resp.status_code == 401


async def _mint_trust_link(username: str) -> str:
    import app.core.db as db_module

    async with db_module.async_session() as db:
        token = await create_trust_token(db, username)
        await db.commit()
    return token


async def test_a_trust_link_remembers_the_browser_once(client: AsyncClient):
    username = await _new_user(client)
    await _fail(client, username, LOGIN_FAILURE_LIMIT)
    token = await _mint_trust_link(username)

    resp = await client.get(f"/auth/device-trust?token={token}")
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/login")
    device = _set_cookie(resp, device_cookie_name(login_account_key(username)))
    assert (
        await _login(client, username, PASSWORD, device=device["value"])
    ).status_code == 200

    again = await client.get(f"/auth/device-trust?token={token}")
    assert again.status_code == 404
    assert again.headers.get_list("set-cookie") == []


async def test_an_expired_trust_link_does_nothing(client: AsyncClient, test_db_session):
    username = await _new_user(client)
    token = await _mint_trust_link(username)
    await test_db_session.execute(
        update(LoginTrustToken).values(
            expires_at=datetime.now(tz=UTC) - timedelta(seconds=1)
        )
    )
    await test_db_session.commit()

    resp = await client.get(f"/auth/device-trust?token={token}")
    assert resp.status_code == 404
    assert resp.headers.get_list("set-cookie") == []


async def test_the_trust_script_prints_a_working_link(client: AsyncClient, capsys):
    from scripts.trust_login_device import _run

    username = await _new_user(client)
    assert await _run(username.upper(), None) == 0
    link = capsys.readouterr().out.strip()
    assert "/auth/device-trust?token=" in link
    resp = await client.get("/auth/device-trust?token=" + link.rsplit("=", 1)[1])
    assert resp.status_code == 303

    assert await _run(f"nobody_{uuid.uuid4().hex[:8]}", None) == 1


async def test_ledger_rows_hold_no_username(client: AsyncClient, test_db_session):
    username = await _new_user(client)
    await _fail(client, username, 2)
    rows = (await test_db_session.execute(select(LoginAttempt))).scalars().all()
    assert rows
    for row in rows:
        assert username not in (row.account_key, row.device_key)
    assert set(LoginAttempt.__table__.c.keys()) == {
        "id",
        "account_key",
        "device_key",
        "tripped",
        "attempted_at",
    }


@pytest.fixture(autouse=True)
def _clear_tenant():
    token = current_tenant_var.set(None)
    yield
    current_tenant_var.reset(token)
