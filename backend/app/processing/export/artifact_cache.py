"""A stable stored artifact behind ``GET /datasets/{id}/export`` (fix(#1532)).

The route used to run a fresh conversion on every request, including every range
request. It advertises ``Accept-Ranges: bytes``, so one ``/vsicurl/`` open cost
roughly ten conversions — and, whenever the data moved under them, ten different
artifacts served under one URL, with two probes reporting different total sizes.

This module is the other half of the fix: the conversion output is stored once
and every subsequent range is a slice of that one object.

Why freshness rests on a TTL and not on an invalidation list
------------------------------------------------------------
#1532 is explicit that the tempting fix is the dangerous one. Anything that lets
one request's range be answered from bytes another request built is only correct
if the cache is invalidated on *every* path that can change the exported bytes,
and this repository already has the cautionary example: ``bump_tile_cache_version``
is called from fourteen places and was designed for tile cache-busting, where a
missed call costs a stale tile. Keying export freshness on a hand-audited list
like that would make a missed call cost a *wrong download that looks right*,
which is strictly worse than the bug, because today's failure is loud (a spliced
GeoJSON dies with ``ERROR 4: Failed to read GeoJSON data``).

So correctness rests on ``_ttl_seconds()``, a property nobody can forget to
maintain: an artifact is usable for a bounded window and then it is not, whatever
anyone did or did not remember to call. The counter still earns its keep — it is
folded into ``selection_key``, where a bump moves the request to a different key
and invalidates instantly — but as a key input it can only ever invalidate MORE
often than the TTL already forces. A missed bump costs one TTL of staleness, not
a wrong answer. That inversion is the whole design: the audited list is an
optimization by construction rather than by promise.

A data-derived version (``count(*)`` plus ``max(xmin)`` over the selection) was
the other candidate and is rejected on cost, not on correctness: it is complete
for INSERT/UPDATE/DELETE, but ``max(xmin)`` has no index, so every range request
on the cache-HIT path would pay a sequential scan — 509 ms on the 5M-row table
#905 measured. Ten of those to save ten conversions is the wrong trade against a
timestamp comparison that costs nothing.

Who cleans up
-------------
One mechanism: the sweep. fix(#1532 review r1) removed an eviction-on-build step
that ran alongside it, because the two answered the same question with different
safety margins and the cheaper one was racy. Two builders publishing at once —
which for a non-deterministic format means two different objects — each computed
"everything but mine and the one I superseded" and deleted the other's, so the
surviving pointer could name a key that was already gone.

That was fixable by preserving more, but not worth keeping once the sweep had to
learn about orphans anyway: reclamation is exactly the question "could anything
still be reading this", it has one right answer (an age horizon well past any
download), and having two mechanisms answer it meant the stricter one was
deciding while the looser one was the one that mattered. So the horizon is the
only rule, and nothing deletes an object a request might still be streaming.

Why the artifact is content-addressed
-------------------------------------
The stored object is named by the SHA-256 of its own bytes, and a small pointer
object names the current one. Two concurrent builders are not a race to be locked
out of: for a deterministic format they compute the same digest and write the same
object, and for a non-deterministic one (GPKG stamps ``gpkg_contents.last_change``,
so its bytes differ between two conversions of identical data) they write two
different objects and one pointer flip picks a winner. Either way a reader that
resolved the pointer earlier keeps slicing an object that still exists, which is
the property a single mutable key cannot offer: there, the loser's write would
replace bytes a reader was midway through.
"""

import hashlib
import json
import time
import uuid
from dataclasses import dataclass

import structlog

from app.core.db.tenant_session import current_tenant_var
from app.platform.storage import get_storage

logger = structlog.stdlib.get_logger(__name__)

# The prefix every cached export lives under, so the sweep and the per-dataset
# invalidation both have one place to look and no other subsystem's objects can
# be reached by either.
_ROOT = "export-cache"

# How long a stored artifact may answer for. Deliberately short: this is the
# whole correctness guarantee (see the module docstring), so it is the bound on
# how stale a download can be, not a performance knob. Long enough to cover a
# /vsicurl/ open, which is seconds.
_DEFAULT_TTL_SECONDS = 60

# Sweep anything older than this. Larger than the TTL by a wide margin because a
# reader that resolved a pointer just before its artifact expired is still
# streaming from it, and deleting the object underneath a download is the one
# failure this module must not introduce.
_SWEEP_AGE_SECONDS = 3600


