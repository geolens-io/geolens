"""Search areas written past ±180 match what their in-range form matches.

Each case pairs a geometry written the way a wrapped web map can send it with
the same area written inside [-180, 180], and runs both through STAC Item
Search and, where it accepts the geometry type, catalog search.
"""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, update

from app.modules.catalog.datasets.domain.models import Record

from tests.factories import create_dataset, create_raster_dataset, get_user_id

_EXTENTS = {
    "east": "POLYGON((170 20,175 20,175 25,170 25,170 20))",
    "west": "POLYGON((-175 20,-170 20,-170 25,-175 25,-175 20))",
    "straddling": (
        "MULTIPOLYGON(((178 20,180 20,180 22,178 22,178 20)),"
        "((-180 20,-178 20,-178 22,-180 22,-180 20)))"
    ),
    "far": "POLYGON((10 20,15 20,15 25,10 25,10 20))",
    # Wholly inside the overlap of _A and _B once folded.
    "overlap_core": "POLYGON((-169 6,-166 6,-166 9,-169 9,-169 6))",
    # Inside the shell of _HOLE_SEAM and outside its hole.
    "ring": "POLYGON((162 5,165 5,165 8,162 8,162 5))",
    # Inside the latitude band of _STAIR but outside its coverage.
    "band_gap": "POLYGON((10 1,15 1,15 3,10 3,10 1))",
}


def _rect(west: float, south: float, east: float, north: float) -> list:
    return [[west, south], [east, south], [east, north], [west, north], [west, south]]


def _poly(*rings: list) -> dict:
    return {"type": "Polygon", "coordinates": list(rings)}


def _multi(*polygons: list) -> dict:
    return {"type": "MultiPolygon", "coordinates": [[ring] for ring in polygons]}


def _collection(*geometries: dict) -> dict:
    return {"type": "GeometryCollection", "geometries": list(geometries)}


# Overlapping rectangles; _A crosses the seam.
_A, _B = _rect(175, 0, 195, 10), _rect(190, 5, 200, 15)
_A_IN = [_rect(175, 0, 180, 10), _rect(-180, 0, -165, 10)]
_B_IN = _rect(-170, 5, -160, 15)
# An overlapping MultiPolygon is invalid, and PostGIS answers it inconsistently
# once its prepared form is cached, so its in-range form is the valid union.
_AB_UNION_IN = [
    [-180, 0],
    [-165, 0],
    [-165, 5],
    [-160, 5],
    [-160, 15],
    [-170, 15],
    [-170, 10],
    [-180, 10],
    [-180, 0],
]
_POINT = {"type": "Point", "coordinates": [12, 22]}
_LINE = {"type": "LineString", "coordinates": [[5, 22], [12, 22]]}

_HOLE_SEAM = _poly(_rect(-200, 0, -150, 40), _rect(-192, 10, -168, 30))
_HOLE_SEAM_IN = {
    "type": "MultiPolygon",
    "coordinates": [
        [
            [
                [160, 0],
                [180, 0],
                [180, 10],
                [168, 10],
                [168, 30],
                [180, 30],
                [180, 40],
                [160, 40],
                [160, 0],
            ]
        ],
        [
            [
                [-180, 0],
                [-150, 0],
                [-150, 40],
                [-180, 40],
                [-180, 30],
                [-168, 30],
                [-168, 10],
                [-180, 10],
                [-180, 0],
            ]
        ],
    ],
}


def _shift(ring: list, dx: float) -> list:
    return [[x + dx, *rest] for x, *rest in ring]


# The seam strip stored split at ±180, as an in-range MultiPolygon.
_SEAM_SPLIT = [_rect(-180, 20, -170, 25), _rect(170, 20, 180, 25)]

_SEAM_LINE = [[-190, 22], [-165, 22]]
_SEAM_LINE_IN = {
    "type": "MultiLineString",
    "coordinates": [[[170, 22], [180, 22]], [[-180, 22], [-165, 22]]],
}

