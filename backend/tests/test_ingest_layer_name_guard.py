"""Tests for the fix(#823) layer_name guards.

The v1.6.0 deep audit found that a user-supplied ``layer_name`` reached GDAL
argv (ogrinfo/ogr2ogr) unvalidated. Two layers of defense were added:

  1. Argv-level guard (``validate_layer_name_argv`` in ingest/ogr.py): every
     spawner that forwards a layer name rejects option-like values (leading
     '-') before building the command, so a crafted name can never be parsed
     as a GDAL flag.
  2. Router-level 4xx guards: POST /ingest/preview/{job_id} and
     POST /ingest/commit/{job_id} reject a leading-dash layer_name with 422,
     and the commit endpoint additionally validates the requested layer_name
     against the preview's recorded ``all_layers`` (mirroring the existing
     commit-fan-out check).

Endpoint tests use a real test database (docker compose up db) and mock
``queue_ingest_job`` so nothing hits Procrastinate or GDAL.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.platform.jobs.models import IngestJob
from app.processing.ingest.ogr import (
    IngestionError,
    run_ogr2ogr,
    run_ogrinfo,
    run_ogrinfo_preview,
    validate_layer_name_argv,
)


# ---------------------------------------------------------------------------
# Unit tests: argv-level guard
# ---------------------------------------------------------------------------


class TestValidateLayerNameArgv:
    def test_leading_dash_rejected(self):
        with pytest.raises(IngestionError) as exc:
            validate_layer_name_argv("-oo")
        assert "must not start with '-'" in str(exc.value)

    def test_double_dash_flag_rejected(self):
        with pytest.raises(IngestionError):
            validate_layer_name_argv("--config")

    def test_normal_layer_name_accepted(self):
        validate_layer_name_argv("buildings")
        validate_layer_name_argv("roads_2024")

    async def test_run_ogrinfo_rejects_before_spawn(self):
        """The guard fires before any file access or subprocess spawn — the
        path does not need to exist."""
        with pytest.raises(IngestionError):
            await run_ogrinfo("/nonexistent/file.gpkg", layer_name="-oo")

    async def test_run_ogrinfo_preview_rejects_before_spawn(self):
        with pytest.raises(IngestionError):
            await run_ogrinfo_preview("/nonexistent/file.gpkg", layer_name="-oo")

    async def test_run_ogr2ogr_rejects_before_spawn(self):
        with pytest.raises(IngestionError):
            await run_ogr2ogr(
                "/nonexistent/file.gpkg",
                "target_table",
                "PG:dbname=unused",
                layer_name="-lco",
                schema="data",
            )


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_queue_ingest_job():
    """Prevent real task dispatch for the commit endpoint tests."""
    with patch(
        "app.processing.ingest.router.queue_ingest_job", new_callable=AsyncMock
    ) as m:
        yield m


async def _admin_user_id(session) -> uuid.UUID:
    from app.modules.auth.models import User

    result = await session.execute(select(User).where(User.username == "admin"))
    admin = result.scalar_one_or_none()
    assert admin is not None, "Admin user not found in test DB"
    return admin.id


async def _make_pending_job(
    session,
    user_id: uuid.UUID,
    all_layers: list[str] | None = None,
    file_path: str = "/tmp/fake-test.gpkg",
    source_filename: str = "test.gpkg",
) -> IngestJob:
    """Insert a pending vector IngestJob, optionally with all_layers recorded."""
    user_metadata: dict = {"file_type": "vector"}
    if all_layers is not None:
        user_metadata["all_layers"] = all_layers
    job = IngestJob(
        source_filename=source_filename,
        file_path=file_path,
        status="pending",
        created_by=user_id,
        user_metadata=user_metadata,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


class TestCommitLayerNameGuard:
    async def test_leading_dash_layer_name_422(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """A layer_name starting with '-' must never reach the worker."""
        uid = await _admin_user_id(test_db_session)
        job = await _make_pending_job(
            test_db_session, uid, all_layers=["buildings", "roads"]
        )
        resp = await client.post(
            f"/ingest/commit/{job.id}",
            json={"title": "Dash Guard", "layer_name": "-oo"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "must not start with '-'" in resp.json()["detail"]

    async def test_unknown_layer_name_422_with_available_layers(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """A layer_name absent from the preview's all_layers is rejected —
        parity with the commit-fan-out endpoint."""
        uid = await _admin_user_id(test_db_session)
        job = await _make_pending_job(
            test_db_session, uid, all_layers=["buildings", "roads"]
        )
        resp = await client.post(
            f"/ingest/commit/{job.id}",
            json={"title": "Unknown Layer", "layer_name": "nope"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["unknown_layers"] == ["nope"]
        assert detail["available_layers"] == ["buildings", "roads"]

    async def test_known_layer_name_accepted(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """A layer_name present in all_layers commits normally (202)."""
        uid = await _admin_user_id(test_db_session)
        job = await _make_pending_job(
            test_db_session, uid, all_layers=["buildings", "roads"]
        )
        resp = await client.post(
            f"/ingest/commit/{job.id}",
            json={"title": "Known Layer", "layer_name": "roads"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 202

    async def test_dict_shaped_all_layers_validated(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """all_layers stored as dicts ({name, feature_count, ...}) — the real
        preview shape — is normalised the same way as the fan-out endpoint."""
        uid = await _admin_user_id(test_db_session)
        job = await _make_pending_job(
            test_db_session,
            uid,
            all_layers=[
                {"name": "buildings", "feature_count": 10, "field_count": 3},
                {"name": "roads", "feature_count": 5, "field_count": 2},
            ],
        )
        resp = await client.post(
            f"/ingest/commit/{job.id}",
            json={"title": "Dict Layers", "layer_name": "nope"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["available_layers"] == ["buildings", "roads"]

    async def test_no_all_layers_skips_membership_check(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Single-layer sources never record all_layers; a stray (non-dash)
        layer_name is only dash-guarded here — the argv-level guard in ogr.py
        still backstops the worker."""
        uid = await _admin_user_id(test_db_session)
        job = await _make_pending_job(test_db_session, uid, all_layers=None)
        resp = await client.post(
            f"/ingest/commit/{job.id}",
            json={"title": "No Layer List", "layer_name": "whatever"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 202


class TestPreviewLayerNameGuard:
    async def test_leading_dash_layer_name_422(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The preview endpoint forwards layer_name to ogrinfo argv; an
        option-like value is rejected up front with a clear 422."""
        uid = await _admin_user_id(test_db_session)
        job = await _make_pending_job(test_db_session, uid)
        resp = await client.post(
            f"/ingest/preview/{job.id}",
            params={"layer_name": "-features"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "must not start with '-'" in resp.json()["detail"]
