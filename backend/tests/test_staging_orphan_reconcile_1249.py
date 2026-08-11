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
halves (`iter_object_pages` on local + S3) are pinned separately, and one
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
from app.platform.jobs.models import STAGING_REAPED_FINAL_MARKER, IngestJob
from app.platform.jobs.staging_reconcile import (
    STAGING_PREFIX,
    _job_id_from_key,
    reconcile_orphaned_staging_objects,
)
from app.platform.storage.provider import StoredObject

pytestmark = pytest.mark.anyio


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def _uuid_starting(first_hex: str) -> uuid.UUID:
    """A real uuid4 with its leading hex digit pinned, for ordering tests."""
    return uuid.UUID(first_hex + str(uuid.uuid4())[1:])


def _old() -> datetime:
    """A last-modified far past the deletion threshold."""
    return NOW - timedelta(seconds=settings.staging_orphan_min_age_seconds + 3600)


def _young() -> datetime:
    """A last-modified inside the threshold — an upload that just landed."""
    return NOW - timedelta(seconds=60)


class FakeStorage:
    """Just enough provider to drive the reconciliation deterministically."""

    def __init__(self, objects: dict[str, datetime], *, page_size: int = 1000) -> None:
        self.objects = dict(objects)
        self.page_size = page_size
        self.deleted: list[str] = []
        self.listed_prefixes: list[str] = []
        # One entry per page of the PREFIX walk actually fetched, so a test can
        # prove the pass stopped paging rather than merely stopped acting. The
        # per-object pre-delete re-reads pass a complete key (no trailing "/")
        # and are excluded — they are not the walk.
        self.pages_served: list[int] = []
        # The `start_after` each prefix walk was handed, so the cursor's
        # advance is observable rather than inferred from what got deleted.
        self.resumed_from: list[str | None] = []
        self.delete_error: Exception | None = None
        # Raise from the prefix walk after this many pages, to model a pass
        # that dies partway through with deletes already committed.
        self.fail_after_pages: int | None = None
        # Called with the key right before its pre-delete re-read, so a test
        # can mutate the world exactly at the moment the race would happen.
        self.on_recheck = None

    async def iter_object_pages(self, prefix: str, *, start_after: str | None = None):
        self.listed_prefixes.append(prefix)
        if prefix.endswith("/"):
            self.resumed_from.append(start_after)
        if self.on_recheck is not None and prefix != STAGING_PREFIX:
            await self.on_recheck(prefix)
        matching = [
            StoredObject(key=key, last_modified=modified)
            for key, modified in sorted(self.objects.items())
            if key.startswith(prefix) and (start_after is None or key > start_after)
        ]
        for start in range(0, max(len(matching), 1), self.page_size):
            page = matching[start : start + self.page_size]
            if prefix.endswith("/"):
                if (
                    self.fail_after_pages is not None
                    and len(self.pages_served) >= self.fail_after_pages
                ):
                    raise RuntimeError("provider down mid-walk")
                self.pages_served.append(len(page))
            yield page

    async def delete(self, key: str) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(key)
        self.objects.pop(key, None)


async def _job(
    session: AsyncSession,
    *,
    status: str = "complete",
    file_path: str | None = None,
    user_metadata: dict | None = None,
) -> uuid.UUID:
    """Insert a committed ingest_jobs row and return its id."""
    job = IngestJob(
        source_filename="orphan-test",
        status=status,
        file_path=file_path,
        user_metadata=user_metadata,
    )
    session.add(job)
    await session.flush()
    job_id = job.id
    await session.commit()
    return job_id


async def _job_with_id(
    session: AsyncSession, job_id: uuid.UUID, *, status: str, user_metadata: dict
) -> None:
    """Insert a committed row at a CHOSEN id, for keys that name their job."""
    session.add(
        IngestJob(
            id=job_id,
            source_filename="orphan-test",
            status=status,
            user_metadata=user_metadata,
        )
    )
    await session.commit()


