"""Procrastinate task: re-measure a registered PostGIS table.

feat(#1265) / ADR-002 Decision 5a, Amendment A10. Registering an existing
table copies no data — the catalog points at the live relation and serves
straight from it — so everything GeoLens stores about that table is a
measurement taken once, at registration, of a table its owner keeps writing
to. Rows arrive, columns are added, the extent moves, and the catalog goes on
reporting the day it was registered. This task takes the measurement again.

**What it is not.** There is no fetch, no staging table, and no swap. Decision
5a is explicit that a postgis refresh moves no data, which is also why this
task is short: the source IS the destination, so the entire operation is a
read of the live relation followed by a write of the catalog row. The
``strategy declares no staging`` clause of the issue is discharged
structurally rather than by a flag — there is no staging table anywhere in
this module for an executor to be told to skip.

**Why it is a worker task at all** when nothing here is slow in the way a GDAL
fetch is slow: because the admission gate, the run ledger, and the history the
user reads are the shared machinery (handoff invariant 11), and that machinery
is dispatch-then-finalize. Running the recount inline in the request would
also hold an HTTP connection open across a ``COUNT(*)`` on a table whose size
nobody promised anything about.

**Health.** This is the only observer a registered table ever gets: the
source-health probe (#1222) refuses postgis origins outright, because probing
one would mean issuing an HTTP request to a relation. So unlike every other
strategy — which leaves ``source_health`` to the probe's classifier rather
than adding a second, weaker one — this one owns the verdict for its origin
kind, and the mapping is a SQLSTATE lookup rather than a guess.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, NamedTuple

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.db.sqlstate import sqlstate
from app.core.db.tenant_session import tenant_task
from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.jobs.heartbeat import (
    claim_job_attempt_and_start_heartbeat,
    require_ingest_job_update,
    resolve_ingest_attempt_or_skip,
    stop_ingest_job_heartbeat,
    update_ingest_job_for_attempt,
)
from app.platform.refresh.service import (
    claim_run_for_job,
    record_refresh_failure,
    record_refresh_success,
)
from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    _current_tenant_schema,
    invalidate_tile_cache_for_table,
    task_app,
)

logger = structlog.get_logger(__name__)

# ADR-002's stored source_health values, mirrored the way
# ``sources/origin_probe.py`` mirrors them: processing/ may not import
# app.modules.catalog (test_no_processing_imports_catalog), so the words are
# retyped here rather than imported. ``test_postgis_refresh_1265`` asserts
# these constants against the probe's own vocabulary, so a divergence fails a
# test instead of persisting a value the API cannot describe.
_HEALTHY = "healthy"
_MISSING = "missing"
_INACCESSIBLE = "inaccessible"

# Members of the probe's closed DETAIL_CODES set, chosen for what they mean
# rather than for their HTTP flavour: a dropped relation is the resource being
# gone, a revoked GRANT is access being lost while the resource is intact, and
# a dead connection is the transport failing. Same three distinctions the
# probe draws over HTTP.
_NOT_FOUND = "not_found"
_UNAUTHORIZED = "unauthorized"
_NETWORK_ERROR = "network_error"

_ERROR_CODE_MISSING = "source_missing"
_ERROR_CODE_INACCESSIBLE = "source_inaccessible"
_ERROR_CODE_GENERIC = "postgis_refresh_failed"


class _Verdict(NamedTuple):
    """What one class of database failure says about the origin."""

    error_code: str
    health: str | None
    detail: str | None
    # Written for the person reading the refresh history, and composed here
    # rather than from the driver: ADR-002 Decision 3 forbids a raw exception
    # in a stored reason string, and driver text carries the statement, its
    # parameters, and in some shapes a connection string. The exception itself
    # still reaches the logs.
    message: str


_MISSING_VERDICT = _Verdict(
    _ERROR_CODE_MISSING,
    _MISSING,
    _NOT_FOUND,
    "The registered table this dataset points at no longer exists. The "
    "catalog entry keeps the metadata from its last successful measurement; "
    "restore or re-create the table, then refresh again.",
)

# SQLSTATE -> verdict. Only failures that say something true about the ORIGIN
# are listed. A statement timeout or a deadlock says something about the
# query, not about the table, and falls through to the inconclusive verdict
# below, which writes no health at all — reporting a healthy table as missing
# because one COUNT(*) was slow would be worse than reporting nothing.
_VERDICT_BY_SQLSTATE: dict[str, _Verdict] = {
    # undefined_table
    "42P01": _MISSING_VERDICT,
    # insufficient_privilege. Deliberately NOT "missing": the table may be
    # entirely intact behind a GRANT somebody revoked, which is the same
    # distinction the probe draws between 404 and 403.
    "42501": _Verdict(
        _ERROR_CODE_INACCESSIBLE,
        _INACCESSIBLE,
        _UNAUTHORIZED,
        "GeoLens is no longer allowed to read the registered table this "
        "dataset points at. Restore the GeoLens role's SELECT privilege on "
        "it, then refresh again.",
    ),
}

# connection_exception and its friends, matched on the two-character class
# because the whole class means one thing here. Barely reachable while gate 2
# holds (the origin is a relation in the database GeoLens is already talking
# to), and mapped anyway so it cannot fall through to a verdict that blames
# the table.
_CONNECTION_CLASS = "08"
_CONNECTION_VERDICT = _Verdict(
    _ERROR_CODE_INACCESSIBLE,
    _INACCESSIBLE,
    _NETWORK_ERROR,
    "GeoLens lost its database connection while re-measuring this dataset's "
    "registered table, so nothing was measured. Try again.",
)


class PostgisRefreshError(Exception):
    """A refresh failure that already knows what it means.

    Carries the run's ``error_code`` and, when the failure described the
    origin rather than the attempt, the source-health verdict to persist. The
    task's failure handler reads both off the exception instead of
    re-classifying, so the classification happens exactly once and at the
    point that has the evidence.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        health: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.health = health
        self.detail = detail


