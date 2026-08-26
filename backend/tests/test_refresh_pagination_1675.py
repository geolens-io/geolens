"""fix(#1675): the refresh executor pages large ArcGIS layers.

A refresh used to do ONE unpaged ogr2ogr fetch and trust GDAL driver paging,
while the initial-import path pages explicitly with a row-count no-progress
guard. Both doors now share tasks_common.run_paged_arcgis_service_fetch;
these tests drive the real ``reupload_service`` worker entry point (the
test_refresh_gate_1269 recipe) and fake only the outbound ogr2ogr boundary.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.platform.dataset_origin import set_dataset_origin
from app.processing.ingest import tasks_vector
from app.processing.ingest.tasks_reupload import reupload_service

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


def _fake_ogr2ogr(calls: list[dict], rows_per_call):
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
                        "(gid serial PRIMARY KEY, name text)"
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
    client: AsyncClient, admin_auth_header: dict, dataset_id
) -> dict:
    async with _dispatch_harness() as task:
        resp = await client.post(
            f"/datasets/{dataset_id}/refresh",
            json={},
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
    await _execute_with_fake(
        task_kwargs, _fake_ogr2ogr(calls, lambda i: 1000 if i < 4 else 500)
    )

    assert len(calls) == 5, calls
    assert [c["append"] for c in calls] == [False, True, True, True, True]
    for i, call in enumerate(calls):
        assert f"resultOffset={i * 1000}" in call["source"], call["source"]
        assert "resultRecordCount=1000" in call["source"], call["source"]

    runs = await _runs_ordered(test_db_session, dataset.id)
    assert [r.status for r in runs] == ["succeeded"]
    assert runs[0].feature_count_after == 4500


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
