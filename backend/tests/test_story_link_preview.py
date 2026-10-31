"""Crawler HTML for story pages: title and summary only for public published stories."""

import uuid

import pytest
from httpx import AsyncClient

from tests.test_map_link_preview_3018 import (
    APP_URL,
    _create_map,
    _meta,
    _upload_og_image,
    public_app_url,  # noqa: F401 - pytest fixture
)
from tests.test_stories import _chapter, _publish, _saved, _story

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("public_app_url")]


async def _published_story(
    client: AsyncClient,
    headers: dict,
    *,
    title: str = "Preview story",
    summary: str | None = "A story for previews",
    chapters: list[dict] | None = None,
    visibility: str = "public",
    publish: bool = True,
) -> str:
    story = await _story(client, headers, title=title, summary=summary)
    story = await _saved(client, headers, story, chapters or [_chapter()])
    if visibility != "private":
        patched = await client.patch(
            f"/stories/{story['id']}", json={"visibility": visibility}, headers=headers
        )
        assert patched.status_code == 200, patched.text
    if publish:
        published = await _publish(client, headers, story["id"])
        assert published.status_code == 200, published.text
    return story["id"]


async def test_public_story_gets_its_own_escaped_tags_and_scene_image(
    client: AsyncClient, admin_auth_header: dict
) -> None:
    title = 'Rivers <script>alert("x")</script> & "mills"'
    first_map = await _create_map(client, admin_auth_header, visibility="public")
    await _upload_og_image(client, admin_auth_header, first_map)
    second_map = await _create_map(client, admin_auth_header, visibility="public")
    story_id = await _published_story(
        client,
        admin_auth_header,
        title=title,
        summary="Line one\n\n  line two " + "long " * 100,
        chapters=[_chapter(), _chapter(first_map), _chapter(second_map)],
    )

    resp = await client.get(f"/stories/{story_id}/link-preview")

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.headers["cache-control"] == "no-store"
    body = resp.text
    assert "<script>" not in body
    assert '"mills"' not in body
    assert _meta(body, "property", "og:title") == title
    assert _meta(body, "name", "twitter:title") == title
    assert _meta(body, "property", "og:url") == f"{APP_URL}/stories/{story_id}"
    og_image = _meta(body, "property", "og:image")
    assert og_image == f"{APP_URL}/api/maps/{first_map}/og-image/"
    assert _meta(body, "name", "twitter:image") == og_image
    description = _meta(body, "property", "og:description")
    assert description.startswith("Line one line two long")
    assert len(description) <= 200


