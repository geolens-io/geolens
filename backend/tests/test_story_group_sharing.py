"""Owners and admins share stories with sharing groups through
PUT /stories/{id}/groups/."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from fastapi import HTTPException

from app.modules.auth import groups as group_service
from app.modules.auth.models import User
from app.modules.auth.service import get_user_identity
from app.modules.catalog.authorization import check_map_access, groups_lacking_maps
from app.modules.catalog.group_access import change_group_access
from app.modules.catalog.maps.models import Map
from app.modules.embed_tokens.models import EmbedToken
from app.modules.embed_tokens.service import create_embed_token
from app.modules.catalog.stories.groups import unshare_group_stories
from app.modules.catalog.stories.models import Story
from tests.factories import create_dataset, create_user
from tests.test_dataset_group_grants import _new_group
from tests.test_map_group_sharing import _blocked_or_done
from tests.test_map_link_preview_3018 import public_app_url  # noqa: F401
from tests.test_stories import _chapter, _detail, _map, _publish, _saved, _story
from tests.test_story_assets import _image, _image_block, _uploaded

pytestmark = pytest.mark.anyio


async def _share(client: AsyncClient, story_id, group_ids: list[str], headers, **extra):
    return await client.put(
        f"/stories/{story_id}/groups/",
        json={"group_ids": group_ids, **extra},
        headers=headers,
    )


async def _stored(session, model, row_id) -> str:
    session.expire_all()
    return await session.scalar(
        select(model.visibility).where(model.id == uuid.UUID(str(row_id)))
    )


async def _listed(client: AsyncClient, headers) -> set[str]:
    resp = await client.get("/stories/?limit=200", headers=headers)
    assert resp.status_code == 200, resp.text
    return {story["id"] for story in resp.json()["stories"]}


@pytest.fixture
async def owned(client: AsyncClient, admin_auth_header: dict):
    """A private story, published with a cover and an image, owned by an
    editor who is in group ``mine`` with another editor; ``other`` is a group
    the owner isn't in, and ``outsider`` is in no group."""
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    member, member_id = await create_user(client, admin_auth_header, "editor")
    outsider, _ = await create_user(client, admin_auth_header, "editor")
    story = await _story(client, owner)
    image = await _uploaded(client, owner, story["id"])
    cover = await _uploaded(client, owner, story["id"])
    await _saved(client, owner, story, [_chapter(blocks=[_image_block(image["id"])])])
    patched = await client.patch(
        f"/stories/{story['id']}", json={"cover_asset_id": cover["id"]}, headers=owner
    )
    assert patched.status_code == 200, patched.text
    assert (await _publish(client, owner, story["id"])).status_code == 200
    return {
        "story": story["id"],
        "images": [image["id"], cover["id"]],
        "owner": owner,
        "owner_id": owner_id,
        "member": member,
        "member_id": member_id,
        "outsider": outsider,
        "mine": await _new_group(client, admin_auth_header, [owner_id, member_id]),
        "other": await _new_group(client, admin_auth_header, []),
    }


async def _reads(client: AsyncClient, owned, headers) -> dict[str, object]:
    story_id = owned["story"]
    return {
        "story": (
            await client.get(f"/stories/{story_id}", headers=headers)
        ).status_code,
        "listed": story_id in await _listed(client, headers),
        "images": [
            (await _image(client, headers, story_id, asset_id)).status_code
            for asset_id in owned["images"]
        ],
    }


_READER = {"story": 200, "listed": True, "images": [200, 200]}
_STRANGER = {"story": 404, "listed": False, "images": [404, 404]}


