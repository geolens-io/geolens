"""Integration tests for job status, retry, and stale cleanup endpoints."""

import uuid
from datetime import datetime, timedelta, timezone

from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs.models import IngestJob

from tests.factories import get_user_id


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
        admin_id = await get_user_id(test_db_session, "admin")
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

    async def test_get_job_status_fanned_out_returns_200(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET /jobs/{id} for a fanned_out parent returns 200 with status='fanned_out'.

        Regression for SMOKE-v1013-F1: JobStatusResponse.status Literal was missing
        'fanned_out' (the terminal status set by POST /ingest/commit-fan-out after
        N child tasks are dispatched), causing Pydantic ValidationError → HTTP 500
        on every poll. The DB CHECK constraint accepts 'fanned_out'; the API
        response model must too.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            status="fanned_out",
        )

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "fanned_out"
        assert data["id"] == str(job.id)

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
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id)

        resp = await client.get(f"/jobs/{job.id}", headers=editor_auth_header)
        assert resp.status_code == 403

    async def test_get_job_auto_fails_stale_running(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET /jobs/{id} auto-fails a job running for >1 hour."""
        admin_id = await get_user_id(test_db_session, "admin")
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
        admin_id = await get_user_id(test_db_session, "admin")
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

    async def test_get_job_default_warnings_empty(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """S3: clean jobs return empty warnings/archive_failed/temporal_parse_errors."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id, status="complete")

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["warnings"] == []
        assert data["archive_failed"] is False
        assert data["temporal_parse_errors"] == {}
        assert data["warning_message"] is None

    async def test_get_job_surfaces_reserved_rename_warnings(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """S3: structured reserved_rename warnings surface via JobStatusResponse."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id, status="complete")
        # Directly stamp user_metadata to simulate what _append_job_warning
        # writes at the end of ingest_file.
        job.user_metadata = {
            "title": "Cities",
            "warnings": [
                {
                    "kind": "reserved_rename",
                    "details": [
                        {"original": "geom", "renamed": "src_geom"},
                        {"original": "gid", "renamed": "src_gid"},
                    ],
                }
            ],
        }
        await test_db_session.commit()

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["warnings"]) == 1
        assert data["warnings"][0]["kind"] == "reserved_rename"
        renames = data["warnings"][0]["details"]
        originals = {r["original"] for r in renames}
        assert originals == {"geom", "gid"}

    async def test_get_job_surfaces_archive_failed(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """S3: archive_failed=True surfaces when storage put failed."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id, status="complete")
        job.user_metadata = {
            "archive_failed": True,
            "archive_error": "S3 unreachable after 3 retries",
        }
        await test_db_session.commit()

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        assert resp.json()["archive_failed"] is True

    async def test_get_job_surfaces_temporal_parse_errors(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """N5: unparseable temporal fields are surfaced to the client."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id, status="complete")
        job.user_metadata = {
            "temporal_parse_errors": {
                "temporal_start": "not-a-date",
                "temporal_end": "2024-13-99",
            }
        }
        await test_db_session.commit()

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        errors = resp.json()["temporal_parse_errors"]
        assert errors == {
            "temporal_start": "not-a-date",
            "temporal_end": "2024-13-99",
        }

    async def test_get_job_surfaces_legacy_collision_warning_message(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Legacy scalar warning_message still surfaces for table-name collisions."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id, status="complete")
        job.user_metadata = {
            "collision_warning": "Table 'cities' already exists, using 'cities_2'",
        }
        await test_db_session.commit()

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        assert "cities_2" in resp.json()["warning_message"]

    async def test_get_job_ignores_malformed_warnings(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Router must not crash when user_metadata contains unexpected shapes."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id, status="complete")
        # warnings is a scalar (wrong), temporal_parse_errors is a list (wrong).
        # Both should be ignored without raising.
        job.user_metadata = {
            "warnings": "not a list",
            "temporal_parse_errors": ["also", "wrong"],
            "archive_failed": "truthy-string",
        }
        await test_db_session.commit()

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["warnings"] == []  # malformed scalar dropped
        assert data["temporal_parse_errors"] == {}  # malformed list dropped
        assert data["archive_failed"] is True  # truthy coerces via bool()

    async def test_get_job_drops_unknown_warning_kind(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """TYPE-2: unknown warning ``kind`` values are dropped, not proxied.

        Regression for the contract-drift scenario: if a future task emits a
        warning kind the Pydantic union does not recognize, ``JobStatusResponse``
        must still serialize cleanly (with the unknown entry skipped) instead
        of 500ing the endpoint.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id, status="complete")
        job.user_metadata = {
            "warnings": [
                # Good entry — should surface.
                {
                    "kind": "reserved_rename",
                    "details": [{"original": "gid", "renamed": "src_gid"}],
                },
                # Unknown kind — should be dropped without error.
                {"kind": "future_kind_nobody_added_yet", "details": []},
                # Malformed entry (missing required field) — dropped too.
                {"kind": "reserved_rename"},
            ],
        }
        await test_db_session.commit()

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["warnings"]) == 1
        assert data["warnings"][0]["kind"] == "reserved_rename"
        assert data["warnings"][0]["details"] == [
            {"original": "gid", "renamed": "src_gid"}
        ]

    async def test_get_job_drops_unknown_temporal_parse_error_keys(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """TYPE-3: ``temporal_parse_errors`` keys are narrowed to the contract set.

        An upstream bug that emits ``temporal_created`` (unknown key) must not
        make the whole response fail Pydantic ``Literal`` validation — the
        router filters the dict before handing it to the schema.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id, status="complete")
        job.user_metadata = {
            "temporal_parse_errors": {
                "temporal_start": "bad-value",
                "temporal_end": "also-bad",
                "temporal_bogus": "should-be-dropped",
            }
        }
        await test_db_session.commit()

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        errors = resp.json()["temporal_parse_errors"]
        assert errors == {
            "temporal_start": "bad-value",
            "temporal_end": "also-bad",
        }
        assert "temporal_bogus" not in errors

    async def test_job_status_includes_progress_fields_default_none(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """REMED-02 / P2-07: new progress fields default to None when never written.

        Pre-existing jobs (or any job before workers populate the new columns)
        must continue to validate as JobStatusResponse — the three new fields
        are optional and default to None.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id, status="pending")

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "progress" in data and data["progress"] is None
        assert "current_step" in data and data["current_step"] is None
        assert "rows_processed" in data and data["rows_processed"] is None

    async def test_job_status_returns_written_progress_values(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """REMED-02 / P2-07: worker-written progress values surface via the API."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id, status="running")

        # Simulate a worker mid-flight progress write.
        await test_db_session.execute(
            text(
                "UPDATE catalog.ingest_jobs "
                "SET progress = 0.5, current_step = 'ogr2ogr', rows_processed = 1234 "
                "WHERE id = :job_id"
            ),
            {"job_id": str(job.id)},
        )
        await test_db_session.commit()

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["progress"] == 0.5
        assert data["current_step"] == "ogr2ogr"
        assert data["rows_processed"] == 1234


# ---------------------------------------------------------------------------
# REMED-02 / P2-07: Pydantic contract bounds for new progress fields
# ---------------------------------------------------------------------------


def test_job_status_response_rejects_out_of_range_progress():
    """REMED-02 / P2-07: ``progress`` field rejects values outside [0.0, 1.0]."""
    from pydantic import ValidationError

    from app.platform.jobs.schemas import JobStatusResponse

    base_kwargs = {
        "id": uuid.uuid4(),
        "status": "running",
        "dataset_id": None,
        "source_filename": "x.geojson",
        "error_message": None,
        "started_at": None,
        "completed_at": None,
        "created_at": datetime.now(timezone.utc),
    }

    # Happy path: in-range progress + valid current_step + non-negative rows.
    JobStatusResponse(
        **base_kwargs, progress=0.42, current_step="ogr2ogr", rows_processed=10000
    )

    # ge=0.0
    with pytest.raises(ValidationError):
        JobStatusResponse(**base_kwargs, progress=-0.1)

    # le=1.0
    with pytest.raises(ValidationError):
        JobStatusResponse(**base_kwargs, progress=1.5)

    # current_step Literal allowlist
    with pytest.raises(ValidationError):
        JobStatusResponse(**base_kwargs, current_step="bogus")

    # rows_processed ge=0
    with pytest.raises(ValidationError):
        JobStatusResponse(**base_kwargs, rows_processed=-1)


# ---------------------------------------------------------------------------
# S3: Get job status by dataset_id
# ---------------------------------------------------------------------------


class TestGetJobStatusByDataset:
    """S3 completion: look up ingest warnings by dataset_id.

    Powers the permanent warnings banner on the dataset detail page — the
    dataset doesn't store ingest warnings directly, so the UI fetches the
    most recent completed job for the dataset and renders any warnings
    attached to it.
    """

    async def test_returns_404_for_unknown_dataset(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        resp = await client.get(
            f"/jobs/by-dataset/{uuid.uuid4()}", headers=admin_auth_header
        )
        assert resp.status_code == 404

    async def test_returns_404_when_dataset_has_no_job(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Dataset registered from an existing table has no ingest job → 404."""
        from tests.factories import create_dataset

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
        )

        resp = await client.get(
            f"/jobs/by-dataset/{dataset.id}", headers=admin_auth_header
        )
        assert resp.status_code == 404

    async def test_returns_warnings_for_dataset_with_job(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Dataset with a completed job surfaces warnings via the new endpoint."""
        from tests.factories import create_dataset

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
        )

        job = await _create_job(test_db_session, created_by=admin_id, status="complete")
        job.dataset_id = dataset.id
        job.user_metadata = {
            "warnings": [
                {
                    "kind": "reserved_rename",
                    "details": [{"original": "gid", "renamed": "src_gid"}],
                }
            ],
            "archive_failed": True,
        }
        await test_db_session.commit()

        resp = await client.get(
            f"/jobs/by-dataset/{dataset.id}", headers=admin_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dataset_id"] == str(dataset.id)
        assert len(data["warnings"]) == 1
        assert data["warnings"][0]["kind"] == "reserved_rename"
        assert data["archive_failed"] is True

    async def test_returns_most_recent_job_when_multiple_exist(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Re-ingest / reupload can create multiple jobs for one dataset."""
        from tests.factories import create_dataset

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
        )

        older = await _create_job(
            test_db_session, created_by=admin_id, status="complete"
        )
        older.dataset_id = dataset.id
        older.user_metadata = {"stamp": "older"}
        await test_db_session.commit()

        newer = await _create_job(
            test_db_session, created_by=admin_id, status="complete"
        )
        newer.dataset_id = dataset.id
        newer.user_metadata = {"stamp": "newer"}
        # Ensure a distinct, later created_at so ORDER BY is deterministic.
        await test_db_session.execute(
            text(
                "UPDATE catalog.ingest_jobs "
                "SET created_at = NOW() + INTERVAL '1 second' "
                "WHERE id = :job_id"
            ),
            {"job_id": str(newer.id)},
        )
        await test_db_session.commit()

        resp = await client.get(
            f"/jobs/by-dataset/{dataset.id}", headers=admin_auth_header
        )
        assert resp.status_code == 200
        # id should match the newer job, not the older one.
        assert resp.json()["id"] == str(newer.id)

    async def test_404_when_dataset_not_visible_to_user(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Users who can't see the dataset cannot leak job existence via 403."""
        from tests.factories import create_dataset

        admin_id = await get_user_id(test_db_session, "admin")
        # Private dataset owned by admin — editor cannot see it.
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
        )
        job = await _create_job(test_db_session, created_by=admin_id, status="complete")
        job.dataset_id = dataset.id
        await test_db_session.commit()

        resp = await client.get(
            f"/jobs/by-dataset/{dataset.id}", headers=editor_auth_header
        )
        # Non-visible dataset should return 404, not 403 or 200.
        assert resp.status_code == 404

    async def test_unauthenticated_rejected(self, client: AsyncClient):
        resp = await client.get(f"/jobs/by-dataset/{uuid.uuid4()}")
        assert resp.status_code == 401


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
        admin_id = await get_user_id(test_db_session, "admin")
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
        admin_id = await get_user_id(test_db_session, "admin")
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
