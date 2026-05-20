"""Tests for POST /ingest/commit-fan-out/{job_id} (GPKG-03, Phase 1058-04).

Tests:
  - Happy path: 3-layer fan-out creates 3 queued results
  - Unknown layer name → 422 with list of unknown names
  - Layer cap exceeded (51 layers in request) → 422
  - Already-fanned-out job → 400
  - Unauthenticated → 401
  - Original job marked 'fanned_out' after dispatch
  - Fan-out jobs carry fan_out_parent_id + layer_name in user_metadata
  - file_path on original job is NOT mutated; all cloned jobs share it
  - Title defaults to '{file_basename}: {layer_name}'
  - T-1058D-04: _user_safe_error strips absolute file-system paths

These tests use a real test database (docker compose up db) and mock
Procrastinate task deferral (defer_with_orphan_guard is replaced with a
no-op so no real queue is needed).
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.platform.jobs.models import IngestJob
from app.processing.ingest.service import _user_safe_error


# ---------------------------------------------------------------------------
# Autouse mock: replace defer_with_orphan_guard so nothing hits Procrastinate.
# The guard is imported lazily inside create_fan_out_jobs, so we patch the
# source module — app.platform.jobs.defer_guard.defer_with_orphan_guard.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_defer_guard():
    """Prevent Procrastinate task deferral in all fan-out tests."""

    async def _noop(fn, rollback=None, db=None):
        # Do NOT call fn() — that would attempt ingest_file.defer_async
        # against a real Procrastinate queue.
        pass

    with patch(
        "app.platform.jobs.defer_guard.defer_with_orphan_guard",
        side_effect=_noop,
    ):
        yield


# ---------------------------------------------------------------------------
# Helper: insert a pending IngestJob directly via the DB session
# ---------------------------------------------------------------------------


async def _make_pending_job(
    session,
    user_id: uuid.UUID,
    all_layers: list[str],
    file_path: str = "/tmp/fake-test.gpkg",
    source_filename: str = "test.gpkg",
) -> IngestJob:
    """Insert a pending IngestJob with all_layers recorded in user_metadata."""
    job = IngestJob(
        source_filename=source_filename,
        file_path=file_path,
        status="pending",
        created_by=user_id,
        user_metadata={
            "all_layers": all_layers,
            "file_type": "vector",
        },
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


# ---------------------------------------------------------------------------
# Helper: resolve admin user ID from DB
# ---------------------------------------------------------------------------


async def _admin_user_id(session) -> uuid.UUID:
    from app.modules.auth.models import User

    result = await session.execute(select(User).where(User.username == "admin"))
    admin = result.scalar_one_or_none()
    assert admin is not None, "Admin user not found in test DB"
    return admin.id


# ---------------------------------------------------------------------------
# Endpoint integration tests
# ---------------------------------------------------------------------------


class TestFanOutEndpoint:
    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        """POST /ingest/commit-fan-out/{job_id} without auth → 401."""
        resp = await client.post(
            f"/ingest/commit-fan-out/{uuid.uuid4()}",
            json={"layers": [{"layer_name": "buildings"}]},
        )
        assert resp.status_code == 401

    async def test_happy_path_3_layers(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """3-layer fan-out → HTTP 202, 3 'queued' results, original job 'fanned_out'."""
        uid = await _admin_user_id(test_db_session)
        job = await _make_pending_job(
            test_db_session,
            uid,
            all_layers=["buildings", "addresses", "roads"],
        )

        resp = await client.post(
            f"/ingest/commit-fan-out/{job.id}",
            json={
                "layers": [
                    {"layer_name": "buildings"},
                    {"layer_name": "addresses", "title": "My Addresses"},
                    {"layer_name": "roads"},
                ]
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 202, resp.text

        data = resp.json()
        assert data["fan_out_id"] == str(job.id)
        assert len(data["results"]) == 3
        for r in data["results"]:
            assert r["status"] == "queued", f"Layer {r['layer_name']} failed: {r.get('error')}"
            assert r["new_job_id"] is not None
            assert r["error"] is None

        # Verify original job is now 'fanned_out' in DB
        await test_db_session.refresh(job)
        assert job.status == "fanned_out"
        assert job.completed_at is not None

    async def test_cloned_jobs_have_correct_metadata(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Each cloned IngestJob carries layer_name, fan_out_parent_id, and correct title."""
        uid = await _admin_user_id(test_db_session)
        job = await _make_pending_job(
            test_db_session,
            uid,
            all_layers=["addresses"],
            source_filename="city.gpkg",
        )

        resp = await client.post(
            f"/ingest/commit-fan-out/{job.id}",
            json={"layers": [{"layer_name": "addresses", "title": "City Addresses"}]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 202

        r = resp.json()["results"][0]
        cloned_result = await test_db_session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(r["new_job_id"]))
        )
        cloned = cloned_result.scalar_one_or_none()
        assert cloned is not None
        assert cloned.user_metadata["layer_name"] == "addresses"
        assert cloned.user_metadata["fan_out_parent_id"] == str(job.id)
        assert cloned.user_metadata["title"] == "City Addresses"
        assert cloned.status == "pending"

    async def test_title_default_uses_filename_plus_layer(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """No title override → default title is '{file_basename}: {layer_name}'."""
        uid = await _admin_user_id(test_db_session)
        job = await _make_pending_job(
            test_db_session,
            uid,
            all_layers=["buildings"],
            source_filename="regions.gpkg",
        )

        resp = await client.post(
            f"/ingest/commit-fan-out/{job.id}",
            json={"layers": [{"layer_name": "buildings"}]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 202

        r = resp.json()["results"][0]
        cloned_result = await test_db_session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(r["new_job_id"]))
        )
        cloned = cloned_result.scalar_one_or_none()
        # "regions.gpkg" → strip extension → "regions: buildings"
        assert cloned.user_metadata["title"] == "regions: buildings"

    async def test_file_path_shared_across_fan_out_jobs(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """All cloned jobs share the original file_path; file is NOT mutated/deleted."""
        uid = await _admin_user_id(test_db_session)
        original_path = "/tmp/shared-multi.gpkg"
        job = await _make_pending_job(
            test_db_session,
            uid,
            all_layers=["alpha", "beta"],
            file_path=original_path,
        )

        resp = await client.post(
            f"/ingest/commit-fan-out/{job.id}",
            json={"layers": [{"layer_name": "alpha"}, {"layer_name": "beta"}]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 202

        data = resp.json()
        for r in data["results"]:
            cloned_result = await test_db_session.execute(
                select(IngestJob).where(IngestJob.id == uuid.UUID(r["new_job_id"]))
            )
            cloned = cloned_result.scalar_one_or_none()
            assert cloned.file_path == original_path

        # Original job's file_path is intact (not nulled or changed)
        await test_db_session.refresh(job)
        assert job.file_path == original_path

    async def test_unknown_layer_returns_422(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """layer_name not in all_layers → 422 with unknown_layers + available_layers."""
        uid = await _admin_user_id(test_db_session)
        job = await _make_pending_job(
            test_db_session,
            uid,
            all_layers=["buildings"],
        )

        resp = await client.post(
            f"/ingest/commit-fan-out/{job.id}",
            json={"layers": [{"layer_name": "does_not_exist"}]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "unknown_layers" in detail
        assert "does_not_exist" in detail["unknown_layers"]
        assert "buildings" in detail["available_layers"]

    async def test_cap_exceeded_51_layers_returns_422(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        """51 layers in request (> max_length=50) → 422 from Pydantic validation."""
        resp = await client.post(
            f"/ingest/commit-fan-out/{uuid.uuid4()}",
            json={"layers": [{"layer_name": f"layer_{i}"} for i in range(51)]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_already_fanned_out_returns_400(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Calling commit-fan-out on a 'fanned_out' job → 400."""
        uid = await _admin_user_id(test_db_session)
        job = await _make_pending_job(
            test_db_session,
            uid,
            all_layers=["buildings"],
        )
        job.status = "fanned_out"
        await test_db_session.commit()

        resp = await client.post(
            f"/ingest/commit-fan-out/{job.id}",
            json={"layers": [{"layer_name": "buildings"}]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "already processed" in resp.json()["detail"]

    async def test_non_pending_job_returns_400(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Calling commit-fan-out on a 'running' job → 400."""
        uid = await _admin_user_id(test_db_session)
        job = await _make_pending_job(
            test_db_session,
            uid,
            all_layers=["layer_a"],
        )
        job.status = "running"
        await test_db_session.commit()

        resp = await client.post(
            f"/ingest/commit-fan-out/{job.id}",
            json={"layers": [{"layer_name": "layer_a"}]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Unit tests for _user_safe_error (T-1058D-04)
# ---------------------------------------------------------------------------


class TestUserSafeError:
    def test_strips_unix_home_path(self):
        """Error messages with /Users/ or /home/ paths are sanitized."""
        exc = Exception("File not found: /Users/john/uploads/staging/abc.gpkg")
        result = _user_safe_error(exc)
        assert "/Users/" not in result
        assert "File not found" in result  # non-path prefix is preserved

    def test_strips_tmp_path(self):
        """Paths under /tmp are stripped."""
        exc = ValueError("ogr2ogr failed on /tmp/geolens_staging/job123_roads.gpkg")
        result = _user_safe_error(exc)
        assert "/tmp/" not in result

    def test_strips_windows_path(self):
        """Windows absolute paths (C:\\...) are sanitized."""
        exc = Exception("Cannot open C:\\Users\\admin\\uploads\\data.gpkg")
        result = _user_safe_error(exc)
        assert "C:\\" not in result

    def test_preserves_non_path_content(self):
        """Plain error messages without paths are unchanged."""
        exc = ValueError("layer 'xyz' not found in source")
        result = _user_safe_error(exc)
        assert result == "layer 'xyz' not found in source"

    def test_no_internal_path_leaked(self):
        """Sanitized string contains no absolute path components."""
        exc = Exception("Error reading /home/ubuntu/data/cities.gpkg: permission denied")
        result = _user_safe_error(exc)
        assert "/home/" not in result
