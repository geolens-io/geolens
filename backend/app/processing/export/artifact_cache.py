"""Stable stored artifact behind ``GET /datasets/{id}/export`` (fix(#1532)).

Stored once; every range request slices that one object. An artifact is
named ``{built_at}-{size}-{digest}-{nonce}.bin`` with no other index: lookup
lists the selection's prefix for the newest key in the freshness window,
publish is one ``put``, sweep deletes past-horizon keys. Nothing is
rewritten, so no lock is needed and a sweep cannot race a publish.

Freshness rests on ``_ttl_seconds()``, not ``bump_tile_cache_version``: a
missed bump only over-invalidates rather than serving stale data.
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

# Sole prefix for cached exports, so sweep touches only its own objects.
_ROOT = "export-cache"

# Correctness bound on staleness, not a performance knob.
_DEFAULT_TTL_SECONDS = 60

# fix(#1532): same horizon as the temp-export sweeper (must not drift) or
# a cached export still streaming past it is removed under its reader.
_SWEEP_AGE_SECONDS = EXPORTS_PERIODIC_SWEEP_AGE_SECONDS

# Sweep cadence; running more often buys nothing since reclaimed objects
# have been unusable for an hour already.
_SWEEP_INTERVAL_SECONDS = 900

# fix(#1532): tolerates NTP jitter, not a broken clock.
_CLOCK_SLACK_SECONDS = 5

# fix(#1532): matches nginx `proxy_read_timeout 600s`; bounds how far
# past its key stamp an artifact's publish may land (`_published_at`).
_MAX_PUBLISH_SECONDS = 600

# fix(#1532): cache ceiling; `_ROOT` shares the staging volume with every
# conversion/ingest and the provider reports no capacity, so this is absolute.
_BUDGET_BYTES = 8 * 1024 * 1024 * 1024

_last_sweep_at = 0.0


def _ttl_seconds() -> int:
    """Artifact freshness window; a constant, not a settings field, since
    raising it widens the correctness bound. Tests substitute this function.
    """
    return _DEFAULT_TTL_SECONDS


@dataclass(frozen=True)
class ExportArtifact:
    """A stored export and everything a response needs to describe it.

    ``filename``/``media_type`` are supplied by the caller, not stored: both
    are cheap to recompute from ``export_descriptor`` and would otherwise be
    a second copy to keep consistent.
    """

    key: str
    digest: str
    size: int
    built_at: float
    filename: str
    media_type: str
    # fix(#1532): set when >1 distinct digest was fresh at lookup, so a
    # slicing client could splice them; caller answers ranges whole while set.
    contested: bool = False

    @property
    def etag(self) -> str:
        """Strong ETag from the artifact's own digest (unlike starlette's
        mtime-derived ``FileResponse`` ETag, this is strong by construction).
        """
        return strong_etag(self.digest)


def strong_etag(digest: str) -> str:
    """The quoted strong entity-tag for a set of export bytes (fix(#1532))."""
    return f'"{digest}"'


def _tenant_segment() -> str:
    """Tenant namespace for cache keys; single-tenant gets literal ``shared``
    rather than empty, so a key is never ambiguous and a later multi-tenant
    instance cannot collide with pre-existing objects.
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
    """Identity of the requested bytes, as a storage path segment.

    Includes ``table_name`` (a replace swaps the physical table) and
    ``dataset_title`` (becomes the GPKG layer name). ``tile_cache_version`` is
    keyed here rather than checked at freshness time: a missed bump then only
    costs bounded staleness, not a wrong download. ``None``/``""`` stay
    distinct through the JSON encoding (#1546).
    """
    # #1585: two segments (URL identity, then version) so every artifact of
    # one URL shares a prefix for `url_answered_other_bytes_recently`.
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

    #1585: bounds bare ranges — a client reading an earlier representation
    that returns within its first TTL gets a whole answer instead. Scoped to
    the URL's own versions; fails CLOSED on a listing error.
    """
    # #1585 r5: two TTLs — one for the artifact's own freshness, one for the
    # client's window to return for a full answer.
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
    """``{built_at}-{size}-{digest}-{nonce}.bin`` — an artifact's whole metadata.

    ``built_at`` makes freshness/reclamation pure functions of the name,
    ``size`` detects truncation, ``digest`` is the strong ETag. ``nonce`` makes
    the key WRITER-OWNED (fix(#1532)): without it, two builders finishing in
    the same second shared a key and one's ``_discard`` deleted the other's
    live object.
    """
    nonce = uuid.uuid4().hex[:12]
    return (
        f"{_selection_prefix(dataset_id, selection)}"
        f"{int(built_at)}-{size}-{digest}-{nonce}.bin"
    )


def parse_artifact_key(key: str) -> tuple[float, int, str] | None:
    """``(built_at, size, digest)`` from a key, or None if not one of ours.

    Callers must leave a None alone: acting on a parse failure is how a
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
    """Build time of a ``.tmp`` scratch file, or None if not one.

    fix(#1532): ``LocalStorageProvider.put`` writes then renames, so a
    SIGKILL leaves this behind; aged from the stamp of the key it targeted.
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
    """Newest usable artifact for this selection, or None.

    "Usable" = published inside the TTL, not future-stamped, and intact (size
    verified via one ``size()`` call, so an in-place-truncated ``put`` is a
    miss rather than a served truncation). ``contested`` reports >1 distinct
    digest among siblings. Every failure here is a miss.
    """
    now = time.time()
    cutoff = now - _ttl_seconds()
    horizon = now + _CLOCK_SLACK_SECONDS
    # fix(#1532): freshness measures from modified time (put
    # completion, via `_published_at`) so a slow upload can't expire early.
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
        # fix(#1532): counts EVERY sibling, not just fresh ones — an old
        # sibling lives until the horizon and a client may still read it.
        siblings.add(digest)
        if built_at > horizon:
            # A future-stamped key would outrank every honest sibling below.
            continue
        published_at = _published_at(modified.get(key, built_at), built_at)
        if cutoff <= published_at:
            candidates.append((built_at, size, digest, key))

    # A selection with two distinct artifacts serves no ranges until sweep
    # clears the older; If-Range requests are already safe.
    contested = len(siblings) > 1

    for built_at, size, digest, key in sorted(candidates, reverse=True):
        try:
            if await storage.size(key) != size:
                # Truncated/altered object: skip rather than serve it.
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
    """When this artifact became readable, bounded by the key naming it.

    fix(#1532): ``built_at`` floors it (a store clock behind the
    writer would expire artifacts at birth); ``built_at + _MAX_PUBLISH_SECONDS``
    ceils it (a store ahead over-reports); the stamp is also pre-clamped by the
    same allowance (a writer clock ahead would otherwise pin an unreclaimable
    object). Pure function of the object — never reads ``now`` — so a verdict
    only moves fresh to expired.
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

    ``snapshot_at`` becomes the key's stamp (fix(#1532)); None means now.
    Returns the published artifact, or the INCUMBENT under this selection if
    one already exists (r29: caller must serve that, not its own bytes, so a
    later bare Range resolves the same representation), or None. Only
    ``Exception`` is caught — a ``CancelledError`` must propagate.
    """
    global _last_sweep_at
    try:
        if digest is None or size is None:
            digest, size = await digest_and_size(file_path)
        # fix(#1532): an artifact that appeared mid-conversion wins; the
        # caller must serve IT so later Range requests resolve consistently.
        incumbent = await lookup(
            dataset_id, selection, filename=filename, media_type=media_type
        )
        if incumbent is not None:
            return incumbent
        # fix(#1532): reclaim BEFORE the budget check/write — this is
        # the only prod sweep call; an early exit above it deadlocks a full
        # store.
        await _sweep_occasionally()
        if not await _fits_in_budget(size):
            # Cadence guard may have skipped sweeping; force one and recheck.
            await sweep()
            _last_sweep_at = time.time()
            if not await _fits_in_budget(size):
                logger.warning("export_cache_budget_exhausted", size=size)
                # r29: a publisher may have landed since the re-check above —
                # same lost race, one step later, same answer.
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
        # fix(#1532): PUBLICATION IS FINAL — a post-write re-check could
        # delete a key another request already resolved, truncating its
        # stream.
        return ExportArtifact(
            key=key,
            digest=digest,
            size=size,
            built_at=built_at,
            filename=filename,
            media_type=media_type,
        )
    except Exception:  # broad: caching is best-effort; the conversion succeeded
        # A failed store is the signal to sweep again sooner than cadence.
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

    fix(#1532): forces an unconditional sweep on failure and retries once
    — not a loop, since an unfreed horizon means the store holds something
    this cache doesn't own. fix(#1532): every attempted key is deleted on
    failure, since a fresh-stamped partial can't be reclaimed by sweep rules.
    """
    global _last_sweep_at
    attempted: list[str] = []

    async def _write() -> tuple[float, str]:
        # Stamp is the caller's snapshot time (r25), unchanged on retry: the
        # bytes aren't newer for having failed to upload once.
        key = _artifact_key(dataset_id, selection, digest, size, built_at)
        attempted.append(key)
        with open(file_path, "rb") as handle:
            await get_storage().put(key, handle)
        return built_at, key

    # fix(#1532): BaseException outside, Exception inside — discard must run
    # on ANY exit (CancelledError included) but retry only on Exception.
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

    Best-effort; a missing key is expected (atomic providers leave nothing).
    Must never raise — it runs on an already-failing path whose caller has a
    working conversion to fall back on.
    """
    storage = get_storage()
    for key in keys:
        try:
            await storage.delete(key)
        except Exception:  # broad: an absent or unremovable key is the sweep's job
            logger.debug("export_artifact_discard_failed", key=key, exc_info=True)


async def _fits_in_budget(size: int) -> bool:
    """Would publishing ``size`` more bytes keep the cache under budget?

    A SOFT ceiling (fix(#1532)): ``StorageProvider`` can't claim space,
    so concurrent publishers may each overshoot by one artifact for up to one
    horizon. Fails OPEN on an unreadable listing.
    """
    # fix(#1532): checked before the listing (outside fail-open) because
    # an empty prefix yields no page, letting any size through on a cold cache.
    if size > _BUDGET_BYTES:
        return False
    # fix(#1532): paged and stops at first overrun, bounding work by
    # budget rather than by a caller-controlled object count.
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

    Public: the route calls it BEFORE ``store`` (fix(#1532)) since the
    digest validates regardless of publication. Runs off the event loop —
    hashing a multi-GB file inline would stall every other request.
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

    Rides a build rather than a startup hook, since the worker's export sweep
    runs before ``init_storage``. Failures are swallowed.
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
    """Reclaim what nothing can still be reading. Returns keys removed.

    An object goes when its publication — floored at its own key's stamp,
    raised by ``last_modified`` (r10) — is past the horizon. An aged key can
    never become fresh, so no judgement depends on a read another worker can
    invalidate. Paged, so the cache is never materialized in memory.
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
                # fix(#1532): ages from the LATER clock, via the same
                # bound freshness uses, so a store clock ahead can't push it
                # out.
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

    # fix(#1532): pruned HERE, not in the generic delete, where an
    # unrelated writer's `mkdir` could race the `rmdir`. Duck-typed — object
    # stores have no directories; `storage` is None if get_storage() raised.
    prune = getattr(storage, "prune_empty_dirs", None)
    if prune is not None:
        try:
            await prune(f"{_ROOT}/")
        except Exception:  # broad: housekeeping, never a request failure
            logger.warning("export_cache_prune_failed", exc_info=True)
    return removed
