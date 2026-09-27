"""Local staged uploads that no ingest job can still use are reconciled away.

Real files in the per-test staging directory and real ``ingest_jobs`` rows:
which rows keep a file is the whole decision, so a mocked session would
assert nothing about it. Every age is set on the file or the row, never waited for.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

import app.platform.jobs.local_staging_reconcile as module
from app.core.config import settings
from app.platform.jobs.models import (
    ARCHIVE_PENDING_METADATA_KEY,
    PUBLISH_FOLLOWUPS_FIELD,
    IngestJob,
)
from app.platform.jobs.local_staging_reconcile import reconcile_orphaned_local_uploads
from app.platform.storage.provider import StoredObject
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

# The rows this test inserted, removed at teardown: an old pending or running
# row left behind would be settled by the stale-job sweep in a later test.
_inserted: list[uuid.UUID] = []

_UNSET = object()


def _old() -> timedelta:
    return timedelta(seconds=settings.staging_orphan_min_age_seconds + 3600)


def _recent() -> timedelta:
    return timedelta(seconds=60)


def _id_starting(first_hex: str) -> uuid.UUID:
    """A real uuid4 with its leading hex digit pinned, for name-order tests."""
    return uuid.UUID(first_hex + str(uuid.uuid4())[1:])


@pytest.fixture(autouse=True)
def _pass_starts_at_the_front():
    module._resume_after = None
    yield
    module._resume_after = None


@pytest.fixture
async def root(test_db_session: AsyncSession):
    """The per-test staging directory the ``client`` fixture configured."""
    import app.core.db as db_module

    path = Path(settings.upload_staging_dir)
    path.mkdir(parents=True, exist_ok=True)
    yield path
    async with db_module.async_session() as session:
        await session.execute(delete(IngestJob).where(IngestJob.id.in_(_inserted)))
        await session.commit()
    _inserted.clear()


@pytest.fixture
def now() -> datetime:
    return datetime.now(timezone.utc)


def _age(path: Path, now: datetime, age: timedelta | None = None) -> None:
    """Set ``path``'s own mtime, not a symlink target's."""
    stamp = (now - (age or _old())).timestamp()
    os.utime(path, (stamp, stamp), follow_symlinks=False)


def _staged(root: Path, name: str, now: datetime, age: timedelta | None = None) -> Path:
    path = root / name
    path.write_bytes(b"staged upload")
    _age(path, now, age)
    return path


async def _job(
    session: AsyncSession,
    file_path: str | Path | None,
    now: datetime,
    *,
    status: str = "complete",
    job_id: uuid.UUID | None = None,
    user_metadata: dict | None = None,
    dataset_id: uuid.UUID | None = None,
    ended: timedelta | None = None,
    created: timedelta | None = None,
) -> uuid.UUID:
    """Insert a committed row naming ``file_path``, created and ended long ago by default."""
    job = IngestJob(
        id=job_id or uuid.uuid4(),
        source_filename="roads.geojson",
        status=status,
        file_path=None if file_path is None else str(file_path),
        user_metadata=user_metadata or {},
        dataset_id=dataset_id,
        created_at=now - (created or ended or _old()),
        completed_at=now - (ended or _old()),
    )
    session.add(job)
    await session.commit()
    _inserted.append(job.id)
    return job.id


async def _upload(
    session: AsyncSession, root: Path, now: datetime, file_path=_UNSET, **job_fields
) -> Path:
    """An old `{job id}_{name}` upload and its job's row, which names it by default."""
    job_id = job_fields.pop("job_id", None) or uuid.uuid4()
    path = _staged(root, f"{job_id}_roads.geojson", now)
    named = path if file_path is _UNSET else file_path
    await _job(session, named, now, job_id=job_id, **job_fields)
    return path


async def _run(session: AsyncSession, now: datetime):
    return await reconcile_orphaned_local_uploads(session, now=now)


