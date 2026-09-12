"""Refresh replay and current-session revocation remain scoped to one login."""

import hashlib
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.modules.auth.models import RefreshToken
from app.modules.auth.service import AuthService


async def login(client, *, cookie=False):
    response = await client.post(
        "/auth/login",
        data={
            "username": settings.geolens_admin_username,
            "password": settings.geolens_admin_password.get_secret_value(),
        },
        headers={"X-GeoLens-Auth-Mode": "cookie"} if cookie else {},
    )
    assert response.status_code == 200, response.text
    if cookie:
        # Tests call the unmounted /auth routes; production cookies use /api/auth.
        values = {
            name: response.cookies[name] for name in ("geolens_refresh", "geolens_csrf")
        }
        client.cookies.clear()
        for name, value in values.items():
            client.cookies.set(name, value)
    return response.json()


async def rotate(client, token):
    return await client.post("/auth/refresh/", json={"refresh_token": token})


async def change_row(db, token, **values):
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hashlib.sha256(token.encode()).hexdigest())
        .values(**values)
    )
    await db.commit()


async def test_replay_revokes_every_grace_branch_but_other_login_survives(
    client, test_db_session
):
    first, other = await login(client), await login(client)
    branches = [(await rotate(client, first["refresh_token"])).json() for _ in range(3)]
    claims = [
        jwt.decode(pair["access_token"], options={"verify_signature": False})
        for pair in [first, *branches, other]
    ]
    assert len({claim["sid"] for claim in claims[:-1]}) == 1
    assert claims[-1]["sid"] != claims[0]["sid"]
    await change_row(
        test_db_session,
        first["refresh_token"],
        rotated_at=datetime.now(UTC) - timedelta(seconds=31),
    )
    assert (await rotate(client, first["refresh_token"])).status_code == 401
    for pair in branches:
        assert (await rotate(client, pair["refresh_token"])).status_code == 401
    assert (await rotate(client, other["refresh_token"])).status_code == 200
    # Family revocation deliberately leaves the existing access-token TTL intact.
    assert (
        await client.get(
            "/auth/me/",
            headers={"Authorization": f"Bearer {branches[0]['access_token']}"},
        )
    ).status_code == 200


@pytest.mark.parametrize("expired_rotated", [False, True])
async def test_natural_expiry_does_not_revoke_successor(
    client, test_db_session, expired_rotated
):
    pair = await login(client)
    successor = (await rotate(client, pair["refresh_token"])).json()
    await change_row(
        test_db_session,
        pair["refresh_token"],
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        rotated_at=datetime.now(UTC) - timedelta(seconds=60)
        if expired_rotated
        else None,
    )
    assert (await rotate(client, pair["refresh_token"])).status_code == 401
    assert (await rotate(client, successor["refresh_token"])).status_code == 200


async def test_current_session_revocation_is_idempotent_and_preserves_other_device(
    client,
):
    first, other = await login(client), await login(client)
    rotated = (await rotate(client, first["refresh_token"])).json()
    for _ in range(2):
        response = await client.post(
            "/auth/logout/session/",
            headers={"Authorization": f"Bearer {first['access_token']}"},
        )
        assert response.status_code == 204
        assert "set-cookie" not in response.headers
    for pair in [first, rotated]:
        assert (await rotate(client, pair["refresh_token"])).status_code == 401
    assert (await rotate(client, other["refresh_token"])).status_code == 200


async def test_refresh_body_can_revoke_without_access_token(client):
    pair = await login(client)
    response = await client.post(
        "/auth/logout/session/", json={"refresh_token": pair["refresh_token"]}
    )
    assert response.status_code == 204
    assert "set-cookie" not in response.headers
    assert (await rotate(client, pair["refresh_token"])).status_code == 401


async def test_cookie_revoke_requires_csrf_and_clears_only_cookie_transport(client):
    await login(client, cookie=True)
    assert (await client.post("/auth/logout/session/")).status_code == 403
    csrf = client.cookies.get("geolens_csrf")
    response = await client.post(
        "/auth/logout/session/", headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]


