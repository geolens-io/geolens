"""A stable stored artifact behind ``GET /datasets/{id}/export`` (fix(#1532)).

The route used to run a fresh conversion on every request, including every range
request. It advertises ``Accept-Ranges: bytes``, so one ``/vsicurl/`` open cost
roughly ten conversions — and, whenever the data moved under them, ten different
artifacts served under one URL, with two probes reporting different total sizes.

This module is the other half of the fix: the conversion output is stored once
and every subsequent range is a slice of that one object.

Everything is in the key
------------------------
An artifact is named ``{built_at}-{size}-{digest}.bin`` and there is nothing
else — no pointer, no index, no metadata object. Lookup lists the selection's
prefix and takes the newest key still inside the freshness window; publishing is
one ``put``; the sweep deletes any key past the horizon. Nothing is ever
rewritten, so there is no flip to race and no read-decide-delete to lose.

fix(#1532 review r3) arrived at that by removing the last piece of mutable state.
A ``current.json`` pointer per selection was the previous design, and it failed
in three ways across two review rounds: r2 found a sweep deleting a pointer
another worker had just published, r2's own fix could only narrow that window
rather than close it (``StorageProvider`` has no compare-and-delete), and leaving
pointers undeleted turned them into an amplification — anonymous callers can
export a public dataset with arbitrary ``bbox``/``where``, so every distinct
selection left one small object forever and the sweep's listing grew with them.
Removing the pointer answers all three at once, and the properties the earlier
rounds fought for now hold by construction:

- **Two concurrent builders need no lock.** Both publish, under different keys
  because the timestamp differs; readers take the newer. Neither can delete the
  other's object, because publishing deletes nothing.
- **A reader mid-stream keeps its object** until the horizon, which is chosen to
  be well past any download.
- **A sweep cannot race a publish.** An aged key can never become fresh and a
  fresh key can never look aged, so no judgement depends on a read that another
  worker can invalidate.
- **Total objects are bounded by build rate times horizon**, not by the number of
  distinct selections ever requested.

The size in the name is what makes this safe on a provider whose ``put`` writes
in place. ``LocalStorageProvider.put`` streams straight to the destination, so a
process killed mid-copy leaves a truncated file at the final key, and a
"newest wins" reader would serve it. Lookup compares the stored object's real
size against the size the key claims and skips a mismatch — the pointer only ever
avoided naming such a file, where this detects it. The check is free: the
response needs the length anyway.

Why freshness rests on a TTL
----------------------------
#1532 is explicit that the tempting fix is the dangerous one. Anything that lets
one request's range be answered from bytes another request built is only correct
if the cache is invalidated on *every* path that can change the exported bytes,
and this repository has the cautionary example already: ``bump_tile_cache_version``
is called from fourteen places and was designed for tile cache-busting, where a
missed call costs a stale tile. Keying export freshness on a hand-audited list
like that would make a missed call cost a *wrong download that looks right*,
which is strictly worse than the bug, because today's failure is loud (a spliced
GeoJSON dies with ``ERROR 4: Failed to read GeoJSON data``).

So correctness rests on ``_ttl_seconds()``, a property nobody can forget to
maintain. The counter still earns its keep — it is folded into ``selection_key``,
where a bump moves the request to a different key and invalidates instantly — but
as a key input it can only ever invalidate MORE often than the TTL already
forces. A missed bump costs one TTL of staleness, not a wrong answer. That
inversion is the whole design: the audited list is an optimization by
construction rather than by promise.

A data-derived version (``count(*)`` plus ``max(xmin)`` over the selection) was
the other candidate and is rejected on cost, not on correctness: it is complete
for INSERT/UPDATE/DELETE, but ``max(xmin)`` has no index, so every range request
on the cache-HIT path would pay a sequential scan — 509 ms on the 5M-row table
#905 measured. Ten of those to save ten conversions is the wrong trade against a
prefix listing.
"""

import hashlib
import json
import time
import uuid
from dataclasses import dataclass

import structlog

from app.core.db.tenant_session import current_tenant_var
from app.core.runtime.staging import EXPORTS_PERIODIC_SWEEP_AGE_SECONDS
from app.platform.storage import get_storage

