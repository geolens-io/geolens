"""The admin job list shows a job's public metadata keys and nothing else."""

import ast
import uuid
from pathlib import Path
from shutil import copyfile
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.platform.jobs import models
from app.platform.jobs.models import (
    EMBEDDING_BACKFILL_METADATA_KEY,
    PUBLIC_METADATA_KEYS,
    IngestJob,
    public_job_metadata,
)
from app.platform.jobs.sweep import _carries_unreaped_artifacts
from app.processing.ingest import schemas as ingest_schemas
from app.processing.ingest import tasks_vector
from tests.factories import get_user_id
from tests.test_refresh_gate_1269 import _runs_ordered
from tests.test_refresh_pagination_1675 import (
    _arcgis_dataset,
    _dispatch_refresh,
    _execute_with_fake,
    _fake_ogr2ogr,
)

ARTIFACT_RECORDS = {
    "unpublished_storage_keys": [f"rasters/{uuid.uuid4()}/attempts/a/b"],
    "unpublished_tileset_attempts": [f"tiles3d/{uuid.uuid4()}/{uuid.uuid4()}/"],
    "analysis_out_table": ["analysis_out_1"],
    "publish_followups": {"task": "ingest_raster", "attempt_id": str(uuid.uuid4())},
}
# Every key the code writes as door or worker state, with a sample value. The
# written-key scan below requires each key it finds to be here or public.
BOOKKEEPING = {
    **ARTIFACT_RECORDS,
    "fan_out_interrupted": True,
    "url_download_in_flight": True,
    "commit_attempted_at": "2026-09-25T00:00:00+00:00",
    "s3_key_reaped": True,
    "s3_key_reaped_final": True,
    "manifest_stage": "downloading",
    "manifest_fingerprint": "sha256:0123",
    "tileset_unpacked_bytes": 4096,
    "presigned": True,
    "s3_key": "staging/job/campus.zip",
    "upload_id": "multipart-upload-id",
    "multipart": True,
    "expected_size": 4096,
    "staged_at": "2026-09-25T00:00:00+00:00",
    "service_auth_required": True,
    "accepted_refresh_run_id": str(uuid.uuid4()),
    "accepted_refresh_fingerprint": "sha256:4567",
    "archive_error": "Could not archive staging/job/original.tif",
}
USER_METADATA = {
    "title": "Campus",
    "summary": "Buildings",
    "tags": ["3d"],
    "visibility": "internal",
    "file_type": "raster",
    "vrt_type": "mosaic",
    "warnings": [{"code": "crs_assumed"}],
    "rows_failed": 2,
    "temporal_parse_errors": 1,
    EMBEDDING_BACKFILL_METADATA_KEY: {"force": False, "records_total": 3},
    "all_layers": [{"name": "roads", "feature_count": 1, "field_count": 2}],
    "fan_out_parent_id": str(uuid.uuid4()),
    "archive_failed": True,
}
UNKNOWN = {"some_new_worker_state": {"attempt": 3}}
BACKEND_APP = Path(__file__).resolve().parents[1] / "app"


async def _job(session, *, filename: str, metadata: dict) -> uuid.UUID:
    job = IngestJob(
        status="complete",
        created_by=await get_user_id(session, "admin"),
        source_filename=filename,
        user_metadata=metadata,
    )
    session.add(job)
    await session.commit()
    return job.id


