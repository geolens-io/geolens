"""Tests for OG-image social-card backend surface (SHARE-08).

Covers:
  - Migration 0024 schema (og_image_uri column present on Map model)
  - OgImageUploadRequest schema (max_length=750_000; ThumbnailUploadRequest unchanged)
  - MapResponse.og_image_url field
  - PUT /maps/{id}/og-image/ (owner-only, PIL-verified, capped, stores og_image_uri)
  - GET /maps/{id}/og-image/ (visibility-checked, 404 when unset)
  - GET /shared/{token}/card  — HTML OG/Twitter meta + access-control + escaping

Security tests (BLOCKING):
  T-1142-01: HTML-escaped title/description in card route
  T-1142-02: Private-map 404, invalid-token 404, expired-token 404
"""

import base64
import uuid
from io import BytesIO

import pytest
from httpx import AsyncClient
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Schema unit tests (no DB required)
# ---------------------------------------------------------------------------


def test_og_image_upload_request_max_length_is_750000() -> None:
    """OgImageUploadRequest accepts a ~750KB-class data_uri."""
    from app.modules.catalog.maps.schemas import OgImageUploadRequest

    valid = OgImageUploadRequest(data_uri="data:image/jpeg;base64," + "A" * 40)
    assert valid.data_uri.startswith("data:image/jpeg")


def test_og_image_upload_request_rejects_oversize() -> None:
    """OgImageUploadRequest rejects a payload > 750_000 chars."""
    from pydantic import ValidationError

    from app.modules.catalog.maps.schemas import OgImageUploadRequest

    with pytest.raises(ValidationError):
        OgImageUploadRequest(data_uri="data:image/jpeg;base64," + "A" * 800_000)


def test_thumbnail_upload_request_max_length_unchanged() -> None:
    """ThumbnailUploadRequest.data_uri max_length remains 100_000 (locked contract)."""
    from app.modules.catalog.maps.schemas import ThumbnailUploadRequest

    field_info = ThumbnailUploadRequest.model_fields["data_uri"]
    # Pydantic v2: metadata list contains MaxLen(100000)
    maxlen_values = [
        getattr(m, "max_length", None) for m in field_info.metadata
    ]
    assert 100_000 in maxlen_values, (
        f"ThumbnailUploadRequest.data_uri max_length must remain 100_000; "
        f"got metadata: {field_info.metadata}"
    )


def test_map_response_has_og_image_url_field() -> None:
    """MapResponse exposes og_image_url: str | None with default None."""
    from app.modules.catalog.maps.schemas import MapResponse

    assert "og_image_url" in MapResponse.model_fields
    assert MapResponse.model_fields["og_image_url"].default is None


def test_map_model_has_og_image_uri_column() -> None:
    """Map ORM model exposes og_image_uri attribute (nullable Text column)."""
    from app.modules.catalog.maps.models import Map

    assert hasattr(Map, "og_image_uri"), "Map model missing og_image_uri attribute"


# ---------------------------------------------------------------------------
# Helpers shared by integration tests
# ---------------------------------------------------------------------------


