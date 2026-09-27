"""A vector import's archive of its original against a delete of its dataset.

The import commits the completed job and its dataset before it writes the
original under ``originals/<dataset id>/``, and a delete reaps that prefix
after its own commit. An import that can't take its job row leaves the
archive to the follow-ups, which write it under the same rule. All of it runs
for real here: the import on a fake ogr2ogr, the delete through its route, the
follow-ups, and the archive and the reap on one local store.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select, update

from app.core.config import settings
from app.modules.auth.models import User
from app.platform.jobs.models import (
    ARCHIVE_PENDING_METADATA_KEY,
    PUBLISH_FOLLOWUPS_FIELD,
    IngestJob,
)
from app.platform.storage import provider as storage_provider
from app.platform.storage.local import LocalStorageProvider
from app.processing.ingest.publish_followups import run_publish_followups
from app.processing.ingest.tasks_vector import ingest_file

pytestmark = pytest.mark.anyio

# What a job's metadata keeps while its archive is owed or has failed.
_ARCHIVE_OWED_KEYS = {
    ARCHIVE_PENDING_METADATA_KEY,
    "archive_failed",
    "archive_error",
    PUBLISH_FOLLOWUPS_FIELD,
}


_GEOJSON = (
    b'{"type":"FeatureCollection","features":['
    b'{"type":"Feature","properties":{"name":"a"},'
    b'"geometry":{"type":"Point","coordinates":[1.0,2.0]}}]}'
)


async def _fake_ogr2ogr(file_path, table_name, db_conn_str, *, schema, **kwargs):
    """Loads the one point ``_GEOJSON`` holds, as ogr2ogr would."""
    from sqlalchemy import text

    from app.core.db import async_session

    async with async_session() as session:
        await session.execute(
            text(
                f'CREATE TABLE "{schema}"."{table_name}" '
                "(gid serial PRIMARY KEY, name text, geom geometry(Point, 4326))"
            )
        )
        await session.execute(
            text(
                f'INSERT INTO "{schema}"."{table_name}" (name, geom) '
                "VALUES ('a', ST_SetSRID(ST_Point(1, 2), 4326))"
            )
        )
        await session.commit()


@pytest.fixture
def store(tmp_path, monkeypatch) -> LocalStorageProvider:
    """One local store for the import's archive and the delete's reap."""
    storage = LocalStorageProvider(str(tmp_path / "objects"))
    monkeypatch.setattr(storage_provider, "_storage", storage)
    return storage


class _Import:
    """One file import of ``_GEOJSON`` by the admin, staged in place."""

    def __init__(self, session, tmp_path) -> None:
        self.session = session
        self.source = tmp_path / "points.geojson"
        self.source.write_bytes(_GEOJSON)
        self.title = f"Archive race {uuid.uuid4().hex[:8]}"
        self.job_id: uuid.UUID | None = None
        self.dataset_id: uuid.UUID | None = None

    async def run(self, *, after_publish=None) -> None:
        """Run the task; ``after_publish`` gets the dataset once its commit has landed."""
        admin_id = (
            await self.session.execute(select(User.id).where(User.username == "admin"))
        ).scalar_one()
        job = IngestJob(
            source_filename="points.geojson",
            file_path=str(self.source),
            created_by=admin_id,
            status="pending",
            user_metadata={"title": self.title},
        )
        self.session.add(job)
        await self.session.commit()
        self.job_id = job.id

        async def published(dataset) -> None:
            self.dataset_id = dataset.id
            if after_publish is not None:
                await after_publish(dataset)

        ogrinfo = {
            "srid": 4326,
            "geometry_type": "Point",
            "columns": [{"name": "name", "type": "String"}],
        }
        with (
            patch(
                "app.processing.ingest.service.resolve_file_path",
                AsyncMock(return_value=str(self.source)),
            ),
            patch(
                "app.processing.ingest.ogr.run_ogrinfo",
                AsyncMock(return_value=ogrinfo),
            ),
            patch("app.processing.ingest.ogr.run_ogr2ogr", new=_fake_ogr2ogr),
            patch("app.processing.ingest.metadata.grant_reader_access", AsyncMock()),
            patch(
                "app.processing.ingest.tasks_common.invalidate_catalog_cache",
                AsyncMock(),
            ),
            # The last step before the task archives the original.
            patch(
                "app.processing.ingest.tasks_common.defer_embedding",
                AsyncMock(side_effect=published),
            ),
        ):
            await ingest_file.func(
                job_id=str(job.id),
                file_path=str(self.source),
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

    async def run_holding_the_job_row(self) -> None:
        """Run the task while another transaction holds the job row, then release it."""
        import app.core.db as db_module

        async with db_module.async_session() as holder:

            async def hold(dataset) -> None:
                await holder.execute(
                    select(IngestJob.id)
                    .where(IngestJob.id == self.job_id)
                    .with_for_update(read=True, key_share=True)
                )

            await self.run(after_publish=hold)
            await holder.rollback()

    async def settle(self) -> None:
        """Run the job's follow-ups as the sweep does once they are due."""
        job = await self.job()
        due = {
            **job.user_metadata[PUBLISH_FOLLOWUPS_FIELD],
            "next_attempt_at": "2000-01-01T00:00:00+00:00",
        }
        await self.session.execute(
            update(IngestJob)
            .where(IngestJob.id == self.job_id)
            .values(user_metadata={**job.user_metadata, PUBLISH_FOLLOWUPS_FIELD: due})
        )
        await self.session.commit()
        await run_publish_followups(self.job_id)

    async def job(self) -> IngestJob:
        self.session.expire_all()
        return await self.session.get(IngestJob, self.job_id)

    async def delete_dataset(self, client, headers) -> int:
        response = await client.request(
            "DELETE",
            f"/datasets/{self.dataset_id}",
            json={"confirm_title": self.title},
            headers=headers,
        )
        return response.status_code

    async def clean_up(self, client, headers) -> None:
        if self.dataset_id is not None and (await self.job()).dataset_id is not None:
            await self.delete_dataset(client, headers)
        if self.job_id is not None:
            await self.session.execute(
                delete(IngestJob).where(IngestJob.id == self.job_id)
            )
            await self.session.commit()


