"""Stale-job recovery and sweep handlers (#1335 split from jobs/router.py).

Stale predicates for ``IngestJob`` and VRT ``RasterAsset``/``VrtGeneration``,
their reconciliation SQL, and the staged-artifact reapers, shared by the
lifespan sweeper, worker startup recovery, and the admin cleanup endpoint in
``router.py``, which re-exports these names for backward compatibility.
"""

import uuid
from collections.abc import Sequence
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
    COMMIT_ATTEMPTED_METADATA_KEY,
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

# Worker LEASE on a running job, not the presigned-upload lifetime below —
# they share a number today by coincidence; never derive one from the other.
JOB_TIMEOUT_SECONDS = 3600  # 60 minutes (accommodates remote service imports)

# fix(#1709): grace before a childless `fanned_out` parent counts as a crashed
# dispatch; the flip->first-child gap is sub-second, so one cadence is generous.
FAN_OUT_CHILDLESS_GRACE_SECONDS = 300

# fix(#1709): never advertise retry here. Generic retry re-queues the parent
# as ONE default-layer import and is refused on the marker; re-upload is the path.
FAN_OUT_DISPATCH_INTERRUPTED_MESSAGE = (
    "Fan-out dispatch was interrupted before any layer was queued. "
    "Re-upload the file to import its layers."
)


# fix(#1235): margin between the last legitimate PUT and a finished completion
# commit, added on top of the upload lifetime wherever a timer must sit beyond it.
_COMMIT_HEADROOM_SECONDS = 3600


def stale_pending_cutoff_seconds(*, completion_bound: bool) -> int:
    """Age at which each half of the pending sweep may fail a job.

    fix(#1235): read at CALL time, not cached — the bound half must stay
    beyond the upload lifetime, which a module-level copy could drift from.
    """
    if completion_bound:
        return max(
            86400,  # 24h floor — preserves the default behaviour exactly
            settings.pending_job_timeout_seconds + _COMMIT_HEADROOM_SECONDS,
        )
    return settings.pending_job_timeout_seconds


# fix(#1235): no hour in the message; the timeout is configurable.
STALE_PENDING_UNBOUND_MESSAGE = "Stale: pending too long (never queued)"
STALE_PENDING_BOUND_MESSAGE = "Stale: upload completed but never committed"


def stale_pending_clauses(now: datetime, *, completion_bound: bool) -> tuple:
    """Every predicate required to fail a timed-out pending job.

    fix(#1235): the one boundary shared by all four sites that flip
    pending -> failed on a timeout, so none can skip the bound/unbound split
    or the live-queue check.

    ``completion_bound`` selects the half by the ``staging/`` PREFIX of
    ``file_path``, not truthiness — a truthy test swept up direct uploads
    (absolute local paths) and left them pending for a day with no retry.
    False is the 1h abandonment policy; True is the 24h backstop for a bound
    upload that never committed, which the retention purge would otherwise
    never reach.
    """
    # coalesce, not a bare LIKE: NOT (NULL LIKE ...) is NULL, so a bare negation
    # would drop every NULL file_path row — the case that most needs the 1h policy.
    completion_key = func.coalesce(IngestJob.file_path, "").like("staging/%")
    cutoff_seconds = stale_pending_cutoff_seconds(completion_bound=completion_bound)
    # fix(#1708): age from `staged_at`, falling back to created_at. Every
    # writer of that key restarts the pending window where the row re-entered it.
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


# fix(#1556): an upload nobody ever committed settles `cancelled`, not `failed`.
# `cancelled` is already in the status CHECK, the admin literal and openapi.json.
ABANDONED_UPLOAD_MESSAGE = "Abandoned: upload was never completed"


def is_abandoned_upload(user_metadata: dict | None) -> bool:
    """Python twin of ``abandoned_upload``, over one loaded row.

    Used only by worker startup recovery, which mirrors the UPDATE onto its
    ORM instances — a plain ``job.status = "failed"`` there would overwrite
    the status the database just computed.
    """
    return not (user_metadata or {}).get(COMMIT_ATTEMPTED_METADATA_KEY)


def abandoned_upload():
    """Predicate: nothing was ever dispatched for this row.

    fix(#1744): ``defer_with_orphan_guard`` stamps and commits
    ``commit_attempted_at`` before every ``defer_async``, so an unbound
    pending row with no stamp was never handed to the queue.

    Known gaps: a death between a door's commit and dispatch settles
    ``cancelled`` (one statement wide); pre-stamp rows reclassify the same
    way; a bound S3 direct upload still settles ``failed`` after the 24h
    backstop.
    """
    return (
        func.coalesce(IngestJob.user_metadata[COMMIT_ATTEMPTED_METADATA_KEY].astext, "")
        == ""
    )


