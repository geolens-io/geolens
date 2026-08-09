"""Job status API endpoints: poll ingestion job progress and retry."""

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, cast, overload

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, delete, func, not_, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import MAX_PRESIGNED_URL_LIFETIME_SECONDS, settings
from app.core.dependencies import get_client_ip, get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import (
    get_current_active_user,
    require_mode_permission,
    require_permission,
)
from app.processing.ingest.schemas import UploadResponse
from app.processing.ingest.service import queue_ingest_job
from app.platform.extensions import get_permission_extension
from app.platform.jobs.heartbeat import ANALYSIS_MATERIALIZE_LEASE_SECONDS
from app.platform.jobs.models import IngestJob, owned_presigned_staging_key
from app.observability.metrics.refresh import refresh_sweep_reconciled_total
from app.platform.refresh.service import sweep_abandoned_refresh_runs
from app.platform.jobs.schemas import (
    DbfTruncationCollisionWarning,
    JobStatusResponse,
    MercatorClipWarning,
    ReservedRenameWarning,
    StaleCleanupResponse,
)
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.standards.ogc.errors import CONFLICT_RESPONSE, ERROR_RESPONSES_AUTH

log = structlog.get_logger()

# Contract: only these two keys may appear in temporal_parse_errors. The
# alias lets ``cast`` narrow dict writes without triggering ruff F821 on
# string literals inside the ``Literal[...]`` expression.
TemporalParseKey = Literal["temporal_start", "temporal_end"]

router = APIRouter(prefix="/jobs", tags=["Admin"], responses=ERROR_RESPONSES_AUTH)

