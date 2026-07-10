"""fix(#435): a database failure must not render as a valid dataset with zero rows.

`get_dataset_rows()` wrapped its query in `except Exception` and returned an empty
page for *every* failure — connection loss, statement timeout, permission failure,
serialization error. A broken data table looked identical to an empty one, which hid
ingest corruption and infrastructure incidents from users and from health monitoring.

The one case that legitimately degrades to an empty page is an absent table: raster
and VRT datasets carry a synthetic `table_name` with no PostGIS table behind it, and
the rows endpoint is generic across dataset types.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db.sqlstate import BAD_QUERY_INPUT, TABLE_ABSENT, is_operational, sqlstate
from app.modules.catalog.datasets.domain.service import get_dataset_rows


class _FakeOrig:
    def __init__(self, code: str | None) -> None:
        self.sqlstate = code


def _dbapi_error(code: str | None) -> DBAPIError:
    return DBAPIError("SELECT 1", {}, _FakeOrig(code))


def test_sqlstate_reads_asyncpg_code() -> None:
    assert sqlstate(_dbapi_error("42P01")) == "42P01"


def test_sqlstate_none_when_driver_gave_no_code() -> None:
    assert sqlstate(_dbapi_error(None)) is None


@pytest.mark.parametrize(
    "code",
    [
        "08006",  # connection_failure
        "08003",  # connection_does_not_exist
        "40001",  # serialization_failure
        "40P01",  # deadlock_detected
        "53300",  # too_many_connections
        "57014",  # query_canceled — statement timeout
        "58030",  # io_error
        None,  # driver raised before the server answered
    ],
)
def test_operational_errors_are_retryable(code) -> None:
    assert is_operational(_dbapi_error(code)) is True


@pytest.mark.parametrize(
    "code",
    [
        "23505",  # unique_violation — a conflict, not an outage
        "42P01",  # undefined_table
        "42703",  # undefined_column
        "42501",  # insufficient_privilege
        "22P02",  # invalid_text_representation
    ],
)
def test_request_shaped_errors_are_not_retryable(code) -> None:
    assert is_operational(_dbapi_error(code)) is False


def test_sqlstate_sets_do_not_overlap() -> None:
    assert not (TABLE_ABSENT & BAD_QUERY_INPUT)


async def test_absent_table_still_yields_an_empty_page(test_db_session) -> None:
    """Raster and VRT datasets have no data table; the endpoint must stay generic."""
    rows, total, columns, cursor = await get_dataset_rows(
        test_db_session, "raster_0123456789abcdef", column_info=[]
    )

    assert rows == []
    assert total == 0
    assert cursor is None


async def test_absent_table_leaves_the_session_usable(test_db_session) -> None:
    """Degrading to an empty page must not strand the session in a failed transaction.

    Postgres aborts the transaction on `undefined_table`, so every later statement on
    that session would raise `InFailedSqlTransaction` until someone rolled back.
    """
    await get_dataset_rows(test_db_session, "raster_0123456789abcdef", column_info=[])

    result = await test_db_session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1


@pytest.mark.parametrize(
    "code",
    ["57014", "08006", "40001"],
    ids=["statement-timeout", "connection-failure", "serialization-failure"],
)
async def test_operational_failure_propagates(
    test_db_session, monkeypatch, code
) -> None:
    """An operational failure reaches the caller rather than becoming `([], 0)`."""

    async def _boom(*args, **kwargs):
        raise _dbapi_error(code)

    monkeypatch.setattr(test_db_session, "execute", _boom)

    with pytest.raises(DBAPIError):
        await get_dataset_rows(test_db_session, "some_table", column_info=[])


async def test_permission_failure_propagates(test_db_session, monkeypatch) -> None:
    async def _boom(*args, **kwargs):
        raise _dbapi_error("42501")

    monkeypatch.setattr(test_db_session, "execute", _boom)

    with pytest.raises(DBAPIError):
        await get_dataset_rows(test_db_session, "some_table", column_info=[])
