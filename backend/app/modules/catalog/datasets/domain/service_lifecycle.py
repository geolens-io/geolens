"""Dataset lifecycle operations: delete + version history (extracted from service.py — Phase 224)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain._sql_safety import (
    SAFE_TABLE_NAME_RE,
    _safe_table_ref,
)
from app.modules.catalog.datasets.domain.models import RetiredTableName
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
    unaffected; a distinct type so callers that need to tell this expected,
    public-safe case apart from other ValueErrors (e.g. a malformed
    persisted table name) can do so by type rather than by message content.
    """


async def _reap_managed_storage(prefixes: list[str], tenant_id: str | None) -> None:
    """Delete every object under GeoLens-managed prefixes for one dataset.

    Extracted from ``delete_dataset``'s two branches (which reaped identically
    from different prefix lists) when fix(#1452) added a branch of its own and
    pushed the function past ruff's complexity ceiling. The import stays
    function-local so tests keep patching the provider attribute.
    """
    from app.platform.storage.provider import get_storage

    storage = get_storage()
    for prefix in prefixes:
        physical_prefix = resolve_storage_key(prefix, tenant_id=tenant_id)
        keys = await storage.list(physical_prefix)
        if keys:
            await asyncio.gather(*(storage.delete(key) for key in keys))


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
) -> str:
    """Delete a dataset: drop data table (vector) or clean storage artifacts (raster).

    Deleting the record cascades to the dataset via FK.
    Returns the table_name for logging. Does NOT commit.
    Raises ValueError if dataset not found, name mismatch, or invalid table name.
    For raster datasets, storage cleanup happens before DB deletion so that a
    storage failure prevents any DB changes (no orphaned records).

    fix(#1452): a dataset registered from an existing PostGIS table is DETACHED
    rather than dropped — the catalog row, its grants, its tiles and its search
    and embedding rows go, and the operator's table survives with its rows,
    exactly as registration left it. See
    :func:`app.platform.dataset_origin.geolens_owns_table`.
    """
    # Function-local import via the service.py façade is intentional — it lets
    # tests mock `service.get_dataset` to inject fixture datasets without DB.
    # Hoisting to module-top broke 7 tests in test_vrt_delete_guard_174.py
    # that patch the façade attribute (post-impl-20260501 P3 #11 partial revert).
    from app.modules.catalog.datasets.domain.service import get_dataset

    dataset = await get_dataset(session, dataset_id)
    if dataset is None:
        raise ValueError("Dataset not found")

    if dataset.record.title != confirm_title:
        raise DatasetTitleMismatchError("Dataset title does not match confirmation")

    table_name = dataset.table_name
    if not SAFE_TABLE_NAME_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name}")

    record_type = dataset.record.record_type

    # fix(#1452): registration copies no data — it points the catalog at a
    # table the operator built and keeps writing to. Deleting the dataset
    # therefore has to detach, not drop, or the delete destroys the original
    # rather than a GeoLens-managed copy. Resolved once here because the DROP
    # and the name retirement below are two effects of this one answer.
    owns_table = geolens_owns_table(
        dataset.source_format, record_type, dataset.origin_ref
    )

    if record_type in RASTER_FAMILY_RECORD_TYPES:
        if record_type == "raster_dataset":
            # Guard: prevent deletion if any VRT still references this COG.
            #
            # fix(#1327): a reference is now either committed or in flight. An
            # add staged by add_vrt_source has no vrt_source_links row until
            # its regeneration publishes the artifact, so the link half of this
            # guard alone would let a source be deleted out from under an
            # in-flight attempt — a hole staging would otherwise open in a
            # guarantee this repo already made. The second branch closes it by
            # asking the same question of the not-yet-applied set. The
            # regeneration task independently refuses to publish a set whose
            # members it cannot load, so a delete that slips past this guard
            # (deleted between this check and the build) fails the attempt
            # instead of half-applying it.
            #
            # Membership is asked with `@>` rather than by expanding the array
            # with jsonb_array_elements_text. Containment is TOTAL over jsonb:
            # a column holding the JSON scalar `null` (which is what SQLAlchemy
            # writes for an explicitly-assigned None — #1322's lesson) answers
            # false instead of raising, and SQL NULL drops the row. An
            # expansion would need a jsonb_typeof guard beside it in the same
            # AND, and nothing obliges the planner to evaluate that guard
            # first. Only 'pending'/'running' generations count — a terminal
            # one will never apply its set.
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
            # COG: clean both rasters/ and originals/ storage prefixes
            prefixes = [f"rasters/{dataset_id}/", f"originals/{dataset_id}/"]
        else:
            # VRT: only rasters/ prefix (no originals -- VRTs are generated, not uploaded)
            # vrt_source_links cascade-deleted via ON DELETE CASCADE on vrt_dataset_id FK
            prefixes = [f"rasters/{dataset_id}/"]

        # Clean up managed storage artifacts before touching the DB.
        # If any storage delete fails the exception propagates and the
        # caller's transaction rolls back, leaving the DB record intact.
        tenant_id = current_tenant_var.get()
        if is_multi_tenant() and tenant_id is None:
            raise RuntimeError(
                "Dataset deletion is missing tenant context in multi-tenant mode"
            )
        await _reap_managed_storage(prefixes, tenant_id)
    else:
        # Vector datasets: drop the PostGIS data table AND clean managed storage.
        # fix(#430 BA-17): vector ingest persists originals/{id}/ (archived source) and
        # vectors/{id}/quicklook_256.png; the old vector branch only dropped the
        # table, orphaning both objects forever (no reaper).
        tenant_id = current_tenant_var.get()
        if is_multi_tenant() and tenant_id is None:
            raise RuntimeError(
                "Dataset deletion is missing tenant context in multi-tenant mode"
            )
        data_schema = tenant_data_schema(tenant_id)
        if owns_table:
            await session.execute(
                text(
                    f"DROP TABLE IF EXISTS "
                    f"{_safe_table_ref(table_name, schema=data_schema)}"
                )
            )
        # The storage reap below runs either way: `originals/` and `vectors/`
        # hold GeoLens-produced artifacts keyed by dataset id (an archived
        # source, a quicklook), never the operator's table. A detached dataset
        # has no claim on them once its row is gone.
        #
        # Detach leaves the table as REGISTRATION left it, which is not the
        # same as untouched: register_existing_table may have added a
        # geom_4326 column and its GIST index, granted SELECT to the reader
        # role, and linearized an existing geom_4326 in place. None of that is
        # undone here, deliberately.
        #
        # Undoing it would be this path writing to a relation GeoLens does not
        # own, and each undo is worse than the state it removes: dropping a
        # column rewrites the operator's table under a lock to delete a
        # harmless one, revoking the grant removes a privilege that reaches
        # nothing (every read resolves a table through `catalog.datasets`, and
        # the row is going), and the linearization is not reversible at all
        # since the pre-linear geometries are gone. Re-registering the table
        # re-applies all three idempotently.
        await _reap_managed_storage(
            [f"originals/{dataset_id}/", f"vectors/{dataset_id}/"], tenant_id
        )

    # fix(#1443): retire the name before releasing it. This is the one site
    # where a name a LIVE dataset row carried stops being carried by one, and
    # that is exactly the condition under which the tile router's table_name ->
    # metadata map could be holding an entry for it — that map is populated
    # only from catalog.datasets. Record TYPE does not gate it — the raster/VRT
    # branch drops nothing, but its dataset row goes, so the name it occupied in
    # the catalog probe is freed just the same, and _resolve_dataset_meta does
    # not filter on record_type before caching what it found. Ownership does
    # gate it, which is the #1452 paragraph below.
    #
    # session.add, so it lands in the caller's transaction alongside the DROP
    # and the record delete. A crash between them can therefore roll back the
    # whole delete, but can never commit a freed name with no tombstone.
    #
    # fix(#1452): except when the delete detached instead of dropping. The
    # recording rule is "retire a name iff a catalog.datasets row pointed at it
    # when it was freed", and a detach frees nothing — the relation is still
    # there, still holding the operator's rows, still occupying the name.
    # Retiring it anyway would make the operator's own table permanently
    # unregisterable, since register_existing_table refuses a retired name and
    # deliberately refuses rather than renames.
    #
    # What that costs is bounded and is not GH-1443's hazard. A successor can
    # only be the SAME physical table re-registered by whoever can still see
    # it: the surviving relation makes the name collide in generate_table_name's
    # pg_class probe, so no ingest can draw it. A tile worker holding the
    # predecessor's metadata past the delete therefore serves the same rows it
    # was cached for, under a visibility that can be up to the 60s meta-cache
    # TTL stale — the bounded-staleness tradeoff processing/tiles/router.py
    # already documents for any visibility change, not a predecessor's
    # visibility over a different dataset's rows.
    if owns_table:
        session.add(
            RetiredTableName(
                table_name=table_name,
                tenant_id=dataset.tenant_id,
                dataset_id=dataset_id,
            )
        )

    # Delete the record (CASCADE handles dataset deletion)
    await session.delete(dataset.record)

    if record_type not in RASTER_FAMILY_RECORD_TYPES:
        # fix(#1427): purge the dropped table's MVT tiles. The cache key was
        # `tile:{table}:{z}:{x}:{y}` with no dataset id and no content version,
        # and generate_table_name collided only against LIVE rows and relations
        # — so the name freed above was immediately reusable, and whoever drew
        # it next was authorized on its own visibility while served this
        # dataset's bytes for up to tile_cache_ttl.
        #
        # fix(#1429) made the purge no longer load-bearing for correctness —
        # tile keys now carry the dataset id, so a successor drawing this name
        # cannot read these entries whether or not the purge lands — and
        # fix(#1444) removed the redraw itself (see the retirement above). It
        # stays because the orphaned entries are dead weight until their TTL,
        # and because it is what every sibling write path does. Placed here
        # rather than after the caller's commit so single delete, bulk delete,
        # and future callers get it from one place. Raster/VRT are excluded —
        # their tiles come from Titiler, and that branch drops no table.
        from app.platform.cache.provider import get_tile_cache

        tile_cache = get_tile_cache()
        if tile_cache is not None:
            await tile_cache.invalidate_table(table_name)

    # fix(#1429): the matching eviction of the tile router's table_name ->
    # metadata map is NOT here, it is at the two delete endpoints after their
    # commit. That map is populated from `catalog.datasets`, which the DROP
    # above does not lock, so a concurrent tile request inside this still-open
    # transaction reads the not-yet-deleted row and re-caches the dataset we
    # just evicted. Only a commit makes the delete visible to that reader.

    # Audit trail for an irreversible operation (DROP TABLE for vector,
    # storage cleanup for raster/VRT). The DB-side row deletion is logged
    # by the audit_emit() facade in the calling router.
    logger.info(
        "dataset_deleted",
        dataset_id=str(dataset_id),
        table_name=table_name,
        record_type=record_type,
        title=confirm_title,
        # fix(#1452): here rather than in the router's audit_emit details,
        # following the split the paragraph above states — this log line
        # covers the PHYSICAL artifact, audit_emit covers the DB row. It is
        # also the only place the answer survives: the dataset row that
        # decided it is deleted a few lines up.
        table_detached=not owns_table,
    )

    return table_name


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

    # Get total count
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = await session.execute(count_stmt)
    total_count = total.scalar_one()

    # Get paginated results
    paginated_stmt = (
        base_stmt.order_by(DatasetVersion.version_number.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(paginated_stmt)
    versions = list(result.scalars().all())

    return versions, total_count
