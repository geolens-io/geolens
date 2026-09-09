"""Procrastinate task: re-measure a registered PostGIS table.

feat(#1265) / ADR-002 Decision 5a. A registered table copies no data — the
catalog points at the live relation — so what GeoLens stores about it is a
measurement taken once at registration, of a table its owner keeps writing
to. This task re-takes that measurement: no fetch, no staging table, no
swap, the source IS the destination.

Runs as a worker task (not inline in the request) to reuse the shared
admission-gate/run-ledger/history machinery (handoff invariant 11), and to
avoid holding an HTTP connection open across a ``COUNT(*)`` of unknown size.

The source-health probe (#1222) refuses postgis origins outright — probing
one would mean an HTTP request to a relation — so this task owns the
``source_health`` verdict for its origin kind via a SQLSTATE lookup, rather
than leaving it to the probe's classifier like every other strategy does.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, NamedTuple

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.failure_reason import redact_failure_reason
from app.core.db.sqlstate import sqlstate
from app.core.db.tenant_session import tenant_task
from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.catalog_locks import bump_tile_cache_version_atomic
from app.platform.jobs.heartbeat import (
    claim_job_attempt_and_start_heartbeat,
    require_ingest_job_update,
    resolve_ingest_attempt_or_skip,
    stop_ingest_job_heartbeat,
    write_job_failure_for_attempt,
)
from app.platform.refresh.service import (
    claim_run_for_job,
    record_refresh_failure,
    record_refresh_success,
)
from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    cleanup_step,
    _current_tenant_role,
    _current_tenant_schema,
    _declared_geometry_type,
    _derived_record_type,
    _effective_geometry_type,
    _retire_geometry_attribute_row,
    invalidate_tile_cache_for_table,
    stamp_failed_origin_health,
    task_app,
)

logger = structlog.get_logger(__name__)

# ADR-002's stored source_health values, retyped rather than imported since
# processing/ may not import app.modules.catalog
# (test_no_processing_imports_catalog); test_postgis_refresh_1265 asserts
# these against the probe's own vocabulary so a divergence fails a test.
_HEALTHY = "healthy"
_MISSING = "missing"
_INACCESSIBLE = "inaccessible"

# Members of the probe's closed DETAIL_CODES set: dropped relation = resource
# gone, revoked GRANT = access lost, dead connection = transport failing —
# the same three distinctions the probe draws over HTTP.
_NOT_FOUND = "not_found"
_UNAUTHORIZED = "unauthorized"
_NETWORK_ERROR = "network_error"

_ERROR_CODE_MISSING = "source_missing"
_ERROR_CODE_INACCESSIBLE = "source_inaccessible"
_ERROR_CODE_GENERIC = "postgis_refresh_failed"
_ERROR_CODE_SUPERSEDED = "superseded"

# fix(#1738): repair phase's own statement deadline, in ms. Worker statements
# have no deadline (`install_api_statement_timeout` only runs in the API
# process), and this repair UPDATE is the one write this task makes to a
# relation GeoLens doesn't own — bounding it caps how long it holds someone
# else's row locks. Five minutes covers the common case (matches no rows, one
# seq scan) while giving the deadline back on an oversized table; the bound
# covers the whole transaction since the DDL's ACCESS EXCLUSIVE lock is
# blocking whether held or awaited.
_REPAIR_STATEMENT_TIMEOUT_MS = 300_000

# fix(#1738): a much shorter bound on WAITING for the lock — a QUEUED lock
# request already blocks readers behind it, so waiting the full statement
# deadline for one would stall the owner's traffic for 5 minutes. 5 seconds
# instead: a busy table gives its queue position back and the next refresh retries.
_REPAIR_LOCK_TIMEOUT_MS = 5_000

# query_canceled (statement_timeout) vs lock_not_available (lock_timeout):
# distinguished because they mean different things in the log — too much
# data to re-derive, versus somebody else using the table right now.
_STATEMENT_TIMEOUT_SQLSTATE = "57014"
_LOCK_TIMEOUT_SQLSTATE = "55P03"

# Coded repair-phase outcomes, logged every run. NOT run error codes — a
# failed repair doesn't fail the refresh (see `_repair_geom_4326`).
#
# These describe the render column only; the reader grant and GiST index are
# restored on every outcome where the table/column exist, so
# `not_applicable` may still mean work was done — see `index_added` on the
# report for that half (fix(#1738)).
_REPAIR_REPAIRED = "repaired"
_REPAIR_NOT_APPLICABLE = "not_applicable"
_REPAIR_TIMED_OUT = "timed_out"
_REPAIR_BLOCKED = "blocked"
_REPAIR_FAILED = "failed"


class _RepairReport(NamedTuple):
    """What phase 1.5 did, for the log line and for the tests."""

    code: str
    rows_rewritten: int = 0
    column_added: bool = False
    index_added: bool = False
    # The version the bump actually published, read back from the increment
    # rather than computed here (fix(#1738)); None when nothing was
    # rewritten and so nothing was bumped.
    tile_cache_version: int | None = None


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
# are listed. A statement timeout or deadlock says something about the
# query, not the table, and falls through to the inconclusive verdict below,
# which writes no health — reporting a healthy table missing because one
# COUNT(*) was slow would be worse than reporting nothing.
_VERDICT_BY_SQLSTATE: dict[str, _Verdict] = {
    # undefined_table
    "42P01": _MISSING_VERDICT,
    # insufficient_privilege. Deliberately NOT "missing": the table may be
    # intact behind a revoked GRANT — same distinction the probe draws
    # between 404 and 403.
    "42501": _Verdict(
        _ERROR_CODE_INACCESSIBLE,
        _INACCESSIBLE,
        _UNAUTHORIZED,
        "GeoLens is no longer allowed to read the registered table this "
        "dataset points at. Restore the GeoLens role's SELECT privilege on "
        "it, then refresh again.",
    ),
}

# connection_exception and friends, matched on the two-character class since
# the whole class means one thing here. Barely reachable while gate 2 holds
# (origin is a relation in the DB GeoLens already talks to), mapped anyway so
# it can't fall through to a verdict that blames the table.
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
    origin, the source-health verdict to persist — classified once, at the
    point with the evidence, rather than re-classified by the failure handler.
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
    conclusive attempt wrote. The SQLSTATE is included since it's a
    five-character code from a closed set an operator can act on.
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


def _chained_sqlstates(exc: BaseException) -> Iterator[str]:
    """Every SQLSTATE on an exception's chain, outermost first.

    fix(#1313): the outermost code isn't always informative. When a table is
    dropped/revoked mid-measurement, ``extract_metadata``'s retry inside an
    already-aborted transaction surfaces ``25P02``
    (in_failed_sql_transaction) with the real ``42P01``/``42501`` in
    ``__context__``. ``25P02`` carries no information of its own, so the
    honest answer is the earlier code found by walking the chain.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, DBAPIError):
            code = sqlstate(current)
            if code:
                yield code
        current = current.__cause__ or current.__context__


