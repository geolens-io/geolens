"""Registration creates geom_4326 as a stored generated column.

Registering a large table used to fill ``geom_4326`` with one full-table
UPDATE, which rewrote every row and left the old versions as dead tuples
until vacuum: a multi-million-row table more than doubled on disk, and
registration time was mostly that update. Registration now adds the column
as ``GENERATED ALWAYS AS (...) STORED`` with the same expression the plain
path wrote, so PostgreSQL derives it as rows are written: one table
rewrite with no dead tuples, and later out-of-band writes to ``geom``
stay visible without a refresh.

The assertions below are about what the database holds and what the real
readers return, not about the DDL string: the generation flag, the dead
tuple count after registration, byte equality of the derived values with
the expression the repair path writes, and the feature read at the new
position with no refresh in between. The plain-path control in the
dead-tuple test is what makes the suite fail if the generated flag is
ever ignored: the same table filled by UPDATE reports every row dead.

Every test registers a real table through ``register_existing_table``, so
this module joins ``_TENANCY_GLOBAL_STATE_MODULES`` in ``conftest``:
``grant_reader_access`` mutates cluster-global GRANTs and the file
otherwise flakes under ``-n 4``.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import asyncpg
import pytest
from sqlalchemy import text

from app.modules.catalog.features.service import (
    get_features,
    insert_feature,
    replace_feature,
    update_feature,
)
from app.processing.ingest.metadata import add_4326_column
from app.processing.ingest.metadata_projection import _geom_4326_expr
from tests.factories import get_user_id

pytestmark = [pytest.mark.anyio]

_HERE = (-73.98, 40.75)
_THERE = (2.35, 48.86)


def _bbox(lon: float, lat: float) -> list[float]:
    """A small envelope around one point, for the feature bbox filter."""
    return [lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05]


async def _create_source_table(
    session, table_name: str, *, lon: float, lat: float, rows: int = 1
):
    """A table exactly as an owner would leave it: `geom`, and no `geom_4326`.

    ``rows`` copies of the same point keep the dead-tuple test fast while
    still proving the fill rewrote (or did not rewrite) every row.
    """
    await session.execute(
        text(
            f'CREATE TABLE data."{table_name}" ('
            f"  gid serial PRIMARY KEY,"
            f"  name text,"
            f"  geom geometry(Point, 4326)"
            f")"
        )
    )
    await session.execute(
        text(
            f'INSERT INTO data."{table_name}" (name, geom) '  # noqa: S608
            f"SELECT 'p-' || i, "
            f"       ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) "
            f"FROM generate_series(1, :rows) AS i"
        ),
        {"lon": lon, "lat": lat, "rows": rows},
    )
    await session.commit()


async def _register(session, table_name: str, admin_id: uuid.UUID):
    """Register the table through the real service, and commit."""
    from app.processing.ingest.schemas import RegisterRequest
    from app.processing.ingest.service import register_existing_table

    dataset = await register_existing_table(
        session,
        RegisterRequest(table_name=table_name, title=f"Registered {table_name}"),
        SimpleNamespace(id=admin_id),
    )
    await session.commit()
    await session.refresh(dataset)
    return SimpleNamespace(
        id=dataset.id,
        record_id=dataset.record_id,
        column_info=dataset.column_info,
    )


async def _drop(session, table_name: str) -> None:
    await session.rollback()
    await session.execute(text(f'DROP TABLE IF EXISTS data."{table_name}" CASCADE'))
    await session.commit()


async def _geom_4326_info(session, table_name: str):
    """(is_generated, generation_expression) for the table's geom_4326."""
    await session.rollback()
    row = (
        await session.execute(
            text(
                "SELECT is_generated, generation_expression "
                "FROM information_schema.columns "
                "WHERE table_schema = 'data' AND table_name = :t "
                "AND column_name = 'geom_4326'"
            ),
            {"t": table_name},
        )
    ).first()
    return (row[0], row[1]) if row is not None else (None, None)


async def _has_gist_index(session, table_name: str) -> bool:
    await session.rollback()
    return bool(
        await session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_indexes "
                "WHERE schemaname = 'data' AND tablename = :t "
                "AND indexdef LIKE '%USING gist (geom_4326)%')"
            ),
            {"t": table_name},
        )
    )