logger = structlog.stdlib.get_logger(__name__)

# The prefix every cached export lives under, so the sweep has one place to look
# and no other subsystem's objects can be reached by it.
_ROOT = "export-cache"

# How long a stored artifact may answer for. Deliberately short: this is the
# whole correctness guarantee (see the module docstring), so it is the bound on
# how stale a download can be, not a performance knob. Long enough to cover a
# /vsicurl/ open, which is seconds.
_DEFAULT_TTL_SECONDS = 60

# Reclaim anything older than this. Well past the TTL, because expiry and
# reclamation answer different questions: expiry asks whether an artifact may
# answer a NEW request, reclamation asks whether a request that started before
# expiry could still be streaming from it.
#
# fix(#1532 review r4): the SAME horizon the temp-export sweeper uses, and
# reused rather than restated so the two cannot drift. `staging.py` already
# worked this out for the identical hazard: at one hour, "an in-flight export
# survives a restart" becomes "any export whose generation plus client download
# time exceeds an hour is deleted out from under it on the very next cycle" —
# guaranteed, not an unlucky coincidence. A full cached export still streaming
# after an hour would have had its object removed by the next build's sweep,
# and on Azure `downloader.chunks()` fetches later chunks as it goes, so an
# already-started 200 dies truncated rather than failing to start.
_SWEEP_AGE_SECONDS = EXPORTS_PERIODIC_SWEEP_AGE_SECONDS

# How often one process will bother sweeping. The sweep is cheap next to the
# conversion it rides along with, and running it more often buys nothing: the
# objects it reclaims have been unusable for an hour.
_SWEEP_INTERVAL_SECONDS = 900

_last_sweep_at = 0.0


def _ttl_seconds() -> int:
    """The artifact freshness window.

    A module constant rather than a settings field. It is the correctness bound
    on how stale a download can be, and an operator who raises it is widening
    that window rather than tuning a cache — a change that wants its own
    decision, not a knob shipped by default. Tests substitute this function.
    """
    return _DEFAULT_TTL_SECONDS


@dataclass(frozen=True)
class ExportArtifact:
    """A stored export and everything a response needs to describe it.

    ``filename`` and ``media_type`` are supplied by the caller rather than
    stored: ``export_descriptor`` derives both from the dataset title and the
    format without touching the database or the filesystem, and both verbs of
    the route already call it. Persisting them would have been a second copy of
    a value that is cheaper to recompute than to keep consistent.
    """

    key: str
    digest: str
    size: int
    built_at: float
    filename: str
    media_type: str

    @property
    def etag(self) -> str:
        """A strong entity-tag: the artifact's own SHA-256.

        Strong by construction rather than by assertion — the object is NAMED by
        this digest, so two responses carrying one tag are slices of literally
        the same stored bytes. That is what starlette's ``FileResponse`` ETag
        could not promise here: it derives from a temp file's mtime, and #1532
        observed two different tags for two conversions of one unchanged
        dataset.
        """
        return f'"{self.digest}"'


def _tenant_segment() -> str:
    """The tenant namespace this cache's keys sit under.

    Single-tenant deployments get a literal ``shared`` rather than an empty
    segment, so a key is never ambiguous and a future multi-tenant instance
    cannot collide with objects written before it was one.
    """
    tenant_id = current_tenant_var.get()
    return str(tenant_id) if tenant_id else "shared"


