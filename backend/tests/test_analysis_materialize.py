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
from tests.test_analysis_preview import _create_polygon_dataset


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
