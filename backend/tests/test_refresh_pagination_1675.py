"""Service-refresh paging and pre-publication verification tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import anyio
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import text, update

from app.modules.catalog.datasets.api import router_refresh
from app.modules.catalog.sources.adapters.arcgis import ArcGISIDPlan
from app.modules.catalog.sources.adapters.arcgis import ArcGISTokenError
from app.modules.catalog.datasets.domain.models import Record
from app.platform.catalog_locks import lock_catalog_rows
from app.platform.refresh.verification import (
    canonical_service_source_binding_fingerprint,
)
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.jobs.models import IngestJob
from app.platform.dataset_origin import set_dataset_origin
from app.processing.ingest import tasks_vector
from app.processing.ingest.tasks_common import _ARCGIS_GDAL_GET_URL_MAX_BYTES
from app.processing.ingest.tasks_reupload import (
    RefreshPublicationFenceError,
    _enforce_refresh_publication_fence,
    reupload_service,
)

from tests.factories import create_dataset, get_user_id
from tests.test_refresh_gate_1269 import _dispatch_harness, _runs_ordered

_ARCGIS_BASE = "https://services.example.com/arcgis/rest/services/Big/FeatureServer"


async def _arcgis_dataset(session, *, created_by: uuid.UUID):
    dataset = await create_dataset(
        session,
        created_by=created_by,
        source_format="arcgis_featureserver",
        visibility="public",
    )
    enriched = f"{_ARCGIS_BASE}/0"
    dataset.source_url = enriched
    set_dataset_origin(
        dataset,
        "service",
        uri=enriched,
        service_type="arcgis_featureserver",
        url=_ARCGIS_BASE,
        layer_id="0",
    )
    await session.commit()
    await session.refresh(dataset)
    return dataset


def _fake_ogr2ogr(
    calls: list[dict], rows_per_call, *, geometry_type: str = "Point", srid: int = 4326
):
    """Record every fetch and materialize rows like the subprocess would.

    ``rows_per_call(call_index)`` returns how many rows this page inserts —
    the no-progress guard counts the staging table for real.
    """

    async def _fake(
        gdal_source: str,
        layer_name: str,
        table_name: str,
        db_conn_str: str,
        service_type: str,
        timeout: float = 1800.0,
        token: str | None = None,
        is_non_spatial: bool = False,
        append: bool = False,
        *,
        schema: str,
        on_spawn=None,
    ) -> None:
        if on_spawn is not None:
            on_spawn()
        index = len(calls)
        calls.append({"source": gdal_source, "append": append, "table": table_name})
        from app.core.db import async_session

        async with async_session() as session:
            if not append:
                await session.execute(
                    text(f'DROP TABLE IF EXISTS "{schema}"."{table_name}"')
                )
                await session.execute(
                    text(
                        f'CREATE TABLE "{schema}"."{table_name}" '
                        "(gid serial PRIMARY KEY, name text, "
                        f"geom geometry({geometry_type}, {srid}))"
                    )
                )
            rows = rows_per_call(index)
            if rows:
                await session.execute(
                    text(
                        f'INSERT INTO "{schema}"."{table_name}" (name) '
                        f"SELECT 'r' FROM generate_series(1, {int(rows)})"
                    )
                )
            await session.commit()

    return _fake


async def _dispatch_refresh(
    client: AsyncClient,
    admin_auth_header: dict,
    dataset_id,
    *,
    body: dict | None = None,
) -> dict:
    async with _dispatch_harness() as task:
        resp = await client.post(
            f"/datasets/{dataset_id}/refresh",
            json=body or {},
            headers=admin_auth_header,
        )
    assert resp.status_code == 202, resp.text
    return task.defer_async.call_args.kwargs


async def _execute_with_fake(task_kwargs: dict, fake) -> None:
    with (
        patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
        patch(
            "app.processing.ingest.ogr.run_ogr2ogr_service", new_callable=AsyncMock
        ) as mock_run,
    ):
        mock_run.side_effect = fake
        await reupload_service.func(**task_kwargs)


@pytest.mark.anyio
async def test_finalization_fence_blocks_a_local_edit_after_the_run_baseline(
    test_db_session,
):
    """A fresh locked record clock fences edits made while fetch was in flight."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    baseline = dataset.record.updated_at
    assert baseline is not None
    job = IngestJob(
        dataset_id=dataset.id,
        created_by=admin_id,
        status="running",
        user_metadata={"refresh": True},
    )
    test_db_session.add(job)
    await test_db_session.flush()
    test_db_session.add(
        DatasetRefreshRun(
            dataset_id=dataset.id,
            ingest_job_id=job.id,
            origin_kind="service",
            trigger="scheduled",
            status="running",
            started_at=datetime.now(timezone.utc),
            scheduled_for=datetime.now(timezone.utc),
            occurrence_key=f"local-edit-fence:{uuid.uuid4()}",
            claim_deadline=datetime.now(timezone.utc),
            execution_key=uuid.uuid4(),
            local_edit_baseline=baseline,
            source_binding_fingerprint=canonical_service_source_binding_fingerprint(
                dataset.origin_ref
            ),
            verification_policy="arcgis_id_set_v1",
        )
    )
    await test_db_session.commit()

    from app.core.db import async_session

    async with async_session() as editor:
        await editor.execute(
            update(Record)
            .where(Record.id == dataset.record_id)
            .values(title="Edited while refresh was fetching")
        )
        await editor.commit()

    await lock_catalog_rows(
        test_db_session,
        dataset_cls=type(dataset),
        record_cls=Record,
        dataset_id=dataset.id,
        record_id=dataset.record_id,
        lock_timeout=None,
    )
    with pytest.raises(
        RefreshPublicationFenceError, match="Dataset changed locally"
    ) as refused:
        await _enforce_refresh_publication_fence(
            test_db_session,
            job_id=job.id,
            dataset=dataset,
            verification={"decision": "allowed"},
        )
    assert refused.value.code == "local_edits_changed"


