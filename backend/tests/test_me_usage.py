"""Integration tests for GET /auth/me/usage/ — the per-user quota self-service endpoint.

The endpoint is a thin wrapper over ``get_user_quota_usage`` (already unit-covered);
these tests pin the route wiring: auth gate, response shape, user-scoping, and the
0=unlimited cap defaults.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_unauthenticated_returns_401(client: AsyncClient):
    resp = await client.get("/auth/me/usage/")
    assert resp.status_code == 401


async def test_authenticated_returns_usage_shape(
    client: AsyncClient, viewer_auth_header: dict
):
    """Any authenticated (non-admin) user gets a complete UserQuotaUsage payload."""
    resp = await client.get("/auth/me/usage/", headers=viewer_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {
        "bytes_used",
        "dataset_count",
        "storage_cap",
        "count_cap",
    }
    assert isinstance(data["bytes_used"], int) and data["bytes_used"] >= 0
    assert isinstance(data["dataset_count"], int) and data["dataset_count"] >= 0


async def test_fresh_user_has_zero_usage(client: AsyncClient, viewer_auth_header: dict):
    """A freshly created user owns no datasets → 0 bytes / 0 count.

    Teeth: exercises the ``COALESCE(SUM(...), 0)`` no-rows path — without the
    COALESCE the aggregate is NULL and ``int(None)`` raises (500). The result also
    reflects the per-user ``WHERE r.created_by = :user_id`` scope, though that half
    only fails loudly if another user's data happens to coexist on the shared DB.
    """
    resp = await client.get("/auth/me/usage/", headers=viewer_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["bytes_used"] == 0
    assert data["dataset_count"] == 0


async def test_default_caps_are_zero_unlimited(
    client: AsyncClient, viewer_auth_header: dict
):
    """With no quota configured (env_default=0), both caps report 0 = unlimited."""
    resp = await client.get("/auth/me/usage/", headers=viewer_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["storage_cap"] == 0
    assert data["count_cap"] == 0
