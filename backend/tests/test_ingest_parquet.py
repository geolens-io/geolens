"""GeoParquet ingest tests: pyarrow reader/loader + PAR1 content validation.

DB-free tests exercise magic-byte validation and the parquet_info preview
(dispatched through run_ogrinfo/run_ogrinfo_preview to also cover the
ogr.py branch). DB-backed tests run the acceptance gate: export a seeded
table with the existing GeoParquet exporter and re-ingest it with
load_parquet_to_postgis, asserting row count and geometry equality.

Requires the Docker database (docker compose up db) with migrations applied
for the DB-backed class.
"""

import json
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import text

from app.processing.export.parquet import build_geoparquet_table, export_parquet
from app.processing.ingest.ogr import (
    IngestionError,
    run_ogrinfo,
    run_ogrinfo_preview,
)
from app.processing.ingest.parquet import (
    _srid_from_geo,
    load_parquet_to_postgis,
    parquet_info,
)
from app.processing.ingest.validation import (
    validate_file_content,
    validate_file_size,
    validate_parquet_file,
)


def _write_geoparquet(path, *, crs: dict | None = None) -> None:
    """3-point GeoParquet file via the export writer (WKB, geo metadata)."""
    from shapely.geometry import Point

    geom = [Point(0, 0).wkb, Point(1, 1).wkb, None]
    cols = {"pop": [10, 20, 30], "name": ["a", "b", "c"]}
    table = build_geoparquet_table(geom, cols, ["pop", "name"])
    if crs is not None:
        geo = json.loads(table.schema.metadata[b"geo"])
        geo["columns"]["geometry"]["crs"] = crs
        table = table.replace_schema_metadata({b"geo": json.dumps(geo).encode()})
    pq.write_table(table, path)


def _write_plain_parquet(path) -> None:
    pq.write_table(
        pa.table({"gid": [1, 2], "label": ["x", "y"], "value": [1.5, 2.5]}), path
    )


@pytest.mark.anyio
async def test_geometry_only_without_geometry_raises(tmp_path):
    """fix(#569): geometry-only file + include_geometry=False must fail fast
    instead of silently publishing an empty dataset."""
    from shapely.geometry import Point

    p = tmp_path / "geomonly.parquet"
    pq.write_table(build_geoparquet_table([Point(0, 0).wkb], {}, []), p)
    with pytest.raises(IngestionError, match="only a geometry column"):
        await load_parquet_to_postgis(
            str(p), "t_geomonly", schema="data", srid=4326, include_geometry=False
        )


class TestParquetValidation:
    def test_valid_parquet_passes(self, tmp_path):
        p = tmp_path / "ok.parquet"
        _write_plain_parquet(p)
        validate_parquet_file(str(p))
        validate_file_content(str(p), "ok.parquet")

    def test_wrong_content_rejected(self, tmp_path):
        p = tmp_path / "fake.parquet"
        p.write_bytes(b"id,name\n1,not parquet at all\n" * 10)
        with pytest.raises(ValueError, match="not a valid Parquet file"):
            validate_file_content(str(p), "fake.parquet")

    def test_truncated_parquet_rejected(self, tmp_path):
        p = tmp_path / "trunc.parquet"
        _write_plain_parquet(p)
        data = p.read_bytes()
        p.write_bytes(data[:-4])  # chop the footer magic
        with pytest.raises(ValueError, match="corrupt or truncated"):
            validate_parquet_file(str(p))

    def test_tiny_file_rejected(self, tmp_path):
        p = tmp_path / "tiny.parquet"
        p.write_bytes(b"PAR1")
        with pytest.raises(ValueError, match="not a valid Parquet file"):
            validate_parquet_file(str(p))

    def test_oversize_parquet_rejected(self, tmp_path):
        p = tmp_path / "big.parquet"
        _write_plain_parquet(p)
        with pytest.raises(ValueError, match="exceeds the maximum"):
            validate_file_size(str(p), max_size_bytes=10)


