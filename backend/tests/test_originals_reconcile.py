"""Originals that no dataset or job can still use are reconciled away.

The dataset and job rows decide what is kept, so the lookups run against the
test database. Storage is a fake, or a real provider where noted. Every age is
a timestamp the test sets.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import boto3
import pytest
from moto import mock_aws
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as db_module
import app.platform.jobs.originals_reconcile as module
import app.platform.jobs.staging_reconcile as staging_module
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import (
    ARCHIVE_PENDING_METADATA_KEY,
    PUBLISH_FOLLOWUPS_FIELD,
    UNPUBLISHED_STORAGE_KEYS_FIELD,
    IngestJob,
)
from app.platform.jobs.originals_reconcile import (
    ORIGINALS_ORPHAN_MIN_AGE,
    ORIGINALS_PREFIX,
    reconcile_orphaned_originals,
)
from app.platform.storage.local import LocalStorageProvider
from app.platform.storage.provider import StoredObject
from tests.factories import get_user_id

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
OLD = NOW - ORIGINALS_ORPHAN_MIN_AGE - timedelta(hours=1)
YOUNG = NOW - timedelta(hours=1)

_records: list[uuid.UUID] = []
_jobs: list[uuid.UUID] = []


def _key(dataset_id: uuid.UUID, name: str = "points.geojson") -> str:
    return f"{ORIGINALS_PREFIX}{dataset_id}/{name}"


class FakeStorage:
    """Just enough provider for the scan, a prefix listing and a one-key re-read."""

    def __init__(
        self,
        objects: dict[str, datetime],
        *,
        page_size: int = 1000,
        scan_prefix: str = ORIGINALS_PREFIX,
        client_side_cursor: bool = False,
    ) -> None:
        self.objects = dict(objects)
        self.page_size = page_size
        self.scan_prefix = scan_prefix
        self.client_side_cursor = client_side_cursor
        self.deleted: list[str] = []
        self.scan_pages = 0
        self.delete_error: Exception | None = None
        self.fail_scan = False
        self.on_relist = None
        self.on_recheck = None

    async def iter_object_pages(self, prefix: str, *, start_after: str | None = None):
        if not prefix.endswith("/"):
            if self.on_recheck is not None:
                await self.on_recheck(prefix)
        elif prefix != self.scan_prefix and self.on_relist is not None:
            await self.on_relist(prefix)
        # A client-side cursor fetches the pages before it and yields them empty.
        server_cursor = None if self.client_side_cursor else start_after
        matching = [
            StoredObject(key=key, last_modified=modified)
            for key, modified in sorted(self.objects.items())
            if key.startswith(prefix) and (server_cursor is None or key > server_cursor)
        ]
        for start in range(0, max(len(matching), 1), self.page_size):
            if prefix == self.scan_prefix:
                if self.fail_scan:
                    raise RuntimeError("provider down")
                self.scan_pages += 1
            page = matching[start : start + self.page_size]
            if self.client_side_cursor and start_after is not None:
                page = [entry for entry in page if entry.key > start_after]
            yield page

    async def delete(self, key: str) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(key)
        self.objects.pop(key, None)


def _fill(value, **fields):
    if isinstance(value, dict):
        return {key: _fill(item, **fields) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill(item, **fields) for item in value]
    return value.format(**fields) if isinstance(value, str) else value


async def _dataset(
    session: AsyncSession,
    dataset_id: uuid.UUID | None = None,
    *,
    record_status: str = "published",
) -> uuid.UUID:
    record = Record(
        title=f"Originals {uuid.uuid4().hex[:8]}",
        visibility="private",
        record_status=record_status,
        created_by=await get_user_id(session, "admin"),
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        id=dataset_id or uuid.uuid4(),
        record_id=record.id,
        table_name=f"ds_{uuid.uuid4().hex[:12]}",
        source_format="geojson",
    )
    session.add(dataset)
    await session.commit()
    _records.append(record.id)
    return dataset.id


async def _job(
    session: AsyncSession, *, status: str = "complete", user_metadata: dict | None
) -> uuid.UUID:
    job = IngestJob(
        source_filename="originals-test", status=status, user_metadata=user_metadata
    )
    session.add(job)
    await session.commit()
    _jobs.append(job.id)
    return job.id


@pytest.fixture(autouse=True)
async def _a_dataset_exists(test_db_session: AsyncSession):
    """A catalog holding one live dataset."""
    staging_module._scan_cursors[ORIGINALS_PREFIX] = None
    live = await _dataset(test_db_session)
    yield live
    staging_module._scan_cursors.clear()
    await test_db_session.execute(delete(IngestJob).where(IngestJob.id.in_(_jobs)))
    await test_db_session.execute(delete(Record).where(Record.id.in_(_records)))
    await test_db_session.commit()
    _jobs.clear()
    _records.clear()


async def _run(session: AsyncSession, storage, *, now: datetime = NOW):
    with patch("app.platform.storage.get_storage", return_value=storage):
        return await reconcile_orphaned_originals(session, now=now)


class TestDeletes:
    async def test_an_old_prefix_no_dataset_names_is_deleted_whole(
        self, test_db_session: AsyncSession
    ) -> None:
        orphan = uuid.uuid4()
        storage = FakeStorage(
            {_key(orphan, "a.geojson"): OLD, _key(orphan, "b.geojson"): OLD}
        )

        outcome = await _run(test_db_session, storage)

        assert storage.objects == {}
        assert outcome.ran
        assert outcome.objects_deleted == 2

    async def test_only_orphans_go_when_a_page_mixes_them_with_live_prefixes(
        self, test_db_session: AsyncSession, _a_dataset_exists: uuid.UUID
    ) -> None:
        orphan = uuid.uuid4()
        storage = FakeStorage({_key(orphan): OLD, _key(_a_dataset_exists): OLD})

        outcome = await _run(test_db_session, storage)

        assert set(storage.objects) == {_key(_a_dataset_exists)}
        assert (outcome.objects_deleted, outcome.skipped_live) == (1, 1)

    async def test_a_job_that_only_mentions_the_id_after_settling_keeps_nothing(
        self, test_db_session: AsyncSession
    ) -> None:
        orphan = uuid.uuid4()
        await _job(test_db_session, user_metadata={"dataset_id": str(orphan)})
        storage = FakeStorage({_key(orphan): OLD})

        await _run(test_db_session, storage)

        assert storage.objects == {}


class TestKeeps:
    @pytest.mark.parametrize("record_status", ["draft", "published"])
    async def test_a_prefix_a_dataset_row_names_is_kept(
        self, test_db_session: AsyncSession, record_status: str
    ) -> None:
        dataset_id = await _dataset(test_db_session, record_status=record_status)
        storage = FakeStorage({_key(dataset_id): OLD})

        outcome = await _run(test_db_session, storage)

        assert set(storage.objects) == {_key(dataset_id)}
        assert outcome.skipped_live == 1

    async def test_a_prefix_inside_the_grace_period_is_kept(
        self, test_db_session: AsyncSession
    ) -> None:
        orphan = uuid.uuid4()
        storage = FakeStorage({_key(orphan): YOUNG})

        outcome = await _run(test_db_session, storage)

        assert set(storage.objects) == {_key(orphan)}
        assert outcome.skipped_recent == 1

    async def test_the_newest_object_sets_the_prefixes_age(
        self, test_db_session: AsyncSession
    ) -> None:
        orphan = uuid.uuid4()
        storage = FakeStorage({_key(orphan, "a"): OLD, _key(orphan, "b"): YOUNG})

        await _run(test_db_session, storage)

        assert set(storage.objects) == {_key(orphan, "a"), _key(orphan, "b")}

    async def test_the_newest_object_on_a_later_page_sets_the_age(
        self, test_db_session: AsyncSession
    ) -> None:
        orphan = uuid.uuid4()
        names = {_key(orphan, f"{index}"): OLD for index in range(3)}
        names[_key(orphan, "9")] = YOUNG
        storage = FakeStorage(names, page_size=2)

        await _run(test_db_session, storage)

        assert set(storage.objects) == set(names)

    @pytest.mark.parametrize(
        ("status", "metadata"),
        [
            ("running", {UNPUBLISHED_STORAGE_KEYS_FIELD: ["{key}"]}),
            ("failed", {UNPUBLISHED_STORAGE_KEYS_FIELD: ["{key}"]}),
            (
                "complete",
                {
                    PUBLISH_FOLLOWUPS_FIELD: {
                        "task": "ingest_file",
                        "archive_key": "{key}",
                    },
                    ARCHIVE_PENDING_METADATA_KEY: True,
                },
            ),
            ("pending", {"dataset_id": "{id}"}),
        ],
        ids=["in-flight write", "failed write awaiting reap", "owed archive", "active"],
    )
    async def test_a_job_that_can_still_write_the_prefix_keeps_it(
        self, test_db_session: AsyncSession, status: str, metadata: dict
    ) -> None:
        orphan = uuid.uuid4()
        key = _key(orphan)
        filled = _fill(metadata, key=key, id=str(orphan))
        await _job(test_db_session, status=status, user_metadata=filled)
        storage = FakeStorage({key: OLD})

        outcome = await _run(test_db_session, storage)

        assert set(storage.objects) == {key}
        assert outcome.skipped_live == 1


class TestShapes:
    @pytest.mark.parametrize(
        "template",
        [
            "originals/not-a-uuid/points.geojson",
            "originals/{upper}/points.geojson",
            "originals/{hex}/points.geojson",
            "originals/{{{id}}}/points.geojson",
            "originals/{id}",
            "originals/{id}/",
            "originals/{id}/nested/points.geojson",
        ],
        ids=[
            "not a uuid",
            "uppercase",
            "no hyphens",
            "braced",
            "the id alone",
            "no name",
            "nested",
        ],
    )
    async def test_a_key_that_is_not_an_originals_shape_is_left_alone(
        self, test_db_session: AsyncSession, template: str
    ) -> None:
        orphan = uuid.uuid4()
        key = template.format(id=orphan, upper=str(orphan).upper(), hex=orphan.hex)
        storage = FakeStorage({key: OLD})

        await _run(test_db_session, storage)

        assert set(storage.objects) == {key}

    async def test_a_prefix_holding_a_nested_key_is_kept_whole(
        self, test_db_session: AsyncSession
    ) -> None:
        orphan = uuid.uuid4()
        objects = {_key(orphan, "points.geojson"): OLD, _key(orphan, "x/y"): OLD}
        storage = FakeStorage(objects)

        outcome = await _run(test_db_session, storage)

        assert set(storage.objects) == set(objects)
        assert outcome.skipped_unattributable >= 1

    async def test_a_prefix_with_more_objects_than_an_original_holds_is_left_alone(
        self, test_db_session: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(module, "_MAX_OBJECTS_PER_PREFIX", 2)
        orphan = uuid.uuid4()
        objects = {_key(orphan, f"{index}"): OLD for index in range(3)}
        storage = FakeStorage(objects)

        await _run(test_db_session, storage)

        assert set(storage.objects) == set(objects)


class TestBounds:
    async def test_the_delete_budget_stops_the_pass_and_the_next_one_resumes(
        self, test_db_session: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(module, "_MAX_DELETES_PER_PASS", 2)
        orphans = [uuid.uuid4() for _ in range(5)]
        storage = FakeStorage({_key(orphan): OLD for orphan in orphans})

        first = await _run(test_db_session, storage)
        assert first.objects_deleted == 2
        assert len(storage.objects) == 3

        await _run(test_db_session, storage)
        await _run(test_db_session, storage)
        assert storage.objects == {}

    async def test_the_delete_budget_counts_failures(
        self, test_db_session: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(module, "_MAX_DELETES_PER_PASS", 2)
        storage = FakeStorage({_key(uuid.uuid4()): OLD for _ in range(4)})
        storage.delete_error = OSError("down")

        outcome = await _run(test_db_session, storage)

        assert outcome.delete_failures == 2
        assert len(storage.objects) == 4

    async def test_the_scan_budget_stops_paging_and_the_next_pass_resumes(
        self, test_db_session: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(module, "_MAX_OBJECTS_SCANNED_PER_PASS", 3)
        orphans = sorted(uuid.uuid4() for _ in range(8))
        storage = FakeStorage({_key(orphan): OLD for orphan in orphans}, page_size=2)

        first = await _run(test_db_session, storage)
        assert storage.scan_pages == 2
        assert first.objects_listed == 4

        for _ in range(3):
            await _run(test_db_session, storage)
        assert storage.objects == {}

    async def test_pages_skipped_before_the_cursor_count_against_the_page_budget(
        self, test_db_session: AsyncSession, monkeypatch
    ) -> None:
        monkeypatch.setattr(module, "_MAX_PAGES_PER_PASS", 3)
        ids = sorted(uuid.uuid4() for _ in range(12))
        storage = FakeStorage(
            {_key(dataset_id): YOUNG for dataset_id in ids},
            page_size=2,
            client_side_cursor=True,
        )
        staging_module._scan_cursors[ORIGINALS_PREFIX] = _key(ids[9])

        await _run(test_db_session, storage)

        assert storage.scan_pages == 3
        assert staging_module._scan_cursors[ORIGINALS_PREFIX] is None

    async def test_a_pass_that_fails_returns_without_raising(
        self, test_db_session: AsyncSession
    ) -> None:
        storage = FakeStorage({_key(uuid.uuid4()): OLD})
        storage.fail_scan = True

        outcome = await _run(test_db_session, storage)

        assert not outcome.ran
        assert (await test_db_session.execute(select(1))).scalar() == 1

    async def test_a_failed_delete_is_counted_and_the_pass_goes_on(
        self, test_db_session: AsyncSession
    ) -> None:
        objects = {_key(uuid.uuid4()): OLD for _ in range(2)}
        storage = FakeStorage(objects)
        storage.delete_error = OSError("down")

        outcome = await _run(test_db_session, storage)

        assert outcome.delete_failures == 2
        assert set(storage.objects) == set(objects)


class TestRechecks:
    async def test_a_dataset_committed_after_the_listing_saves_the_prefix(
        self, test_db_session: AsyncSession
    ) -> None:
        orphan = uuid.uuid4()
        storage = FakeStorage({_key(orphan): OLD})

        async def commit_the_dataset(prefix: str) -> None:
            async with db_module.async_session() as other:
                await _dataset(other, orphan)
            storage.on_relist = None

        storage.on_relist = commit_the_dataset

        outcome = await _run(test_db_session, storage)

        assert set(storage.objects) == {_key(orphan)}
        assert outcome.skipped_live == 1

    async def test_a_job_committed_after_the_listing_saves_the_prefix(
        self, test_db_session: AsyncSession
    ) -> None:
        orphan = uuid.uuid4()
        key = _key(orphan)
        storage = FakeStorage({key: OLD})

        async def commit_the_job(prefix: str) -> None:
            async with db_module.async_session() as other:
                await _job(
                    other,
                    status="running",
                    user_metadata={UNPUBLISHED_STORAGE_KEYS_FIELD: [key]},
                )
            storage.on_relist = None

        storage.on_relist = commit_the_job

        await _run(test_db_session, storage)

        assert set(storage.objects) == {key}

    async def test_an_object_rewritten_after_the_listing_is_kept(
        self, test_db_session: AsyncSession
    ) -> None:
        orphan = uuid.uuid4()
        storage = FakeStorage({_key(orphan): OLD})

        async def land_a_new_upload(key: str) -> None:
            storage.objects[key] = YOUNG

        storage.on_recheck = land_a_new_upload

        outcome = await _run(test_db_session, storage)

        assert set(storage.objects) == {_key(orphan)}
        assert outcome.skipped_changed == 1

    async def test_an_object_gone_after_the_listing_is_skipped(
        self, test_db_session: AsyncSession
    ) -> None:
        orphan = uuid.uuid4()
        storage = FakeStorage({_key(orphan): OLD})

        async def reap_it(key: str) -> None:
            storage.objects.pop(key, None)

        storage.on_recheck = reap_it

        outcome = await _run(test_db_session, storage)

        assert storage.deleted == []
        assert outcome.skipped_changed == 1


class TestDeclines:
    async def test_a_catalog_with_no_datasets_declines(
        self, test_db_session: AsyncSession
    ) -> None:
        storage = FakeStorage({_key(uuid.uuid4()): OLD})

        with patch.object(
            module, "_catalog_has_datasets", AsyncMock(return_value=False)
        ):
            outcome = await _run(test_db_session, storage)

        assert not outcome.ran
        assert storage.scan_pages == 0
        assert len(storage.objects) == 1

    async def test_multi_tenant_mode_without_a_tenant_declines(
        self, test_db_session: AsyncSession
    ) -> None:
        storage = FakeStorage({_key(uuid.uuid4()): OLD})

        with patch("app.core.tenancy.is_multi_tenant", return_value=True):
            outcome = await _run(test_db_session, storage)

        assert not outcome.ran
        assert storage.scan_pages == 0

    async def test_a_tenant_pass_reaches_only_its_own_namespace(
        self, test_db_session: AsyncSession
    ) -> None:
        from app.core.db.tenant_session import current_tenant_var

        mine, theirs = uuid.uuid4(), uuid.uuid4()
        orphan, other_orphan = uuid.uuid4(), uuid.uuid4()
        mine_key = f"tenants/{mine}/{_key(orphan)}"
        theirs_key = f"tenants/{theirs}/{_key(other_orphan)}"
        storage = FakeStorage(
            {mine_key: OLD, theirs_key: OLD}, scan_prefix=f"tenants/{mine}/originals/"
        )

        token = current_tenant_var.set(str(mine))
        try:
            with patch("app.core.tenancy.is_multi_tenant", return_value=True):
                await _run(test_db_session, storage)
        finally:
            current_tenant_var.reset(token)

        assert set(storage.objects) == {theirs_key}

    async def test_a_pass_another_process_holds_declines(
        self, test_db_session: AsyncSession
    ) -> None:
        storage = FakeStorage({_key(uuid.uuid4()): OLD})
        async with db_module.async_session() as holder:
            await holder.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"originals-orphan-reconcile:{ORIGINALS_PREFIX}"},
            )

            outcome = await _run(test_db_session, storage)

        assert not outcome.ran
        assert storage.scan_pages == 0


class TestRealProviders:
    async def test_a_local_store_loses_the_orphan_and_keeps_the_live_prefix(
        self, test_db_session: AsyncSession, tmp_path, _a_dataset_exists: uuid.UUID
    ) -> None:
        storage = LocalStorageProvider(str(tmp_path / "objects"))
        orphan = uuid.uuid4()
        for dataset_id in (orphan, _a_dataset_exists):
            await storage.put(_key(dataset_id), b"original")

        await _run(
            test_db_session, storage, now=datetime.now(timezone.utc) + timedelta(days=2)
        )

        assert await storage.list(f"{ORIGINALS_PREFIX}{orphan}/") == []
        assert await storage.list(f"{ORIGINALS_PREFIX}{_a_dataset_exists}/") != []

    async def test_an_s3_bucket_loses_the_orphan_and_keeps_the_live_prefix(
        self, test_db_session: AsyncSession, _a_dataset_exists: uuid.UUID
    ) -> None:
        from app.platform.storage.s3 import S3StorageProvider

        orphan = uuid.uuid4()
        with mock_aws():
            client = boto3.client("s3", region_name="us-east-1")
            client.create_bucket(Bucket="originals-bucket")
            for dataset_id in (orphan, _a_dataset_exists):
                client.put_object(
                    Bucket="originals-bucket", Key=_key(dataset_id), Body=b"original"
                )
            storage = S3StorageProvider(
                bucket="originals-bucket",
                region="us-east-1",
                access_key_id="testing",
                secret_access_key="testing",
            )

            await _run(
                test_db_session,
                storage,
                now=datetime.now(timezone.utc) + timedelta(days=2),
            )

            assert await storage.list(f"{ORIGINALS_PREFIX}{orphan}/") == []
            assert await storage.list(f"{ORIGINALS_PREFIX}{_a_dataset_exists}/") != []
