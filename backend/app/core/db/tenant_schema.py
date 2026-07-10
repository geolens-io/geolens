"""Per-tenant data schema + reader-role bootstrap (DP-01, Phase 1209-01).

Provides ``apply_tenant_data_schema(conn, tenant_id)`` — idempotent
CREATE SCHEMA IF NOT EXISTS data_t_{tenant_id} + CREATE ROLE IF NOT EXISTS
geolens_reader_t_{tenant_id} (NOLOGIN) + GRANT USAGE/SELECT + ALTER DEFAULT
PRIVILEGES inside the tenant schema.

Design invariants
-----------------
- **single_tenant**: hard no-op — returns immediately, touches NO SQL.
  The shared ``data`` schema + global ``geolens_reader`` stay unchanged.
- **multi_tenant**: idempotent — uses IF NOT EXISTS so concurrent
  tenant-provisioning calls (multi-worker) do not fail.
- Tenant id is ALWAYS passed as a validated UUID string (never f-string
  interpolated directly from user input).

Call from tenant provisioning
-----------------------------
``apply_tenant_data_schema_from_engine(tenant_id)`` is the convenience
wrapper called during tenant creation in the overlay (Phase 1211).
At boot, ``bootstrap()`` does NOT call this per-tenant — schemas are
created on demand at tenant-provision time.

Schema naming convention: ``data_t_{tenant_id with hyphens→underscores}``
Role naming convention:   ``geolens_reader_t_{tenant_id with hyphens→underscores}``
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

    In ``single_tenant`` or when ``tenant_id`` is None: returns ``"data"``
    (the global shared data schema — byte-identical to pre-1209 behavior).

    In ``multi_tenant`` with a non-None tenant_id: returns
    ``"data_t_{tenant_id with hyphens replaced by underscores}"``.

    IN-02 (Phase 1209-CR): ``tenant_id`` is normalized to lowercase before
    building the schema name so mixed-case UUIDs cannot produce
    ``data_t_ABCDEF…`` (case-sensitive in quoted identifiers) while the
    provisioned schema is ``data_t_abcdef…``.

    Parameters
    ----------
    tenant_id:
        UUID string for the tenant, or ``None`` (returns global default).

    Raises
    ------
    ValueError
        If ``tenant_id`` is not a valid UUID string in ``multi_tenant`` mode.
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant() or tenant_id is None:
        return "data"

    normalized = tenant_id.lower()
    if not _TENANT_ID_RE.match(normalized):
        raise ValueError(f"tenant_data_schema: invalid tenant_id: {tenant_id!r}")

    # All identifiers derive from the validated UUID — string formatting is safe.
    return f"data_t_{normalized.replace('-', '_')}"


def tenant_reader_role(tenant_id: str | None) -> str:
    """Return the per-tenant reader role name.

    In ``single_tenant`` or when ``tenant_id`` is None: returns
    ``"geolens_reader"`` (the global reader role).

    In ``multi_tenant`` with a non-None tenant_id: returns
    ``"geolens_reader_t_{tenant_id with hyphens replaced by underscores}"``.

    IN-02 (Phase 1209-CR): ``tenant_id`` is normalized to lowercase before
    building the role name so mixed-case UUIDs cannot produce a role name
    that diverges from the provisioned role.

    Parameters
    ----------
    tenant_id:
        UUID string for the tenant, or ``None`` (returns global default).

    Raises
    ------
    ValueError
        If ``tenant_id`` is not a valid UUID string in ``multi_tenant`` mode.
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant() or tenant_id is None:
        return "geolens_reader"

    normalized = tenant_id.lower()
    if not _TENANT_ID_RE.match(normalized):
        raise ValueError(f"tenant_reader_role: invalid tenant_id: {tenant_id!r}")

    # All identifiers derive from the validated UUID — string formatting is safe.
    return f"geolens_reader_t_{normalized.replace('-', '_')}"


async def apply_tenant_data_schema(conn, tenant_id: str) -> None:
    """Create per-tenant data schema + reader role (multi_tenant only).

    In ``single_tenant``: returns immediately — zero SQL, zero cost.
    In ``multi_tenant``:
      1. Validates tenant_id is a UUID (never interpolated raw).
      2. CREATE SCHEMA IF NOT EXISTS data_t_{tenant_id}
      3. CREATE ROLE IF NOT EXISTS geolens_reader_t_{tenant_id} (NOLOGIN)
      4. GRANT USAGE ON SCHEMA data_t_{tenant_id} TO geolens_reader_t_{tenant_id}
      5. GRANT SELECT ON ALL TABLES IN SCHEMA data_t_{tenant_id} TO ...
      6. ALTER DEFAULT PRIVILEGES IN SCHEMA data_t_{tenant_id}
             GRANT SELECT ON TABLES TO geolens_reader_t_{tenant_id}

    Parameters
    ----------
    conn:
        Open async SQLAlchemy connection in AUTOCOMMIT (for DDL).
    tenant_id:
        UUID string for the tenant. Validated — raises ValueError if not UUID.
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        # single_tenant → unconditional no-op: zero SQL, zero cost.
        logger.debug("apply_tenant_data_schema: single_tenant — skipping (no-op)")
        return

    # IN-02: normalize to lowercase before building identifiers so mixed-case
    # UUIDs don't produce divergent schema/role names.
    normalized = tenant_id.lower()
    if not _TENANT_ID_RE.match(normalized):
        raise ValueError(f"apply_tenant_data_schema: invalid tenant_id: {tenant_id!r}")

    # All identifiers derive from the validated UUID — string formatting is safe
    # (same justification as rls.py static-table formatting; UUID chars + underscores
    # only — no shell/SQL metacharacters possible after hyphen→underscore replacement).
    schema = f"data_t_{normalized.replace('-', '_')}"
    role = f"geolens_reader_t_{normalized.replace('-', '_')}"

    await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    await conn.execute(
        text(
            f"DO $$ BEGIN "
            f"  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN "
            f"    CREATE ROLE {role} NOLOGIN; "
            f"  END IF; "
            f"END $$"
        )
    )
    await conn.execute(text(f"GRANT USAGE ON SCHEMA {schema} TO {role}"))
    await conn.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {role}"))
    await conn.execute(
        text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO {role}"
        )
    )
    logger.info("apply_tenant_data_schema: provisioned", schema=schema, role=role)


async def apply_tenant_data_schema_from_engine(tenant_id: str) -> None:
    """Convenience wrapper: open a connection from the global engine and apply tenant schema DDL.

    In ``single_tenant``: delegates to ``apply_tenant_data_schema()`` which returns
    immediately (zero SQL).

    In ``multi_tenant``: opens an AUTOCOMMIT connection (DDL outside a transaction
    so each statement is visible immediately to other connections), calls
    ``apply_tenant_data_schema(conn, tenant_id)``, then closes the connection.
    """
    from app.core.db.session import engine

    async with engine.connect() as conn:
        # AUTOCOMMIT so each DDL statement is its own implicit transaction
        # and is immediately visible to other connections.
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await apply_tenant_data_schema(conn, tenant_id)


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
