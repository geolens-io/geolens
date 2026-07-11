"""Integration tests for layer column rename and type alter endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _create_layer(client: AsyncClient, headers: dict, *, title: str) -> str:
    resp = await client.post(
        "/layers/",
        json={
            "title": title,
            "geometry_type": "Point",
            "columns": [
                {"name": "name", "type": "text"},
                {"name": "value", "type": "text"},
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.anyio
async def test_rename_column_success(client: AsyncClient, admin_auth_header: dict):
    """PATCH .../columns/{name}/name renames the column and returns the new column list."""
    dataset_id = await _create_layer(client, admin_auth_header, title="Rename Test")

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/value/name",
        json={"new_name": "amount"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    names = {c["name"] for c in resp.json()["columns"]}
    assert "amount" in names
    assert "value" not in names


@pytest.mark.anyio
async def test_rename_column_to_existing_name_fails(
    client: AsyncClient, admin_auth_header: dict
):
    """Renaming to an existing column name returns 400."""
    dataset_id = await _create_layer(client, admin_auth_header, title="Rename Conflict")

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/value/name",
        json={"new_name": "name"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_rename_column_reserved_rejected(
    client: AsyncClient, admin_auth_header: dict
):
    """Renaming to a reserved column name returns 422 (Pydantic validation)."""
    dataset_id = await _create_layer(client, admin_auth_header, title="Reserved Test")

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/value/name",
        json={"new_name": "geom"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_alter_column_type_success(client: AsyncClient, admin_auth_header: dict):
    """PATCH .../columns/{name}/type changes the type when no rows exist."""
    dataset_id = await _create_layer(client, admin_auth_header, title="Type Alter Test")

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/value/type",
        json={"new_type": "integer"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    cols = {c["name"]: c for c in resp.json()["columns"]}
    assert cols["value"]["type"].lower().startswith("int")


@pytest.mark.anyio
async def test_alter_column_type_invalid_type(
    client: AsyncClient, admin_auth_header: dict
):
    """Unknown type returns 422 (Pydantic validation)."""
    dataset_id = await _create_layer(client, admin_auth_header, title="Bad Type")

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/value/type",
        json={"new_type": "bytea"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_rename_column_viewer_forbidden(
    client: AsyncClient, admin_auth_header: dict, viewer_auth_header: dict
):
    """Viewer cannot rename columns (403)."""
    dataset_id = await _create_layer(
        client, admin_auth_header, title="Viewer Rename Block"
    )

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/value/name",
        json={"new_name": "amount"},
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_column_ddl_invalidates_tile_cache(
    client: AsyncClient, admin_auth_header: dict, monkeypatch
):
    """fix(#458 E-05): every column DDL op purges the layer's cached tiles."""
    from unittest.mock import AsyncMock, MagicMock

    import app.modules.catalog.layers.router as layers_router

    mock_cache = MagicMock()
    mock_cache.invalidate_table = AsyncMock()
    monkeypatch.setattr(layers_router, "get_tile_cache", lambda: mock_cache)

    dataset_id = await _create_layer(client, admin_auth_header, title="Tile Purge Test")

    ops = [
        client.post(
            f"/layers/{dataset_id}/columns/",
            json={"column": {"name": "extra", "type": "text"}},
            headers=admin_auth_header,
        ),
        client.patch(
            f"/layers/{dataset_id}/columns/extra/name",
            json={"new_name": "extra2"},
            headers=admin_auth_header,
        ),
        client.patch(
            f"/layers/{dataset_id}/columns/value/type",
            json={"new_type": "integer"},
            headers=admin_auth_header,
        ),
        client.delete(
            f"/layers/{dataset_id}/columns/extra2",
            headers=admin_auth_header,
        ),
    ]
    for op in ops:
        resp = await op
        assert resp.status_code in (200, 201, 204), resp.text

    assert mock_cache.invalidate_table.await_count == 4


@pytest.mark.anyio
async def test_drop_readd_drop_same_column(
    client: AsyncClient, admin_auth_header: dict
):
    """fix(#458 E-12): dropping a re-added column must not 500 on the
    historical AttributeMetadata row left by the first drop."""
    dataset_id = await _create_layer(client, admin_auth_header, title="Drop Readd Test")

    for step in range(2):
        resp = await client.post(
            f"/layers/{dataset_id}/columns/",
            json={"column": {"name": "flaky", "type": "text"}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, f"add #{step}: {resp.text}"
        resp = await client.delete(
            f"/layers/{dataset_id}/columns/flaky",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, f"drop #{step}: {resp.text}"


@pytest.mark.anyio
async def test_column_references_counts_saved_maps(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """fix(#458 E-06): the references probe counts maps whose layer config
    mentions the column, so the schema editor can warn before rename/drop."""
    import uuid as _uuid

    from app.modules.catalog.datasets.domain.models import Dataset
    from app.modules.catalog.maps.models import Map, MapLayer
    from tests.factories import get_user_id

    dataset_id = await _create_layer(client, admin_auth_header, title="Refs Test")

    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await test_db_session.get(Dataset, _uuid.UUID(dataset_id))
    map_obj = Map(
        name=f"Refs Map {_uuid.uuid4().hex[:6]}",
        visibility="private",
        created_by=admin_id,
    )
    test_db_session.add(map_obj)
    await test_db_session.flush()
    test_db_session.add(
        MapLayer(
            map_id=map_obj.id,
            dataset_id=dataset.id,
            sort_order=0,
            style_config={"column": "value", "type": "categorical"},
        )
    )
    await test_db_session.commit()

    referenced = await client.get(
        f"/layers/{dataset_id}/columns/value/references",
        headers=admin_auth_header,
    )
    assert referenced.status_code == 200, referenced.text
    assert referenced.json()["map_count"] == 1

    unreferenced = await client.get(
        f"/layers/{dataset_id}/columns/name/references",
        headers=admin_auth_header,
    )
    assert unreferenced.status_code == 200
    assert unreferenced.json()["map_count"] == 0
