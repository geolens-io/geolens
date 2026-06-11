"""Regression tests for SEC-007: /maps/{id}/visibility-check/ authorization.

The endpoint loaded the map and checked existence but never called
`_check_map_read_access`, so any editor (the `edit_metadata` permission) could
enumerate the non-public dataset names of ANY map by UUID — including PRIVATE
maps owned by other users they cannot read. The fix gates on read access to the
map before disclosing its non-public datasets.

The ATTACK test fails on main (a non-owner editor gets 200); the owner/admin
GUARD tests pass before and after.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import pytest
from httpx import AsyncClient

from .conftest import _create_test_user


async def _create_private_map(
    client: AsyncClient, headers: dict, name: str = "Owner private map"
) -> str:
    resp = await client.post("/maps/", json={"name": name}, headers=headers)
    assert resp.status_code == 201, f"create map failed: {resp.text}"
    body = resp.json()
    assert body["visibility"] == "private"
    return body["id"]


@pytest.mark.anyio
async def test_visibility_check_rejects_non_owner_editor(
    client: AsyncClient, admin_auth_header: dict
):
    """ATTACK: a non-owner editor cannot read another user's private map's
    visibility-check. Fails on main (200)."""
    owner_headers, _ = await _create_test_user(client, admin_auth_header, "editor")
    attacker_headers, _ = await _create_test_user(client, admin_auth_header, "editor")
    map_id = await _create_private_map(client, owner_headers)

    resp = await client.get(
        f"/maps/{map_id}/visibility-check/", headers=attacker_headers
    )

    assert resp.status_code == 404, (
        f"a non-owner editor read another user's PRIVATE map visibility-check, "
        f"got {resp.status_code}: {resp.text}"
    )


@pytest.mark.anyio
async def test_visibility_check_allows_owner(
    client: AsyncClient, admin_auth_header: dict
):
    """GUARD: the owner reads their OWN map's visibility-check (200)."""
    owner_headers, _ = await _create_test_user(client, admin_auth_header, "editor")
    map_id = await _create_private_map(client, owner_headers)

    resp = await client.get(f"/maps/{map_id}/visibility-check/", headers=owner_headers)

    assert resp.status_code == 200, (
        f"owner blocked from their OWN map visibility-check, got "
        f"{resp.status_code}: {resp.text}"
    )
    assert "has_non_public" in resp.json()


@pytest.mark.anyio
async def test_visibility_check_allows_admin(
    client: AsyncClient, admin_auth_header: dict
):
    """GUARD: admin reads any map's visibility-check (200)."""
    owner_headers, _ = await _create_test_user(client, admin_auth_header, "editor")
    map_id = await _create_private_map(client, owner_headers)

    resp = await client.get(
        f"/maps/{map_id}/visibility-check/", headers=admin_auth_header
    )

    assert resp.status_code == 200
