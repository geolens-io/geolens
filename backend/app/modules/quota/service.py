"""Per-user upload and storage quota enforcement service.

Core check is authoritative for community and enterprise editions. The
EntitlementPort enforce_limit calls are an additive cloud seam:
in OSS/Enterprise the DefaultEntitlementPort is grant-all and never raises.

Ownerless datasets (policy, #1293): every seam here resolves the billed
identity from ``catalog.records.created_by``, which is nullable. A NULL
``created_by`` is EXEMPT from quota accounting everywhere -- deliberate
policy, not an accident of the SQL. This is a LIVE state, not only
pre-0019 legacy: ``created_by`` is ``ON DELETE SET NULL``, so hard-deleting
a user orphans their datasets while the datasets keep serving.

The exemption is one mechanism, not six special cases:
``get_user_quota_usage`` filters ``created_by = :user_id``, and ``= NULL``
is never true, so it returns zero usage for a NULL identity; every other
function here reads usage through that one aggregate and inherits the
answer.

Scope, precisely, so nobody "simplifies" it into an early return: usage
reads zero (not a seam short-circuit), and the count cap can never refuse
a NULL owner. The BYTE cap still measures the INCOMING amount on its own
for a NULL owner though -- nothing accumulates, but one oversized single
file is still refused. An early return would drop that.

Chosen over refusing mutation (no ownership-assignment surface exists, so
a refusal has no remedy) or billing the admin pool (misattributes storage
to whichever operator happens to be listed). Durable fix is ownership
adoption, tracked by #998; ``TestOwnerlessDatasetsAreExemptAtEverySeam``
in ``backend/tests/test_raster_replace_1221.py`` has to change with it.
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
    user_id: uuid.UUID | None,
) -> UserQuotaUsage:
    """Return current bytes-used and dataset-count for a user in one SQL round-trip.

    Joins records -> datasets -> dataset_assets (key='data' or
    'archived_original:*') to sum byte size; only dataset record types are
    counted (maps/services/collections excluded).

    Byte-coverage caveat: ``bytes_used`` sums ONLY the ``key='data'`` asset,
    so in practice it's raster file bytes -- vector/``table`` datasets are
    PostGIS-resident and ``vrt_dataset`` is definition-only, so they
    contribute 0. The dataset-COUNT cap is the cross-type fence instead,
    and ``check_upload_quota`` still gates each upload on the actual
    incoming ``file.size``. A true cross-type storage total is deferred to
    the metered/per-tenant (cloud) quota work.

    This is where the ownerless-dataset exemption physically lives (see
    module docstring): ``created_by = :user_id`` is never true for NULL, so
    a NULL ``user_id`` reads zero and every other seam inherits that
    through this function.

    user_id is bound via SQLAlchemy parameterisation, never
    string-formatted into the SQL text.
    """
    sql = text(
        """
        SELECT
            COALESCE(SUM(da.size_bytes), 0)::bigint AS bytes_used,
            COUNT(DISTINCT r.id)::bigint            AS dataset_count
        FROM   catalog.records r
        LEFT JOIN catalog.datasets d  ON d.record_id = r.id
        LEFT JOIN catalog.dataset_assets da
               ON da.dataset_id = d.id
              AND (da.key = 'data' OR da.key LIKE 'archived_original:%')
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


