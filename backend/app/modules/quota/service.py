"""Per-user upload and storage quota enforcement service (QUOTA-01..03).

Core check is authoritative for community and enterprise editions.
The EntitlementPort enforce_limit calls are an additive cloud seam (QUOTA-03):
in OSS/Enterprise the DefaultEntitlementPort is grant-all and never raises.

Ownerless datasets are exempt (policy, #1293)
---------------------------------------------
Every seam in this module resolves the billed identity from
``catalog.records.created_by``, and that column is nullable. A dataset whose
``created_by`` is NULL is EXEMPT from quota accounting at every seam: its bytes
and its dataset row count against nobody, and no seam substitutes a stand-in
identity for it. That is the decided policy, not an accident of the SQL.

The exemption is one mechanism repeated rather than six special cases.
``get_user_quota_usage`` filters ``records.created_by = :user_id``, and
``= NULL`` is never true, so the aggregate returns zeros for a NULL identity
and skips ownerless rows for every real one. Every other function here reads
its usage through that aggregate, so all of them inherit the same answer;
``reserve_replacement_bytes`` in ``app.processing.ingest.tasks_raster_swap``
inherits it by delegating to ``reserve_storage_bytes``. Nothing needs an
``if owner_id is None`` branch, and adding one to a single seam is how the
seams would start to disagree.

Ownerless is a LIVE state, not only a pre-0019 legacy one:
``records.created_by`` is ``ON DELETE SET NULL``, so hard-deleting a user
orphans every dataset they created (``AdminService.delete_user`` relies on
exactly that) while the datasets themselves survive and keep serving.

Why not the alternatives:

- *Refuse mutation until ownership is assigned.* There is no
  ownership-assignment surface in the product, and the migration-0019 adoption
  path is not reachable without a destructive downgrade (#998) — so a refusal
  has no remedy the operator can actually apply. It would permanently brick
  every legacy dataset, and, because of the SET NULL above, deleting one user
  would freeze their datasets for everyone forever.
- *Bill the instance-admin pool.* That misattributes storage rather than
  measuring it: the admin user list reads ``get_user_quota_usage_bulk``, so one
  operator would appear to hold the entire orphaned catalog, and once caps are
  enabled that phantom usage would refuse the admin's own legitimate uploads.
- *Leave it exempt (chosen).* Both caps default to 0 (unlimited), so only an
  instance that opts into enforcement has a gap at all, and the gap has a
  ceiling: creation always carries an authenticated uploader, so no NEW dataset
  can be born into it. It is not frozen, though, and this is the cost being
  accepted rather than a claim of harmlessness — replacing an
  already-orphaned dataset writes uncounted bytes, so the exempt pool can grow
  by the size of the datasets already in it, times however often an operator
  replaces them.

Scope of the exemption, stated precisely so nobody "simplifies" it into an
early return: usage reads zero, which is not the same as a seam
short-circuiting. Accumulated ownerless storage is never charged to anyone, and
the dataset-count cap can never refuse a NULL owner (a zero count is below every
positive cap). The byte cap still measures the INCOMING amount on its own,
though — net of whatever credit the seam applies — so one reservation larger
than the whole cap is still refused for a NULL owner. Nothing accumulates; an
oversized single file is still oversized. An early return would drop that and
change behaviour.

The durable fix is ownership adoption, tracked by #998. When it lands, this
section, the seams that point at it, and
``TestOwnerlessDatasetsAreExemptAtEverySeam`` in
``backend/tests/test_raster_replace_1221.py`` are what has to change together.
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

    Joins catalog.records → catalog.datasets → catalog.dataset_assets
    (key='data' or 'archived_original:*')
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

    This is where the ownerless-dataset exemption physically lives: the
    ``created_by = :user_id`` filter is never true for NULL, so an ownerless
    dataset counts against nobody and a NULL ``user_id`` reads zero. Every
    other seam inherits that answer through this function. See the module
    docstring for the policy and #998 for the adoption path that ends it.

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


async def check_replacement_quota(
    db: AsyncSession,
    owner_id: uuid.UUID | None,
    incoming_bytes: int,
    request: Request,
    *,
    dataset_id: uuid.UUID,
) -> None:
    """Admit a REPLACEMENT at the door, where ``check_upload_quota`` cannot.

    fix(#1290 review). ``check_upload_quota`` is creation-shaped: it refuses at
    ``dataset_count >= count_cap`` and charges the incoming file on top of
    everything the user already stores. Applied to a replacement both halves
    are wrong, and the first is a feature lockout rather than protection — an
    owner sitting at their permitted dataset limit could not replace a dataset
    they already own, because replacing creates no dataset.

    So: no count check, and the byte check credits what the replacement
    SUPERSEDES — the ``data`` row, read from ``dataset_assets`` because that is
    what ``bytes_used`` sums. It is read from the row rather than the raster
    asset because the two diverge for a STAC-imported dataset, which has an
    asset but no counted row, and crediting bytes the quota never counted would
    admit an upload that overshoots. Archived originals are deliberately NOT
    credited: a replacement does not supersede them, they persist and stay
    counted.

    This is the EARLY bound and deliberately approximate: the door sees the
    uploaded file, not the COG it converts into, which can be larger. The
    authoritative check is ``reserve_storage_bytes`` at publish time, under the
    per-user advisory lock, against the real converted size. Shared by both
    reupload doors and by every record type — the vector path had the identical
    lockout.

    fix(#1290 review): the identity is the dataset's OWNER, not the requester.
    Storage belongs to the owner and the worker reserves against
    ``dataset.record.created_by``, so checking the requester let an admin
    replacing someone else's dataset be admitted or refused on their own usage
    with the owner's credit subtracted — a projection that could go negative,
    and admissions the worker's authoritative reserve then failed. One identity,
    one authority, no disagreement possible.

    ``owner_id`` may be None for an ownerless dataset, and is passed straight
    through: see the module docstring's ownerless-dataset policy, which
    ``reserve_storage_bytes`` reaches by the same route at publish time. Door
    and worker inherit one mechanism rather than mirroring two rules, so
    changing the policy is one edit there, not a hunt through the seams.
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
    """Dataset-count cap exceeded at Record-creation time (fix #302).

    Plain exception rather than HTTPException because the authoritative
    check runs inside the ingest worker, where there is no HTTP response
    to shape; API-side callers get a 422 via the handler registered in
    ``app.api.main``.
    """


async def reserve_dataset_slot(db: AsyncSession, user_id: uuid.UUID | None) -> None:
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

    ``user_id`` is nullable for the same reason as on every other seam here —
    it is a ``records.created_by`` value — though no current caller passes None,
    because a Record is only ever created on behalf of an authenticated
    uploader. Should an adoption or re-ingest path reach it, the
    ownerless-dataset policy in the module docstring applies unchanged and this
    seam cannot refuse: a NULL identity aggregates to a count of zero, which is
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
    """Per-user storage byte cap exceeded at asset-commit time (fix #430 BA-23).

    Plain exception (not HTTPException) because the authoritative check runs
    inside the ingest worker; API-side callers get a 413 via the handler
    registered in ``app.api.main``.
    """


async def reserve_storage_bytes(
    db: AsyncSession, user_id: uuid.UUID | None, incoming_bytes: int
) -> None:
    """Atomically reserve ``incoming_bytes`` against the per-user byte cap (BA-23).

    ``check_upload_quota`` runs the byte check at upload time with no
    serialization, so N concurrent uploads all read the same pre-upload usage,
    all pass, and overshoot the cap. Mirroring ``reserve_dataset_slot``, this is
    the authoritative check: call it inside the SAME transaction that persists
    the byte-bearing asset. It takes the same per-user transaction-scoped advisory
    lock and recounts, so concurrent uploads for one user serialize and cannot
    overshoot ``max_storage_bytes_per_user``.

    No-op when the cap is 0 (the default unlimited config).

    ``user_id`` is None for an ownerless dataset (the replacement path passes
    ``record.created_by`` through unchanged). Nothing accumulates against that
    identity — see the module docstring's ownerless-dataset policy for why, and
    for the one thing the exemption does not cover: the recount reads zero, so
    ``incoming_bytes`` is still weighed against the cap on its own.
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
