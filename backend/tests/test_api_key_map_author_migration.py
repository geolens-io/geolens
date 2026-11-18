"""Migration 0104: map_author keys and the map's creating key upgrade cleanly and downgrade only narrower."""

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy
from sqlalchemy import text

from tests import test_api_key_dataset_append_migration as _append_migration_tests
from tests.factories import get_user_id

pytestmark = pytest.mark.anyio

_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0104_map_author_api_keys.py"
)
_SPEC = importlib.util.spec_from_file_location("migration_0104", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
migration = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migration)

_INSERT_KEY = _append_migration_tests._INSERT_KEY
_run = _append_migration_tests._run


def _scope_check(conn) -> str:
    return conn.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'catalog.api_keys'::regclass "
            "AND conname = 'chk_api_keys_scope'"
        )
    ).scalar_one()


def _creator_column(conn):
    return conn.execute(
        text(
            "SELECT data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_schema = 'catalog' "
            "AND table_name = 'maps' AND column_name = 'created_by_api_key_id'"
        )
    ).one_or_none()


def _creator_foreign_keys(conn) -> int:
    return conn.execute(
        text(
            "SELECT count(*) FROM pg_constraint c JOIN pg_attribute a "
            "ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
            "WHERE c.conrelid = 'catalog.maps'::regclass AND c.contype = 'f' "
            "AND a.attname = 'created_by_api_key_id'"
        )
    ).scalar_one()


@pytest.fixture
async def admin_id(test_db_session):
    user_id = await get_user_id(test_db_session, "admin")
    # The fixture session must not hold locks the migration needs.
    await test_db_session.rollback()
    return user_id


def _key(admin_id, *, active: bool, scope="map_author") -> dict:
    return {
        "uid": str(admin_id),
        "hash": f"migration-0104-{uuid.uuid4().hex}",
        "active": active,
        "scope": scope,
        "dataset": None,
        "expires": None,
    }


async def test_the_upgraded_schema_accepts_map_author_keys_and_a_bare_creator_column(
    admin_id,
):
    def check(conn):
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            with conn.begin_nested():
                conn.execute(_INSERT_KEY, _key(admin_id, active=True, scope="author"))
        return _scope_check(conn), _creator_column(conn), _creator_foreign_keys(conn)

    scope_check, column, foreign_keys = _run(check, keys=[_key(admin_id, active=True)])
    assert "'map_author'" in scope_check
    assert tuple(column) == ("uuid", "YES", None)
    assert foreign_keys == 0


async def test_downgrade_refuses_while_an_active_map_author_key_exists(admin_id):
    def downgrade(conn):
        with pytest.raises(RuntimeError, match="active map_author-scoped API key"):
            migration.downgrade()
        return _scope_check(conn), _creator_column(conn)

    scope_check, column = _run(downgrade, keys=[_key(admin_id, active=True)])
    assert "'map_author'" in scope_check
    assert column is not None


async def test_downgrade_then_upgrade_round_trips(admin_id):
    revoked = _key(admin_id, active=False)
    full_key = _key(admin_id, active=True, scope="full")

    def round_trip(conn):
        migration.downgrade()
        assert "'map_author'" not in _scope_check(conn)
        assert _creator_column(conn) is None
        rows = {
            row.key_hash: (row.scope, row.expired)
            for row in conn.execute(
                text(
                    "SELECT key_hash, scope, expires_at <= now() AS expired "
                    "FROM catalog.api_keys WHERE key_hash = ANY(:hashes)"
                ),
                {"hashes": [revoked["hash"], full_key["hash"]]},
            )
        }
        # The relabelled row is narrower and expired, so reactivating it revives nothing.
        assert rows[revoked["hash"]] == ("read_only", True)
        assert rows[full_key["hash"]] == ("full", None)

        migration.upgrade()
        assert "'map_author'" in _scope_check(conn)
        assert _creator_column(conn) is not None
        conn.execute(_INSERT_KEY, _key(admin_id, active=False))

    _run(round_trip, keys=[revoked, full_key])
