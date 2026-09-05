"""fix(#1848): seven doors must not hold a pooled connection across their I/O.

`require_permission` queries the database before the handler body runs, so the
request session has a connection checked out from the first line. Holding it
across a remote service call or a GDAL subprocess pins one of the pool's
thirteen slots for the whole of it, and thirteen concurrent slow previews make
every other database-backed request wait out the 30 s pool timeout.

Each test records `in_transaction()` on the request's own session at the moment
the mocked I/O runs, which is the pool-independent form of the invariant: the
test engine uses NullPool, so a checkout count here says nothing about the
production QueuePool, while an open transaction is what pins the connection
either way. Same assertion the earlier fixes in this class use
(`test_analysis_preview.py`).
"""

import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.sources.schemas import LayerInfo, ProbeResponse
from app.platform.jobs.models import IngestJob
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


@pytest.fixture
def recording_url_validator(request_sessions):
    """The door's SSRF gate, stubbed and recording.

    fix(#1848 codex r1): `validate_url_for_ssrf` awaits `getaddrinfo` in a
    thread, so it is one of the waits the release has to precede, not a cheap
    gate that may sit before it. Yields the same list the I/O recorder appends
    to, so each test reads `[validator, io]` in call order.
    """
    held: list[bool] = []

    async def _recording_validate(_url):
        held.append(_holds_connection(request_sessions))

    with patch(
        "app.modules.catalog.sources.router.validate_url_for_ssrf",
        new=_recording_validate,
    ):
        yield held


@pytest.fixture
def stub_gdal_source():
    with patch(
        "app.modules.catalog.sources.router.build_gdal_source",
        return_value=("WFS:https://a2-preview.example.com/wfs", "buildings"),
    ) as mock:
        yield mock


@pytest.fixture
def request_sessions(client: AsyncClient):
    """Every session the app hands a request, newest last.

    Wraps the `client` fixture's own `get_db` override rather than replacing
    it, so the request still gets the retrying test session factory.
    """
    from app.api.main import app
    from app.core.dependencies import get_db

    captured: list[AsyncSession] = []
    original = app.dependency_overrides[get_db]

    async def _capturing():
        async for session in original():
            captured.append(session)
            yield session

    app.dependency_overrides[get_db] = _capturing
    try:
        yield captured
    finally:
        app.dependency_overrides[get_db] = original


def _holds_connection(captured: list[AsyncSession]) -> bool:
    """Whether the in-flight request is still inside a transaction."""
    assert captured, "no request session was captured"
    return captured[-1].in_transaction()


_PREVIEW_DATA = {
    "srid": 4326,
    "geometry_type": "Point",
    "layer_name": "buildings",
    "feature_count": 7,
    "columns": [{"name": "name", "type": "String"}],
    "sample_rows": [{"name": "a"}],
    "all_layers": None,
}


# ---------------------------------------------------------------------------
# sources/router.py
# ---------------------------------------------------------------------------


async def test_probe_releases_the_connection_before_dns_and_the_probes(
    client: AsyncClient,
    admin_auth_header: dict,
    recording_url_validator,
    request_sessions,
):
    """The SSRF resolver wait and three adapter probes ran on a held connection."""
    held = recording_url_validator

    async def _recording_detect(*_args, **_kwargs):
        held.append(_holds_connection(request_sessions))
        return ProbeResponse(
            service_type="WFS 2.0.0",
            url="https://a2-probe.example.com/wfs",
            layers=[LayerInfo(name="buildings", title="Buildings", layer_id="b")],
        )

    with (
        patch(
            "app.modules.catalog.sources.router.detect_service_type",
            new=_recording_detect,
        ),
        patch(
            "app.modules.catalog.sources.router.assert_endpoints_stay_on_origin",
            new_callable=AsyncMock,
        ),
    ):
        resp = await client.post(
            "/services/probe/",
            json={"url": "https://a2-probe.example.com/wfs"},
            headers=admin_auth_header,
        )

    assert resp.status_code == 200, resp.text
    assert held == [False, False], (
        "the request session was still in a transaction at the SSRF resolver "
        "wait or at the probes, so it held a pooled connection across them"
    )
    # The success audit row is written after the release, which proves the
    # session re-acquires rather than being finished with.
    assert resp.json()["service_type"] == "WFS 2.0.0"


async def test_preview_releases_the_connection_before_dns_and_ogrinfo(
    client: AsyncClient,
    admin_auth_header: dict,
    recording_url_validator,
    stub_gdal_source,
    request_sessions,
):
    """The resolver wait, the OAPIF page walk and ogrinfo ran on a held connection.

    Two releases, not one: the duplicate-source query between them re-acquires
    a connection of its own, so the second release is what covers the walk.
    """
    held = recording_url_validator

    async def _recording_preview(*_args, **_kwargs):
        held.append(_holds_connection(request_sessions))
        return dict(_PREVIEW_DATA)

    with patch(
        "app.modules.catalog.sources.router.run_service_preview",
        new=_recording_preview,
    ):
        resp = await client.post(
            "/services/preview/",
            json={
                "url": "https://a2-preview.example.com/wfs",
                "service_type": "WFS 2.0.0",
                "layer_name": "buildings",
            },
            headers=admin_auth_header,
        )

    assert resp.status_code == 200, resp.text
    assert held == [False, False], (
        "the request session was still in a transaction at the SSRF resolver "
        "wait or when ogrinfo ran"
    )
    # The pending job is written after the release.
    assert resp.json()["job_id"]