def _inconclusive_verdict(code: str | None) -> _Verdict:
    """The verdict for a failure that established nothing about the origin.

    ``health`` is None, so the stored verdict keeps whatever the last
    conclusive attempt wrote. The SQLSTATE goes into the message because it is
    a five-character code from a closed set — the one piece of the driver's
    account that an operator can act on and that cannot carry anything else.
    """
    return _Verdict(
        _ERROR_CODE_GENERIC,
        None,
        None,
        "GeoLens could not finish re-measuring this dataset's registered "
        "table, and the database's answer did not say whether the table is "
        f"still there (SQLSTATE {code or 'unavailable'}). The catalog entry "
        "is unchanged.",
    )


def _classify_db_failure(exc: DBAPIError) -> PostgisRefreshError:
    """Turn a driver error from the live table into a refresh verdict."""
    code = sqlstate(exc)
    verdict = _VERDICT_BY_SQLSTATE.get(code or "")
    if verdict is None and code is not None and code[:2] == _CONNECTION_CLASS:
        verdict = _CONNECTION_VERDICT
    if verdict is None:
        verdict = _inconclusive_verdict(code)
    return PostgisRefreshError(
        verdict.message,
        error_code=verdict.error_code,
        health=verdict.health,
        detail=verdict.detail,
    )


def _resolve_bound_table(dataset: Any, *, schema: str) -> str:
    """The bare table name to re-measure, proven to be this dataset's own.

    The binding names the table (``origin_ref.table_name``, schema-qualified
    by ``set_postgis_origin``), and that is the value this task is specified
    to read. It is not, however, allowed to be the value that STEERS the
    read: ``origin_ref`` is a JSONB column, and a name taken from it and
    dropped into a query is one bad row away from measuring a relation that
    belongs to somebody else and writing the result onto this dataset.

    So the pointer is checked rather than trusted. It must spell exactly the
    pair every other reader of this dataset uses — the active tenant's data
    schema and ``datasets.table_name`` — and the bare name that comes back is
    the one from the dataset row. Registration writes both from a single
    value, so agreement is the normal case and disagreement is a genuine
    fault (a hand-edited row, an interrupted tenant migration) that should
    stop the refresh rather than silently pick a winner.
    """
    ref = dataset.origin_ref or {}
    bound = ref.get("table_name")
    if not bound:
        raise PostgisRefreshError(
            "This dataset's source binding does not record which table it "
            "was registered from, so there is nothing to re-measure.",
            error_code=_ERROR_CODE_GENERIC,
        )
    expected = f"{schema}.{dataset.table_name}"
    if bound != expected:
        raise PostgisRefreshError(
            "This dataset's source binding names a different table than the "
            "one it serves from, so the refresh was stopped rather than "
            "guessing which is current.",
            error_code=_ERROR_CODE_GENERIC,
        )
    return dataset.table_name


