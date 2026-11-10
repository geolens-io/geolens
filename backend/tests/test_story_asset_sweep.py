"""Story image objects no row names are swept away.

The ``story_assets`` rows decide what is kept, so the lookups run against the
test database. Storage is a fake. Every age is a timestamp the test sets.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin import story_asset_jobs
from app.modules.catalog.stories.asset_sweep import (
    ORPHAN_OBJECT_MIN_AGE,
    sweep_unnamed_story_asset_objects,
)
from app.modules.catalog.stories.assets import new_story_asset_key, object_keys
from app.modules.catalog.stories.models import Story, StoryAsset
from app.platform.storage.local import LocalStorageProvider
from app.platform.storage.provider import StoredObject
from app.processing.ingest.tasks import task_app
from tests.factories import get_user_id

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
OLD = NOW - ORPHAN_OBJECT_MIN_AGE - timedelta(hours=1)
YOUNG = NOW - timedelta(minutes=30)
_PREFIX = "stories/assets/"

_stories: list[uuid.UUID] = []


class FakeStorage:
    def __init__(self, objects: dict[str, datetime]) -> None:
        self.objects = dict(objects)
        self.deleted: list[str] = []
        self.failing: set[str] = set()

    async def iter_object_pages(self, prefix: str, *, start_after: str | None = None):
        yield [
            StoredObject(key=key, last_modified=modified)
            for key, modified in sorted(self.objects.items())
            if key.startswith(prefix) and (start_after is None or key > start_after)
        ]

    async def delete(self, key: str) -> None:
        if key in self.failing:
            raise OSError("storage unavailable")
        self.deleted.append(key)
        self.objects.pop(key, None)


async def _story(session: AsyncSession) -> uuid.UUID:
    story = Story(
        title=f"Sweep {uuid.uuid4().hex[:8]}",
        draft={"chapters": []},
        created_by=await get_user_id(session, "admin"),
    )
    session.add(story)
    await session.commit()
    _stories.append(story.id)
    return story.id


async def _asset(session: AsyncSession, story_id: uuid.UUID) -> str:
    key = new_story_asset_key(story_id)
    session.add(
        StoryAsset(story_id=story_id, storage_key=key, byte_size=1, width=1, height=1)
    )
    await session.commit()
    return key


@pytest.fixture(autouse=True)
async def _cleanup(test_db_session: AsyncSession):
    yield
    await test_db_session.execute(delete(Story).where(Story.id.in_(_stories)))
    await test_db_session.commit()
    _stories.clear()


async def _run(session: AsyncSession, storage: FakeStorage):
    with patch("app.platform.storage.get_storage", return_value=storage):
        return await sweep_unnamed_story_asset_objects(session, now=NOW)


async def test_an_old_object_no_row_names_is_deleted_beside_a_named_one(
    test_db_session: AsyncSession,
) -> None:
    story = await _story(test_db_session)
    named = await _asset(test_db_session, story)
    orphan = new_story_asset_key(story)
    storage = FakeStorage({named: OLD, orphan: OLD})

    await _run(test_db_session, storage)

    assert set(storage.objects) == {named}


async def test_an_images_sizes_stay_or_go_with_its_row(
    test_db_session: AsyncSession,
) -> None:
    story = await _story(test_db_session)
    named = await _asset(test_db_session, story)
    orphan = new_story_asset_key(story)
    kept = set(object_keys(named).values())
    storage = FakeStorage(
        {key: OLD for key in kept | set(object_keys(orphan).values())}
    )

    await _run(test_db_session, storage)

    assert set(storage.objects) == kept


async def test_an_object_whose_story_is_gone_is_deleted(
    test_db_session: AsyncSession,
) -> None:
    await _story(test_db_session)
    orphan = new_story_asset_key(uuid.uuid4())
    storage = FakeStorage({orphan: OLD})

    await _run(test_db_session, storage)

    assert storage.objects == {}


async def test_an_object_inside_the_grace_period_is_kept(
    test_db_session: AsyncSession,
) -> None:
    story = await _story(test_db_session)
    young = new_story_asset_key(story)
    storage = FakeStorage({young: YOUNG})

    await _run(test_db_session, storage)

    assert set(storage.objects) == {young}


async def test_keys_that_are_not_story_images_are_left_alone(
    test_db_session: AsyncSession,
) -> None:
    story = await _story(test_db_session)
    others = {
        f"{_PREFIX}{story}.webp",
        f"{_PREFIX}{story}-{uuid.uuid4().hex}.png",
        f"{_PREFIX}{story}-{uuid.uuid4().hex}.thumb.webp",
        f"{_PREFIX}not-a-uuid-{uuid.uuid4().hex}.webp",
        f"{_PREFIX}{story}-{uuid.uuid4().hex}.webp/inner.webp",
    }
    storage = FakeStorage({key: OLD for key in others})

    await _run(test_db_session, storage)

    assert set(storage.objects) == others


async def test_an_object_a_row_takes_after_the_listing_is_kept(
    test_db_session: AsyncSession,
) -> None:
    story = await _story(test_db_session)
    racing = new_story_asset_key(story)
    storage = FakeStorage({racing: OLD})
    original = storage.iter_object_pages

    async def name_it_during_the_recheck(prefix: str, *, start_after=None):
        if prefix == racing:
            await test_db_session.execute(
                StoryAsset.__table__.insert().values(
                    id=uuid.uuid4(),
                    story_id=story,
                    storage_key=racing,
                    byte_size=1,
                    width=1,
                    height=1,
                )
            )
        async for page in original(prefix, start_after=start_after):
            yield page

    storage.iter_object_pages = name_it_during_the_recheck

    await _run(test_db_session, storage)

    assert set(storage.objects) == {racing}


async def test_a_failed_delete_is_counted_and_the_pass_goes_on(
    test_db_session: AsyncSession,
) -> None:
    story = await _story(test_db_session)
    stuck, gone = sorted(new_story_asset_key(story) for _ in range(2))
    storage = FakeStorage({stuck: OLD, gone: OLD})
    storage.failing.add(stuck)

    await _run(test_db_session, storage)

    assert set(storage.objects) == {stuck}


async def test_a_listing_failure_ends_the_pass_without_raising(
    test_db_session: AsyncSession,
) -> None:
    await _story(test_db_session)
    storage = FakeStorage({})

    async def unavailable(prefix: str, *, start_after=None):
        raise OSError("storage unavailable")
        yield []

    storage.iter_object_pages = unavailable

    outcome = await _run(test_db_session, storage)

    assert not outcome.ran


async def test_nothing_is_swept_while_the_catalog_has_no_stories(
    test_db_session: AsyncSession,
) -> None:
    orphan = new_story_asset_key(uuid.uuid4())
    storage = FakeStorage({orphan: OLD})

    async def no_stories(_db) -> bool:
        return False

    with patch(
        "app.modules.catalog.stories.asset_sweep._catalog_has_stories", no_stories
    ):
        await _run(test_db_session, storage)

    assert set(storage.objects) == {orphan}


async def test_a_local_copy_is_a_new_object(tmp_path: Path) -> None:
    storage = LocalStorageProvider(base_dir=str(tmp_path))
    await storage.put("stories/assets/source.webp", b"image")
    source = tmp_path / "stories/assets/source.webp"
    os.utime(source, (OLD.timestamp(), OLD.timestamp()))

    await storage.copy("stories/assets/source.webp", "stories/assets/copy.webp")

    copied = [
        entry
        async for page in storage.iter_object_pages("stories/assets/copy.webp")
        for entry in page
    ]
    assert copied[0].last_modified > OLD + ORPHAN_OBJECT_MIN_AGE


class TestScheduling:
    async def test_the_sweep_runs_every_six_hours_on_the_ingest_queue(self):
        periodic = task_app.periodic_registry.periodic_tasks[
            (story_asset_jobs.sweep_story_asset_objects.name, "story-asset-sweep")
        ]

        assert periodic.cron == "47 */6 * * *"
        assert story_asset_jobs.sweep_story_asset_objects.queue == "ingest"

    async def test_a_fresh_worker_discovers_the_sweep_through_its_import_paths(self):
        script = (
            "import sys\n"
            "from app.processing.ingest.tasks import task_app\n"
            "assert 'app.modules.admin.story_asset_jobs' not in sys.modules\n"
            "task_app.perform_import_paths()\n"
            "print(any(k[1] == 'story-asset-sweep' for k in task_app.periodic_registry.periodic_tasks))\n"
        )
        backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=backend,
            capture_output=True,
            text=True,
            check=True,
        )

        assert result.stdout.strip().splitlines()[-1] == "True"
