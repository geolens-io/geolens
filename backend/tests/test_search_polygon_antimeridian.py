"""Polygon search areas drawn across the antimeridian on a wrapped web map.

The map sends such a polygon with longitudes past ±180; record extents are
stored in [-180, 180].
"""

import json
import uuid

import pytest
from httpx import AsyncClient

from tests.factories import create_dataset, get_user_id

# 165.47°E to 145.31°W, written the way MapLibre reports it west of the seam.
_SEAM_WEST = [[-194.53, 11.59], [-145.31, 11.59], [-145.31, 36.93], [-194.53, 36.93]]

# Each records the same search area, drawn on a different world copy.
_SEAM_POLYGONS = {
    "west_of_seam": _SEAM_WEST,
    "east_of_seam": [[x + 360, y] for x, y in _SEAM_WEST],
    "two_copies_east": [[x + 720, y] for x, y in _SEAM_WEST],
}


def _polygon(ring: list[list[float]]) -> str:
    return json.dumps({"type": "Polygon", "coordinates": [[*ring, ring[0]]]})


@pytest.fixture
async def seam_records(test_db_session) -> dict[str, str]:
    token = f"polyseam{uuid.uuid4().hex[:10]}"
    admin_id = await get_user_id(test_db_session, "admin")
    extents = {
        "east": "POLYGON((170 20,175 20,175 25,170 25,170 20))",
        "west": "POLYGON((-175 20,-170 20,-170 25,-175 25,-175 20))",
        # A seam-crossing extent, stored split at ±180.
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
    client: AsyncClient, headers: dict, token: str, geometry: str, predicate: str
) -> set[str]:
    resp = await client.get(
        "/search/datasets/",
        params={
            "q": token,
            "geometry": geometry,
            "spatial_predicate": predicate,
            "limit": 100,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return {feature["id"] for feature in resp.json()["features"]}


@pytest.mark.anyio
@pytest.mark.parametrize("predicate", ["intersects", "within"])
@pytest.mark.parametrize("ring", _SEAM_POLYGONS.values(), ids=_SEAM_POLYGONS.keys())
async def test_seam_polygon_finds_records_on_both_sides(
    client: AsyncClient,
    admin_auth_header: dict,
    seam_records: dict[str, str],
    ring: list[list[float]],
    predicate: str,
):
    found = await _search_ids(
        client, admin_auth_header, seam_records["token"], _polygon(ring), predicate
    )

    assert found == {
        seam_records["east"],
        seam_records["west"],
        seam_records["straddling"],
    }


@pytest.mark.anyio
@pytest.mark.parametrize("predicate", ["intersects", "within"])
async def test_facets_count_records_on_both_sides_of_a_seam_polygon(
    client: AsyncClient,
    admin_auth_header: dict,
    seam_records: dict[str, str],
    predicate: str,
):
    resp = await client.get(
        "/search/facets/",
        params={
            "q": seam_records["token"],
            "geometry": _polygon(_SEAM_WEST),
            "spatial_predicate": predicate,
        },
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["record_type"] == {"vector_dataset": 3}


_FAR_RING = [[5, 15], [20, 15], [20, 30], [5, 30]]
# Ends exactly on the seam without crossing it.
_UP_TO_180_RING = [[165.47, 11.59], [180, 11.59], [180, 36.93], [165.47, 36.93]]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("ring", "predicate", "expected"),
    [
        (_FAR_RING, "intersects", {"far"}),
        (_FAR_RING, "within", {"far"}),
        (_UP_TO_180_RING, "intersects", {"east", "straddling"}),
        (_UP_TO_180_RING, "within", {"east"}),
    ],
    ids=["far-intersects", "far-within", "up_to_180-intersects", "up_to_180-within"],
)
async def test_in_range_polygon_is_not_wrapped(
    client: AsyncClient,
    admin_auth_header: dict,
    seam_records: dict[str, str],
    ring: list[list[float]],
    predicate: str,
    expected: set[str],
):
    found = await _search_ids(
        client, admin_auth_header, seam_records["token"], _polygon(ring), predicate
    )

    assert found == {seam_records[key] for key in expected}


@pytest.mark.anyio
async def test_self_intersecting_area_past_the_seam_is_repaired(
    client: AsyncClient,
    admin_auth_header: dict,
    seam_records: dict[str, str],
):
    bowtie = [[-190, 20], [-185, 25], [-185, 20], [-190, 25], [-190, 20]]
    square = [[-189, 21], [-186, 21], [-186, 24], [-189, 24], [-189, 21]]
    geometry = json.dumps({"type": "MultiPolygon", "coordinates": [[bowtie], [square]]})

    found = await _search_ids(
        client, admin_auth_header, seam_records["token"], geometry, "intersects"
    )

    assert found == {seam_records["east"]}
