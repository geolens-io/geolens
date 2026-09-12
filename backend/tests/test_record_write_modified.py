"""Record subresource changes advance modification metadata atomically."""

import uuid

import pytest
from sqlalchemy import select

from app.modules.catalog.datasets.domain.models import Record
from tests.factories import create_dataset, get_user_id


async def _modified(session, record_id):
    return (
        await session.execute(
            select(Record.updated_at, Record.updated_by).where(Record.id == record_id)
        )
    ).one()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("resource", "body", "patch"),
    [
        ("contacts", {"role": "author", "name": "Initial"}, {"name": "Changed"}),
        ("keywords", {"keyword": "initial"}, None),
        (
            "distributions",
            {
                "distribution_type": "download",
                "format": "GeoJSON",
                "url": "https://example.com/data.geojson",
            },
            {"title": "Changed"},
        ),
    ],
)
async def test_subresource_writes_advance_record_modified(
    client, admin_auth_header, test_db_session, resource, body, patch
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=admin_id)
    path = f"/records/{dataset.record_id}/{resource}/"
    before = await _modified(test_db_session, dataset.record_id)

    response = await client.post(path, json=body, headers=admin_auth_header)
    assert response.status_code == 201, response.text
    child_id = response.json()["id"]
    after = await _modified(test_db_session, dataset.record_id)
    assert after.updated_at > before.updated_at
    assert after.updated_by == admin_id

    child_path = f"{path}{child_id}/"
    if patch is not None:
        before = after
        response = await client.patch(child_path, json=patch, headers=admin_auth_header)
        assert response.status_code == 200, response.text
        after = await _modified(test_db_session, dataset.record_id)
        assert after.updated_at > before.updated_at
        assert after.updated_by == admin_id

    response = await client.delete(child_path, headers=admin_auth_header)
    assert response.status_code == 204, response.text
    deleted = await _modified(test_db_session, dataset.record_id)
    assert deleted.updated_at > after.updated_at
    assert deleted.updated_by == admin_id

    detail = await client.get(f"/datasets/{dataset.id}", headers=admin_auth_header)
    assert detail.status_code == 200, detail.text
    assert detail.json()["updated_at"] == deleted.updated_at.isoformat().replace(
        "+00:00", "Z"
    )


@pytest.mark.anyio
async def test_rejected_subresource_write_preserves_record_modified(
    client, admin_auth_header, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=admin_id)
    path = f"/records/{dataset.record_id}/contacts/"
    response = await client.post(
        path, json={"role": "author", "name": "Initial"}, headers=admin_auth_header
    )
    assert response.status_code == 201, response.text
    child_id = response.json()["id"]
    before = await _modified(test_db_session, dataset.record_id)

    invalid = await client.patch(
        f"{path}{child_id}/",
        json={"role": "not-an-iso-role", "name": "Invalid"},
        headers=admin_auth_header,
    )
    assert invalid.status_code == 400, invalid.text
    assert await _modified(test_db_session, dataset.record_id) == before

    missing = await client.delete(f"{path}{uuid.uuid4()}/", headers=admin_auth_header)
    assert missing.status_code == 404, missing.text
    assert await _modified(test_db_session, dataset.record_id) == before
    listing = await client.get(path, headers=admin_auth_header)
    assert listing.status_code == 200, listing.text
    assert (
        next(c for c in listing.json()["contacts"] if c["id"] == child_id)["name"]
        == "Initial"
    )
