"""One user's copy of one remote source, published or still being imported.

A service layer is one source per (format, URL, layer identifier), and a
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
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.failure_reason import FixedReason
from app.platform.catalog_locks import lock_request_key
from app.platform.dataset_origin import (
    SERVICE_SOURCE_FORMATS,
    DatabaseSource,
    ServiceSource,
    read_source,
    service_layer_identity,
)
from app.platform.jobs import ledger
from app.platform.jobs.models import (
    DATABASE_SOURCE_METADATA_KEY,
    PUBLISHED_FOR_METADATA_KEY,
    IngestJob,
    dispatch_attempted,
    publication_owner,
)
from app.platform.service_endpoints import bounded_parse_qsl

DUPLICATE_SOURCE_CODE = "duplicate_source"

# A job carrying any of these writes into an existing dataset (a refresh or a
# replacement), so it is never a second copy of its source.
_EXISTING_DATASET_MARKERS = ("dataset_id", "reupload", "refresh")

# Request parameters a WFS or OGC API client adds to any URL; none of them
# picks the service or the layer, unlike `typeName` or a MapServer `map`.
_PROTOCOL_PARAMETERS = frozenset(
    {"service", "request", "version", "acceptversions", "outputformat", "f"}
)

# OGC parameters whose names the standards make case-insensitive; any other
# name, a vendor's, is kept as written.
_CASE_BLIND_PARAMETERS = frozenset(
    {"typename", "typenames", "srsname", "namespace", "namespaces"}
)


@dataclass(frozen=True)
class ServiceIdentity:
    """A service layer: canonical format, canonical URL and service-native layer id.

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
    job_creator: uuid.UUID | None = None


def _canonical_url(url: str) -> str:
    """``url`` with case-blind parts lowered, the trailing slash and fragment
    dropped, and OGC protocol parameters removed from a query sorted by name."""
    try:
        parts = urlsplit(url.strip())
        query = bounded_parse_qsl(parts.query)
    except ValueError:
        return url
    # Sorted by name only: a service reads the first of repeated values, so
    # their order stays part of the identity.
    kept = sorted(
        (
            (key.lower() if key.lower() in _CASE_BLIND_PARAMETERS else key, value)
            for key, value in query
            if key.lower() not in _PROTOCOL_PARAMETERS
        ),
        key=lambda pair: pair[0],
    )
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            urlencode(kept),
            "",
        )
    )


def service_identity(
    service_type: str, url: str, *, layer_id: Any, layer_name: str | None
) -> ServiceIdentity | None:
    """A service layer's identity, the same for every spelling of its URL.

    ``service_type`` is a canonical format or a request's service label. An
    ArcGIS URL is reduced to its service root, and a layer id embedded in it
    counts when none is given. None for a service type nothing can import.
    """
    source_format = _service_format(service_type)
    if source_format is None:
        return None
    raw = url
    if source_format == "arcgis_featureserver":
        from app.modules.catalog.sources.adapters.arcgis import normalize_arcgis_url

        try:
            raw, url_layer_id = normalize_arcgis_url(url)
        except ValueError:
            url_layer_id = None
        if layer_id is None:
            layer_id = url_layer_id
    return ServiceIdentity(
        source_format,
        _canonical_url(raw),
        service_layer_identity(source_format, layer_id=layer_id, layer_name=layer_name),
        legacy_url=f"{raw}/{layer_id}" if layer_id is not None else raw,
    )


def _service_format(service_type: str) -> str | None:
    if service_type in SERVICE_SOURCE_FORMATS:
        return service_type
    from app.processing.ingest.ogr import IngestionError
    from app.processing.ingest.tasks import resolve_service_type

    try:
        return resolve_service_type(service_type)[1]
    except IngestionError:
        return None


def stored_service_identity(origin_ref: Any) -> ServiceIdentity | None:
    """The identity of the service a dataset's ``origin_ref`` binds, if any."""
    source = read_source("service", origin_ref)
    if not isinstance(source, ServiceSource):
        return None
    return service_identity(
        source.service_type,
        source.url,
        layer_id=source.layer_id,
        layer_name=source.layer_id,
    )


def job_source_identity(job: IngestJob) -> SourceIdentity | None:
    """The source a service or database import job copies.

    None for any other job, including one that writes into an existing
    dataset, or a service type nothing can import.
    """
    metadata = job.user_metadata if isinstance(job.user_metadata, dict) else {}
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
    """The published dataset of the source ``job`` copies, held by the account
    its dataset will belong to."""
    identity = job_source_identity(job)
    owner = publication_owner(job)
    if identity is None or owner is None:
        return None
    return await published_copy(session, owner, identity)


