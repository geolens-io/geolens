"""The baseline migration refuses PostgreSQL servers older than 15."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0001_baseline.py"
)
_SPEC = importlib.util.spec_from_file_location("migration_0001_floor", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
migration = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migration)

_SERVER_VERSION = "current_setting('server_version_num')::int"


class _GuardCaptured(Exception):
    pass


def _version_guard_sql(monkeypatch) -> str:
    """The first statement the baseline emits, which is its version check."""
    statements: list[str] = []

    def capture(sql, *args, **kwargs):
        statements.append(str(sql))
        raise _GuardCaptured

    monkeypatch.setattr(migration.op, "execute", capture)
    with pytest.raises(_GuardCaptured):
        migration.upgrade()
    assert _SERVER_VERSION in statements[0]
    return statements[0]


@pytest.mark.anyio
@pytest.mark.parametrize("server_version_num", [130012, 140009])
async def test_servers_older_than_15_are_refused(
    server_version_num, monkeypatch, test_db_session
):
    guard = _version_guard_sql(monkeypatch).replace(
        _SERVER_VERSION, str(server_version_num)
    )

    with pytest.raises(DBAPIError, match=r"PostgreSQL 15\+"):
        await test_db_session.execute(text(guard))
    await test_db_session.rollback()


@pytest.mark.anyio
@pytest.mark.parametrize("server_version_num", [150000, 180003])
async def test_servers_from_15_are_admitted(
    server_version_num, monkeypatch, test_db_session
):
    guard = _version_guard_sql(monkeypatch).replace(
        _SERVER_VERSION, str(server_version_num)
    )

    await test_db_session.execute(text(guard))
    await test_db_session.rollback()