# Jobs running longer than this are considered stale and auto-failed. This is
# the worker LEASE on a RUNNING job, not the presigned-upload lifetime below:
# the two share a number today and answer unrelated questions, so deriving one
# from the other would only look like agreement.
JOB_TIMEOUT_SECONDS = 3600  # 60 minutes (accommodates remote service imports)


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
    return (
        IngestJob.status == "pending",
        IngestJob.created_at < now - timedelta(seconds=cutoff_seconds),
        completion_key if completion_bound else not_(completion_key),
        no_live_procrastinate_job(),
    )


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
        """Legacy count: ingest jobs transitioned from active to failed."""
        return self.pending_failed + self.running_failed

    @property
    def total_affected(self) -> int:
        """Rows and staged objects mutated by the cleanup pass."""
        return (
            self.total_cleaned
            + self.vrt_assets_recovered
            + self.vrt_generations_failed
            + self.terminal_jobs_purged
            + self.local_files_reaped
            + self.storage_objects_reaped
        )

    def as_dict(self) -> dict[str, int]:
        """Return the stable API and audit detail shape."""
        return {
            "pending_failed": self.pending_failed,
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
_STAGING_REAPED_FINAL_MARKER = "s3_key_reaped_final"

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
    from app.core.tenancy import is_multi_tenant
    from app.core.db.tenant_session import current_tenant_var
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
       underneath the attempt. ``add_vrt_source``/``remove_vrt_source``
       commit their ``vrt_source_links`` mutation in the same transaction
       that flips the asset to ``'regenerating'``, BEFORE the regeneration
       itself ever runs, so a dead attempt of THAT kind leaves the
       catalog's stated composition already ahead of the served bytes.
       Restoring ``'ready'`` there would erase the only visible signal of
       that drift — the status endpoint reads the link set, not the served
       VRT, and would report a reduced (or expanded) source list as fully
       healthy while stale composition keeps being served.
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
    # RETURNING carries vrt_dataset_id alongside id (feat(#1267)): the
    # generation-scoped storage key each dead attempt wrote to is keyed on
    # BOTH, and the asset UPDATE below cannot supply that pairing back — its
    # own current_generation_id is nulled in the same statement, so RETURNING
    # it would report the value AFTER the SET, not the attempt being reaped.
    stale_gen_result = await db.execute(
        update(VrtGeneration)
        .where(
            *generation_scope,
            VrtGeneration.status.in_(["pending", "running"]),
            func.coalesce(VrtGeneration.heartbeat_at, VrtGeneration.started_at)
            < stale_cutoff,
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
    # PRESERVING attempt. add_vrt_source / remove_vrt_source commit their
    # vrt_source_links mutation in the SAME transaction that flips the asset
    # to 'regenerating' — BEFORE the regeneration itself ever runs. If that
    # attempt then dies, the catalog's link set already reflects the NEW
    # composition while the published asset_uri (untouched by the dead
    # attempt) still serves the OLD one. Restoring 'ready' would erase the
    # only visible signal of that drift: the status endpoint reads the link
    # set, not the served bytes, and would report the new (reduced) source
    # list as fully healthy while stale data keeps being served.
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
    pending_result = await db.execute(
        update(IngestJob)
        .where(*stale_pending_clauses(now, completion_bound=False))
        .values(
            status="failed",
            error_message=STALE_PENDING_UNBOUND_MESSAGE,
            completed_at=now,
        )
        .returning(IngestJob.id)
    )
    pending_job_ids = list(pending_result.scalars())

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
        .returning(IngestJob.id)
    )
    pending_job_ids += list(bound_pending_result.scalars())

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
        .returning(IngestJob.id)
    )
    running_job_ids = list(running_result.scalars())

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
                    IngestJob.status.in_(("pending", "running", "failed")),
                )
            )
            deleted_paths -= set(survivors.scalars())
        staged_paths_considered = len(deleted_paths)
    outcome = StaleCleanupOutcome(
        pending_failed=len(pending_job_ids),
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
    if detailed:
        return outcome
    return outcome.pending_failed, outcome.running_failed


async def _can_access_another_users_job(
    request: Request,
    db: AsyncSession,
    user: Identity,
    job: IngestJob,
) -> bool:
    """Delegate cross-user job access to the effective permission policy.

    Owner access is handled by callers before invoking this helper. Passing the
    job as ``resource`` lets enterprise extensions apply finer-grained policy
    without core code falling back to a hard-coded role-name check.
    """
    # Deferred by design: shared platform code must not import product-domain
    # policy implementations at module load time (D-17).
    from app.modules.auth.dependencies import (
        get_cached_user_roles,
        log_permission_denial,
    )
    from app.modules.auth.permissions import get_effective_permissions

    user_roles = await get_cached_user_roles(request, db, user)
    matrix = getattr(request.state, "_effective_permissions", None)
    if matrix is None:
        matrix = await get_effective_permissions(db)
        request.state._effective_permissions = matrix
    granted = await get_permission_extension().check_permission(
        db,
        user,
        "manage_users",
        user_roles=user_roles,
        permission_matrix=matrix,
        resource=job,
    )
    if not granted:
        log_permission_denial(
            request,
            user,
            "manage_users",
            user_roles,
            resource_type="ingest_job",
        )
    return granted


@router.post("/cleanup/stale/", response_model=StaleCleanupResponse)
async def cleanup_stale_jobs(
    request: Request,
    user: Identity = Depends(
        require_mode_permission(
            single_tenant="manage_users", multi_tenant="manage_tenants"
        )
    ),
    db: AsyncSession = Depends(get_db),
) -> StaleCleanupResponse:
    """Fail all stale jobs: pending >1h or running >1h.

    **Ops-only.** Not used by the GeoLens UI — invoke from `curl`/`gh api`/cron
    when you need to force-clean orphaned jobs after a worker outage.
    Equivalent logic runs automatically every 5 minutes via the lifespan
    sweeper, so this endpoint is only needed if you need cleanup faster than
    that interval.
    """
    from app.core.tenancy import is_multi_tenant

    # Deferred by design to preserve the platform -> modules layer boundary.
    from app.modules.audit.service import AuditEvent, audit_emit, audit_emit_durable

    operation_uuid = uuid.uuid4()
    operation_id = str(operation_uuid)
    ip_address = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="job.cleanup_stale",
            resource_type="ingest_job",
            resource_id=operation_uuid,
            details={"operation_id": operation_id, "outcome": "requested"},
            ip_address=ip_address,
        ),
    )
    # Retention cleanup can unlink local files and delete S3 objects. Make the
    # operator's request durable before entering that irreversible phase.
    await db.commit()

    try:
        multi_tenant = is_multi_tenant()
        if multi_tenant:
            # FORCE RLS makes a request session visible only to its current
            # tenant. The lifecycle helper opens a scoped transaction for
            # every tenant and reaps each tenant's staged objects in context.
            from app.api.main import sweep_stale_jobs_once

            fleet_details = await sweep_stale_jobs_once(detailed=True)
            if not isinstance(fleet_details, dict):
                raise TypeError("Detailed fleet cleanup returned no details")
            database_details = fleet_details
        else:
            outcome = await fail_stale_jobs(db, commit=False, detailed=True)
            database_details = outcome.as_dict()
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="job.cleanup_stale",
                resource_type="ingest_job",
                resource_id=operation_uuid,
                details={
                    "operation_id": operation_id,
                    "outcome": "database_committed",
                    **database_details,
                },
                ip_address=ip_address,
            ),
        )
        # In single-tenant mode, commit database mutations plus a durable phase
        # marker before touching local/S3 artifacts. The fleet helper applies
        # that ordering inside each tenant-scoped transaction.
        await db.commit()
        if multi_tenant:
            details = database_details
        else:
            # fix(#1277 review): this path passed commit=False, so the sweep
            # deferred its counter to whoever owns the commit — that is the
            # line above. The multi-tenant branch needs nothing here: the
            # fleet helper runs fail_stale_jobs with its own commit per
            # tenant, so each tenant's pass publishes its own.
            publish_refresh_reconciliation(outcome)
            outcome = await _reap_committed_staged_paths(outcome)
            outcome = await _sweep_expired_presigned_staging(db, outcome)
            details = outcome.as_dict()
    except Exception as exc:  # broad: cleanup spans DB and artifact deletion
        await db.rollback()
        # Cleanup failures can embed local paths or storage keys in exception
        # messages. Record only the exception class in operator telemetry; the
        # correlated audit event likewise carries a stable error code only.
        log.error(
            "Stale job cleanup failed",
            operation_id=operation_id,
            user_id=str(user.id),
            error_type=type(exc).__name__,
        )
        try:
            # A failed commit may leave the request session/connection unusable;
            # persist the terminal outcome through an independently owned session.
            await audit_emit_durable(
                AuditEvent(
                    user_id=user.id,
                    action="job.cleanup_stale",
                    resource_type="ingest_job",
                    resource_id=operation_uuid,
                    details={
                        "operation_id": operation_id,
                        "outcome": "failed",
                        "error_code": "cleanup_failed",
                    },
                    ip_address=ip_address,
                )
            )
        except Exception as audit_exc:  # broad: retain the generic failure response
            log.error(
                "Failed to persist stale cleanup failure audit",
                operation_id=operation_id,
                user_id=str(user.id),
                error_type=type(audit_exc).__name__,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stale job cleanup failed. See server logs for details.",
        ) from None

    # Cleanup has already committed and reaped its artifacts. A bookkeeping
    # outage must not turn that successful mutation into a retryable 500 or
    # emit a contradictory ``failed`` event; the committed phase marker still
    # provides a durable recovery trail.
    try:
        await audit_emit_durable(
            AuditEvent(
                user_id=user.id,
                action="job.cleanup_stale",
                resource_type="ingest_job",
                resource_id=operation_uuid,
                details={
                    "operation_id": operation_id,
                    "outcome": "completed",
                    **details,
                },
                ip_address=ip_address,
            )
        )
    except Exception as audit_exc:  # broad: cleanup itself has succeeded
        log.error(
            "Failed to persist stale cleanup completion audit",
            operation_id=operation_id,
            user_id=str(user.id),
            error_type=type(audit_exc).__name__,
        )

    return StaleCleanupResponse(**details)


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: uuid.UUID,
    request: Request,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> JobStatusResponse:
    """Get the status of an ingestion job.

    Only the job creator or an admin can view job status.
    """
    result = await db.execute(select(IngestJob).where(IngestJob.id == job_id))
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Owners always retain access. Cross-user access follows the active
    # capability policy rather than assuming a hard-coded "admin" role.
    if job.created_by != user.id and not await _can_access_another_users_job(
        request, db, user, job
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this job",
        )

    now = datetime.now(timezone.utc)

    # Auto-fail jobs whose worker lease has expired. Fall back to started_at
    # for jobs created before heartbeat support was deployed.
    #
    # fix(#691): analysis materialize jobs use the short materialize lease
    # rather than the 60-minute backstop, mirroring the per-user cap in
    # router_analysis.py. The frontend polls this route for any job it
    # tracks, so a hard-killed worker's analysis job flips to failed within
    # the lease window and the Analysis panel's Create button re-enables at
    # the same moment the server would admit a new materialize — the client
    # follows the server's signal without needing heartbeat visibility.
    liveness_at = job.heartbeat_at or job.started_at
    if job.status == "running" and liveness_at is not None:
        is_analysis = "analysis" in (job.user_metadata or {})
        lease_seconds = (
            ANALYSIS_MATERIALIZE_LEASE_SECONDS if is_analysis else JOB_TIMEOUT_SECONDS
        )
        elapsed = (now - liveness_at).total_seconds()
        if elapsed > lease_seconds:
            await db.execute(
                update(IngestJob)
                .where(
                    IngestJob.id == job.id,
                    IngestJob.attempt_id == job.attempt_id,
                    IngestJob.status == "running",
                    func.coalesce(IngestJob.heartbeat_at, IngestJob.started_at)
                    < now - timedelta(seconds=lease_seconds),
                )
                .values(
                    status="failed",
                    error_message=f"Worker heartbeat expired after {int(elapsed)}s",
                    completed_at=now,
                )
            )
            await db.commit()
            await db.refresh(job)

    # Auto-fail jobs stuck in "pending" beyond the timeout (orphaned / never
    # queued). fix(#724 review): gated on the same live-queue predicate the
    # sweeper uses — this is the path that actually fires, because the frontend
    # polls this route every 2s for any job it is tracking.
    if job.status == "pending" and job.created_at is not None:
        elapsed = (now - job.created_at).total_seconds()
        # fix(#1235 review r2): both halves, through the shared clauses. This
        # path is the one that actually fires, so leaving it on the old
        # predicates left the completion race exactly where it was — a poll
        # blocked on a completing job's row lock resumes post-commit and fails
        # the row it waited for.
        for completion_bound, message in (
            (False, f"Stale: pending for {int(elapsed)}s without being processed"),
            (True, STALE_PENDING_BOUND_MESSAGE),
        ):
            # fix(#1235 review r4): a fast-path skip, NOT a correctness gate.
            # The clauses below remain the authority — they re-check the same
            # age in SQL, so a row that slips past this check is still only
            # failed if it genuinely qualifies. What this restores is the outer
            # `elapsed` check the r2 rewrite dropped: without it, every 2s poll
            # of every pending job issued both UPDATEs, and the frontend polls
            # this route for the whole life of a job that is behaving normally.
            if elapsed <= stale_pending_cutoff_seconds(
                completion_bound=completion_bound
            ):
                continue
            result = await db.execute(
                update(IngestJob)
                .where(
                    IngestJob.id == job.id,
                    IngestJob.attempt_id == job.attempt_id,
                    *stale_pending_clauses(now, completion_bound=completion_bound),
                )
                .values(
                    status="failed",
                    error_message=message,
                    completed_at=now,
                )
            )
            if result.rowcount:
                await db.commit()
                await db.refresh(job)
                break

    return await _job_to_status_response(job)


