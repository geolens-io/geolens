"""Vector quicklook images no dataset points at are reconciled away.

The dataset rows decide what is kept, so the lookups run against the test
database. Storage is a fake. Every age is a timestamp the test sets.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

import app.platform.jobs.staging_reconcile as staging_module
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.quicklook_reconcile import (
    QUICKLOOK_ORPHAN_MIN_AGE,
    QUICKLOOK_PREFIX,
    reconcile_orphaned_quicklooks,
)
from app.platform.storage.provider import StoredObject
from tests.factories import get_user_id

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
OLD = NOW - QUICKLOOK_ORPHAN_MIN_AGE - timedelta(hours=1)
YOUNG = NOW - timedelta(minutes=30)

_records: list[uuid.UUID] = []


def _key(dataset_id: uuid.UUID, name: str | None = None) -> str:
    name = name or f"quicklook_256_{uuid.uuid4().hex[:12]}.png"
    return f"{QUICKLOOK_PREFIX}{dataset_id}/{name}"


class FakeStorage:
    def __init__(self, objects: dict[str, datetime]) -> None:
        self.objects = dict(objects)
        self.deleted: list[str] = []
        self.before_delete = None

    async def iter_object_pages(self, prefix: str, *, start_after: str | None = None):
        yield [
            StoredObject(key=key, last_modified=modified)
            for key, modified in sorted(self.objects.items())
            if key.startswith(prefix) and (start_after is None or key > start_after)
        ]

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


async def _dataset(session: AsyncSession, *, quicklook: str | None = None) -> uuid.UUID:
    record = Record(
        title=f"Quicklook {uuid.uuid4().hex[:8]}",
        visibility="private",
        record_status="published",
        created_by=await get_user_id(session, "admin"),
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"ds_{uuid.uuid4().hex[:12]}",
        source_format="geojson",
        quicklook_256_uri=quicklook,
    )
    session.add(dataset)
    await session.commit()
    _records.append(record.id)
    return dataset.id


@pytest.fixture(autouse=True)
async def _cleanup(test_db_session: AsyncSession):
    staging_module._scan_cursors[QUICKLOOK_PREFIX] = None
    yield
    staging_module._scan_cursors.clear()
    await test_db_session.execute(delete(Record).where(Record.id.in_(_records)))
    await test_db_session.commit()
    _records.clear()


async def _run(session: AsyncSession, storage: FakeStorage):
    with patch("app.platform.storage.get_storage", return_value=storage):
        return await reconcile_orphaned_quicklooks(session, now=NOW)


async def test_an_old_image_no_dataset_points_at_is_deleted(
    test_db_session: AsyncSession,
) -> None:
    owner = await _dataset(test_db_session)
    orphan = _key(owner)
    storage = FakeStorage({orphan: OLD})

    outcome = await _run(test_db_session, storage)

    assert storage.objects == {}
    assert outcome.objects_deleted == 1


async def test_the_image_a_dataset_points_at_is_kept_beside_its_orphans(
    test_db_session: AsyncSession,
) -> None:
    live = _key(uuid.uuid4())
    owner = await _dataset(test_db_session, quicklook=live)
    orphan = _key(owner)
    storage = FakeStorage({live: OLD, orphan: OLD})

    outcome = await _run(test_db_session, storage)

    assert set(storage.objects) == {live}
    assert (outcome.objects_deleted, outcome.skipped_live) == (1, 1)


async def test_an_image_inside_the_grace_period_is_kept(
    test_db_session: AsyncSession,
) -> None:
    owner = await _dataset(test_db_session)
    young = _key(owner)
    storage = FakeStorage({young: YOUNG})

    outcome = await _run(test_db_session, storage)

    assert set(storage.objects) == {young}
    assert outcome.skipped_recent == 1


async def test_keys_that_are_not_versioned_quicklooks_are_left_alone(
    test_db_session: AsyncSession,
) -> None:
    owner = await _dataset(test_db_session)
    others = {
        _key(owner, "quicklook_256.png"),
        _key(owner, "tiles.pmtiles"),
        f"{QUICKLOOK_PREFIX}not-a-uuid/quicklook_256_0123456789ab.png",
    }
    storage = FakeStorage({key: OLD for key in others})

    outcome = await _run(test_db_session, storage)

    assert set(storage.objects) == others
    assert outcome.skipped_unattributable == len(others)


async def test_an_image_a_dataset_takes_after_the_listing_is_kept(
    test_db_session: AsyncSession,
) -> None:
    owner = await _dataset(test_db_session)
    racing = _key(owner)
    storage = FakeStorage({racing: OLD})
    original = storage.iter_object_pages

    async def point_at_it_during_the_recheck(prefix: str, *, start_after=None):
        if prefix == racing:
            await test_db_session.execute(
                Dataset.__table__.update()
                .where(Dataset.id == owner)
                .values(quicklook_256_uri=racing)
            )
        async for page in original(prefix, start_after=start_after):
            yield page

    storage.iter_object_pages = point_at_it_during_the_recheck

    await _run(test_db_session, storage)

    assert set(storage.objects) == {racing}
