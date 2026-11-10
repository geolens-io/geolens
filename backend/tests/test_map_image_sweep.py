"""Map thumbnail and social-card objects no map row names are swept away.

The map rows decide what is kept, so the lookups run against the test
database. Storage is a fake. Every age is a timestamp the test sets.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin import story_asset_jobs
from app.modules.catalog.maps.image_sweep import (
    _MAX_DELETES_PER_PASS,
    ORPHAN_OBJECT_MIN_AGE,
    sweep_unnamed_map_image_objects,
)
from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.service_crud import new_map_asset_key
from tests.factories import get_user_id
from tests.test_story_asset_sweep import FakeStorage

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
OLD = NOW - ORPHAN_OBJECT_MIN_AGE - timedelta(hours=1)
YOUNG = NOW - timedelta(minutes=30)
PREFIXES = ("maps/thumbnails", "maps/og-images")
COLUMNS = ("thumbnail_uri", "og_image_uri")

_maps: list[uuid.UUID] = []


async def _map(session: AsyncSession, **image_columns: str) -> uuid.UUID:
    map_obj = Map(
        name=f"Sweep {uuid.uuid4().hex[:8]}",
        visibility="private",
        created_by=await get_user_id(session, "admin"),
        **image_columns,
    )
    session.add(map_obj)
    await session.commit()
    _maps.append(map_obj.id)
    return map_obj.id


@pytest.fixture(autouse=True)
async def _cleanup(test_db_session: AsyncSession):
    yield
    await test_db_session.execute(delete(Map).where(Map.id.in_(_maps)))
    await test_db_session.commit()
    _maps.clear()


async def _run(session: AsyncSession, storage: FakeStorage):
    with patch("app.platform.storage.get_storage", return_value=storage):
        return await sweep_unnamed_map_image_objects(session, now=NOW)


async def test_only_old_unnamed_objects_are_deleted_under_both_prefixes(
    test_db_session: AsyncSession,
) -> None:
    map_id = uuid.uuid4()
    named = {
        column: new_map_asset_key(prefix, map_id, "jpg")
        for prefix, column in zip(PREFIXES, COLUMNS, strict=True)
    }
    await _map(test_db_session, **named)
    orphans = {new_map_asset_key(prefix, map_id, "png") for prefix in PREFIXES}
    in_flight = {new_map_asset_key(prefix, map_id, "jpg") for prefix in PREFIXES}
    storage = FakeStorage(
        {key: OLD for key in orphans | set(named.values())}
        | {key: YOUNG for key in in_flight}
    )

    outcome = await _run(test_db_session, storage)

    assert set(storage.deleted) == orphans
    assert set(storage.objects) == set(named.values()) | in_flight
    assert outcome.skipped_live == 2
    assert outcome.skipped_recent == 2


async def test_an_older_unversioned_key_a_row_names_is_kept(
    test_db_session: AsyncSession,
) -> None:
    map_id = uuid.uuid4()
    legacy = {
        column: f"{prefix}/{map_id}.png"
        for prefix, column in zip(PREFIXES, COLUMNS, strict=True)
    }
    await _map(test_db_session, **legacy)
    unnamed = f"maps/thumbnails/{uuid.uuid4()}.jpg"
    storage = FakeStorage({key: OLD for key in {*legacy.values(), unnamed}})

    await _run(test_db_session, storage)

    assert set(storage.objects) == set(legacy.values())


async def test_a_tenant_prefixed_object_matches_the_logical_key_its_row_names(
    test_db_session: AsyncSession,
) -> None:
    tenant = "tenants/7d4e1f0a-0000-4000-8000-000000000001/"
    named = new_map_asset_key("maps/thumbnails", uuid.uuid4(), "jpg")
    await _map(test_db_session, thumbnail_uri=named)
    orphan = new_map_asset_key("maps/thumbnails", uuid.uuid4(), "jpg")
    storage = FakeStorage({f"{tenant}{named}": OLD, f"{tenant}{orphan}": OLD})

    with patch(
        "app.platform.jobs.orphan_scan.resolve_current_storage_key",
        lambda key: f"{tenant}{key}",
    ):
        await _run(test_db_session, storage)

    assert set(storage.objects) == {f"{tenant}{named}"}


async def test_a_key_named_by_the_other_column_is_kept(
    test_db_session: AsyncSession,
) -> None:
    crossed = new_map_asset_key("maps/thumbnails", uuid.uuid4(), "jpg")
    await _map(test_db_session, og_image_uri=crossed)
    storage = FakeStorage({crossed: OLD})

    await _run(test_db_session, storage)

    assert set(storage.objects) == {crossed}


async def test_an_object_whose_map_is_gone_is_deleted(
    test_db_session: AsyncSession,
) -> None:
    await _map(test_db_session)
    orphan = new_map_asset_key("maps/og-images", uuid.uuid4(), "jpg")
    storage = FakeStorage({orphan: OLD})

    await _run(test_db_session, storage)

    assert storage.objects == {}


async def test_keys_that_are_not_map_images_are_left_alone(
    test_db_session: AsyncSession,
) -> None:
    map_id = await _map(test_db_session)
    others = {
        f"maps/thumbnails/{map_id}-{uuid.uuid4().hex}.webp",
        f"maps/thumbnails/not-a-uuid-{uuid.uuid4().hex}.jpg",
        f"maps/og-images/{map_id}-{uuid.uuid4().hex}.jpg/inner.jpg",
        f"maps/og-images/{map_id}-{uuid.uuid4().hex[:8]}.jpg",
        f"maps/icons/{uuid.uuid4()}.png",
        f"maps/{map_id}.png",
    }
    storage = FakeStorage({key: OLD for key in others})

    await _run(test_db_session, storage)

    assert set(storage.objects) == others


async def test_an_object_a_row_takes_after_the_listing_is_kept(
    test_db_session: AsyncSession,
) -> None:
    map_id = await _map(test_db_session)
    racing = new_map_asset_key("maps/thumbnails", map_id, "jpg")
    storage = FakeStorage({racing: OLD})
    original = storage.iter_object_pages

    async def name_it_during_the_recheck(prefix: str, *, start_after=None):
        if prefix == racing:
            await test_db_session.execute(
                update(Map).where(Map.id == map_id).values(thumbnail_uri=racing)
            )
        async for page in original(prefix, start_after=start_after):
            yield page

    storage.iter_object_pages = name_it_during_the_recheck

    await _run(test_db_session, storage)

    assert set(storage.objects) == {racing}


async def test_a_failed_delete_is_counted_and_the_pass_goes_on(
    test_db_session: AsyncSession,
) -> None:
    map_id = await _map(test_db_session)
    stuck, gone = sorted(
        new_map_asset_key("maps/thumbnails", map_id, "jpg") for _ in range(2)
    )
    storage = FakeStorage({stuck: OLD, gone: OLD})
    storage.failing.add(stuck)

    outcome = await _run(test_db_session, storage)

    assert set(storage.objects) == {stuck}
    assert outcome.delete_failures == 1


async def test_thumbnails_that_keep_failing_do_not_hold_back_social_cards(
    test_db_session: AsyncSession,
) -> None:
    map_id = await _map(test_db_session)
    stuck = {
        new_map_asset_key("maps/thumbnails", map_id, "jpg")
        for _ in range(_MAX_DELETES_PER_PASS)
    }
    social = new_map_asset_key("maps/og-images", map_id, "jpg")
    storage = FakeStorage({key: OLD for key in stuck | {social}})
    storage.failing |= stuck

    await _run(test_db_session, storage)

    assert set(storage.objects) == stuck


async def test_a_listing_failure_ends_the_pass_without_raising(
    test_db_session: AsyncSession,
) -> None:
    await _map(test_db_session)
    storage = FakeStorage({})

    async def unavailable(prefix: str, *, start_after=None):
        raise OSError("storage unavailable")
        yield []

    storage.iter_object_pages = unavailable

    outcome = await _run(test_db_session, storage)

    assert not outcome.ran


async def test_nothing_is_swept_while_the_catalog_has_no_maps(
    test_db_session: AsyncSession,
) -> None:
    orphan = new_map_asset_key("maps/thumbnails", uuid.uuid4(), "jpg")
    storage = FakeStorage({orphan: OLD})

    async def no_maps(_db) -> bool:
        return False

    with patch("app.modules.catalog.maps.image_sweep._catalog_has_maps", no_maps):
        outcome = await _run(test_db_session, storage)

    assert set(storage.objects) == {orphan}
    assert not outcome.ran


async def test_the_scheduled_sweep_runs_the_map_image_pass(
    test_db_session: AsyncSession,
) -> None:
    await _map(test_db_session)
    orphan = new_map_asset_key("maps/og-images", uuid.uuid4(), "png")
    storage = FakeStorage({orphan: OLD})

    with (
        patch("app.platform.storage.get_storage", return_value=storage),
        patch("app.modules.catalog.maps.image_sweep.datetime") as clock,
    ):
        clock.now.return_value = NOW
        await story_asset_jobs.sweep_story_asset_objects()

    assert storage.objects == {}
