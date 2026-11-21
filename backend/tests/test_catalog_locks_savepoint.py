"""A row lock taken in a savepoint, whose failed wait costs only the savepoint."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

import app.core.db as db_module
from app.modules.auth.models import User
from app.modules.catalog.collections.models import Collection
from app.platform.catalog_locks import lock_row_in_savepoint

pytestmark = pytest.mark.anyio


async def _collection(session, name: str) -> Collection:
    admin = (
        await session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    collection = Collection(name=name, created_by=admin.id)
    session.add(collection)
    await session.commit()
    return collection


async def _budget(session) -> str:
    return await session.scalar(text("SELECT current_setting('lock_timeout')"))


@pytest.mark.parametrize("held", [True, False], ids=["held", "free"])
async def test_a_savepoint_lock_keeps_the_callers_work_and_budget(
    test_db_session, clean_tables, held
):
    collection = await _collection(test_db_session, f"savepoint-{held}")
    row = select(Collection.id).where(Collection.id == collection.id)
    await test_db_session.execute(text("SET LOCAL lock_timeout = '1234ms'"))
    # Uncommitted work of the caller's, which a failed wait must not undo.
    test_db_session.add(Collection(name=f"pending-{held}", created_by=None))
    await test_db_session.flush()

    async with db_module.async_session() as holder:
        if held:
            await holder.execute(
                text("SELECT id FROM catalog.collections WHERE id = :id FOR UPDATE"),
                {"id": collection.id},
            )
        taken = await lock_row_in_savepoint(
            test_db_session, row.with_for_update(key_share=True), lock_timeout="200ms"
        )
        await holder.rollback()

    assert taken is not held
    assert await _budget(test_db_session) == "1234ms"
    assert await test_db_session.scalar(
        select(Collection.id).where(Collection.name == f"pending-{held}")
    )
    await test_db_session.rollback()
