"""A republished raster replaces its data on the same dataset.

A ``raster_cog`` entry whose key names a completed raster dataset queues the
raster replacement the re-upload door uses, under a manifest name of its own,
and the worker brings the record to the entry as a vector update does. A
publish key is refused: a replaced raster keeps no previous version.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Request
from sqlalchemy import delete, func, select, text, update

from app.core.config import settings
from app.modules.auth.models import User
from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import UNPUBLISHED_STORAGE_KEYS_FIELD, IngestJob
from app.platform.request_credential import (
    _SESSION_KEY,
    ApiKeyCredential,
    record_api_key,
)
from app.processing.ingest.manifest_dataset_fields import (
    TILE_CACHE_VERSION_METADATA_KEY,
)
from app.processing.ingest.manifest_schemas import ManifestApplyRequest
from app.processing.ingest.manifest_service import (
    MANIFEST_KEY_NOT_OWNED,
    apply_manifest,
)
from app.processing.ingest.manifest_sources import (
    classify_manifest_source,
    manifest_dataset_fingerprint,
    manifest_job_metadata,
)
from app.processing.ingest.tasks import reupload_manifest_raster, reupload_raster
from app.processing.raster.models import RasterAsset
from tests.test_raster_replace_1221 import (
    _geotiff_bytes,
    _make_live_raster,
    _make_vrt_parent,
    _purge,
    _purge_vrt,
)
from tests.test_raster_replace_1221 import raster_storage as raster_storage

pytestmark = pytest.mark.anyio

_CLIENT = {"id": "geolens-qgis", "version": "0.3.0"}
_MANIFEST_TASK = "app.ingest.tasks.reupload_manifest_raster"


def _entry(
    key: str, uri: str, checksum: str, *, intent: str = "published", **extra
) -> dict:
    return {
        "key": key,
        "title": extra.pop("title", "Elevation"),
        "sources": [{"type": "raster_cog", "uri": uri, "checksum": checksum}],
        "metadata": {"crs": "EPSG:4326"},
        "publication": {"intent": intent},
        **extra,
    }


def _request(
    entry: dict, version: str = "1", *, dry_run: bool = False
) -> ManifestApplyRequest:
    body: dict = {
        "manifest_version": version,
        "catalog": {"title": "Terrain"},
        "datasets": [entry],
        "dry_run": dry_run,
    }
    if version == "2":
        body["client"] = _CLIENT
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


async def _admin(session) -> User:
    return (
        await session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()


class _Published:
    """A raster dataset an earlier apply of ``key`` published, and its source."""

    def __init__(self, live, key: str, uri: str) -> None:
        self.live = live
        self.key = key
        self.uri = uri
        self.dataset_id = live.dataset.id
        self.record_id = live.dataset.record_id
        self.staged = Path(settings.upload_staging_dir) / uri


async def _published(session, storage, user: User) -> _Published:
    """A live raster with a completed apply of its key, and a resurveyed file
    staged under the same URI, as an operator republishing it would leave it."""
    live = await _make_live_raster(session, storage, created_by=user.id)
    key = f"dem-{uuid.uuid4().hex[:8]}"
    uri = f"rasters/{key}.tif"
    original = _request(_entry(key, uri, f"sha256:{'a' * 64}")).datasets[0]
    prepared = await classify_manifest_source(original.sources[0])
    session.add(
        IngestJob(
            dataset_id=live.dataset.id,
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
                TILE_CACHE_VERSION_METADATA_KEY: live.dataset.tile_cache_version,
            },
        )
    )
    await session.commit()
    published = _Published(live, key, uri)
    published.staged.parent.mkdir(parents=True, exist_ok=True)
    published.staged.write_bytes(_geotiff_bytes(seed=2027))
    return published


def _resurveyed(published: _Published) -> str:
    return "sha256:" + hashlib.sha256(published.staged.read_bytes()).hexdigest()


async def _apply(session, request: ManifestApplyRequest, user: User):
    """Apply ``request``; returns its one result and the deferral, if any."""
    defer = AsyncMock()
    with patch(
        "app.processing.ingest.manifest_service.defer_async_with_tenant", new=defer
    ):
        response = await apply_manifest(session, request, user, _http_request())
    [result] = response.results
    return result, defer


async def _run_worker(defer) -> None:
    task = defer.await_args.args[0]
    assert task.name == _MANIFEST_TASK
    await reupload_manifest_raster.func(**defer.await_args.kwargs)


async def _jobs_for_key(session, key: str) -> list[IngestJob]:
    return list(
        (
            await session.execute(
                select(IngestJob)
                .where(IngestJob.user_metadata["manifest_key"].astext == key)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


async def _pending_upload(session, owner_id: uuid.UUID, path: Path) -> uuid.UUID:
    """A pending upload of ``path`` by ``owner_id``, as the upload door leaves one."""
    upload = IngestJob(
        source_filename="dem.tif",
        file_path=str(path),
        created_by=owner_id,
        status="pending",
        user_metadata={"title": "dem"},
    )
    session.add(upload)
    await session.commit()
    return upload.id


async def _delete_job(session, job_id: uuid.UUID) -> None:
    await session.execute(delete(IngestJob).where(IngestJob.id == job_id))
    await session.commit()


async def _cleanup(session, published: _Published) -> None:
    published.staged.unlink(missing_ok=True)
    await _purge(
        session, dataset_id=published.dataset_id, record_id=published.record_id
    )


def test_the_manifest_name_runs_the_raster_replacement() -> None:
    """Earlier workers lack the name, so none of them runs a manifest's
    replacement without its record fields."""
    assert reupload_manifest_raster.func is reupload_raster.func
    assert reupload_manifest_raster.name == _MANIFEST_TASK
    assert reupload_manifest_raster.queue == "raster"


async def test_a_republished_raster_replaces_its_data_on_the_same_dataset(
    test_db_session, raster_storage
):
    user = await _admin(test_db_session)
    published = await _published(test_db_session, raster_storage, user)
    old_tile_version = published.live.dataset.tile_cache_version
    old_cog = published.live.cog_key
    try:
        result, defer = await _apply(
            test_db_session,
            _request(
                _entry(
                    published.key,
                    published.uri,
                    _resurveyed(published),
                    title="Elevation 2027",
                )
            ),
            user,
        )
        assert (result.action, result.dataset_id) == (
            "update",
            published.dataset_id,
        ), result
        await _run_worker(defer)

        test_db_session.expire_all()
        job = await test_db_session.get(IngestJob, result.job_id)
        assert (job.status, job.error_message) == ("complete", None)
        assert job.dataset_id == published.dataset_id
        dataset = await test_db_session.get(Dataset, published.dataset_id)
        assert dataset.tile_cache_version == old_tile_version + 1
        asset = (
            await test_db_session.execute(
                select(RasterAsset).where(
                    RasterAsset.dataset_id == published.dataset_id
                )
            )
        ).scalar_one()
        assert asset.asset_uri != old_cog
        assert await raster_storage.exists(asset.asset_uri)
        record = await test_db_session.get(Record, published.record_id)
        assert record.title == "Elevation 2027"
    finally:
        await _cleanup(test_db_session, published)


async def test_a_version_2_raster_update_applies_the_entry_fields(
    test_db_session, raster_storage
):
    user = await _admin(test_db_session)
    published = await _published(test_db_session, raster_storage, user)
    collection_name = f"Terrain {uuid.uuid4().hex[:8]}"
    try:
        result, defer = await _apply(
            test_db_session,
            _request(
                _entry(
                    published.key,
                    published.uri,
                    _resurveyed(published),
                    title="Elevation (resurveyed)",
                    description="Lidar resurvey",
                    visibility="internal",
                    collection={"name": collection_name},
                ),
                version="2",
            ),
            user,
        )
        assert result.action == "update", result
        await _run_worker(defer)

        test_db_session.expire_all()
        job = await test_db_session.get(IngestJob, result.job_id)
        assert (job.status, job.error_message) == ("complete", None)
        record = await test_db_session.get(Record, published.record_id)
        assert (record.title, record.summary, record.visibility) == (
            "Elevation (resurveyed)",
            "Lidar resurvey",
            "internal",
        )
        member = await test_db_session.scalar(
            select(func.count())
            .select_from(CollectionDataset)
            .join(Collection, Collection.id == CollectionDataset.collection_id)
            .where(
                Collection.name == collection_name,
                CollectionDataset.dataset_id == published.dataset_id,
            )
        )
        assert member == 1
        dataset = await test_db_session.get(Dataset, published.dataset_id)
        assert job.user_metadata["manifest_tile_cache_version"] == (
            dataset.tile_cache_version
        )
    finally:
        await test_db_session.execute(
            delete(CollectionDataset).where(
                CollectionDataset.dataset_id == published.dataset_id
            )
        )
        await test_db_session.execute(
            delete(Collection).where(Collection.name == collection_name)
        )
        await test_db_session.commit()
        await _cleanup(test_db_session, published)


@pytest.mark.parametrize("version", ["1", "2"])
async def test_a_publish_key_is_refused_a_raster_update_and_nothing_is_queued(
    test_db_session, raster_storage, version
):
    """A publish key reaches a version 1 entry by URL and a version 2 one by
    its own upload; either is refused before staging. It can't ask for public."""
    user = await _admin(test_db_session)
    published = await _published(test_db_session, raster_storage, user)
    upload_id = await _pending_upload(test_db_session, user.id, published.staged)
    uri = (
        "https://93.184.216.34/rasters/dem.tif"
        if version == "1"
        else f"upload:{upload_id}"
    )
    before = len(await _jobs_for_key(test_db_session, published.key))
    record_api_key(
        test_db_session,
        ApiKeyCredential(id=uuid.uuid4(), scope="publish", dataset_id=None),
    )
    try:
        with patch(
            "app.processing.ingest.manifest_service._stage_source_if_needed",
            new=AsyncMock(),
        ) as stage:
            result, defer = await _apply(
                test_db_session,
                _request(
                    _entry(
                        published.key, uri, _resurveyed(published), intent="internal"
                    ),
                    version=version,
                ),
                user,
            )
        stage.assert_not_awaited()
        assert result.action == "error", result
        assert "A publish key can't replace" in result.message
        if version == "2":
            assert [(m.code, m.severity) for m in result.messages] == [
                ("A054", "error")
            ]
        else:
            assert result.messages is None
        defer.assert_not_awaited()
        assert len(await _jobs_for_key(test_db_session, published.key)) == before
    finally:
        test_db_session.info.pop(_SESSION_KEY, None)
        await _delete_job(test_db_session, upload_id)
        await _cleanup(test_db_session, published)


