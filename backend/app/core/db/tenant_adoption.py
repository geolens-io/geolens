"""Forward-only tenant-ownership adoption at the current schema head.

Migration ``0019_tenant_provisioning_boundary`` is the only place that has ever
moved restored tenant schemas, roles, and relations under the least-privilege
provisioning boundary.  Reaching it again meant ``alembic downgrade 0016``,
which walks back through migrations that either refuse on data the current
schema legitimately holds or discard state the re-upgrade cannot rebuild.  On a
populated cluster that is a data-loss event, not a recovery procedure (#998).

This module reconstructs the same ownership against the **current head schema**,
so the downgrade is never required.  It is deliberately not a replay of 0019:

- 0019 installs its SECURITY DEFINER functions with plain ``CREATE FUNCTION``,
  which collides with the functions a restored dump already carries.  Adoption
  never installs a function body.  The migrations own that body; adoption
  verifies the two functions are present, ``SECURITY DEFINER``, and
  ``search_path``-pinned, and repairs only the owner and the ACL that
  ``pg_restore --no-owner --no-acl`` strips.  That repair matters on its own:
  PostgreSQL's default function ACL is ``EXECUTE`` to ``PUBLIC``, so a restored
  ``catalog.provision_tenant_data_schema`` is a SECURITY DEFINER function owned
  by the restoring superuser and callable by every login in the database.
- 0019 parked tenant relations on the provisioner so its provisioning function
  could rewrite their ACLs.  Migration 0024 removed that object-ACL pass, so at
  head the relations move straight to the per-tenant writer and the reader's
  per-relation ``SELECT`` is granted by the writer itself — the same contract
  ingest follows.

Idempotence is keyed on database state, never on a marker or a timestamp: each
step reads what the cluster currently holds and issues DDL only for the gap.  A
second run over an adopted tenant issues no DDL at all, and a run interrupted
partway is resumed by running it again — every tenant is adopted in its own
transaction, so completed tenants stay completed.

Run it with the migrator credential — ``CREATEROLE``, authority over the
restored objects, and, on a non-superuser migrator, the privileges of
``geolens_tenant_provisioner`` — against a database already at head::

    docker compose run --rm --no-deps -e DATABASE_URL_OVERRIDE="<migrator-url>" \\
      migrate sh -c "uv run --no-dev python -m app.core.db.tenant_adoption --apply"

Without ``--apply`` the run is a read-only report of what adoption would change.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

import structlog
from sqlalchemy import text

from app.core.db.tenant_adoption_report import (
    BOUNDARY_FUNCTIONS,
    BOUNDARY_TRIGGER,
    BOUNDARY_TRIGGER_FUNCTION,
    BOUNDARY_TRIGGER_TYPE,
    ISOLATION_POLICY_EXPRESSION,
    STAMPING_FUNCTION_SEARCH_PATH,
    AdoptionReport,
    BoundaryFunctionState,
    BoundaryTableState,
    TenantOwnershipState,
    format_report,
    unexpected_shape,
)
from app.core.db.tenant_adoption_sql import (
    ADOPT_TENANT_SQL,
    CLUSTER_ROLE_CREATE_SQL,
    CLUSTER_ROLE_VALIDATE_SQL,
    CONTROL,
    PROVISIONER,
    PROVISIONER_DATABASE_GRANT_SQL,
    RELEASE_BOOTSTRAP_MEMBERSHIP_SQL,
    SANDBOX,
    SECURE_BOUNDARY_FUNCTIONS_SQL,
    TENANT_GUC,
    TILE,
    WRITER,
)

logger = structlog.stdlib.get_logger(__name__)


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


async def live_tenant_boundary(conn) -> list[BoundaryTableState]:
    """Read the tenant boundary from the database, never from a constant.

    The boundary is whatever currently carries 0018's insert-stamping trigger.
    Migration 0018 froze a six-table tuple by design and later migrations
    widened the live set, so any enumeration copied from a migration is stale
    the moment a table joins.  Tables holding a ``tenant_id`` column *without*
    the trigger are reported too: 0037's ``dataset_refresh_runs`` is a
    deliberately dormant column, and an accidental one should look the same
    here so it can be told apart on purpose rather than by omission.
    """
    result = await conn.execute(
        text(
            """
            SELECT relation.relname AS name,
                   -- tgenabled 'O'/'A' are the only states that fire for an
                   -- ordinary application session. A restored trigger left
                   -- 'D' (disabled) or 'R' (replica-only) still exists under
                   -- this name and stamps nothing, and nothing at boot
                   -- re-enables it.
                   EXISTS (
                       SELECT 1 FROM pg_catalog.pg_trigger AS trigger_row
                       WHERE trigger_row.tgrelid = relation.oid
                         AND trigger_row.tgname = :trigger_name
                         AND NOT trigger_row.tgisinternal
                         AND trigger_row.tgenabled IN ('O', 'A')
                         AND trigger_row.tgtype = :before_insert_row
                         -- 0018 installs it unconditional and argument-free. A
                         -- WHEN clause that is false for some rows leaves those
                         -- inserts unstamped while everything else still checks
                         -- out.
                         AND trigger_row.tgqual IS NULL
                         AND trigger_row.tgnargs = 0
                         AND trigger_row.tgfoid = (
                             SELECT routine.oid
                             FROM pg_catalog.pg_proc AS routine
                             JOIN pg_catalog.pg_namespace AS routine_schema
                               ON routine_schema.oid = routine.pronamespace
                             WHERE routine_schema.nspname = 'catalog'
                               AND routine.proname = :trigger_function
                         )
                   ) AS has_stamping_trigger,
                   EXISTS (
                       SELECT 1 FROM pg_catalog.pg_trigger AS trigger_row
                       WHERE trigger_row.tgrelid = relation.oid
                         AND trigger_row.tgname = :trigger_name
                         AND NOT trigger_row.tgisinternal
                   ) AS stamping_trigger_present,
                   EXISTS (
                       SELECT 1 FROM pg_catalog.pg_attribute AS attribute
                       WHERE attribute.attrelid = relation.oid
                         AND attribute.attname = 'tenant_id'
                         AND NOT attribute.attisdropped
                   ) AS has_tenant_id,
                   relation.relrowsecurity AS rls_enabled,
                   relation.relforcerowsecurity AS rls_forced,
                   -- The policy is the isolation rule itself, and boot does not
                   -- recreate it: a restored table with the flags intact but no
                   -- policy denies every runtime read, and an altered one can
                   -- return another tenant's rows. Its expression has been
                   -- byte-identical since 0006, so it is compared exactly.
                   EXISTS (
                       SELECT 1 FROM pg_catalog.pg_policy AS policy
                       WHERE policy.polrelid = relation.oid
                         AND policy.polname = 'tenant_isolation_' || relation.relname
                         AND policy.polcmd = '*'
                         AND policy.polpermissive
                         -- polroles {0} is TO PUBLIC. Narrowed to a named list,
                         -- every role outside it takes the implicit deny.
                         AND policy.polroles = '{0}'::oid[]
                         AND pg_catalog.pg_get_expr(
                             policy.polqual, policy.polrelid
                         ) = :isolation_expression
                         AND pg_catalog.pg_get_expr(
                             policy.polwithcheck, policy.polrelid
                         ) = :isolation_expression
                   ) AS isolation_policy_intact
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'catalog'
              AND relation.relkind IN ('r', 'p')
            ORDER BY relation.relname
            """
        ),
        {
            "trigger_name": BOUNDARY_TRIGGER,
            "trigger_function": BOUNDARY_TRIGGER_FUNCTION,
            "before_insert_row": BOUNDARY_TRIGGER_TYPE,
            "isolation_expression": ISOLATION_POLICY_EXPRESSION,
        },
    )
    states = [BoundaryTableState(**dict(row._mapping)) for row in result]
    return [
        state
        for state in states
        if state.has_stamping_trigger
        or state.stamping_trigger_present
        or state.has_tenant_id
    ]


#: ``prosrc`` with SQL comments removed.  The markers below say what a body
#: still *does*, and a substituted body could otherwise carry them in a comment
#: and satisfy the check while executing something else.  Dead code can still
#: defeat it — see ``BoundaryFunctionState.migration_shaped`` for why this is a
#: structural check and not a provenance one, and why the residual exposure only
#: runs in the safe direction.
_EXECUTABLE_BODY = (
    "regexp_replace("
    "regexp_replace(routine.prosrc, '/\\*.*?\\*/', ' ', 'gs'),"
    " '--[^\n]*', ' ', 'g')"
)


async def boundary_function_states(conn) -> list[BoundaryFunctionState]:
    """Read owner, SECURITY DEFINER, search_path, and ACL of both functions."""
    result = await conn.execute(
        text(
            f"""
            SELECT routine.proname AS name,
                   pg_catalog.pg_get_userbyid(routine.proowner) AS owner,
                   routine.prosecdef AS security_definer,
                   COALESCE(
                       'search_path=pg_catalog' = ANY(routine.proconfig), false
                   ) AS search_path_pinned,
                   language.lanname AS language,
                   routine.prorettype = 'void'::regtype AS returns_void,
                   (
                       {_EXECUTABLE_BODY} LIKE '%catalog.tenants%'
                       AND {_EXECUTABLE_BODY} LIKE '%data_t_%'
                       AND {_EXECUTABLE_BODY} LIKE '%pg_advisory_xact_lock%'
                   ) AS body_markers_present,
                   pg_catalog.has_function_privilege(
                       'public', routine.oid, 'EXECUTE'
                   ) AS public_execute,
                   CASE
                       WHEN EXISTS (
                           SELECT 1 FROM pg_catalog.pg_roles
                           WHERE rolname = :control
                       )
                       THEN pg_catalog.has_function_privilege(
                           :control, routine.oid, 'EXECUTE'
                       )
                       ELSE false
                   END AS control_execute
            FROM pg_catalog.pg_proc AS routine
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = routine.pronamespace
            JOIN pg_catalog.pg_language AS language
              ON language.oid = routine.prolang
            WHERE namespace.nspname = 'catalog'
              AND routine.proname = ANY(:names)
              AND routine.pronargs = 1
              AND routine.proargtypes[0] = 'uuid'::regtype
            ORDER BY routine.proname
            """
        ),
        {"control": CONTROL, "names": list(BOUNDARY_FUNCTIONS)},
    )
    return [BoundaryFunctionState(**dict(row._mapping)) for row in result]


async def stamping_function_shape(conn) -> str | None:
    """Why ``catalog.stamp_current_tenant_on_insert`` is not 0018's, if it is not.

    Checking only that a trigger points at this name proves nothing: replace the
    body with one that returns ``NEW`` untouched and every insert lands
    tenantless while every structural check still passes.  Same structural
    approach, and the same honest limits, as
    ``BoundaryFunctionState.migration_shaped``.
    """
    result = await conn.execute(
        text(
            f"""
            SELECT language.lanname AS language,
                   routine.prosecdef AS security_definer,
                   routine.prorettype = 'trigger'::regtype AS returns_trigger,
                   COALESCE(
                       :stamping_search_path = ANY(routine.proconfig), false
                   ) AS search_path_pinned,
                   (
                       {_EXECUTABLE_BODY} LIKE '%app.current_tenant%'
                       AND {_EXECUTABLE_BODY} LIKE '%NEW.tenant_id%'
                   ) AS body_markers_present
            FROM pg_catalog.pg_proc AS routine
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = routine.pronamespace
            JOIN pg_catalog.pg_language AS language
              ON language.oid = routine.prolang
            WHERE namespace.nspname = 'catalog'
              AND routine.proname = :name
              AND routine.pronargs = 0
            """
        ),
        {
            "name": BOUNDARY_TRIGGER_FUNCTION,
            "stamping_search_path": STAMPING_FUNCTION_SEARCH_PATH,
        },
    )
    row = result.one_or_none()
    if row is None:
        return f"catalog.{BOUNDARY_TRIGGER_FUNCTION}() is missing"
    if row.language != "plpgsql":
        return (
            f"catalog.{BOUNDARY_TRIGGER_FUNCTION}() is written in "
            f"{row.language}, not plpgsql"
        )
    if not row.returns_trigger:
        return f"catalog.{BOUNDARY_TRIGGER_FUNCTION}() does not return trigger"
    if row.security_definer:
        # 0018 installs it SECURITY INVOKER on purpose: it runs on every insert,
        # and after a --no-owner restore its owner is the restoring superuser.
        return (
            f"catalog.{BOUNDARY_TRIGGER_FUNCTION}() is SECURITY DEFINER — 0018 "
            "installs it SECURITY INVOKER, and it fires on every insert"
        )
    if not row.search_path_pinned:
        return (
            f"catalog.{BOUNDARY_TRIGGER_FUNCTION}() does not carry "
            f"`SET {STAMPING_FUNCTION_SEARCH_PATH}` — an unqualified name in it "
            "can resolve through a writable schema"
        )
    if not row.body_markers_present:
        return (
            f"catalog.{BOUNDARY_TRIGGER_FUNCTION}() has a body that no longer "
            "reads app.current_tenant or writes NEW.tenant_id — it stamps nothing"
        )
    return None


async def cluster_topology_error(engine) -> str | None:
    """Would ``--apply`` refuse this cluster's fixed role topology?

    Runs the identical guard ``ensure_cluster_roles`` runs, minus the half that
    creates anything, rather than a read-only paraphrase of it that could drift.
    A raise aborts the transaction, so it gets a connection of its own.
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(text(CLUSTER_ROLE_VALIDATE_SQL))
    except Exception as exc:  # broad: any refusal is the answer, whatever its class
        return str(exc).strip().splitlines()[0]
    return None


