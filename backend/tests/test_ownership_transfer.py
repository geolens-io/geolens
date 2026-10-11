"""Admin-only ownership transfer through PATCH /datasets/{id} and PATCH /maps/{id}.

Pins who may transfer (an admin only, never the current owner or another
editor), which targets are refused (unknown, inactive, or lacking the
permission that creating the object requires), what moves (the owner-or-admin
write gate follows the new owner), and the single audit row per transfer.

Requirements: the docker database must be running with migrations applied.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.maps.models import Map
from tests.factories import create_dataset, create_map_via_api, create_user

pytestmark = pytest.mark.anyio


async def _transfer_rows(
    session: AsyncSession, action: str, resource_id: uuid.UUID
) -> list[AuditLog]:
    session.expire_all()
    result = await session.execute(
        select(AuditLog).where(
            AuditLog.action == action, AuditLog.resource_id == resource_id
        )
    )
    return list(result.scalars().all())


async def _dataset_owner(session: AsyncSession, dataset_id: uuid.UUID) -> uuid.UUID:
    session.expire_all()
    return await session.scalar(
        select(Record.created_by)
        .join(Dataset, Dataset.record_id == Record.id)
        .where(Dataset.id == dataset_id)
    )


async def _map_owner(session: AsyncSession, map_id: uuid.UUID) -> uuid.UUID:
    session.expire_all()
    return await session.scalar(select(Map.created_by).where(Map.id == map_id))


async def _admin_id(session: AsyncSession) -> uuid.UUID:
    return await session.scalar(
        select(User.id).where(User.username == settings.geolens_admin_username)
    )


async def _deactivate(session: AsyncSession, user_id: str) -> None:
    await session.execute(
        update(User)
        .where(User.id == uuid.UUID(user_id))
        .values(status="deactivated", is_active=False)
    )
    await session.commit()


@pytest.fixture
async def people(client: AsyncClient, admin_auth_header: dict) -> dict:
    owner_headers, owner_id = await create_user(client, admin_auth_header, "editor")
    peer_headers, peer_id = await create_user(client, admin_auth_header, "editor")
    target_headers, target_id = await create_user(client, admin_auth_header, "editor")
    _, viewer_id = await create_user(client, admin_auth_header, "viewer")
    return {
        "owner": (owner_headers, owner_id),
        "peer": (peer_headers, peer_id),
        "target": (target_headers, target_id),
        "viewer": viewer_id,
    }


async def _private_dataset(session: AsyncSession, owner_id: str) -> uuid.UUID:
    dataset = await create_dataset(
        session, created_by=uuid.UUID(owner_id), visibility="private"
    )
    return dataset.id


async def test_dataset_transfer_is_admin_only(
    client: AsyncClient, test_db_session: AsyncSession, people: dict
) -> None:
    owner_headers, owner_id = people["owner"]
    peer_headers, _ = people["peer"]
    _, target_id = people["target"]
    dataset_id = await _private_dataset(test_db_session, owner_id)

    as_owner = await client.patch(
        f"/datasets/{dataset_id}",
        json={"owner_id": target_id, "title": "renamed"},
        headers=owner_headers,
    )
    assert as_owner.status_code == 403, as_owner.text
    # The peer cannot see a private dataset, so the read gate answers first.
    as_peer = await client.patch(
        f"/datasets/{dataset_id}", json={"owner_id": target_id}, headers=peer_headers
    )
    assert as_peer.status_code == 404, as_peer.text

    assert await _dataset_owner(test_db_session, dataset_id) == uuid.UUID(owner_id)
    assert (
        await _transfer_rows(test_db_session, "dataset.transfer_owner", dataset_id)
        == []
    )
    # The refused request applied none of its other fields either.
    owner_view = await client.get(f"/datasets/{dataset_id}", headers=owner_headers)
    assert owner_view.json()["title"] != "renamed"


async def test_editor_cannot_take_a_public_dataset(
    client: AsyncClient, test_db_session: AsyncSession, people: dict
) -> None:
    _, owner_id = people["owner"]
    peer_headers, peer_id = people["peer"]
    dataset = await create_dataset(test_db_session, created_by=uuid.UUID(owner_id))

    resp = await client.patch(
        f"/datasets/{dataset.id}", json={"owner_id": peer_id}, headers=peer_headers
    )
    assert resp.status_code == 403, resp.text
    assert await _dataset_owner(test_db_session, dataset.id) == uuid.UUID(owner_id)


async def test_admin_transfers_a_dataset_and_back(
    client: AsyncClient,
    test_db_session: AsyncSession,
    admin_auth_header: dict,
    people: dict,
) -> None:
    owner_headers, owner_id = people["owner"]
    target_headers, target_id = people["target"]
    dataset_id = await _private_dataset(test_db_session, owner_id)
    admin_id = await _admin_id(test_db_session)

    resp = await client.patch(
        f"/datasets/{dataset_id}",
        json={"owner_id": target_id, "title": "Handed over"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created_by"] == target_id
    assert body["title"] == "Handed over"
    assert body["visibility"] == "private"

    rows = await _transfer_rows(test_db_session, "dataset.transfer_owner", dataset_id)
    assert len(rows) == 1
    assert rows[0].user_id == admin_id
    assert rows[0].resource_type == "dataset"
    assert rows[0].details == {
        "previous_owner_id": owner_id,
        "new_owner_id": target_id,
    }

    # The write gate follows the owner: the old one is now locked out of a
    # private dataset, the new one may edit it.
    old = await client.patch(
        f"/datasets/{dataset_id}", json={"title": "x"}, headers=owner_headers
    )
    assert old.status_code == 404, old.text
    new = await client.patch(
        f"/datasets/{dataset_id}", json={"title": "Mine now"}, headers=target_headers
    )
    assert new.status_code == 200, new.text

    back = await client.patch(
        f"/datasets/{dataset_id}",
        json={"owner_id": owner_id},
        headers=admin_auth_header,
    )
    assert back.status_code == 200, back.text
    assert await _dataset_owner(test_db_session, dataset_id) == uuid.UUID(owner_id)
    rows = await _transfer_rows(test_db_session, "dataset.transfer_owner", dataset_id)
    assert sorted(
        (r.details["previous_owner_id"], r.details["new_owner_id"]) for r in rows
    ) == sorted([(owner_id, target_id), (target_id, owner_id)])

    # The transfer is recorded once: the admin's metadata edits name only the
    # title, and the owner-only PATCH wrote no metadata edit at all.
    edits = await _transfer_rows(test_db_session, "metadata.edit", dataset_id)
    assert [r.details for r in edits if r.user_id == admin_id] == [
        {"title": "Handed over"}
    ]


async def test_transfer_to_the_current_owner_writes_no_row(
    client: AsyncClient,
    test_db_session: AsyncSession,
    admin_auth_header: dict,
    people: dict,
) -> None:
    _, owner_id = people["owner"]
    dataset_id = await _private_dataset(test_db_session, owner_id)

    resp = await client.patch(
        f"/datasets/{dataset_id}",
        json={"owner_id": owner_id},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert (
        await _transfer_rows(test_db_session, "dataset.transfer_owner", dataset_id)
        == []
    )


@pytest.mark.parametrize("target", ["unknown", "inactive", "viewer", "null"])
async def test_dataset_transfer_refuses_an_unfit_target(
    client: AsyncClient,
    test_db_session: AsyncSession,
    admin_auth_header: dict,
    people: dict,
    target: str,
) -> None:
    _, owner_id = people["owner"]
    _, target_id = people["target"]
    dataset_id = await _private_dataset(test_db_session, owner_id)
    if target == "inactive":
        await _deactivate(test_db_session, target_id)
    owner_value = {
        "unknown": str(uuid.uuid4()),
        "inactive": target_id,
        "viewer": people["viewer"],
        "null": None,
    }[target]

    resp = await client.patch(
        f"/datasets/{dataset_id}",
        json={"owner_id": owner_value},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, resp.text
    assert await _dataset_owner(test_db_session, dataset_id) == uuid.UUID(owner_id)
    assert (
        await _transfer_rows(test_db_session, "dataset.transfer_owner", dataset_id)
        == []
    )


async def test_map_transfer_is_admin_only(
    client: AsyncClient, test_db_session: AsyncSession, people: dict
) -> None:
    owner_headers, owner_id = people["owner"]
    peer_headers, _ = people["peer"]
    _, target_id = people["target"]
    map_id = uuid.UUID((await create_map_via_api(client, owner_headers))["id"])

    for headers in (owner_headers, peer_headers):
        resp = await client.patch(
            f"/maps/{map_id}", json={"owner_id": target_id}, headers=headers
        )
        assert resp.status_code == 403, resp.text
    assert await _map_owner(test_db_session, map_id) == uuid.UUID(owner_id)
    assert await _transfer_rows(test_db_session, "map.transfer_owner", map_id) == []


async def test_admin_transfers_a_map_and_back(
    client: AsyncClient,
    test_db_session: AsyncSession,
    admin_auth_header: dict,
    people: dict,
) -> None:
    owner_headers, owner_id = people["owner"]
    target_headers, target_id = people["target"]
    created = await create_map_via_api(client, owner_headers)
    map_id = uuid.UUID(created["id"])
    admin_id = await _admin_id(test_db_session)

    resp = await client.patch(
        f"/maps/{map_id}", json={"owner_id": target_id}, headers=admin_auth_header
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created_by"] == target_id
    assert resp.json()["visibility"] == created["visibility"]

    rows = await _transfer_rows(test_db_session, "map.transfer_owner", map_id)
    assert len(rows) == 1
    assert rows[0].user_id == admin_id
    assert rows[0].resource_type == "map"
    assert rows[0].details == {
        "previous_owner_id": owner_id,
        "new_owner_id": target_id,
    }

    old = await client.put(f"/maps/{map_id}", json={"name": "x"}, headers=owner_headers)
    assert old.status_code == 403, old.text
    new = await client.put(
        f"/maps/{map_id}", json={"name": "Mine now"}, headers=target_headers
    )
    assert new.status_code == 200, new.text

    back = await client.patch(
        f"/maps/{map_id}", json={"owner_id": owner_id}, headers=admin_auth_header
    )
    assert back.status_code == 200, back.text
    assert await _map_owner(test_db_session, map_id) == uuid.UUID(owner_id)
    assert len(await _transfer_rows(test_db_session, "map.transfer_owner", map_id)) == 2


@pytest.mark.parametrize("target", ["unknown", "inactive", "viewer"])
async def test_map_transfer_refuses_an_unfit_target(
    client: AsyncClient,
    test_db_session: AsyncSession,
    admin_auth_header: dict,
    people: dict,
    target: str,
) -> None:
    owner_headers, owner_id = people["owner"]
    _, target_id = people["target"]
    map_id = uuid.UUID((await create_map_via_api(client, owner_headers))["id"])
    if target == "inactive":
        await _deactivate(test_db_session, target_id)
    owner_value = {
        "unknown": str(uuid.uuid4()),
        "inactive": target_id,
        "viewer": people["viewer"],
    }[target]

    resp = await client.patch(
        f"/maps/{map_id}", json={"owner_id": owner_value}, headers=admin_auth_header
    )
    assert resp.status_code == 422, resp.text
    assert await _map_owner(test_db_session, map_id) == uuid.UUID(owner_id)
    assert await _transfer_rows(test_db_session, "map.transfer_owner", map_id) == []


async def test_map_patch_takes_only_owner_id(
    client: AsyncClient, admin_auth_header: dict, people: dict
) -> None:
    owner_headers, _ = people["owner"]
    _, target_id = people["target"]
    map_id = (await create_map_via_api(client, owner_headers))["id"]

    resp = await client.patch(
        f"/maps/{map_id}",
        json={"owner_id": target_id, "name": "ignored?"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, resp.text
