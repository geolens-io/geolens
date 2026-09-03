"""fix(#885): an antimeridian-crossing (west>east) bbox must narrow an ogr2ogr
export the same way it narrows /features and format=parquet.

``parse_bbox`` documents west>east as valid, but ogr2ogr's ``-spat`` takes ONE
rectangle and GDAL reads its corners as an envelope, so
``-spat 170 -20 -170 -15`` silently became the *complement* band
(lon -170..170): the export succeeded and dropped every feature the caller had
asked for. A Fiji or Aleutians AOI came back empty from GPKG/GeoJSON/SHP/CSV
while the same bbox returned rows from /features and from parquet.

The command-shape and unit tests here run everywhere. The end-to-end format
tests need a real ogr2ogr against the test PostGIS database, so they carry the
usual ``requires_ogr2ogr`` pair (skip on GDAL-less dev hosts; CI installs
gdal-bin).
"""

import csv
import json
import os
import shutil
import subprocess
import uuid

import pytest
from sqlalchemy import text

from app.processing.export.ogr import bbox_where_sql

# Fiji-ish: 170°E .. 170°W, i.e. minx > maxx.
CROSSING_BBOX = [170.0, -20.0, -170.0, -15.0]
# The east half of the same box — a plain, non-crossing rectangle.
EAST_HALF_BBOX = [170.0, -20.0, 180.0, -15.0]


# ---------------------------------------------------------------------------
# bbox_where_sql — pure unit
# ---------------------------------------------------------------------------


class TestBboxWhereSql:
    def test_non_crossing_is_one_envelope(self):
        sql = bbox_where_sql([1.0, 2.0, 3.0, 4.0])
        assert sql.count("ST_MakeEnvelope") == 2  # && prefilter + ST_Intersects
        assert " OR " not in sql
        assert "ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)" in sql
        assert "geom_4326 &&" in sql
        assert "ST_Intersects(geom_4326," in sql

    def test_crossing_splits_at_the_seam(self):
        sql = bbox_where_sql(CROSSING_BBOX)
        assert " OR " in sql
        # East half runs to +180, west half starts at -180.
        assert "ST_MakeEnvelope(:minx, :miny, 180, :maxy, 4326)" in sql
        assert "ST_MakeEnvelope(-180, :miny, :maxx, :maxy, 4326)" in sql
        # Both halves keep the && index prefilter AND the exact intersects.
        assert sql.count("geom_4326 &&") == 2
        assert sql.count("ST_Intersects(geom_4326,") == 2

    def test_literal_form_carries_no_bind_parameters(self):
        sql = bbox_where_sql(CROSSING_BBOX, literal=True)
        # ogr2ogr -where is a subprocess argv element: binds would never resolve.
        assert ":" not in sql
        assert "170.0" in sql and "-170.0" in sql
        assert "ST_MakeEnvelope(170.0, -20.0, 180, -15.0, 4326)" in sql
        assert "ST_MakeEnvelope(-180, -20.0, -170.0, -15.0, 4326)" in sql

    def test_literal_form_forces_numeric_rendering(self):
        """Every bound goes through float(), so nothing but a numeric literal
        can reach the SQL text. Deliberately violates the list[float] annotation:
        the point is that a non-numeric bound cannot be interpolated even if a
        future caller stops honouring the type."""
        sql = bbox_where_sql(["170", "-20", "-170", "-15"], literal=True)
        assert "170.0" in sql
        with pytest.raises(ValueError):
            bbox_where_sql(["1); DROP TABLE t --", "-20", "10", "-15"], literal=True)


# ---------------------------------------------------------------------------
# ogr2ogr command shape — no DB, no GDAL
# ---------------------------------------------------------------------------


