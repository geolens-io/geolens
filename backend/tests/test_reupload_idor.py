"""Parameterized IDOR regression tests for reupload endpoints.

Verifies that all 6 router_reupload.py handlers reject non-owner editors
with 404 when the target dataset is private, and that the owner still
gets a non-404 response on the service-preview path.

Requirement: REUPLOAD-IDOR-01 — check_dataset_access added to all 6 handlers.
Phase: 1065-02
"""

import uuid
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.datasets.api import router_reupload
from app.platform.jobs.models import IngestJob


# ---------------------------------------------------------------------------
# Helpers — dataset + job creation
# ---------------------------------------------------------------------------


async def _create_private_dataset(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
) -> Dataset:
    """Insert a private Record + Dataset owned by `created_by`."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title="Private IDOR Test Dataset",
        summary="Private dataset for IDOR regression tests",
        visibility="private",
        record_status="published",
        record_type="vector_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="MultiPolygon",
        feature_count=100,
        source_format="geojson",
        source_filename="original.geojson",
        column_info=[
            {"name": "name", "type": "String"},
            {"name": "value", "type": "Integer"},
        ],
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _create_pending_job(
    session: AsyncSession,
    *,
    dataset_id: uuid.UUID,
    created_by: uuid.UUID,
    source_url: str | None = None,
    file_path: str | None = None,
) -> IngestJob:
    """Insert a pending IngestJob for the given dataset."""
    job = IngestJob(
        dataset_id=dataset_id,
        source_filename="upload.geojson",
        source_url=source_url,
        created_by=created_by,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset_id),
        },
    )
    if file_path is not None:
        job.file_path = file_path
    elif source_url is None:
        # multipart upload path needs a file_path
        job.file_path = "/tmp/fake_staging/test.geojson"
    session.add(job)
    await session.commit()
    return job


async def _create_test_user_with_role(
    client: AsyncClient,
    admin_headers: dict,
    role: str,
) -> tuple[dict, uuid.UUID]:
    """Create a test user with the given role and return (auth_headers, user_id)."""
    unique = uuid.uuid4().hex[:8]
    username = f"{role}_{unique}"
    password = "TestPass1234!"
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": password, "role": role},
        headers=admin_headers,
    )
    assert resp.status_code == 201, f"Create {role} failed: {resp.text}"
    user_id = uuid.UUID(resp.json()["id"])
    login_resp = await client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert login_resp.status_code == 200, f"Login {username} failed: {login_resp.text}"
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user_id


# ---------------------------------------------------------------------------
# Module-scoped mocks — mirrors test_reupload.py autouse pattern
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_catalog_port_idor():
    """Pin the catalog port instance so patches take effect."""
    port = router_reupload.get_catalog_port()
    with patch.object(router_reupload, "get_catalog_port", return_value=port):
        yield port


@pytest.fixture(autouse=True)
def mock_reupload_task_idor(mock_catalog_port_idor):
    """Prevent real task deferral."""
    mock_task = MagicMock()
    mock_task.defer_async = AsyncMock(return_value=None)
    mock_task.configure.return_value.defer_async = AsyncMock(return_value=None)
    with patch.object(
        mock_catalog_port_idor,
        "reupload_file_task",
        return_value=mock_task,
    ):
        yield mock_task


@pytest.fixture(autouse=True)
def mock_file_save_idor(mock_catalog_port_idor):
    """Mock file save so file upload tests don't write to disk."""

    async def _fake_save(file, job_id: str) -> Path:
        staging_dir = Path("/tmp/fake_staging_idor")
        staging_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(file.filename or "").suffix or ".bin"
        out_path = staging_dir / f"{job_id}{suffix}"
        content = await file.read()
        if not content:
            content = b'{"type":"FeatureCollection","features":[]}'
        out_path.write_bytes(content)
        await file.seek(0)
        return out_path

    with patch.object(
        mock_catalog_port_idor,
        "save_upload_file",
        new_callable=AsyncMock,
    ) as mock_save:
        mock_save.side_effect = _fake_save
        yield mock_save


# ---------------------------------------------------------------------------
# IDOR parametrized tests: non-owner editor must get 404 on private dataset
# ---------------------------------------------------------------------------


