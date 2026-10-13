"""Wrong current passwords on a password change are throttled per account, apart from sign-in."""

import asyncio
import uuid

from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.modules.auth.login_throttle import (
    LOGIN_FAILURE_LIMIT,
    reserve_password_change_attempt,
)
from tests.conftest import get_auth_header

PASSWORD = "TestPass1234!"
NEW_PASSWORD = "OtherPass5678!"


async def _new_user(client: AsyncClient) -> tuple[str, uuid.UUID]:
    admin = await get_auth_header(
        client,
        settings.geolens_admin_username,
        settings.geolens_admin_password.get_secret_value(),
    )
    username = f"pwthrottle_{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": PASSWORD, "role": "viewer"},
        headers=admin,
    )
    assert resp.status_code == 201, resp.text
    return username, uuid.UUID(resp.json()["id"])


async def _login(client: AsyncClient, username: str, password: str):
    return await client.post(
        "/auth/login", data={"username": username, "password": password}
    )


async def _bearer(client: AsyncClient, username: str) -> dict[str, str]:
    resp = await _login(client, username, PASSWORD)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _change(client: AsyncClient, bearer: dict[str, str], current: str):
    return await client.post(
        "/auth/change-password/",
        json={"current_password": current, "new_password": NEW_PASSWORD},
        headers=bearer,
    )


async def _fail_changes(
    client: AsyncClient, bearer: dict[str, str], times: int
) -> list[int]:
    return [
        (await _change(client, bearer, "wrong-password")).status_code
        for _ in range(times)
    ]


async def test_wrong_current_passwords_are_refused_after_the_limit(
    client: AsyncClient,
):
    username, _ = await _new_user(client)
    bearer = await _bearer(client, username)

    assert await _fail_changes(client, bearer, LOGIN_FAILURE_LIMIT) == [400] * 10

    refused = await _change(client, bearer, "wrong-password")
    assert refused.status_code == 429, refused.text
    assert refused.json()["detail"]["code"] == "password_change_throttled"
    assert refused.json()["detail"]["message"]
    assert 0 < int(refused.headers["retry-after"]) <= 3600
    # The budget counts guesses, so the right password is refused too.
    assert (await _change(client, bearer, PASSWORD)).status_code == 429
    assert (await _login(client, username, PASSWORD)).status_code == 200


async def test_failed_sign_ins_do_not_block_a_password_change(client: AsyncClient):
    username, _ = await _new_user(client)
    bearer = await _bearer(client, username)
    for _ in range(LOGIN_FAILURE_LIMIT):
        assert (await _login(client, username, "wrong-password")).status_code == 401
    assert (await _login(client, username, PASSWORD)).status_code == 429

    assert (await _change(client, bearer, PASSWORD)).status_code == 204


async def test_a_correct_current_password_under_the_limit_is_not_counted(
    client: AsyncClient,
):
    username, _ = await _new_user(client)
    bearer = await _bearer(client, username)
    await _fail_changes(client, bearer, LOGIN_FAILURE_LIMIT - 1)

    assert (await _change(client, bearer, PASSWORD)).status_code == 204
    resp = await _login(client, username, NEW_PASSWORD)
    assert resp.status_code == 200, resp.text


async def test_parallel_checks_cannot_exceed_the_limit(client: AsyncClient):
    import app.core.db as db_module

    user_id = uuid.uuid4()

    async def attempt() -> bool:
        async with db_module.async_session() as db:
            try:
                await reserve_password_change_attempt(db, user_id, "parallel")
            except HTTPException as exc:
                assert exc.status_code == 429
                return False
            return True

    results = await asyncio.gather(*(attempt() for _ in range(LOGIN_FAILURE_LIMIT + 2)))
    assert results.count(True) == LOGIN_FAILURE_LIMIT


async def test_filling_the_budget_writes_one_audit_row(
    client: AsyncClient, test_db_session
):
    username, user_id = await _new_user(client)
    bearer = await _bearer(client, username)
    await _fail_changes(client, bearer, LOGIN_FAILURE_LIMIT + 3)

    rows = (
        await test_db_session.execute(
            text(
                "SELECT user_id, details FROM catalog.audit_logs "
                "WHERE action = 'user.change_password.throttled' "
                "AND resource_id = :user_id"
            ),
            {"user_id": user_id},
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].user_id == user_id
    assert rows[0].details == {
        "username": username,
        "failures": LOGIN_FAILURE_LIMIT,
        "window_seconds": 3600,
    }
