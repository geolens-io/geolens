"""Shared building blocks for the raster ingest and raster replace tasks.

fix(#1290): a pure extraction from ``tasks_raster`` (crossed the 1000-line
ratchet threshold) — every function moved verbatim, and nothing here is a
Procrastinate task. What both raster tails need: the manifest-VRT
discriminators, the strict-COG gate, the row builders for a freshly
published raster, the managed-key resolver, and the orphan reaper.
"""

import asyncio
import os
import uuid
from datetime import datetime, timezone
from collections.abc import Iterable
from typing import Any

import structlog
from sqlalchemy import select

from app.platform.dataset_origin import set_dataset_origin
from app.processing.raster.cog import check_cog_compliance, extract_raster_metadata
from app.platform.storage.titiler_url import resolve_current_storage_key


# Human-readable label per uploaded extension, used only to phrase the
# friendly "could not open" message below.
_RASTER_FORMAT_LABELS: dict[str, str] = {
    ".tif": "GeoTIFF (.tif)",
    ".tiff": "GeoTIFF (.tiff)",
    ".vrt": "VRT (.vrt)",
}


def _friendly_raster_open_failure_message(original_filename: "str | None") -> str:
    """User-facing text for a raster source ``rasterio.open`` open-time failure.

    Built from ``original_filename`` alone — never the staging path or raw
    rasterio message — so it can't leak the `/app/staging/<uuid>_...` path
    rasterio/GDAL echoes back on any open-time failure (unrecognized format,
    corrupt/truncated IFD, missing file, permission error all read the same
    to the uploader: "GeoLens could not open this as a raster").
    """
    name = os.path.basename(original_filename) if original_filename else None
    suffix = os.path.splitext(name)[1].lower() if name else ""
    format_label = _RASTER_FORMAT_LABELS.get(suffix, "raster")
    if name:
        return (
            f"Could not open '{name}' as a raster dataset — the file may be "
            f"corrupt, incomplete, or not a valid {format_label} file."
        )
    return (
        "Could not open the uploaded file as a raster dataset — it may be "
        "corrupt, incomplete, or not a valid raster file."
    )


def extract_source_raster_metadata(
    file_path: str, *, original_filename: "str | None" = None
) -> dict:
    """``extract_raster_metadata``, translating an open-time rasterio failure.

    fix(#1661): both raster ingest tails call this on the freshly-staged
    SOURCE upload. ``extract_raster_metadata`` opens the file with a single
    ``rasterio.open`` call and reads everything else off the resulting
    dataset, so ANY ``RasterioIOError`` it raises means "rasterio could not
    open this file" — unrecognized format, corrupt/truncated IFD, missing
    file, or permission error alike. (A narrower pattern match on just the
    "not recognized" text missed the corrupt-IFD shape, which also quotes
    the staging path and is equally reachable: a .tif with a valid magic
    header but a corrupt IFD passes upload-time content-sniffing same as
    any other .tif.)

    This used to land the raw rasterio message, staging path included, in
    ``IngestJob.error_message`` verbatim. The full message still reaches
    structured logs here, the one place that sees it; a failure from
    anything OTHER than the open call itself (e.g. EXIF/tag parsing further
    into ``extract_raster_metadata``) is not a ``RasterioIOError`` and keeps
    its real message. Callers reading their own just-produced COG (no
    upload filename to leak) don't need this wrapper.
    """
    import rasterio

    try:
        return extract_raster_metadata(file_path)
    except rasterio.errors.RasterioIOError as exc:
        message = str(exc)
        structlog.get_logger().error(
            "rasterio could not open raster source",
            error=message,
            original_filename=original_filename,
        )
        raise ValueError(
            _friendly_raster_open_failure_message(original_filename)
        ) from exc


def _is_manifest_vrt_job(job: Any) -> bool:
    """Return true when a raster queue job represents a manifest VRT source."""
    metadata = job.user_metadata or {}
    source_filename = (job.source_filename or "").lower()
    return metadata.get("manifest_source_type") == "vrt" or source_filename.endswith(
        ".vrt"
    )


def _reject_raw_vrt_job(source_filename: str | None) -> None:
    """Worker-side backstop for jobs created outside current HTTP routes."""
    if (source_filename or "").lower().endswith(".vrt"):
        raise ValueError(
            "Standalone VRT ingest is not supported; managed VRTs must be "
            "created from catalog-tracked raster sources"
        )


