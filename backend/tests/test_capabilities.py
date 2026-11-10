"""``GET /capabilities``: the discovery document a desktop client reads first."""

from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import get_auth_header

ADMIN_USER = settings.geolens_admin_username
ADMIN_PASS = settings.geolens_admin_password.get_secret_value()

ANONYMOUS_FIELDS = {
    "server",
    "publish_contract",
    "auth",
    "upload",
    "basemaps",
    "flags",
    "status_order",
    "rate_limits",
    "me",
}


@asynccontextmanager
async def _api_key(client: AsyncClient, headers: dict, **body):
    """Mint a key and revoke it afterwards so no active key outlives the test."""
    resp = await client.post(
        "/auth/api-keys/", json={"name": "Capabilities", **body}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    minted = resp.json()
    try:
        yield minted
    finally:
        await client.delete(f"/auth/api-keys/{minted['id']}", headers=headers)


@pytest.mark.anyio
async def test_anonymous_gets_no_upload_or_me(client: AsyncClient):
    resp = await client.get("/capabilities/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == ANONYMOUS_FIELDS
    assert body["upload"] is None
    assert body["me"] is None
    assert body["publish_contract"] == 1
    assert body["server"]["edition"] == "community"
    assert "app_signin" not in body["auth"]
    assert body["status_order"] == ["draft", "ready", "internal", "published"]
    assert body["rate_limits"]["login_per_minute"] >= 1
    assert all({"id", "name"} == set(b) for b in body["basemaps"])


@pytest.mark.anyio
async def test_no_trailing_slash_alias(client: AsyncClient):
    assert (await client.get("/capabilities")).status_code == 200


@pytest.mark.anyio
async def test_session_user_gets_upload_and_me_without_key(client: AsyncClient):
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    body = (await client.get("/capabilities/", headers=headers)).json()
    assert body["me"]["username"] == ADMIN_USER
    assert body["me"]["key"] is None
    assert "upload" in body["me"]["permissions"]
    assert body["upload"]["max_file_size_bytes"] > 0


@pytest.mark.anyio
async def test_upload_extensions_are_what_a_manifest_can_publish(
    client: AsyncClient,
):
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    extensions = (await client.get("/capabilities/", headers=headers)).json()["upload"][
        "allowed_extensions"
    ]
    assert ".geojson" in extensions
    assert ".parquet" in extensions
    assert ".laz" not in extensions
    assert extensions == sorted(extensions)


@pytest.mark.anyio
@pytest.mark.parametrize("scope", ["full", "read_only"])
async def test_api_key_reports_its_scope(client: AsyncClient, scope: str):
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    async with _api_key(client, headers, scope=scope) as minted:
        resp = await client.get("/capabilities/", headers={"X-Api-Key": minted["key"]})
    assert resp.status_code == 200, resp.text
    me = resp.json()["me"]
    assert me["username"] == ADMIN_USER
    assert me["key"] == {"scope": scope, "expires_at": None}
    assert "client_id" not in me["key"]


@pytest.mark.anyio
async def test_api_key_reports_its_expiry(client: AsyncClient):
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    async with _api_key(client, headers, expires_at="2099-01-01T00:00:00Z") as minted:
        me = (
            await client.get("/capabilities/", headers={"X-Api-Key": minted["key"]})
        ).json()["me"]
    assert me["key"]["expires_at"].startswith("2099-01-01T00:00:00")


@pytest.mark.anyio
async def test_unresolvable_credentials_are_refused_not_anonymous(
    client: AsyncClient,
):
    resp = await client.get("/capabilities/", headers={"X-Api-Key": "not-a-real-key"})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_rate_limits_come_from_the_stored_configuration(
    client: AsyncClient, monkeypatch
):
    """The sync cache the limiter reads is empty on a fresh worker."""
    from app.modules.settings import router_capabilities

    async def _global(_db):
        return 17

    async def _login(_db):
        return 3

    monkeypatch.setattr(router_capabilities.GLOBAL_RATE_LIMIT, "get", _global)
    monkeypatch.setattr(router_capabilities.LOGIN_RATE_LIMIT, "get", _login)
    limits = (await client.get("/capabilities/")).json()["rate_limits"]
    assert limits == {"global_per_second": 17, "login_per_minute": 3}
