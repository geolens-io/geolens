"""Stories through the real guards: reads, draft saves, publishing and copies."""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.modules.catalog.stories.models import Story, StoryMap
from tests.factories import create_user

pytestmark = pytest.mark.anyio


def _detail(resp) -> dict:
    detail = resp.json()["detail"]
    # The ProblemDetail handler serializes a dict detail as a JSON string.
    return json.loads(detail) if isinstance(detail, str) else detail


async def _map(client: AsyncClient, headers: dict, visibility: str = "private") -> str:
    created = await client.post(
        "/maps/", json={"name": f"story-map-{uuid.uuid4().hex[:8]}"}, headers=headers
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]
    if visibility != "private":
        await _set_map_visibility(client, headers, map_id, visibility)
    return map_id


async def _set_map_visibility(client, headers, map_id, visibility) -> None:
    resp = await client.put(
        f"/maps/{map_id}", json={"visibility": visibility}, headers=headers
    )
    assert resp.status_code == 200, resp.text


def _block(text: str = "Hello") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "type": "markdown",
        "v": 1,
        "config": {"text": text},
    }


def _chapter(map_id: str | None = None, *, blocks=None, chapter_id=None) -> dict:
    chapter = {
        "id": chapter_id or str(uuid.uuid4()),
        "title": "Chapter",
        "blocks": blocks if blocks is not None else [_block()],
    }
    if map_id is not None:
        chapter["scene"] = {
            "map_id": map_id,
            "camera": {"center": [-74.0, 40.7], "zoom": 10},
        }
    return chapter


