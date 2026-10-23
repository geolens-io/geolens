"""Owners and admins share datasets with sharing groups through PUT /datasets/{id}/groups/."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGroupGrant,
    Record,
)
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.schemas import DatasetMeta
from app.modules.catalog.datasets.domain.service import (
    get_dataset,
    set_dataset_groups,
    update_user_metadata,
)
from tests.alembic_helpers import fresh_query
from tests.factories import create_user, get_user_id
from tests.test_dataset_group_grants import _new_group
from tests.test_tile_signature_revocation_1963 import _evict_tile_meta, _make_vector
from tests.test_vrt_member_audience import _servable_vrt
from tests.test_vrt_source_authz_1172 import (
    _create_raster_dataset,
    _create_vrt_dataset,
    _link_source,
)

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")


async def _share(client: AsyncClient, dataset_id, group_ids: list[str], headers):
    return await client.put(
        f"/datasets/{dataset_id}/groups/",
        json={"group_ids": group_ids},
        headers=headers,
    )


async def _visibility(session, dataset_id) -> str:
    session.expire_all()
    return await session.scalar(
        select(Record.visibility)
        .join(Dataset, Dataset.record_id == Record.id)
        .where(Dataset.id == dataset_id)
    )


async def _granted(session, dataset_id) -> set[str]:
    rows = await session.scalars(
        select(DatasetGroupGrant.group_id).where(
            DatasetGroupGrant.dataset_id == dataset_id
        )
    )
    return {str(group_id) for group_id in rows}


async def _version(session, dataset_id) -> int:
    session.expire_all()
    return (
        await session.scalar(
            select(Dataset.publication_version).where(Dataset.id == dataset_id)
        )
        or 0
    )


@pytest.fixture
async def owned(client: AsyncClient, admin_auth_header: dict, test_db_session):
    """A private vector dataset owned by an editor who is in group ``mine``
    with a viewer; ``other`` is a group the owner isn't in."""
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    member, member_id = await create_user(client, admin_auth_header, "viewer")
    dataset = await _make_vector(
        test_db_session, created_by=uuid.UUID(owner_id), visibility="private"
    )
    mine = await _new_group(client, admin_auth_header, [owner_id, member_id])
    other = await _new_group(client, admin_auth_header, [])
    table = dataset.table_name
    yield {
        "dataset": dataset.id,
        "owner": owner,
        "owner_id": owner_id,
        "member": member,
        "member_id": member_id,
        "mine": mine,
        "other": other,
    }
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
    await test_db_session.commit()


async def test_sharing_a_private_dataset_makes_it_restricted_for_the_group(
    client: AsyncClient, owned, test_db_session
):
    dataset_id = owned["dataset"]
    url = f"/datasets/{dataset_id}"
    before = await _version(test_db_session, dataset_id)
    assert (await client.get(url, headers=owned["member"])).status_code == 404

    shared = await _share(client, dataset_id, [owned["mine"]], owned["owner"])

    assert shared.status_code == 200, shared.text
    assert shared.json()["visibility"] == "restricted"
    assert [g["id"] for g in shared.json()["groups"]] == [owned["mine"]]
    assert (await client.get(url, headers=owned["member"])).status_code == 200
    assert await _version(test_db_session, dataset_id) == before + 1


async def test_removing_the_last_group_makes_it_private_again(
    client: AsyncClient, owned, test_db_session
):
    dataset_id = owned["dataset"]
    assert (
        await _share(client, dataset_id, [owned["mine"]], owned["owner"])
    ).is_success
    before = await _version(test_db_session, dataset_id)

    unshared = await _share(client, dataset_id, [], owned["owner"])

    assert unshared.status_code == 200, unshared.text
    assert unshared.json() == {
        "visibility": "private",
        "groups": [],
        "metadata_warnings": None,
    }
    assert await _visibility(test_db_session, dataset_id) == "private"
    member_read = await client.get(f"/datasets/{dataset_id}", headers=owned["member"])
    assert member_read.status_code == 404
    assert await _version(test_db_session, dataset_id) == before + 1


async def test_an_owner_cannot_share_with_a_group_they_are_not_in(
    client: AsyncClient, owned, test_db_session
):
    dataset_id = owned["dataset"]

    refused = await _share(client, dataset_id, [owned["other"]], owned["owner"])

    assert refused.status_code == 403, refused.text
    assert await _granted(test_db_session, dataset_id) == set()
    assert await _visibility(test_db_session, dataset_id) == "private"


