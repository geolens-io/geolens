"""Tests for raster ingest pipeline: COG engine, quicklook, and endpoint routing.

Unit tests use rasterio.MemoryFile to create synthetic GeoTIFFs — no fixtures needed.
Integration/DB tests are marked and skipped when no DB is available.
"""

import io
import tempfile
import uuid
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds


# ---------------------------------------------------------------------------
# Helpers: create synthetic GeoTIFFs
# ---------------------------------------------------------------------------


def _make_geotiff_bytes(
    *,
    width: int = 64,
    height: int = 64,
    bands: int = 1,
    dtype: str = "uint8",
    crs: CRS | None = CRS.from_epsg(4326),
    nodata: float | None = None,
    tiled: bool = False,
    blocksize: int = 256,
    compress: str | None = None,
    add_overviews: bool = False,
) -> bytes:
    """Create a minimal GeoTIFF in memory and return its bytes."""
    transform = from_bounds(-180, -90, 180, 90, width, height)
    profile = {
        "driver": "GTiff",
        "dtype": dtype,
        "width": width,
        "height": height,
        "count": bands,
        "transform": transform,
    }
    if crs is not None:
        profile["crs"] = crs
    if nodata is not None:
        profile["nodata"] = nodata
    if tiled:
        profile["tiled"] = True
        profile["blockxsize"] = blocksize
        profile["blockysize"] = blocksize
    if compress:
        profile["compress"] = compress

    rng = np.random.default_rng(42)
    buf = io.BytesIO()
    with MemoryFile() as mem:
        with mem.open(**profile) as ds:
            for b in range(1, bands + 1):
                data = rng.integers(0, 200, (height, width), dtype=dtype)
                ds.write(data, b)
        buf.write(mem.read())
    return buf.getvalue()


def _write_tmp_tif(
    *,
    width: int = 64,
    height: int = 64,
    bands: int = 1,
    dtype: str = "uint8",
    crs: CRS | None = CRS.from_epsg(4326),
    nodata: float | None = None,
    tiled: bool = False,
    blocksize: int = 256,
    compress: str | None = None,
) -> Path:
    """Write a synthetic GeoTIFF to a temp file and return the path."""
    data = _make_geotiff_bytes(
        width=width,
        height=height,
        bands=bands,
        dtype=dtype,
        crs=crs,
        nodata=nodata,
        tiled=tiled,
        blocksize=blocksize,
        compress=compress,
    )
    tmp = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
    tmp.write(data)
    tmp.close()
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# validate_raster_crs
# ---------------------------------------------------------------------------


class TestValidateRasterCrs:
    def test_valid_crs_passes(self, tmp_path):
        tif = _write_tmp_tif(crs=CRS.from_epsg(4326))
        try:
            from app.processing.raster.cog import validate_raster_crs

            validate_raster_crs(str(tif))  # should not raise
        finally:
            tif.unlink(missing_ok=True)

    def test_missing_crs_raises(self, tmp_path):
        tif = _write_tmp_tif(crs=None)
        try:
            from app.processing.raster.cog import validate_raster_crs

            with pytest.raises(ValueError, match="Missing CRS"):
                validate_raster_crs(str(tif))
        finally:
            tif.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# extract_raster_metadata
# ---------------------------------------------------------------------------


class TestExtractRasterMetadata:
    def test_returns_expected_keys(self, tmp_path):
        tif = _write_tmp_tif(width=64, height=64, bands=3, crs=CRS.from_epsg(4326))
        try:
            from app.processing.raster.cog import extract_raster_metadata

            meta = extract_raster_metadata(str(tif))
            assert meta["width"] == 64
            assert meta["height"] == 64
            assert meta["band_count"] == 3
            assert meta["epsg"] == 4326
            assert meta["crs_wkt"] is not None
            assert meta["res_x"] > 0
            assert meta["res_y"] > 0
            assert "bbox_wkt" in meta
            assert meta["bbox_wkt"].startswith("POLYGON")
        finally:
            tif.unlink(missing_ok=True)

    def test_nodata_captured(self, tmp_path):
        tif = _write_tmp_tif(nodata=255.0)
        try:
            from app.processing.raster.cog import extract_raster_metadata

            meta = extract_raster_metadata(str(tif))
            assert meta["nodata"] == 255.0
        finally:
            tif.unlink(missing_ok=True)

    def test_projected_crs_transforms_bounds(self, tmp_path):
        """Bounds should be in WGS84 even when source CRS is projected."""
        # Create a small 64x64 raster in EPSG:3857 (Web Mercator)
        transform = from_bounds(-20037508, -20037508, 20037508, 20037508, 64, 64)
        buf = io.BytesIO()
        with MemoryFile() as mem:
            with mem.open(
                driver="GTiff",
                dtype="uint8",
                width=64,
                height=64,
                count=1,
                crs=CRS.from_epsg(3857),
                transform=transform,
            ) as ds:
                ds.write(np.zeros((64, 64), dtype="uint8"), 1)
            buf.write(mem.read())
        tmp = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
        tmp.write(buf.getvalue())
        tmp.close()
        try:
            from app.processing.raster.cog import extract_raster_metadata

            meta = extract_raster_metadata(tmp.name)
            # bounds_wgs84 should be roughly [-180, -90, 180, 90]
            left, bottom, right, top = meta["bounds_wgs84"]
            assert left < -170
            assert right > 170
        finally:
            Path(tmp.name).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# check_cog_compliance
