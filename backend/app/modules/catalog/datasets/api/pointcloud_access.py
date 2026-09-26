"""Who may read a COPC point cloud's file, decided once per credential and cached briefly.

A viewer reads one file in many small ranges, and deciding access on every
read would cost a credential lookup, a dataset read and an audit row. A
granted decision is cached per tenant, dataset and credential for at most
``GRANT_TTL_SECONDS``, and never past the credential's own expiry; a refusal
is never cached. A revoked key or session, a dataset made private or a
deleted one reaches a cached reader within that window.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from cachetools import TLRUCache
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_session import current_tenant_var
from app.core.pointcloud import POINTCLOUD_FILENAME, pointcloud_attempt_of
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.dependencies import (
    get_optional_user,
    read_credential,
    read_credential_lifetime,
)
from app.modules.catalog.authorization import check_dataset_access_or_anonymous
from app.modules.catalog.datasets.domain.service import (
    get_dataset,
    get_pointcloud_pointer,
)
from app.platform.storage.titiler_url import resolve_current_storage_key

logger = structlog.stdlib.get_logger(__name__)

GRANT_TTL_SECONDS = 30.0
_GRANT_CACHE_SIZE = 10_000
# The route's last segment is ``{name}.copc.laz``; only the stored name serves.
_STEM = POINTCLOUD_FILENAME.removesuffix(".copc.laz")


@dataclass(frozen=True, slots=True)
class PointCloudGrant:
    """What a granted read may serve: the live attempt's object and its size."""

    attempt_id: uuid.UUID
    storage_key: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class _Entry:
    grant: PointCloudGrant
    expires_at: float


_grants: TLRUCache = TLRUCache(
    maxsize=_GRANT_CACHE_SIZE,
    ttu=lambda _key, entry, _now: entry.expires_at,
    timer=time.monotonic,
)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def authorize_pointcloud_read(
    request: Request,
    db: AsyncSession,
    token: str | None,
    *,
    dataset_id: uuid.UUID,
    attempt_id: uuid.UUID,
    name: str,
) -> PointCloudGrant:
    """Decide whether this request may read one attempt's file of a point cloud.

    A cached grant for the same tenant, dataset and credential answers without
    touching the database when it names the requested attempt; one naming
    another attempt is decided again. Otherwise raises 401 for a supplied
    credential that doesn't resolve, and 404 for an unknown or invisible
    dataset, another record type, a missing or malformed pointer, a stale
    attempt or a name other than the stored one. Each granted decision writes
    one audit row.
    """
    credential = read_credential(request)
    cache_key = (current_tenant_var.get(), dataset_id, credential.fingerprint)
    entry = _grants.get(cache_key)
    if entry is not None and entry.grant.attempt_id == attempt_id:
        if name != _STEM:
            raise _not_found()
        return entry.grant

    identity = await get_optional_user(request, token, db)
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        # Worded like the guard's denial, so a private id and an unknown one match.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, identity)
    if dataset.record.record_type != "pointcloud_dataset":
        raise _not_found()
    grant = await _live_grant(db, dataset_id)
    if grant.attempt_id != attempt_id or name != _STEM:
        raise _not_found()

    cacheable, expires_at = await read_credential_lifetime(request, token, identity, db)
    await audit_emit(
        db,
        AuditEvent(
            user_id=identity.id if identity is not None else None,
            action="dataset.pointcloud_read",
            resource_type="dataset",
            resource_id=dataset_id,
            details={"attempt_id": str(attempt_id), "credential": credential.kind},
            ip_address=request.client.host if request.client else None,
        ),
    )
    await db.commit()
    ttl = _ttl(expires_at)
    if cacheable and ttl > 0:
        _grants[cache_key] = _Entry(grant, time.monotonic() + ttl)
    return grant


async def _live_grant(db: AsyncSession, dataset_id: uuid.UUID) -> PointCloudGrant:
    """The grant the dataset's pointer row describes, or 404 when it can't describe one."""
    pointer = await get_pointcloud_pointer(db, dataset_id)
    if pointer is None:
        raise _not_found()
    attempt = pointcloud_attempt_of(pointer.href, dataset_id)
    size = pointer.size_bytes
    if attempt is None or not isinstance(size, int) or size < 0:
        logger.warning("pointcloud_pointer_malformed", dataset_id=str(dataset_id))
        raise _not_found()
    try:
        key = resolve_current_storage_key(pointer.href)
    except ValueError:
        raise _not_found() from None
    return PointCloudGrant(attempt_id=attempt, storage_key=key, size_bytes=size)


def _ttl(expires_at: datetime | None) -> float:
    if expires_at is None:
        return GRANT_TTL_SECONDS
    remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
    return min(GRANT_TTL_SECONDS, remaining)