# How often one process will bother sweeping. The sweep is cheap next to the
# conversion it rides along with, and running it more often than this buys
# nothing: the objects it reclaims have been abandoned for an hour.
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
    """A stored export and everything a response needs to describe it."""

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

    def is_fresh(self, *, now: float | None = None) -> bool:
        ttl = _ttl_seconds()
        if ttl <= 0:
            return False
        return ((now if now is not None else time.time()) - self.built_at) < ttl


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


def _dataset_prefix(dataset_id: uuid.UUID) -> str:
    return f"{_ROOT}/{_tenant_segment()}/{dataset_id}"


def _pointer_key(dataset_id: uuid.UUID, selection: str) -> str:
    return f"{_dataset_prefix(dataset_id)}/{selection}/current.json"


def _artifact_key(
    dataset_id: uuid.UUID, selection: str, digest: str, built_at: float
) -> str:
    """``{built_at}-{digest}.bin``.

    fix(#1532 review r1): the timestamp is in the NAME because the sweep has to
    be able to age an object whose pointer never landed. An upload that succeeds
    and a pointer write that does not — a failed request, a process killed
    between the two — leaves a ``.bin`` no ``current.json`` mentions, and a sweep
    that derives every deletion from pointers leaks it forever. Multi-gigabyte,
    for a one-off bbox export nobody repeats.

    ``StorageProvider`` exposes no modified time, and adding one is a port
    signature change, so the object carries its own age. The digest stays in the
    name: it is still what makes the object content-addressed and it is still the
    ETag.
    """
    return f"{_dataset_prefix(dataset_id)}/{selection}/{int(built_at)}-{digest}.bin"


def _key_built_at(key: str) -> float | None:
    """The build time encoded in an artifact key, or None if it has none.

    None means "not one of ours" and the sweep leaves it alone. A key it cannot
    date is a key it cannot prove is abandoned, and deleting on a parse failure
    is how a sweep turns a naming change into data loss.
    """
    name = key.rsplit("/", 1)[-1]
    stamp, _, rest = name.partition("-")
    if not rest.endswith(".bin") or not stamp.isdigit():
        return None
    return float(stamp)


async def lookup_raw(dataset_id: uuid.UUID, selection: str) -> ExportArtifact | None:
    """Whatever the pointer names, with no freshness or existence judgement.

    Only ``store`` wants this, to learn which object it is superseding so
    eviction can spare one generation for readers already streaming it. Requests
    go through ``lookup``.
    """
    try:
        pointer = json.loads(
            await get_storage().get(_pointer_key(dataset_id, selection))
        )
        return ExportArtifact(
            key=pointer["key"],
            digest=pointer["digest"],
            size=int(pointer["size"]),
            built_at=float(pointer["built_at"]),
            filename=pointer["filename"],
            media_type=pointer["media_type"],
        )
    except Exception:  # broad: any unreadable/absent/corrupt pointer is "none"
        return None


async def lookup(dataset_id: uuid.UUID, selection: str) -> ExportArtifact | None:
    """The current artifact for this selection, or None if there is not a usable one.

    "Usable" means the pointer resolves, it is inside the TTL, AND the object it
    names still exists. The last check is not paranoia: eviction and the sweep
    both delete artifacts, and a pointer whose object is gone must read as a miss
    and rebuild rather than produce a 404 for a resource that plainly exists.

    Every failure here is a miss. This is a cache in front of a conversion that
    still works, so a storage hiccup should cost a rebuild, not the download.
    """
    artifact = await lookup_raw(dataset_id, selection)
    if artifact is None or not artifact.is_fresh():
        return None
    try:
        if not await get_storage().exists(artifact.key):
            return None
    except Exception:  # broad: same reasoning as above
        return None
    return artifact