class TestDeletes:
    @pytest.mark.parametrize("status", ["complete", "cancelled", "fanned_out"])
    async def test_an_upload_only_a_finished_job_names_is_deleted(
        self, test_db_session: AsyncSession, root: Path, now: datetime, status: str
    ) -> None:
        path = await _upload(test_db_session, root, now, status=status)

        outcome = await _run(test_db_session, now)

        assert not path.exists()
        assert outcome.uploads_deleted == 1

    async def test_a_manifest_copy_is_deleted(
        self, test_db_session: AsyncSession, root: Path, now: datetime
    ) -> None:
        path = _staged(root, f"manifest_{uuid.uuid4().hex}_roads.geojson", now)
        await _job(test_db_session, path, now)

        await _run(test_db_session, now)

        assert not path.exists()

    async def test_a_shared_fan_out_upload_goes_once_every_layer_is_done(
        self, test_db_session: AsyncSession, root: Path, now: datetime
    ) -> None:
        path = await _upload(test_db_session, root, now, status="fanned_out")
        for _ in range(2):
            await _job(test_db_session, path, now)

        await _run(test_db_session, now)

        assert not path.exists()

    @pytest.mark.parametrize("unbound", ["", None], ids=["empty", "null"])
    async def test_an_upload_whose_request_died_before_the_bind(
        self,
        test_db_session: AsyncSession,
        root: Path,
        now: datetime,
        unbound: str | None,
    ) -> None:
        """The row was committed before the file and settled before its path was bound."""
        path = await _upload(
            test_db_session, root, now, file_path=unbound, status="cancelled"
        )

        await _run(test_db_session, now)

        assert not path.exists()

    async def test_an_upload_whose_job_was_purged(
        self, test_db_session: AsyncSession, root: Path, now: datetime
    ) -> None:
        path = _staged(root, f"{uuid.uuid4()}_roads.geojson", now)

        outcome = await _run(test_db_session, now)

        assert not path.exists()
        assert outcome.uploads_deleted == 1


class TestWhatKeepsAnUpload:
    @pytest.mark.parametrize("status", ["pending", "running", "failed"])
    async def test_a_job_that_can_still_read_it(
        self, test_db_session: AsyncSession, root: Path, now: datetime, status: str
    ) -> None:
        path = await _upload(test_db_session, root, now, status=status)

        outcome = await _run(test_db_session, now)

        assert path.exists()
        assert outcome.skipped_needed == 1

    @pytest.mark.parametrize(
        "mark",
        [{"archive_failed": True}, {ARCHIVE_PENDING_METADATA_KEY: True}],
        ids=["archive_failed", "archive_pending"],
    )
    async def test_an_original_not_yet_archived(
        self, test_db_session: AsyncSession, root: Path, now: datetime, mark: dict
    ) -> None:
        dataset = await create_dataset(
            test_db_session,
            created_by=await get_user_id(test_db_session, "admin"),
            name="Unarchived original",
        )
        path = await _upload(
            test_db_session, root, now, user_metadata=mark, dataset_id=dataset.id
        )

        await _run(test_db_session, now)

        assert path.exists()

    async def test_publish_follow_ups_still_owed(
        self, test_db_session: AsyncSession, root: Path, now: datetime
    ) -> None:
        """The follow-ups delete the upload themselves; the sweep leaves it to them."""
        record = {
            "task": "ingest_file",
            "attempt_id": str(uuid.uuid4()),
            "reaps_staged_upload": True,
        }
        path = await _upload(
            test_db_session,
            root,
            now,
            user_metadata={PUBLISH_FOLLOWUPS_FIELD: record},
        )

        await _run(test_db_session, now)

        assert path.exists()

    async def test_a_fan_out_layer_still_importing_the_parents_upload(
        self, test_db_session: AsyncSession, root: Path, now: datetime
    ) -> None:
        path = await _upload(test_db_session, root, now, status="fanned_out")
        await _job(test_db_session, path, now)
        await _job(test_db_session, path, now, status="running")

        await _run(test_db_session, now)

        assert path.exists()

    async def test_a_job_that_ended_within_the_threshold(
        self, test_db_session: AsyncSession, root: Path, now: datetime
    ) -> None:
        """An old upload whose job only just finished: its own cleanup goes first."""
        path = await _upload(test_db_session, root, now, ended=_recent())

        await _run(test_db_session, now)

        assert path.exists()

    async def test_a_job_created_long_ago_that_ended_within_the_threshold(
        self, test_db_session: AsyncSession, root: Path, now: datetime
    ) -> None:
        """Age runs from the job's end when it has one, not from its creation."""
        path = await _upload(
            test_db_session,
            root,
            now,
            status="fanned_out",
            created=_old(),
            ended=_recent(),
        )

        await _run(test_db_session, now)

        assert path.exists()

    async def test_a_file_written_within_the_threshold(
        self, test_db_session: AsyncSession, root: Path, now: datetime
    ) -> None:
        job_id = uuid.uuid4()
        path = _staged(root, f"{job_id}_roads.geojson", now, age=_recent())
        await _job(test_db_session, path, now, job_id=job_id)

        outcome = await _run(test_db_session, now)

        assert path.exists()
        assert outcome.candidates == 0

    async def test_a_row_naming_the_resolved_spelling(
        self, test_db_session: AsyncSession, root: Path, now: datetime, tmp_path: Path
    ) -> None:
        """A staging root reached through a symlink: a row may name either spelling."""
        linked_root = tmp_path / "staging-link"
        linked_root.symlink_to(root, target_is_directory=True)
        settings.upload_staging_dir = str(linked_root)
        job_id = uuid.uuid4()
        name = f"{job_id}_roads.geojson"
        _staged(root, name, now)
        await _job(test_db_session, linked_root / name, now, job_id=job_id)
        await _job(test_db_session, root.resolve() / name, now, status="failed")

        await _run(test_db_session, now)

        assert (root / name).exists()


