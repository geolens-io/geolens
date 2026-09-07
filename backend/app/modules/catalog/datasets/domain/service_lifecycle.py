"""Dataset lifecycle operations: delete + version history (extracted from service.py — Phase 224)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, NamedTuple

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain._sql_safety import (
    SAFE_TABLE_NAME_RE,
    _safe_table_ref,
)
from app.modules.catalog.datasets.domain.models import (
    DetachedRelation,
    RetiredTableName,
)
from app.core.db.tenant_session import current_tenant_var
from app.core.db.tenant_schema import tenant_data_schema
from app.core.tenancy import is_multi_tenant
from app.core.record_types import RASTER_FAMILY_RECORD_TYPES
from app.platform.dataset_origin import geolens_owns_table
from app.platform.storage.titiler_url import resolve_storage_key

logger = structlog.stdlib.get_logger(__name__)


__all__ = [
    "DatasetTitleMismatchError",
    "DependentVrtError",
    "delete_dataset",
    "get_dataset_versions",
]


class DatasetTitleMismatchError(ValueError):
    """Raised when confirm_title does not match the dataset's stored title.

    A ValueError subclass so existing broad `except ValueError` callers are
    unaffected; a distinct type so a caller can tell this expected,
    public-safe case apart from others (e.g. a malformed table name).
    """


class DatasetDeletion(NamedTuple):
    """What `delete_dataset` removed, and what the caller must still reap.

    `storage_prefixes` are GeoLens-managed object prefixes for this dataset;
    `tenant_id` is the tenant they live under. The caller MUST reap them after
    its commit, and only after it: nothing here touches object storage.
    """

    table_name: str
    storage_prefixes: tuple[str, ...]
    tenant_id: str | None


async def reap_managed_storage(prefixes: list[str], tenant_id: str | None) -> None:
    """Delete every object under GeoLens-managed prefixes for one dataset.

    Extracted from ``delete_dataset``'s two branches, which reaped
    identically from different prefix lists, when fix(#1452) pushed the
    function past ruff's complexity ceiling. The import stays function-local
    so tests keep patching the provider attribute.
    """
    from app.platform.storage.provider import get_storage

    storage = get_storage()
    for prefix in prefixes:
        physical_prefix = resolve_storage_key(prefix, tenant_id=tenant_id)
        keys = await storage.list(physical_prefix)
        if keys:
            await asyncio.gather(*(storage.delete(key) for key in keys))


async def _relation_oid(
    session: AsyncSession, table_name: str, *, schema: str
) -> int | None:
    """The oid of the relation holding this name in ``schema``, or None.

    pg_catalog rather than information_schema: the SQL standard filters
    information_schema to relations the current role holds a privilege on,
    so a role that doesn't own the relation could be blind to it; pg_class
    is visible to every role and every relation kind.

    fix(#1456): returns the oid rather than a bare bool so ONE probe answers
    both questions the delete asks -- whether anything occupies the name,
    and which relation it is. None is the only "absent" answer.
    """
    result = await session.execute(
        text(
            "SELECT c.oid FROM pg_catalog.pg_class c"
            " JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = :schema AND c.relname = :table_name"
        ).bindparams(schema=schema, table_name=table_name)
    )
    oid = result.scalar()
    return None if oid is None else int(oid)


class DependentVrtError(Exception):
    """Raised when attempting to delete a COG referenced by VRT datasets."""

    def __init__(self, dependents: list[dict]) -> None:
        self.dependents = dependents
        names = ", ".join(d["vrt_dataset_title"] for d in dependents)
        super().__init__(
            f"Cannot delete: this dataset is used as a source in "
            f"{len(dependents)} virtual raster(s): {names}"
        )


async def delete_dataset(
    session: AsyncSession, dataset_id: uuid.UUID, confirm_title: str
) -> DatasetDeletion:
    """Delete a dataset's rows: drop the data table (vector) or leave it (raster).

    Deleting the record cascades to the dataset via FK. Does NOT commit, and
    does NOT touch object storage: it returns the prefixes the caller must
    reap once the delete has COMMITTED. See `DatasetDeletion` for why that
    order. Raises ValueError if dataset not found, name mismatch, or invalid
    table name.

    fix(#1452): a dataset registered from an existing PostGIS table is
    DETACHED rather than dropped -- the catalog row, grants, tiles, search
    and embedding rows go, but the operator's table survives with its rows.
    See :func:`app.platform.dataset_origin.geolens_owns_table`.
    """
    # Function-local import via the service.py façade is intentional -- it
    # lets tests mock `service.get_dataset` to inject fixture datasets
    # without a DB. Hoisting to module-top broke 7 tests that patch the
    # façade attribute.
    from app.modules.catalog.datasets.domain.service import get_dataset
    from app.modules.catalog.features.service import lock_catalog_rows_for_write

    dataset = await get_dataset(session, dataset_id)
    if dataset is None:
        raise ValueError("Dataset not found")

    if dataset.record.title != confirm_title:
        raise DatasetTitleMismatchError("Dataset title does not match confirmation")

    table_name = dataset.table_name
    if not SAFE_TABLE_NAME_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name}")

    record_type = dataset.record.record_type

    # fix(#1452): registration copies no data -- it points the catalog at a
    # table the operator built and keeps writing to. Deleting the dataset
    # therefore has to detach, not drop, or it destroys the original rather
    # than a GeoLens-managed copy. Decides the DROP alone; name retirement
    # asks the separate question below.
    owns_table = geolens_owns_table(
        dataset.source_format, record_type, dataset.origin_ref
    )

    # fix(#1452): whether this delete FREES the name is separate from
    # ownership -- a detach frees nothing while the relation stands, but a
    # registered dataset whose table was already dropped frees the name
    # like an ingested delete, and skipping its tombstone reopens GH-1443.
    # True by default: a missing tombstone is the disclosure risk; an
    # extra one only costs a rename before re-registering.
    name_is_freed = True

    # fix(#1456): identity of the relation this delete frees, read while
    # it's still there. Stays None where no relation held the name -- the
    # raster/VRT branch (synthetic `raster_<hex>` table_name) and a detach
    # whose table was already dropped. NULL means "nothing to identify",
    # never "no owner".
    relation_oid: int | None = None

    # fix(#1847): lock job rows before the table and the pair; a worker
    # holds its job row before either, and the record delete cascades into them.
    from app.platform.catalog_locks import lock_ingest_jobs
    from app.platform.jobs.models import IngestJob

    await lock_ingest_jobs(session, job_cls=IngestJob, dataset_id=dataset.id)

    if record_type in RASTER_FAMILY_RECORD_TYPES:
        if record_type == "raster_dataset":
            # Guard: prevent deletion if any VRT still references this COG.
            #
            # fix(#1327): a reference is committed OR in flight -- an add
            # staged by add_vrt_source has no vrt_source_links row until
            # its regeneration publishes, so the second branch closes that
            # gap by asking the not-yet-applied set too.
            #
            # Membership uses `@>`, not jsonb_array_elements_text: jsonb
            # containment is TOTAL, so a column holding JSON `null`
            # (#1322) answers false instead of raising. Only
            # 'pending'/'running' generations count.
            refs_result = await session.execute(
                text(
                    """
                    SELECT d.id, r.title
                    FROM catalog.vrt_source_links vsl
                    JOIN catalog.datasets d ON d.id = vsl.vrt_dataset_id
                    JOIN catalog.records r ON r.id = d.record_id
                    WHERE vsl.source_dataset_id = :dataset_id
                    UNION
                    SELECT d.id, r.title
                    FROM catalog.vrt_generations g
                    JOIN catalog.datasets d ON d.id = g.vrt_dataset_id
                    JOIN catalog.records r ON r.id = d.record_id
                    WHERE g.status IN ('pending', 'running')
                      AND g.staged_source_ids @> to_jsonb(CAST(:dataset_id_text AS text))
                    """
                ).bindparams(dataset_id=dataset_id, dataset_id_text=str(dataset_id))
            )
            refs = refs_result.all()
            if refs:
                raise DependentVrtError(
                    [
                        {"vrt_dataset_id": str(row.id), "vrt_dataset_title": row.title}
                        for row in refs
                    ]
                )
            prefixes = [f"rasters/{dataset_id}/", f"originals/{dataset_id}/"]
        else:
            # VRT: no originals/ prefix -- VRTs are generated, not uploaded.
            # vrt_source_links cascade-deletes via ON DELETE CASCADE.
            prefixes = [f"rasters/{dataset_id}/"]

        # These prefixes are returned, not reaped: the caller commits first and
        # then reaps best-effort, so a reap failure leaves orphaned objects
        # rather than a catalog row pointing at deleted bytes.
        tenant_id = current_tenant_var.get()
        if is_multi_tenant() and tenant_id is None:
            raise RuntimeError(
                "Dataset deletion is missing tenant context in multi-tenant mode"
            )
        # fix(#1847): includes the raster child, which the record delete
        # cascades to and the replace worker holds across its upload.
        await lock_catalog_rows_for_write(session, dataset, with_raster_asset=True)

        storage_prefixes = tuple(prefixes)
    else:
        # fix(#430): vector ingest persists originals/{id}/ (archived source)
        # and vectors/{id}/quicklook_256.png; the old branch only dropped
        # the table, orphaning both objects forever (no reaper).
        tenant_id = current_tenant_var.get()
        if is_multi_tenant() and tenant_id is None:
            raise RuntimeError(
                "Dataset deletion is missing tenant context in multi-tenant mode"
            )
        data_schema = tenant_data_schema(tenant_id)
        # fix(#1456): probe ahead of the branch, not inside the detach arm.
        # After the DROP below the pg_class row is gone within this
        # transaction, so this is the last moment the relation can be
        # identified -- and the detach arm needs the same read anyway.
        relation_oid = await _relation_oid(session, table_name, schema=data_schema)
        if owns_table:
            # Deliberately does NOT feed `name_is_freed`. A missing relation
            # here means the DROP IF EXISTS is a no-op, not that the name
            # stays taken -- the catalog row going is what frees it.
            await session.execute(
                text(
                    f"DROP TABLE IF EXISTS "
                    f"{_safe_table_ref(table_name, schema=data_schema)}"
                )
            )
        else:
            # The name stays taken only if the relation is still there,
            # asked inside this transaction; a concurrent DROP either
            # committed before this read (name retired) or lands after
            # (the residual noted in the retirement comment below).
            name_is_freed = relation_oid is None
        # The storage reap below runs either way: originals/ and vectors/
        # hold GeoLens-produced artifacts keyed by dataset id, never the
        # operator's table.
        #
        # Detach leaves the table as REGISTRATION left it (geom_4326
        # column/index, reader grant, linearization), not untouched --
        # undoing any of it writes to a relation GeoLens doesn't own, and
        # is worse than leaving it (linearization isn't reversible; a
        # column drop rewrites the table for nothing). Re-registering
        # reapplies all three idempotently.
        # fix(#1847): ahead of the reap, behind the DROP. See the raster branch.
        await lock_catalog_rows_for_write(session, dataset)

        storage_prefixes = (f"originals/{dataset_id}/", f"vectors/{dataset_id}/")

    # fix(#1443): retire the name before releasing it, so the tile
    # router's table_name -> metadata map can't hold a stale entry.
    # session.add lands in the same transaction as the DROP and record
    # delete: a crash rolls back the whole delete, never a freed name
    # with no tombstone.
    #
    # fix(#1452): except when detached with the relation left standing --
    # nothing was released, so retiring would make the table permanently
    # unregisterable. Reads `name_is_freed`, not `owns_table`, since a
    # registered dataset whose table was ALREADY gone also needs the
    # tombstone (GH-1443). The surviving-relation case is bounded:
    # generate_table_name blocks ingest on it, so stale tile metadata
    # serves at most the 60s meta-cache TTL of the SAME dataset's rows.
    #
    # ONE residual: an operator dropping that relation AFTER this reads
    # it frees the name untombstoned. fix(#1456) records its identity
    # here for a future closure (nothing reads it yet) -- why the ELSE
    # branch below exists, on this no-tombstone path.
    if name_is_freed:
        session.add(
            RetiredTableName(
                table_name=table_name,
                tenant_id=dataset.tenant_id,
                dataset_id=dataset_id,
                # fix(#1456): captured while their sources are alive (oid
                # before the DROP above, created_by before the record delete
                # below). The oid identifies the relation for ONE cluster
                # lifetime only -- pg_dump/restore doesn't preserve oids, so
                # a consumer must treat a post-restore mismatch as unknown,
                # not as a real mismatch. The owner id is the durable half.
                relation_oid=relation_oid,
                previous_owner_id=dataset.record.created_by,
            )
        )
    elif relation_oid is not None:
        # fix(#1456): no name was released, so nothing goes in the
        # retirement set -- recorded HERE or never, since created_by dies
        # with the record row and the oid dies when the operator drops
        # the relation. Separate table so no retirement-set reader has to
        # remember a predicate. `is not None` is belt-and-braces: on this
        # branch name_is_freed is False because the probe found a
        # relation, so None here would mean the two answers disagreed.
        session.add(
            DetachedRelation(
                table_name=table_name,
                tenant_id=dataset.tenant_id,
                dataset_id=dataset_id,
                relation_oid=relation_oid,
                previous_owner_id=dataset.record.created_by,
            )
        )

    # CASCADE handles dataset deletion; both branches above already hold
    # the pair records-first.
    await session.delete(dataset.record)

    if record_type not in RASTER_FAMILY_RECORD_TYPES:
        # fix(#1427): purge the dropped table's MVT tiles -- the old cache
        # key had no dataset id, so a name freed above was immediately
        # reusable and its successor could be served this dataset's bytes.
        #
        # fix(#1429)/fix(#1444): non-load-bearing now (tile keys carry the
        # dataset id) but stays, since orphaned entries are dead weight
        # until TTL. Raster/VRT excluded -- their tiles come from Titiler.
        #
        # fix(#1847): runs with the catalog pair held, before the commit.
        from app.platform.cache.provider import get_tile_cache

        tile_cache = get_tile_cache()
        if tile_cache is not None:
            await tile_cache.invalidate_table(table_name)

    # fix(#1429): the matching eviction of the tile router's table_name ->
    # metadata map is NOT here, it is at the two delete endpoints after
    # their commit -- the DROP above doesn't lock catalog.datasets, so a
    # concurrent tile request inside this still-open transaction would
    # re-cache the dataset we just evicted. Only a commit makes it visible.

    # Audit trail for an irreversible operation. The DB-side row deletion is
    # logged by the calling router's audit_emit(), which also reaps storage
    # after its commit; this line covers the PHYSICAL artifact.
    logger.info(
        "dataset_deleted",
        dataset_id=str(dataset_id),
        table_name=table_name,
        record_type=record_type,
        title=confirm_title,
        # fix(#1452): both flags recorded because they disagree in the one
        # case worth reading about later -- a detach whose table was
        # already gone still retires the name.
        table_detached=not owns_table,
        name_retired=name_is_freed,
    )

    return DatasetDeletion(table_name, storage_prefixes, tenant_id)


async def get_dataset_versions(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """List version history for a dataset, ordered by version_number desc.

    Returns a tuple of (versions, total_count).
    """
    from app.modules.catalog.collections.models import DatasetVersion

    base_stmt = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = await session.execute(count_stmt)
    total_count = total.scalar_one()

    paginated_stmt = (
        base_stmt.order_by(DatasetVersion.version_number.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(paginated_stmt)
    versions = list(result.scalars().all())

    return versions, total_count
