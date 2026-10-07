"""Shapefiles that declare a code page, and ones zipped inside a single folder."""

import json
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import text

from app.processing.ingest import ogr
from app.processing.ingest.shapefile_source import declares_dbf_encoding

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        shutil.which("ogr2ogr") is None,
        reason="ogr2ogr binary not available on host (runs in backend Docker image / CI)",
    ),
    pytest.mark.requires_ogr2ogr,
]

NAME = "Café"


def _shapefile(tmp_path: Path, *, encoding: str | None) -> Path:
    """One point whose text attribute is NAME, stored in ``encoding``."""
    src = tmp_path / "src.geojson"
    src.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": NAME},
                        "geometry": {"type": "Point", "coordinates": [1, 2]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "shp"
    subprocess.run(
        ["ogr2ogr", "-f", "ESRI Shapefile", str(out), str(src), "-nln", "t"]
        + (["-lco", f"ENCODING={encoding}"] if encoding else ["-lco", "ENCODING="]),
        check=True,
        capture_output=True,
    )
    return out


def _zip(shp_dir: Path, dest: Path, *, folder: str | None) -> str:
    with zipfile.ZipFile(dest, "w") as archive:
        for member in sorted(shp_dir.iterdir()):
            archive.write(member, f"{folder}/{member.name}" if folder else member.name)
    return str(dest)


async def _load(source: str) -> str:
    info = await ogr.run_ogrinfo(source)
    table = f"shp_enc_{uuid.uuid4().hex[:10]}"
    await ogr.run_ogr2ogr(
        source,
        table,
        ogr.build_pg_conn_str(),
        source_srid=info.get("srid"),
        geometry_type=info.get("geometry_type"),
        schema="data",
    )
    return table


async def _names(session, table: str) -> list[str]:
    rows = await session.execute(text(f'SELECT name FROM "data"."{table}"'))
    return [row[0] for row in rows]


async def _drop(session, table: str) -> None:
    await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table}"'))
    await session.commit()


async def test_a_declared_cp1252_shapefile_loads_as_utf8(test_db_session, tmp_path):
    source = _zip(
        _shapefile(tmp_path, encoding="CP1252"), tmp_path / "a.zip", folder=None
    )
    table = await _load(source)
    try:
        assert await _names(test_db_session, table) == [NAME]
    finally:
        await _drop(test_db_session, table)


async def test_an_undeclared_utf8_shapefile_still_loads(test_db_session, tmp_path):
    shp = _shapefile(tmp_path, encoding="UTF-8")
    (shp / "t.cpg").unlink()
    table = await _load(_zip(shp, tmp_path / "a.zip", folder=None))
    try:
        assert await _names(test_db_session, table) == [NAME]
    finally:
        await _drop(test_db_session, table)


async def test_a_single_folder_shapefile_zip_previews_and_loads(
    test_db_session, tmp_path
):
    source = _zip(
        _shapefile(tmp_path, encoding="CP1252"), tmp_path / "a.zip", folder="shape"
    )
    preview = await ogr.run_ogrinfo_preview(source)
    assert preview["sample_rows"] == [{"name": NAME}]
    table = await _load(source)
    try:
        assert await _names(test_db_session, table) == [NAME]
    finally:
        await _drop(test_db_session, table)


def test_zip_with_root_files_or_several_folders_is_not_descended(tmp_path):
    shp = _shapefile(tmp_path, encoding="CP1252")
    root = _zip(shp, tmp_path / "root.zip", folder=None)
    assert ogr._resolve_source_path(root) == f"/vsizip/{root}"
    many = tmp_path / "many.zip"
    with zipfile.ZipFile(many, "w") as archive:
        archive.writestr("a/x.txt", "x")
        archive.writestr("b/y.txt", "y")
    assert ogr._resolve_source_path(str(many)) == f"/vsizip/{many}"
    gdb = tmp_path / "gdb.zip"
    with zipfile.ZipFile(gdb, "w") as archive:
        archive.writestr("d.gdb/a00000001.gdbtable", "x")
    assert ogr._resolve_source_path(str(gdb)) == f"/vsizip/{gdb}"


async def test_macos_metadata_does_not_count_as_a_declared_encoding(
    test_db_session, tmp_path
):
    shp = _shapefile(tmp_path, encoding="UTF-8")
    (shp / "t.cpg").unlink()
    source = tmp_path / "a.zip"
    with zipfile.ZipFile(source, "w") as archive:
        for member in sorted(shp.iterdir()):
            archive.write(member, member.name)
        archive.writestr("__MACOSX/._t.dbf", b"\x00" * 29 + b"\x57" + b"\x00" * 2)
    assert not declares_dbf_encoding(str(source))
    table = await _load(str(source))
    try:
        assert await _names(test_db_session, table) == [NAME]
    finally:
        await _drop(test_db_session, table)


async def test_a_csv_in_a_single_folder_zip_keeps_its_z_values(
    test_db_session, tmp_path
):
    source = tmp_path / "c.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("data/c.csv", 'id,wkt\n1,"POINT Z (1 2 3)"\n')
    table = await _load(str(source))
    try:
        ndims = await test_db_session.scalar(
            text(f'SELECT ST_NDims(_geolens_geom) FROM "data"."{table}"')
        )
        assert ndims == 3
    finally:
        await _drop(test_db_session, table)