async def test_members_read_the_story_its_listing_and_images_and_others_get_404(
    client: AsyncClient, owned, test_db_session
):
    assert await _reads(client, owned, owned["member"]) == _STRANGER

    shared = await _share(client, owned["story"], [owned["mine"]], owned["owner"])

    assert shared.status_code == 200, shared.text
    assert shared.json() == {
        "visibility": "restricted",
        "groups": [{"id": owned["mine"], "name": shared.json()["groups"][0]["name"]}],
        "shared_map_ids": [],
    }
    assert await _stored(test_db_session, Story, owned["story"]) == "restricted"
    assert await _reads(client, owned, owned["member"]) == _READER
    assert await _reads(client, owned, owned["outsider"]) == _STRANGER
    assert await _reads(client, owned, {}) == _STRANGER

    unshared = await _share(client, owned["story"], [], owned["owner"])

    assert unshared.json()["visibility"] == "private"
    assert await _reads(client, owned, owned["member"]) == _STRANGER


async def test_leaving_the_group_ends_a_members_read(
    client: AsyncClient, admin_auth_header: dict, owned
):
    assert (
        await _share(client, owned["story"], [owned["mine"]], owned["owner"])
    ).is_success
    assert await _reads(client, owned, owned["member"]) == _READER

    removed = await client.delete(
        f"/admin/groups/{owned['mine']}/members/{owned['member_id']}",
        headers=admin_auth_header,
    )

    assert removed.status_code == 204, removed.text
    assert await _reads(client, owned, owned["member"]) == _STRANGER


async def test_an_unpublished_restricted_story_stays_with_its_editors(
    client: AsyncClient, owned
):
    story = await _story(client, owned["owner"])
    shared = await _share(client, story["id"], [owned["mine"]], owned["owner"])

    assert shared.json()["visibility"] == "restricted"
    member_read = await client.get(f"/stories/{story['id']}", headers=owned["member"])
    assert member_read.status_code == 404


async def test_an_owner_shares_only_with_their_own_groups_and_an_admin_with_any(
    client: AsyncClient, admin_auth_header: dict, owned, test_db_session
):
    refused = await _share(client, owned["story"], [owned["other"]], owned["owner"])

    assert refused.status_code == 403, refused.text
    assert await _stored(test_db_session, Story, owned["story"]) == "private"

    by_admin = await _share(client, owned["story"], [owned["other"]], admin_auth_header)

    assert by_admin.status_code == 200, by_admin.text
    assert [g["id"] for g in by_admin.json()["groups"]] == [owned["other"]]


async def test_a_reader_cannot_change_the_groups_and_a_stranger_gets_404(
    client: AsyncClient, owned
):
    assert (
        await _share(client, owned["story"], [owned["mine"]], owned["owner"])
    ).is_success

    reader = await _share(client, owned["story"], [], owned["member"])
    stranger = await _share(client, owned["story"], [], owned["outsider"])
    unknown = await _share(client, owned["story"], [str(uuid.uuid4())], owned["owner"])

    assert reader.status_code == 403, reader.text
    assert stranger.status_code == 404, stranger.text
    assert unknown.status_code == 404, unknown.text


async def test_only_the_owner_and_admins_see_the_groups(
    client: AsyncClient, admin_auth_header: dict, owned
):
    assert (
        await _share(client, owned["story"], [owned["mine"]], owned["owner"])
    ).is_success
    url = f"/stories/{owned['story']}"

    owner_draft = await client.get(f"{url}/draft", headers=owned["owner"])
    admin_draft = await client.get(f"{url}/draft", headers=admin_auth_header)
    member_read = await client.get(url, headers=owned["member"])
    member_draft = await client.get(f"{url}/draft", headers=owned["member"])

    assert [g["id"] for g in owner_draft.json()["groups"]] == [owned["mine"]]
    assert [g["id"] for g in admin_draft.json()["groups"]] == [owned["mine"]]
    assert "groups" not in member_read.json()
    assert member_draft.status_code == 403


async def test_making_a_shared_story_private_keeps_it_restricted(
    client: AsyncClient, owned
):
    url = f"/stories/{owned['story']}"
    internal = await client.patch(
        url, json={"visibility": "internal"}, headers=owned["owner"]
    )
    assert internal.status_code == 200, internal.text

    shared = await _share(client, owned["story"], [owned["mine"]], owned["owner"])

    assert shared.json()["visibility"] == "internal"
    assert (await client.get(url, headers=owned["outsider"])).status_code == 200

    narrowed = await client.patch(
        url, json={"visibility": "private"}, headers=owned["owner"]
    )

    assert narrowed.json()["visibility"] == "restricted"
    assert (await client.get(url, headers=owned["member"])).status_code == 200
    assert (await client.get(url, headers=owned["outsider"])).status_code == 404