async def _dead_tuples(table_name: str) -> int:
    """n_dead_tup as a fresh backend sees it.

    The session that filled the table reads its own n_dead_tup as 0: a
    backend's pending stats only reach shared memory on a flush boundary,
    so the count is read over a second connection, after the fill
    committed. The value is the count, not an estimate fresh from the
    writer's own snapshot.
    """
    from sqlalchemy.engine import make_url

    from app.core.config import settings

    url = make_url(settings.test_database_url)
    conn = await asyncpg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        database=url.database,
    )
    try:
        return await conn.fetchval(
            "SELECT n_dead_tup FROM pg_stat_user_tables "
            "WHERE schemaname = 'data' AND relname = $1",
            table_name,
        )
    finally:
        await conn.close()


async def _flush_stats(session) -> None:
    """Let the writer backend flush its pending stats to shared memory.

    A backend reports its stats at transaction boundaries, throttled to
    one report per interval, so a count read immediately after a commit
    can still be stale. A pause plus a no-op transaction gives the report
    a boundary to land on before the fresh-connection read.
    """
    await asyncio.sleep(1)
    await session.execute(text("SELECT 1"))
    await session.commit()


async def _features_at(session, table_name: str, point: tuple[float, float]) -> int:
    """How many features the REAL feature read returns in a bbox around a point."""
    await session.rollback()
    page = await get_features(
        session,
        table_name,
        limit=50,
        bbox=_bbox(*point),
        has_geometry=True,
    )
    return len(page.rows)


# ---------------------------------------------------------------------------
# Registration creates a generated column
# ---------------------------------------------------------------------------


async def test_registration_creates_a_stored_generated_geom_4326(
    test_db_session,
) -> None:
    """The render column is generated, with the repair path's expression."""
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"gen_reg_{uuid.uuid4().hex[:10]}"
    await _create_source_table(test_db_session, table_name, lon=_HERE[0], lat=_HERE[1])

    try:
        await _register(test_db_session, table_name, admin_id)

        is_generated, expression = await _geom_4326_info(test_db_session, table_name)
        assert is_generated == "ALWAYS"
        # PostgreSQL stores the expression with function names lowercased.
        assert expression.lower() == _geom_4326_expr(4326).lower()
        assert await _has_gist_index(test_db_session, table_name)

        # The derived value is the source geometry itself for 2D 4326.
        assert await test_db_session.scalar(
            text(
                f"SELECT ST_AsBinary(geom_4326) = ST_AsBinary(geom) "
                f'FROM data."{table_name}"'
            ),
        )
        assert await _features_at(test_db_session, table_name, _HERE) == 1
    finally:
        await _drop(test_db_session, table_name)


async def test_registration_leaves_no_dead_tuples(test_db_session) -> None:
    """A generated fill rewrites nothing; the plain fill rewrites every row.

    Autovacuum is off for both tables so the count is the fill's own,
    not whatever a background vacuum has reclaimed since.
    """
    rows = 2000
    generated_table = f"gen_live_{uuid.uuid4().hex[:10]}"
    plain_table = f"gen_dead_{uuid.uuid4().hex[:10]}"
    await _create_source_table(
        test_db_session, generated_table, lon=_HERE[0], lat=_HERE[1], rows=rows
    )
    await _create_source_table(
        test_db_session, plain_table, lon=_HERE[0], lat=_HERE[1], rows=rows
    )
    for table in (generated_table, plain_table):
        await test_db_session.execute(
            text(f'ALTER TABLE data."{table}" SET (autovacuum_enabled = false)')
        )
    await test_db_session.commit()
    await _flush_stats(test_db_session)

    try:
        assert await _dead_tuples(generated_table) == 0
        assert await _dead_tuples(plain_table) == 0

        await add_4326_column(
            test_db_session, generated_table, 4326, schema="data", generated=True
        )
        await test_db_session.commit()
        await _flush_stats(test_db_session)
        assert await _dead_tuples(generated_table) == 0

        await add_4326_column(
            test_db_session, plain_table, 4326, schema="data", generated=False
        )
        await test_db_session.commit()
        await _flush_stats(test_db_session)
        assert await _dead_tuples(plain_table) == rows
    finally:
        await _drop(test_db_session, generated_table)
        await _drop(test_db_session, plain_table)


