"""Members of a sharing group granted on a restricted dataset can read it."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.auth.models import Role
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGrant,
    DatasetGroupGrant,
    Record,
)
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.auth.verification import issue_verification_token
from tests.factories import create_user, get_user_id
from tests.test_tile_signature_revocation_1963 import _evict_tile_meta, _make_vector
from tests.test_vrt_member_audience import _servable_vrt
from tests.test_vrt_source_authz_1172 import (
    _create_raster_dataset,
    _create_vrt_dataset,
    _link_source,
)

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")


@dataclass
class _Shared:
    dataset: Dataset
    group_id: str
    owner: dict[str, str]
    member: dict[str, str]
    member_id: str
    outsider: dict[str, str]
    outsider_id: str


async def _new_group(client: AsyncClient, admin: dict, member_ids: list[str]) -> str:
    created = await client.post(
        "/admin/groups/", json={"name": f"grp-{uuid.uuid4().hex[:8]}"}, headers=admin
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["id"]
    if member_ids:
        added = await client.post(
            f"/admin/groups/{group_id}/members/",
            json={"user_ids": member_ids},
            headers=admin,
        )
        assert added.status_code == 200, added.text
    return group_id


async def _grant(session, dataset_id, group_id) -> None:
    session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=uuid.UUID(group_id)))
    await session.commit()


@pytest.fixture
async def shared(client: AsyncClient, admin_auth_header: dict, test_db_session):
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    member, member_id = await create_user(client, admin_auth_header, "viewer")
    outsider, outsider_id = await create_user(client, admin_auth_header, "viewer")
    dataset = await _make_vector(
        test_db_session, created_by=uuid.UUID(owner_id), visibility="restricted"
    )
    group_id = await _new_group(client, admin_auth_header, [member_id])
    await _grant(test_db_session, dataset.id, group_id)
    table = dataset.table_name
    yield _Shared(dataset, group_id, owner, member, member_id, outsider, outsider_id)
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
    await test_db_session.commit()


_SURFACES = {
    "dataset": lambda d: f"/datasets/{d.id}",
    "features": lambda d: f"/datasets/{d.id}/features/",
    "ogc_collection": lambda d: f"/collections/{d.id}",
    "ogc_items": lambda d: f"/collections/{d.id}/items",
    "ogc_record": lambda d: f"/collections/datasets/items/{d.id}",
    "dcat": lambda d: f"/datasets/{d.id}/dcat/",
    "tile_token": lambda d: f"/tiles/token/{d.id}/",
    "vector_tile": lambda d: f"/tiles/data.{d.table_name}/0/0/0.pbf",
}


@pytest.mark.parametrize("surface", list(_SURFACES))
async def test_a_member_reads_and_an_outsider_gets_404(
    client: AsyncClient, shared: _Shared, surface: str
):
    url = _SURFACES[surface](shared.dataset)

    member = await client.get(url, headers=shared.member)
    outsider = await client.get(url, headers=shared.outsider)

    assert member.status_code == 200, member.text
    assert outsider.status_code == 404, outsider.text


async def test_search_lists_the_dataset_for_members_only(
    client: AsyncClient, shared: _Shared
):
    title = shared.dataset.record.title

    async def found(headers) -> bool:
        resp = await client.get(
            "/search/datasets/", params={"q": title}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        return str(shared.dataset.id) in [f["id"] for f in resp.json()["features"]]

    assert await found(shared.member)
    assert not await found(shared.outsider)


async def test_stac_serves_a_granted_raster_to_members_only(
    client: AsyncClient, admin_auth_header: dict, shared: _Shared, test_db_session
):
    raster = await _create_raster_dataset(
        test_db_session,
        created_by=await get_user_id(test_db_session, "admin"),
        visibility="restricted",
    )
    await _grant(test_db_session, raster, shared.group_id)

    member = await client.get(f"/stac/items/{raster}", headers=shared.member)
    outsider = await client.get(f"/stac/items/{raster}", headers=shared.outsider)

    assert member.status_code == 200, member.text
    assert outsider.status_code == 404, outsider.text


async def _mint(client: AsyncClient, dataset_id, headers) -> dict:
    resp = await client.get(f"/tiles/token/{dataset_id}/", headers=headers)
    assert resp.status_code == 200, resp.text
    token = resp.json()
    return {"sig": token["sig"], "exp": token["exp"], "scope": token["scope"]}


async def _signed_tile(client: AsyncClient, dataset: Dataset, params: dict):
    _evict_tile_meta()
    return await client.get(
        f"/tiles/data.{dataset.table_name}/0/0/0.pbf", params=params
    )


async def test_removing_the_member_revokes_reads_and_signed_tiles(
    client: AsyncClient, admin_auth_header: dict, shared: _Shared
):
    params = await _mint(client, shared.dataset.id, shared.member)
    assert (await _signed_tile(client, shared.dataset, params)).status_code == 200

    removed = await client.delete(
        f"/admin/groups/{shared.group_id}/members/{shared.member_id}",
        headers=admin_auth_header,
    )
    assert removed.status_code == 204, removed.text

    detail = await client.get(f"/datasets/{shared.dataset.id}", headers=shared.member)
    assert detail.status_code == 404, detail.text
    stale = await _signed_tile(client, shared.dataset, params)
    assert stale.status_code == 403, stale.text
    assert stale.json()["detail"] == "Invalid or expired signature"


async def test_deleting_the_group_leaves_the_owner_and_admins(
    client: AsyncClient, admin_auth_header: dict, shared: _Shared
):
    params = await _mint(client, shared.dataset.id, shared.member)

    deleted = await client.delete(
        f"/admin/groups/{shared.group_id}", headers=admin_auth_header
    )
    assert deleted.status_code == 204, deleted.text

    url = f"/datasets/{shared.dataset.id}"
    assert (await client.get(url, headers=shared.member)).status_code == 404
    assert (await client.get(url, headers=shared.owner)).status_code == 200
    assert (await client.get(url, headers=admin_auth_header)).status_code == 200
    assert (await _signed_tile(client, shared.dataset, params)).status_code == 403


@pytest.mark.parametrize("lifecycle", ["delete", "deactivate", "suspend"])
async def test_ending_a_members_account_retires_tiles_they_signed(
    client: AsyncClient, admin_auth_header: dict, shared: _Shared, lifecycle: str
):
    params = await _mint(client, shared.dataset.id, shared.member)
    assert (await _signed_tile(client, shared.dataset, params)).status_code == 200
    url = f"/admin/users/{shared.member_id}"

    if lifecycle == "delete":
        ended = await client.delete(url, headers=admin_auth_header)
    elif lifecycle == "deactivate":
        ended = await client.post(f"{url}/deactivate/", headers=admin_auth_header)
    else:
        ended = await client.patch(
            url, json={"status": "suspended"}, headers=admin_auth_header
        )

    assert ended.status_code in (200, 204), ended.text
    stale = await _signed_tile(client, shared.dataset, params)
    assert stale.status_code == 403, stale.text


@pytest.mark.parametrize("path", ["deactivate", "patch"])
async def test_ending_an_already_inactive_account_keeps_signed_tiles(
    client: AsyncClient,
    admin_auth_header: dict,
    shared: _Shared,
    test_db_session,
    path: str,
):
    """Only leaving active moves who reads, so a repeat retires nobody's tiles."""
    url = f"/admin/users/{shared.member_id}"

    async def end():
        if path == "deactivate":
            return await client.post(f"{url}/deactivate/", headers=admin_auth_header)
        return await client.patch(
            url, json={"status": "suspended"}, headers=admin_auth_header
        )

    version = select(Dataset.publication_version).where(Dataset.id == shared.dataset.id)
    assert (await end()).status_code == 200
    before = await test_db_session.scalar(version)

    repeated = await end()

    assert repeated.status_code == 200, repeated.text
    assert await test_db_session.scalar(version) == before