async def test_an_import_archives_and_confirms_its_original(
    client, admin_auth_header, test_db_session, tmp_path, store
) -> None:
    ingest = _Import(test_db_session, tmp_path)
    try:
        await ingest.run()

        job = await ingest.job()
        assert job.status == "complete", job.error_message
        key = f"originals/{ingest.dataset_id}/points.geojson"
        assert await store.get(key) == _GEOJSON
        assert ARCHIVE_PENDING_METADATA_KEY not in job.user_metadata
        assert not ingest.source.exists()
    finally:
        await ingest.clean_up(client, admin_auth_header)


async def test_a_delete_committed_before_the_archive_leaves_no_original(
    client, admin_auth_header, test_db_session, tmp_path, store
) -> None:
    """The delete commits and reaps between the publish commit and the archive write."""
    ingest = _Import(test_db_session, tmp_path)
    deletes: list[int] = []

    async def delete_now(dataset) -> None:
        deletes.append(await ingest.delete_dataset(client, admin_auth_header))

    try:
        await ingest.run(after_publish=delete_now)

        assert deletes == [204]
        job = await ingest.job()
        assert job.status == "complete", job.error_message
        assert job.dataset_id is None
        assert await store.list(f"originals/{ingest.dataset_id}/") == []
    finally:
        await ingest.clean_up(client, admin_auth_header)


async def test_a_delete_during_the_archive_write_conflicts_until_it_lands(
    client, admin_auth_header, test_db_session, tmp_path, store, monkeypatch
) -> None:
    """The write holds the job row, so the delete answers 409 and its retry reaps the archive."""
    ingest = _Import(test_db_session, tmp_path)
    deletes: list[int] = []
    put = store.put

    async def put_while_deleting(key, data):
        if key.startswith("originals/"):
            deletes.append(await ingest.delete_dataset(client, admin_auth_header))
        return await put(key, data)

    monkeypatch.setattr(store, "put", put_while_deleting)
    try:
        await ingest.run()

        assert deletes == [409]
        job = await ingest.job()
        assert job.dataset_id == ingest.dataset_id
        assert ARCHIVE_PENDING_METADATA_KEY not in job.user_metadata
        assert await store.list(f"originals/{ingest.dataset_id}/") != []

        assert await ingest.delete_dataset(client, admin_auth_header) == 204
        assert await store.list(f"originals/{ingest.dataset_id}/") == []
    finally:
        await ingest.clean_up(client, admin_auth_header)