async def store(
    dataset_id: uuid.UUID,
    selection: str,
    *,
    file_path: str,
    filename: str,
    media_type: str,
) -> ExportArtifact | None:
    """Publish a freshly converted file as this selection's current artifact.

    Digest first, then the object, then the pointer. That order is what makes a
    crash safe in the only direction that matters: a published pointer always
    names bytes that are already there, while an orphaned object with no pointer
    is invisible and the sweep reclaims it.

    Returns None if anything goes wrong. The caller has the converted file in
    hand and can serve it directly, so a cache that cannot store must not be able
    to fail a download.
    """
    try:
        digest, size = await _digest_and_size(file_path)
        built_at = time.time()
        key = _artifact_key(dataset_id, selection, digest, built_at)
        storage = get_storage()
        with open(file_path, "rb") as handle:
            await storage.put(key, handle)
        artifact = ExportArtifact(
            key=key,
            digest=digest,
            size=size,
            built_at=built_at,
            filename=filename,
            media_type=media_type,
        )
        await storage.put(
            _pointer_key(dataset_id, selection),
            json.dumps(
                {
                    "key": artifact.key,
                    "digest": artifact.digest,
                    "size": artifact.size,
                    "built_at": artifact.built_at,
                    "filename": artifact.filename,
                    "media_type": artifact.media_type,
                }
            ).encode(),
        )
        await _sweep_occasionally()
        return artifact
    except Exception:  # broad: caching is best-effort; the conversion succeeded
        logger.warning(
            "export_artifact_store_failed",
            dataset_id=str(dataset_id),
            exc_info=True,
        )
        return None


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
    object store. The cost is a listing next to an ogr2ogr run.

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

    The only reclamation path (fix(#1532 review r1); see the module docstring for
    what was removed and why). Three populations, because they go stale for
    different reasons:

    - **Abandoned selections.** Nobody has rebuilt this selection in an hour, so
      its pointer and its artifact both go.

    - **Superseded artifacts.** A rebuild publishes a new object and leaves the
      previous one unreferenced. It is kept until the horizon so a reader that
      resolved the old pointer can finish.

    - **Orphans.** An upload that succeeded while its pointer write did not
      leaves a ``.bin`` no pointer mentions. Deriving every deletion from
      pointers, as the first revision did, leaked those forever.

    **Every judgement is per KEY, and none is per prefix** (fix(#1532 review r2)).
    An earlier revision read a selection's pointer, found it older than the
    horizon, declared the whole prefix stale and deleted everything under it.
    On a multi-worker deployment that removes the young artifact another worker
    uploaded moments ago and the pointer it published — so the request that was
    publishing streams a missing key, and the next lookup rebuilds what was
    already there. It is r1's eviction bug one level up: one actor's cleanup
    deleting another actor's truth, this time on the strength of a neighbouring
    key's age.

    The rule is chosen so a concurrent publish cannot satisfy it, which is what
    makes this race-free without a lock rather than merely narrow: an artifact
    goes when the timestamp IN ITS OWN NAME is past the horizon. A publish mints
    its key from ``time.time()``, so an aged key can never become fresh and a
    fresh one can never look aged. Nothing else is consulted, so there is no read
    that can be stale by the time the delete runs.

    **Pointers are never deleted.** Reclaiming one means reading it, deciding it
    is dead, and then deleting it, and a publish landing in that window loses the
    pointer it just wrote — the same shape as the bug this rule closes, moved
    into the check meant to be safe. Two attempts at narrowing that window are in
    this file's history; neither closes it, because ``StorageProvider`` offers no
    compare-and-delete and nothing else can make a read-then-delete atomic.

    Leaving them costs one JSON of a few hundred bytes per selection that is
    never rebuilt, and nothing else: a pointer whose artifact this sweep removed
    reads as a miss through ``lookup``, which is the behaviour it already had for
    an expired one. Reclaiming them needs a conditional delete on the provider
    protocol, which is a port signature change and a decision of its own.

    Ages come from the artifacts and pointers themselves rather than from object
    mtime, which is what makes this portable: ``StorageProvider`` exposes no
    modified time, S3 and the local provider would answer differently if it did,
    and a copy resets it.

    An hour rather than the TTL because expiry and reclamation are different
    questions. Expiry asks whether an artifact may answer a NEW request;
    reclamation asks whether a request that started before expiry could still be
    streaming from it.
    """
    storage = get_storage()
    cutoff = time.time() - age_threshold_seconds
    try:
        keys = await storage.list(f"{_ROOT}/")
    except Exception:  # broad: a sweep that cannot list is a no-op, not an error
        logger.warning("export_cache_sweep_list_failed", exc_info=True)
        return 0

    removed = 0
    for key in keys:
        if key.endswith("current.json"):
            continue
        built_at = _key_built_at(key)
        if built_at is not None and built_at < cutoff:
            removed += await _delete(storage, key)
    return removed


async def _delete(storage, key: str) -> int:
    try:
        await storage.delete(key)
        return 1
    except Exception:  # broad: leave it for the next sweep
        logger.warning("export_cache_sweep_delete_failed", key=key, exc_info=True)
        return 0
