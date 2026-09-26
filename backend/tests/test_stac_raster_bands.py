"""STAC items publish raster:bands as Band objects with only an allowed nodata."""

import uuid

import pytest

from tests.factories import create_raster_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _raster(session, band_info: list[dict], nodata: str | None) -> str:
    dataset = await create_raster_dataset(
        session,
        created_by=await get_user_id(session, "admin"),
        name=f"STAC bands {uuid.uuid4().hex[:8]}",
        create_raster_asset=True,
        raster_asset_kwargs={
            "band_count": len(band_info),
            "band_info": band_info,
            "nodata": nodata,
        },
    )
    return str(dataset.id)


async def _published_bands(client, headers, dataset_id: str) -> list:
    """The item's raster:bands from /stac/items and from /stac/search."""
    item = await client.get(f"/stac/items/{dataset_id}", headers=headers)
    search = await client.get(
        "/stac/search", params={"ids": dataset_id}, headers=headers
    )
    assert item.status_code == 200, item.text
    assert search.status_code == 200, search.text
    ((found,),) = [search.json()["features"]]
    return [
        item.json()["properties"].get("raster:bands"),
        found["properties"].get("raster:bands"),
    ]


async def test_a_band_without_nodata_has_no_nodata_key(
    client, admin_auth_header, test_db_session
):
    band = {"index": 1, "dtype": "uint8", "nodata": None, "color_interp": "Gray"}
    dataset_id = await _raster(test_db_session, [band], None)

    for bands in await _published_bands(client, admin_auth_header, dataset_id):
        assert bands == [{"name": "Gray", "data_type": "uint8"}]
    # The OGC record keeps its explicit null.
    record = await client.get(
        f"/collections/datasets/items/{dataset_id}", headers=admin_auth_header
    )
    assert record.json()["properties"]["raster:bands"][0]["nodata"] is None


async def test_statistics_only_bands_of_a_remote_cog_are_left_out(
    client, admin_auth_header, test_db_session
):
    band_info = [{"min": 0, "max": 255, "mean": 12.5} for _ in range(3)]
    dataset_id = await _raster(test_db_session, band_info, None)

    for bands in await _published_bands(client, admin_auth_header, dataset_id):
        assert bands is None


@pytest.mark.parametrize(
    ("stored", "published"), [("0.0", 0.0), ("nan", "nan")], ids=["number", "nan"]
)
async def test_an_allowed_nodata_is_kept(
    client, admin_auth_header, test_db_session, stored, published
):
    band = {"index": 1, "dtype": "float32", "nodata": stored}
    dataset_id = await _raster(test_db_session, [band], stored)

    for bands in await _published_bands(client, admin_auth_header, dataset_id):
        assert bands == [{"data_type": "float32", "nodata": published}]