@pytest.mark.parametrize("kind", ["expired", "legacy", "forged", "malformed"])
async def test_invalid_bearer_cannot_fall_back_to_cookie(client, kind):
    pair = await login(client, cookie=True)
    payload = jwt.decode(pair["access_token"], options={"verify_signature": False})
    if kind == "expired":
        payload["exp"] = datetime.now(UTC) - timedelta(seconds=1)
    if kind == "legacy":
        payload.pop("sid")
    token = jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    if kind == "forged":
        token = token[:-8] + "abcdefgh"
    if kind == "malformed":
        token = "invalid"
    response = await client.post(
        "/auth/logout/session/", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert (
        await client.post(
            "/auth/refresh/",
            headers={
                "X-GeoLens-Auth-Mode": "cookie",
                "X-CSRF-Token": client.cookies.get("geolens_csrf"),
            },
        )
    ).status_code == 200


async def test_cleanup_bounds_ancestor_retention_and_keeps_recent_evidence(
    client, test_db_session
):
    pair = await login(client)
    successor = (await rotate(client, pair["refresh_token"])).json()
    old_hash = hashlib.sha256(pair["refresh_token"].encode()).hexdigest()
    await change_row(
        test_db_session,
        pair["refresh_token"],
        expires_at=datetime.now(UTC) - timedelta(hours=23),
    )
    service = AuthService(test_db_session)
    await service.cleanup_refresh_tokens()
    assert (
        await test_db_session.execute(
            select(RefreshToken.id).where(RefreshToken.token_hash == old_hash)
        )
    ).scalar_one_or_none() is not None
    await change_row(
        test_db_session,
        pair["refresh_token"],
        expires_at=datetime.now(UTC) - timedelta(days=2),
    )
    await service.cleanup_refresh_tokens()
    await test_db_session.commit()
    assert (
        await test_db_session.execute(
            select(RefreshToken.id).where(RefreshToken.token_hash == old_hash)
        )
    ).scalar_one_or_none() is None
    assert (await rotate(client, successor["refresh_token"])).status_code == 200


async def test_rotation_racing_current_session_revoke_cannot_leave_successor(
    client, monkeypatch
):
    import anyio

    pair = await login(client)
    entered, release = anyio.Event(), anyio.Event()
    original_create = AuthService.create_access_token

    async def stalled_create(self, *args, **kwargs):
        entered.set()
        await release.wait()
        return await original_create(self, *args, **kwargs)

    monkeypatch.setattr(AuthService, "create_access_token", stalled_create)
    results = {}

    async def rotating():
        results["rotation"] = await rotate(client, pair["refresh_token"])

    async def revoking():
        results["revoke"] = await client.post(
            "/auth/logout/session/",
            headers={"Authorization": f"Bearer {pair['access_token']}"},
        )

    with anyio.fail_after(10):
        async with anyio.create_task_group() as group:
            group.start_soon(rotating)
            await entered.wait()
            group.start_soon(revoking)
            await anyio.sleep(0.05)
            release.set()
    assert results["rotation"].status_code == 200
    assert results["revoke"].status_code == 204
    successor = results["rotation"].json()["refresh_token"]
    assert (await rotate(client, successor)).status_code == 401


async def test_migration_backfills_distinct_legacy_families_without_extending_expiry(
    client, test_db_session
):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    first, second = await login(client), await login(client)
    spent = await login(client)
    assert (await rotate(client, spent["refresh_token"])).status_code == 200
    spent_hash = hashlib.sha256(spent["refresh_token"].encode()).hexdigest()
    hashes = [
        hashlib.sha256(pair["refresh_token"].encode()).hexdigest()
        for pair in [first, second]
    ]
    migration_path = (
        Path(__file__).parents[1] / "alembic/versions/0061_refresh_token_families.py"
    )
    spec = importlib.util.spec_from_file_location("families_migration", migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    conn = await test_db_session.connection()

    def roundtrip(sync_conn):
        before = sync_conn.execute(
            text(
                "SELECT token_hash, expires_at FROM catalog.refresh_tokens WHERE token_hash IN (:a, :b)"
            ),
            {"a": hashes[0], "b": hashes[1]},
        ).all()
        with Operations.context(MigrationContext.configure(sync_conn)):
            module.downgrade()
            module.upgrade()
        assert (
            sync_conn.execute(
                text(
                    "SELECT revoked FROM catalog.refresh_tokens WHERE token_hash = :hash"
                ),
                {"hash": spent_hash},
            ).scalar_one()
            is True
        )
        after = sync_conn.execute(
            text(
                "SELECT token_hash, expires_at, family_id, rotated_at FROM catalog.refresh_tokens WHERE token_hash IN (:a, :b)"
            ),
            {"a": hashes[0], "b": hashes[1]},
        ).all()
        assert {(r.token_hash, r.expires_at) for r in after} == set(before)
        assert len({r.family_id for r in after}) == 2
        assert all(r.family_id is not None and r.rotated_at is None for r in after)

    try:
        await conn.run_sync(roundtrip)
    finally:
        # DDL is transactional: restore the test schema and original families.
        await test_db_session.rollback()
    assert (await rotate(client, first["refresh_token"])).status_code == 200
