"""The admin job list shows a job's own metadata and leaves worker bookkeeping out."""

import ast
import uuid
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.platform.jobs import models
from app.platform.jobs.models import (
    EMBEDDING_BACKFILL_METADATA_KEY,
    INTERNAL_METADATA_KEYS,
    IngestJob,
)
from app.platform.jobs.sweep import _carries_unreaped_artifacts
from tests.factories import get_user_id

# Spelled out rather than read from INTERNAL_METADATA_KEYS, so a key dropped
# from that set fails here instead of disappearing from both sides.
ARTIFACT_RECORDS = {
    "unpublished_storage_keys": [f"rasters/{uuid.uuid4()}/attempts/a/b"],
    "unpublished_tileset_attempts": [f"tiles3d/{uuid.uuid4()}/{uuid.uuid4()}/"],
    "analysis_out_table": ["analysis_out_1"],
    "publish_followups": "ingest_raster",
}
BOOKKEEPING = {
    **ARTIFACT_RECORDS,
    "fan_out_interrupted": True,
    "url_download_in_flight": True,
    "commit_attempted_at": "2026-09-25T00:00:00+00:00",
    "s3_key_reaped": True,
    "s3_key_reaped_final": True,
    "manifest_stage": "downloading",
    "tileset_unpacked_bytes": 4096,
    "presigned": True,
    "s3_key": "staging/job/campus.zip",
    "upload_id": "multipart-upload-id",
    "multipart": True,
    "expected_size": 4096,
    "staged_at": "2026-09-25T00:00:00+00:00",
    "service_auth_required": True,
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
}

# Job-metadata keys defined in models.py that stay visible to the admin.
KEPT_KEYS = {EMBEDDING_BACKFILL_METADATA_KEY}

# Keys the code writes into user_metadata that are the user's or describe the
# job's outcome or request, so the admin list keeps them.
PUBLIC_KEYS = {
    "all_layers",
    "analysis",
    "archive_error",
    "archive_failed",
    "collision_warning",
    "dataset_id",
    EMBEDDING_BACKFILL_METADATA_KEY,
    "fan_out_parent_id",
    "file_type",
    "geometry_type",
    "layer_id",
    "layer_name",
    "object_id_field",
    "origin_kind",
    "refresh",
    "reupload",
    "service_type",
    "source_type",
    "summary",
    "temporal_parse_errors",
    "title",
    "verification_policy",
    "visibility",
    "vrt_type",
    "warnings",
}
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


async def test_the_admin_job_list_leaves_worker_bookkeeping_out(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """Every bookkeeping key is left out, and the job's own keys come back unchanged."""
    filename = f"jmeta{uuid.uuid4().hex[:10]}"
    job_id = await _job(
        test_db_session, filename=filename, metadata={**USER_METADATA, **BOOKKEEPING}
    )
    try:
        listed = await _listed_metadata(client, admin_auth_header, filename)
    finally:
        await test_db_session.execute(delete(IngestJob).where(IngestJob.id == job_id))
        await test_db_session.commit()

    assert listed == USER_METADATA


async def test_a_job_with_only_bookkeeping_lists_no_metadata(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """A job whose metadata is all bookkeeping lists null, so the panel shows nothing."""
    filename = f"jmeta{uuid.uuid4().hex[:10]}"
    job_id = await _job(test_db_session, filename=filename, metadata=BOOKKEEPING)
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


def test_every_job_metadata_key_is_internal_or_kept() -> None:
    """Each key name models.py defines is either bookkeeping or on the kept list."""
    names = {
        value
        for name, value in vars(models).items()
        if isinstance(value, str)
        and name.endswith(("_METADATA_KEY", "_FIELD", "_MARKER"))
    }

    assert names - INTERNAL_METADATA_KEYS == KEPT_KEYS
    assert set(BOOKKEEPING) == INTERNAL_METADATA_KEYS


def _written_metadata_keys() -> dict[str, str]:
    """Each key the code writes into a job's user_metadata, with one place it does.

    Reads key-name constants in platform/jobs, the first argument of each
    ``jsonb_build_object`` call, and the keys of dict literals that are assigned
    to ``user_metadata``, passed as ``user_metadata=``, nested under a
    ``"user_metadata"`` key, or that spread an existing ``user_metadata``.
    """
    found: dict[str, str] = {}
    for path in sorted(BACKEND_APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
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
                keys = node.keys
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "jsonb_build_object"
            ):
                keys = node.args[:1]
            for key in keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    found.setdefault(key.value, f"{where}:{key.lineno}")
                elif isinstance(key, ast.Name) and isinstance(names.get(key.id), str):
                    found.setdefault(names[key.id], f"{where}:{key.lineno}")
    return found


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
    """A key written into user_metadata is bookkeeping the list hides or a key it keeps."""
    found = _written_metadata_keys()

    unclassified = {
        key: where
        for key, where in found.items()
        if key not in INTERNAL_METADATA_KEYS | PUBLIC_KEYS
    }
    assert unclassified == {}
    assert "s3_key_reaped" in found and "s3_key" in found