@pytest.mark.anyio
async def test_finalization_fence_blocks_a_source_rebind_before_publication(
    test_db_session,
):
    """A run cannot publish after the service binding it admitted has changed."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    job = IngestJob(
        dataset_id=dataset.id,
        created_by=admin_id,
        status="running",
        user_metadata={"refresh": True},
    )
    test_db_session.add(job)
    await test_db_session.flush()
    test_db_session.add(
        DatasetRefreshRun(
            dataset_id=dataset.id,
            ingest_job_id=job.id,
            origin_kind="service",
            trigger="scheduled",
            status="running",
            started_at=datetime.now(timezone.utc),
            scheduled_for=datetime.now(timezone.utc),
            occurrence_key=f"source-fence:{uuid.uuid4()}",
            claim_deadline=datetime.now(timezone.utc),
            execution_key=uuid.uuid4(),
            source_binding_fingerprint=canonical_service_source_binding_fingerprint(
                dataset.origin_ref
            ),
            verification_policy="arcgis_id_set_v1",
        )
    )
    await test_db_session.flush()
    set_dataset_origin(
        dataset,
        "service",
        uri=f"{_ARCGIS_BASE}/1",
        service_type="arcgis_featureserver",
        url=_ARCGIS_BASE,
        layer_id="1",
    )
    await test_db_session.commit()

    await lock_catalog_rows(
        test_db_session,
        dataset_cls=type(dataset),
        record_cls=Record,
        dataset_id=dataset.id,
        record_id=dataset.record_id,
        lock_timeout=None,
    )
    with pytest.raises(
        RefreshPublicationFenceError, match="Refresh source changed"
    ) as refused:
        await _enforce_refresh_publication_fence(
            test_db_session,
            job_id=job.id,
            dataset=dataset,
            verification={"decision": "allowed"},
        )
    assert refused.value.code == "source_changed"


@pytest.mark.anyio
async def test_refresh_pages_large_arcgis_layer(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """4500 features at page size 1000 -> five appended pages, one success."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)

    async def _fake_page_info(source_url, layer_id, token):
        return 4500, 1000, True, "FID"

    # Patched on tasks_vector: the refresh guard resolves the probe through
    # tasks_vector's module attribute, so one patch covers both doors.
    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)

    calls: list[dict] = []
    task_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset.id)
    with patch(
        "app.processing.ingest.metadata.compute_table_content_digest",
        new_callable=AsyncMock,
        return_value="a" * 64,
    ) as mock_content_digest:
        await _execute_with_fake(
            task_kwargs, _fake_ogr2ogr(calls, lambda i: 1000 if i < 4 else 500)
        )
    mock_content_digest.assert_awaited_once()

    assert len(calls) == 5, calls
    assert [c["append"] for c in calls] == [False, True, True, True, True]
    for i, call in enumerate(calls):
        assert f"resultOffset={i * 1000}" in call["source"], call["source"]
        assert "resultRecordCount=1000" in call["source"], call["source"]

    runs = await _runs_ordered(test_db_session, dataset.id)
    assert [r.status for r in runs] == ["succeeded"]
    assert runs[0].feature_count_after == 4500