async def test_a_dry_run_reports_the_publish_key_refusal(
    test_db_session, raster_storage
):
    user = await _admin(test_db_session)
    published = await _published(test_db_session, raster_storage, user)
    upload_id = await _pending_upload(test_db_session, user.id, published.staged)
    record_api_key(
        test_db_session,
        ApiKeyCredential(id=uuid.uuid4(), scope="publish", dataset_id=None),
    )
    try:
        entry = _entry(
            published.key,
            f"upload:{upload_id}",
            _resurveyed(published),
            intent="internal",
        )
        result, defer = await _apply(
            test_db_session, _request(entry, version="2", dry_run=True), user
        )
        assert result.action == "error", result
        assert [m.code for m in result.messages] == ["A054"]
        defer.assert_not_awaited()
    finally:
        test_db_session.info.pop(_SESSION_KEY, None)
        await _delete_job(test_db_session, upload_id)
        await _cleanup(test_db_session, published)


async def test_a_caller_without_write_access_is_refused_and_nothing_is_queued(
    test_db_session, raster_storage
):
    """Another account's upload, applied on the owner's key, reaches neither
    the dataset nor the queue, and the upload stays unclaimed."""
    owner = await _admin(test_db_session)
    published = await _published(test_db_session, raster_storage, owner)
    suffix = uuid.uuid4().hex[:8]
    other = User(
        username=f"raster_other_{suffix}",
        email=f"raster_other_{suffix}@example.invalid",
        password_hash="x",
    )
    test_db_session.add(other)
    await test_db_session.commit()
    other_id = other.id
    upload_id = await _pending_upload(test_db_session, other_id, published.staged)
    try:
        before = len(await _jobs_for_key(test_db_session, published.key))
        result, defer = await _apply(
            test_db_session,
            _request(
                _entry(published.key, f"upload:{upload_id}", _resurveyed(published)),
                version="2",
            ),
            (
                await test_db_session.execute(
                    select(User)
                    .where(User.id == other_id)
                    .execution_options(populate_existing=True)
                )
            ).scalar_one(),
        )
        assert (result.action, result.message) == ("error", MANIFEST_KEY_NOT_OWNED)
        defer.assert_not_awaited()
        assert len(await _jobs_for_key(test_db_session, published.key)) == before
        test_db_session.expire_all()
        upload_row = await test_db_session.get(IngestJob, upload_id)
        assert upload_row.status == "pending"
        assert "manifest_key" not in (upload_row.user_metadata or {})
    finally:
        await _delete_job(test_db_session, upload_id)
        await _cleanup(test_db_session, published)
        await test_db_session.execute(delete(User).where(User.id == other_id))
        await test_db_session.commit()