async def _retry_capability(job: IngestJob) -> tuple[bool, str | None]:
    if job.status != "failed":
        return False, None
    if bool((job.user_metadata or {}).get("reupload")):
        return (
            False,
            "Dataset replacement jobs cannot be replayed as ordinary imports. Start the reupload again.",
        )
    if bool((job.user_metadata or {}).get("refresh")):
        # feat(#1265): a registered-PostGIS refresh job carries no file and no
        # URL, so without this it fell through to the import copy below and
        # told the user their "source" was gone — for a dataset that was never
        # imported from one. Deliberately AFTER the reupload check: a service
        # refresh job carries both markers and keeps its existing wording.
        return (
            False,
            "Refresh runs cannot be replayed as imports. Refresh the dataset again from its source panel.",
        )
    if bool((job.user_metadata or {}).get("service_auth_required")):
        return (
            False,
            "This service import requires fresh credentials. Start the import again to re-authenticate.",
        )
    if (job.user_metadata or {}).get("analysis"):
        # ux(#698): analysis jobs carry file_path="" and would otherwise fall
        # through to the import copy below, telling the user their "source" is
        # gone and to "start the import again" for something that was never an
        # import. They are genuinely not replayable here either: the drawn clip
        # mask is deliberately not persisted (router_analysis.py stores a
        # marker, not the geometry), so a replay could not reconstruct the run.
        return (
            False,
            "Analysis runs cannot be replayed as imports. Start the analysis again from the map builder.",
        )
    if job.source_url and not job.file_path:
        return True, None
    if not job.file_path:
        return False, "The source is no longer available. Start the import again."

    from app.core.tenancy import is_multi_tenant

    candidate = Path(job.file_path)
    if candidate.exists() and (candidate.is_absolute() or not is_multi_tenant()):
        return True, None
    if job.file_path.startswith("/"):
        return False, "Staging file no longer available. Please re-upload."

    try:
        from app.platform.storage import get_storage

        physical_file_path = (
            resolve_current_storage_key(job.file_path)
            if job.file_path.startswith("staging/")
            else job.file_path
        )
        if await get_storage().exists(physical_file_path):
            return True, None
    except (
        Exception
    ):  # broad: storage implementations expose provider-specific failures
        log.warning(
            "retry_source_availability_check_failed",
            job_id=str(job.id),
            storage_key=job.file_path,
            exc_info=True,
        )
        return False, "Source availability could not be verified. Try again later."

    return False, "The staging object is no longer available. Please re-upload."


