"""A service replacement does not publish over feature edits made while it ran."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import create_pending_run
from app.processing.ingest.tasks_reupload import reupload_service
from tests.factories import get_user_id
from tests.test_refresh_gate_1269 import _dispatch_harness, _runs_ordered
from tests.test_service_reupload_3d import (
    _BASE,
    _FLAT_WELLS,
    _dataset,
    _fake_fetch,
    _ingest,
    _source,
)

pytestmark = pytest.mark.anyio


def _fetch_then_edit(client: AsyncClient, headers, dataset_id: uuid.UUID):
    """The fake fetch, followed by one feature inserted through the API."""
    fetch = _fake_fetch(_FLAT_WELLS)

    async def _fetch(*args, **kwargs):
        await fetch(*args, **kwargs)
        response = await client.post(
            f"/datasets/{dataset_id}/features/",
            headers=headers,
            json={
                "geometry": {"type": "Point", "coordinates": [-73.5, 40.5]},
                "properties": {"name": "edited"},
            },
        )
        assert response.status_code == 201, response.text

    return _fetch


async def _edited_rows(session, dataset_id: uuid.UUID) -> int:
    table = (await _dataset(session, dataset_id)).table_name
    count = await session.scalar(
        text(f"SELECT count(*) FROM data.\"{table}\" WHERE name = 'edited'")
    )
    await session.commit()
    return count


async def _refresh(client, headers, monkeypatch, dataset_id, *, edit, body=None):
    async with _dispatch_harness() as task:
        response = await client.post(
            f"/datasets/{dataset_id}/refresh", json=body or {}, headers=headers
        )
    assert response.status_code == 202, response.text
    fetch = _fetch_then_edit(client, headers, dataset_id) if edit else None
    with _source(monkeypatch, _FLAT_WELLS):
        if fetch is None:
            await reupload_service.func(**task.defer_async.call_args.kwargs)
        else:
            with patch("app.processing.ingest.ogr.run_ogr2ogr_service", new=fetch):
                await reupload_service.func(**task.defer_async.call_args.kwargs)
    return response.json()


async def test_a_refresh_during_a_feature_edit_is_held_and_its_acceptance_publishes(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    dataset_id = await _ingest(test_db_session, monkeypatch, _FLAT_WELLS)

    await _refresh(client, admin_auth_header, monkeypatch, dataset_id, edit=True)

    [held] = await _runs_ordered(test_db_session, dataset_id)
    held_id = held.id
    assert held.status == "blocked", held.verification
    assert held.verification["review_reasons"] == ["live_data_changed"]
    assert await _edited_rows(test_db_session, dataset_id) == 1

    accepted = await _refresh(
        client,
        admin_auth_header,
        monkeypatch,
        dataset_id,
        edit=False,
        body={"accept_blocked_run_id": str(held_id)},
    )

    run = await test_db_session.scalar(
        select(DatasetRefreshRun)
        .where(DatasetRefreshRun.id == uuid.UUID(accepted["run_id"]))
        .execution_options(populate_existing=True)
    )
    assert run.status == "succeeded", run.verification
    assert run.verification["accepted_blocked_run_id"] == str(held_id)
    assert await _edited_rows(test_db_session, dataset_id) == 0


async def test_a_refresh_with_no_feature_edit_publishes(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    dataset_id = await _ingest(test_db_session, monkeypatch, _FLAT_WELLS)

    await _refresh(client, admin_auth_header, monkeypatch, dataset_id, edit=False)

    [run] = await _runs_ordered(test_db_session, dataset_id)
    assert run.status == "succeeded", run.verification
    assert run.verification["review_reasons"] == []


async def test_a_service_reupload_during_a_feature_edit_fails_and_keeps_it(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    """A re-upload with no review step refuses to publish over the edit."""
    dataset_id = await _ingest(test_db_session, monkeypatch, _FLAT_WELLS)
    admin_id = await get_user_id(test_db_session, "admin")
    job = IngestJob(
        dataset_id=dataset_id,
        source_filename="Wells",
        source_url=_BASE,
        source_layer="0",
        created_by=admin_id,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset_id),
            "service_type": "ArcGIS FeatureServer",
            "layer_id": "0",
            "source_type": "service_url",
        },
    )
    test_db_session.add(job)
    await test_db_session.flush()
    job_id, attempt_id = job.id, job.attempt_id
    await create_pending_run(
        test_db_session,
        dataset_id=dataset_id,
        origin_kind="service",
        trigger="manual",
        triggered_by=admin_id,
        ingest_job_id=job_id,
        feature_count_before=len(_FLAT_WELLS),
    )
    await test_db_session.commit()
    version_before = (await _dataset(test_db_session, dataset_id)).current_version

    with (
        _source(monkeypatch, _FLAT_WELLS),
        patch(
            "app.processing.ingest.ogr.run_ogr2ogr_service",
            new=_fetch_then_edit(client, admin_auth_header, dataset_id),
        ),
    ):
        with pytest.raises(Exception, match="edited"):
            await reupload_service.func(
                job_id=str(job_id),
                attempt_id=str(attempt_id),
                dataset_id=str(dataset_id),
                source_url=_BASE,
                source_layer="0",
                user_id=str(admin_id),
            )

    job = await test_db_session.get(IngestJob, job_id, populate_existing=True)
    assert job.status == "failed"
    [run] = await _runs_ordered(test_db_session, dataset_id)
    assert (run.status, run.error_code) == ("failed", "live_data_changed")
    assert (await _dataset(test_db_session, dataset_id)).current_version == (
        version_before
    )
    assert await _edited_rows(test_db_session, dataset_id) == 1