def selection_key(
    *,
    dataset_id: uuid.UUID,
    table_name: str,
    dataset_title: str,
    tile_cache_version: int | None,
    format_key: str,
    target_crs: str | None,
    bbox: str | None,
    where: str | None,
) -> str:
    """Identity of the bytes a request is asking for, as a storage path segment.

    ``table_name`` because a replace swaps the physical table the export reads.
    ``dataset_title`` because it becomes the output FILENAME, and ogr2ogr names a
    GPKG layer after the file it is writing — a retitle therefore changes the
    bytes, not merely the Content-Disposition.

    ``tile_cache_version`` is how invalidation-on-mutation happens, and putting it
    HERE rather than in the freshness check is the whole reason this is safe.
    The counter is bumped by fourteen call sites (feature edits, column DDL,
    reupload, the PostGIS and STAC refreshes, the raster swap) and was designed
    for tile cache-busting, where a missed bump costs a stale tile. Reading it as
    the authority on freshness would make a missed bump cost a wrong download
    that looks right — the trap #1532 spends three paragraphs warning about.

    As a key INPUT it cannot do that. A bump can only ever move the request to a
    different key, so it can only make the cache invalidate MORE often than the
    TTL already forces. A writer that forgets costs one TTL of staleness; a
    writer that remembers costs nothing and invalidates instantly. The
    hand-maintained list is an optimization by construction rather than by
    promise, which is the property the issue asks for and the one an audit cannot
    supply.

    It also needs no cross-layer call. ``processing/`` may not import
    ``modules/catalog/``, so a hook next to each ``bump_tile_cache_version()``
    would have meant a new ``ProcessingPort`` method and an
    EXTENSION_API_VERSION bump to deliver an optimization; the counter is already
    on the dataset row this route has in hand.

    ``None`` and the empty string are kept distinct by the JSON encoding, for the
    reason ``embedding_config_fingerprint`` gives in #1546: a delimiter join
    collapses them, and ``where=""`` is not ``where`` absent.
    """
    payload = json.dumps(
        [
            str(dataset_id),
            table_name,
            dataset_title,
            tile_cache_version,
            str(format_key),
            target_crs,
            bbox,
            where,
        ],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _selection_prefix(dataset_id: uuid.UUID, selection: str) -> str:
    return f"{_ROOT}/{_tenant_segment()}/{dataset_id}/{selection}/"


def _artifact_key(
    dataset_id: uuid.UUID, selection: str, digest: str, size: int, built_at: float
) -> str:
    """``{built_at}-{size}-{digest}.bin`` — the whole of an artifact's metadata.

    Three facts, each earning its place. ``built_at`` is what makes every
    freshness and reclamation decision a pure function of the name, so no
    judgement depends on a read another worker can invalidate. ``size`` is what
    detects a truncated object on a provider that writes in place. ``digest`` is
    the strong ETag, and it is what makes two artifacts with identical content
    distinguishable from two with different content.
    """
    return (
        f"{_selection_prefix(dataset_id, selection)}{int(built_at)}-{size}-{digest}.bin"
    )


def parse_artifact_key(key: str) -> tuple[float, int, str] | None:
    """``(built_at, size, digest)`` from a key, or None if it is not one of ours.

    None means "not one of ours" and every caller leaves it alone. A key this
    cannot read is a key it cannot age, and acting on a parse failure is how a
    naming change turns into data loss.
    """
    name = key.rsplit("/", 1)[-1]
    if not name.endswith(".bin"):
        return None
    parts = name[: -len(".bin")].split("-")
    if len(parts) != 3:
        return None
    stamp, size, digest = parts
    if not stamp.isdigit() or not size.isdigit() or not digest:
        return None
    return float(stamp), int(size), digest


async def lookup(
    dataset_id: uuid.UUID,
    selection: str,
    *,
    filename: str,
    media_type: str,
) -> ExportArtifact | None:
    """The newest usable artifact for this selection, or None.

    "Usable" means inside the TTL and intact. Both are decided from the key plus
    one ``size()``, so a request that goes on to transfer bytes has already
    learned its Content-Length.

    The size check is not belt-and-braces. ``LocalStorageProvider.put`` streams
    to the destination, so a process killed mid-copy leaves a truncated file at
    the final key, and taking the newest key without verifying it would serve
    that truncation to every reader until the horizon. Comparing against the size
    the key claims turns it into a miss and a rebuild.

    Every failure here is a miss. This is a cache in front of a conversion that
    still works, so a storage hiccup should cost a rebuild, not the download.
    """
    cutoff = time.time() - _ttl_seconds()
    try:
        storage = get_storage()
        keys = await storage.list(_selection_prefix(dataset_id, selection))
    except Exception:  # broad: an unreachable store is a miss, not a failure
        return None

    candidates: list[tuple[float, int, str, str]] = []
    for key in keys:
        parsed = parse_artifact_key(key)
        if parsed is None:
            continue
        built_at, size, digest = parsed
        if built_at >= cutoff:
            candidates.append((built_at, size, digest, key))

    for built_at, size, digest, key in sorted(candidates, reverse=True):
        try:
            if await storage.size(key) != size:
                # A truncated or otherwise altered object. Skip it rather than
                # serve it, and let an older sibling answer if there is one.
                logger.warning("export_artifact_size_mismatch", key=key)
                continue
        except Exception:  # broad: cannot verify means cannot use
            continue
        return ExportArtifact(
            key=key,
            digest=digest,
            size=size,
            built_at=built_at,
            filename=filename,
            media_type=media_type,
        )
    return None


async def store(
    dataset_id: uuid.UUID,
    selection: str,
    *,
    file_path: str,
    filename: str,
    media_type: str,
) -> ExportArtifact | None:
    """Publish a freshly converted file. One ``put``, nothing rewritten.

    Publishing is a single write to a key nothing else can be using, so two
    builders racing the same selection simply both succeed and readers take the
    newer. There is no pointer to flip, so there is no window in which a
    half-published state exists.

    Returns None if anything goes wrong. The caller has the converted file in
    hand and can serve it directly, so a cache that cannot store must not be able
    to fail a download.

    Only ``Exception`` is caught, deliberately. A ``CancelledError`` is a
    ``BaseException`` and must keep propagating so the caller's cleanup runs —
    the same distinction fix(#1550) turned on. The caller owns the conversion
    directory until a response takes it, and swallowing a cancel here would leave
    it stranded.
    """
    global _last_sweep_at
    try:
        digest, size = await _digest_and_size(file_path)
        # fix(#1532 review r4): reclaim BEFORE writing, not after. This is the
        # only production call to the sweep, so a `put` that raises on a full
        # store used to exit before it — and with nothing else sweeping
        # `export-cache/`, the aged artifacts that filled the volume could never
        # be reclaimed by a later request. Caching stayed dead, and on the local
        # backend the shared staging volume stayed too full to generate larger
        # exports at all, until an operator deleted files by hand. Sweeping
        # first turns a full store into a self-healing condition instead of a
        # deadlock.
        await _sweep_occasionally()
        built_at, key = await _put_with_reclaim(
            dataset_id, selection, digest, size, file_path
        )
        return ExportArtifact(
            key=key,
            digest=digest,
            size=size,
            built_at=built_at,
            filename=filename,
            media_type=media_type,
        )
    except Exception:  # broad: caching is best-effort; the conversion succeeded
        # And let the NEXT attempt sweep whatever the interval says. A store
        # that failed is the one signal available that the horizon may need
        # applying sooner than the fifteen-minute cadence, so recovery from a
        # full store takes one request rather than up to a quarter of an hour.
        _last_sweep_at = 0.0
        logger.warning(
            "export_artifact_store_failed",
            dataset_id=str(dataset_id),
            exc_info=True,
        )
        return None


async def _put_with_reclaim(
    dataset_id: uuid.UUID, selection: str, digest: str, size: int, file_path: str
) -> tuple[float, str]:
    """Write the artifact, reclaiming and retrying once if the store is full.

    fix(#1532 review r4): sweeping before the write is not enough on its own,
    because ``_sweep_occasionally`` is interval-guarded — a store that fills
    between two cadence ticks would fail without any reclamation having been
    attempted, and with nothing else sweeping ``export-cache/`` the volume stays
    full. So a failed write forces an unconditional sweep and tries once more,
    which makes a full store heal inside the request that hit it rather than
    fifteen minutes later.

    Once, not in a loop. If reclaiming everything past the horizon does not make
    room, the store is full of something this cache does not own and retrying is
    just a slower way to fail.
    """
    global _last_sweep_at

    async def _write() -> tuple[float, str]:
        built_at = time.time()
        key = _artifact_key(dataset_id, selection, digest, size, built_at)
        with open(file_path, "rb") as handle:
            await get_storage().put(key, handle)
        return built_at, key

    try:
        return await _write()
    except Exception:  # broad: any write failure is worth one reclaim-and-retry
        logger.warning("export_artifact_put_failed_reclaiming", exc_info=True)
        await sweep()
        _last_sweep_at = time.time()
        return await _write()


async def _digest_and_size(file_path: str) -> tuple[str, int]:
    """SHA-256 and byte length of a converted export, read in bounded chunks.

    Chunked because an export can be gigabytes and this runs on the API worker.
    Off the event loop for the same reason the shapefile zip is (#435): hashing
    a multi-GB file is CPU-bound, and doing it inline stalls every other request
    and the job heartbeats for the duration.
    """
    from app.core.async_io import run_in_thread_draining

    def _hash() -> tuple[str, int]:
        hasher = hashlib.sha256()
        total = 0
        with open(file_path, "rb") as handle:
            while chunk := handle.read(1024 * 1024):
                hasher.update(chunk)
                total += len(chunk)
        return hasher.hexdigest(), total

    return await run_in_thread_draining(_hash)


async def _sweep_occasionally() -> None:
    """Run the sweep at most once every ``_SWEEP_INTERVAL_SECONDS`` per process.

    Riding a build rather than a startup hook, deliberately. The worker's
    existing ``sweep_orphaned_exports`` runs before ``init_storage``, so a
    storage-backed sweep cannot join it without reordering boot; and a process
    that has just converted a dataset is one that demonstrably has a working
    object store. The cost is a paged listing next to an ogr2ogr run.

    Failures are swallowed for the same reason everything else here is: this is
    housekeeping attached to a request that has already succeeded.
    """
    global _last_sweep_at
    now = time.time()
    if now - _last_sweep_at < _SWEEP_INTERVAL_SECONDS:
        return
    _last_sweep_at = now
    try:
        await sweep()
    except Exception:  # broad: a failed sweep must not fail a download
        logger.warning("export_cache_sweep_failed", exc_info=True)


async def sweep(*, age_threshold_seconds: int = _SWEEP_AGE_SECONDS) -> int:
    """Reclaim what nothing can still be reading. Returns how many keys went.

    One rule, and it is chosen so a concurrent publish cannot satisfy it rather
    than so the window is merely small: an object goes when the timestamp IN ITS
    OWN NAME is past the horizon. A publish mints its key from ``time.time()``,
    so an aged key can never become fresh and a fresh one can never look aged.
    Nothing else is consulted, so there is no read that another worker can make
    stale before the delete runs.

    That is the third shape this sweep has had, and the earlier two are why the
    rule is phrased that way. It deleted by PREFIX first, so a selection whose
    pointer looked old took a neighbouring worker's just-uploaded artifact with
    it (review r2). It then read each pointer to decide, which merely narrowed
    the same window (review r2 again). Both are gone with the pointer itself
    (review r3).

    Ages come from the keys rather than from object mtime, which is what makes
    this portable: ``StorageProvider`` exposes no modified time on ``list``, S3
    and the local provider would answer differently if it did, and a copy resets
    it. ``iter_object_pages`` does expose one, and is used here only to PAGE —
    the whole cache is not materialized in memory to be swept (review r3), and
    the age still comes from the name.

    An hour rather than the TTL because expiry and reclamation are different
    questions. Expiry asks whether an artifact may answer a NEW request;
    reclamation asks whether a request that started before expiry could still be
    streaming from it.
    """
    cutoff = time.time() - age_threshold_seconds
    removed = 0
    try:
        storage = get_storage()
        async for page in storage.iter_object_pages(f"{_ROOT}/"):
            for obj in page:
                parsed = parse_artifact_key(obj.key)
                if parsed is None or parsed[0] >= cutoff:
                    continue
                try:
                    await storage.delete(obj.key)
                    removed += 1
                except Exception:  # broad: leave it for the next sweep
                    logger.warning(
                        "export_cache_sweep_delete_failed", key=obj.key, exc_info=True
                    )
    except Exception:  # broad: a sweep that cannot list is a no-op, not an error
        logger.warning("export_cache_sweep_list_failed", exc_info=True)
    return removed
