"""A job asking for public is judged by the restriction as it is when it runs.

Each job here is admitted while public visibility is open to everyone, and
"restrict public visibility to admins" is turned on before its worker runs,
or while it runs. The worker reads the setting and the roles of the account
it publishes for again, just before it writes: a non-admin's job fails and
the dataset keeps its data and visibility, an admin's publishes, and a
version 2 entry with ``public_fallback`` lands internal with its warning. A
job that asks for less than public, or for public on a dataset already
public, is not refused.
"""

from __future__ import annotations

import shutil
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text, update

from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import UNPUBLISHED_STORAGE_KEYS_FIELD, IngestJob
from app.platform.record_audience import PUBLIC_VISIBILITY_DENIED
from app.processing.ingest.publication import WriteAccessRevoked
from tests.factories import create_user
from tests.test_manifest_dataset_fields import (
    _apply,
    _entry,
    _finalize,
    _manifest_dataset,
    _queue_update,
    _record,
    _request,
    _run_update,
    _stage_fixture,
    _uploaded,
)
from tests.test_raster_replace_1221 import raster_storage as raster_storage
from tests.write_recheck_races import _commit, _move_to_role
from tests.test_regenerate_vrt_integration import (  # noqa: F401 -- fixtures
    local_storage,
    quicklook_stub,
    source_tifs,
    vrt_db_state,
)

pytestmark = pytest.mark.anyio

_REFUSED = ("failed", PUBLIC_VISIBILITY_DENIED, "public_visibility_restricted")
# What the dataset's refresh history shows for the refused replacement.
_RUN_REFUSED = ("failed", "public_visibility_restricted")

_A020 = [{"kind": "manifest_public_fallback", "details": {"reason": "restriction"}}]
_needs_ogr2ogr = pytest.mark.skipif(
    shutil.which("ogr2ogr") is None, reason="needs ogr2ogr"
)


class _Restriction:
    """``restrict_public_visibility``, switched by the test. The cached read
    still answers off, as a cache warmed before the switch would, so only a
    read of the stored value sees it on."""

    on = False

    async def get(self, _db):
        return False

    async def get_uncached(self, _db):
        return self.on


@pytest.fixture
def restriction(monkeypatch) -> _Restriction:
    import app.core.persistent_config as pc

    switch = _Restriction()
    monkeypatch.setattr(pc, "RESTRICT_PUBLIC_VISIBILITY", switch)
    return switch


async def _submitter(client, session, admin_auth_header, role: str):
    """A new account with ``role``: its headers and its row."""
    headers, user_id = await create_user(client, admin_auth_header, role)
    return headers, await session.get(User, uuid.UUID(user_id))


async def _v1_applier(client, session, admin_auth_header) -> User:
    """An admin to apply a version 1 entry, whose sources are local files only
    an admin may read; a test moves them to editor before the worker runs."""
    _, user = await _submitter(client, session, admin_auth_header, "admin")
    return user


