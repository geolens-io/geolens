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

import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any, NamedTuple

import structlog
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.db.sqlstate import sqlstate
from app.core.db.tenant_session import tenant_task
from app.platform.catalog_locks import bump_tile_cache_version_atomic
from app.processing.ingest.catalog_projection import measure, project
from app.processing.ingest.publication import (
    PUBLISH,
    DatasetDeleted,
    Failure,
    PublicationCommit,
    Published,
    Verdict,
    settle_replacement,
)
from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    _current_tenant_role,
    _current_tenant_schema,
    invalidate_tile_cache_for_table,
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
    """Re-derive this table's render column before it is measured.

    ``geom_4326`` is derived once at registration, but the owner keeps
    writing to the table: an ``UPDATE geom``, a delete and re-insert, or
    ``ogr2ogr -overwrite`` leaves rows invisible in tiles, feature reads,
    extent and analysis, since none of those writes touch the render column
    readers filter on.

    Refresh is the only place the fix survives ``-overwrite``, which drops the
    table and any trigger, generated column or index with it. This runs before
    the measurement, in its own transaction, so the measurement sees the
    repaired table and the repair's tile-version bump is committed before the
    content token is read; a later bump would trip the write step's superseded
    check against this task's own repair.

    Bounded twice (``_REPAIR_STATEMENT_TIMEOUT_MS``,
    ``_REPAIR_LOCK_TIMEOUT_MS``) since holding and waiting on a lock are
    different hazards on a table GeoLens doesn't own. The reader GRANT and
    GiST index are restored whatever the geometry outcome: they are the other
    two things ``-overwrite`` destroys.

    Never fatal: a refresh whose repair can't run still takes its
    measurement and reports the repair outcome, leaving the dataset no more
    broken than it already was.
    """
    from app.core.db import async_session
    from app.processing.ingest.metadata import (
        ensure_geom_4326_gist_index,
        get_declared_srid,
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
            srid = await get_declared_srid(session, table_name, schema=schema)
            if srid == 0:
                # Phase 2 refuses a table without an SRID, so nothing about it
                # is re-derived, indexed or granted first.
                return _RepairReport(_REPAIR_NOT_APPLICABLE)

            state = await probe_geom_4326(session, table_name, schema=schema)
            repair = None
            if state.rederivable and srid is not None:
                repair = await rederive_geom_4326(
                    session, table_name, srid, schema=schema, state=state
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
        # Outside the transaction, so a concurrent tile request can't re-cache
        # pre-repair rows. Without it, rows just made visible stay hidden behind
        # cached tiles until the API re-reads the bumped version. Repeated by
        # the end-of-run purge on the success path, but doing it here too makes
        # the repair visible even if the measurement that follows fails.
        await invalidate_tile_cache_for_table(purge_table)

    return report


class _PostgisRefresh:
    """A registered table, re-measured where it lives; nothing is copied or swapped."""

    task = "refresh_postgis"
    staging = False
    raster_row = False
    catalog_event = "postgis_refresh_catalog"

    def __init__(self, *, dataset_id: str):
        self.dataset_uuid = uuid.UUID(dataset_id)
        # The binding this attempt measured against. None until the
        # measurement reads it: nothing before that says anything about an origin.
        self.bound: tuple | None = None

    def prepare(self, job, dataset, staging_table: str) -> None:
        return None

    async def fetch(self) -> None:
        from sqlalchemy.orm import joinedload

        from app.core.db import async_session
        from app.platform.extensions import get_processing_port
        from app.processing.ingest.metadata import get_declared_srid
        from app.processing.ingest.schemas import UNDECLARED_SRID_CODE

        Dataset = get_processing_port().get_dataset_orm_class()
        schema = _current_tenant_schema()
        # The one write to the registered table, ahead of the read-only
        # measurement below. Never fatal; see `_repair_geom_4326`.
        repair = await _repair_geom_4326(
            self.dataset_uuid, Dataset, schema=schema, role=_current_tenant_role()
        )
        logger.info(
            "geom_4326 repair phase finished",
            dataset_id=str(self.dataset_uuid),
            repair=repair.code,
            rows_rewritten=repair.rows_rewritten,
            column_added=repair.column_added,
            index_added=repair.index_added,
            tile_cache_version=repair.tile_cache_version,
        )

        async with async_session() as session:
            # One snapshot for the count, extent, samples and score, set on the
            # connection before BEGIN: a multi-tenant BEGIN runs a query, and
            # SET TRANSACTION is refused after one. READ ONLY makes a write fail.
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
                    .where(Dataset.id == self.dataset_uuid)
                )
            ).scalar_one_or_none()
            if dataset is None:
                raise DatasetDeleted
            self.bound = (dataset.origin_uri, dataset.origin_ref, dataset.source_format)
            table_name = _resolve_bound_table(dataset, schema=schema)
            # The fence `write` checks: the tile version moves with every
            # change to this dataset's content.
            self.content_version = dataset.tile_cache_version
            try:
                if not await _relation_exists(session, schema=schema, table=table_name):
                    raise PostgisRefreshError(
                        _MISSING_VERDICT.message,
                        error_code=_MISSING_VERDICT.error_code,
                        health=_MISSING_VERDICT.health,
                        detail=_MISSING_VERDICT.detail,
                    )
                if await get_declared_srid(session, table_name, schema=schema) == 0:
                    raise PostgisRefreshError(
                        "PostGIS no longer reports an SRID for the registered "
                        "table's geom column, so GeoLens cannot tell where its "
                        "coordinates are. The catalog entry is unchanged; give the "
                        "column an SRID, then refresh again.",
                        error_code=UNDECLARED_SRID_CODE,
                    )
                self.measurement = await measure(
                    session, dataset, table=table_name, schema=schema
                )
            except DBAPIError as exc:
                # The relation can be dropped or its GRANT revoked after the
                # existence check; the driver's SQLSTATE says which.
                raise _classify_db_failure(exc) from exc
            await session.rollback()

    async def stage(self, session, job, dataset) -> Verdict:
        return PUBLISH

    async def install(self, session, dataset) -> None:
        return None

    async def write(self, session, dataset) -> Published:
        from sqlalchemy.orm import joinedload

        from app.platform.extensions import get_processing_port

        Dataset = get_processing_port().get_dataset_orm_class()
        # Re-read under the held rows: a feature write that committed while
        # the table was measured moved the tile version, and this older
        # measurement must not roll the catalog back over it.
        dataset = (
            await session.execute(
                select(Dataset)
                .options(joinedload(Dataset.record))
                .where(Dataset.id == dataset.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        if dataset.tile_cache_version != self.content_version:
            raise PostgisRefreshError(
                "This dataset's data changed while it was being measured, "
                "so the older measurement was discarded rather than "
                "written over the newer state. Refresh again.",
                error_code=_ERROR_CODE_SUPERSEDED,
            )
        # With no staging copy the diff is the live table against what was
        # recorded. Drift is recorded, never refused.
        schema_diff = await project(session, dataset, self.measurement)
        # The measurement read the relation, so it exists and is readable, and
        # this strategy is the only writer of its origin kind's verdict.
        dataset.source_health = _HEALTHY
        dataset.source_health_detail = None
        dataset.last_refreshed_at = datetime.now(timezone.utc)
        # No data moved, so no version; the run dates the contact.
        return Published(
            dataset_version_id=None,
            feature_count=self.measurement.metadata.get("feature_count"),
            schema_diff=schema_diff,
            contacted_origin=True,
            live_table=dataset.table_name,
        )

    def classify(self, exc: BaseException) -> Failure:
        health = getattr(exc, "health", None)
        code = getattr(exc, "error_code", _ERROR_CODE_GENERIC)
        return Failure(
            code,
            contacted=self.bound if health is not None else None,
            health=(health, getattr(exc, "detail", None))
            if health is not None
            else None,
            # An edit overtook the measurement, and the message says to refresh again.
            notify=code != _ERROR_CODE_SUPERSEDED,
        )

    async def release(
        self, *, publication: PublicationCommit | None, failed: bool
    ) -> None:
        return None


@task_app.task(queue="ingest", retry=0)
@tenant_task
async def refresh_postgis(
    job_id: str,
    dataset_id: str,
    attempt_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Background task: re-measure the registered table behind this dataset.

    Recounts features, recomputes the extent and the 3D facts, and rebuilds
    the column schema snapshot, the sample values, the attribute metadata and
    the quality score from the live relation. Nothing is copied and nothing is
    swapped.

    No ``user_id`` argument, unlike the re-upload tasks: a measurement is not
    a new version of the data, so it stamps no ``DatasetVersion`` or audit
    event. The actor is already on the run row as ``triggered_by``.
    """
    _bind_task_log_context(
        task_name="refresh_postgis", job_id=job_id, dataset_id=dataset_id
    )
    await settle_replacement(
        _PostgisRefresh(dataset_id=dataset_id),
        job_id=job_id,
        dataset_id=dataset_id,
        attempt_id=attempt_id,
    )