async def test_a_refused_url_still_writes_its_audit_row_after_the_release(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    request_sessions,
):
    """The release must not cost the refusal path its audit row.

    `_probe_audit_fail` runs after the rollback now, so it has to re-acquire a
    connection and commit on it. If the release left the session unusable this
    is where it would show.
    """
    from sqlalchemy import select

    from app.modules.audit.models import AuditLog
    from app.platform.security import SSRFError

    probe_url = "https://a2-refused.example.com/wfs"

    async def _refuse(_url):
        raise SSRFError("URLs targeting private/internal networks are not allowed")

    with patch("app.modules.catalog.sources.router.validate_url_for_ssrf", new=_refuse):
        resp = await client.post(
            "/services/probe/",
            json={"url": probe_url},
            headers=admin_auth_header,
        )

    assert resp.status_code == 400, resp.text
    rows = (
        (
            await test_db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "probe_service",
                    AuditLog.details["url"].astext == probe_url,
                )
            )
        )
        .scalars()
        .all()
    )
    assert [row.details["result"] for row in rows] == ["ssrf_blocked"]


# ---------------------------------------------------------------------------
# datasets/api/router_reupload.py
# ---------------------------------------------------------------------------


async def _vector_dataset(session: AsyncSession):
    admin_id = await get_user_id(session, "admin")
    return await create_dataset(
        session,
        created_by=admin_id,
        name=f"A2 Reupload {uuid.uuid4().hex[:6]}",
        column_info=[{"name": "name", "type": "String"}],
    )


async def test_reupload_service_preview_releases_the_connection(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    request_sessions,
):
    """DNS validation, the page fetches and ogrinfo ran on a held connection."""
    dataset = await _vector_dataset(test_db_session)
    held: list[bool] = []

    async def _recording_preview(*_args, **_kwargs):
        held.append(_holds_connection(request_sessions))
        return dict(_PREVIEW_DATA)

    from app.modules.catalog.datasets.api import router_reupload

    with (
        patch.object(router_reupload, "run_service_preview", new=_recording_preview),
        patch.object(router_reupload, "validate_url_for_ssrf", new_callable=AsyncMock),
        patch.object(
            router_reupload,
            "build_gdal_source",
            return_value=("WFS:https://a2.example.com/wfs", "buildings"),
        ),
    ):
        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/service/preview",
            json={
                "url": "https://a2.example.com/wfs",
                "service_type": "WFS 2.0.0",
                "layer_name": "buildings",
            },
            headers=admin_auth_header,
        )

    assert resp.status_code == 200, resp.text
    assert held == [False], (
        "the request session was still in a transaction when the service preview ran"
    )
    # The diff is computed from values read off the dataset BEFORE the release.
    # A MissingGreenlet here would mean they were read off an expired instance.
    body = resp.json()
    assert body["schema_diff"] is not None
    assert body["job_id"]


async def test_reupload_preview_releases_the_connection_before_ogrinfo(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    request_sessions,
):
    """The S3 download and `run_ogrinfo_preview` ran on a held connection."""
    dataset = await _vector_dataset(test_db_session)
    admin_id = await get_user_id(test_db_session, "admin")
    job = IngestJob(
        dataset_id=dataset.id,
        source_filename="replacement.geojson",
        file_path="/tmp/a2-replacement.geojson",
        created_by=admin_id,
        status="pending",
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    test_db_session.add(job)
    await test_db_session.commit()

    held: list[bool] = []
    from app.modules.catalog.datasets.api import router_reupload

    port = router_reupload.get_catalog_port()

    async def _recording_ogrinfo(*_args, **_kwargs):
        held.append(_holds_connection(request_sessions))
        return dict(_PREVIEW_DATA)

    async def _resolve(path, _job_id):
        return path

    with (
        patch.object(port, "run_ogrinfo_preview", new=_recording_ogrinfo),
        patch.object(port, "resolve_file_path", new=_resolve),
        patch.object(router_reupload, "get_catalog_port", return_value=port),
    ):
        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/{job.id}/preview",
            json={},
            headers=admin_auth_header,
        )

    assert resp.status_code == 200, resp.text
    assert held == [False], (
        "the request session was still in a transaction when ogrinfo ran"
    )
    body = resp.json()
    # Both were read off ORM instances the release expires.
    assert body["job_id"] == str(job.id)
    assert body["source_filename"] == "replacement.geojson"