@pytest.mark.parametrize(
    ("second_group", "after", "member_reads"),
    [(False, "private", _STRANGER), (True, "restricted", _READER)],
    ids=["its-only-group", "one-of-two-groups"],
)
async def test_deleting_a_group_makes_the_story_private_only_when_it_was_the_last(
    client: AsyncClient,
    admin_auth_header: dict,
    owned,
    test_db_session,
    second_group,
    after,
    member_reads,
):
    groups = [owned["mine"]]
    if second_group:
        groups.append(await _new_group(client, admin_auth_header, [owned["member_id"]]))
    shared = await _share(client, owned["story"], groups, admin_auth_header)
    assert shared.status_code == 200, shared.text

    deleted = await client.delete(
        f"/admin/groups/{owned['mine']}", headers=admin_auth_header
    )

    assert deleted.status_code == 204, deleted.text
    assert await _stored(test_db_session, Story, owned["story"]) == after
    assert await _reads(client, owned, owned["member"]) == member_reads
    draft = await client.get(f"/stories/{owned['story']}/draft", headers=owned["owner"])
    assert [g["id"] for g in draft.json()["groups"]] == groups[1:]


async def test_deleting_a_storys_last_two_groups_at_once_leaves_it_private(
    client: AsyncClient, admin_auth_header: dict, owned, test_db_session
):
    second = await _new_group(client, admin_auth_header, [owned["member_id"]])
    shared = await _share(
        client, owned["story"], [owned["mine"], second], admin_auth_header
    )
    assert shared.status_code == 200, shared.text
    factory = async_sessionmaker(test_db_session.bind, expire_on_commit=False)

    async def delete(session, group_id: str) -> None:
        group_id = uuid.UUID(group_id)

        async def change():
            await unshare_group_stories(session, group_id)
            return await group_service.delete_group(session, group_id, id_limit=10)

        await change_group_access(session, group_id, change, narrowing=True)

    async with factory() as first, factory() as other:
        await delete(first, owned["mine"])
        deleting = asyncio.create_task(delete(other, second))
        await _blocked_or_done(first, deleting)
        await first.commit()
        await deleting
        await other.commit()

    assert await _stored(test_db_session, Story, owned["story"]) == "private"


@pytest.fixture
async def scened(client: AsyncClient, admin_auth_header: dict, owned):
    """``owned`` with a draft whose scene is on the owner's private map."""
    owner = owned["owner"]
    draft = (await client.get(f"/stories/{owned['story']}/draft", headers=owner)).json()
    mine = await _map(client, owner)
    owned["map"] = mine
    await _saved(client, owner, draft, [_chapter(mine)])
    return owned


async def test_sharing_a_published_story_past_a_scene_map_is_refused_naming_it(
    client: AsyncClient, scened, test_db_session
):
    owner = scened["owner"]
    assert (await _publish(client, owner, scened["story"])).status_code == 200

    refused = await _share(client, scened["story"], [scened["mine"]], owner)

    assert refused.status_code == 409, refused.text
    detail = _detail(refused)
    assert detail["code"] == "maps_narrower_than_story"
    assert detail["maps"] == [
        {"id": scened["map"], "name": detail["maps"][0]["name"], "can_share": True}
    ]
    assert detail["unreadable_maps"] == 0
    assert await _stored(test_db_session, Story, scened["story"]) == "private"
    assert await _stored(test_db_session, Map, scened["map"]) == "private"

    confirmed = await _share(
        client, scened["story"], [scened["mine"]], owner, confirm="share_maps"
    )

    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["shared_map_ids"] == [scened["map"]]
    assert await _stored(test_db_session, Map, scened["map"]) == "restricted"
    read = await client.get(f"/stories/{scened['story']}", headers=scened["member"])
    assert read.json()["document"]["chapters"][0]["scene_hidden"] is False


