"""Tests for branding settings API endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_get_branding_default(client: AsyncClient):
    """GET /api/settings/branding/ returns show_badge=true by default (no auth)."""
    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"show_badge": True}


@pytest.mark.anyio
async def test_put_branding_returns_404_community(
    client: AsyncClient, admin_auth_header: dict
):
    """PUT /api/settings/branding/ returns 405 in community mode (no PUT route)."""
    resp = await client.put(
        "/api/settings/branding/",
        json={"show_badge": False},
        headers=admin_auth_header,
    )
    assert resp.status_code == 405


@pytest.mark.anyio
async def test_put_branding_invalid_body(client: AsyncClient, admin_auth_header: dict):
    """PUT /api/settings/branding/ with invalid body returns 405.

    Note: In community mode, no PUT route exists (enterprise only).
    """
    resp = await client.put(
        "/api/settings/branding/",
        json={"wrong_key": "value"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 405


@pytest.mark.anyio
async def test_get_branding_after_config_override(client: AsyncClient):
    """GET /api/settings/branding/ returns correct value after PersistentConfig.set()."""
    from app.core.dependencies import get_db
    from app.main import app
    from app.core.persistent_config import BRANDING_SHOW_BADGE

    # Override via PersistentConfig directly (bypasses enterprise gate)
    get_db_override = app.dependency_overrides.get(get_db)
    assert get_db_override is not None

    async for db in get_db_override():
        await BRANDING_SHOW_BADGE.set(db, False)

    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"show_badge": False}

    # Restore default
    async for db in get_db_override():
        await BRANDING_SHOW_BADGE.set(db, True)