@pytest.fixture(autouse=True)
def _front_of_the_prefix(monkeypatch):
    """Start every test's first pass at the front of the keyspace, on S3.

    The cursor seeds itself at a RANDOM point on first use per process (so a
    restart-prone worker still covers the whole prefix), which would otherwise
    make every assertion here depend on a uuid draw. Tests that care about the
    cursor set it themselves.

    `storage_provider` matters because the pass runs on S3 storage only — the
    local backend's `staging/` directory is not exclusively the upload
    system's. The provider DOUBLE stays a fake (or a real
    LocalStorageProvider, for the end-to-end case); only the setting the gate
    reads is moved.
    """
    import app.platform.jobs.staging_reconcile as module

    monkeypatch.setattr(settings, "storage_provider", "s3")
    module._scan_cursors.clear()
    module._scan_cursors[STAGING_PREFIX] = None
    yield
    module._scan_cursors.clear()


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

    async def test_an_object_whose_job_is_still_running_is_kept(
        self, test_db_session: AsyncSession
    ) -> None:
        job_id = await _job(test_db_session, status="running")
        key = f"staging/{job_id}/roads.geojson"
        storage = FakeStorage({key: _old()})

        outcome = await _run(test_db_session, storage)

        assert storage.deleted == []
        assert outcome.ran is True
        assert outcome.orphans_deleted == 0

    async def test_a_fan_out_childs_shared_input_survives_its_purged_parent(
        self, test_db_session: AsyncSession
    ) -> None:
        """fix(#1249 review r3, codex P1): the key's job segment is not ownership.

        ``create_fan_out_jobs`` clones the parent's ``file_path`` onto every
        child, so a child's only input is the PARENT's staging object. The
        parent row hits the retention cutoff on its own schedule — the purge's
        survivor query keeps the OBJECT alive for a still-pending child, not
        the parent's row. Reconciling on the id in the key alone would look up
        the purged parent, find nothing, and delete the input the child is
        about to read.
        """
        purged_parent_id = uuid.uuid4()
        shared_input = f"staging/{purged_parent_id}/frozen/multi.gpkg"
        await _job(test_db_session, status="pending", file_path=shared_input)
        storage = FakeStorage({shared_input: _old()})

        outcome = await _run(test_db_session, storage)

        assert storage.deleted == [], "deleted a surviving child's only input"
        assert outcome.orphans_deleted == 0

    async def test_a_failed_child_still_shields_the_input_it_can_retry_from(
        self, test_db_session: AsyncSession
    ) -> None:
        """`/jobs/{id}/retry` is failed-only, so a failed row is not done."""
        purged_parent_id = uuid.uuid4()
        shared_input = f"staging/{purged_parent_id}/frozen/multi.gpkg"
        await _job(test_db_session, status="failed", file_path=shared_input)
        storage = FakeStorage({shared_input: _old()})

        outcome = await _run(test_db_session, storage)

        assert storage.deleted == []
        assert outcome.orphans_deleted == 0

    async def test_a_complete_childs_inherited_reference_does_not_shield_forever(
        self, test_db_session: AsyncSession
    ) -> None:
        """fix(#1249 review r4, codex P2): the sibling of the r3 fix.

        A fan-out child stays `complete` forever and is exempt from retention
        indefinitely as a dataset's latest complete job. Counting its inherited
        `file_path` as a live reference at any status would answer "still
        referenced" on every future pass, so an object leaked by a failed
        parent-side delete could never be repaired — the reconciler would
        permanently decline the one case it exists for. The retention purge
        draws the line in exactly the same place.
        """
        purged_parent_id = uuid.uuid4()
        shared_input = f"staging/{purged_parent_id}/frozen/multi.gpkg"
        await _job(
            test_db_session,
            status="complete",
            file_path=shared_input,
            # Cloned wholesale by create_fan_out_jobs, and never ownership —
            # owned_presigned_staging_key rejects an inherited key for the
            # same reason this must not shield one.
            user_metadata={"s3_key": f"staging/{purged_parent_id}/multi.gpkg"},
        )
        storage = FakeStorage({shared_input: _old()})

        outcome = await _run(test_db_session, storage)

        assert storage.deleted == [shared_input]
        assert outcome.orphans_deleted == 1

    async def test_the_owning_row_shields_while_the_post_expiry_sweep_owns_the_key(
        self, test_db_session: AsyncSession
    ) -> None:
        """A complete presigned job that has not been finalized yet.

        `_sweep_expired_presigned_staging` is still going to act on this key,
        so this reconciler must not race it — the status rule alone would have
        called a complete row done with the bytes.
        """
        # The key names the job it belongs to, so the row is created first and
        # its metadata written in a second statement.
        job_id = uuid.uuid4()
        upload_key = f"staging/{job_id}/roads.geojson"
        await _job_with_id(
            test_db_session,
            job_id,
            status="complete",
            user_metadata={"s3_key": upload_key},
        )
        storage = FakeStorage({upload_key: _old()})

        outcome = await _run(test_db_session, storage)

        assert storage.deleted == []
        assert outcome.orphans_deleted == 0

    async def test_a_finally_reaped_owner_no_longer_shields_a_recreated_upload(
        self, test_db_session: AsyncSession
    ) -> None:
        """fix(#1249 review r6, codex P2): #1249's own scenario, end to end.

        A single-part PUT that lands after the post-expiry sweep's FINAL delete
        recreates the object. That sweep never looks at the key again once its
        final marker is set, and retention exempts a dataset's latest
        complete job indefinitely — so "the row still exists" as a shield left
        the recreated object unreachable by every reaper including this one,
        which is the exact leak this module was written to close.
        """
        job_id = uuid.uuid4()
        upload_key = f"staging/{job_id}/roads.geojson"
        await _job_with_id(
            test_db_session,
            job_id,
            status="complete",
            user_metadata={
                "s3_key": upload_key,
                STAGING_REAPED_FINAL_MARKER: True,
            },
        )
        storage = FakeStorage({upload_key: _old()})

        outcome = await _run(test_db_session, storage)

        assert storage.deleted == [upload_key]
        assert outcome.orphans_deleted == 1

    async def test_a_complete_direct_uploads_leftover_is_reclaimable(
        self, test_db_session: AsyncSession
    ) -> None:
        """A job that never presigned gets no marker, ever.

        Reading a missing marker as "not finalized yet" would shield every
        direct-upload row forever — the same permanent-shield shape, arrived at
        from the other side.
        """
        job_id = await _job(test_db_session, status="complete")
        leftover = f"staging/{job_id}/roads.geojson"
        storage = FakeStorage({leftover: _old()})

        outcome = await _run(test_db_session, storage)

        assert storage.deleted == [leftover]
        assert outcome.orphans_deleted == 1

    async def test_a_reference_that_appears_before_the_delete_saves_the_object(
        self, test_db_session: AsyncSession
    ) -> None:
        """The per-object recheck covers references, not just the id.

        A batch query that saw no reference must not licence a delete once a
        fan-out child lands between it and the delete itself.
        """
        parent_id = uuid.uuid4()
        shared_input = f"staging/{parent_id}/frozen/multi.gpkg"
        storage = FakeStorage({shared_input: _old()})

        import app.platform.jobs.staging_reconcile as module

        real_exists = module._staging_reference_exists

        async def _insert_child_then_check(
            db: AsyncSession, checked_id: uuid.UUID, logical_key: str
        ) -> bool:
            await db.execute(
                text(
                    "INSERT INTO catalog.ingest_jobs (status, source_filename,"
                    " file_path) VALUES ('pending', 'late-child', :fp)"
                ).bindparams(fp=logical_key)
            )
            await db.commit()
            return await real_exists(db, checked_id, logical_key)

        with patch.object(
            module, "_staging_reference_exists", _insert_child_then_check
        ):
            outcome = await _run(test_db_session, storage)

        assert storage.deleted == []
        assert outcome.skipped_row_appeared == 1

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
        # Once per completed delete, not once per pass: a pass that fails
        # after partial progress must not take the count with it, since the
        # objects are already gone and nothing can recover it (review r5).
        counter.inc.assert_called_once_with()

    async def test_deletes_already_done_are_counted_when_the_pass_then_fails(
        self, test_db_session: AsyncSession
    ) -> None:
        """fix(#1249 review r5, codex P2): the object is gone either way.

        A pass that dies after partial progress used to discard its tally
        before the end-of-pass increment ran, so the counter permanently
        under-reported cleanup that really happened — nothing later can
        recover a count for an object that no longer exists.
        """
        orphans = {
            f"staging/{uuid.uuid4()}/f{index}.geojson": _old() for index in range(3)
        }
        storage = FakeStorage(orphans, page_size=1)
        storage.fail_after_pages = 1

        with patch(
            "app.platform.jobs.staging_reconcile.staging_orphans_deleted_total"
        ) as counter:
            outcome = await _run(test_db_session, storage)

        assert outcome.ran is False, "precondition: the pass failed"
        assert len(storage.deleted) == 1, "precondition: one delete got through"
        assert counter.inc.call_count == 1

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

        async def _insert_then_check(
            db: AsyncSession, checked_id: uuid.UUID, logical_key: str
        ) -> bool:
            await db.execute(
                text(
                    "INSERT INTO catalog.ingest_jobs (id, status, source_filename)"
                    " VALUES (:id, 'pending', 'raced') ON CONFLICT DO NOTHING"
                ).bindparams(id=checked_id)
            )
            await db.commit()
            return await real_exists(db, checked_id, logical_key)

        import app.platform.jobs.staging_reconcile as module

        real_exists = module._staging_reference_exists
        with patch.object(module, "_staging_reference_exists", _insert_then_check):
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

        async def _explode(prefix: str):
            raise RuntimeError("provider down")
            yield []  # unreachable; makes this an async generator

        storage.iter_object_pages = _explode

        with patch("app.platform.storage.get_storage", return_value=storage):
            outcome = await reconcile_orphaned_staging_objects(test_db_session, now=NOW)

        assert outcome.ran is False
        storage.delete.assert_not_awaited()

    async def test_the_pass_stops_paging_once_its_delete_budget_is_spent(
        self, test_db_session: AsyncSession, monkeypatch
    ) -> None:
        """fix(#1249) review r1: a large `staging/` prefix is not materialized.

        The pass holds a transaction (and its connection) open for the advisory
        lock, so both budgets are checked BETWEEN pages — it must stop asking
        the provider for more, not merely stop deleting what it was handed.
        """
        import app.platform.jobs.staging_reconcile as module

        monkeypatch.setattr(module, "_MAX_DELETES_PER_PASS", 2)
        orphans = {
            f"staging/{uuid.uuid4()}/f{index}.geojson": _old() for index in range(9)
        }
        storage = FakeStorage(orphans, page_size=3)

        outcome = await _run(test_db_session, storage)

        assert outcome.orphans_deleted == 2
        # One page fetched, not three: the budget was spent inside the first.
        assert storage.pages_served == [3]
        assert outcome.objects_listed == 3

    async def test_the_scan_budget_bounds_a_prefix_with_nothing_to_delete(
        self, test_db_session: AsyncSession, monkeypatch
    ) -> None:
        """The other half of the bound: no orphans is not a licence to walk forever."""
        import app.platform.jobs.staging_reconcile as module

        monkeypatch.setattr(module, "_MAX_OBJECTS_SCANNED_PER_PASS", 4)
        young = {
            f"staging/{uuid.uuid4()}/f{index}.geojson": _young() for index in range(12)
        }
        storage = FakeStorage(young, page_size=2)

        outcome = await _run(test_db_session, storage)

        assert outcome.orphans_deleted == 0
        assert outcome.objects_listed == 4
        assert storage.pages_served == [2, 2]


