"""The VRTs that may still read a member raster's COG, and the COGs kept for them.

A VRT names each member's COG by key, so when a member is replaced, every VRT
built from it reads the superseded COG until it is rebuilt. Such a COG is kept,
under a ``retained_cog:<attempt_id>`` row on the member that quota counts, until
no VRT may read it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import structlog
from sqlalchemy import (
    cast,
    delete,
    func,
    literal,
    null,
    or_,
    select,
    text,
    union_all,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.platform.jobs.models import IngestJob
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.processing.raster.models import (
    DatasetAsset,
    RasterAsset,
    VrtGeneration,
    VrtSourceLink,
)

# On a VRT creation's job: the members it reads, recorded before it reads them.
VRT_MEMBERS_FIELD = "vrt_source_dataset_ids"

RETAINED_COG_PREFIX = "retained_cog:"

_IN_FLIGHT = ("pending", "running")
_RECLAIM_BATCH = 50


def retained_cog_key(attempt_id: uuid.UUID | str) -> str:
    """The ``dataset_assets`` key of the COG the ``attempt_id`` replacement kept."""
    return f"{RETAINED_COG_PREFIX}{attempt_id}"


async def note_vrt_members(
    session,
    job_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID,
    member_ids: Sequence[uuid.UUID],
) -> None:
    """Record on a VRT creation's job the members it is about to read; the caller commits."""
    members = {VRT_MEMBERS_FIELD: [str(member) for member in member_ids]}
    await session.execute(
        update(IngestJob)
        .where(IngestJob.id == job_uuid, IngestJob.attempt_id == attempt_uuid)
        .values(
            user_metadata=func.coalesce(
                IngestJob.user_metadata, text("'{}'::jsonb")
            ).op("||")(literal(members, JSONB))
        )
        .execution_options(synchronize_session=False)
    )


async def cog_readers(
    session, dataset_id: uuid.UUID, asset_uri: str
) -> tuple[list[str], list[str]]:
    """The VRT datasets and VRT-creation jobs that may still read ``asset_uri``.

    A VRT that links ``dataset_id`` reads it when it was built from it, or when
    it has no record of what it was built from. So may a generation or a VRT
    creation that includes the dataset and is still pending or running. One
    statement, so a publish that turns a build in flight into a committed VRT
    can't fall between two reads.
    """
    member = str(dataset_id)
    no_id = cast(null(), UUID)
    links_member = select(VrtSourceLink.vrt_dataset_id).where(
        VrtSourceLink.source_dataset_id == dataset_id
    )
    built_from = RasterAsset.built_from
    published = (
        select(VrtSourceLink.vrt_dataset_id, no_id)
        .outerjoin(RasterAsset, RasterAsset.dataset_id == VrtSourceLink.vrt_dataset_id)
        .where(
            VrtSourceLink.source_dataset_id == dataset_id,
            or_(
                func.jsonb_typeof(built_from).is_distinct_from("object"),
                built_from[member].astext == asset_uri,
            ),
        )
    )
    building = select(VrtGeneration.vrt_dataset_id, no_id).where(
        VrtGeneration.status.in_(_IN_FLIGHT),
        or_(
            VrtGeneration.staged_source_ids.contains([member]),
            VrtGeneration.vrt_dataset_id.in_(links_member),
        ),
    )
    creating = select(no_id, IngestJob.id).where(
        IngestJob.status.in_(_IN_FLIGHT),
        IngestJob.user_metadata.contains({VRT_MEMBERS_FIELD: [member]}),
    )
    rows = (await session.execute(union_all(published, building, creating))).all()
    vrt_ids = sorted({str(vrt_id) for vrt_id, _ in rows if vrt_id is not None})
    job_ids = sorted({str(job_id) for _, job_id in rows if job_id is not None})
    return vrt_ids, job_ids


async def retain_cog(
    session,
    *,
    dataset_id: uuid.UUID,
    attempt_id: uuid.UUID | str,
    asset_uri: str,
    size_bytes: int,
) -> None:
    """Count ``asset_uri`` against the member's owner until it is reclaimed; the caller commits.

    Idempotent: the key names the replacement that kept it.
    """
    await session.execute(
        pg_insert(DatasetAsset)
        .values(
            dataset_id=dataset_id,
            key=retained_cog_key(attempt_id),
            href=asset_uri,
            size_bytes=size_bytes,
        )
        .on_conflict_do_nothing(constraint="uq_dataset_assets_key")
    )


async def reclaim_retained_cogs() -> int:
    """Delete each kept COG no VRT may read any longer, object first, then its row; never raises.

    Returns how many were reclaimed. A row whose readers can't be read, or whose
    object can't be deleted, stays counted for the next pass.
    """
    import app.core.db as db_module
    from app.platform.storage import get_storage

    log = structlog.get_logger()
    reclaimed = 0
    after = None
    while True:
        query = (
            select(DatasetAsset.id, DatasetAsset.dataset_id, DatasetAsset.href)
            .where(DatasetAsset.key.startswith(RETAINED_COG_PREFIX, autoescape=True))
            .order_by(DatasetAsset.id)
            .limit(_RECLAIM_BATCH)
        )
        if after is not None:
            query = query.where(DatasetAsset.id > after)
        try:
            async with db_module.async_session() as session:
                rows = (await session.execute(query)).all()
        except Exception:  # broad: the kept COGs wait for the next pass
            log.warning("retained_cogs_unreadable", exc_info=True)
            return reclaimed
        if not rows:
            return reclaimed
        after = rows[-1].id
        for row in rows:
            try:
                async with db_module.async_session() as session:
                    vrt_ids, job_ids = await cog_readers(
                        session, row.dataset_id, row.href
                    )
                if vrt_ids or job_ids:
                    continue
                await get_storage().delete(resolve_current_storage_key(row.href))
                async with db_module.async_session() as session:
                    await session.execute(
                        delete(DatasetAsset).where(DatasetAsset.id == row.id)
                    )
                    await session.commit()
                reclaimed += 1
            except Exception:  # broad: one kept COG's failure waits for the next pass
                log.warning(
                    "retained_cog_reclaim_failed",
                    dataset_id=str(row.dataset_id),
                    exc_info=True,
                )