async def test_a_mosaic_member_is_replaced_and_its_old_cog_kept_for_the_mosaic(
    test_db_session, raster_storage
):
    """As through the re-upload door: the member's data is replaced, and the
    COG the mosaic was built from stays, charged under a retained row."""
    user = await _admin(test_db_session)
    published = await _published(test_db_session, raster_storage, user)
    parent = await _make_vrt_parent(
        test_db_session, raster_storage, created_by=user.id, member=published.live
    )
    old_cog = published.live.cog_key
    await test_db_session.execute(
        text(
            "UPDATE catalog.raster_assets "
            "SET built_from = CAST(:built_from AS jsonb) WHERE dataset_id = :id"
        ),
        {
            "built_from": json.dumps({str(published.dataset_id): old_cog}),
            "id": parent.dataset.id,
        },
    )
    await test_db_session.commit()
    ids = (
        parent.dataset.id,
        parent.dataset.record_id,
        published.dataset_id,
        published.record_id,
    )
    try:
        result, defer = await _apply(
            test_db_session,
            _request(_entry(published.key, published.uri, _resurveyed(published))),
            user,
        )
        assert (result.action, result.dataset_id) == (
            "update",
            published.dataset_id,
        ), result
        await _run_worker(defer)

        test_db_session.expire_all()
        job = await test_db_session.get(IngestJob, result.job_id)
        assert (job.status, job.error_message) == ("complete", None)
        live_cog = await test_db_session.scalar(
            select(RasterAsset.asset_uri).where(
                RasterAsset.dataset_id == published.dataset_id
            )
        )
        assert live_cog != old_cog
        assert await raster_storage.exists(old_cog)
        retained = await test_db_session.scalar(
            text(
                "SELECT href FROM catalog.dataset_assets "
                "WHERE dataset_id = :id AND key LIKE 'retained_cog:%'"
            ),
            {"id": published.dataset_id},
        )
        assert retained == old_cog
    finally:
        published.staged.unlink(missing_ok=True)
        await _purge_vrt(test_db_session, ids=ids)


