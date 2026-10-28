"""Stories through the real guards: reads, draft saves, publishing and copies."""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from fastapi import HTTPException
from sqlalchemy import delete as sa_delete
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


async def _discard(client, headers, story_id: str, revision: int | None = None):
    """Discard at the current draft revision unless one is given."""
    if revision is None:
        draft = await client.get(f"/stories/{story_id}/draft", headers=headers)
        revision = draft.json()["revision"] if draft.status_code == 200 else 0
    return await client.post(
        f"/stories/{story_id}/discard", json={"revision": revision}, headers=headers
    )


async def _publish(client, headers, story_id: str, revision: int | None = None):
    """Publish at the current draft revision unless one is given."""
    if revision is None:
        draft = await client.get(f"/stories/{story_id}/draft", headers=headers)
        revision = draft.json()["revision"] if draft.status_code == 200 else 0
    return await client.post(
        f"/stories/{story_id}/publish", json={"revision": revision}, headers=headers
    )


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
    anon = await client.get("/stories/")
    assert story["id"] not in {s["id"] for s in anon.json()["stories"]}
    assert (await client.get(url)).status_code == 404


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


async def test_narrowing_visibility_is_allowed_after_a_map_narrows(
    client: AsyncClient, people
):
    owner = people["owner"]
    map_id = await _map(client, owner, "public")
    story = await _story(client, owner)
    await _saved(client, owner, story, [_chapter(map_id)])
    url = f"/stories/{story['id']}"
    await client.patch(url, json={"visibility": "public"}, headers=owner)
    assert (await _publish(client, owner, story["id"])).status_code == 200
    await _set_map_visibility(client, owner, map_id, "private")

    for visibility in ("internal", "private"):
        narrowed = await client.patch(
            url, json={"visibility": visibility}, headers=owner
        )
        assert narrowed.status_code == 200, narrowed.text
    widened = await client.patch(url, json={"visibility": "internal"}, headers=owner)
    assert widened.status_code == 409, widened.text


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
    # The owner can't read the map, so it's only counted.
    assert _detail(refused)["maps"] == []
    assert _detail(refused)["unreadable_maps"] == 1


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
        await _discard(client, other, sid),
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

    reverted = await _discard(client, owner, story["id"])

    assert reverted.status_code == 200, reverted.text
    texts = [
        b["config"]["text"]
        for c in reverted.json()["document"]["chapters"]
        for b in c["blocks"]
    ]
    assert texts == ["published"]


