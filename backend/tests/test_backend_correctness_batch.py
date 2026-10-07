"""Timezone-independent date filters, bounded generated maps, relationship
column validation and clearing an optional user email."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.catalog.datasets.domain.models import Record
from app.processing.ai.schemas import LLMMapSpec
from app.standards.stac.router import _apply_datetime_filter
from tests.factories import create_dataset, get_user_id


@pytest.mark.anyio
async def test_stac_instant_filter_ignores_session_timezone(test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="TZ Day",
        record_type="raster_dataset",
    )
    await test_db_session.execute(
        text(
            "UPDATE catalog.records SET created_at = '2026-03-10 00:30:00+00' "
            "WHERE id = :rid"
        ),
        {"rid": ds.record_id},
    )
    await test_db_session.commit()
    # A New York session would read 2026-03-10 as 04:00 UTC and drop this record.
    await test_db_session.execute(text("SET TIME ZONE 'America/New_York'"))
    stmt = _apply_datetime_filter(
        select(Record.id).where(Record.id == ds.record_id), "2026-03-10T00:30:00Z"
    )
    assert (await test_db_session.execute(stmt)).scalar_one_or_none() == ds.record_id


def test_generated_map_spec_is_clamped_to_save_bounds():
    spec = LLMMapSpec(
        name="x" * 400,
        zoom=99,
        center_lat=120,
        layers=[{"dataset_id": str(uuid.uuid4()), "opacity": 2, "sort_order": -1}],
    )
    assert len(spec.name) == 255
    assert spec.zoom == 24
    assert spec.center_lat == 90
    assert spec.layers[0].opacity == 1.0
    assert spec.layers[0].sort_order == 0


@pytest.mark.anyio
async def test_relationship_with_unknown_column_is_rejected(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    source = await create_dataset(test_db_session, created_by=admin_id, name="Rel Src")
    target = await create_dataset(test_db_session, created_by=admin_id, name="Rel Tgt")
    for ds in (source, target):
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{ds.table_name} (gid integer PRIMARY KEY, k integer)"
            )
        )
    await test_db_session.commit()

    async def post(source_column: str, target_column: str):
        return await client.post(
            f"/datasets/{source.id}/relationships/",
            json={
                "target_dataset_id": str(target.record_id),
                "source_column": source_column,
                "target_column": target_column,
            },
            headers=admin_auth_header,
        )

    assert (await post("nope", "k")).status_code == 422
    assert (await post("k", "nope")).status_code == 422
    assert (await post("k", "k")).status_code == 201


@pytest.mark.anyio
@pytest.mark.parametrize("clear", [None, ""])
async def test_admin_can_clear_user_email(
    client: AsyncClient, admin_auth_header: dict, clear
):
    email = f"clear_{uuid.uuid4().hex[:8]}@example.com"
    created = await client.post(
        "/admin/users/",
        json={
            "username": f"clear_{uuid.uuid4().hex[:8]}",
            "password": "TestPass1234!",
            "role": "viewer",
            "email": email,
        },
        headers=admin_auth_header,
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    omitted = await client.patch(
        f"/admin/users/{user_id}", json={}, headers=admin_auth_header
    )
    assert omitted.json()["email"] == email

    resp = await client.patch(
        f"/admin/users/{user_id}", json={"email": clear}, headers=admin_auth_header
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] is None
