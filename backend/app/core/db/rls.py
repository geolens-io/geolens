"""Mode-gated, idempotent RLS enablement helper (ISO-02, Phase 1208-02).

Provides ``apply_tenancy_rls(conn)`` — the **runtime** half of the policy
split: the migration ``0006_tenant_rls`` defines the fail-closed policies, and
this helper enables + FORCEs them per table.

Design invariants
-----------------
- **single_tenant**: hard no-op — returns immediately, touches NO SQL.  RLS
  stays DISABLED (default) → zero planner cost, byte-identical to pre-1208.
- **multi_tenant**: for each of the 6 tenant-shared tables, reads
  ``pg_class.relrowsecurity`` and ``pg_class.relforcerowsecurity`` FIRST and
  only issues ``ALTER TABLE ... ENABLE/FORCE ROW LEVEL SECURITY`` when the
  flag is not already set.  Steady-state boots are a cheap catalog read — no
  ``ACCESS EXCLUSIVE`` lock, no multi-worker contention (T-1208-08).
- **FORCE is required**: the app connects as the table-owner, which bypasses
  non-FORCE RLS.  ``FORCE ROW LEVEL SECURITY`` subjects the owner connection
  to the policy too (T-1208-05).

Call from bootstrap
-------------------
``apply_tenancy_rls_from_engine()`` is the convenience wrapper called by
``bootstrap()`` — it opens a fresh AUTOCOMMIT connection from the global
engine and delegates to ``apply_tenancy_rls(conn)``.  A mode flip (setting
``GEOLENS_TENANCY_MODE=multi_tenant``) needs no new migration: the policies
are already in the schema, and the next boot enables them.

Teardown note (tests)
---------------------
Any test that calls this in ``multi_tenant`` mode MUST disable RLS again in
teardown (``ALTER TABLE ... NO FORCE / DISABLE ROW LEVEL SECURITY``) so the
shared test DB stays in the single_tenant/RLS-disabled state that the rest of
the suite expects.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text

logger = structlog.stdlib.get_logger(__name__)

#: The 6 tenant-shared control-plane tables that received ``tenant_id`` in
#: ``0005_dormant_tenancy`` and got ``tenant_isolation_*`` policies in
#: ``0006_tenant_rls``.  All live in the ``catalog`` schema.
RLS_TABLES: tuple[str, ...] = (
    "users",
    "records",
    "datasets",
    "maps",
    "collections",
    "embed_tokens",
)

#: The 6 policy names created by 0006_tenant_rls.
RLS_POLICY_NAMES: tuple[str, ...] = tuple(f"tenant_isolation_{t}" for t in RLS_TABLES)


async def apply_tenancy_rls(conn) -> None:
    """Enable + FORCE RLS on the 6 tenant-shared tables (multi_tenant only).

    In ``single_tenant`` (the default): returns immediately — zero SQL, zero
    planner cost (T-1208-07).

    In ``multi_tenant``: for each table, queries ``pg_class`` to check the
    current ``relrowsecurity`` and ``relforcerowsecurity`` flags.  Issues
    ``ALTER TABLE ... ENABLE ROW LEVEL SECURITY`` only when ``relrowsecurity``
    is false, and ``ALTER TABLE ... FORCE ROW LEVEL SECURITY`` only when
    ``relforcerowsecurity`` is false.  Steady-state boots skip both ALTERs —
    a single cheap catalog read per table, no ACCESS EXCLUSIVE lock (T-1208-08).

    Parameters
    ----------
    conn:
        An open async SQLAlchemy connection.  Must be in AUTOCOMMIT isolation
        (or a writable transaction) so DDL takes effect immediately.  Pass a
        connection from ``engine.begin()`` or an AUTOCOMMIT connection; do NOT
        pass an in-flight read-only transaction.
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        # single_tenant → unconditional no-op: RLS stays DISABLED, zero cost.
        logger.debug("apply_tenancy_rls: single_tenant — skipping (no-op)")
        return

    logger.info("apply_tenancy_rls: multi_tenant — checking RLS flags")

    for table in RLS_TABLES:
        qualified = f"catalog.{table}"

        # Step 1: read current RLS state from pg_class (cheap catalog read).
        # Table name comes from the static RLS_TABLES constant (never from
        # user input), so string formatting is safe here.
        row = await conn.execute(
            text(
                f"SELECT relrowsecurity, relforcerowsecurity "
                f"FROM pg_class WHERE oid = '{qualified}'::regclass"
            )
        )
        result = row.fetchone()
        if result is None:
            raise RuntimeError(
                f"apply_tenancy_rls: table {qualified!r} not found in pg_class — "
                "ensure migration 0006_tenant_rls has been applied"
            )
        rls_on, force_on = result

        # Step 2: ENABLE only when not already enabled (idempotent).
        if not rls_on:
            await conn.execute(
                text(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
            )
            logger.info("apply_tenancy_rls: enabled RLS", table=qualified)

        # Step 3: FORCE only when not already forced (idempotent, T-1208-08).
        if not force_on:
            await conn.execute(
                text(f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY")
            )
            logger.info("apply_tenancy_rls: forced RLS", table=qualified)

        if rls_on and force_on:
            logger.debug(
                "apply_tenancy_rls: already enabled+forced (no-op)",
                table=qualified,
            )

    logger.info("apply_tenancy_rls: complete", tables=list(RLS_TABLES))


async def apply_tenancy_rls_from_engine() -> None:
    """Convenience wrapper: open a connection from the global engine and apply RLS.

    Called by ``bootstrap()`` so mode flips require no new migration — the
    policies are already in the schema and this call enables them at boot.

    In ``single_tenant``: delegates to ``apply_tenancy_rls()`` which returns
    immediately (zero SQL).

    In ``multi_tenant``: opens an AUTOCOMMIT connection (DDL outside a
    transaction so each ALTER is visible immediately to other connections),
    calls ``apply_tenancy_rls(conn)``, then closes the connection.
    """
    from app.core.db.session import engine

    async with engine.connect() as conn:
        # Use AUTOCOMMIT so each ALTER TABLE is its own implicit transaction
        # and is immediately visible to other connections.
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await apply_tenancy_rls(conn)
