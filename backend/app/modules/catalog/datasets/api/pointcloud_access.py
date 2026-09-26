"""Who may read a COPC point cloud's file, decided again on every read.

Each read resolves the caller, checks the dataset and reads the live pointer,
so a revoked credential, a dataset made private or a replaced file stops
serving at once. A viewer reads one file in many ranges, so only the audit row
is deduplicated: one per tenant, dataset, attempt and credential in each
``AUDIT_WINDOW_SECONDS``, per worker process. The dedupe grants nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from cachetools import TTLCache
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_session import current_tenant_var
from app.core.pointcloud import POINTCLOUD_FILENAME, pointcloud_attempt_of
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.dependencies import get_optional_user, read_credential
from app.modules.catalog.authorization import check_dataset_access_or_anonymous
from app.modules.catalog.datasets.domain.service import (
    get_dataset,
    get_pointcloud_pointer,
)
from app.platform.storage.titiler_url import resolve_current_storage_key

logger = structlog.stdlib.get_logger(__name__)

AUDIT_WINDOW_SECONDS = 30.0
# The route's last segment is ``{name}.copc.laz``; only the stored name serves.
_STEM = POINTCLOUD_FILENAME.removesuffix(".copc.laz")

_audited: TTLCache = TTLCache(maxsize=10_000, ttl=AUDIT_WINDOW_SECONDS)


@dataclass(frozen=True, slots=True)
class PointCloudGrant:
    """What a granted read may serve: the live attempt's object and its size."""

    attempt_id: uuid.UUID
    storage_key: str
    size_bytes: int


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

    Raises 401 for a supplied credential that doesn't resolve, and 404 for an
    unknown or invisible dataset, another record type, a missing or malformed
    pointer, a stale attempt or a name other than the stored one. The first
    granted read per tenant, dataset, attempt and credential in each audit
    window writes one audit row.
    """
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

    credential = read_credential(request)
    audit_key = (
        current_tenant_var.get(),
        dataset_id,
        attempt_id,
        credential.fingerprint,
    )
    if audit_key in _audited:
        return grant
    # Claimed before the first await, so a parallel read on this worker finds
    # it, and released if the row isn't written, so a later read retries it.
    _audited[audit_key] = True
    try:
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
    except BaseException:  # broad: cleanup only; the raise below keeps the failure
        _audited.pop(audit_key, None)
        raise
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
