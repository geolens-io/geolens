"""fix(#1746): every door judges a service token by the worker's policy.

#1277 gave the REFRESH door the shared header-token policy from
``app.core.service_tokens``: a WFS or OGC API credential becomes an
``Authorization`` header line reaching libcurl through GDAL, so it is pinned to
the base64url charset with a length floor, and a token outside that set is
refused with 422 ``invalid_service_token`` before anything is staged.

The other three doors were never widened to match, and each failed differently:

- **import commit** and **re-upload commit** went straight to
  ``resolve_dispatch_credential``, so a token containing ``+`` or ``/`` was
  answered 202, its single-use secret was consumed, and the job then failed
  deterministically inside ogr2ogr's own charset check with the credential
  already spent — a retry needs a new token, and the first one is gone.
- **service preview** judged the same token by ``_validate_safe_token``
  (printable, no whitespace), so a credential that could never import previewed
  cleanly and the refusal arrived a screen later.

Each test asserts three things, because they can regress independently: the
status and code, that the body carries the POLICY and not the credential, and
that the door stopped before the side effect it used to perform.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from app.core.service_tokens import HEADER_TOKEN_POLICY
from app.platform.jobs.models import IngestJob
from tests.factories import create_dataset, get_user_id

# The credential-store fake and both dispatch harnesses are #1676's; reusing
# them keeps this suite answering to the same model of a door that the lease
# tests do, rather than inventing a second one that can drift.
from tests.test_import_token_lease_1676 import (  # noqa: F401
    _import_harness,
    _reupload_harness,
    credential_backend,
)

# fix(#1746 codex r2): autouse where imported — keeps the bearer header file the
# preview tests below write out of the real /tmp/gdal-auth.
from tests.test_ogr_subprocess_env import gdal_header_tmpdir  # noqa: F401

pytestmark = pytest.mark.anyio

_WFS_URL = "https://services.example.test/geoserver/wfs"


# A token that is printable and whitespace-free — so the old, weaker checks all
# passed it — but carries two characters outside the base64url alphabet. The
# uuid tail makes it unique per test so an assertion that it is absent from a
# response body cannot pass by coincidence.
def _rejected_token() -> str:
    return "tok+slash/" + uuid.uuid4().hex


async def _wfs_import_job(session, *, created_by: uuid.UUID) -> IngestJob:
    """A pending first-import job bound to a protected WFS layer."""
    job = IngestJob(
        source_filename="Parcels",
        source_url=_WFS_URL,
        source_layer="topp:parcels",
        created_by=created_by,
        status="pending",
        user_metadata={"service_type": "WFS 2.0.0", "layer_id": None},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _wfs_reupload_job(
    session, *, dataset_id: uuid.UUID, created_by: uuid.UUID
) -> IngestJob:
    job = IngestJob(
        dataset_id=dataset_id,
        source_filename="Parcels",
        source_url=_WFS_URL,
        source_layer="topp:parcels",
        created_by=created_by,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset_id),
            "service_type": "WFS 2.0.0",
            "layer_id": None,
            "source_type": "service_url",
        },
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


def _assert_policy_without_the_token(resp, secret: str) -> None:
    """The refusal names the rule and never the credential."""
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_service_token"
    assert detail["message"] == HEADER_TOKEN_POLICY
    assert "base64url" in detail["message"]
    # On the whole body, not just the message: a door that echoed the token
    # under some other key would satisfy a message-only assertion.
    assert secret not in resp.text


# ---------------------------------------------------------------------------
# Door 1 — first import (POST /ingest/commit/{job_id})
# ---------------------------------------------------------------------------


class TestImportCommitDoor:
    async def test_a_wfs_token_outside_the_charset_never_reaches_the_stash(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        secret = _rejected_token()
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _wfs_import_job(test_db_session, created_by=admin_id)

        with patch(
            "app.platform.refresh.credentials.resolve_dispatch_credential",
            new_callable=AsyncMock,
        ) as stash:
            async with _import_harness() as task:
                resp = await client.post(
                    f"/ingest/commit/{job.id}",
                    json={"title": "Parcels", "token": secret},
                    headers=admin_auth_header,
                )

        _assert_policy_without_the_token(resp, secret)
        # The point of checking at the door: the credential is never staged, so
        # the caller's token survives the refusal and a retry can use it.
        stash.assert_not_awaited()
        task.defer_async.assert_not_awaited()

    async def test_the_refusal_persists_no_service_auth_required_marker(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        """fix(#1746 codex r1): the refusal must land before the metadata write.

        ``commit_import`` writes ``service_auth_required`` into
        ``user_metadata`` and commits it BEFORE dispatching, and that key is a
        one-way door: ``_replay_capability`` in platform/jobs/router.py reads it
        and refuses ``POST /jobs/{id}/retry`` with "This service import requires
        fresh credentials". Checking the token only at the dispatch call would
        leave a still-pending job carrying that marker for a request that queued
        nothing — permanently un-retryable after any later, unrelated failure.
        """
        from sqlalchemy import select

        admin_id = await get_user_id(test_db_session, "admin")
        job = await _wfs_import_job(test_db_session, created_by=admin_id)

        async with _import_harness() as task:
            resp = await client.post(
                f"/ingest/commit/{job.id}",
                json={"title": "Parcels", "token": _rejected_token()},
                headers=admin_auth_header,
            )

        assert resp.status_code == 422, resp.text
        task.defer_async.assert_not_awaited()

        reloaded = (
            await test_db_session.execute(
                select(IngestJob)
                .where(IngestJob.id == job.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        assert "service_auth_required" not in (reloaded.user_metadata or {})
        # And nothing else from the commit body was persisted either, so the
        # job is exactly as retryable as it was before the request.
        assert "title" not in (reloaded.user_metadata or {})
        assert reloaded.status == "pending"

    async def test_a_short_token_is_refused_too(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        """The length floor is half the policy and was equally invisible here."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _wfs_import_job(test_db_session, created_by=admin_id)

        async with _import_harness() as task:
            resp = await client.post(
                f"/ingest/commit/{job.id}",
                json={"title": "Parcels", "token": "short"},
                headers=admin_auth_header,
            )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "invalid_service_token"
        task.defer_async.assert_not_awaited()

    async def test_arcgis_keeps_its_wider_vocabulary(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        """The counterfactual: the policy is header-auth only, deliberately.

        An ArcGIS token is urlencoded into the ESRIJSON query string and never
        becomes a header line, so applying the charset there would refuse valid
        ArcGIS credentials for a danger that path does not have.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        job = IngestJob(
            source_filename="Parcels",
            source_url="https://example.arcgis.test/rest/services/P/FeatureServer/0",
            source_layer="0",
            created_by=admin_id,
            status="pending",
            user_metadata={"service_type": "ArcGIS FeatureServer", "layer_id": 0},
        )
        test_db_session.add(job)
        await test_db_session.commit()

        async with _import_harness() as task:
            resp = await client.post(
                f"/ingest/commit/{job.id}",
                json={"title": "Parcels", "token": "AAPK/secret+value=="},
                headers=admin_auth_header,
            )

        assert resp.status_code == 202, resp.text
        task.defer_async.assert_awaited_once()


# ---------------------------------------------------------------------------
# Door 2 — re-upload commit (POST /datasets/{id}/reupload/{job_id}/commit)
# ---------------------------------------------------------------------------


class TestReuploadCommitDoor:
    async def _dataset(self, session, *, created_by: uuid.UUID):
        return await create_dataset(
            session,
            created_by=created_by,
            name="Service Reupload Dataset",
            visibility="public",
            feature_count=100,
            source_filename="original.geojson",
            source_url="https://old.example.test/source",
        )

    async def test_a_wfs_token_outside_the_charset_never_reaches_the_stash(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        secret = _rejected_token()
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await self._dataset(test_db_session, created_by=admin_id)
        job = await _wfs_reupload_job(
            test_db_session, dataset_id=dataset.id, created_by=admin_id
        )

        with patch(
            "app.modules.catalog.datasets.api.router_reupload."
            "resolve_dispatch_credential",
            new_callable=AsyncMock,
        ) as stash:
            async with _reupload_harness() as task:
                resp = await client.post(
                    f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                    json={"token": secret},
                    headers=admin_auth_header,
                )

        _assert_policy_without_the_token(resp, secret)
        stash.assert_not_awaited()
        task.defer_async.assert_not_awaited()

    async def test_the_refusal_reserves_nothing(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        """No run row, and the job stays committable.

        The check sits ahead of ``create_pending_run`` for this reason: a
        reserved run holds ``uq_refresh_runs_one_active`` against the dataset,
        so a token that provably cannot work would answer the operator's next
        refresh with ``dataset_busy`` until the stale-run sweep.
        """
        from sqlalchemy import select

        from app.platform.refresh.models import DatasetRefreshRun

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await self._dataset(test_db_session, created_by=admin_id)
        job = await _wfs_reupload_job(
            test_db_session, dataset_id=dataset.id, created_by=admin_id
        )

        async with _reupload_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                json={"token": _rejected_token()},
                headers=admin_auth_header,
            )

        assert resp.status_code == 422, resp.text
        run = (
            await test_db_session.execute(
                select(DatasetRefreshRun)
                .where(DatasetRefreshRun.dataset_id == dataset.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        assert run is None

        reloaded = (
            await test_db_session.execute(
                select(IngestJob)
                .where(IngestJob.id == job.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        assert reloaded.status == "pending"


# ---------------------------------------------------------------------------
# Door 3 — service preview (POST /services/preview)
# ---------------------------------------------------------------------------


class TestServicePreviewDoor:
    async def test_the_endpoint_refuses_before_spawning_ogrinfo(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ) -> None:
        """422 out of the handler, not the 500 its broad handler used to make.

        ``preview_service_layer`` wraps the ogrinfo call in a catch-all that
        records a failure and answers 500. Without an explicit re-raise for
        ``HTTPException`` the policy refusal would be swallowed by it, and the
        caller would be told something unexpected happened rather than what is
        wrong with their token.
        """
        import asyncio as aio

        secret = _rejected_token()
        spawned: list = []

        async def _fake_exec(*cmd, **kwargs):
            spawned.append(cmd)
            raise AssertionError("ogrinfo must not be spawned for a refused token")

        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch.object(aio, "create_subprocess_exec", _fake_exec),
        ):
            resp = await client.post(
                "/services/preview",
                json={
                    "url": _WFS_URL,
                    "service_type": "WFS 2.0.0",
                    "layer_name": "topp:parcels",
                    "token": secret,
                },
                headers=admin_auth_header,
            )

        _assert_policy_without_the_token(resp, secret)
        assert spawned == []

    async def test_run_service_preview_refuses_a_wfs_token_outside_the_charset(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        """The check lives in the shared helper, so both callers inherit it.

        ``run_service_preview`` is reached from the service-import preview and
        from the re-upload preview. Pinning it here rather than only at one
        endpoint is what keeps the second caller from being the hole. The
        subprocess is stubbed to fail loudly: a regression must show up as this
        assertion, not as a real ogrinfo reaching for the network.
        """
        import asyncio as aio

        from fastapi import HTTPException

        from app.modules.catalog.sources import preview as preview_mod

        async def _fake_exec(*cmd, **kwargs):
            raise AssertionError("ogrinfo must not be spawned for a refused token")

        monkeypatch.setattr(aio, "create_subprocess_exec", _fake_exec)

        with pytest.raises(HTTPException) as excinfo:
            await preview_mod.run_service_preview(
                f"WFS:{_WFS_URL}", "topp:parcels", token=_rejected_token()
            )
        assert excinfo.value.status_code == 422
        assert excinfo.value.detail["code"] == "invalid_service_token"
        assert excinfo.value.detail["message"] == HEADER_TOKEN_POLICY

    async def test_an_accepted_token_writes_its_header_file_to_the_tmpfs_dir(
        self, client: AsyncClient, monkeypatch, tmp_path
    ) -> None:
        """fix(#1746) finding 16: the header file's directory is named, not inherited.

        The file holds an ``Authorization`` header line, and ``mkstemp`` with no
        ``dir=`` lands wherever ``tempfile.tempdir`` happens to point. That is
        the staging volume only when the process ran
        ``redirect_tempfile_to_staging`` (app/api/main.py,
        app/platform/jobs/worker.py) AND that helper found the directory already
        present, since it silently declines to move ``tempfile.tempdir``
        otherwise.

        fix(#1746 codex r2): and the named directory is ``gdal_header_dir()``,
        the container tmpfs — never ``upload_staging_dir``, which is a
        persistent volume ``scripts/backup-entrypoint.sh`` tars every cycle. A
        crash-orphaned bearer header on that volume can reach a backup.

        ``tempfile.tempdir`` is pointed at a decoy for the duration. Without it
        the assertion below passes on the inherited default and proves nothing
        about the argument this test exists for.
        """
        import asyncio as aio
        import json as json_mod
        import os
        import tempfile

        from app.core.config import settings
        from app.core.runtime.staging import gdal_header_dir
        from app.modules.catalog.sources import preview as preview_mod

        decoy = tmp_path / "not-the-header-dir"
        decoy.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(decoy))

        seen: dict = {}

        class _FakeProc:
            returncode = 0

            async def communicate(self):
                payload = {
                    "layers": [
                        {
                            "name": "topp:parcels",
                            "fields": [],
                            "features": [],
                            "geometryFields": [],
                        }
                    ]
                }
                return (json_mod.dumps(payload).encode(), b"")

        async def _fake_exec(*cmd, **kwargs):
            seen["header_file"] = (kwargs.get("env") or {}).get("GDAL_HTTP_HEADER_FILE")
            return _FakeProc()

        monkeypatch.setattr(aio, "create_subprocess_exec", _fake_exec)

        await preview_mod.run_service_preview(
            f"WFS:{_WFS_URL}",
            "topp:parcels",
            token="averylongbearertoken1234567890",
        )

        header_file = seen["header_file"]
        assert header_file
        parent = os.path.realpath(os.path.dirname(header_file))
        assert parent == os.path.realpath(gdal_header_dir())
        assert parent != os.path.realpath(decoy)
        # The two directories this file must NOT be in: the inherited tempdir,
        # and the backed-up staging volume.
        assert parent != os.path.realpath(settings.upload_staging_dir)
