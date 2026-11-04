"""A password reset racing API-key issuance never leaves a usable key."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends, Request
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text

import app.modules.auth.service as auth_service
from app.modules.auth.dependencies import (
    get_current_active_user,
    require_session_credential,
)
from app.modules.auth.models import ApiKey
from app.modules.catalog.datasets.domain.models import Dataset, Record
from tests.factories import create_user
from tests.lock_wait import await_lock_wait_query

pytestmark = pytest.mark.anyio


def _reset(client: AsyncClient, admin_auth_header: dict, user_id: str):
    return client.post(
        f"/admin/users/{user_id}/reset-password/",
        json={"password": f"Aa1-not-a-real-reset-{uuid.uuid4().hex[:8]}"},
        headers=admin_auth_header,
    )


async def _key_count(test_db_session, user_id: str) -> int:
    return await test_db_session.scalar(
        select(func.count())
        .select_from(ApiKey)
        .where(ApiKey.user_id == uuid.UUID(user_id))
    )


async def _feature_dataset(session, owner_id: str) -> tuple[uuid.UUID, str, uuid.UUID]:
    table_name = f"test_keyrace_{uuid.uuid4().hex[:8]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} (gid SERIAL PRIMARY KEY, "
            "geom geometry(Point, 4326), name TEXT)"
        )
    )
    record = Record(
        title=f"Key race {table_name}",
        visibility="private",
        record_status="published",
        created_by=uuid.UUID(owner_id),
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="POINT",
        feature_count=0,
        column_info=[{"name": "name", "type": "text"}],
        source_format="created",
    )
    session.add(dataset)
    await session.commit()
    return dataset.id, table_name, record.id


@pytest.mark.parametrize("site", ["own", "dataset", "admin"])
async def test_reset_committed_after_admission_refuses_issuance(
    client: AsyncClient, admin_auth_header: dict, test_db_session, site: str
):
    """A reset committing between authentication and issuance gets the issuer a 401 and mints nothing."""
    from app.api.main import app

    if site == "admin":
        headers, caller_id = await create_user(client, admin_auth_header, "admin")
        _, key_owner_id = await create_user(client, admin_auth_header, "viewer")
        url, body = "/admin/api-keys/", {"name": "racing", "user_id": key_owner_id}
    else:
        headers, caller_id = await create_user(client, admin_auth_header, "editor")
        key_owner_id = caller_id
        url, body = "/auth/api-keys/", {"name": "racing"}
    dataset = None
    if site == "dataset":
        dataset = await _feature_dataset(test_db_session, caller_id)
        expires = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        url, body = (
            f"/datasets/{dataset[0]}/api-keys",
            {"name": "racing", "expires_at": expires},
        )

    admitted = asyncio.Event()
    resume = asyncio.Event()

    async def _admit_then_wait(
        request: Request, current_user=Depends(get_current_active_user)
    ):
        identity = await require_session_credential(request, current_user)
        if str(identity.id) == caller_id:
            admitted.set()
            await resume.wait()
        return identity

    app.dependency_overrides[require_session_credential] = _admit_then_wait
    try:
        issuing = asyncio.ensure_future(client.post(url, json=body, headers=headers))
        await asyncio.wait_for(admitted.wait(), timeout=30)
        reset = await _reset(client, admin_auth_header, caller_id)
        assert reset.status_code == 200, reset.text
        resume.set()
        resp = await asyncio.wait_for(issuing, timeout=30)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Could not validate credentials"
        assert resp.headers["WWW-Authenticate"] == "Bearer"
        assert await _key_count(test_db_session, key_owner_id) == 0
    finally:
        resume.set()
        app.dependency_overrides.pop(require_session_credential, None)
        await test_db_session.execute(
            delete(ApiKey).where(ApiKey.user_id == uuid.UUID(key_owner_id))
        )
        if dataset is not None:
            _, table_name, record_id = dataset
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table_name}")
            )
            await test_db_session.execute(delete(Record).where(Record.id == record_id))
        await test_db_session.commit()


async def test_reset_arriving_during_issuance_waits_and_invalidates_the_key(
    client: AsyncClient, admin_auth_header: dict, monkeypatch
):
    """A reset arriving mid-issuance waits for its commit, and the minted key then authenticates to 401."""
    headers, user_id = await create_user(client, admin_auth_header, "editor")
    minting = asyncio.Event()
    resume = asyncio.Event()
    mint = auth_service.create_api_key_for_user

    async def _wait_then_mint(*args, **kwargs):
        minting.set()
        await resume.wait()
        return await mint(*args, **kwargs)

    monkeypatch.setattr(auth_service, "create_api_key_for_user", _wait_then_mint)

    issuing = asyncio.ensure_future(
        client.post("/auth/api-keys/", json={"name": "racing"}, headers=headers)
    )
    resetting = None
    lock_wait = None
    try:
        await asyncio.wait_for(minting.wait(), timeout=30)
        resetting = asyncio.ensure_future(_reset(client, admin_auth_header, user_id))
        lock_wait = asyncio.ensure_future(await_lock_wait_query())
        await asyncio.wait(
            {resetting, lock_wait}, timeout=30, return_when=asyncio.FIRST_COMPLETED
        )
        reset_waited = lock_wait.done() and not resetting.done()
        resume.set()
        issued = await asyncio.wait_for(issuing, timeout=30)
        reset = await asyncio.wait_for(resetting, timeout=30)
    finally:
        resume.set()
        if lock_wait is not None and not lock_wait.cancel():
            lock_wait.exception()

    assert issued.status_code == 201, issued.text
    assert reset.status_code == 200, reset.text
    replay = await client.get("/auth/me/", headers={"X-Api-Key": issued.json()["key"]})
    assert replay.status_code == 401
    assert reset_waited, "the reset committed while issuance was in progress"
