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
    heartbeat_at: datetime | None = None,
    completed_at: datetime | None = None,
    user_metadata: dict | None = None,
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
        heartbeat_at=heartbeat_at,
        completed_at=completed_at,
        user_metadata=user_metadata,
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

        from unittest.mock import patch

        with patch(
            "app.modules.auth.dependencies.log_permission_denial"
        ) as denial_telemetry:
            resp = await client.get(f"/jobs/{job.id}", headers=editor_auth_header)

        assert resp.status_code == 403
        denial_telemetry.assert_called_once()
        assert denial_telemetry.call_args.args[2] == "manage_users"
        assert denial_telemetry.call_args.kwargs == {"resource_type": "ingest_job"}

    async def test_denied_parameterized_route_logs_template_not_job_id(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session,
    ):
        """Denial telemetry must not expose identifiers embedded in URL paths."""
        from unittest.mock import patch

        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id)

        with patch("app.modules.auth.dependencies.log") as denial_log:
            response = await client.get(f"/jobs/{job.id}", headers=editor_auth_header)

        assert response.status_code == 403
        denial_log.warning.assert_called_once()
        fields = denial_log.warning.call_args.kwargs
        assert fields["path"] == "/jobs/{job_id}"
        assert str(job.id) not in repr(fields)

    async def test_cross_user_access_delegates_to_permission_extension(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session,
    ):
        """A capability extension can grant cross-user access without an admin role."""
        import app.platform.extensions as ext_mod
        from app.platform.extensions.defaults import DefaultPermissionExtension

        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, created_by=admin_id)
        seen_resource = None

        class JobManagerExtension(DefaultPermissionExtension):
            async def check_permission(
                self,
                db,
                user,
                capability,
                *,
                user_roles,
                permission_matrix=None,
                resource=None,
            ):
                nonlocal seen_resource
                if capability == "manage_users":
                    seen_resource = resource
                    return True
                return await super().check_permission(
                    db,
                    user,
                    capability,
                    user_roles=user_roles,
                    permission_matrix=permission_matrix,
                    resource=resource,
                )

        previous = ext_mod._extensions.get("permission")
        ext_mod._extensions["permission"] = JobManagerExtension()
        try:
            resp = await client.get(f"/jobs/{job.id}", headers=editor_auth_header)
        finally:
            if previous is None:
                ext_mod._extensions.pop("permission", None)
            else:
                ext_mod._extensions["permission"] = previous

        assert resp.status_code == 200
        assert seen_resource is not None
        assert seen_resource.id == job.id

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
        assert "heartbeat expired" in resp.json()["error_message"]

    async def test_get_job_keeps_old_job_running_with_fresh_heartbeat(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """A long-running job remains active while its worker renews its lease."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            status="running",
            started_at=datetime.now(timezone.utc) - timedelta(hours=2),
            heartbeat_at=datetime.now(timezone.utc) - timedelta(seconds=5),
        )

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)

        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    async def test_worker_can_renew_running_job_lease(self, test_db_session):
        from app.platform.jobs.heartbeat import renew_ingest_job_heartbeat

        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            status="running",
            started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )

        assert await renew_ingest_job_heartbeat(job.id, job.attempt_id) is True
        await test_db_session.refresh(job)
        assert job.heartbeat_at is not None
        assert job.heartbeat_at > datetime.now(timezone.utc) - timedelta(minutes=1)

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
        "can_retry": False,
        "retry_reason": None,
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

    async def test_returns_200_null_when_dataset_has_no_job(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Dataset visible but with no ingest job → 200 + null (not 404).

        Remote/STAC/registered datasets have no ingest job; a 404 here would
        pollute the browser console on the dataset detail page, so the server
        returns a null body instead.
        """
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
        assert resp.status_code == 200
        assert resp.json() is None

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

    async def test_cross_user_retry_denial_emits_safe_telemetry(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session,
    ):
        """Manual cross-user retry checks share permission-denial telemetry."""
        from unittest.mock import patch

        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            status="failed",
            source_url="https://example.com/FeatureServer/0",
            error_message="Transient worker failure",
        )

        with patch(
            "app.modules.auth.dependencies.log_permission_denial"
        ) as denial_telemetry:
            response = await client.post(
                f"/jobs/{job.id}/retry", headers=editor_auth_header
            )

        assert response.status_code == 403
        denial_telemetry.assert_called_once()
        assert denial_telemetry.call_args.args[2] == "manage_users"
        assert denial_telemetry.call_args.kwargs == {"resource_type": "ingest_job"}

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

    async def test_retry_failed_s3_job_uses_storage_provider(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """A retained object-store key is replayable even though it is not local."""
        from unittest.mock import AsyncMock, MagicMock

        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            status="failed",
            file_path=f"staging/{uuid.uuid4()}/roads.geojson",
            error_message="Transient worker failure",
        )
        storage = MagicMock()
        storage.exists = AsyncMock(return_value=True)
        queued = AsyncMock()
        monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)
        monkeypatch.setattr("app.platform.jobs.router.queue_ingest_job", queued)

        resp = await client.post(f"/jobs/{job.id}/retry", headers=admin_auth_header)

        assert resp.status_code == 202, resp.text
        storage.exists.assert_awaited_once_with(job.file_path)
        queued.assert_awaited_once()

        audit_resp = await client.get(
            "/admin/audit-logs/",
            params={"action": "job.retry", "resource_id": str(job.id)},
            headers=admin_auth_header,
        )
        assert audit_resp.status_code == 200
        audit = audit_resp.json()["logs"][0]
        assert audit["resource_id"] == str(job.id)
        assert (
            audit["details"]["previous_attempt_id"]
            != audit["details"]["next_attempt_id"]
        )
        assert audit["details"]["cross_user"] is False
        assert audit["ip_address"] is not None

    async def test_retry_legacy_null_attempt_and_deleted_owner_audit_as_json_null(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        tmp_path,
        monkeypatch,
    ):
        """Legacy nullable identifiers remain machine-readable in retry audits."""
        from unittest.mock import AsyncMock

        admin_id = await get_user_id(test_db_session, "admin")
        staged_file = tmp_path / "legacy-retry.geojson"
        staged_file.write_text("{}")
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            status="failed",
            file_path=str(staged_file),
            error_message="Legacy worker failure",
        )
        job.created_by = None
        job.attempt_id = None
        await test_db_session.commit()

        queued = AsyncMock()
        monkeypatch.setattr("app.platform.jobs.router.queue_ingest_job", queued)

        response = await client.post(f"/jobs/{job.id}/retry", headers=admin_auth_header)

        assert response.status_code == 202, response.text
        audit_resp = await client.get(
            "/admin/audit-logs/",
            params={"action": "job.retry", "resource_id": str(job.id)},
            headers=admin_auth_header,
        )
        details = audit_resp.json()["logs"][0]["details"]
        assert details["job_owner_id"] is None
        assert details["previous_attempt_id"] is None
        assert details["next_attempt_id"] is not None
        assert details["next_attempt_id"] != "None"
        queued.assert_awaited_once()

    async def test_authenticated_service_job_requires_fresh_credentials(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """Request-only service tokens are never silently replaced by anonymous retry."""
        from unittest.mock import AsyncMock

        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            status="failed",
            source_url="https://example.com/FeatureServer/0",
            error_message="Authentication failed",
            user_metadata={"service_auth_required": True},
        )
        queued = AsyncMock()
        monkeypatch.setattr("app.platform.jobs.router.queue_ingest_job", queued)

        status_resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        retry_resp = await client.post(
            f"/jobs/{job.id}/retry", headers=admin_auth_header
        )

        assert status_resp.status_code == 200
        assert status_resp.json()["can_retry"] is False
        assert "fresh credentials" in status_resp.json()["retry_reason"]
        assert retry_resp.status_code == 409
        assert "fresh credentials" in retry_resp.json()["detail"]
        queued.assert_not_awaited()

    async def test_failed_reupload_is_not_requeued_as_ordinary_ingest(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        from unittest.mock import AsyncMock

        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            status="failed",
            file_path="/tmp/replacement.geojson",
            user_metadata={"reupload": True, "dataset_id": str(uuid.uuid4())},
        )
        queued = AsyncMock()
        monkeypatch.setattr("app.platform.jobs.router.queue_ingest_job", queued)

        status_resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        retry_resp = await client.post(
            f"/jobs/{job.id}/retry", headers=admin_auth_header
        )

        assert status_resp.status_code == 200
        assert status_resp.json()["can_retry"] is False
        assert "Start the reupload again" in status_resp.json()["retry_reason"]
        assert retry_resp.status_code == 400
        queued.assert_not_awaited()


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
        expected_counts = {
            "pending_failed",
            "running_failed",
            "total_cleaned",
            "vrt_assets_recovered",
            "vrt_generations_failed",
            "terminal_jobs_purged",
            "staged_paths_considered",
            "local_files_reaped",
            "storage_objects_reaped",
            "staged_paths_skipped",
            "staged_cleanup_failures",
            "total_affected",
        }
        assert expected_counts <= data.keys()
        assert data["total_cleaned"] == (
            data["pending_failed"] + data["running_failed"]
        )

        audit_resp = await client.get(
            "/admin/audit-logs/",
            params={"action": "job.cleanup_stale"},
            headers=admin_auth_header,
        )
        assert audit_resp.status_code == 200
        audits = audit_resp.json()["logs"]
        completed = next(
            audit for audit in audits if audit["details"].get("outcome") == "completed"
        )
        operation_id = completed["details"]["operation_id"]
        assert completed["details"] == {
            "operation_id": operation_id,
            "outcome": "completed",
            **{key: data[key] for key in expected_counts},
        }
        requested = next(
            audit
            for audit in audits
            if audit["details"].get("operation_id") == operation_id
            and audit["details"].get("outcome") == "requested"
        )
        assert requested["details"] == {
            "operation_id": operation_id,
            "outcome": "requested",
        }
        assert completed["resource_id"] == requested["resource_id"]
        assert completed["resource_id"] == operation_id
        assert completed["ip_address"] is not None
        assert requested["ip_address"] is not None

    async def test_cleanup_commit_failure_preserves_requested_and_records_safe_failure(
        self, monkeypatch
    ):
        """A failed DB commit never starts irreversible staging cleanup."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from fastapi import HTTPException

        import app.modules.audit.service as audit_service
        import app.platform.jobs.router as jobs_router
        from app.platform.jobs.router import StaleCleanupOutcome

        secret_path = "/tmp/private/tenant-secret-upload.geojson"

        class RecordingSession:
            def __init__(self):
                self.pending = []
                self.committed = []
                self.commit_count = 0

            async def commit(self):
                self.commit_count += 1
                if self.commit_count == 2:
                    raise RuntimeError(f"commit failed after deleting {secret_path}")
                self.committed.extend(self.pending)
                self.pending.clear()

            async def rollback(self):
                self.pending.clear()

        db = RecordingSession()
        durable_events = []

        async def record_audit(_db, event):
            _db.pending.append(event)

        async def record_durable(event):
            durable_events.append(event)

        outcome = StaleCleanupOutcome(
            pending_failed=1,
            running_failed=0,
            vrt_assets_recovered=0,
            vrt_generations_failed=0,
            terminal_jobs_purged=1,
            staged_paths_considered=1,
            local_files_reaped=1,
            storage_objects_reaped=0,
            staged_paths_skipped=0,
            staged_cleanup_failures=0,
        )
        cleanup = AsyncMock(return_value=outcome)
        reap = AsyncMock(return_value=outcome)
        monkeypatch.setattr(audit_service, "audit_emit", record_audit)
        monkeypatch.setattr(audit_service, "audit_emit_durable", record_durable)
        monkeypatch.setattr(jobs_router, "fail_stale_jobs", cleanup)
        monkeypatch.setattr(jobs_router, "_reap_committed_staged_paths", reap)
        error_logs = []
        monkeypatch.setattr(
            jobs_router.log,
            "error",
            lambda *_args, **kwargs: error_logs.append(kwargs),
        )

        request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
        user = SimpleNamespace(id=uuid.uuid4())

        with pytest.raises(HTTPException) as exc_info:
            await jobs_router.cleanup_stale_jobs(request, user, db)

        assert exc_info.value.status_code == 500
        cleanup.assert_awaited_once_with(db, commit=False, detailed=True)
        reap.assert_not_awaited()
        assert [event.details["outcome"] for event in db.committed] == ["requested"]
        assert [event.details["outcome"] for event in durable_events] == ["failed"]
        recorded_events = [*db.committed, *durable_events]
        operation_ids = {event.details["operation_id"] for event in recorded_events}
        assert len(operation_ids) == 1
        assert len({event.resource_id for event in recorded_events}) == 1
        recorded = repr([event.details for event in recorded_events])
        assert secret_path not in recorded
        assert "tenant-secret" not in recorded
        assert durable_events[-1].details["error_code"] == "cleanup_failed"
        assert error_logs == [
            {
                "operation_id": next(iter(operation_ids)),
                "user_id": str(user.id),
                "error_type": "RuntimeError",
            }
        ]
        assert secret_path not in repr(error_logs)

    async def test_completion_audit_failure_does_not_fail_completed_cleanup(
        self, monkeypatch
    ):
        """A terminal telemetry outage cannot make a committed cleanup retryable."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        import app.modules.audit.service as audit_service
        import app.platform.jobs.router as jobs_router
        from app.platform.jobs.router import StaleCleanupOutcome

        class RecordingSession:
            def __init__(self):
                self.pending = []
                self.committed = []

            async def commit(self):
                self.committed.extend(self.pending)
                self.pending.clear()

            async def rollback(self):
                self.pending.clear()

        async def record_audit(db, event):
            db.pending.append(event)

        async def fail_durable(_event):
            raise RuntimeError("audit database unavailable")

        outcome = StaleCleanupOutcome(
            pending_failed=1,
            running_failed=0,
            vrt_assets_recovered=0,
            vrt_generations_failed=0,
            terminal_jobs_purged=0,
            staged_paths_considered=1,
            local_files_reaped=1,
            storage_objects_reaped=0,
            staged_paths_skipped=0,
            staged_cleanup_failures=0,
        )
        cleanup = AsyncMock(return_value=outcome)
        reap = AsyncMock(return_value=outcome)
        monkeypatch.setattr(audit_service, "audit_emit", record_audit)
        monkeypatch.setattr(audit_service, "audit_emit_durable", fail_durable)
        monkeypatch.setattr(jobs_router, "fail_stale_jobs", cleanup)
        monkeypatch.setattr(jobs_router, "_reap_committed_staged_paths", reap)
        error_logs = []
        monkeypatch.setattr(
            jobs_router.log,
            "error",
            lambda *_args, **kwargs: error_logs.append(kwargs),
        )

        db = RecordingSession()
        request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
        user = SimpleNamespace(id=uuid.uuid4())

        result = await jobs_router.cleanup_stale_jobs(request, user, db)

        assert result.total_cleaned == 1
        cleanup.assert_awaited_once_with(db, commit=False, detailed=True)
        reap.assert_awaited_once_with(outcome)
        assert [event.details["outcome"] for event in db.committed] == [
            "requested",
            "database_committed",
        ]
        assert error_logs == [
            {
                "operation_id": db.committed[0].details["operation_id"],
                "user_id": str(user.id),
                "error_type": "RuntimeError",
            }
        ]