async def get_retry_capability(job: IngestJob) -> tuple[bool, str | None]:
    """Return the retry contract shared by user and admin job surfaces."""

    return await _retry_capability(job)


async def _job_to_status_response(job: IngestJob) -> JobStatusResponse:
    """Extract warnings + structured metadata from ``user_metadata`` (S3/TYPE-2).

    Shared by ``get_job_status`` (lookup by job_id) and
    ``get_job_status_by_dataset`` (lookup by dataset_id) so the warning-parse
    contract lives in a single place.

    Warnings are validated through the ``IngestJobWarning`` discriminated
    union; any malformed entry (unknown ``kind``, missing fields) is logged
    and dropped so a stale-producer bug cannot break the whole endpoint.
    """
    import structlog
    from pydantic import ValidationError

    logger = structlog.get_logger()

    warning_message: str | None = None
    warnings: list[
        ReservedRenameWarning | DbfTruncationCollisionWarning | MercatorClipWarning
    ] = []
    archive_failed = False
    temporal_parse_errors: dict[TemporalParseKey, str] = {}
    if job.user_metadata and isinstance(job.user_metadata, dict):
        warning_message = job.user_metadata.get("collision_warning")
        raw_warnings = job.user_metadata.get("warnings")
        if isinstance(raw_warnings, list):
            for raw in raw_warnings:
                if not isinstance(raw, dict):
                    continue
                kind = raw.get("kind")
                try:
                    if kind == "reserved_rename":
                        warnings.append(ReservedRenameWarning.model_validate(raw))
                    elif kind == "dbf_truncation_collision":
                        warnings.append(
                            DbfTruncationCollisionWarning.model_validate(raw)
                        )
                    elif kind == "mercator_clip":
                        warnings.append(MercatorClipWarning.model_validate(raw))
                    else:
                        logger.warning(
                            "Dropping ingest warning with unknown kind",
                            job_id=str(job.id),
                            kind=kind,
                        )
                except ValidationError as exc:
                    logger.warning(
                        "Dropping malformed ingest warning",
                        job_id=str(job.id),
                        kind=kind,
                        error=str(exc)[:500],
                    )
        archive_failed = bool(job.user_metadata.get("archive_failed"))
        raw_temporal = job.user_metadata.get("temporal_parse_errors")
        if isinstance(raw_temporal, dict):
            # Narrow to the contract keys — drop anything unknown so the
            # Pydantic ``Literal`` validation cannot reject the whole
            # response on a stale producer. ``cast`` makes the narrowing
            # explicit to mypy so no ``type: ignore`` is needed.
            for k, v in raw_temporal.items():
                key = str(k)
                if key in ("temporal_start", "temporal_end"):
                    temporal_parse_errors[cast(TemporalParseKey, key)] = str(v)

    can_retry, retry_reason = await _retry_capability(job)

    return JobStatusResponse(
        id=job.id,
        status=job.status,
        dataset_id=job.dataset_id,
        source_filename=job.source_filename,
        error_message=job.error_message,
        can_retry=can_retry,
        retry_reason=retry_reason,
        warning_message=warning_message,
        warnings=warnings,
        # REMED-02 / ingest-audit P2-07: surface worker-written progress fields.
        progress=job.progress,
        current_step=job.current_step,
        rows_processed=job.rows_processed,
        archive_failed=archive_failed,
        temporal_parse_errors=temporal_parse_errors,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )


