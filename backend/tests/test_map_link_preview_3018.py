"""Crawler HTML for map pages: per-map tags only for maps anyone may read."""

import base64
import html
import re
import uuid
from io import BytesIO

import pytest
from httpx import AsyncClient
from PIL import Image

from app.core import public_urls
from app.core.config import settings

APP_URL = "https://maps.example.org"


@pytest.fixture
def public_app_url(monkeypatch):
    """Configure PUBLIC_APP_URL with persisted overrides out of the way.

    A stored ``public_app_url`` row would outrank ``settings``; see the fixture
    of the same name in test_embed_domain_lock_shipped_defaults_1548.py.
    """

    async def _no_persisted_overrides(db):
        return {}

    monkeypatch.setattr(
        public_urls, "_load_public_url_overrides", _no_persisted_overrides
    )

    def _set(value: str | None) -> None:
        monkeypatch.setattr(settings, "public_app_url", value)
        monkeypatch.setattr(settings, "public_api_url", None)
        monkeypatch.setattr(settings, "public_base_url", None)
        public_urls.invalidate_public_url_cache()

    _set(APP_URL)
    yield _set
    public_urls.invalidate_public_url_cache()


async def _create_map(
    client: AsyncClient,
    headers: dict,
    *,
    visibility: str,
    name: str = "Preview map",
    description: str | None = "A map for previews",
) -> str:
    resp = await client.post(
        "/maps/", json={"name": name, "description": description}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    map_id = resp.json()["id"]
    if visibility != "private":
        resp = await client.put(
            f"/maps/{map_id}", json={"visibility": visibility}, headers=headers
        )
        assert resp.status_code == 200, resp.text
    return map_id


async def _upload_og_image(client: AsyncClient, headers: dict, map_id: str) -> None:
    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(10, 20, 30)).save(buf, format="JPEG")
    data_uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    resp = await client.put(
        f"/maps/{map_id}/og-image/", json={"data_uri": data_uri}, headers=headers
    )
    assert resp.status_code == 204, resp.text


def _meta(body: str, attr: str, key: str) -> str:
    match = re.search(rf'<meta {attr}="{re.escape(key)}" content="([^"]*)">', body)
    assert match, f"{key} missing from:\n{body}"
    return html.unescape(match.group(1))


async def test_public_map_gets_its_own_escaped_absolute_tags(
    client: AsyncClient, admin_auth_header: dict, public_app_url
) -> None:
    name = 'Parks <script>alert("x")</script> & trails'
    description = "Line one\n\n  line two " + "long " * 100
    map_id = await _create_map(
        client,
        admin_auth_header,
        visibility="public",
        name=name,
        description=description,
    )
    await _upload_og_image(client, admin_auth_header, map_id)

    resp = await client.get(f"/maps/{map_id}/link-preview")

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.headers["cache-control"] == "no-store"
    body = resp.text
    assert "<script>" not in body
    assert _meta(body, "property", "og:title") == name
    assert _meta(body, "name", "twitter:title") == name
    assert _meta(body, "property", "og:url") == f"{APP_URL}/maps/{map_id}"
    og_image = _meta(body, "property", "og:image")
    assert og_image == f"{APP_URL}/api/maps/{map_id}/og-image/"
    assert _meta(body, "name", "twitter:image") == og_image
    preview_description = _meta(body, "property", "og:description")
    assert preview_description.startswith("Line one line two long")
    assert len(preview_description) <= 200
    assert 'http-equiv="refresh"' not in body


async def test_public_map_without_images_uses_the_absolute_site_image(
    client: AsyncClient, admin_auth_header: dict, public_app_url
) -> None:
    map_id = await _create_map(
        client, admin_auth_header, visibility="public", description=None
    )

    resp = await client.get(f"/maps/{map_id}/link-preview")

    assert resp.status_code == 200, resp.text
    assert _meta(resp.text, "property", "og:image") == f"{APP_URL}/og-image.png"
    assert _meta(resp.text, "property", "og:description")


@pytest.mark.parametrize("visibility", ["private", "internal"])
async def test_non_public_map_answers_like_a_missing_one(
    client: AsyncClient, admin_auth_header: dict, public_app_url, visibility: str
) -> None:
    name = f"Hidden {visibility} map {uuid.uuid4().hex[:6]}"
    map_id = await _create_map(
        client, admin_auth_header, visibility=visibility, name=name
    )
    await _upload_og_image(client, admin_auth_header, map_id)

    missing = await client.get(f"/maps/{uuid.uuid4()}/link-preview")
    anonymous = await client.get(f"/maps/{map_id}/link-preview")
    # The owner's own credentials must not unlock a crawler's view.
    with_owner_credentials = await client.get(
        f"/maps/{map_id}/link-preview", headers=admin_auth_header
    )

    assert missing.status_code == 404
    for resp in (anonymous, with_owner_credentials):
        assert resp.status_code == 404
        assert resp.content == missing.content
        assert name not in resp.text
        assert map_id not in resp.text


async def test_unconfigured_public_url_never_uses_the_request_host(
    client: AsyncClient, admin_auth_header: dict, public_app_url
) -> None:
    map_id = await _create_map(client, admin_auth_header, visibility="public")
    public_app_url(None)

    resp = await client.get(
        f"/maps/{map_id}/link-preview",
        headers={"Host": "attacker.example", "X-Forwarded-Host": "attacker.example"},
    )

    assert resp.status_code == 404
    assert "attacker.example" not in resp.text