async def _enforce_strict_cog(
    file_path: str,
    *,
    expected_compression: str | None,
    is_manifest_vrt: bool,
    strict_cog: bool,
) -> None:
    """Strict-mode COG gate for ING-07 / P2-09.

    When the user opted in via ``RasterCommitRequest.strict_cog=True``,
    rejects non-COG TIFFs here instead of silently converting via
    ``check_and_prepare_cog``. Manifest-VRT jobs are excluded (VRTs are
    XML, not TIFFs — the compliance check would fail for unrelated
    reasons). Raises ``ValueError`` with the compliance reason;
    ``ingest_raster``'s outer ``except Exception`` handler writes it to the
    job via ``_job_phase_session("error_write")``.
    """
    import asyncio

    if not strict_cog or is_manifest_vrt:
        return

    compliant, reason = await asyncio.to_thread(
        check_cog_compliance, file_path, expected_compression=expected_compression
    )
    if not compliant:
        raise ValueError(
            f"Strict-COG mode rejected upload: {reason}. "
            "Disable strict_cog or upload a COG-compliant TIFF."
        )


async def create_raster_dataset(
    session,
    *,
    meta: dict,
    source_sha256: str,
    asset_sha256: str,
    cog_status: str,
    cog_size: int,
    source_filename: str | None,
    created_by: uuid.UUID,
    title: str,
    summary: str | None,
    visibility: str,
    record_status: str = "published",
    original_srid: int | None = None,
    dataset_id: uuid.UUID | None = None,
) -> tuple:
    """Create Record + Dataset + RasterAsset records for a raster ingest.

    fix(#1290): ``meta`` describes the CONVERTED COG — the file this
    dataset will serve. ``original_srid`` is the one value that must
    describe the upload instead, so the caller reads it off the source and
    passes it in.

    fix(#1778): ``dataset_id`` lets the caller decide the id BEFORE this
    transaction opens, since the object keys the tail is about to write
    embed it and naming them on the durable job row needs the id to exist
    while that row is still writable. Default None keeps every other
    caller on the database-generated id.

    Returns (record, dataset, raster_asset).
    """
    from sqlalchemy import func

    from app.platform.extensions import get_processing_port
    from app.processing.raster.models import RasterAsset

    _port = get_processing_port()
    Dataset = _port.get_dataset_orm_class()
    Record = _port.get_record_orm_class()

    # fix(#302): authoritative count-cap check in the same transaction that
    # inserts the Record (the upload-time pre-check is not atomic).
    # fix(#430): same for the byte cap — recount under the per-user advisory
    # lock so concurrent raster uploads can't overshoot max_storage_bytes_per_user.
    from app.modules.quota.service import (
        reserve_dataset_slot,
        reserve_storage_bytes,
    )

    await reserve_dataset_slot(session, created_by)
    await reserve_storage_bytes(session, created_by, cog_size)

    # Mirrors the vector ingest path (`create_dataset_record` in
    # datasets/service.py), which commits directly to `published`. Without
    # this the raster stayed in `draft` and the anonymous public
    # tile-access check (`_resolve_raster_access` in tiles/router.py) 404'd
    # every raster tile fetch for anonymous users.
    record = Record(
        title=title,
        summary=summary,
        record_type="raster_dataset",
        visibility=visibility,
        record_status=record_status,
        # fix(#302): created_by was never set on raster records, leaving
        # them NULL and invisible to per-user quota count and owner checks.
        created_by=created_by,
        updated_by=created_by,
    )
    if meta.get("bbox_wkt"):
        record.spatial_extent = func.ST_GeomFromText(meta["bbox_wkt"], 4326)
    session.add(record)
    await session.flush()

    table_name = f"raster_{record.id.hex[:16]}"
    dataset = Dataset(
        **({"id": dataset_id} if dataset_id is not None else {}),
        record_id=record.id,
        table_name=table_name,
        source_format="geotiff",
        source_filename=source_filename,
        srid=meta.get("epsg"),
        # fix(#1290): the SRID the uploaded file declared, which under a
        # `srid_override` is not the one the COG carries — two fields, two
        # questions, same line the replace tail draws.
        original_srid=original_srid,
        # fix(#1218): every creation path stamps this (see create_dataset) or
        # post-migration rows report null while backfilled ones don't.
        # Python value, not func.now(): a SQL expression leaves the
        # attribute expired and the next read lazy-loads.
        last_refreshed_at=datetime.now(timezone.utc),
    )
    # feat(#1218): a raster dataset IS the COG; the pre-conversion upload is
    # transient, so the origin is the uploaded file with no remote URI to
    # point at (ADR-002 Decision 7).
    # fix(#1294): file_hash was missing here, unlike the replace tail's call
    # in tasks_raster_swap.py — both go through this same set_dataset_origin
    # authority, so passing the caller's already-computed source_sha256 is
    # the whole fix.
    set_dataset_origin(
        dataset, "upload", filename=source_filename, file_hash=source_sha256
    )
    session.add(dataset)
    await session.flush()

    nodata_val = meta.get("nodata")
    nodata_str = str(nodata_val) if nodata_val is not None else None

    raster_asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri="",  # updated after storage put
        sha256=asset_sha256,
        size_bytes=cog_size,
        driver=meta.get("driver"),
        storage_backend="local",
        ingested_at=datetime.now(timezone.utc),
        crs_wkt=meta.get("crs_wkt"),
        epsg=meta.get("epsg"),
        band_count=meta.get("band_count"),
        dtype=meta.get("dtype"),
        nodata=nodata_str,
        res_x=meta.get("res_x"),
        res_y=meta.get("res_y"),
        width=meta.get("width"),
        height=meta.get("height"),
        compression=meta.get("compression"),
        source_sha256=source_sha256,
        cog_status=cog_status,
        band_info=meta.get("band_info"),
        is_rotated=meta.get("is_rotated", False),
        is_dem=meta.get("is_dem_candidate", False),
    )
    session.add(raster_asset)
    await session.flush()

    return record, dataset, raster_asset


