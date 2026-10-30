"""Story images: what an upload accepts and stores, who reads it, and how
images follow a story through saves, deletes and copies."""

from __future__ import annotations

import struct
import uuid
import zlib
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import func, select, update

from app.api.middleware.body_limit import (
    STORY_ASSET_BODY_LIMIT_BYTES,
    _route_limit,
)
from app.modules.catalog.stories import assets as story_assets
from app.modules.catalog.stories.images import MAX_UPLOAD_BYTES
from app.modules.catalog.stories.models import Story, StoryAsset
from tests.factories import create_user
from tests.test_stories import _chapter, _detail, _publish, _save, _saved, _story

pytestmark = pytest.mark.anyio


@pytest.fixture
async def people(client: AsyncClient, admin_auth_header: dict) -> dict:
    owner, _ = await create_user(client, admin_auth_header, "editor")
    other, _ = await create_user(client, admin_auth_header, "editor")
    return {"owner": owner, "other": other, "admin": admin_auth_header}


def _encode(image: Image.Image, fmt: str, **options) -> bytes:
    out = BytesIO()
    image.save(out, fmt, **options)
    return out.getvalue()


def _png(size=(8, 6)) -> bytes:
    return _encode(Image.new("RGB", size, (20, 120, 200)), "PNG")


async def _upload(client, headers, story_id, data, name="photo.png", kind="image/png"):
    return await client.post(
        f"/stories/{story_id}/assets",
        files={"file": (name, data, kind)},
        headers=headers,
    )


async def _uploaded(client, headers, story_id, data=None) -> dict:
    resp = await _upload(client, headers, story_id, data or _png())
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _image(client, headers, story_id, asset_id):
    return await client.get(
        f"/stories/{story_id}/assets/{asset_id}", headers=headers or {}
    )


def _image_block(asset_id: str, alt: str = "A river") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "type": "image",
        "v": 1,
        "asset_id": asset_id,
        "config": {"alt": alt, "caption": "Looking north"},
    }