class TestScanCursor:
    """fix(#1249) review r2: a capped walk without a cursor is a blind spot.

    Without one, every pass re-walks the same lexicographically first window,
    and an orphan sorting after a window full of tracked, recent, or
    unattributable keys is never reached at all.
    """

    async def test_a_budget_stop_resumes_the_next_pass_where_it_stopped(
        self, test_db_session: AsyncSession, monkeypatch
    ) -> None:
        import app.platform.jobs.staging_reconcile as module

        monkeypatch.setattr(module, "_MAX_OBJECTS_SCANNED_PER_PASS", 2)
        # Young, so nothing is deleted and only the cursor can explain progress.
        keys = [f"staging/{uuid.uuid4()}/f.geojson" for _ in range(6)]
        storage = FakeStorage(dict.fromkeys(keys, _young()), page_size=2)

        first = await _run(test_db_session, storage)
        second = await _run(test_db_session, storage)

        in_key_order = sorted(keys)
        assert storage.resumed_from == [None, in_key_order[1]]
        assert first.objects_listed == 2 and second.objects_listed == 2
        assert module._scan_cursors[STAGING_PREFIX] == in_key_order[3]

    async def test_a_pass_that_starts_mid_prefix_wraps_to_the_front(
        self, test_db_session: AsyncSession
    ) -> None:
        """fix(#1249 review r7, codex P2): a one-directional scan is a sample.

        Starting at a random point and never wrapping means a worker recycled
        before its next pass only ever sees suffixes, so an orphan near the
        front of a large prefix is reached with probability ~1/(objects+1) per
        restart. With the wrap, one unbudgeted pass covers everything and the
        cursor only decides where it starts.
        """
        import app.platform.jobs.staging_reconcile as module

        # Real uuids with a pinned leading hex digit, so they straddle the
        # cursor AND still parse as the job segment of a staging key.
        low = f"staging/{_uuid_starting('0')}/f.geojson"
        high = f"staging/{_uuid_starting('f')}/f.geojson"
        module._scan_cursors[STAGING_PREFIX] = f"staging/8{'0' * 8}"
        storage = FakeStorage({low: _old(), high: _old()})

        outcome = await _run(test_db_session, storage)

        assert storage.resumed_from == [f"staging/8{'0' * 8}", None], (
            "the pass must walk the tail and then come back for the front"
        )
        assert sorted(storage.deleted) == [low, high]
        assert outcome.orphans_deleted == 2
        # It got all the way round, so the next pass may start at the front.
        assert module._scan_cursors[STAGING_PREFIX] is None

    async def test_the_wrap_leg_stops_where_the_pass_started(
        self, test_db_session: AsyncSession
    ) -> None:
        """Otherwise it re-walks the keys the first leg already covered."""
        import app.platform.jobs.staging_reconcile as module

        cursor = f"staging/8{'0' * 8}"
        module._scan_cursors[STAGING_PREFIX] = cursor
        after_cursor = f"staging/{_uuid_starting('9')}/f.geojson"
        storage = FakeStorage({after_cursor: _young()})

        await _run(test_db_session, storage)

        # The tail leg saw it; the wrap leg is bounded above by the cursor and
        # so must not report it a second time.
        assert storage.resumed_from == [cursor, None]
        assert (await _run(test_db_session, storage)).objects_listed == 1

    async def test_a_delete_budget_stop_resumes_at_the_last_candidate_processed(
        self, test_db_session: AsyncSession, monkeypatch
    ) -> None:
        """Not at the end of the page — the rest of it was never worked."""
        import app.platform.jobs.staging_reconcile as module

        monkeypatch.setattr(module, "_MAX_DELETES_PER_PASS", 1)
        keys = sorted(f"staging/{uuid.uuid4()}/f.geojson" for _ in range(4))
        storage = FakeStorage(dict.fromkeys(keys, _old()), page_size=4)

        await _run(test_db_session, storage)

        assert storage.deleted == [keys[0]]
        assert module._scan_cursors[STAGING_PREFIX] == keys[0], (
            "resuming past the unprocessed candidates would skip them until the wrap"
        )

    def test_the_first_pass_of_a_process_starts_somewhere_random(self) -> None:
        """A worker recycled more often than a full walk completes must not
        keep restarting at the front — that is the starvation the cursor
        exists to remove, reintroduced by the restart."""
        import app.platform.jobs.staging_reconcile as module

        module._scan_cursors.clear()
        seeds = set()
        for _ in range(3):
            module._scan_cursors.clear()
            seed = module._resume_point("staging/")
            assert seed is not None and seed.startswith("staging/")
            seeds.add(seed)

        assert len(seeds) == 3, "a fixed seed would make every process walk alike"

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

    async def test_local_storage_is_declined_outright(
        self, test_db_session: AsyncSession, monkeypatch
    ) -> None:
        """fix(#1249 review r8, codex P1): `staging/` is only ours in a BUCKET.

        On the local backend the same prefix sits inside `upload_staging_dir`,
        where an operator also stages manifest seed files — legitimately, and
        legitimately BEFORE the manifest that names them is applied, stored as
        an absolute path no logical-key comparison here would match. Deleting
        one is not a leaked byte, it is someone's input. Nothing is lost by
        declining: presigned uploads refuse anything but S3 at request time,
        so the orphan class this module exists for cannot occur here.
        """
        monkeypatch.setattr(settings, "storage_provider", "local")
        seed = f"staging/{uuid.uuid4()}/seed.geojson"
        storage = FakeStorage({seed: _old()})

        outcome = await _run(test_db_session, storage)

        assert outcome.ran is False
        assert storage.deleted == []
        assert storage.listed_prefixes == [], "it must not even look"

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

        tracked_id = await _job(test_db_session, status="running")
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