@pytest.mark.anyio
async def test_small_arcgis_count_mismatch_refuses_publication(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)

    async def _fake_page_info(source_url, layer_id, token):
        return 500, 1000, False, None

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)

    calls: list[dict] = []
    task_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset.id)
    await _execute_with_fake(task_kwargs, _fake_ogr2ogr(calls, lambda i: 400))

    assert len(calls) == 1
    runs = await _runs_ordered(test_db_session, dataset.id)
    assert runs[0].status == "failed"
    assert runs[0].error_code == "source_count_mismatch"
    assert runs[0].verification["source_count"] == 500
    assert runs[0].verification["fetched_count"] == 400


@pytest.mark.anyio
async def test_empty_refresh_blocks_until_exact_run_is_accepted(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    dataset.feature_count = 10
    await test_db_session.execute(
        text(
            "UPDATE catalog.records SET spatial_extent = "
            "ST_GeomFromText('POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))', 4326) "
            "WHERE id = :record_id"
        ),
        {"record_id": dataset.record_id},
    )
    await test_db_session.commit()
    dataset_id = dataset.id
    record_id = dataset.record_id
    original_version = dataset.current_version

    async def _fake_page_info(source_url, layer_id, token):
        return 0, 1000, True, "FID"

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)
    fake = _fake_ogr2ogr([], lambda i: 0)

    first_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset_id)
    await _execute_with_fake(first_kwargs, fake)

    runs = await _runs_ordered(test_db_session, dataset_id)
    blocked = runs[0]
    assert blocked.status == "blocked"
    assert blocked.verification["review_reasons"] == ["empty_result"]
    await test_db_session.refresh(dataset)
    assert dataset.current_version == original_version

    async with _dispatch_harness() as failed_task:
        failed_task.defer_async.side_effect = RuntimeError("queue unavailable")
        failed_dispatch = await client.post(
            f"/datasets/{dataset_id}/refresh",
            json={"accept_blocked_run_id": str(blocked.id)},
            headers=admin_auth_header,
        )
    assert failed_dispatch.status_code == 503
    await test_db_session.refresh(blocked)
    assert "acceptance_consumed_by_run_id" not in blocked.verification

    accepted_kwargs = await _dispatch_refresh(
        client,
        admin_auth_header,
        dataset_id,
        body={"accept_blocked_run_id": str(blocked.id)},
    )
    await _execute_with_fake(accepted_kwargs, fake)

    test_db_session.expire_all()
    runs = await _runs_ordered(test_db_session, dataset_id)
    assert [run.status for run in runs] == ["blocked", "failed", "succeeded"]
    succeeded = next(run for run in runs if run.status == "succeeded")
    assert succeeded.verification["accepted_blocked_run_id"] == str(blocked.id)
    blocked = next(run for run in runs if run.status == "blocked")
    assert blocked.verification["acceptance_consumed_by_run_id"] == str(succeeded.id)
    assert (
        await test_db_session.scalar(
            text("SELECT spatial_extent FROM catalog.records WHERE id = :record_id"),
            {"record_id": record_id},
        )
        is None
    )

    async with _dispatch_harness():
        reused = await client.post(
            f"/datasets/{dataset_id}/refresh",
            json={"accept_blocked_run_id": str(blocked.id)},
            headers=admin_auth_header,
        )
    assert reused.status_code == 422