class TestParquetInfo:
    @pytest.mark.anyio
    async def test_geoparquet_info_via_run_ogrinfo(self, tmp_path):
        p = tmp_path / "pts.parquet"
        _write_geoparquet(p)
        info = await run_ogrinfo(str(p))
        assert info["srid"] == 4326  # crs omitted -> OGC:CRS84
        assert info["geometry_type"] == "Point"  # probed from first WKB row
        assert info["feature_count"] == 3
        assert [c["name"] for c in info["columns"]] == ["pop", "name"]
        assert info["all_layers"] is None

    @pytest.mark.anyio
    async def test_preview_sample_rows_exclude_geometry(self, tmp_path):
        p = tmp_path / "pts.parquet"
        _write_geoparquet(p)
        info = await run_ogrinfo_preview(str(p), sample_limit=2)
        assert len(info["sample_rows"]) == 2
        assert info["sample_rows"][0] == {"pop": 10, "name": "a"}
        assert "geometry" not in info["sample_rows"][0]

    @pytest.mark.anyio
    async def test_plain_parquet_is_non_spatial(self, tmp_path):
        p = tmp_path / "plain.parquet"
        _write_plain_parquet(p)
        info = await parquet_info(str(p), sample_limit=5)
        assert info["geometry_type"] is None
        assert info["srid"] is None
        assert info["feature_count"] == 2
        assert {c["name"] for c in info["columns"]} == {"gid", "label", "value"}

    @pytest.mark.anyio
    async def test_projjson_epsg_crs_resolves(self, tmp_path):
        p = tmp_path / "utm.parquet"
        _write_geoparquet(p, crs={"id": {"authority": "EPSG", "code": 32633}})
        info = await parquet_info(str(p))
        assert info["srid"] == 32633

    def test_unresolvable_crs_returns_none(self):
        assert _srid_from_geo({"crs": {"name": "some bespoke CRS"}}) is None
        assert _srid_from_geo({}) == 4326  # omitted -> CRS84
        # explicit null differs from omitted per spec: CRS is UNKNOWN, so the
        # pipeline's Missing-CRS / srid_override path must apply (PR #541 review)
        assert _srid_from_geo({"crs": None}) is None

    @pytest.mark.anyio
    async def test_non_wkb_encoding_rejected(self, tmp_path):
        p = tmp_path / "geoarrow.parquet"
        _write_geoparquet(p)
        table = pq.read_table(p)
        geo = json.loads(table.schema.metadata[b"geo"])
        geo["columns"]["geometry"]["encoding"] = "point"
        table = table.replace_schema_metadata({b"geo": json.dumps(geo).encode()})
        pq.write_table(table, p)
        with pytest.raises(IngestionError, match="only WKB"):
            await parquet_info(str(p))

    @pytest.mark.anyio
    async def test_nan_and_inf_sample_values_become_null(self, tmp_path):
        # Starlette serializes JSON with allow_nan=False; non-finite floats in
        # sample rows must not 500 the preview endpoint (PR #543 review).
        p = tmp_path / "nan.parquet"
        pq.write_table(pa.table({"v": [float("nan"), float("inf"), 1.5]}), p)
        info = await parquet_info(str(p), sample_limit=3)
        assert [r["v"] for r in info["sample_rows"]] == [None, None, 1.5]

    @pytest.mark.anyio
    async def test_corrupt_parquet_raises(self, tmp_path):
        # The preview route maps any failure here to a clean 422.
        p = tmp_path / "corrupt.parquet"
        p.write_bytes(b"PAR1" + b"\x00" * 64 + b"PAR1")
        with pytest.raises(Exception):
            await parquet_info(str(p))


class TestMissingCrsGate:
    """Shared ingest/reupload gate (PR #541 review): unknown-CRS spatial
    sources must fail (or carry srid_override) instead of assuming 4326."""

    def test_unknown_crs_blocks(self):
        from app.processing.ingest.tasks_common import check_missing_crs

        msg = check_missing_crs(
            file_path="/tmp/x.parquet",
            has_geometry=True,
            detected_srid=None,
            srid_override=None,
        )
        assert msg is not None and "Missing CRS" in msg

    def test_override_detected_nonspatial_and_4326_formats_pass(self):
        from app.processing.ingest.tasks_common import check_missing_crs

        common = {"has_geometry": True, "detected_srid": None, "srid_override": None}
        assert (
            check_missing_crs(
                **{**common, "file_path": "/x.parquet", "srid_override": 2263}
            )
            is None
        )
        assert (
            check_missing_crs(
                **{**common, "file_path": "/x.parquet", "detected_srid": 4326}
            )
            is None
        )
        assert (
            check_missing_crs(
                **{**common, "file_path": "/x.parquet", "has_geometry": False}
            )
            is None
        )
        assert check_missing_crs(**{**common, "file_path": "/x.geojson"}) is None