async def _all_entries(storage, prefix: str) -> list[StoredObject]:
    return [entry async for page in storage.iter_object_pages(prefix) for entry in page]


class TestProviderIterObjectPages:
    """The new provider call, on both backends that can serve staging keys."""

    async def test_local_reports_mtime_as_aware_utc(self, tmp_path) -> None:
        from app.platform.storage.local import LocalStorageProvider

        storage = LocalStorageProvider(str(tmp_path))
        await storage.put("staging/a/one.txt", b"1")
        await storage.put("staging/b/two.txt", b"2")
        backdated = _old().timestamp()
        os.utime(tmp_path / "staging/a/one.txt", (backdated, backdated))

        entries = {e.key: e for e in await _all_entries(storage, "staging/")}

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

        entries = await _all_entries(storage, "staging/a/one.txt")

        # A prefix listing also returns siblings sharing the prefix, which is
        # exactly why the caller filters for an exact key match.
        assert {e.key for e in entries} == {
            "staging/a/one.txt",
            "staging/a/one.txt.part",
        }

    async def test_local_orders_a_dir_and_file_sharing_a_stem_by_full_key(
        self, tmp_path
    ) -> None:
        """Plain per-name ordering disagrees with full-key ordering here.

        ``/`` is 0x2F and ``.`` is 0x2E, so ``frozen.txt`` sorts BEFORE
        ``frozen/x.txt`` even though the bare names sort the other way — and
        `frozen/` is a real segment of every presigned staging layout, next to
        a filename the uploader chose. Getting this backwards would make
        `start_after` skip or repeat entries on a resumed walk.
        """
        from app.platform.storage.local import LocalStorageProvider

        storage = LocalStorageProvider(str(tmp_path))
        await storage.put("staging/a/frozen.txt", b"1")
        await storage.put("staging/a/frozen/x.txt", b"2")

        keys = [e.key for e in await _all_entries(storage, "staging/")]

        assert keys == ["staging/a/frozen.txt", "staging/a/frozen/x.txt"]
        assert keys == sorted(keys), "the walk must be in full-key order"

    async def test_local_does_not_walk_past_the_page_the_consumer_took(
        self, tmp_path, monkeypatch
    ) -> None:
        """fix(#1249 review r5): the walk itself is lazy, not just its slicing.

        Counted in ``scandir`` calls rather than results, because a walk that
        materializes everything and then hands back one page returns the same
        results while costing the whole tree.
        """
        import app.platform.storage.local as local_module
        from app.platform.storage.local import LocalStorageProvider

        storage = LocalStorageProvider(str(tmp_path))
        for name in ("a", "b", "c"):
            await storage.put(f"staging/{name}/f.txt", b"x")
        monkeypatch.setattr(local_module, "_OBJECT_PAGE_SIZE", 1)

        scans: list[str] = []
        real_scandir = local_module.os.scandir

        def _counting_scandir(path):
            scans.append(str(path))
            return real_scandir(path)

        monkeypatch.setattr(local_module.os, "scandir", _counting_scandir)

        async for page in storage.iter_object_pages("staging/"):
            assert [e.key for e in page] == ["staging/a/f.txt"]
            break

        # staging/ plus staging/a/ only. An eager walk would have entered b/
        # and c/ as well before returning anything.
        assert len(scans) == 2, scans

    async def test_s3_pages_and_stops_when_the_consumer_does(self) -> None:
        """Real ListObjectsV2 continuation, and a consumer that breaks early.

        The second assertion is the one review r1 asked for: abandoning the
        generator must abandon the round trips too, not just the results.
        """
        from app.platform.storage.s3 import S3StorageProvider

        with mock_aws():
            client = boto3.client("s3", region_name="us-east-1")
            client.create_bucket(Bucket="orphan-bucket")
            for index in range(5):
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

            entries = await _all_entries(provider, "staging/")

            calls: list[dict] = []
            unpatched = provider.client.list_objects_v2

            def _counting(**kwargs):
                calls.append(kwargs)
                return unpatched(**kwargs, MaxKeys=2)

            provider.client.list_objects_v2 = _counting
            first_page = None
            async for page in provider.iter_object_pages("staging/"):
                first_page = page
                break

        assert {e.key for e in entries} == {
            f"staging/j/{index}.txt" for index in range(5)
        }
        assert all(e.last_modified.tzinfo is not None for e in entries)
        assert first_page is not None and len(first_page) == 2
        assert len(calls) == 1, "breaking out must stop the paging, not just the loop"


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