async def _job(session, job_id) -> IngestJob:
    return (
        await session.execute(
            select(IngestJob)
            .where(IngestJob.id == job_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _run_outcome(session, job_id) -> tuple[str, str | None]:
    """The status and code of the refresh run a replacement job settled."""
    from app.platform.refresh.models import DatasetRefreshRun

    return tuple(
        (
            await session.execute(
                select(DatasetRefreshRun.status, DatasetRefreshRun.error_code)
                .where(DatasetRefreshRun.ingest_job_id == job_id)
                .execution_options(populate_existing=True)
            )
        ).one()
    )


async def _attempt_tables(session, attempt_id) -> list[str]:
    """Tables an attempt staged that are still there."""
    hex_id = uuid.UUID(str(attempt_id)).hex
    rows = await session.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'data' AND table_name LIKE :pattern"
        ),
        {"pattern": f"%_staging_{hex_id}"},
    )
    return [row[0] for row in rows]


async def _current_version(session, dataset_id) -> int | None:
    return await session.scalar(
        select(Dataset.current_version)
        .where(Dataset.id == dataset_id)
        .execution_options(populate_existing=True)
    )


# ---------------------------------------------------------------------------
# Creates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "version", "extra", "ending"),
    [
        ("editor", "1", {}, None),
        ("admin", "1", {}, ("public", "published")),
        ("editor", "2", {"public_fallback": "internal"}, ("internal", "published")),
        ("editor", "2", {}, None),
        ("editor", "1-internal", {}, ("internal", "internal")),
    ],
    ids=["v1-editor", "v1-admin", "v2-fallback", "v2-no-fallback", "v1-internal"],
)
async def test_a_manifest_create_is_judged_by_the_restriction_when_it_runs(
    client,
    test_db_session,
    admin_auth_header,
    clean_tables,
    restriction,
    role,
    version,
    extra,
    ending,
):
    key = f"in-flight-create-{uuid.uuid4().hex[:8]}"
    if version == "2":
        headers, user = await _submitter(
            client, test_db_session, admin_auth_header, role
        )
        entry = await _uploaded(client, headers, key, visibility="public")
        request = _request(entry, **extra)
    else:
        user = await _v1_applier(client, test_db_session, admin_auth_header)
        intent = "internal" if version == "1-internal" else "published"
        _stage_fixture()
        request = _request(_entry(key, publication={"intent": intent}), version="1")
    response, _ = await _apply(test_db_session, user, request)
    result = response.results[0]
    assert (result.action, result.messages or []) == ("create", []), result
    job = await test_db_session.get(IngestJob, result.job_id)
    assert "admitted_public_visibility" not in job.user_metadata

    if version != "2" and role == "editor":
        await _commit(_move_to_role(user.id, "editor"))
    restriction.on = True

    if ending is None:
        user_id = user.id
        with pytest.raises(WriteAccessRevoked) as refused:
            await _finalize(test_db_session, user, job)
        assert str(refused.value) == PUBLIC_VISIBILITY_DENIED
        await test_db_session.rollback()
        assert (
            await test_db_session.scalar(
                select(Record.id).where(Record.created_by == user_id)
            )
        ) is None
        return
    dataset = await _finalize(test_db_session, user, job)
    assert (dataset.record.visibility, dataset.record.record_status) == ending
    expected = _A020 if extra else None
    assert job.user_metadata.get("warnings") == expected


@pytest.mark.parametrize(
    ("visibility", "refused"), [("public", True), ("internal", False)]
)
async def test_an_upload_committed_public_is_judged_when_it_runs(
    client, test_db_session, admin_auth_header, restriction, visibility, refused
):
    _, editor = await _submitter(client, test_db_session, admin_auth_header, "editor")
    editor_id = editor.id
    job = IngestJob(
        source_filename="roads.geojson",
        file_path="/tmp/roads.geojson",
        created_by=editor_id,
        status="pending",
        user_metadata={"title": "Plain upload", "visibility": visibility},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    restriction.on = True

    try:
        if refused:
            with pytest.raises(WriteAccessRevoked) as error:
                await _finalize(test_db_session, editor, job)
            assert str(error.value) == PUBLIC_VISIBILITY_DENIED
            await test_db_session.rollback()
            return
        dataset = await _finalize(test_db_session, editor, job)
        assert dataset.record.visibility == "internal"
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE created_by = :user"),
            {"user": editor_id},
        )
        await test_db_session.execute(
            text("DELETE FROM catalog.ingest_jobs WHERE created_by = :user"),
            {"user": editor_id},
        )
        await test_db_session.commit()


_GEOJSON = (
    b'{"type":"FeatureCollection","features":['
    b'{"type":"Feature","properties":{"name":"a"},'
    b'"geometry":{"type":"Point","coordinates":[1.0,2.0]}}]}'
)


_OGRINFO = {
    "srid": 4326,
    "geometry_type": "Point",
    "columns": [{"name": "name", "type": "String"}],
}


async def _run_ingest_file(kwargs: dict, *, at: str | None = None, step=None) -> None:
    """The whole vector import task over a stand-in ogr2ogr, awaiting
    ``step()`` once the staged table is normalized (``at="staging"``) or
    once the new dataset's quality is scored (``at="scoring"``)."""
    from tests.test_admin_dataset_list_after_publish import _fake_ogr2ogr

    from app.processing.ingest import metadata, tasks_staging
    from app.processing.ingest.tasks_vector import ingest_file

    staging = tasks_staging._run_staging_pipeline
    score = metadata.compute_quality_score

    async def staged_then(*args, **kw):
        result = await staging(*args, **kw)
        if at == "staging":
            await step()
        return result

    async def scored_then(*args, **kw):
        result = await score(*args, **kw)
        if at == "scoring":
            await step()
        return result

    with (
        patch(
            "app.processing.ingest.service.resolve_file_path",
            AsyncMock(side_effect=lambda path, job_id: path),
        ),
        patch(
            "app.processing.ingest.ogr.run_ogrinfo", AsyncMock(return_value=_OGRINFO)
        ),
        patch("app.processing.ingest.ogr.run_ogr2ogr", new=_fake_ogr2ogr),
        patch("app.processing.ingest.metadata.grant_reader_access", AsyncMock()),
        patch(
            "app.processing.ingest.publish_followups.invalidate_catalog_cache",
            AsyncMock(),
        ),
        patch("app.processing.embeddings.helpers.defer_embedding", AsyncMock()),
        patch.object(tasks_staging, "_run_staging_pipeline", staged_then),
        patch.object(metadata, "compute_quality_score", scored_then),
    ):
        await ingest_file.func(**kwargs)


