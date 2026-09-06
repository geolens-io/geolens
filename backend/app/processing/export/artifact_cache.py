"""A stable stored artifact behind ``GET /datasets/{id}/export`` (fix(#1532)).

The conversion output is stored once and every subsequent range request is a
slice of that one object, so ``Accept-Ranges: bytes`` cannot splice two
conversions.

Everything is in the key
------------------------
An artifact is named ``{built_at}-{size}-{digest}-{nonce}.bin`` and there is
nothing else: no pointer, no index, no metadata object. Lookup lists the
selection's prefix and takes the newest key inside the freshness window;
publishing is one ``put``; the sweep deletes any key past the horizon. Nothing
is rewritten, so two builders need no lock, a reader mid-stream keeps its
object until the horizon, a sweep cannot race a publish, and total objects are
bounded by build rate times horizon. The size in the name detects a file
truncated by a provider whose ``put`` writes in place.

Why freshness rests on a TTL
----------------------------
Keying freshness on ``bump_tile_cache_version`` (fourteen call sites, designed
for tile cache-busting) would make a missed call cost a wrong download that
looks right. So correctness rests on ``_ttl_seconds()``; the counter is folded
into ``selection_key`` where a bump can only invalidate MORE often. A request
served from the cache sees data at most TTL plus ``_MAX_PUBLISH_SECONDS`` old.
A data-derived version (``max(xmin)``) was rejected on cost: no index, so every
cache hit would pay a sequential scan.
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

# How long a stored artifact may answer for. This is the correctness bound on
# how stale a download can be, not a performance knob.
_DEFAULT_TTL_SECONDS = 60

# Reclaim anything older than this. fix(#1532 r4): the SAME horizon the
# temp-export sweeper uses, so the two cannot drift; a cached export still
# streaming after an hour is otherwise removed under its reader.
_SWEEP_AGE_SECONDS = EXPORTS_PERIODIC_SWEEP_AGE_SECONDS

# How often one process will bother sweeping. The sweep is cheap next to the
# conversion it rides along with, and running it more often buys nothing: the
# objects it reclaims have been unusable for an hour.
_SWEEP_INTERVAL_SECONDS = 900

# fix(#1532): how far into the future a key's stamp may sit before this refuses
# to serve it. Small: it tolerates NTP jitter, not a broken clock.
_CLOCK_SLACK_SECONDS = 5

# fix(#1532 r23/r25): the longest a conversion plus upload can take with a
# client still waiting (nginx `proxy_read_timeout 600s`). It bounds how far past
# its key stamp an artifact's publication may be placed (`_published_at`).
_MAX_PUBLISH_SECONDS = 600

# fix(#1532): the ceiling on what this cache may hold. On the local backend
# `_ROOT` shares the staging volume with every conversion and ingest, and
# filters are caller-controlled. Absolute: the provider reports no capacity.
_BUDGET_BYTES = 8 * 1024 * 1024 * 1024

_last_sweep_at = 0.0


def _ttl_seconds() -> int:
    """The artifact freshness window.

    A constant rather than a settings field: raising it widens the correctness
    bound, which wants its own decision. Tests substitute this function.
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
    # fix(#1532 r12): more than one DISTINCT set of bytes was fresh under this
    # selection at lookup, so a slicing client could splice them. The caller
    # answers ranges whole while this is set; HEAD and the ETag are unaffected.
    contested: bool = False

    @property
    def etag(self) -> str:
        """A strong entity-tag: the artifact's own SHA-256.

        Strong by construction: the object is NAMED by this digest, which
        starlette's mtime-derived ``FileResponse`` ETag could not promise.
        """
        return strong_etag(self.digest)


