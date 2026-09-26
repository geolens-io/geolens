"""STAC items publish gsd in metres from a raster's stored CRS facts."""

import uuid

import pytest
import rasterio.crs

from app.core.geo import crs_columns, wkt_crs_facts

from tests.factories import create_raster_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _raster(session, epsg: int, res: float) -> str:
    """A raster in ``epsg`` with ``res``-unit pixels and its CRS facts stored."""
    wkt = rasterio.crs.CRS.from_epsg(epsg).to_wkt(version="WKT2_2019")
    dataset = await create_raster_dataset(
        session,
        created_by=await get_user_id(session, "admin"),
        name=f"STAC gsd {uuid.uuid4().hex[:8]}",
        create_raster_asset=True,
        raster_asset_kwargs={
            "epsg": epsg,
            **crs_columns({"crs_wkt": wkt, **wkt_crs_facts(wkt)}),
            "res_x": res,
            "res_y": -res,
            "width": 100,
            "height": 100,
        },
    )
    return str(dataset.id)


@pytest.mark.parametrize(
    ("epsg", "gsd"),
    [(32618, 10.0), (2263, 3.048006)],
    ids=["utm-metres", "us-survey-feet"],
)
async def test_a_projected_raster_publishes_gsd_in_metres(
    client, admin_auth_header, test_db_session, epsg, gsd
):
    dataset_id = await _raster(test_db_session, epsg, 10.0)

    item = await client.get(f"/stac/items/{dataset_id}", headers=admin_auth_header)
    search = await client.get(
        "/stac/search", params={"ids": dataset_id}, headers=admin_auth_header
    )

    assert item.status_code == 200, item.text
    assert item.json()["properties"]["gsd"] == pytest.approx(gsd, rel=1e-4)
    assert search.status_code == 200, search.text
    ((found,),) = [search.json()["features"]]
    assert found["properties"]["gsd"] == pytest.approx(gsd, rel=1e-4)


async def test_a_geographic_raster_publishes_no_gsd(
    client, admin_auth_header, test_db_session
):
    dataset_id = await _raster(test_db_session, 4326, 0.0001)

    item = await client.get(f"/stac/items/{dataset_id}", headers=admin_auth_header)

    assert item.status_code == 200, item.text
    assert "gsd" not in item.json()["properties"]


async def test_the_record_keeps_gsd_in_crs_units(
    client, admin_auth_header, test_db_session
):
    dataset_id = await _raster(test_db_session, 2263, 10.0)

    record = await client.get(
        f"/collections/datasets/items/{dataset_id}", headers=admin_auth_header
    )

    assert record.status_code == 200, record.text
    assert record.json()["properties"]["gsd"] == 10.0
    assert record.json()["properties"]["crs_is_geographic"] is False
