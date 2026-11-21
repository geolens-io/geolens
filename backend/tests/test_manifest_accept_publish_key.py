"""Accepting a held manifest replacement with a publish key."""

from __future__ import annotations

import shutil
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.modules.auth.models import User
from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.modules.catalog.datasets.api.refresh_acceptance import (
    dispatch_upload_acceptance,
)
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import IngestJob
from app.platform.request_credential import (
    _SESSION_KEY,
    ApiKeyCredential,
    record_api_key,
)
from tests.factories import create_user
from tests.test_manifest_blocked_reapply import _held_apply
from tests.test_manifest_reapply_publication import _run_worker

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="needs ogr2ogr"),
    pytest.mark.requires_ogr2ogr,
]


async def _hold(session, *, record: tuple[str, str], **held_metadata):
    """A held replacement whose entry asks for ``held_metadata``, over a
    dataset whose record is ``record``."""
    held = await _held_apply(session)
    job = await session.get(IngestJob, held.job_id)
    job.user_metadata = {**job.user_metadata, **held_metadata}
    record_id = select(Dataset.record_id).where(Dataset.id == held.dataset_id)
    await session.execute(
        update(Record)
        .where(Record.id == record_id.scalar_subquery())
        .values(visibility=record[0], record_status=record[1])
    )
    await session.commit()
    return held


async def _accept(session, held, *, publish_key: bool) -> IngestJob:
    """Accept the held run, as a publish key or not, and run its worker."""
    dataset = (
        await session.execute(
            select(Dataset)
            .options(selectinload(Dataset.record))
            .where(Dataset.id == held.dataset_id)
        )
    ).scalar_one()
    if publish_key:
        record_api_key(
            session,
            ApiKeyCredential(id=uuid.uuid4(), scope="publish", dataset_id=None),
        )
    defer = AsyncMock()
    try:
        with patch(
            "app.modules.catalog.datasets.api.refresh_acceptance.defer_async_with_tenant",
            new=defer,
        ):
            accepted = await dispatch_upload_acceptance(
                session,
                dataset=dataset,
                dataset_id=held.dataset_id,
                user=held.user,
                run_id=held.run_id,
                token=None,
            )
    finally:
        session.info.pop(_SESSION_KEY, None)
    task = SimpleNamespace(defer_async=SimpleNamespace(await_args=defer.await_args))
    await _run_worker(task)
    return (
        await session.execute(
            select(IngestJob)
            .where(IngestJob.id == accepted.job_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _record(session, dataset_id) -> tuple[str, str]:
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


async def test_a_publish_key_accepting_a_held_narrowing_applies_it(
    test_db_session, clean_tables
):
    held = await _hold(
        test_db_session,
        record=("public", "published"),
        visibility="private",
        record_status="published",
    )

    job = await _accept(test_db_session, held, publish_key=True)

    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, held.dataset_id) == ("private", "published")


async def test_a_publish_key_accepting_a_held_widening_keeps_the_visibility(
    test_db_session, clean_tables
):
    held = await _hold(
        test_db_session,
        record=("private", "published"),
        visibility="internal",
        record_status="published",
    )

    job = await _accept(test_db_session, held, publish_key=True)

    # The data is replaced; only the widening is left out.
    assert (job.status, job.error_message) == ("complete", None)
    assert "visibility" not in job.user_metadata
    assert await _record(test_db_session, held.dataset_id) == ("private", "published")


async def _someone_elses_collection(client, session, admin_auth_header) -> Collection:
    _, other_id = await create_user(client, admin_auth_header, "editor")
    other = await session.get(User, uuid.UUID(other_id))
    collection = Collection(name=f"theirs-{uuid.uuid4().hex[:8]}", created_by=other.id)
    session.add(collection)
    await session.commit()
    return collection


@pytest.mark.parametrize(
    "publish_key,joins", [(True, False), (False, True)], ids=["key", "full"]
)
async def test_an_accepted_run_joins_another_users_collection_only_without_a_key(
    client, test_db_session, admin_auth_header, clean_tables, publish_key, joins
):
    """An admin reaches other people's collections; their publish key doesn't."""
    collection = await _someone_elses_collection(
        client, test_db_session, admin_auth_header
    )
    held = await _hold(
        test_db_session,
        record=("private", "draft"),
        manifest_collection_id=str(collection.id),
    )

    job = await _accept(test_db_session, held, publish_key=publish_key)

    assert (job.status, job.error_message) == ("complete", None)
    member = await test_db_session.scalar(
        select(CollectionDataset.dataset_id).where(
            CollectionDataset.collection_id == collection.id
        )
    )
    assert (member == held.dataset_id) is joins
    warnings = [w["kind"] for w in (job.user_metadata or {}).get("warnings", [])]
    assert ("manifest_collection_refused" in warnings) is not joins