@pytest.mark.anyio
async def test_empty_refresh_acceptance_fences_staged_spatial_contract(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    dataset.feature_count = 10
    await test_db_session.commit()
    dataset_id = dataset.id
    original_version = dataset.current_version

    async def _fake_page_info(source_url, layer_id, token):
        return 0, 1000, True, "FID"

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)

    first_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset_id)
    await _execute_with_fake(
        first_kwargs,
        _fake_ogr2ogr([], lambda i: 0, geometry_type="PointZ", srid=4326),
    )
    first_blocked = (await _runs_ordered(test_db_session, dataset_id))[0]
    assert first_blocked.status == "blocked"
    assert first_blocked.verification["staged_geometry_type"] == "POINT"
    assert first_blocked.verification["staged_srid"] == 4326
    assert first_blocked.verification["staged_coordinate_dimension"] == 3

    changed_kwargs = await _dispatch_refresh(
        client,
        admin_auth_header,
        dataset_id,
        body={"accept_blocked_run_id": str(first_blocked.id)},
    )
    await _execute_with_fake(
        changed_kwargs,
        _fake_ogr2ogr([], lambda i: 0, geometry_type="Point", srid=4326),
    )

    test_db_session.expire_all()
    runs = await _runs_ordered(test_db_session, dataset_id)
    second_blocked = runs[1]
    assert [run.status for run in runs] == ["blocked", "blocked"]
    assert second_blocked.verification["accepted_blocked_run_id"] is None
    assert second_blocked.verification["staged_geometry_type"] == "POINT"
    assert second_blocked.verification["staged_srid"] == 4326
    assert second_blocked.verification["staged_coordinate_dimension"] == 2
    dataset = await test_db_session.get(type(dataset), dataset_id)
    assert dataset is not None
    assert dataset.current_version == original_version

    retry_kwargs = await _dispatch_refresh(
        client,
        admin_auth_header,
        dataset_id,
        body={"accept_blocked_run_id": str(second_blocked.id)},
    )
    await _execute_with_fake(
        retry_kwargs,
        _fake_ogr2ogr([], lambda i: 0, geometry_type="Point", srid=4326),
    )

    test_db_session.expire_all()
    runs = await _runs_ordered(test_db_session, dataset_id)
    assert [run.status for run in runs] == ["blocked", "blocked", "succeeded"]
    assert runs[2].verification["accepted_blocked_run_id"] == str(second_blocked.id)
    dataset = await test_db_session.get(type(dataset), dataset_id)
    assert dataset is not None
    assert dataset.current_version != original_version
    assert dataset.geometry_type == "POINT"
    assert dataset.srid == 4326


