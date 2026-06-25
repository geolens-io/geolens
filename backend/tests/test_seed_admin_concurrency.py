"""Regression: the boot-time seeders must be concurrency-safe.

Prod runs `uvicorn --workers N`; on a fresh DB every worker runs the lifespan
and races the SELECT-then-INSERT in seed_roles() and seed_initial_admin().
Before the advisory-lock fix two workers both saw a row missing and both
INSERTed → one hit `UniqueViolationError` (roles.name or uq_users_username_global)
→ that worker's startup crashed / the admin row never committed → admin/admin
login returned 401 on every fresh self-hosted install (caught by the
v1.4.0-rc.1 prod-smoke gate). seed_roles runs *first*, so it must be guarded
too — otherwise a colliding worker dies there before reaching the admin seed.

The fix serializes both seeders on one Postgres xact-scoped advisory key. These
tests prove the lock is actually taken: they hold that key on a separate
connection and assert each seeder *blocks* until the key is released, then
completes correctly. Deterministic — they force the contention rather than
racing asyncio's scheduler (a plain gather() of seeds serializes by luck and
would pass even without the lock).
"""

import asyncio

import pytest
from sqlalchemy import func, select, text

import app.api.main as main_module
import app.core.db as db_module
from app.api.main import (
    DEFAULT_ROLES,
    _SEED_LOCK_KEY,
    seed_initial_admin,
    seed_roles,
)
from app.core.config import settings
from app.modules.auth.models import Role, User

pytestmark = pytest.mark.anyio


async def _assert_blocks_until_lock_released(seed_coro_factory):
    """Hold the seed advisory key on an independent connection (mimicking
    "another worker is mid-seed"), then assert the seeder blocks until released.

    Returns once the seeder has run to completion against the released lock.
    """
    holder = await db_module.engine.connect()
    await holder.execute(
        text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SEED_LOCK_KEY}
    )
    try:
        task = asyncio.ensure_future(seed_coro_factory())
        # With the lock held, the seeder must block on its own lock acquisition.
        # Give it room; if the code skipped the lock it would finish here.
        await asyncio.sleep(0.5)
        assert not task.done(), "seeder did not block on the advisory lock"
    finally:
        await holder.rollback()  # release the xact-scoped lock
        await holder.close()
    await asyncio.wait_for(task, timeout=10)


async def test_seed_initial_admin_blocks_on_advisory_lock(test_db_session, monkeypatch):
    # seed_initial_admin() resolves `async_session` from app.api.main's namespace;
    # the client fixture only patches app.core.db.async_session, so repoint the
    # seed at the same test engine — otherwise it writes to the default DB.
    monkeypatch.setattr(main_module, "async_session", db_module.async_session)

    # Fresh-DB state (count==0) — the only state the prod guard seeds in. CASCADE
    # clears user_roles; the roles table survives (the client fixture seeded the
    # "admin" role seed_initial_admin requires). Self-healing: the seed recreates
    # the admin + its role link below.
    await test_db_session.execute(text("TRUNCATE TABLE catalog.users CASCADE"))
    await test_db_session.commit()

    await _assert_blocks_until_lock_released(seed_initial_admin)

    count = (
        await test_db_session.execute(
            select(func.count())
            .select_from(User)
            .where(User.username == settings.geolens_admin_username)
        )
    ).scalar()
    assert count == 1


async def test_seed_roles_blocks_on_advisory_lock(test_db_session, monkeypatch):
    # seed_roles runs in the lifespan BEFORE seed_initial_admin and has the same
    # SELECT-then-INSERT race on the unique roles.name. It must take the lock too.
    # No TRUNCATE: the seeder acquires the lock before its SELECT loop, so it
    # blocks regardless of whether rows already exist — and truncating
    # catalog.roles CASCADE would strip the admin's role link without the fixture
    # re-linking it, poisoning the shared per-worker DB for later tests.
    monkeypatch.setattr(main_module, "async_session", db_module.async_session)

    await _assert_blocks_until_lock_released(seed_roles)

    present = (
        (
            await test_db_session.execute(
                select(Role.name).where(
                    Role.name.in_([r["name"] for r in DEFAULT_ROLES])
                )
            )
        )
        .scalars()
        .all()
    )
    assert set(present) == {r["name"] for r in DEFAULT_ROLES}