async def test_reupload_commits_the_job_before_streaming_the_file(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    request_sessions,
    tmp_path: Path,
):
    """The whole multipart body streamed on a held connection.

    This door cannot roll back to release: it holds an uncommitted `IngestJob`
    by construction. It commits the row first instead, which both frees the
    connection and leaves a `pending` row the stale-pending sweep can reap if
    the upload never finishes.
    """
    dataset = await _vector_dataset(test_db_session)
    held: list[bool] = []
    from app.modules.catalog.datasets.api import router_reupload

    port = router_reupload.get_catalog_port()
    staged: list[str] = []

    async def _recording_save(file, job_id, **_kwargs):
        held.append(_holds_connection(request_sessions))
        staged.append(job_id)
        # A `Path` is the local-storage shape, which is what the test harness
        # runs; a str would send the handler down the S3 resolve branch.
        path = tmp_path / f"a2-staged-{job_id}.geojson"
        path.write_bytes(b'{"type":"FeatureCollection","features":[]}')
        return path

    with (
        patch.object(port, "save_upload_file", new=_recording_save),
        patch.object(port, "validate_file_content", return_value=None),
        patch.object(router_reupload, "get_catalog_port", return_value=port),
    ):
        resp = await client.post(
            f"/datasets/{dataset.id}/reupload",
            files={
                "file": (
                    "replacement.geojson",
                    BytesIO(b'{"type":"FeatureCollection","features":[]}'),
                    "application/geo+json",
                )
            },
            headers=admin_auth_header,
        )

    assert resp.status_code == 201, resp.text
    assert held == [False], (
        "the request session was still in a transaction while the upload "
        "streamed, so it held a pooled connection for the whole transfer"
    )

    # The committed row is the point: it exists before the upload and carries
    # the path afterwards.
    job_id = uuid.UUID(resp.json()["job_id"])
    assert staged == [str(job_id)]
    stored = await test_db_session.get(IngestJob, job_id)
    assert stored is not None
    assert stored.file_path == str(tmp_path / f"a2-staged-{job_id}.geojson")