class TestParquetRoundTrip:
    """Acceptance gate: exporter output re-ingests losslessly."""

    @pytest.fixture
    async def seeded_table(self, test_db_session):
        table_name = f"rt_pq_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} "
                "(gid serial PRIMARY KEY, pop integer, name text, "
                "observed_at timestamptz, "
                "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326))"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} "
                "(pop, name, observed_at, geom, geom_4326) VALUES "
                "(10, 'a', '2026-01-01T00:00:00Z', "
                " ST_SetSRID(ST_MakePoint(0, 0), 4326), ST_SetSRID(ST_MakePoint(0, 0), 4326)), "
                "(20, 'b', '2026-02-01T00:00:00Z', "
                " ST_SetSRID(ST_MakePoint(1, 1), 4326), ST_SetSRID(ST_MakePoint(1, 1), 4326)), "
                "(30, 'c', NULL, NULL, NULL)"
            )
        )
        await test_db_session.commit()
        yield table_name
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
        await test_db_session.commit()

    @pytest.fixture
    async def ingested_table(self, test_db_session):
        table_name = f"rt_pq_in_{uuid.uuid4().hex[:12]}"
        yield table_name
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
        await test_db_session.commit()

    @pytest.mark.anyio
    async def test_export_then_reingest(
        self, test_db_session, seeded_table, ingested_table
    ):
        import shutil
        from pathlib import Path

        file_path, _, _ = await export_parquet(
            test_db_session, seeded_table, "roundtrip", schema="data"
        )
        try:
            info = await run_ogrinfo(file_path)
            assert info["srid"] == 4326
            assert info["feature_count"] == 3

            await load_parquet_to_postgis(
                file_path,
                ingested_table,
                schema="data",
                srid=info["srid"],
                include_geometry=True,
            )
        finally:
            shutil.rmtree(Path(file_path).parent, ignore_errors=True)

        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT pop, name, observed_at, "
                    f"ST_AsText(_geolens_geom), ST_SRID(_geolens_geom) "
                    f"FROM data.{ingested_table} ORDER BY pop"
                )
            )
        ).all()
        assert len(rows) == 3
        assert [r[0] for r in rows] == [10, 20, 30]
        assert rows[0][3] == "POINT(0 0)"
        assert rows[1][3] == "POINT(1 1)"
        assert rows[1][4] == 4326
        assert rows[0][2] is not None  # timestamptz survived
        assert rows[2][3] is None  # NULL geometry row survived

        # gid is a pipeline-grade serial PK (rename_reserved_columns leaves it).
        gid_default = (
            await test_db_session.execute(
                text(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_schema = 'data' AND table_name = :t "
                    "AND column_name = 'gid'"
                ).bindparams(t=ingested_table)
            )
        ).scalar_one()
        assert "nextval" in str(gid_default)

    @pytest.mark.anyio
    async def test_srid_override_stamps_geometry(
        self, test_db_session, ingested_table, tmp_path
    ):
        # Unknown-CRS GeoParquet + user srid_override: geometries must carry
        # the override SRID so add_4326_column's ST_Transform is not a no-op
        # (PR #541 review). run_ogr2ogr receives it as effective_srid.
        from app.processing.ingest.ogr import run_ogr2ogr

        p = tmp_path / "override.parquet"
        _write_geoparquet(p)
        await run_ogr2ogr(
            str(p),
            ingested_table,
            "unused-conn-str",
            source_srid=None,
            geometry_type="Point",
            schema="data",
            effective_srid=2263,
        )
        srid = (
            await test_db_session.execute(
                text(
                    f"SELECT ST_SRID(_geolens_geom) FROM data.{ingested_table} "
                    "WHERE _geolens_geom IS NOT NULL LIMIT 1"
                )
            )
        ).scalar_one()
        assert srid == 2263

    @pytest.mark.anyio
    async def test_uint64_column_survives(
        self, test_db_session, ingested_table, tmp_path
    ):
        # uint64 above bigint range must not fail the batch insert (PR #541
        # review): mapped to numeric.
        p = tmp_path / "u64.parquet"
        big = 2**63 + 11  # > bigint max
        pq.write_table(pa.table({"counter": pa.array([1, big], type=pa.uint64())}), p)
        await load_parquet_to_postgis(
            str(p), ingested_table, schema="data", srid=4326, include_geometry=False
        )
        vals = (
            (
                await test_db_session.execute(
                    text(f"SELECT counter FROM data.{ingested_table} ORDER BY gid")
                )
            )
            .scalars()
            .all()
        )
        assert [int(v) for v in vals] == [1, big]

    @pytest.mark.anyio
    async def test_non_spatial_parquet_loads(
        self, test_db_session, ingested_table, tmp_path
    ):
        p = tmp_path / "plain.parquet"
        _write_plain_parquet(p)  # includes a source column named "gid"
        await load_parquet_to_postgis(
            str(p),
            ingested_table,
            schema="data",
            srid=4326,
            include_geometry=False,
        )
        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT gid_2, label, value FROM data.{ingested_table} "
                    "ORDER BY gid"
                )
            )
        ).all()
        # source "gid" collides with the pipeline serial PK -> lands as gid_2
        assert [tuple(r) for r in rows] == [(1, "x", 1.5), (2, "y", 2.5)]


