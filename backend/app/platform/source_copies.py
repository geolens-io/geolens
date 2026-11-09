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
from dataclasses import dataclass, field, fields
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
    DATABASE_SOURCE_METADATA_KEY,
    IngestJob,
    dispatch_attempted,
)

DUPLICATE_SOURCE_CODE = "duplicate_source"

# A job carrying any of these writes into an existing dataset (a refresh or a
# replacement), so it is never a second copy of its source.
_EXISTING_DATASET_MARKERS = ("dataset_id", "reupload", "refresh")


@dataclass(frozen=True)
class ServiceIdentity:
    """A service layer: canonical format, base URL and service-native layer id.

    ``legacy_url`` is the ``source_url`` an import of it writes, which only an
    ``origin_ref`` without url or layer_id is matched on.
    """

    source_format: str
    url: str
    layer_id: str | None
    legacy_url: str = field(compare=False)


SourceIdentity = ServiceIdentity | DatabaseSource


@dataclass(frozen=True)
class ExistingCopy:
    """The dataset that holds the source, or the job still importing it."""

    title: str | None = None
    dataset_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None


def service_identity(
    service_type: str, url: str, *, layer_id: Any, layer_name: str | None
) -> ServiceIdentity | None:
    """A service layer's identity in the spelling its import writes to ``origin_ref``.

    An ArcGIS URL is normalized as the preview stores it, and a layer id
    embedded in it counts when none is given; other services keep the URL
    as given. None for a service type nothing can import.
    """
    from app.processing.ingest.ogr import IngestionError
    from app.processing.ingest.tasks import resolve_service_type

    try:
        _, source_format = resolve_service_type(service_type)
    except IngestionError:
        return None
    if source_format == "arcgis_featureserver":
        from app.modules.catalog.sources.adapters.arcgis import normalize_arcgis_url

        try:
            url, url_layer_id = normalize_arcgis_url(url)
        except ValueError:
            url_layer_id = None
        if layer_id is None:
            layer_id = url_layer_id
    return ServiceIdentity(
        source_format,
        url,
        service_layer_identity(source_format, layer_id=layer_id, layer_name=layer_name),
        legacy_url=f"{url}/{layer_id}" if layer_id is not None else url,
    )


def job_source_identity(job: IngestJob) -> SourceIdentity | None:
    """The source a service or database import job copies.

    None for any other job, including one that writes into an existing
    dataset, or a service type nothing can import.
    """
    metadata = job.user_metadata or {}
    if any(metadata.get(marker) for marker in _EXISTING_DATASET_MARKERS):
        return None
    database = read_source("database", metadata.get(DATABASE_SOURCE_METADATA_KEY))
    if isinstance(database, DatabaseSource):
        return database
    if not job.source_url or job.file_path:
        return None
    return service_identity(
        str(metadata.get("service_type") or ""),
        job.source_url,
        layer_id=metadata.get("layer_id"),
        layer_name=job.source_layer,
    )


async def owner_copy(session: AsyncSession, job: IngestJob) -> ExistingCopy | None:
    """The published dataset of the source ``job`` copies, held by the job's owner."""
    identity = job_source_identity(job)
    if identity is None or job.created_by is None:
        return None
    return await published_copy(session, job.created_by, identity)


async def published_copy(
    session: AsyncSession, user_id: uuid.UUID, identity: SourceIdentity
) -> ExistingCopy | None:
    """The user's dataset already bound to ``identity``, if any.

    Keyed on the structured ``origin_ref``, which only ingest and refresh
    write. A service row whose ``origin_ref`` lacks url or layer_id (one
    migration 0036 could not backfill) is matched on ``source_url`` instead,
    gated on that gap because ``source_url`` is editable through the metadata
    PATCH.
    """
    from app.platform.extensions import get_processing_port

    port = get_processing_port()
    dataset_cls = port.get_dataset_orm_class()
    record_cls = port.get_record_orm_class()
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
        matches = and_(
            dataset_cls.source_format == identity.source_format,
            or_(
                and_(
                    ref["service_type"].astext == identity.source_format,
                    ref_url == identity.url,
                    ref_layer.is_(None)
                    if identity.layer_id is None
                    else ref_layer == identity.layer_id,
                ),
                and_(
                    or_(ref_url.is_(None), ref_layer.is_(None)),
                    dataset_cls.source_url == identity.legacy_url,
                ),
            ),
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
    session: AsyncSession, user_id: uuid.UUID, identity: SourceIdentity
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
                and_(IngestJob.status == "pending", dispatch_attempted()),
            ),
        )
        .order_by(IngestJob.created_at, IngestJob.id)
    )
    for job in jobs:
        if job_source_identity(job) == identity:
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
    identity = job_source_identity(job)
    if identity is None or job.created_by is None:
        return False
    key = [type(identity).__name__, str(job.created_by)]
    key += [getattr(identity, f.name) for f in fields(identity) if f.compare]
    await lock_request_key(
        session, scope=f"source-copy:{json.dumps(key)}", lock_timeout=None
    )
    existing = await published_copy(session, job.created_by, identity)
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
