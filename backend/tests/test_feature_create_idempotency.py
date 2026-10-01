"""A retried feature create must not insert a second row.

The dataset map resends a create whose outcome it could not see (a timeout, a
dropped connection). When the first attempt had already committed, the repeat
used to insert again. The client now sends one ``Idempotency-Key`` per sketch,
and the route answers a repeat with the feature that exists.
"""

import asyncio
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.middleware.cors import DynamicCORSMiddleware
from app.core.db.sqlstate import is_lock_conflict
from app.modules.catalog.features import router as features_router
from app.modules.catalog.features.idempotency import IDEMPOTENCY_KEY_MAX_LENGTH

from tests.conftest import _create_test_user
from tests.factories import create_dataset, get_user_id

PARIS = {"type": "Point", "coordinates": [2.35, 48.85]}
LONDON = {"type": "Point", "coordinates": [-0.13, 51.51]}


async def _create_point_table(
    session, table: str, *, unique_name: bool = False
) -> None:
    unique = " UNIQUE" if unique_name else ""
    await session.execute(
        text(
            f'CREATE TABLE "data"."{table}" (gid serial PRIMARY KEY, '
            "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326), "
            f"name text{unique})"
        )
    )


async def _seed_point_dataset(session, *, created_by, unique_name: bool = False):
    """A public, empty point dataset with a writable name column."""
    table = f"idem_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        session,
        created_by=created_by,
        table_name=table,
        record_type="vector_dataset",
        geometry_type="Point",
        feature_count=0,
        column_info=[{"name": "name", "type": "character varying"}],
    )
    await _create_point_table(session, table, unique_name=unique_name)
    await session.commit()
    return dataset


async def _drop(session, dataset) -> None:
    await session.execute(
        text("DELETE FROM catalog.feature_create_keys WHERE dataset_id = :id"),
        {"id": dataset.id},
    )
    await session.execute(text(f'DROP TABLE IF EXISTS "data"."{dataset.table_name}"'))
    await session.commit()


async def _row_count(session, dataset) -> int:
    return await session.scalar(
        text(f'SELECT count(*) FROM "data"."{dataset.table_name}"')
    )


async def _key_rows(session, dataset) -> int:
    return await session.scalar(
        text("SELECT count(*) FROM catalog.feature_create_keys WHERE dataset_id = :id"),
        {"id": dataset.id},
    )


def _create(
    client: AsyncClient,
    dataset,
    headers: dict,
    sketch: str | None,
    geometry=PARIS,
    *,
    attempt: int | None = None,
    properties: dict | None = None,
):
    sent = dict(headers)
    if sketch is not None:
        sent["Idempotency-Key"] = sketch
    if attempt is not None:
        sent["Idempotency-Attempt"] = str(attempt)
    return client.post(
        f"/datasets/{dataset.id}/features/",
        json={
            "geometry": geometry,
            "properties": {"name": "pin"} if properties is None else properties,
        },
        headers=sent,
    )


async def _stored_name(session, dataset) -> str | None:
    return await session.scalar(
        text(f'SELECT name FROM "data"."{dataset.table_name}" ORDER BY gid LIMIT 1')
    )


