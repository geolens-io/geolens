"""The admin's cap on one owner's story images across their stories."""

from __future__ import annotations

import math
import random

import pytest
from sqlalchemy import func, select
from httpx import AsyncClient
from PIL import Image

from app.modules.catalog.stories.assets import object_keys
from app.modules.catalog.stories.models import Story, StoryAsset
from tests.factories import create_user
from tests.test_stories import _chapter, _detail, _saved, _story
from tests.test_story_assets import _encode, _image_block, _keys, _upload, _uploaded

pytestmark = pytest.mark.anyio

_MB = 2**20


def _noise() -> bytes:
    """A PNG whose stored sizes together run past a megabyte, so a whole
    megabyte cap holds one of it and not two."""
    pixels = random.Random(7).randbytes(1400 * 1400 * 3)
    return _encode(Image.frombytes("RGB", (1400, 1400), pixels), "PNG")


async def _set_cap(client: AsyncClient, admin: dict, mb: int) -> None:
    resp = await client.put(
        "/settings/",
        json={"settings": {"max_story_image_mb_per_user": mb}},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text


@pytest.fixture
async def people(client: AsyncClient, admin_auth_header: dict) -> dict:
    owner, _ = await create_user(client, admin_auth_header, "editor")
    other, _ = await create_user(client, admin_auth_header, "editor")
    return {"owner": owner, "other": other, "admin": admin_auth_header}


@pytest.fixture
async def capped(client: AsyncClient, people):
    """One upload stored, and a cap that holds it but not a second."""
    owner = people["owner"]
    first = await _story(client, owner)
    image = _noise()
    size = (await _uploaded(client, owner, first["id"], image))["byte_size"]
    assert size > _MB
    await _set_cap(client, people["admin"], math.ceil(size / _MB))
    try:
        yield {"owner": owner, "first": first, "image": image, "size": size}
    finally:
        await _set_cap(client, people["admin"], 0)


async def test_an_upload_past_the_owners_cap_is_refused_and_stores_nothing(
    client: AsyncClient, capped, test_db_session
):
    from app.platform.storage.provider import get_storage

    owner = capped["owner"]
    second = await _story(client, owner)

    refused = await _upload(client, owner, second["id"], capped["image"])

    assert refused.status_code == 409, refused.text
    assert _detail(refused)["code"] == "story_asset_owner_limit"
    assert await _keys(test_db_session, second["id"]) == {}
    listed = await get_storage().list("stories/assets/")
    assert [k for k in listed if second["id"] in k] == []
    assert len(await _keys(test_db_session, capped["first"]["id"])) == 1


async def test_images_already_over_a_lowered_cap_stay_readable(
    client: AsyncClient,
    capped,
    people,
):
    owner = capped["owner"]
    first = capped["first"]
    await _set_cap(client, people["admin"], 0)
    second = await _story(client, owner)
    extra = await _uploaded(client, owner, second["id"], capped["image"])
    await _set_cap(client, people["admin"], 1)

    resp = await client.get(
        f"/stories/{second['id']}/assets/{extra['id']}", headers=owner
    )

    assert resp.status_code == 200
    refused = await _upload(client, owner, first["id"], capped["image"])
    assert _detail(refused)["code"] == "story_asset_owner_limit"


async def test_another_owners_images_do_not_count(
    client: AsyncClient,
    capped,
    people,
):
    other = await _story(client, people["other"])

    assert (
        await _upload(client, people["other"], other["id"], capped["image"])
    ).status_code == 201


async def test_a_copy_past_the_owners_cap_is_refused_and_leaves_no_objects(
    client: AsyncClient, capped, test_db_session
):
    from app.platform.storage.provider import get_storage

    owner = capped["owner"]
    first = capped["first"]
    image = next(iter(await _keys(test_db_session, first["id"])))
    await _saved(client, owner, first, [_chapter(blocks=[_image_block(image)])])
    before = set(await get_storage().list("stories/assets/"))

    resp = await client.post(f"/stories/{first['id']}/duplicate", headers=owner)

    assert resp.status_code == 409, resp.text
    assert _detail(resp)["code"] == "story_asset_owner_limit"
    # The copies are written before the check, so the refusal removes them.
    assert set(await get_storage().list("stories/assets/")) == before


async def test_an_upload_waits_for_the_owners_lock_and_is_refused_past_its_wait(
    client: AsyncClient, capped, test_db_session
):
    import app.core.db as db_module
    from app.platform.catalog_locks import lock_request_key

    owner = capped["owner"]
    second = await _story(client, owner)
    # Another upload or copy by the owner, between its check and its commit.
    async with db_module.async_session() as holder:
        await lock_request_key(
            holder, scope=f"story-assets-owner:{second['created_by']}"
        )
        refused = await _upload(client, owner, second["id"], _encode(_tiny(), "PNG"))
        await holder.rollback()

    assert refused.status_code == 409, refused.text
    assert await _keys(test_db_session, second["id"]) == {}


def _tiny() -> Image.Image:
    return Image.new("RGB", (8, 6), (20, 120, 200))


async def test_the_card_and_social_sizes_count_toward_the_cap(
    client: AsyncClient, people, test_db_session
):
    import uuid

    from app.platform.storage.provider import get_storage

    owner = people["owner"]
    first = await _story(client, owner)
    # Room for the original WebP but not the two other sizes stored with it.
    test_db_session.add(
        StoryAsset(
            story_id=uuid.UUID(first["id"]),
            storage_key=f"stories/assets/{first['id']}/filler.webp",
            byte_size=_MB - 1000,
            width=1,
            height=1,
        )
    )
    await test_db_session.commit()
    await _set_cap(client, people["admin"], 1)
    try:
        second = await _story(client, owner)
        refused = await _upload(client, owner, second["id"], _encode(_tiny(), "PNG"))
    finally:
        await _set_cap(client, people["admin"], 0)

    assert refused.status_code == 409, refused.text
    assert _detail(refused)["code"] == "story_asset_owner_limit"
    listed = await get_storage().list("stories/assets/")
    assert [k for k in listed if second["id"] in k] == []


async def test_a_duplicate_carries_every_stored_size_into_the_owners_usage(
    client: AsyncClient, people, test_db_session
):
    from app.platform.storage.provider import get_storage
    from app.platform.storage.titiler_url import resolve_current_storage_key

    owner = people["owner"]
    first = await _story(client, owner)
    await _uploaded(client, owner, first["id"], _encode(_tiny(), "PNG"))
    key = next(iter((await _keys(test_db_session, first["id"])).values()))
    image = next(iter(await _keys(test_db_session, first["id"])))
    await _saved(client, owner, first, [_chapter(blocks=[_image_block(image)])])
    storage = get_storage()
    stored = sum(
        [
            await storage.size(resolve_current_storage_key(k))
            for k in object_keys(key).values()
        ]
    )

    resp = await client.post(f"/stories/{first['id']}/duplicate", headers=owner)

    assert resp.status_code in (200, 201), resp.text
    test_db_session.expire_all()
    usage = await test_db_session.scalar(
        select(func.sum(StoryAsset.byte_size))
        .join(Story, Story.id == StoryAsset.story_id)
        .where(Story.created_by == first["created_by"])
    )
    assert usage == 2 * stored