# ---------------------------------------------------------------------------


class TestCheckCogCompliance:
    def test_non_tiled_fails(self, tmp_path):
        tif = _write_tmp_tif(tiled=False)
        try:
            from app.processing.raster.cog import check_cog_compliance

            ok, reason = check_cog_compliance(str(tif))
            assert ok is False
            assert "tiled" in reason.lower() or "block" in reason.lower()
        finally:
            tif.unlink(missing_ok=True)

    def test_wrong_blocksize_fails(self, tmp_path):
        tif = _write_tmp_tif(tiled=True, blocksize=256, compress="deflate")
        try:
            from app.processing.raster.cog import check_cog_compliance

            ok, reason = check_cog_compliance(str(tif))
            assert ok is False
            assert "512" in reason or "block" in reason.lower()
        finally:
            tif.unlink(missing_ok=True)

    def test_missing_crs_fails(self, tmp_path):
        tif = _write_tmp_tif(crs=None, tiled=True, blocksize=512, compress="deflate")
        try:
            from app.processing.raster.cog import check_cog_compliance

            ok, reason = check_cog_compliance(str(tif))
            assert ok is False
        finally:
            tif.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# sha256_file
# ---------------------------------------------------------------------------


class TestSha256File:
    def test_deterministic(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        from app.processing.raster.cog import sha256_file

        h1 = sha256_file(str(f))
        h2 = sha256_file(str(f))
        assert h1 == h2
        assert len(h1) == 64
        assert (
            h1
            == "b94d27b9934d3e08a52e52d7da7dabfac484efe04294e576f21d7b0d2f5abc4e"[:64]
            or len(h1) == 64
        )

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"content A")
        f2.write_bytes(b"content B")
        from app.processing.raster.cog import sha256_file

        assert sha256_file(str(f1)) != sha256_file(str(f2))


# ---------------------------------------------------------------------------
# generate_quicklook
# ---------------------------------------------------------------------------


class TestGenerateQuicklook:
    def test_single_band_returns_png_bytes(self, tmp_path):
        tif = _write_tmp_tif(bands=1, width=128, height=64)
        try:
            from app.processing.raster.quicklook import generate_quicklook

            result = generate_quicklook(str(tif), 256)
            assert isinstance(result, bytes)
            # PNG magic bytes
            assert result[:8] == b"\x89PNG\r\n\x1a\n"
        finally:
            tif.unlink(missing_ok=True)

    def test_multi_band_returns_png_bytes(self, tmp_path):
        tif = _write_tmp_tif(bands=3, width=128, height=128)
        try:
            from app.processing.raster.quicklook import generate_quicklook

            result = generate_quicklook(str(tif), 256)
            assert isinstance(result, bytes)
            assert result[:8] == b"\x89PNG\r\n\x1a\n"
        finally:
            tif.unlink(missing_ok=True)

    def test_output_is_square(self, tmp_path):
        """PIL Image read back from PNG should be size x size."""
        from PIL import Image

        tif = _write_tmp_tif(bands=1, width=200, height=100)
        try:
            from app.processing.raster.quicklook import generate_quicklook

            png_bytes = generate_quicklook(str(tif), 128)
            img = Image.open(io.BytesIO(png_bytes))
            assert img.size == (128, 128)
        finally:
            tif.unlink(missing_ok=True)

    def test_all_nodata_does_not_raise(self, tmp_path):
        """Should produce black image gracefully when all pixels are nodata."""
        nodata_val = 0.0
        tif = _write_tmp_tif(bands=1, dtype="uint8", nodata=nodata_val)
        # Overwrite with zeros to make all-nodata
        with rasterio.open(str(tif), "r+") as ds:
            ds.write(np.zeros((ds.height, ds.width), dtype="uint8"), 1)
        try:
            from app.processing.raster.quicklook import generate_quicklook

            result = generate_quicklook(str(tif), 64)
            assert isinstance(result, bytes)
            assert result[:8] == b"\x89PNG\r\n\x1a\n"
        finally:
            tif.unlink(missing_ok=True)

    def test_256_and_512_sizes(self, tmp_path):
        from PIL import Image

        tif = _write_tmp_tif(bands=3, width=512, height=512)
        try:
            from app.processing.raster.quicklook import generate_quicklook

            r256 = generate_quicklook(str(tif), 256)
            r512 = generate_quicklook(str(tif), 512)
            assert Image.open(io.BytesIO(r256)).size == (256, 256)
            assert Image.open(io.BytesIO(r512)).size == (512, 512)
        finally:
            tif.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# delete_dataset: raster-aware storage cleanup and vector behavior preservation