class TestExportCommandShape:
    @pytest.fixture
    def captured(self, monkeypatch):
        """Capture the argv run_ogr2ogr_export would spawn."""
        from app.processing.export import ogr as export_ogr

        commands: list[tuple[str, ...]] = []

        async def _capture(*args, **kwargs):
            commands.append(args)

            class _Proc:
                returncode = 0

            return _Proc()

        async def _communicate(*args, **kwargs):
            return b"", b""

        monkeypatch.setattr(export_ogr.asyncio, "create_subprocess_exec", _capture)
        monkeypatch.setattr(export_ogr, "_communicate_with_timeout", _communicate)
        return commands

    async def _run(self, tmp_path, **kwargs):
        from app.processing.export.ogr import run_ogr2ogr_export

        await run_ogr2ogr_export(
            "roads",
            str(tmp_path / "out.geojson"),
            "GeoJSON",
            schema="data",
            **kwargs,
        )

    @pytest.mark.anyio
    async def test_crossing_bbox_uses_where_not_spat(self, captured, tmp_path):
        await self._run(tmp_path, bbox=CROSSING_BBOX)
        cmd = captured[0]
        # -spat would collapse to the complement band, so it must be gone.
        assert "-spat" not in cmd
        assert "-spat_srs" not in cmd
        where = cmd[cmd.index("-where") + 1]
        assert "ST_MakeEnvelope(170.0, -20.0, 180, -15.0, 4326)" in where
        assert "ST_MakeEnvelope(-180, -20.0, -170.0, -15.0, 4326)" in where
        assert " OR " in where

    @pytest.mark.anyio
    async def test_non_crossing_bbox_still_uses_spat(self, captured, tmp_path):
        await self._run(tmp_path, bbox=EAST_HALF_BBOX)
        cmd = captured[0]
        assert "-where" not in cmd
        spat = cmd.index("-spat")
        assert list(cmd[spat : spat + 5]) == [
            "-spat",
            "170.0",
            "-20.0",
            "180.0",
            "-15.0",
        ]
        assert cmd[cmd.index("-spat_srs") + 1] == "EPSG:4326"

    @pytest.mark.anyio
    async def test_crossing_bbox_ands_the_caller_where(self, captured, tmp_path):
        await self._run(tmp_path, bbox=CROSSING_BBOX, where="pop > 15")
        cmd = captured[0]
        assert cmd.count("-where") == 1
        where = cmd[cmd.index("-where") + 1]
        assert where.endswith(" AND (pop > 15)")
        assert " OR " in where

    @pytest.mark.anyio
    async def test_no_bbox_leaves_the_caller_where_alone(self, captured, tmp_path):
        await self._run(tmp_path, where="pop > 15")
        cmd = captured[0]
        assert cmd[cmd.index("-where") + 1] == "pop > 15"
        assert "-spat" not in cmd


# ---------------------------------------------------------------------------
# End-to-end: real ogr2ogr, real PostGIS, every ogr-backed format
# ---------------------------------------------------------------------------

_OGR_TESTS = [
    pytest.mark.skipif(
        shutil.which("ogr2ogr") is None,
        reason="ogr2ogr binary not available on host (runs in backend Docker image / CI)",
    ),
    pytest.mark.requires_ogr2ogr,
]

# name -> (WKT, pop). All linestrings: a shapefile holds one geometry type per
# file, and "on_the_seam" has to be a line so it can straddle the antimeridian
# in its own geometry — that is the feature a two-pass -spat split would emit
# twice. "greenwich" sits in the middle of the band the broken -spat rectangle
# collapsed to, so it pins the wrong-rows half of the bug, not just the
# missing-rows half.
_ROWS = {
    "east_of_170": ("LINESTRING(174 -18, 176 -18)", 10),
    "west_of_-170": ("LINESTRING(-176 -17, -174 -17)", 20),
    "on_the_seam": ("LINESTRING(179 -17.5, -179 -17.5)", 30),
    "greenwich": ("LINESTRING(-1 -17, 1 -17)", 40),
    "outside_lat_band": ("LINESTRING(174 40, 176 40)", 50),
}

# column_info for the where-clause validator (export_dataset rejects a filter
# when it has no column metadata to check the identifiers against).
_COLUMN_INFO = [
    {"name": "gid", "type": "integer"},
    {"name": "name", "type": "varchar"},
    {"name": "pop", "type": "integer"},
]


