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
from collections.abc import Iterator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, NamedTuple

import structlog
from sqlalchemy import func, select, text
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
    cleanup_step,
    _current_tenant_role,
    _current_tenant_schema,
    _declared_geometry_type,
    _derived_record_type,
    _effective_geometry_type,
    _retire_geometry_attribute_row,
    bump_tile_cache_version_atomic,
    invalidate_tile_cache_for_table,
    stamp_failed_origin_health,
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
_ERROR_CODE_SUPERSEDED = "superseded"

# fix(#1738): the repair phase's own statement deadline, in milliseconds.
#
# `install_api_statement_timeout` runs in the API process only (`api/main.py`;
# the docstring on `core/statement_timeout.py` says so explicitly), so a
# worker statement has NO deadline at all. Every other statement this task
# issues is a read under a read-only snapshot; the repair below is the one
# write it makes to a relation GeoLens does not own, and an unbounded UPDATE
# there holds row locks on somebody else's table for as long as it takes.
#
# Five minutes: far longer than the common case (a table nobody wrote to
# matches no rows, so the statement is one sequential scan), and short enough
# that a table too large to re-derive inside it gives the deadline back rather
# than sitting on the owner's locks. The bound is on the whole repair
# transaction, not just the UPDATE, because the DDL takes an ACCESS EXCLUSIVE
# lock and waiting for one is exactly as blocking as holding one.
_REPAIR_STATEMENT_TIMEOUT_MS = 300_000

# fix(#1738): and a much shorter bound on WAITING for a lock, which is a
# different hazard from holding one.
#
# The repair takes ACCESS EXCLUSIVE when it has to add the column back to a
# recreated table, and a lock request that is merely QUEUED already blocks
# every reader that arrives behind it. Waiting out the statement deadline for
# one would therefore stall the owner's own traffic for five minutes to fix a
# column. Five seconds instead: on a busy table the repair gives its queue
# position back and reports itself blocked, and the next refresh tries again.
_REPAIR_LOCK_TIMEOUT_MS = 5_000

# query_canceled — what `statement_timeout` raises. And lock_not_available,
# what `lock_timeout` raises; they are distinguished because they mean
# different things to whoever reads the log line: too much data to re-derive
# inside the deadline, versus somebody else using the table right now.
_STATEMENT_TIMEOUT_SQLSTATE = "57014"
_LOCK_TIMEOUT_SQLSTATE = "55P03"

# Coded outcomes for the repair phase, logged on every run. They are NOT run
# error codes: a failed repair does not fail the refresh (see
# `_repair_geom_4326`), so none of these ever reaches the run ledger.
#
# They describe the RENDER COLUMN only. The reader grant and the GiST index
# are restored on every outcome where the table is there and the column
# exists, so `not_applicable` still means work may have been done — read
# `index_added` on the report for that half (fix(#1738 rounds 1 and 2)).
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
    # rather than computed here (fix(#1738 round 1)); None when nothing was
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


