"""Regression: seed_initial_admin must be concurrency-safe.

Prod runs `uvicorn --workers N`; on a fresh DB every worker runs the lifespan
and races the count-check + INSERT in seed_initial_admin(). Before the
advisory-lock fix two workers both saw count==0 and both INSERTed → one hit
`UniqueViolationError` on uq_users_username_global → the admin row never
committed → admin/admin login returned 401 on every fresh self-hosted install
(caught by the v1.4.0-rc.1 prod-smoke gate).

The fix serializes seeders on a Postgres xact-scoped advisory lock. This test
proves the lock is actually taken: it holds that same advisory key on a separate
connection and asserts seed_initial_admin() *blocks* until the key is released,
then completes and creates exactly one admin. Deterministic — it forces the
contention rather than racing asyncio's scheduler (a plain gather() of seeds
serializes by luck and would pass even without the lock).
"""

import asyncio

import pytest
from sqlalchemy import func, select, text

import app.api.main as main_module
import app.core.db as db_module
from app.api.main import _ADMIN_SEED_LOCK_KEY, seed_initial_admin
from app.core.config import settings
from app.modules.auth.models import User

pytestmark = pytest.mark.anyio


async def test_seed_blocks_on_advisory_lock(test_db_session, monkeypatch):
    # seed_initial_admin() resolves `async_session` from app.api.main's
    # namespace; the client fixture only patches app.core.db.async_session, so
    # repoint the seed at the same test engine.
    monkeypatch.setattr(main_module, "async_session", db_module.async_session)

    # Fresh-DB state (count==0) — the only state the prod guard seeds in.
    await test_db_session.execute(text("TRUNCATE TABLE catalog.users CASCADE"))
    await test_db_session.commit()

    # Hold the seed's advisory key on an independent connection, mimicking
    # "worker A is mid-seed". The lock is xact-scoped, so it's held until we
    # roll back this transaction.
    holder = await db_module.engine.connect()
    await holder.execute(
        text("SELECT pg_advisory_xact_lock(:k)"), {"k": _ADMIN_SEED_LOCK_KEY}
    )

    try:
        seed = asyncio.ensure_future(seed_initial_admin())
        # With the lock taken, the seed must block here. Give it room to run;
        # if the code skipped the lock it would finish and seed within this window.
        await asyncio.sleep(0.5)
        assert not seed.done(), "seed_initial_admin did not block on the advisory lock"
    finally:
        await holder.rollback()  # release the lock
        await holder.close()

    # Now the seed can proceed.
    await asyncio.wait_for(seed, timeout=10)

    count = (
        await test_db_session.execute(
            select(func.count())
            .select_from(User)
            .where(User.username == settings.geolens_admin_username)
        )
    ).scalar()
    assert count == 1
