"""A source mixing geometry kinds is staged under the generic geometry type.

Runs the real ogr2ogr load and the staging pipeline that feeds the catalog, so
it needs the ogr2ogr binary; hosts without it skip.
"""

import shutil
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

pytestmark = [
    pytest.mark.skipif(
        shutil.which("ogr2ogr") is None,
        reason="ogr2ogr binary not available on host (runs in backend Docker image / CI)",
    ),
    pytest.mark.requires_ogr2ogr,
    pytest.mark.anyio,
]

FIXTURE = Path(__file__).parent / "fixtures" / "ingest" / "mixed_geometry.geojson"


async def test_a_mixed_geojson_is_staged_as_geometry(test_db_session) -> None:
    from app.processing.ingest.ogr import build_pg_conn_str, run_ogr2ogr, run_ogrinfo
    from app.processing.ingest.tasks_staging import _run_staging_pipeline

    table = f"mixed_{uuid.uuid4().hex[:8]}"
    info = await run_ogrinfo(str(FIXTURE))
    await run_ogr2ogr(
        str(FIXTURE),
        table,
        build_pg_conn_str(),
        source_srid=info.get("srid"),
        geometry_type=info.get("geometry_type"),
        schema="data",
    )
    try:
        staged = await _run_staging_pipeline(
            test_db_session,
            table_name=table,
            has_geometry=True,
            effective_srid=info.get("srid") or 4326,
        )

        assert staged.metadata["geometry_type"] == "GEOMETRY"
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(
            text(f"DROP TABLE IF EXISTS data.{table} CASCADE")
        )
        await test_db_session.commit()
