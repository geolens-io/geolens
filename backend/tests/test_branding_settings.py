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


@pytest.mark.parametrize(
    "value",
    [
        "not-a-url",
        "javascript:alert(1)",
        "data:text/html,x",
        "//evil.example.com/p",
        "https://example.com:not-a-port/x",
        "https://:443/x",
    ],
)
@pytest.mark.anyio
async def test_put_privacy_url_rejects_non_url(
    client: AsyncClient, admin_auth_header: dict, value: str
):
    """PUT /api/settings/ rejects a privacy_url that is not a safe absolute http(s) URL.

    Covers the XSS-relevant shapes, not just "not a URL": a javascript:/data:
    URI or a scheme-relative value would otherwise reach the login page as a
    raw <a href>. Also covers a malformed authority a browser cannot resolve
    (a non-numeric port, or a netloc with no real hostname) — urlsplit leaves
    that junk sitting in netloc rather than rejecting it outright, so the
    scheme/netloc check alone would let it through.
    """
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": value}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_put_privacy_url_accepts_query_and_fragment(
    client: AsyncClient, admin_auth_header: dict
):
    """A real operator policy URL (Google Docs, Notion, SharePoint) often
    carries a query string or a fragment; the privacy_url validator must not
    strip or reject either, unlike the public_app_url/public_api_url shape
    rule it deliberately does not share.
    """
    value = "https://docs.google.com/document/d/abc123/edit?usp=sharing#heading=h.xyz"
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": value}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    assert resp.json()["privacy_url"] == value

    # Restore default so this test does not leak state to others.
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": ""}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_get_branding_drops_an_unsafe_stored_privacy_url(client: AsyncClient):
    """PRIV-1 reader-side defense: an unsafe stored value must never reach
    the login page as a raw <a href>, even if it bypassed the admin-write
    validator — a row written before that check existed, or by any other
    path than PUT /api/settings/. Writes through PersistentConfig.set()
    directly, which (like a raw DB row) has no shape opinion on a str value;
    only the read path in router_public.py is under test here.
    """
    from app.core.dependencies import get_db
    from app.api.main import app
    from app.core.persistent_config import PRIVACY_URL

    get_db_override = app.dependency_overrides.get(get_db)
    assert get_db_override is not None

    async for db in get_db_override():
        await PRIVACY_URL.set(db, "javascript:alert(document.cookie)")

    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    assert resp.json()["privacy_url"] is None

    # Restore default
    async for db in get_db_override():
        await PRIVACY_URL.set(db, "")
