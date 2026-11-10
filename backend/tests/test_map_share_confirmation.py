"""Sharing a map with groups first lists the layers they can't read, and a confirm shares or skips them."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.modules.catalog.datasets.domain import service as dataset_service
from app.modules.catalog.group_sharing import GroupNotJoinedError

from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGroupGrant,
    Record,
)
from app.modules.catalog.maps.models import Map, MapGroupGrant
from tests.factories import create_dataset, create_user, get_user_id
from tests.test_dataset_group_grants import _new_group
from tests.test_vrt_source_authz_1172 import (
    _create_raster_dataset,
    _create_vrt_dataset,
    _link_source,
)

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.usefixtures("_init_tile_pool_for_tests"),
]


async def _share_map(client: AsyncClient, map_id, group_ids, headers, confirm=None):
    body: dict = {"group_ids": [str(g) for g in group_ids]}
    if confirm is not None:
        body["confirm"] = confirm
    return await client.put(f"/maps/{map_id}/groups/", json=body, headers=headers)


async def _share_dataset(client: AsyncClient, dataset_id, group_ids, headers):
    resp = await client.put(
        f"/datasets/{dataset_id}/groups/",
        json={"group_ids": [str(g) for g in group_ids]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def _dataset_visibility(session, dataset_id) -> str:
    session.expire_all()
    return await session.scalar(
        select(Record.visibility)
        .join(Dataset, Dataset.record_id == Record.id)
        .where(Dataset.id == dataset_id)
    )


async def _dataset_group_ids(session, dataset_id) -> set[uuid.UUID]:
    session.expire_all()
    return set(
        await session.scalars(
            select(DatasetGroupGrant.group_id).where(
                DatasetGroupGrant.dataset_id == dataset_id
            )
        )
    )


async def _map_state(session, map_id) -> tuple[str, set[uuid.UUID]]:
    session.expire_all()
    visibility = await session.scalar(select(Map.visibility).where(Map.id == map_id))
    grants = set(
        await session.scalars(
            select(MapGroupGrant.group_id).where(MapGroupGrant.map_id == map_id)
        )
    )
    return visibility, grants


async def _add_layer(client: AsyncClient, map_id, dataset_id, headers) -> str:
    resp = await client.post(
        f"/maps/{map_id}/layers", json={"dataset_id": str(dataset_id)}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
async def world(client: AsyncClient, admin_auth_header: dict, test_db_session):
    """An editor's private map with one layer per kind of dataset.

    ``g`` holds the owner and a member; ``h`` holds the owner alone, and ``k``
    holds the owner and another editor who owns dataset ``theirs``.
    """
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    member, member_id = await create_user(client, admin_auth_header, "viewer")
    other, other_id = await create_user(client, admin_auth_header, "editor")
    g = await _new_group(client, admin_auth_header, [owner_id, member_id])
    h = await _new_group(client, admin_auth_header, [owner_id])
    k = await _new_group(client, admin_auth_header, [owner_id, other_id])

    datasets = {}
    for name, visibility in (
        ("private", "private"),
        ("with_g", "private"),
        ("without_g", "private"),
        ("internal", "internal"),
        ("public", "public"),
    ):
        dataset = await create_dataset(
            test_db_session, created_by=uuid.UUID(owner_id), visibility=visibility
        )
        datasets[name] = dataset.id
    theirs = await create_dataset(
        test_db_session, created_by=uuid.UUID(other_id), visibility="private"
    )
    datasets["theirs"] = theirs.id
    await test_db_session.commit()
    await _share_dataset(client, datasets["with_g"], [g], owner)
    await _share_dataset(client, datasets["without_g"], [h], owner)
    await _share_dataset(client, datasets["theirs"], [k], other)

    created = await client.post(
        "/maps/", json={"name": f"confirm-{uuid.uuid4().hex[:8]}"}, headers=owner
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]
    layers = {
        name: await _add_layer(client, map_id, dataset_id, owner)
        for name, dataset_id in datasets.items()
    }
    return {
        "map": map_id,
        "owner": owner,
        "member": member,
        "other": other,
        "g": uuid.UUID(g),
        "h": uuid.UUID(h),
        "k": uuid.UUID(k),
        "datasets": datasets,
        "layers": layers,
    }


def _gaps(body: dict) -> dict[str, dict]:
    layers = body["detail"]["layers"] if "detail" in body else body["hidden_layers"]
    return {gap["layer_id"]: gap for gap in layers}


async def test_sharing_lists_the_layers_the_group_cannot_read_and_writes_nothing(
    client: AsyncClient, world, test_db_session
):
    refused = await _share_map(client, world["map"], [world["g"]], world["owner"])

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "layers_hidden_from_groups"
    gaps = _gaps(refused.json())
    layers = world["layers"]
    assert set(gaps) == {layers["private"], layers["without_g"], layers["theirs"]}
    assert {lid: gap["can_share"] for lid, gap in gaps.items()} == {
        layers["private"]: True,
        layers["without_g"]: True,
        layers["theirs"]: False,
    }
    assert all(gap["group_ids"] == [str(world["g"])] for gap in gaps.values())
    assert await _map_state(test_db_session, uuid.UUID(world["map"])) == (
        "private",
        set(),
    )
    assert await _dataset_visibility(test_db_session, world["datasets"]["private"]) == (
        "private"
    )


async def test_a_layer_the_caller_cannot_read_is_not_named(client: AsyncClient, world):
    datasets = world["datasets"]
    await _share_dataset(client, datasets["theirs"], [], world["other"])

    refused = await _share_map(client, world["map"], [world["g"]], world["owner"])

    assert refused.status_code == 409, refused.text
    assert world["layers"]["theirs"] not in _gaps(refused.json())
    assert str(datasets["theirs"]) not in refused.text


async def test_confirming_shares_only_the_datasets_the_caller_may_share(
    client: AsyncClient, world, test_db_session
):
    datasets = world["datasets"]

    shared = await _share_map(
        client, world["map"], [world["g"]], world["owner"], "share_datasets"
    )

    assert shared.status_code == 200, shared.text
    assert set(shared.json()["shared_dataset_ids"]) == {
        str(datasets["private"]),
        str(datasets["without_g"]),
    }
    assert set(_gaps(shared.json())) == {world["layers"]["theirs"]}
    assert await _map_state(test_db_session, uuid.UUID(world["map"])) == (
        "restricted",
        {world["g"]},
    )
    for name in ("private", "without_g"):
        read = await client.get(f"/datasets/{datasets[name]}", headers=world["member"])
        assert read.status_code == 200, name
    unread = await client.get(
        f"/datasets/{datasets['theirs']}", headers=world["member"]
    )
    assert unread.status_code == 404


async def test_confirming_the_map_alone_leaves_the_datasets_untouched(
    client: AsyncClient, world, test_db_session
):
    shared = await _share_map(
        client, world["map"], [world["g"]], world["owner"], "map_only"
    )

    assert shared.status_code == 200, shared.text
    assert shared.json()["shared_dataset_ids"] == []
    assert len(shared.json()["hidden_layers"]) == 3
    assert await _map_state(test_db_session, uuid.UUID(world["map"])) == (
        "restricted",
        {world["g"]},
    )
    assert await _dataset_visibility(test_db_session, world["datasets"]["private"]) == (
        "private"
    )


async def test_an_admin_shares_anyones_dataset(
    client: AsyncClient, admin_auth_header: dict, world
):
    shared = await _share_map(
        client, world["map"], [world["g"]], admin_auth_header, "share_datasets"
    )

    assert shared.status_code == 200, shared.text
    assert str(world["datasets"]["theirs"]) in shared.json()["shared_dataset_ids"]
    assert shared.json()["hidden_layers"] == []


async def test_an_internal_map_needs_no_confirmation(client: AsyncClient, world):
    made = await client.put(
        f"/maps/{world['map']}", json={"visibility": "internal"}, headers=world["owner"]
    )
    assert made.status_code == 200, made.text

    shared = await _share_map(client, world["map"], [world["g"]], world["owner"])

    assert shared.status_code == 200, shared.text
    assert shared.json()["visibility"] == "internal"


async def test_a_vrt_that_would_pass_its_source_is_not_shareable(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Sharing a VRT past its source would be refused, so it is only listed."""
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    _, outsider_id = await create_user(client, admin_auth_header, "viewer")
    source = await _create_raster_dataset(
        test_db_session,
        created_by=await get_user_id(test_db_session, "admin"),
        visibility="restricted",
    )
    readers = await _new_group(client, admin_auth_header, [owner_id])
    await _share_dataset(client, source, [readers], admin_auth_header)
    vrt = await _create_vrt_dataset(
        test_db_session, created_by=uuid.UUID(owner_id), visibility="private"
    )
    await _link_source(test_db_session, vrt, source, 0)
    await test_db_session.commit()
    wider = await _new_group(client, admin_auth_header, [owner_id, outsider_id])
    created = await client.post("/maps/", json={"name": "vrt map"}, headers=owner)
    map_id = created.json()["id"]
    await _add_layer(client, map_id, vrt, owner)

    preview = await _share_map(client, map_id, [wider], owner)
    shared = await _share_map(client, map_id, [wider], owner, "share_datasets")

    assert [gap["can_share"] for gap in _gaps(preview.json()).values()] == [False]
    assert shared.status_code == 200, shared.text
    assert shared.json()["shared_dataset_ids"] == []
    assert await _dataset_visibility(test_db_session, vrt) == "private"
    assert await _dataset_group_ids(test_db_session, vrt) == set()