async def _relation_exists(session: Any, *, schema: str, table: str) -> bool:
    """Whether the physical relation is there, without reading a row from it.

    ``to_regclass`` answers for a name rather than for a query, so a dropped
    or renamed table is a NULL instead of an exception — which keeps the
    "missing" verdict from depending on which statement happened to hit the
    absence first. ``format('%I.%I', ...)`` composes the identifier inside
    PostgreSQL from bound parameters, so nothing is interpolated here; the
    casts are load-bearing, because ``format`` is variadic ``"any"`` and
    asyncpg cannot infer a parameter type through it.
    """
    return bool(
        await session.scalar(
            text(
                "SELECT to_regclass("
                "format('%I.%I', CAST(:schema AS text), CAST(:table AS text))"
                ") IS NOT NULL"
            ),
            {"schema": schema, "table": table},
        )
    )


async def _stamp_failed_health(
    session: Any,
    dataset_cls: Any,
    dataset_uuid: uuid.UUID,
    *,
    health: str | None,
    detail: str | None,
    bound: tuple | None,
) -> None:
    """Persist what a failed attempt learned about the origin, if anything.

    Two writers, one record each, the same split ``reupload_service`` uses:
    this owns the dataset-side verdict, ``record_refresh_failure`` owns the
    run row, and the caller passes ``contacted_origin=False`` there so the run
    finalizer does not write the dataset a second, weaker way.

    Guarded on the ``(origin_uri, origin_ref, source_format)`` triple this
    attempt read. A refresh that failed against a table the dataset is no
    longer bound to must not mark the NEW binding missing — and for a rebind
    to an upload, nothing would ever correct it, because uploads have no
    probe and no refresh. Losing the race is a silent skip; there is nobody
    to tell from a background task, and the rebind's own commit already
    stated what is true now.
    """
    if health is None or bound is None:
        return
    bound_uri, bound_ref, bound_format = bound
    outcome = await session.execute(
        update(dataset_cls)
        .where(
            dataset_cls.id == dataset_uuid,
            dataset_cls.origin_uri.is_not_distinct_from(bound_uri),
            dataset_cls.origin_ref.is_not_distinct_from(bound_ref),
            dataset_cls.source_format.is_not_distinct_from(bound_format),
        )
        .values(
            source_health=health,
            source_health_detail=detail,
            # The attempt reached the origin and got an answer — a dropped
            # relation IS an answer, the same way the probe dates a 404. That
            # is the whole meaning of the column.
            last_checked_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
    if outcome.rowcount:
        # GET /datasets/ serves these fields from a 60s cache; every other
        # writer invalidates it, and a lost guard race changed nothing worth
        # invalidating for.
        await invalidate_catalog_cache()


def _apply_measurement(dataset: Any, metadata: dict, sample_values: Any) -> None:
    """Write one measurement of the live table onto the catalog row.

    ``spatial_extent`` is CLEARED when the table has no extent, which is where
    this deliberately parts from ``_apply_reupload_swap`` (it only ever writes
    a non-NULL extent). That path installs bytes it fetched, and leaving a
    stale polygon there is at worst a missed update. This path exists solely
    to make the stored metadata agree with the live table, and a table that
    has been emptied still claiming its old footprint in spatial search is the
    precise lie the operation was asked to correct.

    The column is POLYGON-typed, and ``extract_metadata`` already pads a
    degenerate point or line extent and emits the two-ring MULTIPOLYGON for a
    seam-crossing one, so the WKT that arrives here is always a shape the
    column accepts.
    """
    dataset.srid = metadata.get("srid")
    dataset.geometry_type = metadata.get("geometry_type")
    dataset.feature_count = metadata.get("feature_count")
    dataset.column_info = metadata.get("column_info") or []
    dataset.sample_values = sample_values
    extent_wkt = metadata.get("extent_wkt")
    dataset.record.spatial_extent = (
        func.ST_GeomFromText(extent_wkt, 4326) if extent_wkt is not None else None
    )


@task_app.task(queue="ingest", retry=0)
@tenant_task
async def refresh_postgis(
    job_id: str,
    dataset_id: str,
    attempt_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Background task: re-measure the registered table behind this dataset.

    Recounts features, recomputes the extent, and rebuilds the column schema
    snapshot, the sample values, the attribute metadata and the quality score
    from the live relation. Nothing is copied and nothing is swapped.

    No ``user_id`` argument, unlike the re-upload tasks: those stamp a
    ``DatasetVersion`` and an audit event with an uploader, and this task
    creates neither — a measurement is not a new version of the data. The
    actor is already on the run row as ``triggered_by``, which is where the
    audit trail for this operation lives.

    Invariant 10 holds by construction on every failure path: nothing here
    writes ``last_refreshed_at`` except the success block, so a failed refresh
    leaves the dataset serving exactly the data and the freshness it had.
    """
    _bind_task_log_context(
        task_name="refresh_postgis", job_id=job_id, dataset_id=dataset_id
    )
    from app.core.db import async_session
    from app.platform.extensions import get_processing_port
    from app.platform.jobs.models import IngestJob
    from sqlalchemy.orm import joinedload

    port = get_processing_port()
    Dataset = port.get_dataset_orm_class()

    resolved = await resolve_ingest_attempt_or_skip(
        job_id, attempt_id, task_label="refresh"
    )
    if resolved is None:
        return
    job_uuid, attempt_uuid = resolved
    dataset_uuid = uuid.UUID(dataset_id)
    heartbeat_task: asyncio.Task[None] | None = None
    # The binding this attempt measured against, for the failure handler's
    # guarded write. Read in phase 2, beside the measurement it describes,
    # and left None until then — a failure before that point established
    # nothing about any origin and must not write a verdict.
    bound: tuple | None = None

    try:
        # ----------------------------------------------------------------- #
        # Phase 1: claim the attempt and the run, and read the binding.
        # ----------------------------------------------------------------- #
        async with async_session() as session:
            job = (
                await session.execute(
                    select(IngestJob).where(
                        IngestJob.id == job_uuid,
                        IngestJob.attempt_id == attempt_uuid,
                    )
                )
            ).scalar_one_or_none()
            if job is None:
                logger.warning("Ingest job not found, skipping", job_id=job_id)
                return

            dataset = (
                await session.execute(
                    select(Dataset)
                    .options(joinedload(Dataset.record))
                    .where(Dataset.id == dataset_uuid)
                )
            ).scalar_one_or_none()
            if dataset is None:
                logger.warning("Dataset not found, skipping", dataset_id=dataset_id)
                return

            heartbeat_task = await claim_job_attempt_and_start_heartbeat(
                session, job_uuid, attempt_uuid
            )
            if heartbeat_task is None:
                return

            await claim_run_for_job(session, job_uuid)
            await session.commit()

        # ----------------------------------------------------------------- #
        # Phase 2: measure the live table and write the result. One session
        # and one transaction, so the numbers that get stored are the numbers
        # that were read — a recount committed apart from the extent it was
        # measured with would describe no state the table was ever in.
        # ----------------------------------------------------------------- #
        from app.processing.ingest.metadata import (
            compute_quality_score,
            extract_metadata,
            get_sample_values,
            refresh_attribute_metadata,
        )

        schema = _current_tenant_schema()

        async with async_session() as session:
            dataset = (
                await session.execute(
                    select(Dataset)
                    .options(joinedload(Dataset.record))
                    .where(Dataset.id == dataset_uuid)
                )
            ).scalar_one_or_none()
            if dataset is None:
                logger.warning("Dataset not found, skipping", dataset_id=dataset_id)
                return

            bound = (dataset.origin_uri, dataset.origin_ref, dataset.source_format)
            table_name = _resolve_bound_table(dataset, schema=schema)

            try:
                if not await _relation_exists(session, schema=schema, table=table_name):
                    raise PostgisRefreshError(
                        _MISSING_VERDICT.message,
                        error_code=_MISSING_VERDICT.error_code,
                        health=_MISSING_VERDICT.health,
                        detail=_MISSING_VERDICT.detail,
                    )
                metadata = await extract_metadata(session, table_name, schema=schema)
                sample_values = await get_sample_values(
                    session,
                    table_name,
                    metadata.get("column_info") or [],
                    schema=schema,
                )
            except DBAPIError as exc:
                # Every read of the origin is inside this block, and the
                # explicit existence check is not the only thing that can
                # discover an absence: the relation can be dropped, or its
                # GRANT revoked, between two statements. The SQLSTATE says
                # which, so the verdict is read off the driver rather than
                # inferred from the check that had just passed.
                raise _classify_db_failure(exc) from exc

            # Measured against the values still stored, before the writes
            # below overwrite them — the same ordering rule the swap paths
            # follow, and the reason it is load-bearing here too. There is no
            # staging copy on this path, so the diff is live-vs-recorded:
            # what the table looks like now against what the catalog last
            # wrote down. Recorded, never refused (#1223, Amendment A5).
            schema_diff = port.compute_schema_diff(
                dataset.column_info or [],
                metadata.get("column_info") or [],
                dataset.feature_count,
                metadata.get("feature_count"),
            )
            count_before = dataset.feature_count
            feature_count = metadata.get("feature_count")

            _apply_measurement(dataset, metadata, sample_values)
            await refresh_attribute_metadata(
                session,
                dataset.id,
                metadata.get("column_info") or [],
                geometry_type=metadata.get("geometry_type"),
                sample_values=sample_values,
            )
            # After the field writes: the score reads dataset.geometry_type
            # and dataset.srid, and scoring the old ones would report on a
            # measurement that no longer exists.
            dataset.quality_detail = await compute_quality_score(
                session,
                table_name,
                metadata.get("column_info") or [],
                dataset,
                schema=schema,
            )

            now = datetime.now(timezone.utc)
            # The measurement succeeded, so the relation demonstrably exists
            # and is readable. This strategy is the only writer of the verdict
            # for its origin kind — the probe refuses postgis — so without
            # this line a table that was marked `missing` and then restored
            # would carry that verdict forever.
            dataset.source_health = _HEALTHY
            dataset.source_health_detail = None
            # Decision 5a's refresh is this operation, so this operation is
            # what dates it. `last_checked_at` is stamped by the run
            # finalizer below, from contacted_origin.
            dataset.last_refreshed_at = now

            await require_ingest_job_update(
                session,
                job_uuid,
                attempt_uuid,
                values={"status": "complete", "completed_at": now},
            )
            # The run's terminal status commits with the job's, which is what
            # makes "job complete, run still running" unreachable for the
            # stale-run sweep. dataset_version_id is None and that is not a
            # gap: no data moved, so there is no new version of it to point
            # at. contacted_origin=True — the origin is a relation in this
            # database and this run read it, which is exactly what
            # last_checked_at records.
            await record_refresh_success(
                session,
                ingest_job_id=job_uuid,
                dataset=dataset,
                dataset_version_id=None,
                feature_count_after=feature_count,
                schema_diff=schema_diff,
                contacted_origin=True,
            )
            live_table_name = dataset.table_name
            await session.commit()

        await invalidate_catalog_cache()
        # A recount that moved is proof the table's contents changed under
        # the cache, and the MVT cache key has no content-version dimension —
        # so cached tiles would keep being 304-served against rows that are
        # gone. Nothing else on this path touches tiles: GeoLens did not
        # replace this table's data, it discovered that somebody else did.
        if feature_count != count_before:
            await invalidate_tile_cache_for_table(live_table_name)

        # Non-fatal, and for the same reason the reupload paths do it: the
        # embedding is built from the column names and sample values this run
        # just rewrote, so leaving it alone would keep semantic search
        # answering from the schema the table used to have.
        async with async_session() as embed_session:
            embed_dataset = (
                await embed_session.execute(
                    select(Dataset)
                    .options(joinedload(Dataset.record))
                    .where(Dataset.id == dataset_uuid)
                )
            ).scalar_one_or_none()
            if embed_dataset is not None:
                from app.processing.embeddings.helpers import defer_embedding

                await defer_embedding(embed_dataset)

    except Exception as exc:  # broad: any step here is a database read that can fail
        logger.exception(
            "Registered-table refresh failed", job_id=job_id, task="refresh_postgis"
        )
        error_code = getattr(exc, "error_code", _ERROR_CODE_GENERIC)
        async with async_session() as err_session:
            await update_ingest_job_for_attempt(
                err_session,
                job_uuid,
                attempt_uuid,
                values={
                    "status": "failed",
                    "error_message": str(exc),
                    "completed_at": datetime.now(timezone.utc),
                },
            )
            await err_session.commit()
            await _stamp_failed_health(
                err_session,
                Dataset,
                dataset_uuid,
                health=getattr(exc, "health", None),
                detail=getattr(exc, "detail", None),
                bound=bound,
            )
            # contacted_origin=False so the run finalizer does not repeat the
            # dataset write above a second, weaker way (it would stamp
            # last_checked_at for failures that never reached the relation).
            await record_refresh_failure(
                err_session,
                ingest_job_id=job_uuid,
                error_code=error_code,
                error_message=str(exc),
                contacted_origin=False,
            )
            await err_session.commit()
        raise
    finally:
        await stop_ingest_job_heartbeat(heartbeat_task)
