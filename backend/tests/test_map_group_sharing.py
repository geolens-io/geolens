"""Owners and admins share maps with sharing groups through PUT /maps/{id}/groups/."""

from __future__ import annotations

import uuid
from typing import Literal

import pytest
import sqlalchemy as sa
from fastapi.routing import APIRoute, iter_route_contexts
from httpx import AsyncClient
from pydantic import BaseModel, TypeAdapter
from sqlalchemy import select, text

from app.api.main import app
from app.modules.catalog.maps.models import Map, MapGroupGrant, MapShareToken
from app.modules.catalog.maps.visibility_contract import map_visibility_contract
from app.modules.embed_tokens.models import EmbedToken
from app.modules.embed_tokens.service import create_embed_token
from app.modules.catalog.maps.service import update_map
from tests.factories import create_dataset, create_user
from tests.test_api_key_scope_875 import _remove_keys_minted_by_the_test  # noqa: F401
from tests.test_dataset_group_grants import _new_group
from tests.test_dataset_group_sharing import _mint_key

pytestmark = pytest.mark.anyio

OPT_IN = {"X-GeoLens-Map-Visibility": "restricted"}


async def _share(client: AsyncClient, map_id, group_ids: list[str], headers):
    return await client.put(
        f"/maps/{map_id}/groups/", json={"group_ids": group_ids}, headers=headers
    )


async def _stored(session, map_id) -> str:
    session.expire_all()
    return await session.scalar(select(Map.visibility).where(Map.id == map_id))


@pytest.fixture
async def owned(client: AsyncClient, admin_auth_header: dict):
    """A private map owned by an editor who is in group ``mine`` with another
    editor; ``other`` is a group the owner isn't in, and ``outsider`` is in
    no group."""
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    member, member_id = await create_user(client, admin_auth_header, "editor")
    outsider, _ = await create_user(client, admin_auth_header, "editor")
    created = await client.post(
        "/maps/", json={"name": f"grp-map-{uuid.uuid4().hex[:8]}"}, headers=owner
    )
    assert created.status_code == 201, created.text
    return {
        "map": created.json()["id"],
        "owner": owner,
        "owner_id": owner_id,
        "member": member,
        "member_id": member_id,
        "outsider": outsider,
        "mine": await _new_group(client, admin_auth_header, [owner_id, member_id]),
        "other": await _new_group(client, admin_auth_header, []),
    }


async def test_sharing_a_private_map_makes_it_restricted_and_back(
    client: AsyncClient, owned, test_db_session
):
    map_id, url = owned["map"], f"/maps/{owned['map']}"
    assert (await client.get(url, headers=owned["member"])).status_code == 404

    shared = await _share(client, map_id, [owned["mine"]], {**owned["owner"], **OPT_IN})

    assert shared.status_code == 200, shared.text
    assert shared.json()["visibility"] == "restricted"
    assert [g["id"] for g in shared.json()["groups"]] == [owned["mine"]]
    assert (await client.get(url, headers=owned["member"])).status_code == 200
    assert (await client.get(url, headers=owned["outsider"])).status_code == 404

    unshared = await _share(client, map_id, [], {**owned["owner"], **OPT_IN})

    assert unshared.status_code == 200, unshared.text
    assert unshared.json() == {"visibility": "private", "groups": []}
    assert await _stored(test_db_session, map_id) == "private"
    assert (await client.get(url, headers=owned["member"])).status_code == 404


async def test_an_owner_cannot_share_with_a_group_they_are_not_in(
    client: AsyncClient, owned, test_db_session
):
    refused = await _share(client, owned["map"], [owned["other"]], owned["owner"])

    assert refused.status_code == 403, refused.text
    assert await _stored(test_db_session, owned["map"]) == "private"