async def test_an_owner_keeps_and_may_drop_a_group_they_have_left(
    client: AsyncClient, admin_auth_header: dict, owned, test_db_session
):
    dataset_id = owned["dataset"]
    other = owned["other"]
    assert (await _share(client, dataset_id, [other], admin_auth_header)).is_success

    kept = await _share(client, dataset_id, [other, owned["mine"]], owned["owner"])
    dropped = await _share(client, dataset_id, [owned["mine"]], owned["owner"])

    assert kept.status_code == 200, kept.text
    assert dropped.status_code == 200, dropped.text
    assert await _granted(test_db_session, dataset_id) == {owned["mine"]}


async def test_an_admin_shares_with_any_group(
    client: AsyncClient, admin_auth_header: dict, owned
):
    shared = await _share(client, owned["dataset"], [owned["other"]], admin_auth_header)

    assert shared.status_code == 200, shared.text
    assert [g["id"] for g in shared.json()["groups"]] == [owned["other"]]


async def test_a_non_owner_reader_gets_403_and_a_non_reader_404(
    client: AsyncClient, admin_auth_header: dict, owned, test_db_session
):
    dataset_id = owned["dataset"]
    reader, reader_id = await create_user(client, admin_auth_header, "editor")
    stranger, _ = await create_user(client, admin_auth_header, "editor")
    readers = await _new_group(client, admin_auth_header, [reader_id])
    assert (await _share(client, dataset_id, [readers], admin_auth_header)).is_success

    by_reader = await _share(client, dataset_id, [readers], reader)
    by_stranger = await _share(client, dataset_id, [], stranger)

    assert by_reader.status_code == 403, by_reader.text
    assert by_stranger.status_code == 404, by_stranger.text
    assert await _granted(test_db_session, dataset_id) == {readers}


async def test_an_unknown_group_is_404(client: AsyncClient, owned):
    missing = str(uuid.uuid4())

    resp = await _share(client, owned["dataset"], [missing], owned["owner"])

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["group_ids"] == [missing]


async def test_only_the_owner_and_admins_see_the_groups_on_the_detail(
    client: AsyncClient, admin_auth_header: dict, owned
):
    dataset_id = owned["dataset"]
    assert (
        await _share(client, dataset_id, [owned["mine"]], owned["owner"])
    ).is_success
    url = f"/datasets/{dataset_id}"

    as_member = (await client.get(url, headers=owned["member"])).json()
    as_owner = (await client.get(url, headers=owned["owner"])).json()
    as_admin = (await client.get(url, headers=admin_auth_header)).json()

    assert as_member["groups"] is None
    assert [g["id"] for g in as_owner["groups"]] == [owned["mine"]]
    assert [g["id"] for g in as_admin["groups"]] == [owned["mine"]]


@pytest.mark.parametrize("visibility", ["internal", "public"])
async def test_an_internal_or_public_dataset_keeps_its_audience(
    client: AsyncClient, admin_auth_header: dict, test_db_session, visibility: str
):
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset_id = (
        await _make_vector(
            test_db_session, created_by=uuid.UUID(owner_id), visibility=visibility
        )
    ).id
    group = await _new_group(client, admin_auth_header, [owner_id])
    before = await _version(test_db_session, dataset_id)

    shared = await _share(client, dataset_id, [group], owner)

    assert shared.status_code == 200, shared.text
    assert shared.json()["visibility"] == visibility
    assert await _granted(test_db_session, dataset_id) == {group}
    assert await _version(test_db_session, dataset_id) == before


async def _owners_internal_map(session, dataset_id, owner_id: str) -> None:
    team_map = Map(
        name=f"Team map {uuid.uuid4().hex[:6]}",
        visibility="internal",
        created_by=uuid.UUID(owner_id),
    )
    session.add(team_map)
    await session.flush()
    session.add(MapLayer(map_id=team_map.id, dataset_id=dataset_id, sort_order=0))
    await session.commit()


@pytest.mark.parametrize("narrowing", ["unshare", "swap"])
async def test_narrowing_that_strands_the_owners_shared_map_is_refused(
    client: AsyncClient, admin_auth_header: dict, owned, test_db_session, narrowing: str
):
    """Unsharing, or moving to a group without the map's viewer, would hide
    the layer from someone who sees the owner's internal map."""
    dataset_id = owned["dataset"]
    assert (
        await _share(client, dataset_id, [owned["mine"]], owned["owner"])
    ).is_success
    await _owners_internal_map(test_db_session, dataset_id, owned["owner_id"])
    without_member = await _new_group(client, admin_auth_header, [owned["owner_id"]])
    target = [] if narrowing == "unshare" else [without_member]

    refused = await _share(client, dataset_id, target, owned["owner"])

    assert refused.status_code == 422, refused.text
    assert "shared maps" in refused.json()["detail"]
    assert await _granted(test_db_session, dataset_id) == {owned["mine"]}
    member_read = await client.get(f"/datasets/{dataset_id}", headers=owned["member"])
    assert member_read.status_code == 200