@pytest.mark.anyio
async def test_blocked_refresh_acceptance_is_consumed_by_one_concurrent_session(
    test_db_session,
):
    """Two dispatches cannot both consume one blocked refresh approval."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    blocked = DatasetRefreshRun(
        dataset_id=dataset.id,
        origin_kind="service",
        trigger="api",
        status="blocked",
        verification={"review_fingerprint": "same-fingerprint"},
    )
    test_db_session.add(blocked)
    await test_db_session.commit()
    blocked_id = blocked.id
    dataset_id = dataset.id
    run_ids = [uuid.uuid4(), uuid.uuid4()]

    import app.core.db as db_module

    outcomes: list[tuple[str, uuid.UUID | int]] = []

    async def _consume_once(new_run_id: uuid.UUID) -> None:
        async with db_module.async_session() as session:
            try:
                await router_refresh._consume_blocked_refresh_acceptance(
                    session,
                    dataset_id=dataset_id,
                    blocked_run_id=blocked_id,
                    new_run_id=new_run_id,
                    fingerprint="same-fingerprint",
                )
            except HTTPException as exc:
                await session.rollback()
                outcomes.append(("rejected", exc.status_code))
            else:
                await session.commit()
                outcomes.append(("consumed", new_run_id))

    with anyio.fail_after(30):
        async with anyio.create_task_group() as task_group:
            for run_id in run_ids:
                task_group.start_soon(_consume_once, run_id)

    assert sorted(outcome[0] for outcome in outcomes) == ["consumed", "rejected"]
    winner_id = next(value for kind, value in outcomes if kind == "consumed")
    loser_status = next(value for kind, value in outcomes if kind == "rejected")
    assert loser_status == 422

    test_db_session.expire_all()
    consumed = await test_db_session.get(DatasetRefreshRun, blocked_id)
    assert consumed is not None
    assert consumed.verification["acceptance_consumed_by_run_id"] == str(winner_id)


@pytest.mark.anyio
async def test_unavailable_source_count_blocks_until_exact_run_is_accepted(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    original_version = dataset.current_version

    async def _fake_page_info(source_url, layer_id, token):
        return None, 1000, False, None

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)
    fake = _fake_ogr2ogr([], lambda i: 10)

    first_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset.id)
    await _execute_with_fake(first_kwargs, fake)
    blocked = (await _runs_ordered(test_db_session, dataset.id))[0]

    assert blocked.status == "blocked"
    assert blocked.verification["review_reasons"] == ["source_count_unavailable"]
    await test_db_session.refresh(dataset)
    assert dataset.current_version == original_version

    accepted_kwargs = await _dispatch_refresh(
        client,
        admin_auth_header,
        dataset.id,
        body={"accept_blocked_run_id": str(blocked.id)},
    )
    await _execute_with_fake(accepted_kwargs, fake)

    runs = await _runs_ordered(test_db_session, dataset.id)
    assert [run.status for run in runs] == ["blocked", "succeeded"]
    assert runs[1].verification["accepted_blocked_run_id"] == str(blocked.id)


@pytest.mark.anyio
async def test_destructive_schema_change_blocks_before_swap(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    dataset.feature_count = 10
    dataset.column_info = [
        {"name": "name", "type": "text", "ordinal_position": 2, "is_nullable": True},
        {
            "name": "zoning_code",
            "type": "text",
            "ordinal_position": 3,
            "is_nullable": True,
        },
    ]
    await test_db_session.commit()
    original_version = dataset.current_version

    async def _fake_page_info(source_url, layer_id, token):
        return 10, 1000, False, None

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)
    task_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset.id)
    await _execute_with_fake(task_kwargs, _fake_ogr2ogr([], lambda i: 10))

    blocked = (await _runs_ordered(test_db_session, dataset.id))[0]
    assert blocked.status == "blocked"
    assert blocked.verification["review_reasons"] == ["destructive_schema_change"]
    assert blocked.schema_diff["columns_removed"] == [
        {"name": "zoning_code", "type": "text"}
    ]
    await test_db_session.refresh(dataset)
    assert dataset.current_version == original_version

    accepted_kwargs = await _dispatch_refresh(
        client,
        admin_auth_header,
        dataset.id,
        body={"accept_blocked_run_id": str(blocked.id)},
    )
    await _execute_with_fake(accepted_kwargs, _fake_ogr2ogr([], lambda i: 10))

    runs = await _runs_ordered(test_db_session, dataset.id)
    assert [run.status for run in runs] == ["blocked", "succeeded"]
    assert runs[1].verification["accepted_blocked_run_id"] == str(blocked.id)


@pytest.mark.anyio
async def test_post_verification_failure_preserves_evidence_and_live_dataset(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    dataset.feature_count = 10
    await test_db_session.execute(
        text(
            "UPDATE catalog.records SET spatial_extent = "
            "ST_GeomFromText('POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))', 4326) "
            "WHERE id = :record_id"
        ),
        {"record_id": dataset.record_id},
    )
    await test_db_session.commit()
    dataset_id = dataset.id
    record_id = dataset.record_id
    original_version = dataset.current_version

    async def _fake_page_info(source_url, layer_id, token):
        return 10, 1000, False, None

    async def _fail_after_swap(*args, **kwargs):
        raise RuntimeError("publication failed")

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)
    monkeypatch.setattr(
        "app.processing.ingest.publication.record_refresh_success", _fail_after_swap
    )
    task_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset_id)

    with pytest.raises(RuntimeError, match="publication failed"):
        await _execute_with_fake(task_kwargs, _fake_ogr2ogr([], lambda i: 10))

    test_db_session.expire_all()
    run = (await _runs_ordered(test_db_session, dataset_id))[0]
    assert run.status == "failed"
    assert run.feature_count_after == 10
    assert run.verification["decision"] == "allowed"
    assert run.verification["count_status"] == "matched"
    assert run.schema_diff["row_count_new"] == 10
    refreshed = await test_db_session.get(type(dataset), dataset_id)
    assert refreshed.current_version == original_version
    extent = await test_db_session.scalar(
        text(
            "SELECT ST_AsText(spatial_extent) FROM catalog.records "
            "WHERE id = :record_id"
        ),
        {"record_id": record_id},
    )
    assert extent == "POLYGON((0 0,0 1,1 1,1 0,0 0))"


@pytest.mark.anyio
async def test_refresh_no_progress_page_fails_the_run(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """An empty page must abort the refresh, not swap a short copy in."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)

    async def _fake_page_info(source_url, layer_id, token):
        return 4500, 1000, True, "FID"

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)

    calls: list[dict] = []
    task_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset.id)
    # The task records the failure on the run row and re-raises so the
    # queue marks the job failed too.
    from app.processing.ingest.ogr import IngestionError

    with pytest.raises(IngestionError, match="no row-count progress"):
        await _execute_with_fake(
            task_kwargs, _fake_ogr2ogr(calls, lambda i: 1000 if i == 0 else 0)
        )

    # Page 2 made no row-count progress: fetch aborted, nothing swapped.
    assert len(calls) == 2, calls
    runs = await _runs_ordered(test_db_session, dataset.id)
    assert [r.status for r in runs] == ["failed"]
    assert "no row-count progress" in (runs[0].error_message or "")