class TestParquetZGeometry:
    """fix(#641): Z-bearing WKB used to fail INSERT because the staging
    column was declared with a 2D typmod (geometry(Geometry, srid))."""

    @pytest.fixture
    async def z_table(self, test_db_session):
        table_name = f"t_zgeom_{uuid.uuid4().hex[:8]}"
        yield table_name
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
        await test_db_session.commit()

    @pytest.mark.anyio
    async def test_z_wkb_probe_creates_3d_column(
        self, test_db_session, z_table, tmp_path
    ):
        """No declared geometry_types (our exporter's shape) — the first-WKB
        probe must detect Z and the load must succeed with Z preserved."""
        from shapely.geometry import Point

        p = tmp_path / "z.parquet"
        geom = [Point(0, 0, 5).wkb, Point(1, 1, 6.5).wkb]
        pq.write_table(build_geoparquet_table(geom, {"pop": [1, 2]}, ["pop"]), p)

        await load_parquet_to_postgis(
            str(p), z_table, schema="data", srid=4326, include_geometry=True
        )

        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT ST_NDims(_geolens_geom), ST_Z(_geolens_geom) "
                    f"FROM data.{z_table} ORDER BY gid"
                )
            )
        ).all()
        assert [r[0] for r in rows] == [3, 3]
        assert [r[1] for r in rows] == [5.0, 6.5]

    @pytest.mark.anyio
    async def test_declared_z_lifts_mixed_dimensions(
        self, test_db_session, z_table, tmp_path
    ):
        """geometry_types declaring ' Z' + a mixed 2D/3D payload: ST_Force3D
        must lift the 2D row (z=0) instead of failing the batch."""
        from shapely.geometry import Point

        p = tmp_path / "z_mixed.parquet"
        geom = [Point(0, 0, 5).wkb, Point(1, 1).wkb]
        table = build_geoparquet_table(geom, {"pop": [1, 2]}, ["pop"])
        geo = json.loads(table.schema.metadata[b"geo"])
        geo["columns"]["geometry"]["geometry_types"] = ["Point Z"]
        table = table.replace_schema_metadata({b"geo": json.dumps(geo).encode()})
        pq.write_table(table, p)

        await load_parquet_to_postgis(
            str(p), z_table, schema="data", srid=4326, include_geometry=True
        )

        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT ST_NDims(_geolens_geom), ST_Z(_geolens_geom) "
                    f"FROM data.{z_table} ORDER BY gid"
                )
            )
        ).all()
        assert [r[0] for r in rows] == [3, 3]
        assert rows[0][1] == 5.0
        assert rows[1][1] == 0.0  # 2D row lifted by ST_Force3D

    @pytest.mark.anyio
    async def test_2d_file_unchanged(self, test_db_session, z_table, tmp_path):
        """Regression guard: plain 2D files still land in a 2D column."""
        p = tmp_path / "flat.parquet"
        _write_geoparquet(p)

        await load_parquet_to_postgis(
            str(p), z_table, schema="data", srid=4326, include_geometry=True
        )

        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT ST_NDims(_geolens_geom) FROM data.{z_table} "
                    f"WHERE _geolens_geom IS NOT NULL"
                )
            )
        ).all()
        assert rows and all(r[0] == 2 for r in rows)


def test_wkb_has_z_header_sniff():
    """_wkb_has_z reads only the WKB header — both ISO and EWKB flavors."""
    from shapely import to_wkb
    from shapely.geometry import Point

    from app.processing.ingest.parquet import _wkb_has_z

    for flavor in ("iso", "extended"):
        assert _wkb_has_z(to_wkb(Point(0, 0, 1), flavor=flavor)) is True
        assert _wkb_has_z(to_wkb(Point(0, 0), flavor=flavor)) is False
    assert _wkb_has_z(b"") is False


class TestParquetZLateRow:
    """codex P2 round 3 on #646: undeclared geometry_types with a 2D row
    before the Z row — the scan must not stop at the first geometry."""

    @pytest.fixture
    async def late_z_table(self, test_db_session):
        table_name = f"t_zlate_{uuid.uuid4().hex[:8]}"
        yield table_name
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
        await test_db_session.commit()

    @pytest.mark.anyio
    async def test_undeclared_mixed_scans_past_first_2d(
        self, test_db_session, late_z_table, tmp_path
    ):
        from shapely.geometry import Point

        p = tmp_path / "z_late.parquet"
        geom = [Point(0, 0).wkb, Point(1, 1, 7).wkb]
        pq.write_table(build_geoparquet_table(geom, {"pop": [1, 2]}, ["pop"]), p)

        await load_parquet_to_postgis(
            str(p), late_z_table, schema="data", srid=4326, include_geometry=True
        )

        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT ST_NDims(_geolens_geom), ST_Z(_geolens_geom) "
                    f"FROM data.{late_z_table} ORDER BY gid"
                )
            )
        ).all()
        assert [r[0] for r in rows] == [3, 3]
        assert rows[0][1] == 0.0  # leading 2D row lifted by ST_Force3D
        assert rows[1][1] == 7.0
