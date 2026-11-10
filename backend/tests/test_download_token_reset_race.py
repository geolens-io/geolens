"""A password reset racing download-token issuance never leaves a usable token."""

import asyncio
import uuid
from typing import Annotated

import pytest
from fastapi import Depends, Request
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_db
from app.modules.auth.dependencies import get_optional_user, oauth2_scheme_optional
from app.modules.auth.models import User
from app.modules.auth.service import AuthService
from tests.conftest import _create_test_user
from tests.lock_wait import await_lock_wait_query
from tests.test_download_token import _create_local_raster_dataset

pytestmark = pytest.mark.anyio


def _reset(client: AsyncClient, admin_auth_header: dict, user_id: str):
    return client.post(
        f"/admin/users/{user_id}/reset-password/",
        json={"password": f"Aa1-not-a-real-reset-{uuid.uuid4().hex[:8]}"},
        headers=admin_auth_header,
    )


async def _public_raster(test_db_session) -> uuid.UUID:
    admin = (
        await test_db_session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
    ).scalar_one()
    _, dataset, _ = await _create_local_raster_dataset(
        test_db_session, created_by=admin.id, visibility="public"
    )
    return dataset.id


async def test_reset_committed_after_admission_refuses_the_download_token(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """A reset committing between sign-in and minting gets the caller a 401 and no token."""
    from app.api.main import app

    dataset_id = await _public_raster(test_db_session)
    headers, user_id = await _create_test_user(client, admin_auth_header, "editor")
    admitted = asyncio.Event()
    resume = asyncio.Event()

    async def _admit_then_wait(
        request: Request,
        token: Annotated[str | None, Depends(oauth2_scheme_optional)],
        db: AsyncSession = Depends(get_db),
    ):
        identity = await get_optional_user(request, token, db)
        if identity is not None and str(identity.id) == user_id:
            admitted.set()
            await resume.wait()
        return identity

    app.dependency_overrides[get_optional_user] = _admit_then_wait
    try:
        minting = asyncio.ensure_future(
            client.post(f"/auth/download-token/{dataset_id}", headers=headers)
        )
        await asyncio.wait_for(admitted.wait(), timeout=30)
        reset = await _reset(client, admin_auth_header, user_id)
        assert reset.status_code == 200, reset.text
        resume.set()
        resp = await asyncio.wait_for(minting, timeout=30)
    finally:
        resume.set()
        app.dependency_overrides.pop(get_optional_user, None)

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "Could not validate credentials"
    assert resp.headers["WWW-Authenticate"] == "Bearer"
    assert "token" not in resp.json()


async def test_reset_arriving_during_minting_waits_and_revokes_the_token(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """A reset arriving mid-mint waits for the mint to finish, and the token then gets 401 on download."""
    dataset_id = await _public_raster(test_db_session)
    headers, user_id = await _create_test_user(client, admin_auth_header, "editor")
    minting_started = asyncio.Event()
    resume = asyncio.Event()
    mint = AuthService.create_download_token

    async def _wait_then_mint(self, *args, **kwargs):
        minting_started.set()
        await resume.wait()
        return await mint(self, *args, **kwargs)

    monkeypatch.setattr(AuthService, "create_download_token", _wait_then_mint)

    minting = asyncio.ensure_future(
        client.post(f"/auth/download-token/{dataset_id}", headers=headers)
    )
    resetting = None
    lock_wait = None
    try:
        await asyncio.wait_for(minting_started.wait(), timeout=30)
        resetting = asyncio.ensure_future(_reset(client, admin_auth_header, user_id))
        lock_wait = asyncio.ensure_future(await_lock_wait_query())
        await asyncio.wait(
            {resetting, lock_wait}, timeout=30, return_when=asyncio.FIRST_COMPLETED
        )
        reset_waited = (
            lock_wait.done()
            and not lock_wait.cancelled()
            and lock_wait.exception() is None
            and not resetting.done()
        )
        resume.set()
        issued = await asyncio.wait_for(minting, timeout=30)
        reset = await asyncio.wait_for(resetting, timeout=30)
    finally:
        resume.set()
        if lock_wait is not None and not lock_wait.cancel():
            lock_wait.exception()

    assert issued.status_code == 200, issued.text
    assert reset.status_code == 200, reset.text
    download = await client.get(
        f"/datasets/{dataset_id}/download/cog?token={issued.json()['token']}",
        follow_redirects=False,
    )
    assert download.status_code == 401, download.text
    assert reset_waited, "the reset committed while minting was in progress"
