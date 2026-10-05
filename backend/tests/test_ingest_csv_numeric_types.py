"""A CSV import stores numeric columns as numbers, as the preview reports them."""

import shutil
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from app.processing.ingest import ogr

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        shutil.which("ogr2ogr") is None,
        reason="ogr2ogr binary not available on host (runs in backend Docker image / CI)",
    ),
    pytest.mark.requires_ogr2ogr,
]


async def _load(csv: Path) -> str:
    source = str(csv)
    info = await ogr.run_ogrinfo(source)
    table = f"csv_types_{uuid.uuid4().hex[:10]}"
    await ogr.run_ogr2ogr(
        source,
        table,
        ogr.build_pg_conn_str(),
        source_srid=info.get("srid"),
        geometry_type=info.get("geometry_type"),
        schema="data",
    )
    return table


async def _column_types(session, table: str) -> dict[str, str]:
    rows = await session.execute(
        text(
            "SELECT column_name, udt_name FROM information_schema.columns "
            "WHERE table_schema = 'data' AND table_name = :t"
        ),
        {"t": table},
    )
    return {name: udt for name, udt in rows}


async def _drop(session, table: str) -> None:
    await session.rollback()
    await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table}"'))
    await session.commit()


async def test_a_point_csv_types_lat_lon_and_other_numbers(test_db_session, tmp_path):
    csv = tmp_path / "points.csv"
    csv.write_text("name,lat,lon,count,kind\nA,40.5,-74.25,3,x\nB,41.0,-73.5,7,y\n")
    table = await _load(csv)
    try:
        types = await _column_types(test_db_session, table)
        assert types["lat"] == "float8"
        assert types["lon"] == "float8"
        assert types["count"] == "int4"
        assert types["name"] == "varchar"
        assert types["kind"] == "varchar"
    finally:
        await _drop(test_db_session, table)


async def test_a_non_spatial_csv_types_numeric_columns(test_db_session, tmp_path):
    csv = tmp_path / "table.csv"
    csv.write_text("name,price,qty\nA,1.5,3\nB,2.25,4\n")
    table = await _load(csv)
    try:
        types = await _column_types(test_db_session, table)
        assert types["price"] == "float8"
        assert types["qty"] == "int4"
        assert types["name"] == "varchar"
    finally:
        await _drop(test_db_session, table)


async def test_a_non_numeric_value_past_the_sample_window_is_kept(
    test_db_session, tmp_path
):
    csv = tmp_path / "late_text.csv"
    rows = "".join(f"row{i:060d},{i}\n" for i in range(20000))
    csv.write_text(f"name,score\n{rows}last,n/a\n")
    assert csv.stat().st_size > 1_000_000
    table = await _load(csv)
    try:
        types = await _column_types(test_db_session, table)
        assert types["score"] == "varchar"
        last = await test_db_session.scalar(
            text(f'SELECT score FROM "data"."{table}" WHERE name = \'last\'')
        )
        assert last == "n/a"
    finally:
        await _drop(test_db_session, table)


@pytest.mark.parametrize("probe", [ogr.run_ogrinfo, ogr.run_ogrinfo_preview])
async def test_previews_report_the_type_the_import_stores(probe, tmp_path):
    csv = tmp_path / "late_text.csv"
    rows = "".join(f"row{i:060d},{i}\n" for i in range(20000))
    csv.write_text(f"name,score\n{rows}last,n/a\n")
    assert csv.stat().st_size > 1_000_000
    info = await probe(str(csv))
    score = next(c for c in info["columns"] if c["name"] == "score")
    assert score["type"] == "String"
