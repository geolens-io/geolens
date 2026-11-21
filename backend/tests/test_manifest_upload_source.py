"""A manifest_version 2 entry publishes a file its caller uploaded first."""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select, text, update

from app.core.config import settings
from app.platform.jobs.models import (
    COMMIT_ATTEMPTED_METADATA_KEY,
    MANIFEST_FINGERPRINT_METADATA_KEY,
    IngestJob,
)
from app.platform.refresh.models import DatasetRefreshRun
from app.processing.ingest import manifest_sources
from app.processing.ingest.manifest_reservation import (
    bind_reservation_to_staged_source,
    claim_upload,
)
from app.processing.ingest.manifest_schemas import ManifestApplyRequest
from app.processing.ingest.manifest_service import apply_manifest
from app.processing.ingest.manifest_sources import (
    UPLOAD_SOURCE_UNAVAILABLE,
    manifest_dataset_fingerprint,
)
from tests.factories import create_dataset, get_user_id
from tests.test_manifest_reapply_publication import (
    _admin,
    _http_request,
    _reupload_task,
    _run_worker,
)

pytestmark = pytest.mark.anyio

_FIXTURE = Path(__file__).parent / "fixtures/ingest/basic_attrs.geojson"
_ORIGINAL = _FIXTURE.read_bytes()
_RESURVEYED = _ORIGINAL + b"\n"
_CLIENT = {"id": "geolens-web", "version": "1.0.0"}


