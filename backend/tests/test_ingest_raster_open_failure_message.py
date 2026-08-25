"""Coverage for the raster-side "unable to open source" friendly-message fix.

Deferred from #1640 (which fixed the VECTOR side): for a corrupt/unopenable
uploaded raster, ``rasterio.open`` (via ``extract_raster_metadata``) raises
``RasterioIOError``, and its message — whatever shape it takes — used to land
verbatim in ``IngestJob.error_message``, echoing the internal
``/app/staging/<uuid>_...`` path instead of the original upload filename.

Mirrors ``test_ingest_ogr_pure.py`` (pure message-builder unit tests) and
``test_ingest_open_failure_message.py`` (real-binaries end-to-end coverage)
for the vector fix. Unlike the vector side, the raster boundary is NOT a
pattern match on specific stderr text: ``extract_raster_metadata`` opens the
source with exactly one ``rasterio.open`` call and reads everything else off
the resulting dataset, so ANY ``RasterioIOError`` it raises is by definition
an open-time "could not read this file" failure (codex review on #1661
round 1: an earlier version of this fix pattern-matched only the "not
recognized as being in a supported file format" text and missed a real,
production-reachable shape — a .tif with a valid TIFF magic header but a
corrupt/truncated IFD, which passes upload-time content-sniffing the same as
any other .tif and ALSO quotes the staging path in its rasterio message).
"""

import os

import pytest
import structlog

from app.processing.ingest.tasks_raster_common import (
    _friendly_raster_open_failure_message,
    extract_source_raster_metadata,
)


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

    Two DIFFERENT corrupt-file shapes both reach ``rasterio.open`` and both
    raise ``RasterioIOError`` — confirmed live on this host (rasterio 1.5.1):
    plain garbage bytes with a ``.tif`` name ("no driver recognizes this at
    all") and a valid TIFF magic header followed by garbage ("the GTiff
    driver claims the source by magic, then fails reading the IFD" —
    ``TIFFReadDirectory:Failed to read directory...``). Both get the friendly
    message, because both are open-time failures at this call site; a
    narrower fix that pattern-matched only the first shape's exact text
    missed the second, which is equally production-reachable (a corrupt-IFD
    .tif passes upload-time content-sniffing the same as any other .tif) and
    equally leaks the staging path.
    """

    def _write_unrecognized_raster(self, tmp_path) -> str:
        """Plain garbage bytes with a .tif name — no driver recognizes this
        at all."""
        path = tmp_path / "9f2c1a3e-uuid_survey.tif"
        path.write_bytes(os.urandom(500))
        return str(path)

    def _write_corrupt_ifd_raster(self, tmp_path) -> str:
        """Valid little-endian TIFF magic ("II*\\x00") followed by garbage —
        the GTiff driver claims the source by magic, then fails reading the
        IFD. A DIFFERENT rasterio failure shape from the "no driver" case
        above, and the one the round-1 fix's narrower pattern match missed."""
        path = tmp_path / "9f2c1a3e-uuid_survey.tif"
        path.write_bytes(b"II*\x00" + os.urandom(500))
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

    def test_corrupt_ifd_source_raises_friendly_message(self, tmp_path):
        """codex review, #1661 round 1: a valid TIFF magic header with a
        corrupt IFD is a distinct RasterioIOError shape from the "no driver"
        case, but it is STILL an open-time failure at this call site — and
        its rasterio message ALSO quotes the staging path — so it gets the
        same friendly translation, not the raw message."""
        source = self._write_corrupt_ifd_raster(tmp_path)
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

    def test_corrupt_ifd_message_also_reaches_structured_logs(self, tmp_path):
        source = self._write_corrupt_ifd_raster(tmp_path)
        with structlog.testing.capture_logs() as captured:
            with pytest.raises(ValueError):
                extract_source_raster_metadata(source, original_filename="survey.tif")

        error_events = [e for e in captured if e.get("log_level") == "error"]
        assert error_events, [e for e in captured]
        logged = error_events[0]
        assert "TIFFReadDirectory" in logged["error"]
        # This shape's rasterio message quotes only the basename, not the
        # full staging path (unlike the "not recognized" shape above) — the
        # point stands either way: the full diagnostic reaches the log.
        assert os.path.basename(source) in logged["error"]
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

    def test_post_open_failure_keeps_real_message(self, tmp_path, monkeypatch):
        """The boundary is "the open call itself", not "anything
        ``extract_raster_metadata`` can raise". A failure from something
        OTHER than ``rasterio.open`` — e.g. a non-``RasterioIOError`` raised
        while parsing metadata off an already-opened dataset — must keep its
        real message, not get relabeled as an open failure. Simulated via
        monkeypatch (a real post-open, non-open-time rasterio failure isn't
        cheaply reproducible with fixture bytes) so this pins the boundary
        decision itself rather than any one rasterio internal."""
        source = self._write_unrecognized_raster(tmp_path)

        def _raise_unrelated(_file_path):
            raise ValueError("malformed TIFFTAG_DATETIME tag: not a date")

        monkeypatch.setattr(
            "app.processing.ingest.tasks_raster_common.extract_raster_metadata",
            _raise_unrelated,
        )

        with pytest.raises(ValueError) as exc_info:
            extract_source_raster_metadata(source, original_filename="survey.tif")
        message = str(exc_info.value)
        assert message == "malformed TIFFTAG_DATETIME tag: not a date"
        assert "Could not open" not in message
        assert "raster dataset" not in message