async def missing_provisioner_grants(conn) -> list[str]:
    """Object privileges ``ensure_cluster_roles`` grants and a restore drops.

    Replaying globals brings the role back; it brings none of these with it, and
    without them ``catalog.provision_tenant_data_schema`` cannot see
    ``catalog.tenants`` or create a tenant schema.  Call only once
    :func:`cluster_topology_error` has confirmed the role exists — the
    ``has_*_privilege`` family errors on a role name that is not there.
    """
    result = await conn.execute(
        text(
            """
            SELECT pg_catalog.has_database_privilege(
                       :provisioner, pg_catalog.current_database(), 'CREATE'
                   ) AS database_create,
                   pg_catalog.has_schema_privilege(
                       :provisioner, 'catalog', 'USAGE'
                   ) AS catalog_usage,
                   pg_catalog.has_table_privilege(
                       :provisioner, 'catalog.tenants', 'SELECT'
                   ) AS tenants_select
            """
        ),
        {"provisioner": PROVISIONER},
    )
    row = result.one()
    labels = {
        "database_create": "CREATE on the database",
        "catalog_usage": "USAGE on schema catalog",
        "tenants_select": "SELECT on catalog.tenants",
    }
    return [label for key, label in labels.items() if not getattr(row, key)]


async def list_tenants(conn) -> list[str]:
    """Every tenant id in the control plane, in a stable order."""
    result = await conn.execute(
        text("SELECT id::text FROM catalog.tenants ORDER BY id")
    )
    return [row[0] for row in result]


