"""Materialize a PostGIS analysis result into a new dataset (M4).

The worker builds the output table with server-rendered SQL (shared
expression templates in ``app.platform.analysis_sql``), normalizes it to the
geom/geom_4326 convention, and registers it through the standard ingest
registration path (``register_existing_table``) so metadata extraction,
reader grants, and the atomic dataset-slot quota all apply.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import structlog
from prometheus_client import Counter
from sqlalchemy import select, text
from sqlalchemy.exc import (
    DataError,
    InternalError,
    ProgrammingError,
    SQLAlchemyError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_schema import tenant_data_schema
from app.core.db.tenant_session import current_tenant_var, tenant_task
from app.core.tenancy import is_multi_tenant
from app.platform.analysis_sql import (
    MAX_MASK_LAYER_FEATURES,
    MAX_SOURCE_FEATURES,
    NOT_EMPTY_PREDICATE,
    render_clip_layer_join,
    render_geometry_expr,
)
from app.processing.analysis.provenance import apply_analysis_provenance
from app.platform.jobs.heartbeat import (
    claim_ingest_job_attempt,
    maintain_ingest_job_heartbeat,
    resolve_ingest_job_attempt,
    stop_ingest_job_heartbeat,
    update_ingest_job_for_attempt,
)
from app.processing.ingest.metadata import _sql_quote_ident
from app.processing.ingest.tasks import task_app

logger = structlog.stdlib.get_logger(__name__)

_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_SAFE_TABLE = re.compile(r"^[a-z0-9_]+$")


# The preview path is bounded (10s sandbox timeout, 500-row cap); the CTAS
# here is the only unbounded statement a user can queue, so cap it.
#
# fix(#1013): the value is an operator setting now, not a hardcoded ceiling.
# Read through a function rather than bound at import: these render into SQL
# and into a user-facing message, and a module-level snapshot would freeze
# whatever the settings object held the first time this module was imported.
def materialize_timeout() -> str:
    """The CTAS statement_timeout, as a PostgreSQL interval literal."""
    from app.core.config import settings

    return f"{settings.analysis_materialize_timeout_seconds}s"


# The mid-task commit that makes the output table durable also ends the
# transaction carrying the CTAS budget — registration then runs full-scan
# metadata extraction (COUNT + ST_Extent + the sample-values CTE) in a fresh
# transaction, which would otherwise have no statement budget at all
# (fix(#692)). Larger than the CTAS budget by default: those scans are cheap
# relative to the build, but must never be unbounded.
def registration_timeout() -> str:
    """The post-commit registration statement_timeout, as an interval literal."""
    from app.core.config import settings

    return f"{settings.analysis_registration_timeout_seconds}s"


# fix(#1012): per-statement work_mem for the materialize CTAS.
#
# The cluster-wide default is 8MB (db/postgresql.conf:93) — right for eighty
# concurrent connections doing ordinary catalog queries, far too small for one
# buffer or dissolve over hundreds of thousands of geometries, which spills to
# pgsql_tmp long before it needs to. Dissolve wants it most: #694 turned off
# hash aggregation there (it holds every group's union state in memory at once
# and could OOM the shared db container), and the sorted aggregation that
# replaces it is precisely what work_mem governs. Turning off hashagg without
# raising work_mem trades an OOM risk for a guaranteed spill.
#
# WHICH BUDGET THIS COMES OUT OF. work_mem is allocated by the PostgreSQL
# backend serving the session, so the memory lands in the `db` service, capped
# by DB_MEM_LIMIT. That budget also holds shared_buffers (512MB),
# maintenance_work_mem (128MB), and up to max_connections = 80 other backends
# each entitled to their own work_mem. The worker's own WORKER_MEM_LIMIT is not
# what constrains this; the Python side of materialize lives there, the sort
# does not.
#
# work_mem is per OPERATION and per BACKEND, so one plan can allocate several
# multiples of it: at most 2 memory-hungry nodes for these shapes (dissolve is
# one Sort feeding a GroupAggregate; buffer and centroid have none; clip has a
# join), times 2 backends. The second factor is guaranteed rather than assumed —
# the override pins max_parallel_workers_per_gather to 1 for this transaction,
# because db/postgresql.conf only governs the bundled database and says nothing
# about an external one.
#
# THE CEILING IS AN OPERATOR SETTING, not a constant, because the two things
# that decide what is safe are both invisible from here:
#
#   - DB_MEM_LIMIT is a compose `mem_limit` and is never passed into this
#     container's environment, so this process cannot read the database's
#     ceiling. It is also tunable (docker-compose.prod.yml documents 1.5g) and
#     an external PostgreSQL may be smaller again.
#   - The divisor below bounds concurrent materializes inside ONE worker
#     process. It cannot bound a deployment running several worker services
#     against the `ingest` queue; each replica would claim the budget
#     independently. Bounding that needs a deployment-wide admission mechanism,
#     which is #695's open question.
#
# So the setting defaults low enough to be safe under both unknowns rather than
# optimal under neither: 64MB is 256MB worst case per worker replica, so even
# two replicas sit inside the default 2 GB alongside shared_buffers and
# maintenance_work_mem. An operator with a bigger database container and one
# worker can raise it; one with a smaller container or more replicas must lower
# it. config.py carries the arithmetic.
#
# Measured on a 60k-polygon grouped dissolve with enable_hashagg = off, the
# leader's sort wanted 96MB: at the 8MB default it spilled 70MB to disk, and at
# 128MB it stayed in memory. 64MB does not eliminate that spill, it shrinks it —
# the conservative default trades some of the win for a ceiling that cannot OOM
# the database on a deployment this process cannot measure.
#
# There is deliberately NO floor at the bundled 8MB default: that would be an
# assumption about the connected cluster this process cannot check. An external
# PostgreSQL tuned below 8MB would be RAISED by a clamp advertised as leaving it
# alone, and an operator who wants less than 8MB per materialize could not have
# it. ANALYSIS_MATERIALIZE_WORK_MEM_MB=0 is the honest way to say "do not touch
# work_mem" — it skips the SET LOCAL entirely.
#
# The division is done in kB, not MB, so the budget is never exceeded by
# rounding: a 1MB budget across 128 slots is 8kB each, not 1MB each. Below
# PostgreSQL's own 64kB minimum the budget cannot be honoured at all, so the
# override is skipped rather than silently overshot.
_MIN_WORK_MEM_KB = 64


async def _apply_materialize_work_mem(session: AsyncSession) -> None:
    """Raise work_mem for the CTAS transaction, unless the operator opted out.

    SET LOCAL, so it applies to this statement and reverts with the
    transaction — the other seventy-nine connections keep the cluster default.
    A global bump would not be safe in the same way. Lives here rather than
    inline in _materialize so the opt-out branch does not push that function
    past its complexity cap.
    """
    work_mem = _materialize_work_mem()
    if work_mem is None:
        return
    # Pin parallelism first, so the budget arithmetic is true by construction
    # rather than by assuming the server's configuration. work_mem is granted to
    # the leader AND to every parallel worker, so a server with
    # max_parallel_workers_per_gather above 1 — a customised bundled conf, or
    # any external PostgreSQL reached through DATABASE_URL_OVERRIDE, neither of
    # which db/postgresql.conf:73 constrains — would multiply the ceiling by a
    # number this process cannot see. One leader plus one worker is what the
    # budget in config.py is sized for.
    await session.execute(text("SET LOCAL max_parallel_workers_per_gather = 1"))
    await session.execute(text(f"SET LOCAL work_mem = '{work_mem}'"))


def _materialize_work_mem() -> str | None:
    """Per-slot work_mem for the CTAS, or None to leave the cluster's alone."""
    from app.core.config import settings

    budget_kb = settings.analysis_materialize_work_mem_mb * 1024
    if budget_kb <= 0:
        return None
    per_slot_kb = budget_kb // max(1, settings.worker_concurrency)
    if per_slot_kb < _MIN_WORK_MEM_KB:
        # Honouring the budget would need a work_mem below what PostgreSQL
        # accepts, so raising it at all would break the ceiling this setting
        # exists to hold. Leave the cluster's value alone instead.
        return None
    if per_slot_kb % 1024 == 0:
        return f"{per_slot_kb // 1024}MB"
    return f"{per_slot_kb}kB"