def _names_in(path: str) -> list[str]:
    """Read the ``name`` column out of an exported artifact."""
    if path.endswith(".csv"):
        with open(path, newline="") as fh:
            return sorted(row["name"] for row in csv.DictReader(fh))
    # GPKG / SHP / GeoJSON: let GDAL normalise them to GeoJSON, then read it.
    converted = os.path.join(os.path.dirname(path), f"read_{uuid.uuid4().hex[:8]}.json")
    subprocess.run(
        ["ogr2ogr", "-f", "GeoJSON", converted, path],
        check=True,
        capture_output=True,
        timeout=120,
    )
    with open(converted) as fh:
        return sorted(f["properties"]["name"] for f in json.load(fh)["features"])


class TestAntimeridianExportEndToEnd:
    pytestmark = _OGR_TESTS

    @pytest.fixture
    async def antimeridian_table(self, test_db_session, monkeypatch, tmp_path):
        from app.processing.export import service as export_service

        monkeypatch.setattr(
            export_service.settings, "upload_staging_dir", str(tmp_path)
        )

        table = f"exp_am_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table} (gid serial PRIMARY KEY, name varchar, "
                "pop integer, geom geometry(Geometry, 4326), "
                "geom_4326 geometry(Geometry, 4326))"
            )
        )
        for name, (wkt, pop) in _ROWS.items():
            await test_db_session.execute(
                text(
                    f"INSERT INTO data.{table} (name, pop, geom, geom_4326) VALUES "
                    "(:n, :p, ST_GeomFromText(:w, 4326), ST_GeomFromText(:w, 4326))"
                ).bindparams(n=name, p=pop, w=wkt)
            )
        await test_db_session.commit()
        yield table
        # Release any server-side cursor the test left open (the parquet writer
        # streams), or the DROP hits asyncpg's "used by active queries".
        await test_db_session.rollback()
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
        await test_db_session.commit()

    async def _export(self, table, format_key, **kwargs):
        from app.processing.export.service import export_dataset

        path, _filename, _media = await export_dataset(
            table, "AM Dataset", format_key, schema="data", **kwargs
        )
        if format_key == "shp":
            # export_dataset returns the ZIP; the .shp sits beside it.
            return os.path.join(os.path.dirname(path), "export.shp")
        return path

    @pytest.mark.anyio
    @pytest.mark.parametrize("format_key", ["gpkg", "geojson", "shp", "csv"])
    async def test_crossing_bbox_exports_both_sides_of_the_seam(
        self, antimeridian_table, format_key
    ):
        """The regression: every ogr-backed format used to come back without the
        features inside the requested box."""
        out = await self._export(antimeridian_table, format_key, bbox=CROSSING_BBOX)
        assert _names_in(out) == ["east_of_170", "on_the_seam", "west_of_-170"]

    @pytest.mark.anyio
    @pytest.mark.parametrize("format_key", ["gpkg", "geojson", "shp", "csv"])
    async def test_non_crossing_bbox_unchanged(self, antimeridian_table, format_key):
        """-spat still serves the ordinary case: the east half selects only what
        lies east of 170, and nothing at Greenwich or outside the lat band."""
        out = await self._export(antimeridian_table, format_key, bbox=EAST_HALF_BBOX)
        assert _names_in(out) == ["east_of_170", "on_the_seam"]

    @pytest.mark.anyio
    async def test_seam_feature_is_not_duplicated(self, antimeridian_table):
        """A geometry that straddles the antimeridian intersects BOTH halves of
        the split. The predicate is one OR in one pass, so it is exported once —
        two appended -spat runs would emit it twice."""
        out = await self._export(antimeridian_table, "geojson", bbox=CROSSING_BBOX)
        with open(out) as fh:
            features = json.load(fh)["features"]
        assert [f["properties"]["name"] for f in features].count("on_the_seam") == 1
        assert len(features) == 3

    @pytest.mark.anyio
    async def test_crossing_bbox_and_where_are_combined(self, antimeridian_table):
        """The split predicate ANDs with the caller's attribute filter instead of
        replacing it."""
        out = await self._export(
            antimeridian_table,
            "geojson",
            bbox=CROSSING_BBOX,
            where="pop > 15",
            column_info=_COLUMN_INFO,
        )
        assert _names_in(out) == ["on_the_seam", "west_of_-170"]

    @pytest.mark.anyio
    async def test_geometry_is_selected_not_clipped(self, antimeridian_table):
        """-spat/-where select whole features; -clipsrc would have cut the seam
        linestring at the box edge. Its coordinates must survive intact."""
        out = await self._export(antimeridian_table, "geojson", bbox=CROSSING_BBOX)
        with open(out) as fh:
            features = json.load(fh)["features"]
        seam = next(f for f in features if f["properties"]["name"] == "on_the_seam")
        assert seam["geometry"]["coordinates"] == [[179.0, -17.5], [-179.0, -17.5]]

    @pytest.mark.anyio
    async def test_ogr_export_agrees_with_the_features_and_parquet_paths(
        self, antimeridian_table, test_db_session
    ):
        """The asymmetry #885 is about: the same crossing bbox now selects the
        same rows through /features, GeoParquet, and the ogr2ogr export."""
        from app.modules.catalog.features.service import get_features
        from app.processing.export.parquet import export_parquet

        page = await get_features(
            test_db_session,
            antimeridian_table,
            limit=100,
            bbox=CROSSING_BBOX,
        )
        features_names = sorted(r["properties"]["name"] for r in page.rows)

        # fix(#1513): planning (introspection + filter validation + the bounded
        # count) is a separate phase from writing, so the route can decide a
        # HEAD's status without producing bytes. Same two steps here.
        from app.processing.export.parquet import plan_parquet_export

        parquet_plan = await plan_parquet_export(
            test_db_session,
            antimeridian_table,
            schema="data",
            bbox=CROSSING_BBOX,
        )
        parquet_path, _fn, _mt = await export_parquet(
            test_db_session,
            antimeridian_table,
            "AM Dataset",
            schema="data",
            plan=parquet_plan,
        )
        try:
            import pyarrow.parquet as pq

            parquet_names = sorted(
                pq.read_table(parquet_path).column("name").to_pylist()
            )
        finally:
            shutil.rmtree(os.path.dirname(parquet_path), ignore_errors=True)

        ogr_names = _names_in(
            await self._export(antimeridian_table, "gpkg", bbox=CROSSING_BBOX)
        )

        assert features_names == parquet_names == ogr_names
        assert ogr_names == ["east_of_170", "on_the_seam", "west_of_-170"]


