"""Idempotent feature creates: one ``Idempotency-Key`` names one created row.

A create whose response was lost may already have committed. The client sends
the same key on every attempt, with an attempt number that grows by one each
time. The key row written beside the insert lets the route answer a repeat
with the feature that exists instead of inserting another, and the attempt
number orders the bodies: the highest one received is the one applied, whatever
order the requests arrive in. Keys are scoped to (dataset, user), so one
caller's key can neither reveal nor collide with another's.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_schema import tenant_data_schema
from app.core.db.tenant_session import current_tenant_var
from app.modules.catalog.features.models import FeatureCreateKey
from app.platform.extensions import get_catalog_port

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
IDEMPOTENCY_KEY_MAX_LENGTH = 128
IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9._:-]+$"
IDEMPOTENCY_ATTEMPT_HEADER = "Idempotency-Attempt"
IDEMPOTENCY_ATTEMPT_MAX = 2_147_483_647

# A key stops matching after this long, whether or not its row was pruned yet.
KEY_RETENTION = timedelta(hours=24)

# Each keyed create adds one row and prunes up to this many, so the table
# stays bounded without a scheduler.
_PRUNE_BATCH = 100


class KeyedFeature(NamedTuple):
    """What a key row records: the feature, its table, and the newest attempt."""

    id: uuid.UUID
    gid: int
    table_oid: int
    attempt: int
    row_xmin: int


class CreatedRow(NamedTuple):
    """The feature a transaction just wrote, as its key row will record it."""

    gid: int
    table_oid: int
    row_xmin: int


def _retention_cutoff() -> datetime:
    return datetime.now(tz=UTC) - KEY_RETENTION


async def current_table_oid(db: AsyncSession, table_name: str) -> int | None:
    """The oid of the physical table behind a dataset, which a drop changes.

    Read while the transaction holds the table (after a write to it, or a read
    of it), so a swap or overwrite cannot commit between that access and this.
    """
    return await db.scalar(
        text(
            "SELECT to_regclass(format('%I.%I', "
            "CAST(:schema AS text), CAST(:table AS text)))::oid"
        ),
        {"schema": tenant_data_schema(current_tenant_var.get()), "table": table_name},
    )


async def held_table_oid(db: AsyncSession, table_name: str) -> int | None:
    """The oid of the physical table behind a dataset, taking hold of it first.

    The read's lock lasts until the transaction ends, so no swap or overwrite
    can replace the table between this and a later write in the transaction.
    """
    quoted = get_catalog_port().quote_table(table_name)
    await db.execute(text(f"SELECT FROM {quoted} LIMIT 0"))
    return await current_table_oid(db, table_name)


async def current_row_xmin(
    db: AsyncSession, table_name: str, gid: int, *, lock: bool = False
) -> int | None:
    """The ``xmin`` of a feature's row, which changes when a transaction writes it.

    ``lock`` takes the row for update first, so a writer still in flight is
    waited out and what comes back is the version it left; the lock then keeps
    anyone else from changing the row before this transaction does. The id is
    32 bits, so a freeze or wraparound of an untouched row also changes it,
    which reads as someone else's edit and is refused rather than overwritten.
    """
    quoted = get_catalog_port().quote_table(table_name)
    sql = f"SELECT xmin::text::bigint FROM {quoted} WHERE gid = :gid"
    if lock:
        sql += " FOR UPDATE"
    return await db.scalar(text(sql), {"gid": gid})


async def find_live_key(
    db: AsyncSession, dataset_id: uuid.UUID, user_id: uuid.UUID, key: str
) -> KeyedFeature | None:
    """The live row for this user's key in this dataset, else None.

    Called under the key's advisory lock, so no other request on the key is
    writing the row, and what comes back is settled. The row itself is not
    locked: deleting the dataset cascades into these rows after it has taken
    the data table, so a request holding the row while it waits for the table
    would deadlock with the delete.
    """
    row = (
        await db.execute(
            select(
                FeatureCreateKey.id,
                FeatureCreateKey.gid,
                FeatureCreateKey.table_oid,
                FeatureCreateKey.attempt,
                FeatureCreateKey.row_xmin,
            ).where(
                FeatureCreateKey.dataset_id == dataset_id,
                FeatureCreateKey.user_id == user_id,
                FeatureCreateKey.key == key,
                FeatureCreateKey.created_at > _retention_cutoff(),
            )
        )
    ).first()
    return None if row is None else KeyedFeature(*row)


async def claim_create_key(
    db: AsyncSession,
    dataset_id: uuid.UUID,
    user_id: uuid.UUID,
    key: str,
    created: CreatedRow,
    attempt: int,
) -> bool:
    """Record ``key`` for the feature this transaction just inserted.

    ``created`` is the feature as just written. False means a live row already
    holds the key, which cannot happen while the caller holds the key's advisory
    lock and has found no live row under it; the caller treats it as a
    conflict. An expired row is taken over rather than refused.

    The caller takes the dataset's catalog rows first. The key row's foreign
    key takes a shared lock on the dataset row, and two creates that each hold
    it while asking for the exclusive lock the metadata refresh needs deadlock.
    """
    cutoff = _retention_cutoff()
    claimed = await db.scalar(
        pg_insert(FeatureCreateKey)
        .values(
            dataset_id=dataset_id,
            user_id=user_id,
            key=key,
            gid=created.gid,
            table_oid=created.table_oid,
            attempt=attempt,
            row_xmin=created.row_xmin,
        )
        .on_conflict_do_update(
            constraint="uq_feature_create_keys_key",
            set_={
                "gid": created.gid,
                "table_oid": created.table_oid,
                "attempt": attempt,
                "row_xmin": created.row_xmin,
                "created_at": func.now(),
            },
            where=FeatureCreateKey.created_at <= cutoff,
        )
        .returning(FeatureCreateKey.id)
    )
    if claimed is None:
        return False
    # Rows another transaction holds are skipped, so two prunes never wait on
    # each other and housekeeping cannot fail a create.
    expired = (
        select(FeatureCreateKey.id)
        .where(FeatureCreateKey.created_at <= cutoff)
        .order_by(FeatureCreateKey.created_at)
        .limit(_PRUNE_BATCH)
        .with_for_update(skip_locked=True)
    )
    await db.execute(
        delete(FeatureCreateKey).where(
            FeatureCreateKey.id.in_(expired.scalar_subquery())
        )
    )
    return True


async def record_attempt(
    db: AsyncSession, key_id: uuid.UUID, attempt: int, row_xmin: int
) -> None:
    """Store the attempt whose body was just applied, and the row it left."""
    await db.execute(
        update(FeatureCreateKey)
        .where(FeatureCreateKey.id == key_id)
        .values(attempt=attempt, row_xmin=row_xmin)
    )
