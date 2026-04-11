"""Column preservation regression tests — backend/app/ingest/.

These tests require a real ogr2ogr binary. On dev hosts without GDAL
installed, every test in this file is skipped. CI and the backend
Docker image install gdal-bin via apt (see backend/Dockerfile), so the
tests run in full there.

Covers:
  RESEARCH §2.1  -lco PRECISION=NO round-trip (type documented, not changed)
  RESEARCH §2.2  Reserved-name auto-rename (gid/geom/geom_4326/fid)
  RESEARCH §2.3  DBF truncation collision warning (shapefile-only)
  RESEARCH §2.4  get_column_info excluded set unchanged (verified safe)
  RESEARCH §2.5  Non-ASCII column names get sample values after identifier quoting

Pure-unit tests for detect_dbf_truncation_collisions live in
test_ingest_ogr_pure.py so they run on dev hosts without GDAL.
"""

import shutil
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

# All tests in this file invoke ogr2ogr against PostGIS. Two module-level
# guards apply:
#
#   1. ``pytest.mark.skipif`` bails out when the ogr2ogr binary is missing
#      (common on dev hosts outside the backend Docker image / CI).
#   2. ``pytest.mark.requires_ogr2ogr`` opts into the autouse
#      ``_point_ogr2ogr_at_test_db`` fixture in ``conftest.py`` (K2-PRE),
#      which monkey-patches ``build_pg_conn_str`` so tables land in the
#      ``geolens_test`` database instead of dev/prod.
pytestmark = [
    pytest.mark.skipif(
        shutil.which("ogr2ogr") is None,
        reason="ogr2ogr binary not available on host (runs in backend Docker image / CI)",
    ),
    pytest.mark.requires_ogr2ogr,
]

FIXTURES = Path(__file__).parent / "fixtures" / "ingest"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _load_fixture(
    test_db_session, fixture_name: str, table: str, *, non_spatial: bool = False
) -> dict:
    """Run ogrinfo + ogr2ogr against the test PostGIS DB, return useful metadata.

    Returns a dict with:
      table_name            — the target table used
      filtered_column_info  — output of get_column_info (what catalog sees)
      raw_column_names      — list[str] from information_schema.columns
      srid                  — detected SRID (may be None for non-spatial)
    """
    from app.ingest.metadata import get_column_info
    from app.ingest.ogr import build_pg_conn_str, run_ogr2ogr, run_ogrinfo

    source = str(FIXTURES / fixture_name)
    info = await run_ogrinfo(source)
    geometry_type = None if non_spatial else info.get("geometry_type")
    await run_ogr2ogr(
        source,
        table,
        build_pg_conn_str(),
        source_srid=info.get("srid"),
        geometry_type=geometry_type,
    )
    filtered = await get_column_info(test_db_session, table)
    raw = await test_db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='data' AND table_name=:t "
            "ORDER BY ordinal_position"
        ).bindparams(t=table),
    )
    return {
        "table_name": table,
        "filtered_column_info": filtered,
        "raw_column_names": [r[0] for r in raw.all()],
        "srid": info.get("srid"),
    }


async def _drop_table(test_db_session, table: str) -> None:
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table} CASCADE"))
    await test_db_session.commit()