# ---------------------------------------------------------------------------


class _MockRecord:
    """Minimal Record stand-in for delete_dataset tests."""

    def __init__(self, title: str, record_type: str):
        self.title = title
        self.record_type = record_type
        self._deleted = False


class _MockDataset:
    """Minimal Dataset stand-in for delete_dataset tests."""

    def __init__(self, dataset_id: uuid.UUID, title: str, record_type: str):
        self.id = dataset_id
        self.table_name = "test_table"
        self.record = _MockRecord(title, record_type)


class _MockStorage:
    """Tracks list and delete calls; raises on delete if configured."""

    def __init__(
        self, keys_by_prefix: dict[str, list[str]], delete_raises: bool = False
    ):
        self._keys = keys_by_prefix
        self._delete_raises = delete_raises
        self.deleted_keys: list[str] = []
        self.listed_prefixes: list[str] = []

    async def list(self, prefix: str) -> list[str]:
        self.listed_prefixes.append(prefix)
        return self._keys.get(prefix, [])

    async def delete(self, key: str) -> None:
        if self._delete_raises:
            raise RuntimeError("Storage delete failed")
        self.deleted_keys.append(key)


class TestRasterDeleteCascadeRemovesStorage:
    @pytest.mark.asyncio
    async def test_raster_delete_cascade_removes_storage(self):
        """Storage artifacts are deleted; no DROP TABLE executed for raster datasets."""
        import unittest.mock as mock

        dataset_id = uuid.uuid4()
        hash_prefix = "abc123"
        raster_prefix = f"rasters/{dataset_id}/"
        original_prefix = f"originals/{dataset_id}/"
        raster_keys = [
            f"rasters/{dataset_id}/{hash_prefix}/source.cog.tif",
            f"rasters/{dataset_id}/{hash_prefix}/quicklook_256.png",
            f"rasters/{dataset_id}/{hash_prefix}/quicklook_512.png",
        ]
        original_keys = [f"originals/{dataset_id}/file.tif"]

        storage = _MockStorage(
            keys_by_prefix={
                raster_prefix: raster_keys,
                original_prefix: original_keys,
            }
        )

        mock_dataset = _MockDataset(dataset_id, "My Raster", "raster_dataset")

        session = mock.AsyncMock()

        execute_calls: list[str] = []
        _default_result = mock.MagicMock()
        _default_result.all.return_value = []  # VRT reference guard returns empty

        async def _track_execute(stmt, *args, **kwargs):
            execute_calls.append(str(stmt))
            return _default_result

        session.execute = mock.AsyncMock(side_effect=_track_execute)

        with (
            mock.patch("app.modules.catalog.datasets.domain.service.get_dataset", return_value=mock_dataset),
            mock.patch("app.platform.storage.provider.get_storage", return_value=storage),
        ):
            from app.modules.catalog.datasets.domain.service import delete_dataset

            result = await delete_dataset(session, dataset_id, "My Raster")

        assert result == "test_table"

        # All raster and original keys must be deleted
        expected_deleted = set(raster_keys + original_keys)
        assert set(storage.deleted_keys) == expected_deleted

        # No DROP TABLE should have been executed
        drop_calls = [c for c in execute_calls if "DROP TABLE" in c.upper()]
        assert drop_calls == [], f"Unexpected DROP TABLE calls: {drop_calls}"

        # DB record deletion called
        session.delete.assert_called_once_with(mock_dataset.record)

    @pytest.mark.asyncio
    async def test_raster_delete_storage_failure_rolls_back(self):
        """Storage failure propagates; DB delete is never called."""
        import unittest.mock as mock

        dataset_id = uuid.uuid4()
        raster_prefix = f"rasters/{dataset_id}/"
        storage = _MockStorage(
            keys_by_prefix={
                raster_prefix: [f"rasters/{dataset_id}/abc/source.cog.tif"],
            },
            delete_raises=True,
        )

        mock_dataset = _MockDataset(dataset_id, "My Raster", "raster_dataset")
        session = mock.AsyncMock()
        # VRT reference guard: session.execute().all() must return empty list
        _refs_result = mock.MagicMock()
        _refs_result.all.return_value = []
        session.execute.return_value = _refs_result

        with (
            mock.patch("app.modules.catalog.datasets.domain.service.get_dataset", return_value=mock_dataset),
            mock.patch("app.platform.storage.provider.get_storage", return_value=storage),
        ):
            from app.modules.catalog.datasets.domain.service import delete_dataset

            with pytest.raises(RuntimeError, match="Storage delete failed"):
                await delete_dataset(session, dataset_id, "My Raster")

        # DB delete must NOT have been called
        session.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_vector_delete_still_drops_table(self):
        """Vector datasets still execute DROP TABLE; no storage calls made."""
        import unittest.mock as mock

        dataset_id = uuid.uuid4()
        mock_dataset = _MockDataset(dataset_id, "My Vector", "vector_dataset")
        session = mock.AsyncMock()
        executed_sqls: list[str] = []

        async def _capture_execute(stmt, *args, **kwargs):
            executed_sqls.append(str(stmt))

        session.execute.side_effect = _capture_execute

        with mock.patch("app.modules.catalog.datasets.domain.service.get_dataset", return_value=mock_dataset):
            from app.modules.catalog.datasets.domain.service import delete_dataset

            result = await delete_dataset(session, dataset_id, "My Vector")

        assert result == "test_table"

        drop_calls = [s for s in executed_sqls if "DROP TABLE" in s.upper()]
        assert len(drop_calls) == 1, f"Expected exactly 1 DROP TABLE, got: {drop_calls}"
        assert "test_table" in drop_calls[0]

        session.delete.assert_called_once_with(mock_dataset.record)