async def test_adding_a_member_grants_reads_and_rolls_the_publication_version(
    client: AsyncClient, admin_auth_header: dict, shared: _Shared, test_db_session
):
    url = f"/datasets/{shared.dataset.id}"
    version = select(Dataset.publication_version).where(Dataset.id == shared.dataset.id)
    before = await test_db_session.scalar(version)

    added = await client.post(
        f"/admin/groups/{shared.group_id}/members/",
        json={"user_ids": [shared.outsider_id]},
        headers=admin_auth_header,
    )

    assert added.status_code == 200, added.text
    assert (await client.get(url, headers=shared.outsider)).status_code == 200
    assert await test_db_session.scalar(version) == (before or 0) + 1


@pytest.mark.parametrize("change", ["noop_add", "inactive_add", "inactive_remove"])
async def test_a_change_that_moves_no_active_member_keeps_signed_tiles(
    client: AsyncClient,
    admin_auth_header: dict,
    shared: _Shared,
    test_db_session,
    change: str,
):
    members_url = f"/admin/groups/{shared.group_id}/members/"
    inactive = shared.outsider_id if change == "inactive_add" else shared.member_id
    if change != "noop_add":
        await test_db_session.execute(
            text(
                "UPDATE catalog.users SET status = 'deactivated', is_active = false "
                "WHERE id = :id"
            ),
            {"id": inactive},
        )
        await test_db_session.commit()
    version = select(Dataset.publication_version).where(Dataset.id == shared.dataset.id)
    before = await test_db_session.scalar(version)

    if change == "inactive_remove":
        resp = await client.delete(
            f"{members_url}{shared.member_id}", headers=admin_auth_header
        )
    else:
        resp = await client.post(
            members_url, json={"user_ids": [inactive]}, headers=admin_auth_header
        )

    assert resp.status_code in (200, 204), resp.text
    assert await test_db_session.scalar(version) == before


