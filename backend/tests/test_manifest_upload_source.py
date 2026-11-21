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


async def _staged_row(
    session,
    owner: uuid.UUID,
    *,
    metadata: dict | None = None,
    **columns,
) -> IngestJob:
    """A pending row naming a staged copy of the fixture, as the upload door leaves one."""
    path = Path(settings.upload_staging_dir) / f"{uuid.uuid4()}_roads.geojson"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_ORIGINAL)
    job = IngestJob(
        **{
            "status": "pending",
            "created_by": owner,
            "source_filename": "roads.geojson",
            "file_path": str(path),
            "user_metadata": {
                "staged_at": datetime.now(timezone.utc).isoformat(),
                **(metadata or {}),
            },
            **columns,
        }
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _user_id(client: AsyncClient, headers: dict) -> uuid.UUID:
    return uuid.UUID((await client.get("/auth/me/", headers=headers)).json()["id"])


async def _owned_dataset(session, owner: uuid.UUID) -> uuid.UUID:
    dataset = await create_dataset(
        session,
        created_by=owner,
        name="Existing",
        table_name=f"manifest_existing_{uuid.uuid4().hex[:10]}",
        record_type="vector_dataset",
        geometry_type="POINT",
        feature_count=1,
        column_info=[{"name": "name", "type": "text"}],
    )
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

    async def test_replaying_an_applied_upload_says_so_without_cancel_advice(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        job_id = await _upload(client, editor_auth_header)
        manifest = _manifest(_entry("web-replay", job_id, _checksum(_ORIGINAL)))
        await _apply(client, editor_auth_header, manifest)
        editor = (await _row(test_db_session, job_id)).created_by
        await _complete(test_db_session, job_id, editor)

        result = await _apply(client, editor_auth_header, manifest)

        assert (result["action"], result["job_id"], result["queued"]) == (
            "skip",
            str(job_id),
            0,
        )
        assert "already applied" in result["message"]
        assert "Cancel" not in result["message"]

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

    async def _pending_upload(self, session, owner: uuid.UUID, **fields) -> IngestJob:
        return await _staged_row(session, owner, **fields)

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

    async def test_the_claim_refuses_a_different_file(
        self, test_db_session, clean_tables
    ):
        owner = await get_user_id(test_db_session, "admin")
        job = await self._pending_upload(test_db_session, owner)
        job_id = job.id

        assert (
            await claim_upload(
                test_db_session,
                job_id=job_id,
                attempt_id=job.attempt_id,
                file_path=job.file_path + ".other",
                owner=owner,
                metadata={"manifest_key": "fence-file"},
                dataset_id=None,
                source_layer=None,
            )
            is None
        )
        await test_db_session.rollback()
        assert (await _row(test_db_session, job_id)).status == "pending"

    async def test_the_claim_refuses_an_attempt_a_retry_replaced(
        self, test_db_session, clean_tables
    ):
        owner = await get_user_id(test_db_session, "admin")
        job = await self._pending_upload(test_db_session, owner)
        job_id, checked_attempt, file_path = job.id, job.attempt_id, job.file_path
        await test_db_session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_id)
            .values(attempt_id=uuid.uuid4())
        )
        await test_db_session.commit()

        claimed = await claim_upload(
            test_db_session,
            job_id=job_id,
            attempt_id=checked_attempt,
            file_path=file_path,
            owner=owner,
            metadata={"manifest_key": "fence-attempt"},
            dataset_id=None,
            source_layer=None,
        )

        assert claimed is None
        await test_db_session.rollback()
        assert (await _row(test_db_session, job_id)).status == "pending"

    async def test_the_claim_refuses_a_reupload_row(
        self, test_db_session, clean_tables
    ):
        owner = await get_user_id(test_db_session, "admin")
        dataset_id = await _owned_dataset(test_db_session, owner)
        job = await self._pending_upload(
            test_db_session,
            owner,
            dataset_id=dataset_id,
            metadata={"reupload": True, "dataset_id": str(dataset_id)},
        )
        job_id = job.id

        assert await self._claim(test_db_session, job, owner, "fence-reupload") is None
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
@pytest.mark.parametrize("uploaded_before_publish", [False, True])
async def test_a_schema_changing_replace_is_held_and_its_reapply_is_blocked(
    test_db_session, clean_tables, monkeypatch, tmp_path, uploaded_before_publish
):
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
    user = await _admin(test_db_session)
    if uploaded_before_publish:
        # The replacement's file was uploaded before the import it replaces.
        upload = await _staged_row(test_db_session, user.id)
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
    if not uploaded_before_publish:
        upload = await _staged_row(test_db_session, user.id)
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

    @pytest.mark.parametrize(
        ("version", "client", "valid"),
        [
            ("1", "omitted", True),
            ("1", None, False),
            ("1", _CLIENT, False),
            ("2", None, False),
            ("2", _CLIENT, True),
        ],
    )
    def test_client_is_decided_by_whether_it_was_sent(self, version, client, valid):
        payload = {
            "manifest_version": version,
            "catalog": {"title": "Catalog"},
            "datasets": [
                {
                    "key": "roads",
                    "title": "Roads",
                    "sources": [
                        {"type": "vector", "uri": "https://example.com/roads.fgb"}
                    ],
                    "publication": {"intent": "draft"},
                }
            ],
        }
        if client != "omitted":
            payload["client"] = client
        if valid:
            ManifestApplyRequest.model_validate(payload)
        else:
            with pytest.raises(ValidationError, match="client"):
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

    async def test_a_symlink_out_of_staging_is_not_read(self, monkeypatch, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()
        monkeypatch.setattr(settings, "upload_staging_dir", str(staging))
        outside = tmp_path / "elsewhere.geojson"
        outside.write_bytes(_ORIGINAL)
        link = staging / f"{uuid.uuid4()}_roads.geojson"
        link.symlink_to(outside)

        with pytest.raises(RuntimeError):
            await manifest_sources._staged_upload_sha256(str(link))

    async def test_a_local_path_outside_staging_is_not_read(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path / "staging"))
        outside = tmp_path / "elsewhere.geojson"
        outside.write_bytes(_ORIGINAL)

        with pytest.raises(RuntimeError):
            await manifest_sources._staged_upload_sha256(str(outside))


