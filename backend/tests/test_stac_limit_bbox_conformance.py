"""STAC over-limit clamping and shared bbox parsing across catalog surfaces.

Two conformance gaps are pinned here:

1. ``GET /stac/collections/{id}/items`` rejected an over-maximum ``limit`` with
   a 422 while both Item Search handlers clamped it. The STAC Item Search spec
   (and stac-api-validator) require a limit above the server maximum to be
   clamped to that maximum, not rejected.

2. STAC parsed bbox inline in two handlers instead of calling the shared
   ``parse_bbox``, and the copies had drifted: a zero-height bbox was accepted
   by STAC and rejected by OGC Features, per-dataset features, export and
   catalog search. OGC API Features and STAC both define a bbox with
   lower <= upper latitude, so a degenerate box is legal and every surface now
   accepts it. Non-finite coordinates (SEC-FU-06) stay rejected everywhere.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.features.service import parse_bbox
from app.standards.stac.router import (
    STAC_UNASSIGNED_COLLECTION_ID as STAC_UNASSIGNED,
    _STAC_MAX_LIMIT,
)

from tests.factories import get_user_id

# Zero-height: south == north. Legal per OGC API Features / STAC (lower <= upper).
ZERO_HEIGHT_BBOX = "-74.10,40.70,-73.90,40.70"
# Inverted latitude: south > north. Invalid on every surface.
INVERTED_BBOX = "-74.10,40.80,-73.90,40.70"
# SEC-FU-06: non-finite coordinates are rejected on every surface.
NAN_BBOX = "-74.10,nan,-73.90,40.80"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def stac_raster_dataset(client: AsyncClient, test_db_session) -> Dataset:
    """A public published raster dataset, so `geolens-unassigned` resolves."""
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"test_stac_conf_{uuid.uuid4().hex[:8]}"
    record = Record(
        title=f"STAC Conformance Raster {table_name}",
        summary="Raster record backing the STAC limit/bbox conformance tests",
        theme_category=["test"],
        visibility="public",
        record_status="published",
        record_type="raster_dataset",
        created_by=admin_id,
    )
    test_db_session.add(record)
    await test_db_session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        source_format="geotiff",
        source_filename="conformance.tif",
    )
    test_db_session.add(dataset)
    await test_db_session.commit()
    await test_db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def vector_dataset(client: AsyncClient, test_db_session) -> Dataset:
    """A public vector dataset with a real backing table for the OGC path."""
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"test_stac_conf_vec_{uuid.uuid4().hex[:8]}"
    await test_db_session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
            f"gid SERIAL PRIMARY KEY, "
            f"geom geometry(Point, 4326), "
            f"geom_4326 geometry(Geometry, 4326), "
            f"name TEXT)"
        )
    )
    await test_db_session.execute(
        text(f"GRANT SELECT ON data.{table_name} TO geolens_reader")
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{table_name} (geom, geom_4326, name) VALUES ("
            f"ST_SetSRID(ST_MakePoint(-74.0, 40.7), 4326), "
            f"ST_SetSRID(ST_MakePoint(-74.0, 40.7), 4326), 'a')"
        )
    )
    record = Record(
        title=f"STAC Conformance Vector {table_name}",
        summary="Vector record backing the STAC/OGC bbox parity tests",
        theme_category=["test"],
        visibility="public",
        record_status="published",
        created_by=admin_id,
    )
    test_db_session.add(record)
    await test_db_session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="POINT",
        feature_count=1,
        column_info=[{"name": "name", "type": "text"}],
        source_format="created",
    )
    test_db_session.add(dataset)
    await test_db_session.commit()
    await test_db_session.refresh(dataset)
    yield dataset
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await test_db_session.commit()


# ---------------------------------------------------------------------------
# Over-limit clamping
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_collection_items_over_limit_is_clamped_not_rejected(
    client: AsyncClient, stac_raster_dataset: Dataset
):
    """An over-maximum limit clamps to the server maximum instead of 422ing."""
    resp = await client.get(
        f"/stac/collections/{STAC_UNASSIGNED}/items", params={"limit": 1000}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["features"]) <= _STAC_MAX_LIMIT
    assert data["context"]["limit"] == _STAC_MAX_LIMIT


@pytest.mark.anyio
async def test_all_three_item_handlers_clamp_the_same_over_limit(
    client: AsyncClient, stac_raster_dataset: Dataset
):
    """Collection items, GET search and POST search agree on the clamp."""
    items = await client.get(
        f"/stac/collections/{STAC_UNASSIGNED}/items", params={"limit": 1000}
    )
    search_get = await client.get("/stac/search", params={"limit": 1000})
    search_post = await client.post("/stac/search", json={"limit": 1000})

    for resp in (items, search_get, search_post):
        assert resp.status_code == 200, resp.text
        assert resp.json()["context"]["limit"] == _STAC_MAX_LIMIT


@pytest.mark.anyio
async def test_collection_items_below_max_limit_is_untouched(
    client: AsyncClient, stac_raster_dataset: Dataset
):
    """Clamping must not disturb a limit inside the allowed range."""
    resp = await client.get(
        f"/stac/collections/{STAC_UNASSIGNED}/items", params={"limit": 3}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["context"]["limit"] == 3
    assert len(data["features"]) <= 3


@pytest.mark.anyio
async def test_collection_items_zero_limit_still_rejected(
    client: AsyncClient, stac_raster_dataset: Dataset
):
    """ge=1 survives the le=200 removal — limit=0 is still rejected.

    Request-validation errors surface as an RFC 7807 400, not FastAPI's raw 422.
    """
    resp = await client.get(
        f"/stac/collections/{STAC_UNASSIGNED}/items", params={"limit": 0}
    )
    assert resp.status_code == 400
    assert "greater than or equal to 1" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Shared bbox parsing — degenerate boxes
# ---------------------------------------------------------------------------


def test_parse_bbox_accepts_zero_height_box():
    """A degenerate (line) box has lower == upper latitude, which is legal."""
    assert parse_bbox(ZERO_HEIGHT_BBOX) == [-74.10, 40.70, -73.90, 40.70]


def test_parse_bbox_accepts_zero_area_point_box():
    assert parse_bbox("-74.10,40.70,-74.10,40.70") == [-74.10, 40.70, -74.10, 40.70]


def test_parse_bbox_still_rejects_inverted_latitude():
    with pytest.raises(ValueError, match="less than or equal to"):
        parse_bbox(INVERTED_BBOX)


def test_parse_bbox_still_allows_antimeridian_crossing():
    """west > east crosses the antimeridian and stays legal."""
    assert parse_bbox("170,-45,-170,-30") == [170.0, -45.0, -170.0, -30.0]


@pytest.mark.anyio
async def test_zero_height_bbox_accepted_by_stac_and_ogc_features(
    client: AsyncClient, stac_raster_dataset: Dataset, vector_dataset: Dataset
):
    """The same degenerate bbox is accepted identically on STAC and OGC."""
    stac_items = await client.get(
        f"/stac/collections/{STAC_UNASSIGNED}/items",
        params={"bbox": ZERO_HEIGHT_BBOX},
    )
    stac_search = await client.get("/stac/search", params={"bbox": ZERO_HEIGHT_BBOX})
    ogc_items = await client.get(
        f"/collections/{vector_dataset.id}/items", params={"bbox": ZERO_HEIGHT_BBOX}
    )
    catalog_search = await client.get(
        "/search/datasets/", params={"bbox": ZERO_HEIGHT_BBOX}
    )

    statuses = {
        "stac_items": stac_items.status_code,
        "stac_search": stac_search.status_code,
        "ogc_items": ogc_items.status_code,
        "catalog_search": catalog_search.status_code,
    }
    assert statuses == dict.fromkeys(statuses, 200), (
        f"surfaces disagree on a zero-height bbox: {statuses}"
    )


@pytest.mark.anyio
async def test_zero_height_bbox_accepted_by_stac_search_post(
    client: AsyncClient, stac_raster_dataset: Dataset
):
    resp = await client.post(
        "/stac/search", json={"bbox": [-74.10, 40.70, -73.90, 40.70]}
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Shared bbox parsing — invalid input stays invalid everywhere
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_inverted_latitude_bbox_rejected_on_every_surface(
    client: AsyncClient, stac_raster_dataset: Dataset, vector_dataset: Dataset
):
    responses = {
        "stac_items": await client.get(
            f"/stac/collections/{STAC_UNASSIGNED}/items",
            params={"bbox": INVERTED_BBOX},
        ),
        "stac_search": await client.get("/stac/search", params={"bbox": INVERTED_BBOX}),
        "ogc_items": await client.get(
            f"/collections/{vector_dataset.id}/items", params={"bbox": INVERTED_BBOX}
        ),
        "catalog_search": await client.get(
            "/search/datasets/", params={"bbox": INVERTED_BBOX}
        ),
    }
    statuses = {name: resp.status_code for name, resp in responses.items()}
    assert statuses == dict.fromkeys(statuses, 400), statuses


@pytest.mark.anyio
async def test_non_finite_bbox_rejected_on_every_surface(
    client: AsyncClient, stac_raster_dataset: Dataset, vector_dataset: Dataset
):
    """SEC-FU-06 survives the move to the shared parser on all callers."""
    responses = {
        "stac_items": await client.get(
            f"/stac/collections/{STAC_UNASSIGNED}/items", params={"bbox": NAN_BBOX}
        ),
        "stac_search": await client.get("/stac/search", params={"bbox": NAN_BBOX}),
        "ogc_items": await client.get(
            f"/collections/{vector_dataset.id}/items", params={"bbox": NAN_BBOX}
        ),
        "catalog_search": await client.get(
            "/search/datasets/", params={"bbox": NAN_BBOX}
        ),
        "export": await client.get(
            f"/datasets/{vector_dataset.id}/export",
            params={"format": "geojson", "bbox": NAN_BBOX},
        ),
    }
    statuses = {name: resp.status_code for name, resp in responses.items()}
    assert statuses == dict.fromkeys(statuses, 400), statuses


@pytest.mark.anyio
async def test_non_finite_bbox_rejected_by_stac_search_post(
    client: AsyncClient, stac_raster_dataset: Dataset
):
    """JSON 1e400 parses to +Inf — the POST body path must reject it too."""
    resp = await client.post(
        "/stac/search",
        content='{"bbox": [-74.10, 1e400, -73.90, 40.80]}',
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 400, resp.text
