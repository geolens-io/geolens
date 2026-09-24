"""A service refresh scans the staged table's quality only when it publishes."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.jobs.heartbeat import attempt_scoped_staging_table
from app.processing.ingest import metadata, tasks_vector
from app.processing.ingest.tasks_reupload import reupload_service
from tests.test_refresh_gate_1269 import _dispatch_harness, _runs_ordered
from tests.test_service_reupload_3d import _WELLS, _ingest, _source

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_reader_grant(monkeypatch) -> None:
    # A real grant would put this module in the tenancy test group.
    monkeypatch.setattr(
        "app.processing.ingest.metadata.grant_reader_access", AsyncMock()
    )


def _record_scores(monkeypatch) -> list[tuple[str, dict]]:
    """Wrap score_quality so each call's table and result land in the list."""
    calls: list[tuple[str, dict]] = []
    real = metadata.score_quality

    async def _recording(session, table_name, column_info, **kwargs):
        result = await real(session, table_name, column_info, **kwargs)
        calls.append((table_name, result))
        return result

    monkeypatch.setattr("app.processing.ingest.metadata.score_quality", _recording)
    return calls


async def _refresh(client, headers, monkeypatch, dataset_id, *, source_count):
    """Refresh against the wells while the layer reports ``source_count`` features."""
    async with _dispatch_harness() as task:
        response = await client.post(
            f"/datasets/{dataset_id}/refresh", json={}, headers=headers
        )
    assert response.status_code == 202, response.text

    async def _page_info(source_url, layer_id, token):
        return source_count, 1000, False, None

    kwargs = task.defer_async.call_args.kwargs
    with _source(monkeypatch, _WELLS):
        monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _page_info)
        await reupload_service.func(**kwargs)
    return kwargs


@pytest.mark.parametrize(
    ("source_count", "status"),
    [(None, "blocked"), (len(_WELLS) + 1, "failed")],
    ids=["blocked", "rejected"],
)
async def test_a_refresh_that_does_not_publish_runs_no_quality_scan(
    client: AsyncClient,
    admin_auth_header,
    test_db_session,
    monkeypatch,
    source_count: int | None,
    status: str,
):
    """A blocked or rejected service refresh never scores quality."""
    dataset_id = await _ingest(test_db_session, monkeypatch, _WELLS)
    calls = _record_scores(monkeypatch)

    await _refresh(
        client, admin_auth_header, monkeypatch, dataset_id, source_count=source_count
    )

    [run] = await _runs_ordered(test_db_session, dataset_id)
    assert run.status == status, run.verification
    assert calls == []


async def test_a_published_refresh_stores_the_quality_of_the_staged_table(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    """A published service refresh scores the staged table once and stores it."""
    dataset_id = await _ingest(test_db_session, monkeypatch, _WELLS)
    calls = _record_scores(monkeypatch)

    kwargs = await _refresh(
        client, admin_auth_header, monkeypatch, dataset_id, source_count=len(_WELLS)
    )

    [run] = await _runs_ordered(test_db_session, dataset_id)
    assert run.status == "succeeded", run.verification
    test_db_session.expire_all()
    dataset = await test_db_session.get(Dataset, dataset_id)
    staging = attempt_scoped_staging_table(
        dataset.table_name, uuid.UUID(kwargs["attempt_id"])
    )
    assert [table for table, _ in calls] == [staging]
    assert dataset.quality_detail == calls[0][1]