async def published_copy(
    session: AsyncSession,
    user_id: uuid.UUID,
    identity: SourceIdentity,
    *,
    excluding: uuid.UUID | None = None,
) -> ExistingCopy | None:
    """The user's dataset, other than ``excluding``, already bound to ``identity``.

    Keyed on the structured ``origin_ref``, which only ingest and refresh
    write; a stored service URL is compared in canonical form, so a copy
    stored under another spelling still matches. A service row whose
    ``origin_ref`` lacks url or layer_id (one migration 0036 could not
    backfill) is matched on its ``source_url``, also in canonical form, gated
    on that gap because ``source_url`` is editable through the metadata PATCH.
    """
    from app.platform.extensions import get_processing_port

    port = get_processing_port()
    dataset_cls = port.get_dataset_orm_class()
    record_cls = port.get_record_orm_class()
    ref = dataset_cls.origin_ref
    owned = [record_cls.created_by == user_id]
    if excluding is not None:
        owned.append(dataset_cls.id != excluding)
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
        # Narrowed to the identity's host and path; the canonical comparison
        # below decides.
        root = urlsplit(identity.url)._replace(query="").geturl().lower()
        matches = and_(
            dataset_cls.source_format == identity.source_format,
            or_(
                and_(
                    ref["service_type"].astext == identity.source_format,
                    func.lower(ref_url).startswith(root, autoescape=True),
                    ref_layer.is_(None)
                    if identity.layer_id is None
                    else ref_layer == identity.layer_id,
                ),
                and_(
                    or_(ref_url.is_(None), ref_layer.is_(None)),
                    func.lower(dataset_cls.source_url).startswith(
                        root, autoescape=True
                    ),
                ),
            ),
        )
    rows = await session.execute(
        select(dataset_cls.id, record_cls.title, ref, dataset_cls.source_url)
        .join(record_cls, dataset_cls.record_id == record_cls.id)
        .where(matches, *owned)
        .order_by(dataset_cls.id)
    )
    for dataset_id, title, stored, source_url in rows:
        if isinstance(identity, DatabaseSource) or _same_service(
            identity, stored, source_url
        ):
            return ExistingCopy(title, dataset_id=dataset_id)
    return None


def _same_service(
    identity: ServiceIdentity, origin_ref: Any, source_url: str | None
) -> bool:
    stored = stored_service_identity(origin_ref)
    if stored is not None:
        return stored == identity
    return source_url is not None and _canonical_url(source_url) == _canonical_url(
        identity.legacy_url
    )