async def test_moving_to_a_group_that_keeps_the_maps_viewers_is_allowed(
    client: AsyncClient, admin_auth_header: dict, owned, test_db_session
):
    dataset_id = owned["dataset"]
    assert (
        await _share(client, dataset_id, [owned["mine"]], owned["owner"])
    ).is_success
    await _owners_internal_map(test_db_session, dataset_id, owned["owner_id"])
    same_people = await _new_group(
        client, admin_auth_header, [owned["owner_id"], owned["member_id"]]
    )
    before = await _version(test_db_session, dataset_id)

    moved = await _share(client, dataset_id, [same_people], owned["owner"])

    assert moved.status_code == 200, moved.text
    assert await _granted(test_db_session, dataset_id) == {same_people}
    assert await _version(test_db_session, dataset_id) == before + 1


@pytest.mark.parametrize("start", ["private", "restricted"])
async def test_widening_a_vrt_past_one_of_its_sources_is_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session, start: str
):
    """The VRT's owner reads its source through a group; sharing the VRT with
    a group whose member can't read the source would serve it to them."""
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    _, outsider_id = await create_user(client, admin_auth_header, "viewer")
    source = await _create_raster_dataset(
        test_db_session,
        created_by=await get_user_id(test_db_session, "admin"),
        visibility="restricted",
    )
    source_readers = await _new_group(client, admin_auth_header, [owner_id])
    assert (
        await _share(client, source, [source_readers], admin_auth_header)
    ).is_success
    vrt = await _create_vrt_dataset(
        test_db_session, created_by=uuid.UUID(owner_id), visibility="private"
    )
    await _link_source(test_db_session, vrt, source, 0)
    await test_db_session.commit()
    if start == "restricted":
        assert (await _share(client, vrt, [source_readers], owner)).is_success
    wider = await _new_group(client, admin_auth_header, [owner_id, outsider_id])

    refused = await _share(client, vrt, [wider], owner)

    assert refused.status_code == 422, refused.text
    assert await _visibility(test_db_session, vrt) == start


async def test_unsharing_a_source_stops_another_users_vrt_instead_of_refusing(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """As with a visibility change, a narrowed source is never held by
    someone else's VRT; the VRT answers 409 instead."""
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    member, member_id = await create_user(client, admin_auth_header, "editor")
    source = await _create_raster_dataset(
        test_db_session, created_by=uuid.UUID(owner_id), visibility="private"
    )
    group = await _new_group(client, admin_auth_header, [owner_id, member_id])
    assert (await _share(client, source, [group], owner)).is_success
    vrt = await _servable_vrt(
        test_db_session, created_by=uuid.UUID(member_id), visibility="private"
    )
    await _link_source(test_db_session, vrt, source, 0)
    await test_db_session.commit()

    async def vrt_tiles():
        _evict_tile_meta()
        return await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(vrt)},
            headers=member,
        )

    assert (await vrt_tiles()).status_code == 200
    unshared = await _share(client, source, [], owner)

    assert unshared.status_code == 200, unshared.text
    assert (await vrt_tiles()).status_code == 409


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
    dataset_id = owned["dataset"]
    try:
        refused = await _share(client, dataset_id, [str(foreign)], admin_auth_header)
        assert refused.status_code == 404, refused.text
        assert await _granted(test_db_session, dataset_id) == set()

        with pytest.raises(sa.exc.DBAPIError, match="does not match dataset tenant"):
            await test_db_session.execute(
                sa.insert(DatasetGroupGrant).values(
                    dataset_id=dataset_id, group_id=foreign
                )
            )
        await test_db_session.rollback()
    finally:
        await test_db_session.execute(
            text("DELETE FROM catalog.groups WHERE id = :id"), {"id": foreign}
        )
        await test_db_session.commit()