async def test_an_admin_shares_with_any_group(
    client: AsyncClient, admin_auth_header: dict, owned
):
    shared = await _share(client, owned["map"], [owned["other"]], admin_auth_header)

    assert shared.status_code == 200, shared.text
    assert [g["id"] for g in shared.json()["groups"]] == [owned["other"]]


async def test_a_non_owner_reader_gets_403_and_a_non_reader_404(
    client: AsyncClient, owned
):
    assert (
        await _share(client, owned["map"], [owned["mine"]], owned["owner"])
    ).is_success

    reader = await _share(client, owned["map"], [], owned["member"])
    stranger = await _share(client, owned["map"], [], owned["outsider"])

    assert reader.status_code == 403, reader.text
    assert stranger.status_code == 404, stranger.text


async def test_only_a_full_key_may_share(client: AsyncClient, owned):
    keys = {
        scope: await _mint_key(client, owned["owner"], scope)
        for scope in ("read_only", "publish", "full")
    }

    status = {
        scope: (
            await _share(client, owned["map"], [owned["mine"]], headers)
        ).status_code
        for scope, headers in keys.items()
    }

    assert status == {"read_only": 403, "publish": 403, "full": 200}


async def test_only_the_owner_and_admins_see_the_groups(
    client: AsyncClient, admin_auth_header: dict, owned
):
    assert (
        await _share(client, owned["map"], [owned["mine"]], owned["owner"])
    ).is_success
    url = f"/maps/{owned['map']}"

    seen = {
        caller: (await client.get(url, headers=headers)).json()["groups"]
        for caller, headers in (
            ("owner", owned["owner"]),
            ("admin", admin_auth_header),
            ("member", owned["member"]),
        )
    }

    assert [g["id"] for g in seen["owner"]] == [owned["mine"]]
    assert [g["id"] for g in seen["admin"]] == [owned["mine"]]
    assert seen["member"] is None


async def test_an_internal_map_keeps_its_audience_until_it_narrows(
    client: AsyncClient, owned, test_db_session
):
    map_id, url = owned["map"], f"/maps/{owned['map']}"
    made_internal = await client.put(
        url, json={"visibility": "internal"}, headers=owned["owner"]
    )
    assert made_internal.status_code == 200, made_internal.text

    shared = await _share(client, map_id, [owned["mine"]], owned["owner"])

    assert shared.json()["visibility"] == "internal"
    assert (await client.get(url, headers=owned["outsider"])).status_code == 200

    narrowed = await client.put(
        url, json={"visibility": "private"}, headers={**owned["owner"], **OPT_IN}
    )

    assert narrowed.json()["visibility"] == "restricted"
    assert (await client.get(url, headers=owned["member"])).status_code == 200
    assert (await client.get(url, headers=owned["outsider"])).status_code == 404


async def test_restricted_needs_a_group(client: AsyncClient, owned, test_db_session):
    refused = await client.put(
        f"/maps/{owned['map']}",
        json={"visibility": "restricted"},
        headers=owned["owner"],
    )

    assert refused.status_code == 422, refused.text
    assert await _stored(test_db_session, owned["map"]) == "private"


async def test_removing_a_member_or_deleting_the_group_ends_their_read(
    client: AsyncClient, admin_auth_header: dict, owned, test_db_session
):
    url = f"/maps/{owned['map']}"
    assert (
        await _share(client, owned["map"], [owned["mine"]], owned["owner"])
    ).is_success
    assert (await client.get(url, headers=owned["member"])).status_code == 200

    removed = await client.delete(
        f"/admin/groups/{owned['mine']}/members/{owned['member_id']}",
        headers=admin_auth_header,
    )
    assert removed.status_code == 204, removed.text
    assert (await client.get(url, headers=owned["member"])).status_code == 404

    deleted = await client.delete(
        f"/admin/groups/{owned['mine']}", headers=admin_auth_header
    )
    assert deleted.status_code == 204, deleted.text
    assert await _stored(test_db_session, owned["map"]) == "private"
    owner_read = await client.get(url, headers=owned["owner"])
    assert owner_read.status_code == 200
    assert owner_read.json()["groups"] == []