@pytest.mark.anyio
async def test_partially_populated_pages_fail_the_run(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """fix(#1675 codex r2): a server that caps responses below its advertised
    page size returns SOME rows per page, so the offset skips records while
    the count keeps growing — positive growth must not be enough."""
    from app.processing.ingest.ogr import IngestionError

    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)

    async def _fake_page_info(source_url, layer_id, token):
        return 4500, 1000, True, "FID"

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)

    calls: list[dict] = []
    task_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset.id)
    with pytest.raises(IngestionError, match="400 rows where 1000 were expected"):
        await _execute_with_fake(task_kwargs, _fake_ogr2ogr(calls, lambda i: 400))

    assert len(calls) == 1, calls  # fails on the very first short page
    runs = await _runs_ordered(test_db_session, dataset.id)
    assert [r.status for r in runs] == ["failed"]


@pytest.mark.anyio
async def test_probe_failure_still_stamps_origin_contact(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """fix(#1675 codex r1): a refresh that dies in the page-info probe (e.g.
    an ArcGIS 498/499 token error) still CONTACTED the origin — the failure
    path must stamp last_checked_at even though no subprocess ever spawned."""
    from app.processing.ingest.ogr import IngestionError

    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    assert dataset.last_checked_at is None

    async def _probe_token_error(source_url, layer_id, token):
        raise IngestionError("ArcGIS token required (498)")

    monkeypatch.setattr(
        tasks_vector, "_fetch_arcgis_import_page_info", _probe_token_error
    )

    calls: list[dict] = []
    task_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset.id)
    # The tokenless auth failure is rewrapped with the "retry with a token"
    # hint by _run_service_import_with_wfs_fallback — that rewrap is the
    # expected user-facing shape, and the contact stamp must survive it.
    with pytest.raises(IngestionError, match="authentication failed"):
        await _execute_with_fake(task_kwargs, _fake_ogr2ogr(calls, lambda i: 0))

    assert calls == []  # the fetch never spawned
    runs = await _runs_ordered(test_db_session, dataset.id)
    assert [r.status for r in runs] == ["failed"]
    await test_db_session.refresh(dataset)
    assert dataset.last_checked_at is not None


@pytest.mark.anyio
async def test_first_arcgis_page_info_token_rejection_preserves_typed_failure(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """A source 498 during the first page-info request expires the refresh credential."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    rejected = ArcGISTokenError(498, "Token rejected")

    monkeypatch.setattr(
        "app.modules.catalog.sources.adapters.arcgis.fetch_arcgis_pagination_info",
        AsyncMock(side_effect=rejected),
    )
    task_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset.id)

    with pytest.raises(ArcGISTokenError) as raised:
        await _execute_with_fake(task_kwargs, _fake_ogr2ogr([], lambda _: 0))

    assert raised.value.code == 498
    assert str(raised.value) == "ArcGIS token error (498): Token rejected"
    run = (await _runs_ordered(test_db_session, dataset.id))[0]
    assert run.status == "failed"
    assert run.error_code == "credential_expired"


@pytest.mark.anyio
async def test_refresh_small_layer_keeps_single_fetch(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """A layer within one page keeps the single unpaged fetch."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)

    async def _fake_page_info(source_url, layer_id, token):
        return 500, 1000, True, "FID"

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)

    calls: list[dict] = []
    task_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset.id)
    await _execute_with_fake(task_kwargs, _fake_ogr2ogr(calls, lambda i: 500))

    assert len(calls) == 1, calls
    assert "resultOffset" not in calls[0]["source"], calls[0]["source"]
    runs = await _runs_ordered(test_db_session, dataset.id)
    assert [r.status for r in runs] == ["succeeded"]