async def test_publishing_a_restricted_story_past_a_scene_map_is_refused_until_shared(
    client: AsyncClient, scened, test_db_session
):
    owner = scened["owner"]
    shared = await _share(client, scened["story"], [scened["mine"]], owner)
    assert shared.status_code == 200, shared.text

    refused = await _publish(client, owner, scened["story"])

    assert refused.status_code == 409, refused.text
    detail = _detail(refused)
    assert [(m["id"], m["can_share"]) for m in detail["maps"]] == [
        (scened["map"], True)
    ]
    member_read = await client.get(
        f"/stories/{scened['story']}", headers=scened["member"]
    )
    assert member_read.json()["document"]["chapters"][0]["scene"] is None

    draft = (
        await client.get(f"/stories/{scened['story']}/draft", headers=owner)
    ).json()
    published = await client.post(
        f"/stories/{scened['story']}/publish",
        json={"revision": draft["revision"], "confirm": "share_maps"},
        headers=owner,
    )

    assert published.status_code == 200, published.text
    assert await _stored(test_db_session, Map, scened["map"]) == "restricted"
    member_read = await client.get(
        f"/stories/{scened['story']}", headers=scened["member"]
    )
    assert (
        member_read.json()["document"]["chapters"][0]["scene"]["map_id"]
        == (scened["map"])
    )


async def test_a_map_the_author_does_not_own_is_named_and_not_shared(
    client: AsyncClient, admin_auth_header: dict, scened, test_db_session
):
    owner = scened["owner"]
    theirs = await _map(client, admin_auth_header)
    await _set_reader(client, admin_auth_header, theirs, scened["owner_id"])
    draft = (
        await client.get(f"/stories/{scened['story']}/draft", headers=owner)
    ).json()
    await _saved(client, owner, draft, [_chapter(scened["map"]), _chapter(theirs)])
    assert (await _share(client, scened["story"], [scened["mine"]], owner)).is_success

    draft = (
        await client.get(f"/stories/{scened['story']}/draft", headers=owner)
    ).json()
    refused = await client.post(
        f"/stories/{scened['story']}/publish",
        json={"revision": draft["revision"], "confirm": "share_maps"},
        headers=owner,
    )

    assert refused.status_code == 409, refused.text
    assert sorted(
        (m["id"], m["can_share"]) for m in _detail(refused)["maps"]
    ) == sorted([(scened["map"], True), (theirs, False)])
    # Nothing is shared while a map the author can't fix still blocks.
    assert await _stored(test_db_session, Map, scened["map"]) == "private"


async def _set_reader(client, admin, map_id, user_id) -> None:
    """Let ``user_id`` read the admin's ``map_id`` through a group of their own."""
    group = await _new_group(client, admin, [user_id])
    shared = await client.put(
        f"/maps/{map_id}/groups/", json={"group_ids": [group]}, headers=admin
    )
    assert shared.status_code == 200, shared.text


async def test_a_blocking_map_the_publisher_cannot_read_is_counted_not_named(
    client: AsyncClient, owned
):
    owner, theirs = owned["owner"], await _map(client, owned["outsider"], "internal")
    story = await _story(client, owner)
    await _saved(client, owner, story, [_chapter(theirs)])
    assert (await _publish(client, owner, story["id"])).status_code == 200
    narrowed = await client.put(
        f"/maps/{theirs}", json={"visibility": "private"}, headers=owned["outsider"]
    )
    assert narrowed.status_code == 200, narrowed.text

    refused = await _share(
        client, story["id"], [owned["mine"]], owner, confirm="share_maps"
    )

    assert refused.status_code == 409, refused.text
    assert _detail(refused)["maps"] == []
    assert _detail(refused)["unreadable_maps"] == 1


