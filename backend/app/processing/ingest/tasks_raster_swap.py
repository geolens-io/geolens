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


class ArchiveNotDurableError(Exception):
    """A lossy conversion whose original could not be archived durably.

    fix(#1290 review): the durable archive is a PRECONDITION of a lossy
    publish, not a best-effort side effect. The swap's success is what licenses
    deleting the staged source, so if the samples the COG cannot carry are not
    yet somewhere durable, the publish has not earned its commit.

    Before this, an archive-write failure returned quietly and the job
    succeeded — leaving the only faithful source in job staging, where the
    retention purge is entitled to remove it once a later job supersedes it. A
    transient storage error silently downgraded a dataset-lifetime guarantee to
    a windowed one, which is precisely the trade this path rejected in round 7
    when it declined retain-in-place for the same reason.
    """


ARCHIVED_ORIGINAL_KEY_PREFIX = "archived_original:"

# fix(#1290 review): 128 bits, not 48. Round 8 made the truncated hash BE the
# archive's identity, which is exactly what puts the truncation width on the
# security boundary. An accidental same-dataset collision at 12 hex chars is
# negligible; a DELIBERATE one is a ~2^24 birthday search — minutes on a laptop
# — and it buys the attacker the invariant this key exists to protect: the
# later archive overwrites the earlier object's only faithful original, the
# upsert collapses both into one row, and a failed later swap leaves the live
# raster with its retained source already destroyed. At 32 chars the birthday
# bound is 2^64, which is not a laptop.
#
# ONE constant for both derivations. Two widths would be two identities again,
# which is the thing round 8 removed. The asset-key column is String(50) and
# the prefix is 18 characters, so 18 + 32 lands exactly on the limit — verified
# against the model and 0001_baseline. 0038's CHECK matches on the prefix, so
# it is width-agnostic and no migration is involved.
ARCHIVE_HASH_CHARS = 32


def archived_original_asset_key(source_sha256: str) -> str:
    """The ``dataset_assets`` key for ONE kept original.

    fix(#1290 review): per-archive, not per-dataset. A single constant key
    counted only the newest original and left every superseded one accumulating
    uncounted — the exact scenario ``MAX_STORAGE_BYTES_PER_USER`` exists to
    bound. Keying on the same content hash the object key uses — same width, one
    constant — means the unique constraint deduplicates identical re-uploads
    for free.
    """
    return f"{ARCHIVED_ORIGINAL_KEY_PREFIX}{source_sha256[:ARCHIVE_HASH_CHARS]}"