async def test_a_job_row_held_elsewhere_leaves_the_archive_owed_and_the_upload_kept(
    client, admin_auth_header, test_db_session, tmp_path, store
) -> None:
    """Without the row the task can't tell a delete from another holder, so it keeps the upload."""
    ingest = _Import(test_db_session, tmp_path)
    try:
        await ingest.run_holding_the_job_row()

        job = await ingest.job()
        assert job.dataset_id == ingest.dataset_id
        assert await store.list(f"originals/{ingest.dataset_id}/") == []
        assert job.user_metadata[ARCHIVE_PENDING_METADATA_KEY] is True
        assert "archive_key" in job.user_metadata[PUBLISH_FOLLOWUPS_FIELD]
        assert ingest.source.exists()
    finally:
        await ingest.clean_up(client, admin_auth_header)


@pytest.mark.parametrize(
    "delete_at", ["before_the_follow_ups", "as_the_follow_ups_read_the_upload"]
)
async def test_a_deferred_archive_is_settled_without_a_write_once_the_dataset_is_deleted(
    client,
    admin_auth_header,
    test_db_session,
    tmp_path,
    store,
    monkeypatch,
    delete_at,
) -> None:
    """The follow-ups confirm the owed archive of a deleted dataset and write nothing."""
    ingest = _Import(test_db_session, tmp_path)
    deletes: list[int] = []
    writes: list[str] = []
    put = store.put

    async def delete_now(*_) -> str:
        deletes.append(await ingest.delete_dataset(client, admin_auth_header))
        return str(ingest.source)

    async def recorded_put(key, data):
        if key.startswith("originals/"):
            writes.append(key)
        return await put(key, data)

    try:
        await ingest.run_holding_the_job_row()
        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
        monkeypatch.setattr(store, "put", recorded_put)

        if delete_at == "before_the_follow_ups":
            await delete_now()
            await ingest.settle()
        else:
            with patch(
                "app.processing.ingest.service.resolve_file_path",
                AsyncMock(side_effect=delete_now),
            ):
                await ingest.settle()
            assert writes == []
            # The pass that lost the row leaves the archive owed for the next.
            await ingest.settle()

        assert deletes == [204]
        assert writes == []
        assert await store.list(f"originals/{ingest.dataset_id}/") == []
        metadata = (await ingest.job()).user_metadata
        assert not _ARCHIVE_OWED_KEYS & metadata.keys()
        assert not ingest.source.exists()
    finally:
        await ingest.clean_up(client, admin_auth_header)


async def test_a_delete_during_a_deferred_archive_write_conflicts_until_it_lands(
    client, admin_auth_header, test_db_session, tmp_path, store, monkeypatch
) -> None:
    """The follow-ups hold the job row while they write, so the delete answers 409 and its retry reaps the archive."""
    ingest = _Import(test_db_session, tmp_path)
    deletes: list[int] = []
    put = store.put

    async def put_while_deleting(key, data):
        if key.startswith("originals/"):
            deletes.append(await ingest.delete_dataset(client, admin_auth_header))
        return await put(key, data)

    try:
        await ingest.run_holding_the_job_row()
        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
        monkeypatch.setattr(store, "put", put_while_deleting)

        await ingest.settle()

        assert deletes == [409]
        job = await ingest.job()
        assert job.dataset_id == ingest.dataset_id
        assert not _ARCHIVE_OWED_KEYS & job.user_metadata.keys()
        assert await store.list(f"originals/{ingest.dataset_id}/") != []
        assert not ingest.source.exists()

        assert await ingest.delete_dataset(client, admin_auth_header) == 204
        assert await store.list(f"originals/{ingest.dataset_id}/") == []
    finally:
        await ingest.clean_up(client, admin_auth_header)