async def test_a_refused_dataset_share_writes_nothing(
    client: AsyncClient, world, test_db_session, monkeypatch
):
    """A refusal from the second dataset share rolls back the first and the map."""

    real = dataset_service.set_dataset_groups
    calls = []

    async def refuse_second(session, dataset, *args, **kwargs):
        calls.append(dataset.id)
        if len(calls) == 2:
            raise HTTPException(status_code=422, detail="refused")
        return await real(session, dataset, *args, **kwargs)

    monkeypatch.setattr(dataset_service, "set_dataset_groups", refuse_second)

    refused = await _share_map(
        client, world["map"], [world["g"]], world["owner"], "share_datasets"
    )

    assert refused.status_code == 422, refused.text
    assert len(calls) == 2
    assert await _map_state(test_db_session, uuid.UUID(world["map"])) == (
        "private",
        set(),
    )
    datasets = world["datasets"]
    assert await _dataset_visibility(test_db_session, datasets["private"]) == "private"
    assert (
        await _dataset_visibility(test_db_session, datasets["without_g"])
        == "restricted"
    )
    assert world["g"] not in await _dataset_group_ids(
        test_db_session, world["datasets"]["without_g"]
    )


async def test_a_dataset_deleted_mid_request_is_skipped(
    client: AsyncClient, world, monkeypatch
):
    gone = world["datasets"]["private"]
    real = dataset_service.get_dataset

    async def deleted(session, dataset_id, *args, **kwargs):
        if dataset_id == gone:
            return None
        return await real(session, dataset_id, *args, **kwargs)

    monkeypatch.setattr(dataset_service, "get_dataset", deleted)

    shared = await _share_map(
        client, world["map"], [world["g"]], world["owner"], "share_datasets"
    )

    assert shared.status_code == 200, shared.text
    assert shared.json()["shared_dataset_ids"] == [str(world["datasets"]["without_g"])]
    assert world["layers"]["private"] in _gaps(shared.json())


