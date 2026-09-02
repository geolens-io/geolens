"""fix(#1778): the row browser must survive a column named after a SQL keyword.

``get_dataset_rows`` interpolated column identifiers bare, so ``SELECT gid, desc
FROM data.x`` was a PostgreSQL syntax error (42601). 42601 is in none of the
sqlstate sets ``get_dataset_rows`` degrades on, so the endpoint 5xx'd for that
dataset permanently -- for anonymous callers on a public dataset too. Nothing
renames SQL keywords on ingest: ``rename_reserved_columns`` only touches
gid/geom/geometry/geom_4326/fid/ogc_fid, and ``desc``/``order``/``user`` are
routine ogr2ogr output from DBF fields.

The same dataset reads fine through /features, which quotes its identifiers,
so before this fix the failure looked like data corruption rather than quoting.

Requires the Docker test database.
"""

import uuid

import pytest
from sqlalchemy import text

from app.modules.catalog.datasets.domain.service import get_dataset_rows

pytestmark = pytest.mark.anyio

# Every one of these is a reserved word in PostgreSQL and every one survives
# ogr2ogr's DBF laundering as a plain lowercase identifier.
RESERVED_COLUMNS = ["desc", "order", "user", "group", "end", "to"]


async def _make_table(session) -> str:
    table = f"rows_1778_{uuid.uuid4().hex[:10]}"
    cols = ", ".join(f'"{name}" text' for name in RESERVED_COLUMNS)
    await session.execute(
        text(
            f"CREATE TABLE data.{table} ("
            "gid serial PRIMARY KEY, geom_4326 geometry(Point, 4326), "
            f"{cols})"
        )
    )
    values = ", ".join(f":v{i}" for i in range(len(RESERVED_COLUMNS)))
    quoted = ", ".join(f'"{name}"' for name in RESERVED_COLUMNS)
    await session.execute(
        text(
            f"INSERT INTO data.{table} (geom_4326, {quoted}) VALUES "
            f"(ST_SetSRID(ST_MakePoint(1, 2), 4326), {values})"
        ).bindparams(
            **{f"v{i}": f"value-{name}" for i, name in enumerate(RESERVED_COLUMNS)}
        )
    )
    await session.commit()
    return table


def _column_info() -> list[dict]:
    return [
        {"name": "gid", "type": "integer", "ordinal_position": 1},
        {"name": "geom_4326", "type": "USER-DEFINED", "ordinal_position": 2},
        *(
            {"name": name, "type": "text", "ordinal_position": i}
            for i, name in enumerate(RESERVED_COLUMNS, start=3)
        ),
    ]


async def test_reserved_word_columns_are_projected(test_db_session) -> None:
    """The page renders instead of raising a 42601 syntax error."""
    table = await _make_table(test_db_session)
    try:
        rows, _total, _cols, _cursor = await get_dataset_rows(
            test_db_session, table, column_info=_column_info()
        )
    finally:
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
        await test_db_session.commit()

    assert len(rows) == 1
    for name in RESERVED_COLUMNS:
        assert rows[0][name] == f"value-{name}"


async def test_reserved_word_column_filter_matches(test_db_session) -> None:
    """`filter[desc]=...` composes into the ILIKE clause without a syntax error."""
    table = await _make_table(test_db_session)
    try:
        matched, _total, _cols, _cursor = await get_dataset_rows(
            test_db_session,
            table,
            column_info=_column_info(),
            filters={"desc": "value-desc"},
        )
        missed, _total, _cols, _cursor = await get_dataset_rows(
            test_db_session,
            table,
            column_info=_column_info(),
            filters={"desc": "no-such-value"},
        )
    finally:
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
        await test_db_session.commit()

    assert len(matched) == 1
    assert missed == []
