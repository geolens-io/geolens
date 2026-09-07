"""Report types and verdicts for :mod:`app.core.db.tenant_adoption`.

Split out at the module's existing boundary: this module is what adoption
*found* (boundary function state, fixed cluster roles, tenant ownership,
row-security posture) plus the predicate deciding whether anything is left to
do and the text an operator reads. :mod:`app.core.db.tenant_adoption` is what
adoption *does* — the queries, the DDL, the CLI.

``AdoptionReport.ok`` sits next to what it consults deliberately: it is the
process exit code, so every printable condition must reach it. fix(#1405):
several review rounds found the report saying something is broken while the
check still exited 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.db.rls import RLS_TABLES
from app.core.db.tenant_adoption_sql import CONTROL, PROVISIONER

#: The two migration-owned SECURITY DEFINER entry points. Adoption verifies
#: and re-secures them; it never rewrites their bodies.
BOUNDARY_FUNCTIONS = (
    "provision_tenant_data_schema",
    "deprovision_tenant_data_schema",
)

#: The insert-stamping trigger 0018 installs. Its presence, not any constant
#: frozen into a migration, is what marks a table as tenant-scoped.
BOUNDARY_TRIGGER = "trg_stamp_current_tenant_on_insert"

#: The function 0018 wires that trigger to, and the ``tgtype`` bitmask for
#: ``BEFORE INSERT … FOR EACH ROW`` (ROW 1 | BEFORE 2 | INSERT 4). A trigger
#: recreated under this name but pointed elsewhere, or on a different event,
#: stamps nothing.
BOUNDARY_TRIGGER_FUNCTION = "stamp_current_tenant_on_insert"

#: The search path 0018 pins on that function, compared exactly: an
#: unqualified name resolved through a writable schema is the classic
#: SECURITY-adjacent function hijack.
STAMPING_FUNCTION_SEARCH_PATH = "search_path=pg_catalog, catalog"
BOUNDARY_TRIGGER_TYPE = 7

#: The isolation rule 0006 installs, as Postgres canonicalizes it. Pinned
#: exactly since it *is* the cross-tenant visibility boundary — a migration
#: that changes it must change this line too, which is the intended friction.
ISOLATION_POLICY_EXPRESSION = (
    "(tenant_id = (current_setting('app.current_tenant'::text))::uuid)"
)


@dataclass(frozen=True)
class BoundaryFunctionState:
    """Live state of one migration-owned SECURITY DEFINER entry point."""

    name: str
    owner: str
    security_definer: bool
    search_path_pinned: bool
    language: str
    returns_void: bool
    body_markers_present: bool
    public_execute: bool
    control_execute: bool
    unexpected_grantees: int

    @property
    def migration_shaped(self) -> bool:
        """Structural agreement with what the migrations install.

        Not proof of provenance — pinning the migration's exact text would go
        stale the next time a migration edits the body. What it rules out is a
        wholesale substitution: a different language, a different return
        type, or a body no longer mentioning the tenant table, schema prefix,
        or advisory lock the boundary is built on.

        Residual exposure is bounded in the direction that matters: adoption
        only ever moves a ``--no-owner --no-acl`` restore's functions to a
        ``NOLOGIN`` role and narrows execution to the control group, so it
        can fail to notice a tampered body but never raise its privilege.
        """
        return (
            self.security_definer
            and self.search_path_pinned
            and self.language == "plpgsql"
            and self.returns_void
            and self.body_markers_present
        )

    @property
    def secured(self) -> bool:
        return (
            self.owner == PROVISIONER
            and self.migration_shaped
            and not self.public_execute
            and self.control_execute
            and self.unexpected_grantees == 0
        )


def unexpected_shape(state: BoundaryFunctionState) -> str | None:
    """Why this function is not the one the migrations install, if it is not.

    The refusal message adoption prints before it would hand a body to
    :data:`PROVISIONER` and grant :data:`CONTROL` execution on it.
    """
    if not state.security_definer:
        return "is not SECURITY DEFINER"
    if not state.search_path_pinned:
        return "has no `SET search_path = pg_catalog`"
    if state.language != "plpgsql":
        return f"is written in {state.language}, not plpgsql"
    if not state.returns_void:
        return "does not return void"
    if not state.body_markers_present:
        return (
            "has a body that no longer references catalog.tenants, the "
            "data_t_ schema prefix, and the tenant advisory lock"
        )
    return None


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
    unsafe_routines: int
    unsafe_types: int
    unsafe_statistics: int
    unsafe_collations: int
    unowned_other_objects: int
    foreign_grantors: int
    relations_not_owned_by_writer: int
    relations_without_reader_select: int
    relations_with_unsafe_acl: int
    unexpected_default_acls: int
    reader_role_secure: bool
    writer_role_secure: bool
    schema_privileges_secure: bool

    @property
    def adopted(self) -> bool:
        """Every invariant ``--apply`` enforces, not just the visible ones.

        Ownership and effective privileges alone would call a reader carrying
        ``LOGIN``/``SUPERUSER``/``BYPASSRLS`` adopted — a superuser satisfies
        ``SELECT`` by fiat — and would miss a stray member or missing gateway
        edge, both of which ``ADOPT_TENANT_SQL`` refuses or repairs.
        """
        return (
            self.schema_exists
            and self.schema_owner == PROVISIONER
            and self.reader_exists
            and self.writer_exists
            and self.unsafe_routines == 0
            and self.unsafe_types == 0
            and self.unsafe_statistics == 0
            and self.unsafe_collations == 0
            and self.unowned_other_objects == 0
            and self.foreign_grantors == 0
            and self.relations_not_owned_by_writer == 0
            and self.relations_without_reader_select == 0
            and self.relations_with_unsafe_acl == 0
            and self.unexpected_default_acls == 0
            and self.reader_role_secure
            and self.writer_role_secure
            and self.schema_privileges_secure
        )


@dataclass(frozen=True)
class BoundaryTableState:
    """A ``catalog`` table carrying tenant state, as the database reports it."""

    name: str
    #: A trigger by the boundary name exists AND fires on an ordinary insert:
    #: enabled, ``BEFORE INSERT … FOR EACH ROW``, calling the migration's
    #: stamping function.
    has_stamping_trigger: bool
    #: The name exists but does not satisfy the above.
    stamping_trigger_present: bool
    has_tenant_id: bool
    rls_enabled: bool
    rls_forced: bool
    isolation_policy_intact: bool

    @property
    def stamping_trigger_inert(self) -> bool:
        """The boundary name is taken by a trigger that stamps nothing.

        Disabled, wired to the wrong event or timing, or calling some other
        function — all the same to a row being inserted, and none of them
        something boot repairs.
        """
        return self.stamping_trigger_present and not self.has_stamping_trigger


def rls_gaps(boundary: list[BoundaryTableState], *, tenants_present: bool) -> list[str]:
    """Boundary tables whose row-security posture is not safe to serve.

    ``apply_tenancy_rls`` is mode-gated, so a uniformly disabled boundary on a
    control plane with no tenants is not a finding — this module can only read
    the tenants, not the mode. Two states always are findings: tenants present
    with row security off (no isolation boundary), and row security enabled
    without ``FORCE`` (the table owner bypasses every policy).
    """
    gaps: list[str] = []
    for table in boundary:
        if not table.has_stamping_trigger:
            continue
        if not table.isolation_policy_intact:
            gaps.append(f"{table.name} (tenant_isolation policy missing or altered)")
        elif tenants_present and not table.rls_enabled:
            gaps.append(f"{table.name} (row security disabled)")
        elif table.rls_enabled and not table.rls_forced:
            gaps.append(f"{table.name} (row security not FORCEd)")
    return gaps


def boundary_drift(boundary: list[BoundaryTableState]) -> tuple[list[str], list[str]]:
    """Compare the live boundary against the runtime constant that drives RLS.

    ``apply_tenancy_rls`` enables and FORCEs row security from
    ``app.core.db.rls.RLS_TABLES``. A table that joined the live boundary
    without joining that tuple is silently skipped at boot — a failure a
    restored multi-tenant cluster cannot afford. The reverse is drift too: a
    table named in the tuple with no stamping trigger accepts an insert with
    no ``tenant_id`` at all. Returns ``(live_only, constant_only)``.
    """
    live = {state.name for state in boundary if state.has_stamping_trigger}
    declared = set(RLS_TABLES)
    return sorted(live - declared), sorted(declared - live)


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
    stamping_function: str | None = None
    provisioner_grants_missing: list[str] = field(default_factory=list)
    tenants_added_during_run: list[str] = field(default_factory=list)

    @property
    def missing_functions(self) -> list[str]:
        """Boundary functions the schema does not have.

        ``boundary_function_states`` omits what it cannot find, so an absent
        function shortens the list rather than marking one unsecured. Naming
        the gap keeps ``all(... .secured)`` from passing vacuously.
        """
        present = {function.name for function in self.functions}
        return [name for name in BOUNDARY_FUNCTIONS if name not in present]

    @property
    def inert_stamping_triggers(self) -> list[str]:
        """Boundary tables whose stamping trigger exists but does not fire.

        Its own condition, not a corollary of the drift check: a table both
        newly tenant-scoped and absent from ``RLS_TABLES`` lands in neither
        drift direction and has no row-security requirement to miss, so a
        disabled trigger there would otherwise print and then be ignored.
        """
        return sorted(
            table.name for table in self.boundary if table.stamping_trigger_inert
        )

    @property
    def rls_gaps(self) -> list[str]:
        """Boundary tables that cannot enforce tenant isolation as they stand.

        Tenant rows in the control plane are what makes a database
        multi-tenant, so they are what makes row security mandatory here.
        """
        return rls_gaps(self.boundary, tenants_present=bool(self.before))

    @property
    def ok(self) -> bool:
        """True when nothing is left to do — the exit code in both modes.

        A dry run that reports pending work exits non-zero, making
        ``--apply``-less invocation usable as a post-restore check. Every
        condition the report surfaces must be in here, or the check passes on
        a database the report itself calls broken: a missing boundary
        function, a fixed-role topology ``--apply`` would refuse, a
        provisioner grant a restore dropped, boundary drift leaving a stamped
        table without RLS at boot, a stamping trigger or function that does
        not stamp, and a boundary table that cannot enforce isolation.
        """
        if (
            self.failures
            or self.missing_functions
            or self.cluster_topology
            or self.provisioner_grants_missing
            or self.stamping_function
            or self.rls_gaps
            or self.inert_stamping_triggers
            or self.tenants_added_during_run
        ):
            return False
        if not all(function.secured for function in self.functions):
            return False
        live_only, constant_only = boundary_drift(self.boundary)
        if live_only or constant_only:
            return False
        states = self.after if self.applied else self.before
        return all(state.adopted for state in states)


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
        if function.unexpected_grantees:
            flags.append(
                f"{function.unexpected_grantees} role(s) outside "
                f"{PROVISIONER}/{CONTROL} hold EXECUTE"
            )
        verdict = "secured" if function.secured else "NEEDS REPAIR"
        lines.append(f"  catalog.{function.name}(uuid): {verdict} — {', '.join(flags)}")
    for name in report.missing_functions:
        lines.append(
            f"  catalog.{name}(uuid): MISSING — this database is not at the head "
            "schema; run `alembic upgrade heads` first"
        )
    return lines


def _boundary_table_markers(
    table: BoundaryTableState, *, tenants_present: bool
) -> list[str]:
    if table.stamping_trigger_inert:
        return [
            f"{BOUNDARY_TRIGGER} exists but does not stamp — DISABLED, or wired "
            "to another event or function; nothing at boot repairs that"
        ]
    if not table.has_stamping_trigger:
        return ["tenant_id column only, outside the stamped boundary"]
    if not table.isolation_policy_intact:
        return [
            "the tenant_isolation policy is missing or no longer the rule the "
            "migrations install; nothing at boot recreates it"
        ]
    if not table.rls_enabled:
        if tenants_present:
            return ["RLS not enabled on a control plane that has tenants"]
        return ["RLS not enabled (correct while the control plane has no tenants)"]
    if not table.rls_forced:
        return ["RLS enabled but not FORCEd — the table owner bypasses it"]
    return []


def _format_boundary(report: AdoptionReport) -> list[str]:
    boundary = report.boundary
    tenants_present = bool(report.before)
    lines = [f"Live tenant boundary ({BOUNDARY_TRIGGER}), read from the database:"]
    if report.stamping_function is not None:
        lines.append(f"  NOT SAFE TO SERVE: {report.stamping_function}")
    for table in boundary:
        markers = _boundary_table_markers(table, tenants_present=tenants_present)
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
            "  DRIFT: listed in app.core.db.rls.RLS_TABLES but carrying no live "
            f"stamping trigger here: {', '.join(constant_only)}"
        )
    if report.rls_gaps:
        lines.append(
            "  NOT SAFE TO SERVE until row security is repaired: "
            f"{', '.join(report.rls_gaps)}"
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
        # fix(#998): a tenant provisioned after the empty snapshot makes
        # report.ok false; "nothing to adopt" while exiting 1 would hide the
        # one condition the operator has to act on.
        if report.tenants_added_during_run:
            return [
                "Tenants: none at the start of the run.",
                "  provisioned while this ran and therefore never adopted: "
                + ", ".join(report.tenants_added_during_run),
            ]
        return ["Tenants: none. Nothing to adopt (single-tenant control plane)."]

    lines = [f"Tenants: {len(report.before)}"]
    if report.tenants_added_during_run:
        lines.append(
            "  provisioned while this ran and therefore never adopted: "
            + ", ".join(report.tenants_added_during_run)
        )
    after_by_id = {state.tenant_id: state for state in report.after}
    for before in report.before:
        # A tenant deleted while this ran has no post-state: its row is gone
        # either way, whether or not its transaction completed.
        after = after_by_id.get(before.tenant_id)
        if after is None:
            lines.append(f"  {before.tenant_id}: deleted while this ran")
            continue
        detail = [
            f"{after.relations} relation(s)",
            f"{after.unsafe_routines} routine(s) out of shape",
            f"{after.unsafe_types} type(s) not owned by the writer",
            f"{after.unsafe_statistics} statistics object(s) not owned by the writer",
            f"{after.foreign_grantors} privilege(s) granted by a third party",
            f"{after.relations_not_owned_by_writer} not owned by the writer",
            f"{after.relations_without_reader_select} without reader SELECT",
            f"{after.relations_with_unsafe_acl} with an ACL beyond reader SELECT",
        ]
        if after.unexpected_default_acls:
            detail.append(
                f"{after.unexpected_default_acls} default-privilege entr(ies) "
                "in the schema"
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
        _format_boundary(report),
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