async def test_a_raster_replaced_since_its_publish_warns_it_cant_be_restored(
    test_db_session, raster_storage
):
    """A053 on a raster says the data a republish discards is gone for good;
    the vector wording promises a restorable previous version."""
    user = await _admin(test_db_session)
    published = await _published(test_db_session, raster_storage, user)
    try:
        # A re-upload in GeoLens moves the tile cache version past the publish.
        await test_db_session.execute(
            update(Dataset)
            .where(Dataset.id == published.dataset_id)
            .values(tile_cache_version=Dataset.tile_cache_version + 1)
        )
        await test_db_session.commit()
        entry = _entry(
            published.key, published.uri, _resurveyed(published), intent="internal"
        )
        result, defer = await _apply(
            test_db_session, _request(entry, version="2", dry_run=True), user
        )
        assert result.action == "update", result
        [warning] = result.messages
        assert (warning.code, warning.severity) == ("A053", "warning")
        assert "a replaced raster can't be restored" in warning.message
        assert "restorable once" not in warning.message
        defer.assert_not_awaited()
    finally:
        await _cleanup(test_db_session, published)


async def test_a_refusal_in_the_raster_write_leaves_the_old_cog_serving(
    client, admin_auth_header, test_db_session, raster_storage, monkeypatch
):
    """Admitted public as an admin while public is restricted, no longer one
    when the replacement publishes: the record fields refuse inside the
    write, after the new COG was stored. The job fails, the old COG still
    serves and the attempt's keys are reaped."""
    import app.core.persistent_config as pc
    from tests.factories import create_user
    from tests.write_recheck_races import _commit, _move_to_role

    class _On:
        async def get(self, _db):
            return True

        get_uncached = get

    monkeypatch.setattr(pc, "RESTRICT_PUBLIC_VISIBILITY", _On())
    _, admin_id = await create_user(client, admin_auth_header, "admin")
    owner = (
        await test_db_session.execute(
            select(User).where(User.id == uuid.UUID(admin_id))
        )
    ).scalar_one()
    published = await _published(test_db_session, raster_storage, owner)
    await test_db_session.execute(
        update(Record)
        .where(Record.id == published.record_id)
        .values(visibility="internal")
    )
    await test_db_session.commit()
    old_cog = published.live.cog_key
    prefix = f"rasters/{published.dataset_id}/"
    keys_before = sorted(await raster_storage.list(prefix))
    try:
        entry = _entry(
            published.key,
            published.uri,
            _resurveyed(published),
            visibility="public",
        )
        result, defer = await _apply(test_db_session, _request(entry, "2"), owner)
        assert result.action == "update", result
        queued = await test_db_session.get(IngestJob, result.job_id)
        assert queued.user_metadata["admitted_public_visibility"] is True
        # Only the public admission is judged here, not the admin-only local
        # source the entry reads from.
        queued.user_metadata = {
            k: v for k, v in queued.user_metadata.items() if k != "admitted_raw_source"
        }
        await test_db_session.commit()
        await _commit(_move_to_role(owner.id, "editor"))

        await _run_worker(defer)

        test_db_session.expire_all()
        job = await test_db_session.get(IngestJob, result.job_id)
        assert job.status == "failed"
        assert "may not open this dataset to more readers" in job.error_message
        # The attempt named its keys before it stored them.
        attempt_keys = job.user_metadata[UNPUBLISHED_STORAGE_KEYS_FIELD]
        assert any(key.endswith("/source.cog.tif") for key in attempt_keys)
        for key in attempt_keys:
            assert not await raster_storage.exists(key), key
        live_cog = await test_db_session.scalar(
            select(RasterAsset.asset_uri).where(
                RasterAsset.dataset_id == published.dataset_id
            )
        )
        assert live_cog == old_cog
        assert await raster_storage.exists(old_cog)
        assert sorted(await raster_storage.list(prefix)) == keys_before
        record = await test_db_session.get(Record, published.record_id)
        assert record.visibility == "internal"
    finally:
        await _cleanup(test_db_session, published)