def _chained_sqlstates(exc: BaseException) -> Iterator[str]:
    """Every SQLSTATE on an exception's chain, outermost first.

    fix(#1313 review): the outermost code is not always the informative one.
    ``extract_metadata``'s spatial fast path catches every exception and
    immediately retries its per-helper queries — inside the transaction the
    first failure has already aborted. So a table dropped or revoked between
    two statements of the measurement surfaces here as ``25P02``
    (in_failed_sql_transaction) with the real ``42P01`` or ``42501`` sitting
    in ``__context__``, because Python records the exception being handled
    when a new one is raised inside an ``except`` block.

    Classifying only the outermost code would report exactly the mid-flight
    race this classifier exists to cover as inconclusive, and leave the
    dataset unmarked. ``25P02`` says "something earlier in this transaction
    failed" and carries no information of its own, so the honest answer is
    the earlier code — which is what walking the chain finds.
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
        # The outermost code, because that is the one an operator correlating
        # against their own logs will see.
        verdict = _inconclusive_verdict(codes[0] if codes else None)
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


async def _repair_geom_4326(
    dataset_uuid: uuid.UUID, Dataset: Any, *, schema: str, role: str
) -> _RepairReport:
    """Phase 1.5: re-derive this table's render column before measuring it.

    fix(#1738): ``geom_4326`` is written once, at registration, and never
    again. The owner of a registered table keeps writing to it — that is the
    whole premise of registering one — and none of those writes touch the
    render column every GeoLens reader filters on, so an ``UPDATE geom``, a
    ``DELETE`` plus re-``INSERT``, or an ``ogr2ogr -overwrite`` leaves rows
    that are silently invisible in tiles, feature reads, extent and analysis.

    Refresh is the right place for the correction: it is the existing
    user-facing "make the catalog agree with the table" action, with an
    admission gate, a run ledger and a history behind it, and it already bumps
    the tile version and purges the tile cache. It is also the only place the
    fix can live and still survive ``-overwrite``, because that drops the
    table: a trigger, a generated column or an index would go with it, and
    only an invariant re-applied from outside comes back.

    **Before the measurement, in its own session and transaction**, so the
    measurement in phase 2 measures the repaired table under its own READ ONLY
    REPEATABLE READ snapshot, and so the tile-version bump below is already
    committed when phase 2 reads `content_version` — a bump landing after that
    read would trip phase 3's superseded guard against this task's own write.

    **Bounded twice**, because holding a lock and waiting for one are
    different hazards on a relation GeoLens does not own — see
    ``_REPAIR_STATEMENT_TIMEOUT_MS`` and ``_REPAIR_LOCK_TIMEOUT_MS``.

    **The reader GRANT and the GiST index are restored whatever the geometry
    turned out to be** (fix(#1738 rounds 1 and 2)). They are the other two
    things ``-overwrite`` destroys, and losing them does not depend on the
    render column needing a rewrite: a table recreated with a valid STORED
    GENERATED ``geom_4326`` needs no re-derive, and without these two it is
    unreadable by ``geolens_reader`` and sequentially scanned by every bbox
    predicate the readers issue.

    **Never fatal.** A refresh whose repair could not run still has a
    measurement to take, and that measurement is what the user asked for; the
    outcome is returned and logged instead. This is also what keeps the change
    from adding a failure mode to a strategy that had none: if the repair
    cannot write, the dataset is left exactly as broken as it already was, not
    more so.
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
            # SET LOCAL, spelled as set_config(..., is_local => true) so the
            # statement stays static SQL with a bound value — `SET` takes no
            # parameters, and interpolating the numbers would put a dynamic
            # text() site in this module for no gain. Both bounds are set
            # before anything else runs in this transaction, so every
            # statement below is covered, DDL included.
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
            # Columns rather than the ORM instance: the only thing needed off
            # the row is the binding, and the version bump below is a SQL
            # increment, so this session never holds a Dataset whose
            # `tile_cache_version` could go stale under it.
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
                # A binding fault is phase 2's to report, with the message and
                # the error code it already owns. Repairing nothing here keeps
                # this phase from changing any existing failure path.
                return _RepairReport(_REPAIR_NOT_APPLICABLE)
            if not await _relation_exists(session, schema=schema, table=table_name):
                # Same: the "missing" verdict belongs to the measurement.
                return _RepairReport(_REPAIR_NOT_APPLICABLE)

            # fix(#1738 round 1): probed BEFORE the SRID is resolved, rather
            # than inside the re-derive. `get_table_srid` wraps PostGIS
            # `Find_SRID`, which RAISES rather than returning NULL for a table
            # with no registered geometry column — so a registered non-spatial
            # table (#1359 admits them) used to reach this as an exception, be
            # reported as a repair failure on every refresh, and skip the
            # grant below.
            state = await probe_geom_4326(session, table_name, schema=schema)
            repair = None
            if state.rederivable:
                srid = await get_table_srid(session, table_name, schema=schema)
                repair = await rederive_geom_4326(
                    session, table_name, srid or 4326, schema=schema, state=state
                )

            # fix(#1738 round 2): the index, on the same rule as the grant
            # below — every outcome where the column EXISTS, not only the one
            # where it had to be rewritten. `rederive_geom_4326` was the only
            # caller of the index helper, so an overwrite that recreated the
            # table with a valid STORED GENERATED `geom_4326` (nothing to
            # re-derive) left the dataset with no GiST index at all, and every
            # bbox predicate the readers issue — `geom_4326 && <envelope>` —
            # fell back to a sequential scan on a table GeoLens does not own.
            if repair is not None:
                index_added = repair.index_added
            elif state.has_render:
                index_added = await ensure_geom_4326_gist_index(
                    session, table_name, schema=schema
                )
            else:
                index_added = False

            # fix(#1738 round 1): unconditionally, not only when the render
            # column was rewritten. The GRANT is the third thing `-overwrite`
            # destroys, and it is destroyed whatever the recreated table's
            # geometry looks like — including the two shapes that need no
            # re-derive at all: a valid STORED GENERATED `geom_4326`, and a
            # non-spatial table. Gating it on the re-derive let both pass a
            # refresh while `geolens_reader` still could not read them.
            # Idempotent, and the same call registration makes.
            await grant_reader_access(session, table_name, schema=schema, role=role)

            tile_version = None
            if repair is not None and repair.rows_rewritten:
                # Gated on rewritten ROWS, not on the column or the index.
                # Restoring an index changes how a tile is computed and not
                # what it contains, and a column added to a table with nothing
                # in it renders the same nothing; a table that had rows and
                # lost the column has all of them in this count anyway. The
                # contract on the bump is that it happens in the same
                # transaction as a change to tile CONTENT, so anything looser
                # would bust every cached tile of every registered dataset on
                # the first refresh after this ships.
                #
                # fix(#1738 round 1): the ATOMIC spelling, because this
                # transaction holds no lock on the datasets row and the
                # feature-edit routers write the counter without one either —
                # see `bump_tile_cache_version_atomic`. It busts browser and
                # CDN copies through the `_v=` parameter, which the
                # server-side purge below cannot reach.
                tile_version = await bump_tile_cache_version_atomic(
                    session, Dataset, dataset_uuid
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
        # Outside the transaction, because it is not part of it: the MVT cache
        # key has no content-version dimension, so cached tiles are served
        # until they expire and the rows this repair just made visible would
        # stay invisible behind them. The end-of-run purge repeats this on the
        # success path; doing it here as well is what makes the repair visible
        # even when the measurement that follows fails.
        await invalidate_tile_cache_for_table(purge_table)

    return report


class _RecordAs:
    """The record as the measurement implies it, for scoring only.

    fix(#1313 review round 7): ``compute_quality_score`` branches on
    ``record_type`` to choose which dimensions apply, and the loaded record
    still carries the PRE-refresh modality. Scoring a table that has just
    gained geometry under the tabular branch drops the geometry and CRS
    dimensions from a score that is then persisted beside a
    ``vector_dataset`` record — the mismatch is stored, not transient.

    Delegates everything else to the real record, because the metadata
    dimension reads a dozen of its fields and its id.
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
    in the measure phase rather than here, so the value written and the value
    the quality score was computed under are the same value rather than two
    derivations of it.

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
    dataset.geometry_type = effective_geometry_type
    # fix(#1313 review round 6): keep the derivation registration makes.
    # `service_create.py` sets `record_type = "table" if geometry_type is None
    # else "vector_dataset"`, and this task is the only thing that can change
    # the answer for a registered table afterwards — an empty table registered
    # as `table` that later gains rows, or a vector dataset whose geom column
    # is dropped. `build_assets` reads `record_type` live, so leaving it stale
    # means a now-spatial dataset never advertises vector tiles or OGC
    # features, and a de-spatialized one advertises tiles it cannot serve.
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
        # Phase 2: MEASURE, under one snapshot, writing nothing.
        #
        # fix(#1313 review): the measurement is four separate reads of a table
        # somebody else is writing to, and the session's default isolation is
        # READ COMMITTED — where every statement takes its own snapshot. One
        # transaction was therefore never one state: the count, the extent,
        # the samples and the validity score could each describe a different
        # instant, and the catalog would store a combination the table was
        # never in. REPEATABLE READ makes the transaction the unit of
        # consistency, which is what this phase was already claiming to be.
        #
        # The writes are in phase 3 rather than here, and that split is what
        # makes the snapshot safe to take: the heartbeat renews this job's row
        # from its own session throughout, so finalizing the job inside a
        # REPEATABLE READ transaction would collide with it and abort the run
        # with a serialization failure. READ ONLY states the intent and makes
        # a future write from this phase fail loudly rather than silently
        # under a snapshot it should not hold.
        # ----------------------------------------------------------------- #
        from app.processing.ingest.metadata import (
            compute_quality_score,
            extract_metadata,
            get_sample_values,
            refresh_attribute_metadata,
        )

        schema = _current_tenant_schema()

        # ----------------------------------------------------------------- #
        # Phase 1.5: REPAIR the render column, before anything measures it.
        #
        # fix(#1738). The one write this task makes to the registered table,
        # deliberately ahead of the read-only phase below rather than inside
        # it: that phase declares `postgresql_readonly=True` precisely so a
        # write from it fails loudly. Non-fatal by design — see
        # `_repair_geom_4326`.
        # ----------------------------------------------------------------- #
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
            # fix(#1313 review round 4): established on the CONNECTION, before
            # the transaction opens — not with a SET TRANSACTION statement
            # inside it.
            #
            # PostgreSQL refuses SET TRANSACTION once any query has run in the
            # transaction (25001), and this engine carries a `begin` hook:
            # `tenant_session._on_begin` issues `SELECT set_config('app.
            # current_tenant', ...)` the instant a multi-tenant transaction
            # starts. So the in-transaction spelling worked in single-tenant,
            # where that hook is a hard no-op, and would have failed EVERY
            # registered-table refresh on a multi-tenant deployment — before
            # the dataset was even loaded. A single-tenant test suite cannot
            # see that, which is why the regression test installs its own
            # begin-time query rather than trusting the default.
            #
            # The execution option is applied to the BEGIN itself, so it lands
            # ahead of any hook, and SQLAlchemy restores the connection's
            # default when it returns to the pool.
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
            # fix(#1313 review round 5): the token phase 3 checks before it
            # writes. `bump_tile_cache_version`'s contract is that it is
            # called in the same transaction as any change to this dataset's
            # tile content — feature edits, column DDL, reupload — which is
            # exactly the set of changes that would make the measurement
            # below stale. It is the codebase's own answer to "did this
            # dataset's content move", so it is what the write is guarded on.
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
                # Resolved BEFORE the score, because the score depends on it:
                # an emptied spatial table whose type comes from the declared
                # column is still spatial, and scoring it off the sampled
                # None would drop the geometry and CRS dimensions.
                effective_geometry_type = _effective_geometry_type(
                    measured=metadata.get("geometry_type"),
                    declared=declared_geometry_type,
                    stored=dataset.geometry_type,
                )
                # Scored against the measurement, not the values it replaces:
                # the CRS and geometry dimensions read `srid` and
                # `geometry_type` off the object they are handed, and the
                # modality branch reads `record_type` off its record. A
                # stand-in rather than the loaded row because this transaction
                # is READ ONLY — mutating the ORM instance here would let an
                # autoflush attempt a write under a snapshot that must not
                # hold one.
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
                # Every read of the origin is inside this block, and the
                # explicit existence check is not the only thing that can
                # discover an absence: the relation can be dropped, or its
                # GRANT revoked, between two statements. The SQLSTATE says
                # which, so the verdict is read off the driver rather than
                # inferred from the check that had just passed.
                raise _classify_db_failure(exc) from exc
            await session.rollback()

        feature_count = metadata.get("feature_count")

        # ----------------------------------------------------------------- #
        # Phase 3: WRITE what phase 2 measured, at the ordinary isolation
        # level. The dataset is re-loaded rather than carried over: the phase
        # 2 instance belongs to a transaction that is gone, and the row this
        # phase writes has to be one attached to the session doing the
        # writing.
        # ----------------------------------------------------------------- #
        async with async_session() as session:
            # fix(#1313 review round 5): lock the row, THEN check the token.
            #
            # Feature writes are not blocked by the refresh admission index —
            # nothing stops an insert or a delete landing while a large table
            # is being measured — and `refresh_dataset_metadata` recomputes
            # `feature_count` and the record extent from the live table on
            # every one of them. Applying this snapshot over the top would
            # roll the catalog back to a count and an extent that were true
            # before that edit, and leave it that way until the next write.
            #
            # `FOR UPDATE` on the datasets row makes the check and the write
            # one indivisible step: a concurrent feature write either commits
            # before this lock is granted (and the token check catches it) or
            # waits behind this transaction (and re-measures afterwards).
            # Reading a single column keeps the statement off the joined
            # record, which PostgreSQL will not lock through an outer join.
            #
            # fix(#1847): also the first half of the house (datasets, records)
            # order, since `_apply_measurement` writes the record row below.
            # The order is stated in `app/platform/catalog_locks.py`.
            #
            # What this guard is NOT (review round 6): it does not detect the
            # OWNER writing to the table directly, because nothing outside
            # GeoLens bumps a catalog field. That is deliberate and not a gap
            # this guard could close. A measurement of a relation GeoLens does
            # not own is true as of a point in time and stale the moment the
            # owner's next commit lands — before this write, after it, or a
            # second later — and the only way to be atomic with an external
            # writer is to lock a table that belongs to somebody else, which
            # is precisely what "no data movement, serves from the live table"
            # forbids. The catalog going stale again is the ordinary condition
            # this whole feature exists to correct, on demand. What the guard
            # closes is the different and fixable problem: GeoLens rolling
            # BACK its own newer measurement.
            # fix(#1847): the job row first, the order every worker phase and
            # the dataset delete hold; the finalize write below touches it.
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
            # below overwrite them — the same ordering rule the swap paths
            # follow, and the reason it is load-bearing here too. There is no
            # staging copy on this path, so the diff is live-vs-recorded:
            # what the table looks like now against what the catalog last
            # wrote down. Recorded, never refused (#1223, Amendment A5).
            schema_diff = port.compute_schema_diff(
                dataset.column_info or [],
                metadata.get("column_info") or [],
                dataset.feature_count,
                feature_count,
            )
            # Read before `_apply_measurement` overwrites it, for the same
            # reason the diff above is: this is the only place the PRE-refresh
            # value is still available.
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
            # fix(#1313 review round 7): the one row that helper will not
            # retire, and since fix(#1380) the reupload swap retires it through
            # the same function — two paths whose relation can lose its
            # geometry column while keeping its identity, one retirement.
            await _retire_geometry_attribute_row(
                session, dataset.id, geometry_type=effective_geometry_type
            )
            # fix(#1314): the persisted half of the modality change.
            # `_apply_measurement` restamps `record_type`, which is what
            # `build_assets` computes its links from — but
            # `record_distributions` rows are generated once, at creation, and
            # nothing re-derives them. Left
            # alone, a table that just gained geometry never advertises vector
            # tiles or GeoPackage in the catalog record, and one that lost it
            # goes on advertising both against a relation that cannot serve
            # them. Gated on the modality FLIP rather than run unconditionally:
            # reconcile normalizes `is_primary` across the generated rows, and
            # a refresh that changed no modality has no business rewriting it.
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
            # fix(#1313 review round 3): the other half of the tile story, and
            # the half the Valkey purge below cannot do. That purge clears the
            # SERVER cache; the `_v=` parameter in the tile URL is what busts
            # browser and CDN caches, and nothing else can reach them. In the
            # write transaction, beside the content change it describes, which
            # is the contract on the method and what every other tile-content
            # mutation does.
            dataset.bump_tile_cache_version()

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
        # fix(#1313 review): unconditionally, not only when the recount moved.
        # The MVT cache key has no content-version dimension, so cached tiles
        # are 304-served until they expire — and an owner who edits geometry,
        # rewrites attributes, or deletes and reinserts the same number of
        # rows changes every tile while leaving the count identical. Gating on
        # the count made the common case the one that silently kept serving
        # stale bytes. Nothing else on this path touches tiles: GeoLens did
        # not replace this table's data, it discovered that somebody else did,
        # and a refresh is an explicit request to stop describing the old
        # state.
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
            await stamp_failed_origin_health(
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
        async with cleanup_step("refresh_postgis heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(heartbeat_task)