def stale_pending_unbound_values(now: datetime, *, message: str) -> dict:
    """Every column the unbound half of the pending sweep writes.

    Companion to ``stale_pending_clauses``: bundles the cancelled/failed
    split with the caller's own ``message``, so a caller cannot take one
    without the other.
    """
    abandoned = abandoned_upload()
    return {
        "status": case((abandoned, "cancelled"), else_="failed"),
        "error_message": case((abandoned, ABANDONED_UPLOAD_MESSAGE), else_=message),
        "completed_at": now,
    }


def no_live_procrastinate_job():
    """Predicate: this ``ingest_jobs`` row has no queued or running task.

    fix(#724): age alone conflated a starved-but-queued job (analysis can
    wait at priority -10 indefinitely) with a true orphan. Correlates on
    args->>'job_id'; both pending auto-fail paths must use this.
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
    # fix(#1556): cancelled uploads are counted apart from `pending_failed`
    # (a failure count). Defaulted only because dataclasses require it last.
    pending_cancelled: int = 0
    _staged_paths: tuple[str, ...] = field(default=(), repr=False, compare=False)
    # fix(#1202): presigned staging keys of the purged rows, kept
    # apart from _staged_paths — namespaced by the job, so no survivor query.
    _staged_presigned_keys: tuple[str, ...] = field(
        default=(), repr=False, compare=False
    )
    # fix(#1277): refresh runs the sweep finalized, published only after the
    # commit lands. Private and absent from as_dict(), like the fields above.
    _refresh_runs_reconciled: int = field(default=0, repr=False, compare=False)
    # fix(#1322): a dead VRT attempt's generation-scoped keys, resolved by
    # sweep_stale_vrt_assets but deleted only after the commit, like _staged_paths.
    _stale_generation_storage_keys: tuple[str, ...] = field(
        default=(), repr=False, compare=False
    )
    # fix(#1778): logical (not tenant-resolved) object keys a raster ingest named
    # on its job row before writing them; reaped after the commit, same rule.
    _unpublished_storage_keys: tuple[str, ...] = field(
        default=(), repr=False, compare=False
    )
    # fix(#1778): analysis output tables named on the job rows this pass
    # settled, dropped after the settling commit under the same rule.
    _unadopted_analysis_tables: tuple[tuple[uuid.UUID, str], ...] = field(
        default=(), repr=False, compare=False
    )

    @property
    def total_cleaned(self) -> int:
        """Legacy count: ingest jobs transitioned from active to failed.

        fix(#1556): cancellations are absent; the published identity stays
        `pending_failed + running_failed`.
        """
        return self.pending_failed + self.running_failed

    @property
    def total_affected(self) -> int:
        """Rows and staged objects mutated by the cleanup pass.

        fix(#1556): cancellations DO belong here; this counts work done.
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

        fix(#1556): `pending_cancelled` reaches the audit event and fleet
        totals but not the HTTP response — pydantic drops the extra key.
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

    fix(#1202): computed from the setting, not fixed at 3600 —
    a URL expires at `created_at + pending_job_timeout_seconds`. Part URLs
    can't recreate an object (CompleteMultipartUpload consumes the upload
    id); only the single-part object-key URL is a recreation vector.
    """
    return settings.pending_job_timeout_seconds + _POST_EXPIRY_SWEEP_MARGIN_SECONDS


# Set on the post-expiry sweep's first pass; not permanent on its own (#1236).
_STAGING_REAPED_MARKER = "s3_key_reaped"

# fix(#1236): set once the RE-CHECK pass has run past
# MAX_PRESIGNED_URL_LIFETIME_SECONDS + the transfer margin; only rows
# carrying it are excluded from every future pass.
_STAGING_REAPED_FINAL_MARKER = STAGING_REAPED_FINAL_MARKER

# fix(#1236): SigV4 bounds when a URL may be SIGNED, not when an accepted
# PUT finishes transferring, so the re-check waits out S3's single-PUT
# ceiling at a slow rate; `expected_size` is never enforced.
_MIN_ASSUMED_UPLOAD_KBPS = 32  # ~256kbit/s: slow, but a still-progressing PUT
_S3_SINGLE_PUT_MAX_BYTES = 5 * 1024 * 1024 * 1024  # AWS hard limit, 5GiB
_RECHECK_TRANSFER_MARGIN_SECONDS = max(
    3600, (_S3_SINGLE_PUT_MAX_BYTES // 1024) // _MIN_ASSUMED_UPLOAD_KBPS
)


async def _sweep_expired_presigned_staging(
    db: AsyncSession, outcome: StaleCleanupOutcome, *, now: datetime | None = None
) -> StaleCleanupOutcome:
    """Sweep staging objects a now-dead PUT URL may have recreated.

    The two event-triggered sweeps close a URL's past; this closes its
    future. Runs at most twice per job: an ordinary pass reaps and sets
    ``_STAGING_REAPED_MARKER``; the re-check pass runs once the row is older
    than ``MAX_PRESIGNED_URL_LIFETIME_SECONDS`` and sets the FINAL marker
    only after ``_RECHECK_TRANSFER_MARGIN_SECONDS`` has also elapsed, since
    SigV4 expiry stops new requests but not an accepted transfer.

    Delete first, mark second — marking a failed delete as done would leak
    the object permanently.
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
            # Not this job's key: a fan-out child inheriting the parent's
            # s3_key lands here too, same rule as everywhere.
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
        # Fresh dict, not an in-place mutation — JSONB doesn't track
        # mutation, so an in-place edit would never flush.
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
                # Hosted jobs store logical keys; resolve the tenant's
                # provider namespace before deleting.
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
                # may be deleted — manifest sources can reference arbitrary
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

    # fix(#1202): a completed job's `file_path` is a frozen copy, so the
    # loop above never reaches this key; namespaced by its own job, so no
    # survivor query.
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

    # fix(#1322): a dead VRT attempt's generation-scoped objects, withheld until
    # the caller's commit landed. Already tenant-resolved at capture time.
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

    # fix(#1778): a killed raster ingest/replace's own pre-commit objects,
    # named on the job row before the puts; withheld for the same reason as
    # the VRT keys above.
    reaped, skipped, failures = await reap_unpublished_storage_keys(
        outcome._unpublished_storage_keys
    )
    storage_objects_reaped += reaped
    staged_paths_skipped += skipped
    staged_cleanup_failures += failures

    # fix(#1778): the analysis peer of the loop above. Same rule, same reason:
    # the table is dropped only once the row that stopped owning it is durable.
    await _reap_unadopted_analysis_outputs(outcome._unadopted_analysis_tables)

    return replace(
        outcome,
        local_files_reaped=local_files_reaped,
        storage_objects_reaped=storage_objects_reaped,
        staged_paths_skipped=staged_paths_skipped,
        staged_cleanup_failures=staged_cleanup_failures,
    )


def unpublished_storage_keys_from_metadata(
    user_metadata: object,
) -> tuple[str, ...]:
    """Read the object keys a killed raster tail named on its own job row.

    fix(#1778): tails write their keys to ``user_metadata`` before the puts,
    so a SIGKILL between the puts and the terminal ``finally`` still leaves
    an owner. The prefix check is the only guard against a hand-edited row
    licensing an arbitrary delete.
    """
    from app.processing.ingest.tasks_raster_common import (
        UNPUBLISHED_STORAGE_KEYS_FIELD,
    )

    if not isinstance(user_metadata, dict):
        return ()
    raw = user_metadata.get(UNPUBLISHED_STORAGE_KEYS_FIELD)
    if not isinstance(raw, list):
        return ()
    return tuple(
        key
        for key in raw
        if isinstance(key, str)
        and key.startswith(("rasters/", "originals/"))
        and ".." not in key
    )


def unadopted_analysis_tables_from_metadata(user_metadata: object) -> tuple[str, ...]:
    """Read EVERY output table an analysis job named on its own job row.

    fix(#1778): all of them — the record accumulates across attempts.
    Delegates to the writer's own normaliser so the two cannot disagree;
    the drop re-validates the identifier before DDL.
    """
    from app.processing.analysis.tasks import recorded_analysis_output_tables

    return recorded_analysis_output_tables(user_metadata)


async def _live_referenced_storage_keys(keys: tuple[str, ...]) -> set[str]:
    """Which of ``keys`` a live catalog row still points at.

    Catalog rows hold LOGICAL keys, same form as the job row, so this is a
    plain match across the four schema columns naming an object under
    `rasters/` or `originals/`.
    """
    from sqlalchemy import Text, any_, bindparam, union_all
    from sqlalchemy.dialects.postgresql import ARRAY

    from app.core.db import async_session
    from app.platform.extensions import get_catalog_port
    from app.processing.raster.models import RasterAsset

    DatasetAsset = get_catalog_port().dataset_asset_orm_class()
    # fix(#1778): ONE array param for all four arms — four IN clauses
    # crossed asyncpg's 32767-arg ceiling at ~8192 keys, and a failed query
    # skipped every delete, leaking the objects for good.
    keys_param = bindparam("reap_keys", value=list(keys), type_=ARRAY(Text))
    async with async_session() as session:
        stmt = union_all(
            select(RasterAsset.asset_uri.label("key")).where(
                RasterAsset.asset_uri == any_(keys_param)
            ),
            select(RasterAsset.quicklook_256_uri.label("key")).where(
                RasterAsset.quicklook_256_uri == any_(keys_param)
            ),
            select(RasterAsset.quicklook_512_uri.label("key")).where(
                RasterAsset.quicklook_512_uri == any_(keys_param)
            ),
            select(DatasetAsset.href.label("key")).where(
                DatasetAsset.href == any_(keys_param)
            ),
        )
        return {row[0] for row in (await session.execute(stmt)).all() if row[0]}


# fix(#1778): outcomes that license forgetting a storage key. "refused" is
# final (a key a live row names is answered); only "failed" keeps the record.
STORAGE_KEY_FINAL_OUTCOMES = frozenset({"deleted", "refused"})


# fix(#1778): rows one pass collects; what it leaves, the next pass takes.
_ARTIFACT_REAP_BATCH = 500


# fix(#1778): settled keys come off one by one, in SQL so two rows
# can't race; the STRING arm clears a legacy pre-list value. `?` isn't a bind
# marker (hence jsonb_exists_any), and `jsonb - $1` is ambiguous untyped.
_CLEAR_SETTLED_LIST_SQL = """
UPDATE catalog.ingest_jobs SET user_metadata =
  CASE
    WHEN jsonb_typeof(user_metadata -> (:field)::text) = 'array' THEN
      CASE WHEN (
             SELECT coalesce(jsonb_agg(k), '[]'::jsonb)
             FROM jsonb_array_elements_text(user_metadata -> (:field)::text) AS k
             WHERE NOT (k = ANY((:settled)::text[]))
           ) = '[]'::jsonb
           THEN user_metadata - (:field)::text
           ELSE jsonb_set(
                  user_metadata,
                  ARRAY[(:field)::text],
                  (
                    SELECT coalesce(jsonb_agg(k), '[]'::jsonb)
                    FROM jsonb_array_elements_text(user_metadata -> (:field)::text) AS k
                    WHERE NOT (k = ANY((:settled)::text[]))
                  )
                )
      END
    ELSE user_metadata - (:field)::text
  END
WHERE (
        jsonb_typeof(user_metadata -> (:field)::text) = 'array'
        AND jsonb_exists_any(user_metadata -> (:field)::text, (:settled)::text[])
      )
   OR (
        jsonb_typeof(user_metadata -> (:field)::text) = 'string'
        AND (user_metadata ->> (:field)::text) = ANY((:settled)::text[])
      )
"""


async def _clear_settled_artifact_records(
    *,
    storage_keys: set[str] = frozenset(),  # type: ignore[assignment]
    analysis_tables: set[str] = frozenset(),  # type: ignore[assignment]
) -> None:
    """Drop the job-row record of artifacts that are now accounted for.

    fix(#1778): the row is the durable pending-reap record (the retention
    purge refuses a row still naming an unreaped artifact), so this is what
    lets a purge terminate. "Accounted for" is deleted OR refused; only an
    error keeps the record. Best effort — failing costs one more sweep.
    """
    from sqlalchemy import Text, bindparam
    from sqlalchemy.dialects.postgresql import ARRAY

    from app.core.db import async_session
    from app.processing.analysis.tasks import ANALYSIS_OUTPUT_TABLE_FIELD
    from app.processing.ingest.tasks_raster_common import (
        UNPUBLISHED_STORAGE_KEYS_FIELD,
    )

    if not storage_keys and not analysis_tables:
        return
    try:
        async with async_session() as session:
            if storage_keys:
                # fix(#1778): remove the settled KEYS, not the whole field;
                # the record accumulates across attempts.
                await session.execute(
                    text(_CLEAR_SETTLED_LIST_SQL).bindparams(
                        bindparam("field", value=UNPUBLISHED_STORAGE_KEYS_FIELD),
                        bindparam(
                            "settled", value=sorted(storage_keys), type_=ARRAY(Text)
                        ),
                    )
                )
            if analysis_tables:
                # fix(#1778): by VALUE, through the same statement; a name
                # carries the attempt that made it, so it is a safe key.
                await session.execute(
                    text(_CLEAR_SETTLED_LIST_SQL).bindparams(
                        bindparam("field", value=ANALYSIS_OUTPUT_TABLE_FIELD),
                        bindparam(
                            "settled", value=sorted(analysis_tables), type_=ARRAY(Text)
                        ),
                    )
                )
            await session.commit()
    except Exception:  # broad: costs one more sweep, never correctness
        log.warning(
            "Failed to clear settled artifact records",
            key_count=len(storage_keys),
            table_count=len(analysis_tables),
        )


async def reap_unpublished_storage_keys(
    keys: tuple[str, ...],
) -> tuple[int, int, int]:
    """Delete a dead attempt's pre-commit objects, but never a live one.

    Returns ``(reaped, skipped, failures)``.

    fix(#1778): the survivor check lives HERE, the only function that
    deletes these keys. A failed survivor query deletes NOTHING — leaving
    objects behind is recoverable, deleting a live raster is not.
    """
    # fix(#1778): deduplicated once so the counts mean distinct objects.
    keys = tuple(dict.fromkeys(keys))
    if not keys:
        return (0, 0, 0)

    try:
        live = await _live_referenced_storage_keys(keys)
    except Exception:  # broad: an unreadable catalog must not license a delete
        log.warning(
            "Skipped unpublished raster reap, survivor query failed",
            key_count=len(keys),
        )
        return (0, len(keys), 0)

    reaped = 0
    skipped = 0
    failures = 0
    # fix(#1778): keys this pass reached a FINAL answer about, keyed
    # off the outcome name; a delete that raised stays on the row for retry.
    settled: set[str] = set()
    for key in keys:
        if key in live:
            skipped += 1
            outcome = "refused"
            log.warning(
                "Refused to reap a raster object a live row still names",
                storage_key=key,
            )
        else:
            try:
                from app.platform.storage import get_storage

                await get_storage().delete(resolve_current_storage_key(key))
            except Exception:  # broad: best-effort staging cleanup
                failures += 1
                outcome = "failed"
                log.warning(
                    "Failed to reap unpublished raster object for stale job",
                    storage_key=key,
                )
            else:
                reaped += 1
                outcome = "deleted"
        if outcome in STORAGE_KEY_FINAL_OUTCOMES:
            settled.add(key)
    await _clear_settled_artifact_records(storage_keys=settled)
    return (reaped, skipped, failures)


async def _reap_unadopted_analysis_outputs(
    out_tables: tuple[tuple[uuid.UUID, str], ...],
) -> None:
    """Drop the analysis outputs of jobs this pass just settled.

    fix(#1778): its own session, opened after the settling commit, so a DROP
    can't block on a dead worker's lock or destroy an output a rolled-back
    reconciliation still owns. Tenant context is the caller's.
    """
    if not out_tables:
        return
    from app.core.db import async_session
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant
    from app.processing.analysis.tasks import (
        ANALYSIS_OUTPUT_FINAL_OUTCOMES,
        drop_unadopted_analysis_output,
    )

    schema = tenant_data_schema(current_tenant_var.get() if is_multi_tenant() else None)
    # fix(#1778): settle by what the call REPORTS, never by "it
    # didn't raise" — the callee catches its own DROP failures. A name is a
    # safe key; the drop re-derives ownership.
    settled: set[str] = set()
    async with async_session() as session:
        for job_uuid, out_table in set(out_tables):
            try:
                outcome = await drop_unadopted_analysis_output(
                    session,
                    out_table=out_table,
                    schema=schema,
                    job_id=str(job_uuid),
                    owner_job_uuid=job_uuid,
                )
            except Exception:  # broad: best-effort cleanup of one orphan
                log.warning("Failed to reap unadopted analysis output")
                continue
            if outcome in ANALYSIS_OUTPUT_FINAL_OUTCOMES:
                settled.add(out_table)
            else:
                log.warning(
                    "Analysis output reap did not settle, retrying next sweep",
                    outcome=outcome,
                )
    await _clear_settled_artifact_records(analysis_tables=settled)


def _stale_generation_storage_keys(
    stale_generations: list[tuple[uuid.UUID, uuid.UUID]],
) -> tuple[str, ...]:
    """Resolve (never delete) a dead attempt's immutable object keys.

    feat(#1267): ``regenerate_vrt`` writes an immutable per-generation key
    BEFORE its phase-2 transaction, so a worker killed in between leaves
    objects only this sweep can name; the caller reaps them after its own
    commit. A missing tenant context resolves no keys rather than raising.
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

    fix(#1322): must run strictly after the caller's commit — a "dead"
    worker is declared by heartbeat, not proof, and a rolled-back
    reconciliation could still publish a generation whose objects this
    already deleted. Deleting a never-written key is a documented no-op.
    """
    if not keys:
        return

    # Function-local: platform may not import processing eagerly
    # (test_platform_processing_imports_stay_deferred).
    from app.processing.ingest.tasks_raster import _cleanup_orphaned_storage_keys

    await _cleanup_orphaned_storage_keys(list(keys), job_id="vrt-stale-sweep")


# fix(#1322): does the PUBLISHED member set (built_from) still
# match the CATALOG's (vrt_source_links)? Count-match + subset proves it.
# `jsonb_typeof = 'object'`, not IS NOT NULL — a JSON `null` scalar raises.
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

# fix(#1322): a retry of an already-'failed' asset that dies again
# must stay 'failed'; `heartbeat_at IS NOT NULL` skips enqueue-rollback rows
# no worker ever ran.
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

# fix(#1322): proof a 'pending' VrtGeneration is dead, keyed on
# `generation_id`; the legacy arm correlates a pre-upgrade row (no
# generation_id) by dataset plus current ownership. Ambiguity blocks the sweep.
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

    GAP-002 / feat(#1267): a worker crash mid-regeneration otherwise leaves
    the asset 'regenerating' forever and every link/regenerate call 409s.
    Staleness is ``VrtGeneration.heartbeat_at`` (falling back to
    ``started_at``), renewed by a live worker every 30s.

    Recovery is ``'ready'`` only when ``_READY_WORTHY_SQL`` holds (published
    member set still matches the catalog AND the asset was provably ready
    when the attempt started, fix(#1322)); ``'failed'`` otherwise, with
    ``current_generation_id`` cleared either way. The dead generation row is
    marked ``'failed'``.

    Resolves the dead attempt's generation-scoped storage keys but deletes
    nothing; the caller must not either until its own commit lands.

    Args:
        db: Active async session; must NOT be committed before returning.
        stale_cutoff: Generations started before this are stale.

    Returns:
        ``(assets_recovered, gens_failed, storage_keys)``; assets_recovered
        counts both branches, and storage_keys are resolved, not deleted.
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

    # fix(#1322): 'running' trusts its own stale heartbeat (procrastinate
    # may still read 'doing'); 'pending' also needs proof of no live queue row.
    # RETURNING vrt_dataset_id: the asset UPDATE below needs it to null the FK.
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
    # Tuple-unpack Row objects directly, not attribute access, so a
    # lightweight test double can stand in with plain tuples.
    stale_generations = [
        (generation_id, vrt_dataset_id)
        for generation_id, vrt_dataset_id in stale_gen_result.all()
    ]
    stale_generation_ids = [generation_id for generation_id, _ in stale_generations]

    # Restore only if the asset still points at the just-failed generation; a
    # newer regeneration is fenced. NULL built_from falls to the conservative
    # branch.
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

    fix(#1277): a counter incremented inside the transaction survives a
    rollback, and the overcount is permanent. Both commit sites call this.
    """
    if outcome._refresh_runs_reconciled:
        refresh_sweep_reconciled_total.inc(outcome._refresh_runs_reconciled)


_PURGE_JOB_TOKENS_BY_ID_SQL = (
    "UPDATE catalog.procrastinate_jobs SET args = args - 'token' "
    "WHERE id = ANY(:job_ids)"
)


async def purge_queue_row_tokens(db: AsyncSession, job_ids: Sequence[int]) -> None:
    """Drop the raw service token from the named queue rows.

    fix(#1755 item 12): the one statement both immediate purge sites use —
    a task that fails on its own (``purge_token_on_failure``) and the
    stalled sweep, which is the first moment a crashed worker's token is
    provably dead weight. Both service tasks are ``retry=0``, so nothing
    re-runs from these args.
    """
    if not job_ids:
        return
    await db.execute(text(_PURGE_JOB_TOKENS_BY_ID_SQL), {"job_ids": list(job_ids)})
    await db.commit()


async def purge_terminal_job_tokens(db: AsyncSession) -> None:
    """Backstop the token purge the service tasks run on their own failure.

    Drops the raw service token from terminal queue rows that never reached
    ``purge_token_on_failure``. fix(#1746): not part of ``fail_stale_jobs``
    (runs once per TENANT) — the queue table is shared, so
    ``sweep_stale_jobs_once`` calls this once per pass. Deliberately
    unindexed: a sequential scan beats a write-amplifying index here.
    """
    await db.execute(
        text(
            "UPDATE catalog.procrastinate_jobs SET args = args - 'token' "
            "WHERE status NOT IN ('todo', 'doing') AND args ? 'token'"
        )
    )
    await db.commit()


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
      - pending: older than ``stale_pending_cutoff_seconds`` AND no live
        Procrastinate job (a true orphan, never queued)
      - running: heartbeat_at/started_at older than JOB_TIMEOUT_SECONDS
        (worker lease expired)

    Also sweeps VRT RasterAsset rows stuck 'regenerating' past
    JOB_TIMEOUT_SECONDS (GAP-002) via ``sweep_stale_vrt_assets``, using the
    same stale_cutoff.
    """
    now = datetime.now(timezone.utc)

    # fix(#1234): the 1h policy applies only to rows that never bound bytes.
    # The guard is FALSY, not IS NULL — every creator writes "" for file_path.
    unbound_result = await db.execute(
        update(IngestJob)
        .where(*stale_pending_clauses(now, completion_bound=False))
        .values(
            **stale_pending_unbound_values(now, message=STALE_PENDING_UNBOUND_MESSAGE)
        )
        # fix(#1556): RETURNING carries the status the CASE actually chose.
        .returning(
            IngestJob.id,
            IngestJob.user_metadata,
            IngestJob.created_by,
            IngestJob.status,
        )
    )
    unbound_rows = list(unbound_result.all())
    # Positional access, like every row read here: a mocked session hands
    # back plain tuples, and attribute access would pass against the DB but
    # raise in the unit suites that drive this with doubles.
    pending_cancelled = sum(1 for row in unbound_rows if row[3] == "cancelled")
    # fix(#1744): cancelled rows still get their audit trail closed; a backfill
    # in the cancelled class is exactly the `never_started` the loop records.
    pending_rows = [(row[0], row[1], row[2]) for row in unbound_rows]
    pending_job_ids = [row[0] for row in unbound_rows]

    # fix(#1234): the bound half — exempt from the 1h clause, and the purge
    # only takes terminal rows, so it is immortal without this backstop.
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

    # fix(#1778): "still names an unreaped artifact" — the purge
    # refuses these rows too. A string test on the JSONB blob, never a
    # throwing cast.
    from app.processing.analysis.tasks import ANALYSIS_OUTPUT_TABLE_FIELD
    from app.processing.ingest.tasks_raster_common import (
        UNPUBLISHED_STORAGE_KEYS_FIELD,
    )

    carries_unreaped_artifacts = or_(
        IngestJob.user_metadata[UNPUBLISHED_STORAGE_KEYS_FIELD].is_not(None),
        IngestJob.user_metadata[ANALYSIS_OUTPUT_TABLE_FIELD].is_not(None),
    )

    running_cutoff = now - timedelta(seconds=JOB_TIMEOUT_SECONDS)
    # fix(#1778): candidates come through their own `FOR UPDATE
    # SKIP LOCKED` subquery — a phase-2 write holds `FOR NO KEY UPDATE`, and
    # a lock_timeout on a set-based UPDATE would cancel the WHOLE statement.
    running_candidates = (
        select(IngestJob.id)
        .where(
            IngestJob.status == "running",
            func.coalesce(IngestJob.heartbeat_at, IngestJob.started_at)
            < running_cutoff,
        )
        .with_for_update(skip_locked=True)
    )
    running_result = await db.execute(
        update(IngestJob)
        .where(IngestJob.id.in_(running_candidates))
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

    # fix(#1550): the row and its audit trail are settled by the same actor in
    # the same transaction; after a hard kill this sweep is the only actor left.
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

    # fix(#1709): a childless `fanned_out` parent past the grace, inside the
    # retention horizon, is the signature of a dispatch interrupted pre-commit.
    # fix(#2016): a dispatch still looping reclaims this row on its way out.
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
            # fix(#1709): the marker _retry_capability refuses on; a generic
            # retry would import ONE default layer of a multi-layer file.
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

    # GAP-002: stale VRT assets, same cutoff. fix(#1322): the generation keys
    # are resolved here and reaped only after the commit, like _staged_paths.
    (
        vrt_assets_recovered,
        vrt_generations_failed,
        stale_generation_storage_keys,
    ) = await sweep_stale_vrt_assets(db, running_cutoff)

    # feat(#1219): AFTER the two job sweeps, which supply one of the facts the
    # run sweep requires. Not folded into StaleCleanupOutcome (published shape).
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

    # fix(#434): purge terminal jobs past retention, cut on finished-at so
    # the sweep's own completed_at=now survives. 0 = keep forever; each
    # dataset's latest complete job is exempt (/jobs/by-dataset/{id} reads it).
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
        # #434 r7: manifest apply looks up the newest complete job per
        # manifest_key, so that row is exempt too or the next apply duplicates.
        manifest_key = IngestJob.user_metadata["manifest_key"].astext
        latest_manifest_ids = (
            select(IngestJob.id)
            .where(
                IngestJob.status == "complete",
                manifest_key.is_not(None),
                # #434 r9: the mirrored lookup joins Dataset, so a job whose
                # dataset was deleted cannot influence reapply.
                IngestJob.dataset_id.is_not(None),
            )
            .distinct(manifest_key)
            .order_by(
                manifest_key,
                IngestJob.completed_at.desc(),
                IngestJob.created_at.desc(),
            )
        )
        # fix(#1236): a presigned job's ROW carries the post-expiry
        # sweep's markers. Owned = key prefix matches the ROW'S OWN id
        # (fan-out children clone s3_key).
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
        purge_clauses = [
            IngestJob.status.not_in(("pending", "running")),
            func.coalesce(IngestJob.completed_at, IngestJob.created_at)
            < retention_cutoff,
            IngestJob.id.not_in(latest_complete_ids),
            IngestJob.id.not_in(latest_manifest_ids),
            not_(presigned_url_may_still_be_live),
        ]
        # fix(#1778): a row still naming an unreaped artifact is not
        # purged; it IS the pending-reap record. One DELETE .. RETURNING
        # (#434) so retry can't flip a candidate mid-way.
        deleted = await db.execute(
            delete(IngestJob)
            .where(*purge_clauses, not_(carries_unreaped_artifacts))
            .returning(IngestJob.id, IngestJob.file_path, IngestJob.user_metadata)
        )
        deleted_rows = deleted.all()
        terminal_jobs_purged = len(deleted_rows)
        deleted_paths = {fp for (_id, fp, _um) in deleted_rows if fp}
        # fix(#1202): a purged presigned job's staging key is the one
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

        # #434 r3-r5: this purge is the retention policy for staged files.
        # Reap only paths no surviving row NEEDS (pending/running reads it,
        # failed keeps it for retry); complete rows keep the row, not the file.
        if deleted_paths:
            survivors = await db.execute(
                select(IngestJob.file_path).where(
                    IngestJob.file_path.in_(deleted_paths),
                    IngestJob.status.in_(STATUSES_NEEDING_STAGED_INPUT),
                )
            )
            deleted_paths -= set(survivors.scalars())
        staged_paths_considered = len(deleted_paths)

    # fix(#1778): ONE collection — terminal, still carrying a record,
    # regardless of age or exemption; bounded so a pass can't hold its
    # session open.
    artifact_rows = await db.execute(
        select(IngestJob.id, IngestJob.user_metadata)
        .where(
            IngestJob.status.not_in(("pending", "running")),
            carries_unreaped_artifacts,
        )
        .limit(_ARTIFACT_REAP_BATCH)
    )
    unpublished_storage_keys: list[str] = []
    # The row id rides along so the drop can refuse a name that isn't this
    # job's, without a second read to re-derive ownership.
    unadopted_analysis_tables: list[tuple[uuid.UUID, str]] = []
    for artifact_id, artifact_metadata in artifact_rows.all():
        unpublished_storage_keys.extend(
            unpublished_storage_keys_from_metadata(artifact_metadata)
        )
        unadopted_analysis_tables.extend(
            (artifact_id, name)
            for name in unadopted_analysis_tables_from_metadata(artifact_metadata)
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
        _unpublished_storage_keys=tuple(sorted(set(unpublished_storage_keys))),
        _unadopted_analysis_tables=tuple(sorted(set(unadopted_analysis_tables))),
    )
    if commit:
        # Never remove an external artifact before a DELETE that may still
        # roll back — a crash after commit can leak an object but can't
        # un-delete a row.
        await db.commit()
        publish_refresh_reconciliation(outcome)
        outcome = await _reap_committed_staged_paths(outcome)
        outcome = await _sweep_expired_presigned_staging(db, outcome, now=now)
        # fix(#1249): starts from the OBJECTS and asks whether any row owns
        # them — the only direction that finds one nothing references.
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

    fix(#1550): the job row and audit trail are written together by
    whichever actor settles the job — after a hard kill, that's the sweeper.
    Emitted on the caller's session so both commit or roll back as one. A
    no-op for any other kind of job.
    """
    marker = (user_metadata or {}).get(EMBEDDING_BACKFILL_METADATA_KEY)
    if not marker:
        return
    # The DATABASE decides which actor's terminal entry wins
    # (`uq_audit_logs_terminal_embedding_backfill`); SAVEPOINT so losing the
    # race rolls back only this insert. fix(#1709): actor = settler.
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
    """Write the one terminal entry; ``actor`` is whoever settled the run."""
    # Deferred by design to preserve the platform -> modules layer boundary,
    # same as the deferred imports elsewhere in this module.
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