async def _throwaway_user(session) -> uuid.UUID:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"raster_new_owner_{suffix}",
        email=f"raster_new_owner_{suffix}@example.invalid",
        password_hash="x",
    )
    session.add(user)
    await session.commit()
    return user.id


def _transfer_while_staging(dataset_id: uuid.UUID, new_owner: uuid.UUID):
    """Stage the source, then commit a transfer of the dataset before the
    entry is admitted, as a transfer during a slow download would."""
    from app.processing.ingest import manifest_service
    from tests.write_recheck_races import _commit, _transfer_dataset

    real = manifest_service._stage_source_if_needed

    async def _stage(*args, **kwargs):
        staged = await real(*args, **kwargs)
        await _commit(_transfer_dataset(dataset_id, new_owner))
        return staged

    return patch.object(manifest_service, "_stage_source_if_needed", _stage)


async def test_a_raster_transferred_while_its_source_stages_is_not_replaced(
    test_db_session, raster_storage
):
    """The key is its owner's alone, an admin's too: the owner is read again
    under the admission lock, and nothing is queued for the new owner's data."""
    user = await _admin(test_db_session)
    published = await _published(test_db_session, raster_storage, user)
    new_owner = await _throwaway_user(test_db_session)
    old_cog = published.live.cog_key
    try:
        with _transfer_while_staging(published.dataset_id, new_owner):
            result, defer = await _apply(
                test_db_session,
                _request(_entry(published.key, published.uri, _resurveyed(published))),
                user,
            )
        assert (result.action, result.message) == ("error", MANIFEST_KEY_NOT_OWNED)
        defer.assert_not_awaited()
        test_db_session.expire_all()
        live_cog = await test_db_session.scalar(
            select(RasterAsset.asset_uri).where(
                RasterAsset.dataset_id == published.dataset_id
            )
        )
        assert live_cog == old_cog
        assert await raster_storage.exists(old_cog)
        [completed] = [
            job
            for job in await _jobs_for_key(test_db_session, published.key)
            if job.status == "complete"
        ]
        assert completed.dataset_id == published.dataset_id
    finally:
        await _cleanup(test_db_session, published)
        await test_db_session.execute(delete(User).where(User.id == new_owner))
        await test_db_session.commit()