async def _team_map_shows(client, session, shared: _Shared) -> tuple[str, bool]:
    """Put the dataset on an internal map its owner made; return the map id
    and whether the member sees the layer."""
    owner_id = await session.scalar(
        select(Record.created_by).where(Record.id == shared.dataset.record_id)
    )
    team_map = Map(
        name=f"Team map {uuid.uuid4().hex[:6]}",
        visibility="internal",
        created_by=owner_id,
    )
    session.add(team_map)
    await session.flush()
    session.add(
        MapLayer(map_id=team_map.id, dataset_id=shared.dataset.id, sort_order=0)
    )
    await session.commit()
    return str(team_map.id), await _member_sees_layer(client, str(team_map.id), shared)


async def _member_sees_layer(client, map_id: str, shared: _Shared) -> bool:
    resp = await client.get(f"/maps/{map_id}", headers=shared.member)
    assert resp.status_code == 200, resp.text
    return any(
        layer["dataset_id"] == str(shared.dataset.id) for layer in resp.json()["layers"]
    )


@pytest.mark.parametrize("revoke", ["remove_member", "delete_group"])
async def test_revoking_drops_the_layer_from_an_owners_shared_map(
    client: AsyncClient,
    admin_auth_header: dict,
    shared: _Shared,
    test_db_session,
    revoke: str,
):
    map_id, saw_layer = await _team_map_shows(client, test_db_session, shared)
    url = f"/admin/groups/{shared.group_id}"
    if revoke == "remove_member":
        url += f"/members/{shared.member_id}"

    revoked = await client.delete(url, headers=admin_auth_header)

    assert saw_layer
    assert revoked.status_code == 204, revoked.text
    assert not await _member_sees_layer(client, map_id, shared)


async def test_removing_a_member_with_their_own_vrt_over_a_granted_source(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Removal is not refused; the member's mosaic stops serving instead."""
    member, member_id = await create_user(client, admin_auth_header, "editor")
    source = await _create_raster_dataset(
        test_db_session,
        created_by=await get_user_id(test_db_session, "admin"),
        visibility="restricted",
    )
    group_id = await _new_group(client, admin_auth_header, [member_id])
    await _grant(test_db_session, source, group_id)
    vrt = await _servable_vrt(
        test_db_session, created_by=uuid.UUID(member_id), visibility="private"
    )
    await _link_source(test_db_session, vrt, source, 0)

    async def vrt_tiles():
        _evict_tile_meta()
        return await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(vrt)},
            headers=member,
        )

    assert (await vrt_tiles()).status_code == 200
    removed = await client.delete(
        f"/admin/groups/{group_id}/members/{member_id}", headers=admin_auth_header
    )

    assert removed.status_code == 204, removed.text
    lost = await client.get(f"/datasets/{source}", headers=member)
    assert lost.status_code == 404, lost.text
    tiles = await vrt_tiles()
    assert tiles.status_code == 409, tiles.text


async def _group_granting_a_vrt_past_its_source(
    client: AsyncClient, admin: dict, session
) -> tuple[str, uuid.UUID]:
    """A group granted a VRT but not its source, which only another group's
    members (the VRT's owner) can read: any new active member makes the VRT
    reach past its source."""
    _, owner_id = await create_user(client, admin, "editor")
    source = await _create_raster_dataset(
        session,
        created_by=await get_user_id(session, "admin"),
        visibility="restricted",
    )
    vrt = await _create_vrt_dataset(
        session, created_by=uuid.UUID(owner_id), visibility="restricted"
    )
    await _link_source(session, vrt, source, 0)
    await _grant(session, source, await _new_group(client, admin, [owner_id]))
    group_id = await _new_group(client, admin, [])
    await _grant(session, vrt, group_id)
    return group_id, source


async def test_adding_a_member_a_vrt_would_reach_past_a_source_is_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    _, joiner_id = await create_user(client, admin_auth_header, "viewer")
    group_id, _ = await _group_granting_a_vrt_past_its_source(
        client, admin_auth_header, test_db_session
    )

    added = await client.post(
        f"/admin/groups/{group_id}/members/",
        json={"user_ids": [joiner_id]},
        headers=admin_auth_header,
    )

    assert added.status_code == 422, added.text
    members = await client.get(
        f"/admin/groups/{group_id}/members/", headers=admin_auth_header
    )
    assert members.json()["total"] == 0


