"""One user's copy of one remote source, published or still being imported.

A service layer is one source per (format, base URL, layer identifier), and a
database table one per (connection, schema, table). The import and retry doors
refuse a second copy with 409 ``duplicate_source``; publication checks again
under a lock, because two requests can both pass a door before either job
publishes.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import astuple, dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.failure_reason import FixedReason
from app.platform.catalog_locks import lock_request_key
from app.platform.dataset_origin import (
    DatabaseSource,
    read_source,
    service_layer_identity,
)
from app.platform.jobs import ledger
from app.platform.jobs.models import (
    COMMIT_ATTEMPTED_METADATA_KEY,
    DATABASE_SOURCE_METADATA_KEY,
    IngestJob,
)

DUPLICATE_SOURCE_CODE = "duplicate_source"

# A job carrying any of these writes into an existing dataset (a refresh or a
# replacement), so it is never a second copy of its source.
_EXISTING_DATASET_MARKERS = ("dataset_id", "reupload", "refresh")


@dataclass(frozen=True)
class ServiceIdentity:
    """A service layer: canonical format, base URL and service-native layer id."""

    source_format: str
    url: str
    layer_id: str | None

    @classmethod
    def of(
        cls, source_format: str, url: str, *, layer_id: Any, layer_name: str | None
    ) -> ServiceIdentity:
        return cls(
            source_format,
            url,
            service_layer_identity(
                source_format, layer_id=layer_id, layer_name=layer_name
            ),
        )


SourceIdentity = ServiceIdentity | DatabaseSource


@dataclass(frozen=True)
class ExistingCopy:
    """The dataset that holds the source, or the job still importing it."""

    title: str | None = None
    dataset_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None


def _writes_into_a_dataset(job: IngestJob) -> bool:
    metadata = job.user_metadata or {}
    return any(metadata.get(marker) for marker in _EXISTING_DATASET_MARKERS)


def database_job_identity(job: IngestJob) -> DatabaseSource | None:
    """The table a database import job names, or None for any other job."""
    stored = (job.user_metadata or {}).get(DATABASE_SOURCE_METADATA_KEY)
    source = read_source("database", stored)
    return source if isinstance(source, DatabaseSource) else None


def job_source_identity(job: IngestJob) -> tuple[SourceIdentity, str | None] | None:
    """The source a service or database import job copies, as its worker writes it.

    The second value is the legacy ``source_url`` spelling of a service layer.
    None for any other job, or a service type nothing can import.
    """
    if _writes_into_a_dataset(job):
        return None
    metadata = job.user_metadata or {}
    database = database_job_identity(job)
    if database is not None:
        return database, None
    if not job.source_url or job.file_path:
        return None
    from app.processing.ingest.ogr import IngestionError
    from app.processing.ingest.tasks import resolve_service_type

    try:
        _, source_format = resolve_service_type(str(metadata.get("service_type") or ""))
    except IngestionError:
        return None
    layer_id = metadata.get("layer_id")
    identity = ServiceIdentity.of(
        source_format, job.source_url, layer_id=layer_id, layer_name=job.source_layer
    )
    legacy = f"{job.source_url}/{layer_id}" if layer_id is not None else job.source_url
    return identity, legacy


async def owner_copy(session: AsyncSession, job: IngestJob) -> ExistingCopy | None:
    """The published dataset of the source ``job`` copies, held by the job's owner."""
    from app.platform.extensions import get_processing_port

    found = job_source_identity(job)
    if found is None or job.created_by is None:
        return None
    identity, legacy = found
    port = get_processing_port()
    return await published_copy(
        session,
        job.created_by,
        identity,
        dataset_cls=port.get_dataset_orm_class(),
        record_cls=port.get_record_orm_class(),
        legacy_source_url=legacy,
    )