@pytest.mark.usefixtures("public_app_url")
async def test_group_names_stay_out_of_the_link_preview(
    client: AsyncClient, admin_auth_header: dict, owned
):
    name = f"Secret planning {uuid.uuid4().hex[:6]}"
    renamed = await client.patch(
        f"/admin/groups/{owned['mine']}", json={"name": name}, headers=admin_auth_header
    )
    assert renamed.status_code == 200, renamed.text
    url = f"/stories/{owned['story']}"
    public = await client.patch(
        url, json={"visibility": "public"}, headers=owned["owner"]
    )
    assert public.status_code == 200, public.text
    assert (
        await _share(client, owned["story"], [owned["mine"]], owned["owner"])
    ).is_success

    preview = await client.get(f"{url}/link-preview")
    listing = await client.get("/stories/?limit=200")
    read = await client.get(url)

    assert preview.status_code == 200, preview.text
    for body in (preview.text, listing.text, read.text):
        assert name not in body


async def test_sharing_a_private_map_from_a_publish_revokes_its_embed_token(
    client: AsyncClient, scened, test_db_session
):
    owner_id = uuid.UUID(scened["owner_id"])
    dataset = await create_dataset(test_db_session, created_by=owner_id)
    await test_db_session.commit()
    added = await client.post(
        f"/maps/{scened['map']}/layers",
        json={"dataset_id": str(dataset.id)},
        headers=scened["owner"],
    )
    assert added.status_code == 201, added.text
    token, _ = await create_embed_token(
        test_db_session, uuid.UUID(scened["map"]), owner_id
    )
    token_id = token.id
    await test_db_session.commit()
    shared = await _share(client, scened["story"], [scened["mine"]], scened["owner"])
    assert shared.status_code == 200, shared.text
    draft = (
        await client.get(f"/stories/{scened['story']}/draft", headers=scened["owner"])
    ).json()

    published = await client.post(
        f"/stories/{scened['story']}/publish",
        json={"revision": draft["revision"], "confirm": "share_maps"},
        headers=scened["owner"],
    )

    assert published.status_code == 200, published.text
    test_db_session.expire_all()
    assert not await test_db_session.scalar(
        select(EmbedToken.is_active).where(EmbedToken.id == token_id)
    )


async def test_a_lacking_group_the_publisher_is_not_in_cannot_be_shared(
    client: AsyncClient, admin_auth_header: dict, scened
):
    theirs = await _new_group(client, admin_auth_header, [scened["member_id"]])
    # Unpublished, so the admin's share isn't reach-checked yet.
    story = await _story(client, scened["owner"])
    await _saved(client, scened["owner"], story, [_chapter(scened["map"])])
    assert (await _share(client, story["id"], [theirs], admin_auth_header)).is_success

    refused = await _publish(client, scened["owner"], story["id"])

    assert refused.status_code == 409, refused.text
    assert [(m["id"], m["can_share"]) for m in _detail(refused)["maps"]] == [
        (scened["map"], False)
    ]


async def test_an_owner_who_left_a_group_keeps_its_grant(
    client: AsyncClient, admin_auth_header: dict, owned
):
    assert (
        await _share(client, owned["story"], [owned["mine"]], owned["owner"])
    ).is_success
    left = await client.delete(
        f"/admin/groups/{owned['mine']}/members/{owned['owner_id']}",
        headers=admin_auth_header,
    )
    assert left.status_code == 204, left.text
    another = await _new_group(client, admin_auth_header, [owned["owner_id"]])

    kept = await _share(
        client, owned["story"], [owned["mine"], another], owned["owner"]
    )

    assert kept.status_code == 200, kept.text
    assert {g["id"] for g in kept.json()["groups"]} == {owned["mine"], another}