async def test_generated_values_match_the_plain_expression_for_curved_3d_sources(
    test_db_session,
) -> None:
    """Curved and 3D rows in a projected source derive exactly as before.

    The generation expression linearizes before it reprojects, so an arc
    densifies in the source CRS and Z is stripped; byte equality with the
    repair path's expression is the assertion, not a visual match.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"gen_val_{uuid.uuid4().hex[:10]}"
    await test_db_session.execute(
        text(
            f'CREATE TABLE data."{table_name}" ('
            f"  gid serial PRIMARY KEY,"
            f"  name text,"
            f"  geom geometry(GeometryZ, 3857)"
            f")"
        )
    )
    await test_db_session.execute(
        text(
            f'INSERT INTO data."{table_name}" (name, geom) VALUES '
            f"('point-3d', ST_SetSRID(ST_MakePoint(1000, 2000, 50), 3857)), "
            f"('point-3d-zero', ST_SetSRID(ST_MakePoint(1000, 2000, 0), 3857)), "
            f"('arc-3d', ST_GeomFromEWKT('SRID=3857;CIRCULARSTRING Z"
            f"(1000 2000 10, 1500 2500 10, 2000 2000 10)'))"
        )
    )
    await test_db_session.commit()

    try:
        await _register(test_db_session, table_name, admin_id)

        is_generated, expression = await _geom_4326_info(test_db_session, table_name)
        assert is_generated == "ALWAYS"
        # PostgreSQL stores the expression with function names lowercased.
        assert expression.lower() == _geom_4326_expr(3857).lower()

        expected = _geom_4326_expr(3857)
        assert await test_db_session.scalar(
            text(
                f"SELECT bool_and(ST_AsBinary(geom_4326) = ST_AsBinary({expected})) "
                f'FROM data."{table_name}"'
            ),
        )
        assert await test_db_session.scalar(
            text(f'SELECT bool_and(NOT ST_HasArc(geom_4326)) FROM data."{table_name}"'),
        )
        assert await test_db_session.scalar(
            text(
                f'SELECT bool_and(ST_CoordDim(geom_4326) = 2) FROM data."{table_name}"'
            ),
        )
    finally:
        await _drop(test_db_session, table_name)


# ---------------------------------------------------------------------------
# Tables that already carry a geom_4326 keep working
# ---------------------------------------------------------------------------


async def test_registration_keeps_an_existing_plain_geom_4326(test_db_session) -> None:
    """A plain column the owner already wrote is left alone, not converted.

    Converting it would rewrite the table this change exists to avoid, so
    registration keeps the plain column and its stored values.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"gen_plain_{uuid.uuid4().hex[:10]}"
    await _create_source_table(test_db_session, table_name, lon=_HERE[0], lat=_HERE[1])
    await test_db_session.execute(
        text(
            f'ALTER TABLE data."{table_name}" '
            f"ADD COLUMN geom_4326 geometry(Geometry, 4326)"
        )
    )
    await test_db_session.execute(
        text(f'UPDATE data."{table_name}" SET geom_4326 = geom')
    )
    await test_db_session.commit()

    try:
        await _register(test_db_session, table_name, admin_id)

        is_generated, _ = await _geom_4326_info(test_db_session, table_name)
        assert is_generated == "NEVER"
        assert await test_db_session.scalar(
            text(
                f"SELECT ST_AsBinary(geom_4326) = ST_AsBinary(geom) "
                f'FROM data."{table_name}"'
            ),
        )
        assert await _features_at(test_db_session, table_name, _HERE) == 1
    finally:
        await _drop(test_db_session, table_name)


