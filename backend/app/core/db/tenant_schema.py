"""Per-tenant data-schema naming and least-privilege lifecycle calls.

Dynamic tenant DDL is owned by the migration-installed SECURITY DEFINER
functions in ``catalog``; API/worker processes call those and never need
CREATE SCHEMA or CREATEROLE themselves.

single_tenant: hard no-op, touches no SQL, shared ``data`` schema and global
``geolens_reader`` unchanged. multi_tenant: idempotent and transaction-bound,
so callers can provision in the same transaction that inserts
``catalog.tenants``. Tenant id is always a validated UUID string, never
f-string interpolated from user input.

``apply_tenant_data_schema_from_engine(tenant_id)`` is for background jobs on
an already-committed tenant; tenant creation must instead pass its request
session to ``provision_tenant_data_schema`` so row + substrate commit or
roll back together. ``bootstrap()`` does not call this per-tenant — schemas
are created on demand at tenant-provision time.

Naming: schema ``data_t_{id}``, reader role ``geolens_reader_t_{id}``, writer
role ``geolens_writer_t_{id}``, with ``id`` = tenant_id, hyphens→underscores.
"""

from __future__ import annotations

import re

import structlog
from sqlalchemy import text

logger = structlog.stdlib.get_logger(__name__)

#: Validated tenant_id pattern: UUID hex chars + hyphens only.
_TENANT_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def tenant_data_schema(tenant_id: str | None) -> str:
    """Return the data schema name for a tenant.

    single_tenant: ``"data"`` (the shared schema); ``tenant_id`` may be
    ``None``. multi_tenant: requires a tenant id (fails closed, no fallback to
    shared storage) and returns ``data_t_{id}``. IN-02: normalized to
    lowercase first, since quoted identifiers are case-sensitive and the
    provisioned schema is always lowercase.

    Raises ``ValueError`` if ``tenant_id`` is not a valid UUID in
    multi_tenant mode.
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        return "data"
    if tenant_id is None:
        raise ValueError(
            "tenant_data_schema: tenant_id is required in multi_tenant mode"
        )

    normalized = tenant_id.lower()
    if not _TENANT_ID_RE.match(normalized):
        raise ValueError(f"tenant_data_schema: invalid tenant_id: {tenant_id!r}")

    # All identifiers derive from the validated UUID — string formatting is safe.
    return f"data_t_{normalized.replace('-', '_')}"


def tenant_reader_role(tenant_id: str | None) -> str:
    """Return the per-tenant reader role name.

    single_tenant: ``"geolens_reader"``, ``tenant_id`` may be ``None``.
    multi_tenant: requires a valid UUID tenant id (fails closed) and returns
    ``geolens_reader_t_{id}``; IN-02: normalized to lowercase first so a
    mixed-case UUID can't diverge from the provisioned role name.
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        return "geolens_reader"
    if tenant_id is None:
        raise ValueError(
            "tenant_reader_role: tenant_id is required in multi_tenant mode"
        )

    normalized = tenant_id.lower()
    if not _TENANT_ID_RE.match(normalized):
        raise ValueError(f"tenant_reader_role: invalid tenant_id: {tenant_id!r}")

    # All identifiers derive from the validated UUID — string formatting is safe.
    return f"geolens_reader_t_{normalized.replace('-', '_')}"


def tenant_writer_role(tenant_id: str | None) -> str:
    """Return the SET-only per-tenant writer target role.

    single_tenant deployments keep using the configured database login, so
    ``"geolens_writer"`` is an inert naming fallback only. multi_tenant
    callers must supply a UUID.
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        return "geolens_writer"
    if tenant_id is None:
        raise ValueError(
            "tenant_writer_role: tenant_id is required in multi_tenant mode"
        )

    normalized = _validated_tenant_id(tenant_id, operation="tenant_writer_role")
    return f"geolens_writer_t_{normalized.replace('-', '_')}"


def _validated_tenant_id(tenant_id: str, *, operation: str) -> str:
    """Return a normalized tenant UUID string before it reaches SQL."""
    normalized = tenant_id.lower()
    if not _TENANT_ID_RE.fullmatch(normalized):
        raise ValueError(f"{operation}: invalid tenant_id: {tenant_id!r}")
    return normalized


async def provision_tenant_data_schema(conn, tenant_id: str) -> None:
    """Provision a tenant through the migration-owned database boundary.

    ``conn`` (``AsyncConnection`` or ``AsyncSession``, not AUTOCOMMIT)
    participates in the caller's transaction, required for Cloud
    create/signup atomicity. PostgreSQL does identifier construction,
    locking, role validation, and grants inside the SECURITY DEFINER
    function. Raises ``ValueError`` if ``tenant_id`` is not a UUID.
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        logger.debug("provision_tenant_data_schema: single_tenant — skipping (no-op)")
        return

    normalized = _validated_tenant_id(
        tenant_id, operation="provision_tenant_data_schema"
    )
    statement = text(
        "SELECT catalog.provision_tenant_data_schema(CAST(:tenant_id AS uuid))"
    ).bindparams(tenant_id=normalized)
    await conn.execute(statement)
    logger.info(
        "provision_tenant_data_schema: provisioned",
        schema=f"data_t_{normalized.replace('-', '_')}",
        role=f"geolens_reader_t_{normalized.replace('-', '_')}",
    )