# Media types for the STAC-aligned dataset_assets rows (BUG-041).
_COG_MEDIA_TYPE = "image/tiff; application=geotiff; profile=cloud-optimized"
_VRT_MEDIA_TYPE = "application/x-vrt+xml"
_PNG_MEDIA_TYPE = "image/png"


def _build_dataset_asset_rows(
    *,
    dataset_id: uuid.UUID,
    cog_key: str,
    ql256_key: str,
    ql512_key: str,
    cog_size: int | None,
    is_manifest_vrt: bool,
) -> list[dict]:
    """Build STAC-aligned ``dataset_assets`` rows for a freshly ingested raster.

    BUG-041: ``dataset_assets`` is read by the search/STAC/OGC asset-output
    path but was never written by ingest, so STAC item assets were never
    advertised. Produces the rows using ``DatasetAsset``'s stable keys:

      - ``data`` / ``vrt``: the primary COG (or VRT) source
      - ``thumbnail``: 256px quicklook
      - ``overview``: 512px quicklook

    hrefs are storage-relative keys; ``resolve_asset_url`` turns them into
    presigned/public URLs at read time (or omits them on local storage per
    GAP-031).
    """
    primary_key = "vrt" if is_manifest_vrt else "data"
    primary_media = _VRT_MEDIA_TYPE if is_manifest_vrt else _COG_MEDIA_TYPE
    primary_title = (
        "GDAL Virtual Raster" if is_manifest_vrt else "Cloud-Optimized GeoTIFF"
    )

    rows: list[dict] = [
        {
            "dataset_id": dataset_id,
            "key": primary_key,
            "href": cog_key,
            "media_type": primary_media,
            "title": primary_title,
            "roles": ["data"],
            "size_bytes": cog_size,
        },
        {
            "dataset_id": dataset_id,
            "key": "thumbnail",
            "href": ql256_key,
            "media_type": _PNG_MEDIA_TYPE,
            "title": "Quicklook (256px)",
            "roles": ["thumbnail"],
        },
        {
            "dataset_id": dataset_id,
            "key": "overview",
            "href": ql512_key,
            "media_type": _PNG_MEDIA_TYPE,
            "title": "Quicklook (512px)",
            "roles": ["overview"],
        },
    ]
    return rows


def _resolve_managed_raster_storage_keys(
    cog_key: str,
    quicklook_256_key: str,
    quicklook_512_key: str,
) -> tuple[str, str, str]:
    """Resolve logical raster asset keys for the active tenant.

    The returned keys are provider-facing. Catalog ``asset_uri`` fields retain
    the logical inputs. Hosted workers fail closed when their tenant context
    is absent; single-tenant workers receive each input byte-for-byte.
    """
    return (
        resolve_current_storage_key(cog_key),
        resolve_current_storage_key(quicklook_256_key),
        resolve_current_storage_key(quicklook_512_key),
    )