async def importing_copy(
    session: AsyncSession, user_id: uuid.UUID, identity: SourceIdentity
) -> ExistingCopy | None:
    """The user's queued or running import of ``identity``, if any: one that
    will publish for them, whoever previewed it.

    A pending job counts only once dispatched: the service preview leaves a
    pending job behind that may never be committed. Failed and cancelled
    jobs never count.
    """
    if isinstance(identity, DatabaseSource):
        kind = IngestJob.user_metadata.has_key(DATABASE_SOURCE_METADATA_KEY)
    else:
        kind = and_(IngestJob.source_url.is_not(None), IngestJob.file_path.is_(None))
    published_for = IngestJob.user_metadata[PUBLISHED_FOR_METADATA_KEY].astext
    jobs = await session.scalars(
        select(IngestJob)
        .where(
            or_(
                published_for == str(user_id),
                and_(published_for.is_(None), IngestJob.created_by == user_id),
            ),
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
            return ExistingCopy(job_id=job.id, job_creator=job.created_by)
    return None


async def visible_copy(
    session: AsyncSession, copy: ExistingCopy, user: Any
) -> ExistingCopy:
    """``copy`` as ``user`` may see it: a dataset they can't read, or a job
    they can't read, goes unnamed.

    A door answering for another account's copy, such as a retry of a job an
    admin committed, would otherwise disclose it.
    """
    if copy.job_id is not None:
        return copy if await _may_read_job(session, copy, user) else ExistingCopy()
    if copy.dataset_id is None:
        return copy
    from sqlalchemy.orm import joinedload

    from app.modules.catalog.authorization import check_dataset_access
    from app.platform.extensions import get_processing_port

    dataset_cls = get_processing_port().get_dataset_orm_class()
    dataset = await session.scalar(
        select(dataset_cls)
        .options(joinedload(dataset_cls.record))
        .where(dataset_cls.id == copy.dataset_id)
    )
    try:
        await check_dataset_access(session, dataset, copy.dataset_id, user)
    except HTTPException:
        return ExistingCopy()
    return copy


async def _may_read_job(session: AsyncSession, copy: ExistingCopy, user: Any) -> bool:
    """The job read rule: its creator, or the cross-user job permission."""
    if copy.job_creator == user.id:
        return True
    from app.modules.catalog.authorization import get_user_roles
    from app.platform.extensions import get_permission_extension

    return await get_permission_extension().check_permission(
        session,
        user,
        "manage_users",
        user_roles=await get_user_roles(session, user),
        resource=await session.get(IngestJob, copy.job_id),
    )


async def visible_conflict(
    session: AsyncSession, user: Any, existing: ExistingCopy, message: str
) -> HTTPException:
    """The 409 a door answers for ``existing``, naming only what ``user`` may read.

    ``message`` describes a published copy; ``{title}`` in it is its title.
    """
    existing = await visible_copy(session, existing, user)
    return duplicate_source_conflict(existing, message.format(title=existing.title))


def duplicate_source_conflict(copy: ExistingCopy, message: str) -> HTTPException:
    """The 409 a door answers, naming the existing dataset or the running job.

    ``message`` describes a published copy; a copy still importing gets its
    own, and one the caller may not see is described without naming it.
    """
    if copy.dataset_id is not None:
        detail = {
            "message": message,
            "existing_dataset_id": str(copy.dataset_id),
            "existing_title": copy.title,
        }
    elif copy.job_id is None:
        detail = {
            "message": (
                "A copy of this source already exists, or is being imported, "
                "for the account this would publish for. Refresh that copy "
                "instead of importing it again."
            )
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


async def retry_conflict(
    session: AsyncSession, user: Any, job: IngestJob
) -> HTTPException | None:
    """The 409 a retry of ``job`` answers while the account it publishes for
    holds a copy of its source, naming that copy only if ``user`` can read it."""
    existing = await owner_copy(session, job)
    if existing is None:
        return None
    existing = await visible_copy(session, existing, user)
    return duplicate_source_conflict(
        existing,
        f"The job's owner already has a dataset from this source (existing: "
        f"'{existing.title}'). Refresh that dataset instead, or delete it and "
        "retry this job.",
    )


def second_copy_reason(existing: ExistingCopy, *, named: bool) -> FixedReason:
    """The failure stored on a job refused for publishing a second copy.

    ``named`` only when the copy is the job submitter's own: anyone who can
    read the job can read the reason, not necessarily that dataset.
    """
    if not named:
        return FixedReason(
            "This source is already imported as another dataset of the account "
            "this job publishes for. Refresh that dataset instead.",
            code=DUPLICATE_SOURCE_CODE,
        )
    return FixedReason(
        f"This source is already imported as dataset {existing.dataset_id}. "
        "Refresh that dataset instead.",
        code=DUPLICATE_SOURCE_CODE,
    )


async def _lock_source(
    session: AsyncSession, user_id: uuid.UUID, identity: SourceIdentity
) -> None:
    key = [type(identity).__name__, str(user_id)]
    key += [getattr(identity, f.name) for f in fields(identity) if f.compare]
    await lock_request_key(
        session, scope=f"source-copy:{json.dumps(key)}", lock_timeout=None
    )


async def locked_copy(
    session: AsyncSession,
    user_id: uuid.UUID,
    identity: SourceIdentity,
    *,
    excluding: uuid.UUID | None = None,
) -> ExistingCopy | None:
    """``published_copy``, after locking ``identity`` for the user until the
    transaction ends.

    Call first in the transaction that publishes, so a concurrent attempt
    for the same source waits here and then finds this one's dataset.
    """
    await _lock_source(session, user_id, identity)
    return await published_copy(session, user_id, identity, excluding=excluding)


async def rebound_copy(
    session: AsyncSession,
    identity: ServiceIdentity | None,
    dataset: Any,
    *,
    lock: bool = False,
) -> ExistingCopy | None:
    """The other dataset of ``dataset``'s owner bound to ``identity``, which
    binding ``dataset`` to it would duplicate.

    The owner counts, not whoever asks. None when ``dataset`` is already bound
    there, which adds no copy. With ``lock``, locks like :func:`locked_copy`
    and reads the owner again under the lock, so a transfer that landed first
    is the one checked.
    """
    if identity is None or stored_service_identity(dataset.origin_ref) == identity:
        return None
    owner = await _owner_of(session, dataset.id)
    while lock and owner is not None:
        await _lock_source(session, owner, identity)
        current = await _owner_of(session, dataset.id)
        if current == owner:
            break
        owner = current
    if owner is None:
        return None
    return await published_copy(session, owner, identity, excluding=dataset.id)


async def _owner_of(session: AsyncSession, dataset_id: uuid.UUID) -> uuid.UUID | None:
    from app.platform.extensions import get_processing_port

    port = get_processing_port()
    dataset_cls = port.get_dataset_orm_class()
    record_cls = port.get_record_orm_class()
    return await session.scalar(
        select(record_cls.created_by)
        .join(dataset_cls, dataset_cls.record_id == record_cls.id)
        .where(dataset_cls.id == dataset_id)
    )


async def refuse_second_copy(
    session: AsyncSession,
    job: IngestJob,
    attempt_id: uuid.UUID,
    owner: uuid.UUID,
) -> bool:
    """Fail this attempt when ``owner``, who the dataset it publishes will
    belong to, already has its source published.

    True means the job is failed and committed, with nothing published.
    """
    identity = job_source_identity(job)
    if identity is None:
        return False
    existing = await locked_copy(session, owner, identity)
    if existing is None:
        return False
    from app.processing.ingest.publish_followups import notify_ingest_failed

    reason = second_copy_reason(existing, named=owner == job.created_by)
    landed = await ledger.fail(session, job.id, attempt_id, reason=reason)
    await session.commit()
    if landed:
        task = (
            "ingest_database"
            if isinstance(identity, DatabaseSource)
            else "ingest_service"
        )
        await notify_ingest_failed(job.id, task=task, reason=reason)
    return True