async def test_registration_accepts_an_existing_generated_geom_4326(
    test_db_session,
) -> None:
    """A table the owner already gave a generated column registers as-is."""
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"gen_byo_{uuid.uuid4().hex[:10]}"
    await test_db_session.execute(
        text(
            f'CREATE TABLE data."{table_name}" ('
            f"  gid serial PRIMARY KEY,"
            f"  name text,"
            f"  geom geometry(Point, 4326),"
            f"  geom_4326 geometry(Geometry, 4326) GENERATED ALWAYS AS "
            f"    (ST_Force2D(ST_CurveToLine(ST_SetSRID(geom, 4326)))) STORED"
            f")"
        )
    )
    await test_db_session.execute(
        text(
            f'INSERT INTO data."{table_name}" (name, geom) '
            f"VALUES ('a', ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))"
        ),
        {"lon": _HERE[0], "lat": _HERE[1]},
    )
    await test_db_session.commit()

    try:
        await _register(test_db_session, table_name, admin_id)

        is_generated, _ = await _geom_4326_info(test_db_session, table_name)
        assert is_generated == "ALWAYS"
        assert await _features_at(test_db_session, table_name, _HERE) == 1
    finally:
        await _drop(test_db_session, table_name)


# ---------------------------------------------------------------------------
# The generated column stays live: out-of-band writes and feature edits
# ---------------------------------------------------------------------------


async def test_an_out_of_band_geometry_update_renders_without_a_refresh(
    test_db_session,
) -> None:
    """`UPDATE ... SET geom` moves the feature, and the render column follows.

    The generated column re-derives itself on the owner's write, so both
    readers show the NEW position with no refresh in between. This is the
    mirror of the rederive suite's load-bearing case, which asserts the
    plain column stays stale until refresh.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"gen_oob_{uuid.uuid4().hex[:10]}"
    await _create_source_table(test_db_session, table_name, lon=_HERE[0], lat=_HERE[1])

    try:
        await _register(test_db_session, table_name, admin_id)

        await test_db_session.execute(
            text(
                f'UPDATE data."{table_name}" '  # noqa: S608
                f"SET geom = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)"
            ),
            {"lon": _THERE[0], "lat": _THERE[1]},
        )
        await test_db_session.commit()

        assert await _features_at(test_db_session, table_name, _HERE) == 0
        assert await _features_at(test_db_session, table_name, _THERE) == 1
    finally:
        await _drop(test_db_session, table_name)


async def test_feature_edits_work_on_a_generated_geom_4326(test_db_session) -> None:
    """Insert, replace and update write geom only; the column derives itself.

    A direct write to a generated column fails at parse time, so the edit
    paths skip it when it is generated. The derived value is asserted
    after each edit, not just the absence of an error.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"gen_edt_{uuid.uuid4().hex[:10]}"
    await _create_source_table(test_db_session, table_name, lon=_HERE[0], lat=_HERE[1])

    try:
        dataset = await _register(test_db_session, table_name, admin_id)
        columns = dataset.column_info

        inserted = await insert_feature(
            test_db_session,
            table_name,
            {"type": "Point", "coordinates": [_THERE[0], _THERE[1]]},
            {"name": "inserted"},
            columns,
            "Point",
            4326,
        )
        await test_db_session.commit()
        assert await test_db_session.scalar(
            text(
                f"SELECT ST_AsBinary(geom_4326) = ST_AsBinary("
                f"  ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) "
                f'FROM data."{table_name}" WHERE gid = :gid'
            ),
            {"lon": _THERE[0], "lat": _THERE[1], "gid": inserted["gid"]},
        )

        replaced = await replace_feature(
            test_db_session,
            table_name,
            inserted["gid"],
            {"type": "Point", "coordinates": [_HERE[0], _HERE[1]]},
            {"name": "replaced"},
            columns,
            "Point",
            4326,
        )
        await test_db_session.commit()
        assert replaced.feature["geometry"]["coordinates"] == [_HERE[0], _HERE[1]]

        await update_feature(
            test_db_session,
            table_name,
            inserted["gid"],
            {"type": "Point", "coordinates": [_THERE[0], _THERE[1]]},
            None,
            columns,
            "Point",
            4326,
        )
        await test_db_session.commit()
        assert await test_db_session.scalar(
            text(
                f"SELECT ST_AsBinary(geom_4326) = ST_AsBinary("
                f"  ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) "
                f'FROM data."{table_name}" WHERE gid = :gid'
            ),
            {"lon": _THERE[0], "lat": _THERE[1], "gid": inserted["gid"]},
        )
        assert await _features_at(test_db_session, table_name, _THERE) == 1
    finally:
        await _drop(test_db_session, table_name)
