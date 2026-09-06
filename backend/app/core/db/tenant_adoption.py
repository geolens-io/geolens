"""Forward-only tenant-ownership adoption at the current schema head.

Reconstructs the ownership migration ``0019_tenant_provisioning_boundary``
installs, against the **current head schema**, so a restored dump never needs
``alembic downgrade 0016`` to reach the least-privilege provisioning boundary.

Function bodies belong to the migrations and are never installed here.
Adoption verifies both boundary functions are present, ``SECURITY DEFINER`` and
``search_path``-pinned, and repairs the owner and the ACL that ``pg_restore
--no-owner --no-acl`` strips: PostgreSQL's default function ACL is ``EXECUTE``
to ``PUBLIC``, so a restored ``catalog.provision_tenant_data_schema`` is a
SECURITY DEFINER function owned by the restoring superuser and callable by
every login in the database.

Idempotence is keyed on database state, never on a marker or a timestamp: each
step reads what the cluster currently holds and issues DDL only for the gap.
Every tenant is adopted in its own transaction, so a run interrupted partway is
resumed by running it again.

Adoption rewrites only the grants it is itself the grantor of.  Any other
anomaly is reported with the exact statement to run and the role to run it as,
and the tenant is left for the next run.  See the repair boundary in
:mod:`app.core.db.tenant_adoption_sql`.

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
    PROVISIONER_DATABASE_REVOKE_OPTION_SQL,
    PROVISIONER_GRANT_OPTION_GUARD_SQL,
    RELEASE_PROVISIONER_EDGE_SQL,
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

    The boundary is whatever currently carries 0018's insert-stamping trigger,
    so an enumeration copied from a migration is stale the moment a table
    joins.  Tables holding a ``tenant_id`` column *without* the trigger are
    reported too, so a deliberately dormant column (0037's
    ``dataset_refresh_runs``) and an accidental one are told apart on purpose
    rather than by omission.
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
                               -- An overload under the same name would make
                               -- this scalar subquery return two rows and fail
                               -- the whole read; the trigger function takes no
                               -- arguments.
                               AND routine.pronargs = 0
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
                   -- ...and the only policy of any kind. PostgreSQL ORs
                   -- permissive policies, so a second `USING (true)` beside the
                   -- canonical rule returns every tenant's rows with RLS fully
                   -- enabled; it ANDs restrictive ones, so an added
                   -- `USING (false)` denies everything. Neither is what the
                   -- migrations install and neither is repaired at boot.
                   (
                       SELECT count(*) FROM pg_catalog.pg_policy AS policy
                       WHERE policy.polrelid = relation.oid
                   ) = 1
                   AND EXISTS (
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


#: ``prosrc`` with SQL comments removed: a substituted body could otherwise
#: carry the markers below in a comment and satisfy the check while executing
#: something else.  Structural, not provenance — see ``migration_shaped``.
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
                   -- Exactly that one setting: an extra proconfig entry such
                   -- as `SET role` changes what a SECURITY DEFINER body runs
                   -- as, and it would sit beside a correct search_path.
                   COALESCE(
                       routine.proconfig = ARRAY['search_path=pg_catalog'], false
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
                   -- A direct EXECUTE to a named role survives REVOKE … FROM
                   -- PUBLIC, and lets that role call provisioner-owned tenant
                   -- management.
                   (
                       SELECT count(DISTINCT grantee_role.rolname)
                       FROM LATERAL pg_catalog.aclexplode(routine.proacl) AS acl
                       JOIN pg_catalog.pg_roles AS grantee_role
                         ON grantee_role.oid = acl.grantee
                       WHERE grantee_role.rolname NOT IN (:provisioner, :control)
                          -- A grantable EXECUTE lets a control-role member
                          -- delegate provisioner-owned tenant management to
                          -- anyone; the canonical grant is plain.
                          OR (grantee_role.rolname = :control AND acl.is_grantable)
                   ) AS unexpected_grantees,
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
              -- A procedure with the same signature is not callable where the
              -- runtime calls these, so it is not one of them.
              AND routine.prokind = 'f'
            ORDER BY routine.proname
            """
        ),
        {
            "control": CONTROL,
            "provisioner": PROVISIONER,
            "names": list(BOUNDARY_FUNCTIONS),
        },
    )
    return [BoundaryFunctionState(**dict(row._mapping)) for row in result]