@pytest.mark.parametrize("when", ["before-the-worker", "staging", "scoring"])
async def test_a_refused_vector_import_drops_its_staged_table(
    client, test_db_session, admin_auth_header, restriction, tmp_path, when
):
    """The whole import task: the job fails with the restriction's coded
    reason, nothing is published, and the table ogr2ogr staged is dropped.
    Turned on after staging, or once the new record exists and its quality
    is scored, the restriction is still seen before the commit, which rolls
    the record back."""
    _, editor = await _submitter(client, test_db_session, admin_auth_header, "editor")
    editor_id = editor.id
    source = tmp_path / "points.geojson"
    source.write_bytes(_GEOJSON)
    job = IngestJob(
        source_filename="points.geojson",
        file_path=str(source),
        created_by=editor_id,
        status="pending",
        user_metadata={"title": "Refused points", "visibility": "public"},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    job_id, attempt_id = job.id, job.attempt_id

    async def restrict() -> None:
        restriction.on = True

    if when == "before-the-worker":
        await restrict()
    try:
        with pytest.raises(WriteAccessRevoked):
            await _run_ingest_file(
                {
                    "job_id": str(job_id),
                    "file_path": str(source),
                    "user_id": str(editor_id),
                    "attempt_id": str(attempt_id),
                },
                at=None if when == "before-the-worker" else when,
                step=restrict,
            )

        failed = await _job(test_db_session, job_id)
        assert (failed.status, failed.error_message, failed.error_code) == _REFUSED
        assert failed.dataset_id is None
        assert await _attempt_tables(test_db_session, attempt_id) == []
        assert (
            await test_db_session.scalar(
                select(Record.id).where(Record.created_by == editor_id)
            )
        ) is None
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(
            text("DELETE FROM catalog.ingest_jobs WHERE created_by = :user"),
            {"user": editor_id},
        )
        await test_db_session.commit()


@pytest.mark.parametrize("committer", ["admin", "uploader"])
async def test_a_commit_is_judged_for_the_account_it_publishes_for(
    client, test_db_session, admin_auth_header, restriction, tmp_path, committer
):
    """An editor's pending upload, committed public. An admin may commit it
    for themselves while public is restricted, and the dataset is theirs;
    the editor's own commit, admitted while public was open, is refused
    once the restriction is on."""
    from tests.test_import_commit_admission import _ingest_task

    headers, editor = await _submitter(
        client, test_db_session, admin_auth_header, "editor"
    )
    editor_id = editor.id
    source = tmp_path / "roads.geojson"
    source.write_bytes(_GEOJSON)
    job = IngestJob(
        source_filename="roads.geojson",
        file_path=str(source),
        created_by=editor_id,
        status="pending",
        attempt_id=uuid.uuid4(),
    )
    test_db_session.add(job)
    await test_db_session.commit()
    job_id = job.id
    queued: list[dict] = []

    async def capture(**kwargs) -> None:
        queued.append(kwargs)

    restriction.on = committer == "admin"
    try:
        with _ingest_task(capture):
            committed = await client.post(
                f"/ingest/commit/{job_id}",
                json={"title": "Committed roads", "visibility": "public"},
                headers=admin_auth_header if committer == "admin" else headers,
            )
        assert committed.status_code == 202, committed.text
        restriction.on = True

        if committer == "admin":
            await _run_ingest_file(queued[0])
            done = await _job(test_db_session, job_id)
            assert (done.status, done.error_message) == ("complete", None)
            record = (
                await test_db_session.execute(
                    select(Record.visibility, Record.created_by)
                    .join(Dataset, Dataset.record_id == Record.id)
                    .where(Dataset.id == done.dataset_id)
                )
            ).one()
            assert record.visibility == "public"
            assert record.created_by != editor_id
            return
        with pytest.raises(WriteAccessRevoked):
            await _run_ingest_file(queued[0])
        failed = await _job(test_db_session, job_id)
        assert (failed.status, failed.error_message, failed.error_code) == _REFUSED
        assert failed.dataset_id is None
    finally:
        await test_db_session.rollback()
        dataset_id = await test_db_session.scalar(
            select(IngestJob.dataset_id).where(IngestJob.id == job_id)
        )
        if dataset_id is not None:
            from tests.test_raster_replace_1221 import _purge

            record_id = await test_db_session.scalar(
                select(Dataset.record_id).where(Dataset.id == dataset_id)
            )
            table = await test_db_session.scalar(
                select(Dataset.table_name).where(Dataset.id == dataset_id)
            )
            await _purge(test_db_session, dataset_id=dataset_id, record_id=record_id)
            await test_db_session.execute(text(f'DROP TABLE IF EXISTS data."{table}"'))
        await test_db_session.execute(
            text("DELETE FROM catalog.ingest_jobs WHERE created_by = :user"),
            {"user": editor_id},
        )
        await test_db_session.commit()


@pytest.mark.parametrize("when", ["before-the-worker", "while-storing"])
async def test_a_raster_create_asking_for_public_is_judged_when_it_runs(
    client,
    test_db_session,
    admin_auth_header,
    restriction,
    raster_storage,
    tmp_path,
    monkeypatch,
    when,
):
    """Refused before anything is stored, or, turned on while the COG is
    stored, before the record commits; the attempt's keys are reaped."""
    from tests.test_raster_replace_1221 import _geotiff_bytes

    from app.processing.ingest.tasks_raster import ingest_raster

    _, editor = await _submitter(client, test_db_session, admin_auth_header, "editor")
    editor_id = editor.id
    source = tmp_path / "dem.tif"
    source.write_bytes(_geotiff_bytes(seed=4036))
    job = IngestJob(
        source_filename="dem.tif",
        file_path=str(source),
        created_by=editor_id,
        status="pending",
        user_metadata={
            "file_type": "raster",
            "title": "Refused DEM",
            "visibility": "public",
        },
    )
    test_db_session.add(job)
    await test_db_session.commit()
    job_id = job.id
    if when == "before-the-worker":
        restriction.on = True
    else:
        put = raster_storage.put

        async def put_then_restrict(*args, **kwargs):
            await put(*args, **kwargs)
            restriction.on = True

        monkeypatch.setattr(raster_storage, "put", put_then_restrict)

    try:
        with pytest.raises(WriteAccessRevoked):
            await ingest_raster.func(
                job_id=str(job_id),
                file_path=str(source),
                user_id=str(editor_id),
                attempt_id=str(job.attempt_id),
            )

        failed = await _job(test_db_session, job_id)
        assert (failed.status, failed.error_message, failed.error_code) == _REFUSED
        assert failed.dataset_id is None
        assert (
            await test_db_session.scalar(
                select(Record.id).where(Record.created_by == editor_id)
            )
        ) is None
        for key in failed.user_metadata.get(UNPUBLISHED_STORAGE_KEYS_FIELD, []):
            assert not await raster_storage.exists(key), key
        assert await raster_storage.list("rasters/") == []
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(
            text("DELETE FROM catalog.ingest_jobs WHERE created_by = :user"),
            {"user": editor_id},
        )
        await test_db_session.commit()


# ---------------------------------------------------------------------------
# Updates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "version", "before", "intent", "ending"),
    [
        ("editor", "1", ("private", "draft"), "published", None),
        ("admin", "1", ("private", "draft"), "published", ("public", "published")),
        ("editor", "2", ("private", "draft"), None, ("internal", "published")),
        ("editor", "1", ("private", "draft"), "internal", ("internal", "internal")),
        ("editor", "1", ("public", "draft"), "published", ("public", "published")),
    ],
    ids=["v1-editor", "v1-admin", "v2-fallback", "v1-internal", "already-public"],
)
async def test_a_manifest_update_is_judged_by_the_restriction_when_it_publishes(
    client,
    test_db_session,
    admin_auth_header,
    clean_tables,
    restriction,
    role,
    version,
    before,
    intent,
    ending,
):
    _stage_fixture()
    key = f"in-flight-update-{uuid.uuid4().hex[:8]}"
    if version == "2":
        headers, user = await _submitter(
            client, test_db_session, admin_auth_header, role
        )
        dataset_id = await _manifest_dataset(test_db_session, user, key, *before)
        entry = await _uploaded(client, headers, key, visibility="public")
        extra = {"public_fallback": "internal"}
    else:
        user = await _v1_applier(client, test_db_session, admin_auth_header)
        dataset_id = await _manifest_dataset(test_db_session, user, key, *before)
        entry = _entry(key, title="Republished", publication={"intent": intent})
        extra = {"version": "1"}
    result, task = await _queue_update(test_db_session, user, entry, **extra)
    assert result.action == "update", result
    queued = await test_db_session.get(IngestJob, result.job_id)
    assert "admitted_public_visibility" not in queued.user_metadata
    # Only the public visibility is judged here, not the admin-only local
    # source version 1 reads from.
    queued.user_metadata = {
        k: v for k, v in queued.user_metadata.items() if k != "admitted_raw_source"
    }
    await test_db_session.commit()
    version_before = await _current_version(test_db_session, dataset_id)

    if version != "2" and role == "editor":
        await _commit(_move_to_role(user.id, "editor"))
    restriction.on = True
    job = await _run_update(test_db_session, result, task)

    if ending is None:
        assert (job.status, job.error_message, job.error_code) == _REFUSED
        assert await _run_outcome(test_db_session, job.id) == _RUN_REFUSED
        assert await _record(test_db_session, dataset_id) == before
        assert await _current_version(test_db_session, dataset_id) == version_before
        attempt_id = task.defer_async.await_args.kwargs["attempt_id"]
        assert await _attempt_tables(test_db_session, attempt_id) == []
        return
    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, dataset_id) == ending
    assert job.user_metadata.get("warnings") == (_A020 if version == "2" else None)