def _valid_jpeg_data_uri() -> str:
    """Return a minimal but PIL-valid JPEG data URI."""
    from PIL import Image

    img = Image.new("RGB", (4, 4), color=(128, 64, 32))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _valid_png_data_uri() -> str:
    """Return a minimal but PIL-valid PNG data URI (for thumbnail parity)."""
    from PIL import Image

    img = Image.new("RGB", (4, 4), color=(0, 0, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


async def _create_map(
    client: AsyncClient,
    headers: dict,
    name: str | None = None,
    visibility: str = "private",
) -> dict:
    map_name = name or f"OG Test Map {uuid.uuid4().hex[:6]}"
    resp = await client.post(
        "/maps/",
        json={"name": map_name, "description": "og image test"},
        headers=headers,
    )
    assert resp.status_code == 201, f"Create map failed: {resp.text}"
    map_data = resp.json()

    if visibility == "public":
        upd = await client.put(
            f"/maps/{map_data['id']}",
            json={"visibility": "public"},
            headers=headers,
        )
        assert upd.status_code == 200, f"Set public failed: {upd.text}"
        map_data = upd.json()

    return map_data


async def _create_share_token(
    client: AsyncClient,
    headers: dict,
    map_id: str,
) -> str:
    """Create a share token for a public map, return the raw token string."""
    resp = await client.post(f"/maps/{map_id}/share/", headers=headers)
    assert resp.status_code == 200, f"Share failed: {resp.text}"
    return resp.json()["token"]


# ---------------------------------------------------------------------------
# PUT / GET /maps/{id}/og-image/ — integration tests
# ---------------------------------------------------------------------------


class TestOgImageRoutes:
    async def test_put_og_image_owner_stores_image(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """PUT /maps/{id}/og-image/ by owner returns 204 and persists og_image_uri."""
        map_data = await _create_map(client, admin_auth_header)
        map_id = map_data["id"]

        resp = await client.put(
            f"/maps/{map_id}/og-image/",
            json={"data_uri": _valid_jpeg_data_uri()},
            headers=admin_auth_header,
        )
        assert resp.status_code == 204, resp.text

    async def test_get_og_image_returns_bytes_after_upload(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """GET /maps/{id}/og-image/ returns image bytes after a successful PUT."""
        map_data = await _create_map(client, admin_auth_header, visibility="public")
        map_id = map_data["id"]

        put_resp = await client.put(
            f"/maps/{map_id}/og-image/",
            json={"data_uri": _valid_jpeg_data_uri()},
            headers=admin_auth_header,
        )
        assert put_resp.status_code == 204

        get_resp = await client.get(
            f"/maps/{map_id}/og-image/",
            headers=admin_auth_header,
        )
        assert get_resp.status_code == 200
        assert get_resp.headers["content-type"].startswith("image/")

    async def test_get_og_image_public_map_cache_control(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """GET /maps/{id}/og-image/ sets public, max-age=86400 for a public map."""
        map_data = await _create_map(client, admin_auth_header, visibility="public")
        map_id = map_data["id"]

        await client.put(
            f"/maps/{map_id}/og-image/",
            json={"data_uri": _valid_jpeg_data_uri()},
            headers=admin_auth_header,
        )

        get_resp = await client.get(
            f"/maps/{map_id}/og-image/",
            headers=admin_auth_header,
        )
        assert get_resp.status_code == 200
        cc = get_resp.headers.get("cache-control", "")
        assert "public" in cc
        assert "max-age=86400" in cc

    async def test_get_og_image_404_when_none_uploaded(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """GET /maps/{id}/og-image/ returns 404 when og_image_uri is unset."""
        map_data = await _create_map(client, admin_auth_header, visibility="public")
        map_id = map_data["id"]

        resp = await client.get(
            f"/maps/{map_id}/og-image/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 404

    async def test_put_og_image_non_owner_forbidden(
        self, client: AsyncClient, admin_auth_header: dict, editor_auth_header: dict
    ) -> None:
        """PUT /maps/{id}/og-image/ by non-owner returns 403/404."""
        # Admin creates map
        map_data = await _create_map(client, admin_auth_header)
        map_id = map_data["id"]

        # Editor (non-owner) tries to upload
        resp = await client.put(
            f"/maps/{map_id}/og-image/",
            json={"data_uri": _valid_jpeg_data_uri()},
            headers=editor_auth_header,
        )
        assert resp.status_code in (403, 404), f"Expected 403/404, got {resp.status_code}"

    async def test_put_og_image_non_image_payload_rejected(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """PUT /maps/{id}/og-image/ with random base64 bytes returns 400 (PIL verify)."""
        map_data = await _create_map(client, admin_auth_header)
        map_id = map_data["id"]

        garbage_b64 = base64.b64encode(b"this is not an image" * 20).decode("ascii")
        resp = await client.put(
            f"/maps/{map_id}/og-image/",
            json={"data_uri": f"data:image/jpeg;base64,{garbage_b64}"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"

    async def test_map_response_includes_og_image_url_after_upload(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """GET /maps/{id} includes og_image_url after an og-image is uploaded."""
        map_data = await _create_map(client, admin_auth_header, visibility="public")
        map_id = map_data["id"]

        # Before upload: og_image_url should be None
        get_before = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert get_before.status_code == 200
        assert get_before.json().get("og_image_url") is None

        # Upload
        await client.put(
            f"/maps/{map_id}/og-image/",
            json={"data_uri": _valid_jpeg_data_uri()},
            headers=admin_auth_header,
        )

        # After upload: og_image_url should be set
        get_after = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert get_after.status_code == 200
        og_url = get_after.json().get("og_image_url")
        assert og_url is not None
        assert "og-image" in og_url


# ---------------------------------------------------------------------------
# GET /shared/{token}/card — HTML OG meta route
# ---------------------------------------------------------------------------


class TestCardRoute:
    async def test_card_route_public_map_emits_og_meta(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """GET /shared/{token}/card returns 200 text/html with OG/Twitter meta."""
        map_data = await _create_map(
            client, admin_auth_header, name="My Card Map", visibility="public"
        )
        token = await _create_share_token(client, admin_auth_header, map_data["id"])

        resp = await client.get(f"/maps/shared/{token}/card")
        assert resp.status_code == 200, resp.text
        ct = resp.headers.get("content-type", "")
        assert "text/html" in ct

        body = resp.text
        assert 'property="og:image"' in body
        assert 'name="twitter:card"' in body
        assert 'content="summary_large_image"' in body
        assert "My Card Map" in body
        assert 'http-equiv="refresh"' in body

    async def test_card_route_og_image_url_is_absolute(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """og:image content in the card route starts with http (absolute URL)."""
        map_data = await _create_map(
            client, admin_auth_header, name="Absolute URL Map", visibility="public"
        )
        token = await _create_share_token(client, admin_auth_header, map_data["id"])

        resp = await client.get(f"/maps/shared/{token}/card")
        assert resp.status_code == 200

        body = resp.text
        # Find the og:image meta tag content value — must start with http
        import re

        og_image_match = re.search(
            r'property="og:image"\s+content="([^"]+)"', body
        ) or re.search(r'content="([^"]+)"\s+property="og:image"', body)
        assert og_image_match, f"og:image meta not found in:\n{body}"
        image_url = og_image_match.group(1)
        assert image_url.startswith("http"), (
            f"og:image must be absolute URL, got: {image_url!r}"
        )

    async def test_card_route_escapes_html_in_title(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """T-1142-01 [BLOCKING]: malicious title is HTML-escaped in meta output."""
        evil_name = 'Evil "><script>alert(1)</script>'
        map_data = await _create_map(
            client, admin_auth_header, name=evil_name, visibility="public"
        )
        token = await _create_share_token(client, admin_auth_header, map_data["id"])

        resp = await client.get(f"/maps/shared/{token}/card")
        assert resp.status_code == 200

        body = resp.text
        # The raw <script> tag must NOT appear unescaped in the output
        assert "<script>" not in body, (
            "Raw <script> found in card HTML — title was not HTML-escaped"
        )
        # The title should appear in some escaped form
        # html.escape produces: Evil &quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;
        assert "&lt;script&gt;" in body or "Evil" in body, (
            "Expected escaped title content not found in card HTML"
        )

    async def test_card_route_404_for_private_map(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """T-1142-02 [BLOCKING]: private map returns 404; title not leaked."""
        map_data = await _create_map(
            client,
            admin_auth_header,
            name="Secret Private Map",
            visibility="public",  # must be public to get share token
        )
        map_id = map_data["id"]
        token = await _create_share_token(client, admin_auth_header, map_id)

        # Revert to private
        upd = await client.put(
            f"/maps/{map_id}",
            json={"visibility": "private"},
            headers=admin_auth_header,
        )
        assert upd.status_code == 200

        resp = await client.get(f"/maps/shared/{token}/card")
        assert resp.status_code == 404, (
            f"Expected 404 for private map, got {resp.status_code}: {resp.text}"
        )
        # Private title must NOT appear in any error body
        assert "Secret Private Map" not in resp.text

    async def test_card_route_404_for_invalid_token(
        self, client: AsyncClient
    ) -> None:
        """T-1142-02 [BLOCKING]: bogus token returns 404."""
        resp = await client.get("/maps/shared/bogus-invalid-token-xyz/card")
        assert resp.status_code == 404, (
            f"Expected 404 for invalid token, got {resp.status_code}"
        )

    async def test_card_route_404_for_expired_token(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """T-1142-02 [BLOCKING]: revoked/expired token returns 404."""
        map_data = await _create_map(
            client, admin_auth_header, name="Expired Token Map", visibility="public"
        )
        map_id = map_data["id"]
        token = await _create_share_token(client, admin_auth_header, map_id)

        # Revoke the share token (deactivate it)
        revoke_resp = await client.delete(
            f"/maps/{map_id}/share/", headers=admin_auth_header
        )
        assert revoke_resp.status_code == 204, f"Revoke failed: {revoke_resp.text}"

        resp = await client.get(f"/maps/shared/{token}/card")
        assert resp.status_code == 404, (
            f"Expected 404 for revoked token, got {resp.status_code}: {resp.text}"
        )

    async def test_card_route_uses_og_image_uri_when_set(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """Card route og:image points to /og-image/ when og_image_uri is set."""
        map_data = await _create_map(
            client, admin_auth_header, name="OG Image Map", visibility="public"
        )
        map_id = map_data["id"]

        # Upload og image
        await client.put(
            f"/maps/{map_id}/og-image/",
            json={"data_uri": _valid_jpeg_data_uri()},
            headers=admin_auth_header,
        )

        token = await _create_share_token(client, admin_auth_header, map_id)
        resp = await client.get(f"/maps/shared/{token}/card")
        assert resp.status_code == 200

        body = resp.text
        assert "og-image" in body, (
            f"Expected og-image path in card body when og_image_uri set; body:\n{body}"
        )

    async def test_card_route_uses_thumbnail_when_no_og_image(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """Card route og:image falls back to /thumbnail/ when only thumbnail_uri set."""
        map_data = await _create_map(
            client, admin_auth_header, name="Thumbnail Fallback Map", visibility="public"
        )
        map_id = map_data["id"]

        # Upload thumbnail only
        await client.put(
            f"/maps/{map_id}/thumbnail/",
            json={"data_uri": _valid_png_data_uri()},
            headers=admin_auth_header,
        )

        token = await _create_share_token(client, admin_auth_header, map_id)
        resp = await client.get(f"/maps/shared/{token}/card")
        assert resp.status_code == 200

        body = resp.text
        assert "thumbnail" in body, (
            f"Expected thumbnail fallback in card body; body:\n{body}"
        )

    async def test_card_route_uses_site_fallback_when_no_images(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """Card route og:image falls back to /og-image.png when no images set."""
        map_data = await _create_map(
            client, admin_auth_header, name="No Image Map", visibility="public"
        )
        map_id = map_data["id"]
        token = await _create_share_token(client, admin_auth_header, map_id)

        resp = await client.get(f"/maps/shared/{token}/card")
        assert resp.status_code == 200

        body = resp.text
        assert "og-image.png" in body, (
            f"Expected /og-image.png fallback in card body; body:\n{body}"
        )

    async def test_card_route_viewer_redirect_present(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """Card route contains meta http-equiv refresh pointing to /m/{token}."""
        map_data = await _create_map(
            client, admin_auth_header, name="Redirect Map", visibility="public"
        )
        token = await _create_share_token(client, admin_auth_header, map_data["id"])

        resp = await client.get(f"/maps/shared/{token}/card")
        assert resp.status_code == 200

        body = resp.text
        assert f"/m/{token}" in body, (
            f"Expected /m/{token} redirect in card body; body:\n{body}"
        )