# fix(#694): post-CTAS backstop on the built output's on-disk size. The
# enqueue gates read the cached feature_count snapshot, which can be stale;
# this is the enforcement that can't be. Buffer is the motivating case: it
# is the only amplifying operation and vector datasets carry no byte quota.
MAX_OUTPUT_BYTES = 2 * 1024**3

# Served by the worker's :8001 /metrics endpoint (default registry).
# Analysis-only counter; generalize to all ingest job types when
# another type needs it.
ANALYSIS_JOBS = Counter(
    "geolens_analysis_jobs_total",
    "Materialize-analysis job outcomes",
    ["operation", "status"],
)


def _user_error_message(exc: Exception, *, registered: bool = False) -> str:
    """Map a failure onto text safe to return from ``GET /jobs/{job_id}``.

    SQLAlchemy stringifies DB errors with the full statement appended
    (``[SQL: CREATE TABLE "data"."…" AS …]``), which would hand internal
    schema and table names to the client (fix(#692)). Mirrors the sandbox's
    ``_handle_execution_error`` categories; raw text stays in server logs.
    """
    if isinstance(exc, SQLAlchemyError):
        exc_text = str(exc).lower()
        if "querycancelederror" in exc_text or "statement timeout" in exc_text:
            # fix(v1.6.0 audit D11): name the configured limit so the user
            # knows what budget was exceeded. fix(#1013 review): WHICH limit
            # depends on the phase — the CTAS transaction carries the
            # materialize budget, and the commit that ends it re-arms
            # registration with its own (#692). Naming the wrong one was
            # harmless while both were hardcoded at 300s/600s and only the
            # first was ever quoted; now that an operator can set them
            # independently, a registration timeout quoting the materialize
            # budget sends them to tune the setting that did not fire.
            budget = registration_timeout() if registered else materialize_timeout()
            return (
                f"The analysis exceeded its {budget} processing "
                "time limit. Try a smaller dataset or area."
            )
        if isinstance(exc, (DataError, InternalError)):
            return "The analysis failed while processing this data"
        # fix(#766): only the SQLSTATEs that mean "this column/type
        # combination can't do this operation": 42883 undefined_function
        # (e.g. no equality operator for `json` in a dissolve GROUP BY),
        # 42803 grouping_error, 42804 datatype_mismatch. Deliberately NOT
        # the whole class 42 — 42501 (privilege), 42P01 (missing table),
        # and 42601 (syntax) are server or configuration faults and must
        # keep reporting as the generic database error.
        if isinstance(exc, ProgrammingError) and str(
            getattr(exc.orig, "sqlstate", "") or ""
        ) in ("42883", "42803", "42804"):
            return (
                "A column in this dataset can't be used for this "
                "operation. Try a different column."
            )
        return "The analysis failed due to a database error"
    return str(exc)[:2000]


