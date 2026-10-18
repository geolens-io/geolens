"""Catalog writes that publish a replaced raster.

The raster strategy in ``tasks_raster_replace`` converts the upload and puts
the new objects; this module makes the catalog point at them: the field swap,
the kept original, the quota reservation and the asset-row upserts.
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import func

from app.platform.dataset_origin import set_dataset_origin
from app.platform.storage.titiler_url import resolve_current_storage_key

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

    Pure field assignment on two attached ORM instances; the caller's
    transaction is what makes it atomic with the storage puts and the job's
    terminal write. ``tile_cache_version`` is not among the fields: the caller
    rolls it through ``bump_tile_cache_version_on`` once it holds the row.
    """
    nodata_val = cog_meta.get("nodata")
    raster_asset.asset_uri = cog_key
    raster_asset.quicklook_256_uri = ql256_key
    raster_asset.quicklook_512_uri = ql512_key
    raster_asset.sha256 = asset_sha256
    raster_asset.size_bytes = cog_size
    raster_asset.source_sha256 = source_sha256
    raster_asset.cog_status = cog_status
    # A STAC-origin row carries storage_backend="remote" because its asset_uri
    # was an external href. It is now a managed `rasters/...` key, and "remote"
    # would make consumers treat it as a URL (the COG download endpoint
    # SSRF-validates and proxies it; VRT health probes it over HTTP). "local"
    # means GeoLens owns the bytes, as `create_raster_dataset` writes for every
    # managed raster; `resolve_open_path` dispatches local/S3/Azure by key.
    raster_asset.storage_backend = "local"
    raster_asset.driver = cog_meta.get("driver")
    raster_asset.ingested_at = datetime.now(timezone.utc)
    raster_asset.set_crs(cog_meta)
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
    # Recomputed, not carried over: replacing a single-band float elevation
    # raster with an RGB orthophoto has to stop rendering as terrain.
    raster_asset.is_dem = cog_meta.get("is_dem_candidate", False)

    new_version = dataset.current_version + 1
    dataset.current_version = new_version
    dataset.srid = cog_meta.get("epsg")
    # `srid` is what the dataset serves (the converted COG's); `original_srid`
    # is the SRID the upload declared, which an srid_override must not
    # replace, since it is the only record of what arrived.
    dataset.original_srid = source_meta.get("epsg")
    dataset.source_filename = source_filename
    dataset.source_format = "geotiff"
    # The dataset is the COG and the upload a transient input, so the origin
    # restamps to the new file with no remote URI to point at.
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


class ArchiveNotDurableError(Exception):
    """A lossy conversion whose original could not be archived durably.

    The durable archive is a precondition of a lossy publish: the swap's
    success licenses deleting the staged source, so the samples the COG
    can't carry must already be somewhere durable. Left in job staging, the
    only faithful source could be removed by the retention purge once a
    later job supersedes it.
    """


ARCHIVED_ORIGINAL_KEY_PREFIX = "archived_original:"

# 128 bits. The truncated hash is the archive's identity, so its width is a
# security boundary: a deliberate collision at 12 hex chars is a ~2^24
# birthday search (minutes on a laptop). A colliding later archive overwrites
# the earlier object's only faithful original, the upsert collapses both into
# one row, and a failed later swap leaves the live raster with its retained
# source destroyed. At 32 chars the birthday bound is 2^64.
#
# One constant for both derivations. The asset-key column is String(50) and
# the prefix is 18 characters, so 18 + 32 lands exactly on the limit. The
# key's CHECK constraint matches on the prefix, so the width needs no
# migration.
ARCHIVE_HASH_CHARS = 32


def archived_original_asset_key(source_sha256: str) -> str:
    """The ``dataset_assets`` key for one kept original.

    Per archive, not per dataset: one constant key would count only the
    newest original and leave superseded ones uncounted against
    ``MAX_STORAGE_BYTES_PER_USER``. Keying on the content hash the object key
    uses lets the unique constraint deduplicate identical re-uploads.
    """
    return f"{ARCHIVED_ORIGINAL_KEY_PREFIX}{source_sha256[:ARCHIVE_HASH_CHARS]}"


def archived_original_uri(dataset_id, *, source_sha256: str) -> str:
    """The logical key a kept original lives at, derived from content alone.

    The counted row is keyed on content (``archived_original:<hash>``), so a
    filename or extension in the object key would let byte-identical uploads
    under two names (or as ``.tif`` and ``.tiff``) produce one row and two
    objects: the reservation would charge nothing, the upsert would repoint
    the row at the newer object, and the older one would be orphaned and
    uncounted, letting storage grow past the cap. The uploaded name rides on
    the counted row's description, where no equality depends on it.
    """
    return f"originals/{dataset_id}/{source_sha256[:ARCHIVE_HASH_CHARS]}"


