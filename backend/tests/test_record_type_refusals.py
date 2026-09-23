"""Routes refuse a record type whose capabilities do not cover them."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core import record_types
from tests.factories import (
    create_dataset,
    create_map_via_api,
    create_raster_dataset,
    get_user_id,
)

pytestmark = pytest.mark.anyio

_COLUMN_CHANGES = [
    ("POST", "/layers/{id}/columns/", {"column": {"name": "note", "type": "text"}}),
    ("PATCH", "/layers/{id}/columns/name/name", {"new_name": "label"}),
    ("PATCH", "/layers/{id}/columns/name/type", {"new_type": "text"}),
    ("DELETE", "/layers/{id}/columns/name", None),
]


async def _raster(session, **kwargs):
    admin_id = await get_user_id(session, "admin")
    return await create_raster_dataset(session, created_by=admin_id, **kwargs)


async def test_vector_tiles_for_a_raster_are_404(client: AsyncClient, test_db_session):
    """A raster's table name is not a vector tile source."""
    raster = await _raster(test_db_session)

    resp = await client.get(f"/tiles/data.{raster.table_name}/0/0/0.pbf")

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "This dataset has no vector tiles"


async def test_a_hidden_raster_gets_the_access_refusal(
    client: AsyncClient, test_db_session
):
    """An anonymous caller is refused a private raster as it is a private vector dataset."""
    raster = await _raster(test_db_session, visibility="private")
    admin_id = await get_user_id(test_db_session, "admin")
    vector = await create_dataset(
        test_db_session, created_by=admin_id, visibility="private"
    )

    raster_resp = await client.get(f"/tiles/data.{raster.table_name}/0/0/0.pbf")
    vector_resp = await client.get(f"/tiles/data.{vector.table_name}/0/0/0.pbf")

    assert raster_resp.status_code == vector_resp.status_code, raster_resp.text
    assert raster_resp.json() == vector_resp.json()


async def test_rows_of_a_raster_are_404(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """A raster has no rows to page through."""
    raster = await _raster(test_db_session)

    resp = await client.get(f"/datasets/{raster.id}/rows/", headers=admin_auth_header)

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "This dataset has no data table"


@pytest.mark.parametrize(("method", "path", "body"), _COLUMN_CHANGES)
async def test_column_changes_on_a_raster_are_404(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    method: str,
    path: str,
    body: dict | None,
):
    """A raster has no columns to add, rename, retype or drop."""
    raster = await _raster(test_db_session)

    resp = await client.request(
        method, path.format(id=raster.id), json=body, headers=admin_auth_header
    )

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "This dataset has no data table"


@pytest.fixture
def vector_dataset_unknown(monkeypatch):
    """Take vector_dataset out of the capability table, like a type it has never seen."""
    monkeypatch.delitem(record_types._CAPABILITIES, "vector_dataset")


_REFUSALS = [
    ("GET", "/datasets/{id}/features/", None, 404, "has no feature items"),
    ("GET", "/datasets/{id}/features/1", None, 404, "has no feature items"),
    ("GET", "/datasets/{id}/features.geojson", None, 404, "has no feature items"),
    ("DELETE", "/datasets/{id}/features/1", None, 404, "has no feature table"),
    ("GET", "/datasets/{id}/columns/name/values/", None, 404, "no tabular columns"),
    ("GET", "/datasets/{id}/rows/", None, 404, "has no data table"),
    (*_COLUMN_CHANGES[0], 404, "has no data table"),
    ("GET", "/datasets/{id}/export?format=csv", None, 400, "no tabular feature data"),
    ("GET", "/collections/{id}", None, 404, "not an OGC API Features collection"),
    ("GET", "/collections/{id}/items", None, 404, "has no feature items"),
    ("GET", "/collections/{id}/queryables", None, 404, "has no feature items"),
    ("GET", "/collections/{id}/items/1", None, 404, "has no feature items"),
    ("GET", "/tiles/token/{id}/", None, 404, "has no tiles"),
    ("GET", "/tiles/data.{table}/0/0/0.pbf", None, 404, "has no vector tiles"),
]


@pytest.mark.parametrize(("method", "path", "body", "status", "detail"), _REFUSALS)
async def test_an_unknown_record_type_is_refused(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    vector_dataset_unknown,
    method: str,
    path: str,
    body: dict | None,
    status: int,
    detail: str,
):
    """Each capability-checked route refuses a record type missing from the table."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=admin_id)

    resp = await client.request(
        method,
        path.format(id=dataset.id, table=dataset.table_name),
        json=body,
        headers=admin_auth_header,
    )

    assert resp.status_code == status, resp.text
    assert detail in resp.json()["detail"]


async def test_a_batch_token_for_an_unknown_record_type_is_an_error_entry(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    vector_dataset_unknown,
):
    """The batch token route answers an unknown record type with an error entry."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=admin_id)

    resp = await client.post(
        "/tiles/tokens/",
        json={"dataset_ids": [str(dataset.id)]},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["tokens"][str(dataset.id)] == {
        "error": "This dataset has no tiles"
    }


async def test_an_unknown_record_type_is_left_out_of_ogc_collections(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """The OGC collections list drops a record type with no OGC item type."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=admin_id)

    async def _listed() -> bool:
        resp = await client.get("/collections?limit=200", headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        return str(dataset.id) in {c["id"] for c in resp.json()["collections"]}

    assert await _listed()
    monkeypatch.delitem(record_types._CAPABILITIES, "vector_dataset")
    assert not await _listed()


@pytest.mark.parametrize("layer_type", [None, "vector_geolens"])
async def test_an_unknown_record_type_cannot_be_added_to_a_map(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    vector_dataset_unknown,
    layer_type: str | None,
):
    """Both layer write paths refuse the dataset, even when a layer type is named."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=admin_id)
    map_id = (await create_map_via_api(client, admin_auth_header))["id"]
    layer = {"dataset_id": str(dataset.id)}
    if layer_type is not None:
        layer["layer_type"] = layer_type

    added = await client.post(
        f"/maps/{map_id}/layers", json=layer, headers=admin_auth_header
    )
    patched = await client.patch(
        f"/maps/{map_id}/layers", json={"added": [layer]}, headers=admin_auth_header
    )

    for resp in (added, patched):
        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"] == "This dataset cannot be added to a map"