async def _fail_cancelled_job(
    working_session: AsyncSession,
    *,
    job_id: str,
    attempt_id: uuid.UUID,
    schema: str,
    out_table: str | None,
    operation: str,
) -> None:
    """Bookkeeping for a materialize cancelled mid-run, on a fresh session.

    Fenced on the attempt token FIRST: a successful fence proves the row was
    still 'running', so the final registration commit (which atomically
    persists the dataset and flips the row to 'complete') has not happened,
    and any committed output table is an unregistered orphan — safe to drop.
    If the fence misses, the job already reached a terminal state; the table
    is dropped only when the adoption probe proves no dataset registered it
    (fix(v1.6.0 audit B13)).
    """
    from app.core.db import async_session

    # fix(#700 review): the cancel can land while `working_session`'s open
    # transaction still holds the job-row lock (any flush since its last
    # commit, e.g. mid-commit). Release it first — time-bounded so a wedged
    # connection can't eat the whole shield window — or the fenced update
    # below waits on our own lock until the shield timeout and the row
    # strands in 'running' anyway.
    try:
        await asyncio.wait_for(working_session.rollback(), timeout=5)
    except Exception:  # broad: cleanup must reach the fenced update regardless
        logger.warning("analysis.cancel_rollback_failed", job_id=job_id)

    async with async_session() as session:
        if not await update_ingest_job_for_attempt(
            session,
            uuid.UUID(job_id),
            attempt_id,
            values={
                "status": "failed",
                "error_message": (
                    "The worker shut down before this analysis finished. Run it again."
                ),
                # fix(v1.6.0 audit B12): terminal writes must stamp
                # completed_at (the ingest tasks all do) — without it the
                # jobs UI renders '-' and retention ages on queue time.
                "completed_at": datetime.now(timezone.utc),
            },
        ):
            await session.rollback()
            # fix(v1.6.0 audit B13): mirror _mark_job_failed's fence-miss
            # cleanup — a swept row leaves an unregistered orphan that used
            # to leak permanently here. Probe for an adopting dataset row;
            # no row means the DROP is safe. If the probe itself errors,
            # prefer leaking the table to dropping a registered dataset's
            # storage.
            if out_table is not None:
                adopted = True
                try:
                    adopted = await _output_table_adopted(session, out_table)
                except Exception:  # broad: prefer leak over loss
                    logger.warning("analysis.adoption_probe_failed", job_id=job_id)
                    await session.rollback()
                if not adopted:
                    try:
                        await session.execute(
                            text(f'DROP TABLE IF EXISTS "{schema}"."{out_table}"')
                        )
                        await session.commit()
                    except Exception:  # broad: best-effort cleanup of the orphan
                        await session.rollback()
            return
        await session.commit()
        if out_table is not None:
            try:
                await session.execute(
                    text(f'DROP TABLE IF EXISTS "{schema}"."{out_table}"')
                )
                await session.commit()
            except Exception:  # broad: best-effort cleanup of the partial table
                await session.rollback()
    ANALYSIS_JOBS.labels(operation=operation, status="failed").inc()


async def _count_features_bounded(
    session: AsyncSession, table_ref: str, cap: int
) -> int:
    """Live row count, stopping at ``cap + 1`` so the probe stays bounded."""
    result = await session.execute(
        text(
            f"SELECT count(*) FROM (SELECT 1 FROM {table_ref} LIMIT :lim) AS _n"  # noqa: S608
        ).bindparams(lim=cap + 1)
    )
    return int(result.scalar_one())


async def _recheck_size_caps(
    session: AsyncSession,
    *,
    operation: str,
    src_ref: str,
    mask_table_ref: str | None,
) -> None:
    """Re-validate the enqueue-time size gates against the live tables.

    The queue wait can be long enough for a source or mask dataset to be
    re-uploaded past its cap (fix(#701 review)), and the post-CTAS output
    check is too late to protect the dissolve/mask union itself from OOM —
    so the bounded counts run again here, immediately before the SQL is
    built.
    """
    cap = MAX_SOURCE_FEATURES.get(operation)
    if cap is not None and await _count_features_bounded(session, src_ref, cap) > cap:
        raise ValueError(
            f"This dataset is too large for {operation} (the limit is "
            f"{cap:,} features). Filter it to a smaller dataset first."
        )
    if (
        mask_table_ref is not None
        and await _count_features_bounded(
            session, mask_table_ref, MAX_MASK_LAYER_FEATURES
        )
        > MAX_MASK_LAYER_FEATURES
    ):
        raise ValueError(
            "The mask layer has too many features to clip with (limit "
            f"{MAX_MASK_LAYER_FEATURES:,}). Choose a smaller mask layer or "
            "draw the mask on the map."
        )


