"""Manifest version 2 dataset fields: visibility, collection and attributes.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select, text, update

from app.core.config import settings
from app.modules.auth.models import User
from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.modules.catalog.datasets.domain.models import (
    AttributeMetadata,
    Dataset,
    Record,
)
from app.modules.catalog.datasets.domain.schemas import AttributeMetadataUpdate
from app.platform.jobs.models import IngestJob
from app.platform.jobs.schemas import ManifestCollectionRefusedWarning
from app.platform.request_credential import (
    _SESSION_KEY,
    ApiKeyCredential,
    record_api_key,
)
from app.processing.ingest import manifest_dataset_fields as fields_module
from app.processing.ingest.manifest_dataset_fields import (
    ManifestEntryFields,
    apply_dataset_fields,
    resolve_entry_collection,
)
from app.processing.ingest.manifest_schemas import (
    MAX_MANIFEST_ATTRIBUTES,
    ManifestApplyRequest,
    ManifestAttribute,
)
from app.processing.ingest.manifest_service import apply_manifest
from app.processing.ingest.manifest_sources import (
    classify_manifest_source,
    manifest_dataset_fingerprint,
    manifest_job_metadata,
)
from app.processing.ingest.tasks import reupload_file
from app.processing.ingest.tasks_common import IngestContext, _finalize_ingest
from tests.factories import create_dataset, create_user

pytestmark = pytest.mark.anyio

_FIXTURE = "tests/fixtures/ingest/basic_attrs.geojson"


def _entry(key: str, **overrides) -> dict:
    entry = {
        "key": key,
        "title": "Road centerlines",
        "sources": [{"type": "vector", "uri": _FIXTURE, "format": "geojson"}],
        "metadata": {"crs": "EPSG:4326"},
        "publication": {"intent": "published"},
    }
    return {**entry, **overrides}


def _request(entry: dict, *, version: str = "2", **extra) -> ManifestApplyRequest:
    body = {
        "manifest_version": version,
        "catalog": {"title": "Manifest catalog"},
        "datasets": [entry],
        **extra,
    }
    if version == "2":
        body["client"] = {"id": "geolens-qgis", "version": "0.2.0"}
    return ManifestApplyRequest.model_validate(body)


def _http_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/ingest/manifest/apply",
            "headers": [],
        }
    )


def _stage_fixture() -> None:
    destination = Path(settings.upload_staging_dir) / _FIXTURE
    destination.parent.mkdir(parents=True, exist_ok=True)
    copyfile(Path(__file__).parent / "fixtures/ingest/basic_attrs.geojson", destination)


async def _admin(session) -> User:
    return (
        await session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()


async def _person(client, session, admin_headers, role: str) -> User:
    _, user_id = await create_user(client, admin_headers, role)
    return await session.get(User, uuid.UUID(user_id))


def _forbid_public():
    """The gate as it answers a non-admin while public visibility is restricted."""

    async def gate(db, user, visibility, **kwargs):
        if visibility == "public":
            raise HTTPException(status_code=403, detail="restricted")

    return patch(
        "app.modules.catalog.authorization.check_public_visibility_allowed",
        new=AsyncMock(side_effect=gate),
    )


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------


def test_version_1_refuses_the_version_2_fields():
    for extra in (
        {"visibility": "private"},
        {"collection": {"name": "Parks"}},
        {"attributes": [{"source_name": "A"}]},
    ):
        with pytest.raises(ValidationError, match="manifest_version '2'"):
            _request(_entry("k", **extra), version="1")
    with pytest.raises(ValidationError, match="manifest_version '2'"):
        _request(_entry("k"), version="1", public_fallback="internal")


@pytest.mark.parametrize("field", ["visibility", "collection", "attributes"])
def test_version_1_refuses_an_explicit_null_version_2_field(field):
    with pytest.raises(ValidationError, match="manifest_version '2'"):
        _request(_entry("k", **{field: None}), version="1")


def test_version_1_refuses_an_explicit_null_public_fallback():
    with pytest.raises(ValidationError, match="manifest_version '2'"):
        _request(_entry("k"), version="1", public_fallback=None)


def test_public_fallback_only_names_internal():
    with pytest.raises(ValidationError):
        _request(_entry("k"), public_fallback="private")


def test_a_collection_names_exactly_one_of_id_and_name():
    _request(_entry("k", collection={"id": str(uuid.uuid4())}))
    _request(_entry("k", collection={"name": "Parks"}))
    for bad in ({}, {"id": str(uuid.uuid4()), "name": "Parks"}):
        with pytest.raises(ValidationError):
            _request(_entry("k", collection=bad))


def test_attribute_limits_are_the_attribute_metadata_updates():
    update_fields = AttributeMetadataUpdate.model_fields
    for name in ("title", "description", "units"):
        assert (
            ManifestAttribute.model_fields[name].metadata[0].max_length
            == update_fields[name].metadata[0].max_length
        )
    assert MAX_MANIFEST_ATTRIBUTES == 500


@pytest.mark.parametrize(
    "attribute",
    [
        {"source_name": "A", "title": "t" * 501},
        {"source_name": "A", "description": "d" * 2001},
        {"source_name": "A", "units": "u" * 51},
        {"source_name": ""},
        {"source_name": "A", "title": "nul\x00byte"},
    ],
)
def test_attribute_text_is_bounded(attribute):
    with pytest.raises(ValidationError):
        _request(_entry("k", attributes=[attribute]))


def test_attributes_are_capped_at_500():
    ok = [{"source_name": f"c{i}"} for i in range(500)]
    _request(_entry("k", attributes=ok))
    with pytest.raises(ValidationError):
        _request(_entry("k", attributes=[*ok, {"source_name": "one-more"}]))


def test_a_null_attribute_field_keeps_the_stored_text():
    request = _request(
        _entry(
            "k",
            attributes=[{"source_name": "A", "title": "Name", "description": None}],
        )
    )
    entry = request.datasets[0]
    metadata = fields_module.job_metadata_fields(
        entry, ManifestEntryFields(visibility=None)
    )
    assert metadata["manifest_attributes"] == [{"source_name": "A", "title": "Name"}]


def test_a_version_1_result_has_no_messages_key():
    from app.processing.ingest.manifest_schemas import ManifestApplyEntryResult

    result = ManifestApplyEntryResult(dataset_key="k", action="skip", message="m")
    assert "messages" not in result.model_dump(mode="json")
    result.messages = []
    assert result.model_dump(mode="json")["messages"] == []


# ---------------------------------------------------------------------------
# Create: visibility, collection, attributes
# ---------------------------------------------------------------------------


async def _apply(session, user, request):
    with patch(
        "app.processing.ingest.manifest_service.queue_ingest_job", new=AsyncMock()
    ) as queue:
        response = await apply_manifest(session, request, user, _http_request())
    return response, queue


async def _finalize(session, user, job: IngestJob, *, columns=None):
    """The worker's commit of a created dataset, over a one-column table."""
    table = f"manifest_fields_{uuid.uuid4().hex[:10]}"
    await session.execute(
        text(f"CREATE TABLE data.{table} (gid serial PRIMARY KEY, name text)")
    )
    await session.commit()
    job.status = "running"
    await session.flush()
    try:
        with (
            patch(
                "app.processing.ingest.publish_followups.invalidate_catalog_cache",
                new=AsyncMock(),
            ),
            patch("app.processing.embeddings.helpers.defer_embedding", new=AsyncMock()),
        ):
            return await _finalize_ingest(
                IngestContext(
                    session=session,
                    job=job,
                    table_name=table,
                    user_id=str(user.id),
                    has_geometry=False,
                    effective_srid=None,
                    source_format="geojson",
                    source_filename="roads.geojson",
                    original_srid=None,
                    user_metadata=job.user_metadata,
                    source_columns=columns,
                )
            )
    finally:
        await session.execute(text(f'DROP TABLE IF EXISTS data."{table}" CASCADE'))
        await session.commit()