def _arcgis_id_plan(ids: tuple[int, ...]) -> ArcGISIDPlan:
    from hashlib import sha256
    import json

    payload = json.dumps(
        {"oid_field": "OBJECTID", "ids": list(ids)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return ArcGISIDPlan(
        oid_field="OBJECTID",
        ids=ids,
        digest=sha256(payload.encode()).hexdigest(),
        source_marker=123,
    )


def _fake_ogr2ogr_with_source_oids(calls: list[dict], staged_ids: list[int]):
    """Materialize the ArcGIS OBJECTID attribute GDAL transports from query."""

    async def _fake(
        gdal_source: str,
        layer_name: str,
        table_name: str,
        db_conn_str: str,
        service_type: str,
        timeout: float = 1800.0,
        token: str | None = None,
        is_non_spatial: bool = False,
        append: bool = False,
        *,
        schema: str,
        on_spawn=None,
    ) -> None:
        if on_spawn is not None:
            on_spawn()
        calls.append({"source": gdal_source, "append": append})
        query = parse_qs(urlparse(gdal_source.split(":", 1)[1]).query)
        requested_ids = {
            int(value) for value in query["objectIds"][0].split(",") if value
        }
        from app.core.db import async_session

        async with async_session() as session:
            if not append:
                await session.execute(
                    text(f'DROP TABLE IF EXISTS "{schema}"."{table_name}"')
                )
                await session.execute(
                    text(
                        f'CREATE TABLE "{schema}"."{table_name}" '
                        "(gid serial PRIMARY KEY, objectid bigint, name text, "
                        "geom geometry(Point, 4326))"
                    )
                )
            await session.execute(
                text(
                    f'INSERT INTO "{schema}"."{table_name}" (objectid, name) '
                    "SELECT source_id, 'r' FROM unnest(CAST(:ids AS bigint[])) "
                    "AS source_id"
                ),
                {
                    "ids": [
                        source_id
                        for source_id in staged_ids
                        if source_id in requested_ids
                    ]
                },
            )
            await session.commit()

    return _fake


@pytest.mark.anyio
async def test_stronger_arcgis_policy_uses_exact_id_chunks_and_records_coverage(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    ids = (3, 991, 9_223_372_036_854_775_807)

    async def _fake_page_info(source_url, layer_id, token):
        return len(ids), 1000, True, "OBJECTID"

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)
    monkeypatch.setattr(
        "app.modules.catalog.sources.adapters.arcgis.fetch_arcgis_id_plan",
        AsyncMock(side_effect=[_arcgis_id_plan(ids), _arcgis_id_plan(ids)]),
    )
    calls: list[dict] = []
    task_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset.id)
    task_kwargs["verification_policy"] = "arcgis_id_set_v1"
    await _execute_with_fake(
        task_kwargs, _fake_ogr2ogr_with_source_oids(calls, list(ids))
    )

    assert len(calls) == 1
    assert "objectIds=3%2C991%2C9223372036854775807" in calls[0]["source"]
    runs = await _runs_ordered(test_db_session, dataset.id)
    verification = runs[0].verification
    assert verification["decision"] == "allowed", verification
    assert runs[0].status == "succeeded", verification
    assert verification["identity_check"] == "arcgis_id_set"
    assert verification["arcgis_id_coverage"]["status"] == "matched"
    assert verification["arcgis_id_coverage"]["source_membership_status"] == "matched"


@pytest.mark.anyio
async def test_stronger_arcgis_policy_clamps_exact_id_chunks_to_gdal_bound(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    ids = (*range(1_000), (1 << 63) - 1)

    async def _fake_page_info(source_url, layer_id, token):
        return len(ids), 2_000, True, "OBJECTID"

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)
    monkeypatch.setattr(
        "app.modules.catalog.sources.adapters.arcgis.fetch_arcgis_id_plan",
        AsyncMock(side_effect=[_arcgis_id_plan(ids), _arcgis_id_plan(ids)]),
    )
    calls: list[dict] = []
    task_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset.id)
    task_kwargs["verification_policy"] = "arcgis_id_set_v1"
    await _execute_with_fake(
        task_kwargs, _fake_ogr2ogr_with_source_oids(calls, list(ids))
    )

    assert [
        len(
            parse_qs(urlparse(call["source"].split(":", 1)[1]).query)["objectIds"][
                0
            ].split(",")
        )
        for call in calls
    ] == [1_000, 1]
    assert all(call["source"].startswith("GeoJSON:") for call in calls)
    run = (await _runs_ordered(test_db_session, dataset.id))[0]
    assert run.status == "succeeded"
    assert run.verification["arcgis_id_coverage"]["status"] == "matched"