async def _enforce_output_size(
    session: AsyncSession, schema: str, table_name: str, *, operation: str
) -> None:
    """Fail the build when the output relation is over MAX_OUTPUT_BYTES.

    ``pg_total_relation_size`` counts heap, TOAST, and indexes, so the
    post-rewrite call measures what the registered dataset will actually
    occupy. Resolved via pg_class with the ``:schema`` bind rather than a
    ``regclass`` cast (fix(#701 review)): the tenant statement hook only
    recognizes schema references in SQL text or schema-named binds, and it
    masks string literals — a schema hidden inside a generic bind would
    skip the tenant role setup and fail the lookup in multi-tenant.
    """
    result = await session.execute(
        text(
            "SELECT pg_total_relation_size(c.oid) FROM pg_catalog.pg_class c"
            " JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = :schema AND c.relname = :table_name"
        ).bindparams(schema=schema, table_name=table_name)
    )
    size_bytes = result.scalar_one_or_none()
    if size_bytes is not None and size_bytes > MAX_OUTPUT_BYTES:
        # fix(v1.6.0 audit D11): only buffer has a distance to reduce —
        # telling a clip/centroid/dissolve user to shrink a buffer they
        # never set is a dead end.
        advice = (
            "Reduce the buffer distance or run it on a smaller dataset."
            if operation == "buffer"
            else "Run it on a smaller dataset or area."
        )
        raise ValueError(
            f"The analysis output exceeded the "
            f"{MAX_OUTPUT_BYTES // 1024**3} GB size limit. {advice}"
        )


async def _complete_job_for_attempt(
    session: AsyncSession,
    *,
    job_id: str,
    attempt_id: uuid.UUID,
    dataset_id: uuid.UUID,
    schema: str,
    out_table: str,
    operation: str,
) -> None:
    """Commit registration together with the fenced terminal 'complete' write.

    fix(#786): the terminal write is fenced on the attempt token, like the
    claim and ``_fail_cancelled_job`` — a plain ``job.status = "complete"``
    would overwrite a row the stale-job sweep already failed (a stalled
    heartbeat expires the lease), resurrecting failed → complete and handing
    the user a dataset for a job they were told failed. The fence shares the
    registration transaction, so a miss rolls the Dataset row back with it.
    """
    if await update_ingest_job_for_attempt(
        session,
        uuid.UUID(job_id),
        attempt_id,
        values={
            "status": "complete",
            "dataset_id": dataset_id,
            # fix(v1.6.0 audit B12): stamp completion time like ingest does.
            "completed_at": datetime.now(timezone.utc),
        },
    ):
        await session.commit()
        ANALYSIS_JOBS.labels(operation=operation, status="complete").inc()
        return
    await session.rollback()
    logger.warning("analysis.complete_write_superseded", job_id=job_id)
    # The build commit made the output table durable, and the rollback above
    # discarded this attempt's registration. fix(v1.6.0 audit B13): mirror
    # _mark_job_failed's fence-miss cleanup — gate the drop on the adoption
    # probe so a dataset row committed by any other actor keeps its storage,
    # and prefer leaking the table over dropping one the probe can't clear.
    adopted = True
    try:
        adopted = await _output_table_adopted(session, out_table)
    except Exception:  # broad: prefer leak over loss
        logger.warning("analysis.adoption_probe_failed", job_id=job_id)
        await session.rollback()
    if not adopted:
        try:
            await session.execute(
                text(f'DROP TABLE IF EXISTS "{schema}"."{out_table}"')
            )
            await session.commit()
        except Exception:  # broad: best-effort cleanup of the orphaned output
            await session.rollback()


async def _output_table_adopted(session: AsyncSession, out_table: str) -> bool:
    """Whether a dataset row has adopted ``out_table`` (fix(v1.6.0 audit B13)).

    Index-backed: ``catalog.datasets`` carries two partial unique indexes on
    ``table_name`` (global and per-tenant). Tenant-scoped in multi_tenant —
    an unscoped probe could match another tenant's dataset of the same name
    and skip a legitimate drop (the IN-01 pattern from the ingest discover
    query). With no tenant context in multi_tenant, report adopted: the
    caller then prefers leaking a table over dropping one it can't attribute.
    """
    tid = current_tenant_var.get() if is_multi_tenant() else None
    if is_multi_tenant():
        if tid is None:
            return True
        stmt = text(
            "SELECT 1 FROM catalog.datasets"
            " WHERE table_name = :out AND tenant_id = :tenant_id"
        ).bindparams(out=out_table, tenant_id=tid)
    else:
        stmt = text(
            "SELECT 1 FROM catalog.datasets WHERE table_name = :out"
        ).bindparams(out=out_table)
    return (await session.execute(stmt)).first() is not None