async def test_a_confirm_does_not_undo_a_revocation_it_raced(
    client: AsyncClient, world, test_db_session, monkeypatch
):
    """A revocation that commits before the confirm locks the dataset stays
    revoked."""

    target = world["datasets"]["without_g"]
    revoked = world["h"]
    real = dataset_service.set_dataset_groups
    committed = []

    async def revoke_first(session, dataset, *args, **kwargs):
        if dataset.id == target and not committed:
            engine = create_async_engine(settings.test_database_url, poolclass=NullPool)
            try:
                async with engine.begin() as conn:
                    await conn.execute(text("SET LOCAL lock_timeout = '300ms'"))
                    await conn.execute(
                        text(
                            "SELECT id FROM catalog.datasets WHERE id = :d FOR UPDATE"
                        ),
                        {"d": target},
                    )
                    await conn.execute(
                        text(
                            "DELETE FROM catalog.dataset_group_grants "
                            "WHERE dataset_id = :d AND group_id = :g"
                        ),
                        {"d": target, "g": revoked},
                    )
                committed.append(True)
            except DBAPIError:
                committed.append(False)
            finally:
                await engine.dispose()
        return await real(session, dataset, *args, **kwargs)

    monkeypatch.setattr(dataset_service, "set_dataset_groups", revoke_first)

    shared = await _share_map(
        client, world["map"], [world["g"]], world["owner"], "share_datasets"
    )

    assert shared.status_code == 200, shared.text
    granted = await _dataset_group_ids(test_db_session, target)
    assert committed == [True]
    assert revoked not in granted


