"""End-to-end coverage for the "unable to open datasource" friendly-message fix.

A corrupt vector upload (the demo incident: an invalid ``march.gpkg``) used to
land the RAW ogr2ogr/ogrinfo stderr — GDAL's full driver enumeration, or
SQLite's own corrupt-database diagnostics, either one including the staging
file path — verbatim in ``IngestJob.error_message``, where a demo visitor
read it in the job UI.

These tests run the real ``ogrinfo``/``ogr2ogr`` binaries against corrupt
fixture files built in ``tmp_path`` and assert:

  1. The raised ``IngestionError`` carries the short, human-readable message
     — built from the ORIGINAL upload filename, never the staging path.
  2. The full raw stderr (driver list / SQLite diagnostics) still reaches
     structured logs at error level, so the diagnostic is not lost.

Two corrupt-file shapes are covered, matching the two stderr patterns GDAL
actually produces for this failure class:

  - No driver recognizes the source at all (plain garbage bytes) → GDAL's
    "Unable to open datasource ... with the following drivers." enumeration.
  - The SQLite/GPKG magic header is intact but the content underneath is
    corrupt (a truncated/garbage-filled GPKG) → SQLite's own
    "file is not a database" diagnostics. This is the realistic upload case:
    the app's content-sniffing at upload time already rejects files with no
    magic header at all, so a corrupt upload that reaches ogr2ogr/ogrinfo in
    production has a valid header and corrupt content underneath it.

Requires the real ogr2ogr/ogrinfo binaries — skipped when unavailable
(dev hosts without GDAL; CI and the backend Docker image install it).
"""

import os
import shutil

import pytest
import structlog

from app.processing.ingest.ogr import IngestionError, run_ogr2ogr, run_ogrinfo

pytestmark = pytest.mark.skipif(
    shutil.which("ogr2ogr") is None or shutil.which("ogrinfo") is None,
    reason="ogr2ogr/ogrinfo binaries not available on host (runs in backend Docker image / CI)",
)


def _write_no_driver_gpkg(tmp_path) -> str:
    """Plain garbage bytes with a .gpkg name — no driver recognizes this at all."""
    path = tmp_path / "9f2c1a3e-uuid_march.gpkg"
    path.write_bytes(b"this is not a real geopackage file, just plain bytes\n")
    return str(path)


def _write_sqlite_magic_corrupt_gpkg(tmp_path) -> str:
    """A GPKG with a real SQLite header but corrupt content underneath.

    Mirrors what content-sniffing at upload time actually lets through: the
    magic header alone is not enough to guarantee GDAL can read the rest.
    """
    path = tmp_path / "1a2b3c4d-uuid_march.gpkg"
    path.write_bytes(b"SQLite format 3\x00" + os.urandom(200))
    return str(path)


class TestRunOgrinfoFriendlyOpenFailure:
    """ogrinfo runs before ogr2ogr in the ingest_file task (CRS detection), so
    for the realistic corrupt-upload case — content-sniffing at upload time
    already rejects a file with no recognizable magic header at all — this is
    the function that actually raises. Empirically (GDAL 3.13 on this host,
    matching the orchestrator's live dev-stack reproduction), ogrinfo's
    "no driver at all" failure is a short one-liner without a driver
    enumeration (a distinct, out-of-scope leak noted in the PR description),
    so only the sqlite-magic-header-but-corrupt-content shape is exercised
    against ogrinfo here; the driver-enumeration shape is exercised against
    ogr2ogr below, which is where the original march.gpkg incident's exact
    stderr came from.
    """

    async def test_sqlite_corrupt_content_case_raises_friendly_message(self, tmp_path):
        source = _write_sqlite_magic_corrupt_gpkg(tmp_path)
        with pytest.raises(IngestionError) as exc_info:
            await run_ogrinfo(source, original_filename="march.gpkg")
        message = str(exc_info.value)
        assert message == (
            "Could not open 'march.gpkg' as a spatial dataset — the file "
            "may be corrupt, incomplete, or not a valid GeoPackage (.gpkg) "
            "file."
        )
        assert str(tmp_path) not in message
        assert "sqlite3_prepare_v2" not in message

    async def test_full_stderr_still_reaches_structured_logs(self, tmp_path):
        """The diagnostic is not lost — it moves to the log, not nowhere."""
        source = _write_sqlite_magic_corrupt_gpkg(tmp_path)
        with structlog.testing.capture_logs() as captured:
            with pytest.raises(IngestionError):
                await run_ogrinfo(source, original_filename="march.gpkg")

        error_events = [e for e in captured if e.get("log_level") == "error"]
        assert error_events, [e for e in captured]
        logged = error_events[0]
        assert "file is not a database" in logged["stderr"]
        assert "sqlite3_prepare_v2" in logged["stderr"]
        # The staging path DOES appear in the logged raw stderr (that's the
        # point — full diagnostics for us) even though it never reaches the
        # user-facing message asserted above.
        assert source in logged["stderr"]
        assert logged["original_filename"] == "march.gpkg"

    async def test_unrelated_ogrinfo_failure_keeps_raw_message(self, tmp_path):
        """Narrow mapping: a non-"unable to open" ogrinfo failure (invalid
        layer name argv rejected before spawn is covered elsewhere; here, a
        nonexistent file with a plain .txt extension still fails, but through
        a different message shape) must not be swallowed by the same
        friendly text — the leading-dash guard raises before spawn, so use a
        real GDAL failure that ISN'T the open-failure class instead: a
        request for a named layer that does not exist in an otherwise valid,
        openable source. ogrinfo's error there names the missing layer, not
        "unable to open" or "file is not a database", so it must fall
        through unmodified.
        """
        # A minimal valid (empty) GeoJSON FeatureCollection: openable, but
        # asking for a layer name GDAL won't find inside it produces a
        # different failure shape than "can't open the source at all".
        source = tmp_path / "empty.geojson"
        source.write_text('{"type": "FeatureCollection", "features": []}')
        with pytest.raises(IngestionError) as exc_info:
            await run_ogrinfo(
                str(source),
                layer_name="nonexistent_layer",
                original_filename="x.geojson",
            )
        message = str(exc_info.value)
        assert "Could not open" not in message
        assert message.startswith("ogrinfo failed")


