"""fix(#435): quota usage for a page of users costs one aggregate, not one per user.

The admin user list labelled its loading "batch" and then called
`get_user_quota_usage()` once per row, at up to 200 rows per page. Each call ran its
own aggregate across records, datasets, and assets, plus two persistent-config reads.
"""

import uuid

import pytest
from sqlalchemy import event

from app.modules.quota.service import get_user_quota_usage, get_user_quota_usage_bulk


class _QueryCounter:
    """Count SQL statements issued on a session's sync engine."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, *args, **kwargs) -> None:
        self.count += 1


async def _count_queries(session, coro_factory):
    counter = _QueryCounter()
    sync_engine = session.bind.sync_engine
    event.listen(sync_engine, "before_cursor_execute", counter)
    try:
        result = await coro_factory()
    finally:
        event.remove(sync_engine, "before_cursor_execute", counter)
    return result, counter.count


async def test_bulk_usage_matches_single_user_usage(test_db_session) -> None:
    """The batched aggregate must agree with the per-user one it replaces."""
    from app.modules.auth.models import User

    user = User(username=f"quota-{uuid.uuid4().hex[:8]}", password_hash="x")
    test_db_session.add(user)
    await test_db_session.flush()

    single = await get_user_quota_usage(test_db_session, user.id)
    bulk = await get_user_quota_usage_bulk(test_db_session, [user.id])

    assert bulk[user.id] == single


async def test_bulk_usage_zeroes_users_with_no_records(test_db_session) -> None:
    """A user absent from the aggregate still gets a row, so callers can index it."""
    missing = uuid.uuid4()

    usage = await get_user_quota_usage_bulk(test_db_session, [missing])

    assert usage[missing].bytes_used == 0
    assert usage[missing].dataset_count == 0


async def test_bulk_usage_of_empty_list_is_free(test_db_session) -> None:
    assert await get_user_quota_usage_bulk(test_db_session, []) == {}


@pytest.mark.parametrize("user_count", [1, 25])
async def test_bulk_usage_query_count_is_constant(test_db_session, user_count) -> None:
    """Query count must not grow with the page size — the whole point of the fix."""
    from app.modules.auth.models import User

    users = [
        User(username=f"quota-{uuid.uuid4().hex[:8]}", password_hash="x")
        for _ in range(user_count)
    ]
    test_db_session.add_all(users)
    await test_db_session.flush()
    user_ids = [u.id for u in users]

    _, queries = await _count_queries(
        test_db_session, lambda: get_user_quota_usage_bulk(test_db_session, user_ids)
    )

    # One aggregate + at most two persistent-config reads for the caps.
    assert queries <= 3, (
        f"{queries} queries for {user_count} users — the aggregate is running per user"
    )
