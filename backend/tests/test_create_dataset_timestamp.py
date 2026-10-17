"""A timestamp column made at dataset creation matches the add-column path."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text


async def _table_and_info(session, dataset_id: str) -> tuple[str, list[dict]]:
    row = (
        await session.execute(
            text("SELECT table_name, column_info FROM catalog.datasets WHERE id = :id"),
            {"id": uuid.UUID(dataset_id)},
        )
    ).one()
    return row.table_name, row.column_info


async def _pg_type(session, table: str, column: str) -> str:
    return (
        await session.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = 'data' AND table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        )
    ).scalar_one()


@pytest.mark.anyio
async def test_created_timestamp_column_matches_add_column_path(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    created = await client.post(
        "/datasets/create/",
        json={
            "title": "Timestamp create parity",
            "columns": [{"name": "seen_at", "type": "timestamp"}],
        },
        headers=admin_auth_header,
    )
    assert created.status_code == 201, created.text
    created_id = created.json()["id"]

    layer = await client.post(
        "/layers/",
        json={
            "title": "Timestamp add parity",
            "geometry_type": "Point",
            "columns": [{"name": "label", "type": "text"}],
        },
        headers=admin_auth_header,
    )
    assert layer.status_code == 201, layer.text
    layer_id = layer.json()["id"]
    added = await client.post(
        f"/layers/{layer_id}/columns/",
        json={"column": {"name": "seen_at", "type": "timestamp"}},
        headers=admin_auth_header,
    )
    assert added.status_code in (200, 201), added.text

    created_table, created_info = await _table_and_info(test_db_session, created_id)
    layer_table, layer_info = await _table_and_info(test_db_session, layer_id)
    try:
        created_pg = await _pg_type(test_db_session, created_table, "seen_at")
        assert created_pg == "timestamp with time zone"
        assert created_pg == await _pg_type(test_db_session, layer_table, "seen_at")

        stored = {c["name"]: c["type"] for c in created_info}
        added_stored = {c["name"]: c["type"] for c in layer_info}
        assert stored["seen_at"] == added_stored["seen_at"]

        # The stored type is what feature writes validate against.
        feature = await client.post(
            f"/datasets/{created_id}/features/",
            json={
                "geometry": {"type": "Point", "coordinates": [1, 2]},
                "properties": {"seen_at": "2026-10-17T09:00:00+02:00"},
            },
            headers=admin_auth_header,
        )
        assert feature.status_code == 201, feature.text
        assert feature.json()["properties"]["seen_at"].startswith("2026-10-17T07:00:00")
    finally:
        for table in (created_table, layer_table):
            await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
        await test_db_session.commit()