async def archive_lossy_original(
    session,
    *,
    job,
    dataset_id,
    file_path: str,
    source_sha256: str,
    filename: str | None,
    log_message: str,
    needed: bool,
    written_storage_keys: list[str] | None = None,
) -> tuple[bool, str | None, int, str | None]:
    """Keep the pre-conversion upload, and report everything the caller needs.

    Returns ``(archived, logical_key, size_bytes, new_physical_key)``.

    - ``archived`` gates the caller's deletes: the staged upload may only go
      once a durable copy exists.
    - ``logical_key`` and ``size_bytes`` feed the counted asset row and the
      quota reservation.
    - ``new_physical_key`` is non-None only when this attempt created the
      object, and is what may join the failure-reap set.

    ``needed`` is False when the COG preserved the source; every return
    value is then empty. ``filename`` is not part of the key (see
    ``archived_original_uri``).

    The key is content-derived, so a failed attempt can archive bytes
    identical to an archive an earlier successful replace already wrote.
    Reaping that key on failure would delete a good archive of the raster
    still live, so the existence check runs before the write and only a new
    object joins the written set.
    """
    import os

    from app.platform.storage import get_storage
    from app.platform.storage.titiler_url import resolve_current_storage_key
    from app.processing.ingest.tasks_staging import _archive_original_file

    if not needed:
        return False, None, 0, None

    logical_key = archived_original_uri(dataset_id, source_sha256=source_sha256)
    physical_key = resolve_current_storage_key(logical_key)
    # An indeterminate probe must never make a pre-existing archive eligible
    # for failure cleanup: a later swap failure would delete an earlier
    # successful replacement's archive, the last faithful original of a
    # raster still served. So `existed` stays None when the store can't say,
    # and the write proceeds (same bytes over the same content-derived key is
    # idempotent) without the key joining the reap set. At worst a new archive
    # from a failed attempt leaks one bounded object until the dataset is
    # deleted; a leak costs storage, a wrong delete costs the only lossless
    # copy.
    #
    # Retain-in-place (skip the archive, keep the staged upload) is rejected:
    # the retention purge can remove a copy in `staging/`, so a probe blip
    # would downgrade a permanent guarantee to a windowed one.
    existed: bool | None
    try:
        existed = await get_storage().exists(physical_key)
    except Exception:  # broad: an unreadable store must not claim prior state
        logger.warning(
            "archive_precheck_indeterminate",
            dataset_id=str(dataset_id),
            key=logical_key,
        )
        existed = None

    # An indeterminate probe proceeds, since the write is the evidence. A
    # failed write proves the durable copy doesn't exist, so it refuses the
    # publish below.
    #
    # Ownership is registered by intent, before the write.
    # `LocalStorageProvider.put` drains its thread before re-raising
    # `CancelledError` (a BaseException), so a cancelled write can have
    # completed on disk while nothing below runs, leaving an `originals/`
    # object with no quota row. Reaping a key the write never created is a
    # no-op. A probe that said True, or couldn't answer, never registers, so
    # a pre-existing archive stays out of this attempt's cleanup.
    if existed is False and written_storage_keys is not None:
        written_storage_keys.append(physical_key)

    archived = await _archive_original_file(
        session,
        job=job,
        dataset_id=dataset_id,
        file_path=file_path,
        log_message=log_message,
        commit=False,
        # Just the hash: `_archive_original_file` rebuilds
        # `originals/<dataset_id>/<name>`, so the logical key's basename
        # reproduces exactly that key.
        archive_name=logical_key.rsplit("/", 1)[-1],
    )
    if not archived:
        raise ArchiveNotDurableError(
            "Refusing to publish a lossy conversion whose original could not "
            "be durably archived. The dataset keeps its previous raster and "
            "the uploaded file is retained with the failed job; retry once "
            "object storage is healthy."
        )
    return (
        True,
        logical_key,
        os.path.getsize(file_path),
        # Only a probe that said "absent" licenses reaping this key on failure.
        physical_key if existed is False else None,
    )