async def _mark_job_failed(
    session: AsyncSession,
    *,
    job_id: str,
    attempt_id: uuid.UUID,
    exc: Exception,
    schema: str,
    out_table: str | None,
    operation: str,
    registered: bool = False,
) -> None:
    """Roll back, record the failure, and drop this job's own partial table.

    fix(#786): fenced on the attempt token FIRST, mirroring
    ``_fail_cancelled_job`` — the previous plain ORM write could overwrite a
    terminal state some other actor already set (the stale-job sweep failing
    the row after a stalled lease, or a final commit that reached the server
    before the connection dropped, leaving the row 'complete'). A successful
    fence proves the row was still 'running', so the registration commit has
    not happened and any committed output table is an unregistered orphan —
    safe to drop. If the fence misses, the row is left alone; the table is
    dropped only when the adoption probe proves no dataset registered it
    (fix(v1.6.0 audit B13)).
    """
    await session.rollback()
    if not await update_ingest_job_for_attempt(
        session,
        uuid.UUID(job_id),
        attempt_id,
        values={
            "status": "failed",
            # Sanitized (fix(#692)): raw DB errors embed the generated SQL.
            "error_message": _user_error_message(exc, registered=registered),
            # fix(v1.6.0 audit B12): stamp completion time like ingest does.
            "completed_at": datetime.now(timezone.utc),
        },
    ):
        await session.rollback()
        logger.warning("analysis.failed_write_superseded", job_id=job_id)
        # fix(v1.6.0 audit B13): a fence miss means some other actor set a
        # terminal state, but only a completed job has adopted the table —
        # a swept row leaves an unregistered orphan that used to leak
        # permanently. Probe for an adopting dataset row; no row means the
        # DROP is safe. Failure direction stays safe: if the probe itself
        # errors, prefer leaking the table to dropping a registered
        # dataset's storage.
        if out_table is not None:
            adopted = True
            try:
                adopted = await _output_table_adopted(session, out_table)
            except Exception:  # broad: prefer leak over loss
                logger.warning("analysis.adoption_probe_failed", job_id=job_id)
                await session.rollback()
            if not adopted:
                try:
                    await session.execute(
                        text(f'DROP TABLE IF EXISTS "{schema}"."{out_table}"')
                    )
                    await session.commit()
                except Exception:  # broad: best-effort cleanup of the orphan
                    await session.rollback()
        return
    await session.commit()
    if out_table is not None:
        try:
            await session.execute(
                text(f'DROP TABLE IF EXISTS "{schema}"."{out_table}"')
            )
            await session.commit()
        except Exception:  # broad: best-effort cleanup of the partial table
            await session.rollback()
    ANALYSIS_JOBS.labels(operation=operation, status="failed").inc()


async def _list_carry_columns(
    session: AsyncSession, schema: str, table_name: str
) -> list[str]:
    """Attribute columns to carry into 1:1 op output (skip system/geom cols).

    fix(#763): every name is carried — GDAL launders only case/`-`/`#`, so
    ingested tables legitimately hold columns like ``Área`` or ``2020_pop``;
    filtering to identifier-shaped names silently dropped them from every
    analysis output. Rendering quotes via ``_sql_quote_ident``, whose
    colon escape also keeps Socrata-style ``:id`` columns from being parsed
    as bind parameters by ``text()``.
    """
    rows = await session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table_name "
            "AND column_name NOT IN ('gid', 'geom', 'geom_4326') "
            "ORDER BY ordinal_position"
        ).bindparams(schema=schema, table_name=table_name)
    )
    return [row[0] for row in rows]


def _wrap_not_empty(select_sql: str) -> str:
    """Exclude NULL/EMPTY-geometry rows inside the CTAS itself.

    fix(#786): ``_enforce_output_size`` probes ``pg_total_relation_size``
    right after the CTAS, and the post-CTAS DELETE cannot shrink what it
    measures — dead tuples keep their pages until a rewrite. Rows the
    cleanup removes therefore counted toward the output ceiling for
    buffer/centroid/dissolve and the drawn-mask clip, failing analyses
    whose real output is small. The clip-by-layer branch has filtered
    in-CTAS since fix(#719 review); this extends the same rule to the
    other shapes. ``OFFSET 0`` fences subquery pull-up so the geometry
    expression (``ST_Buffer`` at worst) is evaluated once per row rather
    than re-evaluated inside the outer WHERE.
    """
    return (
        f"SELECT * FROM ({select_sql} OFFSET 0) AS _rows"
        f" WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom)"
    )