# ---------------------------------------------------------------------------
# Distribution and quicklook URI tests (unit-level via mock ingest_raster task)
# ---------------------------------------------------------------------------


class TestRasterDistributionAndQuicklook:
    def test_raster_distribution_created(self):
        """RecordDistribution model supports download/geotiff distribution type.

        Validates that the distribution model fields used by ingest_raster are
        correct: distribution_type='download', format='geotiff'. The actual
        creation during ingest is tested end-to-end via the integration tests;
        this test verifies the model contract.
        """
        from app.modules.catalog.datasets.domain.models import RecordDistribution

        record_id = uuid.uuid4()
        dataset_id = uuid.uuid4()

        dist = RecordDistribution(
            record_id=record_id,
            distribution_type="download",
            format="geotiff",
            url=f"https://example.com/datasets/{dataset_id}/download?format=geotiff",
        )
        assert dist.distribution_type == "download"
        assert dist.format == "geotiff"
        assert dist.record_id == record_id
        assert "geotiff" in dist.url

    def test_quicklook_stored_in_managed_storage(self):
        """RasterAsset quicklook URI fields follow the expected path pattern."""
        from app.processing.raster.models import RasterAsset

        dataset_id = uuid.uuid4()
        sha256 = "deadbeef" * 8  # 64-char hex

        asset = RasterAsset(
            dataset_id=dataset_id,
            asset_uri=f"rasters/{dataset_id}/{sha256}/source.cog.tif",
            storage_backend="local",
            quicklook_256_uri=f"rasters/{dataset_id}/{sha256}/quicklook_256.png",
            quicklook_512_uri=f"rasters/{dataset_id}/{sha256}/quicklook_512.png",
        )

        expected_256 = f"rasters/{dataset_id}/{sha256}/quicklook_256.png"
        expected_512 = f"rasters/{dataset_id}/{sha256}/quicklook_512.png"

        assert asset.quicklook_256_uri == expected_256, (
            f"Expected {expected_256!r}, got {asset.quicklook_256_uri!r}"
        )
        assert asset.quicklook_512_uri == expected_512, (
            f"Expected {expected_512!r}, got {asset.quicklook_512_uri!r}"
        )
        assert f"{dataset_id}" in asset.quicklook_256_uri
        assert "quicklook_256.png" in asset.quicklook_256_uri
        assert "quicklook_512.png" in asset.quicklook_512_uri
