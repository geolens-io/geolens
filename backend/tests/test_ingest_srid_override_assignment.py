"""An accepted SRID override is the CRS a GDAL-loaded table's geometries carry."""

import shutil
import uuid
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import text

from app.processing.ingest.metadata import add_4326_column, ensure_geom_column
from app.processing.ingest import ogr

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        shutil.which("ogr2ogr") is None,
        reason="ogr2ogr binary not available on host (runs in backend Docker image / CI)",
    ),
    pytest.mark.requires_ogr2ogr,
]

FIXTURES = Path(__file__).parent / "fixtures" / "ingest"


def _shapefile_without_prj(tmp_path: Path) -> str:
    """A zipped shapefile that declares no CRS at all."""
    out = tmp_path / "no_crs.zip"
    with (
        zipfile.ZipFile(FIXTURES / "dbf_collision.zip") as src,
        zipfile.ZipFile(out, "w") as dst,
    ):
        for name in src.namelist():
            if not name.endswith(".prj"):
                dst.writestr(name, src.read(name))
    return str(out)


async def _load(source: str, *, effective_srid: int) -> tuple[str, int | None]:
    info = await ogr.run_ogrinfo(source)
    table = f"srid_override_{uuid.uuid4().hex[:10]}"
    await ogr.run_ogr2ogr(
        source,
        table,
        # Through the module: the test fixture points this at the test database.
        ogr.build_pg_conn_str(),
        source_srid=info.get("srid"),
        geometry_type=info.get("geometry_type"),
        schema="data",
        effective_srid=effective_srid,
    )
    return table, info.get("srid")


async def _stored_srids(session, table: str) -> set[int]:
    rows = await session.execute(
        text(f'SELECT DISTINCT ST_SRID(_geolens_geom) FROM "data"."{table}"')
    )
    return {row[0] for row in rows}


async def _drop(session, table: str) -> None:
    await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table}"'))
    await session.commit()


async def test_a_shapefile_with_no_crs_takes_the_override(test_db_session, tmp_path):
    table, detected = await _load(_shapefile_without_prj(tmp_path), effective_srid=3857)
    try:
        assert detected is None
        assert await _stored_srids(test_db_session, table) == {3857}
        # The 4326 render column can be derived, which SRID 0 refuses.
        assert await ensure_geom_column(test_db_session, table)
        await add_4326_column(test_db_session, table, 3857)
        missing = await test_db_session.scalar(
            text(f'SELECT count(*) FROM "data"."{table}" WHERE geom_4326 IS NULL')
        )
        assert missing == 0
    finally:
        await test_db_session.rollback()
        await _drop(test_db_session, table)


async def test_an_override_replaces_a_declared_crs_without_moving_coordinates(
    test_db_session,
):
    source = str(FIXTURES / "basic_attrs.geojson")
    table, detected = await _load(source, effective_srid=3857)
    try:
        assert detected == 4326
        assert await _stored_srids(test_db_session, table) == {3857}
        paris = await test_db_session.execute(
            text(
                f"SELECT ST_X(ST_GeometryN(_geolens_geom, 1)), "
                f'ST_Y(ST_GeometryN(_geolens_geom, 1)) FROM "data"."{table}" '
                "WHERE name = 'Paris'"
            )
        )
        assert tuple(paris.one()) == pytest.approx((2.3522, 48.8566))
    finally:
        await _drop(test_db_session, table)


async def test_without_an_override_the_declared_crs_stays(test_db_session):
    source = str(FIXTURES / "basic_attrs.geojson")
    table, detected = await _load(source, effective_srid=4326)
    try:
        assert detected == 4326
        assert await _stored_srids(test_db_session, table) == {4326}
    finally:
        await _drop(test_db_session, table)