async def test_a_vector_transferred_while_its_source_stages_is_not_replaced(
    test_db_session, clean_tables
):
    from tests.factories import create_dataset
    from tests.test_manifest_apply_service import (
        _create_completed_manifest_job,
        _manifest_dataset,
        _stage_basic_vector_fixture,
    )
    from tests.test_manifest_apply_service import _request as _v1_request

    _stage_basic_vector_fixture()
    user = await _admin(test_db_session)
    key = "vector-transferred-while-staging"
    dataset = await create_dataset(test_db_session, created_by=user.id)
    await _create_completed_manifest_job(
        test_db_session,
        user=user,
        dataset=dataset,
        manifest_dataset=_v1_request(_manifest_dataset(key=key)).datasets[0],
    )
    dataset_id = dataset.id
    new_owner = await _throwaway_user(test_db_session)
    try:
        with _transfer_while_staging(dataset_id, new_owner):
            result, defer = await _apply(
                test_db_session,
                _v1_request(_manifest_dataset(key=key, title="Resurveyed roads")),
                user,
            )
        assert (result.action, result.message) == ("error", MANIFEST_KEY_NOT_OWNED)
        defer.assert_not_awaited()
    finally:
        await test_db_session.execute(
            delete(IngestJob).where(IngestJob.dataset_id == dataset_id)
        )
        await test_db_session.commit()
        await test_db_session.execute(delete(User).where(User.id == new_owner))
        await test_db_session.commit()
