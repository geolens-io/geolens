"""Catalog writes that publish a replaced raster, and the work that follows.

fix(#1290 review): a pure extraction from ``tasks_raster_replace``, which
crossed the 1000-line ratchet threshold in round 4. Nothing here is new — every
function moved verbatim.

The seam is the one the task itself is built around. ``tasks_raster_replace``
now holds the pipeline: claim, validate, convert, verify, and the terminal
cleanup that decides what the uploaded bytes were worth. This module holds what
happens once those bytes have become a COG worth publishing — the field swap,
the asset-row upsert, the superseded-object reap, and the post-commit
follow-ups. One is about producing an artifact; the other is about making the
catalog point at it.
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select

from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.dataset_origin import set_dataset_origin
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.processing.ingest.tasks_raster_common import _cleanup_orphaned_storage_keys

logger = structlog.get_logger(__name__)


def _write_swapped_fields(
    raster_asset,
    dataset,
    *,
    cog_meta: dict,
    cog_key: str,
    ql256_key: str,
    ql512_key: str,
    asset_sha256: str,
    source_sha256: str,
    source_meta: dict,
    cog_size: int,
    cog_status: str,
    source_filename: str | None,
    user_id: str,
) -> int:
    """Move every catalog field the swap owns, and return the new version.

    Extracted from ``reupload_raster`` when the round-3 archive step pushed
    that function back over the McCabe gate. Pure field assignment on two
    attached ORM instances — the caller's transaction is what makes it atomic
    with the storage puts and the job's terminal write.
    """
    nodata_val = cog_meta.get("nodata")
    raster_asset.asset_uri = cog_key
    raster_asset.quicklook_256_uri = ql256_key
    raster_asset.quicklook_512_uri = ql512_key
    raster_asset.sha256 = asset_sha256
    raster_asset.size_bytes = cog_size
    raster_asset.source_sha256 = source_sha256
    raster_asset.cog_status = cog_status
    # fix(#1290 review): a STAC-origin row carries
    # storage_backend="remote" because its asset_uri WAS an external
    # href. The swap has just replaced that with a managed
    # `rasters/...` key, so leaving the backend alone tells every
    # consumer to treat a managed key as a URL: the COG download
    # endpoint SSRF-validates it and proxies it, and VRT health probes
    # it over HTTP. "local" is what `create_raster_dataset` writes for
    # every managed raster — the value means "GeoLens owns these
    # bytes", and `resolve_open_path` does the local/S3/Azure dispatch
    # from the key itself.
    raster_asset.storage_backend = "local"
    raster_asset.driver = cog_meta.get("driver")
    raster_asset.ingested_at = datetime.now(timezone.utc)
    raster_asset.crs_wkt = cog_meta.get("crs_wkt")
    raster_asset.epsg = cog_meta.get("epsg")
    raster_asset.band_count = cog_meta.get("band_count")
    raster_asset.dtype = cog_meta.get("dtype")
    raster_asset.nodata = str(nodata_val) if nodata_val is not None else None
    raster_asset.res_x = cog_meta.get("res_x")
    raster_asset.res_y = cog_meta.get("res_y")
    raster_asset.width = cog_meta.get("width")
    raster_asset.height = cog_meta.get("height")
    raster_asset.compression = cog_meta.get("compression")
    raster_asset.band_info = cog_meta.get("band_info")
    raster_asset.is_rotated = cog_meta.get("is_rotated", False)
    # Recomputed, not carried over: replacing a single-band float
    # elevation raster with an RGB orthophoto has to stop rendering as
    # terrain. Same reasoning as the VRT regenerate path (#185).
    raster_asset.is_dem = cog_meta.get("is_dem_candidate", False)

    new_version = dataset.current_version + 1
    dataset.current_version = new_version
    dataset.srid = cog_meta.get("epsg")
    # fix(#1290 review): the two fields answer different questions and
    # round 1 collapsed them onto one read. `srid` is what the dataset
    # serves, which is the converted COG's; `original_srid` is
    # documented as the SRID of the uploaded file, so under an override
    # it must still report what the upload declared. Collapsing them
    # made a 4326 source with srid_override=3857 record 3857 twice and
    # lose the only record of what arrived.
    dataset.original_srid = source_meta.get("epsg")
    dataset.source_filename = source_filename
    dataset.source_format = "geotiff"
    # fix(#525 B-038): the Valkey purge cannot reach CDN or browser
    # caches keyed on the tile URL, so the `_v=` buster has to roll in
    # the same transaction as the pointer it invalidates.
    dataset.bump_tile_cache_version()
    # feat(#1218) ADR-002 Decision 7: the dataset IS the COG and the
    # upload is a transient input, so the origin restamps to the new
    # file with no remote URI to point at.
    set_dataset_origin(
        dataset,
        "upload",
        filename=source_filename,
        file_hash=source_sha256,
    )
    swap_time = datetime.now(timezone.utc)
    dataset.last_refreshed_at = swap_time
    dataset.record.updated_by = uuid.UUID(user_id)
    if cog_meta.get("bbox_wkt"):
        dataset.record.spatial_extent = func.ST_GeomFromText(cog_meta["bbox_wkt"], 4326)

    return new_version


async def reserve_replacement_bytes(
    session, *, dataset_id: uuid.UUID, owner_id: uuid.UUID, new_size: int
) -> None:
    """Reserve the replacement's NET byte increase under the owner's quota lock.

    fix(#1290 review). The swap rewrites the quota-counted
    ``dataset_assets.data.size_bytes`` and did so with no reservation at all —
    only first ingest took the lock. So a small source expanding into a large
    COG, or two replaces of DIFFERENT datasets owned by one user running
    concurrently, both committed past ``MAX_STORAGE_BYTES_PER_USER``. (Two
    replaces of the SAME dataset cannot race: the one-active-run index refuses
    the second at the door.)

    Net, not absolute, and that composes with the existing primitive rather
    than forking a second lock discipline: ``reserve_storage_bytes`` adds its
    argument to a LIVE recount, and at this point the recount still includes
    the row this swap is about to overwrite. So passing the delta asks exactly
    "will the post-swap total fit". It must therefore run BEFORE
    ``_upsert_managed_asset_rows`` — after it, the recount already holds the
    new value and the delta would be counted twice.

    The credit comes from the ``dataset_assets`` row rather than the
    ``RasterAsset``, because that row is what the quota sums: a STAC-imported
    dataset has an asset carrying bytes and no counted row, and crediting bytes
    the quota never counted would admit an overshoot.

    A shrinking replacement reserves nothing and needs no special case — usage
    is a live sum, so it self-corrects the moment the smaller row commits.
    """
    from sqlalchemy import text

    from app.modules.quota.service import reserve_storage_bytes

    counted = await session.scalar(
        text(
            "SELECT COALESCE(SUM(size_bytes), 0)::bigint "
            "FROM catalog.dataset_assets "
            "WHERE dataset_id = :dataset_id AND key = 'data'"
        ),
        {"dataset_id": dataset_id},
    )
    delta = new_size - int(counted or 0)
    if delta <= 0:
        return
    await reserve_storage_bytes(session, owner_id, delta)


async def _upsert_managed_asset_rows(
    session,
    *,
    dataset_id: uuid.UUID,
    record_id: uuid.UUID,
    cog_key: str,
    ql256_key: str,
    ql512_key: str,
    cog_size: int,
) -> None:
    """Point the STAC/search/download surfaces at the newly published COG.

    fix(#1290 review). This was two UPDATEs, which is correct only for a
    dataset that already has the rows — true of an upload-origin raster, false
    of a STAC-imported one, whose import writes the dataset and the raster
    asset and nothing else. Against those the UPDATEs matched zero rows and
    reported success, so a replaced STAC raster advertised no data asset and no
    quicklooks at all.

    Upserting makes the outcome the same either way, which is the property
    worth having: after this runs the four rows exist and describe the live
    asset, whatever the dataset's origin was. The ``dataset_assets`` rows are
    built by ``_build_dataset_asset_rows`` — the same helper first ingest uses
    — so the two paths cannot describe the same asset differently.

    ``record_distributions`` is delete-then-insert rather than ON CONFLICT
    because its unique constraint includes ``url``: the replacement has a new
    URL by construction, so a conflict target keyed on it can never match the
    row that needs replacing.
    """
    from sqlalchemy import delete as sa_delete
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.platform.extensions import get_catalog_port, get_processing_port
    from app.processing.ingest.tasks_raster_common import _build_dataset_asset_rows

    DatasetAsset = get_catalog_port().dataset_asset_orm_class()
    RecordDistribution = get_processing_port().get_record_distribution_orm_class()

    for row in _build_dataset_asset_rows(
        dataset_id=dataset_id,
        cog_key=cog_key,
        ql256_key=ql256_key,
        ql512_key=ql512_key,
        cog_size=cog_size,
        is_manifest_vrt=False,
    ):
        stmt = pg_insert(DatasetAsset).values(**row)
        await session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_dataset_assets_key",
                # Only the columns this row actually carries: the quicklook
                # rows have no size_bytes, and listing it would overwrite a
                # stored value with NULL.
                set_={
                    k: stmt.excluded[k] for k in row if k not in ("dataset_id", "key")
                },
            )
        )

    await session.execute(
        sa_delete(RecordDistribution).where(
            RecordDistribution.record_id == record_id,
            RecordDistribution.format == "geotiff",
        )
    )
    session.add(
        RecordDistribution(
            record_id=record_id,
            distribution_type="download",
            format="geotiff",
            url=cog_key,
        )
    )


async def _run_post_swap_followups(
    *,
    dataset_uuid: uuid.UUID,
    dataset_cls: type,
    prior_physical_keys: list[str],
    written_storage_keys: list[str],
    job_id: str,
) -> None:
    """Work that happens once the replacement is durably published.

    Extracted (fix(#1290 review)) so the caller can fence the whole of it in
    one place — every statement here is optional, and none of it may be
    confused with a failed replace.

    Reaping the superseded objects is safe only now. Up to the commit every
    exit left the previous COG both pointed at and present; past it the pointer
    is durably elsewhere, so those objects have no reader left. The
    ``not in written`` filter is what makes re-uploading the identical file a
    no-op rather than a self-inflicted delete.

    "No reader left" is true of the DATABASE. An API process that served a tile
    in the last minute may still hold this dataset in the tile router's
    ``_resolve_raster_meta`` cache, whose entries carry the OLD asset_uri for up
    to ``_RASTER_META_CACHE_TTL`` (60s) — so raster tiles can fail for that
    window before the entry expires and the new pointer is read. Deliberately
    not worked around: ``regenerate_vrt`` reaps its superseded generation the
    same way against the same cache, the window is bounded and self-healing, and
    closing it needs cross-process invalidation neither path has. The bumped
    ``tile_cache_version`` already changes the tile URL, so browser and CDN
    caches roll over immediately.
    """
    from app.core.db import async_session
    from sqlalchemy.orm import joinedload

    await invalidate_catalog_cache()
    await _cleanup_orphaned_storage_keys(
        [key for key in prior_physical_keys if key not in written_storage_keys],
        job_id=job_id,
    )
    async with async_session() as embed_session:
        embed_dataset = (
            await embed_session.execute(
                select(dataset_cls)
                .options(joinedload(dataset_cls.record))
                .where(dataset_cls.id == dataset_uuid)
            )
        ).scalar_one_or_none()
        if embed_dataset is not None:
            from app.processing.embeddings.helpers import defer_embedding

            await defer_embedding(embed_dataset)


def _prior_asset_keys_to_reap(
    *,
    asset_uri: str | None,
    quicklook_256_uri: str | None,
    quicklook_512_uri: str | None,
) -> list[str]:
    """Resolve the superseded objects, in the same physical form as the puts.

    Mirrors ``tasks_vrt._prior_generation_storage_keys_to_reap``: catalog rows
    hold logical keys and storage holds tenant-prefixed ones, so the two lists
    the caller compares must both be physical or a same-key replace would reap
    the object it just wrote.
    """
    return [
        resolve_current_storage_key(key)
        for key in (asset_uri, quicklook_256_uri, quicklook_512_uri)
        if key
    ]


# No legacy alias: the sibling tasks carry `app.ingest.tasks.*` aliases because
