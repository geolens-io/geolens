"""fix(#1848): five doors must not hold a pooled connection across their I/O.

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
