"""Tests for async analysis materialization (M4).

Covers the materialize endpoint (job creation, auth, validation) and the
worker's core logic (`_materialize`) run directly against the test DB.

Requirements:
  - Docker database must be running (docker compose up db)
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as core_db
from app.modules.catalog.datasets.api import router_analysis
from app.platform.jobs.models import IngestJob
from app.processing.analysis.tasks import (
    MATERIALIZE_TIMEOUT,
    _enforce_output_size,
    _fail_cancelled_job,
    _mark_job_failed,
    _materialize,
    _user_error_message,
)

from tests.factories import create_dataset, get_user_id
from tests.test_analysis_preview import _create_mask_dataset, _create_polygon_dataset
from tests.test_export_hardening import (
    _DEFAULT_PERMISSION_MATRIX,
    _put_permission_matrix,
    _reset_permission_matrix,
)


def _materialize_url(dataset_id) -> str:
    return f"/datasets/{dataset_id}/analysis/materialize/"


async def _create_job(session: AsyncSession, user_id: uuid.UUID) -> IngestJob:
    job = IngestJob(
        source_filename="analysis-test",
        created_by=user_id,
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


class TestMaterializeEndpoint:
    async def test_materialize_returns_job(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        # Patch only the queue hop — job creation, auth, and quota stay real.
        with patch.object(
            router_analysis, "defer_async_with_tenant", AsyncMock()
        ) as mock_defer:
            resp = await client.post(
                _materialize_url(ds.id),
                json={
                    "operation": "buffer",
                    "distance_meters": 100,
                    "title": f"Buffered {uuid.uuid4().hex[:6]}",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "pending"
        mock_defer.assert_awaited_once()
        kwargs = mock_defer.await_args.kwargs
        assert kwargs["operation"] == "buffer"
        assert kwargs["dataset_id"] == str(ds.id)
        # fix(#695): queue names don't rank in Procrastinate — the analysis
        # defer must carry a below-default per-job priority (still on the
        # shared "ingest" queue) so queued uploads always fetch first.
        deferrer = mock_defer.await_args.args[0]
        assert deferrer.job.priority == router_analysis.ANALYSIS_JOB_PRIORITY
        assert deferrer.job.priority < 0
        assert deferrer.job.queue == "ingest"
        job = await test_db_session.get(IngestJob, uuid.UUID(data["job_id"]))
        assert job is not None
        assert job.status == "pending"
        # Request params ride the job row so Admin → Jobs can diagnose runs.
        meta = (job.user_metadata or {}).get("analysis", {})
        assert meta["operation"] == "buffer"
        assert meta["distance_meters"] == 100
        assert meta["source_dataset_id"] == str(ds.id)
        assert "mask" not in meta
        # Release the per-user active-job slot for later tests (shared DB).
        job.status = "failed"
        await test_db_session.commit()

    async def test_second_materialize_while_active_is_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """One materialize per user at a time: a second request while a job is
        still pending/running 429s instead of stacking CTAS work; a finished
        job releases the slot."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            first = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "First"},
                headers=admin_auth_header,
            )
            assert first.status_code == 200, first.text
            second = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Second"},
                headers=admin_auth_header,
            )
            assert second.status_code == 429
            job = await test_db_session.get(
                IngestJob, uuid.UUID(first.json()["job_id"])
            )
            job.status = "failed"
            await test_db_session.commit()
            third = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Third"},
                headers=admin_auth_header,
            )
            assert third.status_code == 200, third.text
            # Release the slot for later tests (shared DB).
            third_job = await test_db_session.get(
                IngestJob, uuid.UUID(third.json()["job_id"])
            )
            third_job.status = "failed"
            await test_db_session.commit()

    async def test_upload_named_like_an_analysis_job_does_not_block(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#682 review): the active-job check keys on the analysis marker
        in user_metadata, not source_filename — that column holds the user's
        own upload filename, so uploading "analysis-data.geojson" must not
        lock them out of analysis."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        upload = await _create_job(test_db_session, admin_id)
        upload.source_filename = "analysis-data.geojson"
        upload.status = "running"
        upload.user_metadata = None
        await test_db_session.commit()

        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Not blocked"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        job = await test_db_session.get(IngestJob, uuid.UUID(resp.json()["job_id"]))
        job.status = "failed"
        upload.status = "failed"
        await test_db_session.commit()

    async def test_old_pending_job_still_blocks(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """A pending job is queued work that will still run, so a backlogged
        ingest queue must not let a second CTAS through however old it is."""
        from datetime import datetime, timedelta, timezone

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        backlogged = await _create_job(test_db_session, admin_id)
        backlogged.user_metadata = {"analysis": {"operation": "buffer"}}
        backlogged.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        await test_db_session.commit()

        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Should be blocked"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 429, resp.text
        backlogged.status = "failed"
        await test_db_session.commit()

    async def test_backlogged_job_that_just_started_still_blocks(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """A job that waited out a queue backlog and only just began is fully
        active, so enqueue age must not exclude it from the cap."""
        from datetime import datetime, timedelta, timezone

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        backlogged = await _create_job(test_db_session, admin_id)
        backlogged.user_metadata = {"analysis": {"operation": "buffer"}}
        backlogged.status = "running"
        backlogged.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        backlogged.started_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await test_db_session.commit()

        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Should be blocked"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 429, resp.text
        backlogged.status = "failed"
        await test_db_session.commit()

    async def test_long_running_job_still_blocks(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#682 review): elapsed time is NOT a liveness signal, so an old
        'running' job keeps the slot.

        The 300s statement_timeout bounds each statement, not the job — a
        materialize runs a CTAS, a DELETE, an EXISTS probe, two ALTERs, a
        primary key, add_4326_column and registration in sequence, so a
        legitimate run over a large dataset can outlive any window short
        enough to be useful. Releasing the slot on age would let a second
        expensive CTAS through and defeat the cap. A worker that truly died
        is resolved by the platform job timeout instead (see #691).
        """
        from datetime import datetime, timedelta, timezone

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        long_running = await _create_job(test_db_session, admin_id)
        long_running.status = "running"
        long_running.user_metadata = {"analysis": {"operation": "buffer"}}
        long_running.started_at = datetime.now(timezone.utc) - timedelta(minutes=45)
        long_running.created_at = datetime.now(timezone.utc) - timedelta(minutes=45)
        await test_db_session.commit()

        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Should be blocked"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 429, resp.text
        long_running.status = "failed"
        await test_db_session.commit()

    async def test_materialize_private_source_hidden(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Rule 1 on the source dataset. Editor (who HAS the upload
        permission) so the check exercised here is visibility, not the
        permission gate covered below."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "centroid", "title": "Nope"},
            headers=editor_auth_header,
        )
        assert resp.status_code == 404

    async def test_materialize_private_mask_hidden(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """test(#761): Rule 1 applies to the MASK dataset on the write path
        too. The preview suite pins this; the materialize branch sits between
        two size gates that were each rewritten twice in two weeks (#693,
        #701) and had no test of its own."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        private_mask = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((-1 -1, -1 1, 1 1, 1 -1, -1 -1))",
            visibility="private",
        )
        resp = await client.post(
            _materialize_url(ds.id),
            json={
                "operation": "clip",
                "mask_dataset_id": str(private_mask.id),
                "title": "Nope",
            },
            headers=editor_auth_header,
        )
        assert resp.status_code == 404

    async def test_materialize_requires_upload_permission(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#692): materialize creates a dataset, so it carries the same
        `upload` permission as every ingest endpoint that creates one — a
        viewer gets 403 even on a dataset they can read. Preview must stay
        open to viewers: read-only, nothing persisted, and the chat tool's
        read-only surface depends on it."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "centroid", "title": "Not allowed"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403
        preview = await client.post(
            f"/datasets/{ds.id}/analysis/preview/",
            json={"operation": "centroid"},
            headers=viewer_auth_header,
        )
        assert preview.status_code == 200, preview.text

    async def test_materialize_requires_export_permission(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        editor_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Materialize hands the caller an owned dataset carrying the
        source's attributes — the outcome the download endpoints gate on
        `export` — so the two paths must agree under a customized role
        matrix: an editor whose export was revoked gets 403, not a job."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        revoked = {
            **_DEFAULT_PERMISSION_MATRIX,
            "editor": {**_DEFAULT_PERMISSION_MATRIX["editor"], "export": False},
        }
        try:
            await _put_permission_matrix(client, admin_auth_header, revoked)
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Not allowed"},
                headers=editor_auth_header,
            )
            assert resp.status_code == 403, resp.text
            assert "export" in resp.json()["detail"].lower()
        finally:
            await _reset_permission_matrix(client, admin_auth_header)

    async def test_dissolve_unknown_column_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _materialize_url(ds.id),
            json={
                "operation": "dissolve",
                "by_field": "no_such_col",
                "title": "Dissolved",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_dissolve_json_column_rejected_at_enqueue(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#766): PG has no equality operator for `json` (GDAL maps
        nested GeoJSON objects to it), so the CTAS GROUP BY would burn the
        queue wait and the per-user job slot on an opaque 42883. Reject at
        enqueue, naming the column."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            geometry_type="POLYGON",
            feature_count=2,
            column_info=[
                {"name": "props", "type": "json"},
                {"name": "name", "type": "text"},
            ],
        )
        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "dissolve", "by_field": "props", "title": "Grouped"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "props" in detail
        assert "group" in detail.lower()

    async def test_materialize_requires_title(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "centroid"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_by_field_source_count_conflict_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """A real source column named source_count would collide with the
        generated output column and fail the CTAS with an opaque error."""
        admin_id = await get_user_id(test_db_session, "admin")
        from tests.factories import create_dataset

        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            geometry_type="POLYGON",
            column_info=[{"name": "source_count", "type": "integer"}],
        )
        resp = await client.post(
            _materialize_url(ds.id),
            json={
                "operation": "dissolve",
                "by_field": "source_count",
                "title": "Conflict",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "source_count" in resp.json()["detail"]

    async def test_centroid_ignores_stray_distance(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Materialize mirrors the preview schema: distance is buffer-only."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={
                    "operation": "centroid",
                    "distance_meters": 999_999,
                    "title": "Centroids",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        # Release the per-user active-job slot for later tests (shared DB).
        job = await test_db_session.get(IngestJob, uuid.UUID(resp.json()["job_id"]))
        job.status = "failed"
        await test_db_session.commit()

    async def test_source_size_gates_dissolve_and_buffer(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#694): dissolve/buffer are size-gated at enqueue on the cached
        feature_count — dissolve's ST_Union can OOM the shared db container,
        and buffer amplifies storage with no byte quota. Centroid is 1:1 and
        stays ungated."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)

        ds.feature_count = 250_001
        await test_db_session.commit()
        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "dissolve", "title": "Too big"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "too large for dissolve" in resp.json()["detail"]

        # The boundary itself is allowed.
        ds.feature_count = 250_000
        await test_db_session.commit()
        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "dissolve", "title": "At the cap"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        job = await test_db_session.get(IngestJob, uuid.UUID(resp.json()["job_id"]))
        job.status = "failed"
        await test_db_session.commit()

        # buffer's ceiling is higher but real; centroid has none.
        ds.feature_count = 500_001
        await test_db_session.commit()
        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "buffer", "distance_meters": 10, "title": "Too big"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "too large for buffer" in resp.json()["detail"]

        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Centroid ok"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        job = await test_db_session.get(IngestJob, uuid.UUID(resp.json()["job_id"]))
        job.status = "failed"
        await test_db_session.commit()

    async def test_oversized_mask_layer_rejected_at_enqueue(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#693): the shared mask loader caps the mask layer's cached
        feature_count — the whole layer is unioned before any row limit can
        bite — so materialize rejects it before creating a job."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((-0.5 -0.5, -0.5 0.5, 0.5 0.5, 0.5 -0.5, -0.5 -0.5))",
        )
        mask_ds.feature_count = 1_001
        await test_db_session.commit()

        resp = await client.post(
            _materialize_url(ds.id),
            json={
                "operation": "clip",
                "mask_dataset_id": str(mask_ds.id),
                "title": "Too many mask features",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "mask layer has too many features" in resp.json()["detail"].lower()

        # fix(#701 review): a NULL snapshot must not read as zero — the mask
        # table (1 row) is counted live against the patched cap.
        mask_ds.feature_count = None
        await test_db_session.commit()
        with patch.object(router_analysis, "MAX_MASK_LAYER_FEATURES", 0):
            resp = await client.post(
                _materialize_url(ds.id),
                json={
                    "operation": "clip",
                    "mask_dataset_id": str(mask_ds.id),
                    "title": "Unknown mask size",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 422
        assert "mask layer has too many features" in resp.json()["detail"].lower()

    async def test_null_feature_count_probes_live_table(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#701 review): a NULL feature_count (legacy imports,
        register_existing_table paths) must not read as zero — that admits
        exactly the unknown-size datasets the OOM gate exists for. The gate
        falls back to a LIMIT-bounded live count of the physical table."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        ds.feature_count = None
        await test_db_session.commit()

        # The fixture table holds 2 rows; a cap of 1 must reject via the
        # live probe...
        with patch.dict(
            "app.platform.analysis_sql.MAX_SOURCE_FEATURES", {"dissolve": 1}
        ):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "dissolve", "title": "Unknown size"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 422
        assert "too large for dissolve" in resp.json()["detail"]

        # ...and a cap above the true count enqueues.
        with (
            patch.dict(
                "app.platform.analysis_sql.MAX_SOURCE_FEATURES", {"dissolve": 5}
            ),
            patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()),
        ):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "dissolve", "title": "Small enough"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        job = await test_db_session.get(IngestJob, uuid.UUID(resp.json()["job_id"]))
        job.status = "failed"
        await test_db_session.commit()


# ---------------------------------------------------------------------------
# Worker tests (core logic run inline, no queue)
# ---------------------------------------------------------------------------


class TestMaterializeWorker:
    async def test_buffer_materialize_creates_dataset(
        self,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        title = f"Buffered {uuid.uuid4().hex[:6]}"

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="buffer",
            title=title,
            distance_meters=100,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message
        assert job.dataset_id is not None
        # fix(v1.6.0 audit B12): the terminal write must stamp completed_at —
        # without it the jobs UI renders '-' and retention ages on queue time.
        assert job.completed_at is not None
        # fix(#682 review): without started_at the row carries no liveness
        # signal, so the platform's stale-job sweep (which matches on
        # coalesce(heartbeat_at, started_at)) could never recover a crashed
        # analysis job.
        assert job.started_at is not None
        # ...and started_at ALONE would condemn a job that legitimately outlives
        # JOB_TIMEOUT_SECONDS, since the same coalesce would then read as stale
        # while the work is still running. The lease the worker takes is what
        # keeps a live job out of the sweep, so pin that it exists.
        assert job.attempt_id is not None
        assert job.heartbeat_at is not None

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        assert new_ds.feature_count == 2
        # Output table follows the geom/geom_4326 convention with rows intact.
        count = (
            await test_db_session.execute(
                text(
                    f"SELECT COUNT(*) FROM data.{new_ds.table_name} "  # noqa: S608
                    f"WHERE geom_4326 IS NOT NULL"
                )
            )
        ).scalar_one()
        assert count == 2
        # Attribute columns are carried through 1:1 ops.
        name_count = (
            await test_db_session.execute(
                text(
                    f"SELECT COUNT(*) FROM data.{new_ds.table_name} "  # noqa: S608
                    f"WHERE name IS NOT NULL"
                )
            )
        ).scalar_one()
        assert name_count == 2

    async def test_non_identifier_columns_survive_materialize(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#763): GDAL launders only case/`-`/`#`, so ingested tables
        legitimately carry columns like `Área` or `2020_pop`; the old
        identifier-shaped filter silently dropped them from every analysis
        output."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        # ":id" doubles as the codex-review case: text() parses `:name` as a
        # bind parameter even inside quoted identifiers, so an unescaped
        # Socrata-style column would fail the whole CTAS, not just drop out.
        await test_db_session.execute(
            text(
                f"ALTER TABLE data.{ds.table_name} "
                f'ADD COLUMN "Área" TEXT, ADD COLUMN "2020_pop" INTEGER, '
                f'ADD COLUMN "\\:id" TEXT'
            )
        )
        await test_db_session.execute(
            text(
                f"UPDATE data.{ds.table_name} "  # noqa: S608
                f'SET "Área" = \'norte\', "2020_pop" = 7, "\\:id" = \'r1\''
            )
        )
        await test_db_session.commit()
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="buffer",
            title=f"Buffered unicode {uuid.uuid4().hex[:6]}",
            distance_meters=100,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        rows = (
            await test_db_session.execute(
                text(
                    f'SELECT "Área", "2020_pop", "\\:id" '  # noqa: S608
                    f"FROM data.{new_ds.table_name}"
                )
            )
        ).all()
        assert len(rows) == 2
        assert all(tuple(row) == ("norte", 7, "r1") for row in rows)

    async def test_null_geometry_rows_are_dropped_from_output(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#692): the preview filters NULL/EMPTY results in SQL, so the
        saved dataset must agree — buffer of a NULL geometry is NULL and must
        not survive into the registered output."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        await test_db_session.execute(
            text(f"INSERT INTO data.{ds.table_name} (name) VALUES ('null-geom')")  # noqa: S608
        )
        await test_db_session.commit()
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="buffer",
            title=f"Buffered nulls {uuid.uuid4().hex[:6]}",
            distance_meters=100,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        total, nulls = (
            await test_db_session.execute(
                text(
                    f"SELECT COUNT(*), COUNT(*) FILTER (WHERE geom_4326 IS NULL) "  # noqa: S608
                    f"FROM data.{new_ds.table_name}"
                )
            )
        ).one()
        assert (total, nulls) == (2, 0)

    async def test_terminal_job_is_not_resurrected(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#692): the worker claims pending→running fenced on the attempt
        token. A job that already reached a terminal state — the pending
        sweeper failing a backlogged job, or the defer orphan-guard failing
        the row after the queue INSERT committed — must stay there; before
        the claim, a late delivery would flip it back to running and later
        'complete', defeating the per-user cap and creating a dataset for a
        job the user was told failed."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        job.status = "failed"
        job.error_message = "Stale: pending for over 1 hour (never queued)"
        await test_db_session.commit()

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="centroid",
            title="Resurrected?",
        )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.dataset_id is None

    async def test_sweeper_failed_job_is_not_resurrected_at_completion(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#786): the terminal 'complete' write is fenced on the attempt
        token like the claim — if a stalled heartbeat lets the lease expire
        and the stale-job sweep fails the row mid-run, the worker must not
        overwrite failed → complete and hand the user a dataset for a job
        they were told failed. The fence shares the registration
        transaction, so the Dataset row rolls back with the miss, and the
        already-committed output table is dropped as a provable orphan."""
        import app.processing.ingest.service as ingest_service

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        real_register = ingest_service.register_existing_table
        out_tables: list[str] = []

        async def sweeping_register(session, request, user):
            # The sweep lands between the build commit and the terminal
            # write: fail the row out from under the worker on its own
            # session, exactly as the platform's stale-job sweep does.
            out_tables.append(request.table_name)
            async with core_db.async_session() as sweeper:
                await sweeper.execute(
                    update(IngestJob)
                    .where(IngestJob.id == job.id)
                    .values(
                        status="failed",
                        error_message="Stale: heartbeat lease expired",
                    )
                )
                await sweeper.commit()
            return await real_register(session, request, user)

        with patch.object(ingest_service, "register_existing_table", sweeping_register):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="centroid",
                title=f"Superseded {uuid.uuid4().hex[:6]}",
            )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.error_message == "Stale: heartbeat lease expired"
        assert job.dataset_id is None
        assert out_tables, "materialize never reached registration"

        from app.modules.catalog.datasets.domain.models import Dataset

        registered = (
            await test_db_session.execute(
                select(Dataset).where(Dataset.table_name == out_tables[0])
            )
        ).scalar_one_or_none()
        assert registered is None
        # ...and the committed output table was dropped, not leaked.
        leaked = (
            await test_db_session.execute(
                text("SELECT to_regclass(:ref)").bindparams(
                    ref=f'data."{out_tables[0]}"'
                )
            )
        ).scalar_one()
        assert leaked is None

    async def test_sweeper_failed_job_error_is_not_overwritten(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#786): _mark_job_failed is fenced like _fail_cancelled_job —
        when another actor already moved the row to a terminal state, this
        worker's later failure must not clobber the message the user saw.
        fix(v1.6.0 audit B13): the failure path CAN now tell a swept row
        from a completed one — no dataset row adopted the table here, so it
        is a provable orphan and gets dropped instead of leaking forever."""
        import app.processing.ingest.service as ingest_service

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        out_tables: list[str] = []

        async def sweeping_register(session, request, user):
            out_tables.append(request.table_name)
            async with core_db.async_session() as sweeper:
                await sweeper.execute(
                    update(IngestJob)
                    .where(IngestJob.id == job.id)
                    .values(
                        status="failed",
                        error_message="Stale: heartbeat lease expired",
                    )
                )
                await sweeper.commit()
            raise RuntimeError("boom after supersession")

        with patch.object(ingest_service, "register_existing_table", sweeping_register):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="centroid",
                title=f"Superseded fail {uuid.uuid4().hex[:6]}",
            )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.error_message == "Stale: heartbeat lease expired"
        assert job.dataset_id is None
        assert out_tables, "materialize never reached registration"
        # fix(v1.6.0 audit B13): the sweep never registered a dataset for the
        # table, so the fence-missed failure path drops it as an orphan.
        left = (
            await test_db_session.execute(
                text("SELECT to_regclass(:ref)").bindparams(
                    ref=f'data."{out_tables[0]}"'
                )
            )
        ).scalar_one()
        assert left is None

    async def test_fence_missed_failure_keeps_adopted_table(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(v1.6.0 audit B13): the other side of the adoption probe — a
        final commit that reached the server before the connection dropped
        leaves the row 'complete' with a registered dataset. The late
        _mark_job_failed fence-misses AND finds the adopting dataset row, so
        it must leave the table (a live dataset's storage) alone."""
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(f"CREATE TABLE data.{table_name} (gid SERIAL PRIMARY KEY)")
        )
        await test_db_session.commit()
        await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
        )
        job = await _create_job(test_db_session, admin_id)
        job.status = "complete"
        await test_db_session.commit()
        assert job.attempt_id is not None

        async with core_db.async_session() as session:
            await _mark_job_failed(
                session,
                job_id=str(job.id),
                attempt_id=job.attempt_id,
                exc=RuntimeError("late failure after commit"),
                schema="data",
                out_table=table_name,
                operation="centroid",
            )

        await test_db_session.refresh(job)
        assert job.status == "complete"
        left = (
            await test_db_session.execute(
                text("SELECT to_regclass(:ref)").bindparams(ref=f"data.{table_name}")
            )
        ).scalar_one()
        assert left is not None

    async def test_name_collision_warning_is_surfaced(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#786): the rename generate_table_name reports on a collision
        was discarded — the upload path persists it to
        user_metadata['collision_warning'], which the job-status endpoint
        surfaces as warning_message, so an analysis output landing in e.g.
        parcels_buffered_3 said nothing to the user."""
        from app.processing.ingest.service import generate_table_name

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        title = f"Warned {uuid.uuid4().hex[:6]}"
        taken, _ = await generate_table_name(title, test_db_session)
        await test_db_session.execute(
            text(f'CREATE TABLE data."{taken}" (marker integer)')
        )
        await test_db_session.commit()

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="centroid",
            title=title,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message
        warning = (job.user_metadata or {}).get("collision_warning")
        assert warning is not None
        assert f"{taken}_2" in warning

    async def test_cleanup_rows_do_not_count_toward_size_cap(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#786): NULL/EMPTY-geometry rows are excluded in the CTAS
        itself — a DELETE cannot shrink pg_total_relation_size (dead tuples
        keep their pages until a rewrite), so the early ceiling probe used
        to measure rows the cleanup removes and could fail a small analysis
        as oversized. Same shape as the clip-by-layer case from the #719
        review, extended to the render_geometry_expr operations."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        # 2,025 NULL-geometry decoys: centroid maps them to NULL and the
        # cleanup removes them, but before the in-CTAS filter they inflated
        # the measured relation well past the 64 KB ceiling below, while
        # the 2 real centroids fit comfortably.
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{ds.table_name} (name) "  # noqa: S608
                f"SELECT 'decoy' FROM generate_series(1, 2025)"
            )
        )
        await test_db_session.commit()
        job = await _create_job(test_db_session, admin_id)

        with patch("app.processing.analysis.tasks.MAX_OUTPUT_BYTES", 65536):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="centroid",
                title=f"Centroids {uuid.uuid4().hex[:6]}",
            )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        kept = await test_db_session.scalar(
            text(f"SELECT COUNT(*) FROM data.{new_ds.table_name}")  # noqa: S608
        )
        assert kept == 2

    async def test_worker_cancellation_fails_job_and_reraises(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#692): graceful worker shutdown cancels the task mid-CTAS. The
        job must fail immediately with a comprehensible message — not strand
        in 'running' holding the slot until the 60-minute sweep — and the
        CancelledError must propagate so the queue records the abort."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        slow_sql = (
            "SELECT 1 AS gid, "
            "(SELECT ST_GeomFromText('POINT(0 0)', 4326) FROM pg_sleep(30)) AS geom"
        )
        with patch(
            "app.processing.analysis.tasks._build_materialize_select",
            return_value=slow_sql,
        ):
            run = asyncio.create_task(
                _materialize(
                    job_id=str(job.id),
                    dataset_id=str(ds.id),
                    user_id=str(admin_id),
                    operation="centroid",
                    title="Cancelled",
                )
            )
            # Cancel only once the worker owns the row (claim committed), so
            # the cancellation lands inside the guarded body, then give the
            # CTAS a beat to start.
            for _ in range(100):
                await asyncio.sleep(0.1)
                await test_db_session.refresh(job)
                if job.status == "running":
                    break
            assert job.status == "running"
            await asyncio.sleep(0.3)
            run.cancel()
            with pytest.raises(asyncio.CancelledError):
                await run

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "worker shut down" in (job.error_message or "")

    async def test_cancel_cleanup_releases_working_sessions_row_lock(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#700 review): a cancel can land while the working session's
        open transaction still holds the job-row lock (e.g. mid-commit,
        after flush). The cleanup must roll that session back before its
        fenced update, or it blocks on its own lock until the shield
        timeout and the row strands in 'running' after all."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, admin_id)
        job.status = "running"
        await test_db_session.commit()

        # Late-bound attribute access: conftest repoints app.core.db's
        # session maker at the per-run test DB after import time.
        async with core_db.async_session() as working_session:
            # Uncommitted UPDATE → this transaction holds the row lock,
            # exactly as a cancel landing mid-commit would leave it.
            await working_session.execute(
                update(IngestJob)
                .where(IngestJob.id == job.id)
                .values(current_step="registering")
            )
            await asyncio.wait_for(
                _fail_cancelled_job(
                    working_session,
                    job_id=str(job.id),
                    attempt_id=job.attempt_id,
                    schema="data",
                    out_table=None,
                    operation="centroid",
                ),
                timeout=10,
            )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "worker shut down" in (job.error_message or "")

    async def test_dissolve_materialize_single_feature(
        self,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        title = f"Dissolved {uuid.uuid4().hex[:6]}"

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="dissolve",
            title=title,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        assert new_ds.feature_count == 1

    async def test_missing_source_marks_job_failed(
        self,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(uuid.uuid4()),
            user_id=str(admin_id),
            operation="centroid",
            title="Ghost",
        )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.error_message
        # fix(v1.6.0 audit B12): the failure path stamps completed_at too.
        assert job.completed_at is not None

    async def test_result_dataset_is_private_and_owned_by_requester(
        self,
        test_db_session: AsyncSession,
    ):
        """The single highest-risk invariant: analysis outputs must register
        as private datasets owned by the requesting user — a regression here
        silently exposes derived copies of source data."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="centroid",
            title=f"Owned {uuid.uuid4().hex[:6]}",
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset, Record

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        # Visibility and ownership both live on the catalog Record.
        record = await test_db_session.get(Record, new_ds.record_id)
        assert record is not None
        assert record.visibility == "private"
        assert record.created_by == admin_id

    async def test_clip_materialize_creates_dataset(
        self,
        test_db_session: AsyncSession,
    ):
        """End-to-end clip: mask renders into the CTAS, only intersecting rows
        survive, attributes carry, and the output geometry stays polygonal."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        mask = {
            "type": "Polygon",
            "coordinates": [
                [[-0.5, -0.5], [-0.5, 0.5], [0.5, 0.5], [0.5, -0.5], [-0.5, -0.5]]
            ],
        }

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title=f"Clipped {uuid.uuid4().hex[:6]}",
            mask=mask,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        assert new_ds.feature_count == 1
        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT name, GeometryType(geom_4326) FROM data.{new_ds.table_name}"  # noqa: S608
                )
            )
        ).all()
        assert rows == [("a", "POLYGON")]

    async def test_dissolve_by_field_groups(
        self,
        test_db_session: AsyncSession,
    ):
        """Grouped dissolve: one row per group key, source_count populated,
        gid numbered — the only branch that interpolates a user column."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="dissolve",
            title=f"Dissolved by name {uuid.uuid4().hex[:6]}",
            by_field="name",
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT gid, name, source_count, GeometryType(geom_4326) "  # noqa: S608
                    f"FROM data.{new_ds.table_name} ORDER BY name"
                )
            )
        ).all()
        assert rows == [
            (1, "a", 1, "MULTIPOLYGON"),
            (2, "b", 1, "MULTIPOLYGON"),
        ] or rows == [
            (2, "a", 1, "MULTIPOLYGON"),
            (1, "b", 1, "MULTIPOLYGON"),
        ]

    async def test_empty_result_fails_job(
        self,
        test_db_session: AsyncSession,
    ):
        """A clip matching nothing must fail loud, not register a junk dataset."""
        from app.processing.analysis.tasks import ANALYSIS_JOBS

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        far_mask = {
            "type": "Polygon",
            "coordinates": [[[50, 50], [51, 50], [51, 51], [50, 51], [50, 50]]],
        }
        failed_before = ANALYSIS_JOBS.labels(
            operation="clip", status="failed"
        )._value.get()

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title="Empty Clip",
            mask=far_mask,
        )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "no features" in (job.error_message or "")
        assert job.dataset_id is None
        assert (
            ANALYSIS_JOBS.labels(operation="clip", status="failed")._value.get()
            == failed_before + 1
        )

    async def test_name_collision_preserves_existing_table(
        self,
        test_db_session: AsyncSession,
    ):
        """When CREATE TABLE loses a name race, cleanup must not drop the
        winner's table — only a table this job actually created.

        fix(#692): generate_table_name now sidesteps live relations, so the
        lost race is simulated by pinning the generated name to the occupied
        one — exactly what happens when two jobs draw the same name in the
        window between generation and CREATE."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        title = f"Collide {uuid.uuid4().hex[:6]}"
        expected = f"collide_{uuid.uuid4().hex[:6]}"
        await test_db_session.execute(
            text(f'CREATE TABLE data."{expected}" (marker integer)')
        )
        await test_db_session.commit()

        with patch(
            "app.processing.ingest.service.generate_table_name",
            AsyncMock(return_value=(expected, None)),
        ):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="centroid",
                title=title,
            )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        survived = (
            await test_db_session.execute(
                text("SELECT to_regclass(:ref)").bindparams(ref=f'data."{expected}"')
            )
        ).scalar_one()
        assert survived is not None
        # And it is still the pre-existing table, not a half-built output.
        cols = (
            (
                await test_db_session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'data' AND table_name = :t"
                    ).bindparams(t=expected)
                )
            )
            .scalars()
            .all()
        )
        assert cols == ["marker"]

    async def test_orphan_physical_table_self_heals_to_suffix(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#692): a table committed without a catalog row (worker killed
        during registration) used to poison its title forever — the name
        generator collided only against the catalog, so every retry died on
        CREATE TABLE. It now probes information_schema too: the retry lands
        on a _2 suffix and the orphan is left untouched for an operator."""
        from app.processing.ingest.service import generate_table_name

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        title = f"Orphaned {uuid.uuid4().hex[:6]}"
        orphan, _ = await generate_table_name(title, test_db_session)
        await test_db_session.execute(
            text(f'CREATE TABLE data."{orphan}" (marker integer)')
        )
        await test_db_session.commit()

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="centroid",
            title=title,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds.table_name == f"{orphan}_2"
        cols = (
            (
                await test_db_session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'data' AND table_name = :t"
                    ).bindparams(t=orphan)
                )
            )
            .scalars()
            .all()
        )
        assert cols == ["marker"]

    async def test_clip_by_layer_materialize(
        self,
        test_db_session: AsyncSession,
    ):
        """Worker resolves the mask dataset's table and clips against its
        unioned geometries — same output as an equivalent drawn mask."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((-0.5 -0.5, -0.5 0.5, 0.5 0.5, 0.5 -0.5, -0.5 -0.5))",
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title=f"Layer clipped {uuid.uuid4().hex[:6]}",
            mask_dataset_id=str(mask_ds.id),
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT name, GeometryType(geom_4326) FROM data.{new_ds.table_name}"  # noqa: S608
                )
            )
        ).all()
        assert rows == [("a", "POLYGON")]

    async def test_clip_by_layer_multirow_mask_equals_union_clip(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#719): the subdivided join must equal clipping against the
        whole-layer union it replaced.

        The old materialize shape unioned the mask layer into one geometry and
        intersected every source row against it. This one subdivides the mask
        and unions the per-piece intersections instead — 33.2s -> 3.4s on a
        972-polygon mask over 22k source rows. Intersection distributes over
        union so the two are equal in theory; this pins it in practice, on a
        MULTI-row overlapping mask where the distinction actually bites (a
        single-row mask subdivides to pieces that trivially reassemble).
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        mask_wkts = (
            "POLYGON((-0.5 -0.5, -0.5 0.5, 0.5 0.5, 0.5 -0.5, -0.5 -0.5))",
            "POLYGON((0.25 0.25, 0.25 1.5, 1.5 1.5, 1.5 0.25, 0.25 0.25))",
            "POLYGON((0.4 -0.2, 0.4 0.3, 0.9 0.3, 0.9 -0.2, 0.4 -0.2))",
        )
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt=mask_wkts[0],
            extra_wkts=mask_wkts[1:],
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title=f"Multirow clip {uuid.uuid4().hex[:6]}",
            mask_dataset_id=str(mask_ds.id),
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None

        # Ground truth: clip against the unioned mask, the pre-#719 semantics.
        union_wkt = ", ".join(f"ST_GeomFromText('{w}', 4326)" for w in mask_wkts)
        n_got, n_want, symdiff = (
            await test_db_session.execute(
                text(
                    f"WITH truth AS ("  # noqa: S608
                    f"  SELECT ST_CollectionExtract("
                    f"    ST_Intersection(ST_MakeValid(s.geom_4326),"
                    f"      ST_Union(ARRAY[{union_wkt}])),"
                    f"    ST_Dimension(s.geom_4326) + 1) AS geom"
                    f"  FROM data.{ds.table_name} AS s"
                    f"), want AS ("
                    f"  SELECT geom FROM truth"
                    f"  WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom)"
                    f"), got AS (SELECT geom_4326 AS geom FROM data.{new_ds.table_name})"
                    f" SELECT (SELECT count(*) FROM got),"
                    f"        (SELECT count(*) FROM want),"
                    f"        ST_Area(ST_SymDifference("
                    f"          (SELECT ST_Union(geom) FROM got),"
                    f"          (SELECT ST_Union(geom) FROM want)))"
                )
            )
        ).one()
        # Guard against a vacuous pass: 0 == 0 with a NULL symdiff would
        # otherwise satisfy both assertions below.
        assert n_got > 0, "clip produced nothing — the fixture no longer overlaps"
        assert n_got == n_want, (
            f"subdivided clip produced {n_got} rows, union clip {n_want}"
        )
        assert symdiff < 1e-12, (
            f"subdivided clip diverged from the whole-layer union it replaced "
            f"(symmetric-difference area {symdiff})"
        )

    async def test_clip_by_layer_does_not_fragment_a_line_at_mask_seams(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#719 review): ST_Union does not sew line segments.

        The subdivided join intersects per mask piece and unions the results.
        For polygons that reassembles exactly, but a LineString crossing a
        seam between two touching mask polygons came back as an artificially
        fragmented MultiLineString where the old whole-mask intersection
        returned one continuous LineString — which changes the geometry type
        the new dataset is registered with. ST_LineMerge on single-part
        LineString sources restores it; a line with a REAL gap must stay
        multi-part.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} ("
                f"  gid SERIAL PRIMARY KEY,"
                f"  geom geometry(LineString, 4326),"
                f"  geom_4326 geometry(LineString, 4326))"
            )
        )
        # gid 1 crosses the seam between the two touching mask polygons;
        # gid 2 spans the real gap before the third, detached mask polygon.
        for wkt in ("LINESTRING(1 5, 9 5)", "LINESTRING(1 6, 24 6)"):
            await test_db_session.execute(
                text(
                    f"INSERT INTO data.{table_name} (geom, geom_4326) VALUES "  # noqa: S608
                    f"(ST_GeomFromText('{wkt}', 4326),"
                    f" ST_GeomFromText('{wkt}', 4326))"
                )
            )
        await test_db_session.commit()
        from tests.factories import create_dataset

        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
            geometry_type="LINESTRING",
            feature_count=2,
        )
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((0 0, 0 10, 5 10, 5 0, 0 0))",
            extra_wkts=(
                "POLYGON((5 0, 5 10, 10 10, 10 0, 5 0))",
                "POLYGON((20 0, 20 10, 25 10, 25 0, 20 0))",
            ),
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title=f"Clipped lines {uuid.uuid4().hex[:6]}",
            mask_dataset_id=str(mask_ds.id),
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT GeometryType(geom_4326), ST_NumGeometries(geom_4326) "  # noqa: S608
                    f"FROM data.{new_ds.table_name} ORDER BY gid"
                )
            )
        ).all()
        assert rows == [("LINESTRING", 1), ("MULTILINESTRING", 2)], rows

    async def test_clip_by_layer_keeps_touching_multiline_parts_separate(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#719 review): seam repair must not merge REAL components.

        The seam fix above keys on ``GeometryType(...) = 'LINESTRING'``, not
        ``ST_Dimension(...) = 1``. A MultiLineString whose components merely
        touch at an endpoint is dimension 1 too, so a dimension test sews
        those genuine components into one LineString — a change the mask never
        asked for, and one the whole-mask intersection does not make. Measured
        against the old shape: MULTILINESTRING/2 parts, both before and after.

        Both components sit well inside a single mask polygon, so the mask
        introduces no seam here at all; anything but a passthrough is wrong.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} ("
                f"  gid SERIAL PRIMARY KEY,"
                f"  geom geometry(MultiLineString, 4326),"
                f"  geom_4326 geometry(MultiLineString, 4326))"
            )
        )
        wkt = "MULTILINESTRING((1 2, 4 2), (4 2, 4 8))"
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326) VALUES "  # noqa: S608
                f"(ST_GeomFromText('{wkt}', 4326),"
                f" ST_GeomFromText('{wkt}', 4326))"
            )
        )
        await test_db_session.commit()
        from tests.factories import create_dataset

        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
            geometry_type="MULTILINESTRING",
            feature_count=1,
        )
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((0 0, 0 10, 5 10, 5 0, 0 0))",
            extra_wkts=("POLYGON((5 0, 5 10, 10 10, 10 0, 5 0))",),
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title=f"Clipped multilines {uuid.uuid4().hex[:6]}",
            mask_dataset_id=str(mask_ds.id),
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT GeometryType(geom_4326), ST_NumGeometries(geom_4326) "  # noqa: S608
                    f"FROM data.{new_ds.table_name} ORDER BY gid"
                )
            )
        ).all()
        assert rows == [("MULTILINESTRING", 2)], rows

    async def test_clip_by_layer_bbox_only_rows_do_not_count_toward_size_cap(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#719 review): NULL rows must not be measured as output.

        The row filter admits a source row on a bounding-box overlap, so a
        concave mask lets through rows that never actually intersect it; their
        lateral aggregates over zero pieces and yields geom_out = NULL.
        ``_enforce_output_size`` runs against the CTAS BEFORE the NULL/EMPTY
        cleanup, so those rows used to count toward the ceiling — and clip has
        no source-feature cap bounding how many of them there are.

        The mask is the lower-right triangle of a 0..40 box (hypotenuse along
        y = x), so its bbox covers the whole box while its interior is only
        y < x. Every decoy sits just above the hypotenuse: inside the bbox,
        outside the polygon. Measured sizes for this shape — 1 row = 16 KB,
        2025 rows = 270 KB — so the ceiling below passes the real feature and
        fails the decoys by 4x.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} ("
                f"  gid SERIAL PRIMARY KEY,"
                f"  geom geometry(Point, 4326),"
                f"  geom_4326 geometry(Point, 4326))"
            )
        )
        # 2025 decoys clustered just above the hypotenuse near (1, 39):
        # inside the mask's bbox, outside the triangle.
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326) "  # noqa: S608
                f"SELECT ST_SetSRID(ST_MakePoint(1 + x * 0.001, 39 - y * 0.001), 4326),"
                f"       ST_SetSRID(ST_MakePoint(1 + x * 0.001, 39 - y * 0.001), 4326)"
                f"  FROM generate_series(1, 45) AS x,"
                f"       generate_series(1, 45) AS y"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326) VALUES "  # noqa: S608
                f"(ST_SetSRID(ST_MakePoint(30, 5), 4326),"
                f" ST_SetSRID(ST_MakePoint(30, 5), 4326))"
            )
        )
        await test_db_session.commit()
        from tests.factories import create_dataset

        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
            geometry_type="POINT",
            feature_count=2026,
        )
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((0 0, 40 0, 40 40, 0 0))",
        )
        job = await _create_job(test_db_session, admin_id)

        # 64 KB of headroom: the single real feature (16 KB) fits, the 2025
        # bbox-only rows (270 KB) do not.
        with patch("app.processing.analysis.tasks.MAX_OUTPUT_BYTES", 65536):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="clip",
                title=f"Clipped points {uuid.uuid4().hex[:6]}",
                mask_dataset_id=str(mask_ds.id),
            )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        kept = await test_db_session.scalar(
            text(f"SELECT COUNT(*) FROM data.{new_ds.table_name}")  # noqa: S608
        )
        assert kept == 1, kept

    async def test_clip_by_layer_survives_a_geom_out_attribute_column(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#719 review): "geom_out" is a legal attribute name.

        The CTAS selects the carry columns from _src alongside the lateral's
        own geom_out, so an unqualified predicate is rejected outright:
        `column reference "geom_out" is ambiguous`. The whole-mask shape this
        PR replaced had no lateral and so no collision, making this a
        regression on datasets that happen to use the name.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} ("
                f"  gid SERIAL PRIMARY KEY,"
                f'  "geom_out" TEXT,'
                f"  geom geometry(Polygon, 4326),"
                f"  geom_4326 geometry(Polygon, 4326))"
            )
        )
        wkt = "POLYGON((1 1, 4 1, 4 4, 1 4, 1 1))"
        await test_db_session.execute(
            text(
                f'INSERT INTO data.{table_name} ("geom_out", geom, geom_4326)'  # noqa: S608
                f" VALUES ('an ordinary attribute',"
                f" ST_GeomFromText('{wkt}', 4326),"
                f" ST_GeomFromText('{wkt}', 4326))"
            )
        )
        await test_db_session.commit()
        from tests.factories import create_dataset

        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
            geometry_type="POLYGON",
            feature_count=1,
        )
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((0 0, 0 10, 5 10, 5 0, 0 0))",
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title=f"Clipped with attr {uuid.uuid4().hex[:6]}",
            mask_dataset_id=str(mask_ds.id),
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

    async def test_clip_by_layer_missing_mask_fails_job(
        self,
        test_db_session: AsyncSession,
    ):
        """A mask dataset deleted between enqueue and run fails cleanly."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title="Ghost mask",
            mask_dataset_id=str(uuid.uuid4()),
        )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "Mask dataset not found" in (job.error_message or "")

    async def test_analyze_and_registration_timeout_between_phases(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#692): the output table is ANALYZEd before the mid-task commit
        (tile queries land before autovacuum's pass), and registration gets a
        fresh statement_timeout (SET LOCAL died with that commit). Pin both
        by inspecting the statements the worker actually ran."""
        executed: list[str] = []
        from sqlalchemy.ext.asyncio import AsyncSession as _AS

        real_execute = _AS.execute

        async def spying_execute(self, statement, *args, **kwargs):
            executed.append(str(statement))
            return await real_execute(self, statement, *args, **kwargs)

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        with patch.object(_AS, "execute", spying_execute):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="centroid",
                title=f"Spied {uuid.uuid4().hex[:6]}",
            )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message
        analyzes = [s for s in executed if s.startswith("ANALYZE ")]
        assert len(analyzes) == 1
        timeouts = [s for s in executed if "SET LOCAL statement_timeout" in s]
        # One budget for the build transaction, one re-armed for registration.
        assert len(timeouts) == 2
        # The registration budget is set after the ANALYZE (i.e. in the new
        # transaction), not before.
        assert executed.index(timeouts[1]) > executed.index(analyzes[0])
        # Only dissolve flips the aggregation strategy (fix(#694)).
        assert not [s for s in executed if "enable_hashagg" in s]
        # fix(#701 review): the size ceiling is probed twice — a cheap early
        # exit after the CTAS, and the authoritative check on the finished
        # relation (post-4326-rewrite, so heap + TOAST + GIST all count),
        # which must land before the ANALYZE that precedes the commit.
        # Positions, not values: both probes stringify identically, so
        # list.index() would find the first one twice.
        size_pos = [i for i, s in enumerate(executed) if "pg_total_relation_size" in s]
        assert len(size_pos) == 2
        rewrite_pos = max(
            i for i, s in enumerate(executed) if "geom_4326" in s and "UPDATE" in s
        )
        assert size_pos[1] > rewrite_pos
        assert size_pos[1] < executed.index(analyzes[0])

    async def test_dissolve_ctas_disables_hashagg(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#694): hash aggregation holds every group's union state in
        memory simultaneously; the dissolve CTAS transaction must switch to
        sorted aggregation, which bounds memory to one group at a time."""
        executed: list[str] = []
        from sqlalchemy.ext.asyncio import AsyncSession as _AS

        real_execute = _AS.execute

        async def spying_execute(self, statement, *args, **kwargs):
            executed.append(str(statement))
            return await real_execute(self, statement, *args, **kwargs)

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        with patch.object(_AS, "execute", spying_execute):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="dissolve",
                title=f"Hashagg {uuid.uuid4().hex[:6]}",
            )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message
        hashaggs = [s for s in executed if "enable_hashagg" in s]
        assert len(hashaggs) == 1
        ctas = [s for s in executed if s.startswith("CREATE TABLE")]
        # Same transaction, ahead of the CTAS it protects.
        assert executed.index(hashaggs[0]) < executed.index(ctas[0])

    async def test_worker_rechecks_size_caps_before_ctas(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#701 review): the enqueue gate's count can go stale while the
        job waits in the queue (a source or mask can be re-uploaded past its
        cap), and the post-CTAS size check is too late to protect the
        dissolve/mask union itself from OOM — the worker re-counts the live
        tables immediately before building the SQL."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)

        # Source recheck: the fixture table holds 2 rows; cap 1 must fail
        # the job before any output table exists.
        job = await _create_job(test_db_session, admin_id)
        with patch.dict(
            "app.platform.analysis_sql.MAX_SOURCE_FEATURES", {"dissolve": 1}
        ):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="dissolve",
                title="Grew past the cap",
            )
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "too large for dissolve" in (job.error_message or "")
        assert job.dataset_id is None

        # Mask recheck: the 1-row mask table against a cap of 0.
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((-0.5 -0.5, -0.5 0.5, 0.5 0.5, 0.5 -0.5, -0.5 -0.5))",
        )
        job2 = await _create_job(test_db_session, admin_id)
        with patch("app.processing.analysis.tasks.MAX_MASK_LAYER_FEATURES", 0):
            await _materialize(
                job_id=str(job2.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="clip",
                title="Mask grew past the cap",
                mask_dataset_id=str(mask_ds.id),
            )
        await test_db_session.refresh(job2)
        assert job2.status == "failed"
        assert "mask layer has too many features" in (job2.error_message or "")
        assert job2.dataset_id is None

    async def test_oversized_output_fails_before_registration(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#694): the enqueue gates read a cached feature_count snapshot;
        the post-CTAS pg_total_relation_size backstop is the enforcement that
        can't go stale. The job fails with an actionable message, no dataset
        is registered, and the cleanup path drops the built table."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        with patch("app.processing.analysis.tasks.MAX_OUTPUT_BYTES", 1):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="buffer",
                title=f"Oversized {uuid.uuid4().hex[:6]}",
                distance_meters=10.0,
            )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "size limit" in (job.error_message or "")
        assert job.dataset_id is None

    async def test_oversized_message_advice_matches_operation(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(v1.6.0 audit D11): only buffer has a distance to reduce —
        clip/centroid/dissolve users must not be told to shrink a buffer
        they never set."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)

        with patch("app.processing.analysis.tasks.MAX_OUTPUT_BYTES", 1):
            with pytest.raises(ValueError) as clip_exc:
                await _enforce_output_size(
                    test_db_session, "data", ds.table_name, operation="clip"
                )
            with pytest.raises(ValueError) as buffer_exc:
                await _enforce_output_size(
                    test_db_session, "data", ds.table_name, operation="buffer"
                )
        assert "buffer" not in str(clip_exc.value)
        assert "smaller dataset" in str(clip_exc.value)
        assert "buffer distance" in str(buffer_exc.value)

    async def test_mixed_geometry_dissolve_stays_typed(
        self,
        test_db_session: AsyncSession,
    ):
        """A union over mixed types must not register a GEOMETRYCOLLECTION —
        only the highest-dimension components survive."""
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} ("
                f"  gid SERIAL PRIMARY KEY,"
                f"  geom geometry(Geometry, 4326),"
                f"  geom_4326 geometry(Geometry, 4326)"
                f")"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326) VALUES "
                f"(ST_GeomFromText('POINT(5 5)', 4326),"
                f" ST_GeomFromText('POINT(5 5)', 4326)),"
                f"(ST_GeomFromText('POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))', 4326),"
                f" ST_GeomFromText('POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))', 4326))"
            )
        )
        await test_db_session.commit()
        from tests.factories import create_dataset

        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
            geometry_type="GEOMETRY",
            feature_count=2,
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="dissolve",
            title=f"Mixed dissolve {uuid.uuid4().hex[:6]}",
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        geom_type = (
            await test_db_session.execute(
                text(
                    f"SELECT GeometryType(geom_4326) FROM data.{new_ds.table_name}"  # noqa: S608
                )
            )
        ).scalar_one()
        assert geom_type == "MULTIPOLYGON"


# ---------------------------------------------------------------------------
# Error-message sanitization (pure, no DB)
# ---------------------------------------------------------------------------


class TestUserErrorMessage:
    def test_db_error_hides_generated_sql(self):
        """fix(#692): SQLAlchemy appends `[SQL: …]` to DB errors — schema and
        table names must never reach GET /jobs/{id}."""
        from sqlalchemy.exc import ProgrammingError

        exc = ProgrammingError(
            'CREATE TABLE "data"."secret_output" AS SELECT 1', {}, Exception("boom")
        )
        msg = _user_error_message(exc)
        assert "secret_output" not in msg
        assert "CREATE TABLE" not in msg

    def test_sqlstate_42_is_named_a_column_problem(self):
        """fix(#766): SQLSTATE class 42 (e.g. no equality operator for
        `json` in a dissolve GROUP BY) is a parameter problem, not a
        generic database error — say so, without leaking the SQL."""
        from sqlalchemy.exc import ProgrammingError

        orig = Exception("could not identify an equality operator for type json")
        orig.sqlstate = "42883"
        exc = ProgrammingError(
            'CREATE TABLE "data"."secret_output" AS SELECT 1', {}, orig
        )
        msg = _user_error_message(exc)
        assert "column" in msg.lower()
        assert "secret_output" not in msg
        assert "CREATE TABLE" not in msg

    def test_other_class_42_states_stay_generic(self):
        """codex(#791): 42501 (privilege), 42P01 (missing table) and the
        like are server/configuration faults — mapping them onto "choose a
        different column" would bury the actionable failure."""
        from sqlalchemy.exc import ProgrammingError

        for sqlstate in ("42501", "42P01", "42601"):
            orig = Exception("boom")
            orig.sqlstate = sqlstate
            exc = ProgrammingError("CREATE TABLE x AS SELECT 1", {}, orig)
            assert _user_error_message(exc) == (
                "The analysis failed due to a database error"
            ), sqlstate

    def test_statement_timeout_is_actionable(self):
        from sqlalchemy.exc import OperationalError

        exc = OperationalError(
            'CREATE TABLE "data"."big_output" AS SELECT 1',
            {},
            Exception("canceling statement due to statement timeout"),
        )
        msg = _user_error_message(exc)
        assert "time limit" in msg
        # fix(v1.6.0 audit D11): the message names the configured limit.
        assert MATERIALIZE_TIMEOUT in msg
        assert "big_output" not in msg

    def test_domain_errors_pass_through(self):
        msg = _user_error_message(ValueError("Analysis produced no features to save"))
        assert "no features" in msg