@router.get("/by-dataset/{dataset_id}", response_model=JobStatusResponse | None)
async def get_job_status_by_dataset(
    dataset_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> JobStatusResponse | None:
    """Look up the most recent ingest job for a dataset.

    Used by the dataset detail page to surface ingest warnings permanently
    (S3 completion) — the job is the source of truth for
    ``reserved_rename`` / ``dbf_truncation_collision`` / ``mercator_clip`` /
    ``archive_failed`` / ``temporal_parse_errors`` metadata.

    Returns the most recently created completed job for the dataset. When the
    dataset is visible but has no ingest job (e.g. registered from an existing
    table, or a remote/STAC dataset), returns ``200`` with a ``null`` body
    instead of 404 — a "no job" outcome is normal for these datasets and a
    404 would needlessly pollute the browser console on the dataset detail
    page. A genuine 404 is still raised when the dataset is not visible to the
    user, to avoid leaking job existence (see visibility check below).
    """
    # Visibility check: reuse the dataset detail permission so only users
    # who can see the dataset can see the job warnings. Avoid leaking the
    # existence of jobs via 403 vs 404 divergence.
    from app.modules.catalog.authorization import (
        apply_visibility_filter,
        get_user_roles,
    )
    from app.modules.catalog.datasets.domain.models import (
        Dataset,
        DatasetGrant,
        Record,
    )

    user_roles = await get_user_roles(db, user)
    dataset_stmt = (
        select(Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id == dataset_id)
    )
    dataset_stmt = apply_visibility_filter(
        dataset_stmt, user, user_roles, Record, DatasetGrant
    )
    dataset_result = await db.execute(dataset_stmt)
    if dataset_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found or no ingest job associated",
        )

    job_result = await db.execute(
        select(IngestJob)
        .where(IngestJob.dataset_id == dataset_id)
        .order_by(IngestJob.created_at.desc())
        .limit(1)
    )
    job = job_result.scalar_one_or_none()
    if job is None:
        # Dataset is visible but has no ingest job (remote/STAC/registered
        # dataset). Return 200 + null rather than 404 so the dataset detail
        # page can treat it as "no warnings" without a console 404.
        return None

    return await _job_to_status_response(job)


