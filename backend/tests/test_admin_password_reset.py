"""Integration tests for POST /admin/users/{user_id}/reset-password/ (#1715).

The login page tells a locked-out user to contact an administrator; before
this endpoint the administrator had no way to help short of psql. These pin
the four things that make the promise true and safe:

  - the target's stored password really changes (new value logs in, old one
    does not), and the response is the updated user;
  - the reset revokes the target's outstanding credentials, mirroring what
    POST /auth/change-password/ already does on the self-service path;
  - the refusals: 403 for a non-admin, 404 for an unknown user, 422 for a
    value the password policy rejects, 422 for an account that signs in
    through an identity provider;
  - the audit row names the actor and the target and carries no password.

Requirements: the docker database must be running (docker compose up db) with
alembic migrations applied.
"""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.auth.models import User


def _synthetic_password(tag: str) -> str:
    """A policy-satisfying value that is obviously not a real credential.

    Generated rather than written as a literal so nothing in this file reads
    like a password anyone could have used anywhere.
    """
    return f"Aa1-not-a-real-{tag}-{uuid.uuid4().hex[:8]}"


async def _create_local_user(
    client: AsyncClient, admin_auth_header: dict, role: str = "viewer"
) -> tuple[str, str, str]:
    """Create a user through the admin API. Returns (id, username, password)."""
    username = f"reset_{role}_{uuid.uuid4().hex[:8]}"
    password = _synthetic_password("original")
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": password, "role": role},
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], username, password


async def _login(client: AsyncClient, username: str, password: str):
    return await client.post(
        "/auth/login", data={"username": username, "password": password}
    )


@pytest.mark.anyio
async def test_reset_password_replaces_the_stored_credential(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """The new value logs in, the old one stops working, and the user comes back."""
    user_id, username, old_password = await _create_local_user(
        client, admin_auth_header
    )
    new_password = _synthetic_password("replacement")

    resp = await client.post(
        f"/admin/users/{user_id}/reset-password/",
        json={"password": new_password},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == user_id
    assert body["username"] == username
    # The response is the user, not the credential.
    assert "password" not in body
    assert "password_hash" not in body

    assert (await _login(client, username, new_password)).status_code == 200
    assert (await _login(client, username, old_password)).status_code == 401


@pytest.mark.anyio
async def test_reset_password_revokes_the_targets_existing_sessions(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """An access token minted before the reset stops resolving after it.

    This is the half that makes a reset a recovery rather than a co-tenancy:
    whoever held the old password is not left with a live session. It mirrors
    change_password's revoke_all_tokens(bump_key_epoch=True).
    """
    user_id, username, old_password = await _create_local_user(
        client, admin_auth_header
    )
    login = await _login(client, username, old_password)
    assert login.status_code == 200
    target_header = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # The token works before the reset.
    assert (await client.get("/auth/me/", headers=target_header)).status_code == 200

    resp = await client.post(
        f"/admin/users/{user_id}/reset-password/",
        json={"password": _synthetic_password("replacement")},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text

    assert (await client.get("/auth/me/", headers=target_header)).status_code == 401


@pytest.mark.anyio
async def test_reset_password_ends_the_acting_admins_own_session(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Resetting your own password signs you out, as the docstring promises.

    Uses a throwaway admin: the seeded admin's credentials back every other
    test's fixture, so this must never touch them.
    """
    user_id, username, password = await _create_local_user(
        client, admin_auth_header, role="admin"
    )
    login = await _login(client, username, password)
    assert login.status_code == 200
    own_header = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post(
        f"/admin/users/{user_id}/reset-password/",
        json={"password": _synthetic_password("self")},
        headers=own_header,
    )
    assert resp.status_code == 200, resp.text
    assert (await client.get("/auth/me/", headers=own_header)).status_code == 401


@pytest.mark.anyio
async def test_reset_password_forbidden_for_non_admin(
    client: AsyncClient,
    admin_auth_header: dict,
    viewer_auth_header: dict,
):
    """A viewer cannot reset anyone's password, and the target is untouched."""
    user_id, username, password = await _create_local_user(client, admin_auth_header)

    resp = await client.post(
        f"/admin/users/{user_id}/reset-password/",
        json={"password": _synthetic_password("denied")},
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403, resp.text
    assert (await _login(client, username, password)).status_code == 200


@pytest.mark.anyio
async def test_reset_password_404_for_unknown_user(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """An id nothing matches maps through the shared not-found path."""
    resp = await client.post(
        f"/admin/users/{uuid.uuid4()}/reset-password/",
        json={"password": _synthetic_password("nobody")},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.anyio
async def test_reset_password_422_for_a_value_the_policy_rejects(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """The shared password policy gates this endpoint too.

    The value is long enough to clear the schema's fast-fail floor and has one
    character class, so only the policy validator can reject it -- which is
    what proves the endpoint reuses it rather than relying on min_length.
    """
    user_id, username, password = await _create_local_user(client, admin_auth_header)

    resp = await client.post(
        f"/admin/users/{user_id}/reset-password/",
        json={"password": "aaaaaaaaaaaaaaaa"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, resp.text
    # The refusal changed nothing.
    assert (await _login(client, username, password)).status_code == 200


@pytest.mark.anyio
async def test_reset_password_422_for_an_identity_provider_account(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
):
    """An account with no local password credential is refused, not given one."""
    user_id, _, _ = await _create_local_user(client, admin_auth_header)
    await test_db_session.execute(
        update(User)
        .where(User.id == uuid.UUID(user_id))
        .values(auth_provider="oauth", password_hash=None)
    )
    await test_db_session.commit()

    resp = await client.post(
        f"/admin/users/{user_id}/reset-password/",
        json={"password": _synthetic_password("sso")},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, resp.text

    stored = await test_db_session.execute(
        select(User.password_hash, User.auth_provider).where(
            User.id == uuid.UUID(user_id)
        )
    )
    password_hash, auth_provider = stored.one()
    assert password_hash is None
    assert auth_provider == "oauth"


@pytest.mark.anyio
async def test_reset_password_audits_actor_and_target_without_the_password(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
):
    """One audit row, naming who acted on whom, carrying no credential."""
    user_id, username, _ = await _create_local_user(client, admin_auth_header)
    me = await client.get("/auth/me/", headers=admin_auth_header)
    assert me.status_code == 200
    admin_id = me.json()["id"]
    new_password = _synthetic_password("audited")

    resp = await client.post(
        f"/admin/users/{user_id}/reset-password/",
        json={"password": new_password},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text

    rows = (
        (
            await test_db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.password_reset",
                    AuditLog.resource_id == uuid.UUID(user_id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert str(row.user_id) == admin_id
    assert row.resource_type == "user"
    assert row.details == {"username": username}
    # Nothing on the row can carry the submitted value.
    serialized = json.dumps(
        {
            "action": row.action,
            "resource_type": row.resource_type,
            "details": row.details,
            "ip_address": row.ip_address,
        }
    )
    assert new_password not in serialized
