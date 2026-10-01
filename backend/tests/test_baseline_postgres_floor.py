"""Fresh installs and upgrades refuse PostgreSQL servers older than 15.

The baseline checks a fresh install; 0050, the first revision that needs 15,
checks an install already past the baseline."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load(filename: str):
    spec = importlib.util.spec_from_file_location(
        f"floor_{filename.removesuffix('.py')}", _VERSIONS / filename
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MIGRATIONS = pytest.mark.parametrize(
    "migration",
    [_load("0001_baseline.py"), _load("0050_one_active_embedding_backfill.py")],
    ids=["baseline", "0050"],
)

_SERVER_VERSION = "current_setting('server_version_num')::int"


class _GuardCaptured(Exception):
    pass


def _version_guard_sql(monkeypatch, migration) -> str:
    """The first statement the migration emits, which is its version check."""
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
@_MIGRATIONS
@pytest.mark.parametrize("server_version_num", [130012, 140009])
async def test_servers_older_than_15_are_refused(
    migration, server_version_num, monkeypatch, test_db_session
):
    guard = _version_guard_sql(monkeypatch, migration).replace(
        _SERVER_VERSION, str(server_version_num)
    )

    with pytest.raises(DBAPIError, match=r"PostgreSQL 15\+"):
        await test_db_session.execute(text(guard))
    await test_db_session.rollback()


@pytest.mark.anyio
@_MIGRATIONS
@pytest.mark.parametrize("server_version_num", [150000, 180003])
async def test_servers_from_15_are_admitted(
    migration, server_version_num, monkeypatch, test_db_session
):
    guard = _version_guard_sql(monkeypatch, migration).replace(
        _SERVER_VERSION, str(server_version_num)
    )

    await test_db_session.execute(text(guard))
    await test_db_session.rollback()