async def test_an_explicit_visibility_beats_the_intent_on_create(
    test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    request = _request(_entry("fields-private", visibility="private"))

    response, queue = await _apply(test_db_session, user, request)

    result = response.results[0]
    assert result.action == "create"
    assert result.messages == []
    queue.assert_awaited_once()
    job = await test_db_session.get(IngestJob, result.job_id)
    assert job.user_metadata["visibility"] == "private"
    assert job.user_metadata["record_status"] == "published"

    # The row the worker commits, not one fixed up afterwards.
    dataset = await _finalize(test_db_session, user, job)
    assert dataset.record.visibility == "private"
    assert dataset.record.record_status == "published"


async def test_an_omitted_visibility_creates_a_private_dataset(
    test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)

    response, _ = await _apply(test_db_session, user, _request(_entry("fields-omit")))

    job = await test_db_session.get(IngestJob, response.results[0].job_id)
    assert job.user_metadata["visibility"] == "private"
    dataset = await _finalize(test_db_session, user, job)
    assert dataset.record.visibility == "private"
    assert dataset.record.record_status == "published"


async def test_a_refused_public_is_an_error_and_queues_nothing(
    test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    request = _request(_entry("fields-refused", visibility="public"))

    with _forbid_public():
        response, queue = await _apply(test_db_session, user, request)

    result = response.results[0]
    assert (result.action, response.accepted) == ("error", False)
    assert [(m.code, m.severity) for m in result.messages] == [("A020", "error")]
    assert result.messages[0].message.startswith(
        "Public visibility is restricted on this server"
    )
    queue.assert_not_awaited()
    assert (
        await test_db_session.scalar(
            select(IngestJob.id).where(
                IngestJob.user_metadata["manifest_key"].astext == "fields-refused"
            )
        )
        is None
    )


async def test_public_fallback_writes_internal_with_a_warning(
    test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    request = _request(
        _entry("fields-fallback", visibility="public"), public_fallback="internal"
    )

    with _forbid_public():
        response, queue = await _apply(test_db_session, user, request)

    result = response.results[0]
    assert result.action == "create"
    assert [(m.code, m.severity) for m in result.messages] == [("A020", "warning")]
    queue.assert_awaited_once()
    job = await test_db_session.get(IngestJob, result.job_id)
    assert job.user_metadata["visibility"] == "internal"


async def test_public_fallback_does_not_widen_what_was_not_refused(
    test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    request = _request(
        _entry("fields-no-widen", visibility="private"), public_fallback="internal"
    )

    with _forbid_public() as gate:
        response, _ = await _apply(test_db_session, user, request)

    assert response.results[0].messages == []
    job = await test_db_session.get(IngestJob, response.results[0].job_id)
    assert job.user_metadata["visibility"] == "private"
    assert [call.args[2] for call in gate.call_args_list] == ["private"]


async def test_the_gate_checks_the_explicit_value_not_the_intent(
    test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    request = _request(_entry("fields-gated", visibility="internal"))

    with _forbid_public() as gate:
        response, _ = await _apply(test_db_session, user, request)

    assert response.results[0].action == "create"
    assert [call.args[2] for call in gate.call_args_list] == ["internal"]


async def test_a_collection_is_created_and_the_dataset_joins_it(
    test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    request = _request(_entry("fields-collection", collection={"name": "Parks"}))

    response, _ = await _apply(test_db_session, user, request)

    assert response.results[0].messages == []
    job = await test_db_session.get(IngestJob, response.results[0].job_id)
    collection = await test_db_session.scalar(
        select(Collection).where(Collection.name == "Parks")
    )
    assert job.user_metadata["manifest_collection_id"] == str(collection.id)

    dataset = await _finalize(test_db_session, user, job)
    member = await test_db_session.scalar(
        select(CollectionDataset).where(CollectionDataset.dataset_id == dataset.id)
    )
    assert member.collection_id == collection.id
    assert "warnings" not in (job.user_metadata or {})


async def test_a_dry_run_leaves_no_collection_behind(test_db_session, clean_tables):
    _stage_fixture()
    user = await _admin(test_db_session)
    request = _request(_entry("fields-dry", collection={"name": "Dry"}), dry_run=True)

    response, queue = await _apply(test_db_session, user, request)

    assert response.results[0].messages == []
    queue.assert_not_awaited()
    assert (
        await test_db_session.scalar(select(Collection).where(Collection.name == "Dry"))
        is None
    )


class _Recorder:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def emit(self, session, event) -> None:
        self.actions.append(event.action)


async def test_a_dry_run_naming_a_new_collection_writes_and_emits_nothing(
    test_db_session, clean_tables
):
    from app.modules.audit.models import AuditLog
    from app.platform.extensions import _extensions
    from app.platform.extensions.defaults import DefaultAuditSink

    _stage_fixture()
    user = await _admin(test_db_session)
    recorder = _Recorder()
    saved = _extensions.get("audit_sinks")
    _extensions["audit_sinks"] = [DefaultAuditSink(), recorder]
    try:
        result = await _dry_run(
            test_db_session,
            user,
            _entry("fields-dry-collection", collection={"name": "Dry parks"}),
        )
    finally:
        if saved is None:
            _extensions.pop("audit_sinks", None)
        else:
            _extensions["audit_sinks"] = saved

    # An apply would create it, so the preview warns of nothing.
    assert (result.action, result.messages) == ("create", [])
    assert recorder.actions == []
    assert (
        await test_db_session.scalar(
            select(Collection.id).where(Collection.name == "Dry parks")
        )
        is None
    )
    assert (
        await test_db_session.scalar(
            select(AuditLog.id).where(
                AuditLog.action == "collection.create",
                AuditLog.details["name"].astext == "Dry parks",
            )
        )
        is None
    )


async def test_a_caller_without_manage_collections_gets_a033(
    client, test_db_session, admin_auth_header, clean_tables
):
    viewer = await _person(client, test_db_session, admin_auth_header, "viewer")
    entry = _request(_entry("fields-viewer", collection={"name": "Viewer made"}))
    fields = ManifestEntryFields(visibility=None)

    await resolve_entry_collection(
        test_db_session, entry.datasets[0], viewer, fields, dry_run=False
    )

    assert [(m.code, m.severity) for m in fields.messages] == [("A033", "warning")]
    assert fields.collection_id is None
    assert (
        await test_db_session.scalar(
            select(Collection).where(Collection.name == "Viewer made")
        )
        is None
    )


async def _job_for(session, user: User, **metadata) -> IngestJob:
    job = IngestJob(
        source_filename="roads.geojson",
        created_by=user.id,
        status="running",
        user_metadata={"manifest_key": "tail", **metadata},
    )
    session.add(job)
    await session.flush()
    return job


async def test_the_tail_refuses_a_submitter_who_cannot_add_to_the_collection(
    client, test_db_session, admin_auth_header, clean_tables
):
    viewer = await _person(client, test_db_session, admin_auth_header, "viewer")
    # The viewer owns it, so only the missing permission can refuse them.
    collection = Collection(name="viewer-owned", created_by=viewer.id)
    test_db_session.add(collection)
    dataset = await create_dataset(test_db_session, created_by=viewer.id)
    job = await _job_for(
        test_db_session, viewer, manifest_collection_id=str(collection.id)
    )

    await apply_dataset_fields(test_db_session, job, dataset, job.user_metadata)

    assert [w["kind"] for w in job.user_metadata["warnings"]] == [
        "manifest_collection_refused"
    ]
    assert (
        await test_db_session.scalar(
            select(CollectionDataset).where(CollectionDataset.dataset_id == dataset.id)
        )
        is None
    )


async def test_the_tail_does_not_trust_a_collection_id_it_cannot_read(
    test_db_session, clean_tables
):
    user = await _admin(test_db_session)
    dataset = await create_dataset(test_db_session, created_by=user.id)
    job = await _job_for(test_db_session, user, manifest_collection_id="not-a-uuid")

    await apply_dataset_fields(test_db_session, job, dataset, job.user_metadata)

    assert [w["kind"] for w in job.user_metadata["warnings"]] == [
        "manifest_collection_refused"
    ]


async def test_a_busy_collection_is_a033_and_keeps_the_tails_transaction(
    test_db_session, clean_tables, monkeypatch
):
    import app.core.db as db_module

    monkeypatch.setattr(
        "app.modules.catalog.collections.manifest.WORKER_LOCK_TIMEOUT", "200ms"
    )
    user = await _admin(test_db_session)
    collection = Collection(name="busy", created_by=user.id)
    test_db_session.add(collection)
    dataset = await create_dataset(test_db_session, created_by=user.id)
    await test_db_session.commit()
    # Uncommitted, as the tail's new dataset is.
    job = await _job_for(
        test_db_session, user, manifest_collection_id=str(collection.id)
    )

    async with db_module.async_session() as holder:
        await holder.execute(
            text("SELECT id FROM catalog.collections WHERE id = :id FOR UPDATE"),
            {"id": collection.id},
        )
        await apply_dataset_fields(test_db_session, job, dataset, job.user_metadata)
        await holder.rollback()
    await test_db_session.commit()

    (warning,) = job.user_metadata["warnings"]
    assert warning == {
        "kind": "manifest_collection_refused",
        "details": {"collection_id": str(collection.id), "reason": "busy"},
    }
    assert ManifestCollectionRefusedWarning.model_validate(warning).details.reason == (
        "busy"
    )
    assert await test_db_session.scalar(
        select(IngestJob.id).where(IngestJob.id == job.id)
    )
    assert (
        await test_db_session.scalar(
            select(CollectionDataset).where(CollectionDataset.dataset_id == dataset.id)
        )
        is None
    )


async def test_joining_a_collection_leaves_the_transactions_lock_timeout(
    test_db_session, clean_tables
):
    user = await _admin(test_db_session)
    collection = Collection(name="free", created_by=user.id)
    test_db_session.add(collection)
    dataset = await create_dataset(test_db_session, created_by=user.id)
    await test_db_session.commit()
    job = await _job_for(
        test_db_session, user, manifest_collection_id=str(collection.id)
    )
    await test_db_session.execute(text("SET LOCAL lock_timeout = '1234ms'"))

    await apply_dataset_fields(test_db_session, job, dataset, job.user_metadata)

    assert "warnings" not in job.user_metadata
    assert await test_db_session.scalar(
        text("SELECT current_setting('lock_timeout')")
    ) == ("1234ms")


@pytest.mark.parametrize(
    "count,applied", [(500, True), (501, False)], ids=["at-the-cap", "over-the-cap"]
)
async def test_the_tail_drops_more_attributes_than_an_apply_accepts(
    test_db_session, clean_tables, count, applied
):
    assert MAX_MANIFEST_ATTRIBUTES == 500
    user = await _admin(test_db_session)
    dataset = await create_dataset(test_db_session, created_by=user.id)
    job = await _job_for(
        test_db_session,
        user,
        manifest_attributes=[
            {"source_name": f"C{i}", "title": "t"} for i in range(count)
        ],
    )

    port = MagicMock()
    port.apply_manifest_attributes = AsyncMock(return_value=[])
    with patch.object(fields_module, "get_processing_port", return_value=port):
        await apply_dataset_fields(test_db_session, job, dataset, job.user_metadata)

    assert port.apply_manifest_attributes.await_count == int(applied)


async def test_an_unchanged_reapply_adds_a_collection_left_out_while_busy(
    test_db_session, clean_tables, monkeypatch
):
    import app.core.db as db_module

    monkeypatch.setattr(
        "app.modules.catalog.collections.manifest.WORKER_LOCK_TIMEOUT", "200ms"
    )
    _stage_fixture()
    user = await _admin(test_db_session)
    collection = Collection(name="Retry parks", created_by=user.id)
    test_db_session.add(collection)
    await test_db_session.commit()
    request = _request(_entry("fields-retry", collection={"id": str(collection.id)}))
    response, _ = await _apply(test_db_session, user, request)
    job = await test_db_session.get(IngestJob, response.results[0].job_id)

    async with db_module.async_session() as holder:
        await holder.execute(
            text("SELECT id FROM catalog.collections WHERE id = :id FOR UPDATE"),
            {"id": collection.id},
        )
        dataset = await _finalize(test_db_session, user, job)
        await holder.rollback()
    assert [w["details"].get("reason") for w in job.user_metadata["warnings"]] == [
        "busy"
    ]
    dataset_id = dataset.id

    again, queue = await _apply(test_db_session, user, request)

    assert (again.results[0].action, again.results[0].messages) == ("skip", [])
    queue.assert_not_awaited()
    member = await test_db_session.scalar(
        select(CollectionDataset.collection_id).where(
            CollectionDataset.dataset_id == dataset_id
        )
    )
    assert member == collection.id


def test_the_tails_add_the_collection_after_their_slow_work():
    """The collection row is held from the add to the commit, so nothing slow
    may run in between."""
    import inspect

    from app.processing.ingest.tasks_raster import ingest_raster

    raster = inspect.getsource(ingest_raster)
    added = raster.index("await apply_dataset_fields(")
    assert raster.rindex("await storage.put(") < added
    assert raster.index("await archive_lossy_original(") < added
    assert added < raster.index("await ledger.complete(")

    vector = inspect.getsource(_finalize_ingest)
    added = vector.index("await apply_dataset_fields(")
    assert vector.index("await compute_quality_score(") < added
    assert added < vector.index("await ledger.complete(")


async def test_attributes_are_saved_and_an_unknown_name_is_a092(
    test_db_session, clean_tables
):
    user = await _admin(test_db_session)
    dataset = await create_dataset(
        test_db_session,
        created_by=user.id,
        column_info=[{"name": "name", "type": "text", "source_name": "NAME"}],
    )
    test_db_session.add(
        AttributeMetadata(dataset_id=dataset.id, field_name="name", ordinal_position=0)
    )
    job = await _job_for(
        test_db_session,
        user,
        manifest_attributes=[
            {"source_name": "NAME", "title": "Place name", "units": "text"},
            {"source_name": "MISSING", "title": "Nope"},
        ],
    )

    await apply_dataset_fields(test_db_session, job, dataset, job.user_metadata)

    attribute = await test_db_session.scalar(
        select(AttributeMetadata).where(AttributeMetadata.dataset_id == dataset.id)
    )
    assert (attribute.title, attribute.units) == ("Place name", "text")
    assert job.user_metadata["warnings"] == [
        {
            "kind": "manifest_attribute_unmatched",
            "details": {"source_names": ["MISSING"]},
        }
    ]


async def test_the_tail_drops_attributes_that_no_longer_validate(
    test_db_session, clean_tables
):
    user = await _admin(test_db_session)
    dataset = await create_dataset(
        test_db_session,
        created_by=user.id,
        column_info=[{"name": "name", "type": "text", "source_name": "NAME"}],
    )
    test_db_session.add(
        AttributeMetadata(dataset_id=dataset.id, field_name="name", ordinal_position=0)
    )
    job = await _job_for(
        test_db_session,
        user,
        manifest_attributes=[{"source_name": "NAME", "title": "t" * 501}],
    )

    await apply_dataset_fields(test_db_session, job, dataset, job.user_metadata)

    attribute = await test_db_session.scalar(
        select(AttributeMetadata).where(AttributeMetadata.dataset_id == dataset.id)
    )
    assert attribute.title is None
    assert "warnings" not in job.user_metadata


async def test_a_job_no_manifest_made_changes_nothing(test_db_session, clean_tables):
    user = await _admin(test_db_session)
    dataset = await create_dataset(test_db_session, created_by=user.id)
    job = IngestJob(
        source_filename="roads.geojson",
        created_by=user.id,
        status="running",
        user_metadata={"manifest_attributes": [{"source_name": "X", "title": "t"}]},
    )
    test_db_session.add(job)
    await test_db_session.flush()

    await apply_dataset_fields(test_db_session, job, dataset, job.user_metadata)

    assert "warnings" not in job.user_metadata


async def test_create_records_the_tile_cache_version_at_completion(
    test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    response, _ = await _apply(test_db_session, user, _request(_entry("fields-tiles")))
    job = await test_db_session.get(IngestJob, response.results[0].job_id)

    dataset = await _finalize(test_db_session, user, job)

    assert job.user_metadata["manifest_tile_cache_version"] == (
        dataset.tile_cache_version
    )


async def test_create_with_attributes_through_the_ingest_tail(
    test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    request = _request(
        _entry(
            "fields-attrs",
            attributes=[
                {"source_name": "Name", "title": "Place"},
                {"source_name": "Absent"},
            ],
        )
    )
    response, _ = await _apply(test_db_session, user, request)
    job = await test_db_session.get(IngestJob, response.results[0].job_id)

    dataset = await _finalize(test_db_session, user, job, columns=[{"name": "Name"}])

    title = await test_db_session.scalar(
        select(AttributeMetadata.title).where(
            AttributeMetadata.dataset_id == dataset.id,
            AttributeMetadata.field_name == "name",
        )
    )
    assert title == "Place"
    assert [w["details"] for w in job.user_metadata["warnings"]] == [
        {"source_names": ["Absent"]}
    ]


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


async def _published_by_manifest(session, user: User, key: str) -> uuid.UUID:
    """A public, published dataset an earlier apply of ``key`` created."""
    table = f"manifest_upd_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        session,
        created_by=user.id,
        name="Road centerlines",
        table_name=table,
        record_type="vector_dataset",
        geometry_type="Point",
        feature_count=1,
        column_info=[{"name": "name", "type": "text"}],
    )
    await session.execute(
        text(
            f'CREATE TABLE "data"."{table}" (gid serial PRIMARY KEY, '
            "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326), name text)"
        )
    )
    original = _request(_entry(key), version="1").datasets[0]
    prepared = await classify_manifest_source(original.sources[0])
    session.add(
        IngestJob(
            dataset_id=dataset.id,
            source_filename=prepared.source_filename,
            file_path=prepared.file_path,
            created_by=user.id,
            status="complete",
            completed_at=datetime.now(timezone.utc),
            user_metadata={
                **manifest_job_metadata(
                    original,
                    prepared,
                    fingerprint=manifest_dataset_fingerprint(original),
                ),
                "manifest_tile_cache_version": 1,
            },
        )
    )
    await session.commit()
    return dataset.id


async def _stage_rows(file_path, staging_table, db_conn_str, **kwargs):
    """Stands in for ogr2ogr, whose connection is not the test database's."""
    import app.core.db as db_module

    async with db_module.async_session() as session:
        await session.execute(
            text(
                f'CREATE TABLE "data"."{staging_table}" '
                "(gid serial PRIMARY KEY, geom geometry(Point, 4326), name text)"
            )
        )
        await session.execute(
            text(
                f'INSERT INTO "data"."{staging_table}" (geom, name) VALUES '
                "(ST_SetSRID(ST_MakePoint(2.35, 48.85), 4326), 'Paris')"
            )
        )
        await session.commit()


async def _queue_update(session, user, entry: dict, **extra):
    """Apply a version 2 update of the key; the result and its queued task."""
    task = MagicMock()
    task.defer_async = AsyncMock()
    port = MagicMock()
    port.reupload_file_task.return_value = task
    with patch(
        "app.processing.ingest.manifest_service.get_catalog_port", return_value=port
    ):
        response = await apply_manifest(
            session, _request(entry, **extra), user, _http_request()
        )
    return response.results[0], task


async def _update(session, user, entry: dict) -> tuple[IngestJob, uuid.UUID]:
    """Apply a version 2 update of the key and run its worker."""
    result, task = await _queue_update(session, user, entry)
    assert result.action == "update", result
    job = await _run_update(session, result, task)
    assert (job.status, job.error_message) == ("complete", None)
    return job, result.dataset_id


async def _run_update(session, result, task) -> IngestJob:
    """Run the reupload worker an update queued; the job as it ended."""
    with (
        patch(
            "app.processing.ingest.service.resolve_file_path",
            new=AsyncMock(side_effect=lambda path, job_id: path),
        ),
        patch(
            "app.processing.ingest.ogr.run_ogr2ogr",
            new=AsyncMock(side_effect=_stage_rows),
        ),
        patch("app.processing.ingest.metadata.grant_reader_access", new=AsyncMock()),
        patch(
            "app.processing.ingest.tasks_staging.get_storage", return_value=AsyncMock()
        ),
    ):
        await reupload_file(**task.defer_async.await_args.kwargs)
    return (
        await session.execute(
            select(IngestJob)
            .where(IngestJob.id == result.job_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _record(session, dataset_id: uuid.UUID) -> tuple[str, str]:
    return tuple(
        (
            await session.execute(
                select(Record.visibility, Record.record_status)
                .join(Dataset, Dataset.record_id == Record.id)
                .where(Dataset.id == dataset_id)
                .execution_options(populate_existing=True)
            )
        ).one()
    )


async def test_an_update_without_visibility_keeps_the_current_level(
    test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    key = "fields-keep"
    dataset_id = await _published_by_manifest(test_db_session, user, key)

    job, _ = await _update(
        test_db_session,
        user,
        _entry(key, title="Updated", publication={"intent": "draft"}),
    )

    assert "visibility" not in job.user_metadata
    assert await _record(test_db_session, dataset_id) == ("public", "draft")


async def test_an_update_with_a_visibility_applies_it(test_db_session, clean_tables):
    _stage_fixture()
    user = await _admin(test_db_session)
    key = "fields-change"
    dataset_id = await _published_by_manifest(test_db_session, user, key)

    await _update(test_db_session, user, _entry(key, visibility="internal"))

    assert await _record(test_db_session, dataset_id) == ("internal", "published")


async def test_an_update_records_the_tile_cache_version_it_left(
    test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    key = "fields-version"
    dataset_id = await _published_by_manifest(test_db_session, user, key)

    job, _ = await _update(test_db_session, user, _entry(key, visibility="internal"))

    version = await test_db_session.scalar(
        select(Dataset.tile_cache_version)
        .where(Dataset.id == dataset_id)
        .execution_options(populate_existing=True)
    )
    assert version > 1
    assert job.user_metadata["manifest_tile_cache_version"] == version


async def test_an_update_adds_the_collection_and_reports_attributes(
    test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    key = "fields-update-extras"
    dataset_id = await _published_by_manifest(test_db_session, user, key)

    job, _ = await _update(
        test_db_session,
        user,
        _entry(
            key,
            visibility="internal",
            collection={"name": "Updated parks"},
            attributes=[{"source_name": "name", "title": "Place"}],
        ),
    )

    member = await test_db_session.scalar(
        select(Collection.name)
        .join(CollectionDataset, CollectionDataset.collection_id == Collection.id)
        .where(CollectionDataset.dataset_id == dataset_id)
    )
    assert member == "Updated parks"
    # The staged table's columns don't line up with the fixture's source fields,
    # so no stored column records the name; the tail still reports it.
    assert job.user_metadata["warnings"] == [
        {
            "kind": "manifest_attribute_unmatched",
            "details": {"source_names": ["name"]},
        }
    ]


async def test_a_held_run_accepted_later_keeps_the_collection_and_attributes():
    from app.modules.catalog.datasets.api.refresh_acceptance import (
        _accepted_upload_metadata,
    )

    blocked = IngestJob(
        user_metadata={
            "manifest_key": "held",
            "manifest_collection_id": str(uuid.uuid4()),
            "manifest_attributes": [{"source_name": "A", "title": "Alpha"}],
        }
    )

    carried = _accepted_upload_metadata(
        blocked,
        dataset_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        fingerprint="f",
        held_version=1,
    )

    assert (
        carried["manifest_collection_id"]
        == blocked.user_metadata["manifest_collection_id"]
    )
    assert (
        carried["manifest_attributes"] == blocked.user_metadata["manifest_attributes"]
    )


# ---------------------------------------------------------------------------
# Who can read the record an update leaves
# ---------------------------------------------------------------------------


_KEY_REFUSAL = "A publish key can't make anything public"


@contextmanager
def _publish_key(session):
    """The session as a publish-scoped key's request sees it."""
    record_api_key(
        session, ApiKeyCredential(id=uuid.uuid4(), scope="publish", dataset_id=None)
    )
    try:
        yield
    finally:
        session.info.pop(_SESSION_KEY, None)


@pytest.fixture
def _restricted_public(monkeypatch):
    import app.core.persistent_config as pc

    class _On:
        async def get(self, _db):
            return True

        get_uncached = get

    monkeypatch.setattr(pc, "RESTRICT_PUBLIC_VISIBILITY", _On())


async def _set_record(session, dataset_id, visibility: str, record_status: str):
    record_id = select(Dataset.record_id).where(Dataset.id == dataset_id)
    await session.execute(
        update(Record)
        .where(Record.id == record_id.scalar_subquery())
        .values(visibility=visibility, record_status=record_status)
    )
    await session.commit()


async def _manifest_dataset(session, user, key, visibility, record_status):
    dataset_id = await _published_by_manifest(session, user, key)
    await _set_record(session, dataset_id, visibility, record_status)
    return dataset_id


async def _jobs_for(session, key: str) -> int:
    return len(
        (
            await session.execute(
                select(IngestJob.id).where(
                    IngestJob.user_metadata["manifest_key"].astext == key
                )
            )
        ).all()
    )


async def _uploaded(client, headers, key: str, **overrides) -> dict:
    """An entry whose source the caller uploaded, as a key holder's must be."""
    body = (Path(__file__).parent / "fixtures/ingest/basic_attrs.geojson").read_bytes()
    response = await client.post(
        "/ingest/upload",
        files={"file": ("roads.geojson", body, "application/geo+json")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    source = {
        "type": "vector",
        "uri": f"upload:{response.json()['job_id']}",
        "checksum": "sha256:" + hashlib.sha256(body).hexdigest(),
    }
    return _entry(key, sources=[source], **overrides)


async def _editor(client, session, admin_headers) -> tuple[dict, User]:
    headers, user_id = await create_user(client, admin_headers, "editor")
    return headers, await session.get(User, uuid.UUID(user_id))


async def test_a_publish_key_cannot_publish_a_public_draft_it_leaves_public(
    client, test_db_session, admin_auth_header, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    key = "audience-key-omitted"
    dataset_id = await _manifest_dataset(test_db_session, user, key, "public", "draft")

    with _publish_key(test_db_session):
        result, task = await _queue_update(
            test_db_session, user, await _uploaded(client, admin_auth_header, key)
        )

    assert result.action == "error", result
    assert [(m.code, m.severity) for m in result.messages] == [("A020", "error")]
    assert result.messages[0].message.startswith(_KEY_REFUSAL)
    task.defer_async.assert_not_awaited()
    assert await _jobs_for(test_db_session, key) == 1
    assert await _record(test_db_session, dataset_id) == ("public", "draft")


async def test_public_fallback_shares_a_publish_keys_public_draft_internally(
    client, test_db_session, admin_auth_header, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    key = "audience-key-omitted-fallback"
    dataset_id = await _manifest_dataset(test_db_session, user, key, "public", "draft")

    with _publish_key(test_db_session):
        result, task = await _queue_update(
            test_db_session,
            user,
            await _uploaded(client, admin_auth_header, key),
            public_fallback="internal",
        )
    assert result.action == "update", result
    job = await _run_update(test_db_session, result, task)

    assert [(m.code, m.severity) for m in result.messages] == [("A020", "warning")]
    assert result.messages[0].message.startswith(_KEY_REFUSAL)
    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, dataset_id) == ("internal", "published")


async def test_the_gate_refuses_a_publish_key_that_names_public(
    client, test_db_session, admin_auth_header, clean_tables
):
    """The gate on the entry's own visibility, before anything is staged: an
    A020, not the widening rule's plain refusal further on."""
    _stage_fixture()
    user = await _admin(test_db_session)
    key = "audience-key-public"
    dataset_id = await _manifest_dataset(test_db_session, user, key, "public", "draft")

    with _publish_key(test_db_session):
        result, task = await _queue_update(
            test_db_session,
            user,
            await _uploaded(client, admin_auth_header, key, visibility="public"),
        )

    assert result.action == "error", result
    assert [(m.code, m.severity) for m in result.messages] == [("A020", "error")]
    assert result.messages[0].message.startswith(_KEY_REFUSAL)
    task.defer_async.assert_not_awaited()
    assert await _record(test_db_session, dataset_id) == ("public", "draft")


async def test_a_publish_key_narrows_a_public_draft_as_it_publishes_it(
    client, test_db_session, admin_auth_header, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    key = "audience-key-private"
    dataset_id = await _manifest_dataset(test_db_session, user, key, "public", "draft")

    with _publish_key(test_db_session):
        result, task = await _queue_update(
            test_db_session,
            user,
            await _uploaded(client, admin_auth_header, key, visibility="private"),
        )
    assert result.action == "update", result
    job = await _run_update(test_db_session, result, task)

    assert job.user_metadata["visibility"] == "private"
    # The id of the key the publish holds the job to.
    assert uuid.UUID(job.user_metadata["admitted_publish_key"])
    assert (job.status, job.error_message) == ("complete", None)
    # The row the worker commits: published, and never public while it is.
    assert await _record(test_db_session, dataset_id) == ("private", "published")


async def test_a_publish_key_cannot_widen_through_a_manifest(
    client, test_db_session, admin_auth_header, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    key = "audience-key-widen"
    dataset_id = await _manifest_dataset(test_db_session, user, key, "private", "draft")

    with _publish_key(test_db_session):
        result, task = await _queue_update(
            test_db_session,
            user,
            await _uploaded(
                client,
                admin_auth_header,
                key,
                visibility="internal",
                publication={"intent": "draft"},
            ),
        )

    assert result.action == "error", result
    assert result.errors == ["A publish key can't widen a dataset's visibility"]
    task.defer_async.assert_not_awaited()
    assert await _record(test_db_session, dataset_id) == ("private", "draft")


@pytest.mark.usefixtures("_restricted_public")
async def test_a_non_admin_may_publish_a_public_draft_while_public_is_restricted(
    client, test_db_session, admin_auth_header, clean_tables
):
    """The restriction is on naming public; the record status is the owner's."""
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    key = "audience-restricted"
    dataset_id = await _manifest_dataset(
        test_db_session, editor, key, "public", "draft"
    )

    result, task = await _queue_update(
        test_db_session, editor, await _uploaded(client, headers, key)
    )
    assert (result.action, result.messages) == ("update", []), result
    job = await _run_update(test_db_session, result, task)

    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, dataset_id) == ("public", "published")


async def test_the_publish_refuses_a_publish_key_once_the_dataset_went_public(
    client, test_db_session, admin_auth_header, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    key = "audience-key-raced"
    dataset_id = await _manifest_dataset(test_db_session, user, key, "private", "draft")
    with _publish_key(test_db_session):
        result, task = await _queue_update(
            test_db_session, user, await _uploaded(client, admin_auth_header, key)
        )
    assert result.action == "update", result

    # The owner shares it publicly while the replacement waits in the queue.
    await _set_record(test_db_session, dataset_id, "public", "draft")
    job = await _run_update(test_db_session, result, task)

    assert job.status == "failed"
    assert "may not open this dataset to more readers" in job.error_message
    assert await _record(test_db_session, dataset_id) == ("public", "draft")


@pytest.mark.usefixtures("_restricted_public")
async def test_the_publish_lets_a_non_admin_publish_a_dataset_made_public_meanwhile(
    client, test_db_session, admin_auth_header, clean_tables
):
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    key = "audience-restricted-raced"
    dataset_id = await _manifest_dataset(
        test_db_session, editor, key, "private", "draft"
    )
    result, task = await _queue_update(
        test_db_session, editor, await _uploaded(client, headers, key)
    )
    assert result.action == "update", result

    # An admin shares it publicly while the replacement waits in the queue.
    await _set_record(test_db_session, dataset_id, "public", "draft")
    job = await _run_update(test_db_session, result, task)

    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, dataset_id) == ("public", "published")


async def test_public_fallback_never_widens_a_publish_keys_private_dataset(
    client, test_db_session, admin_auth_header, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    key = "audience-key-fallback"
    dataset_id = await _manifest_dataset(test_db_session, user, key, "private", "draft")

    with _publish_key(test_db_session):
        result, task = await _queue_update(
            test_db_session,
            user,
            await _uploaded(client, admin_auth_header, key, visibility="public"),
            public_fallback="internal",
        )

    assert result.action == "error", result
    assert result.errors == ["A publish key can't widen a dataset's visibility"]
    task.defer_async.assert_not_awaited()
    assert await _record(test_db_session, dataset_id) == ("private", "draft")


@pytest.mark.usefixtures("_restricted_public")
@pytest.mark.parametrize(
    "fallback,ending", [(None, None), ("internal", "internal")], ids=["no", "fallback"]
)
async def test_a_non_admin_naming_public_on_an_update_while_restricted(
    client, test_db_session, admin_auth_header, clean_tables, fallback, ending
):
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    key = f"audience-restricted-named-{fallback or 'none'}"
    dataset_id = await _manifest_dataset(
        test_db_session, editor, key, "private", "draft"
    )
    extra = {} if fallback is None else {"public_fallback": fallback}

    result, task = await _queue_update(
        test_db_session,
        editor,
        await _uploaded(client, headers, key, visibility="public"),
        **extra,
    )

    assert [(m.code, m.message.split(",")[0]) for m in result.messages] == [
        ("A020", "Public visibility is restricted on this server")
    ]
    if ending is None:
        assert result.action == "error", result
        task.defer_async.assert_not_awaited()
        assert await _record(test_db_session, dataset_id) == ("private", "draft")
        return
    assert result.action == "update", result
    job = await _run_update(test_db_session, result, task)
    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, dataset_id) == ("internal", "published")


async def _replayed_public_entry(client, session, headers, user, key) -> dict:
    """An entry naming public, already published unchanged: its replay skips."""
    entry = await _uploaded(client, headers, key, visibility="public")
    dataset_id = await _manifest_dataset(session, user, key, "public", "published")
    await session.execute(
        update(IngestJob)
        .where(IngestJob.dataset_id == dataset_id)
        .values(
            user_metadata=IngestJob.user_metadata.op("||")(
                {
                    "manifest_fingerprint": manifest_dataset_fingerprint(
                        _request(entry).datasets[0]
                    )
                }
            )
        )
    )
    await session.commit()
    return {"entry": entry, "dataset_id": dataset_id}


@pytest.mark.parametrize("fallback", [None, "internal"], ids=["no", "fallback"])
async def test_a_skipped_replay_reports_no_refused_public(
    client, test_db_session, admin_auth_header, clean_tables, fallback
):
    """A skip writes nothing, so it claims no fallback and blocks nothing."""
    _stage_fixture()
    user = await _admin(test_db_session)
    key = f"audience-replay-{fallback or 'none'}"
    replay = await _replayed_public_entry(
        client, test_db_session, admin_auth_header, user, key
    )
    extra = {} if fallback is None else {"public_fallback": fallback}

    with _publish_key(test_db_session):
        result, task = await _queue_update(
            test_db_session, user, replay["entry"], **extra
        )

    assert (result.action, result.messages) == ("skip", []), result
    task.defer_async.assert_not_awaited()
    assert await _record(test_db_session, replay["dataset_id"]) == (
        "public",
        "published",
    )


def _editors_without(monkeypatch, capability: str) -> None:
    from app.modules.auth import permissions

    effective = permissions.get_effective_permissions

    async def narrowed(db):
        matrix = await effective(db)
        matrix["editor"][capability] = False
        return matrix

    monkeypatch.setattr(permissions, "get_effective_permissions", narrowed)


_ATTRIBUTES = [{"source_name": "name", "title": "Place"}]


@pytest.mark.parametrize(
    "attributes,refused", [(_ATTRIBUTES, True), (None, False)], ids=["with", "without"]
)
async def test_an_upload_only_owner_cannot_edit_attributes_through_an_update(
    client,
    test_db_session,
    admin_auth_header,
    clean_tables,
    monkeypatch,
    attributes,
    refused,
):
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    key = f"attributes-upload-only-{'with' if attributes else 'without'}"
    dataset_id = await _manifest_dataset(
        test_db_session, editor, key, "private", "draft"
    )
    _editors_without(monkeypatch, "edit_metadata")
    entry = await _uploaded(client, headers, key)
    if attributes:
        entry["attributes"] = attributes

    result, task = await _queue_update(test_db_session, editor, entry)

    if refused:
        assert result.action == "error", result
        assert result.errors == ["Missing permission: edit_metadata"]
        task.defer_async.assert_not_awaited()
        assert await _jobs_for(test_db_session, key) == 1
        return
    assert result.action == "update", result
    job = await _run_update(test_db_session, result, task)
    assert job.user_metadata["admitted_capability"] == "upload"
    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, dataset_id) == ("private", "published")


@pytest.mark.parametrize(
    "revoked", ["edit_metadata", "upload"], ids=["edit-metadata", "upload"]
)
async def test_attributes_need_both_capabilities_still_held_when_published(
    client, test_db_session, admin_auth_header, clean_tables, monkeypatch, revoked
):
    """Lost after queueing, either fails the replacement whole, as every
    door's recorded capability does: half a publish would replace the data
    and drop the edits the entry asked for."""
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    key = f"attributes-revoked-{revoked.replace('_', '-')}"
    dataset_id = await _manifest_dataset(
        test_db_session, editor, key, "private", "draft"
    )
    entry = await _uploaded(client, headers, key, attributes=_ATTRIBUTES)
    result, task = await _queue_update(test_db_session, editor, entry)
    assert result.action == "update", result

    _editors_without(monkeypatch, revoked)
    job = await _run_update(test_db_session, result, task)

    assert job.user_metadata["admitted_capability"] == "upload"
    assert job.status == "failed"
    assert "can no longer modify this dataset" in job.error_message
    assert await _record(test_db_session, dataset_id) == ("private", "draft")


async def test_the_publish_falls_back_when_a_key_would_open_a_dataset_made_public(
    client, test_db_session, admin_auth_header, clean_tables
):
    """Judged again when it publishes, a publish key's job takes its stored
    fallback where the dataset became a public draft meanwhile."""
    _stage_fixture()
    user = await _admin(test_db_session)
    key = "audience-key-raced-fallback"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "internal", "draft"
    )
    with _publish_key(test_db_session):
        result, task = await _queue_update(
            test_db_session,
            user,
            await _uploaded(client, admin_auth_header, key),
            public_fallback="internal",
        )
    assert (result.action, result.messages) == ("update", []), result

    await _set_record(test_db_session, dataset_id, "public", "draft")
    job = await _run_update(test_db_session, result, task)

    assert (job.status, job.error_message) == ("complete", None)
    assert job.user_metadata["warnings"] == [
        {"kind": "manifest_public_fallback", "details": {"reason": "key"}}
    ]
    assert await _record(test_db_session, dataset_id) == ("internal", "published")


@pytest.mark.parametrize("fallback", [None, "internal"], ids=["no", "fallback"])
async def test_the_publish_judges_a_named_public_by_the_restriction_as_it_is_then(
    client, test_db_session, admin_auth_header, clean_tables, monkeypatch, fallback
):
    """Queued while public was allowed, published after an admin restricted it."""
    import app.core.persistent_config as pc

    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    key = f"audience-restricted-later-{fallback or 'none'}"
    dataset_id = await _manifest_dataset(
        test_db_session, editor, key, "private", "draft"
    )
    extra = {} if fallback is None else {"public_fallback": fallback}
    result, task = await _queue_update(
        test_db_session,
        editor,
        await _uploaded(client, headers, key, visibility="public"),
        **extra,
    )
    assert (result.action, result.messages) == ("update", []), result

    class _On:
        async def get(self, _db):
            return True

        get_uncached = get

    monkeypatch.setattr(pc, "RESTRICT_PUBLIC_VISIBILITY", _On())
    job = await _run_update(test_db_session, result, task)

    if fallback is None:
        assert job.status == "failed"
        assert await _record(test_db_session, dataset_id) == ("private", "draft")
        return
    assert (job.status, job.error_message) == ("complete", None)
    assert job.user_metadata["warnings"] == [
        {"kind": "manifest_public_fallback", "details": {"reason": "restriction"}}
    ]
    assert await _record(test_db_session, dataset_id) == ("internal", "published")


async def _in_flight(session, user, entry: dict, **metadata) -> IngestJob:
    """A running job of ``entry``'s key, as an earlier apply left it."""
    job = IngestJob(
        source_filename="roads.geojson",
        created_by=user.id,
        status="running",
        user_metadata={
            "manifest_key": entry["key"],
            "manifest_fingerprint": manifest_dataset_fingerprint(
                _request(entry).datasets[0]
            ),
            "record_status": "published",
            **metadata,
        },
    )
    session.add(job)
    await session.commit()
    return job


@pytest.mark.parametrize(
    "stored,restricted",
    [
        ({"visibility": "public"}, False),
        ({"manifest_version": "2", "visibility": "public"}, True),
    ],
    ids=["version-1-job", "decided-otherwise"],
)
async def test_an_in_flight_job_publishing_otherwise_is_not_reported_as_a_skip(
    test_db_session, clean_tables, stored, restricted
):
    _stage_fixture()
    user = await _admin(test_db_session)
    entry = _entry("audience-in-flight", visibility="public")
    await _in_flight(test_db_session, user, entry, **stored)

    if restricted:
        with _forbid_public():
            response, queue = await _apply(
                test_db_session, user, _request(entry, public_fallback="internal")
            )
    else:
        response, queue = await _apply(test_db_session, user, _request(entry))

    result = response.results[0]
    assert (result.action, result.errors) == ("error", ["dataset_busy"]), result
    queue.assert_not_awaited()


async def test_a_publish_keys_create_without_visibility_is_private(
    client, test_db_session, admin_auth_header, clean_tables
):
    """The stored ``private`` is judged again by the key rule when the
    create runs, and passes."""
    user = await _admin(test_db_session)
    entry = await _uploaded(client, admin_auth_header, "audience-key-create")

    with _publish_key(test_db_session):
        response, queue = await _apply(test_db_session, user, _request(entry))

    result = response.results[0]
    assert (result.action, result.messages) == ("create", []), result
    queue.assert_awaited_once()
    job = await test_db_session.get(IngestJob, result.job_id)
    assert job.user_metadata["visibility"] == "private"
    assert uuid.UUID(job.user_metadata["admitted_publish_key"])
    dataset = await _finalize(test_db_session, user, job)
    assert (dataset.record.visibility, dataset.record.record_status) == (
        "private",
        "published",
    )


@pytest.mark.parametrize("fallback", [None, "internal"], ids=["no", "fallback"])
async def test_a_create_by_an_admin_demoted_before_it_runs_is_judged_again(
    client, test_db_session, admin_auth_header, clean_tables, monkeypatch, fallback
):
    """Admitted public as an admin while public was restricted; no longer an
    admin when the create runs."""
    import app.core.persistent_config as pc
    from app.processing.ingest.publication import WideningRefused
    from tests.write_recheck_races import _commit, _move_to_role

    class _On:
        async def get(self, _db):
            return True

        get_uncached = get

    monkeypatch.setattr(pc, "RESTRICT_PUBLIC_VISIBILITY", _On())
    _stage_fixture()
    _, admin_id = await create_user(client, admin_auth_header, "admin")
    admin = await test_db_session.get(User, uuid.UUID(admin_id))
    extra = {} if fallback is None else {"public_fallback": fallback}
    response, _ = await _apply(
        test_db_session,
        admin,
        _request(
            _entry(f"audience-demoted-{fallback or 'none'}", visibility="public"),
            **extra,
        ),
    )
    result = response.results[0]
    assert (result.action, result.messages) == ("create", []), result
    job = await test_db_session.get(IngestJob, result.job_id)
    assert job.user_metadata["visibility"] == "public"

    await _commit(_move_to_role(admin.id, "editor"))

    if fallback is None:
        with pytest.raises(WideningRefused):
            await _finalize(test_db_session, admin, job)
        return
    dataset = await _finalize(test_db_session, admin, job)
    assert (dataset.record.visibility, dataset.record.record_status) == (
        "internal",
        "published",
    )


async def test_an_in_flight_job_deciding_the_same_is_reported_as_a_skip(
    test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    entry = _entry("audience-in-flight-same", visibility="public")
    await _in_flight(
        test_db_session,
        user,
        entry,
        manifest_version="2",
        manifest_requested_visibility="public",
        visibility="public",
    )

    response, queue = await _apply(test_db_session, user, _request(entry))

    assert response.results[0].action == "skip", response.results[0]
    queue.assert_not_awaited()


async def test_a_publish_key_cannot_retry_a_manifest_job(
    client, test_db_session, admin_auth_header, clean_tables, tmp_path
):
    """Retry is not a door onto a stored manifest job: only the apply, which
    holds the key's lock, and accept write one."""
    from tests.test_api_key_publish_scope import _mint

    user = await _admin(test_db_session)
    staged = tmp_path / "roads.geojson"
    staged.write_text("{}")
    job = IngestJob(
        source_filename="roads.geojson",
        file_path=str(staged),
        created_by=user.id,
        status="failed",
        user_metadata={
            "manifest_key": "audience-retry",
            "manifest_version": "2",
            "manifest_collection_id": str(uuid.uuid4()),
        },
    )
    test_db_session.add(job)
    await test_db_session.commit()
    publish = await _mint(client, admin_auth_header, "publish")

    with patch("app.platform.jobs.router.queue_ingest_job", new=AsyncMock()) as queue:
        retried = await client.post(f"/jobs/{job.id}/retry", headers=publish)

    assert retried.status_code == 400, retried.text
    queue.assert_not_awaited()
    await test_db_session.refresh(job)
    assert job.status == "failed"


# ---------------------------------------------------------------------------
# Edits since the last publish
# ---------------------------------------------------------------------------


async def _bump_tile_cache_version(session, dataset_id: uuid.UUID) -> None:
    await session.execute(
        update(Dataset)
        .where(Dataset.id == dataset_id)
        .values(tile_cache_version=Dataset.tile_cache_version + 1)
    )
    await session.commit()


async def _dry_run(session, user, entry, **extra):
    response, queue = await _apply(
        session, user, _request(entry, dry_run=True, **extra)
    )
    queue.assert_not_awaited()
    return response.results[0]


async def test_a_feature_edit_between_publishes_warns_a053_on_the_dry_run(
    test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    key = "fields-edited"
    dataset_id = await _published_by_manifest(test_db_session, user, key)
    entry = _entry(key, visibility="internal")

    untouched = await _dry_run(test_db_session, user, entry)
    await _bump_tile_cache_version(test_db_session, dataset_id)
    edited = await _dry_run(test_db_session, user, entry)

    assert (untouched.action, untouched.messages) == ("update", [])
    assert edited.action == "update"
    assert [(m.code, m.severity) for m in edited.messages] == [("A053", "warning")]


async def test_a053_is_left_to_the_dry_run(test_db_session, clean_tables):
    _stage_fixture()
    user = await _admin(test_db_session)
    key = "fields-edited-real"
    dataset_id = await _published_by_manifest(test_db_session, user, key)
    await _bump_tile_cache_version(test_db_session, dataset_id)

    task = MagicMock()
    task.defer_async = AsyncMock()
    port = MagicMock()
    port.reupload_file_task.return_value = task
    with patch(
        "app.processing.ingest.manifest_service.get_catalog_port", return_value=port
    ):
        response = await apply_manifest(
            test_db_session,
            _request(_entry(key, visibility="internal")),
            user,
            _http_request(),
        )

    assert response.results[0].action == "update"
    assert response.results[0].messages == []
