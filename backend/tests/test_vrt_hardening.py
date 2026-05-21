"""Unit tests for IA-P1-03: VRT magic-byte sniff + path-traversal guard +
GDAL VSI surface clamp.

Pins the 3-layer defense added in Phase 1068:
- validate_file_content routes .vrt through validate_vrt_body
- validate_vrt_body rejects non-VRT XML, '..' segments, and unsanctioned
  absolute paths in <SourceFilename>
- _build_vrt subprocess env applies CPL_VSIL_CURL_ALLOWED_EXTENSIONS +
  VRT_VIRTUAL_OVERVIEWS=NO + GDAL_HTTP_FOLLOWLOCATION=NO

Requirement: IA-P1-03
Phase: 1068
"""

from unittest.mock import patch

import pytest

from app.processing.ingest.validation import (
    validate_file_content,
    validate_vrt_body,
)


# ---------------------------------------------------------------------------
# validate_vrt_body — XML structure
# ---------------------------------------------------------------------------


class TestVrtMagicByteSniff:
    def test_valid_vrtdataset_root_accepted(self, tmp_path):
        f = tmp_path / "valid.vrt"
        f.write_bytes(
            b'<?xml version="1.0"?>\n'
            b'<VRTDataset rasterXSize="100" rasterYSize="100">\n'
            b'  <SRS>EPSG:4326</SRS>\n'
            b'</VRTDataset>\n'
        )
        validate_vrt_body(str(f))  # no raise

    def test_valid_vrtdataset_without_xml_decl_accepted(self, tmp_path):
        f = tmp_path / "valid_no_decl.vrt"
        f.write_bytes(b"<VRTDataset rasterXSize=\"100\" rasterYSize=\"100\"></VRTDataset>")
        validate_vrt_body(str(f))  # no raise

    def test_non_vrt_xml_rejected(self, tmp_path):
        f = tmp_path / "fake.vrt"
        f.write_bytes(b"<?xml version=\"1.0\"?>\n<NotAVRT/>")
        with pytest.raises(ValueError) as exc:
            validate_vrt_body(str(f))
        assert "VRTDataset" in str(exc.value)

    def test_empty_vrt_rejected(self, tmp_path):
        f = tmp_path / "empty.vrt"
        f.write_bytes(b"")
        with pytest.raises(ValueError) as exc:
            validate_vrt_body(str(f))
        assert "empty" in str(exc.value).lower()

    def test_plaintext_with_vrt_extension_rejected(self, tmp_path):
        f = tmp_path / "fake.vrt"
        f.write_bytes(b"not even xml content here")
        with pytest.raises(ValueError) as exc:
            validate_vrt_body(str(f))
        assert "VRTDataset" in str(exc.value)


# ---------------------------------------------------------------------------
# validate_vrt_body — path-traversal guard
# ---------------------------------------------------------------------------