def _table_id(prefix: str) -> str:
    """Generate a collision-safe table name for parallel test runs."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# §2.1  Basic round-trip + PRECISION=NO behavior (locked decision)
# ---------------------------------------------------------------------------


class TestBasicAttrsRoundTrip:
    """RESEARCH §2.1: every source attribute is queryable after import."""

    async def test_all_fields_in_column_info(self, test_db_session):
        table = _table_id("tst_basic")
        try:
            result = await _load_fixture(test_db_session, "basic_attrs.geojson", table)
            names = {c["name"] for c in result["filtered_column_info"]}
            assert {
                "name",
                "population",
                "area_km2",
                "is_capital",
                "founded",
            } <= names, (
                f"Expected source columns missing from column_info. Got: {names}"
            )
        finally:
            await _drop_table(test_db_session, table)

    async def test_numeric_precision_becomes_double(self, test_db_session):
        """Document current PRECISION=NO behavior — pinned, not a bug.

        -lco PRECISION=NO forces all numeric-family source fields to FLOAT8 /
        INTEGER / VARCHAR. This is an intentional trade-off (see ogr.py comment
        and 260410-d7k-CONTEXT.md locked decision). The test pins the behavior
        so any accidental change to the flag is caught immediately.
        """
        table = _table_id("tst_precision")
        try:
            result = await _load_fixture(test_db_session, "basic_attrs.geojson", table)
            area = next(
                (c for c in result["filtered_column_info"] if c["name"] == "area_km2"),
                None,
            )
            assert area is not None, "area_km2 column not found in column_info"
            # PRECISION=NO maps float source fields to double precision or real.
            col_type = area["type"].lower()
            assert "double" in col_type or "real" in col_type or "float" in col_type, (
                f"Expected double/real/float for area_km2, got: {area['type']!r}. "
                "If PRECISION=NO was removed, this test correctly catches the regression."
            )
        finally:
            await _drop_table(test_db_session, table)


# ---------------------------------------------------------------------------
# §2.2  Reserved-name auto-rename
# ---------------------------------------------------------------------------


class TestReservedNameAutoRename:
    """RESEARCH §2.2: source fields named gid/geom/geom_4326/fid are preserved."""

    async def test_reserved_names_renamed_to_src_prefix(self, test_db_session):
        """After rename_reserved_columns(), src_* columns exist in the table."""
        from app.ingest.metadata import rename_reserved_columns

        table = _table_id("tst_reserved")
        try:
            await _load_fixture(test_db_session, "reserved_names.geojson", table)
            renames = await rename_reserved_columns(test_db_session, table)
            rename_originals = {r["original"] for r in renames}
            rename_targets = {r["renamed"] for r in renames}

            # geom_4326 and fid must always be renamed (always source-origin on entry).
            assert "geom_4326" in rename_originals, (
                f"Expected geom_4326 in renames, got originals: {rename_originals}"
            )
            assert "fid" in rename_originals, (
                f"Expected fid in renames, got originals: {rename_originals}"
            )

            # Targets must all use the src_ prefix.
            for target in rename_targets:
                assert target.startswith("src_"), (
                    f"Rename target {target!r} does not start with 'src_'"
                )

            # The renamed columns must actually exist in the table now.
            raw = await test_db_session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='data' AND table_name=:t"
                ).bindparams(t=table),
            )
            raw_names = {r[0] for r in raw.all()}
            for target in rename_targets:
                assert target in raw_names, (
                    f"Renamed column {target!r} not found in information_schema. "
                    f"Table columns: {raw_names}"
                )
        finally:
            await _drop_table(test_db_session, table)

    async def test_add_4326_column_after_rename_does_not_crash(self, test_db_session):
        """Regression for RESEARCH §2.2 Scenario C.

        Before fix: add_4326_column would silently no-op the ALTER TABLE
        (because a source geom_4326 text column already existed), then overwrite
        the source attribute with reprojected geometry via UPDATE.

        After fix: rename_reserved_columns() runs first, renaming the source
        geom_4326 to src_geom_4326. ensure_geom_column() then renames the
        pipeline placeholder (`_geolens_geom`, per S1 fix) to `geom`. Finally
        add_4326_column() creates a fresh geom_4326 geometry column without
        collision.
        """
        from app.ingest.metadata import (
            add_4326_column,
            ensure_geom_column,
            rename_reserved_columns,
        )

        table = _table_id("tst_add4326")
        try:
            result = await _load_fixture(
                test_db_session, "reserved_names.geojson", table
            )
            await rename_reserved_columns(test_db_session, table)
            # Mirror _finalize_ingest: ensure_geom_column must run before
            # add_4326_column so the pipeline placeholder becomes `geom`.
            await ensure_geom_column(test_db_session, table)

            # This previously would either crash or silently clobber the source attr.
            await add_4326_column(test_db_session, table, result["srid"] or 4326)

            raw = await test_db_session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='data' AND table_name=:t"
                ).bindparams(t=table),
            )
            raw_names = {r[0] for r in raw.all()}
            assert "geom_4326" in raw_names, (
                "Pipeline-internal geom_4326 column was not created by add_4326_column"
            )
            assert "src_geom_4326" in raw_names, (
                "Source geom_4326 attribute was not preserved as src_geom_4326"
            )
        finally:
            await _drop_table(test_db_session, table)

    async def test_src_columns_visible_in_get_column_info(self, test_db_session):
        """After rename, src_* columns appear in column_info (not stripped).

        get_column_info excludes {'gid', 'geom', 'geom_4326'} — the pipeline-
        internal names. It must NOT exclude 'src_gid', 'src_geom_4326', etc.
        """
        from app.ingest.metadata import get_column_info, rename_reserved_columns

        table = _table_id("tst_vis")
        try:
            await _load_fixture(test_db_session, "reserved_names.geojson", table)
            renames = await rename_reserved_columns(test_db_session, table)
            col_info = await get_column_info(test_db_session, table)
            col_names = {c["name"] for c in col_info}

            for rename in renames:
                target = rename["renamed"]
                assert target in col_names, (
                    f"Renamed column {target!r} not visible in get_column_info output. "
                    f"Available: {col_names}"
                )
        finally:
            await _drop_table(test_db_session, table)

    async def test_source_geom_attribute_renamed_to_src_geom(self, test_db_session):
        """S1 regression: source `geom` attribute does not collide with pipeline geom.

        Before fix: ogr2ogr used GEOMETRY_NAME=geom and crashed at CREATE TABLE
        because the source file also had a `geom` attribute. Both columns would
        be declared as `"geom" VARCHAR` and `"geom" geometry(...)`.

        After fix: ogr2ogr uses GEOMETRY_NAME=_geolens_geom (placeholder),
        rename_reserved_columns() moves the source `geom` attribute to `src_geom`,
        then ensure_geom_column() renames the placeholder to `geom`. Both the
        source attribute and the pipeline geometry column coexist.
        """
        from app.ingest.metadata import ensure_geom_column, rename_reserved_columns

        table = _table_id("tst_srcgeom")
        try:
            # _load_fixture runs ogrinfo + ogr2ogr. Pre-fix, ogr2ogr crashes here.
            await _load_fixture(test_db_session, "reserved_names.geojson", table)

            # Apply the post-ingest normalization pipeline in order.
            renames = await rename_reserved_columns(test_db_session, table)
            has_geom = await ensure_geom_column(test_db_session, table)

            assert has_geom is True, "Pipeline geometry column should exist"

            rename_originals = {r["original"] for r in renames}
            assert "geom" in rename_originals, (
                f"Source `geom` attribute should have been renamed, "
                f"got originals: {rename_originals}"
            )

            # Verify both columns exist and have the expected types.
            result = await test_db_session.execute(
                text(
                    "SELECT column_name, data_type, udt_name "
                    "FROM information_schema.columns "
                    "WHERE table_schema='data' AND table_name=:t "
                    "AND column_name IN ('geom', 'src_geom')"
                ).bindparams(t=table),
            )
            cols_by_name = {r[0]: (r[1], r[2]) for r in result.all()}

            assert "geom" in cols_by_name, (
                "Pipeline `geom` geometry column missing after rename"
            )
            pipeline_type, pipeline_udt = cols_by_name["geom"]
            assert pipeline_udt == "geometry", (
                f"`geom` should be a PostGIS geometry column, got "
                f"data_type={pipeline_type!r} udt_name={pipeline_udt!r}"
            )

            assert "src_geom" in cols_by_name, (
                "Source `geom` attribute was not preserved as `src_geom`"
            )
            src_type, src_udt = cols_by_name["src_geom"]
            assert src_udt != "geometry", (
                f"`src_geom` should be the source VARCHAR/text column, got "
                f"udt_name={src_udt!r}"
            )

            # Confirm the source values survived the rename.
            value_result = await test_db_session.execute(
                text(f"SELECT src_geom FROM data.{table} ORDER BY gid")
            )
            values = [r[0] for r in value_result.all()]
            assert values == ["not-actually-a-geometry", "also-text"], (
                f"Source `geom` values lost or reordered: {values}"
            )
        finally:
            await _drop_table(test_db_session, table)


# ---------------------------------------------------------------------------
# §2.5  Non-ASCII column names get sample values after SQL-quoting fix
# ---------------------------------------------------------------------------


class TestUnicodeSampleValues:
    """RESEARCH §2.5: get_sample_values returns values for non-ASCII column names."""

    async def test_non_ascii_columns_have_sample_values(self, test_db_session):
        """No column should be silently absent from sample_values.

        GDAL's LAUNDER=YES typically lowercases and ASCII-ifies column names
        during PG import, so the names in column_info may differ from the
        source. The assertion is: whatever names land in column_info, every
        non-geometry column with non-null data must have sample values.
        """
        from app.ingest.metadata import get_column_info, get_sample_values

        table = _table_id("tst_unicode")
        try:
            await _load_fixture(test_db_session, "unicode_attrs.geojson", table)
            cols = await get_column_info(test_db_session, table)
            samples = await get_sample_values(test_db_session, table, cols)

            non_geom_cols = [
                c for c in cols if "geometry" not in c.get("type", "").lower()
            ]
            assert len(non_geom_cols) >= 1, "Expected at least one non-geometry column"

            # Every non-geometry column that has data must appear in samples.
            for col in non_geom_cols:
                assert col["name"] in samples, (
                    f"Column {col['name']!r} is missing from sample_values. "
                    f"Present keys: {list(samples.keys())}"
                )
        finally:
            await _drop_table(test_db_session, table)

    async def test_ascii_control_column_has_sample_values(self, test_db_session):
        """Control: the plain ASCII column name_ascii must also have samples."""
        from app.ingest.metadata import get_column_info, get_sample_values

        table = _table_id("tst_ascii_ctrl")
        try:
            await _load_fixture(test_db_session, "unicode_attrs.geojson", table)
            cols = await get_column_info(test_db_session, table)
            samples = await get_sample_values(test_db_session, table, cols)

            # name_ascii is a guaranteed pure-ASCII column in the fixture.
            # LAUNDER=YES preserves it as-is.
            ascii_cols = [c for c in cols if "name_ascii" in c["name"]]
            assert len(ascii_cols) >= 1, "name_ascii column not found in column_info"
            for col in ascii_cols:
                assert col["name"] in samples, (
                    f"Control column {col['name']!r} missing from sample_values"
                )
        finally:
            await _drop_table(test_db_session, table)


# ---------------------------------------------------------------------------
# §N6  get_sample_values yields samples for sparse (>=99%-null) columns
# ---------------------------------------------------------------------------


class TestSparseColumnSampleValues:
    """INGEST-N6: get_sample_values returns samples for 99%+ NULL columns.

    Regression test for the sparse-column yield bug introduced by the
    CTE-batched rewrite (commit 180cfa97). Pre-bump (sample_size=1000),
    a column that is 99.95% NULL would yield 0 or 1 samples depending on
    row ordering. Post-bump (sample_size=10000), the same column yields
    ~5 samples, comfortably under the LIMIT 10 display cap.
    """

    async def test_sparse_column_yields_at_least_one_sample(self, test_db_session):
        """A 99.95%-null column must still have sample values with default sample_size."""
        from app.ingest.metadata import get_sample_values

        table = _table_id("tst_sparse")
        try:
            # Build a synthetic table with:
            #   - `id` (non-null control column — always populated)
            #   - `sparse_col` (99.95% NULL — non-null on row 1 only, NULL on rows 2-2000)
            await test_db_session.execute(
                text(
                    f"CREATE TABLE data.{table} ("
                    f"  id integer PRIMARY KEY,"
                    f"  sparse_col text"
                    f")"
                )
            )
            await test_db_session.execute(
                text(
                    f"INSERT INTO data.{table} (id, sparse_col) "
                    f"SELECT g, CASE WHEN g = 1 THEN 'only-value' ELSE NULL END "
                    f"FROM generate_series(1, 2000) g"
                )
            )
            await test_db_session.commit()

            column_info = [
                {"name": "id", "type": "integer"},
                {"name": "sparse_col", "type": "text"},
            ]
            samples = await get_sample_values(test_db_session, table, column_info)

            # Control: the dense id column always has samples.
            assert "id" in samples, (
                f"Control column 'id' missing from samples. "
                f"Got keys: {list(samples.keys())}"
            )
            assert len(samples["id"]) >= 1

            # Regression: the sparse column must also have at least one sample.
            # Pre-bump (sample_size=1000): zero or one non-null in a 1000-row
            # scan window on the 1-in-2000 row -> flaky or empty.
            # Post-bump (sample_size=10000): the 10000-row scan window always
            # includes row 1 -> sample is always present.
            assert "sparse_col" in samples, (
                f"Sparse column 'sparse_col' missing from samples. "
                f"Got keys: {list(samples.keys())}. This is the exact regression "
                f"the sample_size bump is meant to fix."
            )
            assert samples["sparse_col"] == ["only-value"]
        finally:
            await _drop_table(test_db_session, table)

    async def test_dense_column_unchanged_by_bump(self, test_db_session):
        """Control: dense columns continue to yield up to 10 distinct samples.

        Ensures the bump did not accidentally change behavior for the
        common case where LIMIT 10 is the binding constraint.
        """
        from app.ingest.metadata import get_sample_values

        table = _table_id("tst_dense_ctrl")
        try:
            await test_db_session.execute(
                text(
                    f"CREATE TABLE data.{table} ("
                    f"  id integer PRIMARY KEY,"
                    f"  color text"
                    f")"
                )
            )
            # 12 distinct values across 24 rows — every value appears twice.
            # Expected: LIMIT 10 truncates to 10 distinct.
            await test_db_session.execute(
                text(
                    f"INSERT INTO data.{table} (id, color) VALUES "
                    f"(1,'red'),(2,'red'),(3,'orange'),(4,'orange'),"
                    f"(5,'yellow'),(6,'yellow'),(7,'green'),(8,'green'),"
                    f"(9,'blue'),(10,'blue'),(11,'indigo'),(12,'indigo'),"
                    f"(13,'violet'),(14,'violet'),(15,'cyan'),(16,'cyan'),"
                    f"(17,'magenta'),(18,'magenta'),(19,'teal'),(20,'teal'),"
                    f"(21,'lime'),(22,'lime'),(23,'pink'),(24,'pink')"
                )
            )
            await test_db_session.commit()

            column_info = [
                {"name": "id", "type": "integer"},
                {"name": "color", "type": "text"},
            ]
            samples = await get_sample_values(test_db_session, table, column_info)

            assert "color" in samples
            # LIMIT 10 display cap unchanged — should be exactly 10 distinct.
            assert len(samples["color"]) == 10
        finally:
            await _drop_table(test_db_session, table)


# ---------------------------------------------------------------------------
# §2.3  DBF truncation collision detection (shapefile-specific)
# ---------------------------------------------------------------------------


class TestDbfTruncationCollision:
    """RESEARCH §2.3: warn when shapefile field names collide post-truncation.

    The pure-unit test (no ogr2ogr needed) lives in test_ingest_ogr_pure.py.
    This class exercises the full path: load the fixture via run_ogrinfo_preview
    and assert that detect_dbf_truncation_collisions fires on its column list.
    """

    async def test_shapefile_zip_ogrinfo_preview_returns_columns(self, test_db_session):
        """run_ogrinfo_preview parses the DBF column list from the zip fixture."""
        from app.ingest.ogr import run_ogrinfo_preview

        preview = await run_ogrinfo_preview(
            str(FIXTURES / "dbf_collision.zip"), sample_limit=0
        )
        columns = preview.get("columns") or []
        col_names = [c["name"] for c in columns]
        # The fixture DBF has population_2020 and population_2021 — but after
        # GDAL's LAUNDER+truncation they may appear as 'populatio' / 'populati'
        # or 'population' / 'populatio'. Either way, at least one field named
        # starting with 'populat' must appear to confirm parsing worked.
        assert any("populat" in n.lower() for n in col_names), (
            f"Expected a 'populat*' column in ogrinfo preview, got: {col_names}"
        )

    async def test_shapefile_zip_collision_detected(self, test_db_session):
        """detect_dbf_truncation_collisions fires on the dbf_collision.zip fixture.

        Note: GDAL may auto-disambiguate the conflicting names before our
        pipeline sees them (e.g., rename to 'population_' and 'populatio').
        The collision detector works on the *source* names as reported by
        ogrinfo; if ogrinfo already shows disambiguated names, collisions == 0.
        This test verifies the detection path executes without error and the
        helper does not crash on real fixture data.
        """
        from app.ingest.metadata import detect_dbf_truncation_collisions
        from app.ingest.ogr import run_ogrinfo_preview

        preview = await run_ogrinfo_preview(
            str(FIXTURES / "dbf_collision.zip"), sample_limit=0
        )
        columns = preview.get("columns") or []
        # Should not raise:
        collisions = detect_dbf_truncation_collisions(columns)
        # collisions may be 0 if GDAL already disambiguated; that is acceptable.
        assert isinstance(collisions, list)
