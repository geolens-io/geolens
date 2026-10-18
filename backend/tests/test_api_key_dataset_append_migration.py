"""Migration 0086: append-only dataset keys upgrade cleanly and never downgrade into wider keys."""

import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.core.config import settings
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0086_dataset_append_api_keys.py"
)
_SPEC = importlib.util.spec_from_file_location("migration_0086", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
migration = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migration)

_INSERT_KEY = text(
    "INSERT INTO catalog.api_keys "
    "(user_id, key_hash, name, is_active, scope, dataset_id, key_epoch, expires_at) "
    "SELECT :uid, :hash, 'migration fixture', :active, :scope, :dataset, "
    "u.key_epoch, :expires FROM catalog.users u WHERE u.id = :uid"
)


def _constraints(conn) -> dict[str, str]:
    return dict(
        conn.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'catalog.api_keys'::regclass AND contype = 'c'"
            )
        ).all()
    )


@pytest.fixture
async def fixture_rows(test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=admin_id)
    ids = (admin_id, dataset.id, dataset.record_id)
    # The fixture session must not hold locks the migration needs.
    await test_db_session.rollback()
    yield ids
    await test_db_session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"), {"id": ids[2]}
    )
    await test_db_session.commit()


def _run(fn, *, keys: list[dict]) -> object:
    """Insert ``keys`` and run ``fn`` in one transaction that is always rolled back."""
    engine = sqlalchemy.create_engine(settings.test_database_url_sync)
    try:
        with engine.connect() as conn:
            try:
                for key in keys:
                    conn.execute(_INSERT_KEY, key)
                with Operations.context(MigrationContext.configure(conn)):
                    return fn(conn)
            finally:
                conn.rollback()
    finally:
        engine.dispose()


def _key(admin_id, dataset_id, *, active: bool, scope="dataset_append") -> dict:
    return {
        "uid": str(admin_id),
        "hash": f"migration-0086-{uuid.uuid4().hex}",
        "active": active,
        "scope": scope,
        "dataset": str(dataset_id) if scope.startswith("dataset_") else None,
        "expires": None,
    }


def _insert_refused(conn, key: dict) -> None:
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        with conn.begin_nested():
            conn.execute(_INSERT_KEY, key)


async def test_the_upgraded_schema_binds_append_keys(fixture_rows):
    admin_id, dataset_id, _ = fixture_rows

    def check(conn):
        _insert_refused(
            conn, _key(admin_id, dataset_id, active=True) | {"dataset": None}
        )
        _insert_refused(
            conn, _key(admin_id, dataset_id, active=True, scope="dataset_other")
        )

    _run(check, keys=[_key(admin_id, dataset_id, active=True)])


async def test_downgrade_refuses_while_an_active_append_key_exists(fixture_rows):
    admin_id, dataset_id, _ = fixture_rows

    def downgrade(conn):
        with pytest.raises(RuntimeError, match="ACTIVE catalog.api_keys"):
            migration.downgrade()
        return _constraints(conn)["chk_api_keys_scope"]

    assert "dataset_append" in _run(
        downgrade, keys=[_key(admin_id, dataset_id, active=True)]
    )


async def test_downgrade_then_upgrade_round_trips(fixture_rows):
    admin_id, dataset_id, _ = fixture_rows
    never_expiring = _key(admin_id, dataset_id, active=False)
    expiring_later = _key(admin_id, dataset_id, active=False) | {
        "expires": datetime.now(timezone.utc) + timedelta(days=30)
    }
    expired = _key(admin_id, dataset_id, active=False) | {
        "expires": datetime(2026, 1, 1, tzinfo=timezone.utc)
    }
    write_key = _key(admin_id, dataset_id, active=True, scope="dataset_write") | {
        "expires": datetime.now(timezone.utc) + timedelta(days=30)
    }
    keys = [never_expiring, expiring_later, expired, write_key]

    def round_trip(conn):
        migration.downgrade()
        assert "dataset_append" not in str(_constraints(conn))
        _insert_refused(conn, _key(admin_id, dataset_id, active=False))
        rows = {
            row.key_hash: (row.scope, row.expired, row.expires_at, row.dataset_id)
            for row in conn.execute(
                text(
                    "SELECT key_hash, scope, expires_at <= now() AS expired, "
                    "expires_at, dataset_id FROM catalog.api_keys "
                    "WHERE key_hash = ANY(:hashes)"
                ),
                {"hashes": [k["hash"] for k in keys]},
            )
        }
        # Relabelled rows can't authenticate even if someone reactivates one.
        for key in (never_expiring, expiring_later, expired):
            assert rows[key["hash"]][:2] == ("dataset_write", True)
            assert rows[key["hash"]][3] == dataset_id
        assert rows[expired["hash"]][2] == expired["expires"]
        assert rows[write_key["hash"]][:3] == (
            "dataset_write",
            False,
            write_key["expires"],
        )

        migration.upgrade()
        assert "dataset_append" in _constraints(conn)["chk_api_keys_scope"]
        assert "dataset_append" in _constraints(conn)["chk_api_keys_dataset_scope"]
        conn.execute(_INSERT_KEY, _key(admin_id, dataset_id, active=False))

    _run(round_trip, keys=keys)
