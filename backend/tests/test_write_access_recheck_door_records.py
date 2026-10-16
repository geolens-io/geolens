"""A replacement door records the capability it admitted its job under, and
that record is what the job's publish re-checks.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

import app.modules.auth.permissions as permissions
from app.modules.catalog.datasets.api.refresh_acceptance import (
    _accepted_upload_metadata,
)
from app.modules.catalog.datasets.api.router_reupload import _new_reupload_metadata
from app.platform.jobs.models import ADMITTED_CAPABILITY_METADATA_KEY
from app.processing.ingest.manifest_service import apply_manifest
from app.processing.ingest.publication import WriteAccessRevoked
from tests.test_manifest_run_admission import (
    _admin,
    _applied_dataset,
    _http_request,
    _newest_job,
    _reupload_task,
    _stage_fixture,
    _update,
)
from tests.test_previous_version_2590 import (
    _cleanup,
    _job_status,
    _names,
    _replace,
    _seed,
)

pytestmark = pytest.mark.anyio


def test_the_reupload_doors_record_edit_metadata() -> None:
    dataset = SimpleNamespace(data_revision=1)
    metadata = _new_reupload_metadata(uuid.uuid4(), dataset)
    assert metadata[ADMITTED_CAPABILITY_METADATA_KEY] == "edit_metadata"


def test_an_accepted_upload_records_edit_metadata() -> None:
    metadata = _accepted_upload_metadata(
        SimpleNamespace(id=uuid.uuid4(), user_metadata={"manifest_key": "k"}),
        dataset_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        fingerprint="fp",
        held_version=None,
    )
    assert metadata[ADMITTED_CAPABILITY_METADATA_KEY] == "edit_metadata"


async def test_a_manifest_update_records_upload(test_db_session, clean_tables) -> None:
    _stage_fixture()
    user = await _admin(test_db_session)
    await _applied_dataset(test_db_session, user, "records-upload")

    with _reupload_task():
        response = await apply_manifest(
            test_db_session, _update("records-upload"), user, _http_request()
        )

    assert response.results[0].action == "update"
    job = await _newest_job(test_db_session, "records-upload")
    assert job.user_metadata[ADMITTED_CAPABILITY_METADATA_KEY] == "upload"


async def test_a_restore_rechecks_the_capability_its_door_recorded(
    client: AsyncClient,
    test_db_session,
    admin_auth_header,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The record survives from the door to the publish the worker runs."""
    from app.processing.ingest.tasks import restore_previous_version

    session = test_db_session
    admin_id, dataset = await _seed(session)
    try:
        await _replace(session, dataset, admin_id, ["paris", "london"])
        deferred = AsyncMock()
        with patch(
            "app.modules.catalog.datasets.api.router_previous_version."
            "defer_async_with_tenant",
            deferred,
        ):
            response = await client.post(
                f"/api/datasets/{dataset.id}/previous-version/restore",
                json={"expected_version_number": 1},
                headers=admin_auth_header,
            )
        assert response.status_code == 202, response.text
        committed = await session.scalar(
            text("SELECT user_metadata FROM catalog.ingest_jobs WHERE id = :id"),
            {"id": response.json()["job_id"]},
        )
        assert committed[ADMITTED_CAPABILITY_METADATA_KEY] == "edit_metadata"

        # The admin's role loses edit_metadata while the restore is queued.
        effective = permissions.get_effective_permissions

        async def admins_without_edit_metadata(db):
            matrix = await effective(db)
            matrix["admin"]["edit_metadata"] = False
            return matrix

        monkeypatch.setattr(
            permissions, "get_effective_permissions", admins_without_edit_metadata
        )
        await restore_previous_version(**deferred.await_args.kwargs)

        job_id = response.json()["job_id"]
        assert await _job_status(session, job_id) == "failed"
        error = await session.scalar(
            text("SELECT error_message FROM catalog.ingest_jobs WHERE id = :id"),
            {"id": job_id},
        )
        assert error == str(WriteAccessRevoked())
        assert await _names(session, dataset.table_name) == ["London", "Paris"]
    finally:
        await _cleanup(session, dataset)