async def get_user_quota_usage_bulk(
    db: AsyncSession,
    user_ids: list[uuid.UUID],
) -> dict[uuid.UUID, UserQuotaUsage]:
    """Return quota usage for many users in one aggregate plus one cap read.

    fix(#435): the admin user list called `get_user_quota_usage()` once per row —
    200 rows per page, each running its own three-table aggregate, plus two
    persistent-config reads. That is 600 queries to render one admin page, and it
    grows with the catalog.

    Users with no records are absent from the aggregate; they get a zeroed usage
    row so callers can index the result unconditionally.
    """
    storage_cap = int(await MAX_STORAGE_BYTES_PER_USER.get(db))
    count_cap = int(await MAX_DATASETS_PER_USER.get(db))

    if not user_ids:
        return {}

    sql = text(
        """
        SELECT
            r.created_by                            AS user_id,
            COALESCE(SUM(da.size_bytes), 0)::bigint AS bytes_used,
            COUNT(DISTINCT r.id)::bigint            AS dataset_count
        FROM   catalog.records r
        LEFT JOIN catalog.datasets d  ON d.record_id = r.id
        LEFT JOIN catalog.dataset_assets da
               ON da.dataset_id = d.id
              AND (da.key = 'data' OR da.key LIKE 'archived_original:%')
        WHERE  r.created_by = ANY(CAST(:user_ids AS uuid[]))
          AND  r.record_type IN (
                   'vector_dataset', 'raster_dataset', 'vrt_dataset', 'table'
               )
        GROUP BY r.created_by
        """
    )
    result = await db.execute(sql, {"user_ids": [str(uid) for uid in user_ids]})
    by_user = {
        row.user_id: UserQuotaUsage(
            bytes_used=int(row.bytes_used),
            dataset_count=int(row.dataset_count),
            storage_cap=storage_cap,
            count_cap=count_cap,
        )
        for row in result.all()
    }

    return {
        user_id: by_user.get(
            user_id,
            UserQuotaUsage(
                bytes_used=0,
                dataset_count=0,
                storage_cap=storage_cap,
                count_cap=count_cap,
            ),
        )
        for user_id in user_ids
    }


async def check_upload_quota(
    db: AsyncSession,
    user_id: uuid.UUID,
    incoming_bytes: int,
    request: Request | None,
) -> None:
    """Enforce per-user byte and dataset-count caps before accepting an upload.

    Call this BEFORE creating an ingest job or staging the file.

    fix(#1710): ``request`` is optional so a worker re-check charges the same
    policy the door applied rather than forking a byte-cap copy. It reaches
    only ``enforce_limit``, which forwards a dimension and a count.

    Raises HTTPException 413 if the byte cap is exceeded.
    Raises HTTPException 422 if the dataset-count cap is exceeded.
    Never raises when either cap is 0 (the default unlimited config).

    After the core checks, calls enforce_limit as the EntitlementPort cloud
    extension seam.  In OSS/Enterprise the seam is a no-op.
    """
    usage = await get_user_quota_usage(db, user_id)

    # Byte cap enforcement (CORE, no entitlement port required)
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

    # Dataset-count cap enforcement (CORE)
    if usage.count_cap > 0 and usage.dataset_count >= usage.count_cap:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Dataset quota exceeded: {usage.dataset_count} of "
                f"{usage.count_cap} datasets used"
            ),
        )

    # EntitlementPort cloud extension seam (OSS/Enterprise = no-op)
    await enforce_limit(request, "storage_bytes", usage.bytes_used + incoming_bytes)
    await enforce_limit(request, "dataset_count", usage.dataset_count + 1)


async def check_replacement_quota(
    db: AsyncSession,
    owner_id: uuid.UUID | None,
    incoming_bytes: int,
    request: Request,
    *,
    dataset_id: uuid.UUID,
) -> None:
    """Admit a REPLACEMENT at the door, where ``check_upload_quota`` cannot.

    fix(#1290): ``check_upload_quota`` is creation-shaped (refuses at
    ``dataset_count >= count_cap``, charges the incoming file on top of
    existing usage). Both are wrong for a replacement -- the count check
    would lock out an owner already at their limit even though replacing
    creates no new dataset -- so: no count check, and the byte check
    credits what the replacement SUPERSEDES (the ``data`` row in
    ``dataset_assets``, not the raster asset -- they diverge for a
    STAC-imported dataset, which has an asset but no counted row, and
    crediting that would admit an overshoot). Archived originals are NOT
    credited: a replacement doesn't supersede them.

    Deliberately an EARLY, approximate bound: the door sees the uploaded
    file, not the (possibly larger) COG it converts into. The authoritative
    check is ``reserve_storage_bytes`` at publish time, under the per-user
    advisory lock, against the real converted size. Shared by both reupload
    doors and every record type.

    fix(#1290): identity is the dataset's OWNER, not the requester --
    an admin replacing someone else's dataset must be checked against the
    same identity the worker later reserves against
    (``dataset.record.created_by``), or the two authorities could disagree.

    ``owner_id`` may be None for an ownerless dataset and passes straight
    through unchanged (module docstring's exemption policy), same route
    ``reserve_storage_bytes`` uses at publish time.
    """
    usage = await get_user_quota_usage(db, owner_id)
    counted = await db.scalar(
        text(
            "SELECT COALESCE(SUM(size_bytes), 0)::bigint "
            "FROM catalog.dataset_assets "
            "WHERE dataset_id = :dataset_id AND key = 'data'"
        ),
        {"dataset_id": dataset_id},
    )
    projected = usage.bytes_used - int(counted or 0) + incoming_bytes

    if usage.storage_cap > 0 and projected > usage.storage_cap:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"Storage quota exceeded: used {usage.bytes_used} of "
                f"{usage.storage_cap} bytes (replacing {int(counted or 0)} "
                f"bytes with {incoming_bytes} bytes)"
            ),
        )

    # No dataset_count seam call: a replacement does not create one.
    await enforce_limit(request, "storage_bytes", projected)


