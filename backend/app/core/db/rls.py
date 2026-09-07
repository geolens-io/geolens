"""Mode-gated, idempotent RLS enablement helper (ISO-02, Phase 1208-02).

Provides ``apply_tenancy_rls(conn)`` — the runtime half of the policy split:
migration ``0006_tenant_rls`` defines the fail-closed policies, this helper
enables + FORCEs them per table.

single_tenant: RLS stays disabled; runtime-role verification is a hard no-op
unless ``GEOLENS_RUNTIME_DB_ROLE`` explicitly opts in, preserving existing
installs byte-for-byte by default. multi_tenant: for each tenant-shared
table, reads ``pg_class.relrowsecurity``/``relforcerowsecurity`` first and
only issues ``ALTER TABLE ... ENABLE/FORCE ROW LEVEL SECURITY`` when unset —
steady-state boots are a cheap catalog read, no ``ACCESS EXCLUSIVE`` lock or
multi-worker contention (T-1208-08).

FORCE is required: table owners bypass non-FORCE RLS, and ``FORCE ROW LEVEL
SECURITY`` subjects a non-superuser owner to the policy too (T-1208-05). A
safe runtime role is mandatory: superusers and ``BYPASSRLS`` roles ignore
even FORCE RLS, so multi-tenant bootstrap verifies both ``session_user`` and
``current_user`` (plus privileged role membership) and refuses to serve when
either can bypass the boundary.

``apply_tenancy_rls_from_engine()`` is the convenience wrapper ``bootstrap()``
calls — opens a fresh AUTOCOMMIT connection and delegates to
``apply_tenancy_rls(conn)``. A mode flip to multi_tenant needs no new
migration: the policies are already in the schema, and the next boot enables
them.

Tests: any test calling this in multi_tenant mode MUST disable RLS again in
teardown (``ALTER TABLE ... NO FORCE / DISABLE ROW LEVEL SECURITY``) so the
shared test DB stays in the single_tenant/RLS-disabled state the rest of the
suite expects.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text

logger = structlog.stdlib.get_logger(__name__)

#: Tenant-shared control-plane tables protected by ``tenant_isolation_*``
#: policies. The original six were introduced in 0005/0006; later migrations
#: extend this boundary when a child table needs an independent tenant key.
RLS_TABLES: tuple[str, ...] = (
    "users",
    "records",
    "datasets",
    "maps",
    "collections",
    "embed_tokens",
    "oauth_accounts",
    "audit_logs",
    "ingest_jobs",
)

#: Policy names for the complete current tenant boundary.
RLS_POLICY_NAMES: tuple[str, ...] = tuple(f"tenant_isolation_{t}" for t in RLS_TABLES)


async def assert_multi_tenant_runtime_role(conn) -> None:
    """Verify the live role when tenancy or the single-tenant opt-in requires it.

    ``FORCE ROW LEVEL SECURITY`` does not constrain superusers or
    ``BYPASSRLS`` roles. Checking only ``current_user`` is also insufficient:
    a superuser ``session_user`` can ``RESET ROLE`` after a temporary switch.
    So the login itself, the effective role, and every privileged role it can
    assume must all be safe.

    single_tenant is a hard no-op unless ``GEOLENS_RUNTIME_DB_ROLE`` opts the
    process into the same verification, additionally requiring the live login
    to match the configured role name.
    """
    from app.core.config import settings
    from app.core.tenancy import is_multi_tenant

    multi_tenant = is_multi_tenant()
    expected_runtime_role = settings.geolens_runtime_db_role
    if not multi_tenant and expected_runtime_role is None:
        logger.warning(
            "Single-tenant database runtime role guard is disabled",
            remediation="Set GEOLENS_RUNTIME_DB_ROLE to adopt the opt-in least-privilege login",
        )
        return

    result = await conn.execute(
        text(
            """
            SELECT
                current_user,
                session_user,
                effective_role.rolsuper,
                effective_role.rolbypassrls,
                effective_role.rolcreaterole,
                effective_role.rolcreatedb,
                effective_role.rolreplication,
                login_role.rolsuper,
                login_role.rolbypassrls,
                login_role.rolcreaterole,
                login_role.rolcreatedb,
                login_role.rolreplication,
                EXISTS (
                    SELECT 1
                    FROM pg_roles privileged_role
                    WHERE (
                        privileged_role.rolsuper
                        OR privileged_role.rolbypassrls
                        OR privileged_role.rolcreaterole
                        OR privileged_role.rolcreatedb
                        OR privileged_role.rolreplication
                    )
                      AND pg_has_role(session_user, privileged_role.oid, 'MEMBER')
                ) AS can_assume_powerful_role,
                EXISTS (
                    SELECT 1
                    FROM pg_roles forbidden_role
                    WHERE forbidden_role.rolname IN (
                        'geolens_tenant_provisioner',
                        'geolens_tile_gateway'
                    )
                      AND pg_has_role(session_user, forbidden_role.oid, 'MEMBER')
                ) OR EXISTS (
                    SELECT 1
                    FROM pg_auth_members direct_membership
                    JOIN pg_roles granted_role
                      ON granted_role.oid = direct_membership.roleid
                    JOIN pg_roles member_role
                      ON member_role.oid = direct_membership.member
                    WHERE member_role.rolname = session_user
                      AND granted_role.rolname ~
                          '^geolens_(reader|writer)_t_[0-9a-f_]+'
                ) AS has_forbidden_runtime_membership
                , EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_class protected_relation
                    JOIN pg_catalog.pg_namespace protected_namespace
                      ON protected_namespace.oid = protected_relation.relnamespace
                    WHERE protected_namespace.nspname = 'catalog'
                      AND protected_relation.relname IN (
                          'users', 'records', 'datasets', 'maps',
                          'collections', 'embed_tokens', 'oauth_accounts',
                          'audit_logs', 'ingest_jobs'
                      )
                      AND protected_relation.relkind IN ('r', 'p')
                      AND pg_catalog.pg_has_role(
                          session_user,
                          protected_relation.relowner,
                          'MEMBER'
                      )
                ) AS can_assume_catalog_table_owner,
                EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_namespace tenant_namespace
                    WHERE tenant_namespace.nspname ~
                        '^data_t_[0-9a-f]{8}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{12}$'
                      AND pg_catalog.pg_has_role(
                          session_user,
                          tenant_namespace.nspowner,
                          'MEMBER'
                      )
                ) AS can_assume_tenant_schema_owner,
                pg_catalog.has_schema_privilege(
                    session_user, 'catalog', 'CREATE'
                ) OR pg_catalog.has_schema_privilege(
                    session_user, 'public', 'CREATE'
                ) AS can_create_in_protected_schema,
                EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_database owned_database
                    WHERE pg_catalog.pg_has_role(
                        session_user, owned_database.datdba, 'MEMBER'
                    )
                ) AS can_assume_database_owner,
                EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_namespace owned_schema
                    WHERE pg_catalog.pg_has_role(
                        session_user, owned_schema.nspowner, 'MEMBER'
                    )
                ) AS can_assume_schema_owner
            FROM pg_roles effective_role
            JOIN pg_roles login_role ON login_role.rolname = session_user
            WHERE effective_role.rolname = current_user
            """
        )
    )
    row = result.fetchone()
    if row is None:
        raise RuntimeError("Database role verification returned no PostgreSQL role")

    (
        current_role_name,
        session_role_name,
        current_superuser,
        current_bypassrls,
        current_createrole,
        current_createdb,
        current_replication,
        session_superuser,
        session_bypassrls,
        session_createrole,
        session_createdb,
        session_replication,
        can_assume_powerful_role,
        has_forbidden_runtime_membership,
        can_assume_catalog_table_owner,
        can_assume_tenant_schema_owner,
        can_create_in_protected_schema,
        can_assume_database_owner,
        can_assume_schema_owner,
    ) = row
    unsafe_role = any(
        (
            current_superuser,
            current_bypassrls,
            current_createrole,
            current_createdb,
            current_replication,
            session_superuser,
            session_bypassrls,
            session_createrole,
            session_createdb,
            session_replication,
            can_assume_powerful_role,
            has_forbidden_runtime_membership,
            can_assume_catalog_table_owner,
            can_assume_tenant_schema_owner,
            can_create_in_protected_schema,
            can_assume_database_owner,
            can_assume_schema_owner,
        )
    )
    wrong_single_tenant_role = (
        not multi_tenant
        and expected_runtime_role is not None
        and (
            current_role_name != expected_runtime_role
            or session_role_name != expected_runtime_role
        )
    )
    if unsafe_role or wrong_single_tenant_role:
        if not multi_tenant:
            raise RuntimeError(
                "GEOLENS_RUNTIME_DB_ROLE requires the live PostgreSQL session "
                "to use that exact dedicated LOGIN with SUPERUSER, BYPASSRLS, "
                "CREATEROLE, CREATEDB, and REPLICATION disabled; it must not "
                "inherit/assume a powerful role, own a database or schema, "
                "or create in catalog/public. "
                f"Configured role={expected_runtime_role!r}, "
                f"current_user={current_role_name!r}, "
                f"session_user={session_role_name!r}. Keep migrations and "
                "restore on the separate privileged credential."
            )
        raise RuntimeError(
            "GEOLENS_TENANCY_MODE=multi_tenant requires a dedicated PostgreSQL "
            "application login that is not SUPERUSER, BYPASSRLS, CREATEROLE, "
            "CREATEDB, or REPLICATION and cannot assume such a role. The "
            "migrator provisioner and tile gateway must remain separate; the "
            "runtime login must not own (or be able to assume ownership of) "
            "a database, schema, catalog RLS table, or tenant schema, or have "
            "CREATE on catalog/public. "
            f"Resolved current_user={current_role_name!r}, "
            f"session_user={session_role_name!r}. Configure API and worker "
            "DATABASE_URL_OVERRIDE with a least-privilege runtime credential; "
            "keep schema migration/RLS preparation on a separate migrator role."
        )

    logger.info(
        "Database runtime role verified",
        tenancy_mode="multi_tenant" if multi_tenant else "single_tenant",
        current_user=current_role_name,
        session_user=session_role_name,
    )


async def apply_tenancy_rls(conn) -> None:
    """Enable + FORCE RLS on every tenant-shared table (multi_tenant only).

    single_tenant: returns immediately, zero SQL, zero planner cost
    (T-1208-07). multi_tenant: for each table, queries ``pg_class`` for the
    current ``relrowsecurity``/``relforcerowsecurity`` flags and issues
    ``ALTER TABLE ... ENABLE``/``FORCE ROW LEVEL SECURITY`` only for the flag
    that is false. Steady-state boots skip both ALTERs — one cheap catalog
    read per table, no ACCESS EXCLUSIVE lock (T-1208-08).

    ``conn`` must be AUTOCOMMIT or a writable transaction so DDL takes effect
    immediately — never an in-flight read-only transaction.
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        logger.debug("apply_tenancy_rls: single_tenant — skipping (no-op)")
        return

    logger.info("apply_tenancy_rls: multi_tenant — checking RLS flags")

    for table in RLS_TABLES:
        qualified = f"catalog.{table}"

        # Table name comes from the static RLS_TABLES constant, never user
        # input, so string formatting into SQL is safe here.
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

        if not rls_on:
            await conn.execute(
                text(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
            )
            logger.info("apply_tenancy_rls: enabled RLS", table=qualified)

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


async def apply_tenancy_rls_from_engine(*, verify_runtime_role: bool = True) -> None:
    """Convenience wrapper: open a connection from the global engine and apply RLS.

    Called by ``bootstrap()`` so mode flips require no new migration — the
    policies are already in the schema and this call enables them at boot.

    single_tenant: RLS and the role check both remain a no-op unless
    ``GEOLENS_RUNTIME_DB_ROLE`` opts into the non-superuser path. multi_tenant:
    opens an AUTOCOMMIT connection, calls ``apply_tenancy_rls(conn)``,
    verifies the runtime role cannot bypass RLS, then closes it. A privileged
    migration process may pass ``verify_runtime_role=False`` while preparing
    the schema; API/worker bootstrap always use the default verification.
    """
    # fix(#909): via the app.core.db façade, not app.core.db.session — the
    # test fixture reassigns the façade attribute, so importing from the
    # origin module would resolve the un-patched engine even when late-bound.
    from app.core.db import engine

    async with engine.connect() as conn:
        # AUTOCOMMIT so each ALTER TABLE is its own implicit transaction,
        # immediately visible to other connections.
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await apply_tenancy_rls(conn)
        if verify_runtime_role:
            await assert_multi_tenant_runtime_role(conn)
