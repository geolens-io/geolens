"""BUG-041 regression: raster ingest now populates dataset_assets.

The STAC-aligned ``dataset_assets`` table is read by the search/STAC/OGC asset
output path (``_build_stac_assets`` -> ``build_assets``) but was never written
by ingest, so STAC item assets were never advertised — the entire read path
operated on an always-empty input.

Disposition: POPULATE the table during raster ingest (additive, matches the
schema's documented intent: data/vrt + thumbnail + overview keys map exactly to
the COG/VRT + 256/512 quicklooks ingest already produces). Lower blast radius
than removing the migration-backed table + port + 3 reader call sites +
enterprise overlay.

These tests pin:
  - the row builder produces the correct stable keys / hrefs / media types, and
  - those rows make the previously-dead read path surface assets (verified on
    S3-published storage; local storage still omits them per GAP-031).
"""

import uuid

from app.modules.catalog.search.service import build_assets
from app.processing.ingest.tasks_raster import _build_dataset_asset_rows


class _FakeS3Provider:
    """Minimal storage provider that 'presigns' by echoing a signed URL."""

    def generate_presigned_get_url(self, key: str, expiration: int = 3600) -> str:
        return f"https://s3.example.com/{key}?sig=abc"


def _make_raster_dataset(dataset_id: str):
    from types import SimpleNamespace

    record = SimpleNamespace(record_type="raster_dataset")
    return SimpleNamespace(id=dataset_id, table_name=None, record=record)


class TestBuildDatasetAssetRows:
    def test_cog_rows(self):
        """Non-VRT raster -> data + thumbnail + overview rows with correct hrefs."""
        ds_id = uuid.uuid4()
        rows = _build_dataset_asset_rows(
            dataset_id=ds_id,
            cog_key="rasters/x/abc/source.cog.tif",
            ql256_key="rasters/x/abc/quicklook_256.png",
            ql512_key="rasters/x/abc/quicklook_512.png",
            cog_size=2048,
            is_manifest_vrt=False,
        )
        by_key = {r["key"]: r for r in rows}
        assert set(by_key) == {"data", "thumbnail", "overview"}
        assert by_key["data"]["href"] == "rasters/x/abc/source.cog.tif"
        assert by_key["data"]["roles"] == ["data"]
        assert by_key["data"]["size_bytes"] == 2048
        assert by_key["thumbnail"]["href"] == "rasters/x/abc/quicklook_256.png"
        assert by_key["thumbnail"]["media_type"] == "image/png"
        assert by_key["overview"]["href"] == "rasters/x/abc/quicklook_512.png"
        # All keys are allowed by chk_dataset_assets_key.
        assert all(
            r["key"] in {"data", "vrt", "thumbnail", "overview", "metadata"}
            for r in rows
        )

    def test_vrt_rows_use_vrt_key(self):
        """Manifest-VRT job -> primary key is 'vrt', not 'data'."""
        rows = _build_dataset_asset_rows(
            dataset_id=uuid.uuid4(),
            cog_key="rasters/x/abc/source.vrt",
            ql256_key="rasters/x/abc/quicklook_256.png",
            ql512_key="rasters/x/abc/quicklook_512.png",
            cog_size=None,
            is_manifest_vrt=True,
        )
        by_key = {r["key"]: r for r in rows}
        assert "vrt" in by_key
        assert "data" not in by_key
        assert by_key["vrt"]["href"] == "rasters/x/abc/source.vrt"


class TestReadPathNowLive:
    """The previously-dead read path surfaces assets once the rows exist."""

    def test_s3_published_surfaces_data_thumbnail_overview(self):
        """Feeding the built rows into build_assets (S3 + published) emits assets.

        Before BUG-041 these rows never existed, so build_assets only ever
        returned computed raster_tiles. Now the data/thumbnail/overview assets
        appear with presigned hrefs.
        """
        ds_id = "00000000-0000-0000-0000-0000000000aa"
        ds = _make_raster_dataset(ds_id)
        rows = _build_dataset_asset_rows(
            dataset_id=uuid.UUID(ds_id),
            cog_key="rasters/x/abc/source.cog.tif",
            ql256_key="rasters/x/abc/quicklook_256.png",
            ql512_key="rasters/x/abc/quicklook_512.png",
            cog_size=4096,
            is_manifest_vrt=False,
        )
        # build_assets consumes plain dicts; the ingest rows are dict-shaped.
        assets = build_assets(
            ds,
            "http://localhost:8080/api",
            stac_asset_rows=rows,
            record_status="published",
            storage_backend="s3",
            storage_provider=_FakeS3Provider(),
        )

        # Computed tiles still present...
        assert "raster_tiles" in assets
        # ...AND the dataset_assets-sourced entries now surface (read path live).
        assert "data" in assets
        assert "thumbnail" in assets
        assert "overview" in assets
        assert assets["data"]["href"].startswith("https://s3.example.com/")
        assert "source.cog.tif" in assets["data"]["href"]

    def test_local_storage_still_omits_per_gap031(self):
        """On local storage the rows resolve to None and are omitted (GAP-031).

        Populating the table must NOT regress GAP-031: local-storage hrefs have
        no safe proxy URL, so the read path skips them — only computed
        raster_tiles remain.
        """
        ds_id = "00000000-0000-0000-0000-0000000000bb"
        ds = _make_raster_dataset(ds_id)
        rows = _build_dataset_asset_rows(
            dataset_id=uuid.UUID(ds_id),
            cog_key="rasters/x/abc/source.cog.tif",
            ql256_key="rasters/x/abc/quicklook_256.png",
            ql512_key="rasters/x/abc/quicklook_512.png",
            cog_size=4096,
            is_manifest_vrt=False,
        )
        assets = build_assets(
            ds,
            "http://localhost:8080/api",
            stac_asset_rows=rows,
            record_status="published",
            storage_backend="local",
        )
        assert "raster_tiles" in assets
        assert "data" not in assets
        assert "thumbnail" not in assets
        assert "overview" not in assets