@_needs_ogr2ogr
@pytest.mark.parametrize("role", ["editor", "admin"])
async def test_an_accepted_run_is_judged_by_the_restriction_when_it_publishes(
    client, test_db_session, admin_auth_header, clean_tables, restriction, role
):
    """Held, then accepted while public was open to everyone; the restriction
    was turned on before the accepted run's worker."""
    from tests.test_manifest_accept_publish_key import (
        _accept,
        _hold,
        _owned_by_an_editor,
    )
    from tests.test_manifest_accept_publish_key import _record as _held_record

    held = await _hold(
        test_db_session, record=("private", "draft"), visibility="public"
    )
    if role == "editor":
        held = await _owned_by_an_editor(
            client, test_db_session, admin_auth_header, held
        )
    version_before = await _current_version(test_db_session, held.dataset_id)

    async def restrict() -> None:
        restriction.on = True

    job = await _accept(
        test_db_session, held, publish_key=False, before_worker=restrict
    )

    assert "admitted_public_visibility" not in job.user_metadata
    if role == "editor":
        assert (job.status, job.error_message, job.error_code) == _REFUSED
        assert await _run_outcome(test_db_session, job.id) == _RUN_REFUSED
        assert await _held_record(test_db_session, held.dataset_id) == (
            "private",
            "draft",
        )
        assert (
            await _current_version(test_db_session, held.dataset_id) == version_before
        )
        return
    assert (job.status, job.error_message) == ("complete", None)
    assert await _held_record(test_db_session, held.dataset_id) == (
        "public",
        "published",
    )


