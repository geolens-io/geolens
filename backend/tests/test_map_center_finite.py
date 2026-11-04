"""Map centers stay finite on write, and style export tolerates stored non-finite ones."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.modules.catalog.maps.models import Map
from tests.factories import create_map_via_api


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("field", ["center_lng", "center_lat"])
async def test_map_update_rejects_a_non_finite_center(
    client: AsyncClient, admin_auth_header: dict, field: str, bad: str
):
    created = await create_map_via_api(client, admin_auth_header)

    resp = await client.put(
        f"/maps/{created['id']}",
        content=f'{{"{field}": {bad}}}',
        headers={**admin_auth_header, "Content-Type": "application/json"},
    )

    assert resp.status_code == 422, resp.text


async def test_map_update_keeps_a_finite_wrapped_center(
    client: AsyncClient, admin_auth_header: dict
):
    created = await create_map_via_api(client, admin_auth_header)

    resp = await client.put(
        f"/maps/{created['id']}",
        json={"center_lng": 540.5, "center_lat": -12.25},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["center_lng"] == 540.5


@pytest.mark.parametrize("center", ["[Infinity, 0]", "[0, NaN]"])
async def test_style_import_rejects_a_non_finite_center(
    client: AsyncClient, admin_auth_header: dict, center: str
):
    resp = await client.post(
        "/maps/import",
        content=f'{{"version": 8, "name": "Bad center", "center": {center}}}',
        headers={**admin_auth_header, "Content-Type": "application/json"},
    )

    assert resp.status_code == 422, resp.text


async def test_style_export_omits_a_stored_non_finite_center(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    created = await create_map_via_api(client, admin_auth_header)
    await test_db_session.execute(
        update(Map)
        .where(Map.id == uuid.UUID(created["id"]))
        .values(center_lng=float("nan"), center_lat=float("inf"))
    )
    await test_db_session.commit()

    resp = await client.get(
        f"/maps/{created['id']}/style.json", headers=admin_auth_header
    )

    assert resp.status_code == 200, resp.text
    assert "center" not in resp.json()


async def test_shared_map_read_falls_back_from_a_stored_non_finite_center(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    created = await create_map_via_api(client, admin_auth_header)
    await test_db_session.execute(
        update(Map)
        .where(Map.id == uuid.UUID(created["id"]))
        .values(center_lng=float("nan"), center_lat=0.0, zoom=5.0, visibility="public")
    )
    await test_db_session.commit()
    share = await client.post(
        f"/maps/{created['id']}/share/", headers=admin_auth_header
    )
    assert share.status_code in (200, 201), share.text

    resp = await client.get(f"/maps/shared/{share.json()['token']}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["center_lng"], body["center_lat"]) == (0.0, 0.0)
    assert body["has_saved_view"] is False
