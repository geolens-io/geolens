"""Disabling an account ends its credentials for good.

Deactivating or suspending a user and later reactivating them must not bring
back a refresh token or API key issued before the account was disabled.

Requirements: the docker database must be running with migrations applied.
"""

import uuid

import pytest
from httpx import AsyncClient


async def _active_user_with_credentials(
    client: AsyncClient, admin_auth_header: dict
) -> tuple[str, str, dict]:
    """Return (user_id, refresh_token, api_key_header)."""
    username = f"disable_{uuid.uuid4().hex[:8]}"
    password = f"Aa1-not-a-real-{uuid.uuid4().hex[:8]}"
    created = await client.post(
        "/admin/users/",
        json={"username": username, "password": password, "role": "viewer"},
        headers=admin_auth_header,
    )
    assert created.status_code == 201, created.text

    login = await client.post(
        "/auth/login", data={"username": username, "password": password}
    )
    assert login.status_code == 200, login.text
    bearer = {"Authorization": f"Bearer {login.json()['access_token']}"}

    minted = await client.post(
        "/auth/api-keys/", json={"name": "before disable"}, headers=bearer
    )
    assert minted.status_code == 201, minted.text
    key_header = {"X-Api-Key": minted.json()["key"]}
    assert (await client.get("/auth/me/", headers=key_header)).status_code == 200
    return created.json()["id"], login.json()["refresh_token"], key_header


async def _deactivate(client: AsyncClient, user_id: str, headers: dict) -> None:
    resp = await client.post(f"/admin/users/{user_id}/deactivate/", headers=headers)
    assert resp.status_code == 200, resp.text


async def _suspend(client: AsyncClient, user_id: str, headers: dict) -> None:
    resp = await client.patch(
        f"/admin/users/{user_id}", json={"status": "suspended"}, headers=headers
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "disable", [_deactivate, _suspend], ids=["deactivate", "suspend"]
)
async def test_reactivation_does_not_revive_old_credentials(
    client: AsyncClient, admin_auth_header: dict, disable
):
    user_id, refresh_token, key_header = await _active_user_with_credentials(
        client, admin_auth_header
    )

    await disable(client, user_id, admin_auth_header)
    reactivated = await client.patch(
        f"/admin/users/{user_id}", json={"status": "active"}, headers=admin_auth_header
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["is_active"] is True

    refreshed = await client.post(
        "/auth/refresh/", json={"refresh_token": refresh_token}
    )
    assert refreshed.status_code == 401, refreshed.text
    assert (await client.get("/auth/me/", headers=key_header)).status_code == 401
