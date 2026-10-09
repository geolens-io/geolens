"""The upgrade that marks admin-entered account emails as verified."""

import importlib.util
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.auth.models import User


def _migration():
    path = (
        Path(__file__).parents[1]
        / "alembic/versions/0081_admin_entered_email_verified.py"
    )
    spec = importlib.util.spec_from_file_location("admin_entered_email", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _user(kind: str, **fields) -> User:
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        username=f"{kind}-{suffix}",
        email=f"{kind}-{suffix}@example.com",
        status="active",
        is_active=True,
        auth_provider="local",
    )
    return User(**{**defaults, **fields})


async def test_upgrade_verifies_only_admin_entered_addresses(test_db_session):
    session = test_db_session
    admin_created = _user("admin-created")
    self_registered = _user("self-registered")
    pending = _user("pending", status="pending", is_active=False)
    oauth = _user("oauth", auth_provider="oauth")
    session.add_all([admin_created, self_registered, pending, oauth])
    await session.flush()
    session.add(
        AuditLog(
            user_id=self_registered.id,
            action="user.register",
            resource_type="user",
            resource_id=self_registered.id,
        )
    )
    await session.flush()
    migration = _migration()

    def upgrade(sync_session):
        with Operations.context(MigrationContext.configure(sync_session.connection())):
            migration.upgrade()

    try:
        await session.run_sync(upgrade)
        rows = await session.execute(
            select(User.id, User.email_verified).where(
                User.id.in_(
                    [admin_created.id, self_registered.id, pending.id, oauth.id]
                )
            )
        )
        verified = dict(rows.all())
    finally:
        await session.rollback()

    assert verified == {
        admin_created.id: True,
        self_registered.id: False,
        pending.id: False,
        oauth.id: False,
    }