async def test_the_vrt_add_source_door_commits_upload_on_its_job(
    client: AsyncClient, test_db_session, admin_auth_header
) -> None:
    import app.core.db as db_module
    from app.platform.jobs.models import IngestJob
    from tests.test_vrt_source_authz_1172 import (
        _create_raster_dataset,
        _create_vrt_dataset,
        _link_source,
        _make_editor,
        _patch_defer,
    )

    editor_headers, editor_id = await _make_editor(client, admin_auth_header)
    vrt_id = await _create_vrt_dataset(test_db_session, created_by=editor_id)
    for position in range(2):
        source_id = await _create_raster_dataset(test_db_session, created_by=editor_id)
        await _link_source(test_db_session, vrt_id, source_id, position)
    added = await _create_raster_dataset(test_db_session, created_by=editor_id)

    p_create, p_regen = _patch_defer()
    with p_create, p_regen:
        resp = await client.post(
            f"/ingest/vrt/{vrt_id}/sources/",
            json={"source_dataset_id": str(added)},
            headers=editor_headers,
        )
    assert resp.status_code == 202, resp.text

    async with db_module.async_session() as session:
        metadata = await session.scalar(
            select(IngestJob.user_metadata).where(
                IngestJob.id == uuid.UUID(resp.json()["job_id"])
            )
        )
    assert metadata[ADMITTED_CAPABILITY_METADATA_KEY] == "upload"


async def test_a_public_manifest_update_records_its_admin_admission(
    test_db_session, clean_tables, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.core.persistent_config as persistent_config
    from app.platform.jobs.models import ADMITTED_PUBLIC_VISIBILITY_METADATA_KEY
    from tests.test_manifest_run_admission import _entry, _request

    class _Restricted:
        async def get(self, _db):
            return True

    monkeypatch.setattr(persistent_config, "RESTRICT_PUBLIC_VISIBILITY", _Restricted())
    _stage_fixture()
    user = await _admin(test_db_session)
    await _applied_dataset(test_db_session, user, "records-public")
    entry = _entry("records-public", title="Published roads")
    entry["publication"] = {"intent": "published"}

    with _reupload_task():
        response = await apply_manifest(
            test_db_session, _request(entry), user, _http_request()
        )

    assert response.results[0].action == "update", response.results[0]
    job = await _newest_job(test_db_session, "records-public")
    assert job.user_metadata[ADMITTED_PUBLIC_VISIBILITY_METADATA_KEY] is True


def test_an_accepted_upload_carries_the_admin_admission() -> None:
    from app.platform.jobs.models import ADMITTED_PUBLIC_VISIBILITY_METADATA_KEY

    blocked = {"manifest_key": "k", ADMITTED_PUBLIC_VISIBILITY_METADATA_KEY: True}
    metadata = _accepted_upload_metadata(
        SimpleNamespace(id=uuid.uuid4(), user_metadata=blocked),
        dataset_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        fingerprint="fp",
        held_version=None,
    )
    assert metadata[ADMITTED_PUBLIC_VISIBILITY_METADATA_KEY] is True


async def test_a_manifest_update_over_http_hands_an_overlay_a_full_identity(
    client: AsyncClient,
    test_db_session,
    admin_auth_header,
    clean_tables,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The authorized caller, unchanged, through the real endpoint, with an
    extension that reads the identity contract."""
    from app.platform import extensions
    from tests.test_manifest_run_admission import _ContractReadingExtension

    _stage_fixture()
    user = await _admin(test_db_session)
    await _applied_dataset(test_db_session, user, "http-identity")
    monkeypatch.setitem(
        extensions._extensions, "permission", _ContractReadingExtension()
    )

    with _reupload_task() as task:
        resp = await client.post(
            "/ingest/manifest/apply",
            json=_update("http-identity").model_dump(mode="json"),
            headers=admin_auth_header,
        )

    assert resp.status_code == 200, resp.text
    [result] = resp.json()["results"]
    assert result["action"] == "update", result
    task.defer_async.assert_awaited_once()