def archived_original_uri(dataset_id, *, source_sha256: str) -> str:
    """The logical key a kept original lives at. Content, and nothing else.

    fix(#1290 review): the key used to carry the uploaded filename too, which
    split the archive's identity in half. The counted row is keyed on content
    alone (``archived_original:<hash>``), so byte-identical uploads under two
    different names produced ONE row and TWO objects — the reservation credited
    the existing row and charged nothing, the upsert repointed it at the newer
    object, and the older one was left orphaned and uncounted. Repeat with a
    third name and storage grows without limit past the cap.

    One identity, derived solely from content, makes that unreachable rather
    than merely unlikely: same bytes means same key means an idempotent
    rewrite and a zero delta, whatever the file was called.

    No extension either, deliberately. The same bytes uploaded as ``.tif`` and
    as ``.tiff`` would otherwise be two objects again — the identical bug with
    a smaller blast radius, which is the worst kind to leave in. The
    human-readable name is not lost; it rides on the counted row's description,
    where an operator can read it and no equality depends on it.
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
    - ``new_physical_key`` is non-None only when this attempt CREATED the
      object, and is what may join the failure-reap set.

    ``needed`` is False when the COG preserved the source, in which case there
    is nothing to keep and every return value is empty. It lives here rather
    than at the call site so both raster tails ask one question once.

    ``filename`` no longer participates in the key (fix(#1290 review) — see
    ``archived_original_uri``). It survives as the operator-facing label on the
    counted row, which is the only place a human-readable name belongs once
    identity is content.

    fix(#1290 review), the trap: the key is content-derived, so a failed
    attempt can archive bytes identical to an archive an EARLIER successful
    replace already wrote — the same key. Adding it to the failure-reap set
    unconditionally would then delete a good archive belonging to the raster
    that is still live. So the existence check runs BEFORE the write, and only
    a genuinely new object joins the written set. An object that was already
    there is prior state and this attempt has no claim on it.
    """
    import os

    from app.platform.storage import get_storage
    from app.platform.storage.titiler_url import resolve_current_storage_key
    from app.processing.ingest.tasks_common import _archive_original_file

    if not needed:
        return False, None, 0, None

    logical_key = archived_original_uri(dataset_id, source_sha256=source_sha256)
    physical_key = resolve_current_storage_key(logical_key)
    # fix(#1290 review): an INDETERMINATE probe must never make a pre-existing
    # archive eligible for failure cleanup. Treating a transient `exists()`
    # error as "did not exist" put the key into `written_storage_keys`, and a
    # later swap failure then deleted an archive that belonged to an EARLIER
    # SUCCESSFUL replacement — the last faithful original of a raster still
    # being served.
    #
    # So the two answers are separated. `existed` stays None when the store
    # could not say, and the write proceeds regardless: the key is
    # content-derived, so writing the same bytes over the same key is
    # effectively idempotent whether or not something was there. What does NOT
    # happen is the key joining the reap set. The worst case is that a
    # genuinely-new archive from a failed attempt leaks one bounded object,
    # reclaimed when the dataset is deleted. That is the correct side to err
    # on: a leaked object costs storage, a wrong delete costs the only
    # lossless copy of someone's data.
    #
    # Considered and rejected: falling back to retain-in-place (skip the
    # archive, keep the staged upload). It trades a bounded leak for a
    # different unbounded one — the staged copy then survives in `staging/`,
    # where the retention purge is entitled to remove it, so a probe blip
    # would silently downgrade a permanent guarantee to a windowed one.
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

    # fix(#1290 review): note the deliberate asymmetry with the probe above.
    # An INDETERMINATE probe proceeds — the write is the evidence, and refusing
    # to publish because a store could not answer a question would fail work
    # that is fine. A failed WRITE is different in kind: it is proof the
    # durable copy does not exist, and publishing anyway is what silently voids
    # the retention promise.
    # fix(#1290 review): ownership is registered by INTENT, before the write,
    # not by whether the write returned. `LocalStorageProvider.put` drains its
    # worker thread before re-raising `CancelledError`, so a cancelled write
    # can have COMPLETED on disk — and `CancelledError` is a BaseException, so
    # nothing below runs, the key is never reported, and a finished
    # `originals/` object survives with no quota row. Repeat that and storage
    # grows uncounted.
    #
    # Registering first is safe in the other direction: reaping a key the write
    # never created is an idempotent no-op. This is `written_storage_keys`
    # recording what the code SET OUT to do rather than what it SAW happen —
    # the same correction this review has made repeatedly.
    #
    # Confined to the `existed is False` branch on purpose. Round 7's rule is
    # unchanged: a probe that said True, or could not answer, never registers,
    # so a pre-existing archive stays untouchable by this attempt's cleanup.
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
        # `originals/<dataset_id>/<name>`, so handing it the basename of the
        # logical key reproduces exactly that key.
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
        # Only a probe that AFFIRMATIVELY said "absent" licenses reaping this
        # key on failure. `None` — the store could not answer — declines, the
        # same as `True`.
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

    fix(#1290 review). ``originals/`` accumulated permanently and was counted
    by nothing — usage sums ``dataset_assets`` — so repeated distinct lossy
    replacements exhausted a user's byte cap with no check refusing them. A row
    makes the EXISTING sum authoritative instead of standing up a second ledger
    that would drift, and it is cleaned by the same ``delete_dataset`` that
    already clears the object prefix.

    The key is internal: ``app.platform.assets.keys`` keeps it
    out of STAC responses, because the kept original is the higher-fidelity copy
    the operator chose not to serve.

    One row per KEPT ORIGINAL, not per dataset. Counting only the newest would
    leave superseded originals accumulating uncounted, which is precisely the
    unbounded growth the cap exists to prevent; an owner's release valve is
    deleting the dataset (which clears both the rows and the object prefix) or
    removing individual objects themselves, not the accounting looking away.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.platform.extensions import get_catalog_port

    # No key means the conversion preserved the source and nothing was kept.
    # Handled here so the caller has one unconditional call rather than a
    # branch it has to remember to write.
    if logical_key is None or asset_key is None:
        return

    DatasetAsset = get_catalog_port().dataset_asset_orm_class()
    row = {
        "dataset_id": dataset_id,
        "key": asset_key,
        "href": logical_key,
        "media_type": "image/tiff",
        "title": "Pre-conversion original",
        # fix(#1290 review): the uploaded name lives here now that the object
        # key is pure content. Internal row — `app.platform.assets.keys` keeps
        # it out of every response — so this is for the operator reading the
        # table, not for a client.
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

    ``owner_id`` is None for an ownerless dataset and is handed to
    ``reserve_storage_bytes`` unexamined, which is what makes this seam and the
    request-time door reach the same answer through the same code. The policy
    those two share, and why it is an exemption rather than a bug, is stated
    once in ``app.modules.quota.service``'s module docstring (#1293).
    """
    from sqlalchemy import text

    from app.modules.quota.service import reserve_storage_bytes

    # fix(#1290 review): the credit is the SUPERSEDED `data` row and nothing
    # else. Crediting every archive too was far too generous: archives persist
    # and stay billed, so subtracting them let each successive lossy replace
    # reserve roughly nothing while adding another permanent object — the exact
    # unbounded growth the counted rows were introduced to stop.
    counted_data = await session.scalar(
        text(
            "SELECT COALESCE(SUM(size_bytes), 0)::bigint "
            "FROM catalog.dataset_assets "
            "WHERE dataset_id = :dataset_id AND key = 'data'"
        ),
        {"dataset_id": dataset_id},
    )
    # What this attempt ADDS in archive bytes: the new original, minus whatever
    # a row under the same key already contributes. Keyed off the ROW rather
    # than the object-exists check, because the row is what the quota sums —
    # they agree in every normal case, and where they differ (an object
    # archived before the counted rows existed) the row is the honest answer.
    # An identical re-upload falls out with no arithmetic of its own: same key,
    # same size, contributes zero.
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
    delta = (new_size - int(counted_data or 0)) + (archived_bytes - existing_archive)
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
    ``_resolve_raster_meta`` cache, whose entries carry the OLD asset_uri.
    fix(#1329): that cache is now keyed on the request's ``v``, so the
    ``tile_cache_version`` bump this swap already made in the write transaction
    IS the invalidation — the first tile request carrying the new version misses
    in every API process and reads the new pointer, with no separate
    coordination channel (``regenerate_vrt`` and the STAC moved-asset refresh
    bump the same counter and get the same effect). What is left is requests
    still carrying the OLD ``v`` — a tab that has not refetched its tile URL:
    those keep the pre-swap asset_uri until the entry expires
    (``_RASTER_META_CACHE_TTL``, 60s), so their tiles can fail for that bounded,
    self-healing window. The bumped ``tile_cache_version`` also changes the tile
    URL, so browser and CDN caches roll over immediately.
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


async def run_post_swap_followups_best_effort(
    *,
    dataset_uuid: uuid.UUID,
    dataset_cls: type,
    prior_physical_keys: list[str],
    written_storage_keys: list[str],
    job_id: str,
    dataset_id: str,
) -> None:
    """``_run_post_swap_followups`` with the caller's fence built in.

    fix(#1778 codex r2): the replace tail reaches this from two places now —
    the ordinary success path and the stand-down a lost commit acknowledgement
    takes — and both need the identical rule: the swap is durable, so a cache
    purge that cannot reach Valkey, a reap that cannot reach storage or an
    embedding defer against a busy queue are things to log and move on from,
    never reasons to fail a job whose outcome is already committed and already
    reported as succeeded in the run row. One home for that rule rather than
    two copies of the try/except, so the two paths cannot drift.

    The reap inside is what makes this worth running on the stand-down path at
    all: it is the ONLY deletion of the superseded COG and quicklooks, and the
    committed pointer already names the new keys, so skipping it strands
    objects no row references and no quota counts.
    """
    try:
        await _run_post_swap_followups(
            dataset_uuid=dataset_uuid,
            dataset_cls=dataset_cls,
            prior_physical_keys=prior_physical_keys,
            written_storage_keys=written_storage_keys,
            job_id=job_id,
        )
    except Exception:  # broad: nothing after the commit may fail the job
        structlog.get_logger().warning(
            "raster_replace_post_swap_followup_failed",
            job_id=job_id,
            dataset_id=dataset_id,
            exc_info=True,
        )


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
