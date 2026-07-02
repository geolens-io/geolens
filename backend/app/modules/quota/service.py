"""Per-user upload and storage quota enforcement service (QUOTA-01..03).

Core check is authoritative for community and enterprise editions.
The EntitlementPort enforce_limit calls are an additive cloud seam (QUOTA-03):
in OSS/Enterprise the DefaultEntitlementPort is grant-all and never raises.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistent_config import (
    MAX_DATASETS_PER_USER,
    MAX_STORAGE_BYTES_PER_USER,
)
from app.modules.quota.schemas import UserQuotaUsage
from app.platform.extensions.entitlement import enforce_limit


async def get_user_quota_usage(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> UserQuotaUsage:
    """Return current bytes-used and dataset-count for a user in one SQL round-trip.

    Joins catalog.records → catalog.datasets → catalog.dataset_assets (key='data')
    to sum the byte size of the user's owned dataset files.  Only dataset record
    types are counted (maps, services, and collections are excluded).

    Byte-coverage caveat: ``bytes_used`` sums ONLY the ``key='data'`` file asset,
    so in practice it tracks *raster file bytes*.  Vector and ``table`` datasets are
    PostGIS-resident and ``vrt_dataset`` is definition-only, so they carry no
    ``data`` asset and contribute 0 bytes; ``overview``/``thumbnail`` (and any other
    asset key) are also excluded.  The dataset-COUNT cap is therefore the cross-type
    fence, and ``check_upload_quota`` still gates each upload on the actual incoming
    ``file.size`` regardless of type.  A true cross-type storage total (e.g.
    ``pg_total_relation_size`` per vector table + VRT source attribution) is
    intentionally deferred to the metered/per-tenant (cloud) quota work.

    T-1224-01 mitigation: user_id is bound via SQLAlchemy parameterisation —
    never string-formatted into the SQL text.
    """
    sql = text(
        """
        SELECT
            COALESCE(SUM(da.size_bytes), 0)::bigint AS bytes_used,
            COUNT(DISTINCT r.id)::bigint            AS dataset_count
        FROM   catalog.records r
        LEFT JOIN catalog.datasets d  ON d.record_id = r.id
        LEFT JOIN catalog.dataset_assets da
               ON da.dataset_id = d.id AND da.key = 'data'
        WHERE  r.created_by = :user_id
          AND  r.record_type IN (
                   'vector_dataset', 'raster_dataset', 'vrt_dataset', 'table'
               )
        """
    )
    result = await db.execute(sql, {"user_id": user_id})
    row = result.one()

    storage_cap = await MAX_STORAGE_BYTES_PER_USER.get(db)
    count_cap = await MAX_DATASETS_PER_USER.get(db)

    return UserQuotaUsage(
        bytes_used=int(row.bytes_used),
        dataset_count=int(row.dataset_count),
        storage_cap=int(storage_cap),
        count_cap=int(count_cap),
    )


async def check_upload_quota(
    db: AsyncSession,
    user_id: uuid.UUID,
    incoming_bytes: int,
    request: Request,
) -> None:
    """Enforce per-user byte and dataset-count caps before accepting an upload.

    Call this BEFORE creating an ingest job or staging the file.

    Raises HTTPException 413 if the byte cap is exceeded.
    Raises HTTPException 422 if the dataset-count cap is exceeded.
    Never raises when either cap is 0 (the default unlimited config).

    After the core checks, calls enforce_limit as the EntitlementPort cloud
    extension seam (QUOTA-03).  In OSS/Enterprise the seam is a no-op.
    """
    usage = await get_user_quota_usage(db, user_id)

    # QUOTA-01: byte cap enforcement (CORE — no entitlement port required)
    if (
        usage.storage_cap > 0
        and (usage.bytes_used + incoming_bytes) > usage.storage_cap
    ):
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"Storage quota exceeded: used {usage.bytes_used} of "
                f"{usage.storage_cap} bytes (adding {incoming_bytes} bytes)"
            ),
        )

    # QUOTA-02: dataset-count cap enforcement (CORE)
    if usage.count_cap > 0 and usage.dataset_count >= usage.count_cap:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Dataset quota exceeded: {usage.dataset_count} of "
                f"{usage.count_cap} datasets used"
            ),
        )

    # QUOTA-03: EntitlementPort cloud extension seam (OSS/Enterprise = no-op)
    await enforce_limit(request, "storage_bytes", usage.bytes_used + incoming_bytes)
    await enforce_limit(request, "dataset_count", usage.dataset_count + 1)


class DatasetQuotaExceededError(Exception):
    """Dataset-count cap exceeded at Record-creation time (fix #302).

    Plain exception rather than HTTPException because the authoritative
    check runs inside the ingest worker, where there is no HTTP response
    to shape; API-side callers get a 422 via the handler registered in
    ``app.api.main``.
    """


async def reserve_dataset_slot(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Atomically reserve a dataset-count slot for ``user_id`` (fix #302).

    ``check_upload_quota`` runs at upload time, but the ``Record`` rows the
    count aggregates over are created later by the ingest worker, so N
    concurrent uploads could all pass the pre-check and overshoot the cap.
    This is the authoritative check: call it inside the SAME transaction
    that inserts the new ``Record`` row. It takes a per-user
    transaction-scoped advisory lock and recounts, so concurrent creations
    for one user serialize and cannot overshoot ``max_datasets_per_user``.
    The lock is released automatically at commit/rollback.

    No-op when the cap is 0 (the default unlimited config).
    """
    cap = await MAX_DATASETS_PER_USER.get(db)
    if cap <= 0:
        return

    await db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended('geolens:dataset_quota:' || :uid, 0))"
        ),
        {"uid": str(user_id)},
    )
    usage = await get_user_quota_usage(db, user_id)
    if usage.dataset_count >= cap:
        raise DatasetQuotaExceededError(
            f"Dataset quota exceeded: {usage.dataset_count} of {cap} datasets used"
        )
