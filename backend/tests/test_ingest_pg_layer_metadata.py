"""ogr2ogr imports write no GDAL layer metadata into the database.

GDAL's PostgreSQL driver keeps layer metadata in an ``ogr_system_tables``
schema it creates on a layer's first write. Concurrent first imports into a
database without that schema raced on its CREATE SCHEMA, and every loser
failed. The file-import tests need a real ogr2ogr and the test PostGIS.
"""

import asyncio
import shutil
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from app.processing.ingest.ogr import run_ogr2ogr_service

SOURCE = Path(__file__).parent / "fixtures" / "ingest" / "basic_attrs.geojson"

needs_ogr2ogr = pytest.mark.skipif(
    shutil.which("ogr2ogr") is None,
    reason="ogr2ogr binary not available on host (runs in backend Docker image / CI)",
)


async def _import(table: str) -> None:
    from app.processing.ingest.ogr import build_pg_conn_str, run_ogr2ogr

    await run_ogr2ogr(
        str(SOURCE),
        table,
        build_pg_conn_str(),
        source_srid=4326,
        geometry_type="Point",
        schema="data",
    )


async def _row_count(session, table: str) -> int:
    result = await session.execute(
        text(f"SELECT count(*) FROM data.{table}")  # noqa: S608 - test table
    )
    return result.scalar_one()


async def _drop_tables(session, tables: list[str]) -> None:
    for table in tables:
        await session.execute(text(f"DROP TABLE IF EXISTS data.{table} CASCADE"))
    await session.commit()


@needs_ogr2ogr
@pytest.mark.requires_ogr2ogr
async def test_file_import_records_no_layer_metadata(test_db_session):
    table = f"tst_pgmeta_{uuid.uuid4().hex[:8]}"
    try:
        await _import(table)

        assert await _row_count(test_db_session, table) > 0
        metadata_table = await test_db_session.execute(
            text("SELECT to_regclass('ogr_system_tables.metadata')")
        )
        if metadata_table.scalar_one() is not None:
            rows = await test_db_session.execute(
                text(
                    "SELECT count(*) FROM ogr_system_tables.metadata "
                    "WHERE schema_name = 'data' AND table_name = :t"
                ).bindparams(t=table)
            )
            assert rows.scalar_one() == 0
    finally:
        await _drop_tables(test_db_session, [table])


@needs_ogr2ogr
@pytest.mark.requires_ogr2ogr
async def test_concurrent_first_imports_into_a_fresh_database_all_succeed(
    test_db_session,
):
    await test_db_session.execute(
        text(
            "DROP EVENT TRIGGER IF EXISTS ogr_system_tables_event_trigger_for_metadata"
        )
    )
    await test_db_session.execute(
        text("DROP SCHEMA IF EXISTS ogr_system_tables CASCADE")
    )
    await test_db_session.commit()

    tables = [f"tst_pgrace_{uuid.uuid4().hex[:8]}" for _ in range(4)]
    try:
        results = await asyncio.gather(
            *(_import(table) for table in tables), return_exceptions=True
        )

        assert [r for r in results if isinstance(r, BaseException)] == []
        for table in tables:
            assert await _row_count(test_db_session, table) > 0
    finally:
        await _drop_tables(test_db_session, tables)


async def test_service_import_disables_layer_metadata():
    argv: list[str] = []

    async def _fake_exec(*args, **kwargs):
        argv.extend(args)
        proc = MagicMock()
        proc.returncode = 0
        return proc

    async def _fake_communicate(proc, timeout, tool_name):
        return (b"", b"")

    with (
        patch("asyncio.create_subprocess_exec", side_effect=_fake_exec),
        patch(
            "app.processing.ingest.ogr._communicate_with_timeout",
            new=_fake_communicate,
        ),
    ):
        await run_ogr2ogr_service(
            gdal_source="WFS:https://example.test/wfs",
            layer_name="roads",
            table_name="test_table",
            db_conn_str="PG:dummy",
            service_type="wfs",
            schema="data",
        )

    config = {
        argv[i + 1]: argv[i + 2] for i, arg in enumerate(argv) if arg == "--config"
    }
    assert config["OGR_PG_ENABLE_METADATA"] == "NO"