class TestAnUploadBeforeItsBind:
    """A `{job id}_` file its job's row does not name yet: that row's rules decide."""

    async def test_kept_while_the_upload_request_is_recent(
        self, test_db_session: AsyncSession, root: Path, now: datetime
    ) -> None:
        path = await _upload(
            test_db_session, root, now, file_path="", status="pending", ended=_recent()
        )

        await _run(test_db_session, now)

        assert path.exists()

    async def test_kept_while_its_job_is_pending_however_old(
        self, test_db_session: AsyncSession, root: Path, now: datetime
    ) -> None:
        path = await _upload(test_db_session, root, now, file_path="", status="pending")

        outcome = await _run(test_db_session, now)

        assert path.exists()
        assert outcome.skipped_needed == 1


class TestWhatIsNeverAnUpload:
    async def test_an_operator_seed_even_when_a_row_names_it(
        self, test_db_session: AsyncSession, root: Path, now: datetime
    ) -> None:
        seed = _staged(root, "roads.geojson", now)
        await _job(test_db_session, seed, now)

        outcome = await _run(test_db_session, now)

        assert seed.exists()
        assert outcome.candidates == 0

    async def test_a_manifest_shaped_file_no_row_names(
        self, test_db_session: AsyncSession, root: Path, now: datetime
    ) -> None:
        """Its name carries no job, so only a row naming it proves it is an upload."""
        stray = _staged(root, f"manifest_{uuid.uuid4().hex}_roads.geojson", now)

        outcome = await _run(test_db_session, now)

        assert stray.exists()
        assert outcome.skipped_unidentified == 1

    @pytest.mark.parametrize("status", ["running", "complete"])
    async def test_a_copy_of_an_upload_its_job_keeps_in_object_storage(
        self, test_db_session: AsyncSession, root: Path, now: datetime, status: str
    ) -> None:
        """A download or leftover local copy of a job whose row names its storage key."""
        job_id = uuid.uuid4()
        copy = _staged(root, f"{job_id}_a1b2c3d4_roads.geojson", now)
        await _job(
            test_db_session,
            f"staging/{job_id}/roads.geojson",
            now,
            job_id=job_id,
            status=status,
        )

        outcome = await _run(test_db_session, now)

        assert copy.exists()
        assert outcome.skipped_unidentified == 1

    @pytest.mark.parametrize("subdir", ["exports", "originals/dataset"])
    async def test_a_file_in_a_subdirectory(
        self, test_db_session: AsyncSession, root: Path, now: datetime, subdir: str
    ) -> None:
        directory = root / subdir
        directory.mkdir(parents=True)
        nested = _staged(directory, f"{uuid.uuid4()}_roads.geojson", now)
        await _job(test_db_session, nested, now)

        await _run(test_db_session, now)

        assert nested.exists()

    async def test_a_symlink_or_a_directory(
        self, test_db_session: AsyncSession, root: Path, now: datetime, tmp_path: Path
    ) -> None:
        target = _staged(tmp_path, "elsewhere.geojson", now)
        link = root / f"{uuid.uuid4()}_roads.geojson"
        link.symlink_to(target)
        directory = root / f"{uuid.uuid4()}_layers"
        directory.mkdir()
        for path in (link, directory):
            _age(path, now)
            await _job(test_db_session, path, now)

        outcome = await _run(test_db_session, now)

        assert link.is_symlink() and target.exists() and directory.is_dir()
        assert outcome.candidates == 0