async def test_discard_points_story_maps_back_at_the_published_maps(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    kept_map, scratch_map = await _map(client, owner), await _map(client, owner)
    story = await _story(client, owner)
    story = await _saved(client, owner, story, [_chapter(kept_map)])
    assert (await _publish(client, owner, story["id"])).status_code == 200
    await _saved(client, owner, story, [_chapter(kept_map), _chapter(scratch_map)])

    async def listed() -> set[str]:
        rows = await test_db_session.scalars(
            select(StoryMap.map_id).where(StoryMap.story_id == uuid.UUID(story["id"]))
        )
        return {str(r) for r in rows}

    assert await listed() == {kept_map, scratch_map}
    assert (await _discard(client, owner, story["id"])).status_code == 200
    assert await listed() == {kept_map}


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


async def test_a_reader_copies_only_the_published_document(client: AsyncClient, people):
    owner, other = people["owner"], people["other"]
    story = await _story(client, owner)
    story = await _saved(client, owner, story, [_chapter(blocks=[_block("published")])])
    await client.patch(
        f"/stories/{story['id']}", json={"visibility": "internal"}, headers=owner
    )
    assert (await _publish(client, owner, story["id"])).status_code == 200
    await _saved(client, owner, story, [_chapter(blocks=[_block("unpublished")])])

    def texts(resp) -> list[str]:
        return [
            b["config"]["text"]
            for c in resp.json()["document"]["chapters"]
            for b in c["blocks"]
        ]

    theirs = await client.post(f"/stories/{story['id']}/duplicate", headers=other)
    assert theirs.status_code == 201, theirs.text
    assert texts(theirs) == ["published"]
    mine = await client.post(f"/stories/{story['id']}/duplicate", headers=owner)
    assert texts(mine) == ["unpublished"]


@pytest.fixture
def _restrict_public_visibility(monkeypatch):
    import app.core.persistent_config as pc

    class _AlwaysOn:
        async def get(self, _db):
            return True

    monkeypatch.setattr(pc, "RESTRICT_PUBLIC_VISIBILITY", _AlwaysOn())


async def test_restrict_public_visibility_stops_a_non_admin_making_a_story_public(
    client: AsyncClient, people, _restrict_public_visibility
):
    story = await _story(client, people["owner"])
    url = f"/stories/{story['id']}"

    refused = await client.patch(
        url, json={"visibility": "public"}, headers=people["owner"]
    )
    assert refused.status_code == 403, refused.text
    allowed = await client.patch(
        url, json={"visibility": "public"}, headers=people["admin"]
    )
    assert allowed.status_code == 200, allowed.text


async def test_publish_needs_the_current_revision(client: AsyncClient, people):
    owner = people["owner"]
    story = await _story(client, owner)
    await _saved(client, owner, story, [_chapter()])
    stale = await _publish(client, owner, story["id"], revision=story["revision"])
    assert stale.status_code == 409, stale.text
    assert _detail(stale)["code"] == "stale_revision"
    missing = await client.post(f"/stories/{story['id']}/publish", headers=owner)
    assert missing.status_code == 422


async def test_document_size_is_capped(client: AsyncClient, people):
    story = await _story(client, people["owner"])
    big = [_chapter(blocks=[_block("x" * 20_000)]) for _ in range(120)]
    resp = await _save(client, people["owner"], story, big)
    assert resp.status_code == 422, resp.text[:300]
    assert "too large" in resp.text


async def test_image_blocks_and_repeated_chapter_ids_are_refused(
    client: AsyncClient, people
):
    story = await _story(client, people["owner"])
    image = {
        "id": str(uuid.uuid4()),
        "type": "image",
        "v": 1,
        "asset_id": str(uuid.uuid4()),
        "config": {"alt": ""},
    }
    resp = await _save(client, people["owner"], story, [_chapter(blocks=[image])])
    assert resp.status_code == 422 and "image blocks" in resp.text
    twice = str(uuid.uuid4())
    resp = await _save(
        client,
        people["owner"],
        story,
        [_chapter(chapter_id=twice), _chapter(chapter_id=twice)],
    )
    assert resp.status_code == 422 and "unique" in resp.text


async def _store(session, story_id: str, **values) -> None:
    await session.execute(
        update(Story).where(Story.id == uuid.UUID(story_id)).values(**values)
    )
    await session.commit()


async def _stored_draft(session, story_id: str) -> dict:
    session.expire_all()
    return await session.scalar(
        select(Story.draft).where(Story.id == uuid.UUID(story_id))
    )


async def test_a_scene_this_server_cannot_parse_is_hidden_kept_and_reach_checked(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    private_map = await _map(client, owner)
    story = await _story(client, owner)
    chapter_id = str(uuid.uuid4())
    future_scene = {"map_id": private_map, "camera": {"orbit": 3}, "tour": [1]}
    draft = {
        "version": 1,
        "chapters": [
            {"id": chapter_id, "title": "T", "scene": future_scene, "blocks": []}
        ],
    }
    await _store(test_db_session, story["id"], draft=draft, visibility="public")

    read = await client.get(f"/stories/{story['id']}/draft", headers=owner)
    (chapter,) = read.json()["document"]["chapters"]
    assert chapter["scene"] is None and chapter["scene_hidden"] is True

    await _saved(client, owner, read.json(), [chapter])
    assert (await _stored_draft(test_db_session, story["id"]))["chapters"][0][
        "scene"
    ] == future_scene

    refused = await _publish(client, owner, story["id"])
    assert refused.status_code == 409, refused.text
    assert [m["id"] for m in _detail(refused)["maps"]] == [private_map]

    draft["chapters"][0]["scene"] = {"place": "somewhere"}
    await _store(test_db_session, story["id"], draft=draft)
    unplaced = await _publish(client, owner, story["id"])
    assert unplaced.status_code == 409
    assert _detail(unplaced)["code"] == "scenes_unreadable"


async def test_a_save_over_chapters_this_server_cannot_identify_is_refused(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    story = await _story(client, owner)
    for draft in (
        {"version": 1, "chapters": [{"id": "intro", "blocks": []}]},
        {"version": 2, "chapters": []},
    ):
        await _store(test_db_session, story["id"], draft=draft)
        current = (
            await client.get(f"/stories/{story['id']}/draft", headers=owner)
        ).json()
        resp = await _save(client, owner, current, [_chapter()])
        assert resp.status_code == 409, resp.text
        assert await _stored_draft(test_db_session, story["id"]) == draft


async def test_a_stored_restricted_story_reads_and_refuses_publishing(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    story = await _story(client, owner)
    await _store(test_db_session, story["id"], visibility="restricted")

    read = await client.get(f"/stories/{story['id']}", headers=owner)
    assert read.status_code == 200 and read.json()["visibility"] == "restricted"
    assert (
        await client.get(f"/stories/{story['id']}", headers=people["other"])
    ).status_code == 404
    refused = await _publish(client, owner, story["id"])
    assert refused.status_code == 409
    assert _detail(refused)["code"] == "visibility_unsupported"
    bad = await client.patch(
        f"/stories/{story['id']}", json={"visibility": "restricted"}, headers=owner
    )
    assert bad.status_code == 422


async def test_an_internal_story_cannot_publish_a_restricted_map(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    map_id = await _map(client, owner)
    story = await _story(client, owner)
    await _saved(client, owner, story, [_chapter(map_id)])
    # A restricted map reaches only its groups; the shape is all this check reads.
    from app.modules.catalog.maps.models import Map

    await test_db_session.execute(
        update(Map).where(Map.id == uuid.UUID(map_id)).values(visibility="restricted")
    )
    await test_db_session.commit()
    await client.patch(
        f"/stories/{story['id']}", json={"visibility": "internal"}, headers=owner
    )
    refused = await _publish(client, owner, story["id"])
    assert refused.status_code == 409, refused.text
    assert [m["id"] for m in _detail(refused)["maps"]] == [map_id]


async def test_an_admin_publishes_another_admins_private_story_by_the_owners_roles(
    client: AsyncClient, people
):
    owner_admin, _ = await create_user(client, people["admin"], "admin")
    their_map = await _map(client, people["other"])
    story = await _story(client, owner_admin)
    await _saved(client, owner_admin, story, [_chapter(their_map)])

    published = await _publish(client, people["admin"], story["id"])
    assert published.status_code == 200, published.text

    plain = await _story(client, people["owner"])
    await _saved(client, people["owner"], plain, [])
    # The owner isn't an admin, so an admin can't publish a map they can't read.
    plain_draft = (
        await client.get(f"/stories/{plain['id']}/draft", headers=people["admin"])
    ).json()
    await _saved(client, people["admin"], plain_draft, [_chapter(their_map)])
    refused = await _publish(client, people["admin"], plain["id"])
    assert refused.status_code == 409, refused.text
    assert [m["id"] for m in _detail(refused)["maps"]] == [their_map]


async def test_a_held_story_lock_answers_409(
    client: AsyncClient, people, test_db_session
):
    story = await _story(client, people["owner"])
    await test_db_session.execute(
        select(Story.id).where(Story.id == uuid.UUID(story["id"])).with_for_update()
    )
    try:
        resp = await _save(client, people["owner"], story, [])
        assert resp.status_code == 409, resp.text
        assert "in progress" in resp.text
    finally:
        await test_db_session.rollback()


async def test_the_lock_rechecks_the_writer_it_admitted(
    client: AsyncClient, people, test_db_session
):
    import app.core.db as db_module
    from app.modules.auth.models import User
    from app.modules.catalog.stories.service import (
        check_story_ownership,
        get_story,
        lock_story,
    )

    story = await _story(client, people["owner"])
    other_id = (await client.get("/auth/me", headers=people["other"])).json()["id"]
    async with db_module.async_session() as session:
        owner = await session.get(User, uuid.UUID(people["owner_id"]))
        loaded = await get_story(session, uuid.UUID(story["id"]))
        await check_story_ownership(session, loaded, owner)
        # Ownership moves after the guard admitted the writer.
        await _store(test_db_session, story["id"], created_by=uuid.UUID(other_id))
        with pytest.raises(HTTPException) as refused:
            await lock_story(session, uuid.UUID(story["id"]), owner)
        assert refused.value.status_code == 403


@pytest.mark.parametrize("published", [True, False])
async def test_a_stale_or_retried_discard_cannot_erase_a_newer_draft(
    client: AsyncClient, people, published
):
    owner = people["owner"]
    story = await _story(client, owner)
    story = await _saved(client, owner, story, [_chapter(blocks=[_block("base")])])
    if published:
        assert (await _publish(client, owner, story["id"])).status_code == 200
    stale_tab = story["revision"]
    newer = await _saved(client, owner, story, [_chapter(blocks=[_block("newer")])])

    stale = await _discard(client, owner, story["id"], revision=stale_tab)
    assert stale.status_code == 409, stale.text
    assert _detail(stale)["code"] == "stale_revision"

    done = await _discard(client, owner, story["id"], revision=newer["revision"])
    assert done.status_code == 200, done.text
    after = await _saved(
        client, owner, done.json(), [_chapter(blocks=[_block("later")])]
    )
    retried = await _discard(client, owner, story["id"], revision=newer["revision"])
    assert retried.status_code == 409, retried.text

    draft = (await client.get(f"/stories/{story['id']}/draft", headers=owner)).json()
    assert draft["revision"] == after["revision"]
    texts = [
        b["config"]["text"] for c in draft["document"]["chapters"] for b in c["blocks"]
    ]
    assert texts == ["later"]


async def test_discard_drops_scenes_on_deleted_maps_from_the_stored_draft(
    client: AsyncClient, people, test_db_session
):
    owner = people["owner"]
    map_id = await _map(client, owner)
    story = await _story(client, owner)
    story = await _saved(
        client, owner, story, [_chapter(map_id, blocks=[_block("kept")])]
    )
    assert (await _publish(client, owner, story["id"])).status_code == 200
    assert (await client.delete(f"/maps/{map_id}", headers=owner)).status_code == 204

    assert (await _discard(client, owner, story["id"])).status_code == 200

    (chapter,) = (await _stored_draft(test_db_session, story["id"]))["chapters"]
    assert chapter["scene"] is None
    assert chapter["blocks"][0]["config"]["text"] == "kept"


@pytest.fixture
async def demoted_in_the_lock_window(client: AsyncClient, people, monkeypatch):
    """An admin who owns a story, and a switch that turns them into an editor
    after the guard admits a write but before it takes the story lock."""
    import app.core.db as db_module
    from app.modules.auth.models import Role, UserRole
    from app.modules.catalog.stories import router as stories_router

    admin, admin_id = await create_user(client, people["admin"], "admin")
    real_lock = stories_router.lock_story
    armed = {"on": False}

    async def demote() -> None:
        async with db_module.async_session() as session:
            roles = {r.name: r.id for r in (await session.scalars(select(Role))).all()}
            await session.execute(
                sa_delete(UserRole).where(UserRole.user_id == uuid.UUID(admin_id))
            )
            session.add(UserRole(user_id=uuid.UUID(admin_id), role_id=roles["editor"]))
            await session.commit()

    async def lock_after_demotion(db, story_id, user):
        if armed["on"]:
            armed["on"] = False
            await demote()
        return await real_lock(db, story_id, user)

    monkeypatch.setattr(stories_router, "lock_story", lock_after_demotion)
    return admin, armed


async def test_a_write_uses_the_roles_rechecked_under_the_lock(
    client: AsyncClient, people, demoted_in_the_lock_window
):
    admin, armed = demoted_in_the_lock_window
    their_map = await _map(client, people["other"])
    story = await _story(client, admin)
    story = await _saved(client, admin, story, [_chapter(their_map)])
    assert (await _publish(client, admin, story["id"])).status_code == 200
    # Rendering: the response hides the scene the demoted owner can't read.
    armed["on"] = True
    renamed = await client.patch(
        f"/stories/{story['id']}", json={"title": "Renamed"}, headers=admin
    )
    assert renamed.status_code == 200, renamed.text
    (chapter,) = renamed.json()["document"]["chapters"]
    assert chapter["scene"] is None and chapter["scene_hidden"] is True


async def test_a_demoted_writer_cannot_add_a_map_they_lost(
    client: AsyncClient, people, demoted_in_the_lock_window
):
    admin, armed = demoted_in_the_lock_window
    their_map = await _map(client, people["other"])
    story = await _story(client, admin)

    # Admission: the scene's map is checked with the editor's roles.
    armed["on"] = True
    refused = await _save(client, admin, story, [_chapter(their_map)])
    assert refused.status_code == 422, refused.text
    assert _detail(refused)["code"] == "story_maps_not_found"


async def test_a_demoted_publisher_is_not_told_the_map_name(
    client: AsyncClient, people, demoted_in_the_lock_window
):
    admin, armed = demoted_in_the_lock_window
    their_map = await _map(client, people["other"])
    story = await _story(client, admin)
    await _saved(client, admin, story, [_chapter(their_map)])

    # Redaction: the owner, now an editor, can't read the map, so the private
    # story can't publish it and the refusal doesn't name it.
    armed["on"] = True
    refused = await _publish(client, admin, story["id"])
    assert refused.status_code == 409, refused.text
    assert _detail(refused)["maps"] == []
    assert _detail(refused)["unreadable_maps"] == 1
