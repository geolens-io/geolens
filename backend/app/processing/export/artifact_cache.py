"""A stable stored artifact behind ``GET /datasets/{id}/export`` (fix(#1532)).

The route used to run a fresh conversion on every request, including every range
request. It advertises ``Accept-Ranges: bytes``, so one ``/vsicurl/`` open cost
roughly ten conversions — and, whenever the data moved under them, ten different
artifacts served under one URL, with two probes reporting different total sizes.

This module is the other half of the fix: the conversion output is stored once
and every subsequent range is a slice of that one object.

Everything is in the key
------------------------
An artifact is named ``{built_at}-{size}-{digest}-{nonce}.bin`` and there is
nothing else — no pointer, no index, no metadata object. Lookup lists the
selection's prefix and takes the newest key still inside the freshness window;
publishing is one ``put``; the sweep deletes any key past the horizon. Nothing is
ever rewritten, so there is no flip to race and no read-decide-delete to lose.
(Freshness and reclamation also read the object's own modified time, for
reasons ``lookup`` and ``sweep`` give; the key remains the portable floor.)

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
forces. A missed bump costs bounded staleness, not a wrong answer: an artifact
answers for one TTL after publication, its key is stamped with the moment the
conversion took its snapshot of the data, and publication is placed no later
than ``_MAX_PUBLISH_SECONDS`` after that stamp (fix(#1532 review r25)) — so a
request served from the cache sees data at most TTL plus that ceiling old, and
a conversion plus upload that outlives the ceiling produces an artifact no
request will use. That inversion is the whole design: the audited list is an
optimization by construction rather than by promise.

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

# fix(#1532 review, internal): how far into the future a key's timestamp may sit
# before this refuses to serve it. Small, because it exists to tolerate ordinary
# NTP jitter between workers rather than to accommodate a broken clock: a
# genuinely future-stamped artifact stays fresh for the TTL PLUS the skew and
# unreclaimable for the horizon plus the skew, and it outranks every honest
# sibling because the newest wins.
_CLOCK_SLACK_SECONDS = 5

# fix(#1532 review r23, then r25): the longest a conversion and its upload can
# take and still have a client waiting for the response they precede.
# `frontend/nginx.conf` closes the request at `proxy_read_timeout 600s`, and
# both run before the first response byte, so a publication that outlives this
# has already lost its request. It is the ceiling on how far past its key stamp
# — the conversion's snapshot time — an artifact's publication may be placed
# (see `_published_at`), which bounds a store clock running ahead AND how old
# the data behind a served artifact can be. Not a settings field: it restates
# an edge fact, and raising it widens the staleness bound.
_MAX_PUBLISH_SECONDS = 600

# fix(#1532 review, internal): the ceiling on what this cache may hold.
#
# On the local backend `_ROOT` sits inside `settings.upload_staging_dir` — the
# same volume `export_dataset` writes its conversions to and every ingest stages
# uploads on. Before this cache those export bytes were transient; retaining a
# copy of every distinct selection for a horizon turns a few large exports into a
# volume that has no room for the next conversion. Filters are caller-controlled,
# so "a few large distinct selections" needs no adversary — five bbox tiles of a
# multi-gigabyte dataset will do it.
#
# 8 GiB: enough for the case the cache exists for (one client range-reading one
# export, plus its neighbours) and small enough to leave an ordinary staging
# volume room to work. An absolute number rather than a fraction of the volume,
# because the provider protocol reports no capacity and a fraction of an
# unknowable whole is not a bound.
_BUDGET_BYTES = 8 * 1024 * 1024 * 1024

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
    # fix(#1532 review, internal): more than one DISTINCT set of bytes was fresh
    # under this selection when the lookup ran, so a client reading in slices
    # can be handed a different one between two requests and splice them.
    #
    # Nothing prevents two artifacts inside one TTL: every client that arrives
    # during a slow build misses and builds its own, and the herd repeats at each
    # window boundary. The bytes differ whenever the format is GPKG — the default,
    # whenever a write landed without moving `tile_cache_version`. So "a
    # forgotten bump costs one TTL of staleness" was really "a forgotten bump
    # plus overlapping builders costs a silent splice".
    #
    # fix(#1532 review r12): GeoPackage used to be the other source of distinct
    # bytes, because ogr2ogr stamped `gpkg_contents.last_change` per conversion —
    # which made the DEFAULT format permanently contested under steady traffic
    # and meant it never served a range at all. `normalize_gpkg_timestamps` fixed
    # the input rather than this rule: unchanged data now hashes the same twice,
    # so only a genuine change contests a selection, which is the case that
    # SHOULD refuse ranges.
    #
    # The caller answers ranges with the complete representation while this is
    # set. HEAD and the ETag are unaffected: each artifact is still internally
    # consistent, and a whole-object read of either is a correct answer.
    contested: bool = False

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
        return strong_etag(self.digest)


def strong_etag(digest: str) -> str:
    """The quoted strong entity-tag for a set of export bytes.

    fix(#1532 review r18): one place, because two responses now name bytes by
    digest — the stored artifact through ``ExportArtifact.etag``, and the
    conversion served directly when publication does not happen. A validator
    formatted twice is one that can drift.
    """
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
    TTL already forces. A writer that forgets costs bounded staleness (the
    module docstring states the bound); a
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
    # Two path segments, deliberately (fix(#1532) follow-up, #1585): the URL's
    # identity first, then the version's. `format`, `target_crs`, `bbox` and
    # `where` are what a client can see in the URL it is reading; `table_name`,
    # `dataset_title` and `tile_cache_version` are the server-side facts that
    # move the bytes under that same URL. Every artifact of one URL, at every
    # version, therefore lives under one prefix, and
    # `url_answered_other_bytes_recently` can ask "has this URL answered with
    # different bytes inside the last TTL" with one listing. `lookup`, `store` and the sweep are
    # indifferent to the shape: they take the whole thing as an opaque prefix.
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

    fix(#1532) follow-up (#1585): the bound on bare ranges. A client that read
    a block of an earlier representation of this URL and comes back for the
    next one — to a hit on the new artifact, to a fresh build of it, or
    re-reading the header — makes that request within the change's first TTL,
    and for that TTL the route answers it whole. Answering requires a fresh
    artifact, and a fresh artifact is one published within the TTL, so "the
    URL answered other bytes recently" is exactly "an artifact with another
    digest was published under this URL within the last TTL" — at any version,
    which is why every version of a URL shares a prefix (``selection_key``).
    A→B→A within retention is caught by the same test: while B is still being
    answered, B artifacts keep being published, and the moment they stop the
    clock starts. Same bytes cannot splice and do not count. After the TTL a
    client holding a handle across a longer gap without ``If-Range`` is the
    residual every range-serving origin has.

    Bounded: the URL's own versions, not the dataset's selections, and called
    only for a request that could receive a 206 (a bare, satisfiable Range).
    Fails CLOSED on a listing error: an unknown history reads as a recent
    change, and the client gets the whole file, which is safe.

    The parent revision of #1582 wrote a single-segment layout that lives
    outside every URL prefix. Nothing can be served from it after this
    revision (``lookup`` never lists it), no release wrote it, and retention
    ages it out; the exposure is a client spanning both the upgrade and a data
    change, and it is stated rather than paid for on every range.
    """
    cutoff = time.time() - _ttl_seconds()
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

    Each part earns its place. ``built_at`` makes every freshness and
    reclamation decision a pure function of the name, so no judgement depends on
    a read another worker can invalidate. ``size`` detects a truncated object on
    a provider that writes in place. ``digest`` is the strong ETag.

    ``nonce`` makes the key WRITER-OWNED, which the first three do not
    (fix(#1532 review, internal)). ``built_at`` is whole seconds, so two builders
    of a deterministic format finishing in the same second computed the same key
    — and then a failed write on one of them called `_discard` on a key the
    OTHER had just published successfully, deleting a live object out from under
    readers who were already past their response headers. A writer can only ever
    clean up its own attempts now.

    Two builders with identical bytes therefore leave two objects carrying one
    ETag, which is harmless: they are byte-identical by construction, the newer
    answers, and the horizon reclaims the other.
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

    fix(#1532 review, internal): ``LocalStorageProvider.put`` writes to
    ``<key>.<hex>.tmp`` and renames, so a SIGKILL, an OOM or a power loss leaves
    that scratch file behind. ``parse_artifact_key`` answers None for it, every
    caller reads None as "leave it alone", and it leaked onto the shared staging
    volume permanently.

    Aged from the ``<stamp>`` of the artifact key it was going to become: a write
    that started more than a horizon ago and never renamed is not going to.
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

    "Usable" means inside the TTL and intact. Both are decided from the key plus
    one ``size()``, so a request that goes on to transfer bytes has already
    learned its Content-Length.

    The size check is not belt-and-braces. ``LocalStorageProvider.put`` streams
    to the destination, so a process killed mid-copy leaves a truncated file at
    the final key, and taking the newest key without verifying it would serve
    that truncation to every reader until the horizon. Comparing against the size
    the key claims turns it into a miss and a rebuild.

    fix(#1532 review, internal): the returned artifact says whether the fresh
    set was CONTESTED — more than one distinct digest inside the window. See
    ``ExportArtifact.contested``; the caller turns it into "answer ranges with
    the whole thing".

    A future-stamped key is unusable. A worker whose clock runs ahead writes one
    that stays fresh for the TTL plus the skew and unreclaimable for the horizon
    plus the skew, and it outranks every honest sibling because the newest wins.
    Ignoring it costs a rebuild; trusting it costs correctness for as long as the
    skew lasts.

    Every failure here is a miss. This is a cache in front of a conversion that
    still works, so a storage hiccup should cost a rebuild, not the download.
    """
    now = time.time()
    cutoff = now - _ttl_seconds()
    horizon = now + _CLOCK_SLACK_SECONDS
    # fix(#1532 review r9): freshness is measured from the object's own modified
    # time, which every backend reports as COMPLETION time — S3 and Azure use
    # the put's completion, and locally it is the temp file's last write, since
    # the atomic rename preserves it. The key's stamp is taken BEFORE the
    # upload, so a multi-gigabyte push to an object store spent the whole TTL
    # getting there and the artifact was expired the moment it existed: the next
    # probe missed and reconverted, defeating the cache for exactly the exports
    # big enough to need ranges.
    #
    # The key keeps its stamp, and reclamation keeps using it — that decision is
    # about whether anything could still be reading, it must be portable, and it
    # must not depend on a value a backend could revise.
    #
    # The honest bound: an artifact can be up to TTL plus its own upload
    # duration old, the upload duration capped at `_MAX_PUBLISH_SECONDS` (r23:
    # `_published_at` bounds the store's clock by the key, both ways). That is
    # inherent rather than a compromise — bytes cannot answer before they
    # exist, and a client pulling a ten-gigabyte export is spending that long
    # anyway — and `tile_cache_version` in the selection key still invalidates
    # a known mutation instantly.
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
        # fix(#1532 review r8): `contested` counts EVERY sibling under this
        # selection, not just the fresh ones. Computed over the fresh set it
        # missed the staggered case entirely: two builders a second apart are
        # both inside the window at first, so ranges are correctly refused —
        # and then the older one crosses the TTL, the fresh set holds one
        # digest, `contested` flips false, and a bare-Range client that started
        # on the older artifact resumes into a 206 of the newer. The silent
        # splice, arriving late.
        #
        # Old siblings are exactly the ones a client can still be reading: they
        # live until the horizon by design, so a reader that resolved one keeps
        # streaming it. Freshness answers "may this serve a NEW request"; this
        # question is "could anyone be part-way through a different one".
        siblings.add(digest)
        if built_at > horizon:
            # A key stamped in the future, from a worker whose clock runs ahead.
            # fix(#1532 review r9) moved FRESHNESS onto the object's modified
            # time, which comes from the backend rather than that worker and so
            # is no longer fooled — but the ordering below still sorts on the
            # key's stamp, so a future one would outrank every honest sibling
            # for as long as the skew lasts. Skipping it costs a rebuild.
            continue
        published_at = _published_at(modified.get(key, built_at), built_at)
        if cutoff <= published_at:
            candidates.append((built_at, size, digest, key))

    # The cost, stated: a selection that ever had two distinct artifacts serves
    # no ranges until the sweep clears the older, which is up to a horizon. Only
    # bare-Range clients pay it — anything sending If-Range is already safe
    # through the strong ETag — and the pre-publish re-check keeps a second
    # artifact rare in the first place.
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

    ``modified`` is the object's ``last_modified`` and comes from the STORE's
    clock; ``built_at`` is the key stamp, from the writer's. Freshness compares
    the result against this worker's cutoff, so a skew between the clocks moves
    the window, and this is what bounds it (fix(#1532 review r22, then r23)):

    - A store clock BEHIND the writer by more than the TTL made every artifact
      expired the moment it appeared, and every probe reconverted and uploaded
      it — the cache silently dead. Publication cannot precede the stamp the
      writer minted before uploading, so ``built_at`` is the FLOOR. Worst case
      is the pre-r9 rule, which is a cache that works.
    - A store clock AHEAD reports a publication later than it was. The CEILING
      is ``built_at`` plus the longest a build and its upload can take with a
      client still waiting: ``_MAX_PUBLISH_SECONDS``. Past that, a modified
      time carries no information about THIS artifact — the request that
      produced it has already been closed at the edge — so it is not trusted.
      (``built_at`` is the conversion's snapshot time since r25, so this also
      bounds how old the DATA behind a served artifact can be.)

    A pure function of the object, deliberately (r23). An earlier revision
    distrusted a modified time beyond ``now`` plus the jitter allowance and
    fell back to the stamp, which was right at first and wrong later: as
    ``now`` moved, the same immutable object crossed from expired back to fresh
    the moment its future mtime came within reach — stale bytes served well
    past the TTL, on a schedule set by the skew. Nothing here reads ``now``, so
    an artifact's verdict can only ever go fresh → expired.

    Symmetric, since fix(#1532 review r28): the STAMP is clamped to the store's
    modified time plus the same allowance before the floor and ceiling apply. A
    stamp more than the allowance after the store saw the bytes is a writer
    clock running ahead — a build cannot start after its own upload finished by
    more than one request budget — and left unclamped it pinned the object:
    ``lookup`` refused the future key, but the sweep floored publication at
    that future stamp and could not reclaim it until then plus the horizon,
    while its size counted against the budget and its digest kept the
    selection contested for as long as it lived. So neither clock may place
    publication more than ``_MAX_PUBLISH_SECONDS`` from the other, in either
    direction, and every input remains immutable per object.

    Honest bound, restated: the data behind a served artifact is at most TTL
    plus ``min(build + upload, _MAX_PUBLISH_SECONDS)`` old under honest clocks;
    a store clock ahead, or a writer clock ahead, can add at most the unused
    part of that allowance. A store behind the fleet by more than the allowance
    plus the TTL makes every artifact expired at publication — a cache that
    does not serve rather than one that serves stale — and that store is
    within a few minutes of refusing the fleet's requests altogether.
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

    ``snapshot_at`` is when the conversion read the data, and it becomes the
    key's stamp (fix(#1532 review r25)). The stamp used to be minted just before
    the upload, so a mutation that missed ``tile_cache_version`` and landed
    during a long conversion produced an artifact that was stale at birth and
    then aged from a point AFTER the staleness began. Stamping the snapshot
    makes ``built_at`` mean what its name says, and the publish ceiling in
    ``_published_at`` then bounds build plus upload rather than upload alone.
    None means now, for callers that convert and store in one breath.

    ``digest`` and ``size`` may be supplied by a caller that has already run
    ``digest_and_size`` — the route does, so the validator it evaluates
    preconditions against exists whether or not this publishes (fix(#1532
    review r18)). Left out, they are computed here.

    Publishing is a single write to a key nothing else can be using, so two
    builders racing the same selection simply both succeed and readers take the
    newer. There is no pointer to flip, so there is no window in which a
    half-published state exists.

    Returns the published artifact; or, when publication does not happen, the
    INCUMBENT artifact under this selection if there is one (fix(#1532 review
    r29) — the caller must serve that, not its own bytes, so a client's later
    bare Range resolves the same representation); or None when there is nothing
    to serve but the caller's own file. The caller has the converted file in
    hand and can serve it directly, so a cache that cannot store must not be
    able to fail a download.

    Only ``Exception`` is caught, deliberately. A ``CancelledError`` is a
    ``BaseException`` and must keep propagating so the caller's cleanup runs —
    the same distinction fix(#1550) turned on. The caller owns the conversion
    directory until a response takes it, and swallowing a cancel here would leave
    it stranded.
    """
    global _last_sweep_at
    try:
        if digest is None or size is None:
            digest, size = await digest_and_size(file_path)
        # fix(#1532 review, internal): do not publish if a fresh artifact has
        # appeared while this request was converting. Every client arriving
        # during a slow build misses and builds its own, so the overlap is the
        # normal case rather than a rare one, and each extra publication is
        # another set of bytes a range-reading client can be flipped onto.
        #
        # fix(#1532 review r29, P1): and hand that INCUMBENT back, so the caller
        # serves it rather than its own conversion. Returning None here had the
        # caller stream its own bytes whole — which, when the two builders had
        # taken different snapshots (a mutation that missed `tile_cache_version`
        # landing between them), put a client on bytes no later request would
        # resolve: an interrupted download resumed with a bare Range against the
        # sole, uncontested incumbent and was handed a 206 of the OTHER
        # conversion at its offsets. Serving the incumbent keeps every response
        # under this selection on the artifact the next Range will find. The
        # losing conversion is discarded; it published nothing and adds nothing.
        incumbent = await lookup(
            dataset_id, selection, filename=filename, media_type=media_type
        )
        if incumbent is not None:
            return incumbent
        # And do not publish past the byte budget. The local root IS the shared
        # staging volume that `export_dataset` and every ingest writes to, and
        # before this cache those export bytes were transient; retaining them for
        # a horizon means a handful of large distinct selections can block every
        # conversion and upload on the instance. r4's reclaim-and-retry only
        # frees AGED artifacts, so a volume filled with FRESH ones has nothing to
        # give back — the budget is what keeps that from happening at all.
        #
        # fix(#1532 review r4): reclaim BEFORE writing, not after. This is the
        # only production call to the sweep, so a `put` that raises on a full
        # store used to exit before it — and with nothing else sweeping
        # `export-cache/`, the aged artifacts that filled the volume could never
        # be reclaimed by a later request. Caching stayed dead, and on the local
        # backend the shared staging volume stayed too full to generate larger
        # exports at all, until an operator deleted files by hand.
        #
        # fix(#1532 review r6): and reclaim before the BUDGET CHECK, not after.
        # The check was an early return sitting above the sweep, so once claimed
        # sizes reached the ceiling every later publication left before the only
        # thing that reclaims could run — and once those artifacts passed the
        # horizon, nothing was ever going to. The exact deadlock r4 fixed for
        # ENOSPC, re-created by a new early exit above the same sweep.
        await _sweep_occasionally()
        if not await _fits_in_budget(size):
            # The cadence guard means the sweep above may not have run at all,
            # so a budget that looks exhausted has not necessarily been tested
            # against the horizon yet. Force one pass and ask again — the same
            # shape `_put_with_reclaim` uses, and for the same reason.
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
        # fix(#1532 review r7): PUBLICATION IS FINAL. A post-write re-check that
        # dropped this artifact when the total had moved lived here for one
        # round, and it could delete a key another request had already resolved
        # through `lookup` — that response has declared a Content-Length and is
        # about to open its stream, so the delete truncates it. Trading an
        # overshoot for a truncated download is the wrong direction, and the
        # overshoot is bounded anyway. See `_fits_in_budget` for the contract.
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
        # r29: same reasoning as the budget exit. `lookup` never raises — a
        # store that cannot even list answers None, and the caller falls back to
        # its own bytes, which no incumbent can then contradict.
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

    fix(#1532 review r4): sweeping before the write is not enough on its own,
    because ``_sweep_occasionally`` is interval-guarded — a store that fills
    between two cadence ticks would fail without one having been attempted, and
    with nothing else sweeping ``export-cache/`` the volume stays full. So a
    failed write forces an unconditional sweep and tries once more, which makes a
    full store heal inside the request that hit it rather than fifteen minutes
    later.

    Once, not in a loop. If reclaiming everything past the horizon does not make
    room, the store is full of something this cache does not own and retrying is
    just a slower way to fail.

    fix(#1532 review r5): every key this function attempts is deleted if its
    write fails, and that is the difference between a failure and a leak. A
    partial carries a FRESH timestamp, so the forced sweep cannot reclaim it — it
    is young by every rule this module has — and the retry would then fail for
    the same reason the first attempt did, on a volume the first attempt made
    worse. Two attempts, two partials, and the space held for the whole horizon.

    ``LocalStorageProvider.put`` is atomic now, so on the shipped backends a
    failed write leaves nothing to delete and these calls are belt-and-braces.
    They are here because this module cannot see which provider it has, and
    because a cleanup that only runs on the backends known today is one a new
    backend silently opts out of.
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

    # fix(#1532 review, internal): BaseException on the outside, Exception on
    # the inside. A CancelledError — a client disconnect, a worker shutdown — is
    # not an Exception, so the first write's failure arm did not see it: it
    # skipped the retry (correctly, a cancelled request wants no retry) AND the
    # discard (not correctly, the attempt it made may have landed). The local
    # provider is atomic now so its final key is safe either way, but a
    # non-atomic backend keeps the partial, and even locally the scratch file's
    # removal depends on `put` seeing the cancel itself rather than on anything
    # here.
    #
    # So: clean up on ANY exit, retry only on the ones a retry can help.
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

    Free to compute: every artifact's size is in its own key, so the current
    total is a listing and some string parsing rather than a stat per object.

    A SOFT ceiling, and the contract is worth stating exactly (fix(#1532 review
    r6, then r7)).

    ``StorageProvider`` offers no way to claim space, so two publishers can
    measure the same total, both pass, and both write. The excess is therefore
    bounded by the number of concurrent publishers times one artifact each, and
    it lasts at most one reclamation horizon. It is not eliminated, and this is
    the only check: a post-write re-check that dropped the writer's own artifact
    was tried and withdrawn, because once ``put`` returns, ``lookup`` can hand
    that key to another request — which has declared a Content-Length and is
    about to open its stream, so deleting it truncates a download. An overshoot
    that expires is a better failure than a truncated file.

    Making it hard would need publication to become visible only after a check,
    which needs a rename primitive: S3 and Azure have no such thing short of a
    server-side copy, which for a multi-gigabyte export is not a cheap
    afterthought. A lock is the other answer and does not belong in this fix.

    Failing OPEN on an unreadable listing. The budget bounds a resource this
    cache borrows; a cache that refused to work whenever it could not measure
    itself would trade a bounded disk cost for an unbounded conversion one.

    """
    # fix(#1532 review r16): the ceiling on ONE artifact, checked before the
    # listing and outside the fail-open below.
    #
    # The running check lives inside the page loop, and a provider yields NO
    # page for an empty prefix — so on a cold cache the loop body never ran and
    # this returned True for an artifact of any size. The first export after a
    # deploy is exactly when the prefix is empty, and a single one larger than
    # the whole budget could publish, doubling the biggest conversion on the
    # shared staging volume rather than bounding it.
    #
    # It sits above the `try` as well, because whether one artifact exceeds the
    # entire budget is knowable without measuring anything. Failing open on an
    # unreadable listing is right for the running total, which is a comparison
    # against other objects; it is not right here.
    if size > _BUDGET_BYTES:
        return False
    # fix(#1532 review r11): paged, and stopped as soon as the answer is known.
    # This materialised the whole `export-cache/` listing on every publication,
    # and the prefix is caller-controlled — anonymous callers vary bbox and
    # where — so the inventory grew with the number of distinct selections in
    # the window and every publication paid for all of them. Accumulating page
    # by page and returning at the first overrun bounds the work by the BUDGET
    # rather than by the object count: at most one page beyond whatever fits.
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

    Public because the route calls it BEFORE ``store`` (fix(#1532 review r18)):
    the digest is the response's validator, and a client's ``If-Match`` or
    ``If-None-Match`` has to be answered from what was built even when
    publication does not happen — a full store, a lost race, an outage. Passed
    back into ``store`` so the file is hashed once.

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

    Ages come from the key's stamp as the portable floor, raised to the object's
    ``last_modified`` where the provider reports one (review r10 — the stamp is
    taken before the upload, and a slow push must not make a live artifact look
    aged). ``iter_object_pages`` supplies both, one page at a time — the whole
    cache is not materialized in memory to be swept (review r3).

    Well past the TTL because expiry and reclamation are different questions.
    Expiry asks whether an artifact may answer a NEW request; reclamation asks
    whether a request that started before expiry could still be streaming from
    it.
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
                # fix(#1532 review r10): age from the LATER of the two clocks.
                # The key's stamp is taken before the upload, so once freshness
                # moved onto `last_modified` the two diverged by however long the
                # push took — an S3 or Azure upload that consumed most of the
                # horizon could be reclaimed shortly after becoming visible,
                # while a client was streaming it, and one that exceeded the
                # horizon was eligible the moment it appeared.
                #
                # The key stamp stays as the portable floor (a backend that
                # reports no useful modified time still gets an answer) and
                # `last_modified` raises it to publication. Both are already in
                # hand here, and neither moves for a writer-owned key that
                # nothing copies.
                #
                # fix(#1532 review r24): through the SAME bound freshness uses.
                # An unbounded `max` let a store clock running ahead push the
                # age origin into the future, and an object then lived a full
                # horizon past a time that had not happened yet — the inventory
                # pinned at its ceiling and every later export forced onto the
                # uncached path. `_published_at` caps publication at the stamp
                # plus the publish ceiling, so the worst an ahead store can do
                # to reclamation is what it can do to freshness: at most that
                # allowance, once, per object.
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

    # fix(#1532 review r7): prune this prefix's empty directories HERE rather
    # than inside `StorageProvider.delete`. A filesystem keeps a directory after
    # its last file goes, an object store has none to keep, and the export cache
    # creates one per caller-controlled selection — so they accumulate and every
    # listing scandirs all of them. Doing it in the generic delete made an
    # unrelated writer's `mkdir` race this `rmdir`; doing it here confines the
    # pruning to the prefix this module owns, at the moment it knows a selection
    # is finished.
    #
    # Duck-typed rather than isinstance-checked: a provider with no directories
    # simply does not offer this, which is the honest way to ask. `storage` is
    # None if `get_storage()` itself raised above, and then there is nothing to
    # prune either.
    prune = getattr(storage, "prune_empty_dirs", None)
    if prune is not None:
        try:
            await prune(f"{_ROOT}/")
        except Exception:  # broad: housekeeping, never a request failure
            logger.warning("export_cache_prune_failed", exc_info=True)
    return removed