class TestRaces:
    @staticmethod
    def _after_lookup(monkeypatch, action):
        """Run ``action`` once the batch lookup has read the rows, before any recheck."""
        original = module._verdicts
        calls = 0

        async def looked_up(*args, **kwargs):
            nonlocal calls
            verdicts = await original(*args, **kwargs)
            calls += 1
            if calls == 1:
                await action()
            return verdicts

        monkeypatch.setattr(module, "_verdicts", looked_up)

    async def test_a_row_committed_after_the_lookup_keeps_the_file(
        self, test_db_session: AsyncSession, root: Path, now: datetime, monkeypatch
    ) -> None:
        import app.core.db as db_module

        path = await _upload(test_db_session, root, now)

        async def retry_lands() -> None:
            async with db_module.async_session() as other:
                await _job(other, path, now, status="pending")

        self._after_lookup(monkeypatch, retry_lands)

        outcome = await _run(test_db_session, now)

        assert path.exists()
        assert outcome.skipped_needed == 1

    async def test_a_row_deleted_after_the_lookup_leaves_the_file_unidentified(
        self, test_db_session: AsyncSession, root: Path, now: datetime, monkeypatch
    ) -> None:
        import app.core.db as db_module

        path = _staged(root, f"manifest_{uuid.uuid4().hex}_roads.geojson", now)
        job_id = await _job(test_db_session, path, now)

        async def row_purged() -> None:
            async with db_module.async_session() as other:
                await other.execute(delete(IngestJob).where(IngestJob.id == job_id))
                await other.commit()

        self._after_lookup(monkeypatch, row_purged)

        outcome = await _run(test_db_session, now)

        assert path.exists()
        assert outcome.skipped_unidentified == 1

    async def test_a_file_rewritten_after_the_lookup_is_kept(
        self, test_db_session: AsyncSession, root: Path, now: datetime, monkeypatch
    ) -> None:
        path = await _upload(test_db_session, root, now)

        async def rewritten() -> None:
            path.write_bytes(b"new bytes")

        self._after_lookup(monkeypatch, rewritten)

        outcome = await _run(test_db_session, now)

        assert path.read_bytes() == b"new bytes"
        assert outcome.skipped_changed == 1

    async def test_a_file_swapped_for_a_symlink_after_the_lookup_is_kept(
        self,
        test_db_session: AsyncSession,
        root: Path,
        now: datetime,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        path = await _upload(test_db_session, root, now)
        target = _staged(tmp_path, "elsewhere.geojson", now)

        async def swapped() -> None:
            path.unlink()
            path.symlink_to(target)
            _age(path, now)

        self._after_lookup(monkeypatch, swapped)

        outcome = await _run(test_db_session, now)

        assert path.is_symlink() and target.exists()
        assert outcome.skipped_changed == 1

    async def test_a_file_gone_before_its_delete_is_not_a_failure(
        self, test_db_session: AsyncSession, root: Path, now: datetime, monkeypatch
    ) -> None:
        path = await _upload(test_db_session, root, now)

        async def removed() -> None:
            path.unlink()

        self._after_lookup(monkeypatch, removed)

        outcome = await _run(test_db_session, now)

        assert (outcome.skipped_changed, outcome.delete_failures) == (1, 0)


def _unlink_fails_for(monkeypatch, name: str) -> None:
    original = Path.unlink

    def unlink(self, *args, **kwargs):
        if self.name == name:
            raise PermissionError("read-only")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)