def _classify_db_failure(exc: DBAPIError) -> PostgisRefreshError:
    """Turn a driver error from the live table into a refresh verdict."""
    codes = list(_chained_sqlstates(exc))
    verdict: _Verdict | None = None
    for code in codes:
        verdict = _VERDICT_BY_SQLSTATE.get(code)
        if verdict is None and code[:2] == _CONNECTION_CLASS:
            verdict = _CONNECTION_VERDICT
        if verdict is not None:
            break
    if verdict is None:
        # Outermost code: what an operator correlating against their own logs sees.
        verdict = _inconclusive_verdict(codes[0] if codes else None)
    return PostgisRefreshError(
        verdict.message,
        error_code=verdict.error_code,
        health=verdict.health,
        detail=verdict.detail,
    )


def _resolve_bound_table(dataset: Any, *, schema: str) -> str:
    """The bare table name to re-measure, proven to be this dataset's own.

    ``origin_ref.table_name`` (JSONB) names the table but must not steer the
    read: a name taken from it and dropped into a query is one bad row away
    from measuring a relation belonging to somebody else. So the pointer is
    checked, not trusted — it must match the active tenant's data schema
    plus ``datasets.table_name``, the pair every other reader uses.
    Registration writes both from one value, so disagreement is a genuine
    fault (hand-edited row, interrupted tenant migration) that stops the
    refresh rather than silently picking a winner.
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

    ``to_regclass`` answers for a name, so a dropped/renamed table is a NULL
    instead of an exception, keeping the "missing" verdict from depending on
    which statement hit the absence first. ``format('%I.%I', ...)`` composes
    the identifier from bound parameters — nothing is interpolated here —
    and the casts are load-bearing since ``format`` is variadic ``"any"``
    and asyncpg can't infer a parameter type through it.
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


async def _repair_geom_4326(
    dataset_uuid: uuid.UUID, Dataset: Any, *, schema: str, role: str
) -> _RepairReport:
    """Phase 1.5: re-derive this table's render column before measuring it.

    fix(#1738): ``geom_4326`` is derived once at registration and never
    again, but the owner keeps writing to the table — an ``UPDATE geom``, a
    delete+re-insert, or ``ogr2ogr -overwrite`` leaves rows silently
    invisible in tiles, feature reads, extent, and analysis, since none of
    those writes touch the render column readers filter on.

    Refresh is the only place the fix can live and still survive
    ``-overwrite`` (which drops the table, taking any trigger/generated
    column/index with it) — a re-applied invariant is the only kind that
    comes back. Runs before the measurement, in its own session/transaction,
    so phase 2 measures the repaired table under its own snapshot, and its
    tile-version bump is already committed before phase 2 reads
    `content_version` (a later bump would trip phase 3's superseded guard
    against this task's own write).

    Bounded twice (``_REPAIR_STATEMENT_TIMEOUT_MS``,
    ``_REPAIR_LOCK_TIMEOUT_MS``) since holding vs. waiting on a lock are
    different hazards on a table GeoLens doesn't own.

    The reader GRANT and GiST index are restored regardless of the geometry
    outcome (fix(#1738)) — the other two things ``-overwrite`` destroys,
    independent of whether the render column needs a rewrite.

    Never fatal: a refresh whose repair can't run still takes its
    measurement and reports the repair outcome, leaving the dataset no more
    broken than it already was.
    """
    from app.core.db import async_session
    from app.processing.ingest.metadata import (
        ensure_geom_4326_gist_index,
        get_table_srid,
        grant_reader_access,
        probe_geom_4326,
        rederive_geom_4326,
    )

    report = _RepairReport(_REPAIR_NOT_APPLICABLE)
    purge_table: str | None = None

    async with async_session() as session:
        try:
            # SET LOCAL via set_config(..., is_local => true) so the statement
            # stays static SQL with a bound value (`SET` takes no
            # parameters). Set before anything else runs, so every statement
            # below is covered, DDL included.
            await session.execute(
                text(
                    "SELECT set_config('statement_timeout', :ms, true), "
                    "       set_config('lock_timeout', :lock_ms, true)"
                ),
                {
                    "ms": str(_REPAIR_STATEMENT_TIMEOUT_MS),
                    "lock_ms": str(_REPAIR_LOCK_TIMEOUT_MS),
                },
            )
            # Columns, not the ORM instance: only the binding is needed, and
            # the version bump below is a SQL increment, so this session
            # never holds a Dataset whose `tile_cache_version` could go stale.
            binding = (
                await session.execute(
                    select(Dataset.origin_ref, Dataset.table_name).where(
                        Dataset.id == dataset_uuid
                    )
                )
            ).first()
            if binding is None:
                return _RepairReport(_REPAIR_NOT_APPLICABLE)
            try:
                table_name = _resolve_bound_table(binding, schema=schema)
            except PostgisRefreshError:
                # A binding fault is phase 2's to report; don't touch its failure path.
                return _RepairReport(_REPAIR_NOT_APPLICABLE)
            if not await _relation_exists(session, schema=schema, table=table_name):
                # Same: the "missing" verdict belongs to the measurement.
                return _RepairReport(_REPAIR_NOT_APPLICABLE)

            # fix(#1738): probed before the SRID is resolved. `get_table_srid`
            # wraps PostGIS `Find_SRID`, which RAISES rather than returning
            # NULL for a table with no geometry column — so a registered
            # non-spatial table (#1359) used to hit this as an exception,
            # reported as a repair failure every refresh, skipping the grant below.
            state = await probe_geom_4326(session, table_name, schema=schema)
            repair = None
            if state.rederivable:
                srid = await get_table_srid(session, table_name, schema=schema)
                repair = await rederive_geom_4326(
                    session, table_name, srid or 4326, schema=schema, state=state
                )

            # fix(#1738): index restored on the same rule as the grant below —
            # every outcome where the column EXISTS, not only a rewrite.
            # `rederive_geom_4326` was the only caller of the index helper,
            # so a valid STORED GENERATED `geom_4326` after overwrite (nothing
            # to re-derive) left no GiST index, and bbox predicates fell back
            # to a sequential scan on a table GeoLens doesn't own.
            if repair is not None:
                index_added = repair.index_added
            elif state.has_render:
                index_added = await ensure_geom_4326_gist_index(
                    session, table_name, schema=schema
                )
            else:
                index_added = False

            # fix(#1738): unconditional, not only when rewritten. The GRANT
            # is the third thing `-overwrite` destroys regardless of the
            # recreated table's geometry — including a valid STORED
            # GENERATED `geom_4326` or a non-spatial table, both of which
            # need no re-derive but still left `geolens_reader` locked out
            # when this was gated on it. Idempotent, same call registration makes.
            await grant_reader_access(session, table_name, schema=schema, role=role)

            tile_version = None
            if repair is not None and repair.rows_rewritten:
                # Gated on rewritten ROWS, not column or index: the bump's
                # contract is that it fires with a change to tile CONTENT.
                # An index restore doesn't change content; an added column on
                # an empty table renders the same nothing.
                #
                # fix(#1738): atomic spelling — this transaction holds no
                # lock on the datasets row.
                tile_version = await bump_tile_cache_version_atomic(
                    session, dataset_cls=Dataset, dataset_id=dataset_uuid
                )
                purge_table = table_name
            await session.commit()
            report = _RepairReport(
                _REPAIR_REPAIRED if repair is not None else _REPAIR_NOT_APPLICABLE,
                repair.rows_rewritten if repair is not None else 0,
                repair.column_added if repair is not None else False,
                index_added,
                tile_version,
            )
        except Exception as exc:  # broad: the repair is best-effort — see the docstring
            await session.rollback()
            codes = set(_chained_sqlstates(exc))
            if _STATEMENT_TIMEOUT_SQLSTATE in codes:
                code = _REPAIR_TIMED_OUT
            elif _LOCK_TIMEOUT_SQLSTATE in codes:
                code = _REPAIR_BLOCKED
            else:
                code = _REPAIR_FAILED
            logger.warning(
                "geom_4326 repair did not complete",
                dataset_id=str(dataset_uuid),
                repair=code,
                exc_info=True,
            )
            return _RepairReport(code)

    if purge_table is not None:
        # Outside the transaction: the MVT cache key has no content-version
        # dimension, so without this, rows just made visible stay hidden
        # behind cached tiles until they expire. Repeated by the end-of-run
        # purge on the success path, but doing it here too makes the repair
        # visible even if the measurement that follows fails.
        await invalidate_tile_cache_for_table(purge_table)

    return report


class _RecordAs:
    """The record as the measurement implies it, for scoring only.

    fix(#1313): ``compute_quality_score`` branches on ``record_type``, but
    the loaded record still carries the PRE-refresh modality — scoring a
    table that just gained geometry under the tabular branch would drop the
    geometry/CRS dimensions and persist that mismatch beside a
    ``vector_dataset`` record. Delegates everything else to the real record.
    """

    def __init__(self, record: Any, record_type: str | None) -> None:
        self._record = record
        self.record_type = record_type

    def __getattr__(self, name: str) -> Any:
        return getattr(self._record, name)


def _apply_measurement(
    dataset: Any,
    metadata: dict,
    sample_values: Any,
    *,
    effective_geometry_type: str | None,
) -> None:
    """Write one measurement of the live table onto the catalog row.

    ``effective_geometry_type`` is resolved by :func:`_effective_geometry_type`
    in the measure phase rather than here, so the value written and the
    value the quality score was computed under are the same derivation.

    ``spatial_extent`` is CLEARED when the table has no extent — unlike
    ``_apply_reupload_swap``, which only ever writes a non-NULL extent. This
    path exists solely to make stored metadata agree with the live table, so
    an emptied table still claiming its old footprint is the exact lie this
    operation corrects.

    The column is POLYGON-typed; ``extract_metadata`` already pads a
    degenerate extent and emits a two-ring MULTIPOLYGON for a seam-crossing
    one, so the WKT here is always a shape the column accepts.
    """
    dataset.srid = metadata.get("srid")
    dataset.geometry_type = effective_geometry_type
    # fix(#1313): keep the derivation registration makes
    # (`record_type = "table" if geometry_type is None else "vector_dataset"`)
    # current — this task is the only thing that can change it afterward
    # (an empty table gains rows, or a geom column is dropped).
    # `build_assets` reads `record_type` live, so a stale value means a
    # now-spatial dataset never advertises tiles/features, or vice versa.
    dataset.record.record_type = _derived_record_type(
        dataset.record.record_type, effective_geometry_type
    )
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

    No ``user_id`` argument, unlike the re-upload tasks — a measurement is
    not a new version of the data, so it stamps no ``DatasetVersion`` or
    audit event. The actor is already on the run row as ``triggered_by``.

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
    # guarded write. Left None until phase 2 — a failure before that point
    # established nothing about any origin and must not write a verdict.
    bound: tuple | None = None

    try:
        # Phase 1: claim the attempt and the run, and read the binding.
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

        # Phase 2: MEASURE, under one snapshot, writing nothing.
        #
        # fix(#1313): the measurement is four separate reads of a table
        # somebody else is writing to, and the default READ COMMITTED
        # isolation gives every statement its own snapshot — the count,
        # extent, samples and validity score could each describe a different
        # instant. REPEATABLE READ makes the transaction one consistent unit.
        #
        # Writes are in phase 3, not here: the heartbeat renews this job's
        # row from its own session throughout, so finalizing inside a
        # REPEATABLE READ transaction would collide with it and abort the
        # run with a serialization failure. READ ONLY makes a future write
        # from this phase fail loudly instead of silently.
        from app.processing.ingest.metadata import (
            compute_quality_score,
            extract_metadata,
            get_sample_values,
            refresh_attribute_metadata,
        )

        schema = _current_tenant_schema()

        # Phase 1.5: REPAIR the render column, before anything measures it.
        #
        # fix(#1738): the one write this task makes to the registered table,
        # deliberately ahead of the read-only phase below (which declares
        # `postgresql_readonly=True` precisely so a write fails loudly).
        # Non-fatal by design — see `_repair_geom_4326`.
        repair = await _repair_geom_4326(
            dataset_uuid, Dataset, schema=schema, role=_current_tenant_role()
        )
        logger.info(
            "geom_4326 repair phase finished",
            dataset_id=dataset_id,
            repair=repair.code,
            rows_rewritten=repair.rows_rewritten,
            column_added=repair.column_added,
            index_added=repair.index_added,
            tile_cache_version=repair.tile_cache_version,
        )

        async with async_session() as session:
            # fix(#1313): established on the CONNECTION, before
            # the transaction opens — not with a SET TRANSACTION statement
            # inside it.
            #
            # PostgreSQL refuses SET TRANSACTION once any query has run
            # (25001), and `tenant_session._on_begin` runs a query the
            # instant a multi-tenant transaction starts — so the
            # in-transaction spelling worked in single-tenant only and would
            # have failed every registered-table refresh on multi-tenant.
            # The execution option applies to the BEGIN itself, ahead of any
            # hook; SQLAlchemy restores the connection's default afterward.
            await session.connection(
                execution_options={
                    "isolation_level": "REPEATABLE READ",
                    "postgresql_readonly": True,
                }
            )
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
            # fix(#1313): the token phase 3 checks before it writes.
            # `bump_tile_cache_version`'s contract is to fire in the same
            # transaction as any change to this dataset's tile content —
            # exactly the set of changes that would make the measurement
            # below stale — so it's the codebase's own answer to "did this
            # dataset's content move", and what the write is guarded on.
            content_version = dataset.tile_cache_version

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
                declared_geometry_type = await _declared_geometry_type(
                    session, schema=schema, table=table_name
                )
                # Resolved BEFORE the score, which depends on it: an emptied
                # spatial table (type from the declared column) is still
                # spatial, but scoring off the sampled None would drop the
                # geometry/CRS dimensions.
                effective_geometry_type = _effective_geometry_type(
                    measured=metadata.get("geometry_type"),
                    declared=declared_geometry_type,
                    stored=dataset.geometry_type,
                )
                # Scored against the measurement, not the values it replaces:
                # a stand-in rather than the loaded row, because this
                # transaction is READ ONLY and mutating the ORM instance
                # would let an autoflush attempt a write under it.
                quality_detail = await compute_quality_score(
                    session,
                    table_name,
                    metadata.get("column_info") or [],
                    SimpleNamespace(
                        record=_RecordAs(
                            dataset.record,
                            _derived_record_type(
                                dataset.record.record_type, effective_geometry_type
                            ),
                        ),
                        srid=metadata.get("srid"),
                        geometry_type=effective_geometry_type,
                    ),
                    schema=schema,
                )
            except DBAPIError as exc:
                # The relation can be dropped or its GRANT revoked between
                # two statements even after the existence check passes; read
                # the verdict off the driver's SQLSTATE rather than infer it.
                raise _classify_db_failure(exc) from exc
            await session.rollback()

        feature_count = metadata.get("feature_count")

        # Phase 3: WRITE what phase 2 measured, at the ordinary isolation
        # level. The dataset is re-loaded rather than carried over — the
        # phase 2 instance belongs to a transaction that is gone.
        async with async_session() as session:
            # fix(#1313): lock the row, THEN check the token. Feature writes
            # aren't blocked during measurement, and `refresh_dataset_metadata`
            # recomputes `feature_count`/extent from the live table on every
            # one — applying this snapshot over that would roll the catalog
            # back. `FOR UPDATE` makes check-and-write indivisible: a
            # concurrent write either commits before this lock (caught by
            # the token check) or waits behind this transaction. A single
            # column keeps the statement off the joined record, which
            # PostgreSQL won't lock through an outer join.
            #
            # fix(#1847): job row locked first — the datasets/records lock
            # order stated in `app/platform/catalog_locks.py`, since
            # `_apply_measurement` writes the record row below, and the
            # finalize write touches the job row too.
            #
            # This guard does NOT detect the table owner writing directly —
            # nothing outside GeoLens bumps a catalog field, and being atomic
            # with an external writer would mean locking a table GeoLens
            # doesn't own, which "no data movement" forbids. Going stale
            # again is the ordinary condition this feature corrects on
            # demand; what the guard closes is GeoLens rolling BACK its own
            # newer measurement.
            await session.execute(
                select(IngestJob.id)
                .where(IngestJob.id == job_uuid)
                .with_for_update(key_share=True)
            )
            locked_version = await session.scalar(
                select(Dataset.tile_cache_version)
                .where(Dataset.id == dataset_uuid)
                .with_for_update()
            )
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
            if locked_version != content_version:
                raise PostgisRefreshError(
                    "This dataset's data changed while it was being measured, "
                    "so the older measurement was discarded rather than "
                    "written over the newer state. Refresh again.",
                    error_code=_ERROR_CODE_SUPERSEDED,
                )

            # Measured against the values still stored, before the writes
            # below overwrite them — same ordering rule the swap paths
            # follow. No staging copy on this path, so the diff is
            # live-vs-recorded. Recorded, never refused (#1223, Amendment A5).
            schema_diff = port.compute_schema_diff(
                dataset.column_info or [],
                metadata.get("column_info") or [],
                dataset.feature_count,
                feature_count,
            )
            # Read before `_apply_measurement` overwrites it — same reason
            # as the diff above: the only place the PRE-refresh value exists.
            stored_geometry_type = dataset.geometry_type

            _apply_measurement(
                dataset,
                metadata,
                sample_values,
                effective_geometry_type=effective_geometry_type,
            )
            await refresh_attribute_metadata(
                session,
                dataset.id,
                metadata.get("column_info") or [],
                geometry_type=effective_geometry_type,
                sample_values=sample_values,
            )
            # fix(#1313): since fix(#1380) the reupload swap retires this
            # same row through the same function — two paths whose relation
            # can lose its geometry column while keeping identity, one retirement.
            await _retire_geometry_attribute_row(
                session, dataset.id, geometry_type=effective_geometry_type
            )
            # fix(#1314): the persisted half of the modality change.
            # `_apply_measurement` restamps `record_type`, but
            # `record_distributions` rows are generated once at creation and
            # never re-derived — left alone, a table that gained geometry
            # never advertises vector tiles, and one that lost it keeps
            # advertising formats it can't serve. Gated on the modality FLIP:
            # a refresh with no modality change has no business rewriting
            # `is_primary`.
            if (stored_geometry_type is None) != (effective_geometry_type is None):
                await port.reconcile_distributions(
                    session,
                    dataset.id,
                    dataset.record_id,
                    dataset.table_name,
                    geometry_type=effective_geometry_type,
                )
            dataset.quality_detail = quality_detail

            now = datetime.now(timezone.utc)
            # The measurement succeeded, so the relation demonstrably exists
            # and is readable. This strategy is the only writer of the
            # verdict for its origin kind (the probe refuses postgis), so
            # without this a table marked `missing` and restored would carry
            # that verdict forever.
            dataset.source_health = _HEALTHY
            dataset.source_health_detail = None
            # `last_checked_at` is stamped by the run finalizer below, from contacted_origin.
            dataset.last_refreshed_at = now
            # fix(#1313): the half the Valkey purge below can't do — that
            # purge clears the SERVER cache, while the tile URL's `_v=`
            # parameter is what busts browser/CDN caches. In the write
            # transaction beside the content change it describes, per the
            # contract on this method.
            dataset.bump_tile_cache_version()

            await require_ingest_job_update(
                session,
                job_uuid,
                attempt_uuid,
                values={"status": "complete", "completed_at": now},
            )
            # The run's terminal status commits with the job's, making "job
            # complete, run still running" unreachable for the stale-run
            # sweep. dataset_version_id is None: no data moved, so no new
            # version to point at. contacted_origin=True: this run read the
            # origin relation, which is what last_checked_at records.
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
        # fix(#1313): unconditional, not only when the recount moved. The MVT
        # cache key has no content-version dimension, so an owner who edits
        # geometry or rewrites attributes without changing the row count
        # would otherwise keep serving stale tiles until they expire.
        await invalidate_tile_cache_for_table(live_table_name)

        # Non-fatal, same reason the reupload paths do it: the embedding is
        # built from the column names/sample values this run just rewrote.
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
            # fix(#1957): the job row is the one a retry of this refresh
            # contends for. An expiry leaves it `running` for the stale sweep
            # and does not stop the refresh-run row below from recording why.
            await write_job_failure_for_attempt(
                err_session,
                job_uuid,
                attempt_uuid,
                values={
                    "status": "failed",
                    "error_message": redact_failure_reason(exc),
                    "completed_at": datetime.now(timezone.utc),
                },
                task_name="refresh_postgis",
            )
            await stamp_failed_origin_health(
                err_session,
                Dataset,
                dataset_uuid,
                health=getattr(exc, "health", None),
                detail=getattr(exc, "detail", None),
                bound=bound,
            )
            # contacted_origin=False: the run finalizer would otherwise stamp
            # last_checked_at for failures that never reached the relation.
            await record_refresh_failure(
                err_session,
                ingest_job_id=job_uuid,
                error_code=error_code,
                error_message=exc,
                contacted_origin=False,
            )
            await err_session.commit()
        raise
    finally:
        async with cleanup_step("refresh_postgis heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(heartbeat_task)
