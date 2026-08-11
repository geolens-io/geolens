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

Run it with the migrator credential (``CREATEROLE``, plus authority over the
restored objects), against a database already at head::

    docker compose run --rm --no-deps -e DATABASE_URL_OVERRIDE="<migrator-url>" \\
      migrate sh -c "uv run --no-dev python -m app.core.db.tenant_adoption --apply"

Without ``--apply`` the run is a read-only report of what adoption would change.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from dataclasses import dataclass, field

import structlog
from sqlalchemy import text

from app.core.db.rls import RLS_TABLES
from app.core.db.tenant_adoption_sql import (
    ADOPT_TENANT_SQL,
    CLUSTER_ROLE_CREATE_SQL,
    CLUSTER_ROLE_VALIDATE_SQL,
    CONTROL,
    PROVISIONER,
    PROVISIONER_DATABASE_GRANT_SQL,
    SANDBOX,
    TENANT_GUC,
    TILE,
    WRITER,
)

logger = structlog.stdlib.get_logger(__name__)

#: The two migration-owned SECURITY DEFINER entry points.  Adoption verifies and
#: re-secures them; it never rewrites their bodies.
BOUNDARY_FUNCTIONS = (
    "provision_tenant_data_schema",
    "deprovision_tenant_data_schema",
)

#: The insert-stamping trigger 0018 installs.  Its presence — not any constant
#: frozen into a migration — is what marks a table as tenant-scoped.
BOUNDARY_TRIGGER = "trg_stamp_current_tenant_on_insert"


# ---------------------------------------------------------------------------
# Report types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoundaryFunctionState:
    """Live state of one migration-owned SECURITY DEFINER entry point."""

    name: str
    owner: str
    security_definer: bool
    search_path_pinned: bool
    public_execute: bool
    control_execute: bool

    @property
    def secured(self) -> bool:
        return (
            self.owner == PROVISIONER
            and self.security_definer
            and self.search_path_pinned
            and not self.public_execute
            and self.control_execute
        )


@dataclass(frozen=True)
class TenantOwnershipState:
    """Live ownership state of one tenant's data plane."""

    tenant_id: str
    schema_name: str
    schema_exists: bool
    schema_owner: str | None
    reader_exists: bool
    writer_exists: bool
    relations: int
    relations_not_owned_by_writer: int
    relations_without_reader_select: int
    reader_default_acls: int
    reader_role_secure: bool
    writer_role_secure: bool
    schema_privileges_secure: bool

    @property
    def adopted(self) -> bool:
        """Every invariant ``--apply`` enforces, not just the visible ones.

        Ownership and effective privileges alone would call a reader carrying
        ``LOGIN``/``SUPERUSER``/``BYPASSRLS`` adopted — a superuser satisfies the
        ``SELECT`` check by fiat — and would miss a stray member or a missing
        gateway edge, both of which ``ADOPT_TENANT_SQL`` refuses or repairs.
        """
        return (
            self.schema_exists
            and self.schema_owner == PROVISIONER
            and self.reader_exists
            and self.writer_exists
            and self.relations_not_owned_by_writer == 0
            and self.relations_without_reader_select == 0
            and self.reader_default_acls == 0
            and self.reader_role_secure
            and self.writer_role_secure
            and self.schema_privileges_secure
        )


@dataclass(frozen=True)
class BoundaryTableState:
    """A ``catalog`` table carrying tenant state, as the database reports it."""

    name: str
    has_stamping_trigger: bool
    has_tenant_id: bool
    rls_enabled: bool
    rls_forced: bool


