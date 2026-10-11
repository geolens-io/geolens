"""Distinct column values serialize for every column type.

Requires the test database with migrations applied.
"""

import datetime
import uuid

import pytest
from sqlalchemy import text

from app.modules.catalog.datasets.domain.column_stats import get_distinct_values
from app.modules.catalog.datasets.domain.schemas import ColumnValuesResponse

TABLE = f"test_colvals_{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def mixed_table(test_db_session):
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{TABLE} (gid serial PRIMARY KEY, tz timestamptz, "
            "ts timestamp, d date, t time, b boolean, u uuid, n numeric, big numeric, "
            "iv interval)"
        )
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{TABLE} (tz, ts, d, t, b, u, n, big, iv) VALUES "
            "('2024-03-01 12:00:00-05', '2024-03-01 17:00:00', '2024-03-01', "
            "'17:30:00', true, '11111111-1111-1111-1111-111111111111', 1.5, 1e309, "
            "'1 day')"
        )
    )
    await test_db_session.commit()
    yield TABLE
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{TABLE}"))
    await test_db_session.commit()


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("tz", "2024-03-01T17:00:00+00:00"),
        ("ts", "2024-03-01 17:00:00"),
        ("d", "2024-03-01"),
        ("t", "17:30:00"),
        ("b", True),
        ("u", "11111111-1111-1111-1111-111111111111"),
        ("n", 1.5),
        ("big", "1.0E+309"),
        ("iv", "1 day"),
    ],
)
async def test_values_serialize_in_tile_form(
    test_db_session, mixed_table, column, expected
):
    values = await get_distinct_values(test_db_session, mixed_table, column)

    assert values == [expected]
    assert type(values[0]) is type(expected)
    dumped = ColumnValuesResponse(values=values, count=1).model_dump()["values"]
    assert dumped == [expected]
    assert type(dumped[0]) is type(expected)


def test_datetime_would_not_serialize():
    with pytest.raises(ValueError):
        ColumnValuesResponse(values=[datetime.datetime.now()], count=1)
