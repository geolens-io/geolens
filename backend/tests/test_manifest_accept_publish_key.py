"""Accepting a held manifest replacement with a publish key."""

from __future__ import annotations

import shutil
from dataclasses import replace
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.modules.auth.models import User
from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.modules.catalog.datasets.api.refresh_acceptance import (
    dispatch_upload_acceptance,
)
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.request_credential import (
    _SESSION_KEY,
    ApiKeyCredential,
    record_api_key,
)
from app.processing.ingest.manifest_schemas import ManifestApplyRequest
from app.processing.ingest.manifest_service import apply_manifest
from app.processing.ingest.manifest_sources import manifest_dataset_fingerprint
from tests.factories import create_user
from tests.test_manifest_blocked_reapply import _KEY, _held_apply
from tests.test_manifest_reapply_publication import (
    _entry,
    _http_request,
    _reupload_task,
    _run_worker,
)

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="needs ogr2ogr"),
    pytest.mark.requires_ogr2ogr,
]


async def _hold(session, *, record: tuple[str, str], **held_metadata):
    """A held replacement whose entry asks for ``held_metadata``, over a
    dataset whose record is ``record``."""
    held = await _held_apply(session)
    job = await session.get(IngestJob, held.job_id)
    job.user_metadata = {**job.user_metadata, **held_metadata}
    record_id = select(Dataset.record_id).where(Dataset.id == held.dataset_id)
    await session.execute(
        update(Record)
        .where(Record.id == record_id.scalar_subquery())
        .values(visibility=record[0], record_status=record[1])
    )
    await session.commit()
    return held