async def _listed_metadata(client: AsyncClient, headers: dict, filename: str):
    resp = await client.get(
        "/admin/jobs/", params={"search": filename}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    (job,) = resp.json()["jobs"]
    return job["user_metadata"]


async def test_the_admin_job_list_shows_only_public_keys(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """Bookkeeping and unknown keys are left out; public keys come back unchanged."""
    filename = f"jmeta{uuid.uuid4().hex[:10]}"
    job_id = await _job(
        test_db_session,
        filename=filename,
        metadata={**USER_METADATA, **BOOKKEEPING, **UNKNOWN},
    )
    try:
        listed = await _listed_metadata(client, admin_auth_header, filename)
    finally:
        await test_db_session.execute(delete(IngestJob).where(IngestJob.id == job_id))
        await test_db_session.commit()

    assert listed == USER_METADATA


async def test_a_job_with_no_public_keys_lists_no_metadata(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """A job with only bookkeeping and unknown keys lists null, so the panel shows nothing."""
    filename = f"jmeta{uuid.uuid4().hex[:10]}"
    job_id = await _job(
        test_db_session, filename=filename, metadata={**BOOKKEEPING, **UNKNOWN}
    )
    try:
        listed = await _listed_metadata(client, admin_auth_header, filename)
    finally:
        await test_db_session.execute(delete(IngestJob).where(IngestJob.id == job_id))
        await test_db_session.commit()

    assert listed is None


async def test_the_retention_check_reads_every_artifact_record(test_db_session) -> None:
    """A row naming any one artifact record is kept by the purge; a row naming none is not."""
    filenames = {key: f"jmeta{uuid.uuid4().hex[:10]}" for key in ARTIFACT_RECORDS}
    control = f"jmeta{uuid.uuid4().hex[:10]}"
    ids = [
        await _job(test_db_session, filename=filenames[key], metadata={key: value})
        for key, value in ARTIFACT_RECORDS.items()
    ]
    ids.append(await _job(test_db_session, filename=control, metadata=USER_METADATA))
    try:
        kept = set(
            (
                await test_db_session.execute(
                    select(IngestJob.source_filename).where(
                        IngestJob.id.in_(ids), _carries_unreaped_artifacts()
                    )
                )
            ).scalars()
        )
    finally:
        await test_db_session.execute(delete(IngestJob).where(IngestJob.id.in_(ids)))
        await test_db_session.commit()

    assert kept == set(filenames.values())


def test_every_key_name_models_defines_is_classified() -> None:
    """Each job-metadata key name models.py defines is public or listed as bookkeeping."""
    names = {
        value
        for name, value in vars(models).items()
        if isinstance(value, str)
        and name.endswith(("_METADATA_KEY", "_FIELD", "_MARKER"))
    }

    assert names <= PUBLIC_METADATA_KEYS | set(BOOKKEEPING)
    assert not PUBLIC_METADATA_KEYS & set(BOOKKEEPING)
    assert set(USER_METADATA) <= PUBLIC_METADATA_KEYS


def test_every_commit_field_is_public() -> None:
    """Each field a commit request persists into the job's metadata is public."""
    fields = {
        field
        for model in (
            ingest_schemas.VectorCommitRequest,
            ingest_schemas.RasterCommitRequest,
            ingest_schemas.TilesetCommitRequest,
            ingest_schemas.ServiceCommitRequest,
        )
        for field in model.model_fields
    } - {"token", "auth"}

    assert fields <= PUBLIC_METADATA_KEYS


def test_an_unknown_key_is_left_out() -> None:
    """A key nobody has classified yet does not reach the admin list."""
    assert public_job_metadata({"title": "Campus", **UNKNOWN}) == {"title": "Campus"}


def _written_metadata_keys() -> dict[str, str]:
    """Each key the code writes into a job's user_metadata, with one place it does.

    Reads key-name constants in platform/jobs, the first argument of each
    ``jsonb_build_object`` call not nested in another (a nested one builds a
    value, not a top-level key), the keys of dict literals that are assigned
    to ``user_metadata``, passed as ``user_metadata=``, nested under a
    ``"user_metadata"`` key, or that spread an existing ``user_metadata``, and
    every key a ``*_job_metadata`` helper builds when a dict spreads its result.
    """
    trees = {
        path: ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(BACKEND_APP.rglob("*.py"))
    }
    producers = {
        _called_name(value)
        for tree in trees.values()
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values)
        if key is None and _called_name(value).endswith("_job_metadata")
    }
    found: dict[str, str] = {}
    for path, tree in trees.items():
        where = str(path.relative_to(BACKEND_APP))
        constants = {
            node.targets[0].id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }
        if where.startswith("platform/jobs/"):
            for name, value in constants.items():
                if name.endswith(("_METADATA_KEY", "_FIELD", "_MARKER")):
                    found.setdefault(value, f"{where}:{name}")
        names = {**vars(models), **constants}
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            keys: list[ast.expr | None] = []
            if isinstance(node, ast.Dict) and _is_job_metadata(node, parents.get(node)):
                keys = [
                    key
                    for spread in [node, *_spread_literals(node)]
                    for key in spread.keys
                ]
            elif _called_name(node) == "jsonb_build_object" and not (
                _called_name(parents.get(node)) == "jsonb_build_object"
            ):
                keys = node.args[:1]
            elif isinstance(node, ast.FunctionDef) and node.name in producers:
                keys = [
                    key
                    for inner in ast.walk(node)
                    if isinstance(inner, ast.Dict)
                    for key in inner.keys
                ] + [
                    target.slice
                    for inner in ast.walk(node)
                    if isinstance(inner, ast.Assign)
                    for target in inner.targets
                    if isinstance(target, ast.Subscript)
                ]
            for key in keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    found.setdefault(key.value, f"{where}:{key.lineno}")
                elif isinstance(key, ast.Name) and isinstance(names.get(key.id), str):
                    found.setdefault(names[key.id], f"{where}:{key.lineno}")
    return found


def _spread_literals(node: ast.Dict):
    """Dict literals a ``**`` spread in ``node`` supplies, such as a conditional one.

    A call's arguments are left out: what a function builds is its own.
    """
    pending = [value for key, value in zip(node.keys, node.values) if key is None]
    while pending:
        current = pending.pop()
        if isinstance(current, ast.Call):
            continue
        if isinstance(current, ast.Dict):
            yield current
        pending.extend(ast.iter_child_nodes(current))


def _called_name(node: ast.AST) -> str:
    if not isinstance(node, ast.Call):
        return ""
    func = node.func
    return func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")


def _is_job_metadata(node: ast.Dict, parent: ast.AST | None) -> bool:
    if isinstance(parent, ast.Assign):
        return any(
            isinstance(target, ast.Attribute) and target.attr == "user_metadata"
            for target in parent.targets
        )
    if isinstance(parent, ast.keyword):
        return parent.arg == "user_metadata"
    if isinstance(parent, ast.Dict) and any(
        value is node and isinstance(key, ast.Constant) and key.value == "user_metadata"
        for key, value in zip(parent.keys, parent.values)
    ):
        return True
    return any(
        key is None and "user_metadata" in ast.unparse(value)
        for key, value in zip(node.keys, node.values)
    )


def test_every_metadata_key_the_code_writes_is_classified() -> None:
    """Each key written into user_metadata is public or listed as bookkeeping."""
    found = _written_metadata_keys()

    unclassified = {
        key: where
        for key, where in found.items()
        if key not in PUBLIC_METADATA_KEYS | set(BOOKKEEPING)
    }
    assert unclassified == {}
    assert {
        "s3_key_reaped",
        "s3_key",
        "manifest_fingerprint",
        "manifest_tags",
        "accepted_refresh_run_id",
    } <= set(found)


async def test_a_manifest_job_lists_its_author_keys_without_its_fingerprint(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch, tmp_path
) -> None:
    """A job the manifest apply creates lists its author's keys, not its fingerprint."""
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
    key = f"jmeta-{uuid.uuid4().hex[:10]}"
    seed = tmp_path / "manifest" / f"{key}.geojson"
    seed.parent.mkdir(parents=True)
    copyfile(Path(__file__).parent / "fixtures/ingest/basic_attrs.geojson", seed)
    payload = {
        "manifest_version": "1",
        "catalog": {"title": "Job metadata catalog"},
        "datasets": [
            {
                "key": key,
                "title": "Roads",
                "description": "Road centerlines",
                "sources": [
                    {
                        "type": "vector",
                        "uri": f"manifest/{key}.geojson",
                        "format": "geojson",
                    }
                ],
                "metadata": {
                    "tags": ["roads"],
                    "organization": "City GIS Office",
                    "license": "CC-BY-4.0",
                    "attribution": "City GIS Office",
                },
                "publication": {"intent": "draft"},
            }
        ],
    }
    with (
        patch(
            "app.processing.ingest.manifest_service.queue_ingest_job", new=AsyncMock()
        ),
        patch(
            "app.processing.ingest.manifest_service._manifest_source_size_bytes",
            new=AsyncMock(return_value=1024),
        ),
    ):
        applied = await client.post(
            "/ingest/manifest/apply", json=payload, headers=admin_auth_header
        )
    assert applied.status_code == 200, applied.text
    (entry,) = applied.json()["results"]
    job_id = uuid.UUID(entry["job_id"])
    try:
        stored = (await test_db_session.get(IngestJob, job_id)).user_metadata
        listed = await _listed_metadata(client, admin_auth_header, f"{key}.geojson")
    finally:
        await test_db_session.execute(delete(IngestJob).where(IngestJob.id == job_id))
        await test_db_session.commit()

    assert "manifest_fingerprint" in stored
    assert "manifest_fingerprint" not in listed
    assert {
        name: listed[name]
        for name in (
            "title",
            "summary",
            "manifest_key",
            "manifest_source_type",
            "manifest_publication_intent",
            "manifest_tags",
            "manifest_organization",
            "manifest_license",
            "manifest_attribution",
        )
    } == {
        "title": "Roads",
        "summary": "Road centerlines",
        "manifest_key": key,
        "manifest_source_type": "vector",
        "manifest_publication_intent": "draft",
        "manifest_tags": ["roads"],
        "manifest_organization": "City GIS Office",
        "manifest_license": "CC-BY-4.0",
        "manifest_attribution": "City GIS Office",
    }
    assert listed["manifest_source_uri"] == stored["manifest_source_uri"]


async def test_a_refresh_accepting_a_blocked_run_lists_no_acceptance_state(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
) -> None:
    """A refresh that accepts a blocked run lists its request, not the acceptance it carries."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _arcgis_dataset(test_db_session, created_by=admin_id)
    dataset.feature_count = 10
    await test_db_session.commit()
    dataset_id = dataset.id

    async def _empty_layer(source_url, layer_id, token):
        return 0, 1000, True, "FID"

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _empty_layer)
    fake = _fake_ogr2ogr([], lambda i: 0)
    await _execute_with_fake(
        await _dispatch_refresh(client, admin_auth_header, dataset_id), fake
    )
    (blocked,) = await _runs_ordered(test_db_session, dataset_id)
    assert blocked.status == "blocked"
    blocked_id = str(blocked.id)

    accepted = await _dispatch_refresh(
        client,
        admin_auth_header,
        dataset_id,
        body={"accept_blocked_run_id": blocked_id},
    )
    job_id = uuid.UUID(accepted["job_id"])
    test_db_session.expire_all()
    stored = (await test_db_session.get(IngestJob, job_id)).user_metadata
    resp = await client.get(
        "/admin/jobs/", params={"limit": 200}, headers=admin_auth_header
    )
    (listed,) = [
        job["user_metadata"] for job in resp.json()["jobs"] if job["id"] == str(job_id)
    ]
    # Settled like any other refresh, so no pending job is left for a later sweep.
    await _execute_with_fake(accepted, fake)

    assert stored["accepted_refresh_run_id"] == blocked_id
    assert "accepted_refresh_fingerprint" in stored
    assert not {"accepted_refresh_run_id", "accepted_refresh_fingerprint"} & set(listed)
    assert {name: listed[name] for name in ("reupload", "refresh", "dataset_id")} == {
        "reupload": True,
        "refresh": True,
        "dataset_id": str(dataset_id),
    }
