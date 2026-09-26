"""STAC items publish raster:bands on the data asset, with only an allowed nodata."""

import json
import uuid
from pathlib import Path

import pystac
import pystac.stac_io
import pytest
from pystac.validation.stac_validator import JsonSchemaSTACValidator

from app.processing.raster.models import DatasetAsset
from app.standards.stac.serializer import STAC_RASTER_EXTENSION_URI

from tests.factories import create_raster_dataset, get_user_id

pytestmark = pytest.mark.anyio

# The published raster extension v1.1.0 schema, kept here so no test fetches it.
_RASTER_SCHEMA = Path(__file__).parent / "fixtures/stac/raster-v1.1.0-schema.json"


async def _raster(
    session,
    band_info: list[dict],
    nodata: str | None,
    dtype: str | None = None,
    *,
    data_asset: bool = True,
) -> str:
    dataset = await create_raster_dataset(
        session,
        created_by=await get_user_id(session, "admin"),
        name=f"STAC bands {uuid.uuid4().hex[:8]}",
        create_raster_asset=True,
        raster_asset_kwargs={
            "band_count": len(band_info),
            "band_info": band_info,
            "nodata": nodata,
            "dtype": dtype,
        },
    )
    if data_asset:
        session.add(
            DatasetAsset(
                dataset_id=dataset.id,
                key="data",
                href=f"rasters/{dataset.id}/abc/source.cog.tif",
                media_type="image/tiff; application=geotiff",
                roles=["data"],
            )
        )
        await session.commit()
    return str(dataset.id)


async def _published_items(client, headers, dataset_id: str) -> list[dict]:
    """The item from /stac/items and from /stac/search."""
    item = await client.get(f"/stac/items/{dataset_id}", headers=headers)
    search = await client.get(
        "/stac/search", params={"ids": dataset_id}, headers=headers
    )
    assert item.status_code == 200, item.text
    assert search.status_code == 200, search.text
    ((found,),) = [search.json()["features"]]
    return [item.json(), found]


async def _published_bands(client, headers, dataset_id: str) -> list:
    """The raster:bands of the item's data asset, from both routes."""
    items = await _published_items(client, headers, dataset_id)
    for item in items:
        assert "raster:bands" not in item["properties"]
    return [item["assets"]["data"].get("raster:bands") for item in items]


def _validate_raster_extension(item: dict, monkeypatch) -> None:
    """Validate ``item`` against the raster extension schema, offline."""

    def _no_fetch(*args, **kwargs):
        raise AssertionError("a schema was fetched")

    monkeypatch.setattr(pystac.stac_io.DefaultStacIO, "read_text_from_href", _no_fetch)
    validator = JsonSchemaSTACValidator()
    validator.schema_cache[STAC_RASTER_EXTENSION_URI] = json.loads(
        _RASTER_SCHEMA.read_text()
    )
    validator.validate_extension(
        item, pystac.STACObjectType.ITEM, "1.0.0", STAC_RASTER_EXTENSION_URI
    )


async def test_the_bands_are_on_the_data_asset_and_meet_the_raster_schema(
    client, admin_auth_header, test_db_session, monkeypatch
):
    band_info = [{"min": 0, "max": 255, "mean": 12.5 + band} for band in range(3)]
    dataset_id = await _raster(test_db_session, band_info, "0", dtype="uint8")

    for item in await _published_items(client, admin_auth_header, dataset_id):
        assert "raster:bands" not in item["properties"]
        assert [key for key, a in item["assets"].items() if "raster:bands" in a] == [
            "data"
        ]
        assert STAC_RASTER_EXTENSION_URI in item["stac_extensions"]
        _validate_raster_extension(item, monkeypatch)

        # The schema does check the asset's bands.
        item["assets"]["data"]["raster:bands"][0]["nodata"] = None
        with pytest.raises(pystac.errors.STACValidationError):
            _validate_raster_extension(item, monkeypatch)


async def test_an_item_without_a_data_asset_publishes_no_bands(
    client, admin_auth_header, test_db_session
):
    band = {"index": 1, "dtype": "uint8", "nodata": "0", "color_interp": "Gray"}
    dataset_id = await _raster(test_db_session, [band], "0", data_asset=False)

    for item in await _published_items(client, admin_auth_header, dataset_id):
        assert "data" not in item["assets"]
        assert "raster:bands" not in item["properties"]
        assert not [a for a in item["assets"].values() if "raster:bands" in a]
        assert STAC_RASTER_EXTENSION_URI not in item.get("stac_extensions", [])


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


@pytest.mark.parametrize("count", [1, 3], ids=["one-band", "three-bands"])
async def test_a_remote_cogs_bands_carry_their_statistics_and_data_type(
    client, admin_auth_header, test_db_session, count
):
    # fetch_cog_info's band_info: Titiler's statistics, and no nodata.
    band_info = [{"min": 0, "max": 255, "mean": 12.5 + band} for band in range(count)]
    dataset_id = await _raster(test_db_session, band_info, None, dtype="uint8")

    for bands in await _published_bands(client, admin_auth_header, dataset_id):
        assert bands == [
            {
                "data_type": "uint8",
                "statistics": {"minimum": 0, "maximum": 255, "mean": 12.5 + band},
            }
            for band in range(count)
        ]


async def test_a_remote_cogs_bands_take_the_rasters_nodata(
    client, admin_auth_header, test_db_session
):
    # fetch_cog_info keeps the nodata on the raster, not on its bands.
    band_info = [{"min": 0, "max": 255, "mean": 12.5 + band} for band in range(3)]
    dataset_id = await _raster(test_db_session, band_info, "0", dtype="uint8")

    for bands in await _published_bands(client, admin_auth_header, dataset_id):
        assert bands == [
            {
                "data_type": "uint8",
                "nodata": 0.0,
                "statistics": {"minimum": 0, "maximum": 255, "mean": 12.5 + band},
            }
            for band in range(3)
        ]


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