_COMMIT_QUEUE = "app.processing.ingest.router.queue_ingest_job"


class TestNotAPlainUpload:
    @pytest.mark.parametrize(
        "shape",
        ["reupload", "refresh", "dataset_column", "url_import", "database_import"],
    )
    async def test_a_row_that_is_not_a_plain_upload_answers_like_an_unknown_id(
        self,
        client: AsyncClient,
        editor_auth_header,
        test_db_session,
        clean_tables,
        shape: str,
    ):
        editor = await _user_id(client, editor_auth_header)
        if shape in ("reupload", "dataset_column"):
            dataset_id = await _owned_dataset(test_db_session, editor)
        fields = {
            "reupload": lambda: {
                "dataset_id": dataset_id,
                "metadata": {"reupload": True, "dataset_id": str(dataset_id)},
            },
            "refresh": lambda: {"metadata": {"refresh": True}},
            "dataset_column": lambda: {"dataset_id": dataset_id},
            "url_import": lambda: {"source_url": "https://example.com/roads.geojson"},
            "database_import": lambda: {
                "metadata": {
                    "database_source": {"connection": "c", "schema": "s", "table": "t"}
                }
            },
        }[shape]()
        row = await _staged_row(test_db_session, editor, **fields)
        job_id, untouched = row.id, (row.status, dict(row.user_metadata))

        answers = await _answers(
            client, editor_auth_header, "web-shape", job_id, _checksum(_ORIGINAL)
        )

        assert answers == await _unknown_answers(
            client, editor_auth_header, "web-shape"
        )
        job = await _row(test_db_session, job_id)
        assert (job.status, job.user_metadata) == untouched

    async def test_an_upload_committed_through_the_import_door_answers_like_an_unknown_id(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        job_id = await _upload(client, editor_auth_header)
        with patch(_COMMIT_QUEUE, new=AsyncMock()):
            commit = await client.post(
                f"/ingest/commit/{job_id}",
                json={"title": "Committed"},
                headers=editor_auth_header,
            )
        assert commit.status_code == 202, commit.text

        answers = await _answers(
            client, editor_auth_header, "web-committed", job_id, _checksum(_ORIGINAL)
        )

        assert answers == await _unknown_answers(
            client, editor_auth_header, "web-committed"
        )
        assert "manifest_key" not in (await _row(test_db_session, job_id)).user_metadata


class TestDuringTheCheck:
    async def test_a_cancel_between_the_hash_and_the_claim_claims_nothing(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        import app.core.db as db_module
        from app.platform.jobs import ledger

        job_id = await _upload(client, editor_auth_header)
        real_hash = manifest_sources._staged_upload_sha256

        async def _hash_then_cancel(file_path: str):
            result = await real_hash(file_path)
            async with db_module.async_session() as other:
                job = await other.get(IngestJob, job_id)
                await ledger.cancel(other, job, actor=job.created_by)
                await other.commit()
            return result

        with patch.object(manifest_sources, "_staged_upload_sha256", _hash_then_cancel):
            result = await _apply(
                client,
                editor_auth_header,
                _manifest(_entry("web-cancelled", job_id, _checksum(_ORIGINAL))),
            )

        assert (result["action"], result["message"], result["queued"]) == (
            "error",
            UPLOAD_SOURCE_UNAVAILABLE,
            0,
        )
        job = await _row(test_db_session, job_id)
        assert job.status == "cancelled"
        assert "manifest_key" not in job.user_metadata

    async def test_the_upload_is_hashed_with_no_connection_or_key_held(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        import app.core.db as db_module

        job_id = await _upload(client, editor_auth_header)
        released: list[bool] = []
        seen_while_hashing: dict[str, object] = {}
        real_release = manifest_sources.release_connection
        real_hash = manifest_sources._staged_upload_sha256

        async def _release(db):
            await real_release(db)
            released.append(db.in_transaction())

        async def _probing_hash(file_path: str):
            seen_while_hashing["released"] = list(released)
            async with db_module.async_session() as other:
                seen_while_hashing["key_free"] = await other.scalar(
                    text(
                        "SELECT pg_try_advisory_xact_lock("
                        "hashtextextended('manifest_apply:web-probed', 0))"
                    )
                )
                await other.rollback()
            return await real_hash(file_path)

        with (
            patch.object(manifest_sources, "release_connection", _release),
            patch.object(manifest_sources, "_staged_upload_sha256", _probing_hash),
        ):
            result = await _apply(
                client,
                editor_auth_header,
                _manifest(_entry("web-probed", job_id, _checksum(_ORIGINAL))),
            )

        assert result["action"] == "create", result["message"]
        # The connection went back to the pool and the key was free while it read.
        assert seen_while_hashing == {"released": [False], "key_free": True}

    async def test_the_checksum_time_limit_ends_the_entry_holding_nothing(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        import asyncio

        import app.core.db as db_module

        job_id = await _upload(client, editor_auth_header)
        untouched = dict((await _row(test_db_session, job_id)).user_metadata)

        async def _slow_hash(file_path: str):
            await asyncio.sleep(5)

        with (
            patch.object(manifest_sources, "UPLOAD_CHECKSUM_MAX_SECONDS", 0.5),
            patch.object(manifest_sources, "_staged_upload_sha256", _slow_hash),
        ):
            result = await _apply(
                client,
                editor_auth_header,
                _manifest(_entry("web-slow", job_id, _checksum(_ORIGINAL))),
            )

        assert result["action"] == "error"
        assert "within 0.5 seconds" in result["message"]
        job = await _row(test_db_session, job_id)
        assert (job.status, job.user_metadata) == ("pending", untouched)
        async with db_module.async_session() as other:
            assert await other.scalar(
                text(
                    "SELECT pg_try_advisory_xact_lock("
                    "hashtextextended('manifest_apply:web-slow', 0))"
                )
            )
            await other.rollback()

    async def test_an_upload_that_expires_during_the_hash_is_not_claimed(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        import app.core.db as db_module

        job_id = await _upload(client, editor_auth_header)
        real_hash = manifest_sources._staged_upload_sha256
        old = datetime.now(timezone.utc) - timedelta(
            seconds=settings.pending_job_timeout_seconds + 60
        )

        async def _hash_then_expire(file_path: str):
            result = await real_hash(file_path)
            async with db_module.async_session() as other:
                await other.execute(
                    update(IngestJob)
                    .where(IngestJob.id == job_id)
                    .values(
                        created_at=old,
                        user_metadata=IngestJob.user_metadata.op("||")(
                            text(f"""'{{"staged_at": "{old.isoformat()}"}}'::jsonb""")
                        ),
                    )
                )
                await other.commit()
            return result

        with patch.object(manifest_sources, "_staged_upload_sha256", _hash_then_expire):
            result = await _apply(
                client,
                editor_auth_header,
                _manifest(_entry("web-late", job_id, _checksum(_ORIGINAL))),
            )

        assert (result["action"], result["message"], result["queued"]) == (
            "error",
            UPLOAD_SOURCE_UNAVAILABLE,
            0,
        )
        job = await _row(test_db_session, job_id)
        assert job.status == "pending"
        assert "manifest_key" not in job.user_metadata

    async def test_a_storage_error_while_hashing_is_not_echoed(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        job_id = await _upload(client, editor_auth_header)
        leak = "https://minio.internal:9000/geolens/tenants/t1/staging/secret.geojson"

        class _StorageError(Exception):
            pass

        with patch.object(
            manifest_sources,
            "_staged_upload_sha256",
            new=AsyncMock(side_effect=_StorageError(leak)),
        ):
            answers = await _answers(
                client, editor_auth_header, "web-storage", job_id, _checksum(_ORIGINAL)
            )

        assert {a["message"] for a in answers} == {manifest_sources.UPLOAD_READ_FAILED}
        assert all("minio" not in str(a) for a in answers)

    async def test_one_upload_named_twice_is_refused_before_any_read(
        self, client: AsyncClient, editor_auth_header, clean_tables
    ):
        job_id = await _upload(client, editor_auth_header)
        checksum = _checksum(_ORIGINAL)
        hashing = AsyncMock(return_value=("0" * 64, 1))

        with patch.object(manifest_sources, "_staged_upload_sha256", hashing):
            response = await client.post(
                "/ingest/manifest/apply",
                json=_manifest(
                    *(_entry(f"web-twice-{n}", job_id, checksum) for n in range(50)),
                    dry_run=True,
                ),
                headers=editor_auth_header,
            )

        assert response.status_code == 422
        assert f"duplicate upload source(s): upload:{job_id}" in response.text
        hashing.assert_not_awaited()


class TestFanOut:
    async def _fan_out(self, client, headers, job_id):
        with patch(
            "app.platform.jobs.defer_guard.defer_with_orphan_guard", new=AsyncMock()
        ):
            return await client.post(
                f"/ingest/commit-fan-out/{job_id}",
                json={"layers": [{"layer_name": "capitals"}]},
                headers=headers,
            )

    async def _layers_previewed(self, session, job_id):
        await session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_id)
            .values(
                user_metadata=IngestJob.user_metadata.op("||")(
                    text("""'{"all_layers": ["capitals"]}'::jsonb""")
                )
            )
        )
        await session.commit()

    async def _children(self, session, job_id) -> int:
        return await session.scalar(
            select(func.count())
            .select_from(IngestJob)
            .where(IngestJob.user_metadata["fan_out_parent_id"].astext == str(job_id))
        )

    async def test_an_upload_a_manifest_claimed_cannot_fan_out(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        job_id = await _upload(client, editor_auth_header)
        await self._layers_previewed(test_db_session, job_id)
        await _apply(
            client,
            editor_auth_header,
            _manifest(_entry("web-fan", job_id, _checksum(_ORIGINAL))),
        )

        response = await self._fan_out(client, editor_auth_header, job_id)

        assert response.status_code == 409, response.text
        assert (await _row(test_db_session, job_id)).status == "pending"
        assert await self._children(test_db_session, job_id) == 0

    async def test_an_upload_committed_through_the_import_door_cannot_fan_out(
        self, client: AsyncClient, editor_auth_header, test_db_session, clean_tables
    ):
        job_id = await _upload(client, editor_auth_header)
        await self._layers_previewed(test_db_session, job_id)
        with patch(_COMMIT_QUEUE, new=AsyncMock()):
            commit = await client.post(
                f"/ingest/commit/{job_id}",
                json={"title": "Committed"},
                headers=editor_auth_header,
            )
        assert commit.status_code == 202, commit.text

        response = await self._fan_out(client, editor_auth_header, job_id)

        assert response.status_code == 409, response.text
        assert await self._children(test_db_session, job_id) == 0


async def test_recovery_never_adopts_a_claim_another_request_made(
    test_db_session, clean_tables, monkeypatch, tmp_path
):
    """A's claim is lost and B claims the upload before A reads the row back."""
    import app.core.db as db_module

    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
    user = await _admin(test_db_session)
    upload = await _staged_row(test_db_session, user.id)
    upload_id = upload.id
    request = ManifestApplyRequest.model_validate(
        _manifest(_entry("claim-a", upload_id, _checksum(_ORIGINAL)))
    )

    async def _lost_then_claimed_by_b(db) -> None:
        await (await db.connection()).rollback()
        async with db_module.async_session() as other:
            row = await other.get(IngestJob, upload_id)
            assert await claim_upload(
                other,
                job_id=upload_id,
                attempt_id=row.attempt_id,
                file_path=row.file_path,
                owner=user.id,
                metadata={"manifest_key": "claim-b", "manifest_stage": "downloading"},
                dataset_id=None,
                source_layer=None,
            )
            await other.commit()
        raise RuntimeError("connection reset")

    with (
        patch(
            "app.processing.ingest.manifest_service._commit_reservation",
            new=_lost_then_claimed_by_b,
        ),
        patch(
            "app.processing.ingest.manifest_service.queue_ingest_job", new=AsyncMock()
        ) as queue,
    ):
        response = await apply_manifest(test_db_session, request, user, _http_request())

    [result] = response.results
    assert result.action == "error"
    queue.assert_not_awaited()
    job = await _row(test_db_session, upload_id)
    assert job.status == "running"
    assert job.user_metadata["manifest_key"] == "claim-b"
    assert job.user_metadata["manifest_stage"] == "downloading"


async def test_a_fan_out_that_read_the_upload_before_a_claim_writes_nothing(
    client: AsyncClient, editor_auth_header, test_db_session, clean_tables
):
    """The route merges its portal link into a copy read before the claim landed."""
    import app.core.db as db_module
    import app.modules.catalog.authorization as authorization

    job_id = await _upload(client, editor_auth_header)
    await TestFanOut()._layers_previewed(test_db_session, job_id)
    real_gate = authorization.check_public_visibility_allowed

    async def _claimed_meanwhile(db, user, visibility):
        async with db_module.async_session() as other:
            row = await other.get(IngestJob, job_id)
            claimed = await claim_upload(
                other,
                job_id=job_id,
                attempt_id=row.attempt_id,
                file_path=row.file_path,
                owner=row.created_by,
                metadata={"manifest_key": "web-raced", "manifest_stage": "downloading"},
                dataset_id=None,
                source_layer=None,
            )
            assert await bind_reservation_to_staged_source(
                other, claimed, file_path=claimed.file_path
            )
            await other.commit()
        return await real_gate(db, user, visibility)

    with (
        patch.object(
            authorization, "check_public_visibility_allowed", _claimed_meanwhile
        ),
        patch("app.platform.jobs.defer_guard.defer_with_orphan_guard", new=AsyncMock()),
    ):
        response = await client.post(
            f"/ingest/commit-fan-out/{job_id}",
            json={
                "layers": [{"layer_name": "capitals"}],
                "item_id": "0123456789abcdef0123456789abcdef",
            },
            headers=editor_auth_header,
        )

    assert response.status_code == 409, response.text
    job = await _row(test_db_session, job_id)
    assert job.status == "pending"
    assert job.user_metadata["manifest_key"] == "web-raced"
    assert job.user_metadata[COMMIT_ATTEMPTED_METADATA_KEY]
    assert "item_id" not in job.user_metadata


async def test_a_retry_and_a_manifest_apply_never_both_take_an_upload(
    client: AsyncClient, editor_auth_header, test_db_session, clean_tables
):
    """A manifest apply lands between a retry's commit and its dispatch."""
    import app.core.db as db_module
    from app.modules.auth.models import User
    from app.platform.jobs.defer_guard import stamp_commit_attempted

    editor = await _user_id(client, editor_auth_header)
    failed = await _staged_row(
        test_db_session,
        editor,
        status="failed",
        error_message="Stale: upload completed but never committed",
        completed_at=datetime.now(timezone.utc),
    )
    job_id = failed.id
    request = ManifestApplyRequest.model_validate(
        _manifest(_entry("web-retried", job_id, _checksum(_ORIGINAL)))
    )
    applied: list = []

    async def _applied_then_dispatched(job, user_id, *, db, **kwargs):
        async with db_module.async_session() as other:
            user = await other.get(User, editor)
            response = await apply_manifest(other, request, user, _http_request())
            applied.extend(response.results)
        await stamp_commit_attempted(job, db=db)

    with (
        patch(
            "app.platform.jobs.router.queue_ingest_job",
            side_effect=_applied_then_dispatched,
        ),
        patch(
            "app.processing.ingest.manifest_service.queue_ingest_job", new=AsyncMock()
        ) as manifest_queue,
    ):
        retried = await client.post(f"/jobs/{job_id}/retry", headers=editor_auth_header)

    assert retried.status_code == 202, retried.text
    [result] = applied
    assert (result.action, result.message) == ("error", UPLOAD_SOURCE_UNAVAILABLE)
    manifest_queue.assert_not_awaited()
    job = await _row(test_db_session, job_id)
    assert job.status == "pending"
    assert "manifest_key" not in job.user_metadata
    assert job.user_metadata[COMMIT_ATTEMPTED_METADATA_KEY]


async def test_a_dispatch_stamp_from_a_copy_read_before_a_claim_keeps_the_claim(
    test_db_session, clean_tables, monkeypatch, tmp_path
):
    import app.core.db as db_module
    from app.platform.jobs.defer_guard import stamp_commit_attempted

    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
    owner = await get_user_id(test_db_session, "admin")
    stale = await _staged_row(test_db_session, owner)
    job_id = stale.id
    async with db_module.async_session() as other:
        row = await other.get(IngestJob, job_id)
        claimed = await claim_upload(
            other,
            job_id=job_id,
            attempt_id=row.attempt_id,
            file_path=row.file_path,
            owner=owner,
            metadata={
                "manifest_key": "stamp-raced",
                MANIFEST_FINGERPRINT_METADATA_KEY: "f" * 64,
                "manifest_stage": "downloading",
            },
            dataset_id=None,
            source_layer=None,
        )
        await other.commit()
        assert claimed is not None

    await stamp_commit_attempted(stale, db=test_db_session)
    await test_db_session.commit()

    job = await _row(test_db_session, job_id)
    assert job.status == "running"
    assert job.user_metadata["manifest_key"] == "stamp-raced"
    assert job.user_metadata[MANIFEST_FINGERPRINT_METADATA_KEY] == "f" * 64
    assert job.user_metadata["manifest_stage"] == "downloading"


class TestJsonNullMetadata:
    """A row created with None holds JSON null, which a merge must treat as empty."""

    async def _json_null(self, session, job_id) -> None:
        await session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_id)
            .values(user_metadata=text("'null'::jsonb"))
        )
        await session.commit()

    async def test_a_retry_leaves_an_object_carrying_the_dispatch_marker(
        self, test_db_session, clean_tables, monkeypatch, tmp_path
    ):
        from app.platform.jobs import ledger
        from app.platform.jobs.models import dispatch_attempted

        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
        owner = await get_user_id(test_db_session, "admin")
        job = await _staged_row(test_db_session, owner, status="failed")
        job_id = job.id
        await self._json_null(test_db_session, job_id)
        job = await _row(test_db_session, job_id)

        assert await ledger.retry(test_db_session, job) is ledger.Outcome.LANDED
        await test_db_session.commit()

        row = await _row(test_db_session, job_id)
        assert isinstance(row.user_metadata, dict)
        assert row.user_metadata["staged_at"]
        assert await test_db_session.scalar(
            select(dispatch_attempted()).where(IngestJob.id == job_id)
        )

    async def test_a_claim_leaves_an_object_carrying_the_manifest_fields(
        self, test_db_session, clean_tables, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
        owner = await get_user_id(test_db_session, "admin")
        job = await _staged_row(test_db_session, owner)
        job_id, attempt_id, file_path = job.id, job.attempt_id, job.file_path
        await self._json_null(test_db_session, job_id)

        claimed = await claim_upload(
            test_db_session,
            job_id=job_id,
            attempt_id=attempt_id,
            file_path=file_path,
            owner=owner,
            metadata={"manifest_key": "null-claim"},
            dataset_id=None,
            source_layer=None,
        )
        await test_db_session.commit()

        assert claimed is not None
        row = await _row(test_db_session, job_id)
        assert isinstance(row.user_metadata, dict)
        assert row.user_metadata["manifest_key"] == "null-claim"
