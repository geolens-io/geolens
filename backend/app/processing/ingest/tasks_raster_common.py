"""Shared building blocks for the raster ingest and raster replace tasks.

fix(#1290 review): a pure extraction from ``tasks_raster``, which crossed the
1000-line ratchet threshold in round 3. Nothing here is new — every function
moved verbatim — and nothing here is a Procrastinate task. What lives here is
what BOTH raster tails need: the manifest-VRT discriminators, the strict-COG
gate, the row builders for a freshly published raster, the managed-key
resolver, and the orphan reaper.

The replace tail was already importing four of these out of a sibling task
module, which is the kind of reach-across that makes a later split harder than
it needs to be. They have one home now.
"""

import os
import uuid
from datetime import datetime, timezone
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

    Deliberately built from ``original_filename`` alone — never from the
    staging path or the raw rasterio message — so the message can never leak
    the `/app/staging/<uuid>_...` path rasterio/GDAL echo back on any
    open-time failure (unrecognized format, corrupt/truncated IFD, missing
    file, permission error — all read, from the person who uploaded the
    file, as the same thing: "GeoLens could not open this as a raster").
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

    fix(#1661): both raster ingest tails (``ingest_raster``, the replace tail)
    call this on the freshly-staged SOURCE upload. ``extract_raster_metadata``
    opens that file with a single ``rasterio.open`` call and reads everything
    else off the resulting dataset, so ANY ``RasterioIOError`` it raises is by
    definition "rasterio could not open this file" — the class GDAL raises
    for an unrecognized format, a corrupt/truncated IFD, a missing file, or a
    permission error alike (codex review on #1661 round 1: a narrower pattern
    match on just the "not recognized as being in a supported file format"
    text missed the corrupt-IFD shape, which ALSO quotes the staging path and
    is equally production-reachable — a .tif with a valid magic header but a
    corrupt IFD passes upload-time content-sniffing same as any other .tif).
    That used to land the raw rasterio message — including the internal
    staging path — in ``IngestJob.error_message`` verbatim. The full rasterio
    message still reaches structured logs at error level here, the one place
    that sees it; a failure raised by anything OTHER than the open call
    itself (e.g. malformed EXIF/tag parsing further down in
    ``extract_raster_metadata``) is not a ``RasterioIOError`` and keeps its
    real message unchanged. Callers reading their own just-produced COG (no
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
    reject non-COG TIFFs here instead of silently routing through
    ``check_and_prepare_cog`` conversion.

    Manifest-VRT jobs are excluded (VRTs are XML, not TIFFs — the COG
    compliance check would fail for unrelated reasons).

    On non-compliance, raises ``ValueError`` whose message contains the
    compliance reason. The existing ``ingest_raster`` outer
    ``except Exception`` handler writes the failure to the job via
    ``_job_phase_session("error_write")``.
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
) -> tuple:
    """Create Record + Dataset + RasterAsset records for a raster ingest.

    ``meta`` describes the CONVERTED COG — the file this dataset will serve
    (fix(#1290 review)). ``original_srid`` is the one value that must describe
    the upload instead, so the caller reads it off the source and passes it in.

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
    # fix(#430 BA-23): same for the byte cap — recount under the per-user advisory
    # lock so concurrent raster uploads can't overshoot max_storage_bytes_per_user.
    from app.modules.quota.service import (
        reserve_dataset_slot,
        reserve_storage_bytes,
    )

    await reserve_dataset_slot(session, created_by)
    await reserve_storage_bytes(session, created_by, cog_size)

    # Mirror the vector ingest path (datasets/service.py
    # `create_dataset_record`) which commits directly to `published`.
    # Without this the raster stayed in `draft` and the anonymous public
    # tile-access check at tiles/router.py `_resolve_raster_access`
    # returned 404 for every raster tile fetch, so every public demo map
    # containing a raster layer (Earth as Seen from Space, Global
    # Bathymetry, …) was broken for anonymous users.
    record = Record(
        title=title,
        summary=summary,
        record_type="raster_dataset",
        visibility=visibility,
        record_status=record_status,
        # fix(#302): created_by was never set on raster records, leaving them
        # NULL and invisible to the per-user quota count and owner checks.
        created_by=created_by,
        updated_by=created_by,
    )
    if meta.get("bbox_wkt"):
        record.spatial_extent = func.ST_GeomFromText(meta["bbox_wkt"], 4326)
    session.add(record)
    await session.flush()

    table_name = f"raster_{record.id.hex[:16]}"
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        source_format="geotiff",
        source_filename=source_filename,
        srid=meta.get("epsg"),
        # fix(#1290 review): the SRID the uploaded file declared, which under a
        # `srid_override` is not the one the COG carries. Two fields, two
        # questions — the replace tail draws the same line.
        original_srid=original_srid,
        # fix(#1218 review): see create_dataset — every creation path stamps
        # this, or post-migration rows report null while backfilled ones do
        # not. Python value, not func.now(): a SQL expression leaves the
        # attribute expired and the next read lazy-loads.
        last_refreshed_at=datetime.now(timezone.utc),
    )
    # feat(#1218): a raster dataset IS the COG; the pre-conversion upload is a
    # transient input, so the origin is the uploaded file and there is no
    # remote URI to point at (ADR-002 Decision 7).
    # fix(#1294): file_hash was missing here, unlike the replace tail's
    # equivalent call in tasks_raster_swap.py — both go through this same
    # set_dataset_origin authority, so passing the sha256 the caller already
    # computed for `source_sha256` is the whole fix.
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

    BUG-041: ``dataset_assets`` is read by the search/STAC/OGC asset-output path
    but was never written by ingest, so STAC item assets were never advertised.
    This produces the rows the read path expects, using the stable keys defined
    on ``DatasetAsset``:

      - ``data`` / ``vrt``: the primary COG (or VRT) source
      - ``thumbnail``: 256px quicklook
      - ``overview``: 512px quicklook

    hrefs are storage keys (storage-relative); ``resolve_asset_url`` turns them
    into presigned/public URLs at read time (or omits them on local storage per
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
    terminal DB commit. If the commit (or any later step) fails, the dataset row
    is rolled back and ``delete_dataset`` never runs for it, orphaning the bytes.
    This reaps exactly the keys that were written. Failures here are swallowed —
    cleanup must never mask the original ingest error.
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

    fix(#1778): #1708 codex r11's reasoning, applied to the raster and VRT
    publish tails. A commit whose acknowledgement is lost — a dropped
    connection, or the ``asyncio.CancelledError`` a cancel request delivers,
    which is a BaseException the tails' ``except Exception`` never sees but
    which their ``finally`` still runs through — may have been applied by
    PostgreSQL all the same. Each tail set its "published" flag on the line
    after that await, so a lost acknowledgement left the flag false and the
    terminal cleanup deleted the exact object keys the committed row had just
    been pointed at. Nothing
    reclaims that: the superseded objects are still in the bucket but no row
    points at them, so every tile request, download and STAC asset 404s until
    an operator lists the prefix by hand.

    So decide by OBSERVATION rather than by the await's outcome: read the job
    row back on a FRESH session (the publishing session is mid-failure and
    cannot be trusted to see anything) and ask whether this attempt's terminal
    write is there. ``status == 'complete'`` for this exact ``attempt_id`` is
    the signal all four of these tails can share, because every one of them
    stamps it in the SAME transaction as the pointer swap: seeing it means the
    swap is durable, and no other attempt can have produced it, because the
    attempt token is fresh per attempt and each of these tasks is ``retry=0``.

    A probe that itself fails returns True — standing down. The asymmetry is
    deliberate and is #1708's: standing down on a false positive leaves objects
    behind that an operator or a later sweep can still remove, while proceeding
    on a false negative deletes the live raster.

    Callers gate ONLY the orphaned-key cleanup on this. It is deliberately not
    folded into ``final_status``, which also decides whether the uploader's
    staged original may be deleted — standing down there would turn a probe
    failure into a second, worse deletion.
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
