"""Tests for branding settings API endpoints."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_get_branding_default(client: AsyncClient):
    """GET /api/settings/branding/ returns show_badge=true and no privacy_url by default (no auth)."""
    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"show_badge": True, "privacy_url": None}


@pytest.mark.anyio
async def test_get_branding_consults_extension(client: AsyncClient):
    """The route invokes BrandingExtension.get_branding_defaults() each call."""
    from app.platform.extensions.defaults import DefaultBrandingExtension

    with patch.object(
        DefaultBrandingExtension,
        "get_branding_defaults",
        return_value={"show_badge": True},
    ) as spy:
        resp = await client.get("/api/settings/branding/")
        assert resp.status_code == 200
        spy.assert_called()


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
async def test_put_branding_key_returns_404_in_community(
    client: AsyncClient, admin_auth_header: dict
):
    """PUT /api/settings/ for an enterprise-only branding key returns 404, not 403.

    404 (with no detail body) prevents trivial enumeration of paid keys —
    consistent with the require_enterprise() guard contract.
    """
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"branding.show_badge": False}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404
    body = resp.json()
    detail = str(body.get("detail", "")).lower()
    for word in ("enterprise", "upgrade", "feature"):
        assert word not in detail, f"Gate response leaked '{word}'"


@pytest.mark.anyio
async def test_reset_branding_key_returns_404_in_community(
    client: AsyncClient, admin_auth_header: dict
):
    """POST /api/settings/reset/ for an enterprise-only branding key returns 404."""
    resp = await client.post(
        "/api/settings/reset/",
        json={"keys": ["branding.show_badge"]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_branding_after_config_override(client: AsyncClient):
    """GET /api/settings/branding/ returns correct value after PersistentConfig.set()."""
    from app.core.dependencies import get_db
    from app.api.main import app
    from app.core.persistent_config import BRANDING_SHOW_BADGE

    # Override via PersistentConfig directly (bypasses enterprise gate)
    get_db_override = app.dependency_overrides.get(get_db)
    assert get_db_override is not None

    async for db in get_db_override():
        await BRANDING_SHOW_BADGE.set(db, False)

    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"show_badge": False, "privacy_url": None}

    # Restore default
    async for db in get_db_override():
        await BRANDING_SHOW_BADGE.set(db, True)


@pytest.mark.anyio
async def test_get_branding_privacy_url_unset_by_default(
    client: AsyncClient, admin_auth_header: dict
):
    """PRIV-1: no privacy_url is configured until an admin sets one.

    GET /api/settings/branding/ returns null (community and self-hosted
    instances never link to another operator's privacy page by default), and
    PUT /api/settings/ with a configured URL makes it appear.
    """
    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    assert resp.json()["privacy_url"] is None

    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": "https://operator.example.com/privacy"}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    assert resp.json()["privacy_url"] == "https://operator.example.com/privacy"

    # Clearing it back to empty restores the "no link shown" default.
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": ""}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    assert resp.json()["privacy_url"] is None


@pytest.mark.anyio
async def test_put_privacy_url_rejects_non_url(
    client: AsyncClient, admin_auth_header: dict
):
    """PUT /api/settings/ rejects a privacy_url value that is not an absolute http(s) URL."""
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": "not-a-url"}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422
