"""Stale-job recovery and sweep handlers (#1335 split from jobs/router.py).

The predicates that define "stale" for an ``IngestJob`` or a VRT
``RasterAsset``/``VrtGeneration``, the SQL that reconciles them, and the
staged-artifact reapers that clean up after a sweep — all shared by the
background lifespan sweeper (``app/api/main.py``), the worker's own startup
recovery (``worker.py``), and the admin cleanup endpoint that stays in
``router.py``.

``router.py`` imports what it needs from here and re-exports it, so every
name a caller previously imported from ``app.platform.jobs.router`` still
resolves from there.
"""

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, overload

import structlog
from sqlalchemy import (
    DateTime,
    and_,
    case,
    delete,
    func,
    not_,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import MAX_PRESIGNED_URL_LIFETIME_SECONDS, settings
from app.observability.metrics.refresh import refresh_sweep_reconciled_total
from app.platform.jobs.models import (
    EMBEDDING_BACKFILL_METADATA_KEY,
    FAN_OUT_INTERRUPTED_METADATA_KEY,
    STAGING_REAPED_FINAL_MARKER,
    STATUSES_NEEDING_STAGED_INPUT,
    IngestJob,
    owned_presigned_staging_key,
)
from app.platform.jobs.staging_reconcile import reconcile_orphaned_staging_objects
from app.platform.refresh.service import sweep_abandoned_refresh_runs
from app.platform.storage.titiler_url import resolve_current_storage_key

log = structlog.get_logger()

# Jobs running longer than this are considered stale and auto-failed. This is
# the worker LEASE on a RUNNING job, not the presigned-upload lifetime below:
# the two share a number today and answer unrelated questions, so deriving one
# from the other would only look like agreement.
JOB_TIMEOUT_SECONDS = 3600  # 60 minutes (accommodates remote service imports)

# fix(#1709 review r7 A): grace before a childless `fanned_out` parent is
# treated as a crashed dispatch. The flip->first-child gap is sub-second in
# health (claim_fan_out_parent commits, then the first create_fan_out_jobs
# commits), so one sweep cadence is generous, and a request still mid-flight
# is never touched.
FAN_OUT_CHILDLESS_GRACE_SECONDS = 300

# fix(#1709 review r8 A): the message must not advertise retry — generic
# /jobs/{id}/retry re-queues the parent as ONE default-layer import (the
# layer selection lived only in the fan-out request body), and retry is
# refused outright on the marker below. Re-upload is the real path.
FAN_OUT_DISPATCH_INTERRUPTED_MESSAGE = (
    "Fan-out dispatch was interrupted before any layer was queued. "
    "Re-upload the file to import its layers."
)


# fix(#1235 review r4): the margin between the last moment a client may still
# legitimately PUT and the moment its completion request has finished freezing,
# verifying and committing. Added on top of the upload lifetime wherever a
# timer has to sit strictly BEYOND it.
_COMMIT_HEADROOM_SECONDS = 3600


def stale_pending_cutoff_seconds(*, completion_bound: bool) -> int:
    """Age at which each half of the pending sweep may fail a job.

    fix(#1235 review r4): both halves read the one setting, at CALL time.
    #1234 made the pending lifetime configurable but left the consumers holding
    the numbers that used to be its fixed value. The 24h backstop was one of
    them: configure the timeout past a day and a legitimate completion at hour
    25 committed the frozen path into a row that was instantly eligible for its
    own backstop. Deriving it keeps the backstop strictly beyond the upload
    lifetime by construction, rather than by the accident that 86400 > 3600.

    Module-level constants would reproduce the same class one indirection down:
    a copy taken at import can disagree with the value the presign handlers
    read per request.
    """
    if completion_bound:
        return max(
            86400,  # 24h floor — preserves the default behaviour exactly
            settings.pending_job_timeout_seconds + _COMMIT_HEADROOM_SECONDS,
        )
    return settings.pending_job_timeout_seconds


# fix(#1235 review r4): the message no longer names an hour. The timeout is
# configurable, so a hard-coded "over 1 hour" is a claim the code stopped
# guaranteeing in #1234; "never queued" is the part that is always true.
STALE_PENDING_UNBOUND_MESSAGE = "Stale: pending too long (never queued)"
STALE_PENDING_BOUND_MESSAGE = "Stale: upload completed but never committed"


def stale_pending_clauses(now: datetime, *, completion_bound: bool) -> tuple:
    """Every predicate required to fail a timed-out pending job.

    fix(#1235 review r2): ONE boundary, because there are four sites that flip
    pending -> failed on a timeout and #1234 only guarded two of them. The
    background sweep was fixed; `get_job_status` — which the comment above it
    correctly calls "the path that actually fires", since the frontend polls
    every 2s — kept the old predicates, so a poll that blocked on a completing
    job's row lock resumed after the commit and failed the row it had just
    waited for. The worker's startup recovery had neither this guard nor the
    live-queue predicate.

    Returning the whole clause set rather than just the guard is the point: a
    caller cannot express "fail stale pending jobs" here without also getting
    the bound/unbound split and the live-queue check, so the next site added
    cannot forget them by being written carefully — only by not using this.

    `completion_bound` selects which half, and the class is defined by the
    `staging/` PREFIX rather than by file_path being merely truthy. That
    distinction is the point: the race being fixed involves exactly the rows a
    presigned completion has bound, and both doors bind
    `staging/{job}/frozen/...` — nothing else writes a staging-prefixed
    file_path on a pending row. Same discriminator #1213 established for the
    reapers, same reason.

    Defining the class as "truthy" instead swept in rows with nothing to do
    with the race: a direct upload whose dispatch failed binds an ABSOLUTE
    local path, and giving it the 24h backstop leaves it `pending` for a day —
    during which /jobs/{id}/retry is unavailable, because retry requires
    status `failed`. That turns a 1h-to-recoverable state into a
    24h-to-recoverable one on a real path.

    So False is the 1h abandonment policy and now covers everything that is
    not a completion — falsy file_path AND non-staging absolute paths (direct
    uploads, manifest operator keys), all keeping their original message.
    True is the 24h backstop for completions that bound but never committed:
    exempt from the 1h clause, and the retention purge only considers terminal
    rows, so without it they never die.
    """
    # coalesce, not a bare LIKE: `NOT (NULL LIKE ...)` is NULL, not TRUE, so a
    # bare negation silently drops every row whose file_path is NULL — the
    # "never bound anything" case that most needs the 1h policy. Three-valued
    # logic turns the guard into a filter that excludes what it should catch.
    completion_key = func.coalesce(IngestJob.file_path, "").like("staging/%")
    cutoff_seconds = stale_pending_cutoff_seconds(completion_bound=completion_bound)
    # fix(#1708 codex r6): pending age is measured from the last moment the
    # flow declared the artifact STAGED, falling back to creation. A URL
    # import spends up to FETCH_MAX_SECONDS downloading before its
    # running->pending CAS, with created_at unchanged — measured from
    # created_at, a local-mode staged import (absolute file_path, so the
    # unbound half) arrived pre-aged: at the 61s floor of
    # pending_job_timeout_seconds the very next sweep or get_job_status poll
    # failed it while the user was mid-preview. `staged_at` is stamped by
    # upload_from_url's completion CAS (always an isoformat timestamptz, the
    # only writer); every other flow lacks the key and keeps aging from
    # created_at exactly as before, so a genuinely abandoned pre-fetch row
    # is not softened. The window RESTARTS at staging, it does not become an
    # exemption — a staged row whose staged_at itself ages past the cutoff
    # is reaped like any other.
    age_basis = func.coalesce(
        IngestJob.user_metadata.op("->>")("staged_at").cast(DateTime(timezone=True)),
        IngestJob.created_at,
    )
    return (
        IngestJob.status == "pending",
        age_basis < now - timedelta(seconds=cutoff_seconds),
        completion_key if completion_bound else not_(completion_key),
        no_live_procrastinate_job(),
    )


# fix(#1556): the terminal state for a presigned upload nobody ever bound bytes
# to. `failed` claims an ingest was attempted and broke; for a visitor who
# presigned an upload and walked away, nothing was ever attempted, and on the
# public demo those rows are indistinguishable from real ingest failures in the
# admin jobs list and the failed-jobs badge that counts it. `cancelled` is
# already in the `ingest_jobs` status CHECK constraint, in the admin `JobStatus`
# literal and in openapi.json, so this needs no migration and changes no
# published contract.
ABANDONED_UPLOAD_MESSAGE = "Abandoned: upload was never completed"


def is_abandoned_presigned_upload(
    file_path: str | None, user_metadata: dict | None
) -> bool:
    """Python twin of ``abandoned_presigned_upload``, over one loaded row.

    Only the worker's startup recovery needs it: that site mirrors the UPDATE
    onto the returned ORM instances, and a plain ``job.status = "failed"``
    there would write the in-memory object back over the status the database
    just computed. Kept beside the SQL so the two are read as one rule.
    """
    return not file_path and bool((user_metadata or {}).get("presigned"))


def abandoned_presigned_upload():
    """Predicate: a presigned upload whose bytes were never bound.

    Deliberately narrower than "falsy ``file_path``". The unbound half of the
    pending sweep also reaps rows that DID have work attempted for them, and
    each of those must keep reporting `failed`:

    - a service/URL import (``source_url`` set, ``file_path`` empty) whose
      defer never landed. ``/jobs/{id}/retry`` requires status `failed`, and
      ``_retry_capability`` offers exactly that row, so cancelling it would
      take a recoverable job's only recovery path away — the same 1h-to-
      recoverable-becomes-unrecoverable trap #1235 avoided for absolute paths.
    - an analysis run or an admin embedding backfill, both of which carry
      ``file_path=""`` by construction. A dispatch that never landed is a real
      failure of something the user asked for, and #1550's audit trail settles
      the backfill `never_started` in the same transaction as the row.

    The ``presigned`` marker is what both presign doors stamp
    (``processing/ingest/router.py`` and ``datasets/api/router_reupload.py``)
    at the moment they hand a client a URL, so it names the one class where an
    empty ``file_path`` means "the client never came back". A completion binds
    ``staging/{job}/frozen/...`` and is therefore the BOUND half's business,
    never this one.
    """
    return and_(
        func.coalesce(IngestJob.file_path, "") == "",
        func.coalesce(IngestJob.user_metadata["presigned"].astext, "false") == "true",
    )


def stale_pending_unbound_values(now: datetime, *, message: str) -> dict:
    """Every column the unbound half of the pending sweep writes.

    The companion to ``stale_pending_clauses``, for the same reason it exists:
    three sites flip an unbound pending row terminal — the background sweep,
    `get_job_status` (the one that actually fires, polled every 2s) and the
    worker's startup recovery — and a split expressed in the ACTION at one of
    them, with the other two still writing `failed`, would make the same
    abandoned upload report two different terminal states depending on which
    actor reached it first. Returning the whole mapping rather than just the
    status means a caller cannot take the split without also taking the
    message.

    ``message`` is the caller's own unbound wording (the poll path interpolates
    the elapsed seconds); it survives untouched for every row that is not an
    abandoned upload, so nothing about the existing failure reporting moves.
    """
    abandoned = abandoned_presigned_upload()
    return {
        "status": case((abandoned, "cancelled"), else_="failed"),
        "error_message": case((abandoned, ABANDONED_UPLOAD_MESSAGE), else_=message),
        "completed_at": now,
    }


def no_live_procrastinate_job():
    """Predicate: this ``ingest_jobs`` row has no queued or running task.

    fix(#724): age alone conflated two states. A job Procrastinate still holds
    as 'todo' was queued correctly and is simply waiting — and since fix(#695)
    deferred analysis to priority -10, waiting behind a steady upload stream is
    by design, with no upper bound. Failing those at the one-hour mark is both
    a lie and a loss: the analysis dies while its task sits in the queue, and
    the worker later picks the task up against a row already marked failed.

    A genuine orphan — committed, then the process died before defer landed a
    row, the gap defer_with_orphan_guard structurally cannot cover — has no row
    at all, so it is still reaped and the message is true by construction.

    Correlated on args->>'job_id', which every task in this codebase passes.
    Schema hard-coded to 'catalog', matching observability/metrics/jobs.py.

    fix(#724 review): BOTH pending auto-fail paths must use this. The periodic
    sweeper is the lesser one — get_job_status() runs the same age check on
    every poll, and the frontend polls it every 2s via useJobStatus /
    AnalysisJobWatcher, so the polling path is what actually kills a starved
    job the moment it crosses an hour.
    """
    return text(
        "NOT EXISTS (SELECT 1 FROM catalog.procrastinate_jobs pj"
        " WHERE pj.args->>'job_id' = ingest_jobs.id::text"
        " AND pj.status IN ('todo', 'doing'))"
    )


@dataclass(frozen=True)
class StaleCleanupOutcome:
    """Complete result of one stale-job and retained-staging cleanup pass."""

    pending_failed: int
    running_failed: int
    vrt_assets_recovered: int
    vrt_generations_failed: int
    terminal_jobs_purged: int
    staged_paths_considered: int
    local_files_reaped: int
    storage_objects_reaped: int
    staged_paths_skipped: int
    staged_cleanup_failures: int
    # fix(#1556 review, codex P2): pending rows the sweep settled `cancelled`
    # rather than `failed` — abandoned presigned uploads. Counted apart from
    # `pending_failed` because that number is read as a failure count by the
    # admin cleanup response, its audit event and the sweeper's log line, and
    # folding abandonments back into it would undo the split at exactly the
    # surfaces the split exists for.
    #
    # Last, with a default, only because a dataclass cannot put a defaulted
    # field before undefaulted ones; it belongs beside `pending_failed`.
    pending_cancelled: int = 0
    _staged_paths: tuple[str, ...] = field(default=(), repr=False, compare=False)
    # fix(#1202 review r5): presigned staging keys of the purged rows. Kept
    # separate from _staged_paths because they need no survivor query — a
    # staging key is namespaced by the job that presigned it.
    _staged_presigned_keys: tuple[str, ...] = field(
        default=(), repr=False, compare=False
    )
    # fix(#1277 review): refresh runs the sweep finalized, carried out to
    # whoever commits so the metric is published only once that commit lands.
    # Private and absent from as_dict() like the two fields above, so the
    # published API and audit shape is unchanged.
    _refresh_runs_reconciled: int = field(default=0, repr=False, compare=False)
    # fix(#1322 review): a dead VRT regeneration attempt's own generation-
    # scoped storage keys (source.vrt + 2 quicklooks), already resolved by
    # sweep_stale_vrt_assets but deliberately NOT yet deleted — carried out to
    # whoever commits, same rule as _staged_paths below, because deleting
    # before that commit is durable can destroy a generation a rolled-back
    # reconciliation still owns.
    _stale_generation_storage_keys: tuple[str, ...] = field(
        default=(), repr=False, compare=False
    )

    @property
    def total_cleaned(self) -> int:
        """Legacy count: ingest jobs transitioned from active to failed.

        fix(#1556 review): still literally that, which is why cancellations
        are absent. Its published identity is `pending_failed + running_failed`
        and a caller reading "cleaned" as "failed" is reading it correctly.
        """
        return self.pending_failed + self.running_failed

    @property
    def total_affected(self) -> int:
        """Rows and staged objects mutated by the cleanup pass.

        fix(#1556 review): cancellations DO belong here. This one counts work
        done, not failures, so leaving them out would under-report the rows the
        pass actually mutated — a number that hides work is worse than one that
        does not break down.
        """
        return (
            self.total_cleaned
            + self.pending_cancelled
            + self.vrt_assets_recovered
            + self.vrt_generations_failed
            + self.terminal_jobs_purged
            + self.local_files_reaped
            + self.storage_objects_reaped
        )

    def as_dict(self) -> dict[str, int]:
        """Return the stable API and audit detail shape.

        fix(#1556 review): `pending_cancelled` reaches the audit event (a JSONB
        `details` blob with no schema) and the multi-tenant fleet totals, which
        is where an operator reconstructs what a pass did. It deliberately does
        NOT reach the HTTP response: `StaleCleanupResponse` is a published
        model, generated into both SDKs and `api.generated.ts`, and pydantic's
        default `extra="ignore"` drops the key on the way out. Surfacing it
        there is a contract change with a regen attached, and it is not needed
        to fix the misreport — `pending_failed` no longer counts abandonments
        on any of the three surfaces.
        """
        return {
            "pending_failed": self.pending_failed,
            "pending_cancelled": self.pending_cancelled,
            "running_failed": self.running_failed,
            "total_cleaned": self.total_cleaned,
            "vrt_assets_recovered": self.vrt_assets_recovered,
            "vrt_generations_failed": self.vrt_generations_failed,
            "terminal_jobs_purged": self.terminal_jobs_purged,
            "staged_paths_considered": self.staged_paths_considered,
            "local_files_reaped": self.local_files_reaped,
            "storage_objects_reaped": self.storage_objects_reaped,
            "staged_paths_skipped": self.staged_paths_skipped,
            "staged_cleanup_failures": self.staged_cleanup_failures,
            "total_affected": self.total_affected,
        }


_POST_EXPIRY_SWEEP_MARGIN_SECONDS = 900


def post_expiry_sweep_after_seconds() -> int:
    """Job age past which no PUT URL for it can recreate the staging object.

    fix(#1202 review r8): the sweep below has to wait out the window in which a
    presigned PUT URL can still recreate the staging object after the
    event-triggered sweeps have already run.

    fix(#1235 review r3): that window used to be grounded on "the provider
    default is 3600 and no call site passes one". The ground is now firmer:
    every signing site passes an expiration computed as the job's REMAINING
    lifetime (`remaining_job_lifetime_seconds`), so a URL expires at
    `created_at + pending_job_timeout_seconds` rather than that long after
    whenever it happened to be signed. The window is therefore EXACT rather
    than conservative, and URL life only ever shortens. The provider-side
    min() clamps stay as the backstop for any future site that forgets.

    fix(#1235 review r4): and it is computed from the setting rather than from
    a fixed 3600, which the r3 comment already claimed while the constant it
    described still did not. Configure the timeout longer and the sweep ran
    while the URL was still live; a re-PUT after it then survived forever,
    because the reaped marker takes the row out of every later pass.

    Part URLs default to 7200 but cannot recreate an OBJECT either way: they
    need a live upload id, and CompleteMultipartUpload consumes it (an abort
    kills it). Only the single-part object-key URL is a recreation vector.

    `created_at` is the anchor on both sides — the row is inserted before any
    URL for it is minted, and the URLs are signed against that same value.
    """
    return settings.pending_job_timeout_seconds + _POST_EXPIRY_SWEEP_MARGIN_SECONDS


# Set on the post-expiry sweep's first pass over a job. Not permanent on its
# own — see _STAGING_REAPED_FINAL_MARKER below (fix #1236).
_STAGING_REAPED_MARKER = "s3_key_reaped"

# fix(#1236): set once the sweep's RE-CHECK pass has run AND cleared the
# transfer margin below, which only happens after
# MAX_PRESIGNED_URL_LIFETIME_SECONDS have elapsed since `created_at` — the
# latest moment any URL for the job, signed under any setting the deployment
# ever ran, can still be live. Only rows carrying this marker are excluded
# from every future pass; _STAGING_REAPED_MARKER alone no longer is.
_STAGING_REAPED_FINAL_MARKER = STAGING_REAPED_FINAL_MARKER

# fix(#1236 review, codex P1): SigV4 bounds when a URL may be SIGNED for, not
# when an already-accepted PUT finishes transferring bytes — S3 validates the
# signature at request start, not completion. A slow single-part upload begun
# just under the ceiling can still be writing after it, so the re-check's
# first delete attempt must not retire the row on the spot: only once an
# additional margin has ALSO elapsed is a live transfer no longer credible.
#
# fix(#1236 review r2, codex P1): that margin used to reuse
# `_COMMIT_HEADROOM_SECONDS` — APPLICATION commit-round-trip headroom.
# Presigned PUTs bypass the app entirely, so it never actually bounded
# anything about them.
#
# fix(#1236 review r3/second-opinion/r4, codex P1 x3): rounds r2-r3 then
# scaled the margin from `presigned_multipart_threshold_mb` and, after that
# proved config-fragile, from a job's own declared `expected_size` instead.
# Round 4 found the actual root cause under BOTH attempts:
# `generate_presigned_put_url` signs only `ContentType`, never a
# content-length constraint, so nothing ever enforced `expected_size` —
# a client can declare one byte and stream anything up to S3's real limit
# regardless. A margin derived from an unenforced declaration was tighter
# than the fixed ceiling, but never actually SAFE, which is worse than
# simply being wide: fixed and correct beats tight and wrong. The margin is
# now S3's own single-PUT ceiling, unconditionally, for every job — the one
# bound nothing but S3 itself enforces, so no per-job data or setting can
# ever undermine it. (Signing `Content-Length` into the URL so a mismatched
# PUT gets rejected by S3, making a declared-size margin trustworthy, was
# the other option; not worth the API-surface change for a low-frequency
# finalization check.)
_MIN_ASSUMED_UPLOAD_KBPS = 32  # ~256kbit/s: slow, but a still-progressing PUT
_S3_SINGLE_PUT_MAX_BYTES = 5 * 1024 * 1024 * 1024  # AWS hard limit, 5GiB
_RECHECK_TRANSFER_MARGIN_SECONDS = max(
    3600, (_S3_SINGLE_PUT_MAX_BYTES // 1024) // _MIN_ASSUMED_UPLOAD_KBPS
)


async def _sweep_expired_presigned_staging(
    db: AsyncSession, outcome: StaleCleanupOutcome, *, now: datetime | None = None
) -> StaleCleanupOutcome:
    """Sweep staging objects a now-dead PUT URL may have recreated.

    The other two sweeps are EVENT-triggered — one at completion, one at job
    end — and a fast ingest fires both while the client's URL is still valid.
    A re-PUT after them recreates an object nothing later reaps, because a
    successful job is the per-dataset latest-complete that the retention purge
    exempts forever. Those sweeps close the URL's past; this closes its future.

    Runs up to twice per job, ever: an ordinary pass reaps once and sets
    ``_STAGING_REAPED_MARKER``, which excludes the row from the ordinary
    window from then on but not from the re-check window below. Only
    ``_STAGING_REAPED_FINAL_MARKER`` — set once the re-check has actually run
    — takes a row out of the query for good, so the steady-state cost stays
    one excluded row per pass rather than one delete forever.

    Delete first, mark second — the opposite of ``_reap_committed_staged_paths``
    and for a different reason. That one must not destroy an artifact a
    rolled-back row DELETE might still need. Here the row survives either way,
    so the only asymmetric outcome is marking a FAILED delete as done, which
    leaks the object permanently. A crash between the two costs one redundant
    delete on the next pass instead, which is a no-op.

    fix(#1236): closes the #1235 review r5 known gap. The ordinary window is
    computed from the CURRENT `pending_job_timeout_seconds`, but a live URL was
    signed against whatever value was in force when it was issued. Lower the
    setting and restart while presigned uploads are in flight, and the
    ordinary pass ran early against those older, longer-lived URLs — it reaped
    the object and set the first marker while a PUT could still recreate it,
    and that marker used to exempt the row forever.

    The fix does not need to know which deadline a given URL actually carries
    — persisting that per job was rejected in #1235 for exactly that reason,
    plus a JSONB-to-timestamptz cast in the candidate WHERE that could throw
    and fail the whole bulk pass. Instead it uses the one bound every URL
    obeys regardless of history: SigV4 rejects any `X-Amz-Expires` beyond
    `MAX_PRESIGNED_URL_LIFETIME_SECONDS`, and `pending_job_timeout_seconds` has
    always been capped at that same ceiling, so no URL for a job can still be
    live past `created_at + MAX_PRESIGNED_URL_LIFETIME_SECONDS` no matter which
    setting minted it. A row already carrying the first marker gets a delete
    attempt every pass once it crosses that age, which either recovers an
    object a stale marker was hiding or costs one no-op DeleteObject against a
    key that was never recreated — but does not finalize it until
    `_RECHECK_TRANSFER_MARGIN_SECONDS` past that same age has ALSO elapsed
    (codex P1 on this PR): SigV4 expiry stops new requests, not one already
    accepted, so a slow PUT begun just under the ceiling can still be writing
    after it. Only once no such transfer is credible does the final marker
    retire the row for good.

    fix(#1236 review r4, codex P1): that margin is FIXED at S3's own
    single-PUT ceiling for every job, not derived from anything a client
    declared or an operator configured — see `_RECHECK_TRANSFER_MARGIN_SECONDS`
    above for why rounds r2/r3 both proved unsafe.
    """
    now = now or datetime.now(timezone.utc)
    first_pass_cutoff = now - timedelta(seconds=post_expiry_sweep_after_seconds())
    recheck_cutoff = now - timedelta(seconds=MAX_PRESIGNED_URL_LIFETIME_SECONDS)
    recheck_final_cutoff = recheck_cutoff - timedelta(
        seconds=_RECHECK_TRANSFER_MARGIN_SECONDS
    )
    not_yet_reaped = IngestJob.user_metadata[_STAGING_REAPED_MARKER].astext.is_(None)
    candidates = (
        await db.execute(
            select(
                IngestJob.id,
                IngestJob.file_path,
                IngestJob.user_metadata,
                IngestJob.created_at,
            ).where(
                IngestJob.status.not_in(("pending", "running")),
                IngestJob.user_metadata["s3_key"].astext.is_not(None),
                IngestJob.user_metadata[_STAGING_REAPED_FINAL_MARKER].astext.is_(None),
                or_(
                    and_(not_yet_reaped, IngestJob.created_at < first_pass_cutoff),
                    and_(
                        not_(not_yet_reaped),
                        IngestJob.created_at < recheck_cutoff,
                    ),
                ),
            )
        )
    ).all()

    reaped = 0
    failures = 0
    for job_row_id, file_path, metadata, created_at in candidates:
        staging_key = owned_presigned_staging_key(job_row_id, metadata, file_path)
        if staging_key is None:
            # Not this job's key to delete — a fan-out child holding the
            # parent's inherited s3_key lands here, same rule as everywhere.
            continue
        is_recheck_pass = (metadata or {}).get(_STAGING_REAPED_MARKER) is not None
        try:
            from app.platform.storage import get_storage

            await get_storage().delete(resolve_current_storage_key(staging_key))
        except Exception:  # broad: best-effort staging cleanup
            failures += 1
            log.warning(
                "Failed to reap expired presigned staging object",
                storage_key=staging_key,
                recheck_pass=is_recheck_pass,
            )
            continue
        # A Core UPDATE with a fresh dict, not an in-place mutation of the
        # loaded value — JSONB does not track mutation, so an in-place edit
        # would never flush.
        new_metadata = {**(metadata or {}), _STAGING_REAPED_MARKER: True}
        if is_recheck_pass and created_at < recheck_final_cutoff:
            new_metadata[_STAGING_REAPED_FINAL_MARKER] = True
        await db.execute(
            update(IngestJob)
            .where(IngestJob.id == job_row_id)
            .values(user_metadata=new_metadata)
        )
        reaped += 1

    if reaped:
        await db.commit()

    if not (reaped or failures):
        return outcome
    return replace(
        outcome,
        storage_objects_reaped=outcome.storage_objects_reaped + reaped,
        staged_cleanup_failures=outcome.staged_cleanup_failures + failures,
    )


async def _reap_committed_staged_paths(
    outcome: StaleCleanupOutcome,
) -> StaleCleanupOutcome:
    """Delete staging artifacts only after their job-row purge is durable."""
    from app.core.tenancy import is_multi_tenant

    local_files_reaped = 0
    storage_objects_reaped = 0
    staged_paths_skipped = 0
    staged_cleanup_failures = 0
    staging_root = Path(settings.upload_staging_dir).resolve()

    for file_path in outcome._staged_paths:
        try:
            if is_multi_tenant() and file_path.startswith("staging/"):
                # Hosted jobs store logical keys. Resolve the active tenant's
                # provider namespace before deleting the staged object.
                from app.platform.storage import get_storage

                await get_storage().delete(resolve_current_storage_key(file_path))
                storage_objects_reaped += 1
                continue

            local = Path(file_path).resolve()
            if local.exists():
                if local.is_relative_to(staging_root):
                    local.unlink(missing_ok=True)
                    local_files_reaped += 1
                else:
                    staged_paths_skipped += 1
            elif file_path.startswith("staging/"):
                # Only presigned-upload staging keys ("staging/{job_id}/…")
                # may be deleted. Manifest sources can reference arbitrary
                # same-bucket keys through this column.
                from app.platform.storage import get_storage

                await get_storage().delete(resolve_current_storage_key(file_path))
                storage_objects_reaped += 1
            else:
                staged_paths_skipped += 1
        except Exception:  # broad: best-effort staging cleanup
            staged_cleanup_failures += 1
            log.warning(
                "Failed to reap staged file for purged jobs",
                file_path=file_path,
            )

    # fix(#1202 review r5): the presigned staging keys. A completed presigned
    # job points `file_path` at its frozen copy, so the loop above never
    # reaches the key the client still holds a PUT URL for — and a
    # post-completion re-PUT recreates an object that escapes size and quota
    # accounting. These are always provider keys (never local paths) and are
    # namespaced by the job that presigned them, which is what makes deleting
    # them safe without a survivor query.
    for staging_key in outcome._staged_presigned_keys:
        try:
            from app.platform.storage import get_storage

            await get_storage().delete(resolve_current_storage_key(staging_key))
            storage_objects_reaped += 1
        except Exception:  # broad: best-effort staging cleanup
            staged_cleanup_failures += 1
            log.warning(
                "Failed to reap presigned staging object for purged jobs",
                storage_key=staging_key,
            )

    # fix(#1322 review): a dead VRT regeneration attempt's own generation-
    # scoped objects, resolved by sweep_stale_vrt_assets but withheld from
    # deletion until now — this function IS "after the commit landed" for
    # every caller (fail_stale_jobs's own commit=True branch calls it
    # immediately after `await db.commit()`; the admin commit=False branch
    # calls it immediately after its own commit). Already tenant-resolved at
    # capture time, unlike the two loops above, so no resolve_current_storage_key.
    for stale_key in outcome._stale_generation_storage_keys:
        try:
            from app.platform.storage import get_storage

            await get_storage().delete(stale_key)
            storage_objects_reaped += 1
        except Exception:  # broad: best-effort staging cleanup
            staged_cleanup_failures += 1
            log.warning(
                "Failed to reap stale VRT generation object",
                storage_key=stale_key,
            )

    return replace(
        outcome,
        local_files_reaped=local_files_reaped,
        storage_objects_reaped=storage_objects_reaped,
        staged_paths_skipped=staged_paths_skipped,
        staged_cleanup_failures=staged_cleanup_failures,
    )


def _stale_generation_storage_keys(
    stale_generations: list[tuple[uuid.UUID, uuid.UUID]],
) -> tuple[str, ...]:
    """Resolve (never delete) a dead attempt's immutable object keys.

    feat(#1267): ``regenerate_vrt`` writes its rebuilt VRT + quicklooks to an
    immutable ``rasters/{vrt_dataset_id}/generations/{generation_id}/...`` key
    (the full generation UUID, unset by attempt-fencing convention A3 —
    mirroring ``attempt_scoped_staging_table``'s full-hex rule for staging
    tables) BEFORE the phase-2 transaction that would otherwise clean them up
    via ``_cleanup_orphaned_storage_keys``. A worker killed between that write
    and the commit leaves the objects with no reference anywhere — this sweep
    is the only remaining owner of the key, so its caller reaps them the same
    way, but only once the reconciliation itself is durable (see
    ``_reap_stale_generation_storage`` for why deletion is a separate,
    later step).

    ``current_tenant_var`` carries the right tenant because every caller of
    ``sweep_stale_vrt_assets`` (the startup recovery pass and the periodic
    sweep, both directly and via ``fail_stale_jobs``) runs inside
    ``tenant_job_context`` per tenant in multi-tenant mode — the same context
    ``regenerate_vrt`` itself reads to resolve these same keys. A missing
    tenant context in multi-tenant mode resolves no keys rather than raising:
    the asset/generation reconciliation is not gated on this best-effort pass.
    """
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant
    from app.platform.storage.titiler_url import resolve_storage_key

    tenant_id = current_tenant_var.get()
    if is_multi_tenant() and tenant_id is None:
        return ()

    return tuple(
        resolve_storage_key(
            f"rasters/{vrt_dataset_id}/generations/{generation_id}/{suffix}",
            tenant_id=tenant_id,
        )
        for generation_id, vrt_dataset_id in stale_generations
        for suffix in ("source.vrt", "quicklook_256.png", "quicklook_512.png")
    )


async def _reap_stale_generation_storage(keys: tuple[str, ...]) -> None:
    """Best-effort delete of already-resolved, already-committed keys.

    fix(#1322 review): deleting these objects had lived inside
    ``sweep_stale_vrt_assets`` itself, before its caller's commit. A worker
    is declared dead by a timed-out heartbeat, not by proof it can never run
    another statement — if the reconciling transaction then failed to commit
    (or a later statement in the same pass raised), the generation/asset
    UPDATEs rolled back while these objects were already gone. A resumed
    "dead" worker could pass the (rolled-back-to) ownership checks and
    publish a generation whose own source.vrt and quicklooks no longer
    exist, leaving a `'ready'` asset backed by deleted data. Every caller now
    resolves the keys during the sweep (``_stale_generation_storage_keys``,
    read-only) but defers this call until strictly after its own commit
    succeeds — mirroring ``_reap_committed_staged_paths``, which reaps
    ``StaleCleanupOutcome._staged_paths`` under the identical rule.

    A dead attempt may have written none, some, or all three objects before
    the worker died; deleting a key that was never written is a documented
    no-op on every StorageProvider.
    """
    if not keys:
        return

    # Function-local: mirrors the deferred processing-import convention
    # already used for RasterAsset/VrtGeneration below (D-17,
    # test_platform_processing_imports_stay_deferred) — the exact same helper
    # regenerate_vrt itself uses to reap its own orphaned writes.
    from app.processing.ingest.tasks_raster import _cleanup_orphaned_storage_keys

    await _cleanup_orphaned_storage_keys(list(keys), job_id="vrt-stale-sweep")


# fix(#1322 review round 3): does the PUBLISHED VRT's member set (built_from's
# keys — feat(#1290 review): "what the published VRT was assembled FROM")
# still equal the CATALOG's current member set (vrt_source_links)? A bare
# fragment, not a full statement, so it can be embedded as-is in one UPDATE's
# WHERE and wrapped in NOT(...) for its mirror — see sweep_stale_vrt_assets.
#
# fix(#1327): this check is now near-unreachable in the FALSE direction, and
# that is the point. add_vrt_source/remove_vrt_source no longer mutate
# vrt_source_links at request time — they stage the intended member set on the
# VrtGeneration row, and regenerate_vrt applies it in the same transaction that
# publishes the artifact and writes built_from. A composition-changing attempt
# that dies before that swap now leaves the links exactly as built_from
# describes them, so it takes the honest restore branch like any other dead
# attempt. The check stays because it is the guard, not the mechanism: rows
# written before #1327, a generation staged by future code that forgets to
# apply it, or any path that mutates the link table outside a publish
# transaction all still produce real drift, and the sweep must keep refusing to
# call that 'ready'. A check whose FALSE branch has become rare is the outcome
# of fixing the cause; deleting it would only make the next cause invisible.
#
# Count-match + one-directional subset (every built_from key has a live
# link) proves full set equality: a JSONB object cannot repeat a key, and
# uq_vsl_vrt_source forbids vrt_source_links from repeating a
# (vrt_dataset_id, source_dataset_id) pair, so neither side can inflate its
# own count to fake a subset match.
#
# jsonb_typeof(...) = 'object', not built_from IS NOT NULL — a real-DB test
# caught the difference: SQLAlchemy's plain JSONB type (no none_as_null=True)
# serializes a Python None to the JSON scalar `null`, not SQL NULL, so
# "IS NOT NULL" alone is TRUE for a column holding JSON null and
# jsonb_object_keys() raises "cannot call jsonb_object_keys on a scalar" —
# turning the conservative branch into a 500 instead of a safe fallback.
# jsonb_typeof() returns SQL NULL for a genuinely NULL column and 'null' (a
# string, not a match) for a JSON-null scalar, so both forms — and any other
# non-object value — fail the `= 'object'` test the same safe way. A legacy
# VRT predating the built_from column cannot answer the question at all,
# and the unanswerable case must fall to the SAME conservative branch as a
# proven mismatch.
_COMPOSITION_PRESERVED_SQL = """
    jsonb_typeof(built_from) = 'object'
    AND (SELECT COUNT(*) FROM jsonb_object_keys(built_from)) = (
        SELECT COUNT(*) FROM catalog.vrt_source_links vsl
        WHERE vsl.vrt_dataset_id = dataset_id
    )
    AND NOT EXISTS (
        SELECT 1 FROM jsonb_object_keys(built_from) AS built_from_key
        WHERE NOT EXISTS (
            SELECT 1 FROM catalog.vrt_source_links vsl2
            WHERE vsl2.vrt_dataset_id = dataset_id
              AND vsl2.source_dataset_id::text = built_from_key
        )
    )
"""

# fix(#1322 review round 4): composition-preserving is necessary but not
# sufficient. regenerate_vrt_endpoint's guard only rejects 'regenerating' —
# a caller may retry an asset that is already 'failed'. If THAT retry is
# also abandoned and its membership still matches built_from, the check
# above alone would call it composition-preserving and restore 'ready',
# erasing a real failure signal a worker crash had nothing to do with:
# no successful artifact was ever produced by the retry, and whatever made
# the FIRST attempt fail is still unaddressed.
#
# There is no column recording "the asset's status the instant this
# generation started" — router.py's own `previous_status` is a local
# variable, never persisted. The nearest STORED fact is the outcome of the
# attempt immediately before this one: at most one generation is ever
# in-flight per dataset (the 409 + advisory lock in regenerate_vrt_endpoint
# / add_vrt_source / remove_vrt_source forbid a second), so
# `vrt_generations` rows for one dataset form a strict, gap-free timeline,
# and the row immediately preceding the one being reconciled records
# exactly what happened right before THIS attempt was allowed to start.
# 'completed' (or no such row — the dataset's first-ever attempt, whose
# prior state is 'ready' by construction, per create_vrt_dataset) means the
# asset was 'ready' when this attempt began; 'failed' means it was not.
#
# Accepted conservative cost, stated plainly: a generation this sweep
# itself restores to 'ready' still leaves its OWN vrt_generations row
# 'failed' below (only the asset recovers, not the attempt's record) — so
# a LATER dead attempt on the same dataset, whose immediately-prior row IS
# that earlier swept-and-recovered one, reads 'failed' here and is kept
# 'failed' even though the asset was legitimately 'ready' when it started.
# The alternative (a further stored marker distinguishing "recovered by
# the sweep" from "never recovered") is a bigger schema surface than this
# fix's blast radius, and the safety direction is right for a reconciler:
# never claims 'ready' the moment there is any doubt, at the cost of
# occasionally staying 'failed' one cycle longer than strictly necessary,
# which self-corrects the moment an operator retries and it succeeds.
#
# fix(#1322 review round 5): raw `status` alone over-counts what "failed"
# means. regenerate_vrt_endpoint's own orphan guard (_rollback,
# lines ~507-520) marks the just-created VrtGeneration 'failed' when
# Procrastinate's ENQUEUE itself throws — a dispatch failure the task never
# reached — and in the SAME rollback reverts the asset to whatever it was
# (commonly 'ready'). That generation row genuinely never ran: nothing
# about its outcome describes the asset's state, only that it could not be
# queued. Reading its 'failed' status here as "the asset was not ready"
# would be wrong in exactly the direction this predicate exists to avoid —
# not a false 'ready', but a false 'failed' for an asset that never had a
# real attempt run against it.
#
# `heartbeat_at IS NOT NULL` is the fact that separates them: it is set in
# exactly one place in this codebase, `tasks_vrt.regenerate_vrt`'s Phase-1
# claim (either the CAS `UPDATE ... status='pending' -> 'running'`, or the
# equivalent field on a freshly-created legacy-pointer generation) — the
# first thing the TASK does once a worker actually picks it up, never
# anything the ENDPOINT touches at creation. A synchronous enqueue failure
# never reaches that line, so its generation keeps heartbeat_at NULL
# forever; the same is true of a generation stuck 'pending' because no
# worker ever claimed it before this sweep's own cutoff — which is the
# same "never actually ran" fact, so excluding it here is consistent with,
# not a special case against, its own eventual sweep as a dead attempt.
# Filtering to `heartbeat_at IS NOT NULL` therefore finds the most recent
# OTHER generation that a worker actually claimed and ran, skipping past
# any number of enqueue-failures or claim-starved rows in between — those
# never touched the asset's state, so they carry no information about it.
_PRIOR_ATTEMPT_WAS_READY_SQL = """
    (
        SELECT g.status FROM catalog.vrt_generations g
        WHERE g.vrt_dataset_id = dataset_id
          AND g.id <> current_generation_id
          AND g.heartbeat_at IS NOT NULL
        ORDER BY g.started_at DESC
        LIMIT 1
    ) IS DISTINCT FROM 'failed'
"""

_READY_WORTHY_SQL = (
    f"({_COMPOSITION_PRESERVED_SQL}) AND ({_PRIOR_ATTEMPT_WAS_READY_SQL})"
)

# fix(#1322 review round 6, completed): the proven-dead proof for a
# 'pending' VrtGeneration — mirrors _ABANDONED_RUN_SQL's
# `catalog.procrastinate_jobs` correlation in platform/refresh/service.py,
# keyed on `generation_id` instead of `ingest_job_id` because that is the
# kwarg every regenerate_vrt dispatch site (regenerate_vrt_endpoint,
# add_vrt_source, remove_vrt_source) actually passes — there is no
# ingest_job_id column on VrtGeneration to correlate through. `'todo'`/
# `'doing'` is Procrastinate's own live-job vocabulary, same two statuses
# stale_pending_clauses excludes for IngestJob.
#
# Two correlation forms, because `tasks_vrt.regenerate_vrt` accepts two
# delivery shapes and this predicate has to cover both to be complete:
#   1. Modern: `generation_id` is present in `args` — exact 1:1 match.
#   2. Legacy: a delivery queued by pre-upgrade code carries no
#      `generation_id` at all (the task parameter is optional precisely to
#      keep such deliveries alive across a rolling deploy). On execution it
#      adopts `RasterAsset.current_generation_id` instead (see the
#      "Legacy queued deliveries" comment at tasks_vrt.py's claim site). A
#      live legacy row is therefore correlated by dataset (`vrt_dataset_id`
#      is a required, non-optional task argument, so every delivery of
#      either shape always carries it) PLUS current ownership: it counts as
#      live for THIS generation only if this generation IS, right now, that
#      dataset's `RasterAsset.current_generation_id` — the exact row the
#      legacy task will claim once it runs.
# Deliberately conservative in the direction the finding asked for: an
# ambiguous or legacy-shaped live row blocks the sweep rather than being
# read as absence of one — a delayed sweep of a truly-dead attempt costs a
# retry window; sweeping a live one loses real work.
_NO_LIVE_GENERATION_JOB_SQL = """
    NOT EXISTS (
        SELECT 1 FROM catalog.procrastinate_jobs pj
        WHERE pj.status IN ('todo', 'doing')
          AND (
            pj.args->>'generation_id' = vrt_generations.id::text
            OR (
                pj.args->>'generation_id' IS NULL
                AND pj.args->>'vrt_dataset_id' = vrt_generations.vrt_dataset_id::text
                AND EXISTS (
                    SELECT 1 FROM catalog.raster_assets ra
                    WHERE ra.dataset_id = vrt_generations.vrt_dataset_id
                      AND ra.current_generation_id = vrt_generations.id
                )
            )
          )
    )
"""


async def sweep_stale_vrt_assets(
    db: AsyncSession,
    stale_cutoff: datetime,
) -> tuple[int, int, tuple[str, ...]]:
    """Reconcile RasterAsset rows stuck in status='regenerating' past ``stale_cutoff``.

    GAP-002 / feat(#1267): a worker crash mid-regeneration leaves the VRT
    asset permanently stuck in ``status='regenerating'``, causing all future
    link/regenerate calls to 409. This helper mirrors the IngestJob
    stale-recovery pattern and uses the same
    ``stale_cutoff = now - JOB_TIMEOUT_SECONDS`` threshold.

    Staleness is measured via ``VrtGeneration.heartbeat_at`` (falling back to
    ``started_at`` for a generation whose worker died before its first
    renewal) — the same self-reported liveness signal ``maintain_vrt_
    generation_heartbeat`` renews every 30s while the worker is alive, so a
    live job's row never crosses the cutoff and this sweep never touches it.

    Recovery status: ``'ready'`` only when BOTH hold (fix(#1322 review
    rounds 3-4) — see ``_READY_WORTHY_SQL``, ``_COMPOSITION_PRESERVED_SQL``,
    ``_PRIOR_ATTEMPT_WAS_READY_SQL``); ``'failed'`` otherwise. ``regenerate_
    vrt`` only overwrites the asset's published pointer (``asset_uri``,
    ``sha256``, ...) in the SAME transaction that clears
    ``current_generation_id`` on success — a dead attempt never reaches
    that transaction, so those fields still describe the last-good VRT the
    asset was serving before this attempt started. That is necessary to
    restore ``'ready'`` but not sufficient on its own, for two independent
    reasons:

    1. Nothing about the dataset's declared MEMBERSHIP may have changed
       underneath the attempt. Restoring ``'ready'`` over such a change
       would erase the only visible signal of it — the status endpoint
       reads the link set, not the served VRT, and would report a reduced
       (or expanded) source list as fully healthy while stale composition
       keeps being served. fix(#1327) removed the path that used to
       produce this state routinely: ``add_vrt_source``/``remove_vrt_
       source`` stage their intended member set on the ``VrtGeneration``
       row and ``regenerate_vrt`` applies it in the same transaction as
       the artifact swap, so a dead composition-changing attempt now
       leaves the links untouched and takes the restore branch. The check
       remains as the guard for what it cannot see: rows written before
       #1327, and any future path that mutates the link table outside a
       publish transaction.
    2. The asset must have actually BEEN ``'ready'`` — not ``'failed'`` —
       the instant this attempt was allowed to start. ``regenerate_vrt_
       endpoint``'s guard rejects only ``'regenerating'``, so a caller may
       retry an asset that is already ``'failed'``. If that retry then dies
       too and its membership still matches, condition 1 alone would call
       it composition-preserving and restore ``'ready'`` — erasing a real
       failure a worker crash had nothing to do with, since no successful
       artifact was ever produced by the retry and whatever caused the
       FIRST failure is still unaddressed.

    The degraded branch keeps ``current_generation_id`` cleared (a retry
    can still be triggered) but leaves ``status='failed'``, matching the
    ordinary explicit-failure path.

    Either branch marks the dead attempt's own ``VrtGeneration`` row
    ``'failed'`` below; an operator or retry call can re-trigger
    regeneration regardless of which branch fired.

    There is no "first-ever generation, no built_from to compare" gap.
    ``status='regenerating'`` is reachable from exactly three call sites
    (``regenerate_vrt_endpoint``, ``add_vrt_source``, ``remove_vrt_source``),
    and all three 404 unless a VRT dataset already exists — which means its
    ``RasterAsset`` row was already created, and the only constructor of that
    row (``create_vrt_dataset``, run inside ``ingest_vrt``) sets
    ``status='ready'`` with a real ``asset_uri`` AND a real ``built_from`` in
    the same flush the row first becomes queryable. No code path ever
    inserts a ``RasterAsset`` row pre-set to ``'regenerating'``, and no VRT
    created after ``built_from`` shipped (#1290) ever has a NULL value for
    it — only a legacy pre-#1290 row can, and that case is exactly the
    "cannot answer, so don't guess ready" branch above.

    Also resolves the dead attempt's own generation-scoped storage keys for
    the caller to reap, but does NOT delete anything itself — the caller must
    not do so either until its own commit lands (fix(#1322 review); see
    ``_reap_stale_generation_storage``). Deleting before that commit is
    durable can destroy a generation a rolled-back reconciliation just
    restored ownership of, orphaning a `'ready'` asset against missing bytes.

    Args:
        db: The active async session (must NOT be committed before returning
            — the caller is responsible for the final ``await db.commit()``).
        stale_cutoff: Any regenerating asset whose generation started before
            this timestamp is considered stale.

    Returns:
        ``(assets_recovered, gens_failed, storage_keys)`` — ``assets_
        recovered`` counts BOTH branches (restored to ready and kept
        failed; both are a resolved outcome for a dead attempt).
        ``storage_keys`` are resolved, not yet deleted.
    """
    from app.processing.raster.models import RasterAsset, VrtGeneration

    now = datetime.now(timezone.utc)

    generation_scope = []
    asset_scope = []
    from app.core.tenancy import is_multi_tenant

    if is_multi_tenant():
        # Function-local import preserves the platform/catalog module boundary.
        # The subqueries are RLS-visible and fail closed without a tenant GUC.
        from app.modules.catalog.datasets.domain.models import Dataset

        generation_scope.append(VrtGeneration.vrt_dataset_id.in_(select(Dataset.id)))
        asset_scope.append(RasterAsset.dataset_id.in_(select(Dataset.id)))

    # --- 1. Find stale regenerating RasterAssets ---
    # A VRT asset is stale when:
    #   - status = 'regenerating'
    #   - its latest VrtGeneration (matched by vrt_dataset_id) has
    #     started_at older than stale_cutoff.
    # We query via VrtGeneration so the staleness signal is the
    # regeneration start time, not the asset's last_regenerated_at
    # (which is only written on successful completion).
    # Fail generation leases atomically. The status + liveness predicates are
    # re-evaluated by PostgreSQL at UPDATE time, so a heartbeat racing the
    # sweep wins and the generation remains live.
    #
    # fix(#1322 review round 6): 'running' and 'pending' need DIFFERENT
    # proof, mirroring the split this file already applies to IngestJob
    # (the running-job sweep just above trusts a stale heartbeat outright;
    # stale_pending_clauses additionally requires no_live_procrastinate_job
    # because queue waits are unbounded). A 'running' generation's
    # heartbeat_at is the worker's own, actively-renewed liveness signal —
    # stale on it is proof enough, independent of what Procrastinate's OWN
    # bookkeeping currently shows (a crashed worker can leave its
    # procrastinate_jobs row reading 'doing' until the separate stalled-
    # queue sweep prunes it, so requiring "no live row" here would make a
    # genuinely-dead running generation UNSWEEPABLE until that other sweep
    # runs). A 'pending' generation has no such signal — nothing has
    # claimed it yet, so its `started_at` age alone cannot distinguish
    # "orphaned" from "sitting in a sustained worker backlog, still queued
    # and will run" — so it additionally requires proof no live
    # Procrastinate row still references it, correlated via `generation_id`
    # in `args` (the same kwarg all three dispatch call sites pass), the
    # exact fact stale_pending_clauses checks for IngestJob and for the
    # identical reason.
    #
    # RETURNING carries vrt_dataset_id alongside id (feat(#1267)): the
    # generation-scoped storage key each dead attempt wrote to is keyed on
    # BOTH, and the asset UPDATE below cannot supply that pairing back — its
    # own current_generation_id is nulled in the same statement, so RETURNING
    # it would report the value AFTER the SET, not the attempt being reaped.
    stale_gen_result = await db.execute(
        update(VrtGeneration)
        .where(
            *generation_scope,
            or_(
                and_(
                    VrtGeneration.status == "running",
                    func.coalesce(VrtGeneration.heartbeat_at, VrtGeneration.started_at)
                    < stale_cutoff,
                ),
                and_(
                    VrtGeneration.status == "pending",
                    VrtGeneration.started_at < stale_cutoff,
                    text(_NO_LIVE_GENERATION_JOB_SQL),
                ),
            ),
        )
        .values(
            status="failed",
            completed_at=now,
            error_message=(
                f"Stale: regeneration running for over {JOB_TIMEOUT_SECONDS // 60} minutes"
            ),
        )
        .returning(VrtGeneration.id, VrtGeneration.vrt_dataset_id)
    )
    # Tuple-unpack the Row objects directly (matches the RETURNING pattern
    # used for the retention purge above) rather than attribute access, so a
    # lightweight test double can stand in with plain tuples.
    stale_generations = [
        (generation_id, vrt_dataset_id)
        for generation_id, vrt_dataset_id in stale_gen_result.all()
    ]
    stale_generation_ids = [generation_id for generation_id, _ in stale_generations]

    # Restore the asset only if it still points at the generation just
    # failed. A newer regeneration has a different current_generation_id and
    # is fenced — same CAS discipline as the failure-handler path in
    # tasks_vrt.regenerate_vrt.
    #
    # fix(#1322 review round 3): 'ready' is only honest for a COMPOSITION-
    # PRESERVING attempt. If the catalog's link set reflects a NEW composition
    # while the published asset_uri (untouched by the dead attempt) still
    # serves the OLD one, restoring 'ready' would erase the only visible signal
    # of that drift: the status endpoint reads the link set, not the served
    # bytes, and would report the new (reduced) source list as fully healthy
    # while stale data keeps being served.
    #
    # fix(#1327): the routine producer of that drift is gone — add_vrt_source /
    # remove_vrt_source stage their member set on the generation and
    # regenerate_vrt applies it in the publish transaction, so a dead
    # composition-changing attempt leaves the links matching built_from and
    # lands in the restore branch below. What remains for this check is what it
    # was always the guard against rather than the mechanism for: pre-#1327
    # rows and any unforeseen writer of the link table.
    #
    # There is no stored "attempt type" to key off — VrtGeneration.
    # triggered_by holds a user id on every call site, not a kind, and
    # source_count is populated post-mutation on both. So this asks the
    # question the drift itself is about, from state rather than provenance:
    # does the PUBLISHED composition (built_from's key set — what the served
    # VRT was actually assembled from, feat(#1290 review)) still equal the
    # CATALOG's current composition (vrt_source_links)? Count-match plus a
    # one-directional subset check proves set equality here because neither
    # side can hold a duplicate id (a JSONB object key is unique by
    # construction; vrt_source_links carries uq_vsl_vrt_source).
    #
    # NULL built_from (a pre-#1290 VRT with no recorded build set) cannot
    # answer the question at all, and falls to the same conservative branch
    # as a genuine mismatch — matching the "unknown answers unknown, not
    # fresh" posture in source_freshness.py, not the other one.
    #
    # fix(#1322 review round 4): composition-preserving is necessary but not
    # sufficient — see _PRIOR_ATTEMPT_WAS_READY_SQL above for the second,
    # independently-required fact (was the asset actually 'ready', not
    # 'failed', the instant this attempt was allowed to start).
    _asset_composition = (
        *asset_scope,
        RasterAsset.status == "regenerating",
        RasterAsset.current_generation_id.in_(stale_generation_ids),
    )
    ready_result = await db.execute(
        update(RasterAsset)
        .where(*_asset_composition, text(_READY_WORTHY_SQL))
        .values(status="ready", current_generation_id=None)
        .returning(RasterAsset.dataset_id)
    )
    ready_ids = list(ready_result.scalars())
    for dataset_id in ready_ids:
        log.warning(
            "Reconciled abandoned VRT regeneration, restored to ready",
            dataset_id=str(dataset_id),
            stale_cutoff=str(stale_cutoff),
        )

    degraded_result = await db.execute(
        update(RasterAsset)
        .where(*_asset_composition, text(f"NOT ({_READY_WORTHY_SQL})"))
        .values(status="failed", current_generation_id=None)
        .returning(RasterAsset.dataset_id)
    )
    degraded_ids = list(degraded_result.scalars())
    for dataset_id in degraded_ids:
        log.warning(
            "Reconciled abandoned VRT regeneration, kept failed — "
            "composition changed since the published build, or the "
            "asset was not provably ready when this attempt started",
            dataset_id=str(dataset_id),
            stale_cutoff=str(stale_cutoff),
        )

    stale_asset_ids = ready_ids + degraded_ids

    storage_keys = (
        _stale_generation_storage_keys(stale_generations) if stale_generations else ()
    )

    return len(stale_asset_ids), len(stale_generation_ids), storage_keys


def publish_refresh_reconciliation(outcome: StaleCleanupOutcome) -> None:
    """Publish the sweep's reconciliation counter, AFTER its commit landed.

    fix(#1277 review): this used to increment where the sweep runs, inside the
    transaction. A later failure in the same pass rolls the cancellations back
    but not the counter, and a counter only goes up — so the overcount is
    permanent and every rate() over that window stays wrong. Publishing waits
    for durability rather than intent.

    Both commit sites call it: ``fail_stale_jobs`` when it owns the commit,
    and the admin cleanup endpoint when it passes ``commit=False``. A
    rolled-back pass reaches neither. Every increment is a run that reached a
    terminal status with no worker reporting one.
    """
    if outcome._refresh_runs_reconciled:
        refresh_sweep_reconciled_total.inc(outcome._refresh_runs_reconciled)


@overload
async def fail_stale_jobs(
    db: AsyncSession,
    *,
    commit: bool = True,
    detailed: Literal[False] = False,
) -> tuple[int, int]: ...


@overload
async def fail_stale_jobs(
    db: AsyncSession,
    *,
    commit: bool = True,
    detailed: Literal[True],
) -> StaleCleanupOutcome: ...


async def fail_stale_jobs(
    db: AsyncSession,
    *,
    commit: bool = True,
    detailed: bool = False,
) -> tuple[int, int] | StaleCleanupOutcome:
    """Mark stale jobs failed and reap retained staging artifacts.

    The default two-item tuple preserves the background-sweeper contract.
    ``detailed=True`` returns the complete operational outcome for the admin
    endpoint and its audit event.

    Stale rules:
      - status='pending', created_at older than the matching
        ``stale_pending_cutoff_seconds``, AND no
        live Procrastinate job (a true orphan that was never queued)
      - status='running' and heartbeat_at/started_at older than JOB_TIMEOUT_SECONDS
        (worker lease expired)

    Also sweeps VRT RasterAsset rows stuck in status='regenerating' past
    JOB_TIMEOUT_SECONDS (GAP-002) via the shared ``sweep_stale_vrt_assets``
    helper. The VRT sweep uses the same stale_cutoff as the running-jobs sweep.

    Used by both the admin cleanup endpoint and the background lifespan sweeper.
    """
    now = datetime.now(timezone.utc)

    # fix(#1234): the 1h abandonment policy applies only to jobs that never
    # got as far as binding bytes. A presigned completion sets `file_path` and
    # then commits; between those two the row is still `pending` with a
    # `file_path`, and this sweep used to fail it out from under the request —
    # a race whose loser is a completion that actually succeeded.
    #
    # The guard is a FALSY check, not IS NULL. The column is nullable, but no
    # creator ever writes NULL: `create_ingest_job` is called with "" by both
    # presign endpoints, and analysis jobs carry "" too (see
    # `_retry_capability`). An IS NULL guard would match nothing and leave the
    # race exactly as it was, while looking fixed.
    unbound_result = await db.execute(
        update(IngestJob)
        .where(*stale_pending_clauses(now, completion_bound=False))
        .values(
            **stale_pending_unbound_values(now, message=STALE_PENDING_UNBOUND_MESSAGE)
        )
        # fix(#1556 review, codex P2): RETURNING carries the status the CASE
        # actually chose. Postgres returns the NEW row, so this is what the
        # database wrote — the alternative, re-deriving the predicate in
        # Python to classify the rows, is a second copy of the rule that can
        # disagree with the one that ran.
        .returning(
            IngestJob.id,
            IngestJob.user_metadata,
            IngestJob.created_by,
            IngestJob.status,
        )
    )
    unbound_rows = list(unbound_result.all())
    # Positional, like every other row read in this function: a mocked session
    # hands back plain tuples, and attribute access would work against the
    # database while raising in the unit suites that drive this with doubles.
    pending_cancelled = sum(1 for row in unbound_rows if row[3] == "cancelled")
    # Back to the three columns every consumer below expects; the audit loop
    # still visits cancelled rows, which is a no-op for them by construction
    # (an embedding backfill carries no `presigned` marker, so it is never in
    # the cancelled class).
    pending_rows = [(row[0], row[1], row[2]) for row in unbound_rows]
    pending_job_ids = [row[0] for row in unbound_rows]

    # fix(#1234): the other half. A row that DID bind bytes but never committed
    # its status is now exempt from the 1h clause, and the retention purge only
    # considers terminal rows — so without this it is immortal. A day is far
    # past any legitimate completion, and the message says which failure this
    # is so an operator is not told the upload "never queued".
    bound_pending_result = await db.execute(
        update(IngestJob)
        .where(*stale_pending_clauses(now, completion_bound=True))
        .values(
            status="failed",
            error_message=STALE_PENDING_BOUND_MESSAGE,
            completed_at=now,
        )
        .returning(IngestJob.id, IngestJob.user_metadata, IngestJob.created_by)
    )
    bound_pending_rows = list(bound_pending_result.all())
    pending_rows += bound_pending_rows
    pending_job_ids += [row[0] for row in bound_pending_rows]

    running_cutoff = now - timedelta(seconds=JOB_TIMEOUT_SECONDS)
    running_result = await db.execute(
        update(IngestJob)
        .where(
            IngestJob.status == "running",
            func.coalesce(IngestJob.heartbeat_at, IngestJob.started_at)
            < running_cutoff,
        )
        .values(
            status="failed",
            error_message=(
                f"Stale: running for over {JOB_TIMEOUT_SECONDS // 60} minutes"
            ),
            completed_at=now,
        )
        .returning(IngestJob.id, IngestJob.user_metadata, IngestJob.created_by)
    )
    running_rows = list(running_result.all())
    running_job_ids = [row[0] for row in running_rows]

    # fix(#1550 review): the row and its audit trail are settled by the same
    # actor, in the same transaction. After a hard kill this sweep is the only
    # actor left, so an embedding backfill it fails here would otherwise stay
    # `requested` in the audit log forever while its job row is terminal.
    for job_id_, user_metadata_, created_by_ in running_rows:
        await audit_settled_embedding_backfill(
            db,
            job_id=job_id_,
            user_metadata=user_metadata_,
            created_by=created_by_,
            error_code="worker_lost",
        )
    for job_id_, user_metadata_, created_by_ in pending_rows:
        await audit_settled_embedding_backfill(
            db,
            job_id=job_id_,
            user_metadata=user_metadata_,
            created_by=created_by_,
            error_code="never_started",
        )

    # fix(#1709 review r7 A): reconcile fan-out parents stranded by a crash
    # between the pre-dispatch flip and the first child commit. Since the r5
    # fix, `fanned_out` COMMITS before any child exists (the mutex that
    # closed the fast-child cancel window) — which regressed the
    # recoverability the old late transition got for free: the old crash
    # left a `pending` parent this sweep's one-hour clause self-healed,
    # while the new one left a terminal parent that retry (failed-only) and
    # cancel (terminal -> 409) both refuse. Permanently stuck, zero
    # children, staged file idle.
    #
    # A childless `fanned_out` parent is the crash signature and nothing
    # else's: a layer's `queued` result requires its child row to have
    # committed first (a failed defer still leaves the row, flipped `failed`
    # by the orphan guard; a failure before the insert commits leaves no row
    # AND no queued result), and an ALL-failed dispatch restores the parent
    # to `pending` rather than leaving it `fanned_out`
    # (restore_fan_out_parent_pending). Two bounds keep the signature exact:
    #
    # - the grace above: never touch a dispatch still in flight.
    # - the retention horizon: a LEGIT old fan-out's children can be deleted
    #   by the retention purge, after which "never existed" and "purged at
    #   age" are indistinguishable — but the purge cutoff is
    #   coalesce(completed_at, created_at) and every child postdates its
    #   parent's flip, so a parent still INSIDE the horizon cannot have lost
    #   children to it. Parents past the horizon are the purge's to delete,
    #   not this clause's to relabel (the freak alignment — children crossing
    #   the horizon seconds before an old-ordering parent — costs a `failed`
    #   label the same purge erases seconds later). retention_days=0 keeps
    #   every row forever, so no bound is needed.
    #
    # `failed`, not `cancelled`: nothing was asked to stop — a dispatch was
    # interrupted — and `failed` is what makes /jobs/{id}/retry offer the
    # parent again (retry flips it to `pending`; the fan-out is then
    # committable again), which is the recoverability being restored.
    #
    # Not folded into StaleCleanupOutcome, same reasoning as the refresh-run
    # sweep below: the dataclass is a published shape several callers
    # reconstruct field by field, and the log line carries the ids.
    childless_fanout_clauses = [
        IngestJob.status == "fanned_out",
        IngestJob.completed_at.is_not(None),
        IngestJob.completed_at
        < now - timedelta(seconds=FAN_OUT_CHILDLESS_GRACE_SECONDS),
        text(
            "NOT EXISTS (SELECT 1 FROM catalog.ingest_jobs c"
            " WHERE c.user_metadata->>'fan_out_parent_id' = ingest_jobs.id::text)"
        ),
    ]
    if settings.ingest_jobs_retention_days > 0:
        childless_fanout_clauses.append(
            IngestJob.completed_at
            >= now - timedelta(days=settings.ingest_jobs_retention_days)
        )
    childless_fanout_result = await db.execute(
        update(IngestJob)
        .where(*childless_fanout_clauses)
        .values(
            status="failed",
            error_message=FAN_OUT_DISPATCH_INTERRUPTED_MESSAGE,
            completed_at=now,
            # fix(#1709 review r8 A): the marker _retry_capability refuses on.
            # Generic retry of this parent would silently import ONE default
            # layer of a multi-layer file; restore-to-pending is no better —
            # the pending sweep's unbound clause keys on created_at, so any
            # parent older than that cutoff would be re-reaped into the
            # GENERIC failed message on the next pass, and the generic row
            # retries into exactly that wrong import.
            user_metadata=func.coalesce(
                IngestJob.user_metadata, text("'{}'::jsonb")
            ).op("||")(
                text(f"'{{\"{FAN_OUT_INTERRUPTED_METADATA_KEY}\": true}}'::jsonb")
            ),
        )
        .returning(IngestJob.id)
    )
    childless_fanout_ids = list(childless_fanout_result.scalars())
    if childless_fanout_ids:
        log.warning(
            "childless_fanned_out_parents_failed",
            job_ids=[str(job_id_) for job_id_ in childless_fanout_ids],
        )

    # GAP-002: sweep stale VRT regenerating assets using the same cutoff.
    # fix(#1322 review): stale_generation_storage_keys are resolved, not yet
    # deleted — carried into StaleCleanupOutcome and reaped only after this
    # function's own commit (or its commit=False caller's) lands, exactly
    # like _staged_paths below.
    (
        vrt_assets_recovered,
        vrt_generations_failed,
        stale_generation_storage_keys,
    ) = await sweep_stale_vrt_assets(db, running_cutoff)

    # feat(#1219): cancel refresh runs whose task is proven gone. Ordered
    # AFTER the two job sweeps above on purpose — those flip an orphaned job
    # to `failed`, which is one of the two facts the run sweep requires before
    # it may write a terminal status. Deliberately not folded into
    # StaleCleanupOutcome: the run rows are themselves the record, and the
    # dataclass is a published shape several callers reconstruct field by
    # field.
    cancelled_runs = await sweep_abandoned_refresh_runs(db, now)
    if cancelled_runs:
        log.info("abandoned_refresh_runs_cancelled", count=cancelled_runs)

    terminal_jobs_purged = 0
    staged_paths_considered = 0
    local_files_reaped = 0
    storage_objects_reaped = 0
    staged_paths_skipped = 0
    staged_cleanup_failures = 0
    deleted_paths: set[str] = set()
    deleted_presigned_keys: set[str] = set()

    # fix(#434): purge terminal jobs past retention so the admin Jobs page
    # doesn't accumulate history forever. Cutoff is on finished-at
    # (coalesce(completed_at, created_at)) rather than created_at — the stale
    # sweep above fails ancient pending/running rows with completed_at=now, and
    # a created_at cutoff would delete that fresh failure evidence in the same
    # transaction (codex P2 r8). 0 = keep forever. Each dataset's most recent
    # complete job is exempt regardless of age: /jobs/by-dataset/{id} serves the
    # dataset page's persistent ingest warnings and the reupload source_layer
    # hint from it (codex P2 on #434). Jobs whose dataset was deleted have
    # dataset_id nulled (FK ondelete=SET NULL) and stay purgeable.
    if settings.ingest_jobs_retention_days > 0:
        retention_cutoff = now - timedelta(days=settings.ingest_jobs_retention_days)
        latest_complete_ids = (
            select(IngestJob.id)
            .where(
                IngestJob.status == "complete",
                IngestJob.dataset_id.is_not(None),
            )
            .distinct(IngestJob.dataset_id)
            .order_by(IngestJob.dataset_id, IngestJob.created_at.desc())
        )
        # codex P2 (r7) on #434: manifest apply classifies skip/update-vs-create
        # via _latest_completed_manifest_job (manifest_service.py), which looks
        # up the newest complete job per user_metadata->>'manifest_key'. A
        # manual reupload makes the manual job the per-dataset exemption, so
        # without this second exemption the manifest-keyed row would age out
        # and the next apply would duplicate the dataset. Mirrors the lookup's
        # ordering (completed_at desc, created_at desc).
        manifest_key = IngestJob.user_metadata["manifest_key"].astext
        latest_manifest_ids = (
            select(IngestJob.id)
            .where(
                IngestJob.status == "complete",
                manifest_key.is_not(None),
                # codex P2 (r9): the mirrored lookup joins Dataset, so a job
                # whose dataset was deleted (dataset_id nulled by the FK) can't
                # influence reapply — exempting it would only defeat cleanup.
                IngestJob.dataset_id.is_not(None),
            )
            .distinct(manifest_key)
            .order_by(
                manifest_key,
                IngestJob.completed_at.desc(),
                IngestJob.created_at.desc(),
            )
        )
        # fix(#1236 review, codex P1): a presigned job's ROW is the only place
        # _sweep_expired_presigned_staging's markers live. Purging it before
        # any URL issued for it can possibly still be live removes that
        # tracking outright — worse than the marker gap this PR closes,
        # because a re-PUT afterward recreates an object no row anywhere
        # references, and retention (unlike the sweep's own cutoff) is
        # commonly configured well under a week (1 day is an exercised
        # value).
        #
        # fix(#1236 review r2, codex P1): deferred exactly as long as the
        # sweep's own FINALIZATION window, not just its ceiling — an accepted
        # PUT can still be transferring past MAX_PRESIGNED_URL_LIFETIME_SECONDS,
        # which is why the sweep itself withholds its final marker for
        # _RECHECK_TRANSFER_MARGIN_SECONDS longer. Purging on the bare
        # ceiling reopened the exact race this row exists to close, just
        # moved to the retention purge instead of the sweep. Past the
        # combined window purging is safe and `deleted_presigned_keys` below
        # still reaps the object at that same moment — the row just doesn't
        # need to survive to see it happen.
        #
        # fix(#1236 review r4, codex P1): that margin is now the SAME fixed
        # constant the sweep uses (see its definition for why r3's per-job
        # `expected_size` scaling proved unsafe) — no per-row data needed, so
        # this bulk DELETE never has to branch per row on JSONB.
        #
        # fix(#1236 review r5, codex P2): a non-null `s3_key` alone is not
        # OWNERSHIP. `create_fan_out_jobs` clones the parent's `user_metadata`
        # wholesale (processing/ingest/service.py), so every fan-out child
        # carries the PARENT's `s3_key` too — the exact case
        # `owned_presigned_staging_key` exists to reject, by requiring the
        # key's prefix match the ROW'S OWN id. Without that same check here,
        # every terminal fan-out child was exempted from retention for
        # ~8.9 days regardless of how short `ingest_jobs_retention_days` was
        # configured, since it can never be the row that legitimately reaps
        # or finalizes that key. A `LIKE` prefix match is a safe string
        # comparison — unlike a JSONB-to-numeric/timestamptz cast, it cannot
        # throw and fail the whole bulk pass on a malformed value.
        presigned_url_may_still_be_live = and_(
            IngestJob.user_metadata["s3_key"].astext.is_not(None),
            IngestJob.user_metadata["s3_key"].astext.like(
                func.concat("staging/", IngestJob.id, "/%")
            ),
            IngestJob.created_at
            >= now
            - timedelta(
                seconds=MAX_PRESIGNED_URL_LIFETIME_SECONDS
                + _RECHECK_TRANSFER_MARGIN_SECONDS
            ),
        )
        # Single DELETE .. RETURNING re-applies every predicate atomically at
        # delete time — a SELECT-then-DELETE-by-id pair let /jobs/{id}/retry
        # flip a candidate back to pending between the two statements and
        # still lose the row (codex P2 r10 on #434).
        deleted = await db.execute(
            delete(IngestJob)
            .where(
                IngestJob.status.not_in(("pending", "running")),
                func.coalesce(IngestJob.completed_at, IngestJob.created_at)
                < retention_cutoff,
                IngestJob.id.not_in(latest_complete_ids),
                IngestJob.id.not_in(latest_manifest_ids),
                not_(presigned_url_may_still_be_live),
            )
            .returning(IngestJob.id, IngestJob.file_path, IngestJob.user_metadata)
        )
        deleted_rows = deleted.all()
        terminal_jobs_purged = len(deleted_rows)
        deleted_paths = {fp for (_id, fp, _um) in deleted_rows if fp}
        # fix(#1202 review r5): a purged presigned job's staging key is the one
        # reference left to an object the client's PUT URL can still recreate.
        deleted_presigned_keys = {
            key
            for (job_row_id, fp, um) in deleted_rows
            if (key := owned_presigned_staging_key(job_row_id, um, fp))
        }
        if deleted_rows:
            log.info(
                "Purged ingest jobs past retention",
                purged=len(deleted_rows),
                retention_days=settings.ingest_jobs_retention_days,
            )

        # codex P2 (r3) on #434: failed local uploads keep their staged file
        # for retry (_should_unlink_staging), and fan-out children's shared S3
        # original is explicitly deferred to "a retention policy" (#430 BA-09)
        # — this purge is that policy. Reap staged objects whose last pointer
        # was just deleted, but (codex P2 r4) only when no surviving row that
        # still NEEDS the file references the same path: pending/running read
        # it now; failed keeps it for /jobs/{id}/retry (a failed-only
        # endpoint). Surviving complete rows (e.g. the exemptions above) keep
        # their metadata row but not the staged file — otherwise a successful
        # fan-out's shared original, referenced forever by children that are
        # each a dataset's latest complete job, would never be reaped
        # (codex P2 r5). Running after the DELETE, any remaining row counts.
        if deleted_paths:
            survivors = await db.execute(
                select(IngestJob.file_path).where(
                    IngestJob.file_path.in_(deleted_paths),
                    IngestJob.status.in_(STATUSES_NEEDING_STAGED_INPUT),
                )
            )
            deleted_paths -= set(survivors.scalars())
        staged_paths_considered = len(deleted_paths)

    # fix(#1746): backstop for the token purge the service tasks run on their
    # own failure path (`purge_token_on_failure` in processing/ingest/
    # tasks_common.py). A row that never reached that handler still holds the
    # raw service token in its kwargs — a worker killed mid-attempt, a job
    # cancelled before it was ever claimed, a row deferred before this fix —
    # and the worker's `delete_jobs="successful"` only ever removes the rows
    # that succeeded. Terminal statuses only: `todo` is still waiting to be
    # worked with those args, and `doing` is being worked right now.
    # (`aborting` is legacy in procrastinate 3.x and never written.) Last
    # statement in the sweep so it costs nothing when there is nothing to do.
    await db.execute(
        text(
            "UPDATE catalog.procrastinate_jobs SET args = args - 'token' "
            "WHERE status NOT IN ('todo', 'doing') AND args ? 'token'"
        )
    )

    outcome = StaleCleanupOutcome(
        pending_failed=len(pending_job_ids) - pending_cancelled,
        pending_cancelled=pending_cancelled,
        running_failed=len(running_job_ids),
        vrt_assets_recovered=vrt_assets_recovered,
        vrt_generations_failed=vrt_generations_failed,
        terminal_jobs_purged=terminal_jobs_purged,
        staged_paths_considered=staged_paths_considered,
        local_files_reaped=local_files_reaped,
        storage_objects_reaped=storage_objects_reaped,
        staged_paths_skipped=staged_paths_skipped,
        staged_cleanup_failures=staged_cleanup_failures,
        _staged_paths=tuple(sorted(deleted_paths)),
        _staged_presigned_keys=tuple(sorted(deleted_presigned_keys)),
        _refresh_runs_reconciled=cancelled_runs,
        _stale_generation_storage_keys=stale_generation_storage_keys,
    )
    if commit:
        # Never remove an external artifact for a DELETE that may still roll
        # back. A crash after this commit can leak a staging object, but it
        # cannot restore a job row whose only retry input has been destroyed.
        await db.commit()
        publish_refresh_reconciliation(outcome)
        outcome = await _reap_committed_staged_paths(outcome)
        outcome = await _sweep_expired_presigned_staging(db, outcome, now=now)
        # fix(#1249): the row-driven reapers above can only clean up objects
        # some surviving row still names. This one starts from the objects and
        # asks whether any row still owns them, which is the only direction
        # that finds one nothing references. Deliberately not folded into
        # StaleCleanupOutcome — that dataclass is a published API and audit
        # shape several callers reconstruct field by field, and this pass
        # answers a different question with its own log line and counter.
        await reconcile_orphaned_staging_objects(db, now=now)
    if detailed:
        return outcome
    return outcome.pending_failed, outcome.running_failed


async def audit_settled_embedding_backfill(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    user_metadata: dict | None,
    created_by: uuid.UUID | None,
    error_code: str,
    settled_by: uuid.UUID | None = None,
) -> None:
    """Close an embedding backfill's audit trail when a sweeper settles its row.

    fix(#1550 review): every other way a backfill can end is closed inside the
    worker — the dispatch failure, a lost fence, cancellation, a failing
    terminal write, a lost commit acknowledgement. A hard kill has no
    in-process path to close, because after SIGKILL there is no process. The
    row is then settled by whoever notices it is stale, and that actor is the
    only one left that can record the outcome. Without this the trail stays at
    `requested` forever while the job is terminal, and on the force path that
    can be a catalog whose vectors were deleted.

    The rule the module now follows: **the job row and the audit trail are
    written together by whichever actor settles the job.** After a hard kill,
    that actor is the sweeper.

    Emitted on the caller's session, deliberately, so the audit row and the
    status change commit or roll back as one. `audit_emit_durable` would use
    its own session and could record an outcome for a row whose update was
    later rolled back — the same divergence in the other direction.

    Correlated by `operation_id`, read back off the job row's own metadata, so
    it pairs with the `requested` entry the route committed alongside the job.
    A no-op for every other kind of job.
    """
    marker = (user_metadata or {}).get(EMBEDDING_BACKFILL_METADATA_KEY)
    if not marker:
        return
    # One operation gets one terminal entry, and the DATABASE decides which —
    # `uq_audit_logs_terminal_embedding_backfill` (migration 0051). Three
    # actors can close the same run, so an existence check here would be a
    # check-then-insert: both read "nothing yet", both insert, and the trail
    # carries two conflicting outcomes.
    #
    # Wrapped in a SAVEPOINT so losing that race rolls back only this insert.
    # The audit is emitted on the caller's session precisely so it commits with
    # the status change; an unguarded IntegrityError would take the status
    # change down with it.
    # fix(#1709 review r10): the terminal event is attributed to the actor
    # who SETTLED the run when one exists. The sweeps have no acting user —
    # a lease expiry is nobody's click, so the requester (created_by) stays
    # the honest attribution there — but the cancel endpoint acts on behalf
    # of a specific person, and in the arm-3/cross-user case that person is
    # not the requester. Same rule refresh.cancelled follows since r8.
    actor = settled_by if settled_by is not None else created_by
    try:
        async with session.begin_nested():
            await _emit_terminal_backfill_event(
                session, marker, job_id, actor, error_code
            )
    except IntegrityError:
        log.info(
            "embedding_backfill_terminal_audit_already_recorded",
            job_id=str(job_id),
            skipped_error_code=error_code,
        )


async def _emit_terminal_backfill_event(
    session: AsyncSession,
    marker: dict,
    job_id: uuid.UUID,
    actor: uuid.UUID | None,
    error_code: str,
) -> None:
    """Write the one terminal entry. ``actor`` is whoever SETTLED the run —
    the canceller when a person cancelled it, else the requester (fix(#1709
    review r10); a sweep has no acting user to name)."""
    # Deferred by design to preserve the platform -> modules layer boundary,
    # matching `cleanup_stale_jobs` above.
    from app.modules.audit.service import AuditEvent, audit_emit

    await audit_emit(
        session,
        AuditEvent(
            user_id=actor,
            # Literal, not the constant: test_audit_action_registry checks
            # every emit site statically and cannot resolve a name. The
            # other writer of this action is the admin backfill task.
            action="embedding.backfill",
            resource_type="record_embedding",
            details={
                "force": bool(marker.get("force")),
                "operation_id": marker.get("operation_id"),
                "job_id": str(job_id),
                "outcome": "failed",
                "error_code": error_code,
            },
            # No request behind a sweep, and inventing one would be a fiction
            # in a record whose purpose is attribution.
            ip_address=None,
        ),
    )