async def test_a_never_published_restricted_story_stays_hidden_from_members(
    client: AsyncClient, admin_auth_header: dict, owned
):
    owner, member = owned["owner"], owned["member"]
    outsider_map = await _map(client, owned["outsider"], "internal")
    member_map = await _map(client, member, "internal")
    story = await _story(client, owner, title=f"Unpublished {uuid.uuid4().hex[:6]}")
    cover = await _uploaded(client, owner, story["id"])
    patched = await client.patch(
        f"/stories/{story['id']}", json={"cover_asset_id": cover["id"]}, headers=owner
    )
    assert patched.status_code == 200, patched.text
    await _saved(client, owner, story, [_chapter(member_map), _chapter(outsider_map)])
    assert (await _share(client, story["id"], [owned["mine"]], owner)).is_success

    async def map_stories(map_id, headers) -> dict:
        resp = await client.get(f"/maps/{map_id}/stories/", headers=headers)
        assert resp.status_code == 200, resp.text
        return resp.json()

    assert story["id"] not in await _listed(client, member)
    assert (await _image(client, member, story["id"], cover["id"])).status_code == 404
    assert await map_stories(member_map, member) == {"stories": [], "hidden_count": 1}
    assert await map_stories(outsider_map, owned["outsider"]) == {
        "stories": [],
        "hidden_count": 1,
    }

    assert (await _publish(client, owner, story["id"])).status_code == 200

    assert story["id"] in await _listed(client, member)
    assert (await map_stories(member_map, member))["stories"] == [
        {"id": story["id"], "title": story["title"]}
    ]


@pytest.fixture
async def kinds(client: AsyncClient, admin_auth_header: dict):
    """A map owner and one editor of each kind the map audience tells apart."""
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    _, admin_id = await create_user(client, admin_auth_header, "admin")
    _, plain_id = await create_user(client, admin_auth_header, "editor")
    _, granted_id = await create_user(client, admin_auth_header, "editor")
    return {
        "headers": owner,
        "owner_id": owner_id,
        "map_group": await _new_group(
            client, admin_auth_header, [owner_id, granted_id]
        ),
        "members": {
            "owner": owner_id,
            "admin": admin_id,
            "plain": plain_id,
            "granted": granted_id,
        },
    }


@pytest.mark.parametrize("visibility", ["private", "restricted", "internal", "public"])
async def test_groups_lacking_maps_agrees_with_the_map_guard(
    client: AsyncClient, admin_auth_header: dict, kinds, test_db_session, visibility
):
    map_id = await _map(client, kinds["headers"])
    if visibility == "restricted":
        shared = await client.put(
            f"/maps/{map_id}/groups/",
            json={"group_ids": [kinds["map_group"]]},
            headers=kinds["headers"],
        )
        assert shared.status_code == 200, shared.text
    elif visibility != "private":
        made = await client.put(
            f"/maps/{map_id}", json={"visibility": visibility}, headers=kinds["headers"]
        )
        assert made.status_code == 200, made.text
    map_obj = await test_db_session.get(Map, uuid.UUID(map_id))

    for kind, user_id in kinds["members"].items():
        group = uuid.UUID(await _new_group(client, admin_auth_header, [user_id]))
        lacking = await groups_lacking_maps(test_db_session, {map_obj.id}, {group})
        identity = await get_user_identity(test_db_session, uuid.UUID(user_id))
        try:
            await check_map_access(test_db_session, map_obj, identity)
            reads = True
        except HTTPException:
            reads = False
        assert (group in lacking.get(map_obj.id, set())) is not reads, kind


@pytest.mark.parametrize("status", ["pending", "suspended", "deactivated"])
async def test_a_member_who_cannot_sign_in_does_not_lack_a_map(
    client: AsyncClient, admin_auth_header: dict, kinds, test_db_session, status
):
    map_id = uuid.UUID(await _map(client, kinds["headers"]))
    user_id = uuid.UUID(kinds["members"]["plain"])
    group = uuid.UUID(await _new_group(client, admin_auth_header, [str(user_id)]))
    assert await groups_lacking_maps(test_db_session, {map_id}, {group}) == {
        map_id: {group}
    }
    # The schema keeps is_active equal to status = 'active'.
    user = await test_db_session.get(User, user_id)
    user.status, user.is_active = status, False
    await test_db_session.commit()

    assert await groups_lacking_maps(test_db_session, {map_id}, {group}) == {}