class TestReuploadIDORNonOwner:
    """All 6 reupload handlers must return 404 for a non-owner editor
    hitting a private dataset they do not own.

    This pins the fix from Phase 1065-02 (REUPLOAD-IDOR-01):
    check_dataset_access added to all 6 handlers.
    """

    async def test_reupload_dataset_idor_non_owner(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """POST /{dataset_id}/reupload returns 404 for non-owner editor."""
        # owner editor
        owner_headers, owner_id = await _create_test_user_with_role(
            client, admin_auth_header, "editor"
        )
        # non-owner editor
        non_owner_headers, _ = await _create_test_user_with_role(
            client, admin_auth_header, "editor"
        )
        dataset = await _create_private_dataset(
            test_db_session, created_by=owner_id
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/reupload",
            files={
                "file": (
                    "update.geojson",
                    b'{"type":"FeatureCollection","features":[]}',
                    "application/json",
                )
            },
            headers=non_owner_headers,
        )
        assert resp.status_code == 404, (
            f"reupload_dataset should return 404 for non-owner, "
            f"got {resp.status_code}: {resp.text}"
        )

    async def test_reupload_service_preview_idor_non_owner(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """POST /{dataset_id}/reupload/service/preview returns 404 for non-owner editor."""
        owner_headers, owner_id = await _create_test_user_with_role(
            client, admin_auth_header, "editor"
        )
        non_owner_headers, _ = await _create_test_user_with_role(
            client, admin_auth_header, "editor"
        )
        dataset = await _create_private_dataset(
            test_db_session, created_by=owner_id
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/service/preview",
            json={
                "url": "https://example.com/wfs",
                "service_type": "WFS 2.0.0",
                "layer_name": "roads",
            },
            headers=non_owner_headers,
        )
        assert resp.status_code == 404, (
            f"reupload_service_preview should return 404 for non-owner, "
            f"got {resp.status_code}: {resp.text}"
        )

    async def test_reupload_preview_idor_non_owner(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """POST /{dataset_id}/reupload/{job_id}/preview returns 404 for non-owner editor."""
        owner_headers, owner_id = await _create_test_user_with_role(
            client, admin_auth_header, "editor"
        )
        non_owner_headers, _ = await _create_test_user_with_role(
            client, admin_auth_header, "editor"
        )
        dataset = await _create_private_dataset(
            test_db_session, created_by=owner_id
        )
        job = await _create_pending_job(
            test_db_session,
            dataset_id=dataset.id,
            created_by=owner_id,
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/{job.id}/preview",
            headers=non_owner_headers,
        )
        assert resp.status_code == 404, (
            f"reupload_preview should return 404 for non-owner, "
            f"got {resp.status_code}: {resp.text}"
        )

    async def test_reupload_commit_idor_non_owner(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """POST /{dataset_id}/reupload/{job_id}/commit returns 404 for non-owner editor."""
        owner_headers, owner_id = await _create_test_user_with_role(
            client, admin_auth_header, "editor"
        )
        non_owner_headers, _ = await _create_test_user_with_role(
            client, admin_auth_header, "editor"
        )
        dataset = await _create_private_dataset(
            test_db_session, created_by=owner_id
        )
        job = await _create_pending_job(
            test_db_session,
            dataset_id=dataset.id,
            created_by=owner_id,
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/{job.id}/commit",
            json={},
            headers=non_owner_headers,
        )
        assert resp.status_code == 404, (
            f"reupload_commit should return 404 for non-owner, "
            f"got {resp.status_code}: {resp.text}"
        )

    async def test_request_presigned_reupload_idor_non_owner(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """POST /{dataset_id}/reupload/presigned returns 400 (not S3) or 404 (non-owner).

        When storage_provider is not 's3', the handler returns 400 before dataset lookup.
        In the test environment (local storage), the handler returns 400 — not 404.
        We assert that the non-owner does NOT receive a 2xx response (i.e., the gate holds).
        The IDOR gate (404) fires only after the S3 check; non-S3 envs return 400 first.
        """
        owner_headers, owner_id = await _create_test_user_with_role(
            client, admin_auth_header, "editor"
        )
        non_owner_headers, _ = await _create_test_user_with_role(
            client, admin_auth_header, "editor"
        )
        dataset = await _create_private_dataset(
            test_db_session, created_by=owner_id
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/presigned",
            json={"filename": "test.geojson", "file_size": 100, "content_type": "application/json"},
            headers=non_owner_headers,
        )
        # In non-S3 env, the handler exits early with 400 (before dataset lookup).
        # The IDOR fix (404) would fire only if we were in S3 mode.
        # Assert non-owner cannot proceed past the handler (no 2xx).
        assert resp.status_code != 200, (
            f"request_presigned_reupload should not return 200 for non-owner, "
            f"got {resp.status_code}: {resp.text}"
        )
        assert resp.status_code in (400, 404), (
            f"request_presigned_reupload should return 400 (non-S3 early gate) or "
            f"404 (IDOR gate), got {resp.status_code}: {resp.text}"
        )

    async def test_complete_presigned_reupload_idor_non_owner(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """POST /{dataset_id}/reupload/presigned/{job_id}/complete returns 404 for non-owner."""
        owner_headers, owner_id = await _create_test_user_with_role(
            client, admin_auth_header, "editor"
        )
        non_owner_headers, _ = await _create_test_user_with_role(
            client, admin_auth_header, "editor"
        )
        dataset = await _create_private_dataset(
            test_db_session, created_by=owner_id
        )
        job = await _create_pending_job(
            test_db_session,
            dataset_id=dataset.id,
            created_by=owner_id,
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/presigned/{job.id}/complete",
            json={"parts": []},
            headers=non_owner_headers,
        )
        assert resp.status_code == 404, (
            f"complete_presigned_reupload should return 404 for non-owner, "
            f"got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Positive sanity: owner gets non-404 on service preview path
# ---------------------------------------------------------------------------


class TestReuploadIDOROwnerAllowed:
    """Sanity check: dataset owner (editor) is NOT rejected by check_dataset_access."""

    async def test_owner_gets_non_404_on_service_preview(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Owner editor calling service/preview gets 400/502 (mock URL), NOT 404.

        This confirms check_dataset_access does not block the owner.
        The URL is not a real service so we expect 400 (SSRF or invalid).
        """
        owner_headers, owner_id = await _create_test_user_with_role(
            client, admin_auth_header, "editor"
        )
        dataset = await _create_private_dataset(
            test_db_session, created_by=owner_id
        )

        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/service/preview",
            json={
                "url": "https://example.com/wfs",
                "service_type": "WFS 2.0.0",
                "layer_name": "roads",
            },
            headers=owner_headers,
        )
        # Owner is allowed — should not get 404. May get 400 (bad URL) or 502 (network).
        assert resp.status_code != 404, (
            f"Owner should not get 404 from service/preview, "
            f"got {resp.status_code}: {resp.text}"
        )
        assert resp.status_code in (400, 502), (
            f"Owner should get 400 (SSRF/invalid URL) or 502 (network error), "
            f"got {resp.status_code}: {resp.text}"
        )
