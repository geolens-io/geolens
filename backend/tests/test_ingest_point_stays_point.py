"""A file layer declared Point is staged as Point; every other type keeps its multi form."""

import json
import shutil
import subprocess
import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.processing.ingest.ogr import (
    build_pg_conn_str,
    declares_single_point,
    run_ogr2ogr,
    run_ogrinfo,
)


@pytest.mark.parametrize(
    ("declared", "single"),
    [
        ("Point", True),
        ("PointZ", True),
        ("PointM", True),
        ("PointZM", True),
        ("3D Point", True),
        ("Measured Point", True),
        ("3D Measured Point", True),
        ("MultiPoint", False),
        ("Multi Point", False),
        ("MultiPointZ", False),
        ("3D Multi Point", False),
        ("Unknown (any)", False),
        ("Geometry", False),
        ("LineString", False),
        ("Polygon", False),
        ("", False),
        (None, False),
    ],
)
def test_declares_single_point(declared, single):
    assert declares_single_point(declared) is single


def _feature(geometry: dict) -> dict:
    return {"type": "Feature", "properties": {"a": 1}, "geometry": geometry}


POINT = {"type": "Point", "coordinates": [1, 2]}
POINT_Z = {"type": "Point", "coordinates": [1, 2, 3]}
MULTIPOINT = {"type": "MultiPoint", "coordinates": [[1, 2], [3, 4]]}
LINE = {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}


def _geojson(tmp_path, *geometries: dict):
    path = tmp_path / "layer.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [_feature(g) for g in geometries],
            }
        )
    )
    return path


def _ogr(*args: str) -> None:
    subprocess.run(args, check=True, capture_output=True)


@pytest.mark.anyio
@pytest.mark.requires_ogr2ogr
@pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="ogr2ogr not available")
class TestStagedGeometryColumn:
    async def _stage(self, session, path, **kwargs) -> str:
        info = await run_ogrinfo(str(path), **kwargs)
        table = f"tst_pt_{uuid.uuid4().hex[:8]}"
        await run_ogr2ogr(
            str(path),
            table,
            build_pg_conn_str(),
            source_srid=info.get("srid"),
            geometry_type=info.get("geometry_type"),
            layer_name=info.get("layer_name"),
            schema="data",
        )
        self._tables.append(table)
        result = await session.execute(
            text(
                "SELECT format_type(a.atttypid, a.atttypmod) "
                "FROM pg_attribute a WHERE a.attrelid = CAST(:t AS regclass) "
                "AND a.attname = '_geolens_geom'"
            ),
            {"t": f"data.{table}"},
        )
        # "geometry(MultiPoint,4326)" -> "MULTIPOINT"
        return result.scalar_one().split("(")[1].split(",")[0].upper()

    @pytest.fixture(autouse=True)
    async def _cleanup(self, test_db_session, monkeypatch):
        # ogr2ogr opens its own connection from settings; aim it at the test
        # database the session reads.
        monkeypatch.setattr(settings, "postgres_db", settings.postgres_db_test)
        self._tables: list[str] = []
        yield
        await test_db_session.rollback()
        for table in self._tables:
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table} CASCADE")
            )
        await test_db_session.commit()

    async def test_geojson_points_stay_point(self, test_db_session, tmp_path):
        path = _geojson(tmp_path, POINT, POINT)
        assert await self._stage(test_db_session, path) == "POINT"

    async def test_point_z_stays_point(self, test_db_session, tmp_path):
        path = _geojson(tmp_path, POINT_Z)
        assert await self._stage(test_db_session, path) == "POINT"

    async def test_shapefile_points_stay_point(self, test_db_session, tmp_path):
        shp = tmp_path / "pts.shp"
        _ogr(
            "ogr2ogr", "-f", "ESRI Shapefile", str(shp), str(_geojson(tmp_path, POINT))
        )
        assert await self._stage(test_db_session, shp) == "POINT"

    async def test_geopackage_points_stay_point(self, test_db_session, tmp_path):
        gpkg = tmp_path / "pts.gpkg"
        _ogr("ogr2ogr", "-f", "GPKG", str(gpkg), str(_geojson(tmp_path, POINT)))
        assert await self._stage(test_db_session, gpkg) == "POINT"

    async def test_multipoint_layer_stays_multi(self, test_db_session, tmp_path):
        path = _geojson(tmp_path, MULTIPOINT)
        assert await self._stage(test_db_session, path) == "MULTIPOINT"

    async def test_mixed_geojson_keeps_generic_column(self, test_db_session, tmp_path):
        path = _geojson(tmp_path, POINT, MULTIPOINT)
        assert await self._stage(test_db_session, path) == "GEOMETRY"

    async def test_lines_are_still_promoted(self, test_db_session, tmp_path):
        path = _geojson(tmp_path, LINE)
        assert await self._stage(test_db_session, path) == "MULTILINESTRING"

    async def test_point_header_over_multipoint_rows_falls_back(
        self, test_db_session, tmp_path
    ):
        """A GeoPackage declaring Point over a MultiPoint row still imports, as multi."""
        gpkg = tmp_path / "hdr.gpkg"
        _ogr(
            "ogr2ogr",
            "-f",
            "GPKG",
            str(gpkg),
            str(_geojson(tmp_path, POINT)),
            "-nln",
            "t",
        )
        _ogr(
            "ogrinfo",
            str(gpkg),
            "-dialect",
            "SQLite",
            "-sql",
            "INSERT INTO t(geom, a) VALUES "
            "(GeomFromText('MULTIPOINT((1 2),(3 4))', 4326), 2)",
        )
        info = await run_ogrinfo(str(gpkg))
        assert declares_single_point(info["geometry_type"])
        assert await self._stage(test_db_session, gpkg) == "MULTIPOINT"
