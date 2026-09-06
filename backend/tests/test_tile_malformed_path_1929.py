"""A malformed vector-tile path answers 400 on both tile routes, however it is
malformed, while a well-formed path naming no dataset still answers 404."""

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.processing.tiles.router import _parse_vector_tile_table

_MALFORMED = (
    ("roads", "Table path must start with 'data.'"),
    ("data.", "Table name is required"),
    ("data.Roads-1", "Invalid table name"),
)


@pytest.mark.parametrize(("table_path", "detail"), _MALFORMED)
def test_every_malformed_path_is_400(table_path: str, detail: str):
    with pytest.raises(HTTPException) as raised:
        _parse_vector_tile_table(table_path)

    assert raised.value.status_code == 400
    assert raised.value.detail == detail


@pytest.mark.parametrize(("table_path", "_detail"), _MALFORMED)
async def test_the_vector_route_answers_400(
    client: AsyncClient, table_path: str, _detail: str
):
    resp = await client.get(f"/tiles/{table_path}/0/0/0.pbf")

    assert resp.status_code == 400, resp.text


@pytest.mark.parametrize(("table_path", "_detail"), _MALFORMED)
async def test_the_cluster_route_answers_400(
    client: AsyncClient, table_path: str, _detail: str
):
    resp = await client.get(f"/tiles/clusters/{table_path}/0/0/0.pbf")

    assert resp.status_code == 400, resp.text


async def test_a_well_formed_path_for_no_dataset_still_answers_404(
    client: AsyncClient,
):
    """Existence stays undisclosed; only syntax is answered with a 400."""
    absent = f"absent_{uuid.uuid4().hex[:12]}"

    resp = await client.get(f"/tiles/data.{absent}/0/0/0.pbf")

    assert resp.status_code == 404, resp.text
