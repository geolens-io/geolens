"""Column changes on the column a dataset's retention reads are refused."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text

RETENTION = {"column": "ts", "days": 5}

# (method, path suffix, body) for each column change the schema editor sends.
CHANGES = {
    "rename": ("PATCH", "name", {"new_name": "ts_old"}),
    "retype": ("PATCH", "type", {"new_type": "text"}),
    "drop": ("DELETE", None, None),
}


@pytest.fixture
async def layer(client: AsyncClient, admin_auth_header: dict, test_db_session):
    """A layer whose retention reads ``ts``, removed afterwards so later
    retention sweeps in the session don't pick it up."""
    resp = await client.post(
        "/layers/",
        json={
            "title": "Retention column DDL",
            "geometry_type": "Point",
            "columns": [
                {"name": "ts", "type": "timestamp"},
                {"name": "other_ts", "type": "timestamp"},
            ],
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    dataset_id, table_name = resp.json()["id"], resp.json()["table_name"]
    saved = await client.put(
        f"/datasets/{dataset_id}/retention/",
        json={"retention": RETENTION},
        headers=admin_auth_header,
    )
    assert saved.status_code == 200, saved.text

    yield dataset_id, table_name

    await test_db_session.rollback()
    await test_db_session.execute(
        text(
            "DELETE FROM catalog.records WHERE id = "
            "(SELECT record_id FROM catalog.datasets WHERE id = :id)"
        ),
        {"id": dataset_id},
    )
    await test_db_session.execute(text(f'DROP TABLE IF EXISTS data."{table_name}"'))
    await test_db_session.commit()


async def _change(client, headers, dataset_id: str, column: str, change: str):
    method, suffix, body = CHANGES[change]
    path = f"/layers/{dataset_id}/columns/{column}"
    if suffix:
        path = f"{path}/{suffix}"
    return await client.request(method, path, json=body, headers=headers)


async def _column_types(session, table_name: str) -> dict[str, str]:
    rows = await session.execute(
        text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'data' AND table_name = :table"
        ),
        {"table": table_name},
    )
    return dict(rows.all())


async def _stored_retention(session, dataset_id: str) -> tuple:
    row = await session.execute(
        text(
            "SELECT retention_column, retention_days FROM catalog.datasets "
            "WHERE id = :id"
        ),
        {"id": dataset_id},
    )
    return tuple(row.one())


@pytest.mark.anyio
@pytest.mark.parametrize("change", list(CHANGES))
async def test_changing_the_retention_column_is_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session, layer, change: str
):
    dataset_id, table_name = layer
    before = await _column_types(test_db_session, table_name)

    resp = await _change(client, admin_auth_header, dataset_id, "ts", change)

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "retention_column_in_use"
    assert detail["column"] == "ts"
    assert await _column_types(test_db_session, table_name) == before
    assert before["ts"] == "timestamp with time zone"
    assert await _stored_retention(test_db_session, dataset_id) == ("ts", 5)


@pytest.mark.anyio
@pytest.mark.parametrize("change", list(CHANGES))
async def test_other_columns_still_change(
    client: AsyncClient, admin_auth_header: dict, test_db_session, layer, change: str
):
    dataset_id, table_name = layer

    resp = await _change(client, admin_auth_header, dataset_id, "other_ts", change)

    assert resp.status_code == 200, resp.text
    after = await _column_types(test_db_session, table_name)
    expected = {
        "rename": "ts_old" in after and "other_ts" not in after,
        "retype": after.get("other_ts") == "text",
        "drop": "other_ts" not in after,
    }
    assert expected[change], after
    assert await _stored_retention(test_db_session, dataset_id) == ("ts", 5)


@pytest.mark.anyio
async def test_a_setting_saved_after_the_dataset_loaded_still_refuses(
    client: AsyncClient, admin_auth_header: dict, test_db_session, layer, monkeypatch
):
    """The check reads the stored setting, not the one the request loaded."""
    import app.core.db as db_module
    from app.modules.catalog.layers import router as layers_router

    dataset_id, table_name = layer
    cleared = await client.put(
        f"/datasets/{dataset_id}/retention/",
        json={"retention": None},
        headers=admin_auth_header,
    )
    assert cleared.status_code == 200, cleared.text
    real_gate = layers_router.require_dataset_editing_enabled

    async def save_retention_then_gate(db):
        async with db_module.async_session() as other:
            await other.execute(
                text(
                    "UPDATE catalog.datasets SET retention_column = 'ts', "
                    "retention_days = 5 WHERE id = :id"
                ),
                {"id": dataset_id},
            )
            await other.commit()
        await real_gate(db)

    monkeypatch.setattr(
        layers_router, "require_dataset_editing_enabled", save_retention_then_gate
    )

    resp = await _change(client, admin_auth_header, dataset_id, "ts", "drop")

    assert resp.status_code == 409, resp.text
    assert "ts" in await _column_types(test_db_session, table_name)


async def _drop_outside_the_api(session, table_name: str, column: str) -> None:
    """Remove the column and its metadata outside the API, leaving retention set.

    A replacement keeps the removed column's metadata, and a rename onto that
    name is refused for it, so the metadata goes too.
    """
    await session.execute(text(f'ALTER TABLE data."{table_name}" DROP COLUMN {column}'))
    await session.execute(
        text(
            "UPDATE catalog.datasets SET column_info = (SELECT jsonb_agg(c) "
            "FROM jsonb_array_elements(column_info) c WHERE c->>'name' <> :column) "
            "WHERE table_name = :table"
        ),
        {"column": column, "table": table_name},
    )
    await session.execute(
        text(
            "DELETE FROM catalog.attribute_metadata WHERE field_name = :column "
            "AND dataset_id = (SELECT id FROM catalog.datasets WHERE table_name = :table)"
        ),
        {"column": column, "table": table_name},
    )
    await session.commit()


@pytest.mark.anyio
async def test_renaming_another_column_to_the_retention_name_is_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session, layer
):
    dataset_id, table_name = layer
    await _drop_outside_the_api(test_db_session, table_name, "ts")
    before = await _column_types(test_db_session, table_name)

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/other_ts/name",
        json={"new_name": "ts"},
        headers=admin_auth_header,
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "retention_column_in_use"
    assert resp.json()["detail"]["column"] == "ts"
    assert await _column_types(test_db_session, table_name) == before
    assert "other_ts" in before
    assert await _stored_retention(test_db_session, dataset_id) == ("ts", 5)


@pytest.mark.anyio
async def test_adding_a_column_with_the_retention_name_is_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session, layer
):
    dataset_id, table_name = layer
    await _drop_outside_the_api(test_db_session, table_name, "ts")
    before = await _column_types(test_db_session, table_name)

    resp = await client.post(
        f"/layers/{dataset_id}/columns/",
        json={"column": {"name": "ts", "type": "timestamp"}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "retention_column_in_use"
    assert await _column_types(test_db_session, table_name) == before
    assert "ts" not in before
    assert await _stored_retention(test_db_session, dataset_id) == ("ts", 5)