# Wider than 360° but covering only part of its latitude band.
_STAIR = _poly(
    [[-200, 0], [-100, 0], [-100, 5], [200, 5], [200, 10], [-200, 10], [-200, 0]]
)
_STAIR_IN = _poly(
    [
        [-100, 0],
        [-180, 0],
        [-180, 10],
        [180, 10],
        [180, 0],
        [160, 0],
        [160, 5],
        [-100, 5],
        [-100, 0],
    ]
)

_SEAM_Z = [[x, y, 5] for x, y in _rect(-194.53, 11.59, -145.31, 36.93)]
_SEAM_Z_IN = {
    "type": "MultiPolygon",
    "coordinates": [
        [[[x, y, 5] for x, y in _rect(165.47, 11.59, 180, 36.93)]],
        [[[x, y, 5] for x, y in _rect(-180, 11.59, -145.31, 36.93)]],
    ],
}

# (wrapped, in range, items the in-range form intersects, catalog accepts it)
_CASES = {
    "overlapping_multipolygon": (
        _multi(_A, _B),
        _multi(_A_IN[0], _AB_UNION_IN),
        {"overlap_core"},
        True,
    ),
    "collection_overlapping_point_line": (
        _collection(_poly(_A), _poly(_B), _POINT, _LINE),
        _collection(*(_poly(r) for r in _A_IN), _poly(_B_IN), _POINT, _LINE),
        {"overlap_core", "far"},
        False,
    ),
    "nested_collection": (
        _collection(_collection(_poly(_A), _POINT), _collection(_poly(_B), _LINE)),
        _collection(
            _collection(*(_poly(r) for r in _A_IN), _POINT),
            _collection(_poly(_B_IN), _LINE),
        ),
        {"overlap_core", "far"},
        False,
    ),
    "hole_across_seam": (_HOLE_SEAM, _HOLE_SEAM_IN, {"ring", "overlap_core"}, True),
    "line_across_seam": (
        {"type": "LineString", "coordinates": _SEAM_LINE},
        _SEAM_LINE_IN,
        {"east", "west", "straddling"},
        True,
    ),
    "point_past_seam": (
        {"type": "Point", "coordinates": [188, 22]},
        {"type": "Point", "coordinates": [-172, 22]},
        {"west"},
        True,
    ),
    "point_on_seam_turns_away": (
        {"type": "Point", "coordinates": [540, 21]},
        {"type": "Point", "coordinates": [-180, 21]},
        {"straddling"},
        True,
    ),
    "wider_than_360": (
        _poly(_rect(-200, 21, 200, 23)),
        _poly(_rect(-180, 21, 180, 23)),
        {"east", "west", "straddling", "far"},
        True,
    ),
    "several_turns": (
        _poly(_rect(-900, 21, 900, 23)),
        _poly(_rect(-180, 21, 180, 23)),
        {"east", "west", "straddling", "far"},
        True,
    ),
    "z_coordinates": (
        _poly(_SEAM_Z),
        _SEAM_Z_IN,
        {"east", "west", "straddling"},
        True,
    ),
    "seam_split_turn_east": (
        _multi(*(_shift(r, 360) for r in _SEAM_SPLIT)),
        _multi(*_SEAM_SPLIT),
        {"east", "west", "straddling"},
        True,
    ),
    "seam_split_turn_west": (
        _multi(*(_shift(r, -360) for r in _SEAM_SPLIT)),
        _multi(*_SEAM_SPLIT),
        {"east", "west", "straddling"},
        True,
    ),
    "wider_than_360_partial": (_STAIR, _STAIR_IN, {"overlap_core", "ring"}, True),
    "point_two_turns_east": (
        {"type": "Point", "coordinates": [548, 22]},
        {"type": "Point", "coordinates": [-172, 22]},
        {"west"},
        True,
    ),
    "point_in_two_copies": (
        {"type": "MultiPoint", "coordinates": [[-172, 22], [548, 22]]},
        {"type": "Point", "coordinates": [-172, 22]},
        {"west"},
        True,
    ),
    "line_two_turns_east": (
        {"type": "LineString", "coordinates": _shift(_SEAM_LINE, 720)},
        _SEAM_LINE_IN,
        {"east", "west", "straddling"},
        True,
    ),
    "line_in_two_copies": (
        {
            "type": "MultiLineString",
            "coordinates": [_SEAM_LINE, _shift(_SEAM_LINE, 720)],
        },
        _SEAM_LINE_IN,
        {"east", "west", "straddling"},
        True,
    ),
    "hole_two_turns_east": (
        _poly(*(_shift(r, 720) for r in _HOLE_SEAM["coordinates"])),
        _HOLE_SEAM_IN,
        {"ring", "overlap_core"},
        True,
    ),
    "hole_in_two_copies": (
        {
            "type": "MultiPolygon",
            "coordinates": [
                _HOLE_SEAM["coordinates"],
                [_shift(r, 720) for r in _HOLE_SEAM["coordinates"]],
            ],
        },
        _HOLE_SEAM_IN,
        {"ring", "overlap_core"},
        True,
    ),
}

