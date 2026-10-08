"""Service re-uploads with review reasons publish only once a person has reviewed them."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.processing.ingest.tasks_reupload import reupload_service
from tests.test_refresh_gate_1269 import _dispatch_harness, _runs_ordered
from tests.test_service_reupload_3d import (
    _FLAT_WELLS,
    _commit,
    _dataset,
    _ingest,
    _live_columns,
    _preview,
    _source,
)

pytestmark = pytest.mark.anyio

_BASE_COLUMNS = ("name", "legacy")
_DROPPED = ("name",)


async def _service_dataset(session, monkeypatch) -> uuid.UUID:
    return await _ingest(session, monkeypatch, _FLAT_WELLS, _BASE_COLUMNS)


async def _reupload(
    client, headers, session, monkeypatch, dataset_id, columns, *, reviewed: bool
) -> tuple[dict, DatasetRefreshRun]:
    """Preview ``columns``, commit with the preview's fingerprint when ``reviewed``, run."""
    preview = await _preview(client, headers, dataset_id, _FLAT_WELLS, columns)
    body = {"review_fingerprint": preview["review_fingerprint"]} if reviewed else {}
    await _commit(
        client,
        headers,
        monkeypatch,
        dataset_id,
        preview["job_id"],
        _FLAT_WELLS,
        columns,
        **body,
    )
    run = (
        await session.execute(
            select(DatasetRefreshRun)
            .where(DatasetRefreshRun.ingest_job_id == uuid.UUID(preview["job_id"]))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return preview, run


async def _held(client, headers, session, monkeypatch) -> tuple[uuid.UUID, uuid.UUID]:
    """A service dataset and the held re-upload that drops one of its columns."""
    dataset_id = await _service_dataset(session, monkeypatch)
    _preview_body, run = await _reupload(
        client, headers, session, monkeypatch, dataset_id, _DROPPED, reviewed=False
    )
    assert run.status == "blocked", run.verification
    return dataset_id, run.id


async def test_a_service_reupload_that_drops_a_column_is_held_without_review(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    """The run blocks, the job waits for review and the live data stays."""
    dataset_id = await _service_dataset(test_db_session, monkeypatch)
    version_before = (await _dataset(test_db_session, dataset_id)).current_version

    preview, run = await _reupload(
        client,
        admin_auth_header,
        test_db_session,
        monkeypatch,
        dataset_id,
        _DROPPED,
        reviewed=False,
    )

    assert preview["review_reasons"] == ["destructive_schema_change"]
    assert run.status == "blocked", run.verification
    assert run.verification["review_reasons"] == ["destructive_schema_change"]
    assert run.verification["review_fingerprint"] == preview["review_fingerprint"]
    job = await test_db_session.get(
        IngestJob, uuid.UUID(preview["job_id"]), populate_existing=True
    )
    assert (job.status, job.error_code) == ("failed", "review_required")
    dataset = await _dataset(test_db_session, dataset_id)
    assert dataset.current_version == version_before
    assert "legacy" in await _live_columns(test_db_session, dataset.table_name)


async def test_a_service_reupload_with_the_previews_fingerprint_publishes(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    dataset_id = await _service_dataset(test_db_session, monkeypatch)

    _preview_body, run = await _reupload(
        client,
        admin_auth_header,
        test_db_session,
        monkeypatch,
        dataset_id,
        _DROPPED,
        reviewed=True,
    )

    assert run.status == "succeeded", run.verification
    assert run.verification["review_acknowledged_by"] == "preview"
    dataset = await _dataset(test_db_session, dataset_id)
    assert "legacy" not in await _live_columns(test_db_session, dataset.table_name)


async def test_a_service_reupload_with_an_unchanged_schema_publishes_without_review(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    dataset_id = await _service_dataset(test_db_session, monkeypatch)

    preview, run = await _reupload(
        client,
        admin_auth_header,
        test_db_session,
        monkeypatch,
        dataset_id,
        _BASE_COLUMNS,
        reviewed=False,
    )

    assert (preview["review_reasons"], preview["review_fingerprint"]) == ([], None)
    assert run.status == "succeeded", run.verification
    assert run.verification["review_reasons"] == []


async def _accept(client, headers, monkeypatch, dataset_id, run_id, columns):
    async with _dispatch_harness() as task:
        response = await client.post(
            f"/datasets/{dataset_id}/refresh",
            headers=headers,
            json={"accept_blocked_run_id": str(run_id)},
        )
    if response.status_code == 202:
        with _source(monkeypatch, _FLAT_WELLS, columns):
            await reupload_service.func(**task.defer_async.call_args.kwargs)
    return response


async def test_accepting_a_held_service_reupload_publishes_it_once(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    dataset_id, held_id = await _held(
        client, admin_auth_header, test_db_session, monkeypatch
    )

    response = await _accept(
        client, admin_auth_header, monkeypatch, dataset_id, held_id, _DROPPED
    )

    assert response.status_code == 202, response.text
    accepted = await test_db_session.get(
        DatasetRefreshRun,
        uuid.UUID(response.json()["run_id"]),
        populate_existing=True,
    )
    assert accepted.status == "succeeded", accepted.verification
    assert accepted.verification["accepted_blocked_run_id"] == str(held_id)
    dataset = await _dataset(test_db_session, dataset_id)
    assert "legacy" not in await _live_columns(test_db_session, dataset.table_name)

    again = await _accept(
        client, admin_auth_header, monkeypatch, dataset_id, held_id, _DROPPED
    )
    assert again.status_code == 422, again.text


async def test_accepting_a_held_service_reupload_after_the_source_moved_is_refused(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    """The acceptance would fetch a source the reviewed changes do not describe."""
    dataset_id, held_id = await _held(
        client, admin_auth_header, test_db_session, monkeypatch
    )
    dataset = await _dataset(test_db_session, dataset_id)
    await test_db_session.execute(
        update(Dataset)
        .where(Dataset.id == dataset_id)
        .values(origin_ref={**dataset.origin_ref, "layer_id": "1"})
    )
    await test_db_session.commit()
    runs_before = len(await _runs_ordered(test_db_session, dataset_id))

    response = await _accept(
        client, admin_auth_header, monkeypatch, dataset_id, held_id, _DROPPED
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "origin_changed"
    test_db_session.expire_all()
    assert len(await _runs_ordered(test_db_session, dataset_id)) == runs_before
    held = await test_db_session.get(DatasetRefreshRun, held_id)
    assert "acceptance_consumed_by_run_id" not in held.verification