async def apply_tenant_data_schema(conn, tenant_id: str) -> None:
    """Backward-compatible name for ``provision_tenant_data_schema``."""
    await provision_tenant_data_schema(conn, tenant_id)


async def deprovision_tenant_data_schema(conn, tenant_id: str) -> None:
    """Remove an already-deleted tenant through the guarded DB boundary.

    The database function refuses to run while ``catalog.tenants`` still has
    the tenant row.  Callers should delete that row in the same transaction or
    commit the control-plane deletion before invoking this helper.
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        logger.debug("deprovision_tenant_data_schema: single_tenant — skipping (no-op)")
        return

    normalized = _validated_tenant_id(
        tenant_id, operation="deprovision_tenant_data_schema"
    )
    statement = text(
        "SELECT catalog.deprovision_tenant_data_schema(CAST(:tenant_id AS uuid))"
    ).bindparams(tenant_id=normalized)
    await conn.execute(statement)
    logger.info("deprovision_tenant_data_schema: complete", tenant_id=normalized)


async def apply_tenant_data_schema_from_engine(tenant_id: str) -> None:
    """Provision an already-committed tenant using the global engine.

    single_tenant: delegates to ``apply_tenant_data_schema()``, an immediate
    no-op. The SECURITY DEFINER function runs in one ordinary transaction;
    tenant creation paths must instead pass their existing session directly.
    """
    # fix(#909): façade import — see the note in rls.py.
    from app.core.db import engine

    async with engine.begin() as conn:
        await apply_tenant_data_schema(conn, tenant_id)


def tenant_shard_id(tenant_id: str | None) -> str | None:
    """Look up the shard routing key for a tenant (Phase-1214 routing primitive).

    Reserved for Phase 1214's promote/rebalance; intentionally NOT wired into
    the Plans 02/03 read/write hot paths, which use ``tenant_data_schema`` /
    ``tenant_reader_role`` directly since there is nothing to route at one
    shard.

    single_tenant or ``tenant_id is None``: returns ``None``. multi_tenant:
    queries ``catalog.tenants.shard_id``, falling back to ``'shard-0'`` if the
    column is NULL or the tenant row is absent.
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant() or tenant_id is None:
        return None

    import asyncio

    from sqlalchemy import text as sa_text
    from sqlalchemy.pool import NullPool

    # fix(#909): façade import — see the note in rls.py.
    from app.core.db import engine as _engine

    async def _fetch() -> str:
        from sqlalchemy.ext.asyncio import create_async_engine

        # NullPool: don't borrow a connection from the shared pool for this
        # infrequent lookup.
        url = _engine.url
        tmp_engine = create_async_engine(str(url), poolclass=NullPool)
        try:
            async with tmp_engine.connect() as conn:
                row = await conn.execute(
                    sa_text(
                        "SELECT shard_id FROM catalog.tenants WHERE id = :tid"
                    ).bindparams(tid=tenant_id)
                )
                result = row.fetchone()
                if result is None or result[0] is None:
                    return "shard-0"
                return result[0]
        finally:
            await tmp_engine.dispose()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already in an async context: run the fetch on a separate thread
            # since asyncio.run() cannot nest inside a running loop.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, _fetch())
                return future.result()
        else:
            return asyncio.run(_fetch())
    except Exception:  # broad: shard routing lookup can fail with DB/asyncio/executor errors; always fall back to shard-0 so tile reads degrade gracefully
        logger.warning(
            "tenant_shard_id: lookup failed, returning default shard",
            tenant_id=tenant_id,
            exc_info=True,  # WR-01: surface stack trace so failures are diagnosable
        )
        return "shard-0"


async def schema_exists(session, schema: str) -> bool:
    """True when *schema* exists in the current database.

    fix(#435): `42P01` (undefined_table) is ambiguous — Postgres returns it
    both for a missing schema and for a raster dataset's synthetic table in a
    schema that exists. Read-side callers degrading `42P01` to an empty page
    must probe first, or a never-provisioned (or restore-lost) tenant schema
    is silently reported as a zero-row dataset.

    Error path only: costs a catalog lookup, and must follow a rollback since
    the failed statement aborted the transaction.
    """
    result = await session.execute(
        text("SELECT to_regnamespace(:schema) IS NOT NULL"), {"schema": schema}
    )
    return bool(result.scalar_one())