class TestVrtPathTraversalGuard:
    def test_dotdot_segment_rejected(self, tmp_path):
        f = tmp_path / "traversal.vrt"
        f.write_bytes(
            b'<VRTDataset rasterXSize="100" rasterYSize="100">'
            b"<VRTRasterBand>"
            b"<SimpleSource>"
            b"<SourceFilename>../../etc/hostname</SourceFilename>"
            b"</SimpleSource>"
            b"</VRTRasterBand>"
            b"</VRTDataset>"
        )
        with pytest.raises(ValueError) as exc:
            validate_vrt_body(str(f))
        assert "traversal" in str(exc.value).lower() or ".." in str(exc.value)

    def test_relative_path_accepted(self, tmp_path):
        f = tmp_path / "ok.vrt"
        f.write_bytes(
            b'<VRTDataset rasterXSize="100" rasterYSize="100">'
            b"<VRTRasterBand>"
            b"<SimpleSource>"
            b"<SourceFilename>tile_001.tif</SourceFilename>"
            b"</SimpleSource>"
            b"</VRTRasterBand>"
            b"</VRTDataset>"
        )
        validate_vrt_body(str(f))  # no raise

    def test_nested_relative_path_accepted(self, tmp_path):
        f = tmp_path / "ok2.vrt"
        f.write_bytes(
            b'<VRTDataset rasterXSize="100" rasterYSize="100">'
            b"<VRTRasterBand>"
            b"<SimpleSource>"
            b"<SourceFilename>subdir/tile.tif</SourceFilename>"
            b"</SimpleSource>"
            b"</VRTRasterBand>"
            b"</VRTDataset>"
        )
        validate_vrt_body(str(f))  # no raise

    def test_absolute_filesystem_path_rejected(self, tmp_path):
        f = tmp_path / "abs.vrt"
        f.write_bytes(
            b'<VRTDataset rasterXSize="100" rasterYSize="100">'
            b"<VRTRasterBand>"
            b"<SimpleSource>"
            b"<SourceFilename>/etc/hostname</SourceFilename>"
            b"</SimpleSource>"
            b"</VRTRasterBand>"
            b"</VRTDataset>"
        )
        with pytest.raises(ValueError) as exc:
            validate_vrt_body(str(f))
        assert "absolute" in str(exc.value).lower()

    def test_vsis3_prefix_accepted(self, tmp_path):
        f = tmp_path / "vsis3.vrt"
        f.write_bytes(
            b'<VRTDataset rasterXSize="100" rasterYSize="100">'
            b"<VRTRasterBand>"
            b"<SimpleSource>"
            b"<SourceFilename>/vsis3/bucket/key.tif</SourceFilename>"
            b"</SimpleSource>"
            b"</VRTRasterBand>"
            b"</VRTDataset>"
        )
        validate_vrt_body(str(f))  # no raise

    def test_vsicurl_prefix_accepted(self, tmp_path):
        f = tmp_path / "vsicurl.vrt"
        f.write_bytes(
            b'<VRTDataset rasterXSize="100" rasterYSize="100">'
            b"<VRTRasterBand>"
            b"<SimpleSource>"
            b"<SourceFilename>/vsicurl/https://example.com/tile.tif</SourceFilename>"
            b"</SimpleSource>"
            b"</VRTRasterBand>"
            b"</VRTDataset>"
        )
        validate_vrt_body(str(f))  # no raise

    def test_multiple_sources_one_bad_rejected(self, tmp_path):
        f = tmp_path / "mixed.vrt"
        f.write_bytes(
            b'<VRTDataset rasterXSize="100" rasterYSize="100">'
            b"<VRTRasterBand>"
            b"<SimpleSource><SourceFilename>good.tif</SourceFilename></SimpleSource>"
            b"<SimpleSource><SourceFilename>../bad.tif</SourceFilename></SimpleSource>"
            b"</VRTRasterBand>"
            b"</VRTDataset>"
        )
        with pytest.raises(ValueError) as exc:
            validate_vrt_body(str(f))
        assert ".." in str(exc.value)


# ---------------------------------------------------------------------------
# validate_file_content — dispatch
# ---------------------------------------------------------------------------


class TestFileContentDispatchesVrt:
    def test_validate_file_content_routes_vrt_to_body_validator(self, tmp_path):
        """A .vrt with traversal markers must fail validate_file_content."""
        f = tmp_path / "traversal.vrt"
        f.write_bytes(
            b"<VRTDataset>"
            b"<SimpleSource>"
            b"<SourceFilename>../../etc/passwd</SourceFilename>"
            b"</SimpleSource>"
            b"</VRTDataset>"
        )
        with pytest.raises(ValueError):
            validate_file_content(str(f), "traversal.vrt")


# ---------------------------------------------------------------------------
# _build_vrt subprocess env
# ---------------------------------------------------------------------------


class TestGdalBuildVrtSafeEnv:
    def test_gdalbuildvrt_subprocess_uses_safe_env(self, tmp_path):
        """`_build_vrt` invokes gdalbuildvrt with the safety-clamp env vars."""
        captured_env: dict | None = None

        def _fake_run(cmd, capture_output, text, env):
            nonlocal captured_env
            captured_env = env

            class _Result:
                returncode = 0
                stderr = ""

            return _Result()

        from app.processing.raster import vrt as vrt_module

        with patch.object(vrt_module.subprocess, "run", side_effect=_fake_run):
            vrt_module._build_vrt(
                source_paths=[str(tmp_path / "a.tif")],
                output_path=str(tmp_path / "out.vrt"),
                resolution_strategy="finest",
            )

        assert captured_env is not None
        assert captured_env.get("CPL_VSIL_CURL_ALLOWED_EXTENSIONS") == "tif,tiff,vrt"
        assert captured_env.get("VRT_VIRTUAL_OVERVIEWS") == "NO"
        assert captured_env.get("GDAL_HTTP_FOLLOWLOCATION") == "NO"