_ROUTES = ["stac-GET", "stac-POST", "catalog-intersects", "catalog-within"]


@pytest.fixture
async def items(client: AsyncClient, test_db_session) -> dict:
    """The same extents as public raster items (STAC) and vector records (catalog)."""
    token = f"seamclass{uuid.uuid4().hex[:10]}"
    admin_id = await get_user_id(test_db_session, "admin")
    rasters, vectors = {}, {}
    for name, wkt in _EXTENTS.items():
        raster = await create_raster_dataset(
            test_db_session, created_by=admin_id, name=f"{token} raster {name}"
        )
        await test_db_session.execute(
            update(Record)
            .where(Record.id == raster.record_id)
            .values(spatial_extent=func.ST_GeomFromText(wkt, 4326))
        )
        await test_db_session.commit()
        rasters[name] = str(raster.id)
        vector = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"{token} vector {name}",
            spatial_extent_wkt=wkt,
        )
        vectors[name] = str(vector.id)
    return {"token": token, "rasters": rasters, "vectors": vectors}


async def _matches(
    client: AsyncClient, headers: dict, items: dict, route: str, geometry: dict
) -> set[str]:
    """Names of the fixture items the route returns for ``geometry``."""
    kind, mode = route.split("-")
    if kind == "stac":
        ids = list(items["rasters"].values())
        if mode == "GET":
            resp = await client.get(
                "/stac/search",
                params={"ids": ",".join(ids), "intersects": json.dumps(geometry)},
            )
        else:
            resp = await client.post(
                "/stac/search", json={"ids": ids, "intersects": geometry}
            )
        by_id = items["rasters"]
    else:
        resp = await client.get(
            "/search/datasets/",
            params={
                "q": items["token"],
                "record_type": "vector_dataset",
                "geometry": json.dumps(geometry),
                "spatial_predicate": mode,
                "limit": 100,
            },
            headers=headers,
        )
        by_id = items["vectors"]
    assert resp.status_code == 200, resp.text
    found = {feature["id"] for feature in resp.json()["features"]}
    return {name for name, item_id in by_id.items() if item_id in found}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("case", "route"),
    [
        (case, route)
        for case, (*_, catalog_ok) in _CASES.items()
        for route in _ROUTES
        if catalog_ok or route.startswith("stac")
    ],
)
async def test_wrapped_area_matches_its_in_range_form(
    client: AsyncClient, admin_auth_header: dict, items: dict, case: str, route: str
):
    wrapped, in_range, intersected, _ = _CASES[case]

    expected = await _matches(client, admin_auth_header, items, route, in_range)
    found = await _matches(client, admin_auth_header, items, route, wrapped)

    assert found == expected
    if not route.endswith("within"):
        assert expected == intersected


@pytest.mark.anyio
@pytest.mark.parametrize("route", _ROUTES)
@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "Polygon", "coordinates": []},
        {"type": "Point", "coordinates": []},
        {"type": "GeometryCollection", "geometries": []},
    ],
    ids=["polygon", "point", "collection"],
)
async def test_empty_area_matches_nothing(
    client: AsyncClient, admin_auth_header: dict, items: dict, route: str, geometry
):
    if geometry["type"] == "GeometryCollection" and route.startswith("catalog"):
        resp = await client.get(
            "/search/datasets/",
            params={"geometry": json.dumps(geometry)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        return

    assert await _matches(client, admin_auth_header, items, route, geometry) == set()