async def test_deleting_one_of_two_groups_keeps_the_map_restricted(
    client: AsyncClient, admin_auth_header: dict, owned, test_db_session
):
    second = await _new_group(client, admin_auth_header, [owned["member_id"]])
    shared = await _share(
        client, owned["map"], [owned["mine"], second], admin_auth_header
    )
    assert shared.status_code == 200, shared.text

    deleted = await client.delete(
        f"/admin/groups/{owned['mine']}", headers=admin_auth_header
    )

    assert deleted.status_code == 204, deleted.text
    assert await _stored(test_db_session, owned["map"]) == "restricted"
    member_read = await client.get(f"/maps/{owned['map']}", headers=owned["member"])
    assert member_read.status_code == 200


@pytest.fixture
async def layered(client: AsyncClient, owned, test_db_session):
    """``owned`` with a public dataset layer, so it can carry an embed token."""
    dataset = await create_dataset(
        test_db_session, created_by=uuid.UUID(owned["owner_id"]), visibility="public"
    )
    await test_db_session.commit()
    added = await client.post(
        f"/maps/{owned['map']}/layers",
        json={"dataset_id": str(dataset.id)},
        headers=owned["owner"],
    )
    assert added.status_code == 201, added.text
    return owned


async def _mint_embed(session, owned) -> uuid.UUID:
    token, _ = await create_embed_token(
        session, uuid.UUID(owned["map"]), uuid.UUID(owned["owner_id"])
    )
    await session.commit()
    return token.id


async def _active(session, model, token_id) -> bool:
    session.expire_all()
    return await session.scalar(select(model.is_active).where(model.id == token_id))


async def test_going_restricted_revokes_share_and_embed_tokens(
    client: AsyncClient, layered, test_db_session
):
    owned, url = layered, f"/maps/{layered['map']}"
    published = await client.put(
        url, json={"visibility": "public"}, headers=owned["owner"]
    )
    assert published.status_code == 200, published.text
    link = await client.post(f"{url}/share/", headers=owned["owner"])
    assert link.status_code == 200, link.text
    share_id = await test_db_session.scalar(
        select(MapShareToken.id).where(MapShareToken.map_id == uuid.UUID(owned["map"]))
    )
    embed_id = await _mint_embed(test_db_session, owned)
    # A public map keeps its audience and its links while it gains groups.
    assert (
        await _share(client, owned["map"], [owned["mine"]], owned["owner"])
    ).is_success
    assert await _active(test_db_session, MapShareToken, share_id)
    assert await _active(test_db_session, EmbedToken, embed_id)

    narrowed = await client.put(
        url, json={"visibility": "private"}, headers=owned["owner"]
    )

    assert narrowed.status_code == 200, narrowed.text
    assert await _stored(test_db_session, owned["map"]) == "restricted"
    assert not await _active(test_db_session, MapShareToken, share_id)
    assert not await _active(test_db_session, EmbedToken, embed_id)


async def test_sharing_a_private_map_revokes_its_embed_token(
    client: AsyncClient, layered, test_db_session
):
    embed_id = await _mint_embed(test_db_session, layered)

    assert (
        await _share(client, layered["map"], [layered["mine"]], layered["owner"])
    ).is_success

    assert not await _active(test_db_session, EmbedToken, embed_id)


class _OldMapSummary(BaseModel):
    """A map list row as a client generated before restricted maps reads it."""

    id: uuid.UUID
    visibility: Literal["private", "internal", "public"]


class _OldMapList(BaseModel):
    maps: list[_OldMapSummary]
    total: int