@pytest.mark.parametrize("demoted", [True, False], ids=["now-editor", "still-admin"])
async def test_a_raster_update_is_judged_by_the_restriction_when_it_publishes(
    client, admin_auth_header, test_db_session, raster_storage, restriction, demoted
):
    """Applied by an admin owner while public was open to everyone, so nothing
    was recorded about public; the restriction was turned on, and the owner
    moved to editor or not, before the worker. A refusal comes inside the
    write, after the new COG was stored: the old COG keeps serving and the
    attempt's keys are reaped."""
    from tests.test_manifest_raster_replace import (
        _apply,
        _cleanup,
        _entry,
        _published,
        _request,
        _resurveyed,
        _run_worker,
    )
    from app.processing.raster.models import RasterAsset

    _, owner = await _submitter(client, test_db_session, admin_auth_header, "admin")
    published = await _published(test_db_session, raster_storage, owner)
    await test_db_session.execute(
        update(Record)
        .where(Record.id == published.record_id)
        .values(visibility="internal")
    )
    await test_db_session.commit()
    old_cog = published.live.cog_key
    prefix = f"rasters/{published.dataset_id}/"
    keys_before = sorted(await raster_storage.list(prefix))
    try:
        entry = _entry(published.key, published.uri, _resurveyed(published))
        result, defer = await _apply(test_db_session, _request(entry), owner)
        assert result.action == "update", result
        queued = await test_db_session.get(IngestJob, result.job_id)
        assert queued.user_metadata["visibility"] == "public"
        assert "admitted_public_visibility" not in queued.user_metadata
        # Only the public visibility is judged here, not the admin-only local
        # source the entry reads from.
        queued.user_metadata = {
            k: v for k, v in queued.user_metadata.items() if k != "admitted_raw_source"
        }
        await test_db_session.commit()
        if demoted:
            await _commit(_move_to_role(owner.id, "editor"))
        restriction.on = True

        await _run_worker(defer)

        test_db_session.expire_all()
        job = await _job(test_db_session, result.job_id)
        record = await test_db_session.get(Record, published.record_id)
        if not demoted:
            assert (job.status, job.error_message) == ("complete", None)
            assert record.visibility == "public"
            return
        assert (job.status, job.error_message, job.error_code) == _REFUSED
        assert await _run_outcome(test_db_session, job.id) == _RUN_REFUSED
        attempt_keys = job.user_metadata[UNPUBLISHED_STORAGE_KEYS_FIELD]
        assert any(key.endswith("/source.cog.tif") for key in attempt_keys)
        for key in attempt_keys:
            assert not await raster_storage.exists(key), key
        live_cog = await test_db_session.scalar(
            select(RasterAsset.asset_uri).where(
                RasterAsset.dataset_id == published.dataset_id
            )
        )
        assert live_cog == old_cog
        assert sorted(await raster_storage.list(prefix)) == keys_before
        assert record.visibility == "internal"
    finally:
        await _cleanup(test_db_session, published)


