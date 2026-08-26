"""Tier-1 vector import formats: FlatGeobuf, KML/KMZ, and zipped File Geodatabase.

The GDAL drivers were already compiled into the worker image; what was missing
was the plumbing. Three layers are covered here:

  * admission — the extensions are on the accepted-upload list, and each one's
    content check accepts a real file and refuses a mislabelled one;
  * naming — ``derive_source_format`` maps a path to the value stored in
    ``datasets.source_format``, including the two disambiguations that are not
    a plain suffix strip (``.kmz`` → ``kml``, a ``.zip`` holding a ``.gdb`` →
    ``fgdb``);
  * ingest — an end-to-end ogr2ogr load per format, so a driver that GDAL
    refuses to open cannot pass the first two layers unnoticed.

The ingest class needs a real ogr2ogr and the test PostGIS; it skips on hosts
without GDAL, exactly like ``test_ingest_column_preservation.py``. Everything
above it runs anywhere.
"""

import shutil
import uuid
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.processing.ingest.ogr import _resolve_source_path
from app.processing.ingest.source_format import (
    derive_source_format,
    zip_contains_filegdb,
)
from app.processing.ingest.validation import (
    EXTENSION_CONTENT_MAP,
    ZIP_CONTAINER_EXTENSIONS,
    validate_archive_safety,
    validate_file_content,
    validate_flatgeobuf_file,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ingest"

FGB = FIXTURES / "tier1_points.fgb"
KML = FIXTURES / "tier1_points.kml"
KMZ = FIXTURES / "tier1_points.kmz"
GDB_ZIP = FIXTURES / "tier1_points_gdb.zip"
SHAPEFILE_ZIP = FIXTURES / "dbf_collision.zip"


# ---------------------------------------------------------------------------
# Admission: accepted extensions
# ---------------------------------------------------------------------------


class TestAcceptedExtensions:
    """The four formats reach the upload handler at all."""

    @pytest.mark.parametrize("extension", [".fgb", ".kml", ".kmz", ".zip"])
    def test_extension_is_accepted_by_default(self, extension: str):
        allowed = {
            part.strip().lower()
            for part in settings.upload_allowed_extensions.split(",")
            if part.strip()
        }
        assert extension in allowed

    def test_kmz_is_treated_as_a_zip_container(self):
        """A KMZ is a zip, so it must go through the zip-bomb checks."""
        assert ".kmz" in ZIP_CONTAINER_EXTENSIONS

    def test_kmz_fixture_passes_archive_safety(self):
        validate_archive_safety(str(KMZ), "tier1_points.kmz")

    def test_fgb_is_not_a_zip_container(self):
        assert ".fgb" not in ZIP_CONTAINER_EXTENSIONS


# ---------------------------------------------------------------------------
# Admission: content-type mapping
# ---------------------------------------------------------------------------


class TestContentValidation:
    """Real driver output is accepted; a mislabelled file is not."""

    @pytest.mark.parametrize(
        "path,filename",
        [
            (FGB, "tier1_points.fgb"),
            (KML, "tier1_points.kml"),
            (KMZ, "tier1_points.kmz"),
            (GDB_ZIP, "tier1_points_gdb.zip"),
        ],
    )
    def test_real_fixture_passes(self, path: Path, filename: str):
        validate_file_content(str(path), filename)

    def test_kml_and_kmz_have_content_rules(self):
        """Absent from EXTENSION_CONTENT_MAP means "skip validation entirely"."""
        assert ".kml" in EXTENSION_CONTENT_MAP
        assert ".kmz" in EXTENSION_CONTENT_MAP

    def test_fgb_magic_is_version_agnostic(self):
        """Only the two "fgb" literals are pinned, not the version bytes."""
        assert FGB.read_bytes()[:8].startswith(b"fgb")
        validate_flatgeobuf_file(str(FGB))

    def test_fgb_with_wrong_magic_rejected(self, tmp_path: Path):
        f = tmp_path / "fake.fgb"
        f.write_bytes(b"\x7fELF" + b"\x00" * 100)
        with pytest.raises(ValueError, match="FlatGeobuf"):
            validate_file_content(str(f), "fake.fgb")

    def test_truncated_fgb_rejected(self, tmp_path: Path):
        f = tmp_path / "short.fgb"
        f.write_bytes(b"fgb\x03")
        with pytest.raises(ValueError, match="FlatGeobuf"):
            validate_file_content(str(f), "short.fgb")

    def test_binary_kml_rejected(self, tmp_path: Path):
        f = tmp_path / "fake.kml"
        f.write_bytes(b"\x00\x01\x02\x03" * 64)
        with pytest.raises(ValueError, match="content"):
            validate_file_content(str(f), "fake.kml")

    def test_plain_text_kml_rejected(self, tmp_path: Path):
        """KML must at least open a tag — the .csv text rule is too generous."""
        f = tmp_path / "notes.kml"
        f.write_text("just some notes, not markup at all\n")
        with pytest.raises(ValueError, match="content"):
            validate_file_content(str(f), "notes.kml")

    def test_kml_without_xml_prologue_passes(self, tmp_path: Path):
        """`<kml>` as the first bytes is legal and puremagic detects nothing."""
        f = tmp_path / "bare.kml"
        f.write_text('<kml xmlns="http://www.opengis.net/kml/2.2"></kml>')
        validate_file_content(str(f), "bare.kml")

    def test_kml_with_utf8_bom_passes(self, tmp_path: Path):
        f = tmp_path / "bom.kml"
        f.write_bytes(b"\xef\xbb\xbf" + b'<kml xmlns="x"></kml>')
        validate_file_content(str(f), "bom.kml")

    def test_kmz_that_is_not_a_zip_rejected(self, tmp_path: Path):
        f = tmp_path / "fake.kmz"
        f.write_text('<kml xmlns="http://www.opengis.net/kml/2.2"></kml>')
        with pytest.raises(ValueError, match="content"):
            validate_file_content(str(f), "fake.kmz")


# ---------------------------------------------------------------------------
# Naming: derive_source_format
# ---------------------------------------------------------------------------


class TestDeriveSourceFormat:
    """The value stored in ``datasets.source_format``."""

    def test_fgb_gets_its_own_format(self):
        assert derive_source_format("/staging/1_points.fgb") == "fgb"

    def test_kml_stays_kml(self):
        assert derive_source_format("/staging/1_points.kml") == "kml"

    def test_kmz_normalizes_to_kml(self):
        """One format, two containers — see the module docstring for why."""
        assert derive_source_format("/staging/1_points.kmz") == "kml"

    def test_uppercase_extension_normalizes(self):
        assert derive_source_format("/staging/1_POINTS.KMZ") == "kml"

    def test_gdb_zip_is_fgdb(self):
        assert derive_source_format(str(GDB_ZIP)) == "fgdb"

    def test_shapefile_zip_stays_shapefile(self):
        assert derive_source_format(str(SHAPEFILE_ZIP)) == "shapefile"

    def test_unreadable_zip_falls_back_to_shapefile(self, tmp_path: Path):
        """GDAL has already opened the file by then; this is a naming question."""
        f = tmp_path / "broken.zip"
        f.write_bytes(b"PK\x03\x04not-really-an-archive")
        assert derive_source_format(str(f)) == "shapefile"

    def test_missing_file_falls_back_to_shapefile(self, tmp_path: Path):
        assert derive_source_format(str(tmp_path / "absent.zip")) == "shapefile"

    def test_existing_formats_unchanged(self):
        assert derive_source_format("/staging/1_a.geojson") == "geojson"
        assert derive_source_format("/staging/1_a.gpkg") == "gpkg"
        assert derive_source_format("/staging/1_a.csv") == "csv"


class TestZipContainsFilegdb:
    def test_real_gdb_zip_detected(self):
        assert zip_contains_filegdb(str(GDB_ZIP)) is True

    def test_shapefile_zip_not_detected(self):
        assert zip_contains_filegdb(str(SHAPEFILE_ZIP)) is False

    def test_windows_separators_detected(self, tmp_path: Path):
        f = tmp_path / "win.zip"
        with zipfile.ZipFile(f, "w") as zf:
            zf.writestr("data\\parcels.gdb\\a00000001.gdbtable", b"x")
        assert zip_contains_filegdb(str(f)) is True

    def test_bare_directory_entry_detected(self, tmp_path: Path):
        """A writer that stores directory entries names the .gdb with no members."""
        f = tmp_path / "dironly.zip"
        with zipfile.ZipFile(f, "w") as zf:
            zf.writestr("parcels.gdb/", b"")
        assert zip_contains_filegdb(str(f)) is True

    def test_gdb_in_a_filename_is_not_a_directory(self, tmp_path: Path):
        f = tmp_path / "notgdb.zip"
        with zipfile.ZipFile(f, "w") as zf:
            zf.writestr("notes_about_gdb.txt", b"x")
        assert zip_contains_filegdb(str(f)) is False


class TestSourcePathResolution:
    """GDAL opens a KMZ natively; wrapping it in /vsizip/ breaks it."""

    def test_zip_is_wrapped(self):
        assert _resolve_source_path("/staging/a.zip") == "/vsizip//staging/a.zip"

    def test_kmz_is_not_wrapped(self):
        assert _resolve_source_path("/staging/a.kmz") == "/staging/a.kmz"

    def test_fgb_is_not_wrapped(self):
        assert _resolve_source_path("/staging/a.fgb") == "/staging/a.fgb"


class TestSourceFormatConstraint:
    """Every derivable value has to survive ``chk_datasets_source_format``."""

    def test_model_check_lists_every_tier1_value(self):
        from app.modules.catalog.datasets.domain.models import Dataset

        constraint = next(
            c
            for c in Dataset.__table__.constraints
            if getattr(c, "name", None) == "chk_datasets_source_format"
        )
        sql = str(constraint.sqltext)
        for value in ("fgb", "kml", "fgdb", "shapefile"):
            assert f"'{value}'" in sql

    async def test_live_constraint_carries_the_tier1_values(self, test_db_session):
        """The migration ran, not just the model. The test DB is migrated to
        head by the session fixture, so this reads what 0053 actually built."""
        rows = await test_db_session.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'chk_datasets_source_format'"
            )
        )
        definitions = rows.scalars().all()
        assert definitions, "chk_datasets_source_format is missing from the test DB"
        for definition in definitions:
            for value in ("fgb", "kml", "fgdb"):
                assert f"'{value}'" in definition

    def test_migration_matches_the_model(self):
        """The migration is the source of truth; drift here is a silent 500."""
        from app.modules.catalog.datasets.domain.models import Dataset

        migration = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "0053_source_format_fgb.py"
        ).read_text()
        constraint = next(
            c
            for c in Dataset.__table__.constraints
            if getattr(c, "name", None) == "chk_datasets_source_format"
        )
        model_values = set(_quoted_values(str(constraint.sqltext)))
        migration_values = set(_quoted_values(migration))
        assert model_values == migration_values