def boundary_drift(boundary: list[BoundaryTableState]) -> tuple[list[str], list[str]]:
    """Compare the live boundary against the runtime constant that drives RLS.

    ``apply_tenancy_rls`` enables and FORCEs row security from
    ``app.core.db.rls.RLS_TABLES``.  A table that joined the live boundary
    without joining that tuple is silently skipped at boot, which is exactly the
    failure a restored multi-tenant cluster cannot afford.  The other direction
    is drift too: a table named in the tuple but carrying no stamping trigger
    accepts an insert with no ``tenant_id`` at all.  Returns
    ``(live_only, constant_only)``.
    """
    live = {state.name for state in boundary if state.has_stamping_trigger}
    declared = set(RLS_TABLES)
    return sorted(live - declared), sorted(declared - live)


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
                   EXISTS (
                       SELECT 1 FROM pg_catalog.pg_trigger AS trigger_row
                       WHERE trigger_row.tgrelid = relation.oid
                         AND trigger_row.tgname = :trigger_name
                         AND NOT trigger_row.tgisinternal
                   ) AS has_stamping_trigger,
                   EXISTS (
                       SELECT 1 FROM pg_catalog.pg_attribute AS attribute
                       WHERE attribute.attrelid = relation.oid
                         AND attribute.attname = 'tenant_id'
                         AND NOT attribute.attisdropped
                   ) AS has_tenant_id,
                   relation.relrowsecurity AS rls_enabled,
                   relation.relforcerowsecurity AS rls_forced
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'catalog'
              AND relation.relkind IN ('r', 'p')
            ORDER BY relation.relname
            """
        ),
        {"trigger_name": BOUNDARY_TRIGGER},
    )
    states = [BoundaryTableState(**dict(row._mapping)) for row in result]
    return [
        state for state in states if state.has_stamping_trigger or state.has_tenant_id
    ]


async def boundary_function_states(conn) -> list[BoundaryFunctionState]:
    """Read owner, SECURITY DEFINER, search_path, and ACL of both functions."""
    result = await conn.execute(
        text(
            """
            SELECT routine.proname AS name,
                   pg_catalog.pg_get_userbyid(routine.proowner) AS owner,
                   routine.prosecdef AS security_definer,
                   COALESCE(
                       'search_path=pg_catalog' = ANY(routine.proconfig), false
                   ) AS search_path_pinned,
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
                     AND pg_catalog.has_schema_privilege(
                             (SELECT oid FROM writer),
                             (SELECT schema_name FROM names),
                             'USAGE, CREATE'
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
        if not state.security_definer:
            raise RuntimeError(
                f"catalog.{name}(uuid) is not SECURITY DEFINER. This is not the "
                "migration-installed boundary function; refusing to adopt it."
            )
        if not state.search_path_pinned:
            raise RuntimeError(
                f"catalog.{name}(uuid) has no `SET search_path = pg_catalog`. "
                "This is not the migration-installed boundary function; "
                "refusing to adopt it."
            )

    for name in BOUNDARY_FUNCTIONS:
        signature = f"catalog.{name}(uuid)"
        await conn.execute(text(f"ALTER FUNCTION {signature} OWNER TO {PROVISIONER}"))
        await conn.execute(text(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC"))
        await conn.execute(text(f"GRANT EXECUTE ON FUNCTION {signature} TO {CONTROL}"))
    return await boundary_function_states(conn)


async def adopt_tenant(conn, tenant_id: str) -> None:
    """Move one tenant's schema, roles, and relations under the boundary."""
    normalized = str(uuid.UUID(tenant_id))
    await conn.execute(
        text("SELECT set_config(:guc, :tenant_id, true)"),
        {"guc": TENANT_GUC, "tenant_id": normalized},
    )
    await conn.execute(text(ADOPT_TENANT_SQL))


# ---------------------------------------------------------------------------
# Orchestration + CLI
# ---------------------------------------------------------------------------


@dataclass
class AdoptionReport:
    """What adoption found, and what it changed."""

    applied: bool
    functions: list[BoundaryFunctionState]
    boundary: list[BoundaryTableState]
    before: list[TenantOwnershipState]
    after: list[TenantOwnershipState]
    failures: dict[str, str]
    cluster_topology: str | None = None
    provisioner_grants_missing: list[str] = field(default_factory=list)

    @property
    def missing_functions(self) -> list[str]:
        """Boundary functions the schema does not have.

        ``boundary_function_states`` omits what it cannot find, so an absent
        function shortens the list rather than marking one unsecured.  Naming
        the gap keeps ``all(... .secured)`` from passing vacuously.
        """
        present = {function.name for function in self.functions}
        return [name for name in BOUNDARY_FUNCTIONS if name not in present]

    @property
    def ok(self) -> bool:
        """True when nothing is left to do — the exit code in both modes.

        A dry run that reports pending work therefore exits non-zero, which is
        what makes ``--apply``-less invocation usable as a post-restore check.
        Every condition the report surfaces has to be in here, or the check
        passes on a database the report itself calls broken: a missing boundary
        function, a fixed-role topology ``--apply`` would refuse, a provisioner
        grant a restore dropped, and boundary drift that leaves a stamped table
        without RLS at boot all count.
        """
        if (
            self.failures
            or self.missing_functions
            or self.cluster_topology
            or self.provisioner_grants_missing
        ):
            return False
        if not all(function.secured for function in self.functions):
            return False
        live_only, constant_only = boundary_drift(self.boundary)
        if live_only or constant_only:
            return False
        states = self.after if self.applied else self.before
        return all(state.adopted for state in states)


async def run_adoption(engine, *, apply: bool) -> AdoptionReport:
    """Report the ownership gap and, with ``apply``, close it."""
    topology = await cluster_topology_error(engine)
    async with engine.connect() as conn:
        tenants = await list_tenants(conn)
        before = [await tenant_ownership_state(conn, tid) for tid in tenants]
        boundary = await live_tenant_boundary(conn)
        functions = await boundary_function_states(conn)
        grants = [] if topology else await missing_provisioner_grants(conn)

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

    topology = await cluster_topology_error(engine)
    async with engine.connect() as conn:
        after = [await tenant_ownership_state(conn, tid) for tid in tenants]
        boundary = await live_tenant_boundary(conn)
        grants = [] if topology else await missing_provisioner_grants(conn)

    return AdoptionReport(
        applied=True,
        functions=functions,
        boundary=boundary,
        before=before,
        after=after,
        failures=failures,
        cluster_topology=topology,
        provisioner_grants_missing=grants,
    )


def _format_cluster_roles(report: AdoptionReport) -> list[str]:
    if report.cluster_topology is not None:
        return [
            f"Fixed cluster roles: NEEDS ATTENTION — {report.cluster_topology}",
            "  --apply creates a missing role; it refuses an unsafe one.",
        ]
    lines = [
        f"Fixed cluster roles ({PROVISIONER} and the four gateways): "
        "present, with safe attributes and memberships."
    ]
    if report.provisioner_grants_missing:
        lines.append(
            f"  {PROVISIONER} is missing "
            f"{', '.join(report.provisioner_grants_missing)} — tenant "
            "provisioning cannot run without them; --apply re-grants them."
        )
    return lines


def _format_functions(report: AdoptionReport) -> list[str]:
    lines = ["Boundary functions:"]
    for function in report.functions:
        flags = [f"owner={function.owner}"]
        if function.public_execute:
            flags.append("EXECUTE granted to PUBLIC")
        if not function.control_execute:
            flags.append(f"no EXECUTE for {CONTROL}")
        verdict = "secured" if function.secured else "NEEDS REPAIR"
        lines.append(f"  catalog.{function.name}(uuid): {verdict} — {', '.join(flags)}")
    for name in report.missing_functions:
        lines.append(
            f"  catalog.{name}(uuid): MISSING — this database is not at the head "
            "schema; run `alembic upgrade heads` first"
        )
    return lines


def _boundary_table_markers(table: BoundaryTableState) -> list[str]:
    if not table.has_stamping_trigger:
        return ["tenant_id column only, outside the stamped boundary"]
    if not table.rls_enabled:
        return ["RLS not enabled (the API enables it at boot in multi_tenant)"]
    if not table.rls_forced:
        return ["RLS enabled but not FORCEd — the table owner bypasses it"]
    return []


def _format_boundary(boundary: list[BoundaryTableState]) -> list[str]:
    lines = [f"Live tenant boundary ({BOUNDARY_TRIGGER}), read from the database:"]
    for table in boundary:
        markers = _boundary_table_markers(table)
        suffix = f" — {'; '.join(markers)}" if markers else ""
        lines.append(f"  catalog.{table.name}{suffix}")

    live_only, constant_only = boundary_drift(boundary)
    if live_only:
        lines.append(
            "  DRIFT: stamped in the database but absent from "
            "app.core.db.rls.RLS_TABLES, so boot never enables RLS on them: "
            f"{', '.join(live_only)}"
        )
    if constant_only:
        lines.append(
            "  DRIFT: listed in app.core.db.rls.RLS_TABLES but carrying no "
            f"stamping trigger here: {', '.join(constant_only)}"
        )
    return lines


def _tenant_verdict(
    before: TenantOwnershipState, after: TenantOwnershipState, applied: bool
) -> str:
    if not applied:
        return "adopted" if before.adopted else "needs adoption"
    if not after.adopted:
        return "STILL INCOMPLETE"
    return "already adopted (no changes)" if before.adopted else "adopted"


def _format_tenants(report: AdoptionReport) -> list[str]:
    if not report.before:
        return ["Tenants: none. Nothing to adopt (single-tenant control plane)."]

    lines = [f"Tenants: {len(report.before)}"]
    after_by_id = {state.tenant_id: state for state in report.after}
    for before in report.before:
        after = after_by_id[before.tenant_id]
        detail = [
            f"{after.relations} relation(s)",
            f"{after.relations_not_owned_by_writer} not owned by the writer",
            f"{after.relations_without_reader_select} without reader SELECT",
        ]
        if after.reader_default_acls:
            detail.append(
                f"{after.reader_default_acls} legacy default-privilege "
                "entr(ies) for the reader"
            )
        if not after.reader_role_secure:
            detail.append(
                "reader role attributes or memberships are not the safe shape"
            )
        if not after.writer_role_secure:
            detail.append(
                "writer role attributes or memberships are not the safe shape"
            )
        if not after.schema_privileges_secure:
            detail.append("schema privileges are not the safe shape")
        verdict = _tenant_verdict(before, after, report.applied)
        lines.append(f"  {before.tenant_id}: {verdict} — {', '.join(detail)}")
    return lines


def format_report(report: AdoptionReport) -> str:
    """Render the report an operator reads mid-recovery."""
    mode = "APPLIED" if report.applied else "DRY RUN (no changes made)"
    sections = [
        [f"Tenant-ownership adoption — {mode}"],
        _format_cluster_roles(report),
        _format_functions(report),
        _format_boundary(report.boundary),
        _format_tenants(report),
    ]
    if report.failures:
        failures = ["Failures (re-run after fixing; adopted tenants stay adopted):"]
        failures += [
            f"  {tenant_id}: {message}"
            for tenant_id, message in report.failures.items()
        ]
        sections.append(failures)
    return "\n\n".join("\n".join(section) for section in sections)


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