async def _cleanup_orphaned_storage_keys(keys: list[str], *, job_id: str) -> None:
    """Best-effort delete storage keys written before a failed/rolled-back commit.

    GAP-017: raster ingest puts COG/quicklook bytes to storage BEFORE the
    terminal DB commit. If the commit (or a later step) fails, the dataset
    row rolls back and ``delete_dataset`` never runs, orphaning the bytes —
    this reaps exactly the keys that were written. Failures here are
    swallowed; cleanup must never mask the original ingest error.
    """
    from app.platform.storage import get_storage

    try:
        storage = get_storage()
    except Exception:  # broad: storage may be unavailable; nothing to clean then
        return
    for key in keys:
        try:
            await storage.delete(key)
        except Exception:  # broad: best-effort per-key cleanup, keep going
            structlog.get_logger().warning(
                "Failed to clean up orphaned raster asset",
                job_id=job_id,
                storage_key=key,
            )


async def publish_commit_landed(
    job_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID,
    *,
    job_id: str,
    task: str,
) -> bool:
    """Did the publishing commit durably land, despite the raise?

    fix(#1778): applies #1708's reasoning to the raster and VRT publish
    tails. A commit whose acknowledgement is lost — a dropped connection, or
    the ``asyncio.CancelledError`` a cancel delivers (a BaseException the
    tails' ``except Exception`` never sees but their ``finally`` still runs
    through) — may still have been applied by PostgreSQL. Each tail sets its
    "published" flag on the line after that await, so a lost ack left the
    flag false and the terminal cleanup deleted the exact object keys the
    committed row had just been pointed at: the objects survive in the
    bucket but nothing points at them, and every tile request, download and
    STAC asset 404s until an operator lists the prefix by hand.

    So decide by OBSERVATION, not the await's outcome: read the job row back
    on a FRESH session (the publishing session is mid-failure) and ask
    whether this attempt's terminal write is there. ``status == 'complete'``
    for this exact ``attempt_id`` is the shared signal, because every tail
    stamps it in the SAME transaction as the pointer swap — seeing it means
    the swap is durable, and no other attempt could have produced it since
    the attempt token is fresh per attempt and each task is ``retry=0``.

    A probe that itself fails returns True — standing down. The asymmetry is
    #1708's: standing down on a false positive leaves objects an operator or
    sweep can still remove, while proceeding on a false negative deletes the
    live raster.

    A caller that gets True stands DOWN, returning normally rather than
    re-raising into its failure handler — gating only the orphaned-key
    cleanup was not enough, because the handler still entered writes about a
    job that succeeded (``regenerate_vrt`` reloaded the now ``completed``
    ``VrtGeneration`` and stamped it ``failed``, which both ``get_vrt_status``
    and the stale-generation sweep then read as an unhealthy asset). Nothing
    is lost by returning: the terminal write is durable, and the only work
    skipped is the post-commit best-effort block those tails already treat
    as unfailable.

    The caller must NOT set ``final_status`` from this: that string also
    decides whether the uploader's staged original may be deleted, and
    standing down there would turn a probe failure into a second, worse
    deletion.
    """
    # fix(#909)-style late bind so tests' engine patching is honored.
    import app.core.db as db_module

    from app.platform.jobs.models import IngestJob

    try:
        async with db_module.async_session() as probe:
            status = (
                await probe.execute(
                    select(IngestJob.status).where(
                        IngestJob.id == job_uuid,
                        IngestJob.attempt_id == attempt_uuid,
                    )
                )
            ).scalar_one_or_none()
    except BaseException:
        structlog.get_logger().warning(
            "publish_commit_probe_failed", job_id=job_id, task=task
        )
        return True
    landed = status == "complete"
    if landed:
        structlog.get_logger().warning(
            "publish_commit_ack_lost_but_landed", job_id=job_id, task=task
        )
    return landed


def absorb_cancellation(exc: BaseException) -> None:
    """Clear the pending cancellation a stand-down is about to stop honouring.

    fix(#1778): a tail that observes its publish landed returns normally
    instead of re-raising, so on the cancel path it swallows the
    ``asyncio.CancelledError`` #1709's ``abort=True`` delivers. Suppressing
    a cancellation without saying so leaves ``Task.cancelling()`` above
    zero, which a structured-concurrency parent reads to decide whether its
    own body was cancelled. Every other exception type is left alone; a
    call outside a running task is a no-op.
    """
    if not isinstance(exc, asyncio.CancelledError):
        return
    task = asyncio.current_task()
    if task is not None:
        task.uncancel()


