"""Coverage for the raster-side "unable to open source" friendly-message fix.

Deferred from #1640 (which fixed the VECTOR side): for a corrupt/unopenable
uploaded raster, ``rasterio.open`` (via ``extract_raster_metadata``) raises
``RasterioIOError`` with GDAL's one-liner ``'<path>' not recognized as being
in a supported file format.`` — no driver enumeration (far less noisy than
the vector case), but it still echoes the internal ``/app/staging/<uuid>_...``
path instead of the original upload filename, and that raw message used to
land verbatim in ``IngestJob.error_message``.

Mirrors ``test_ingest_ogr_pure.py`` (pure pattern/message-builder unit tests)
and ``test_ingest_open_failure_message.py`` (real-binaries end-to-end
coverage) for the vector fix. The raster class has only ONE known stderr
shape (empirically confirmed: plain unrecognized bytes, GDAL never gets far
enough to enumerate drivers for a genuinely-unrecognized raster the way it
does for a claimed-but-corrupt vector source), so there is only one pattern
here rather than three.
"""

import os

import pytest
import structlog

from app.processing.ingest.tasks_raster_common import (
    _friendly_raster_open_failure_message,
    _is_unopenable_raster_stderr,
    extract_source_raster_metadata,
)


class TestIsUnopenableRasterStderr:
    def test_matches_not_recognized_message(self):
        """Empirically reproduced (GDAL/rasterio on this host): plain
        unrecognized bytes given a .tif name produce exactly this
        RasterioIOError text, quoting the path GDAL was asked to open."""
        stderr = "'/app/staging/9f2c1a3e-uuid_survey.tif' not recognized as being in a supported file format."
        assert _is_unopenable_raster_stderr(stderr) is True

    def test_matches_message_without_quoted_path(self):
        """The pattern anchors on the trailing phrase only, not the quoting —
        some rasterio/GDAL builds omit the leading quoted path entirely."""
        stderr = "not recognized as being in a supported file format."
        assert _is_unopenable_raster_stderr(stderr) is True

    def test_does_not_match_unrelated_rasterio_failure(self):
        """Narrow anchoring: a real, different rasterio/GDAL failure (a TIFF
        whose magic header is intact but whose IFD is corrupt) must NOT be
        caught by this pattern — that message keeps its real stderr."""
        stderr = "survey.tif: TIFFReadDirectory:Failed to read directory at offset 1907891221"
        assert _is_unopenable_raster_stderr(stderr) is False

    def test_does_not_match_permission_denied(self):
        stderr = "Permission denied"
        assert _is_unopenable_raster_stderr(stderr) is False

    def test_empty_string_does_not_match(self):
        assert _is_unopenable_raster_stderr("") is False


class TestFriendlyRasterOpenFailureMessage:
    """The user-facing replacement text — built only from the original
    upload filename, never from the staging path or the raw rasterio
    message."""

    def test_tif_extension_names_geotiff(self):
        msg = _friendly_raster_open_failure_message("survey.tif")
        assert msg == (
            "Could not open 'survey.tif' as a raster dataset — the file may "
            "be corrupt, incomplete, or not a valid GeoTIFF (.tif) file."
        )

    def test_tiff_extension_names_geotiff(self):
        msg = _friendly_raster_open_failure_message("survey.tiff")
        assert "GeoTIFF (.tiff)" in msg
        assert "survey.tiff" in msg

    def test_unknown_extension_falls_back_to_generic_phrasing(self):
        msg = _friendly_raster_open_failure_message("data.mysteryformat")
        assert "data.mysteryformat" in msg
        assert "not a valid raster file" in msg

    def test_no_filename_uses_fully_generic_message(self):
        msg = _friendly_raster_open_failure_message(None)
        assert msg == (
            "Could not open the uploaded file as a raster dataset — it may "
            "be corrupt, incomplete, or not a valid raster file."
        )

    def test_staging_path_never_appears_in_message(self):
        """The staging path GDAL echoes in its own rasterio message must
        never reach this message — only the original upload filename does."""
        msg = _friendly_raster_open_failure_message("survey.tif")
        assert "/app/staging" not in msg
        assert "staging" not in msg

    def test_directory_component_stripped_even_if_passed(self):
        """Defensive: even if a caller passed a path instead of a bare
        filename, only the leaf name is shown — never the directories."""
        msg = _friendly_raster_open_failure_message("/app/staging/9f2c_survey.tif")
        assert "survey.tif" in msg
        assert "/app/staging" not in msg


