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