#: ``pg_auth_members.inherit_option``/``set_option`` arrived in PostgreSQL 16 and
#: GeoLens supports 13 and up (README), so naming those columns directly would be
#: a parse error on an older server.  Reading them back out of the row as jsonb
#: parses everywhere, and the guard degrades to ``admin_option`` alone before 16 —
#: which is correct, because that is where NOINHERIT on the fixed gateway roles
#: carries the same SET-only guarantee.
_MEMBER_OPTIONS_PRESENT = "jsonb_exists(to_jsonb(membership), 'set_option')"
_MEMBER_INHERIT = "(to_jsonb(membership) ->> 'inherit_option')::boolean"
_MEMBER_SET = "(to_jsonb(membership) ->> 'set_option')::boolean"
_MEMBER_ADMIN_ONLY = (
    f"(NOT {_MEMBER_OPTIONS_PRESENT} OR NOT ({_MEMBER_INHERIT} OR {_MEMBER_SET}))"
)
_MEMBER_SET_ONLY = (
    f"(NOT {_MEMBER_OPTIONS_PRESENT} OR (NOT {_MEMBER_INHERIT} AND {_MEMBER_SET}))"
)


def _role_secure_sql(
    role_cte: str, allowed_members: tuple[str, ...], gateways: tuple[str, ...]
) -> str:
    """SQL for "this per-tenant role has the shape ``--apply`` enforces".

    Every clause mirrors a refusal in ``ADOPT_TENANT_SQL`` or in
    ``catalog.provision_tenant_data_schema``, so a dry run cannot call a topology
    adopted that ``--apply`` would reject or repair.  Role existence and
    effective privileges are not enough on their own: a reader carrying
    ``SUPERUSER`` satisfies every ``has_table_privilege`` check by fiat.

    Role names come from the module constants above, never from a caller.
    """
    allowed = ", ".join(f"'{name}'" for name in allowed_members)
    gateway_names = ", ".join(f"'{name}'" for name in gateways)
    return f"""(
                    EXISTS (
                        SELECT 1 FROM {role_cte}
                        WHERE NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
                          AND NOT rolcreaterole AND NOT rolinherit
                          AND NOT rolreplication AND NOT rolbypassrls
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM pg_catalog.pg_auth_members AS membership
                        JOIN pg_catalog.pg_roles AS member_role
                          ON member_role.oid = membership.member
                        WHERE membership.roleid = (SELECT oid FROM {role_cte})
                          AND member_role.rolname NOT IN ({allowed})
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM pg_catalog.pg_auth_members AS membership
                        WHERE membership.member = (SELECT oid FROM {role_cte})
                    )
                    AND EXISTS (
                        SELECT 1 FROM pg_catalog.pg_auth_members AS membership
                        JOIN pg_catalog.pg_roles AS member_role
                          ON member_role.oid = membership.member
                        WHERE membership.roleid = (SELECT oid FROM {role_cte})
                          AND member_role.rolname = '{PROVISIONER}'
                          AND membership.admin_option
                          AND {_MEMBER_ADMIN_ONLY}
                    )
                    AND (
                        SELECT count(*)
                        FROM pg_catalog.pg_auth_members AS membership
                        JOIN pg_catalog.pg_roles AS member_role
                          ON member_role.oid = membership.member
                        WHERE membership.roleid = (SELECT oid FROM {role_cte})
                          AND member_role.rolname IN ({gateway_names})
                          AND NOT membership.admin_option
                          AND {_MEMBER_SET_ONLY}
                    ) = {len(gateways)}
                )"""


