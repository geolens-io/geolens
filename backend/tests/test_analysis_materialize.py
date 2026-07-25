"""Tests for async analysis materialization (M4).

Covers the materialize endpoint (job creation, auth, validation) and the
worker's core logic (`_materialize`) run directly against the test DB.

Requirements:
  - Docker database must be running (docker compose up db)
"""

import uuid
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.api import router_analysis
from app.platform.jobs.models import IngestJob
from app.processing.analysis.tasks import _materialize

from tests.factories import get_user_id
from tests.test_analysis_preview import _create_mask_dataset, _create_polygon_dataset


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
        viewer_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "centroid", "title": "Nope"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 404

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
        winner's table — only a table this job actually created."""
        from app.processing.ingest.service import generate_table_name

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        title = f"Collide {uuid.uuid4().hex[:6]}"
        # generate_table_name checks only the catalog, so pre-creating the
        # physical table simulates the concurrent winner.
        expected, _ = await generate_table_name(title, test_db_session)
        await test_db_session.execute(
            text(f'CREATE TABLE data."{expected}" (marker integer)')
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
