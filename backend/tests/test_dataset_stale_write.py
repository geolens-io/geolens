"""A dataset metadata write with a stale expected_updated_at is refused with 409."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from tests.factories import create_dataset as _create_dataset, get_user_id


async def _dataset(client: AsyncClient, headers: dict, test_db_session) -> tuple:
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_dataset(test_db_session, created_by=admin_id)
    read = await client.get(f"/datasets/{dataset.id}", headers=headers)
    assert read.status_code == 200, read.text
    return dataset, read.json()["updated_at"]


async def test_a_write_naming_the_current_version_is_applied(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    dataset, updated_at = await _dataset(client, admin_auth_header, test_db_session)

    resp = await client.patch(
        f"/datasets/{dataset.id}",
        json={"summary": "Written", "expected_updated_at": updated_at},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["summary"] == "Written"


async def test_a_write_naming_an_older_version_is_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    dataset, updated_at = await _dataset(client, admin_auth_header, test_db_session)
    edit = await client.patch(
        f"/datasets/{dataset.id}",
        json={"summary": "Edited in GeoLens"},
        headers=admin_auth_header,
    )
    assert edit.status_code == 200, edit.text

    resp = await client.patch(
        f"/datasets/{dataset.id}",
        json={"summary": "From the portal", "expected_updated_at": updated_at},
        headers=admin_auth_header,
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "stale_write"
    after = await client.get(f"/datasets/{dataset.id}", headers=admin_auth_header)
    assert after.json()["summary"] == "Edited in GeoLens"


async def test_a_write_without_an_expected_version_is_unconditional(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    dataset, _ = await _dataset(client, admin_auth_header, test_db_session)
    await client.patch(
        f"/datasets/{dataset.id}",
        json={"summary": "Edited in GeoLens"},
        headers=admin_auth_header,
    )

    resp = await client.patch(
        f"/datasets/{dataset.id}",
        json={"summary": "Overwritten"},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["summary"] == "Overwritten"


async def test_the_expected_version_is_not_recorded_as_an_edit(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    dataset, updated_at = await _dataset(client, admin_auth_header, test_db_session)

    resp = await client.patch(
        f"/datasets/{dataset.id}",
        json={"summary": "Written", "expected_updated_at": updated_at},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    details = (
        await test_db_session.execute(
            select(AuditLog.details).where(
                AuditLog.resource_id == dataset.id, AuditLog.action == "metadata.edit"
            )
        )
    ).scalar_one()
    assert details == {"summary": "Written"}
