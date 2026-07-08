"""Regression tests for public dataset history redaction."""

import pytest
from httpx import AsyncClient

from app.modules.audit.models import AuditLog
from tests.factories import create_dataset, get_user_id


@pytest.mark.anyio
async def test_anonymous_public_dataset_history_redacts_actor_details_and_ip(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="Public History Target",
        visibility="public",
    )
    test_db_session.add(
        AuditLog(
            user_id=admin_id,
            action="dataset.update",
            resource_type="dataset",
            resource_id=dataset.id,
            details={"table_name": dataset.table_name, "secretish": "internal"},
            ip_address="203.0.113.10",
        )
    )
    await test_db_session.commit()

    resp = await client.get(f"/datasets/{dataset.id}/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    row = next(log for log in body["logs"] if log["action"] == "dataset.update")
    assert row["user_id"] is None
    assert row["username"] is None
    assert row["details"] is None
    assert row["ip_address"] is None


@pytest.mark.anyio
async def test_owner_dataset_history_keeps_actor_details_and_ip(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="Owner History Target",
        visibility="public",
    )
    test_db_session.add(
        AuditLog(
            user_id=admin_id,
            action="dataset.update",
            resource_type="dataset",
            resource_id=dataset.id,
            details={"table_name": dataset.table_name},
            ip_address="203.0.113.11",
        )
    )
    await test_db_session.commit()

    resp = await client.get(
        f"/datasets/{dataset.id}/history", headers=admin_auth_header
    )
    assert resp.status_code == 200
    row = next(log for log in resp.json()["logs"] if log["action"] == "dataset.update")
    assert row["user_id"] == str(admin_id)
    assert row["details"] == {"table_name": dataset.table_name}
    assert row["ip_address"] == "203.0.113.11"