async def published_copy(
    session: AsyncSession,
    user_id: uuid.UUID,
    identity: SourceIdentity,
    *,
    dataset_cls: Any,
    record_cls: Any,
    legacy_source_url: str | None = None,
) -> ExistingCopy | None:
    """The user's dataset already bound to ``identity``, if any.

    Keyed on the structured ``origin_ref``, which only ingest and refresh
    write. ``legacy_source_url`` matches a service row whose ``origin_ref``
    lacks url or layer_id (one migration 0036 could not backfill); gated on
    that gap because ``source_url`` is editable through the metadata PATCH.
    """
    ref = dataset_cls.origin_ref
    if isinstance(identity, DatabaseSource):
        matches = and_(
            dataset_cls.source_format == "database",
            ref["connection"].astext == identity.connection,
            ref["schema"].astext == identity.schema,
            ref["table"].astext == identity.table,
        )
    else:
        ref_url = ref["url"].astext
        ref_layer = ref["layer_id"].astext
        structured = and_(
            ref["service_type"].astext == identity.source_format,
            ref_url == identity.url,
            ref_layer.is_(None)
            if identity.layer_id is None
            else ref_layer == identity.layer_id,
        )
        legacy = and_(
            or_(ref_url.is_(None), ref_layer.is_(None)),
            dataset_cls.source_url == legacy_source_url,
        )
        matches = and_(
            dataset_cls.source_format == identity.source_format,
            or_(structured, legacy) if legacy_source_url is not None else structured,
        )
    row = (
        await session.execute(
            select(dataset_cls.id, record_cls.title)
            .join(record_cls, dataset_cls.record_id == record_cls.id)
            .where(matches, record_cls.created_by == user_id)
            .limit(1)
        )
    ).first()
    return None if row is None else ExistingCopy(row.title, dataset_id=row.id)


async def importing_copy(
    session: AsyncSession,
    user_id: uuid.UUID,
    identity: SourceIdentity,
    *,
    job_identity: Callable[[IngestJob], SourceIdentity | None],
) -> ExistingCopy | None:
    """The user's queued or running import of ``identity``, if any.

    A pending job counts only once dispatched: the service preview leaves a
    pending job behind that may never be committed. Failed and cancelled
    jobs never count.
    """
    if isinstance(identity, DatabaseSource):
        kind = IngestJob.user_metadata.has_key(DATABASE_SOURCE_METADATA_KEY)
    else:
        kind = and_(IngestJob.source_url.is_not(None), IngestJob.file_path.is_(None))
    jobs = await session.scalars(
        select(IngestJob)
        .where(
            IngestJob.created_by == user_id,
            kind,
            or_(
                IngestJob.status == "running",
                and_(
                    IngestJob.status == "pending",
                    IngestJob.user_metadata.has_key(COMMIT_ATTEMPTED_METADATA_KEY),
                ),
            ),
        )
        .order_by(IngestJob.created_at, IngestJob.id)
    )
    for job in jobs:
        if not _writes_into_a_dataset(job) and job_identity(job) == identity:
            return ExistingCopy(job_id=job.id)
    return None


def duplicate_source_conflict(copy: ExistingCopy, message: str) -> HTTPException:
    """The 409 a door answers, naming the existing dataset or the running job.

    ``message`` describes a published copy; a copy still importing gets its own.
    """
    if copy.dataset_id is not None:
        detail = {
            "message": message,
            "existing_dataset_id": str(copy.dataset_id),
            "existing_title": copy.title,
        }
    else:
        detail = {
            "message": (
                "This source is already being imported. Wait for that import "
                "to finish, then refresh the dataset it creates."
            ),
            "existing_job_id": str(copy.job_id),
        }
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={"code": DUPLICATE_SOURCE_CODE, **detail},
    )


async def refuse_second_copy(
    session: AsyncSession,
    job: IngestJob,
    attempt_id: uuid.UUID,
) -> bool:
    """Fail this attempt when the job's owner already has its source published.

    Call first in the transaction that publishes. The lock lasts until that
    transaction ends, so a concurrent attempt for the same source waits here
    and then finds this one's dataset. True means the job is failed and
    committed, with nothing published.
    """
    found = job_source_identity(job)
    if found is None or job.created_by is None:
        return False
    scope = json.dumps(
        [str(job.created_by), type(found[0]).__name__, *astuple(found[0])]
    )
    await lock_request_key(session, scope=f"source-copy:{scope}", lock_timeout=None)
    existing = await owner_copy(session, job)
    if existing is None:
        return False
    await ledger.fail(
        session,
        job.id,
        attempt_id,
        reason=FixedReason(
            f"This source is already imported as dataset {existing.dataset_id}. "
            "Refresh that dataset instead.",
            code=DUPLICATE_SOURCE_CODE,
        ),
    )
    await session.commit()
    return True