async def test_unsharing_a_dataset_that_strands_a_restricted_map_is_refused(
    client: AsyncClient, world, test_db_session
):
    shared = await _share_map(
        client, world["map"], [world["g"]], world["owner"], "map_only"
    )
    assert shared.status_code == 200, shared.text

    refused = await client.put(
        f"/datasets/{world['datasets']['with_g']}/groups/",
        json={"group_ids": []},
        headers=world["owner"],
    )

    assert refused.status_code == 422, refused.text
    assert (
        await _dataset_visibility(test_db_session, world["datasets"]["with_g"])
        == "restricted"
    )


async def test_a_dataset_group_refusal_names_the_dataset(
    client: AsyncClient, world, monkeypatch
):
    async def not_joined(*args, **kwargs):
        raise GroupNotJoinedError

    monkeypatch.setattr(dataset_service, "set_dataset_groups", not_joined)

    refused = await _share_map(
        client, world["map"], [world["g"]], world["owner"], "share_datasets"
    )

    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == (
        "You can share a dataset only with groups you belong to."
    )


async def _hidden_from_groups(client: AsyncClient, map_id, headers):
    """The layer ids the visibility check lists, and the response's text."""
    resp = await client.get(f"/maps/{map_id}/visibility-check/", headers=headers)
    assert resp.status_code == 200, resp.text
    return {gap["layer_id"] for gap in resp.json()["hidden_from_groups"]}, resp.text


async def test_the_visibility_check_lists_what_a_restricted_maps_groups_cannot_read(
    client: AsyncClient, world
):
    assert (await _hidden_from_groups(client, world["map"], world["owner"]))[0] == set()
    shared = await _share_map(
        client, world["map"], [world["g"]], world["owner"], "map_only"
    )
    assert shared.status_code == 200, shared.text

    layers = world["layers"]
    gaps, _ = await _hidden_from_groups(client, world["map"], world["owner"])
    assert gaps == {
        layers["private"],
        layers["without_g"],
        layers["theirs"],
    }


async def test_the_visibility_check_names_no_layer_the_caller_cannot_read(
    client: AsyncClient, world
):
    datasets = world["datasets"]
    await _share_dataset(client, datasets["theirs"], [], world["other"])
    shared = await _share_map(
        client, world["map"], [world["g"]], world["owner"], "map_only"
    )
    assert shared.status_code == 200, shared.text

    gaps, text = await _hidden_from_groups(client, world["map"], world["owner"])

    assert gaps == {world["layers"]["private"], world["layers"]["without_g"]}
    assert str(datasets["theirs"]) not in text


async def test_the_visibility_check_lists_nothing_under_an_authority_that_cannot_say(
    client: AsyncClient, world, monkeypatch
):
    """An authority that can't answer audience questions would have every group
    lack every layer; a warning built on that would flag the whole map."""
    import app.platform.extensions as extensions
    from app.platform.extensions.defaults_extensions import (
        DefaultPermissionExtension,
    )

    class _Opaque(DefaultPermissionExtension):
        # Overriding a read without record_audience makes the answer untrusted.
        async def can_access_dataset(self, *args, **kwargs):
            return await super().can_access_dataset(*args, **kwargs)

    shared = await _share_map(
        client, world["map"], [world["g"]], world["owner"], "map_only"
    )
    assert shared.status_code == 200, shared.text
    monkeypatch.setitem(extensions._extensions, "permission", _Opaque())

    assert (await _hidden_from_groups(client, world["map"], world["owner"]))[0] == set()