async def test_records_stac_and_dcat_never_name_the_groups(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    raster = await _create_raster_dataset(
        test_db_session, created_by=uuid.UUID(owner_id), visibility="private"
    )
    name = f"Planning-{uuid.uuid4().hex[:8]}"
    created = await client.post(
        "/admin/groups/", json={"name": name}, headers=admin_auth_header
    )
    group = created.json()["id"]
    added = await client.post(
        f"/admin/groups/{group}/members/",
        json={"user_ids": [owner_id]},
        headers=admin_auth_header,
    )
    assert added.status_code == 200, added.text
    assert (await _share(client, raster, [group], owner)).is_success
    detail = await client.get(f"/datasets/{raster}", headers=owner)
    assert name in detail.text

    for url in (
        f"/collections/datasets/items/{raster}",
        f"/stac/items/{raster}",
        f"/datasets/{raster}/dcat/",
    ):
        resp = await client.get(url, headers=owner)
        assert resp.status_code == 200, (url, resp.text)
        assert name not in resp.text, url
        assert group not in resp.text, url


async def test_my_groups_lists_the_callers_groups_and_all_for_an_admin(
    client: AsyncClient, admin_auth_header: dict, owned
):
    mine = await client.get("/groups/mine/", headers=owned["owner"])
    everything = await client.get("/groups/mine/", headers=admin_auth_header)
    admin_list = await client.get("/admin/groups/", headers=admin_auth_header)

    assert mine.status_code == 200, mine.text
    assert [g["id"] for g in mine.json()["groups"]] == [owned["mine"]]
    assert mine.json()["total"] == 1
    assert everything.json()["total"] == admin_list.json()["total"] >= 2


async def _stale_private_dataset(session, owner_id: str):
    """A private dataset loaded into ``session``, then made internal by another
    connection, as a write racing the caller's lock would."""
    dataset_id = (
        await _make_vector(
            session, created_by=uuid.UUID(owner_id), visibility="private"
        )
    ).id
    loaded = await get_dataset(session, dataset_id)
    await session.commit()
    await fresh_query(
        "UPDATE catalog.records SET visibility = 'internal' WHERE id = :id",
        {"id": loaded.record_id},
    )
    return loaded


async def test_sharing_judges_the_visibility_committed_under_the_lock(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Read stale, the internal dataset would be judged private and narrowed
    to restricted with no stranding or VRT check."""
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    group = await _new_group(client, admin_auth_header, [owner_id])
    loaded = await _stale_private_dataset(test_db_session, owner_id)
    owner = await test_db_session.get(User, uuid.UUID(owner_id))

    await set_dataset_groups(
        test_db_session, loaded, [uuid.UUID(group)], actor=owner, is_admin=False
    )
    await test_db_session.commit()

    assert await _visibility(test_db_session, loaded.id) == "internal"


async def test_a_metadata_patch_judges_the_visibility_committed_under_the_lock(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Read stale, narrowing the internal dataset to restricted would skip the
    guard that protects viewers of the owner's internal map."""
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    loaded = await _stale_private_dataset(test_db_session, owner_id)
    await _owners_internal_map(test_db_session, loaded.id, owner_id)

    with pytest.raises(ValueError, match="shared maps"):
        await update_user_metadata(
            test_db_session,
            loaded.id,
            DatasetMeta(visibility="restricted"),
            actor_id=uuid.UUID(owner_id),
        )
    await test_db_session.rollback()


async def _mint_key(client: AsyncClient, headers: dict, scope: str) -> dict:
    resp = await client.post(
        "/auth/api-keys/",
        json={"name": f"{scope} key", "scope": scope},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return {"X-Api-Key": resp.json()["key"]}


async def test_only_a_full_key_may_share(client: AsyncClient, owned):
    dataset_id = owned["dataset"]
    bound = await client.post(
        f"/datasets/{dataset_id}/api-keys",
        json={
            "name": "Webhook",
            "scope": "dataset_write",
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        },
        headers=owned["owner"],
    )
    assert bound.status_code == 201, bound.text
    keys = {
        scope: await _mint_key(client, owned["owner"], scope)
        for scope in ("read_only", "publish", "full")
    }
    keys["dataset_write"] = {"X-Api-Key": bound.json()["key"]}
    body = [owned["mine"]]

    status = {
        scope: (await _share(client, dataset_id, body, headers)).status_code
        for scope, headers in keys.items()
    }

    assert status == {
        "read_only": 403,
        "publish": 403,
        "dataset_write": 401,
        "full": 200,
    }


async def test_an_admins_publish_key_lists_only_the_admins_own_groups(
    client: AsyncClient, admin_auth_header: dict, owned
):
    publish = await _mint_key(client, admin_auth_header, "publish")

    as_key = await client.get("/groups/mine/", params={"limit": 200}, headers=publish)
    as_admin = await client.get("/groups/mine/", headers=admin_auth_header)

    assert as_key.status_code == 200, as_key.text
    assert owned["other"] not in {g["id"] for g in as_key.json()["groups"]}
    assert as_key.json()["total"] < as_admin.json()["total"]