def _build_materialize_select(
    src_ref: str,
    operation: str,
    *,
    distance_meters: float | None,
    mask: dict[str, Any] | None,
    by_field: str | None,
    carry_cols: list[str],
    mask_table_ref: str | None = None,
) -> str:
    """Render the SELECT that produces the output table's rows."""
    if operation == "dissolve":
        # ST_MakeValid: one invalid ring would abort the whole union.
        # ST_CollectionExtract: a union over mixed geometry types returns a
        # GEOMETRYCOLLECTION, which the MVT tile path can't render — keep only
        # the highest-dimension components so the output stays typed.
        union_expr = "ST_Multi(ST_CollectionExtract(ST_Union(ST_MakeValid(geom_4326))))"
        if by_field:
            # fix(#836): quote via _sql_quote_ident like every other identifier
            # site here — _SAFE_IDENT already guards by_field, but a lone
            # inline-quoting divergence is where the next escaping bug hides.
            col = _sql_quote_ident(by_field)
            return _wrap_not_empty(
                f"SELECT (row_number() OVER ())::integer AS gid, {col}, "
                f"COUNT(*)::integer AS source_count, "
                f"{union_expr} AS geom "
                f"FROM {src_ref} GROUP BY {col}"
            )
        return _wrap_not_empty(
            f"SELECT 1 AS gid, COUNT(*)::integer AS source_count, "
            f"{union_expr} AS geom FROM {src_ref}"
        )
    if operation == "clip" and mask_table_ref is not None:
        # fix(#719): the same subdivided-mask join the preview uses. This used
        # to render a single whole-layer ST_Union instead, so a clip whose
        # preview came back in under a second could exhaust the 300s CTAS
        # budget on "Create dataset" (see render_clip_layer_join for the
        # measurements).
        #
        # The empty-result filter is applied HERE, not left to the post-CTAS
        # DELETE (fix(#719 review)). The row filter admits a source row on a
        # bounding-box overlap, so a wide or concave mask lets through rows
        # whose geometries never actually intersect; their lateral yields
        # geom_out = NULL. _enforce_output_size runs against the CTAS BEFORE
        # that DELETE, so those rows could fail an analysis as oversized when
        # the dataset it would have saved is small. Clip has no source-feature
        # cap, so nothing else bounds how many of them there are.
        cte, lateral, where = render_clip_layer_join(mask_table_ref, src="_src")
        cols = "".join(f"_src.{_sql_quote_ident(c)}, " for c in carry_cols)
        return (
            f"{cte} SELECT _src.gid, {cols}_op.geom_out AS geom"
            f" FROM {src_ref} AS _src"
            f" CROSS JOIN LATERAL {lateral} AS _op"
            f"{where} AND {NOT_EMPTY_PREDICATE}"
        )
    expr, where = render_geometry_expr(
        operation,
        distance_meters=distance_meters,
        mask=mask,
    )
    cols = "".join(f"{_sql_quote_ident(c)}, " for c in carry_cols)
    return _wrap_not_empty(f"SELECT gid, {cols}{expr} AS geom FROM {src_ref}{where}")


