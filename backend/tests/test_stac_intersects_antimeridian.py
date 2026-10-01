"""STAC Item Search with an ``intersects`` area that crosses the antimeridian.

A client that draws on a wrapped web map sends such a polygon with longitudes
past ±180; record extents are stored in [-180, 180].
"""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import func, update

from app.modules.catalog.datasets.domain.models import Record

from tests.factories import create_raster_dataset, get_user_id

# 165.47°E to 145.31°W, written the way MapLibre reports it west of the seam.
_SEAM_WEST = [[-194.53, 11.59], [-145.31, 11.59], [-145.31, 36.93], [-194.53, 36.93]]

# The same search area, drawn on three different world copies.
_SEAM_RINGS = {
    "west_of_seam": _SEAM_WEST,
    "east_of_seam": [[x + 360, y] for x, y in _SEAM_WEST],
    "two_copies_east": [[x + 720, y] for x, y in _SEAM_WEST],
}

# The same area again, split at ±180 into in-range halves.
_SEAM_SPLIT = {
    "type": "MultiPolygon",
    "coordinates": [
        [
            [
                [165.47, 11.59],
                [180, 11.59],
                [180, 36.93],
                [165.47, 36.93],
                [165.47, 11.59],
            ]
        ],
        [
            [
                [-180, 11.59],
                [-145.31, 11.59],
                [-145.31, 36.93],
                [-180, 36.93],
                [-180, 11.59],
            ]
        ],
    ],
}


def _polygon(ring: list[list[float]]) -> dict:
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


@pytest.fixture
async def seam_rasters(client: AsyncClient, test_db_session) -> dict[str, str]:
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
    ids = {}
    for key, wkt in extents.items():
        dataset = await create_raster_dataset(
            test_db_session, created_by=admin_id, name=f"stac seam {key}"
        )
        await test_db_session.execute(
            update(Record)
            .where(Record.id == dataset.record_id)
            .values(spatial_extent=func.ST_GeomFromText(wkt, 4326))
        )
        ids[key] = str(dataset.id)
    await test_db_session.commit()
    return ids


async def _search(
    client: AsyncClient, method: str, ids: list[str], intersects: dict
) -> set[str]:
    if method == "GET":
        resp = await client.get(
            "/stac/search",
            params={"ids": ",".join(ids), "intersects": json.dumps(intersects)},
        )
    else:
        resp = await client.post(
            "/stac/search", json={"ids": ids, "intersects": intersects}
        )
    assert resp.status_code == 200, resp.text
    return {feature["id"] for feature in resp.json()["features"]}


def _names(seam_rasters: dict[str, str], found: set[str]) -> set[str]:
    return {name for name, item_id in seam_rasters.items() if item_id in found}


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("ring", _SEAM_RINGS.values(), ids=_SEAM_RINGS.keys())
async def test_seam_intersects_finds_items_on_both_sides(
    client: AsyncClient,
    seam_rasters: dict[str, str],
    ring: list[list[float]],
    method: str,
):
    found = await _search(client, method, list(seam_rasters.values()), _polygon(ring))

    assert _names(seam_rasters, found) == {"east", "west", "straddling"}


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_seam_intersects_split_at_180_finds_items_on_both_sides(
    client: AsyncClient, seam_rasters: dict[str, str], method: str
):
    found = await _search(client, method, list(seam_rasters.values()), _SEAM_SPLIT)

    assert _names(seam_rasters, found) == {"east", "west", "straddling"}


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize(
    ("ring", "expected"),
    [
        ([[5, 15], [20, 15], [20, 30], [5, 30]], {"far"}),
        # Ends exactly on the seam without crossing it.
        (
            [[165.47, 11.59], [180, 11.59], [180, 36.93], [165.47, 36.93]],
            {"east", "straddling"},
        ),
    ],
    ids=["far", "up_to_180"],
)
async def test_in_range_intersects_is_not_wrapped(
    client: AsyncClient,
    seam_rasters: dict[str, str],
    ring: list[list[float]],
    expected: set[str],
    method: str,
):
    found = await _search(client, method, list(seam_rasters.values()), _polygon(ring))

    assert _names(seam_rasters, found) == expected
