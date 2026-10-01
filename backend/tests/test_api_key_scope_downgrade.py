"""The scope downgrade counts restricted keys only after it holds the table locks."""

import importlib.util
import threading
import time
import uuid
from pathlib import Path

import pytest
import sqlalchemy
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.core.config import settings
from tests.factories import get_user_id

pytestmark = pytest.mark.anyio

_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0032_api_key_scope.py"
)
_SPEC = importlib.util.spec_from_file_location("migration_0032_downgrade", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
migration = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migration)

_INSERT_READ_ONLY_KEY = text(
    "INSERT INTO catalog.api_keys "
    "(user_id, key_hash, name, is_active, scope, key_epoch) "
    "SELECT :uid, :hash, 'scope downgrade fixture', true, 'read_only', u.key_epoch "
    "FROM catalog.users u WHERE u.id = :uid"
)


def _wait_until_blocked(connection, pid: int) -> bool:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        waiting = connection.execute(
            text(
                "SELECT 1 FROM pg_stat_activity "
                "WHERE pid = :pid AND wait_event_type = 'Lock'"
            ),
            {"pid": pid},
        ).first()
        if waiting:
            return True
        time.sleep(0.05)
    return False


async def test_downgrade_sees_a_read_only_key_committed_while_it_waits_for_the_locks(
    test_db_session,
):
    admin_id = await get_user_id(test_db_session, "admin")
    # The fixture session must not hold table locks that would block the downgrade.
    await test_db_session.rollback()

    key_hash = f"scope-downgrade-{uuid.uuid4().hex}"
    engine = sqlalchemy.create_engine(settings.test_database_url_sync)
    writer = engine.connect()
    migrator = engine.connect()
    outcome: dict[str, object] = {}

    def downgrade() -> None:
        try:
            with Operations.context(MigrationContext.configure(migrator)):
                migration.downgrade()
            outcome["result"] = "dropped the scope column"
        except RuntimeError as exc:
            outcome["result"] = exc
        finally:
            migrator.rollback()

    thread: threading.Thread | None = None
    try:
        # An uncommitted insert holds the table until the downgrade is already waiting.
        writer.execute(_INSERT_READ_ONLY_KEY, {"uid": str(admin_id), "hash": key_hash})
        migrator_pid = migrator.execute(text("SELECT pg_backend_pid()")).scalar_one()
        thread = threading.Thread(target=downgrade)
        thread.start()
        assert _wait_until_blocked(writer, migrator_pid), (
            "the downgrade never waited on the in-flight key insert"
        )
        writer.commit()
        thread.join(timeout=30)
        assert not thread.is_alive()
    finally:
        writer.rollback()
        if thread is not None:
            thread.join(timeout=30)
        writer.close()
        migrator.close()
        with engine.begin() as cleanup:
            cleanup.execute(
                text("DELETE FROM catalog.api_keys WHERE key_hash = :hash"),
                {"hash": key_hash},
            )
        engine.dispose()

    result = outcome["result"]
    assert isinstance(result, RuntimeError), result
    assert "ACTIVE catalog.api_keys" in str(result)
