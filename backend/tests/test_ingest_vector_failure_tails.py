"""fix(#1778): the two exits a vector import takes when it does not succeed.

Both were copies. The upload-safety validation exit is pasted into four ingest
tasks and the #1290 "NO unlink" correction reached only the two raster ones, so
on a local-storage install a worker-side validation failure deleted the user's
only copy of the file it had just recorded as failed. The terminal failure
write is pasted into four tasks as well, and the shared helper the re-upload
doors use is the one that emits ``ingest_failed`` — so an operator who had
switched failure mail on heard about raster imports and re-uploads and heard
nothing when a vector file import, a service import or a VRT build failed.

Both are asserted by driving the real task, not by reading the source.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select

from app.modules.auth.models import User
from app.platform.jobs.models import IngestJob
from app.processing.ingest.tasks_vector import ingest_file

pytestmark = pytest.mark.anyio


_GEOJSON = (
    b'{"type":"FeatureCollection","features":['
    b'{"type":"Feature","properties":{"name":"a"},'
    b'"geometry":{"type":"Point","coordinates":[1.0,2.0]}}]}'
)


async def _admin_id(session) -> uuid.UUID:
    return (
        await session.execute(select(User.id).where(User.username == "admin"))
    ).scalar_one()


async def _queue_upload(session, *, file_path: str, user_id: uuid.UUID) -> IngestJob:
    """A pending file-import job bound to a LOCAL staging path.

    ``file_path == original_file_path`` is the shape that matters here: on a
    local-storage install ``resolve_file_path`` returns the path unchanged, so
    this IS the durable original rather than a downloaded scratch copy.
    """
    job = IngestJob(
        source_filename="points.geojson",
        file_path=file_path,
        created_by=user_id,
        status="pending",
        user_metadata={"title": "Points"},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _drop_job(session, job_id: uuid.UUID) -> None:
    await session.execute(delete(IngestJob).where(IngestJob.id == job_id))
    await session.commit()


class TestValidationExitKeepsTheLocalOriginal:
    """The #1290 correction, applied to the copy that missed it.

    The canonical trigger needs no attacker: lowering ``UPLOAD_MAX_SIZE_MB``
    while a job sits queued fails it at worker pickup, and the exit used to
    unlink unconditionally.
    """

    async def test_a_local_upload_survives_a_worker_side_validation_failure(
        self, test_db_session, tmp_path
    ) -> None:
        from app.core.persistent_config import UPLOAD_MAX_SIZE_MB

        source = tmp_path / "points.geojson"
        source.write_bytes(_GEOJSON)
        admin_id = await _admin_id(test_db_session)
        job = await _queue_upload(
            test_db_session, file_path=str(source), user_id=admin_id
        )
        job_id = job.id

        try:
            with patch.object(UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=0)):
                await ingest_file.func(
                    job_id=str(job_id),
                    file_path=str(source),
                    user_id=str(admin_id),
                    attempt_id=str(job.attempt_id),
                )

            test_db_session.expire_all()
            finished = (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id == job_id)
                )
            ).scalar_one()
            assert finished.status == "failed", "precondition: the size check refused"
            assert "exceeds the maximum" in (finished.error_message or "")
            assert source.exists(), (
                "the validation exit deleted the uploaded file. On a "
                "local-storage install that is the only copy, and the job it "
                "just recorded as failed now has nothing to diagnose from and "
                "nothing to retry from (#1290)."
            )
        finally:
            await _drop_job(test_db_session, job_id)


class TestVectorFailureEmitsTheOperatorNotification:
    """The terminal failure write goes through the shared helper.

    Asserted through the real task so the test covers the wiring rather than
    the helper, which ``test_event_ingest.py`` already covers on its own.
    """

    @staticmethod
    def _capture(monkeypatch, *, toggle: bool) -> list:
        from app.core.config import settings
        from app.platform.notifications import events as events_mod

        monkeypatch.setattr(settings, "notify_on_ingest_failed", toggle, raising=False)
        emitted: list = []

        async def _fake_notify(notification):
            emitted.append(notification)

        monkeypatch.setattr(events_mod, "notify", _fake_notify)
        return emitted

    @staticmethod
    def _break_ogrinfo(monkeypatch, message: str) -> None:
        async def _raise(*args, **kwargs):
            raise RuntimeError(message)

        monkeypatch.setattr(
            "app.processing.ingest.ogr.run_ogrinfo", _raise, raising=True
        )

    async def _run_failing_import(self, session, tmp_path, monkeypatch, message):
        source = tmp_path / "points.geojson"
        source.write_bytes(_GEOJSON)
        admin_id = await _admin_id(session)
        job = await _queue_upload(session, file_path=str(source), user_id=admin_id)
        self._break_ogrinfo(monkeypatch, message)
        with pytest.raises(RuntimeError):
            await ingest_file.func(
                job_id=str(job.id),
                file_path=str(source),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )
        return job.id

    async def test_a_failed_vector_import_notifies_the_operator(
        self, test_db_session, tmp_path, monkeypatch
    ) -> None:
        emitted = self._capture(monkeypatch, toggle=True)
        message = "ogrinfo could not read the layer"
        job_id = await self._run_failing_import(
            test_db_session, tmp_path, monkeypatch, message
        )

        try:
            assert len(emitted) == 1, (
                "a vector file import failed and the operator was told "
                f"nothing (emitted={emitted})"
            )
            note = emitted[0]
            assert note.event_type == "ingest_failed"
            assert note.data.get("task") == "ingest_file", (
                "the notification must name the tail it came from, or this "
                "assertion would pass on a raster path's emission"
            )
            assert message in (note.data.get("reason") or "")

            test_db_session.expire_all()
            finished = (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id == job_id)
                )
            ).scalar_one()
            assert finished.status == "failed"
            assert message in (finished.error_message or "")
        finally:
            await _drop_job(test_db_session, job_id)

    async def test_nothing_is_emitted_while_the_toggle_is_off(
        self, test_db_session, tmp_path, monkeypatch
    ) -> None:
        """The negative control: the assertion above is about the toggle an
        operator actually set, not about an unconditional email."""
        emitted = self._capture(monkeypatch, toggle=False)
        job_id = await self._run_failing_import(
            test_db_session, tmp_path, monkeypatch, "ogrinfo blew up"
        )
        try:
            assert emitted == []
        finally:
            await _drop_job(test_db_session, job_id)


class TestNoImportTailStillHandRollsItsFailureWrite:
    """Structural, because the finding is that the write was COPIED.

    Four tasks pasted a narrower version of the terminal UPDATE, and each copy
    quietly dropped the redaction backstop, the pending-inclusive attempt
    fence and the notification. ``ingest_raster`` keeps its own copy on
    purpose — it is the one tail that already emits ``ingest_failed`` — and is
    named here rather than silently skipped.
    """

    def test_the_vector_and_vrt_tails_route_through_the_shared_helper(self) -> None:
        import inspect

        from app.processing.ingest import tasks_vector, tasks_vrt

        for module, funcs in (
            (tasks_vector, ("ingest_file", "ingest_service")),
            (tasks_vrt, ("ingest_vrt",)),
        ):
            for name in funcs:
                target = getattr(module, name)
                source = inspect.getsource(getattr(target, "func", target))
                assert "_cleanup_staging_on_failure" in source, (
                    f"{module.__name__}.{name} writes its own terminal "
                    "failure row instead of routing through the shared "
                    "helper, so its failures emit no ingest_failed "
                    "notification"
                )


class TestACleanupFailureCannotSwallowTheFailureWrite:
    """fix(#1778 codex r2): the order inside the shared helper.

    PostgreSQL aborts the whole transaction on any statement error, so with
    the staging DROP running first, a drop that hit a lock or statement
    timeout left the session unusable and the failure UPDATE that followed it
    raised `current transaction is aborted`. The job stayed `running` until
    the stale sweep, and the reason nobody recorded was the one the user
    needed. The failure row is written and committed first now.
    """

    @staticmethod
    def _break_the_drop(monkeypatch) -> None:
        """Make the DROP fail at the SERVER, which is what aborts the
        transaction. A double raised in Python would leave the session healthy
        and the reordering counterfactual would pass for the wrong reason."""
        import app.processing.ingest.metadata as metadata_mod

        real_qtable = metadata_mod._qtable

        def _malformed(table_name: str, schema: str = "data") -> str:
            real_qtable(table_name, schema=schema)  # keep the identifier checks
            return '"data"."x" ,,,'

        monkeypatch.setattr(metadata_mod, "_qtable", _malformed, raising=True)

    async def test_the_job_still_records_the_original_failure(
        self, test_db_session, monkeypatch
    ) -> None:
        from app.core.db import async_session
        from app.processing.ingest.tasks_common import _cleanup_staging_on_failure

        admin_id = await _admin_id(test_db_session)
        job = IngestJob(
            source_filename="points.geojson",
            created_by=admin_id,
            status="running",
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)
        job_id = job.id
        attempt_id = job.attempt_id

        self._break_the_drop(monkeypatch)

        try:
            async with async_session() as err_session:
                err_job = (
                    await err_session.execute(
                        select(IngestJob).where(IngestJob.id == job_id)
                    )
                ).scalar_one()
                await _cleanup_staging_on_failure(
                    err_session,
                    staging_table="roads_staging_deadbeef",
                    job=err_job,
                    exc=RuntimeError("ogr2ogr could not read the layer"),
                    task_name="ingest_file",
                    attempt_id=attempt_id,
                )

            test_db_session.expire_all()
            finished = (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id == job_id)
                )
            ).scalar_one()
            assert finished.status == "failed", (
                "a staging-table cleanup error swallowed the failure write, so "
                "the job sits running with no reason until the stale sweep"
            )
            assert "could not read the layer" in (finished.error_message or "")
            assert finished.completed_at is not None
        finally:
            await _drop_job(test_db_session, job_id)

    def test_the_drop_runs_after_the_failure_commit(self) -> None:
        """Structural, because the property is an ORDER and the behavioural
        test above can only observe one half of it."""
        import ast
        import inspect

        import app.processing.ingest.tasks_common as tc_mod

        tree = ast.parse(inspect.getsource(tc_mod._cleanup_staging_on_failure))
        drop_lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "DROP TABLE IF EXISTS" in node.value
        ]
        status_lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.keyword)
            and node.arg == "status"
            and isinstance(node.value, ast.Constant)
            and node.value.value == "failed"
        ]
        assert drop_lines and status_lines, "the helper's shape changed"
        assert min(drop_lines) > min(status_lines), (
            "the staging DROP runs before the failure UPDATE again. A DDL "
            "error aborts the transaction, and every statement after it on "
            "that session raises until a rollback."
        )
