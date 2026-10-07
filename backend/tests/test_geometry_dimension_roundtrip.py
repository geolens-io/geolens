"""Z and M dimensions survive the GeoParquet export and the CSV WKT imports."""

import shutil
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from httpx import AsyncClient
from shapely import wkb as shapely_wkb
from sqlalchemy import text

from app.processing.ingest import ogr
from app.processing.ingest.tasks_common import _detect_and_override_geometry
from app.processing.ingest.metadata import ensure_geom_column, rename_reserved_columns
from tests.factories import get_user_id
from tests.test_export import _create_dataset

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        shutil.which("ogr2ogr") is None,
        reason="ogr2ogr binary not available on host (runs in backend Docker image / CI)",
    ),
    pytest.mark.requires_ogr2ogr,
]


async def _drop(session, table: str) -> None:
    await session.rollback()
    await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table}"'))
    await session.commit()


async def _export_table(
    session,
    client,
    headers,
    *,
    srid: int,
    geom_sql: str,
    render_sql: str,
    geom_type: str = "GeometryZ",
    attributes: bool = True,
):
    table = f"dim_pq_{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table} (gid serial PRIMARY KEY, "
            f"{'name text, ' if attributes else ''}"
            f"geom geometry({geom_type}, {srid}), "
            "geom_4326 geometry(Geometry, 4326))"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table} ({'name, ' if attributes else ''}"
            f"geom, geom_4326) VALUES "
            f"({'' if not attributes else chr(39) + 'a' + chr(39) + ', '}"
            f"{geom_sql}, {render_sql})"
        )
    )
    await session.commit()
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(
        session,
        created_by=admin_id,
        name="DimExport",
        table_name=table,
        srid=srid,
        geometry_type="Point",
        feature_count=1,
        column_info=[
            {"name": "gid", "type": "integer"},
            *([{"name": "name", "type": "text"}] if attributes else []),
        ],
    )
    resp = await client.get(
        f"/datasets/{ds.id}/export", params={"format": "parquet"}, headers=headers
    )
    assert resp.status_code == 200
    return table, pq.read_table(pa.BufferReader(resp.content))


async def test_parquet_export_keeps_z(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    table, out = await _export_table(
        test_db_session,
        client,
        admin_auth_header,
        srid=4326,
        geom_sql="ST_SetSRID(ST_MakePoint(10, 20, 30), 4326)",
        render_sql="ST_SetSRID(ST_MakePoint(10, 20), 4326)",
    )
    try:
        geom = shapely_wkb.loads(out.column("geometry")[0].as_py())
        assert geom.has_z
        assert list(geom.coords[0]) == [10, 20, 30]
    finally:
        await _drop(test_db_session, table)


async def test_parquet_export_keeps_m(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    table, out = await _export_table(
        test_db_session,
        client,
        admin_auth_header,
        srid=4326,
        geom_sql="ST_SetSRID(ST_MakePointM(10, 20, 7), 4326)",
        render_sql="ST_SetSRID(ST_MakePoint(10, 20), 4326)",
        geom_type="GeometryM",
    )
    try:
        wkb = out.column("geometry")[0].as_py()
        # ISO WKB: type 1001 (POINT M) then x, y, m.
        assert wkb == bytes.fromhex(
            "01d1070000000000000000244000000000000034400000000000001c40"
        )
    finally:
        await _drop(test_db_session, table)


async def test_parquet_export_of_a_geometry_only_table_keeps_z(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    table, out = await _export_table(
        test_db_session,
        client,
        admin_auth_header,
        srid=4326,
        geom_sql="ST_SetSRID(ST_MakePoint(10, 20, 30), 4326)",
        render_sql="ST_SetSRID(ST_MakePoint(10, 20), 4326)",
        attributes=False,
    )
    try:
        assert shapely_wkb.loads(out.column("geometry")[0].as_py()).has_z
    finally:
        await _drop(test_db_session, table)


async def test_parquet_export_reprojects_z_to_4326(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    table, out = await _export_table(
        test_db_session,
        client,
        admin_auth_header,
        srid=3857,
        geom_sql="ST_SetSRID(ST_MakePoint(1113194.9, 2273030.9, 45), 3857)",
        render_sql="ST_SetSRID(ST_MakePoint(10, 20), 4326)",
    )
    try:
        x, y, z = shapely_wkb.loads(out.column("geometry")[0].as_py()).coords[0]
        assert (round(x, 3), round(y, 3), z) == (10.0, 20.0, 45.0)
    finally:
        await _drop(test_db_session, table)


async def _load_wkt_csv(session, tmp_path, header: str, rows: list[str], **override):
    csv = tmp_path / "shapes.csv"
    csv.write_text(header + "\n" + "\n".join(rows) + "\n")
    source = str(csv)
    info = await ogr.run_ogrinfo(source)
    table = f"dim_csv_{uuid.uuid4().hex[:10]}"
    wants_override = bool(override)
    await ogr.run_ogr2ogr(
        source,
        table,
        ogr.build_pg_conn_str(),
        source_srid=info.get("srid"),
        geometry_type=None if wants_override else info.get("geometry_type"),
        schema="data",
        effective_srid=4326,
    )
    if wants_override:
        renames = await rename_reserved_columns(session, table, schema="data")
        await _detect_and_override_geometry(
            session,
            table_name=table,
            user_metadata=override,
            effective_srid=4326,
            renamed_columns=renames,
        )
        await session.commit()
    else:
        await ensure_geom_column(session, table, schema="data")
        await session.commit()
    return table


async def _dims(session, table: str) -> list[tuple[int, str]]:
    rows = await session.execute(
        text(f'SELECT ST_NDims(geom), ST_AsText(geom) FROM "data"."{table}" ORDER BY 2')
    )
    return [tuple(r) for r in rows]


@pytest.mark.parametrize(
    ("wkt", "ndims"),
    [
        ("POINT Z (1 2 3)", 3),
        ("POINT ZM (1 2 3 4)", 4),
        ("POINT M (1 2 3)", 3),
        ("POINT (1 2)", 2),
    ],
)
async def test_selected_wkt_column_keeps_dimensions(
    test_db_session, tmp_path, wkt, ndims
):
    table = await _load_wkt_csv(
        test_db_session,
        tmp_path,
        "id,shape_text",
        [f'1,"{wkt}"'],
        geom_column="shape_text",
    )
    try:
        assert [n for n, _ in await _dims(test_db_session, table)] == [ndims]
    finally:
        await _drop(test_db_session, table)


async def test_selected_reserved_geom_column_is_remapped(test_db_session, tmp_path):
    table = await _load_wkt_csv(
        test_db_session,
        tmp_path,
        "id,geom",
        ['1,"POINT Z (1 2 3)"'],
        geom_column="geom",
    )
    try:
        assert [n for n, _ in await _dims(test_db_session, table)] == [3]
    finally:
        await _drop(test_db_session, table)


async def test_auto_detected_wkt_keeps_z(test_db_session, tmp_path):
    table = await _load_wkt_csv(
        test_db_session, tmp_path, "id,wkt", ['1,"LINESTRING Z (0 0 5, 1 1 6)"']
    )
    try:
        assert [n for n, _ in await _dims(test_db_session, table)] == [3]
    finally:
        await _drop(test_db_session, table)