class TestFailuresAndBudgets:
    async def test_a_failed_delete_is_counted_and_the_pass_continues(
        self, test_db_session: AsyncSession, root: Path, now: datetime, monkeypatch
    ) -> None:
        stuck = await _upload(test_db_session, root, now, job_id=_id_starting("0"))
        other = await _upload(test_db_session, root, now, job_id=_id_starting("f"))
        _unlink_fails_for(monkeypatch, stuck.name)

        outcome = await _run(test_db_session, now)

        assert stuck.exists() and not other.exists()
        assert (outcome.delete_failures, outcome.uploads_deleted) == (1, 1)

    async def test_deletes_stop_at_the_per_pass_budget(
        self, test_db_session: AsyncSession, root: Path, now: datetime, monkeypatch
    ) -> None:
        monkeypatch.setattr(module, "_MAX_DELETES_PER_PASS", 1)
        paths = [await _upload(test_db_session, root, now) for _ in range(2)]

        first = await _run(test_db_session, now)
        second = await _run(test_db_session, now)

        assert first.uploads_deleted == 1
        assert second.uploads_deleted == 1
        assert not any(path.exists() for path in paths)

    async def test_a_delete_that_keeps_failing_cannot_starve_the_rest(
        self, test_db_session: AsyncSession, root: Path, now: datetime, monkeypatch
    ) -> None:
        monkeypatch.setattr(module, "_MAX_DELETES_PER_PASS", 1)
        stuck = await _upload(test_db_session, root, now, job_id=_id_starting("0"))
        later = await _upload(test_db_session, root, now, job_id=_id_starting("f"))
        _unlink_fails_for(monkeypatch, stuck.name)

        await _run(test_db_session, now)
        assert later.exists()
        await _run(test_db_session, now)

        assert not later.exists()

    async def test_candidates_beyond_one_pass_are_reached_in_turn(
        self, test_db_session: AsyncSession, root: Path, now: datetime, monkeypatch
    ) -> None:
        monkeypatch.setattr(module, "_MAX_CANDIDATES_PER_PASS", 1)
        kept = await _upload(
            test_db_session, root, now, job_id=_id_starting("0"), status="failed"
        )
        later = await _upload(test_db_session, root, now, job_id=_id_starting("f"))

        await _run(test_db_session, now)
        assert later.exists()
        await _run(test_db_session, now)

        assert kept.exists() and not later.exists()

    async def test_the_window_wraps_to_names_before_the_resume_point(
        self, test_db_session: AsyncSession, root: Path, now: datetime, monkeypatch
    ) -> None:
        monkeypatch.setattr(module, "_MAX_CANDIDATES_PER_PASS", 2)
        early = await _upload(test_db_session, root, now, job_id=_id_starting("0"))
        module._resume_after = f"{_id_starting('8')}_"

        outcome = await _run(test_db_session, now)

        assert not early.exists()
        assert outcome.candidates == 1

    async def test_a_failing_pass_never_raises(
        self, test_db_session: AsyncSession, root: Path, now: datetime, monkeypatch
    ) -> None:
        def broken(*_args):
            raise OSError("staging volume unreadable")

        monkeypatch.setattr(module, "_old_upload_files", broken)

        outcome = await _run(test_db_session, now)

        assert outcome.ran and outcome.uploads_deleted == 0


async def test_multi_tenant_mode_declines(
    test_db_session: AsyncSession, root: Path, now: datetime
) -> None:
    """Row-level security would hide other tenants' rows, so nothing can be judged."""
    path = await _upload(test_db_session, root, now)

    with patch("app.core.tenancy.is_multi_tenant", return_value=True):
        outcome = await _run(test_db_session, now)

    assert path.exists()
    assert not outcome.ran


class _Bucket:
    """Just enough object storage for the storage pass."""

    def __init__(self, objects: dict[str, datetime]) -> None:
        self.objects = dict(objects)

    async def iter_object_pages(self, prefix: str, *, start_after: str | None = None):
        yield [
            StoredObject(key=key, last_modified=modified)
            for key, modified in sorted(self.objects.items())
            if key.startswith(prefix) and (start_after is None or key > start_after)
        ]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class TestWiring:
    """The stale-job sweep and the admin cleanup both reach the pass through here."""

    async def test_the_staging_reconciliation_runs_the_local_pass(
        self, test_db_session: AsyncSession, root: Path, now: datetime, monkeypatch
    ) -> None:
        from app.platform.jobs.staging_reconcile import (
            reconcile_orphaned_staging_objects,
        )

        monkeypatch.setattr(settings, "storage_provider", "local")
        path = await _upload(test_db_session, root, now)

        await reconcile_orphaned_staging_objects(test_db_session, now=now)

        assert not path.exists()

    async def test_a_database_error_in_the_local_pass_leaves_the_storage_pass_running(
        self, test_db_session: AsyncSession, root: Path, now: datetime, monkeypatch
    ) -> None:
        import app.platform.jobs.staging_reconcile as storage_pass

        async def failing_lookup(db, *_args):
            await db.execute(text("SELECT 1 / 0"))

        monkeypatch.setattr(module, "_verdicts", failing_lookup)
        monkeypatch.setattr(settings, "storage_provider", "s3")
        monkeypatch.setitem(
            storage_pass._scan_cursors, storage_pass.STAGING_PREFIX, None
        )
        await _upload(test_db_session, root, now)
        orphan = f"staging/{uuid.uuid4()}/roads.geojson"
        bucket = _Bucket({orphan: now - _old()})

        with patch("app.platform.storage.get_storage", return_value=bucket):
            outcome = await storage_pass.reconcile_orphaned_staging_objects(
                test_db_session, now=now
            )

        assert outcome.ran and outcome.orphans_deleted == 1
        assert orphan not in bucket.objects
