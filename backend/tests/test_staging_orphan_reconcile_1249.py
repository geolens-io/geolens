"""fix(#1249): staging objects with no ingest_jobs row are reconciled away.

#1236 review r5 left a residual orphan window that no time-based margin can
close: S3 validates a presigned signature when a request STARTS, so an
accepted single-part PUT can still be transferring after every deadline
derived from its URL has passed, and a sweep that inferred "the transfer must
be done by now" from elapsed time deleted the key and retired the row before
the PUT landed. The fix reverses the direction of the question — start from
the OBJECT, ask whether any row still owns it — so nothing has to be inferred
from a clock at all.

The decision logic is exercised against a fake storage layer with a REAL
database session: the row lookups are the whole point, so a mocked session
would assert nothing about whether they are even valid SQL. The provider
halves (`list_objects` on local + S3) are pinned separately, and one
end-to-end case runs the whole pass against a real ``LocalStorageProvider``
with a backdated mtime — no sleeps anywhere, every wait is a fact the test
sets up rather than one it hopes for.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import boto3
import pytest
from moto import mock_aws
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.platform.jobs.models import IngestJob
from app.platform.jobs.staging_reconcile import (
    STAGING_PREFIX,
    _job_id_from_key,
    reconcile_orphaned_staging_objects,
)
from app.platform.storage.provider import StoredObject

pytestmark = pytest.mark.anyio


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def _old() -> datetime:
    """A last-modified far past the deletion threshold."""
    return NOW - timedelta(seconds=settings.staging_orphan_min_age_seconds + 3600)


def _young() -> datetime:
    """A last-modified inside the threshold — an upload that just landed."""
    return NOW - timedelta(seconds=60)


class FakeStorage:
    """Just enough provider to drive the reconciliation deterministically."""

    def __init__(self, objects: dict[str, datetime]) -> None:
        self.objects = dict(objects)
        self.deleted: list[str] = []
        self.listed_prefixes: list[str] = []
        self.delete_error: Exception | None = None
        # Called with the key right before its pre-delete re-read, so a test
        # can mutate the world exactly at the moment the race would happen.
        self.on_recheck = None

    async def list_objects(self, prefix: str) -> list[StoredObject]:
        self.listed_prefixes.append(prefix)
        if self.on_recheck is not None and prefix != STAGING_PREFIX:
            await self.on_recheck(prefix)
        return [
            StoredObject(key=key, last_modified=modified)
            for key, modified in sorted(self.objects.items())
            if key.startswith(prefix)
        ]

    async def delete(self, key: str) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(key)
        self.objects.pop(key, None)


async def _job(session: AsyncSession, *, status: str = "complete") -> uuid.UUID:
    """Insert a committed ingest_jobs row and return its id."""
    job = IngestJob(source_filename="orphan-test", status=status)
    session.add(job)
    await session.flush()
    job_id = job.id
    await session.commit()
    return job_id


async def _run(session: AsyncSession, storage: FakeStorage):
    with patch("app.platform.storage.get_storage", return_value=storage):
        return await reconcile_orphaned_staging_objects(session, now=NOW)


class TestJobIdFromKey:
    """Which keys this sweep is willing to reason about at all."""

    def test_a_staging_upload_key_names_its_job(self) -> None:
        job_id = uuid.uuid4()
        assert _job_id_from_key(f"staging/{job_id}/roads.geojson") == job_id

    def test_the_frozen_snapshot_names_the_same_job(self) -> None:
        """`frozen/` sits under the job segment, so it reconciles identically."""
        job_id = uuid.uuid4()
        assert _job_id_from_key(f"staging/{job_id}/frozen/roads.geojson") == job_id

    # Literal uuids, not uuid4() calls: a parametrize argument evaluated at
    # collection time differs per xdist worker, and xdist aborts the whole run
    # when workers disagree about which tests exist.
    @pytest.mark.parametrize(
        "key",
        [
            "staging/not-a-uuid/roads.geojson",
            "staging/roads.geojson",
            "staging/",
            "staging/6f1b6b1e-6d3a-4f0a-9f0e-1f2a3b4c5d6e/",
            "other/6f1b6b1e-6d3a-4f0a-9f0e-1f2a3b4c5d6e/roads.geojson",
            "",
        ],
    )
    def test_anything_it_cannot_attribute_is_declined(self, key: str) -> None:
        """ "I cannot tell whose this is" must never become "so delete it"."""
        assert _job_id_from_key(key) is None


class TestReconciliationDecision:
    """Row present / absent+young / absent+old, plus both races."""

    async def test_an_object_whose_job_row_still_exists_is_kept(
        self, test_db_session: AsyncSession
    ) -> None:
        job_id = await _job(test_db_session)
        key = f"staging/{job_id}/roads.geojson"
        storage = FakeStorage({key: _old()})

        outcome = await _run(test_db_session, storage)

        assert storage.deleted == []
        assert outcome.ran is True
        assert outcome.orphans_deleted == 0

    async def test_an_untracked_object_inside_the_threshold_is_kept(
        self, test_db_session: AsyncSession
    ) -> None:
        """The single-part PUT that just landed after its row was purged.

        This is #1249's own scenario at the moment it happens: the object is
        real, nothing tracks it, and deleting it now would race a client that
        may still be finishing. The age threshold is what makes waiting free —
        the next pass a day later deletes it with no inference required.
        """
        key = f"staging/{uuid.uuid4()}/roads.geojson"
        storage = FakeStorage({key: _young()})

        outcome = await _run(test_db_session, storage)

        assert storage.deleted == []
        assert outcome.skipped_recent == 1
        assert outcome.orphans_deleted == 0

    async def test_an_untracked_object_past_the_threshold_is_deleted(
        self, test_db_session: AsyncSession
    ) -> None:
        key = f"staging/{uuid.uuid4()}/roads.geojson"
        storage = FakeStorage({key: _old()})

        with patch(
            "app.platform.jobs.staging_reconcile.staging_orphans_deleted_total"
        ) as counter:
            outcome = await _run(test_db_session, storage)

        assert storage.deleted == [key]
        assert outcome.orphans_deleted == 1
        assert outcome.delete_failures == 0
        counter.inc.assert_called_once_with(1)

    async def test_a_row_that_appears_before_the_delete_saves_the_object(
        self, test_db_session: AsyncSession
    ) -> None:
        """Race #2, with the real recheck query rather than a stubbed answer.

        The row is committed after the batch query has already concluded the
        object is untracked. Under READ COMMITTED the per-object recheck takes
        its own snapshot, so it sees the new row and declines — which is the
        entire reason the recheck is a separate statement instead of a reuse of
        the batch result.
        """
        job_id = uuid.uuid4()
        key = f"staging/{job_id}/roads.geojson"
        storage = FakeStorage({key: _old()})

        real_exists = None

        async def _insert_then_check(db: AsyncSession, checked_id: uuid.UUID) -> bool:
            await db.execute(
                text(
                    "INSERT INTO catalog.ingest_jobs (id, status, source_filename)"
                    " VALUES (:id, 'pending', 'raced') ON CONFLICT DO NOTHING"
                ).bindparams(id=checked_id)
            )
            await db.commit()
            return await real_exists(db, checked_id)

        import app.platform.jobs.staging_reconcile as module

        real_exists = module._job_row_exists
        with patch.object(module, "_job_row_exists", _insert_then_check):
            outcome = await _run(test_db_session, storage)

        assert storage.deleted == []
        assert outcome.skipped_row_appeared == 1
        assert outcome.orphans_deleted == 0

    async def test_an_object_rewritten_before_the_delete_is_left_alone(
        self, test_db_session: AsyncSession
    ) -> None:
        """Race #1: a listing entry is never authority for destroying anything.

        The object is old in the snapshot and freshly written by the time the
        pre-delete re-read runs. The re-read is what decides, so it survives.
        """
        key = f"staging/{uuid.uuid4()}/roads.geojson"
        storage = FakeStorage({key: _old()})

        async def _rewrite(prefix: str) -> None:
            storage.objects[prefix] = _young()

        storage.on_recheck = _rewrite

        outcome = await _run(test_db_session, storage)

        assert storage.deleted == []
        assert outcome.skipped_object_changed == 1
        assert outcome.orphans_deleted == 0

    async def test_an_object_that_vanished_before_the_delete_is_not_a_failure(
        self, test_db_session: AsyncSession
    ) -> None:
        key = f"staging/{uuid.uuid4()}/roads.geojson"
        storage = FakeStorage({key: _old()})

        async def _vanish(prefix: str) -> None:
            storage.objects.pop(prefix, None)

        storage.on_recheck = _vanish

        outcome = await _run(test_db_session, storage)

        assert storage.deleted == []
        assert outcome.skipped_object_changed == 1
        assert outcome.delete_failures == 0

    async def test_an_unattributable_staging_key_is_never_touched(
        self, test_db_session: AsyncSession
    ) -> None:
        storage = FakeStorage(
            {
                "staging/not-a-uuid/mystery.gpkg": _old(),
                "staging/loose-file.gpkg": _old(),
            }
        )

        outcome = await _run(test_db_session, storage)

        assert storage.deleted == []
        assert outcome.skipped_unattributable == 2

    async def test_only_the_staging_prefix_is_ever_listed(
        self, test_db_session: AsyncSession
    ) -> None:
        """Objects the upload system does not own are out of reach by construction."""
        outside = f"customer-data/{uuid.uuid4()}/quarterly.gpkg"
        storage = FakeStorage({outside: _old()})

        outcome = await _run(test_db_session, storage)

        assert storage.deleted == []
        assert outcome.objects_listed == 0
        assert storage.listed_prefixes == [STAGING_PREFIX]

    async def test_a_provider_delete_failure_is_counted_not_raised(
        self, test_db_session: AsyncSession
    ) -> None:
        """The sweep this runs inside must survive a broken object store."""
        key = f"staging/{uuid.uuid4()}/roads.geojson"
        storage = FakeStorage({key: _old()})
        storage.delete_error = RuntimeError("provider down")

        outcome = await _run(test_db_session, storage)

        assert outcome.delete_failures == 1
        assert outcome.orphans_deleted == 0

    async def test_a_listing_failure_ends_the_pass_without_raising(
        self, test_db_session: AsyncSession
    ) -> None:
        storage = AsyncMock()
        storage.list_objects.side_effect = RuntimeError("provider down")

        with patch("app.platform.storage.get_storage", return_value=storage):
            outcome = await reconcile_orphaned_staging_objects(test_db_session, now=NOW)

        assert outcome.ran is False
        storage.delete.assert_not_awaited()

    async def test_the_callers_orm_instances_survive_the_pass(
        self, test_db_session: AsyncSession
    ) -> None:
        """The pass must not commit or roll back the session it is handed.

        A rollback expires every instance in the identity map regardless of
        ``expire_on_commit``, so a caller still holding ORM objects (which
        ``fail_stale_jobs`` does) would find them unloadable afterwards. This
        is why the advisory lock lives on a session of the pass's own.
        """
        job = IngestJob(source_filename="held-across-the-pass", status="complete")
        test_db_session.add(job)
        await test_db_session.flush()
        await test_db_session.commit()
        key = f"staging/{uuid.uuid4()}/roads.geojson"

        outcome = await _run(test_db_session, FakeStorage({key: _old()}))

        assert outcome.orphans_deleted == 1
        # Reading through the instance, not a fresh query: an expired
        # attribute would raise here rather than answer.
        assert job.source_filename == "held-across-the-pass"

    async def test_a_concurrent_pass_declines_rather_than_double_counting(
        self, test_db_session: AsyncSession
    ) -> None:
        """The advisory lock is what makes the counter honest.

        Every API worker runs its own sweeper loop; without the lock each would
        list the same prefix and count the same delete, reporting N times the
        truth under UVICORN_WORKERS>1.
        """
        import app.core.db as db_module

        key = f"staging/{uuid.uuid4()}/roads.geojson"
        storage = FakeStorage({key: _old()})

        async with db_module.async_session() as holder:
            held = await holder.execute(
                text(
                    "SELECT pg_try_advisory_xact_lock(hashtextextended(:lock_key, 0))"
                ),
                {"lock_key": f"staging-orphan-reconcile:{STAGING_PREFIX}"},
            )
            assert held.scalar() is True, "precondition: the other process has it"

            outcome = await _run(test_db_session, storage)

        assert outcome.ran is False
        assert storage.deleted == []
        assert storage.listed_prefixes == []


class TestAgainstRealLocalStorage:
    """One end-to-end pass with a real provider and real mtimes."""

    async def test_the_orphan_is_deleted_and_the_tracked_object_survives(
        self, test_db_session: AsyncSession, tmp_path, monkeypatch
    ) -> None:
        from app.platform.storage.local import LocalStorageProvider

        storage = LocalStorageProvider(str(tmp_path))
        monkeypatch.setattr(
            "app.platform.storage.get_storage", lambda: storage, raising=True
        )

        tracked_id = await _job(test_db_session)
        orphan_id = uuid.uuid4()
        tracked_key = f"staging/{tracked_id}/tracked.geojson"
        orphan_key = f"staging/{orphan_id}/orphan.geojson"
        await storage.put(tracked_key, b"tracked")
        await storage.put(orphan_key, b"orphan")

        # Backdate both past the threshold. Deterministic by construction —
        # the age is a fact the test writes, never one it waits for.
        backdated = (_old()).timestamp()
        for key in (tracked_key, orphan_key):
            os.utime(tmp_path / key, (backdated, backdated))

        outcome = await reconcile_orphaned_staging_objects(test_db_session, now=NOW)

        assert outcome.orphans_deleted == 1
        assert await storage.exists(tracked_key)
        assert not await storage.exists(orphan_key)


class TestProviderListObjects:
    """The new provider call, on both backends that can serve staging keys."""

    async def test_local_reports_mtime_as_aware_utc(self, tmp_path) -> None:
        from app.platform.storage.local import LocalStorageProvider

        storage = LocalStorageProvider(str(tmp_path))
        await storage.put("staging/a/one.txt", b"1")
        await storage.put("staging/b/two.txt", b"2")
        backdated = _old().timestamp()
        os.utime(tmp_path / "staging/a/one.txt", (backdated, backdated))

        entries = {e.key: e for e in await storage.list_objects("staging/")}

        assert set(entries) == {"staging/a/one.txt", "staging/b/two.txt"}
        assert entries["staging/a/one.txt"].last_modified.tzinfo is not None
        assert entries["staging/a/one.txt"].last_modified == datetime.fromtimestamp(
            backdated, tz=timezone.utc
        )

    async def test_local_accepts_a_complete_key_as_the_prefix(self, tmp_path) -> None:
        """The pre-delete re-read passes an exact key, not a directory."""
        from app.platform.storage.local import LocalStorageProvider

        storage = LocalStorageProvider(str(tmp_path))
        await storage.put("staging/a/one.txt", b"1")
        await storage.put("staging/a/one.txt.part", b"partial")

        entries = await storage.list_objects("staging/a/one.txt")

        # A prefix listing also returns siblings sharing the prefix, which is
        # exactly why the caller filters for an exact key match.
        assert {e.key for e in entries} == {
            "staging/a/one.txt",
            "staging/a/one.txt.part",
        }

    async def test_s3_reports_aware_timestamps_and_paginates(self) -> None:
        from app.platform.storage.s3 import S3StorageProvider

        with mock_aws():
            client = boto3.client("s3", region_name="us-east-1")
            client.create_bucket(Bucket="orphan-bucket")
            for index in range(3):
                client.put_object(
                    Bucket="orphan-bucket", Key=f"staging/j/{index}.txt", Body=b"x"
                )
            client.put_object(Bucket="orphan-bucket", Key="other/keep.txt", Body=b"x")
            provider = S3StorageProvider(
                bucket="orphan-bucket",
                region="us-east-1",
                access_key_id="testing",
                secret_access_key="testing",
            )

            entries = await provider.list_objects("staging/")

        assert {e.key for e in entries} == {
            "staging/j/0.txt",
            "staging/j/1.txt",
            "staging/j/2.txt",
        }
        assert all(e.last_modified.tzinfo is not None for e in entries)


async def test_the_stale_job_sweep_runs_the_reconciliation(
    test_db_session: AsyncSession,
) -> None:
    """The wiring, not the logic: a sweep pass must actually reach it.

    ``fail_stale_jobs`` is where every scheduled cleanup converges, so a
    reconciliation nothing calls is a reconciliation that does not exist.
    """
    from app.platform.jobs import sweep as sweep_module

    with patch.object(
        sweep_module, "reconcile_orphaned_staging_objects", new_callable=AsyncMock
    ) as reconcile:
        await sweep_module.fail_stale_jobs(test_db_session)

    reconcile.assert_awaited_once()