class TestExtractSourceRasterMetadataFriendlyOpenFailure:
    """Real-binaries coverage against the actual rasterio/GDAL install.

    Plain garbage bytes with a ``.tif`` name reproduce GDAL's "no driver
    recognizes this at all" shape (confirmed live on this host: a valid TIFF
    magic prefix instead makes the GTiff driver claim the source and fail
    with a DIFFERENT, more specific error — "TIFFReadDirectory:Failed to
    read directory..." — which is exactly the unrelated-failure case
    ``test_does_not_match_unrelated_rasterio_failure`` above pins). The
    upload-time content-sniffer (``validate_file_content``) would reject
    magic-less bytes before they ever reach this function in production —
    same as the vector fix's "no driver at all" fixture — but that gate is a
    separate, already-tested layer; this test exercises
    ``extract_source_raster_metadata`` directly, the one place that
    translates whatever rasterio raises.
    """

    def _write_unrecognized_raster(self, tmp_path) -> str:
        path = tmp_path / "9f2c1a3e-uuid_survey.tif"
        path.write_bytes(os.urandom(500))
        return str(path)

    def test_unrecognized_source_raises_friendly_message(self, tmp_path):
        source = self._write_unrecognized_raster(tmp_path)
        with pytest.raises(ValueError) as exc_info:
            extract_source_raster_metadata(source, original_filename="survey.tif")
        message = str(exc_info.value)
        assert message == (
            "Could not open 'survey.tif' as a raster dataset — the file may "
            "be corrupt, incomplete, or not a valid GeoTIFF (.tif) file."
        )
        assert str(tmp_path) not in message
        assert source not in message

    def test_full_message_still_reaches_structured_logs(self, tmp_path):
        """The diagnostic is not lost — it moves to the log, not nowhere."""
        source = self._write_unrecognized_raster(tmp_path)
        with structlog.testing.capture_logs() as captured:
            with pytest.raises(ValueError):
                extract_source_raster_metadata(source, original_filename="survey.tif")

        error_events = [e for e in captured if e.get("log_level") == "error"]
        assert error_events, [e for e in captured]
        logged = error_events[0]
        assert "not recognized as being in a supported file format" in logged["error"]
        # The staging path DOES appear in the logged raw message (that's the
        # point — full diagnostics for us) even though it never reaches the
        # user-facing message asserted above.
        assert source in logged["error"]
        assert logged["original_filename"] == "survey.tif"

    def test_no_original_filename_uses_generic_message(self, tmp_path):
        source = self._write_unrecognized_raster(tmp_path)
        with pytest.raises(ValueError) as exc_info:
            extract_source_raster_metadata(source, original_filename=None)
        message = str(exc_info.value)
        assert message == (
            "Could not open the uploaded file as a raster dataset — it may "
            "be corrupt, incomplete, or not a valid raster file."
        )
        assert source not in message

    def test_unrelated_rasterio_failure_keeps_real_message(self, tmp_path):
        """A TIFF with a valid magic header but a corrupt IFD is a
        DIFFERENT rasterio failure shape from the "not recognized" class —
        it must propagate the real rasterio message unchanged, not the
        friendly one, so a genuinely different problem doesn't get
        misdiagnosed as "wrong format"."""
        path = tmp_path / "9f2c1a3e-uuid_survey.tif"
        # Valid little-endian TIFF magic ("II*\x00") followed by garbage —
        # the GTiff driver claims the source by magic, then fails reading
        # the IFD, which is a distinct rasterio error from the
        # "not recognized" class this fix targets.
        path.write_bytes(b"II*\x00" + os.urandom(500))
        source = str(path)

        with pytest.raises(Exception) as exc_info:
            extract_source_raster_metadata(source, original_filename="survey.tif")
        message = str(exc_info.value)
        assert "Could not open" not in message
        assert "raster dataset" not in message