async def stamping_function_shape(conn) -> str | None:
    """Why ``catalog.stamp_current_tenant_on_insert`` is not 0018's, if it is not.

    A trigger pointing at this name proves nothing on its own: a body that
    returns ``NEW`` untouched lands every insert tenantless while every
    structural check passes.  Same structural limits as
    ``BoundaryFunctionState.migration_shaped``.
    """
    result = await conn.execute(
        text(
            f"""
            SELECT language.lanname AS language,
                   pg_catalog.pg_get_userbyid(routine.proowner) AS owner,
                   -- Owned by a role this credential is not, cannot assume, and
                   -- that is not a superuser: a body firing on every
                   -- control-plane insert, rewritable by a third party.
                   (
                       pg_catalog.pg_has_role(
                           CURRENT_USER, routine.proowner, 'USAGE'
                       )
                       OR EXISTS (
                           SELECT 1 FROM pg_catalog.pg_roles AS owner_role
                           WHERE owner_role.oid = routine.proowner
                             AND owner_role.rolsuper
                       )
                   ) AS owner_reachable,
                   routine.prosecdef AS security_definer,
                   routine.prorettype = 'trigger'::regtype AS returns_trigger,
                   COALESCE(
                       routine.proconfig = ARRAY[:stamping_search_path], false
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
              AND routine.prokind = 'f'
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
    if not row.owner_reachable:
        return (
            f"catalog.{BOUNDARY_TRIGGER_FUNCTION}() is owned by {row.owner}, a "
            "role this credential cannot assume — it fires on every "
            "control-plane insert and its owner can rewrite it"
        )
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
    creates anything.  A raise aborts the transaction, so it gets a connection
    of its own.
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(text(CLUSTER_ROLE_VALIDATE_SQL))
    except Exception as exc:  # broad: any refusal is the answer, whatever its class
        return _failure_message(exc)
    return None


async def missing_provisioner_grants(conn) -> list[str]:
    """Object privileges ``ensure_cluster_roles`` grants and a restore drops.

    Without them ``catalog.provision_tenant_data_schema`` cannot see
    ``catalog.tenants`` or create a tenant schema.  Call only once
    :func:`cluster_topology_error` has confirmed the role exists — the
    ``has_*_privilege`` family errors on a role name that is not there.
    """
    result = await conn.execute(
        text(
            """
            WITH owner AS (
                SELECT oid FROM pg_catalog.pg_roles WHERE rolname = :provisioner
            ),
            grantable AS (
                SELECT 'database_create' AS grant_key
                FROM pg_catalog.pg_database AS db
                JOIN LATERAL pg_catalog.aclexplode(db.datacl) AS acl ON true
                WHERE db.datname = pg_catalog.current_database()
                  AND acl.grantee = (SELECT oid FROM owner)
                  AND acl.privilege_type = 'CREATE'
                  AND acl.is_grantable
                UNION ALL
                SELECT 'catalog_usage'
                FROM pg_catalog.pg_namespace AS namespace
                JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl ON true
                WHERE namespace.nspname = 'catalog'
                  AND acl.grantee = (SELECT oid FROM owner)
                  AND acl.privilege_type = 'USAGE'
                  AND acl.is_grantable
                UNION ALL
                SELECT 'tenants_select'
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl ON true
                WHERE namespace.nspname = 'catalog'
                  AND relation.relname = 'tenants'
                  AND acl.grantee = (SELECT oid FROM owner)
                  AND acl.privilege_type = 'SELECT'
                  AND acl.is_grantable
            )
            SELECT pg_catalog.has_database_privilege(
                       :provisioner, pg_catalog.current_database(), 'CREATE'
                   ) AS database_create,
                   pg_catalog.has_schema_privilege(
                       :provisioner, 'catalog', 'USAGE'
                   ) AS catalog_usage,
                   pg_catalog.has_table_privilege(
                       :provisioner, 'catalog.tenants', 'SELECT'
                   ) AS tenants_select,
                   ARRAY(SELECT grant_key FROM grantable) AS grantable_keys
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
    findings = [label for key, label in labels.items() if not getattr(row, key)]
    # The provisioner is reachable only through SECURITY DEFINER functions, so a
    # grantable privilege there is a delegation nothing else would notice.
    findings += [
        f"{labels[key]} is grantable" for key in row.grantable_keys if key in labels
    ]
    return findings


async def list_tenants(conn) -> list[str]:
    """Every tenant id in the control plane, in a stable order."""
    result = await conn.execute(
        text("SELECT id::text FROM catalog.tenants ORDER BY id")
    )
    return [row[0] for row in result]


#: ``inherit_option``/``set_option`` arrived in PostgreSQL 16 and GeoLens
#: supports 13 up, so they are read back out of the row as jsonb.  Before 16
#: ``admin_option`` alone is correct: NOINHERIT gateway roles are SET-only.
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
    ``catalog.provision_tenant_data_schema``, so a dry run cannot call a
    topology adopted that ``--apply`` would reject or repair.  Effective
    privileges are not enough on their own: a reader carrying ``SUPERUSER``
    satisfies every ``has_table_privilege`` check by fiat.

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
                    -- DISTINCT on the member: two canonical grants of the same
                    -- gateway from different grantors are two rows, and a plain
                    -- count would let them stand in for a gateway that is
                    -- missing its grant entirely.
                    AND (
                        SELECT count(DISTINCT member_role.rolname)
                        FROM pg_catalog.pg_auth_members AS membership
                        JOIN pg_catalog.pg_roles AS member_role
                          ON member_role.oid = membership.member
                        WHERE membership.roleid = (SELECT oid FROM {role_cte})
                          AND member_role.rolname IN ({gateway_names})
                          AND NOT membership.admin_option
                          AND {_MEMBER_SET_ONLY}
                    ) = {len(gateways)}
                    -- Counting the good rows is not enough: PostgreSQL allows a
                    -- second grant of the same role to the same member from a
                    -- different grantor, and one carrying INHERIT or ADMIN would
                    -- sit beside the canonical row undetected. The gateway would
                    -- then hold the tenant role's privileges outright instead of
                    -- having to SET ROLE for them.
                    AND NOT EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_auth_members AS membership
                        JOIN pg_catalog.pg_roles AS member_role
                          ON member_role.oid = membership.member
                        WHERE membership.roleid = (SELECT oid FROM {role_cte})
                          AND member_role.rolname IN ({gateway_names})
                          AND NOT (
                              NOT membership.admin_option AND {_MEMBER_SET_ONLY}
                          )
                    )
                    AND NOT EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_auth_members AS membership
                        JOIN pg_catalog.pg_roles AS member_role
                          ON member_role.oid = membership.member
                        WHERE membership.roleid = (SELECT oid FROM {role_cte})
                          AND member_role.rolname = '{PROVISIONER}'
                          AND NOT (membership.admin_option AND {_MEMBER_ADMIN_ONLY})
                    )
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
                -- Routines live in pg_proc, so none of the relation reads see
                -- them. A restore brings one back owned by the restore login
                -- with PUBLIC EXECUTE; a SECURITY DEFINER one is refused
                -- outright rather than re-owned.
                CASE
                    WHEN NOT EXISTS (SELECT 1 FROM reader) THEN 0
                    ELSE (
                        SELECT count(*)
                        FROM pg_catalog.pg_proc AS routine
                        JOIN pg_catalog.pg_namespace AS namespace
                          ON namespace.oid = routine.pronamespace
                        WHERE namespace.nspname = (SELECT schema_name FROM names)
                          AND (
                              routine.proowner IS DISTINCT FROM (
                                  SELECT oid FROM writer
                              )
                              OR routine.prosecdef
                              OR NOT EXISTS (
                                  -- prokind 'a' names the `internal`
                                  -- pseudo-language and says nothing about the
                                  -- functions that run.
                                  SELECT 1 FROM pg_catalog.pg_language AS language
                                  WHERE language.oid = routine.prolang
                                    AND (
                                        language.lanpltrusted
                                        OR routine.prokind = 'a'
                                    )
                              )
                              OR pg_catalog.has_function_privilege(
                                  'public', routine.oid, 'EXECUTE'
                              )
                              OR NOT pg_catalog.has_function_privilege(
                                  (SELECT oid FROM reader), routine.oid, 'EXECUTE'
                              )
                              -- The ACL itself, matching what --apply rewrites:
                              -- a named grantee, or a grantable reader entry.
                              OR EXISTS (
                                  SELECT 1
                                  FROM LATERAL pg_catalog.aclexplode(routine.proacl)
                                    AS acl
                                  WHERE acl.grantee NOT IN (
                                      COALESCE((SELECT oid FROM writer), 0),
                                      (SELECT oid FROM reader)
                                  )
                                  OR (
                                      acl.grantee = (SELECT oid FROM reader)
                                      AND acl.is_grantable
                                  )
                              )
                          )
                    )
                END AS unsafe_routines,
                -- Types a tenant defined live in pg_type, so the relation reads
                -- miss them, and a writer that cannot alter one cannot replace
                -- the dataset using it.
                (
                    SELECT count(*)
                    FROM pg_catalog.pg_type AS type_row
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = type_row.typnamespace
                    WHERE namespace.nspname = (SELECT schema_name FROM names)
                      AND type_row.typowner IS DISTINCT FROM (
                          SELECT oid FROM writer
                      )
      -- Array types follow their element type, a table's row type follows the
      -- table, and a range's generated multirange follows the range (14+):
      -- all move on their own, and ALTER TYPE on the multirange directly is
      -- refused (fix(#998 codex r46)). An extension's types belong to the
      -- extension.
      AND NOT EXISTS (
          SELECT 1 FROM pg_catalog.pg_type AS element
          WHERE element.typarray = type_row.oid
      )
      AND NOT EXISTS (
          SELECT 1 FROM pg_catalog.pg_range AS range_type
          WHERE range_type.rngmultitypid = type_row.oid
      )
      AND (
          type_row.typrelid = 0
          OR EXISTS (
              SELECT 1 FROM pg_catalog.pg_class AS relation
              WHERE relation.oid = type_row.typrelid AND relation.relkind = 'c'
          )
      )
      AND NOT EXISTS (
          SELECT 1 FROM pg_catalog.pg_depend AS dependency
          WHERE dependency.classid = 'pg_type'::regclass
            AND dependency.objid = type_row.oid
            AND dependency.deptype = 'e'
      )
                ) AS unsafe_types,
                -- fix(#998 codex r48): extended statistics are schema objects
                -- with an owner of their own; the writer must be able to
                -- ALTER and DROP them.
                (
                    SELECT count(*)
                    FROM pg_catalog.pg_statistic_ext AS statistics_row
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = statistics_row.stxnamespace
                    WHERE namespace.nspname = (SELECT schema_name FROM names)
                      AND statistics_row.stxowner IS DISTINCT FROM (
                          SELECT oid FROM writer
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM pg_catalog.pg_depend AS dependency
                          WHERE dependency.classid
                                = 'pg_statistic_ext'::regclass
                            AND dependency.objid = statistics_row.oid
                            AND dependency.deptype = 'e'
                      )
                ) AS unsafe_statistics,
                -- fix(#998 codex r49): collations, transferred like types and
                -- statistics; the six rarer owned kinds --apply refuses.
                (
                    SELECT count(*)
                    FROM pg_catalog.pg_collation AS collation_row
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = collation_row.collnamespace
                    WHERE namespace.nspname = (SELECT schema_name FROM names)
                      AND collation_row.collowner IS DISTINCT FROM (
                          SELECT oid FROM writer
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM pg_catalog.pg_depend AS dependency
                          WHERE dependency.classid = 'pg_collation'::regclass
                            AND dependency.objid = collation_row.oid
                            AND dependency.deptype = 'e'
                      )
                ) AS unsafe_collations,
                (
                    SELECT count(*)
                    FROM (
                        SELECT conversion.oid,
                               'pg_conversion'::regclass AS classid,
                               conversion.connamespace AS namespace_oid,
                               conversion.conowner AS owner_oid
                        FROM pg_catalog.pg_conversion AS conversion
                        UNION ALL
                        SELECT operator.oid, 'pg_operator'::regclass,
                               operator.oprnamespace, operator.oprowner
                        FROM pg_catalog.pg_operator AS operator
                        UNION ALL
                        SELECT opclass.oid, 'pg_opclass'::regclass,
                               opclass.opcnamespace, opclass.opcowner
                        FROM pg_catalog.pg_opclass AS opclass
                        UNION ALL
                        SELECT opfamily.oid, 'pg_opfamily'::regclass,
                               opfamily.opfnamespace, opfamily.opfowner
                        FROM pg_catalog.pg_opfamily AS opfamily
                        UNION ALL
                        SELECT dictionary.oid, 'pg_ts_dict'::regclass,
                               dictionary.dictnamespace, dictionary.dictowner
                        FROM pg_catalog.pg_ts_dict AS dictionary
                        UNION ALL
                        SELECT config.oid, 'pg_ts_config'::regclass,
                               config.cfgnamespace, config.cfgowner
                        FROM pg_catalog.pg_ts_config AS config
                    ) AS owned_object
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = owned_object.namespace_oid
                    WHERE namespace.nspname = (SELECT schema_name FROM names)
                      AND owned_object.owner_oid IS DISTINCT FROM (
                          SELECT oid FROM writer
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM pg_catalog.pg_depend AS dependency
                          WHERE dependency.classid = owned_object.classid
                            AND dependency.objid = owned_object.oid
                            AND dependency.deptype = 'e'
                      )
                ) AS unowned_other_objects,
                -- The same four surfaces the apply side refuses on, counted
                -- here so the dry run cannot call a tenant adopted that
                -- `--apply` would stop on.
                (
                    SELECT count(*)
                    FROM (
            SELECT 'schema ' || namespace.nspname AS object_name,
                   acl.grantor AS grantor_oid
            FROM pg_catalog.pg_namespace AS namespace
            JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl ON true
            WHERE namespace.nspname = (SELECT schema_name FROM names)
              AND acl.grantor <> COALESCE((SELECT oid FROM pg_catalog.pg_roles WHERE rolname = :provisioner), 0)
            UNION ALL
            SELECT 'relation ' || relation.relname, acl.grantor
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl ON true
            WHERE namespace.nspname = (SELECT schema_name FROM names)
              AND acl.grantor <> COALESCE((SELECT oid FROM writer), 0)
            UNION ALL
            SELECT 'column ' || relation.relname || '.' || column_row.attname,
                   acl.grantor
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            JOIN pg_catalog.pg_attribute AS column_row
              ON column_row.attrelid = relation.oid
            JOIN LATERAL pg_catalog.aclexplode(column_row.attacl) AS acl ON true
            WHERE namespace.nspname = (SELECT schema_name FROM names)
              AND NOT column_row.attisdropped
              AND acl.grantor <> COALESCE((SELECT oid FROM writer), 0)
            UNION ALL
            SELECT 'routine ' || routine.proname, acl.grantor
            FROM pg_catalog.pg_proc AS routine
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = routine.pronamespace
            JOIN LATERAL pg_catalog.aclexplode(routine.proacl) AS acl ON true
            WHERE namespace.nspname = (SELECT schema_name FROM names)
              AND acl.grantor <> COALESCE((SELECT oid FROM writer), 0)
                    ) AS foreign_grant
                ) AS foreign_grantors,
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
                            -- Column grants live in pg_attribute, and a
                            -- table-level REVOKE ALL does not clear them.
                            SELECT 1
                            FROM pg_catalog.pg_attribute AS column_row
                            JOIN LATERAL
                              pg_catalog.aclexplode(column_row.attacl) AS acl
                              ON true
                            WHERE column_row.attrelid = relations.oid
                              AND NOT column_row.attisdropped
                              AND acl.grantee IS DISTINCT FROM (
                                  SELECT oid FROM writer
                              )
                        )
                        OR EXISTS (
                            SELECT 1
                            FROM pg_catalog.pg_class AS relation
                            JOIN LATERAL pg_catalog.aclexplode(relation.relacl)
                              AS acl ON true
                            WHERE relation.oid = relations.oid
                              AND (
                                  -- Anything but the owning writer and the
                                  -- reader. Grantee 0 is PUBLIC, which the
                                  -- reader holds along with everyone else who
                                  -- can reach the schema; a named role with its
                                  -- own grant reads tenant data without going
                                  -- near either tenant role.
                                  acl.grantee NOT IN (
                                      COALESCE((SELECT oid FROM writer), 0),
                                      (SELECT oid FROM reader)
                                  )
                                  -- Grantable SELECT lets a gateway that SET
                                  -- ROLEs to the reader hand tenant reads to
                                  -- any role it likes.
                                  OR (
                                      acl.grantee = (SELECT oid FROM reader)
                                      AND acl.is_grantable
                                  )
                                  OR (
                                      acl.grantee = (SELECT oid FROM reader)
                                      AND acl.privilege_type <> 'SELECT'
                                      AND NOT (
                                          relations.relkind = 'S'
                                          AND acl.privilege_type = 'USAGE'
                                      )
                                  )
                              )
                        )
                    )
                END AS relations_with_unsafe_acl,
                -- The pre-0019 runtime helper left an ALTER DEFAULT PRIVILEGES
                -- entry behind; ADOPT_TENANT_SQL revokes it, so a tenant still
                -- carrying one is not adopted however correct the rest looks.
                -- Any of them, for any object kind and any grantee: the
                -- contract in a tenant schema is that the writer grants the
                -- reader explicitly on each relation, so a default ACL here
                -- hands out privileges on relations that do not exist yet, to
                -- whoever it names.
                -- fix(#998 codex r47): schema-less entries (defaclnamespace 0)
                -- owned by the tenant pair or the provisioner apply to every
                -- schema they create in; --apply refuses them, so the dry run
                -- must count them or call adopted what --apply would stop on.
                (
                    SELECT count(*)
                    FROM pg_catalog.pg_default_acl AS default_acl
                    LEFT JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = default_acl.defaclnamespace
                    WHERE namespace.nspname = (SELECT schema_name FROM names)
                       OR (
                           default_acl.defaclnamespace = 0
                           AND default_acl.defaclrole IN (
                               (SELECT oid FROM reader),
                               (SELECT oid FROM writer),
                               (
                                   SELECT oid FROM pg_catalog.pg_roles
                                   WHERE rolname = :provisioner
                               )
                           )
                       )
                ) AS unexpected_default_acls,
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
                    ELSE NOT EXISTS (
                             -- Nobody outside the three belongs on the schema.
                             -- A stray USAGE plus a relation grant, or a stray
                             -- CREATE, is a path around the writer boundary.
                             SELECT 1
                             FROM pg_catalog.pg_namespace AS namespace
                             JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl)
                               AS acl ON true
                             WHERE namespace.nspname = (
                                 SELECT schema_name FROM names
                             )
                               AND (
                                   acl.grantee NOT IN (
                                       COALESCE((SELECT oid FROM reader), 0),
                                       COALESCE((SELECT oid FROM writer), 0),
                                       COALESCE(
                                           (
                                               SELECT oid FROM pg_catalog.pg_roles
                                               WHERE rolname = :provisioner
                                           ),
                                           0
                                       )
                                   )
                                   -- Same delegation problem one level up: a
                                   -- grantable USAGE on the schema travels with
                                   -- a grantable SELECT on the relations.
                                   OR (
                                       acl.is_grantable
                                       AND acl.grantee <> COALESCE(
                                           (
                                               SELECT oid FROM pg_catalog.pg_roles
                                               WHERE rolname = :provisioner
                                           ),
                                           0
                                       )
                                   )
                               )
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
        {"tenant_id": tenant_id, "provisioner": PROVISIONER},
    )
    row = result.one()
    return TenantOwnershipState(tenant_id=tenant_id, **dict(row._mapping))


# ---------------------------------------------------------------------------
# Adoption steps
# ---------------------------------------------------------------------------


async def _holds_provisioner_privileges(conn) -> bool:
    result = await conn.execute(
        text("SELECT pg_catalog.pg_has_role(CURRENT_USER, :owner, 'USAGE')"),
        {"owner": PROVISIONER},
    )
    return bool(result.scalar_one())


async def ensure_cluster_roles(conn) -> bool:
    """Create the fixed role topology if absent, and refuse an unsafe one.

    Returns whether *this* run had to take a usable membership in the
    provisioner, which is what decides whether the run gives one back.  A
    membership an operator granted by hand is left alone: revoking somebody
    else's grant is not this tool's business.
    """
    held_before = await _holds_provisioner_privileges(conn)
    await conn.execute(text(CLUSTER_ROLE_CREATE_SQL))
    await conn.execute(text(CLUSTER_ROLE_VALIDATE_SQL))
    await conn.execute(text(PROVISIONER_DATABASE_GRANT_SQL))
    await conn.execute(text(f"GRANT USAGE ON SCHEMA catalog TO {PROVISIONER}"))
    await conn.execute(text(f"GRANT SELECT ON TABLE catalog.tenants TO {PROVISIONER}"))
    # fix(#998): a grantable entry some third role issued survives the plain revokes
    # below; refuse it with the grantor named before pretending to rewrite it.
    await conn.execute(text(PROVISIONER_GRANT_OPTION_GUARD_SQL))
    # A re-GRANT adds the privilege and leaves an existing GRANT OPTION alone.
    # These are no-ops on a database that never had one.
    await conn.execute(
        text(f"REVOKE GRANT OPTION FOR USAGE ON SCHEMA catalog FROM {PROVISIONER}")
    )
    await conn.execute(
        text(
            "REVOKE GRANT OPTION FOR SELECT ON TABLE catalog.tenants "
            f"FROM {PROVISIONER}"
        )
    )
    await conn.execute(text(PROVISIONER_DATABASE_REVOKE_OPTION_SQL))
    return not held_before and await _holds_provisioner_privileges(conn)


async def secure_boundary_functions(conn) -> list[BoundaryFunctionState]:
    """Re-own and re-restrict the two functions a restore left wide open.

    The bodies belong to the migrations and are never rewritten here.  What
    ``pg_restore --no-owner --no-acl`` strips is the owner and the ACL, and the
    PostgreSQL default for a function with no ACL is ``EXECUTE`` to ``PUBLIC``,
    so the state this repairs is a SECURITY DEFINER function owned by the
    restoring superuser and callable by everyone.
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


async def release_bootstrap_membership(engine, *, took_provisioner_edge: bool) -> None:
    """Give back the usable membership a fresh-cluster run had to take.

    Only that one.  The automatic ADMIN membership PostgreSQL gives a role's
    creator is tolerated by the guards instead of revoked, because a member
    cannot revoke it — its grantor is the bootstrap superuser, and on a managed
    provider no customer role can assume that.

    From PostgreSQL 16 this runs whatever the flag says: the predicate — granted
    by the current role, carrying no ADMIN — describes the edge adoption takes
    and nothing an operator would set up by hand, so running it unconditionally
    also recovers one a previous run was killed before returning.  Before 16
    there is a single row per pair and no way to tell those apart, so there the
    flag is the only evidence there is.
    """
    async with engine.begin() as conn:
        modern = await conn.execute(
            text("SELECT current_setting('server_version_num')::integer >= 160000")
        )
        if took_provisioner_edge or modern.scalar_one():
            await conn.execute(text(RELEASE_PROVISIONER_EDGE_SQL))


async def adopt_tenant(conn, tenant_id: str) -> None:
    """Move one tenant's schema, roles, and relations under the boundary."""
    normalized = str(uuid.UUID(tenant_id))
    await conn.execute(
        text("SELECT set_config(:guc, :tenant_id, true)"),
        {"guc": TENANT_GUC, "tenant_id": normalized},
    )
    await conn.execute(text(ADOPT_TENANT_SQL))


def _failure_message(exc: BaseException) -> str:
    """One line, plus the remediation PostgreSQL attached to it.

    The refusals this module raises carry the exact statement to run and the
    role to run it as in the exception's HINT, and the driver leaves that out of
    ``str(exc)``.  Dropping it would report a tenant as incomplete without
    saying what to do about it.
    """
    message = str(exc).strip().splitlines()[0]
    cause: BaseException | None = exc
    while cause is not None:
        hint = getattr(cause, "hint", None)
        if hint:
            return f"{message} — {hint}"
        cause = cause.__cause__
    return message


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
        took_provisioner_edge = await ensure_cluster_roles(conn)
        functions = await secure_boundary_functions(conn)

    failures: dict[str, str] = {}
    try:
        for tenant_id in tenants:
            try:
                async with engine.begin() as conn:
                    await adopt_tenant(conn, tenant_id)
            except (
                Exception
            ) as exc:  # broad: one tenant's refusal must not strand the rest
                failures[tenant_id] = _failure_message(exc)
                logger.error(
                    "tenant_adoption: tenant failed", tenant_id=tenant_id, exc_info=True
                )
    finally:
        # A bare finally, so a Ctrl-C (CancelledError, a BaseException) hands
        # the edge back too. From PostgreSQL 16 even a SIGKILL is recoverable:
        # the next run releases the edge whether or not it took one.
        await release_bootstrap_membership(
            engine, took_provisioner_edge=took_provisioner_edge
        )

    topology = await cluster_topology_error(engine)
    async with engine.connect() as conn:
        # Re-read rather than reuse the pre-apply list: a tenant provisioned
        # while this ran was never adopted, and reporting only the snapshot
        # would call the database clean without having looked at it.
        tenants_after = await list_tenants(conn)
        after = [await tenant_ownership_state(conn, tid) for tid in tenants_after]
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
        tenants_added_during_run=sorted(set(tenants_after) - set(tenants)),
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
        reason = _failure_message(exc)
        print(f"Tenant-ownership adoption refused before any tenant: {reason}")
        return 2
    finally:
        await engine.dispose()

    print(format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
