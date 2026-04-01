"""Integration tests for job status, retry, and stale cleanup endpoints."""

import uuid
from datetime import datetime, timedelta, timezone

from typing import TYPE_CHECKING

from httpx import AsyncClient
from sqlalchemy import select, text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.jobs.models import IngestJob


async def _get_user_id(session: "AsyncSession", username: str) -> uuid.UUID:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one().id


async def _create_job(
    session: "AsyncSession",
    *,
    created_by: uuid.UUID,
    status: str = "pending",
    source_filename: str = "test.geojson",
    file_path: str | None = None,
    source_url: str | None = None,
    error_message: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> IngestJob:
    """Insert an IngestJob directly for testing."""
    job = IngestJob(
        status=status,
        created_by=created_by,
        source_filename=source_filename,
        file_path=file_path,
        source_url=source_url,
        error_message=error_message,
        started_at=started_at,
        completed_at=completed_at,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


# ---------------------------------------------------------------------------
# Get job status
# ---------------------------------------------------------------------------


class TestGetJobStatus:
    async def test_get_job_status_as_creator(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET /jobs/{id} as job creator returns 200 with job details."""
        admin_id = await _get_user_id(test_db_session, "admin")
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            status="complete",
        )

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(job.id)
        assert data["status"] == "complete"
        assert data["source_filename"] == "test.geojson"

    async def test_get_job_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /jobs/{random_uuid} returns 404."""
        resp = await client.get(f"/jobs/{uuid.uuid4()}", headers=admin_auth_header)
        assert resp.status_code == 404

    async def test_get_job_unauthenticated(self, client: AsyncClient):
        """GET /jobs/{id} without auth returns 401."""
        resp = await client.get(f"/jobs/{uuid.uuid4()}")
        assert resp.status_code == 401

    async def test_get_job_other_user_forbidden(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        editor_auth_header: dict,
        test_db_session,
    ):
        """GET /jobs/{id} as non-creator non-admin returns 403."""
        admin_id = await _get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id)

        resp = await client.get(f"/jobs/{job.id}", headers=editor_auth_header)
        assert resp.status_code == 403

    async def test_get_job_auto_fails_stale_running(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET /jobs/{id} auto-fails a job running for >1 hour."""
        admin_id = await _get_user_id(test_db_session, "admin")
        stale_start = datetime.now(timezone.utc) - timedelta(hours=2)
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            status="running",
            started_at=stale_start,
        )

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        assert "Timed out" in resp.json()["error_message"]

    async def test_get_job_auto_fails_stale_pending(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET /jobs/{id} auto-fails a job pending for >1 hour."""
        admin_id = await _get_user_id(test_db_session, "admin")
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            status="pending",
        )
        # Backdate created_at to 2 hours ago
        await test_db_session.execute(
            text(
                "UPDATE catalog.ingest_jobs SET created_at = NOW() - INTERVAL '2 hours' "
                "WHERE id = :job_id"
            ),
            {"job_id": str(job.id)},
        )
        await test_db_session.commit()

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        assert "Stale" in resp.json()["error_message"]


# ---------------------------------------------------------------------------
# Retry job
# ---------------------------------------------------------------------------


class TestRetryJob:
    async def test_retry_not_found(self, client: AsyncClient, admin_auth_header: dict):
        """POST /jobs/{random_uuid}/retry returns 404."""
        resp = await client.post(
            f"/jobs/{uuid.uuid4()}/retry", headers=admin_auth_header
        )
        assert resp.status_code == 404

    async def test_retry_non_failed_job_rejected(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """POST /jobs/{id}/retry on a pending job returns 400."""
        admin_id = await _get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id, status="pending")

        resp = await client.post(f"/jobs/{job.id}/retry", headers=admin_auth_header)
        assert resp.status_code == 400
        assert "Only failed jobs" in resp.json()["detail"]

    async def test_retry_unauthenticated(self, client: AsyncClient):
        """POST /jobs/{id}/retry without auth returns 401."""
        resp = await client.post(f"/jobs/{uuid.uuid4()}/retry")
        assert resp.status_code == 401

    async def test_retry_viewer_forbidden(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """POST /jobs/{id}/retry as viewer returns 403."""
        resp = await client.post(
            f"/jobs/{uuid.uuid4()}/retry", headers=viewer_auth_header
        )
        assert resp.status_code == 403

    async def test_retry_failed_job_missing_file(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """POST /jobs/{id}/retry on failed job with missing staging file returns 400."""
        admin_id = await _get_user_id(test_db_session, "admin")
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            status="failed",
            file_path="/nonexistent/path/test.geojson",
            error_message="Original failure",
        )

        resp = await client.post(f"/jobs/{job.id}/retry", headers=admin_auth_header)
        assert resp.status_code == 400
        assert "Staging file" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Cleanup stale jobs
# ---------------------------------------------------------------------------


class TestCleanupStaleJobs:
    async def test_cleanup_requires_admin(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        """POST /jobs/cleanup/stale/ as editor returns 403."""
        resp = await client.post("/jobs/cleanup/stale/", headers=editor_auth_header)
        assert resp.status_code == 403

    async def test_cleanup_unauthenticated(self, client: AsyncClient):
        """POST /jobs/cleanup/stale/ without auth returns 401."""
        resp = await client.post("/jobs/cleanup/stale/")
        assert resp.status_code == 401

    async def test_cleanup_returns_counts(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /jobs/cleanup/stale/ returns cleanup counts."""
        resp = await client.post("/jobs/cleanup/stale/", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_cleaned" in data
        assert "pending_failed" in data
        assert "running_failed" in data
