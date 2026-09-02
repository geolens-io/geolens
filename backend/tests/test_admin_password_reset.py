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

import anyio
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.auth.models import RefreshToken, User
from app.modules.auth.providers.local import hash_password


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


# ---------------------------------------------------------------------------
# bcrypt's 72-byte input limit (fix(#1715 codex r1))
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reset_password_422_for_a_value_over_the_bcrypt_byte_limit(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """73 ASCII characters is 73 bytes, one more than bcrypt accepts.

    The schema permits 256 characters, so before the shared validator learned
    the byte rule this reached BcryptHasher and raised ValueError there. The
    refusal has to name the real constraint, and the account must be untouched.
    """
    user_id, username, password = await _create_local_user(client, admin_auth_header)
    over_limit = "Abcdef1!" + "x" * 65
    assert len(over_limit.encode("utf-8")) == 73

    resp = await client.post(
        f"/admin/users/{user_id}/reset-password/",
        json={"password": over_limit},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, resp.text
    assert "72 bytes" in resp.text
    assert (await _login(client, username, password)).status_code == 200


@pytest.mark.anyio
async def test_reset_password_422_for_a_short_multibyte_value_over_the_limit(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """43 characters, 83 bytes: the character count alone looks acceptable."""
    user_id, username, password = await _create_local_user(client, admin_auth_header)
    multibyte = "Aa1" + "é" * 40
    assert len(multibyte) == 43
    assert len(multibyte.encode("utf-8")) == 83

    resp = await client.post(
        f"/admin/users/{user_id}/reset-password/",
        json={"password": multibyte},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, resp.text
    assert "72 bytes" in resp.text
    assert (await _login(client, username, password)).status_code == 200


@pytest.mark.anyio
async def test_reset_password_accepts_exactly_the_byte_limit(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """72 bytes is the most bcrypt hashes, so it must still be a valid reset."""
    user_id, username, _ = await _create_local_user(client, admin_auth_header)
    at_limit = "Abcdef1!" + "x" * 64
    assert len(at_limit.encode("utf-8")) == 72

    resp = await client.post(
        f"/admin/users/{user_id}/reset-password/",
        json={"password": at_limit},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert (await _login(client, username, at_limit)).status_code == 200


@pytest.mark.anyio
async def test_the_byte_limit_also_closed_the_two_pre_existing_entry_points(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """POST /admin/users/ and POST /auth/change-password/ had the same gap.

    Both call validate_password_from_settings, so putting the byte rule in the
    shared policy fixed them at the same time. Both were measured before the
    fix: admin-create turned the bcrypt ValueError into a 409 carrying the
    library's own text, and on change-password the ValueError escaped the
    handler entirely (nothing registers a ValueError handler, so a 500).
    """
    over_limit = "Abcdef1!" + "x" * 65

    created = await client.post(
        "/admin/users/",
        json={
            "username": f"bytes_{uuid.uuid4().hex[:8]}",
            "password": over_limit,
            "role": "viewer",
        },
        headers=admin_auth_header,
    )
    assert created.status_code == 422, created.text
    assert "72 bytes" in created.text

    _, username, password = await _create_local_user(client, admin_auth_header)
    login = await _login(client, username, password)
    assert login.status_code == 200
    target_header = {"Authorization": f"Bearer {login.json()['access_token']}"}

    changed = await client.post(
        "/auth/change-password/",
        json={"current_password": password, "new_password": over_limit},
        headers=target_header,
    )
    assert changed.status_code == 422, changed.text
    assert "72 bytes" in changed.text


# ---------------------------------------------------------------------------
# Reset vs. self-service change-password (fix(#1715 codex r1 P1))
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reset_is_not_overwritten_by_a_racing_change_password(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
):
    """A holder of the old password cannot win the recovery by racing it.

    The interleaving codex found: change_password verified the pre-reset hash
    and assigned its replacement, then blocked inside revoke_all_tokens' own
    FOR UPDATE. When the reset released the row, SQLAlchemy autoflush wrote the
    self-service password on top of the admin's, so the account stayed under
    the old holder's control while the admin saw a successful reset.

    Reproduced by holding the target's row the way the reset does, starting a
    change-password underneath it, then committing the admin's hash before
    letting go. change_password now takes that same lock before it verifies, so
    it re-reads the committed hash and refuses the stale current_password.
    """
    user_id, username, old_password = await _create_local_user(
        client, admin_auth_header
    )
    login = await _login(client, username, old_password)
    assert login.status_code == 200
    target_header = {"Authorization": f"Bearer {login.json()['access_token']}"}

    admin_value = _synthetic_password("admin-set")
    old_holder_value = _synthetic_password("old-holder")
    target_uuid = uuid.UUID(user_id)
    locked = anyio.Event()
    change_password_status: list[int] = []

    async def hold_the_row_then_commit_the_reset() -> None:
        """Stand in for the admin reset: lock, write, commit."""
        await test_db_session.execute(
            select(User).where(User.id == target_uuid).with_for_update()
        )
        locked.set()
        # Give the change-password request time to reach its own lock wait.
        await anyio.sleep(0.5)
        await test_db_session.execute(
            update(User)
            .where(User.id == target_uuid)
            .values(password_hash=hash_password(admin_value))
        )
        await test_db_session.commit()

    async def racing_change_password() -> None:
        await locked.wait()
        resp = await client.post(
            "/auth/change-password/",
            json={
                "current_password": old_password,
                "new_password": old_holder_value,
            },
            headers=target_header,
        )
        change_password_status.append(resp.status_code)

    with anyio.fail_after(30):
        async with anyio.create_task_group() as tg:
            tg.start_soon(hold_the_row_then_commit_the_reset)
            tg.start_soon(racing_change_password)

    # The stale current_password is refused against the freshly committed hash.
    assert change_password_status == [400]
    # The admin's value is what the account ends up with.
    assert (await _login(client, username, admin_value)).status_code == 200
    assert (await _login(client, username, old_holder_value)).status_code == 401
    assert (await _login(client, username, old_password)).status_code == 401


@pytest.mark.anyio
async def test_reset_is_not_outrun_by_a_racing_password_login(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
):
    """A login with the old password cannot mint credentials across the reset.

    The second interleaving of the same class codex found on change-password,
    this time on the login path. LocalAuthProvider.authenticate() looked the
    account up with an unlocked SELECT, so a login that read the row before the
    reset committed verified the STALE hash. It then minted from the post-reset
    row: an access JWT stamped with the new token_version, and a refresh row
    created after sessions_revoked_at. Both survive the revocation, so the
    old-password holder walks out of the recovery holding a live session.

    Reproduced the same way as the change-password race: hold the target's row
    the way the reset does, start a login underneath it, then commit the
    admin's hash before letting go. The lookup takes FOR SHARE now, so the
    login blocks, verifies against the committed hash, and fails.
    """
    user_id, username, old_password = await _create_local_user(
        client, admin_auth_header
    )
    admin_value = _synthetic_password("admin-set")
    target_uuid = uuid.UUID(user_id)

    async def _refresh_row_count() -> int:
        result = await test_db_session.execute(
            select(func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.user_id == target_uuid)
        )
        return int(result.scalar_one())

    locked = anyio.Event()
    login_status: list[int] = []

    async def hold_the_row_then_commit_the_reset() -> None:
        """Stand in for the admin reset: lock, write the new hash, commit."""
        await test_db_session.execute(
            select(User).where(User.id == target_uuid).with_for_update()
        )
        locked.set()
        # Give the login time to reach its own lock wait.
        await anyio.sleep(0.5)
        await test_db_session.execute(
            update(User)
            .where(User.id == target_uuid)
            .values(password_hash=hash_password(admin_value))
        )
        await test_db_session.commit()

    async def racing_login() -> None:
        await locked.wait()
        resp = await client.post(
            "/auth/login",
            data={"username": username, "password": old_password},
        )
        login_status.append(resp.status_code)

    before = await _refresh_row_count()

    with anyio.fail_after(30):
        async with anyio.create_task_group() as tg:
            tg.start_soon(hold_the_row_then_commit_the_reset)
            tg.start_soon(racing_login)

    # The old password is refused against the hash the reset committed.
    assert login_status == [401]
    # And nothing was minted: no refresh row was created for the account.
    assert await _refresh_row_count() == before
    # The admin's value is the only one that works.
    assert (await _login(client, username, admin_value)).status_code == 200
    assert (await _login(client, username, old_password)).status_code == 401
