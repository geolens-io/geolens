"""Per-tenant data-schema naming and least-privilege lifecycle calls.

Dynamic tenant DDL is owned by the migration-installed SECURITY DEFINER
functions in ``catalog``.  API and worker processes call those functions; they
never need CREATE SCHEMA or CREATEROLE themselves.

Design invariants
-----------------
- **single_tenant**: hard no-op — returns immediately, touches NO SQL.
  The shared ``data`` schema + global ``geolens_reader`` stay unchanged.
- **multi_tenant**: idempotent and transaction-bound — callers can provision in
  the same transaction that inserts ``catalog.tenants``.
- Tenant id is ALWAYS passed as a validated UUID string (never f-string
  interpolated directly from user input).

Call from tenant provisioning
-----------------------------
``apply_tenant_data_schema_from_engine(tenant_id)`` is retained for background
jobs operating on an already-committed tenant.  Tenant creation must pass its
request session to ``provision_tenant_data_schema`` so row + substrate commit or
roll back together.
At boot, ``bootstrap()`` does NOT call this per-tenant — schemas are
created on demand at tenant-provision time.

Schema naming convention: ``data_t_{tenant_id with hyphens→underscores}``
Role naming convention:   ``geolens_reader_t_{tenant_id with hyphens→underscores}``
Writer naming convention: ``geolens_writer_t_{tenant_id with hyphens→underscores}``
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

    In ``single_tenant``: returns ``"data"`` (the global shared data schema —
    byte-identical to pre-1209 behavior). Multi-tenant callers must supply a
    tenant id; missing context fails closed instead of falling back to shared
    storage.

    In ``multi_tenant`` with a non-None tenant_id: returns
    ``"data_t_{tenant_id with hyphens replaced by underscores}"``.

    IN-02 (Phase 1209-CR): ``tenant_id`` is normalized to lowercase before
    building the schema name so mixed-case UUIDs cannot produce
    ``data_t_ABCDEF…`` (case-sensitive in quoted identifiers) while the
    provisioned schema is ``data_t_abcdef…``.

    Parameters
    ----------
    tenant_id:
        UUID string for the tenant. ``None`` is accepted only in single-tenant
        mode.

    Raises
    ------
    ValueError
        If ``tenant_id`` is not a valid UUID string in ``multi_tenant`` mode.
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

    In ``single_tenant``: returns ``"geolens_reader"`` (the global reader
    role). Missing tenant context fails closed in multi-tenant mode.

    In ``multi_tenant`` with a non-None tenant_id: returns
    ``"geolens_reader_t_{tenant_id with hyphens replaced by underscores}"``.

    IN-02 (Phase 1209-CR): ``tenant_id`` is normalized to lowercase before
    building the role name so mixed-case UUIDs cannot produce a role name
    that diverges from the provisioned role.

    Parameters
    ----------
    tenant_id:
        UUID string for the tenant. ``None`` is accepted only in single-tenant
        mode.

    Raises
    ------
    ValueError
        If ``tenant_id`` is not a valid UUID string in ``multi_tenant`` mode.
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

    Single-tenant deployments keep using the configured database login and
    therefore return ``"geolens_writer"`` only as an inert naming fallback.
    Multi-tenant callers must supply a UUID.
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

    ``conn`` may be an ``AsyncConnection`` or ``AsyncSession``.  The function
    call participates in the caller's transaction, which is required for Cloud
    create/signup atomicity.  PostgreSQL performs identifier construction,
    locking, role validation, and grants inside the SECURITY DEFINER function.

    Parameters
    ----------
    conn:
        Open async SQLAlchemy connection or session.  Do not use AUTOCOMMIT for
        tenant creation.
    tenant_id:
        UUID string for the tenant. Validated — raises ValueError if not UUID.
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        # single_tenant → unconditional no-op: zero SQL, zero cost.
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

    In ``single_tenant``: delegates to ``apply_tenant_data_schema()`` which returns
    immediately (zero SQL).

    The SECURITY DEFINER function runs in one ordinary transaction.  Tenant
    creation paths must instead pass their existing session directly.
    """
    from app.core.db.session import engine

    async with engine.begin() as conn:
        await apply_tenant_data_schema(conn, tenant_id)


async def deprovision_tenant_data_schema_from_engine(tenant_id: str) -> None:
    """Deprovision an already-deleted tenant using the global engine."""
    from app.core.db.session import engine

    async with engine.begin() as conn:
        await deprovision_tenant_data_schema(conn, tenant_id)


def tenant_shard_id(tenant_id: str | None) -> str | None:
    """Look up the shard routing key for a tenant (Phase-1214 routing primitive).

    This is a routing PRIMITIVE reserved for Phase 1214's promote/rebalance.
    It is INTENTIONALLY NOT wired into the read/write hot paths in Plans 02/03:
    at one shard there is nothing to route; hot paths use ``tenant_data_schema``
    / ``tenant_reader_role`` directly. Non-use in Plans 02/03 is by design.

    In ``single_tenant`` or when ``tenant_id`` is None: returns ``None``
    (routing primitive inactive — caller falls back to the single shard).

    In ``multi_tenant``: queries ``catalog.tenants.shard_id`` for the given
    tenant, returning ``'shard-0'`` as the fallback if the column is NULL or
    the tenant row is absent.

    Parameters
    ----------
    tenant_id:
        UUID string for the tenant, or ``None``.
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant() or tenant_id is None:
        return None

    import asyncio

    from sqlalchemy import text as sa_text
    from sqlalchemy.pool import NullPool

    from app.core.db.session import engine as _engine

    async def _fetch() -> str:
        from sqlalchemy.ext.asyncio import create_async_engine

        # Use NullPool to avoid borrowing a connection from the shared pool
        # for this infrequent lookup.
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
            # Inside an async context — caller should use await; return the
            # coroutine so callers that need to await can do so.
            # For the synchronous shim used by test-only code, we fall through
            # to asyncio.run() below.
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

    fix(#435 codex r1): Postgres answers `SELECT * FROM missing_schema.t` with
    `42P01` (undefined_table), the same code a raster dataset's synthetic table
    produces in a schema that does exist. Read-side callers that degrade `42P01`
    to an empty page must probe first, or a tenant data schema that was never
    provisioned (or was lost in a restore) is silently reported as a dataset with
    zero rows.

    Run this only on an error path: it costs a catalog lookup, and it must follow
    a rollback because the failed statement aborted the transaction.
    """
    result = await session.execute(
        text("SELECT to_regnamespace(:schema) IS NOT NULL"), {"schema": schema}
    )
    return bool(result.scalar_one())