async def tenant_ownership_state(conn, tenant_id: str) -> TenantOwnershipState:
    """Read one tenant's ownership state without changing anything."""
    result = await conn.execute(
        text(
            """
            WITH names AS (
                SELECT 'data_t_' || replace(:tenant_id, '-', '_') AS schema_name,
                       'geolens_reader_t_' || replace(:tenant_id, '-', '_')
                           AS reader_name,
                       'geolens_writer_t_' || replace(:tenant_id, '-', '_')
                           AS writer_name
            ),
            reader AS (
                SELECT * FROM pg_catalog.pg_roles
                WHERE rolname = (SELECT reader_name FROM names)
            ),
            writer AS (
                SELECT * FROM pg_catalog.pg_roles
                WHERE rolname = (SELECT writer_name FROM names)
            ),
            relations AS (
                SELECT relation.oid, relation.relkind, owner_role.rolname AS owner
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                JOIN pg_catalog.pg_roles AS owner_role
                  ON owner_role.oid = relation.relowner
                WHERE namespace.nspname = (SELECT schema_name FROM names)
                  AND relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
            )
            SELECT
                (SELECT schema_name FROM names) AS schema_name,
                EXISTS (
                    SELECT 1 FROM pg_catalog.pg_namespace
                    WHERE nspname = (SELECT schema_name FROM names)
                ) AS schema_exists,
                (
                    SELECT owner_role.rolname
                    FROM pg_catalog.pg_namespace AS namespace
                    JOIN pg_catalog.pg_roles AS owner_role
                      ON owner_role.oid = namespace.nspowner
                    WHERE namespace.nspname = (SELECT schema_name FROM names)
                ) AS schema_owner,
                EXISTS (
                    SELECT 1 FROM pg_catalog.pg_roles
                    WHERE rolname = (SELECT reader_name FROM names)
                ) AS reader_exists,
                EXISTS (
                    SELECT 1 FROM pg_catalog.pg_roles
                    WHERE rolname = (SELECT writer_name FROM names)
                ) AS writer_exists,
                (SELECT count(*) FROM relations) AS relations,
                (
                    SELECT count(*) FROM relations
                    WHERE owner <> (SELECT writer_name FROM names)
                ) AS relations_not_owned_by_writer,
                -- CASE, not OR: SQL does not promise to short-circuit an OR, and
                -- has_table_privilege() errors outright on a role name that the
                -- restore never brought back.
                CASE
                    WHEN NOT EXISTS (SELECT 1 FROM reader)
                    THEN (SELECT count(*) FROM relations)
                    ELSE (
                        SELECT count(*) FROM relations
                        WHERE (
                            relations.relkind IN ('r', 'p', 'v', 'm', 'f')
                            AND NOT pg_catalog.has_table_privilege(
                                (SELECT oid FROM reader), relations.oid, 'SELECT'
                            )
                        )
                        OR (
                            relations.relkind = 'S'
                            AND NOT pg_catalog.has_sequence_privilege(
                                (SELECT oid FROM reader), relations.oid, 'SELECT'
                            )
                        )
                    )
                END AS relations_without_reader_select,
                -- Beyond SELECT is a write path: the sandbox and tile gateways
                -- SET ROLE to this reader. Read out of the ACL rather than
                -- named privilege by privilege, which grows by release.
                CASE
                    WHEN NOT EXISTS (SELECT 1 FROM reader) THEN 0
                    ELSE (
                        SELECT count(*) FROM relations
                        WHERE EXISTS (
                            SELECT 1
                            FROM pg_catalog.pg_class AS relation
                            JOIN LATERAL pg_catalog.aclexplode(relation.relacl)
                              AS acl ON true
                            WHERE relation.oid = relations.oid
                              AND acl.grantee = (SELECT oid FROM reader)
                              AND acl.privilege_type <> 'SELECT'
                              AND NOT (
                                  relations.relkind = 'S'
                                  AND acl.privilege_type = 'USAGE'
                              )
                        )
                    )
                END AS relations_with_reader_write,
                -- The pre-0019 runtime helper left an ALTER DEFAULT PRIVILEGES
                -- entry behind; ADOPT_TENANT_SQL revokes it, so a tenant still
                -- carrying one is not adopted however correct the rest looks.
                CASE
                    WHEN NOT EXISTS (SELECT 1 FROM reader) THEN 0
                    ELSE (
                        SELECT count(DISTINCT default_acl.oid)
                        FROM pg_catalog.pg_default_acl AS default_acl
                        JOIN LATERAL pg_catalog.aclexplode(default_acl.defaclacl)
                          AS acl ON true
                        JOIN pg_catalog.pg_namespace AS namespace
                          ON namespace.oid = default_acl.defaclnamespace
                        WHERE namespace.nspname = (SELECT schema_name FROM names)
                          AND default_acl.defaclobjtype = 'r'
                          AND acl.grantee = (SELECT oid FROM reader)
                    )
                END AS reader_default_acls,
                """
            + _role_secure_sql("reader", (PROVISIONER, SANDBOX, TILE), (SANDBOX, TILE))
            + " AS reader_role_secure, "
            + _role_secure_sql("writer", (PROVISIONER, WRITER), (WRITER,))
            + """ AS writer_role_secure,
                CASE
                    WHEN NOT EXISTS (
                        SELECT 1 FROM pg_catalog.pg_namespace
                        WHERE nspname = (SELECT schema_name FROM names)
                    ) OR NOT EXISTS (SELECT 1 FROM reader)
                      OR NOT EXISTS (SELECT 1 FROM writer)
                    THEN false
                    -- One privilege per call: a comma-separated list is an
                    -- any-of test, so 'USAGE, CREATE' stays true on a writer
                    -- that has lost one of them.
                    ELSE NOT pg_catalog.has_schema_privilege(
                             'public', (SELECT schema_name FROM names), 'USAGE'
                         )
                     AND NOT pg_catalog.has_schema_privilege(
                             'public', (SELECT schema_name FROM names), 'CREATE'
                         )
                     AND pg_catalog.has_schema_privilege(
                             (SELECT oid FROM reader),
                             (SELECT schema_name FROM names),
                             'USAGE'
                         )
                     -- The reader is the SET target of the sandbox and tile
                     -- gateways. CREATE there would let either of them build
                     -- objects in a schema meant to be read-only.
                     AND NOT pg_catalog.has_schema_privilege(
                             (SELECT oid FROM reader),
                             (SELECT schema_name FROM names),
                             'CREATE'
                         )
                     AND pg_catalog.has_schema_privilege(
                             (SELECT oid FROM writer),
                             (SELECT schema_name FROM names),
                             'USAGE'
                         )
                     AND pg_catalog.has_schema_privilege(
                             (SELECT oid FROM writer),
                             (SELECT schema_name FROM names),
                             'CREATE'
                         )
                END AS schema_privileges_secure
            """
        ),
        {"tenant_id": tenant_id},
    )
    row = result.one()
    return TenantOwnershipState(tenant_id=tenant_id, **dict(row._mapping))