# fix(#1778): the `user_metadata` field a raster tail names its pre-commit
# object keys under. `written_storage_keys` is a local list, so a SIGKILL or
# OOM between the puts and the terminal `finally` reclaimed nothing:
# `base_key` embeds a dataset id that rolls back with the transaction, so no
# row, `delete_dataset` reap, or staging reconciler (`STAGING_PREFIX` is
# `staging/` only) could ever name the objects again. The VRT publish path
# already had an out-of-process owner for this class
# (`_stale_generation_storage_keys` in the job sweep); this field extends
# the same shape to `rasters/` and `originals/`.
def attempt_scoped_raster_base_key(
    dataset_id: uuid.UUID,
    attempt_id: uuid.UUID,
    asset_sha256: str,
) -> str:
    """The object prefix ONE replace attempt may write under.

    fix(#1778): the replace tail used to key on dataset id plus content hash
    alone, deterministic across attempts — re-running the same upload
    derives the same three keys, a collision the durable reaper can't
    survive. ``fail_stale_jobs``'s commit both settles the dead attempt and
    releases the dataset's active-run reservation, so a replacement can be
    admitted while post-commit cleanup is still running; the new attempt
    then writes the same keys the reaper is about to delete, and its own
    commit lands a ``RasterAsset`` pointing at bytes that are gone.

    Attempt fencing closes that structurally rather than by ordering — the
    same approach the VRT publish path takes with
    ``rasters/{id}/generations/{generation_id}/``: no two attempts can name
    the same object, so there's no window to get the ordering wrong in.
    Same convention as ``attempt_scoped_staging_table`` for the vector
    tails' staging tables.

    The content hash stays in the key: it's what invariant 10 rests on (a
    replacement cannot overwrite the live asset in place) and keeps the key
    content-addressed, with the attempt segment making it attempt-addressed
    too.

    The first-ingest tail needs no equivalent: its keys sit under a dataset
    id generated inside the task, so a retry produces a different one.
    """
    return f"rasters/{dataset_id}/attempts/{attempt_id}/{asset_sha256}"


UNPUBLISHED_STORAGE_KEYS_FIELD = "unpublished_storage_keys"


