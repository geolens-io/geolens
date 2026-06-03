"""Unit tests for upload file validation: magic bytes, zip safety, size limits."""

import io
import zipfile
from pathlib import Path

import pytest

from app.processing.ingest.validation import (
    validate_file_content,
    validate_file_size,
    validate_zip_safety,
)


# ---------------------------------------------------------------------------
# validate_file_content tests
# ---------------------------------------------------------------------------


class TestValidateFileContent:
    """Tests for magic byte / content-type validation."""

    def test_binary_elf_in_geojson_rejected(self, tmp_path: Path):
        """A .geojson containing binary ELF data is rejected."""
        f = tmp_path / "test.geojson"
        f.write_bytes(b"\x7fELF" + b"\x00" * 100)
        with pytest.raises(ValueError, match="content"):
            validate_file_content(str(f), "test.geojson")

    def test_valid_geojson_passes(self, tmp_path: Path):
        """A valid .geojson file passes content validation."""
        f = tmp_path / "test.geojson"
        f.write_text('{"type": "FeatureCollection", "features": []}')
        validate_file_content(str(f), "test.geojson")

    def test_zip_magic_in_geojson_rejected(self, tmp_path: Path):
        """A .geojson containing ZIP magic bytes is rejected."""
        f = tmp_path / "test.geojson"
        # PK\x03\x04 is ZIP local file header
        f.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
        with pytest.raises(ValueError):
            validate_file_content(str(f), "test.geojson")

    def test_valid_zip_passes(self, tmp_path: Path):
        """A .zip file with ZIP magic bytes passes."""
        f = tmp_path / "test.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("data.txt", "hello")
        f.write_bytes(buf.getvalue())
        validate_file_content(str(f), "test.zip")

    def test_valid_gpkg_sqlite_magic_passes(self, tmp_path: Path):
        """A .gpkg with SQLite magic bytes passes validation."""
        f = tmp_path / "test.gpkg"
        # SQLite format 3\000 magic header (100 bytes total header)
        header = b"SQLite format 3\x00" + b"\x00" * 84
        f.write_bytes(header)
        validate_file_content(str(f), "test.gpkg")

    def test_valid_csv_text_passes(self, tmp_path: Path):
        """A .csv with plain text content passes."""
        f = tmp_path / "test.csv"
        f.write_text("name,lat,lon\nNew York,40.7,-74.0\n")
        validate_file_content(str(f), "test.csv")

    def test_empty_file_rejected(self, tmp_path: Path):
        """An empty file raises ValueError about being empty."""
        f = tmp_path / "test.geojson"
        f.write_bytes(b"")
        with pytest.raises(ValueError, match="empty"):
            validate_file_content(str(f), "test.geojson")

    def test_unknown_extension_skips_validation(self, tmp_path: Path):
        """Extensions not in EXTENSION_CONTENT_MAP skip magic-byte validation."""
        f = tmp_path / "data.parquet"
        f.write_bytes(b"PAR1" + b"\x00" * 100)
        # Should NOT raise -- unknown extensions pass through
        validate_file_content(str(f), "data.parquet")


# ---------------------------------------------------------------------------
# validate_zip_safety tests
# ---------------------------------------------------------------------------


class TestValidateZipSafety:
    """Tests for ZIP archive safety checks."""

    def test_high_compression_ratio_rejected(self, tmp_path: Path):
        """ZIP with compression ratio >100:1 is rejected."""
        f = tmp_path / "bomb.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Create highly compressible data (all zeros)
            # 1MB of zeros compresses to ~1KB, ratio ~1000:1
            zf.writestr("big.txt", b"\x00" * (1024 * 1024))
        f.write_bytes(buf.getvalue())
        with pytest.raises(ValueError, match="compression"):
            validate_zip_safety(str(f))

    def test_nested_zip_rejected(self, tmp_path: Path):
        """ZIP containing a nested .zip file is rejected."""
        f = tmp_path / "nested.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("inner.zip", b"fake zip content")
        f.write_bytes(buf.getvalue())
        with pytest.raises(ValueError, match="nested"):
            validate_zip_safety(str(f))

    def test_decompressed_size_over_2gb_rejected(self, tmp_path: Path):
        """ZIP with total decompressed size >2GB is rejected."""
        f = tmp_path / "huge.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
            # Create entries that claim large file_size via ZipInfo
            # We use stored (no compression) so ratio is 1:1 (passes ratio check)
            # But we craft the metadata to claim huge size
            for i in range(3):
                info = zipfile.ZipInfo(f"part_{i}.dat")
                info.compress_type = zipfile.ZIP_STORED
                # Write small actual data but we need the metadata to show >2GB total
                # We'll use a different approach: write actual entries summing >2GB
                # Since we can't write 2GB of real data in a test, we'll mock at the level
                # of the function. Instead, let's craft the ZIP manually.
                pass

        # Better approach: create a ZIP with crafted ZipInfo headers
        # that report large file_size values
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
            for i in range(3):
                data = b"x" * 100
                info = zipfile.ZipInfo(f"part_{i}.dat")
                info.compress_type = zipfile.ZIP_STORED
                zf.writestr(info, data)

        # Patch the ZIP to report huge file_sizes
        # Read the zip, modify infolist file_size, rewrite
        raw = buf.getvalue()
        # Instead, let's test this via monkeypatch on zipfile
        # Actually, let's use a simpler approach: monkeypatch the constant
        import app.processing.ingest.validation as val_mod

        original = val_mod.MAX_DECOMPRESSED_BYTES
        try:
            # Temporarily set max to 200 bytes so our 300-byte zip triggers it
            val_mod.MAX_DECOMPRESSED_BYTES = 200
            f.write_bytes(raw)
            with pytest.raises(ValueError, match="size"):
                validate_zip_safety(str(f))
        finally:
            val_mod.MAX_DECOMPRESSED_BYTES = original

    def test_valid_shapefile_zip_passes(self, tmp_path: Path):
        """Valid shapefile ZIP (component files, low ratio) passes."""
        f = tmp_path / "shapefile.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Simulate shapefile components with realistic (non-compressible) data
            import os

            for ext in [".shp", ".shx", ".dbf", ".prj"]:
                # Random-ish data that won't compress extremely
                data = os.urandom(1024)
                zf.writestr(f"layer{ext}", data)
        f.write_bytes(buf.getvalue())
        validate_zip_safety(str(f))

    def test_not_a_valid_zip_rejected(self, tmp_path: Path):
        """File with .zip extension but not a valid ZIP is rejected."""
        f = tmp_path / "fake.zip"
        f.write_bytes(b"this is not a zip file at all")
        with pytest.raises(ValueError, match="not a valid ZIP"):
            validate_zip_safety(str(f))


# ---------------------------------------------------------------------------
# validate_file_size tests
# ---------------------------------------------------------------------------


class TestValidateFileSize:
    """Tests for file size enforcement."""

    def test_oversized_file_rejected(self, tmp_path: Path):
        """File exceeding max size is rejected."""
        f = tmp_path / "big.geojson"
        # Create a 600-byte file, test against 500-byte limit
        f.write_bytes(b"x" * 600)
        with pytest.raises(ValueError, match="size"):
            validate_file_size(str(f), 500)

    def test_undersized_file_passes(self, tmp_path: Path):
        """File within size limit passes."""
        f = tmp_path / "small.geojson"
        f.write_bytes(b"x" * 400)
        validate_file_size(str(f), 500)