# ---------------------------------------------------------------------------
# Adoption steps
# ---------------------------------------------------------------------------


async def ensure_cluster_roles(conn) -> None:
    """Create the fixed role topology if absent, and refuse an unsafe one."""
    await conn.execute(text(CLUSTER_ROLE_CREATE_SQL))
    await conn.execute(text(CLUSTER_ROLE_VALIDATE_SQL))
    await conn.execute(text(PROVISIONER_DATABASE_GRANT_SQL))
    await conn.execute(text(f"GRANT USAGE ON SCHEMA catalog TO {PROVISIONER}"))
    await conn.execute(text(f"GRANT SELECT ON TABLE catalog.tenants TO {PROVISIONER}"))


async def secure_boundary_functions(conn) -> list[BoundaryFunctionState]:
    """Re-own and re-restrict the two functions a restore left wide open.

    The bodies belong to the migrations and are never rewritten here.  What a
    ``pg_restore --no-owner --no-acl`` strips is the owner and the ACL, and the
    PostgreSQL default for a function with no ACL is ``EXECUTE`` to ``PUBLIC``.
    A SECURITY DEFINER function owned by the restoring superuser and callable by
    everyone is the state this repairs.
    """
    states = {state.name: state for state in await boundary_function_states(conn)}
    missing = [name for name in BOUNDARY_FUNCTIONS if name not in states]
    if missing:
        raise RuntimeError(
            "Tenant boundary function(s) missing from schema catalog: "
            f"{', '.join(missing)}. Adoption repairs ownership at the current "
            "head schema; it does not install function bodies. Run "
            "`alembic upgrade heads` against this database first."
        )
    for name, state in states.items():
        reason = unexpected_shape(state)
        if reason is not None:
            raise RuntimeError(
                f"catalog.{name}(uuid) {reason}. This is not the shape the "
                "migrations install; refusing to give it to "
                f"{PROVISIONER} or to grant {CONTROL} execution on it."
            )

    await conn.execute(text(SECURE_BOUNDARY_FUNCTIONS_SQL))
    return await boundary_function_states(conn)


