"""Codebase audit 2026-08-30, band_info and STAC nodata (tracked in #1778).

``raster:bands`` published a numeric nodata as the string the producer stored,
published ``[{}, {}, {}]`` for a remotely described COG, and the OGC Records
peer dropped the band name of every locally ingested raster because it read a
key no producer writes.
"""

import uuid

import pytest


def _raster_asset(band_info):
    from app.processing.raster.models import RasterAsset

    return RasterAsset(
        dataset_id=uuid.uuid4(),
        asset_uri="rasters/x/y/source.cog.tif",
        sha256="0" * 64,
        band_info=band_info,
    )


class TestBandInfoShapes:
    def test_stac_nodata_is_published_as_a_number(self) -> None:
        """``extract_raster_metadata`` stores ``str(src.nodata)``."""
        asset = _raster_asset(
            [{"index": 1, "dtype": "uint8", "nodata": "0.0", "color_interp": "Red"}]
        )
        bands = asset.to_stac_properties()["raster:bands"]
        assert bands == [{"data_type": "uint8", "nodata": 0.0, "name": "Red"}]
        assert isinstance(bands[0]["nodata"], float)

    @pytest.mark.parametrize("sentinel", ["nan", "inf", "-inf", "NaN"])
    def test_the_extension_sentinels_stay_strings(self, sentinel: str) -> None:
        asset = _raster_asset([{"dtype": "float32", "nodata": sentinel}])
        bands = asset.to_stac_properties()["raster:bands"]
        assert bands[0]["nodata"] == sentinel.lower()

    def test_an_unparseable_nodata_is_dropped(self) -> None:
        asset = _raster_asset([{"dtype": "uint8", "nodata": "unknown"}])
        assert "nodata" not in asset.to_stac_properties()["raster:bands"][0]

    def test_a_remotely_described_cog_publishes_no_empty_bands(self) -> None:
        """``fetch_cog_info`` writes ``{min, max, mean}`` and nothing else."""
        asset = _raster_asset([{"min": 0, "max": 255, "mean": 12.5} for _ in range(3)])
        assert "raster:bands" not in asset.to_stac_properties()

    def test_the_ogc_records_serializer_reports_the_band_name(self) -> None:
        """``color_interp`` is the key the local producer writes; nothing
        writes the ``name`` this serializer used to read."""
        bands = _ogc_bands(
            [
                {"index": 1, "dtype": "uint8", "color_interp": "Red"},
                {"index": 2, "dtype": "uint8", "color_interp": "Green"},
                {"index": 3, "dtype": "uint8", "color_interp": "Blue"},
            ]
        )
        assert [band["name"] for band in bands] == ["Red", "Green", "Blue"]

    def test_the_two_serializers_agree_on_one_band_info(self) -> None:
        band_info = [
            {"index": 1, "dtype": "uint16", "nodata": "0.0", "color_interp": "Gray"}
        ]
        stac = _raster_asset(band_info).to_stac_properties()["raster:bands"]
        ogc = _ogc_bands(band_info)
        assert stac[0]["name"] == ogc[0]["name"] == "Gray"
        assert stac[0]["nodata"] == ogc[0]["nodata"] == 0.0


def _ogc_bands(band_info: list[dict]) -> list[dict]:
    """``raster:bands`` as the OGC Records representation publishes them.

    Transient ORM instances rather than a session: the serializer is
    synchronous and reads attributes, so nothing here needs to be persisted.
    """
    from datetime import datetime, timezone

    from app.modules.catalog.datasets.domain.models import Dataset, Record
    from app.modules.catalog.search.service_records import dataset_to_ogc_record

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record = Record(
        id=uuid.uuid4(),
        title="raster",
        record_type="raster_dataset",
        visibility="public",
        record_status="published",
        created_at=now,
        updated_at=now,
    )
    dataset = Dataset(
        id=uuid.uuid4(), record_id=record.id, table_name="raster_x", srid=4326
    )
    dataset.record = record
    result = dataset_to_ogc_record(
        dataset,
        "https://example.test",
        raster_meta={"band_count": len(band_info), "band_info": band_info},
    )
    return result["properties"].get("raster:bands", [])