async def _accept(session, held, *, publish_key: bool) -> IngestJob:
    """Accept the held run, as a publish key or not, and run its worker.
    Raises what the accept refuses with."""
    dataset = (
        await session.execute(
            select(Dataset)
            .options(selectinload(Dataset.record))
            .where(Dataset.id == held.dataset_id)
        )
    ).scalar_one()
    if publish_key:
        record_api_key(
            session,
            ApiKeyCredential(id=uuid.uuid4(), scope="publish", dataset_id=None),
        )
    defer = AsyncMock()
    try:
        with patch(
            "app.modules.catalog.datasets.api.refresh_acceptance.defer_async_with_tenant",
            new=defer,
        ):
            accepted = await dispatch_upload_acceptance(
                session,
                dataset=dataset,
                dataset_id=held.dataset_id,
                user=held.user,
                run_id=held.run_id,
                token=None,
            )
    finally:
        session.info.pop(_SESSION_KEY, None)
    task = SimpleNamespace(defer_async=SimpleNamespace(await_args=defer.await_args))
    await _run_worker(task)
    return (
        await session.execute(
            select(IngestJob)
            .where(IngestJob.id == accepted.job_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _record(session, dataset_id) -> tuple[str, str]:
    return tuple(
        (
            await session.execute(
                select(Record.visibility, Record.record_status)
                .join(Dataset, Dataset.record_id == Record.id)
                .where(Dataset.id == dataset_id)
                .execution_options(populate_existing=True)
            )
        ).one()
    )


def _v2(**metadata) -> dict:
    """What a version 2 apply stores besides what the held fixture has."""
    return {"manifest_version": "2", **metadata}


async def test_a_publish_key_accepting_a_held_v2_narrowing_applies_it(
    test_db_session, clean_tables
):
    held = await _hold(
        test_db_session,
        record=("public", "published"),
        **_v2(visibility="private", manifest_requested_visibility="private"),
    )

    job = await _accept(test_db_session, held, publish_key=True)

    assert (job.status, job.error_message) == ("complete", None)
    assert uuid.UUID(job.user_metadata["admitted_publish_key"])
    assert await _record(test_db_session, held.dataset_id) == ("private", "published")


async def test_a_publish_key_cannot_accept_a_held_v2_widening(
    test_db_session, clean_tables
):
    """Refused as the key's own apply of it would be; nothing is queued."""
    held = await _hold(
        test_db_session,
        record=("private", "published"),
        **_v2(visibility="internal", manifest_requested_visibility="internal"),
    )

    with pytest.raises(HTTPException) as refused:
        await _accept(test_db_session, held, publish_key=True)

    assert refused.value.status_code == 403
    assert refused.value.detail["message"] == (
        "A publish key can't widen a dataset's visibility"
    )
    assert await _record(test_db_session, held.dataset_id) == ("private", "published")


async def test_a_publish_key_accepting_a_held_v1_run_keeps_the_publication(
    test_db_session, clean_tables
):
    """Version 1: the held entry may be another credential's, so the dataset
    keeps its visibility and status, and no key limits are recorded."""
    held = await _hold(test_db_session, record=("private", "draft"))

    job = await _accept(test_db_session, held, publish_key=True)

    assert (job.status, job.error_message) == ("complete", None)
    assert "admitted_publish_key" not in job.user_metadata
    assert await _record(test_db_session, held.dataset_id) == ("private", "draft")


async def test_a_publish_key_accepting_a_now_public_draft_falls_back(
    test_db_session, clean_tables
):
    """The entry kept the visibility and asked to publish; the dataset became
    a public draft meanwhile, which a key may not publish."""
    held = await _hold(
        test_db_session,
        record=("public", "draft"),
        **_v2(manifest_public_fallback="internal"),
    )
    job_row = await test_db_session.get(IngestJob, held.job_id)
    job_row.user_metadata = {
        k: v for k, v in job_row.user_metadata.items() if k != "visibility"
    }
    await test_db_session.commit()

    job = await _accept(test_db_session, held, publish_key=True)

    assert (job.status, job.error_message) == ("complete", None)
    assert [w["kind"] for w in job.user_metadata["warnings"]] == [
        "manifest_public_fallback"
    ]
    assert await _record(test_db_session, held.dataset_id) == ("internal", "published")


async def _someone_elses_collection(client, session, admin_auth_header) -> Collection:
    _, other_id = await create_user(client, admin_auth_header, "editor")
    other = await session.get(User, uuid.UUID(other_id))
    collection = Collection(name=f"theirs-{uuid.uuid4().hex[:8]}", created_by=other.id)
    session.add(collection)
    await session.commit()
    return collection


@pytest.mark.parametrize(
    "publish_key,joins", [(True, False), (False, True)], ids=["key", "full"]
)
async def test_an_accepted_run_joins_another_users_collection_only_without_a_key(
    client, test_db_session, admin_auth_header, clean_tables, publish_key, joins
):
    """An admin reaches other people's collections; their publish key doesn't."""
    collection = await _someone_elses_collection(
        client, test_db_session, admin_auth_header
    )
    held = await _hold(
        test_db_session,
        record=("private", "draft"),
        **_v2(manifest_collection_id=str(collection.id)),
    )

    job = await _accept(test_db_session, held, publish_key=publish_key)

    assert (job.status, job.error_message) == ("complete", None)
    member = await test_db_session.scalar(
        select(CollectionDataset.dataset_id).where(
            CollectionDataset.collection_id == collection.id
        )
    )
    assert (member == held.dataset_id) is joins
    warnings = [w["kind"] for w in (job.user_metadata or {}).get("warnings", [])]
    assert ("manifest_collection_refused" in warnings) is not joins


# ---------------------------------------------------------------------------
# Re-applying an unchanged entry whose replacement is held
# ---------------------------------------------------------------------------


def _v2_resurveyed(**extra) -> ManifestApplyRequest:
    """The held fixture's entry, in version 2, naming public."""
    entry = _entry(_KEY, title="Resurveyed roads", intent="published")
    return ManifestApplyRequest.model_validate(
        {
            "manifest_version": "2",
            "client": {"id": "geolens-qgis", "version": "0.2.0"},
            "catalog": {"title": "Manifest catalog"},
            "datasets": [{**entry, "visibility": "public"}],
            **extra,
        }
    )


async def _held_v2(session, **stored):
    """A held replacement of the version 2 entry, storing ``stored``."""
    held = await _hold(
        session,
        record=("private", "draft"),
        **_v2(manifest_requested_visibility="public", **stored),
    )
    job = await session.get(IngestJob, held.job_id)
    job.user_metadata = {
        **job.user_metadata,
        "manifest_fingerprint": manifest_dataset_fingerprint(
            _v2_resurveyed().datasets[0]
        ),
    }
    await session.commit()
    return held


async def _reapply(session, held, request):
    with _reupload_task() as task:
        response = await apply_manifest(session, request, held.user, _http_request())
    return response.results[0], task


def _restricted():
    async def gate(db, user, visibility, **kwargs):
        if visibility == "public":
            raise HTTPException(status_code=403, detail="restricted")

    return patch(
        "app.modules.catalog.authorization.check_public_visibility_allowed",
        new=AsyncMock(side_effect=gate),
    )


async def _stored(session, job_id) -> dict:
    return (
        await session.execute(
            select(IngestJob.user_metadata)
            .where(IngestJob.id == job_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def test_an_unchanged_held_v2_entry_deciding_the_same_reports_it_blocked(
    test_db_session, clean_tables
):
    held = await _held_v2(test_db_session, visibility="public")

    result, task = await _reapply(test_db_session, held, _v2_resurveyed())

    assert (result.action, result.run_id) == ("blocked", held.run_id), result
    task.defer_async.assert_not_awaited()


async def test_a_held_public_entry_reapplied_under_the_restriction_queues_internal(
    test_db_session, clean_tables
):
    """The re-apply decides otherwise, so it is queued past the hold and the
    response matches its job. The superseded run, accepted later, is judged
    for the accepter: still refused public, and it stored no fallback, so the
    accept is refused and the dataset is left as it was."""
    held = await _held_v2(test_db_session, visibility="public")

    with _restricted():
        result, task = await _reapply(
            test_db_session, held, _v2_resurveyed(public_fallback="internal")
        )
        assert result.action == "update", result
        assert [(m.code, m.severity) for m in result.messages] == [("A020", "warning")]
        queued = await _stored(test_db_session, result.job_id)
        assert (queued["visibility"], queued["manifest_public_fallback"]) == (
            "internal",
            "internal",
        )

        with pytest.raises(HTTPException) as refused:
            await _accept(test_db_session, held, publish_key=False)
        assert refused.value.status_code == 403
        assert "public" in str(refused.value.detail).lower()
        assert await _record(test_db_session, held.dataset_id) == ("private", "draft")

        # The run the re-apply queued is held for the same dropped column;
        # accepting it publishes what the response said.
        await _run_worker(task)
        run_id = await test_db_session.scalar(
            select(DatasetRefreshRun.id)
            .where(DatasetRefreshRun.ingest_job_id == result.job_id)
            .execution_options(populate_existing=True)
        )
        accepted = await _accept(
            test_db_session, replace(held, run_id=run_id), publish_key=False
        )

    assert (accepted.status, accepted.error_message) == ("complete", None)
    assert await _record(test_db_session, held.dataset_id) == (
        "internal",
        "published",
    )


@pytest.mark.parametrize(
    "stored",
    [
        {"visibility": "internal"},
        {"visibility": "public", "admitted_publish_key": "k"},
    ],
    ids=["fallback-then-public", "key-then-signed-in"],
)
async def test_a_held_entry_decided_otherwise_now_is_queued_past_the_hold(
    test_db_session, clean_tables, stored
):
    """Held internal by a fallback, then named public with nothing refusing
    it; or held by a publish key, then applied by its owner signed in."""
    held = await _held_v2(test_db_session, **stored)

    result, task = await _reapply(test_db_session, held, _v2_resurveyed())

    assert result.action == "update", result
    task.defer_async.assert_awaited_once()
    queued = await _stored(test_db_session, result.job_id)
    assert queued["visibility"] == "public"
    assert "admitted_publish_key" not in queued


async def test_a_held_v1_run_is_not_reused_by_a_v2_apply(test_db_session, clean_tables):
    """The versions decide visibility differently, so the entry is queued past
    the hold rather than reporting the v1 run as its own."""
    held = await _hold(test_db_session, record=("private", "draft"))
    job = await test_db_session.get(IngestJob, held.job_id)
    job.user_metadata = {
        **job.user_metadata,
        "manifest_fingerprint": manifest_dataset_fingerprint(
            _v2_resurveyed().datasets[0]
        ),
    }
    await test_db_session.commit()

    result, task = await _reapply(test_db_session, held, _v2_resurveyed())

    assert result.action == "update", result
    task.defer_async.assert_awaited_once()


async def test_a_held_entry_reapplied_keeps_its_a020_warning(
    test_db_session, clean_tables
):
    """Held internal by the fallback, then applied again the same way."""
    held = await _held_v2(
        test_db_session, visibility="internal", manifest_public_fallback="internal"
    )

    with _restricted():
        result, task = await _reapply(
            test_db_session, held, _v2_resurveyed(public_fallback="internal")
        )

    assert (result.action, result.run_id) == ("blocked", held.run_id), result
    assert [(m.code, m.severity) for m in result.messages] == [("A020", "warning")]
    task.defer_async.assert_not_awaited()


async def test_an_accepted_run_with_attributes_needs_edit_metadata_when_it_publishes(
    test_db_session, clean_tables, monkeypatch
):
    from app.modules.auth import permissions

    held = await _hold(
        test_db_session,
        record=("private", "draft"),
        **_v2(manifest_attributes=[{"source_name": "name", "title": "Place"}]),
    )
    effective = permissions.get_effective_permissions

    async def narrowed(db):
        matrix = await effective(db)
        matrix["admin"]["edit_metadata"] = False
        return matrix

    # Accepted while held, revoked before the publish.
    real_run_worker = _run_worker

    async def revoke_then_run(task):
        monkeypatch.setattr(permissions, "get_effective_permissions", narrowed)
        await real_run_worker(task)

    monkeypatch.setattr(
        "tests.test_manifest_accept_publish_key._run_worker", revoke_then_run
    )
    job = await _accept(test_db_session, held, publish_key=False)

    assert job.status == "failed"
    assert "can no longer modify this dataset" in job.error_message
    assert await _record(test_db_session, held.dataset_id) == ("private", "draft")


@pytest.mark.parametrize(
    "version,name",
    [
        ("2", "app.ingest.tasks.reupload_manifest_v2_file"),
        ("1", "app.ingest.tasks.reupload_verified_file"),
    ],
    ids=["v2", "v1"],
)
async def test_an_accepted_run_is_queued_under_its_versions_task_name(
    test_db_session, clean_tables, version, name
):
    held = await _hold(
        test_db_session,
        record=("private", "draft"),
        **(_v2() if version == "2" else {}),
    )
    dataset = (
        await test_db_session.execute(
            select(Dataset)
            .options(selectinload(Dataset.record))
            .where(Dataset.id == held.dataset_id)
        )
    ).scalar_one()
    defer = AsyncMock()
    with patch(
        "app.modules.catalog.datasets.api.refresh_acceptance.defer_async_with_tenant",
        new=defer,
    ):
        await dispatch_upload_acceptance(
            test_db_session,
            dataset=dataset,
            dataset_id=held.dataset_id,
            user=held.user,
            run_id=held.run_id,
            token=None,
        )

    assert defer.await_args.args[0].name == name
