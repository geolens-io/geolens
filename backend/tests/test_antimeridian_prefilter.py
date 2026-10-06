"""Search areas on ±180 prefilter on each folded piece, not the union's envelope."""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.modules.catalog.datasets.domain.models import Record
from app.modules.catalog.search.service_filters import (
    SearchFilters,
    _apply_common_filters,
)
from app.standards.stac.router import _build_search_filters
from tests.factories import create_dataset, get_user_id


@pytest.fixture
async def seam_records(test_db_session) -> dict[str, str]:
    token = f"prefilter{uuid.uuid4().hex[:10]}"
    admin_id = await get_user_id(test_db_session, "admin")
    extents = {
        "east": "POLYGON((170 20,175 20,175 25,170 25,170 20))",
        "west": "POLYGON((-175 20,-170 20,-170 25,-175 25,-175 20))",
        "straddling": (
            "MULTIPOLYGON(((178 20,180 20,180 22,178 22,178 20)),"
            "((-180 20,-178 20,-178 22,-180 22,-180 20)))"
        ),
        "far": "POLYGON((10 20,15 20,15 25,10 25,10 20))",
    }
    ids = {"token": token}
    for key, wkt in extents.items():
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"{token} {key}",
            spatial_extent_wkt=wkt,
        )
        ids[key] = str(dataset.id)
    return ids


async def _search_ids(
    client: AsyncClient, headers: dict, token: str, geometry: dict
) -> set[str]:
    resp = await client.get(
        "/search/datasets/",
        params={"q": token, "geometry": json.dumps(geometry), "limit": 100},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return {feature["id"] for feature in resp.json()["features"]}


@pytest.mark.anyio
async def test_area_across_180_finds_both_sides_only(
    client: AsyncClient, admin_auth_header: dict, seam_records: dict[str, str]
):
    ring = [[170, 18], [190, 18], [190, 27], [170, 27], [170, 18]]

    found = await _search_ids(
        client,
        admin_auth_header,
        seam_records["token"],
        {"type": "Polygon", "coordinates": [ring]},
    )

    assert found == {
        seam_records["east"],
        seam_records["west"],
        seam_records["straddling"],
    }


@pytest.mark.anyio
@pytest.mark.parametrize("longitude", [180, -180])
async def test_point_on_180_finds_the_seam_record_only(
    client: AsyncClient,
    admin_auth_header: dict,
    seam_records: dict[str, str],
    longitude: int,
):
    found = await _search_ids(
        client,
        admin_auth_header,
        seam_records["token"],
        {"type": "Point", "coordinates": [longitude, 21]},
    )

    assert found == {seam_records["straddling"]}


_SEAM_AREA = {
    "type": "Polygon",
    "coordinates": [[[170, 18], [190, 18], [190, 27], [170, 27], [170, 18]]],
}


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def _assert_probes_each_piece(sql: str) -> None:
    assert "ST_Dump(" in sql
    assert "&& ST_Envelope(anon_" in sql
    assert "&& ST_Envelope(CASE" not in sql


@pytest.mark.parametrize("predicate", ["intersects", "within"])
def test_catalog_search_probes_each_folded_piece(predicate: str):
    filters = SearchFilters(
        geometry_geojson=json.dumps(_SEAM_AREA), spatial_predicate=predicate
    )

    sql = _sql(_apply_common_filters(select(Record.id), filters))

    _assert_probes_each_piece(sql)
    assert ("ST_Intersects(records_1.spatial_extent, anon_" in sql) is (
        predicate == "intersects"
    )
    assert ("ST_Within(records_1.spatial_extent, CASE" in sql) is (
        predicate == "within"
    )


def test_stac_intersects_probes_each_folded_piece():
    clauses, _ = _build_search_filters(intersects=_SEAM_AREA)

    sql = _sql(select(Record.id).where(*clauses))

    _assert_probes_each_piece(sql)
    assert "ST_Intersects(records_1.spatial_extent, anon_" in sql
