"""HARDEN-04 (T-1238-07): Admin create_user fail-fast role check tests.

Verifies that AdminService.create_user() resolves the role BEFORE adding or
flushing the User row, so a bad role name raises ValueError with no partial
user write in the session.
"""

import uuid

import pytest
from sqlalchemy import select

from app.modules.admin.service import AdminService
from app.modules.auth.models import User


# ---------------------------------------------------------------------------
# Test 1: Missing role raises ValueError with NO partial user write
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_user_bogus_role_raises_no_partial_write(client, test_db_session):
    """A non-existent role_name raises ValueError and leaves no User row."""
    username = f"failfast-{uuid.uuid4().hex[:8]}"
    service = AdminService(test_db_session)

    with pytest.raises(ValueError, match="Role '.*' not found"):
        await service.create_user(
            username=username,
            password="TestPass1234!",
            role_name="nonexistent-role-xyz",
        )

    # The session must not have a pending/flushed user with that username.
    # We query the DB directly to confirm no user was written.
    result = await test_db_session.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()
    assert user is None, (
        f"Expected no User row for {username!r} after failed create_user, "
        f"but found: {user}"
    )


# ---------------------------------------------------------------------------
# Test 2: Valid role still creates the user correctly
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_user_valid_role_succeeds(client, test_db_session):
    """A valid role_name creates the user and assigns the role as before."""
    username = f"validrole-{uuid.uuid4().hex[:8]}"
    service = AdminService(test_db_session)

    user = await service.create_user(
        username=username,
        password="TestPass1234!",
        role_name="viewer",
    )
    await test_db_session.commit()

    assert user is not None
    assert user.username == username
    role_names = {r.name for r in user.roles}
    assert "viewer" in role_names, f"Expected 'viewer' role, got: {role_names}"


# ---------------------------------------------------------------------------
# Test 3: Uniqueness checks still run before role check
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_user_duplicate_username_raises_before_role_check(
    client, test_db_session
):
    """Username uniqueness check fires before role resolution (ordering preserved)."""
    # Create an initial user with the 'viewer' role
    username = f"dup-{uuid.uuid4().hex[:8]}"
    service = AdminService(test_db_session)

    await service.create_user(
        username=username,
        password="TestPass1234!",
        role_name="viewer",
    )
    await test_db_session.commit()

    # Trying the same username with a bogus role should still raise "Username already taken",
    # not "Role not found" — uniqueness check has priority.
    with pytest.raises(ValueError, match="Username already taken"):
        await service.create_user(
            username=username,
            password="TestPass1234!",
            role_name="nonexistent-role-xyz",
        )


# ---------------------------------------------------------------------------
# Test 4: Email uniqueness check fires before role check
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_user_duplicate_email_raises_before_role_check(
    client, test_db_session
):
    """Email uniqueness check fires before role resolution (ordering preserved)."""
    email = f"dup-email-{uuid.uuid4().hex[:8]}@example.com"
    service = AdminService(test_db_session)

    await service.create_user(
        username=f"firstuser-{uuid.uuid4().hex[:8]}",
        password="TestPass1234!",
        email=email,
        role_name="viewer",
    )
    await test_db_session.commit()

    with pytest.raises(ValueError, match="Email already registered"):
        await service.create_user(
            username=f"seconduser-{uuid.uuid4().hex[:8]}",
            password="TestPass1234!",
            email=email,
            role_name="nonexistent-role-xyz",
        )