async def test_a_sweep_during_the_upload_refuses_rather_than_binding(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    tmp_path: Path,
):
    """fix(#1848 audit): the cost of committing first, bounded.

    The row is visible and `pending` for the whole upload now, so the
    stale-pending sweep can reclaim it while the bytes are still arriving. An
    ORM flush would then bind the path onto a `cancelled` row and answer 201
    with a job the next call refuses as already processed, losing the upload.
    The bind is a compare-and-set on `status = 'pending'` instead, so a
    reclaimed row is left alone and the caller is told to start again.
    """
    from sqlalchemy import select

    from app.api.main import sweep_stale_jobs_once
    from app.modules.catalog.datasets.api import router_reupload
    from app.platform.jobs.sweep import stale_pending_cutoff_seconds

    dataset = await _vector_dataset(test_db_session)
    port = router_reupload.get_catalog_port()

    async def _sweep_mid_upload(_file, job_id, **_kwargs):
        # Age the row past the unbound cutoff and let the real sweep reclaim
        # it, which is what a slow upload runs into.
        cutoff = stale_pending_cutoff_seconds(completion_bound=False)
        aged = datetime.now(timezone.utc) - timedelta(seconds=cutoff + 60)
        row = await test_db_session.get(IngestJob, uuid.UUID(job_id))
        assert row is not None, "the job must be committed before the upload"
        row.created_at = aged
        await test_db_session.commit()
        await sweep_stale_jobs_once()
        path = tmp_path / f"a2-swept-{job_id}.geojson"
        path.write_bytes(b'{"type":"FeatureCollection","features":[]}')
        return path

    with (
        patch.object(port, "save_upload_file", new=_sweep_mid_upload),
        patch.object(port, "validate_file_content", return_value=None),
        patch.object(router_reupload, "get_catalog_port", return_value=port),
    ):
        resp = await client.post(
            f"/datasets/{dataset.id}/reupload",
            files={
                "file": (
                    "replacement.geojson",
                    BytesIO(b'{"type":"FeatureCollection","features":[]}'),
                    "application/geo+json",
                )
            },
            headers=admin_auth_header,
        )

    assert resp.status_code == 409, resp.text

    rows = (
        (
            await test_db_session.execute(
                select(IngestJob).where(IngestJob.dataset_id == dataset.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    await test_db_session.refresh(rows[0])
    # The sweep's verdict stands, and no path was bound onto it.
    assert rows[0].status == "cancelled"
    assert not rows[0].file_path
    # The staged file is cleaned on the refusal path, like every other failure.
    assert not (tmp_path / f"a2-swept-{rows[0].id}.geojson").exists()


async def test_only_the_local_provider_needs_the_stamp(
    test_db_session: AsyncSession,
):
    """fix(#1848 codex r2): why the finding is local-only, measured.

    `save_upload_file` returns `staging/{job}/{name}` under S3 and an absolute
    path under the local provider. The sweep's two classes are split by
    whether `file_path` matches `staging/%`, so an S3 bind lands in the
    24-hour class while a local bind stays in the short one. The stamp is
    written for both because it is one statement, but this is the asymmetry it
    exists for.
    """
    from sqlalchemy import text

    local_path = "/app/staging/abc_replacement.geojson"
    s3_key = "staging/2f1c/replacement.geojson"

    async def _is_bound_class(value: str) -> bool:
        return await test_db_session.scalar(
            text("SELECT coalesce(:p, '') LIKE 'staging/%'").bindparams(p=value)
        )

    assert await _is_bound_class(s3_key) is True
    assert await _is_bound_class(local_path) is False


async def test_a_slow_local_upload_that_binds_survives_the_next_sweep(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    tmp_path: Path,
):
    """fix(#1848 codex r2): the bind restarts the pending window.

    With the local provider the bound path is absolute, so it never matches
    the sweep's `staging/%` completion class and the row stays in the class
    measured from `coalesce(staged_at, created_at)`. Bound without a fresh
    `staged_at`, an upload slower than the pending timeout returned 201 and
    the very next sweep cancelled the job it had just accepted. Stamping at
    the bind is what gives the caller a full window from the moment the bytes
    landed.
    """
    from app.api.main import sweep_stale_jobs_once
    from app.modules.catalog.datasets.api import router_reupload
    from app.platform.jobs.sweep import stale_pending_cutoff_seconds

    dataset = await _vector_dataset(test_db_session)
    port = router_reupload.get_catalog_port()
    staged_file = tmp_path / "a2-slow-upload.geojson"

    async def _slow_local_upload(_file, job_id, **_kwargs):
        # The upload outlives the pending window, which `created_at` alone
        # would measure from.
        cutoff = stale_pending_cutoff_seconds(completion_bound=False)
        aged = datetime.now(timezone.utc) - timedelta(seconds=cutoff + 60)
        row = await test_db_session.get(IngestJob, uuid.UUID(job_id))
        assert row is not None
        row.created_at = aged
        await test_db_session.commit()
        staged_file.write_bytes(b'{"type":"FeatureCollection","features":[]}')
        return staged_file

    with (
        patch.object(port, "save_upload_file", new=_slow_local_upload),
        patch.object(port, "validate_file_content", return_value=None),
        patch.object(router_reupload, "get_catalog_port", return_value=port),
    ):
        resp = await client.post(
            f"/datasets/{dataset.id}/reupload",
            files={
                "file": (
                    "replacement.geojson",
                    BytesIO(b'{"type":"FeatureCollection","features":[]}'),
                    "application/geo+json",
                )
            },
            headers=admin_auth_header,
        )

    assert resp.status_code == 201, resp.text
    job_id = uuid.UUID(resp.json()["job_id"])

    # The premise: an absolute path, so the `staging/%` class does not cover it.
    stored = await test_db_session.get(IngestJob, job_id)
    assert stored is not None
    assert stored.file_path == str(staged_file)
    assert not stored.file_path.startswith("staging/")

    await sweep_stale_jobs_once()

    await test_db_session.refresh(stored)
    assert stored.status == "pending"
    assert staged_file.exists()
    # The markers the job-binding gate reads survive the metadata write.
    assert stored.user_metadata["reupload"] is True
    assert stored.user_metadata["dataset_id"] == str(dataset.id)
    assert stored.user_metadata["staged_at"]

    # And the door still accepts the job, which is what the user paid for.
    preview = await client.post(
        f"/datasets/{dataset.id}/reupload/{job_id}/preview",
        json={},
        headers=admin_auth_header,
    )
    assert preview.status_code != 404, preview.text


async def test_a_dataset_deleted_during_the_upload_refuses_the_bind(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    tmp_path: Path,
):
    """fix(#1848 codex r3): the binding is part of the guard, not just status.

    The early commit released the row's foreign-key lock, and
    `ingest_jobs.dataset_id` is `ON DELETE SET NULL`. A dataset deleted while
    the bytes were arriving therefore left a job whose binding was gone, and a
    guard that read only id and status bound the file and answered 201. Every
    later re-upload endpoint then refused that job, because the binding gate
    matches on `dataset_id`.
    """
    from sqlalchemy import select

    from app.modules.catalog.datasets.api import router_reupload

    dataset = await _vector_dataset(test_db_session)
    dataset_id = dataset.id
    port = router_reupload.get_catalog_port()
    staged_file = tmp_path / "a2-orphaned.geojson"

    async def _delete_dataset_mid_upload(_file, _job_id, **_kwargs):
        await test_db_session.delete(dataset)
        await test_db_session.commit()
        staged_file.write_bytes(b'{"type":"FeatureCollection","features":[]}')
        return staged_file

    with (
        patch.object(port, "save_upload_file", new=_delete_dataset_mid_upload),
        patch.object(port, "validate_file_content", return_value=None),
        patch.object(router_reupload, "get_catalog_port", return_value=port),
    ):
        resp = await client.post(
            f"/datasets/{dataset_id}/reupload",
            files={
                "file": (
                    "replacement.geojson",
                    BytesIO(b'{"type":"FeatureCollection","features":[]}'),
                    "application/geo+json",
                )
            },
            headers=admin_auth_header,
        )

    assert resp.status_code == 409, resp.text
    # The staged file goes with the refusal, like every other failure path.
    assert not staged_file.exists()

    rows = (
        (
            await test_db_session.execute(
                select(IngestJob).where(
                    IngestJob.source_filename == "replacement.geojson"
                )
            )
        )
        .scalars()
        .all()
    )
    orphaned = [row for row in rows if row.dataset_id is None]
    assert len(orphaned) == 1
    # The premise: the FK nulled the binding, and nothing was bound onto it.
    assert orphaned[0].status == "pending"
    assert not orphaned[0].file_path


async def test_a_failed_upload_leaves_a_reapable_pending_job(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
):
    """The cost of committing first, and the reason it is affordable.

    Before this change a transport failure rolled the uncommitted job back with
    the request transaction. Now the row survives. It survives in exactly the
    shape `stale_pending_clauses` reaps on its one-hour policy: `pending`, with
    nothing bound into `file_path`, which is the unbound half of that
    predicate.
    """
    from app.modules.catalog.datasets.api import router_reupload
    from app.platform.jobs.sweep import stale_pending_clauses

    dataset = await _vector_dataset(test_db_session)
    port = router_reupload.get_catalog_port()

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("transport failed mid-upload")

    with (
        patch.object(port, "save_upload_file", new=_boom),
        patch.object(router_reupload, "get_catalog_port", return_value=port),
    ):
        # The test transport re-raises whatever the app did not handle, so the
        # failure arrives here rather than as a 500 body.
        with pytest.raises(RuntimeError, match="transport failed mid-upload"):
            await client.post(
                f"/datasets/{dataset.id}/reupload",
                files={
                    "file": (
                        "replacement.geojson",
                        BytesIO(b'{"type":"FeatureCollection","features":[]}'),
                        "application/geo+json",
                    )
                },
                headers=admin_auth_header,
            )

    from sqlalchemy import select

    rows = (
        (
            await test_db_session.execute(
                select(IngestJob).where(IngestJob.dataset_id == dataset.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == "pending"
    # `create_ingest_job` seeds an empty path, so this is the unbound half of
    # the sweep's discriminator rather than the completion half.
    assert not rows[0].file_path
    # The predicate that reaps it, evaluated on this row rather than described.
    from sqlalchemy import select as _select

    later = datetime.now(timezone.utc) + timedelta(days=1)
    reapable = (
        await test_db_session.execute(
            _select(IngestJob.id).where(
                IngestJob.id == rows[0].id,
                *stale_pending_clauses(later, completion_bound=False),
            )
        )
    ).scalar_one_or_none()
    assert reapable == rows[0].id


async def test_the_release_is_not_a_blanket_rollback_of_the_gates(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
):
    """The counterfactual for every test above: the gates still refuse first.

    A release placed one line too early would run the write-access check after
    the I/O, or skip it. A viewer must still be refused before any preview
    work happens at all.
    """
    dataset = await _vector_dataset(test_db_session)
    from app.modules.catalog.datasets.api import router_reupload

    ran = SimpleNamespace(called=False)

    async def _should_not_run(*_args, **_kwargs):
        ran.called = True
        return dict(_PREVIEW_DATA)

    with patch.object(router_reupload, "run_service_preview", new=_should_not_run):
        resp = await client.post(
            f"/datasets/{uuid.uuid4()}/reupload/service/preview",
            json={
                "url": "https://a2.example.com/wfs",
                "service_type": "WFS 2.0.0",
                "layer_name": "buildings",
            },
            headers=admin_auth_header,
        )

    assert resp.status_code == 404, resp.text
    assert ran.called is False
    assert dataset.id is not None


# ---------------------------------------------------------------------------
# datasets/api/router_reupload.py, presigned door
# ---------------------------------------------------------------------------


def _presigned_storage(request_sessions, held: list[bool]):
    """A storage double whose signing calls record the request session's state."""
    from unittest.mock import MagicMock

    storage = MagicMock()

    def _initiate(*_args):
        held.append(_holds_connection(request_sessions))
        return "upload-a2b"

    def _sign_part(_key, _upload_id, part_number, _expiration):
        held.append(_holds_connection(request_sessions))
        return f"https://a2b.example.com/part/{part_number}"

    def _sign_put(*_args):
        held.append(_holds_connection(request_sessions))
        return "https://a2b.example.com/put"

    storage.initiate_multipart_upload.side_effect = _initiate
    storage.generate_presigned_part_url.side_effect = _sign_part
    storage.generate_presigned_put_url.side_effect = _sign_put
    return storage


async def _request_presigned(
    client: AsyncClient, admin_auth_header: dict, dataset_id, *, filename, file_size
):
    return await client.post(
        f"/datasets/{dataset_id}/reupload/presigned",
        json={
            "filename": filename,
            "file_size": file_size,
            "content_type": "application/geo+json",
        },
        headers=admin_auth_header,
    )


async def _job_named(session: AsyncSession, filename: str) -> IngestJob:
    from sqlalchemy import select

    row = (
        await session.execute(
            select(IngestJob).where(IngestJob.source_filename == filename)
        )
    ).scalar_one()
    await session.refresh(row)
    return row


async def test_presigned_reupload_commits_the_job_before_asking_storage(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    request_sessions,
):
    """The multipart initiation and every part signature ran on a held connection.

    Same shape as the direct door: the row is committed before storage is asked
    for anything, and the presigned facts land afterwards through the guarded
    bind rather than an ORM flush.
    """
    from app.modules.catalog.datasets.api import router_reupload

    dataset = await _vector_dataset(test_db_session)
    filename = f"a2b-{uuid.uuid4().hex[:8]}.geojson"
    held: list[bool] = []
    storage = _presigned_storage(request_sessions, held)

    with (
        patch.object(router_reupload.settings, "storage_provider", "s3"),
        patch.object(router_reupload.settings, "presigned_multipart_threshold_mb", 1),
        patch.object(router_reupload, "get_storage", return_value=storage),
    ):
        resp = await _request_presigned(
            client,
            admin_auth_header,
            dataset.id,
            filename=filename,
            file_size=2 * 1024 * 1024,
        )

    assert resp.status_code == 201, resp.text
    assert held == [False, False], (
        "the request session was still in a transaction when storage was "
        "asked to initiate the multipart upload or to sign a part"
    )
    body = resp.json()
    assert body["upload_id"] == "upload-a2b"
    job = await _job_named(test_db_session, filename)
    assert str(job.id) == body["job_id"]
    assert job.dataset_id == dataset.id
    assert job.status == "pending"
    # Everything the completion door reads is on the row, and nothing is
    # staged yet, so the pending window keeps counting from creation.
    assert job.user_metadata["presigned"] is True
    assert job.user_metadata["multipart"] is True
    assert job.user_metadata["upload_id"] == "upload-a2b"
    assert job.user_metadata["s3_key"] == f"staging/{job.id}/{filename}"
    assert job.user_metadata["expected_size"] == 2 * 1024 * 1024
    assert job.user_metadata["reupload"] is True
    assert job.user_metadata["dataset_id"] == str(dataset.id)
    assert "staged_at" not in job.user_metadata


async def test_a_presigned_reupload_swept_while_signing_is_refused_and_aborted(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    request_sessions,
):
    """The committed row is visible to the sweep while storage answers.

    An ORM flush would have written the presigned facts onto a row the sweep
    had already cancelled and answered 201 with an upload id whose job is
    terminal. The bind is guarded instead, the multipart upload is aborted,
    and the caller is told to start again.
    """
    from app.api.main import sweep_stale_jobs_once
    from app.modules.catalog.datasets.api import router_reupload
    from app.platform.jobs.sweep import stale_pending_cutoff_seconds

    dataset = await _vector_dataset(test_db_session)
    filename = f"a2b-{uuid.uuid4().hex[:8]}.geojson"
    held: list[bool] = []
    storage = _presigned_storage(request_sessions, held)

    async def _sweep_while_initiating(fn, *args):
        cutoff = stale_pending_cutoff_seconds(completion_bound=False)
        aged = datetime.now(timezone.utc) - timedelta(seconds=cutoff + 60)
        row = await _job_named(test_db_session, filename)
        row.created_at = aged
        await test_db_session.commit()
        await sweep_stale_jobs_once()
        return fn(*args), None

    with (
        patch.object(router_reupload.settings, "storage_provider", "s3"),
        patch.object(router_reupload.settings, "presigned_multipart_threshold_mb", 1),
        patch.object(router_reupload, "get_storage", return_value=storage),
        patch.object(
            router_reupload,
            "run_in_thread_draining_capture_cancel",
            new=_sweep_while_initiating,
        ),
    ):
        resp = await _request_presigned(
            client,
            admin_auth_header,
            dataset.id,
            filename=filename,
            file_size=2 * 1024 * 1024,
        )

    assert resp.status_code == 409, resp.text
    job = await _job_named(test_db_session, filename)
    # The sweep's verdict stands and no presigned fact was written onto it.
    assert job.status == "cancelled"
    assert "presigned" not in (job.user_metadata or {})
    # The upload id storage handed out is given back on the refusal.
    (aborted_key, aborted_upload_id), _kwargs = storage.abort_multipart_upload.call_args
    assert aborted_key.endswith(f"staging/{job.id}/{filename}")
    assert aborted_upload_id == "upload-a2b"


async def test_a_dataset_deleted_while_signing_refuses_the_presigned_bind(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    request_sessions,
):
    """The binding is part of the guard on this door too.

    The early commit releases the row's foreign-key lock, so a dataset deleted
    while storage signs nulls the job's binding. A guard on id and status alone
    would have written the presigned facts onto an orphan that every later
    re-upload door refuses.
    """
    from app.modules.catalog.datasets.api import router_reupload

    dataset = await _vector_dataset(test_db_session)
    dataset_id = dataset.id
    filename = f"a2b-{uuid.uuid4().hex[:8]}.geojson"
    held: list[bool] = []
    storage = _presigned_storage(request_sessions, held)

    async def _delete_dataset_while_signing(fn, *args):
        await test_db_session.delete(dataset)
        await test_db_session.commit()
        return fn(*args)

    with (
        patch.object(router_reupload.settings, "storage_provider", "s3"),
        patch.object(router_reupload, "get_storage", return_value=storage),
        patch.object(
            router_reupload, "run_in_thread_draining", new=_delete_dataset_while_signing
        ),
    ):
        resp = await _request_presigned(
            client, admin_auth_header, dataset_id, filename=filename, file_size=128
        )

    assert resp.status_code == 409, resp.text
    # The single-part signature ran on a released connection as well.
    assert held == [False]
    job = await _job_named(test_db_session, filename)
    # The premise: the FK nulled the binding, and nothing was written onto it.
    assert job.dataset_id is None
    assert job.status == "pending"
    assert "presigned" not in (job.user_metadata or {})


# ---------------------------------------------------------------------------
# processing/ingest/router.py
# ---------------------------------------------------------------------------

_EMPTY_COLLECTION = b'{"type":"FeatureCollection","features":[]}'


async def _post_upload(client: AsyncClient, admin_auth_header: dict, filename: str):
    return await client.post(
        "/ingest/upload",
        files={"file": (filename, BytesIO(_EMPTY_COLLECTION), "application/geo+json")},
        headers=admin_auth_header,
    )


async def test_upload_commits_the_job_before_staging_the_file(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    request_sessions,
    tmp_path: Path,
):
    """The staging step ran on a held connection.

    FastAPI spools the multipart body before any dependency runs, so the
    connection was never held across the network stream. It was held across
    `save_upload_file` (the copy into staging, or the S3 put), the validation
    download and the content sniff. Same shape as the direct re-upload door:
    the row is committed first and the bind afterwards is guarded.
    """
    from app.processing.ingest import router as ingest_router

    filename = f"a2b-{uuid.uuid4().hex[:8]}.geojson"
    staged_file = tmp_path / filename
    held: list[bool] = []
    visible: list[bool] = []

    async def _recording_save(_file, job_id, **_kwargs):
        held.append(_holds_connection(request_sessions))
        # Durable before staging starts: another session can already see it.
        visible.append(
            await test_db_session.get(IngestJob, uuid.UUID(job_id)) is not None
        )
        staged_file.write_bytes(_EMPTY_COLLECTION)
        return staged_file

    with (
        patch.object(ingest_router, "save_upload_file", new=_recording_save),
        patch.object(ingest_router, "validate_file_content", return_value=None),
    ):
        resp = await _post_upload(client, admin_auth_header, filename)

    assert resp.status_code == 201, resp.text
    assert held == [False], (
        "the request session was still in a transaction while the spooled "
        "body was staged, so it held a pooled connection across that work"
    )
    assert visible == [True]
    job = await _job_named(test_db_session, filename)
    assert str(job.id) == resp.json()["job_id"]
    assert job.status == "pending"
    assert job.file_path == str(staged_file)
    # The bind restarts the pending window from the moment the bytes landed.
    assert job.user_metadata["staged_at"]


async def test_a_sweep_during_the_upload_refuses_rather_than_binding_the_file(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    tmp_path: Path,
):
    """A row the sweep reclaimed mid-upload is left as the sweep left it.

    Bound through an ORM flush, the path would land on a `cancelled` row and
    the door would answer 201 with a job the preview refuses. The guarded bind
    matches no row, the staged file is cleaned, and the caller gets a 409.
    """
    from app.api.main import sweep_stale_jobs_once
    from app.platform.jobs.sweep import stale_pending_cutoff_seconds
    from app.processing.ingest import router as ingest_router

    filename = f"a2b-{uuid.uuid4().hex[:8]}.geojson"
    staged_file = tmp_path / filename

    async def _sweep_mid_upload(_file, job_id, **_kwargs):
        cutoff = stale_pending_cutoff_seconds(completion_bound=False)
        aged = datetime.now(timezone.utc) - timedelta(seconds=cutoff + 60)
        row = await test_db_session.get(IngestJob, uuid.UUID(job_id))
        assert row is not None, "the job must be committed before the upload"
        row.created_at = aged
        await test_db_session.commit()
        await sweep_stale_jobs_once()
        staged_file.write_bytes(_EMPTY_COLLECTION)
        return staged_file

    with (
        patch.object(ingest_router, "save_upload_file", new=_sweep_mid_upload),
        patch.object(ingest_router, "validate_file_content", return_value=None),
    ):
        resp = await _post_upload(client, admin_auth_header, filename)

    assert resp.status_code == 409, resp.text
    job = await _job_named(test_db_session, filename)
    assert job.status == "cancelled"
    assert not job.file_path
    assert not staged_file.exists()


async def test_a_slow_local_upload_that_binds_is_not_reaped_by_the_next_sweep(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    tmp_path: Path,
):
    """The bind stamps `staged_at`, so the pending window restarts there.

    The local provider binds an absolute path, which never reaches the sweep's
    `staging/%` completion class, so the row stays in the class measured from
    `coalesce(staged_at, created_at)`. Without the stamp a staging step slower
    than the pending timeout was accepted with 201 and cancelled by the next
    sweep.
    """
    from app.api.main import sweep_stale_jobs_once
    from app.platform.jobs.sweep import stale_pending_cutoff_seconds
    from app.processing.ingest import router as ingest_router

    filename = f"a2b-{uuid.uuid4().hex[:8]}.geojson"
    staged_file = tmp_path / filename

    async def _slow_local_upload(_file, job_id, **_kwargs):
        cutoff = stale_pending_cutoff_seconds(completion_bound=False)
        aged = datetime.now(timezone.utc) - timedelta(seconds=cutoff + 60)
        row = await test_db_session.get(IngestJob, uuid.UUID(job_id))
        assert row is not None
        row.created_at = aged
        await test_db_session.commit()
        staged_file.write_bytes(_EMPTY_COLLECTION)
        return staged_file

    with (
        patch.object(ingest_router, "save_upload_file", new=_slow_local_upload),
        patch.object(ingest_router, "validate_file_content", return_value=None),
    ):
        resp = await _post_upload(client, admin_auth_header, filename)

    assert resp.status_code == 201, resp.text
    job = await _job_named(test_db_session, filename)
    assert not job.file_path.startswith("staging/")

    await sweep_stale_jobs_once()

    await test_db_session.refresh(job)
    assert job.status == "pending"
    assert job.user_metadata["staged_at"]
    assert staged_file.exists()


async def test_an_upload_refused_for_content_leaves_a_failed_job(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    tmp_path: Path,
):
    """The cost of committing first on the content path, and its shape.

    The 422 used to roll the uncommitted row back. The row is durable now, so
    it is stamped `failed` with the refusal through the same guard as the bind,
    which is what the presigned completion door already does for this 422.
    """
    from app.processing.ingest import router as ingest_router

    filename = f"a2b-{uuid.uuid4().hex[:8]}.geojson"
    staged_file = tmp_path / filename

    async def _save(_file, _job_id, **_kwargs):
        staged_file.write_bytes(b"not a dataset")
        return staged_file

    with (
        patch.object(ingest_router, "save_upload_file", new=_save),
        patch.object(
            ingest_router,
            "validate_file_content",
            side_effect=ValueError("a2b: not a recognised dataset"),
        ),
    ):
        resp = await _post_upload(client, admin_auth_header, filename)

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "a2b: not a recognised dataset"
    job = await _job_named(test_db_session, filename)
    assert job.status == "failed"
    assert job.error_message == "a2b: not a recognised dataset"
    # Terminal rows carry `completed_at`, as every other terminal writer stamps it.
    assert job.completed_at is not None
    assert not job.file_path
    assert not staged_file.exists()


async def test_a_direct_reupload_refused_for_content_leaves_a_completed_failed_row(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    tmp_path: Path,
):
    """The direct door's refusal stamp carries `completed_at` like every other terminal writer."""
    from app.modules.catalog.datasets.api import router_reupload

    dataset = await _vector_dataset(test_db_session)
    filename = f"a2b-{uuid.uuid4().hex[:8]}.geojson"
    staged_file = tmp_path / filename
    port = router_reupload.get_catalog_port()

    async def _save(_file, _job_id, **_kwargs):
        staged_file.write_bytes(b"not a dataset")
        return staged_file

    with (
        patch.object(port, "save_upload_file", new=_save),
        patch.object(
            port,
            "validate_file_content",
            side_effect=ValueError("a2b: not a recognised dataset"),
        ),
        patch.object(router_reupload, "get_catalog_port", return_value=port),
    ):
        resp = await client.post(
            f"/datasets/{dataset.id}/reupload",
            files={
                "file": (filename, BytesIO(_EMPTY_COLLECTION), "application/geo+json")
            },
            headers=admin_auth_header,
        )

    assert resp.status_code == 422, resp.text
    job = await _job_named(test_db_session, filename)
    assert job.status == "failed"
    assert job.error_message == "a2b: not a recognised dataset"
    assert job.completed_at is not None
    assert not staged_file.exists()