def strong_etag(digest: str) -> str:
    """The quoted strong entity-tag for a set of export bytes (fix(#1532 r18))."""
    return f'"{digest}"'


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

    ``table_name`` because a replace swaps the physical table; ``dataset_title``
    because it becomes the GPKG layer name. ``tile_cache_version`` sits HERE
    rather than in the freshness check: as a key input a bump can only
    invalidate MORE often than the TTL, so a missed bump costs bounded
    staleness rather than a wrong download. ``None`` and ``""`` stay distinct
    through the JSON encoding (#1546).
    """
    # Two segments (#1585): the URL's identity, then the version's. Every
    # artifact of one URL at every version shares a prefix, so
    # `url_answered_other_bytes_recently` needs one listing.
    url_payload = json.dumps(
        [str(dataset_id), str(format_key), target_crs, bbox, where],
        separators=(",", ":"),
    )
    version_payload = json.dumps(
        [table_name, dataset_title, tile_cache_version],
        separators=(",", ":"),
    )
    url_part = hashlib.sha256(url_payload.encode()).hexdigest()[:20]
    version_part = hashlib.sha256(version_payload.encode()).hexdigest()[:20]
    return f"{url_part}/{version_part}"


def _url_prefix(dataset_id: uuid.UUID, selection: str) -> str:
    """The prefix under which every version of one export URL is stored."""
    return f"{_ROOT}/{_tenant_segment()}/{dataset_id}/{selection.split('/', 1)[0]}/"


async def url_answered_other_bytes_recently(
    dataset_id: uuid.UUID, selection: str, digest: str
) -> bool:
    """Has this URL answered with DIFFERENT bytes inside the last TTL?

    #1585: the bound on bare ranges. A client that read a block of an earlier
    representation and comes back within the change's first TTL is answered
    whole. Bounded to the URL's own versions, called only for a request that
    could receive a 206, and fails CLOSED on a listing error.
    """
    # #1585 r5: TWO TTLs. An artifact answers for a TTL after publication, and
    # the client that took its last answer needs a TTL of its own to come back.
    cutoff = time.time() - 2 * _ttl_seconds()
    try:
        async for page in get_storage().iter_object_pages(
            _url_prefix(dataset_id, selection)
        ):
            for obj in page:
                parsed = parse_artifact_key(obj.key)
                if parsed is None or parsed[2] == digest:
                    continue
                if _published_at(obj.last_modified.timestamp(), parsed[0]) >= cutoff:
                    return True
    except Exception:  # broad: unknown history reads as a recent change; whole is safe
        return True
    return False


def _selection_prefix(dataset_id: uuid.UUID, selection: str) -> str:
    return f"{_ROOT}/{_tenant_segment()}/{dataset_id}/{selection}/"


def _artifact_key(
    dataset_id: uuid.UUID, selection: str, digest: str, size: int, built_at: float
) -> str:
    """``{built_at}-{size}-{digest}-{nonce}.bin``, an artifact's whole metadata.

    ``built_at`` makes freshness and reclamation pure functions of the name,
    ``size`` detects a truncated object, ``digest`` is the strong ETag, and
    ``nonce`` makes the key WRITER-OWNED (fix(#1532)): two builders finishing
    in the same second otherwise shared a key and one's `_discard` deleted the
    other's live object. Two identical objects under one ETag are harmless.
    """
    nonce = uuid.uuid4().hex[:12]
    return (
        f"{_selection_prefix(dataset_id, selection)}"
        f"{int(built_at)}-{size}-{digest}-{nonce}.bin"
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
    if len(parts) != 4:
        return None
    stamp, size, digest, nonce = parts
    if not stamp.isdigit() or not size.isdigit() or not digest or not nonce:
        return None
    return float(stamp), int(size), digest


def parse_tmp_key(key: str) -> float | None:
    """The build time of a ``.tmp`` scratch file, or None if it is not one.

    fix(#1532): ``LocalStorageProvider.put`` writes ``<key>.<hex>.tmp`` and
    renames, so a SIGKILL leaves the scratch file; aged from the stamp of the
    key it was going to become.
    """
    name = key.rsplit("/", 1)[-1]
    if not name.endswith(".tmp") or ".bin." not in name:
        return None
    stamp = name.split("-", 1)[0]
    return float(stamp) if stamp.isdigit() else None


async def lookup(
    dataset_id: uuid.UUID,
    selection: str,
    *,
    filename: str,
    media_type: str,
) -> ExportArtifact | None:
    """The newest usable artifact for this selection, or None.

    "Usable" means published inside the TTL, not future-stamped, and intact:
    the size in the key is compared with one ``size()`` call, which the
    response needs anyway, so a file truncated by an in-place ``put`` is a
    miss rather than a served truncation. ``contested`` reports more than one
    distinct digest among the siblings. Every failure here is a miss.
    """
    now = time.time()
    cutoff = now - _ttl_seconds()
    horizon = now + _CLOCK_SLACK_SECONDS
    # fix(#1532 r9/r23): freshness is measured from the object's modified time
    # (COMPLETION of the put, bounded by the key through `_published_at`), so a
    # slow upload cannot expire an artifact before it exists.
    try:
        storage = get_storage()
        modified: dict[str, float] = {}
        async for page in storage.iter_object_pages(
            _selection_prefix(dataset_id, selection)
        ):
            for obj in page:
                modified[obj.key] = obj.last_modified.timestamp()
        keys = list(modified)
    except Exception:  # broad: an unreachable store is a miss, not a failure
        return None

    candidates: list[tuple[float, int, str, str]] = []
    siblings: set[str] = set()
    oldest_by_digest: dict[str, float] = {}
    for key in keys:
        parsed = parse_artifact_key(key)
        if parsed is None:
            continue
        built_at, size, digest = parsed
        _publication = _published_at(modified.get(key, built_at), built_at)
        oldest_by_digest[digest] = min(
            oldest_by_digest.get(digest, _publication), _publication
        )
        # fix(#1532 r8): `contested` counts EVERY sibling, not just the fresh
        # ones; old siblings live until the horizon and a client may still be
        # reading one.
        siblings.add(digest)
        if built_at > horizon:
            # A future-stamped key from a worker whose clock runs ahead would
            # outrank every honest sibling in the sort below.
            continue
        published_at = _published_at(modified.get(key, built_at), built_at)
        if cutoff <= published_at:
            candidates.append((built_at, size, digest, key))

    # A selection that ever had two distinct artifacts serves no ranges until
    # the sweep clears the older; anything sending If-Range is already safe.
    contested = len(siblings) > 1

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
            contested=contested,
        )
    return None


def _published_at(modified: float, built_at: float) -> float:
    """When this artifact became readable, bounded by the key that names it.

    ``modified`` comes from the STORE's clock, ``built_at`` from the writer's.
    fix(#1532 r22/r23/r28): ``built_at`` is the floor (a store behind the
    writer otherwise made every artifact expired at birth), ``built_at`` plus
    ``_MAX_PUBLISH_SECONDS`` is the ceiling (a store ahead reports a
    publication later than it was), and the stamp is first clamped to the
    modified time plus the same allowance (a writer ahead otherwise pinned an
    unreclaimable object). A pure function of the object: nothing reads
    ``now``, so a verdict can only ever go fresh to expired.
    """
    stamp = min(built_at, modified + _MAX_PUBLISH_SECONDS)
    return min(max(modified, stamp), stamp + _MAX_PUBLISH_SECONDS)


async def store(
    dataset_id: uuid.UUID,
    selection: str,
    *,
    file_path: str,
    filename: str,
    media_type: str,
    digest: str | None = None,
    size: int | None = None,
    snapshot_at: float | None = None,
) -> ExportArtifact | None:
    """Publish a freshly converted file. One ``put``, nothing rewritten.

    ``snapshot_at`` is when the conversion read the data and becomes the key's
    stamp (fix(#1532 r25)); None means now. ``digest`` and ``size`` may be
    supplied by a caller that already ran ``digest_and_size`` (r18).

    Returns the published artifact; or, when publication does not happen, the
    INCUMBENT under this selection (r29: the caller must serve that, not its
    own bytes, so a later bare Range resolves the same representation); or
    None. Only ``Exception`` is caught: a ``CancelledError`` must propagate so
    the caller's cleanup runs.
    """
    global _last_sweep_at
    try:
        if digest is None or size is None:
            digest, size = await digest_and_size(file_path)
        # fix(#1532 r29): a fresh artifact that appeared while this request was
        # converting wins, and the caller serves THAT, so every response under
        # this selection is on the artifact the next Range will find.
        incumbent = await lookup(
            dataset_id, selection, filename=filename, media_type=media_type
        )
        if incumbent is not None:
            return incumbent
        # fix(#1532 r4/r6): reclaim BEFORE the budget check and BEFORE writing.
        # This is the only production call to the sweep, so an early exit above
        # it deadlocked a full store for good.
        await _sweep_occasionally()
        if not await _fits_in_budget(size):
            # The cadence guard may have skipped the sweep; force one and ask
            # again, the shape `_put_with_reclaim` uses.
            await sweep()
            _last_sweep_at = time.time()
            if not await _fits_in_budget(size):
                logger.warning("export_cache_budget_exhausted", size=size)
                # r29: a publisher may have landed between the re-check above
                # and here — the same lost race, one step later. Same answer.
                return await lookup(
                    dataset_id, selection, filename=filename, media_type=media_type
                )
        built_at, key = await _put_with_reclaim(
            dataset_id,
            selection,
            digest,
            size,
            file_path,
            built_at=time.time() if snapshot_at is None else snapshot_at,
        )
        # fix(#1532 r7): PUBLICATION IS FINAL. A post-write re-check could delete
        # a key another request had already resolved and truncate its stream.
        return ExportArtifact(
            key=key,
            digest=digest,
            size=size,
            built_at=built_at,
            filename=filename,
            media_type=media_type,
        )
    except Exception:  # broad: caching is best-effort; the conversion succeeded
        # A failed store is the one signal the horizon may need applying sooner
        # than the cadence, so the next attempt sweeps.
        _last_sweep_at = 0.0
        logger.warning(
            "export_artifact_store_failed",
            dataset_id=str(dataset_id),
            exc_info=True,
        )
        # r29: same reasoning as the budget exit; `lookup` never raises.
        return await lookup(
            dataset_id, selection, filename=filename, media_type=media_type
        )


async def _put_with_reclaim(
    dataset_id: uuid.UUID,
    selection: str,
    digest: str,
    size: int,
    file_path: str,
    *,
    built_at: float,
) -> tuple[float, str]:
    """Write the artifact, reclaiming and retrying once if the store is full.

    fix(#1532 r4): ``_sweep_occasionally`` is interval-guarded, so a failed
    write forces an unconditional sweep and one retry. Once, not a loop: if
    the horizon frees nothing the store is full of something this cache does
    not own. fix(#1532 r5): every attempted key is deleted on failure, because
    a fresh-stamped partial cannot be reclaimed by any rule here.
    """
    global _last_sweep_at
    attempted: list[str] = []

    async def _write() -> tuple[float, str]:
        # The stamp is the caller's snapshot time (r25), the same on a retry:
        # the bytes did not get any newer for having failed to upload once.
        key = _artifact_key(dataset_id, selection, digest, size, built_at)
        attempted.append(key)
        with open(file_path, "rb") as handle:
            await get_storage().put(key, handle)
        return built_at, key

    # fix(#1532): BaseException outside, Exception inside. A CancelledError is
    # not an Exception, so the discard must run on ANY exit while the retry
    # runs only on the ones a retry can help.
    try:
        try:
            return await _write()
        except Exception:  # broad: any write failure is worth one reclaim-and-retry
            logger.warning("export_artifact_put_failed_reclaiming", exc_info=True)
            await _discard(attempted)
            await sweep()
            _last_sweep_at = time.time()
            return await _write()
    except BaseException:
        await _discard(attempted)
        raise


async def _discard(keys: list[str]) -> None:
    """Remove whatever a failed write may have left behind.

    Deletes are best-effort and a missing key is the expected case: an atomic
    provider leaves nothing, and this exists for the ones that do not. What it
    must not do is raise, because it runs on a path that is already failing and
    whose caller has a working conversion to fall back on.
    """
    storage = get_storage()
    for key in keys:
        try:
            await storage.delete(key)
        except Exception:  # broad: an absent or unremovable key is the sweep's job
            logger.debug("export_artifact_discard_failed", key=key, exc_info=True)


async def _fits_in_budget(size: int) -> bool:
    """Would publishing ``size`` more bytes keep the cache under its budget?

    A SOFT ceiling (fix(#1532 r6/r7)): ``StorageProvider`` cannot claim space,
    so concurrent publishers can each overshoot by one artifact for at most
    one horizon. This is the only check; a post-write re-check was withdrawn
    because it could truncate a download already resolved through ``lookup``.
    Fails OPEN on an unreadable listing.
    """
    # fix(#1532 r16): the ceiling on ONE artifact, above the listing and outside
    # the fail-open: a provider yields NO page for an empty prefix, so a cold
    # cache let an artifact of any size through.
    if size > _BUDGET_BYTES:
        return False
    # fix(#1532 r11): paged, and stopped at the first overrun, so the work is
    # bounded by the budget rather than by a caller-controlled object count.
    total = 0
    try:
        async for page in get_storage().iter_object_pages(f"{_ROOT}/"):
            for obj in page:
                parsed = parse_artifact_key(obj.key)
                if parsed is not None:
                    total += parsed[1]
            if total + size > _BUDGET_BYTES:
                return False
    except Exception:  # broad: cannot measure means do not block
        return True
    return True


async def digest_and_size(file_path: str) -> tuple[str, int]:
    """SHA-256 and byte length of a converted export, read in bounded chunks.

    Public because the route calls it BEFORE ``store`` (fix(#1532 r18)): the
    digest is the validator whether or not publication happens. Off the event
    loop because hashing a multi-GB file inline stalls every other request.
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

    Rides a build rather than a startup hook: the worker's export sweep runs
    before ``init_storage``. Failures are swallowed; this is housekeeping.
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

    An object goes when its publication, floored at the timestamp IN ITS OWN
    NAME and raised to ``last_modified`` (r10), is past the horizon. An aged
    key can never become fresh, so no judgement depends on a read another
    worker can invalidate; earlier shapes deleted by prefix or read a pointer
    (r2/r3). Paged, so the cache is never materialized in memory.
    """
    cutoff = time.time() - age_threshold_seconds
    removed = 0
    storage = None
    try:
        storage = get_storage()
        async for page in storage.iter_object_pages(f"{_ROOT}/"):
            for obj in page:
                parsed = parse_artifact_key(obj.key)
                built_at = parsed[0] if parsed is not None else parse_tmp_key(obj.key)
                if built_at is None:
                    continue
                # fix(#1532 r10/r24): age from the LATER of the two clocks,
                # through the SAME bound freshness uses, so a store clock ahead
                # cannot push the age origin into the future.
                published_at = _published_at(obj.last_modified.timestamp(), built_at)
                if published_at >= cutoff:
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

    # fix(#1532 r7): prune empty directories HERE, not in the generic delete,
    # where an unrelated writer's `mkdir` raced the `rmdir`. Duck-typed: an
    # object store has no directories. `storage` is None if get_storage() raised.
    prune = getattr(storage, "prune_empty_dirs", None)
    if prune is not None:
        try:
            await prune(f"{_ROOT}/")
        except Exception:  # broad: housekeeping, never a request failure
            logger.warning("export_cache_prune_failed", exc_info=True)
    return removed
