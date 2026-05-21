"""Phase 279 ADMIN-05 + ADMIN-06 regression tests.

ADMIN-05 (L-02): POST /auth/register/ now emits a `user.register` audit
event. Without this lock, a future register-route refactor could silently
drop the event and the registration funnel goes dark.

ADMIN-06 (L-03): delete_user assumes every catalog FK referencing users.id
has ondelete='SET NULL' (cross-user references) or 'CASCADE' (owned data).
A future migration that introduces a non-nullable user FK without setting
ondelete would break delete_user at runtime. This test catches that BEFORE
the migration ships.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.auth.router import REGISTRATION_ENABLED


# -------------------------------------------------------------------
# ADMIN-06 — Static-analysis FK delete-behavior regression
# -------------------------------------------------------------------


def test_user_fk_delete_behavior_locked():
    """Every FK referencing catalog.users.id must use SET NULL or whitelisted CASCADE.

    delete_user assumes referencing rows either survive (SET NULL) or follow
    the deletion (CASCADE for owned-by-user data). Any future migration that
    introduces a NOT NULL + ondelete=NO ACTION (the SQLAlchemy default) FK to
    users would break delete_user at runtime with IntegrityError. This test
    fires before that breakage ships.
    """
    from app.core.db import Base

    # Force-import every module that registers ORM mappers so Base.metadata is
    # complete. New module with a users.id FK? Add the import here.
    import app.modules.audit.models  # noqa: F401
    import app.modules.auth.models  # noqa: F401
    import app.modules.auth.oauth.models  # noqa: F401
    import app.modules.catalog.collections.models  # noqa: F401
    import app.modules.catalog.datasets.domain.models  # noqa: F401
    import app.modules.catalog.maps.models  # noqa: F401
    import app.modules.catalog.search.saved  # noqa: F401
    import app.modules.embed_tokens.models  # noqa: F401
    import app.platform.jobs.models  # noqa: F401
    import app.processing.ai.token_usage  # noqa: F401
    import app.processing.embeddings.models  # noqa: F401
    import app.processing.raster.models  # noqa: F401

    # Tables/columns where CASCADE is intentional (owned-by-user data that
    # must vanish when the owning user is hard-deleted). Adding to this set
    # is a deliberate decision — review at PR time and document in the diff.
    CASCADE_WHITELIST = {
        "user_roles.user_id",
        "refresh_tokens.user_id",
        "api_keys.user_id",
        # OAuth/SAML identity linkage — when the user is hard-deleted the
        # linkage is meaningless and must follow the user out (table name is
        # ``oauth_accounts`` per OAuthAccount.__tablename__; the column links
        # the local user to its external identity).
        "oauth_accounts.user_id",
        # SavedSearch is per-user state (named queries the user authored);
        # has no value once the user is gone.
        "saved_searches.user_id",
    }

    bad_fks: list[str] = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            for fk in col.foreign_keys:
                # Match references to users.id regardless of schema-qualified
                # form. fk.column.table.name returns the bare table name; fk
                # may have been declared as "catalog.users.id" but the resolved
                # column lives on the bare ``users`` table object.
                if fk.column.table.name != "users":
                    continue
                qualified = f"{table.name}.{col.name}"
                ondelete = fk.ondelete or "NO ACTION"
                if ondelete == "SET NULL":
                    continue
                if ondelete == "CASCADE" and qualified in CASCADE_WHITELIST:
                    continue
                bad_fks.append(
                    f"{qualified} -> {fk.column.table.name}.{fk.column.name} "
                    f"(ondelete={ondelete})"
                )

    assert not bad_fks, (
        "Found user-FK references that would break delete_user. Either set "
        "ondelete='SET NULL' (cross-user reference) or ondelete='CASCADE' and "
        "add to CASCADE_WHITELIST (owned-by-user data):\n  - " + "\n  - ".join(bad_fks)
    )


def test_user_fk_test_imports_dont_silently_skip():
    """Sanity check: importing the model modules must populate Base.metadata.

    If a future refactor splits these modules and the
    test_user_fk_delete_behavior_locked force-imports become incomplete, this
    guard fires.
    """
    from app.core.db import Base

    # We expect at LEAST these tables to be in metadata after Task 1's
    # imports above run (pytest collects test functions in order and the
    # noqa imports persist for the module's lifetime).
    table_names = set(Base.metadata.tables.keys())
    for required in ("users", "audit_logs", "datasets", "maps"):
        assert any(t.endswith(required) or t == required for t in table_names), (
            f"Required table '{required}' not in metadata: "
            f"{sorted(table_names)[:10]}..."
        )


# -------------------------------------------------------------------
# ADMIN-05 — register emits user.register audit event
# -------------------------------------------------------------------
#
# These integration tests need a live DB + AsyncClient. They use the same
# `client` + `test_db_session` + `admin_auth_header` fixtures that
# tests/test_auth.py uses. The fixture model creates a per-session test DB
# and the admin user is seeded by lifespan.


@pytest.mark.anyio
async def test_register_emits_user_register_audit(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
):
    """A successful registration writes a user.register audit row."""
    from app.modules.audit.models import AuditLog

    # Enable registration for this test (default is disabled).
    monkeypatch.setattr(
        REGISTRATION_ENABLED,
        "get",
        AsyncMock(return_value=True),
    )

    unique = uuid.uuid4().hex[:8]
    username = f"audituser_{unique}"
    email = f"audituser_{unique}@example.com"
    # TD-02 (Plan 1081-01): v1014 SEC-S16 enforces 12-char minimum + 3-of-4 class
    # diversity at validate_password_complexity. The prior "securepass123" literal
    # (lowercase + digit = 2 classes) fails the 3-of-4 rule before the register
    # audit path runs. "TestPass1234!" mirrors conftest.py:491 / test_password_policy.py:37.
    resp = await client.post(
        "/auth/register/",
        json={
            "username": username,
            "password": "TestPass1234!",
            "email": email,
        },
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"

    # Find the audit row by action + the new user's username (no easy way to
    # discover the new user_id from the registration response — the API only
    # returns a generic message — so we filter by action and pick the most
    # recent matching row authored by anyone with that username).
    result = await test_db_session.execute(
        select(AuditLog)
        .where(AuditLog.action == "user.register")
        .order_by(AuditLog.created_at.desc())
        .limit(20)
    )
    rows = list(result.scalars().all())
    matching = [r for r in rows if r.details and r.details.get("username") == username]
    assert matching, (
        f"No user.register audit row for username={username}. "
        f"Recent user.register rows: "
        f"{[(r.id, r.details) for r in rows[:5]]}"
    )
    row = matching[0]
    assert row.action == "user.register"
    assert row.resource_type == "user"
    # resource_id == user_id == the new user (registrant is also the actor)
    assert row.resource_id == row.user_id
    # Email captured in details for funnel analytics
    assert row.details.get("email") == email


@pytest.mark.anyio
async def test_register_disabled_does_not_emit_audit(
    client: AsyncClient,
    test_db_session,
):
    """When registration is disabled, no audit row is created."""
    from app.modules.audit.models import AuditLog

    # Snapshot the audit count before the request (default state =
    # registration disabled — no setattr needed).
    before = await test_db_session.execute(
        select(AuditLog).where(AuditLog.action == "user.register")
    )
    before_count = len(list(before.scalars().all()))

    unique = uuid.uuid4().hex[:8]
    # TD-03 (Plan 1081-01): v1014 SEC-S16 enforces 12-char minimum + 3-of-4 class
    # diversity at validate_password_complexity. The prior "securepass123" literal
    # (lowercase + digit = 2 classes) fails the 3-of-4 rule before the registration
    # disabled path runs. "TestPass1234!" mirrors conftest.py:491 / test_password_policy.py:37.
    resp = await client.post(
        "/auth/register/",
        json={
            "username": f"shouldfail_{unique}",
            "password": "TestPass1234!",
        },
    )
    assert resp.status_code == 403

    after = await test_db_session.execute(
        select(AuditLog).where(AuditLog.action == "user.register")
    )
    after_count = len(list(after.scalars().all()))
    assert after_count == before_count, (
        "Disabled-registration path must not emit a user.register audit row."
    )