@pytest.mark.anyio
async def test_stronger_arcgis_policy_bounds_long_id_chunks_by_gdal_url_size(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    ids = tuple((1 << 63) - 1 - offset for offset in range(1_000))

    async def _fake_page_info(source_url, layer_id, token):
        return len(ids), 2_000, True, "OBJECTID"

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)
    monkeypatch.setattr(
        "app.modules.catalog.sources.adapters.arcgis.fetch_arcgis_id_plan",
        AsyncMock(side_effect=[_arcgis_id_plan(ids), _arcgis_id_plan(ids)]),
    )
    calls: list[dict] = []
    task_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset.id)
    task_kwargs["verification_policy"] = "arcgis_id_set_v1"
    await _execute_with_fake(
        task_kwargs, _fake_ogr2ogr_with_source_oids(calls, list(ids))
    )

    requested_ids: list[int] = []
    for call in calls:
        assert len(call["source"].encode("utf-8")) <= _ARCGIS_GDAL_GET_URL_MAX_BYTES
        query = parse_qs(urlparse(call["source"].split(":", 1)[1]).query)
        requested_ids.extend(int(value) for value in query["objectIds"][0].split(","))

    assert len(calls) > 1
    assert requested_ids == list(ids)
    assert len(requested_ids) == len(set(requested_ids))
    run = (await _runs_ordered(test_db_session, dataset.id))[0]
    assert run.status == "succeeded"
    assert run.verification["arcgis_id_coverage"]["status"] == "matched"


@pytest.mark.anyio
async def test_stronger_arcgis_policy_records_source_token_challenge_as_expired(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)

    async def _fake_page_info(source_url, layer_id, token):
        return 1, 1000, True, "OBJECTID"

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)
    monkeypatch.setattr(
        "app.modules.catalog.sources.adapters.arcgis.fetch_arcgis_id_plan",
        AsyncMock(side_effect=ArcGISTokenError(498, "Token rejected")),
    )
    task_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset.id)
    task_kwargs["verification_policy"] = "arcgis_id_set_v1"

    with pytest.raises(ArcGISTokenError, match="498"):
        await _execute_with_fake(task_kwargs, _fake_ogr2ogr([], 1))

    run = (await _runs_ordered(test_db_session, dataset.id))[0]
    assert run.status == "failed"
    assert run.error_code == "credential_expired"


@pytest.mark.anyio
async def test_stronger_arcgis_policy_rejects_same_count_duplicate_source_oids(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    original_version = dataset.current_version
    ids = (3, 991, 9_223_372_036_854_775_807)

    async def _fake_page_info(source_url, layer_id, token):
        return len(ids), 1000, True, "OBJECTID"

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)
    monkeypatch.setattr(
        "app.modules.catalog.sources.adapters.arcgis.fetch_arcgis_id_plan",
        AsyncMock(side_effect=[_arcgis_id_plan(ids), _arcgis_id_plan(ids)]),
    )
    task_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset.id)
    task_kwargs["verification_policy"] = "arcgis_id_set_v1"
    await _execute_with_fake(
        task_kwargs, _fake_ogr2ogr_with_source_oids([], [3, 3, 991])
    )

    await test_db_session.refresh(dataset)
    run = (await _runs_ordered(test_db_session, dataset.id))[0]
    assert run.status == "failed"
    assert run.error_code == "arcgis_id_coverage_mismatch"
    assert run.error_message == (
        "The staged ArcGIS object IDs did not match the source IDs."
    )
    assert dataset.current_version == original_version
    assert run.verification["arcgis_id_coverage"]["duplicate_count"] == 1
    assert run.verification["arcgis_id_coverage"]["missing_count"] == 1


@pytest.mark.anyio
async def test_stronger_arcgis_policy_reports_changed_source_membership(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    original_version = dataset.current_version
    initial_ids = (3, 991, 9_223_372_036_854_775_807)
    changed_ids = (3, 992, 9_223_372_036_854_775_807)

    async def _fake_page_info(source_url, layer_id, token):
        return len(initial_ids), 1000, True, "OBJECTID"

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _fake_page_info)
    monkeypatch.setattr(
        "app.modules.catalog.sources.adapters.arcgis.fetch_arcgis_id_plan",
        AsyncMock(
            side_effect=[_arcgis_id_plan(initial_ids), _arcgis_id_plan(changed_ids)]
        ),
    )
    task_kwargs = await _dispatch_refresh(client, admin_auth_header, dataset.id)
    task_kwargs["verification_policy"] = "arcgis_id_set_v1"
    await _execute_with_fake(
        task_kwargs, _fake_ogr2ogr_with_source_oids([], list(initial_ids))
    )

    await test_db_session.refresh(dataset)
    run = (await _runs_ordered(test_db_session, dataset.id))[0]
    assert run.status == "failed"
    assert run.error_code == "arcgis_source_membership_changed"
    assert run.error_message == "The ArcGIS source membership changed during refresh."
    assert dataset.current_version == original_version
    assert run.verification["count_status"] == "matched"
    assert run.verification["arcgis_id_coverage"]["status"] == "matched"
    assert (
        run.verification["arcgis_id_coverage"]["source_membership_status"] == "changed"
    )