async def test_a_client_that_has_not_opted_in_reads_restricted_as_private(
    client: AsyncClient, owned, test_db_session
):
    map_id, url = owned["map"], f"/maps/{owned['map']}"
    assert (await _share(client, map_id, [owned["mine"]], owned["owner"])).is_success
    name = (await client.get(url, headers=owned["owner"])).json()["name"]

    old_detail = await client.get(url, headers=owned["member"])
    new_detail = await client.get(url, headers={**owned["member"], **OPT_IN})
    old_list = await client.get(
        "/maps/", params={"search": name}, headers=owned["member"]
    )
    old_private = await client.get(
        "/maps/",
        params={"search": name, "visibility": "private"},
        headers=owned["owner"],
    )
    new_private = await client.get(
        "/maps/",
        params={"search": name, "visibility": "private"},
        headers={**owned["owner"], **OPT_IN},
    )

    assert old_detail.json()["visibility"] == "private"
    assert new_detail.json()["visibility"] == "restricted"
    assert _OldMapList.model_validate(old_list.json()).maps[0].id == uuid.UUID(map_id)
    assert [m["id"] for m in old_private.json()["maps"]] == [map_id]
    assert new_private.json()["maps"] == []

    written = await client.put(
        url, json={"visibility": "private"}, headers=owned["owner"]
    )

    assert written.json()["visibility"] == "private"
    assert await _stored(test_db_session, map_id) == "restricted"
    assert (await client.get(url, headers=owned["member"])).status_code == 200


async def test_map_responses_vary_on_the_opt_in(
    client: AsyncClient, layered, test_db_session
):
    owned = layered
    dataset_id = (
        await client.get(f"/maps/{owned['map']}", headers=owned["owner"])
    ).json()["layers"][0]["dataset_id"]
    responses = {
        "detail": await client.get(f"/maps/{owned['map']}", headers=owned["owner"]),
        "list": await client.get("/maps/", headers=owned["owner"]),
        "dataset maps": await client.get(
            f"/datasets/{dataset_id}/maps/", headers=owned["owner"]
        ),
        "share": await _share(client, owned["map"], [], owned["owner"]),
        "update": await client.put(
            f"/maps/{owned['map']}", json={"name": "renamed"}, headers=owned["owner"]
        ),
    }

    assert {
        name: (
            resp.status_code,
            "x-geolens-map-visibility" in resp.headers.get("vary", "").lower(),
        )
        for name, resp in responses.items()
    } == {name: (200, True) for name in responses}


def _dependency_calls(dependant) -> set:
    pending, calls = [dependant], set()
    while pending:
        dependant = pending.pop()
        calls.add(dependant.call)
        pending.extend(dependant.dependencies)
    return calls


def test_every_route_returning_a_map_visibility_reads_the_opt_in():
    returning = [
        ctx
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.route, APIRoute)
        and ctx.response_model is not None
        and "MapVisibility"
        in str(TypeAdapter(ctx.response_model).json_schema(mode="serialization"))
    ]

    assert len(returning) > 10
    missing = [
        f"{sorted(ctx.methods)} {ctx.path}"
        for ctx in returning
        if map_visibility_contract not in _dependency_calls(ctx.dependant)
    ]
    assert missing == []


async def test_a_group_from_another_tenant_is_refused(
    client: AsyncClient, admin_auth_header: dict, owned, test_db_session
):
    foreign = uuid.uuid4()
    await test_db_session.execute(
        text(
            "INSERT INTO catalog.groups (id, name, tenant_id) "
            "VALUES (:id, :name, :tenant)"
        ),
        {"id": foreign, "name": f"foreign-{foreign.hex[:8]}", "tenant": uuid.uuid4()},
    )
    await test_db_session.commit()
    map_id = uuid.UUID(owned["map"])
    try:
        refused = await _share(client, map_id, [str(foreign)], admin_auth_header)
        assert refused.status_code == 404, refused.text
        granted = await test_db_session.scalars(
            select(MapGroupGrant.group_id).where(MapGroupGrant.map_id == map_id)
        )
        assert list(granted) == []

        with pytest.raises(sa.exc.DBAPIError, match="does not match map tenant"):
            await test_db_session.execute(
                sa.insert(MapGroupGrant).values(map_id=map_id, group_id=foreign)
            )
        await test_db_session.rollback()
    finally:
        await test_db_session.execute(
            text("DELETE FROM catalog.groups WHERE id = :id"), {"id": foreign}
        )
        await test_db_session.commit()