async def _draft(client, headers, story_id) -> dict:
    resp = await client.get(f"/stories/{story_id}/draft", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _stored_object(test_db_session, asset_id: str) -> bytes:
    from app.platform.storage.provider import get_storage

    key = await test_db_session.scalar(
        select(StoryAsset.storage_key).where(StoryAsset.id == uuid.UUID(asset_id))
    )
    return await get_storage().get(key)


async def _object_exists(key: str) -> bool:
    from app.platform.storage.provider import get_storage

    return await get_storage().exists(key)


async def _keys(test_db_session, story_id: str) -> dict[str, str]:
    test_db_session.expire_all()
    rows = await test_db_session.execute(
        select(StoryAsset.id, StoryAsset.storage_key).where(
            StoryAsset.story_id == uuid.UUID(story_id)
        )
    )
    return {str(row.id): row.storage_key for row in rows}


async def _age(test_db_session, *asset_ids: str) -> None:
    """Move uploads past the grace period cleanup leaves recent ones in."""
    old = datetime.now(UTC) - story_assets.UNREFERENCED_GRACE - timedelta(hours=1)
    await test_db_session.execute(
        update(StoryAsset)
        .where(StoryAsset.id.in_([uuid.UUID(a) for a in asset_ids]))
        .values(last_used_at=old)
    )
    await test_db_session.commit()


# What an upload accepts and stores ------------------------------------------


async def test_an_upload_is_stored_as_upright_webp_without_metadata(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    story = await _story(client, owner)
    exif = Image.Exif()
    exif[0x0112] = 6  # stored sideways: shown rotated a quarter turn
    exif[0x010F] = "Example Camera"
    exif[0x8825] = {2: (40.0, 42.0, 0.0)}  # GPS latitude
    photo = _encode(
        Image.new("RGB", (40, 20), (200, 30, 30)),
        "JPEG",
        exif=exif.tobytes(),
        icc_profile=b"not a real profile" * 4,
    )
    with Image.open(BytesIO(photo)) as source:
        assert source.getexif() and source.info.get("icc_profile")

    resp = await _upload(client, owner, story["id"], photo, "photo.jpg", "image/jpeg")
    assert resp.status_code == 201, resp.text
    asset = resp.json()
    assert (asset["width"], asset["height"]) == (20, 40)

    stored = await _stored_object(test_db_session, asset["id"])
    assert asset["byte_size"] == len(stored)
    with Image.open(BytesIO(stored)) as image:
        assert image.format == "WEBP"
        assert image.size == (20, 40)
        assert not image.getexif()
        assert not {"exif", "xmp", "icc_profile"} & set(image.info)

    served = await _image(client, owner, story["id"], asset["id"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"
    assert served.content == stored


async def test_large_images_are_scaled_to_the_output_cap(client: AsyncClient, people):
    owner = people["owner"]
    story = await _story(client, owner)
    wide = await _uploaded(client, owner, story["id"], _png((3000, 1500)))
    assert (wide["width"], wide["height"]) == (2400, 1200)

    # 60 megapixels: past the cap for other formats, but a baseline JPEG
    # decodes at a reduced scale.
    big = _encode(Image.new("L", (12000, 5000), 128), "JPEG")
    resp = await _upload(client, owner, story["id"], big, "big.jpg", "image/jpeg")
    assert resp.status_code == 201, resp.text
    assert (resp.json()["width"], resp.json()["height"]) == (2400, 1000)

    # A progressive JPEG keeps every coefficient at full size, so it gets the
    # pixel cap.
    progressive = _encode(Image.new("L", (12000, 5000), 128), "JPEG", progressive=True)
    resp = await _upload(client, owner, story["id"], progressive, "p.jpg", "image/jpeg")
    assert resp.status_code == 413, resp.text
    assert _detail(resp)["code"] == "story_image_too_large"


@pytest.mark.parametrize(
    ("data", "name", "kind"),
    [
        pytest.param(
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            "photo.png",
            "image/png",
            id="svg named as png",
        ),
        pytest.param(
            _encode(Image.new("RGB", (4, 4)), "GIF"), "a.gif", "image/gif", id="gif"
        ),
        pytest.param(
            _encode(Image.new("RGB", (4, 4)), "BMP"), "a.png", "image/png", id="bmp"
        ),
        pytest.param(b"plain text", "a.webp", "image/webp", id="text"),
    ],
)
async def test_only_png_jpeg_and_webp_bytes_are_accepted(
    client: AsyncClient, people, data, name, kind
):
    story = await _story(client, people["owner"])
    resp = await _upload(client, people["owner"], story["id"], data, name, kind)
    assert resp.status_code == 415, resp.text
    assert _detail(resp)["code"] == "story_image_unsupported"


async def test_every_accepted_format_is_stored_as_webp(client: AsyncClient, people):
    owner = people["owner"]
    story = await _story(client, owner)
    source = Image.new("RGBA", (10, 10), (10, 20, 30, 128))
    for fmt in ("PNG", "WEBP"):
        asset = await _uploaded(client, owner, story["id"], _encode(source, fmt))
        served = await _image(client, owner, story["id"], asset["id"])
        with Image.open(BytesIO(served.content)) as image:
            assert (image.format, image.mode) == ("WEBP", "RGBA")


async def test_a_truncated_image_is_refused(client: AsyncClient, people):
    story = await _story(client, people["owner"])
    truncated = _png((200, 200))[:-40]
    resp = await _upload(client, people["owner"], story["id"], truncated)
    assert resp.status_code == 400, resp.text
    assert _detail(resp)["code"] == "story_image_unreadable"


def _png_claiming(width: int, height: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\0" * 64))
        + chunk(b"IEND", b"")
    )


def _webp_claiming(width: int, height: int) -> bytes:
    body = b"VP8X" + struct.pack("<I", 10) + b"\0\0\0\0"
    body += (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


def _jpeg_claiming(width: int, height: int) -> bytes:
    data = bytearray(_encode(Image.new("RGB", (16, 16)), "JPEG"))
    sof = data.index(b"\xff\xc0")
    data[sof + 5 : sof + 9] = struct.pack(">HH", height, width)
    return bytes(data)


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        pytest.param(_png_claiming(10_000, 10_000), "image/png", id="png 100 MP"),
        pytest.param(_webp_claiming(16_000, 16_000), "image/webp", id="webp 256 MP"),
        pytest.param(_jpeg_claiming(16_000, 10), "image/jpeg", id="jpeg 16000 wide"),
    ],
)
async def test_a_small_file_claiming_a_huge_canvas_is_refused_before_decoding(
    client: AsyncClient, people, monkeypatch, data, kind
):
    from PIL import ImageFile

    def no_decode(self):
        raise AssertionError("decoded an image that was over the caps")

    monkeypatch.setattr(ImageFile.ImageFile, "load", no_decode)
    story = await _story(client, people["owner"])
    resp = await _upload(client, people["owner"], story["id"], data, "x", kind)
    assert resp.status_code == 413, resp.text
    assert _detail(resp)["code"] == "story_image_too_large"


async def test_an_upload_over_the_byte_cap_is_refused(
    client: AsyncClient, people, monkeypatch
):
    from app.modules.catalog.stories import images, router_assets

    monkeypatch.setattr(images, "MAX_UPLOAD_BYTES", 1000)
    monkeypatch.setattr(router_assets, "MAX_UPLOAD_BYTES", 1000)
    story = await _story(client, people["owner"])
    resp = await _upload(client, people["owner"], story["id"], b"\0" * 1001)
    assert resp.status_code == 413, resp.text


def test_the_body_cap_admits_a_full_size_upload_on_that_route_only():
    route = f"/api/stories/{uuid.uuid4()}/assets"
    assert _route_limit(route, "POST") == STORY_ASSET_BODY_LIMIT_BYTES
    assert STORY_ASSET_BODY_LIMIT_BYTES > MAX_UPLOAD_BYTES
    for path, method in [
        (route, "PUT"),
        (route + "/", "POST"),
        ("/stories/not-a-uuid/assets", "POST"),
        (f"/stories/{uuid.uuid4()}/draft", "PUT"),
    ]:
        assert _route_limit(path, method) < MAX_UPLOAD_BYTES


async def test_the_per_story_caps_refuse_and_leave_nothing_stored(
    client: AsyncClient, people, monkeypatch, test_db_session
):
    from app.platform.storage.provider import get_storage

    owner = people["owner"]
    story = await _story(client, owner)
    monkeypatch.setattr(story_assets, "MAX_STORY_ASSETS", 2)
    await _uploaded(client, owner, story["id"])
    await _uploaded(client, owner, story["id"])
    refused = await _upload(client, owner, story["id"], _png())
    assert refused.status_code == 409, refused.text
    assert _detail(refused)["code"] == "story_asset_limit"
    listed = await get_storage().list("stories/assets/")
    assert len([k for k in listed if story["id"] in k]) == 2

    other = await _story(client, owner)
    first = await _uploaded(client, owner, other["id"])
    monkeypatch.setattr(story_assets, "MAX_STORY_ASSET_BYTES", first["byte_size"] + 1)
    refused = await _upload(client, owner, other["id"], _png())
    assert refused.status_code == 409
    assert len(await _keys(test_db_session, other["id"])) == 1


async def test_only_the_storys_editors_upload(client: AsyncClient, people):
    story = await _story(client, people["owner"])
    resp = await _upload(client, people["other"], story["id"], _png())
    assert resp.status_code == 404
    await client.patch(
        f"/stories/{story['id']}",
        json={"visibility": "internal"},
        headers=people["owner"],
    )
    assert (await _publish(client, people["owner"], story["id"])).status_code == 200
    resp = await _upload(client, people["other"], story["id"], _png())
    assert resp.status_code == 403
    assert (
        await _upload(client, people["admin"], story["id"], _png())
    ).status_code == 201
    assert (await _upload(client, {}, story["id"], _png())).status_code == 401


# Who reads an image --------------------------------------------------------


@pytest.fixture
async def illustrated(client: AsyncClient, people) -> dict:
    """A published internal story: one image in the published document, one
    only in the draft, a cover and an unused upload."""
    owner = people["owner"]
    story = await _story(client, owner)
    ids = {
        name: (await _uploaded(client, owner, story["id"]))["id"]
        for name in ("published", "draft_only", "cover", "unused")
    }
    chapter = _chapter(blocks=[_image_block(ids["published"])])
    await _saved(client, owner, story, [chapter])
    resp = await client.patch(
        f"/stories/{story['id']}",
        json={"visibility": "internal", "cover_asset_id": ids["cover"]},
        headers=owner,
    )
    assert resp.status_code == 200, resp.text
    assert (await _publish(client, owner, story["id"])).status_code == 200
    chapter["blocks"].append(_image_block(ids["draft_only"]))
    await _saved(client, owner, await _draft(client, owner, story["id"]), [chapter])
    return {"story": story["id"], **ids}


async def _statuses(client, headers, story) -> dict[str, int]:
    return {
        name: (await _image(client, headers, story["story"], story[name])).status_code
        for name in ("published", "draft_only", "cover", "unused")
    }


async def test_editors_get_every_image_and_readers_only_the_published_ones(
    client: AsyncClient, people, illustrated
):
    for editor in ("owner", "admin"):
        assert set((await _statuses(client, people[editor], illustrated)).values()) == {
            200
        }
    assert await _statuses(client, people["other"], illustrated) == {
        "published": 200,
        "draft_only": 404,
        "cover": 200,
        "unused": 404,
    }
    assert set((await _statuses(client, None, illustrated)).values()) == {404}


async def test_anonymous_readers_get_a_public_storys_published_images(
    client: AsyncClient, people, illustrated
):
    story_id = illustrated["story"]
    resp = await client.patch(
        f"/stories/{story_id}", json={"visibility": "public"}, headers=people["admin"]
    )
    assert resp.status_code == 200, resp.text
    assert await _statuses(client, None, illustrated) == {
        "published": 200,
        "draft_only": 404,
        "cover": 200,
        "unused": 404,
    }
    public = await _image(client, None, story_id, illustrated["published"])
    assert public.headers["cache-control"] == "public, no-cache"
    own_draft = await _image(
        client, people["owner"], story_id, illustrated["draft_only"]
    )
    assert own_draft.headers["cache-control"] == "private, no-cache"

    again = await _image(
        client,
        {"If-None-Match": public.headers["etag"]},
        story_id,
        illustrated["published"],
    )
    assert again.status_code == 304


async def test_a_private_or_unpublished_storys_images_reach_only_its_editors(
    client: AsyncClient, people, illustrated
):
    story_id = illustrated["story"]
    await client.patch(
        f"/stories/{story_id}", json={"visibility": "private"}, headers=people["owner"]
    )
    assert set((await _statuses(client, people["other"], illustrated)).values()) == {
        404
    }
    internal = await client.get(
        f"/stories/{story_id}/assets/{illustrated['published']}",
        headers=people["owner"],
    )
    assert internal.headers["cache-control"] == "private, no-cache"

    unpublished = await _story(client, people["owner"])
    await client.patch(
        f"/stories/{unpublished['id']}",
        json={"visibility": "public"},
        headers=people["admin"],
    )
    asset = await _uploaded(client, people["owner"], unpublished["id"])
    for reader in (people["other"], None):
        assert (
            await _image(client, reader, unpublished["id"], asset["id"])
        ).status_code == 404


async def test_an_image_is_read_only_through_its_own_story(
    client: AsyncClient, people, illustrated
):
    other_story = await _story(client, people["owner"])
    for asset in (illustrated["published"], str(uuid.uuid4())):
        resp = await _image(client, people["owner"], other_story["id"], asset)
        assert resp.status_code == 404
    missing = await _image(
        client, people["owner"], str(uuid.uuid4()), illustrated["published"]
    )
    assert missing.status_code == 404


# Blocks and the cover --------------------------------------------------------


async def test_an_image_block_names_an_image_of_its_own_story(
    client: AsyncClient, people
):
    owner = people["owner"]
    story = await _story(client, owner)
    elsewhere = await _story(client, owner)
    foreign = await _uploaded(client, owner, elsewhere["id"])
    resp = await _save(
        client, owner, story, [_chapter(blocks=[_image_block(foreign["id"])])]
    )
    assert resp.status_code == 422, resp.text
    assert _detail(resp)["code"] == "story_assets_not_found"
    assert _detail(resp)["asset_ids"] == [foreign["id"]]

    own = await _uploaded(client, owner, story["id"])
    no_alt = _image_block(own["id"], alt=" ")
    resp = await _save(client, owner, story, [_chapter(blocks=[no_alt])])
    assert resp.status_code == 422, resp.text

    block = _image_block(own["id"])
    saved = await _saved(client, owner, story, [_chapter(blocks=[block])])
    assert saved["document"]["chapters"][0]["blocks"] == [{**block, "title": None}]


async def test_the_cover_is_an_image_of_the_story(client: AsyncClient, people):
    owner = people["owner"]
    story = await _story(client, owner)
    elsewhere = await _story(client, owner)
    foreign = await _uploaded(client, owner, elsewhere["id"])
    resp = await client.patch(
        f"/stories/{story['id']}", json={"cover_asset_id": foreign["id"]}, headers=owner
    )
    assert resp.status_code == 422
    assert _detail(resp)["code"] == "story_assets_not_found"

    cover = await _uploaded(client, owner, story["id"])
    resp = await client.patch(
        f"/stories/{story['id']}", json={"cover_asset_id": cover["id"]}, headers=owner
    )
    assert resp.status_code == 200 and resp.json()["cover_asset_id"] == cover["id"]
    listed = await client.get("/stories/?owned_only=true", headers=owner)
    by_id = {s["id"]: s for s in listed.json()["stories"]}
    assert by_id[story["id"]]["cover_asset_id"] == cover["id"]

    resp = await client.patch(
        f"/stories/{story['id']}", json={"title": "Renamed"}, headers=owner
    )
    assert resp.json()["cover_asset_id"] == cover["id"]
    resp = await client.patch(
        f"/stories/{story['id']}", json={"cover_asset_id": None}, headers=owner
    )
    assert resp.json()["cover_asset_id"] is None


# Cleanup, deletes and copies -------------------------------------------------


async def test_a_save_removes_old_images_nothing_uses_and_keeps_the_rest(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    story = await _story(client, owner)
    names = ("published", "draft", "cover", "kept_raw", "old_unused", "new_unused")
    ids = {n: (await _uploaded(client, owner, story["id"]))["id"] for n in names}
    keys = await _keys(test_db_session, story["id"])

    published = _chapter(blocks=[_image_block(ids["published"])])
    await _saved(client, owner, story, [published])
    await client.patch(
        f"/stories/{story['id']}", json={"cover_asset_id": ids["cover"]}, headers=owner
    )
    assert (await _publish(client, owner, story["id"])).status_code == 200
    # A block of a newer version, which this server can't parse, still uses
    # its image.
    future = {**_image_block(ids["kept_raw"]), "v": 99}
    draft = {
        "version": 1,
        "chapters": [
            {
                "id": published["id"],
                "title": None,
                "scene": None,
                "blocks": [_image_block(ids["draft"]), future],
            }
        ],
    }
    await test_db_session.execute(
        update(Story).where(Story.id == uuid.UUID(story["id"])).values(draft=draft)
    )
    await test_db_session.commit()
    await _age(test_db_session, *(ids[n] for n in names if n != "new_unused"))

    current = await _draft(client, owner, story["id"])
    await _saved(client, owner, current, current["document"]["chapters"])

    remaining = await _keys(test_db_session, story["id"])
    assert set(remaining) == {ids[n] for n in names if n != "old_unused"}
    assert not await _object_exists(keys[ids["old_unused"]])
    for name in ("published", "cover", "new_unused"):
        assert await _object_exists(keys[ids[name]])


async def test_deleting_a_story_deletes_its_images(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    story = await _story(client, owner)
    first = await _uploaded(client, owner, story["id"])
    await _uploaded(client, owner, story["id"])
    await client.patch(
        f"/stories/{story['id']}", json={"cover_asset_id": first["id"]}, headers=owner
    )
    keys = await _keys(test_db_session, story["id"])
    assert len(keys) == 2

    resp = await client.delete(f"/stories/{story['id']}", headers=owner)
    assert resp.status_code == 204, resp.text
    assert await _keys(test_db_session, story["id"]) == {}
    for key in keys.values():
        assert not await _object_exists(key)


async def test_a_copy_gets_its_own_images(client: AsyncClient, people, test_db_session):
    owner = people["owner"]
    story = await _story(client, owner)
    image = await _uploaded(client, owner, story["id"])
    cover = await _uploaded(client, owner, story["id"])
    await _uploaded(client, owner, story["id"])  # unused: not copied
    await _saved(client, owner, story, [_chapter(blocks=[_image_block(image["id"])])])
    await client.patch(
        f"/stories/{story['id']}", json={"cover_asset_id": cover["id"]}, headers=owner
    )
    original = await _keys(test_db_session, story["id"])

    resp = await client.post(f"/stories/{story['id']}/duplicate", headers=owner)
    assert resp.status_code == 201, resp.text
    copy = resp.json()
    (block,) = copy["document"]["chapters"][0]["blocks"]
    copied = await _keys(test_db_session, copy["id"])
    assert set(copied) == {block["asset_id"], copy["cover_asset_id"]}
    assert not set(copied) & set(original)
    assert not set(copied.values()) & set(original.values())

    assert (
        await client.delete(f"/stories/{story['id']}", headers=owner)
    ).status_code == 204
    for asset_id in copied:
        served = await _image(client, owner, copy["id"], asset_id)
        assert served.status_code == 200


async def test_a_readers_copy_takes_only_the_published_images(
    client: AsyncClient, people, illustrated, test_db_session
):
    resp = await client.post(
        f"/stories/{illustrated['story']}/duplicate", headers=people["other"]
    )
    assert resp.status_code == 201, resp.text
    copy = resp.json()
    (block,) = copy["document"]["chapters"][0]["blocks"]
    copied = await _keys(test_db_session, copy["id"])
    assert set(copied) == {block["asset_id"], copy["cover_asset_id"]}
    assert len(copied) == 2
    served = await _image(client, people["other"], copy["id"], block["asset_id"])
    original = await _image(
        client, people["owner"], illustrated["story"], illustrated["published"]
    )
    assert served.content == original.content


async def test_a_copy_leaves_out_an_image_whose_object_is_gone(
    client: AsyncClient, people, test_db_session
):
    from app.platform.storage.provider import get_storage

    owner = people["owner"]
    story = await _story(client, owner)
    image = await _uploaded(client, owner, story["id"])
    text = {
        "id": str(uuid.uuid4()),
        "type": "markdown",
        "v": 1,
        "config": {"text": "x"},
    }
    await _saved(
        client, owner, story, [_chapter(blocks=[text, _image_block(image["id"])])]
    )
    keys = await _keys(test_db_session, story["id"])
    await get_storage().delete(keys[image["id"]])

    resp = await client.post(f"/stories/{story['id']}/duplicate", headers=owner)
    assert resp.status_code == 201, resp.text
    assert resp.json()["document"]["chapters"][0]["blocks"] == [{**text, "title": None}]
    assert await _keys(test_db_session, resp.json()["id"]) == {}


# Readers, grace periods, colour and caching ----------------------------------


async def test_readers_get_only_image_blocks_and_blocks_this_server_cannot_read(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    story = await _story(client, owner)
    shown, named, future = [
        (await _uploaded(client, owner, story["id"]))["id"] for _ in range(3)
    ]
    # Its id matches an image's; that doesn't make the image readable.
    text = {"id": named, "type": "markdown", "v": 1, "config": {"text": "x"}}
    await _saved(client, owner, story, [_chapter(blocks=[_image_block(shown), text])])
    await client.patch(
        f"/stories/{story['id']}", json={"visibility": "public"}, headers=owner
    )
    draft = await test_db_session.scalar(
        select(Story.draft).where(Story.id == uuid.UUID(story["id"]))
    )
    draft["chapters"][0]["blocks"].append({**_image_block(future), "v": 99})
    await test_db_session.execute(
        update(Story).where(Story.id == uuid.UUID(story["id"])).values(draft=draft)
    )
    await test_db_session.commit()
    assert (await _publish(client, owner, story["id"])).status_code == 200

    for reader in (people["other"], None):
        statuses = [
            (await _image(client, reader, story["id"], asset)).status_code
            for asset in (shown, named, future)
        ]
        assert statuses == [200, 404, 200]


async def test_an_image_taken_out_of_use_keeps_its_grace_period(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    story = await _story(client, owner)
    image, cover, new_cover = [
        (await _uploaded(client, owner, story["id"]))["id"] for _ in range(3)
    ]
    await _saved(client, owner, story, [_chapter(blocks=[_image_block(image)])])
    await client.patch(
        f"/stories/{story['id']}", json={"cover_asset_id": cover}, headers=owner
    )
    # Months in use, then taken out: the block is removed and the cover swapped.
    await _age(test_db_session, image, cover)
    await client.patch(
        f"/stories/{story['id']}", json={"cover_asset_id": new_cover}, headers=owner
    )
    await _saved(client, owner, await _draft(client, owner, story["id"]), [_chapter()])
    assert {image, cover} <= set(await _keys(test_db_session, story["id"]))

    # Once the grace period passes with nothing using them, they go.
    await _age(test_db_session, image, cover)
    current = await _draft(client, owner, story["id"])
    await _saved(client, owner, current, current["document"]["chapters"])
    assert set(await _keys(test_db_session, story["id"])) == {new_cover}


def _icc_profile(primaries) -> bytes:
    """A minimal ICC v2 RGB display profile with a 2.2 gamma."""

    def s15(value: float) -> bytes:
        return struct.pack(">i", round(value * 65536))

    def xyz(x: float, y: float, z: float) -> bytes:
        return b"XYZ " + bytes(4) + s15(x) + s15(y) + s15(z)

    curve = b"curv" + bytes(4) + struct.pack(">IH", 1, round(2.2 * 256)) + bytes(2)
    name = b"Display P3 (test)"
    desc = b"desc" + bytes(4) + struct.pack(">I", len(name) + 1) + name + bytes(79)
    white = (0.9642, 1.0, 0.8249)
    tags = [
        (b"desc", desc),
        (b"wtpt", xyz(*white)),
        (b"rXYZ", xyz(*primaries[0])),
        (b"gXYZ", xyz(*primaries[1])),
        (b"bXYZ", xyz(*primaries[2])),
        (b"rTRC", curve),
        (b"gTRC", curve),
        (b"bTRC", curve),
    ]
    start = 128 + 4 + 12 * len(tags)
    table, body = b"", b""
    for signature, data in tags:
        body += bytes(-len(body) % 4)
        table += signature + struct.pack(">II", start + len(body), len(data))
        body += data
    header = (
        struct.pack(">I", start + len(body))
        + bytes(4)
        + struct.pack(">I", 0x02100000)
        + b"mntrRGB XYZ "
        + bytes(12)
        + b"acsp"
        + bytes(28)
        + s15(white[0])
        + s15(white[1])
        + s15(white[2])
        + bytes(48)
    )
    return header + struct.pack(">I", len(tags)) + table + body


async def test_an_embedded_colour_profile_is_converted_to_srgb(
    client: AsyncClient, people
):
    from PIL import ImageCms

    display_p3 = _icc_profile(
        (
            (0.515102, 0.241196, -0.001050),
            (0.291965, 0.692236, 0.041882),
            (0.157153, 0.066574, 0.784097),
        )
    )
    colour = (40, 180, 90)
    source = Image.new("RGB", (32, 32), colour)
    expected = ImageCms.profileToProfile(
        source,
        ImageCms.ImageCmsProfile(BytesIO(display_p3)),
        ImageCms.createProfile("sRGB"),
    ).getpixel((0, 0))
    assert max(abs(a - b) for a, b in zip(expected, colour)) > 20

    story = await _story(client, people["owner"])
    photo = _encode(source, "PNG", icc_profile=display_p3)
    asset = await _uploaded(client, people["owner"], story["id"], photo)
    served = await _image(client, people["owner"], story["id"], asset["id"])
    with Image.open(BytesIO(served.content)) as image:
        assert "icc_profile" not in image.info
        stored = image.convert("RGB").getpixel((16, 16))
    assert max(abs(a - b) for a, b in zip(stored, expected)) <= 4


async def test_a_refused_image_read_is_not_cached(
    client: AsyncClient, people, illustrated
):
    for reader, asset in (
        (None, illustrated["published"]),
        (people["other"], illustrated["draft_only"]),
        (people["owner"], str(uuid.uuid4())),
    ):
        resp = await _image(client, reader, illustrated["story"], asset)
        assert resp.status_code == 404
        assert resp.headers["cache-control"] == "private, no-store"


# Uploads waiting on memory -----------------------------------------------------


class _Body:
    """A multipart upload as a stream that notes whether anyone read it."""

    def __init__(self, *parts: tuple[str, bytes]) -> None:
        self.boundary = uuid.uuid4().hex
        chunks = []
        for name, data in parts:
            chunks.append(
                f"--{self.boundary}\r\nContent-Disposition: form-data; "
                f'name="{name}"; filename="{name}.png"\r\n'
                "Content-Type: image/png\r\n\r\n".encode()
                + data
                + b"\r\n"
            )
        chunks.append(f"--{self.boundary}--\r\n".encode())
        self.chunks = chunks
        self.read = False

    async def stream(self):
        self.read = True
        for chunk in self.chunks:
            yield chunk

    async def post(self, client, story_id, headers):
        return await client.post(
            f"/stories/{story_id}/assets",
            content=self.stream(),
            headers={
                **headers,
                "Content-Type": f"multipart/form-data; boundary={self.boundary}",
            },
        )


async def test_an_upload_is_read_only_after_its_caller_is_admitted(
    client: AsyncClient, people, monkeypatch
):
    import asyncio

    from app.modules.catalog.stories import images

    story = await _story(client, people["owner"])
    anonymous = _Body(("file", _png()))
    assert (await anonymous.post(client, story["id"], {})).status_code == 401
    assert not anonymous.read

    monkeypatch.setattr(images, "_upload_slots", asyncio.Semaphore(0))
    busy = _Body(("file", _png()))
    resp = await busy.post(client, story["id"], people["owner"])
    assert resp.status_code == 503, resp.text
    assert resp.headers["retry-after"] == str(images.RETRY_AFTER_SECONDS)
    assert _detail(resp)["code"] == "story_image_busy"
    assert not busy.read

    monkeypatch.setattr(images, "_upload_slots", asyncio.Semaphore(1))
    two = _Body(("file", _png()), ("other", _png()))
    assert (await two.post(client, story["id"], people["owner"])).status_code == 400
    assert not images._upload_slots.locked()

    monkeypatch.setattr(images, "_decode_reserved", images.DECODE_BUDGET_BYTES)
    resp = await _upload(client, people["owner"], story["id"], _png())
    assert resp.status_code == 503, resp.text


async def test_the_upload_slot_is_held_through_storage_and_the_commit(
    client: AsyncClient, people, monkeypatch
):
    import asyncio

    from app.modules.catalog.stories import images, router_assets
    from app.platform.storage.provider import get_storage

    slots = asyncio.Semaphore(1)
    monkeypatch.setattr(images, "_upload_slots", slots)
    held: list[str] = []
    storage = get_storage()
    real_put = storage.put
    real_discard = router_assets.discard_story_asset_objects

    async def put(key, data):
        held.append(f"put {slots.locked()}")
        return await real_put(key, data)

    async def discard(keys):
        held.append(f"after commit {slots.locked()}")
        await real_discard(keys)

    monkeypatch.setattr(storage, "put", put)
    monkeypatch.setattr(router_assets, "discard_story_asset_objects", discard)
    story = await _story(client, people["owner"])
    await _uploaded(client, people["owner"], story["id"])
    assert held == ["put True", "after commit True"]
    assert not slots.locked()


async def test_decodes_run_on_their_own_threads_and_hold_memory_until_done(
    monkeypatch,
):
    import asyncio
    import threading

    from app.modules.catalog.stories import images

    started, release = threading.Event(), threading.Event()
    threads: list[str] = []
    real_decode = images.decode_story_image

    def held_decode(data, plan):
        threads.append(threading.current_thread().name)
        started.set()
        release.wait(5)
        return real_decode(data, plan)

    monkeypatch.setattr(images, "decode_story_image", held_decode)
    data = _png()
    cost = images.plan_story_image(data).cost
    task = asyncio.ensure_future(images.prepare_story_image(data))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0.05)
    # The thread still holds the decode, so its reservation stands.
    assert not task.done()
    assert images._decode_reserved == cost
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert images._decode_reserved == 0
    assert threads[0].startswith("story-image")


def test_every_cap_fits_the_decode_budget_alone():
    from app.modules.catalog.stories import images

    for kind, pixels in images.MAX_PIXELS.items():
        assert images.BYTES_PER_PIXEL[kind] * pixels <= images.DECODE_BUDGET_BYTES
    # A one-pass JPEG decodes to under twice the output size a side.
    worst = images._draft_pixels((2 * images.MAX_OUTPUT_SIDE - 1,) * 2)
    assert images.BYTES_PER_PIXEL["JPEG"] * worst <= images.DECODE_BUDGET_BYTES
    for side in range(images.MAX_OUTPUT_SIDE, images.MAX_JPEG_SIDE + 1, 97):
        for other in (1, side // 3, side):
            assert images._draft_pixels((side, other)) <= worst


# Copies racing the source -------------------------------------------------------


async def test_a_copy_drops_images_removed_from_the_source_while_it_ran(
    client: AsyncClient, people, test_db_session, monkeypatch
):
    from sqlalchemy import delete

    from app.modules.catalog.stories import service

    owner = people["owner"]
    story = await _story(client, owner)
    image = await _uploaded(client, owner, story["id"])
    text = {
        "id": str(uuid.uuid4()),
        "type": "markdown",
        "v": 1,
        "config": {"text": "x"},
    }
    await _saved(
        client, owner, story, [_chapter(blocks=[text, _image_block(image["id"])])]
    )
    await client.patch(
        f"/stories/{story['id']}", json={"cover_asset_id": image["id"]}, headers=owner
    )
    real_create = service.create_story

    async def create_after_a_concurrent_delete(db, **kwargs):
        # Between the copy reading the document and listing the images.
        await db.execute(
            delete(StoryAsset).where(StoryAsset.story_id == uuid.UUID(story["id"]))
        )
        return await real_create(db, **kwargs)

    monkeypatch.setattr(service, "create_story", create_after_a_concurrent_delete)
    resp = await client.post(f"/stories/{story['id']}/duplicate", headers=owner)
    assert resp.status_code == 201, resp.text
    copy = resp.json()
    assert copy["document"]["chapters"][0]["blocks"] == [{**text, "title": None}]
    assert copy["cover_asset_id"] is None
    resaved = await _save(client, owner, copy, copy["document"]["chapters"])
    assert resaved.status_code == 200, resaved.text


async def test_a_cancelled_copy_leaves_no_object_behind(
    client: AsyncClient, people, test_db_session, monkeypatch
):
    import asyncio
    import shutil
    import threading
    import time

    from app.platform.storage.provider import get_storage

    owner = people["owner"]
    story = await _story(client, owner)
    image = await _uploaded(client, owner, story["id"])
    await _saved(client, owner, story, [_chapter(blocks=[_image_block(image["id"])])])
    before = set(await get_storage().list("stories/assets/"))

    copying = threading.Event()
    real_copy2 = shutil.copy2

    def slow_copy2(src, dst, **kwargs):
        copying.set()
        time.sleep(0.3)
        return real_copy2(src, dst, **kwargs)

    monkeypatch.setattr(shutil, "copy2", slow_copy2)
    task = asyncio.ensure_future(
        client.post(f"/stories/{story['id']}/duplicate", headers=owner)
    )
    await asyncio.to_thread(copying.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.5)
    assert set(await get_storage().list("stories/assets/")) == before


# What a copy and a read may reach --------------------------------------------------


async def test_a_copy_takes_only_images_the_copier_could_read(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    story = await _story(client, owner)
    shown, hidden = [
        (await _uploaded(client, owner, story["id"]))["id"] for _ in range(2)
    ]
    # The hidden image's id appears as a block id, a chapter id and a title,
    # none of which shows it to a reader.
    text = {"id": hidden, "type": "markdown", "v": 1, "config": {"text": hidden}}
    chapter = {**_chapter(blocks=[_image_block(shown), text]), "id": hidden}
    chapter["title"] = hidden
    await _saved(client, owner, story, [chapter])
    await client.patch(
        f"/stories/{story['id']}", json={"visibility": "internal"}, headers=owner
    )
    assert (await _publish(client, owner, story["id"])).status_code == 200
    assert (
        await _image(client, people["other"], story["id"], hidden)
    ).status_code == 404

    for copier in (people["other"], owner):
        resp = await client.post(f"/stories/{story['id']}/duplicate", headers=copier)
        assert resp.status_code == 201, resp.text
        copy = resp.json()
        copied = await _keys(test_db_session, copy["id"])
        image_block = copy["document"]["chapters"][0]["blocks"][0]
        assert set(copied) == {image_block["asset_id"]}
        assert image_block["asset_id"] != shown


async def _publish_as_an_older_server(session, story_id: uuid.UUID, edit) -> None:
    """Rewrite the published document and its publish time, as a 1.28.0
    process publishing would, with nothing else of this server's."""
    published = await session.scalar(
        select(Story.published).where(Story.id == story_id)
    )
    edit(published["chapters"][0]["blocks"])
    await session.execute(
        update(Story)
        .where(Story.id == story_id)
        .values(published=published, published_at=func.now())
    )
    await session.commit()


async def test_reader_access_follows_a_publish_by_an_older_server(
    client: AsyncClient, people, illustrated, test_db_session
):
    story_id = uuid.UUID(illustrated["story"])
    reader = people["other"]
    before = await _image(client, reader, str(story_id), illustrated["published"])
    assert before.status_code == 200
    assert (
        await _image(client, reader, str(story_id), illustrated["unused"])
    ).status_code == 404

    def swap(blocks):
        blocks[:] = [_image_block(illustrated["unused"])]

    await _publish_as_an_older_server(test_db_session, story_id, swap)

    assert (
        await _image(client, reader, str(story_id), illustrated["unused"])
    ).status_code == 200
    removed = await _image(
        client,
        {**reader, "If-None-Match": before.headers["etag"]},
        str(story_id),
        illustrated["published"],
    )
    assert removed.status_code == 404

    resp = await client.post(f"/stories/{story_id}/duplicate", headers=reader)
    assert resp.status_code == 201, resp.text
    copy = resp.json()
    (block,) = copy["document"]["chapters"][0]["blocks"]
    assert set(await _keys(test_db_session, copy["id"])) == {
        block["asset_id"],
        copy["cover_asset_id"],
    }
    copied = await _image(client, reader, copy["id"], block["asset_id"])
    original = await _image(client, reader, str(story_id), illustrated["unused"])
    assert copied.content == original.content


async def test_a_cover_change_reaches_readers_at_once(
    client: AsyncClient, people, illustrated
):
    story_id = illustrated["story"]
    resp = await client.patch(
        f"/stories/{story_id}",
        json={"cover_asset_id": illustrated["unused"]},
        headers=people["owner"],
    )
    assert resp.status_code == 200, resp.text
    statuses = await _statuses(client, people["other"], illustrated)
    assert (statuses["unused"], statuses["cover"]) == (200, 404)


async def test_a_current_copy_is_confirmed_without_reading_storage(
    client: AsyncClient, people, illustrated, monkeypatch
):
    from app.platform.storage.provider import get_storage

    first = await _image(
        client, people["other"], illustrated["story"], illustrated["published"]
    )
    assert first.status_code == 200

    async def no_read(key):
        raise AssertionError("read an image the caller already holds")

    monkeypatch.setattr(get_storage(), "get", no_read)
    again = await _image(
        client,
        {**people["other"], "If-None-Match": first.headers["etag"]},
        illustrated["story"],
        illustrated["published"],
    )
    assert again.status_code == 304


async def test_an_upload_prunes_only_to_make_room(
    client: AsyncClient, people, monkeypatch, test_db_session
):
    owner = people["owner"]
    story = await _story(client, owner)
    old = (await _uploaded(client, owner, story["id"]))["id"]
    await _age(test_db_session, old)
    await _uploaded(client, owner, story["id"])
    assert old in await _keys(test_db_session, story["id"])

    monkeypatch.setattr(story_assets, "MAX_STORY_ASSETS", 2)
    await _uploaded(client, owner, story["id"])
    assert old not in await _keys(test_db_session, story["id"])


async def test_an_image_only_the_published_document_shows_survives_a_prune(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    story = await _story(client, owner)
    image = (await _uploaded(client, owner, story["id"]))["id"]
    await _saved(client, owner, story, [_chapter()])
    assert (await _publish(client, owner, story["id"])).status_code == 200
    await _publish_as_an_older_server(
        test_db_session,
        uuid.UUID(story["id"]),
        lambda blocks: blocks.append(_image_block(image)),
    )
    await _age(test_db_session, image)

    current = await _draft(client, owner, story["id"])
    await _saved(client, owner, current, current["document"]["chapters"])
    assert image in await _keys(test_db_session, story["id"])


_SPELLINGS = {
    "canonical": str,
    "uppercase": lambda value: str(value).upper(),
    "compact": lambda value: value.hex,
    "braced": lambda value: "{" + str(value) + "}",
    "urn": lambda value: value.urn,
}


@pytest.mark.parametrize("spelling", sorted(_SPELLINGS))
async def test_a_block_this_server_cannot_parse_keeps_and_copies_its_image(
    client: AsyncClient, people, test_db_session, spelling
):
    owner = people["owner"]
    story = await _story(client, owner)
    image = (await _uploaded(client, owner, story["id"]))["id"]
    future = {
        **_image_block(image),
        "v": 99,
        "asset_id": _SPELLINGS[spelling](uuid.UUID(image)),
    }
    await _saved(client, owner, story, [_chapter()])
    draft = await test_db_session.scalar(
        select(Story.draft).where(Story.id == uuid.UUID(story["id"]))
    )
    draft["chapters"][0]["blocks"] = [future]
    await test_db_session.execute(
        update(Story).where(Story.id == uuid.UUID(story["id"])).values(draft=draft)
    )
    await test_db_session.commit()
    await _age(test_db_session, image)

    current = await _draft(client, owner, story["id"])
    await _saved(client, owner, current, current["document"]["chapters"])
    assert image in await _keys(test_db_session, story["id"])

    resp = await client.post(f"/stories/{story['id']}/duplicate", headers=owner)
    assert resp.status_code == 201, resp.text
    (copied,) = await _keys(test_db_session, resp.json()["id"])
    stored = await test_db_session.scalar(
        select(Story.draft).where(Story.id == uuid.UUID(resp.json()["id"]))
    )
    assert stored["chapters"][0]["blocks"][0]["asset_id"] == copied


async def test_a_copy_whose_source_vanishes_mid_write_leaves_nothing_behind(
    client: AsyncClient, people, test_db_session, monkeypatch
):
    import os
    import shutil

    from app.platform.storage.provider import get_storage

    owner = people["owner"]
    story = await _story(client, owner)
    image = (await _uploaded(client, owner, story["id"]))["id"]
    await _saved(client, owner, story, [_chapter(blocks=[_image_block(image)])])
    real_copystat = shutil.copystat

    def source_deleted_after_the_bytes(src, dst, **kwargs):
        # copy2 has written the bytes; a concurrent delete takes the source.
        os.remove(src)
        return real_copystat(src, dst, **kwargs)

    monkeypatch.setattr(shutil, "copystat", source_deleted_after_the_bytes)
    resp = await client.post(f"/stories/{story['id']}/duplicate", headers=owner)
    assert resp.status_code == 201, resp.text
    copy_id = resp.json()["id"]
    assert await _keys(test_db_session, copy_id) == {}
    left = [k for k in await get_storage().list("stories/assets/") if copy_id in k]
    assert left == []


async def test_an_upload_without_a_file_part_names_the_problem(
    client: AsyncClient, people
):
    story = await _story(client, people["owner"])
    resp = await client.post(
        f"/stories/{story['id']}/assets",
        files={"image": ("a.png", _png(), "image/png")},
        headers=people["owner"],
    )
    assert resp.status_code == 422, resp.text
    assert _detail(resp)["code"] == "story_image_missing"


async def test_an_upload_holds_no_database_transaction_while_it_processes(
    client: AsyncClient, people, monkeypatch
):
    from app.api.main import app
    from app.core.dependencies import get_db
    from app.modules.catalog.stories import router_assets
    from app.platform.storage.provider import get_storage

    sessions = []
    request_session = app.dependency_overrides[get_db]

    async def recording_session():
        async for session in request_session():
            sessions.append(session)
            yield session

    monkeypatch.setitem(app.dependency_overrides, get_db, recording_session)
    seen: dict[str, bool] = {}
    real_prepare = router_assets.prepare_story_image
    storage = get_storage()
    real_put = storage.put

    async def prepare(data):
        seen["decode"] = sessions[-1].in_transaction()
        return await real_prepare(data)

    async def put(key, data):
        seen["store"] = sessions[-1].in_transaction()
        return await real_put(key, data)

    monkeypatch.setattr(router_assets, "prepare_story_image", prepare)
    monkeypatch.setattr(storage, "put", put)
    story = await _story(client, people["owner"])
    await _uploaded(client, people["owner"], story["id"])
    assert seen == {"decode": False, "store": False}
