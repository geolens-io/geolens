"""Migration 0087: publish keys upgrade cleanly and never downgrade into wider keys."""

import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
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
    / "0087_publish_api_keys.py"
)
_SPEC = importlib.util.spec_from_file_location("migration_0087", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
migration = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migration)

# Shared with the 0086 tests; _run inserts keys and runs a step, then rolls back.
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


@pytest.fixture
async def admin_id(test_db_session):
    user_id = await get_user_id(test_db_session, "admin")
    # The fixture session must not hold locks the migration needs.
    await test_db_session.rollback()
    return user_id


def _key(admin_id, *, active: bool, scope="publish", expires=None) -> dict:
    return {
        "uid": str(admin_id),
        "hash": f"migration-0087-{uuid.uuid4().hex}",
        "active": active,
        "scope": scope,
        "dataset": None,
        "expires": expires,
    }


async def test_the_upgraded_schema_accepts_publish_keys_only_as_named(admin_id):
    def check(conn):
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            with conn.begin_nested():
                conn.execute(
                    _INSERT_KEY, _key(admin_id, active=True, scope="publisher")
                )
        return _scope_check(conn)

    assert "'publish'" in _run(check, keys=[_key(admin_id, active=True)])


async def test_downgrade_refuses_while_an_active_publish_key_exists(admin_id):
    def downgrade(conn):
        with pytest.raises(RuntimeError, match="active publish-scoped API key"):
            migration.downgrade()
        return _scope_check(conn)

    assert "'publish'" in _run(downgrade, keys=[_key(admin_id, active=True)])


async def test_downgrade_then_upgrade_round_trips(admin_id):
    in_a_month = datetime.now(timezone.utc) + timedelta(days=30)
    never_expiring = _key(admin_id, active=False)
    expiring_later = _key(admin_id, active=False, expires=in_a_month)
    full_key = _key(admin_id, active=True, scope="full", expires=in_a_month)
    keys = [never_expiring, expiring_later, full_key]

    def round_trip(conn):
        migration.downgrade()
        assert "'publish'" not in _scope_check(conn)
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            with conn.begin_nested():
                conn.execute(_INSERT_KEY, _key(admin_id, active=False))
        rows = {
            row.key_hash: (row.scope, row.expired, row.expires_at)
            for row in conn.execute(
                text(
                    "SELECT key_hash, scope, expires_at <= now() AS expired, "
                    "expires_at FROM catalog.api_keys WHERE key_hash = ANY(:hashes)"
                ),
                {"hashes": [k["hash"] for k in keys]},
            )
        }
        # Relabelled rows are narrower and expired, so reactivating one revives nothing.
        for key in (never_expiring, expiring_later):
            assert rows[key["hash"]][:2] == ("read_only", True)
        assert rows[full_key["hash"]] == ("full", False, in_a_month)

        migration.upgrade()
        assert "'publish'" in _scope_check(conn)
        conn.execute(_INSERT_KEY, _key(admin_id, active=False))

    _run(round_trip, keys=keys)