async def test_story_card_skips_scene_maps_no_longer_public(
    client: AsyncClient, admin_auth_header: dict
) -> None:
    narrowed = await _create_map(client, admin_auth_header, visibility="public")
    await _upload_og_image(client, admin_auth_header, narrowed)
    still_public = await _create_map(client, admin_auth_header, visibility="public")
    await _upload_og_image(client, admin_auth_header, still_public)
    story_id = await _published_story(
        client,
        admin_auth_header,
        summary=None,
        chapters=[_chapter(narrowed), _chapter(still_public)],
    )

    async def og_image() -> str:
        # nginx forwards the id with whatever casing the crawler asked for.
        resp = await client.get(f"/stories/{story_id.upper()}/link-preview")
        assert resp.status_code == 200, resp.text
        assert narrowed not in resp.text
        assert _meta(resp.text, "property", "og:url") == f"{APP_URL}/stories/{story_id}"
        assert _meta(resp.text, "property", "og:description")
        return _meta(resp.text, "property", "og:image")

    for map_id in (narrowed, still_public):
        resp = await client.put(
            f"/maps/{map_id}",
            json={"visibility": "internal"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        if map_id == narrowed:
            assert await og_image() == f"{APP_URL}/api/maps/{still_public}/og-image/"
    assert await og_image() == f"{APP_URL}/og-image.png"


async def test_public_story_without_scenes_uses_the_site_image(
    client: AsyncClient, admin_auth_header: dict
) -> None:
    story_id = await _published_story(client, admin_auth_header)

    resp = await client.get(f"/stories/{story_id}/link-preview")

    assert resp.status_code == 200, resp.text
    assert _meta(resp.text, "property", "og:image") == f"{APP_URL}/og-image.png"


@pytest.mark.parametrize(
    ("visibility", "publish"),
    [("private", True), ("internal", True), ("public", False)],
    ids=["private", "internal", "public-draft-only"],
)
async def test_story_anyone_cannot_read_answers_like_a_missing_one(
    client: AsyncClient,
    admin_auth_header: dict,
    visibility: str,
    publish: bool,
) -> None:
    title = f"Hidden {visibility} story {uuid.uuid4().hex[:6]}"
    story_id = await _published_story(
        client,
        admin_auth_header,
        title=title,
        summary="Secret summary",
        visibility=visibility,
        publish=publish,
    )

    missing = await client.get(f"/stories/{uuid.uuid4()}/link-preview")
    anonymous = await client.get(f"/stories/{story_id}/link-preview")
    # The owner's own credentials must not unlock a crawler's view.
    with_owner_credentials = await client.get(
        f"/stories/{story_id}/link-preview", headers=admin_auth_header
    )

    assert missing.status_code == 404
    for resp in (anonymous, with_owner_credentials):
        assert resp.status_code == 404
        assert resp.content == missing.content
        assert title not in resp.text
        assert "Secret summary" not in resp.text
        assert story_id not in resp.text


async def test_story_preview_never_uses_the_request_host(
    client: AsyncClient, admin_auth_header: dict, request: pytest.FixtureRequest
) -> None:
    story_id = await _published_story(client, admin_auth_header)
    request.getfixturevalue("public_app_url")(None)

    resp = await client.get(
        f"/stories/{story_id}/link-preview",
        headers={"Host": "attacker.example", "X-Forwarded-Host": "attacker.example"},
    )

    assert resp.status_code == 404
    assert "attacker.example" not in resp.text


async def _story_with_cover(client: AsyncClient, headers: dict) -> tuple[str, str]:
    from tests.test_story_assets import _png

    scene_map = await _create_map(client, headers, visibility="public")
    await _upload_og_image(client, headers, scene_map)
    story_id = await _published_story(client, headers, chapters=[_chapter(scene_map)])
    uploaded = await client.post(
        f"/stories/{story_id}/assets",
        files={"file": ("cover.png", _png(), "image/png")},
        headers=headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    cover = uploaded.json()["id"]
    patched = await client.patch(
        f"/stories/{story_id}", json={"cover_asset_id": cover}, headers=headers
    )
    assert patched.status_code == 200, patched.text
    return story_id, cover


async def test_a_story_cover_is_its_card_image_as_jpeg(
    client: AsyncClient, admin_auth_header: dict
) -> None:
    story_id, cover = await _story_with_cover(client, admin_auth_header)

    resp = await client.get(f"/stories/{story_id}/link-preview")

    assert resp.status_code == 200, resp.text
    image = _meta(resp.text, "property", "og:image")
    assert image == f"{APP_URL}/api/stories/{story_id}/assets/{cover}?variant=social"
    served = await client.get(
        f"/stories/{story_id}/assets/{cover}", params={"variant": "social"}
    )
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/jpeg"


async def test_a_cover_stored_without_its_jpeg_serves_the_original_there(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    from app.modules.catalog.stories.assets import variant_key
    from app.platform.storage.provider import get_storage
    from tests.test_story_assets import _keys

    story_id, cover = await _story_with_cover(client, admin_auth_header)
    key = (await _keys(test_db_session, story_id))[cover]
    await get_storage().delete(variant_key(key, "social"))

    resp = await client.get(f"/stories/{story_id}/link-preview")
    served = await client.get(
        f"/stories/{story_id}/assets/{cover}", params={"variant": "social"}
    )

    image = _meta(resp.text, "property", "og:image")
    assert image == f"{APP_URL}/api/stories/{story_id}/assets/{cover}?variant=social"
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"
    assert served.content == await get_storage().get(key)
