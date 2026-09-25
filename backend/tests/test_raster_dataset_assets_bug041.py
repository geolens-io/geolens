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
  - those rows make the previously-dead read path surface assets: presigned
    hrefs on S3, the download and quicklook routes on local storage.
"""

import inspect
import uuid

import pytest

from app.modules.catalog.search.service import build_assets
from app.processing.ingest import tasks_raster as _tasks_raster
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

    def _local_assets(
        self, *, record_type="raster_dataset", status="published", cog_download=True
    ):
        ds_id = "00000000-0000-0000-0000-0000000000bb"
        ds = _make_raster_dataset(ds_id)
        ds.record.record_type = record_type
        rows = _build_dataset_asset_rows(
            dataset_id=uuid.UUID(ds_id),
            cog_key="rasters/x/abc/source.cog.tif",
            ql256_key="rasters/x/abc/quicklook_256.png",
            ql512_key="rasters/x/abc/quicklook_512.png",
            cog_size=4096,
            is_manifest_vrt=record_type == "vrt_dataset",
        )
        return ds_id, build_assets(
            ds,
            "http://localhost:8080/api",
            stac_asset_rows=rows,
            record_status=status,
            storage_backend="local",
            cog_download=cog_download,
        )

    def test_local_storage_published_raster_points_at_the_serving_routes(self):
        """A local key has no URL of its own; the download and quicklook routes serve it."""
        ds_id, assets = self._local_assets()
        api = f"http://localhost:8080/api/datasets/{ds_id}"
        assert "raster_tiles" in assets
        assert assets["data"]["href"] == f"{api}/download/cog"
        assert assets["data"]["type"].endswith("profile=cloud-optimized")
        assert assets["data"]["roles"] == ["data"]
        assert assets["thumbnail"]["href"] == f"{api}/quicklook?size=256&pv=0"
        assert assets["overview"]["href"] == f"{api}/quicklook?size=512&pv=0"
        assert not [a for a in assets.values() if "/assets/" in a["href"]]

    def test_quicklooks_carry_the_tile_cache_versions(self):
        """The quicklook route is cached publicly; a replacement rolls its URL."""
        ds_id = "00000000-0000-0000-0000-0000000000cc"
        ds = _make_raster_dataset(ds_id)
        ds.tile_cache_version = 3
        ds.publication_version = 2
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
        assert assets["thumbnail"]["href"].endswith("quicklook?size=256&v=3&pv=2")

    def test_local_storage_without_cog_download_omits_only_data(self):
        """A caller the download route would refuse gets the quicklooks only."""
        _, assets = self._local_assets(cog_download=False)
        assert "data" not in assets
        assert {"raster_tiles", "thumbnail", "overview"} <= set(assets)

    @pytest.mark.parametrize(
        ("record_type", "status"),
        [("raster_dataset", "draft"), ("vrt_dataset", "published")],
    )
    def test_local_storage_omits_unpublished_and_vrt_rows(self, record_type, status):
        """Unpublished rasters and VRTs (no single COG) keep only raster_tiles."""
        _, assets = self._local_assets(record_type=record_type, status=status)
        assert set(assets) == {"raster_tiles"}


class TestIngestWritePathPortResolution:
    """Regression for the BUG-041 *follow-up* crash.

    The original BUG-041 fix wrote the dataset_assets rows during ingest via
    ``get_processing_port().dataset_asset_orm_class()`` — but that ORM accessor
    lives on the **CatalogPort**, not the ProcessingPort. Every COG/VRT ingest
    therefore raised ``'DefaultProcessingPort' object has no attribute
    'dataset_asset_orm_class'`` and failed. The unit tests above never caught it
    because they exercise the pure row builder and the read path, never the
    ingest *write path's* port resolution.

    These tests use the REAL default ports (no mocks) and pin the exact
    cross-port contract the write path depends on.
    """

    def test_dataset_asset_orm_resolves_via_catalog_port_and_instantiates(self):
        """The fixed write path's two operations, against the real ports/ORM.

        ``DatasetAsset = get_catalog_port().dataset_asset_orm_class()`` then
        ``DatasetAsset(**row)`` — exactly what ingest_raster does. Before the
        fix the equivalent call on the processing port raised AttributeError.
        """
        from app.platform.extensions import get_catalog_port, get_processing_port
        from app.processing.raster.models import DatasetAsset

        # Exact resolution the fixed write path performs (real port, no mock).
        resolved = get_catalog_port().dataset_asset_orm_class()
        assert resolved is DatasetAsset

        rows = _build_dataset_asset_rows(
            dataset_id=uuid.uuid4(),
            cog_key="rasters/x/abc/source.cog.tif",
            ql256_key="rasters/x/abc/quicklook_256.png",
            ql512_key="rasters/x/abc/quicklook_512.png",
            cog_size=1024,
            is_manifest_vrt=False,
        )
        # Instantiate the ORM from each built row (write path: DatasetAsset(**row)).
        instances = [resolved(**row) for row in rows]
        assert {i.key for i in instances} == {"data", "thumbnail", "overview"}

        # Boundary: the accessor is NOT on the processing port — calling it there
        # (the original bug) raised AttributeError on every ingest.
        assert not hasattr(get_processing_port(), "dataset_asset_orm_class")
        # ...while the *sibling* call the write path makes (line 608) correctly
        # DOES live on the processing port.
        assert hasattr(get_processing_port(), "get_record_distribution_orm_class")

    def test_ingest_source_resolves_dataset_asset_via_catalog_port(self):
        """Guard the actual file: dataset_asset_orm_class must come from the
        catalog port, never the processing port (the regression that shipped)."""
        src = inspect.getsource(_tasks_raster)
        assert "get_catalog_port().dataset_asset_orm_class()" in src
        # The original (broken) form must not reappear under any port alias.
        assert "_get_port().dataset_asset_orm_class()" not in src
        assert "get_processing_port().dataset_asset_orm_class()" not in src
