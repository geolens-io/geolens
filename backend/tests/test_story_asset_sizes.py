"""A story image's card and link-preview sizes: made at upload, served under
the original's read rules, and gone with it."""

from __future__ import annotations

from io import BytesIO

import pytest
from httpx import AsyncClient
from PIL import Image

from app.modules.catalog.stories.assets import variant_key
from app.modules.catalog.stories.images import CARD_WIDTH, SOCIAL_SIZE
from tests.factories import create_user
from tests.test_stories import _story
from tests.test_story_assets import _encode, _image, _keys, _object_exists, _uploaded

pytestmark = pytest.mark.anyio

_SIZES = ("card", "social")


@pytest.fixture
async def people(client: AsyncClient, admin_auth_header: dict) -> dict:
    owner, _ = await create_user(client, admin_auth_header, "editor")
    other, _ = await create_user(client, admin_auth_header, "editor")
    return {"owner": owner, "other": other, "admin": admin_auth_header}


def _wide_png() -> bytes:
    image = Image.new("RGBA", (1600, 400), (20, 120, 200, 0))
    image.paste((200, 60, 20, 255), (0, 0, 800, 400))
    return _encode(image, "PNG")


async def _sized(client, headers, story_id, asset_id, variant):
    return await client.get(
        f"/stories/{story_id}/assets/{asset_id}",
        params={"variant": variant},
        headers=headers or {},
    )


async def test_an_upload_stores_a_card_and_a_link_preview(client: AsyncClient, people):
    owner = people["owner"]
    story = await _story(client, owner)
    asset = (await _uploaded(client, owner, story["id"], _wide_png()))["id"]

    card = await _sized(client, owner, story["id"], asset, "card")
    social = await _sized(client, owner, story["id"], asset, "social")

    assert card.status_code == 200, card.text
    assert card.headers["content-type"] == "image/webp"
    assert card.headers["etag"] == f'"{asset}-card"'
    assert Image.open(BytesIO(card.content)).size == (CARD_WIDTH, 160)
    assert social.headers["content-type"] == "image/jpeg"
    with Image.open(BytesIO(social.content)) as preview:
        assert (preview.format, preview.size, preview.mode) == (
            "JPEG",
            SOCIAL_SIZE,
            "RGB",
        )


async def test_a_size_is_withheld_like_the_original(client: AsyncClient, people):
    owner = people["owner"]
    story = await _story(client, owner)
    asset = (await _uploaded(client, owner, story["id"]))["id"]

    for headers in (people["other"], None):
        for variant in _SIZES:
            resp = await _sized(client, headers, story["id"], asset, variant)
            assert resp.status_code == 404, (variant, resp.text)


async def test_an_image_stored_without_its_sizes_answers_with_the_original(
    client: AsyncClient, people, test_db_session
):
    from app.platform.storage.provider import get_storage

    owner = people["owner"]
    story = await _story(client, owner)
    asset = (await _uploaded(client, owner, story["id"]))["id"]
    key = (await _keys(test_db_session, story["id"]))[asset]
    for variant in _SIZES:
        await get_storage().delete(variant_key(key, variant))

    card = await _sized(client, owner, story["id"], asset, "card")

    assert card.status_code == 200
    assert card.headers["content-type"] == "image/webp"
    assert card.headers["etag"] == f'"{asset}"'
    assert card.content == (await _image(client, owner, story["id"], asset)).content


async def test_a_size_cached_by_its_etag_is_confirmed(client: AsyncClient, people):
    owner = people["owner"]
    story = await _story(client, owner)
    asset = (await _uploaded(client, owner, story["id"]))["id"]

    resp = await client.get(
        f"/stories/{story['id']}/assets/{asset}",
        params={"variant": "card"},
        headers={**owner, "If-None-Match": f'"{asset}-card"'},
    )

    assert resp.status_code == 304


async def test_the_sizes_go_with_the_story_and_follow_its_copies(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    story = await _story(client, owner)
    asset = (await _uploaded(client, owner, story["id"]))["id"]
    await client.patch(
        f"/stories/{story['id']}", json={"cover_asset_id": asset}, headers=owner
    )
    key = (await _keys(test_db_session, story["id"]))[asset]
    sizes = [variant_key(key, variant) for variant in _SIZES]

    copied = await client.post(f"/stories/{story['id']}/duplicate", headers=owner)
    assert copied.status_code == 201, copied.text
    copy_key = next(iter((await _keys(test_db_session, copied.json()["id"])).values()))
    for variant in _SIZES:
        assert await _object_exists(variant_key(copy_key, variant))

    deleted = await client.delete(f"/stories/{story['id']}", headers=owner)
    assert deleted.status_code == 204, deleted.text
    for size in sizes:
        assert not await _object_exists(size)