async def _materialize(
    *,
    job_id: str,
    dataset_id: str,
    user_id: str,
    operation: str,
    title: str,
    distance_meters: float | None = None,
    mask: dict[str, Any] | None = None,
    mask_dataset_id: str | None = None,
    by_field: str | None = None,
) -> None:
    """Core materialize logic; separated from the task wrapper for tests."""
    from app.core.db import async_session
    from app.platform.extensions import get_processing_port
    from app.platform.jobs.models import IngestJob
    from app.processing.ingest.metadata import add_4326_column
    from app.processing.ingest.schemas import RegisterRequest
    from app.processing.ingest.service import (
        generate_table_name,
        register_existing_table,
    )

    async with async_session() as session:
        job = await session.get(IngestJob, uuid.UUID(job_id))
        if job is None:
            logger.warning("analysis.job_not_found", job_id=job_id)
            return
        # Fenced claim (fix(#692), the ingest_file pattern): pending → running
        # succeeds at most once per attempt token, and stamps
        # started_at/heartbeat_at — the liveness signals the stale-job sweep
        # and the lease below depend on (fix(#682 review): statement_timeout
        # bounds each STATEMENT, not the task, so a large materialize can
        # legitimately run long and only the lease keeps it out of the sweep).
        # Without the claim this worker would act on rows some other actor
        # already moved to a terminal state — the pending-sweeper failing a
        # backlogged job after an hour, or the defer orphan-guard failing the
        # row after the queue INSERT committed — and resurrect them: the
        # per-user cap admits a second CTAS, and a dataset appears for a job
        # the user was told failed.
        #
        # The row's own attempt_id is the token (column-defaulted at
        # creation; retry=0, so there is no second delivery to fence against).
        # Rows predating that default are adopted atomically.
        attempt_id = job.attempt_id or await resolve_ingest_job_attempt(job.id, None)
        if attempt_id is None or not await claim_ingest_job_attempt(
            session, job.id, attempt_id
        ):
            await session.rollback()
            logger.warning("analysis.attempt_not_claimed", job_id=job_id)
            return
        # current_step only, no numeric progress: the operation is a single
        # CTAS, so there is no intra-statement telemetry to report and a bar
        # parked at 10% for five minutes reads as "stuck" rather than "busy".
        job.current_step = "analyzing"
        await session.commit()

        _schema = tenant_data_schema(
            current_tenant_var.get() if is_multi_tenant() else None
        )
        out_table: str | None = None
        # Only drop the output table on failure if THIS job created it: when
        # CREATE TABLE itself fails because a concurrent job won the same
        # generated name, an unconditional cleanup would destroy the winner's
        # table while its dataset registration stays live.
        out_table_created = False
        # fix(#1013 review): flipped when the CTAS transaction commits and
        # registration re-arms its own statement_timeout, so a failure after
        # that point quotes the budget that actually fired.
        registration_started = False
        # Created inside the try so the finally below always reaps it: a
        # heartbeat left running after an exception here would renew a lease
        # for a job nobody is executing, and the sweep can never fail a row
        # with a fresh lease (fix(#692)).
        heartbeat: asyncio.Task[None] | None = None
        try:
            # Renews on its own session, so it never contends with the work
            # below, and returns by itself once the row leaves 'running'.
            heartbeat = asyncio.create_task(
                maintain_ingest_job_heartbeat(job.id, attempt_id)
            )
            port = get_processing_port()
            Dataset = port.get_dataset_orm_class()
            result = await session.execute(
                select(Dataset).where(Dataset.id == uuid.UUID(dataset_id))
            )
            src = result.scalar_one_or_none()
            if src is None or not src.table_name:
                raise ValueError("Source dataset not found")
            if not _SAFE_TABLE.match(src.table_name):
                raise ValueError("Invalid source table name")
            if by_field is not None and not _SAFE_IDENT.match(by_field):
                raise ValueError("Invalid dissolve column name")
            src_ref = f'"{_schema}"."{src.table_name}"'

            # Layer-sourced clip mask: re-resolve the table name at run time
            # (access was checked at enqueue by the router, same trust model
            # as the source dataset).
            mask_table_ref: str | None = None
            if mask_dataset_id is not None:
                mask_result = await session.execute(
                    select(Dataset).where(Dataset.id == uuid.UUID(mask_dataset_id))
                )
                mask_ds = mask_result.scalar_one_or_none()
                if mask_ds is None or not mask_ds.table_name:
                    raise ValueError("Mask dataset not found")
                if not _SAFE_TABLE.match(mask_ds.table_name):
                    raise ValueError("Invalid mask table name")
                mask_table_ref = f'"{_schema}"."{mask_ds.table_name}"'

            await _recheck_size_caps(
                session,
                operation=operation,
                src_ref=src_ref,
                mask_table_ref=mask_table_ref,
            )

            out_table, collision_warning = await generate_table_name(title, session)
            if collision_warning:
                # fix(#786): persisted like the upload path (tasks_vector) —
                # the job-status endpoint surfaces
                # user_metadata['collision_warning'] as warning_message, so
                # discarding it here silently landed an analysis output in
                # e.g. parcels_buffered_3 with no indication to the user.
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "collision_warning": collision_warning,
                }
            # INVARIANT: from the user_metadata/current_step assignments above
            # to the commit after ANALYZE, every statement must stay text() —
            # SQLAlchemy autoflushes only for ORM queries, so the dirty job
            # row is flushed (and its row lock taken) only microseconds inside
            # that commit. A single ORM select() added in this stretch would
            # autoflush the dirty row and hold the job-row lock across the
            # CTAS, blocking renew_ingest_job_heartbeat (separate session,
            # same row) for the entire build.
            out_ref = f'"{_schema}"."{out_table}"'

            carry_cols = (
                await _list_carry_columns(session, _schema, src.table_name)
                if operation != "dissolve"
                else []
            )
            select_sql = _build_materialize_select(
                src_ref,
                operation,
                distance_meters=distance_meters,
                mask=mask,
                by_field=by_field,
                carry_cols=carry_cols,
                mask_table_ref=mask_table_ref,
            )
            await session.execute(
                text(f"SET LOCAL statement_timeout = '{materialize_timeout()}'")
            )
            await _apply_materialize_work_mem(session)
            if operation == "dissolve":
                # fix(#694): hash aggregation holds every group's union state
                # in memory at once, so a grouped dissolve over enough
                # polygons can OOM-kill the shared db container. Sorted
                # aggregation bounds memory to one group at a time. The
                # enqueue-time feature cap is the first line of defense;
                # this is the second.
                await session.execute(text("SET LOCAL enable_hashagg = off"))
            await session.execute(text(f"CREATE TABLE {out_ref} AS {select_sql}"))
            out_table_created = True
            # Early exit only — a table already over the ceiling must not
            # hold the single worker slot through the rewrite phases. The
            # authoritative check runs after add_4326_column below.
            await _enforce_output_size(session, _schema, out_table, operation=operation)
            # Rows with nothing to show are excluded inside the CTAS for
            # EVERY shape (fix(#786), extending fix(#719 review)'s clip
            # rule via _wrap_not_empty): buffer/centroid map NULL source
            # geometries to NULL, dissolve unions an all-NULL group to NULL,
            # and boundary-grazing clips survive ST_Intersects but extract to
            # EMPTY (see analysis_sql.render_geometry_expr). The preview
            # filters the same rows in SQL (fix(#680 review)) — the saved
            # dataset must agree with the preview the user approved. This
            # DELETE stays as the backstop enforcing that invariant should a
            # future query shape miss the in-CTAS filter.
            await session.execute(
                text(f"DELETE FROM {out_ref} WHERE geom IS NULL OR ST_IsEmpty(geom)")
            )
            has_features = await session.scalar(
                text(f"SELECT EXISTS (SELECT 1 FROM {out_ref})")
            )
            if not has_features:
                # e.g. a clip matching nothing, or dissolving an empty
                # dataset (whose no-GROUP-BY aggregate still yields one
                # NULL-geometry row) — fail loud instead of registering junk.
                raise ValueError("Analysis produced no features to save")
            # CTAS yields an untyped geometry column (typmod srid=0), which
            # metadata extraction reports as SRID 0 — stamp the 4326 typmod.
            await session.execute(
                text(
                    f"ALTER TABLE {out_ref} ALTER COLUMN geom "
                    f"TYPE geometry(Geometry, 4326) USING ST_SetSRID(geom, 4326)"
                )
            )
            await session.execute(text(f"ALTER TABLE {out_ref} ADD PRIMARY KEY (gid)"))
            await add_4326_column(session, out_table, 4326, schema=_schema)
            # fix(#701 review): the 4326 rewrite roughly doubles the geometry
            # payload, rewrites every row, and adds the GIST index — the
            # post-CTAS probe undercounts the final footprint by a multiple,
            # so the ceiling is enforced here, on the finished relation.
            await _enforce_output_size(session, _schema, out_table, operation=operation)
            # In-transaction ANALYZE (fix(#692)): the table only becomes
            # visible to autovacuum at the commit below, and the first tile
            # queries land before its pass — without statistics the planner
            # has no geometry selectivity for `&&` against the fresh GIST
            # index and can seq-scan a large output.
            await session.execute(text(f"ANALYZE {out_ref}"))
            job.current_step = "registering"
            await session.commit()
            registration_started = True

            # The commit above ended the transaction and the SET LOCAL with
            # it — give registration its own budget (fix(#692)). Set here
            # rather than inside register_existing_table, which is shared
            # with the upload path.
            await session.execute(
                text(f"SET LOCAL statement_timeout = '{registration_timeout()}'")
            )
            # Identity is a structural Protocol; registration only reads .id.
            requester = SimpleNamespace(id=uuid.UUID(user_id))
            dataset = await register_existing_table(
                session,
                RegisterRequest(
                    table_name=out_table, title=title, visibility="private"
                ),
                requester,
            )
            # feat(#765): provenance before the completing commit, so a
            # registered output can never be visible without its lineage.
            await apply_analysis_provenance(
                session,
                new_record_id=dataset.record_id,
                source_dataset_id=dataset_id,
                user_id=user_id,
                operation=operation,
                params={
                    "distance_meters": distance_meters,
                    "by_field": by_field,
                    "mask_source": (
                        ("layer" if mask_dataset_id else "drawn")
                        if operation == "clip"
                        else None
                    ),
                    "mask_dataset_id": mask_dataset_id,
                },
            )
            await _complete_job_for_attempt(
                session,
                job_id=job_id,
                attempt_id=attempt_id,
                dataset_id=dataset.id,
                schema=_schema,
                out_table=out_table,
                operation=operation,
            )
        except asyncio.CancelledError:
            # Graceful worker shutdown cancels this task after the drain
            # window; `except Exception` cannot catch it, and retry=0 means no
            # redelivery — without this branch the row would strand in
            # 'running', holding the user's one analysis slot, until the
            # 60-minute sweep (fix(#692)). Bookkeeping runs on a fresh session
            # (this one may be mid-statement) and is shielded so the
            # cancellation doesn't also cancel it; then re-raise so the queue
            # records the abort.
            try:
                await asyncio.shield(
                    asyncio.wait_for(
                        _fail_cancelled_job(
                            session,
                            job_id=job_id,
                            attempt_id=attempt_id,
                            schema=_schema,
                            out_table=out_table if out_table_created else None,
                            operation=operation,
                        ),
                        timeout=15,
                    )
                )
            except BaseException:  # broad: best-effort cleanup during shutdown; the raise below preserves the abort
                logger.warning("analysis.cancel_cleanup_failed", job_id=job_id)
            raise
        except Exception as exc:  # broad: any failure must mark the job failed, not raise into the queue
            logger.warning(
                "analysis.materialize_failed",
                job_id=job_id,
                error=str(exc),
                exc_info=True,
            )
            await _mark_job_failed(
                session,
                job_id=job_id,
                attempt_id=attempt_id,
                exc=exc,
                schema=_schema,
                out_table=out_table if out_table_created else None,
                operation=operation,
                # True only once the CTAS transaction has committed, which is
                # exactly when the registration budget is the one in force.
                registered=registration_started,
            )
        finally:
            # The row has left 'running' by now, so the loop would exit on its
            # own at the next renewal — stop (cancel + await, the ingest
            # convention) so the task neither outlives the work by a heartbeat
            # interval nor leaks a pending task through worker shutdown.
            await stop_ingest_job_heartbeat(heartbeat)


@task_app.task(
    queue="ingest", retry=0, aliases=["app.analysis.tasks.materialize_analysis"]
)
@tenant_task
async def materialize_analysis(
    job_id: str,
    dataset_id: str,
    user_id: str,
    operation: str,
    title: str,
    distance_meters: float | None = None,
    mask: dict[str, Any] | None = None,
    mask_dataset_id: str | None = None,
    by_field: str | None = None,
) -> None:
    """Procrastinate entry point for async analysis materialization."""
    await _materialize(
        job_id=job_id,
        dataset_id=dataset_id,
        user_id=user_id,
        operation=operation,
        title=title,
        distance_meters=distance_meters,
        mask=mask,
        mask_dataset_id=mask_dataset_id,
        by_field=by_field,
    )
