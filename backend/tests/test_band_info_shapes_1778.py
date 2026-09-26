"""Either producer's band_info reaches OGC records and STAC items as raster:bands."""

import uuid

import pytest


class TestBandInfoShapes:
    def test_stac_nodata_is_published_as_a_number(self) -> None:
        """``extract_raster_metadata`` stores ``str(src.nodata)``."""
        bands = _stac_bands(
            [{"index": 1, "dtype": "uint8", "nodata": "0.0", "color_interp": "Red"}]
        )
        assert bands == [{"data_type": "uint8", "nodata": 0.0, "name": "Red"}]
        assert isinstance(bands[0]["nodata"], float)

    @pytest.mark.parametrize("sentinel", ["nan", "inf", "-inf", "NaN"])
    def test_the_extension_sentinels_stay_strings(self, sentinel: str) -> None:
        bands = _stac_bands([{"dtype": "float32", "nodata": sentinel}])
        assert bands[0]["nodata"] == sentinel.lower()

    def test_an_unparseable_nodata_is_dropped(self) -> None:
        bands = _stac_bands([{"dtype": "uint8", "nodata": "unknown"}])
        assert bands == [{"data_type": "uint8"}]

    def test_a_remotely_described_cog_publishes_no_empty_bands(self) -> None:
        """``fetch_cog_info`` writes ``{min, max, mean}`` and nothing else."""
        assert (
            _stac_bands([{"min": 0, "max": 255, "mean": 12.5} for _ in range(3)]) == []
        )

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


def _ogc_record(band_info: list[dict]) -> dict:
    """The OGC record of a raster whose band_info is ``band_info``.

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
    return dataset_to_ogc_record(
        dataset,
        "https://example.test",
        raster_meta={"band_count": len(band_info), "band_info": band_info},
    )


def _ogc_bands(band_info: list[dict]) -> list[dict]:
    return _ogc_record(band_info)["properties"].get("raster:bands", [])


def _stac_bands(band_info: list[dict]) -> list[dict]:
    from app.standards.stac.serializer import ogc_record_to_stac_item

    item = ogc_record_to_stac_item(
        _ogc_record(band_info), stac_api_url="https://example.test/stac"
    )
    return item["properties"].get("raster:bands", [])