@pytest.mark.parametrize(
    ("role", "when"),
    [
        ("editor", "before-the-worker"),
        ("editor", "while-storing"),
        ("admin", "before-the-worker"),
    ],
)
async def test_a_vrt_created_public_is_judged_by_the_restriction_when_it_runs(
    client,
    test_db_session,
    admin_auth_header,
    vrt_db_state,  # noqa: F811
    local_storage,  # noqa: F811
    quicklook_stub,  # noqa: F811
    clean_tables,
    restriction,
    monkeypatch,
    role,
    when,
):
    """A mosaic of public members, queued public while anyone could make one;
    the restriction is turned on before the worker, or while the VRT is
    stored."""
    import json

    from app.processing.ingest.tasks_vrt import ingest_vrt
    from tests.test_vrt_probe_failures import _vrt_count

    _, user = await _submitter(client, test_db_session, admin_auth_header, role)
    user_id = user.id
    member_records = select(Dataset.record_id).where(
        Dataset.id.in_(vrt_db_state["source_dataset_ids"])
    )
    await test_db_session.execute(
        update(Record)
        .where(Record.id.in_(member_records.scalar_subquery()))
        .values(visibility="public")
    )
    await test_db_session.execute(
        update(IngestJob)
        .where(IngestJob.id == uuid.UUID(vrt_db_state["job_id"]))
        .values(created_by=user_id, user_metadata={"visibility": "public"})
    )
    await test_db_session.commit()
    before = await _vrt_count(test_db_session)
    if when == "before-the-worker":
        restriction.on = True
    else:
        put = local_storage.put

        async def put_then_restrict(*args, **kwargs):
            await put(*args, **kwargs)
            restriction.on = True

        monkeypatch.setattr(local_storage, "put", put_then_restrict)
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: local_storage)

    async def run() -> None:
        await ingest_vrt.func(
            job_id=vrt_db_state["job_id"],
            user_id=str(user_id),
            source_dataset_ids=json.dumps(
                [str(i) for i in vrt_db_state["source_dataset_ids"]]
            ),
            vrt_type="mosaic",
            resolution_strategy="finest",
            attempt_id=vrt_db_state["attempt_id"],
        )

    if role == "admin":
        await run()
        job = await _job(test_db_session, uuid.UUID(vrt_db_state["job_id"]))
        assert (job.status, job.error_message) == ("complete", None)
        assert await _vrt_count(test_db_session) == before + 1
        return
    with pytest.raises(WriteAccessRevoked):
        await run()
    job = await _job(test_db_session, uuid.UUID(vrt_db_state["job_id"]))
    assert (job.status, job.error_message, job.error_code) == _REFUSED
    assert job.dataset_id is None
    assert await _vrt_count(test_db_session) == before
    assert not list(local_storage.base_dir.rglob("*.vrt"))