def _quoted_values(sql: str) -> list[str]:
    import re

    return re.findall(r"'([a-z_0-9]+)'", sql)


# ---------------------------------------------------------------------------
# Ingest: end-to-end ogr2ogr load per format
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    shutil.which("ogr2ogr") is None,
    reason="ogr2ogr binary not available on host (runs in backend Docker image / CI)",
)
@pytest.mark.requires_ogr2ogr
class TestTier1Ingest:
    """Each format loads into PostGIS with its three attribute columns intact.

    All four fixtures are the same three cities, so one expected column set and
    one expected row count cover the matrix.
    """

    @pytest.mark.parametrize(
        "fixture",
        [
            "tier1_points.fgb",
            "tier1_points.kml",
            "tier1_points.kmz",
            "tier1_points_gdb.zip",
        ],
    )
    async def test_loads_three_features(self, test_db_session, fixture: str):
        from app.processing.ingest.ogr import (
            build_pg_conn_str,
            run_ogr2ogr,
            run_ogrinfo,
        )

        table = f"tst_tier1_{uuid.uuid4().hex[:8]}"
        source = str(FIXTURES / fixture)
        try:
            info = await run_ogrinfo(source)
            await run_ogr2ogr(
                source,
                table,
                build_pg_conn_str(),
                source_srid=info.get("srid"),
                geometry_type=info.get("geometry_type"),
                schema="data",
            )
            count = await test_db_session.execute(
                text(f"SELECT count(*) FROM data.{table}")  # noqa: S608 - test table
            )
            assert count.scalar_one() == 3

            columns = await test_db_session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='data' AND table_name=:t"
                ).bindparams(t=table)
            )
            names = {row[0] for row in columns.all()}
            # KML flattens attributes into <SimpleData> and LIBKML also adds
            # `name`/`description`; every driver keeps the numeric columns.
            assert {"population", "area_km2"} <= names
        finally:
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table} CASCADE")
            )
            await test_db_session.commit()