# ---------------------------------------------------------------------------
# A bbox must never reach the geom_4326 predicate on a geometry-less layer
# ---------------------------------------------------------------------------


class TestNonSpatialBboxIsDropped:
    """A non-spatial dataset can only reach the ogr path as csv, and ``-spat``
    was already a no-op there. The router drops the bbox for it so the
    server-side geom_4326 predicate is never asked of a table without the
    column (which would fail the whole translation)."""

    @pytest.fixture
    def captured_bbox(self, monkeypatch, tmp_path):
        """Patch the router's export_dataset and record the bbox it receives."""
        seen: dict = {}

        async def _fake_export(
            table_name,
            dataset_name,
            format_key,
            *,
            schema,
            target_srs=None,
            bbox=None,
            where=None,
            pmtiles_maxzoom=None,
            column_info=None,
            deadline=None,
        ):
            seen["bbox"] = bbox
            path = tmp_path / f"{uuid.uuid4().hex}.out"
            path.write_text("name\n")
            return str(path), path.name, "text/csv"

        monkeypatch.setattr("app.processing.export.router.export_dataset", _fake_export)
        return seen

    @pytest.mark.anyio
    async def test_router_drops_bbox_for_non_spatial_dataset(
        self, client, admin_auth_header, test_db_session, captured_bbox
    ):
        from tests.factories import get_user_id
        from tests.test_export import _create_dataset

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="NonSpatialAmDS",
            geometry_type=None,
            record_type="table",
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"format": "csv", "bbox": "170,-20,-170,-15"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert captured_bbox["bbox"] is None

    @pytest.mark.anyio
    async def test_router_keeps_bbox_for_spatial_dataset(
        self, client, admin_auth_header, test_db_session, captured_bbox
    ):
        from tests.factories import get_user_id
        from tests.test_export import _create_dataset

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="SpatialAmDS",
            geometry_type="Point",
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"format": "geojson", "bbox": "170,-20,-170,-15"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert captured_bbox["bbox"] == CROSSING_BBOX