async def test_a_restricted_map_cannot_be_imported(
    client: AsyncClient, admin_auth_header: dict
):
    refused = await client.post(
        "/maps/import/arcgis-webmap/",
        json={"webmap": {}, "title": "Imported", "visibility": "restricted"},
        headers=admin_auth_header,
    )

    assert refused.status_code == 422, refused.text


@pytest.mark.parametrize(
    ("origin", "requested"),
    [
        ("https://app.example.com", "authorization, x-geolens-map-visibility"),
        ("https://notebook.example.org", "x-api-key, x-geolens-map-visibility"),
    ],
)
async def test_a_cross_origin_client_may_send_the_opt_in(
    client: AsyncClient, monkeypatch, origin, requested
):
    async def _allow(_self, candidate):
        return candidate == "https://app.example.com"

    monkeypatch.setattr(
        "app.api.middleware.cors.DynamicCORSMiddleware._is_origin_allowed", _allow
    )

    preflight = await client.options(
        "/maps/",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": requested,
        },
    )

    allowed = {
        h.strip().lower()
        for h in preflight.headers["access-control-allow-headers"].split(",")
    }
    assert "x-geolens-map-visibility" in allowed


async def test_a_fork_names_its_source_only_to_readers_of_the_source(
    client: AsyncClient, owned
):
    source = owned["map"]
    assert (await _share(client, source, [owned["mine"]], owned["owner"])).is_success
    fork = await client.post(f"/maps/{source}/duplicate/", headers=owned["member"])
    assert fork.status_code == 201, fork.text
    fork_url = f"/maps/{fork.json()['id']}"
    shown = await client.put(
        fork_url, json={"visibility": "internal"}, headers=owned["member"]
    )
    assert shown.status_code == 200, shown.text
    renamed = await client.put(
        f"/maps/{source}", json={"name": "Renamed source"}, headers=owned["owner"]
    )
    assert renamed.status_code == 200, renamed.text

    outsider = (await client.get(fork_url, headers=owned["outsider"])).json()
    member = (await client.get(fork_url, headers=owned["member"])).json()

    assert outsider["forked_from_id"] == source
    assert outsider["forked_from_name"] is None
    assert member["forked_from_name"] == "Renamed source"


async def test_update_map_keeps_a_grouped_map_restricted(
    client: AsyncClient, owned, test_db_session
):
    map_id = uuid.UUID(owned["map"])
    assert (await _share(client, map_id, [owned["mine"]], owned["owner"])).is_success

    await update_map(test_db_session, map_id, visibility="private")
    await test_db_session.commit()

    assert await _stored(test_db_session, map_id) == "restricted"


# Every route family that writes to or manages a map.
_MANAGE_ROUTES = [
    ("put", "", {"json": {"name": "x"}}),
    ("get", "/history", {}),
    ("get", "/share/", {}),
    ("post", "/embed-tokens/", {"json": {}}),
    ("get", "/embed-tokens/", {}),
]


@pytest.mark.parametrize(("method", "suffix", "kwargs"), _MANAGE_ROUTES)
async def test_managing_a_map_the_caller_cannot_read_answers_404(
    client: AsyncClient, owned, method, suffix, kwargs
):
    async def status(map_id) -> int:
        resp = await getattr(client, method)(
            f"/maps/{map_id}{suffix}", headers=owned["outsider"], **kwargs
        )
        return resp.status_code

    assert await status(owned["map"]) == 404
    assert await status(uuid.uuid4()) == 404