@router.post(
    "/{job_id}/retry",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={409: CONFLICT_RESPONSE},
)
async def retry_job(
    job_id: uuid.UUID,
    request: Request,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """Retry a failed ingestion job by re-queuing.

    Only callable on jobs with status 'failed'. The staging file must
    still exist (preserved on failure for retry).
    """
    # Deferred by design to preserve the platform -> modules layer boundary.
    from app.modules.audit.service import AuditEvent, audit_emit

    result = await db.execute(select(IngestJob).where(IngestJob.id == job_id))
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Owners always retain access. Cross-user retries additionally require the
    # effective manage_users capability through PermissionExtension.
    if job.created_by != user.id and not await _can_access_another_users_job(
        request, db, user, job
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to retry this job",
        )

    if job.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only failed jobs can be retried",
        )

    can_retry, retry_reason = await _retry_capability(job)
    if not can_retry:
        status_code = (
            status.HTTP_409_CONFLICT
            if bool((job.user_metadata or {}).get("service_auth_required"))
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail=retry_reason or "This job cannot be retried.",
        )

    # Reset the job to pending and commit before re-queueing so the
    # orphan guard in queue_ingest_job can flip it back to failed if
    # the queue is down (RESILIENCE-2).
    previous_attempt_id = job.attempt_id
    next_attempt_id = uuid.uuid4()
    retry_result = await db.execute(
        update(IngestJob)
        .where(
            IngestJob.id == job.id,
            IngestJob.status == "failed",
            IngestJob.attempt_id == previous_attempt_id,
        )
        .values(
            status="pending",
            attempt_id=next_attempt_id,
            error_message=None,
            started_at=None,
            heartbeat_at=None,
            completed_at=None,
            dataset_id=None,
        )
    )
    if not retry_result.rowcount:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job was already retried by another request",
        )
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="job.retry",
            resource_type="ingest_job",
            resource_id=job.id,
            details={
                "job_owner_id": (
                    str(job.created_by) if job.created_by is not None else None
                ),
                "previous_attempt_id": (
                    str(previous_attempt_id)
                    if previous_attempt_id is not None
                    else None
                ),
                "next_attempt_id": str(next_attempt_id),
                "cross_user": job.created_by != user.id,
            },
            ip_address=get_client_ip(request),
        ),
    )
    await db.commit()
    await db.refresh(job)

    await queue_ingest_job(job, str(job.created_by), db=db)

    return UploadResponse(
        job_id=job.id,
        status="pending",
        message="Job re-queued for ingestion",
    )