async def upsert_archived_original_row(
    session,
    *,
    dataset_id,
    logical_key: str | None,
    asset_key: str | None,
    size_bytes: int,
    source_filename: str | None = None,
) -> None:
    """Give the kept original a counted row so storage quota can see it.

    ``originals/`` persists and usage sums ``dataset_assets``, so without a
    row repeated distinct lossy replacements would exhaust a user's byte cap
    unchecked. The row uses the existing sum rather than a second ledger,
    and ``delete_dataset`` clears it along with the object prefix.

    The key is internal: ``app.platform.assets.keys`` keeps it out of STAC
    responses, since the kept original is the higher-fidelity copy the
    operator chose not to serve. There is one row per kept original, not
    per dataset, so superseded originals stay counted.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.platform.extensions import get_catalog_port

    # No key means the conversion preserved the source and nothing was kept.
    if logical_key is None or asset_key is None:
        return

    DatasetAsset = get_catalog_port().dataset_asset_orm_class()
    row = {
        "dataset_id": dataset_id,
        "key": asset_key,
        "href": logical_key,
        "media_type": "image/tiff",
        "title": "Pre-conversion original",
        # For an operator reading the table: the object key is pure content,
        # and `app.platform.assets.keys` keeps this row out of responses.
        "description": source_filename,
        "roles": ["archive"],
        "size_bytes": size_bytes,
    }
    stmt = pg_insert(DatasetAsset).values(**row)
    await session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_dataset_assets_key",
            set_={k: stmt.excluded[k] for k in row if k not in ("dataset_id", "key")},
        )
    )


async def reserve_replacement_bytes(
    session,
    *,
    dataset_id: uuid.UUID,
    owner_id: uuid.UUID | None,
    new_size: int,
    archived_bytes: int = 0,
    archived_asset_key: str | None = None,
    credit_superseded: bool = True,
) -> int:
    """Reserve the replacement's net byte increase under the owner's quota lock.

    Returns the bytes the superseded ``data`` row counts. ``reserve_storage_bytes``
    adds its argument to a live recount that still includes that row, so
    crediting it asks whether the post-swap total fits. This must run before
    ``_upsert_managed_asset_rows``, or the new size would count twice. With
    ``credit_superseded`` False the superseded bytes stay charged, for a COG
    that is kept after the swap.

    The credit comes from the ``dataset_assets`` row rather than the
    ``RasterAsset``, because that row is what the quota sums: a STAC-imported
    dataset has an asset carrying bytes and no counted row. A credited
    replacement that shrinks reserves nothing, since usage is a live sum.

    ``owner_id`` is None for an ownerless dataset and handed to
    ``reserve_storage_bytes`` unexamined, so this seam and the request-time
    door reach the same answer. ``app.modules.quota.service`` states the
    shared policy.
    """
    from sqlalchemy import text

    from app.modules.quota.service import reserve_storage_bytes

    # Only the superseded `data` row is credited. Archives persist and stay
    # billed; crediting them would let each lossy replace reserve roughly
    # nothing while adding another permanent object.
    counted_data = await session.scalar(
        text(
            "SELECT COALESCE(SUM(size_bytes), 0)::bigint "
            "FROM catalog.dataset_assets "
            "WHERE dataset_id = :dataset_id AND key = 'data'"
        ),
        {"dataset_id": dataset_id},
    )
    # Archive bytes this attempt adds: the new original minus what a row under
    # the same key already counts. Keyed off the row, not the object-exists
    # check, because the row is what the quota sums (an object archived
    # before counted rows existed has none). An identical re-upload adds zero.
    existing_archive = 0
    if archived_asset_key is not None:
        existing_archive = int(
            await session.scalar(
                text(
                    "SELECT COALESCE(SUM(size_bytes), 0)::bigint "
                    "FROM catalog.dataset_assets "
                    "WHERE dataset_id = :dataset_id AND key = :key"
                ),
                {"dataset_id": dataset_id, "key": archived_asset_key},
            )
            or 0
        )
    counted_data = int(counted_data or 0)
    credit = counted_data if credit_superseded else 0
    delta = (new_size - credit) + (archived_bytes - existing_archive)
    if delta > 0:
        await reserve_storage_bytes(session, owner_id, delta)
    return counted_data


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

    Upserts, because a STAC-imported raster has no asset rows (its import
    writes the dataset and raster asset only), and plain UPDATEs would match
    nothing and leave it advertising no data asset or quicklooks. The
    ``dataset_assets`` rows come from ``_build_dataset_asset_rows``, as on
    first ingest.

    ``record_distributions`` is delete-then-insert rather than ON CONFLICT
    because its unique constraint includes ``url``, which the replacement
    changes, so a conflict target could never match the row being replaced.
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


def _prior_asset_keys_to_reap(
    *,
    asset_uri: str | None,
    quicklook_256_uri: str | None,
    quicklook_512_uri: str | None,
) -> list[str]:
    """Resolve the superseded objects, in the same physical form as the puts.

    Catalog rows hold logical keys and storage holds tenant-prefixed ones, so
    the two lists the caller compares must both be physical or a same-key
    replace would reap the object it just wrote.
    """
    return [
        resolve_current_storage_key(key)
        for key in (asset_uri, quicklook_256_uri, quicklook_512_uri)
        if key
    ]