async def _activate(client, admin, session, path: str, user_id: str):
    url = f"/admin/users/{user_id}"
    if path == "patch":
        return await client.patch(url, json={"status": "active"}, headers=admin)
    if path == "legacy_patch":
        return await client.patch(url, json={"is_active": True}, headers=admin)
    if path == "approve":
        return await client.post(
            f"{url}/approve/", json={"role": "viewer"}, headers=admin
        )
    token = await issue_verification_token(session, uuid.UUID(user_id))
    await session.commit()
    return await client.post("/auth/verify-email", json={"token": token})


async def _inactive_member_of_a_vrt_group(
    client: AsyncClient, admin: dict, session, *, pending: bool
) -> tuple[str, uuid.UUID]:
    """An inactive (or pending) viewer in a group granted a VRT but not its
    source; returns the user id and the source."""
    _, user_id = await create_user(client, admin, "viewer")
    await session.execute(
        text("UPDATE catalog.users SET status = :s, is_active = false WHERE id = :id"),
        {"s": "pending" if pending else "deactivated", "id": user_id},
    )
    await session.commit()
    group_id, source = await _group_granting_a_vrt_past_its_source(
        client, admin, session
    )
    added = await client.post(
        f"/admin/groups/{group_id}/members/",
        json={"user_ids": [user_id]},
        headers=admin,
    )
    assert added.status_code == 200, added.text
    return user_id, source


@pytest.mark.parametrize("path", ["patch", "legacy_patch", "approve", "verify"])
async def test_activating_a_member_a_vrt_would_reach_past_a_source_is_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session, path: str
):
    """An inactive account counts in no audience, so it can join the group;
    becoming active is the widening and is refused as adding it would be."""
    pending = path in ("approve", "verify")
    user_id, _ = await _inactive_member_of_a_vrt_group(
        client, admin_auth_header, test_db_session, pending=pending
    )

    activated = await _activate(
        client, admin_auth_header, test_db_session, path, user_id
    )

    assert activated.status_code == (409 if path == "verify" else 422), activated.text
    status_now = await test_db_session.scalar(
        text("SELECT status FROM catalog.users WHERE id = :id"), {"id": user_id}
    )
    assert status_now == ("pending" if pending else "deactivated")


@pytest.mark.parametrize("path", ["patch", "approve"])
async def test_activating_into_a_role_that_reads_the_source_is_admitted(
    client: AsyncClient, admin_auth_header: dict, test_db_session, path: str
):
    """The admission judges the account with the role it is given."""
    user_id, source = await _inactive_member_of_a_vrt_group(
        client, admin_auth_header, test_db_session, pending=path == "approve"
    )
    editor = await test_db_session.scalar(select(Role.id).where(Role.name == "editor"))
    test_db_session.add(DatasetGrant(dataset_id=source, role_id=editor))
    await test_db_session.commit()
    url = f"/admin/users/{user_id}"

    if path == "patch":
        activated = await client.patch(
            url, json={"status": "active", "role": "editor"}, headers=admin_auth_header
        )
    else:
        activated = await client.post(
            f"{url}/approve/", json={"role": "editor"}, headers=admin_auth_header
        )

    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"


async def test_an_untrusted_audience_authority_refuses_an_add_over_a_vrt_link(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """An authority that overrides reads but not ``record_audience`` can't say
    whether a VRT reaches past its source, so an add over a VRT link is refused."""
    from app.platform import extensions
    from app.platform.extensions import DefaultPermissionExtension

    class _OwnReads(DefaultPermissionExtension):
        def filter_visible(self, *args, **kwargs):
            return super().filter_visible(*args, **kwargs)

    _, joiner_id = await create_user(client, admin_auth_header, "viewer")
    admin_id = await get_user_id(test_db_session, "admin")
    source = await _create_raster_dataset(
        test_db_session, created_by=admin_id, visibility="internal"
    )
    vrt = await _create_vrt_dataset(
        test_db_session, created_by=admin_id, visibility="restricted"
    )
    await _link_source(test_db_session, vrt, source, 0)
    vrt_group = await _new_group(client, admin_auth_header, [])
    await _grant(test_db_session, vrt, vrt_group)
    plain = await _create_raster_dataset(
        test_db_session, created_by=admin_id, visibility="restricted"
    )
    plain_group = await _new_group(client, admin_auth_header, [])
    await _grant(test_db_session, plain, plain_group)
    monkeypatch.setitem(extensions._extensions, "permission", _OwnReads())

    async def add(group_id):
        return await client.post(
            f"/admin/groups/{group_id}/members/",
            json={"user_ids": [joiner_id]},
            headers=admin_auth_header,
        )

    over_vrt = await add(vrt_group)
    over_plain = await add(plain_group)

    assert over_vrt.status_code == 422, over_vrt.text
    assert over_plain.status_code == 200, over_plain.text