async def record_unpublished_storage_keys(
    job_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID,
    *,
    keys: list[str],
    already_published: "Iterable[str]",
    attempt_scope: str,
    job_id: str,
    task: str,
) -> bool:
    """Persist the object keys this attempt is ABOUT to write, best effort.

    Returns whether the caller may proceed to write those objects. ``False``
    means this attempt is DEFINITIVELY fenced out: the ``(job_uuid,
    attempt_uuid)`` pair matched no row — the stale sweep failed the row on
    a heartbeat timeout while this worker was merely paused (GC pause, slow
    syscall) rather than dead, and a retry has since minted a new attempt on
    the same job. Every other fenced job-row write in this codebase checks
    its match (``update_ingest_job_for_attempt`` in ``heartbeat.py`` returns
    ``bool(rowcount)`` and every caller branches on a miss); this one used
    to be the exception, silently committing nothing and letting the caller
    write objects a dead attempt's row would never record — the #1778 leak
    class reopened at the one recorder that didn't check its own fence.

    An unreachable database or other transient failure is a DIFFERENT case
    and still returns ``True``: nothing there proves this attempt is gone,
    and refusing over it would trade a possible leak for a certain one.
    Only a confirmed zero-row match is a confirmed fence miss.

    fix(#1778): one JSONB write, committed on its own session before the
    publishing transaction opens, so the keys are nameable after the
    process is gone. Logical keys (never tenant-resolved) so the sweep
    resolves them in its own tenant context, as it already does for
    ``_staged_presigned_keys``.

    ``already_published`` — what the LIVE asset names — is subtracted here
    rather than at either call site. A replace whose conversion reproduces
    the published COG byte for byte derives the same ``asset_sha256``, so
    the three keys this attempt intends ARE the three keys currently
    serving; a crash any time after this write would hand the stale-job
    reaper permission to delete the live COG and both quicklooks otherwise.
    In-process failure cleanup has always excluded ``prior_physical_keys``;
    the durable record needs the same exclusion, and doing it here rather
    than at call sites means a future writer gets it for free. The reaper
    carries the other half: it refuses to delete a key a live row still
    references, whatever the job row says.

    ``attempt_scope`` is a token unique to this attempt, and a key that
    doesn't contain it is DROPPED rather than recorded — the rule the
    recorded set must satisfy for the reaper to be safe at all, since the
    reaper deletes on "the attempt that wrote this is gone", and a key two
    attempts can both name is one it can delete out from under the live
    one. Checking it here, the single point where keys become durable,
    stops a future writer from recording a shared key and finding out from
    a support ticket. The replace tail's token is its attempt id, carried
    through ``attempt_scoped_raster_base_key``; the first-ingest tail's is
    the dataset id it generates per attempt.

    Ordering is the whole mechanism, and narrow: this must run BEFORE the
    phase-2 session takes the ``ingest_jobs`` row lock (phase 2's first
    statements dirty ``current_step``/``progress``), or a second session
    updating that row would block on phase 2 while phase 2 waits on this
    call — so it lives beside the pre-phase-2 progress write, never inside
    phase 2.

    A JSONB merge rather than assignment, so it can't clobber a field a
    later write adds, fenced on ``attempt_id`` so a retry's keys never land
    on another attempt's row. A transient failure is swallowed: this buys
    reclaimability for a crash that may not happen, and refusing the ingest
    over an error that says nothing about the fence would trade a possible
    leak for a certain failure.
    """
    from sqlalchemy import bindparam, case, func, text, update
    from sqlalchemy.dialects.postgresql import JSONB

    import app.core.db as db_module

    from app.platform.jobs.models import IngestJob

    published = set(already_published)
    candidates = [key for key in keys if key not in published]
    unpublished = [key for key in candidates if attempt_scope in key]
    if len(unpublished) < len(candidates):
        structlog.get_logger().warning(
            "unpublished_storage_key_not_attempt_scoped", job_id=job_id, task=task
        )
    if not unpublished:
        return True
    # fix(#1778): APPEND to what the row already names, never replace it.
    # `/jobs/{id}/retry` preserves `user_metadata`, so a retried ingest
    # reaches this with the previous attempt's keys still on the row; a
    # merge that set the field to this attempt's keys alone would drop
    # them, orphaning an earlier attempt's objects if its own best-effort
    # delete had also failed.
    #
    # A flat list each attempt extends, not a map keyed by attempt — no
    # reader needs to know which attempt wrote a key, only "is this key
    # still owed a reap", so the shape stays simple and a row written
    # before this commit still reaps.
    #
    # The CASE keeps it total: `jsonb || jsonb` concatenates two arrays but
    # would fold an array into a non-array, so anything that isn't an array
    # is replaced rather than appended to.
    _existing_keys = func.coalesce(
        IngestJob.user_metadata[UNPUBLISHED_STORAGE_KEYS_FIELD],
        text("'[]'::jsonb"),
    )
    _new_keys = bindparam("unpublished_patch", value=unpublished, type_=JSONB)
    _accumulated_keys = case(
        (
            func.jsonb_typeof(_existing_keys) == "array",
            _existing_keys.op("||")(_new_keys),
        ),
        else_=_new_keys,
    )
    try:
        async with db_module.async_session() as session:
            result = await session.execute(
                update(IngestJob)
                .where(
                    IngestJob.id == job_uuid,
                    IngestJob.attempt_id == attempt_uuid,
                )
                .values(
                    user_metadata=func.coalesce(
                        IngestJob.user_metadata, text("'{}'::jsonb")
                    ).op("||")(
                        func.jsonb_build_object(
                            UNPUBLISHED_STORAGE_KEYS_FIELD, _accumulated_keys
                        )
                    )
                )
            )
            await session.commit()
    except Exception:  # broad: reclaimability is best effort, the ingest is not
        structlog.get_logger().warning(
            "unpublished_storage_keys_not_recorded", job_id=job_id, task=task
        )
        # An error here says nothing about the fence, so it does not license
        # an abort. See the docstring: only a confirmed zero-row match does.
        return True
    if not result.rowcount:  # type: ignore[attr-defined]
        # fix(#1778): a confirmed miss. This attempt no longer owns the
        # row, so the objects it is about to write would have nothing durable
        # naming them; the caller must not write them.
        structlog.get_logger().warning(
            "unpublished_storage_keys_fence_missed", job_id=job_id, task=task
        )
        return False
    return True