class TestRunOgr2ogrFriendlyOpenFailure:
    async def test_no_driver_case_raises_friendly_message(self, tmp_path):
        source = _write_no_driver_gpkg(tmp_path)
        with pytest.raises(IngestionError) as exc_info:
            await run_ogr2ogr(
                source,
                "some_table",
                "PG:dbname=unused_this_never_gets_reached",
                schema="data",
                original_filename="march.gpkg",
            )
        message = str(exc_info.value)
        assert message == (
            "Could not open 'march.gpkg' as a spatial dataset — the file "
            "may be corrupt, incomplete, or not a valid GeoPackage (.gpkg) "
            "file."
        )
        assert str(tmp_path) not in message
        assert "->" not in message

    async def test_sqlite_corrupt_content_case_raises_friendly_message(self, tmp_path):
        source = _write_sqlite_magic_corrupt_gpkg(tmp_path)
        with pytest.raises(IngestionError) as exc_info:
            await run_ogr2ogr(
                source,
                "some_table",
                "PG:dbname=unused_this_never_gets_reached",
                schema="data",
                original_filename="march.gpkg",
            )
        message = str(exc_info.value)
        assert message == (
            "Could not open 'march.gpkg' as a spatial dataset — the file "
            "may be corrupt, incomplete, or not a valid GeoPackage (.gpkg) "
            "file."
        )
        assert str(tmp_path) not in message

    async def test_full_stderr_still_reaches_structured_logs(self, tmp_path):
        source = _write_sqlite_magic_corrupt_gpkg(tmp_path)
        with structlog.testing.capture_logs() as captured:
            with pytest.raises(IngestionError):
                await run_ogr2ogr(
                    source,
                    "some_table",
                    "PG:dbname=unused_this_never_gets_reached",
                    schema="data",
                    original_filename="march.gpkg",
                )

        error_events = [e for e in captured if e.get("log_level") == "error"]
        assert error_events, [e for e in captured]
        logged = error_events[0]
        assert "file is not a database" in logged["stderr"]
        assert source in logged["stderr"]
        assert logged["original_filename"] == "march.gpkg"

    async def test_no_original_filename_falls_back_to_generic_message(self, tmp_path):
        """Callers that can't supply the original filename (none exist in
        production today, but the parameter is optional) still get a safe,
        staging-path-free message instead of an AttributeError or a leak."""
        source = _write_no_driver_gpkg(tmp_path)
        with pytest.raises(IngestionError) as exc_info:
            await run_ogr2ogr(
                source,
                "some_table",
                "PG:dbname=unused_this_never_gets_reached",
                schema="data",
            )
        message = str(exc_info.value)
        assert message == (
            "Could not open the uploaded file as a spatial dataset — it "
            "may be corrupt, incomplete, or not a valid spatial data file."
        )
        assert str(tmp_path) not in message