@pytest.fixture
async def admin_dataset(client: AsyncClient, admin_auth_header, test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _seed_point_dataset(test_db_session, created_by=admin_id)
    yield dataset
    await _drop(test_db_session, dataset)


async def test_a_retry_after_a_lost_response_returns_the_created_feature(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    """The first attempt commits, then fails before answering; the retry finds it."""

    class DroppedAfterCommit:
        async def invalidate_table(self, table: str) -> None:
            raise RuntimeError("connection dropped after the commit")

    sketch = f"sketch-{uuid.uuid4()}"
    with patch.object(features_router, "get_tile_cache", lambda: DroppedAfterCommit()):
        with pytest.raises(RuntimeError, match="dropped after the commit"):
            await _create(client, admin_dataset, admin_auth_header, sketch)
    assert await _row_count(test_db_session, admin_dataset) == 1

    invalidated: list[str] = []

    class RecordingCache:
        async def invalidate_table(self, table: str) -> None:
            invalidated.append(table)

    with patch.object(features_router, "get_tile_cache", lambda: RecordingCache()):
        retry = await _create(client, admin_dataset, admin_auth_header, sketch)

    assert retry.status_code == 201, retry.text
    assert await _row_count(test_db_session, admin_dataset) == 1
    stored = await test_db_session.scalar(
        text(f'SELECT gid FROM "data"."{admin_dataset.table_name}"')
    )
    body = retry.json()
    assert body["id"] == stored
    assert body["properties"]["name"] == "pin"
    assert body["geometry"]["coordinates"] == pytest.approx(PARIS["coordinates"])
    assert body["tile_cache_version"] == await test_db_session.scalar(
        text("SELECT tile_cache_version FROM catalog.datasets WHERE id = :id"),
        {"id": admin_dataset.id},
    )
    assert invalidated == [admin_dataset.table_name]
    assert (
        await test_db_session.scalar(
            text("SELECT feature_count FROM catalog.datasets WHERE id = :id"),
            {"id": admin_dataset.id},
        )
        == 1
    )


async def test_repeats_of_one_key_return_the_same_feature(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    sketch = uuid.uuid4().hex
    first = await _create(client, admin_dataset, admin_auth_header, sketch)
    second = await _create(client, admin_dataset, admin_auth_header, sketch)
    third = await _create(
        client, admin_dataset, admin_auth_header, sketch, geometry=LONDON
    )

    assert [r.status_code for r in (first, second, third)] == [201, 201, 201]
    assert second.json()["id"] == first.json()["id"] == third.json()["id"]
    assert await _row_count(test_db_session, admin_dataset) == 1


async def _await_lock_wait_query() -> str:
    """Block until some backend is parked on a lock, and return what it is running.

    Each poll uses its own session: a rollback on the test's session would
    expire the ORM objects the test still holds.
    """
    import app.core.db as db_module

    for _ in range(600):
        async with db_module.async_session() as probe:
            query = await probe.scalar(
                text(
                    "SELECT query FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' LIMIT 1"
                )
            )
        if query:
            return query
        await asyncio.sleep(0.01)
    raise AssertionError("no backend ever parked on a lock")


async def test_a_request_waits_out_an_in_flight_holder_of_its_key(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    """Two requests with one key overlap: one insert, both answered."""
    reached = asyncio.Event()
    release = asyncio.Event()
    real_refresh = features_router._refresh_metadata_guarded

    async def hold_before_commit(*args, **kwargs):
        reached.set()
        await release.wait()
        return await real_refresh(*args, **kwargs)

    sketch = uuid.uuid4().hex
    with patch.object(features_router, "_refresh_metadata_guarded", hold_before_commit):
        winner = asyncio.create_task(
            _create(client, admin_dataset, admin_auth_header, sketch)
        )
        await asyncio.wait_for(reached.wait(), timeout=10)
        loser = asyncio.create_task(
            _create(client, admin_dataset, admin_auth_header, sketch)
        )
        try:
            await _await_lock_wait_query()
            assert not loser.done()
        finally:
            release.set()
        responses = await asyncio.gather(winner, loser)

    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert await _row_count(test_db_session, admin_dataset) == 1
    assert await _key_rows(test_db_session, admin_dataset) == 1


async def test_a_retry_blocked_on_a_unique_value_resolves_to_the_first_feature(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """A unique attribute cannot make the same-key retry fail on its own insert.

    The retry waits for the first request before it writes anything, so its
    value never meets the first request's, and it answers with that feature
    instead of a 400.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _seed_point_dataset(
        test_db_session, created_by=admin_id, unique_name=True
    )
    reached = asyncio.Event()
    release = asyncio.Event()
    real_refresh = features_router._refresh_metadata_guarded

    async def hold_before_commit(*args, **kwargs):
        reached.set()
        await release.wait()
        return await real_refresh(*args, **kwargs)

    sketch = uuid.uuid4().hex
    try:
        with patch.object(
            features_router, "_refresh_metadata_guarded", hold_before_commit
        ):
            winner = asyncio.create_task(
                _create(client, dataset, admin_auth_header, sketch)
            )
            await asyncio.wait_for(reached.wait(), timeout=10)
            retry = asyncio.create_task(
                _create(client, dataset, admin_auth_header, sketch)
            )
            try:
                waiting_on = await _await_lock_wait_query()
                assert "pg_advisory_xact_lock" in waiting_on
            finally:
                release.set()
            responses = await asyncio.gather(winner, retry)

        assert [r.status_code for r in responses] == [201, 201], [
            r.text for r in responses
        ]
        assert responses[0].json()["id"] == responses[1].json()["id"]
        assert await _row_count(test_db_session, dataset) == 1
    finally:
        await _drop(test_db_session, dataset)


async def test_a_unique_violation_that_is_not_a_same_key_retry_is_still_refused(
    client: AsyncClient, admin_auth_header, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _seed_point_dataset(
        test_db_session, created_by=admin_id, unique_name=True
    )
    try:
        first = await _create(client, dataset, admin_auth_header, uuid.uuid4().hex)
        second = await _create(client, dataset, admin_auth_header, uuid.uuid4().hex)

        assert first.status_code == 201
        assert second.status_code == 400
        assert await _row_count(test_db_session, dataset) == 1
    finally:
        await _drop(test_db_session, dataset)


async def test_a_keyed_create_takes_the_catalog_rows_before_its_key_row(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    """The key row's foreign key must not take a shared lock on the dataset first.

    Two creates that each held that shared lock and then asked for the
    exclusive catalog lock would wait on each other. With the dataset row held
    by a third session, the create must park on the catalog lock itself, never
    on its key insert.
    """
    import app.core.db as db_module

    async with db_module.async_session() as holder:
        await holder.execute(
            text("SELECT id FROM catalog.datasets WHERE id = :id FOR UPDATE"),
            {"id": admin_dataset.id},
        )
        request = asyncio.create_task(
            _create(client, admin_dataset, admin_auth_header, uuid.uuid4().hex)
        )
        try:
            waiting_on = await _await_lock_wait_query()
        finally:
            await holder.rollback()
    response = await request

    assert "FOR UPDATE" in waiting_on
    assert "feature_create_keys" not in waiting_on
    assert response.status_code == 201, response.text


async def test_concurrent_creates_with_different_keys_all_insert(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    responses = await asyncio.gather(
        *(
            _create(client, admin_dataset, admin_auth_header, uuid.uuid4().hex)
            for _ in range(6)
        )
    )

    assert {r.status_code for r in responses} == {201}
    assert len({r.json()["id"] for r in responses}) == 6
    assert await _row_count(test_db_session, admin_dataset) == 6


async def test_concurrent_creates_with_one_key_insert_once(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    sketch = uuid.uuid4().hex
    responses = await asyncio.gather(
        *(_create(client, admin_dataset, admin_auth_header, sketch) for _ in range(6))
    )

    assert {r.status_code for r in responses} == {201}
    assert len({r.json()["id"] for r in responses}) == 1
    assert await _row_count(test_db_session, admin_dataset) == 1


async def test_a_repeat_after_the_feature_was_deleted_is_refused(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    sketch = uuid.uuid4().hex
    created = await _create(client, admin_dataset, admin_auth_header, sketch)
    deleted = await client.delete(
        f"/datasets/{admin_dataset.id}/features/{created.json()['id']}",
        headers=admin_auth_header,
    )
    assert deleted.status_code == 204

    repeat = await _create(client, admin_dataset, admin_auth_header, sketch)

    assert repeat.status_code == 409, repeat.text
    assert await _row_count(test_db_session, admin_dataset) == 0


async def test_a_repeat_after_the_table_was_replaced_is_refused(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    """A swap or overwrite recreates the table, so the stored gid names another row."""
    sketch = uuid.uuid4().hex
    created = await _create(client, admin_dataset, admin_auth_header, sketch)
    table = admin_dataset.table_name
    await test_db_session.execute(text(f'DROP TABLE "data"."{table}"'))
    await _create_point_table(test_db_session, table)
    await test_db_session.execute(
        text(
            f'INSERT INTO "data"."{table}" (gid, geom, geom_4326, name) VALUES '
            "(:gid, ST_SetSRID(ST_MakePoint(9, 9), 4326), "
            "ST_SetSRID(ST_MakePoint(9, 9), 4326), 'unrelated')"
        ),
        {"gid": created.json()["id"]},
    )
    await test_db_session.commit()

    repeat = await _create(client, admin_dataset, admin_auth_header, sketch, attempt=2)

    assert repeat.status_code == 409, repeat.text
    assert await _row_count(test_db_session, admin_dataset) == 1
    assert await _stored_name(test_db_session, admin_dataset) == "unrelated"


async def test_a_repeat_returns_the_feature_as_it_is_now(
    client: AsyncClient, admin_auth_header, admin_dataset
):
    """Editing the feature does not spend the key."""
    sketch = uuid.uuid4().hex
    created = await _create(client, admin_dataset, admin_auth_header, sketch)
    edited = await client.patch(
        f"/datasets/{admin_dataset.id}/features/{created.json()['id']}",
        json={"properties": {"name": "edited"}},
        headers=admin_auth_header,
    )
    assert edited.status_code == 200, edited.text

    repeat = await _create(client, admin_dataset, admin_auth_header, sketch)

    assert repeat.status_code == 201, repeat.text
    assert repeat.json()["id"] == created.json()["id"]
    assert repeat.json()["properties"]["name"] == "edited"


async def test_a_retry_with_an_edited_body_stores_the_edited_values(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    sketch = uuid.uuid4().hex
    first = await _create(client, admin_dataset, admin_auth_header, sketch, attempt=1)
    retry = await _create(
        client,
        admin_dataset,
        admin_auth_header,
        sketch,
        attempt=2,
        properties={"name": "edited"},
    )

    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == first.json()["id"]
    assert retry.json()["properties"]["name"] == "edited"
    assert await _stored_name(test_db_session, admin_dataset) == "edited"
    assert await _row_count(test_db_session, admin_dataset) == 1


async def test_a_later_attempt_leaves_the_properties_it_does_not_name(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    sketch = uuid.uuid4().hex
    await _create(client, admin_dataset, admin_auth_header, sketch, attempt=1)

    skipped = await _create(
        client, admin_dataset, admin_auth_header, sketch, attempt=2, properties={}
    )

    assert skipped.status_code == 201, skipped.text
    assert await _stored_name(test_db_session, admin_dataset) == "pin"


async def test_an_equal_or_lower_attempt_returns_the_stored_feature_unchanged(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    sketch = uuid.uuid4().hex
    await _create(client, admin_dataset, admin_auth_header, sketch, attempt=1)
    await _create(
        client,
        admin_dataset,
        admin_auth_header,
        sketch,
        attempt=3,
        properties={"name": "third"},
    )

    same = await _create(
        client,
        admin_dataset,
        admin_auth_header,
        sketch,
        attempt=3,
        properties={"name": "same attempt"},
    )
    older = await _create(
        client,
        admin_dataset,
        admin_auth_header,
        sketch,
        attempt=2,
        properties={"name": "older"},
    )

    assert same.json()["properties"]["name"] == "third"
    assert older.json()["properties"]["name"] == "third"
    assert await _stored_name(test_db_session, admin_dataset) == "third"


async def test_an_older_attempt_in_flight_cannot_commit_after_a_newer_one(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    """A straggler waits for the newer attempt and then finds it recorded."""
    sketch = uuid.uuid4().hex
    await _create(client, admin_dataset, admin_auth_header, sketch, attempt=1)
    reached = asyncio.Event()
    release = asyncio.Event()
    real_refresh = features_router._refresh_metadata_guarded

    async def hold_before_commit(*args, **kwargs):
        reached.set()
        await release.wait()
        return await real_refresh(*args, **kwargs)

    with patch.object(features_router, "_refresh_metadata_guarded", hold_before_commit):
        newer = asyncio.create_task(
            _create(
                client,
                admin_dataset,
                admin_auth_header,
                sketch,
                attempt=3,
                properties={"name": "third"},
            )
        )
        await asyncio.wait_for(reached.wait(), timeout=10)
        older = asyncio.create_task(
            _create(
                client,
                admin_dataset,
                admin_auth_header,
                sketch,
                attempt=2,
                properties={"name": "second"},
            )
        )
        try:
            await _await_lock_wait_query()
            assert not older.done()
        finally:
            release.set()
        responses = await asyncio.gather(newer, older)

    assert [r.status_code for r in responses] == [201, 201]
    assert [r.json()["properties"]["name"] for r in responses] == ["third", "third"]
    assert await _stored_name(test_db_session, admin_dataset) == "third"


async def _datasets_row_is_held(dataset) -> bool:
    import app.core.db as db_module

    async with db_module.async_session() as probe:
        try:
            await probe.execute(
                text(
                    "SELECT id FROM catalog.datasets WHERE id = :id FOR UPDATE NOWAIT"
                ),
                {"id": dataset.id},
            )
        except DBAPIError as exc:
            if is_lock_conflict(exc):
                return True
            raise
    return False


async def test_a_later_attempt_waits_for_a_patch_without_holding_the_catalog_rows(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    """A PATCH locks the feature and then the catalog rows.

    A later attempt that held the catalog rows while it waited for that feature
    would be the other half of a deadlock, and the PATCH's request for them
    would never be granted.
    """
    import app.core.db as db_module

    sketch = uuid.uuid4().hex
    created = await _create(client, admin_dataset, admin_auth_header, sketch, attempt=1)
    async with db_module.async_session() as patch:
        await patch.execute(
            text(
                f'SELECT gid FROM "data"."{admin_dataset.table_name}" '
                "WHERE gid = :gid FOR UPDATE"
            ),
            {"gid": created.json()["id"]},
        )
        retry = asyncio.create_task(
            _create(
                client,
                admin_dataset,
                admin_auth_header,
                sketch,
                attempt=2,
                properties={"name": "edited"},
            )
        )
        try:
            waiting_on = await _await_lock_wait_query()
            catalog_held = await _datasets_row_is_held(admin_dataset)
            # What the PATCH does next, once it has written the feature.
            await patch.execute(
                text("SELECT id FROM catalog.datasets WHERE id = :id FOR UPDATE"),
                {"id": admin_dataset.id},
            )
        finally:
            await patch.commit()
    response = await retry

    assert admin_dataset.table_name in waiting_on
    assert catalog_held is False
    assert response.status_code == 201, response.text
    assert response.json()["properties"]["name"] == "edited"


async def _patch_name(client: AsyncClient, dataset, headers: dict, gid: int, name):
    response = await client.patch(
        f"/datasets/{dataset.id}/features/{gid}",
        json={"properties": {"name": name}},
        headers=headers,
    )
    assert response.status_code == 200, response.text


async def test_a_later_attempt_does_not_overwrite_another_writers_edit(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    """The create's response is lost, someone else edits, then the user retries."""
    sketch = uuid.uuid4().hex
    created = await _create(client, admin_dataset, admin_auth_header, sketch, attempt=1)
    gid = created.json()["id"]
    await _patch_name(client, admin_dataset, admin_auth_header, gid, "theirs")

    refused = await _create(
        client,
        admin_dataset,
        admin_auth_header,
        sketch,
        attempt=2,
        properties={"name": "edited"},
    )
    again = await _create(
        client,
        admin_dataset,
        admin_auth_header,
        sketch,
        attempt=3,
        properties={"name": "edited again"},
    )
    unchanged = await _create(
        client, admin_dataset, admin_auth_header, sketch, attempt=1
    )

    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "feature_changed"
    assert detail["feature"]["id"] == gid
    assert detail["feature"]["properties"]["name"] == "theirs"
    assert again.status_code == 409
    assert unchanged.status_code == 201
    assert unchanged.json()["properties"]["name"] == "theirs"
    assert await _stored_name(test_db_session, admin_dataset) == "theirs"


async def test_an_edit_to_another_feature_does_not_block_a_later_attempt(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    sketch = uuid.uuid4().hex
    await _create(client, admin_dataset, admin_auth_header, sketch, attempt=1)
    other = await _create(client, admin_dataset, admin_auth_header, None)
    await _patch_name(
        client, admin_dataset, admin_auth_header, other.json()["id"], "someone else's"
    )

    retry = await _create(
        client,
        admin_dataset,
        admin_auth_header,
        sketch,
        attempt=2,
        properties={"name": "edited"},
    )

    assert retry.status_code == 201, retry.text
    assert retry.json()["properties"]["name"] == "edited"


async def test_successive_attempts_of_one_sketch_do_not_conflict_with_each_other(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    sketch = uuid.uuid4().hex
    await _create(client, admin_dataset, admin_auth_header, sketch, attempt=1)

    for attempt, name in ((2, "second"), (3, "third")):
        response = await _create(
            client,
            admin_dataset,
            admin_auth_header,
            sketch,
            attempt=attempt,
            properties={"name": name},
        )
        assert response.status_code == 201, response.text

    assert await _stored_name(test_db_session, admin_dataset) == "third"


async def test_a_later_attempt_waits_for_a_writer_in_flight_and_then_refuses(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    """The version is read under the row lock, so an uncommitted edit still counts."""
    import app.core.db as db_module

    sketch = uuid.uuid4().hex
    created = await _create(client, admin_dataset, admin_auth_header, sketch, attempt=1)
    async with db_module.async_session() as writer:
        await writer.execute(
            text(
                f'UPDATE "data"."{admin_dataset.table_name}" '
                "SET name = 'theirs' WHERE gid = :gid"
            ),
            {"gid": created.json()["id"]},
        )
        retry = asyncio.create_task(
            _create(
                client,
                admin_dataset,
                admin_auth_header,
                sketch,
                attempt=2,
                properties={"name": "edited"},
            )
        )
        try:
            await _await_lock_wait_query()
            assert not retry.done()
        finally:
            await writer.commit()
    response = await retry

    assert response.status_code == 409, response.text
    assert await _stored_name(test_db_session, admin_dataset) == "theirs"


async def test_a_retry_waiting_for_the_table_holds_nothing_deleting_the_dataset_needs(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    """Deleting a dataset takes the data table, then cascades into its key rows.

    A retry that held its key row while it waited for the table would be the
    other half of a deadlock with that delete.
    """
    import app.core.db as db_module

    sketch = uuid.uuid4().hex
    await _create(client, admin_dataset, admin_auth_header, sketch, attempt=1)
    async with db_module.async_session() as deleter:
        await deleter.execute(
            text(
                f'LOCK TABLE "data"."{admin_dataset.table_name}" IN ACCESS EXCLUSIVE MODE'
            )
        )
        retry = asyncio.create_task(
            _create(
                client,
                admin_dataset,
                admin_auth_header,
                sketch,
                attempt=2,
                properties={"name": "edited"},
            )
        )
        try:
            waiting_on = await _await_lock_wait_query()
            await deleter.execute(text("SET LOCAL lock_timeout = '1s'"))
            # What the delete does after the table: remove the dataset's key rows.
            await deleter.execute(
                text("DELETE FROM catalog.feature_create_keys WHERE dataset_id = :id"),
                {"id": admin_dataset.id},
            )
        finally:
            await deleter.commit()
    response = await retry

    assert admin_dataset.table_name in waiting_on
    assert response.status_code == 201, response.text


async def test_a_later_attempt_is_validated_like_a_create(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    sketch = uuid.uuid4().hex
    await _create(client, admin_dataset, admin_auth_header, sketch, attempt=1)

    refused = await _create(
        client,
        admin_dataset,
        admin_auth_header,
        sketch,
        attempt=2,
        properties={"no_such_column": "x"},
    )
    created_without_key = await _create(
        client,
        admin_dataset,
        admin_auth_header,
        None,
        properties={"no_such_column": "x"},
    )

    assert refused.status_code == created_without_key.status_code
    assert refused.status_code >= 400
    assert await _stored_name(test_db_session, admin_dataset) == "pin"


@pytest.mark.parametrize("attempt", ["0", "-1", "abc", "2147483648", ""])
async def test_an_invalid_attempt_number_is_refused_before_anything_is_written(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session, attempt
):
    refused = await client.post(
        f"/datasets/{admin_dataset.id}/features/",
        json={"geometry": PARIS, "properties": {"name": "pin"}},
        headers={
            **admin_auth_header,
            "Idempotency-Key": uuid.uuid4().hex,
            "Idempotency-Attempt": attempt,
        },
    )

    assert refused.status_code == 422, refused.text
    assert await _row_count(test_db_session, admin_dataset) == 0


async def test_keys_are_scoped_to_the_user(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """Another user's key neither returns nor blocks this user's feature."""
    owner_headers, owner_id = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    dataset = await _seed_point_dataset(test_db_session, created_by=uuid.UUID(owner_id))
    try:
        sketch = uuid.uuid4().hex
        owners = await _create(client, dataset, owner_headers, sketch)
        admins = await _create(
            client, dataset, admin_auth_header, sketch, geometry=LONDON
        )

        assert owners.status_code == admins.status_code == 201
        assert owners.json()["id"] != admins.json()["id"]
        assert admins.json()["geometry"]["coordinates"] == pytest.approx(
            LONDON["coordinates"]
        )
        assert await _row_count(test_db_session, dataset) == 2

        owners_again = await _create(client, dataset, owner_headers, sketch)
        admins_again = await _create(client, dataset, admin_auth_header, sketch)
        assert owners_again.json()["id"] == owners.json()["id"]
        assert admins_again.json()["id"] == admins.json()["id"]
        assert await _row_count(test_db_session, dataset) == 2
    finally:
        await _drop(test_db_session, dataset)


async def test_a_caller_who_lost_write_access_cannot_replay_their_key(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """The access check runs before the key lookup, so a stored key reveals nothing."""
    owner_headers, owner_id = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    dataset = await _seed_point_dataset(test_db_session, created_by=uuid.UUID(owner_id))
    try:
        sketch = uuid.uuid4().hex
        assert (
            await _create(client, dataset, owner_headers, sketch)
        ).status_code == 201
        await test_db_session.execute(
            text("UPDATE catalog.records SET created_by = :admin WHERE id = :id"),
            {
                "admin": await get_user_id(test_db_session, "admin"),
                "id": dataset.record_id,
            },
        )
        await test_db_session.commit()

        refused = await _create(client, dataset, owner_headers, sketch)

        assert refused.status_code == 403
        assert "geometry" not in refused.json()
        assert await _row_count(test_db_session, dataset) == 1
    finally:
        await _drop(test_db_session, dataset)


async def test_without_the_header_every_request_inserts(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    first = await _create(client, admin_dataset, admin_auth_header, None)
    second = await _create(client, admin_dataset, admin_auth_header, None)

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert await _row_count(test_db_session, admin_dataset) == 2
    assert await _key_rows(test_db_session, admin_dataset) == 0


@pytest.mark.parametrize(
    "sketch",
    [
        "x" * (IDEMPOTENCY_KEY_MAX_LENGTH + 1),
        "has space",
        "semi;colon",
        "quote'",
        "",
    ],
)
async def test_an_invalid_key_is_refused_before_anything_is_written(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session, sketch
):
    refused = await _create(client, admin_dataset, admin_auth_header, sketch)

    assert refused.status_code == 422, refused.text
    assert await _row_count(test_db_session, admin_dataset) == 0
    assert await _key_rows(test_db_session, admin_dataset) == 0


async def test_the_longest_key_is_accepted(
    client: AsyncClient, admin_auth_header, admin_dataset
):
    sketch = "a" * IDEMPOTENCY_KEY_MAX_LENGTH
    assert (
        await _create(client, admin_dataset, admin_auth_header, sketch)
    ).status_code == 201


async def test_an_expired_key_is_taken_over_and_old_rows_are_pruned(
    client: AsyncClient, admin_auth_header, admin_dataset, test_db_session
):
    """A key stops matching after its retention, and old rows do not pile up."""
    expired_before = await test_db_session.scalar(
        text(
            "SELECT count(*) FROM catalog.feature_create_keys "
            "WHERE created_at < now() - interval '24 hours'"
        )
    )
    stale_key = uuid.uuid4().hex
    admin_id = await get_user_id(test_db_session, "admin")
    await test_db_session.execute(
        text(
            "INSERT INTO catalog.feature_create_keys "
            "(dataset_id, user_id, key, gid, table_oid, attempt, row_xmin, created_at) "
            "SELECT CAST(:dataset_id AS uuid), CAST(:user_id AS uuid), "
            "CASE WHEN n = 0 THEN CAST(:stale AS text) ELSE 'old-' || n END, "
            "987654, 1, 1, 1, now() - interval '25 hours' "
            "FROM generate_series(0, 104) AS n"
        ),
        {"dataset_id": admin_dataset.id, "user_id": admin_id, "stale": stale_key},
    )
    await test_db_session.commit()

    created = await _create(client, admin_dataset, admin_auth_header, stale_key)

    assert created.status_code == 201, created.text
    assert created.json()["id"] != 987654
    assert await _row_count(test_db_session, admin_dataset) == 1
    row = (
        await test_db_session.execute(
            text(
                "SELECT gid, created_at > now() - interval '1 hour' "
                "FROM catalog.feature_create_keys "
                "WHERE dataset_id = :id AND key = :key"
            ),
            {"id": admin_dataset.id, "key": stale_key},
        )
    ).one()
    assert row == (created.json()["id"], True)
    expired_after = await test_db_session.scalar(
        text(
            "SELECT count(*) FROM catalog.feature_create_keys "
            "WHERE created_at < now() - interval '24 hours'"
        )
    )
    # 105 expired rows went in and one of them was taken over as a live key,
    # so the batch bound leaves 104 - 100 of this test's rows behind.
    assert expired_after - expired_before == 4


def test_the_key_headers_are_published_as_plain_optional_values():
    """A nullable schema makes generated clients accept None and then send it."""
    from app.api.main import app

    parameters = {
        p["name"]: p
        for p in app.openapi()["paths"]["/datasets/{dataset_id}/features/"]["post"][
            "parameters"
        ]
    }

    for name, kind in (
        ("Idempotency-Key", "string"),
        ("Idempotency-Attempt", "integer"),
    ):
        header = parameters[name]
        assert header["in"] == "header"
        assert header["required"] is False
        assert header["schema"]["type"] == kind
        assert "anyOf" not in header["schema"]


def test_the_credentialed_cors_policy_allows_the_key_headers():
    """A separate web origin can send them; without them the preflight fails."""
    from starlette.responses import Response

    response = Response()
    DynamicCORSMiddleware._set_cors_headers(response, "https://app.example.com")

    allowed = response.headers["Access-Control-Allow-Headers"]
    assert "Idempotency-Key" in allowed
    assert "Idempotency-Attempt" in allowed


async def test_the_table_lookups_bind_a_tenant_role_holding_their_privilege(
    monkeypatch,
):
    """Multi-tenant: the runtime login has no data-schema privilege of its own."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.core.db.tenant_session import (
        _before_tenant_cursor_execute,
        current_tenant_var,
    )
    from app.modules.catalog.features.idempotency import (
        current_row_xmin,
        current_table_oid,
    )

    tenant = "00000000-0000-0000-0000-000000000001"
    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)
    roles = []
    token = current_tenant_var.set(tenant)
    try:
        await current_table_oid(db, "roads")
        await current_row_xmin(db, "roads", 1, lock=True)
        for call in db.scalar.await_args_list:
            statement, params = call.args
            cursor = MagicMock()
            _before_tenant_cursor_execute(
                object(), cursor, str(statement), params, SimpleNamespace(), False
            )
            roles += [c.args[0] for c in cursor.execute.call_args_list]
    finally:
        current_tenant_var.reset(token)

    suffix = tenant.replace("-", "_")
    assert roles == [
        f'SET LOCAL ROLE "geolens_reader_t_{suffix}"',
        f'SET LOCAL ROLE "geolens_writer_t_{suffix}"',
    ]