async def release_bootstrap_membership(engine) -> None:
    """Give back the provisioner membership a fresh-cluster run had to take.

    Leaving it would make the next recovery depend on the same migrator
    credential, because the cluster guard rejects every direct member of the
    provisioner except the role running it.  A no-op unless this run created the
    role and granted itself the edge.
    """
    async with engine.begin() as conn:
        await conn.execute(text(RELEASE_BOOTSTRAP_MEMBERSHIP_SQL))


async def adopt_tenant(conn, tenant_id: str) -> None:
    """Move one tenant's schema, roles, and relations under the boundary."""
    normalized = str(uuid.UUID(tenant_id))
    await conn.execute(
        text("SELECT set_config(:guc, :tenant_id, true)"),
        {"guc": TENANT_GUC, "tenant_id": normalized},
    )
    await conn.execute(text(ADOPT_TENANT_SQL))


async def run_adoption(engine, *, apply: bool) -> AdoptionReport:
    """Report the ownership gap and, with ``apply``, close it."""
    topology = await cluster_topology_error(engine)
    async with engine.connect() as conn:
        tenants = await list_tenants(conn)
        before = [await tenant_ownership_state(conn, tid) for tid in tenants]
        boundary = await live_tenant_boundary(conn)
        functions = await boundary_function_states(conn)
        grants = [] if topology else await missing_provisioner_grants(conn)
        stamping = await stamping_function_shape(conn)

    if not apply:
        return AdoptionReport(
            applied=False,
            functions=functions,
            boundary=boundary,
            before=before,
            after=before,
            failures={},
            cluster_topology=topology,
            provisioner_grants_missing=grants,
            stamping_function=stamping,
        )

    async with engine.begin() as conn:
        await ensure_cluster_roles(conn)
        functions = await secure_boundary_functions(conn)

    failures: dict[str, str] = {}
    for tenant_id in tenants:
        try:
            async with engine.begin() as conn:
                await adopt_tenant(conn, tenant_id)
        except Exception as exc:  # broad: one tenant's refusal must not strand the rest
            failures[tenant_id] = str(exc).strip().splitlines()[0]
            logger.error(
                "tenant_adoption: tenant failed", tenant_id=tenant_id, exc_info=True
            )

    await release_bootstrap_membership(engine)

    topology = await cluster_topology_error(engine)
    async with engine.connect() as conn:
        after = [await tenant_ownership_state(conn, tid) for tid in tenants]
        boundary = await live_tenant_boundary(conn)
        grants = [] if topology else await missing_provisioner_grants(conn)
        stamping = await stamping_function_shape(conn)

    return AdoptionReport(
        applied=True,
        functions=functions,
        boundary=boundary,
        before=before,
        after=after,
        failures=failures,
        cluster_topology=topology,
        provisioner_grants_missing=grants,
        stamping_function=stamping,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.core.db.tenant_adoption",
        description=(
            "Reconstruct tenant schema/role ownership at the current head "
            "schema, without the destructive downgrade to 0016 (#998)."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the adoption. Without it the run only reports the gap.",
    )
    parser.epilog = (
        "Exit codes: 0 nothing left to do; 1 work is pending or a tenant "
        "failed; 2 refused before touching any tenant."
    )
    return parser


async def _main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import settings

    engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args=settings.database_connect_args,
    )
    try:
        report = await run_adoption(engine, apply=args.apply)
    except (
        Exception
    ) as exc:  # broad: an operator mid-recovery needs the reason, not a traceback
        logger.error("tenant_adoption: refused", exc_info=True)
        reason = str(exc).strip().splitlines()[0]
        print(f"Tenant-ownership adoption refused before any tenant: {reason}")
        return 2
    finally:
        await engine.dispose()

    print(format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