async def _story(client: AsyncClient, headers: dict) -> dict:
    resp = await client.post("/stories/", json={"title": "A story"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _save(client, headers, story: dict, chapters: list[dict]):
    return await client.put(
        f"/stories/{story['id']}/draft",
        json={
            "revision": story["revision"],
            "document": {"version": 1, "chapters": chapters},
        },
        headers=headers,
    )


async def _saved(client, headers, story, chapters) -> dict:
    resp = await _save(client, headers, story, chapters)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _publish(client, headers, story_id: str):
    return await client.post(f"/stories/{story_id}/publish", headers=headers)


@pytest.fixture
async def people(client: AsyncClient, admin_auth_header: dict) -> dict:
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    other, _ = await create_user(client, admin_auth_header, "editor")
    return {
        "owner": owner,
        "owner_id": owner_id,
        "other": other,
        "admin": admin_auth_header,
    }


async def test_unpublished_story_is_readable_only_by_its_owner_and_admins(
    client: AsyncClient, people
):
    story = await _story(client, people["owner"])
    url = f"/stories/{story['id']}"

    assert (await client.get(url)).status_code == 404
    assert (await client.get(url, headers=people["other"])).status_code == 404
    own = await client.get(url, headers=people["owner"])
    assert own.status_code == 200 and own.json()["document"] is None
    assert (await client.get(url, headers=people["admin"])).status_code == 200

    listed = await client.get("/stories/", headers=people["other"])
    assert story["id"] not in {s["id"] for s in listed.json()["stories"]}
    anon = await client.get("/stories/")
    assert story["id"] not in {s["id"] for s in anon.json()["stories"]}

    # A wider visibility reaches readers only once there is something published.
    widened = await client.patch(
        url, json={"visibility": "internal"}, headers=people["owner"]
    )
    assert widened.status_code == 200, widened.text
    assert (await client.get(url, headers=people["other"])).status_code == 404
    listed = await client.get("/stories/", headers=people["other"])
    assert story["id"] not in {s["id"] for s in listed.json()["stories"]}
    assert (await _publish(client, people["owner"], story["id"])).status_code == 200
    assert (await client.get(url, headers=people["other"])).status_code == 200
    listed = await client.get("/stories/", headers=people["other"])
    assert story["id"] in {s["id"] for s in listed.json()["stories"]}


async def test_public_story_drops_a_scene_whose_map_turned_private(
    client: AsyncClient, people
):
    owner = people["owner"]
    map_id = await _map(client, owner, "public")
    story = await _story(client, owner)
    chapter = _chapter(map_id, blocks=[_block("Text that stays")])
    await _saved(client, owner, story, [chapter])
    patched = await client.patch(
        f"/stories/{story['id']}", json={"visibility": "public"}, headers=owner
    )
    assert patched.status_code == 200, patched.text
    assert (await _publish(client, owner, story["id"])).status_code == 200

    read = await client.get(f"/stories/{story['id']}")
    assert read.status_code == 200, read.text
    (shown,) = read.json()["document"]["chapters"]
    assert shown["scene"]["map_id"] == map_id
    listed = await client.get("/stories/")
    assert story["id"] in {s["id"] for s in listed.json()["stories"]}

    await _set_map_visibility(client, owner, map_id, "private")
    read = await client.get(f"/stories/{story['id']}")
    (shown,) = read.json()["document"]["chapters"]
    assert shown["scene"] is None and shown["scene_hidden"] is True
    assert shown["blocks"][0]["config"]["text"] == "Text that stays"
    # Its owner still reads the map, so they still see the scene.
    own = await client.get(f"/stories/{story['id']}", headers=owner)
    assert own.json()["document"]["chapters"][0]["scene"]["map_id"] == map_id


async def test_publish_is_refused_with_the_maps_narrower_than_the_story(
    client: AsyncClient, people
):
    owner = people["owner"]
    public_map = await _map(client, owner, "public")
    internal_map = await _map(client, owner, "internal")
    story = await _story(client, owner)
    story = await _saved(client, owner, story, [_chapter(public_map)])
    assert (
        await client.patch(
            f"/stories/{story['id']}", json={"visibility": "public"}, headers=owner
        )
    ).status_code == 200
    await _saved(client, owner, story, [_chapter(public_map), _chapter(internal_map)])

    refused = await _publish(client, owner, story["id"])

    assert refused.status_code == 409, refused.text
    detail = _detail(refused)
    assert detail["code"] == "maps_narrower_than_story"
    assert [m["id"] for m in detail["maps"]] == [internal_map]
    assert detail["maps"][0]["name"].startswith("story-map-")
    assert (await client.get(f"/stories/{story['id']}")).status_code == 404


async def test_widening_visibility_past_a_published_map_is_refused(
    client: AsyncClient, people
):
    owner = people["owner"]
    internal_map = await _map(client, owner, "internal")
    story = await _story(client, owner)
    await _saved(client, owner, story, [_chapter(internal_map)])
    assert (
        await client.patch(
            f"/stories/{story['id']}", json={"visibility": "internal"}, headers=owner
        )
    ).status_code == 200
    assert (await _publish(client, owner, story["id"])).status_code == 200

    refused = await client.patch(
        f"/stories/{story['id']}", json={"visibility": "public"}, headers=owner
    )

    assert refused.status_code == 409, refused.text
    assert [m["id"] for m in _detail(refused)["maps"]] == [internal_map]
    read = await client.get(f"/stories/{story['id']}", headers=people["other"])
    assert read.status_code == 200 and read.json()["visibility"] == "internal"
    assert (await client.get(f"/stories/{story['id']}")).status_code == 404


async def test_private_story_cannot_publish_a_map_its_owner_lost(
    client: AsyncClient, people
):
    owner, other = people["owner"], people["other"]
    their_map = await _map(client, other, "internal")
    story = await _story(client, owner)
    await _saved(client, owner, story, [_chapter(their_map)])
    await _set_map_visibility(client, other, their_map, "private")

    refused = await _publish(client, owner, story["id"])

    assert refused.status_code == 409, refused.text
    # The owner can't read the map, so its name isn't disclosed.
    assert _detail(refused)["maps"] == [{"id": their_map, "name": None}]


async def test_draft_is_only_for_editors(client: AsyncClient, people):
    owner, other = people["owner"], people["other"]
    story = await _story(client, owner)
    await _saved(client, owner, story, [_chapter(blocks=[_block("draft only")])])
    draft_url = f"/stories/{story['id']}/draft"

    assert (await client.get(draft_url, headers=other)).status_code == 404
    assert (await client.get(draft_url)).status_code == 401

    await client.patch(
        f"/stories/{story['id']}", json={"visibility": "internal"}, headers=owner
    )
    await _publish(client, owner, story["id"])
    current = (await client.get(draft_url, headers=owner)).json()
    await _saved(client, owner, current, [_chapter(blocks=[_block("unpublished")])])

    assert (await client.get(draft_url, headers=other)).status_code == 403
    read = await client.get(f"/stories/{story['id']}", headers=other)
    texts = [
        b["config"]["text"]
        for c in read.json()["document"]["chapters"]
        for b in c["blocks"]
    ]
    assert texts == ["draft only"]
    assert read.json()["can_edit"] is False
    assert (await client.get(draft_url, headers=people["admin"])).status_code == 200


async def test_only_the_owner_or_an_admin_writes(client: AsyncClient, people):
    owner, other = people["owner"], people["other"]
    story = await _story(client, owner)
    sid = story["id"]

    # Unpublished: another editor can't see it at all.
    assert (await _save(client, other, story, [])).status_code == 404
    assert (await client.delete(f"/stories/{sid}", headers=other)).status_code == 404

    await client.patch(
        f"/stories/{sid}", json={"visibility": "internal"}, headers=owner
    )
    await _publish(client, owner, sid)
    for resp in (
        await _save(client, other, story, []),
        await client.patch(f"/stories/{sid}", json={"title": "x"}, headers=other),
        await _publish(client, other, sid),
        await client.post(f"/stories/{sid}/discard", headers=other),
        await client.delete(f"/stories/{sid}", headers=other),
    ):
        assert resp.status_code == 403, resp.text

    renamed = await client.patch(
        f"/stories/{sid}", json={"title": "Renamed"}, headers=people["admin"]
    )
    assert renamed.status_code == 200 and renamed.json()["title"] == "Renamed"


async def test_unknown_block_on_write_is_refused(client: AsyncClient, people):
    story = await _story(client, people["owner"])
    for block in (
        {"id": str(uuid.uuid4()), "type": "video", "v": 1, "config": {}},
        {"id": str(uuid.uuid4()), "type": "markdown", "v": 2, "config": {"text": "x"}},
        {
            "id": str(uuid.uuid4()),
            "type": "markdown",
            "v": 1,
            "config": {"markdown": "x"},
        },
        {
            "id": str(uuid.uuid4()),
            "type": "markdown",
            "v": 1,
            "config": {"text": "x" * 20_001},
        },
    ):
        resp = await _save(client, people["owner"], story, [_chapter(blocks=[block])])
        assert resp.status_code == 422, (block, resp.text)


async def test_stored_unknown_block_survives_a_save(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    story = await _story(client, owner)
    chapter_id = str(uuid.uuid4())
    first, last = _block("first"), _block("last")
    story = await _saved(
        client, owner, story, [_chapter(blocks=[first, last], chapter_id=chapter_id)]
    )
    future = {"id": str(uuid.uuid4()), "type": "video", "v": 3, "config": {"url": "x"}}
    stored = await test_db_session.scalar(
        select(Story.draft).where(Story.id == uuid.UUID(story["id"]))
    )
    stored["chapters"][0]["blocks"].insert(1, future)
    await test_db_session.execute(
        update(Story).where(Story.id == uuid.UUID(story["id"])).values(draft=stored)
    )
    await test_db_session.commit()

    draft = (await client.get(f"/stories/{story['id']}/draft", headers=owner)).json()
    shown = draft["document"]["chapters"][0]["blocks"]
    assert [b["config"]["text"] for b in shown] == ["first", "last"]

    edited = {**last, "config": {"text": "last, edited"}}
    await _saved(
        client, owner, draft, [_chapter(blocks=[first, edited], chapter_id=chapter_id)]
    )

    test_db_session.expire_all()
    stored = await test_db_session.scalar(
        select(Story.draft).where(Story.id == uuid.UUID(story["id"]))
    )
    as_stored = [{**first, "title": None}, future, {**edited, "title": None}]
    assert stored["chapters"][0]["blocks"] == as_stored


async def test_scene_on_a_map_the_editor_cannot_read_is_refused(
    client: AsyncClient, people
):
    hidden = await _map(client, people["other"])
    story = await _story(client, people["owner"])
    resp = await _save(client, people["owner"], story, [_chapter(hidden)])
    assert resp.status_code == 422, resp.text
    detail = _detail(resp)
    assert detail["code"] == "story_maps_not_found" and detail["map_ids"] == [hidden]
    missing = str(uuid.uuid4())
    resp = await _save(client, people["owner"], story, [_chapter(missing)])
    assert resp.status_code == 422 and _detail(resp)["map_ids"] == [missing]


async def test_a_save_keeps_a_scene_the_editor_can_no_longer_read(
    client: AsyncClient, people, test_db_session
):
    owner, other = people["owner"], people["other"]
    their_map = await _map(client, other, "internal")
    story = await _story(client, owner)
    chapter_id = str(uuid.uuid4())
    story = await _saved(
        client, owner, story, [_chapter(their_map, chapter_id=chapter_id)]
    )
    await _set_map_visibility(client, other, their_map, "private")

    draft = (await client.get(f"/stories/{story['id']}/draft", headers=owner)).json()
    (chapter,) = draft["document"]["chapters"]
    assert chapter["scene"] is None and chapter["scene_hidden"] is True

    kept = await _saved(client, owner, draft, [{**chapter, "title": "Renamed"}])
    test_db_session.expire_all()
    stored = await test_db_session.scalar(
        select(Story.draft).where(Story.id == uuid.UUID(story["id"]))
    )
    assert stored["chapters"][0]["scene"]["map_id"] == their_map
    assert stored["chapters"][0]["title"] == "Renamed"

    removed = {**chapter, "scene_hidden": False}
    await _saved(client, owner, kept, [removed])
    test_db_session.expire_all()
    stored = await test_db_session.scalar(
        select(Story.draft).where(Story.id == uuid.UUID(story["id"]))
    )
    assert stored["chapters"][0]["scene"] is None


async def test_stale_revision_is_refused(client: AsyncClient, people):
    story = await _story(client, people["owner"])
    await _saved(client, people["owner"], story, [_chapter()])
    stale = await _save(client, people["owner"], story, [])
    assert stale.status_code == 409
    assert _detail(stale)["code"] == "stale_revision"


async def test_discard_reverts_to_the_published_document(client: AsyncClient, people):
    owner = people["owner"]
    story = await _story(client, owner)
    story = await _saved(client, owner, story, [_chapter(blocks=[_block("published")])])
    await _publish(client, owner, story["id"])
    await _saved(client, owner, story, [_chapter(blocks=[_block("scratch")])])

    reverted = await client.post(f"/stories/{story['id']}/discard", headers=owner)

    assert reverted.status_code == 200, reverted.text
    texts = [
        b["config"]["text"]
        for c in reverted.json()["document"]["chapters"]
        for b in c["blocks"]
    ]
    assert texts == ["published"]


async def test_deleting_a_map_drops_the_scene_and_keeps_the_text(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    map_id = await _map(client, owner)
    story = await _story(client, owner)
    await _saved(client, owner, story, [_chapter(map_id, blocks=[_block("kept")])])
    rows = await test_db_session.scalars(
        select(StoryMap.map_id).where(StoryMap.story_id == uuid.UUID(story["id"]))
    )
    assert [str(r) for r in rows] == [map_id]

    assert (await client.delete(f"/maps/{map_id}", headers=owner)).status_code == 204

    draft = (await client.get(f"/stories/{story['id']}/draft", headers=owner)).json()
    (chapter,) = draft["document"]["chapters"]
    assert chapter["scene"] is None
    assert chapter["blocks"][0]["config"]["text"] == "kept"
    published = await _publish(client, owner, story["id"])
    assert published.status_code == 200, published.text
    assert published.json()["document"]["chapters"][0]["scene"] is None


async def test_duplicate_copies_chapters_and_drops_unreadable_scenes(
    client: AsyncClient, people
):
    owner, other = people["owner"], people["other"]
    shared_map = await _map(client, owner, "internal")
    own_map = await _map(client, owner)
    story = await _story(client, owner)
    await _saved(
        client,
        owner,
        story,
        [
            _chapter(shared_map, blocks=[_block("one")]),
            _chapter(own_map, blocks=[_block("two")]),
        ],
    )
    await client.patch(
        f"/stories/{story['id']}", json={"visibility": "internal"}, headers=owner
    )
    assert (await _publish(client, owner, story["id"])).status_code == 409
    await client.patch(
        f"/stories/{story['id']}", json={"visibility": "private"}, headers=owner
    )

    own_copy = await client.post(f"/stories/{story['id']}/duplicate", headers=owner)
    assert own_copy.status_code == 201, own_copy.text
    chapters = own_copy.json()["document"]["chapters"]
    assert [c["scene"]["map_id"] for c in chapters] == [shared_map, own_map]
    assert own_copy.json()["visibility"] == "private"

    assert (
        await client.post(f"/stories/{story['id']}/duplicate", headers=other)
    ).status_code == 404

    await _set_map_visibility(client, owner, own_map, "internal")
    await client.patch(
        f"/stories/{story['id']}", json={"visibility": "internal"}, headers=owner
    )
    assert (await _publish(client, owner, story["id"])).status_code == 200
    await _set_map_visibility(client, owner, own_map, "private")

    their_copy = await client.post(f"/stories/{story['id']}/duplicate", headers=other)
    assert their_copy.status_code == 201, their_copy.text
    chapters = their_copy.json()["document"]["chapters"]
    assert [b["config"]["text"] for c in chapters for b in c["blocks"]] == [
        "one",
        "two",
    ]
    assert chapters[0]["scene"]["map_id"] == shared_map
    assert chapters[1]["scene"] is None and chapters[1]["scene_hidden"] is False


async def test_delete_removes_the_story(client: AsyncClient, people):
    story = await _story(client, people["owner"])
    resp = await client.delete(f"/stories/{story['id']}", headers=people["owner"])
    assert resp.status_code == 204
    assert (
        await client.get(f"/stories/{story['id']}", headers=people["owner"])
    ).status_code == 404