class DatasetQuotaExceededError(Exception):
    """Dataset-count cap exceeded at Record-creation time (fix(#302)).

    Plain exception rather than HTTPException because the authoritative
    check runs inside the ingest worker, where there is no HTTP response
    to shape; API-side callers get a 422 via the handler registered in
    ``app.api.main``.
    """


async def reserve_dataset_slot(db: AsyncSession, user_id: uuid.UUID | None) -> None:
    """Atomically reserve a dataset-count slot for ``user_id`` (fix(#302)).

    ``check_upload_quota`` runs at upload time, but the ``Record`` row it
    counts is created later by the ingest worker, so N concurrent uploads
    could all pass the pre-check and overshoot the cap. This is the
    authoritative check: call inside the SAME transaction that inserts the
    new ``Record`` row. Takes a per-user transaction-scoped advisory lock
    and recounts, so concurrent creations for one user serialize. Lock
    releases automatically at commit/rollback.

    No-op when the cap is 0 (default unlimited).

    ``user_id`` is nullable like every other seam here, though no current
    caller passes None -- a Record always has an authenticated uploader.
    Should an adoption/re-ingest path reach it, the module docstring's
    ownerless policy applies unchanged: a NULL identity counts as zero,
    below every positive cap.
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


class StorageQuotaExceededError(Exception):
    """Per-user storage byte cap exceeded at asset-commit time (fix(#430) BA-23).

    Plain exception (not HTTPException) because the authoritative check runs
    inside the ingest worker; API-side callers get a 413 via the handler
    registered in ``app.api.main``.
    """


async def reserve_storage_bytes(
    db: AsyncSession, user_id: uuid.UUID | None, incoming_bytes: int
) -> None:
    """Atomically reserve ``incoming_bytes`` against the per-user byte cap.

    ``check_upload_quota`` checks at upload time with no serialization, so N
    concurrent uploads can all read the same pre-upload usage, all pass,
    and overshoot the cap. Mirrors ``reserve_dataset_slot``: call inside
    the SAME transaction that persists the byte-bearing asset, under the
    same per-user advisory lock, recounting so concurrent uploads serialize.

    No-op when the cap is 0 (default unlimited).

    ``user_id`` is None for an ownerless dataset (the replacement path
    passes ``record.created_by`` through unchanged) -- see the module
    docstring's exemption policy; the recount still reads zero, so
    ``incoming_bytes`` alone is still weighed against the cap.
    """
    cap = await MAX_STORAGE_BYTES_PER_USER.get(db)
    if cap <= 0:
        return

    # Same lock namespace as reserve_dataset_slot so both caps serialize together
    # per user (a single upload takes both under one lock, no interleave).
    await db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended('geolens:dataset_quota:' || :uid, 0))"
        ),
        {"uid": str(user_id)},
    )
    usage = await get_user_quota_usage(db, user_id)
    if (usage.bytes_used + incoming_bytes) > cap:
        raise StorageQuotaExceededError(
            f"Storage quota exceeded: used {usage.bytes_used} of {cap} bytes "
            f"(adding {incoming_bytes} bytes)"
        )