def _checksum(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _entry(key: str, job_id: uuid.UUID | str, checksum: str, **extra) -> dict:
    return {
        "key": key,
        "title": extra.pop("title", "Capitals"),
        "sources": [
            {
                "type": extra.pop("source_type", "vector"),
                "uri": f"upload:{job_id}",
                "checksum": checksum,
            }
        ],
        "metadata": {"crs": "EPSG:4326"},
        "publication": {"intent": "draft"},
        **extra,
    }


def _manifest(*entries: dict, dry_run: bool = False) -> dict:
    return {
        "manifest_version": "2",
        "catalog": {"title": "Browser publish"},
        "client": _CLIENT,
        "datasets": list(entries),
        "dry_run": dry_run,
    }


async def _upload(client: AsyncClient, headers: dict, body: bytes = _ORIGINAL):
    response = await client.post(
        "/ingest/upload",
        files={"file": ("capitals.geojson", body, "application/geo+json")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["job_id"])


async def _apply(client: AsyncClient, headers: dict, manifest: dict) -> dict:
    with patch(
        "app.processing.ingest.manifest_service.queue_ingest_job", new=AsyncMock()
    ) as queue:
        response = await client.post(
            "/ingest/manifest/apply", json=manifest, headers=headers
        )
    assert response.status_code == 200, response.text
    [result] = response.json()["results"]
    result["queued"] = queue.await_count
    return result


async def _row(session, job_id: uuid.UUID) -> IngestJob:
    return (
        await session.execute(
            select(IngestJob)
            .where(IngestJob.id == job_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _unknown_answers(client: AsyncClient, headers: dict, key: str) -> list:
    """What an entry naming a job id that never existed gets, preview then apply."""
    never = uuid.uuid4()
    return [
        await _apply(
            client,
            headers,
            _manifest(_entry(key, never, _checksum(_ORIGINAL)), dry_run=d),
        )
        for d in (True, False)
    ]


async def _answers(client, headers, key, job_id, checksum) -> list:
    return [
        await _apply(
            client, headers, _manifest(_entry(key, job_id, checksum), dry_run=d)
        )
        for d in (True, False)
    ]


async def _complete(session, job_id: uuid.UUID, owner: uuid.UUID) -> uuid.UUID:
    """Finish a claimed job as the worker would, with a dataset the owner owns."""
    dataset = await create_dataset(
        session,
        created_by=owner,
        name="Capitals",
        table_name=f"manifest_upload_{uuid.uuid4().hex[:10]}",
        record_type="vector_dataset",
        geometry_type="POINT",
        feature_count=3,
        column_info=[{"name": "name", "type": "text"}],
    )
    await session.execute(
        update(IngestJob)
        .where(IngestJob.id == job_id)
        .values(
            status="complete",
            dataset_id=dataset.id,
            completed_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
    return dataset.id


class TestApply:
    async def test_a_browser_geojson_upload_is_published_from_its_own_row(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        job_id = await _upload(client, editor_auth_header)
        before = await _row(test_db_session, job_id)
        staged = before.file_path

        result = await _apply(
            client,
            editor_auth_header,
            _manifest(_entry("web-capitals", job_id, _checksum(_ORIGINAL))),
        )

        assert (result["action"], result["job_id"]) == ("create", str(job_id))
        assert result["queued"] == 1
        job = await _row(test_db_session, job_id)
        assert (job.status, job.file_path) == ("pending", staged)
        assert job.user_metadata["manifest_key"] == "web-capitals"
        assert job.user_metadata["manifest_source_uri"] == f"upload:{job_id}"
        assert job.user_metadata["title"] == "Capitals"
        assert job.user_metadata[COMMIT_ATTEMPTED_METADATA_KEY]
        assert Path(staged).exists()
        # The import commit door no longer takes it.
        commit = await client.post(
            f"/ingest/commit/{job_id}",
            json={"title": "Elsewhere"},
            headers=editor_auth_header,
        )
        assert commit.status_code == 400
        rows = await test_db_session.scalar(
            select(func.count())
            .select_from(IngestJob)
            .where(IngestJob.user_metadata["manifest_key"].astext == "web-capitals")
        )
        assert rows == 1

    async def test_a_new_upload_replaces_the_dataset_on_the_same_key(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        first = await _upload(client, editor_auth_header)
        await _apply(
            client,
            editor_auth_header,
            _manifest(_entry("web-replace", first, _checksum(_ORIGINAL))),
        )
        editor = (await _row(test_db_session, first)).created_by
        dataset_id = await _complete(test_db_session, first, editor)
        second = await _upload(client, editor_auth_header, _RESURVEYED)
        staged = (await _row(test_db_session, second)).file_path

        with _reupload_task() as task:
            response = await client.post(
                "/ingest/manifest/apply",
                json=_manifest(_entry("web-replace", second, _checksum(_RESURVEYED))),
                headers=editor_auth_header,
            )

        [result] = response.json()["results"]
        assert (result["action"], result["job_id"], result["dataset_id"]) == (
            "update",
            str(second),
            str(dataset_id),
        )
        task.defer_async.assert_awaited_once()
        kwargs = task.defer_async.await_args.kwargs
        assert (kwargs["job_id"], kwargs["file_path"]) == (str(second), staged)
        assert kwargs["dataset_id"] == str(dataset_id)
        run = await test_db_session.scalar(
            select(DatasetRefreshRun).where(DatasetRefreshRun.ingest_job_id == second)
        )
        assert run is not None and run.dataset_id == dataset_id
        job = await _row(test_db_session, second)
        assert job.dataset_id == dataset_id
        assert job.user_metadata["reupload"] is True
        # An upload is the caller's own file, not an admin-only raw seed.
        assert "admitted_raw_source" not in job.user_metadata

    async def test_an_unchanged_re_export_is_a_skip_and_claims_nothing(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        first = await _upload(client, editor_auth_header)
        await _apply(
            client,
            editor_auth_header,
            _manifest(_entry("web-unchanged", first, _checksum(_ORIGINAL))),
        )
        editor = (await _row(test_db_session, first)).created_by
        await _complete(test_db_session, first, editor)
        again = await _upload(client, editor_auth_header)
        untouched = dict((await _row(test_db_session, again)).user_metadata)

        result = await _apply(
            client,
            editor_auth_header,
            _manifest(_entry("web-unchanged", again, _checksum(_ORIGINAL))),
        )

        assert (result["action"], result["job_id"]) == ("skip", str(first))
        assert "Cancel the unused upload" in result["message"]
        assert result["queued"] == 0
        job = await _row(test_db_session, again)
        assert (job.status, job.user_metadata) == ("pending", untouched)

    async def test_a_dry_run_claims_nothing(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        job_id = await _upload(client, editor_auth_header)
        before = await _row(test_db_session, job_id)
        untouched = (before.status, dict(before.user_metadata), before.attempt_id)

        result = await _apply(
            client,
            editor_auth_header,
            _manifest(
                _entry("web-preview", job_id, _checksum(_ORIGINAL)), dry_run=True
            ),
        )

        assert (result["action"], result["job_id"], result["queued"]) == (
            "create",
            None,
            0,
        )
        job = await _row(test_db_session, job_id)
        assert (job.status, job.user_metadata, job.attempt_id) == untouched

    async def test_the_staged_upload_survives_a_sweep_after_the_claim(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        import app.platform.jobs.local_staging_reconcile as reconcile
        from app.platform.jobs.sweep import fail_stale_jobs

        job_id = await _upload(client, editor_auth_header)
        await _apply(
            client,
            editor_auth_header,
            _manifest(_entry("web-sweep", job_id, _checksum(_ORIGINAL))),
        )
        staged = Path((await _row(test_db_session, job_id)).file_path)
        now = datetime.now(timezone.utc)
        aged = (
            now - timedelta(seconds=settings.staging_orphan_min_age_seconds + 3600)
        ).timestamp()
        os.utime(staged, (aged, aged))

        await fail_stale_jobs(test_db_session)
        reconcile._resume_after = None
        await reconcile.reconcile_orphaned_local_uploads(test_db_session, now=now)
        await test_db_session.commit()

        assert staged.exists()
        job = await _row(test_db_session, job_id)
        assert (job.status, job.file_path) == ("pending", str(staged))


class TestRefusals:
    async def test_another_users_upload_answers_like_an_unknown_id(
        self,
        client: AsyncClient,
        admin_auth_header,
        editor_auth_header,
        test_db_session,
        clean_tables,
    ):
        job_id = await _upload(client, editor_auth_header)
        before = await _row(test_db_session, job_id)
        untouched = (before.status, dict(before.user_metadata))

        # Even an admin, with the right checksum, can't take someone's upload.
        answers = await _answers(
            client, admin_auth_header, "web-other", job_id, _checksum(_ORIGINAL)
        )

        assert answers == await _unknown_answers(client, admin_auth_header, "web-other")
        assert {a["message"] for a in answers} == {UPLOAD_SOURCE_UNAVAILABLE}
        job = await _row(test_db_session, job_id)
        assert (job.status, job.user_metadata) == untouched

    async def test_an_expired_upload_answers_like_an_unknown_id(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        job_id = await _upload(client, editor_auth_header)
        old = datetime.now(timezone.utc) - timedelta(
            seconds=settings.pending_job_timeout_seconds + 60
        )
        await test_db_session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_id)
            .values(
                created_at=old,
                user_metadata=IngestJob.user_metadata.op("||")(
                    text(f"""'{{"staged_at": "{old.isoformat()}"}}'::jsonb""")
                ),
            )
        )
        await test_db_session.commit()

        answers = await _answers(
            client, editor_auth_header, "web-expired", job_id, _checksum(_ORIGINAL)
        )

        assert answers == await _unknown_answers(
            client, editor_auth_header, "web-expired"
        )
        assert (await _row(test_db_session, job_id)).status == "pending"

    async def test_an_upload_is_claimed_once(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        job_id = await _upload(client, editor_auth_header)
        checksum = _checksum(_ORIGINAL)
        first = await _apply(
            client, editor_auth_header, _manifest(_entry("web-first", job_id, checksum))
        )
        assert first["action"] == "create"

        answers = await _answers(
            client, editor_auth_header, "web-second", job_id, checksum
        )

        assert answers == await _unknown_answers(
            client, editor_auth_header, "web-second"
        )
        job = await _row(test_db_session, job_id)
        assert job.user_metadata["manifest_key"] == "web-first"
        # The same entry sent again is the apply already under way.
        retry = await _apply(
            client, editor_auth_header, _manifest(_entry("web-first", job_id, checksum))
        )
        assert (retry["action"], retry["job_id"], retry["queued"]) == (
            "skip",
            str(job_id),
            0,
        )

    async def test_a_wrong_checksum_is_refused_before_the_claim(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        job_id = await _upload(client, editor_auth_header)
        before = await _row(test_db_session, job_id)
        untouched = (before.status, dict(before.user_metadata))

        answers = await _answers(
            client, editor_auth_header, "web-mismatch", job_id, _checksum(_RESURVEYED)
        )

        assert [a["action"] for a in answers] == ["error", "error"]
        assert all(
            "does not match the source's checksum" in a["message"] for a in answers
        )
        assert [a["queued"] for a in answers] == [0, 0]
        job = await _row(test_db_session, job_id)
        assert (job.status, job.user_metadata) == untouched

    async def test_an_upload_of_another_kind_is_refused(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        job_id = await _upload(client, editor_auth_header)

        [preview, apply] = [
            await _apply(
                client,
                editor_auth_header,
                _manifest(
                    _entry(
                        "web-kind",
                        job_id,
                        _checksum(_ORIGINAL),
                        source_type="raster_cog",
                    ),
                    dry_run=dry_run,
                ),
            )
            for dry_run in (True, False)
        ]

        assert preview == apply
        assert apply["action"] == "error"
        assert "requires one of: .tif, .tiff" in apply["message"]


class TestClaimFence:
    """The claim's own conditions, held even when the read before it passed."""

    async def _pending_upload(self, session, owner: uuid.UUID) -> IngestJob:
        path = Path(settings.upload_staging_dir) / f"{uuid.uuid4()}_roads.geojson"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_ORIGINAL)
        job = IngestJob(
            status="pending",
            created_by=owner,
            source_filename="roads.geojson",
            file_path=str(path),
            user_metadata={"staged_at": datetime.now(timezone.utc).isoformat()},
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job

    async def _claim(self, session, job: IngestJob, owner: uuid.UUID, key: str):
        return await claim_upload(
            session,
            job_id=job.id,
            attempt_id=job.attempt_id,
            file_path=job.file_path,
            owner=owner,
            metadata={"manifest_key": key, "manifest_stage": "downloading"},
            dataset_id=None,
            source_layer=None,
        )

    async def test_the_claim_refuses_another_owner(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        admin = await get_user_id(test_db_session, "admin")
        editor = (await client.get("/auth/me/", headers=editor_auth_header)).json()
        job = await self._pending_upload(test_db_session, uuid.UUID(editor["id"]))
        job_id = job.id

        assert await self._claim(test_db_session, job, admin, "fence-owner") is None
        await test_db_session.rollback()
        assert (await _row(test_db_session, job_id)).status == "pending"

    async def test_the_claim_refuses_an_upload_already_claimed(
        self, test_db_session, clean_tables
    ):
        owner = await get_user_id(test_db_session, "admin")
        job = await self._pending_upload(test_db_session, owner)
        job_id = job.id
        claimed = await self._claim(test_db_session, job, owner, "fence-first")
        assert claimed is not None
        assert await bind_reservation_to_staged_source(
            test_db_session, claimed, file_path=claimed.file_path
        )
        await test_db_session.commit()
        assert (await _row(test_db_session, job_id)).status == "pending"

        again = await self._claim(test_db_session, claimed, owner, "fence-second")

        assert again is None
        await test_db_session.rollback()
        row = await _row(test_db_session, job_id)
        assert row.user_metadata["manifest_key"] == "fence-first"


@pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="needs ogr2ogr")
@pytest.mark.requires_ogr2ogr
async def test_a_schema_changing_replace_is_held_and_its_reapply_is_blocked(
    test_db_session, clean_tables, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
    user = await _admin(test_db_session)
    key = "upload-held"
    table = f"manifest_held_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        test_db_session,
        created_by=user.id,
        name="Roads",
        table_name=table,
        record_type="vector_dataset",
        geometry_type="POINT",
        feature_count=1,
        column_info=[
            {"name": "name", "type": "text"},
            {"name": "legacy", "type": "text"},
        ],
    )
    await test_db_session.execute(
        text(
            f'CREATE TABLE "data"."{table}" (gid serial PRIMARY KEY, '
            "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326), "
            "name text, legacy text)"
        )
    )
    original = ManifestApplyRequest.model_validate(
        _manifest(_entry(key, uuid.uuid4(), _checksum(_ORIGINAL), title="Roads"))
    ).datasets[0]
    test_db_session.add(
        IngestJob(
            dataset_id=dataset.id,
            source_filename="roads.geojson",
            created_by=user.id,
            status="complete",
            completed_at=datetime.now(timezone.utc),
            user_metadata={
                "manifest_key": key,
                MANIFEST_FINGERPRINT_METADATA_KEY: manifest_dataset_fingerprint(
                    original
                ),
            },
        )
    )
    await test_db_session.commit()
    upload = await TestClaimFence()._pending_upload(test_db_session, user.id)
    staged = Path(upload.file_path)
    staged.write_bytes(_RESURVEYED)
    resurveyed = ManifestApplyRequest.model_validate(
        _manifest(_entry(key, upload.id, _checksum(_RESURVEYED), title="Roads"))
    )

    with _reupload_task() as task:
        response = await apply_manifest(
            test_db_session, resurveyed, user, _http_request()
        )
    [result] = response.results
    assert (result.action, result.job_id) == ("update", upload.id), result.message
    await _run_worker(task)
    run = (
        await test_db_session.execute(
            select(DatasetRefreshRun)
            .where(DatasetRefreshRun.ingest_job_id == upload.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert run.status == "blocked"

    for dry_run in (True, False):
        with _reupload_task() as task:
            again = await apply_manifest(
                test_db_session,
                resurveyed.model_copy(update={"dry_run": dry_run}),
                user,
                _http_request(),
            )
        [result] = again.results
        assert result.action == "blocked", result.message
        assert (result.job_id, result.run_id) == (upload.id, run.id)
        assert result.review_reasons == ["destructive_schema_change"]
        task.defer_async.assert_not_awaited()


async def test_an_upload_source_is_open_to_its_owner_in_multi_tenant_mode(
    test_db_session, clean_tables, monkeypatch, tmp_path
):
    """The raw-seed gate refuses local paths there; an owned upload is not one."""
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
    user = await _admin(test_db_session)
    upload = await TestClaimFence()._pending_upload(test_db_session, user.id)
    request = ManifestApplyRequest.model_validate(
        _manifest(_entry("tenant-upload", upload.id, _checksum(_ORIGINAL)))
    )

    with (
        patch("app.core.tenancy.is_multi_tenant", return_value=True),
        patch(
            "app.processing.ingest.manifest_service.queue_ingest_job", new=AsyncMock()
        ) as queue,
    ):
        response = await apply_manifest(test_db_session, request, user, _http_request())

    [result] = response.results
    assert (result.action, result.job_id) == ("create", upload.id), result.message
    queue.assert_awaited_once()


class TestSchema:
    def _payload(self, **changes) -> dict:
        payload = _manifest(_entry("schema", uuid.uuid4(), _checksum(_ORIGINAL)))
        payload.update(changes)
        return payload

    def test_version_2_takes_an_upload_source(self):
        request = ManifestApplyRequest.model_validate(self._payload())
        assert request.datasets[0].sources[0].uri.startswith("upload:")

    def test_an_upload_source_needs_its_checksum(self):
        payload = self._payload()
        del payload["datasets"][0]["sources"][0]["checksum"]
        with pytest.raises(ValidationError, match="requires checksum"):
            ManifestApplyRequest.model_validate(payload)

    def test_version_1_refuses_upload_sources_and_client(self):
        payload = self._payload(manifest_version="1")
        with pytest.raises(ValidationError, match="client requires manifest_version"):
            ManifestApplyRequest.model_validate(payload)
        del payload["client"]
        with pytest.raises(ValidationError, match="upload: sources require"):
            ManifestApplyRequest.model_validate(payload)

    def test_version_2_requires_client(self):
        payload = self._payload()
        del payload["client"]
        with pytest.raises(ValidationError, match="requires client"):
            ManifestApplyRequest.model_validate(payload)

    @pytest.mark.parametrize(
        "uri",
        [
            "upload:not-a-job-id",
            "upload:" + "-" * 36,
            "upload:" + str(uuid.uuid4()).upper(),
            "upload:" + str(uuid.uuid4()) + "\n",
            "upload:../" + str(uuid.uuid4()),
        ],
    )
    def test_an_upload_uri_names_one_canonical_job_id(self, uri: str):
        payload = self._payload()
        payload["datasets"][0]["sources"][0]["uri"] = uri
        with pytest.raises(ValidationError):
            ManifestApplyRequest.model_validate(payload)

    def test_the_fingerprint_counts_the_checksum_not_the_job(self):
        def entry(job_id, checksum):
            payload = _manifest(_entry("schema", job_id, checksum))
            return ManifestApplyRequest.model_validate(payload).datasets[0]

        same = _checksum(_ORIGINAL)
        assert manifest_dataset_fingerprint(
            entry(uuid.uuid4(), same)
        ) == manifest_dataset_fingerprint(entry(uuid.uuid4(), same))
        assert manifest_dataset_fingerprint(
            entry(uuid.uuid4(), same)
        ) != manifest_dataset_fingerprint(entry(uuid.uuid4(), _checksum(_RESURVEYED)))


class TestStagedBytes:
    async def test_a_staging_key_is_read_through_storage_for_the_tenant(self):
        chunks = [_ORIGINAL[:100], _ORIGINAL[100:]]
        read: list[str] = []

        class _Storage:
            async def get_stream(self, key: str):
                read.append(key)
                for chunk in chunks:
                    yield chunk

        with (
            patch("app.platform.storage.get_storage", return_value=_Storage()),
            patch(
                "app.platform.storage.titiler_url.resolve_current_storage_key",
                side_effect=lambda key: f"tenants/t1/{key}",
            ),
        ):
            digest, size = await manifest_sources._staged_upload_sha256(
                "staging/job/capitals.geojson"
            )

        assert ("sha256:" + digest, size) == (_checksum(_ORIGINAL), len(_ORIGINAL))
        assert read == ["tenants/t1/staging/job/capitals.geojson"]

    async def test_a_local_path_outside_staging_is_not_read(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path / "staging"))
        outside = tmp_path / "elsewhere.geojson"
        outside.write_bytes(_ORIGINAL)

        with pytest.raises(RuntimeError):
            await manifest_sources._staged_upload_sha256(str(outside))
