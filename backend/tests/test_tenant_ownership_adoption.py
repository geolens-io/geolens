"""Forward-only tenant-ownership adoption at the head schema (#998).

The only path that ever reconstructed tenant ownership was
``alembic downgrade 0016`` followed by a re-upgrade through 0019 — a data-loss
event on a populated cluster.  ``app.core.db.tenant_adoption`` does the same
reconstruction at head; these tests hold it to the state 0019 produced.

Coverage
--------
A: a head-schema database carrying tenant data with no ownership rows — schema,
   relations, and roles all sitting where ``pg_restore --no-owner --no-acl``
   leaves them — is adopted into the 0019 end state.
B: a second run changes nothing.  Asserted by diffing a full catalog snapshot
   (owners, ACLs, role attributes, memberships), not by trusting the report.
C: the dump-restore case — the SECURITY DEFINER boundary functions are already
   present, owned by the restoring login, with the PostgreSQL default ACL that
   grants EXECUTE to PUBLIC.  Adoption must not collide with them and must take
   that grant away.
D: the tenant boundary is read from the database, never from a constant frozen
   into a migration.

Run:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_tenant_ownership_adoption.py -x -q
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db.rls import RLS_TABLES
from app.core.db.tenant_adoption import (
    CONTROL,
    PROVISIONER,
    boundary_function_states,
    cluster_topology_error,
    live_tenant_boundary,
    missing_provisioner_grants,
    run_adoption,
    stamping_function_shape,
    secure_boundary_functions,
    tenant_ownership_state,
)
from app.core.db.tenant_adoption_report import (
    BOUNDARY_FUNCTIONS,
    AdoptionReport,
    BoundaryFunctionState,
    BoundaryTableState,
    TenantOwnershipState,
    boundary_drift,
    format_report,
    rls_gaps,
)
from app.core.db.tenant_adoption_sql import (
    CLUSTER_ROLE_VALIDATE_SQL,
    RELEASE_PROVISIONER_EDGE_SQL,
    TILE,
)
from app.core.db.tenant_adoption_sql import WRITER as WRITER_GATEWAY
from tests.repo_paths import repo_root

pytestmark = pytest.mark.anyio

ROOT = repo_root(__file__)


def _new_tenant() -> tuple[str, str, str, str]:
    """A tenant id whose cluster-wide role names cannot collide with a peer.

    Per-tenant roles are cluster objects shared by every xdist worker's test
    database, so a fixed fixture id would have two workers adopting and dropping
    the same roles.
    """
    tenant_id = str(uuid.uuid4())
    suffix = tenant_id.replace("-", "_")
    return (
        tenant_id,
        f"data_t_{suffix}",
        f"geolens_reader_t_{suffix}",
        f"geolens_writer_t_{suffix}",
    )


def _make_engine():
    from app.core.config import settings

    return create_async_engine(settings.test_database_url, poolclass=NullPool)


@asynccontextmanager
async def _row_security_enabled(engine):
    """Give the worker's database the multi-tenant row-security posture.

    Tenant rows in ``catalog.tenants`` are what make a control plane
    multi-tenant, so they are what makes row security mandatory to
    ``AdoptionReport.ok``. The suite's shared database is single-tenant with RLS
    off, so a test that inserts a tenant has to supply the posture and hand it
    back. The connecting login is a superuser, which is never subject to RLS
    even under FORCE, so nothing but the catalog flags changes here.
    """
    async with engine.begin() as conn:
        for table in RLS_TABLES:
            await conn.execute(
                sa.text(f"ALTER TABLE catalog.{table} ENABLE ROW LEVEL SECURITY")
            )
            await conn.execute(
                sa.text(f"ALTER TABLE catalog.{table} FORCE ROW LEVEL SECURITY")
            )
    try:
        yield
    finally:
        async with engine.begin() as conn:
            for table in RLS_TABLES:
                await conn.execute(
                    sa.text(f"ALTER TABLE catalog.{table} NO FORCE ROW LEVEL SECURITY")
                )
                await conn.execute(
                    sa.text(f"ALTER TABLE catalog.{table} DISABLE ROW LEVEL SECURITY")
                )


@pytest.fixture
async def multi_tenant_row_security():
    """For any test that puts a tenant row in the control plane.

    Tenants present is what makes row security mandatory to
    ``AdoptionReport.ok``, so a test that seeds one has to supply the posture a
    real multi-tenant database would already have.
    """
    engine = _make_engine()
    try:
        async with _row_security_enabled(engine):
            yield
    finally:
        await engine.dispose()


async def _seed_restored_tenant(engine, tenant_id: str, schema: str) -> None:
    """Recreate what a ``pg_restore --no-owner --no-acl`` hands the operator.

    Every relation is owned by the restoring login, no ACLs survive, and the
    per-tenant reader/writer roles do not exist at all — the fresh-cluster case
    where no globals dump was replayed.
    """
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO catalog.tenants (id, slug, name) "
                "VALUES (CAST(:id AS uuid), :slug, :name)"
            ),
            {"id": tenant_id, "slug": f"w998-{tenant_id[:8]}", "name": "adoption"},
        )
        await conn.execute(sa.text(f"CREATE SCHEMA {schema}"))
        # bigserial gives us a column-owned sequence: PostgreSQL refuses
        # ALTER SEQUENCE ... OWNER TO on those, and every ogr2ogr vector ingest
        # produces one as ogc_fid.
        await conn.execute(
            sa.text(
                f"CREATE TABLE {schema}.parcels "
                "(id bigserial PRIMARY KEY, name text NOT NULL)"
            )
        )
        await conn.execute(
            sa.text(f"INSERT INTO {schema}.parcels (name) VALUES ('restored row')")
        )
        await conn.execute(
            sa.text(
                f"CREATE VIEW {schema}.parcel_names AS SELECT name FROM {schema}.parcels"
            )
        )


async def _drop_tenant(engine, tenant_id: str) -> None:
    """Remove the tenant whatever state the test left it in.

    Not through ``deprovision_tenant_data_schema``: that refuses on a schema the
    provisioner does not own, which is exactly the state the dry-run and
    failure-path tests leave behind. Per-tenant roles are cluster objects, so
    teardown has to drop them or every run leaks two roles into the cluster the
    other xdist workers share.
    """
    suffix = tenant_id.replace("-", "_")
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM catalog.tenants WHERE id = CAST(:id AS uuid)"),
            {"id": tenant_id},
        )
        await conn.execute(sa.text(f"DROP SCHEMA IF EXISTS data_t_{suffix} CASCADE"))
        for role in (f"geolens_reader_t_{suffix}", f"geolens_writer_t_{suffix}"):
            await conn.execute(
                sa.text(
                    "DO $$ BEGIN "
                    f"IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN "
                    f"EXECUTE 'DROP OWNED BY {role}'; "
                    f"EXECUTE 'DROP ROLE {role}'; "
                    "END IF; END $$"
                )
            )


async def _catalog_snapshot(engine, tenant_id: str) -> list[tuple]:
    """Owners, ACLs, role attributes, and memberships for one tenant."""
    suffix = tenant_id.replace("-", "_")
    async with engine.connect() as conn:
        rows: list[tuple] = []
        rows += list(
            await conn.execute(
                sa.text(
                    "SELECT 'schema', nspname, pg_get_userbyid(nspowner), "
                    "COALESCE(nspacl::text, '') FROM pg_namespace "
                    "WHERE nspname = :schema"
                ),
                {"schema": f"data_t_{suffix}"},
            )
        )
        rows += list(
            await conn.execute(
                sa.text(
                    "SELECT 'relation', relation.relname, "
                    "pg_get_userbyid(relation.relowner), "
                    "COALESCE(relation.relacl::text, '') "
                    "FROM pg_class AS relation "
                    "JOIN pg_namespace AS namespace "
                    "  ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = :schema "
                    "ORDER BY relation.relname"
                ),
                {"schema": f"data_t_{suffix}"},
            )
        )
        rows += list(
            await conn.execute(
                sa.text(
                    "SELECT 'role', rolname, rolcanlogin::text || rolinherit::text "
                    "|| rolsuper::text || rolcreaterole::text || rolbypassrls::text, '' "
                    "FROM pg_roles WHERE rolname LIKE :pattern ORDER BY rolname"
                ),
                {"pattern": f"%{suffix}"},
            )
        )
        rows += list(
            await conn.execute(
                sa.text(
                    "SELECT 'member', granted.rolname, member.rolname, "
                    "membership.admin_option::text || membership.inherit_option::text "
                    "|| membership.set_option::text "
                    "FROM pg_auth_members AS membership "
                    "JOIN pg_roles AS granted ON granted.oid = membership.roleid "
                    "JOIN pg_roles AS member ON member.oid = membership.member "
                    "WHERE granted.rolname LIKE :pattern OR member.rolname LIKE :pattern "
                    "ORDER BY granted.rolname, member.rolname"
                ),
                {"pattern": f"%{suffix}"},
            )
        )
        return [tuple(row) for row in rows]


async def _break_boundary_functions(engine) -> None:
    """Leave the functions exactly as a --no-owner --no-acl restore leaves them."""
    async with engine.begin() as conn:
        current_user = (await conn.execute(sa.text("SELECT current_user"))).scalar_one()
        for name in BOUNDARY_FUNCTIONS:
            signature = f"catalog.{name}(uuid)"
            await conn.execute(
                sa.text(f"ALTER FUNCTION {signature} OWNER TO {current_user}")
            )
            await conn.execute(
                sa.text(f"REVOKE ALL ON FUNCTION {signature} FROM {CONTROL}")
            )
            await conn.execute(
                sa.text(f"GRANT EXECUTE ON FUNCTION {signature} TO PUBLIC")
            )


async def _restore_boundary_functions(engine) -> None:
    async with engine.begin() as conn:
        for name in BOUNDARY_FUNCTIONS:
            signature = f"catalog.{name}(uuid)"
            await conn.execute(
                sa.text(f"ALTER FUNCTION {signature} OWNER TO {PROVISIONER}")
            )
            await conn.execute(
                sa.text(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
            )
            await conn.execute(
                sa.text(f"GRANT EXECUTE ON FUNCTION {signature} TO {CONTROL}")
            )


# ---------------------------------------------------------------------------
# A: reconstruct ownership on a head-schema database
# ---------------------------------------------------------------------------


class TestAdoptionReconstructsOwnership:
    """A: the 0019 end state, reached forward-only at head."""

    async def test_restored_tenant_is_adopted(self, multi_tenant_row_security):
        tenant_id, schema, reader, writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)

            async with engine.connect() as conn:
                before = await tenant_ownership_state(conn, tenant_id)
            assert not before.adopted
            assert not before.reader_exists
            assert not before.writer_exists
            assert before.relations_not_owned_by_writer == before.relations > 0

            report = await run_adoption(engine, apply=True)
            assert report.failures == {}, report.failures
            assert report.ok

            async with engine.connect() as conn:
                after = await tenant_ownership_state(conn, tenant_id)
                assert after.adopted
                assert after.schema_owner == PROVISIONER
                assert after.relations_not_owned_by_writer == 0
                assert after.relations_without_reader_select == 0

                # The reader reads and cannot write; the data itself survives.
                privileges = (
                    await conn.execute(
                        sa.text(
                            "SELECT has_table_privilege(:reader, :table, 'SELECT'), "
                            "has_table_privilege(:reader, :table, 'INSERT'), "
                            "has_schema_privilege(:reader, :schema, 'USAGE'), "
                            "has_schema_privilege(:writer, :schema, 'CREATE')"
                        ),
                        {
                            "reader": reader,
                            "writer": writer,
                            "schema": schema,
                            "table": f"{schema}.parcels",
                        },
                    )
                ).one()
                assert tuple(privileges) == (True, False, True, True)

                rows = (
                    await conn.execute(
                        sa.text(f"SELECT count(*) FROM {schema}.parcels")
                    )
                ).scalar_one()
                assert rows == 1

                # Per-tenant roles are NOLOGIN/NOINHERIT, and the provisioner
                # holds ADMIN only — no inherit, no SET.
                attributes = (
                    await conn.execute(
                        sa.text(
                            "SELECT rolcanlogin, rolinherit, rolsuper, rolbypassrls "
                            "FROM pg_roles WHERE rolname = :role"
                        ),
                        {"role": reader},
                    )
                ).one()
                assert tuple(attributes) == (False, False, False, False)

                membership = (
                    await conn.execute(
                        sa.text(
                            "SELECT membership.admin_option, membership.inherit_option, "
                            "membership.set_option "
                            "FROM pg_auth_members AS membership "
                            "JOIN pg_roles AS granted ON granted.oid = membership.roleid "
                            "JOIN pg_roles AS member ON member.oid = membership.member "
                            "WHERE granted.rolname = :writer AND member.rolname = :owner"
                        ),
                        {"writer": writer, "owner": PROVISIONER},
                    )
                ).one()
                assert tuple(membership) == (True, False, False)

                # The transaction-scoped SET edge the transfer needs is handed
                # back before commit.
                leftover = (
                    await conn.execute(
                        sa.text(
                            "SELECT count(*) FROM pg_auth_members AS membership "
                            "JOIN pg_roles AS granted ON granted.oid = membership.roleid "
                            "JOIN pg_roles AS member ON member.oid = membership.member "
                            "WHERE granted.rolname = :writer "
                            "AND member.rolname = current_user"
                        ),
                        {"writer": writer},
                    )
                ).scalar_one()
                assert leftover == 0
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_column_owned_sequence_follows_its_table(
        self, multi_tenant_row_security
    ):
        """``bigserial``/identity sequences cannot be re-owned directly.

        0019's loop issued ``ALTER SEQUENCE … OWNER TO`` unconditionally, which
        PostgreSQL rejects for a column-owned sequence.  Adoption skips them and
        lets the ``ALTER TABLE`` carry them across.
        """
        tenant_id, schema, reader, writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            report = await run_adoption(engine, apply=True)
            assert report.failures == {}, report.failures

            async with engine.connect() as conn:
                owner = (
                    await conn.execute(
                        sa.text(
                            "SELECT pg_get_userbyid(relation.relowner) "
                            "FROM pg_class AS relation "
                            "JOIN pg_namespace AS namespace "
                            "  ON namespace.oid = relation.relnamespace "
                            "WHERE namespace.nspname = :schema "
                            "AND relation.relname = 'parcels_id_seq'"
                        ),
                        {"schema": schema},
                    )
                ).scalar_one()
                assert owner == writer

                reader_usage = (
                    await conn.execute(
                        sa.text(
                            "SELECT has_sequence_privilege(:reader, :sequence, 'SELECT')"
                        ),
                        {"reader": reader, "sequence": f"{schema}.parcels_id_seq"},
                    )
                ).scalar_one()
                assert reader_usage is True
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()


class TestReportedStateMatchesWhatApplyEnforces:
    """The dry-run verdict cannot be softer than `--apply`'s refusals.

    Ownership plus effective privileges is not enough on its own: a reader that
    can log in still holds every relation privilege the ownership check reads,
    and a superuser one satisfies `has_table_privilege` by fiat.
    """

    async def test_unsafe_reader_attributes_are_not_adopted(
        self, multi_tenant_row_security
    ):
        """A LOGIN reader is refused, and the dry run says so before `--apply`.

        The role is left un-adopted (no provisioner membership) on purpose:
        once a reserved role holds an edge to it, an unsafe attribute becomes a
        *cluster*-topology refusal, and cluster roles are shared with every
        other xdist worker's database.
        """
        tenant_id, schema, reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            async with engine.begin() as conn:
                await conn.execute(sa.text(f"CREATE ROLE {reader} LOGIN"))

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert state.reader_exists
            assert not state.reader_role_secure
            assert not state.adopted

            report = await run_adoption(engine, apply=True)
            assert tenant_id in report.failures
            assert "unsafe attributes" in report.failures[tenant_id]
            assert not report.ok
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_a_third_party_gateway_grant_is_refused(
        self, multi_tenant_row_security
    ):
        """The unsafe row belongs to another grantor, not to the adopter.

        A plain REVOKE removes only the caller's own grant, so this is the case
        that separates targeting the row from targeting the grantor the adopter
        happens to be.
        """
        tenant_id, schema, reader, _writer = _new_tenant()
        grantor = f"w998_grantor_{tenant_id.replace('-', '_')}"
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            async with engine.begin() as conn:
                await conn.execute(sa.text(f"CREATE ROLE {grantor} NOLOGIN CREATEROLE"))
                await conn.execute(
                    sa.text(f"GRANT {reader} TO {grantor} WITH ADMIN OPTION")
                )
                await conn.execute(sa.text(f"SET LOCAL ROLE {grantor}"))
                await conn.execute(
                    sa.text(f"GRANT {reader} TO {TILE} WITH INHERIT TRUE, SET TRUE")
                )
                await conn.execute(sa.text("RESET ROLE"))

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert not state.reader_role_secure

            refused = await run_adoption(engine, apply=True)
            assert tenant_id in refused.failures
            assert "will not rewrite" in refused.failures[tenant_id]
            # The remediation PostgreSQL attached to the refusal survives
            # into the report; without it the operator is told a tenant is
            # incomplete and not what to run.
            assert "REVOKE" in refused.failures[tenant_id]
            assert not refused.ok
        finally:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f"DROP OWNED BY {grantor}"))
                await conn.execute(sa.text(f"DROP ROLE IF EXISTS {grantor}"))
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_the_provisioners_own_edge_is_repaired_in_place(
        self, multi_tenant_row_security
    ):
        """The row adoption granted, so adoption is its grantor and can rewrite it.

        The other side of the boundary: a second row from a third-party grantor
        is refused instead — see the gateway test above.
        """
        tenant_id, schema, reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        f"GRANT {reader} TO {PROVISIONER} "
                        "WITH ADMIN TRUE, INHERIT TRUE, SET TRUE"
                    )
                )

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert not state.reader_role_secure
            assert not state.adopted

            repaired = await run_adoption(engine, apply=True)
            assert repaired.failures == {}, repaired.failures
            assert repaired.ok

            async with engine.connect() as conn:
                rows = [
                    tuple(row)
                    for row in await conn.execute(
                        sa.text(
                            "SELECT membership.admin_option, "
                            "membership.inherit_option, membership.set_option "
                            "FROM pg_auth_members AS membership "
                            "JOIN pg_roles AS granted "
                            "  ON granted.oid = membership.roleid "
                            "JOIN pg_roles AS member "
                            "  ON member.oid = membership.member "
                            "WHERE granted.rolname = :reader AND member.rolname = :owner"
                        ),
                        {"reader": reader, "owner": PROVISIONER},
                    )
                ]
            assert rows == [(True, False, False)]
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_a_second_inheriting_gateway_edge_is_not_adopted(
        self, multi_tenant_row_security
    ):
        """A duplicate grant from another grantor sits beside the canonical row.

        PostgreSQL keeps both, and one carrying INHERIT hands the gateway the
        tenant role's privileges outright instead of making it SET ROLE.
        """
        tenant_id, schema, reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(f"GRANT {reader} TO {TILE} WITH INHERIT TRUE, SET TRUE")
                )

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert not state.reader_role_secure
            assert not state.adopted

            # And a re-run repairs it: nothing else removes the extra row, so
            # leaving it would make the tenant permanently unadoptable.
            refused = await run_adoption(engine, apply=True)
            assert tenant_id in refused.failures
            assert "will not rewrite" in refused.failures[tenant_id]
            assert not refused.ok
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_stray_reader_member_is_refused_with_a_remedy(
        self, multi_tenant_row_security
    ):
        tenant_id, schema, reader, _writer = _new_tenant()
        stray = f"w998_stray_{tenant_id.replace('-', '_')}"
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            # A member outside {provisioner, sandbox, tile} is a read path into
            # the tenant that nothing else in the report would show: ownership
            # and per-relation privileges are all still correct.
            async with engine.begin() as conn:
                await conn.execute(sa.text(f"CREATE ROLE {stray} NOLOGIN NOINHERIT"))
                await conn.execute(sa.text(f"GRANT {reader} TO {stray}"))

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert state.relations_not_owned_by_writer == 0
            assert state.relations_without_reader_select == 0
            assert not state.reader_role_secure
            assert not state.adopted

            refused = await run_adoption(engine, apply=True)
            assert tenant_id in refused.failures
            assert "will not rewrite" in refused.failures[tenant_id]
            assert not refused.ok
        finally:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f"DROP ROLE IF EXISTS {stray}"))
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_creator_membership_on_the_writer_is_refused(
        self, multi_tenant_row_security
    ):
        """PostgreSQL 16+ makes the role creator a direct member of the writer.

        A non-superuser CREATEROLE migrator replaying the fresh-cluster globals
        dump holds that edge on every restored writer, and the migration-owned
        `provision_tenant_data_schema` refuses an unexpected direct member
        outright. Adoption refuses first, with the remedy: its grantor is the
        bootstrap superuser so nobody else can revoke it, and at this point the
        tenant role owns nothing, so DROP ROLE and let provisioning recreate it.
        """
        tenant_id, schema, _reader, writer = _new_tenant()
        creator = f"w998_creator_{tenant_id.replace('-', '_')}"
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            async with engine.begin() as conn:
                await conn.execute(sa.text(f"CREATE ROLE {creator} NOLOGIN CREATEROLE"))
                await conn.execute(
                    sa.text(
                        f"CREATE ROLE {writer} NOLOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    )
                )
                await conn.execute(
                    sa.text(f"GRANT {writer} TO {creator} WITH ADMIN OPTION")
                )

            report = await run_adoption(engine, apply=True)
            assert tenant_id in report.failures
            assert "will not rewrite" in report.failures[tenant_id]
            assert "DROP ROLE" in report.failures[tenant_id]
            assert not report.ok
        finally:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f"DROP ROLE IF EXISTS {creator}"))
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_legacy_admin_option_membership_is_rewritten(
        self, multi_tenant_row_security
    ):
        """A globals dump from PostgreSQL 13-15 replays as `WITH ADMIN OPTION`.

        On 16+ that lands SET TRUE, which `provision_tenant_data_schema` rejects
        as not ADMIN-only — so every restored tenant whose roles came back from
        an older cluster would fail adoption. Checking `admin_option` alone was
        not enough to notice.
        """
        tenant_id, schema, reader, writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            async with engine.begin() as conn:
                for role in (reader, writer):
                    await conn.execute(
                        sa.text(
                            f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB "
                            "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                        )
                    )
                    await conn.execute(
                        sa.text(f"GRANT {role} TO {PROVISIONER} WITH ADMIN OPTION")
                    )

            async with engine.connect() as conn:
                options = (
                    await conn.execute(
                        sa.text(
                            "SELECT membership.set_option FROM pg_auth_members "
                            "AS membership "
                            "JOIN pg_roles AS granted ON granted.oid = membership.roleid "
                            "JOIN pg_roles AS member ON member.oid = membership.member "
                            "WHERE granted.rolname = :reader AND member.rolname = :owner"
                        ),
                        {"reader": reader, "owner": PROVISIONER},
                    )
                ).scalar_one()
            assert options is True, "fixture must reproduce the legacy grant shape"

            report = await run_adoption(engine, apply=True)
            assert report.failures == {}, report.failures
            assert report.ok

            async with engine.connect() as conn:
                for role in (reader, writer):
                    membership = (
                        await conn.execute(
                            sa.text(
                                "SELECT membership.admin_option, "
                                "membership.inherit_option, membership.set_option "
                                "FROM pg_auth_members AS membership "
                                "JOIN pg_roles AS granted "
                                "  ON granted.oid = membership.roleid "
                                "JOIN pg_roles AS member "
                                "  ON member.oid = membership.member "
                                "WHERE granted.rolname = :role "
                                "AND member.rolname = :owner"
                            ),
                            {"role": role, "owner": PROVISIONER},
                        )
                    ).one()
                    assert tuple(membership) == (True, False, False), role
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_writer_missing_one_schema_privilege_is_not_adopted(
        self, multi_tenant_row_security
    ):
        """`has_schema_privilege(role, schema, 'USAGE, CREATE')` is any-of."""
        tenant_id, schema, _reader, writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(f"REVOKE CREATE ON SCHEMA {schema} FROM {writer}")
                )

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert not state.schema_privileges_secure
            assert not state.adopted

            repaired = await run_adoption(engine, apply=True)
            assert repaired.failures == {}, repaired.failures
            assert repaired.ok
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_reader_create_on_the_tenant_schema_is_revoked(
        self, multi_tenant_row_security
    ):
        """CREATE on a read-only schema is a write path through two gateways.

        The sandbox and tile gateways SET ROLE to the reader, and the
        provisioning function grants USAGE without ever taking CREATE away.
        """
        tenant_id, schema, reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(f"GRANT CREATE ON SCHEMA {schema} TO {reader}")
                )

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert not state.schema_privileges_secure
            assert not state.adopted

            repaired = await run_adoption(engine, apply=True)
            assert repaired.failures == {}, repaired.failures
            assert repaired.ok

            async with engine.connect() as conn:
                can_create = (
                    await conn.execute(
                        sa.text(
                            "SELECT has_schema_privilege(:role, :schema, 'CREATE')"
                        ),
                        {"role": reader, "schema": schema},
                    )
                ).scalar_one()
            assert can_create is False
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_reader_write_privileges_on_relations_are_revoked(
        self, multi_tenant_row_security
    ):
        """SELECT present is not the same as SELECT only.

        The sandbox and tile gateways SET ROLE to the reader, so an INSERT the
        restore carried over is a write path into tenant data that the
        SELECT-presence check reported as fine.
        """
        tenant_id, schema, reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(f"GRANT INSERT, DELETE ON {schema}.parcels TO {reader}")
                )

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert state.relations_without_reader_select == 0
            assert state.relations_with_unsafe_acl == 1
            assert not state.adopted

            repaired = await run_adoption(engine, apply=True)
            assert repaired.failures == {}, repaired.failures
            assert repaired.ok

            async with engine.connect() as conn:
                privileges = (
                    await conn.execute(
                        sa.text(
                            "SELECT has_table_privilege(:role, :table, 'SELECT'), "
                            "has_table_privilege(:role, :table, 'INSERT'), "
                            "has_table_privilege(:role, :table, 'DELETE')"
                        ),
                        {"role": reader, "table": f"{schema}.parcels"},
                    )
                ).one()
            assert tuple(privileges) == (True, False, False)
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_grant_options_on_reader_privileges_are_cleared(
        self, multi_tenant_row_security
    ):
        """A grantable privilege is a delegation the gateways can use.

        The sandbox and tile logins SET ROLE to the reader; with GRANT OPTION on
        the schema and the relation, either can hand tenant reads to any role.
        """
        tenant_id, schema, reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        f"GRANT USAGE ON SCHEMA {schema} TO {reader} WITH GRANT OPTION"
                    )
                )
                await conn.execute(
                    sa.text(
                        f"GRANT SELECT ON {schema}.parcels TO {reader} "
                        "WITH GRANT OPTION"
                    )
                )

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert not state.schema_privileges_secure
            assert state.relations_with_unsafe_acl == 1
            assert not state.adopted

            repaired = await run_adoption(engine, apply=True)
            assert repaired.failures == {}, repaired.failures
            assert repaired.ok

            async with engine.connect() as conn:
                grantable = (
                    await conn.execute(
                        sa.text(
                            "SELECT count(*) FROM pg_namespace AS namespace "
                            "JOIN LATERAL aclexplode(namespace.nspacl) AS acl "
                            "  ON true "
                            "JOIN pg_roles AS grantee "
                            "  ON grantee.oid = acl.grantee "
                            "WHERE namespace.nspname = :schema "
                            "AND grantee.rolname = :reader AND acl.is_grantable"
                        ),
                        {"schema": schema, "reader": reader},
                    )
                ).scalar_one()
            assert grantable == 0
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_a_restored_routine_is_re_owned_and_taken_off_public(
        self, multi_tenant_row_security
    ):
        """Routines live in pg_proc, so no relation sweep sees them."""
        tenant_id, schema, reader, writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            # What pg_restore --no-owner --no-acl leaves: owned by the restore
            # login, executable by PUBLIC.
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        f"CREATE FUNCTION {schema}.parcel_count() RETURNS bigint "
                        "LANGUAGE sql AS $$ SELECT count(*) FROM "
                        f"{schema}.parcels $$"
                    )
                )

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert state.unsafe_routines == 1
            assert not state.adopted

            repaired = await run_adoption(engine, apply=True)
            assert repaired.failures == {}, repaired.failures
            assert repaired.ok

            async with engine.connect() as conn:
                owner, public_execute, reader_execute = (
                    await conn.execute(
                        sa.text(
                            "SELECT pg_get_userbyid(routine.proowner), "
                            "has_function_privilege('public', routine.oid, 'EXECUTE'), "
                            "has_function_privilege(:reader, routine.oid, 'EXECUTE') "
                            "FROM pg_proc AS routine "
                            "JOIN pg_namespace AS namespace "
                            "  ON namespace.oid = routine.pronamespace "
                            "WHERE namespace.nspname = :schema "
                            "AND routine.proname = 'parcel_count'"
                        ),
                        {"reader": reader, "schema": schema},
                    )
                ).one()
            assert owner == writer
            assert public_execute is False
            assert reader_execute is True
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_a_security_definer_routine_in_a_tenant_schema_is_refused(
        self, multi_tenant_row_security
    ):
        """Re-owning one would bless a body with no migration behind it."""
        tenant_id, schema, _reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        f"CREATE FUNCTION {schema}.planted() RETURNS void "
                        "LANGUAGE sql SECURITY DEFINER AS $$ SELECT NULL::void $$"
                    )
                )

            refused = await run_adoption(engine, apply=True)
            assert tenant_id in refused.failures
            assert "SECURITY DEFINER" in refused.failures[tenant_id]
            assert "SECURITY INVOKER" in refused.failures[tenant_id]
            assert not refused.ok
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_a_tenant_defined_type_is_re_owned(self, multi_tenant_row_security):
        """Types are in pg_type, so the relation pass never sees them."""
        tenant_id, schema, _reader, writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(f"CREATE TYPE {schema}.parcel_kind AS ENUM ('a', 'b')")
                )

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert state.unsafe_types == 1
            assert not state.adopted

            repaired = await run_adoption(engine, apply=True)
            assert repaired.failures == {}, repaired.failures
            assert repaired.ok

            async with engine.connect() as conn:
                owner = (
                    await conn.execute(
                        sa.text(
                            "SELECT pg_get_userbyid(type_row.typowner) "
                            "FROM pg_type AS type_row "
                            "JOIN pg_namespace AS namespace "
                            "  ON namespace.oid = type_row.typnamespace "
                            "WHERE namespace.nspname = :schema "
                            "AND type_row.typname = 'parcel_kind'"
                        ),
                        {"schema": schema},
                    )
                ).scalar_one()
            assert owner == writer
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_column_level_grants_are_revoked(self, multi_tenant_row_security):
        """Column grants live in pg_attribute; a table REVOKE ALL misses them."""
        tenant_id, schema, reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(f"GRANT UPDATE (name) ON {schema}.parcels TO {reader}")
                )

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert state.relations_with_unsafe_acl == 1
            assert not state.adopted

            repaired = await run_adoption(engine, apply=True)
            assert repaired.failures == {}, repaired.failures
            assert repaired.ok

            async with engine.connect() as conn:
                can_update = (
                    await conn.execute(
                        sa.text(
                            "SELECT has_column_privilege(:role, :table, 'name', 'UPDATE')"
                        ),
                        {"role": reader, "table": f"{schema}.parcels"},
                    )
                ).scalar_one()
            assert can_update is False
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_a_stray_grantee_on_the_tenant_schema_is_revoked(
        self, multi_tenant_row_security
    ):
        """USAGE on the schema is half of a path around the writer boundary."""
        tenant_id, schema, _reader, _writer = _new_tenant()
        stray = f"w998_nsp_{tenant_id.replace('-', '_')}"
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            async with engine.begin() as conn:
                await conn.execute(sa.text(f"CREATE ROLE {stray} NOLOGIN"))
                await conn.execute(
                    sa.text(f"GRANT USAGE, CREATE ON SCHEMA {schema} TO {stray}")
                )

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert not state.schema_privileges_secure
            assert not state.adopted

            repaired = await run_adoption(engine, apply=True)
            assert repaired.failures == {}, repaired.failures
            assert repaired.ok

            async with engine.connect() as conn:
                usage = (
                    await conn.execute(
                        sa.text("SELECT has_schema_privilege(:role, :schema, 'USAGE')"),
                        {"role": stray, "schema": schema},
                    )
                ).scalar_one()
            assert usage is False
        finally:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f"DROP OWNED BY {stray}"))
                await conn.execute(sa.text(f"DROP ROLE IF EXISTS {stray}"))
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_default_privileges_for_any_grantee_are_cleared(
        self, multi_tenant_row_security
    ):
        """A default ACL hands out privileges on relations that do not exist yet."""
        tenant_id, schema, _reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} "
                        "GRANT SELECT ON TABLES TO PUBLIC"
                    )
                )
                await conn.execute(
                    sa.text(
                        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} "
                        "GRANT USAGE ON SEQUENCES TO PUBLIC"
                    )
                )
                # One owned by the tenant writer, which the migrator can only
                # assume inside the adoption window.
                await conn.execute(sa.text(f"SET LOCAL ROLE {_writer}"))
                await conn.execute(
                    sa.text(
                        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} "
                        "GRANT SELECT ON TABLES TO PUBLIC"
                    )
                )
                await conn.execute(sa.text("RESET ROLE"))
                # Functions carry a built-in PUBLIC EXECUTE that aclexplode
                # reports alongside the added grantee; revoking it would leave a
                # subtractive entry nothing here could reset.
                await conn.execute(
                    sa.text(
                        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} "
                        f"GRANT EXECUTE ON FUNCTIONS TO {_reader}"
                    )
                )

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert state.unexpected_default_acls == 4
            assert not state.adopted

            repaired = await run_adoption(engine, apply=True)
            assert repaired.failures == {}, repaired.failures
            assert repaired.ok
            async with engine.connect() as conn:
                assert (
                    await tenant_ownership_state(conn, tenant_id)
                ).unexpected_default_acls == 0
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_a_stray_grantee_on_a_tenant_relation_is_revoked(
        self, multi_tenant_row_security
    ):
        """A named role with its own grant needs neither tenant role."""
        tenant_id, schema, _reader, _writer = _new_tenant()
        stray = f"w998_stray_{tenant_id.replace('-', '_')}"
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            async with engine.begin() as conn:
                await conn.execute(sa.text(f"CREATE ROLE {stray} NOLOGIN"))
                await conn.execute(
                    sa.text(f"GRANT SELECT ON {schema}.parcels TO {stray}")
                )

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert state.relations_with_unsafe_acl == 1
            assert not state.adopted

            repaired = await run_adoption(engine, apply=True)
            assert repaired.failures == {}, repaired.failures
            assert repaired.ok

            async with engine.connect() as conn:
                stray_select = (
                    await conn.execute(
                        sa.text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                        {"role": stray, "table": f"{schema}.parcels"},
                    )
                ).scalar_one()
            assert stray_select is False
        finally:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f"DROP OWNED BY {stray}"))
                await conn.execute(sa.text(f"DROP ROLE IF EXISTS {stray}"))
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_public_grants_on_tenant_relations_are_revoked(
        self, multi_tenant_row_security
    ):
        """PUBLIC reaches the reader, and everyone else with schema USAGE."""
        tenant_id, schema, reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(f"GRANT SELECT, INSERT ON {schema}.parcels TO PUBLIC")
                )

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert state.relations_with_unsafe_acl == 1
            assert not state.adopted

            repaired = await run_adoption(engine, apply=True)
            assert repaired.failures == {}, repaired.failures
            assert repaired.ok

            async with engine.connect() as conn:
                public_select = (
                    await conn.execute(
                        sa.text(
                            "SELECT has_table_privilege('public', :table, 'SELECT')"
                        ),
                        {"table": f"{schema}.parcels"},
                    )
                ).scalar_one()
                reader_select = (
                    await conn.execute(
                        sa.text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                        {"role": reader, "table": f"{schema}.parcels"},
                    )
                ).scalar_one()
            assert public_select is False
            assert reader_select is True
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_legacy_reader_default_privileges_are_not_adopted(
        self, multi_tenant_row_security
    ):
        """The pre-0019 helper's ALTER DEFAULT PRIVILEGES entry is a live grant.

        Nothing else in the report sees it: ownership and per-relation
        privileges are all correct, and it still hands the reader access to
        every table the writer creates next.
        """
        tenant_id, schema, reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            assert (await run_adoption(engine, apply=True)).ok

            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} "
                        f"GRANT SELECT ON TABLES TO {reader}"
                    )
                )

            async with engine.connect() as conn:
                state = await tenant_ownership_state(conn, tenant_id)
            assert state.unexpected_default_acls == 1
            assert state.relations_not_owned_by_writer == 0
            assert not state.adopted

            repaired = await run_adoption(engine, apply=True)
            assert repaired.failures == {}, repaired.failures
            assert repaired.ok
            async with engine.connect() as conn:
                assert (
                    await tenant_ownership_state(conn, tenant_id)
                ).unexpected_default_acls == 0
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_missing_provisioner_grant_is_reported_and_re_granted(self):
        """Globals replay restores the role; it restores none of its grants."""
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                assert await missing_provisioner_grants(conn) == []

            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(f"REVOKE USAGE ON SCHEMA catalog FROM {PROVISIONER}")
                )

            async with engine.connect() as conn:
                assert await missing_provisioner_grants(conn) == [
                    "USAGE on schema catalog"
                ]

            dry_run = await run_adoption(engine, apply=False)
            assert dry_run.provisioner_grants_missing == ["USAGE on schema catalog"]
            assert not dry_run.ok
            assert "is missing USAGE on schema catalog" in format_report(dry_run)

            applied = await run_adoption(engine, apply=True)
            assert applied.provisioner_grants_missing == []
            assert applied.ok
        finally:
            # Self-healing above, but a failed assertion must not leave the
            # worker's database unable to provision a tenant.
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(f"GRANT USAGE ON SCHEMA catalog TO {PROVISIONER}")
                )
            await engine.dispose()

    async def test_a_grantable_provisioner_privilege_is_reported_and_cleared(self):
        """The provisioner is reachable only through SECURITY DEFINER code.

        A grantable privilege there is a delegation nothing else in the report
        would show.
        """
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                assert await missing_provisioner_grants(conn) == []

            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        f"GRANT USAGE ON SCHEMA catalog TO {PROVISIONER} "
                        "WITH GRANT OPTION"
                    )
                )

            async with engine.connect() as conn:
                assert await missing_provisioner_grants(conn) == [
                    "USAGE on schema catalog is grantable"
                ]

            applied = await run_adoption(engine, apply=True)
            assert applied.provisioner_grants_missing == []
            assert applied.ok
        finally:
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        "REVOKE GRANT OPTION FOR USAGE ON SCHEMA catalog "
                        f"FROM {PROVISIONER}"
                    )
                )
                await conn.execute(
                    sa.text(f"GRANT USAGE ON SCHEMA catalog TO {PROVISIONER}")
                )
            await engine.dispose()

    async def test_extra_proconfig_on_a_boundary_function_is_refused(self):
        """`SET role` beside a correct search_path changes what the body runs as."""
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(
                        sa.text(
                            "ALTER FUNCTION catalog.provision_tenant_data_schema(uuid) "
                            "SET statement_timeout = '1s'"
                        )
                    )
                    with pytest.raises(RuntimeError, match="search_path"):
                        await secure_boundary_functions(conn)
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_another_databases_tenant_roles_do_not_fail_validation(self):
        """Roles are cluster objects; catalog.tenants is not.

        A cluster hosting a second GeoLens database has its tenant roles and
        gateway edges visible from here with no matching row in this database's
        catalog.tenants. Judging those would make each database unadoptable
        because the other exists — which is exactly what the whole suite hits
        under xdist, every worker being another database. Rolled back.
        """
        foreign = f"geolens_writer_t_{uuid.uuid4().hex[:8]}_0000_0000_0000_000000000000"
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(
                        sa.text(
                            f"CREATE ROLE {foreign} NOLOGIN NOSUPERUSER NOCREATEDB "
                            "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                        )
                    )
                    await conn.execute(
                        sa.text(
                            f"GRANT {foreign} TO {WRITER_GATEWAY} "
                            "WITH INHERIT FALSE, SET TRUE"
                        )
                    )
                    await conn.execute(sa.text(CLUSTER_ROLE_VALIDATE_SQL))
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_healthy_cluster_topology_reports_no_error(self):
        engine = _make_engine()
        try:
            assert await cluster_topology_error(engine) is None
        finally:
            await engine.dispose()


# ---------------------------------------------------------------------------
# B: a second run is a no-op
# ---------------------------------------------------------------------------


class TestAdoptionIsIdempotent:
    """B: re-running changes nothing, and says so."""

    async def test_second_run_leaves_the_catalog_byte_identical(
        self, multi_tenant_row_security
    ):
        tenant_id, schema, _reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            first = await run_adoption(engine, apply=True)
            assert first.failures == {}, first.failures
            snapshot_after_first = await _catalog_snapshot(engine, tenant_id)

            second = await run_adoption(engine, apply=True)
            assert second.failures == {}, second.failures
            assert second.ok
            snapshot_after_second = await _catalog_snapshot(engine, tenant_id)

            assert snapshot_after_second == snapshot_after_first

            # The report distinguishes "already adopted" from "just adopted",
            # which is what tells an operator a re-run did nothing.
            before_states = {state.tenant_id: state for state in second.before}
            assert before_states[tenant_id].adopted
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_dry_run_makes_no_changes(self, multi_tenant_row_security):
        tenant_id, schema, _reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            snapshot_before = await _catalog_snapshot(engine, tenant_id)

            report = await run_adoption(engine, apply=False)
            assert not report.applied
            # A dry run over an unadopted tenant reports pending work, which is
            # the non-zero exit an operator can script against.
            assert not report.ok

            assert await _catalog_snapshot(engine, tenant_id) == snapshot_before
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()


# ---------------------------------------------------------------------------
# C: the dump-restore case — functions already present, wide open
# ---------------------------------------------------------------------------


class TestAdoptionWithRestoredBoundaryFunctions:
    """C: no CREATE FUNCTION collision, and the PUBLIC grant goes away."""

    async def test_restored_functions_are_re_owned_and_re_restricted(
        self, multi_tenant_row_security
    ):
        tenant_id, schema, _reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            await _break_boundary_functions(engine)

            async with engine.connect() as conn:
                broken = await boundary_function_states(conn)
            assert len(broken) == len(BOUNDARY_FUNCTIONS)
            assert all(state.public_execute for state in broken)
            assert all(state.owner != PROVISIONER for state in broken)
            assert not any(state.secured for state in broken)

            report = await run_adoption(engine, apply=True)
            assert report.failures == {}, report.failures
            assert report.ok

            async with engine.connect() as conn:
                repaired = await boundary_function_states(conn)
                after = await tenant_ownership_state(conn, tenant_id)
            assert all(state.secured for state in repaired)
            assert all(state.owner == PROVISIONER for state in repaired)
            assert not any(state.public_execute for state in repaired)
            assert after.adopted
        finally:
            await _restore_boundary_functions(engine)
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_a_non_superuser_migrator_can_transfer_ownership(self):
        """The documented CREATEROLE migrator, not just a bundled superuser.

        `ALTER FUNCTION ... OWNER TO` needs the incoming owner to hold CREATE on
        the containing schema, which the provisioner deliberately does not have.
        A superuser is exempt from neither requirement but satisfies both by
        fiat, so this path only shows up on a managed provider.

        Everything here runs in one transaction that is rolled back: the role
        and its membership in the provisioner are cluster objects that every
        other xdist worker's database shares, and an uncommitted grant is
        invisible to them.
        """
        migrator = f"w998_mig_{uuid.uuid4().hex[:12]}"
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(
                        sa.text(f"CREATE ROLE {migrator} NOSUPERUSER CREATEROLE")
                    )
                    await conn.execute(
                        sa.text(
                            f"GRANT CREATE, USAGE ON SCHEMA catalog TO {migrator} "
                            "WITH GRANT OPTION"
                        )
                    )
                    await conn.execute(
                        sa.text(f"GRANT {PROVISIONER} TO {migrator} WITH INHERIT TRUE")
                    )
                    # What pg_restore --no-owner leaves behind.
                    for name in BOUNDARY_FUNCTIONS:
                        await conn.execute(
                            sa.text(
                                f"ALTER FUNCTION catalog.{name}(uuid) "
                                f"OWNER TO {migrator}"
                            )
                        )
                        await conn.execute(
                            sa.text(
                                f"GRANT EXECUTE ON FUNCTION catalog.{name}(uuid) "
                                "TO PUBLIC"
                            )
                        )

                    await conn.execute(sa.text(f"SET LOCAL ROLE {migrator}"))
                    assert not (
                        await conn.execute(
                            sa.text(
                                "SELECT has_schema_privilege("
                                ":provisioner, 'catalog', 'CREATE')"
                            ),
                            {"provisioner": PROVISIONER},
                        )
                    ).scalar_one()

                    repaired = await secure_boundary_functions(conn)
                    assert all(state.secured for state in repaired), repaired

                    # The borrowed schema privilege is given back, not kept.
                    assert not (
                        await conn.execute(
                            sa.text(
                                "SELECT has_schema_privilege("
                                ":provisioner, 'catalog', 'CREATE')"
                            ),
                            {"provisioner": PROVISIONER},
                        )
                    ).scalar_one()
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_role_creation_leaves_the_creator_able_to_use_the_role(self):
        """What CLUSTER_ROLE_CREATE_SQL compensates for, pinned to the server.

        On a fresh cluster with no globals dump, the non-superuser CREATEROLE
        migrator creates the provisioner itself. PostgreSQL 16+ makes it an
        ADMIN member of the new role with INHERIT FALSE and SET FALSE, which is
        not the same as holding that role's privileges — and the boundary
        function repair needs the privileges. The real provisioner cannot be
        dropped and recreated on a shared cluster, so this pins the server
        behaviour and the compensating grant on a stand-in, in a transaction
        that is rolled back.
        """
        creator = f"w998_creator_{uuid.uuid4().hex[:12]}"
        created = f"w998_created_{uuid.uuid4().hex[:12]}"
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(
                        sa.text(f"CREATE ROLE {creator} NOLOGIN NOSUPERUSER CREATEROLE")
                    )
                    await conn.execute(sa.text(f"SET LOCAL ROLE {creator}"))
                    await conn.execute(sa.text(f"CREATE ROLE {created} NOLOGIN"))

                    async def creator_holds_privileges() -> bool:
                        return (
                            await conn.execute(
                                sa.text(
                                    "SELECT pg_has_role(:creator, :created, 'USAGE')"
                                ),
                                {"creator": creator, "created": created},
                            )
                        ).scalar_one()

                    assert not await creator_holds_privileges(), (
                        "the automatic creator membership is expected to be "
                        "ADMIN-only; if PostgreSQL changed this, the "
                        "compensating grant in CLUSTER_ROLE_CREATE_SQL is dead code"
                    )

                    # No ADMIN in the compensating grant: PostgreSQL refuses
                    # "ADMIN option cannot be granted back to your own grantor",
                    # and the automatic membership already carries it.
                    await conn.execute(
                        sa.text(
                            f"GRANT {created} TO {creator} WITH INHERIT TRUE, SET TRUE"
                        )
                    )
                    assert await creator_holds_privileges()
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_the_bootstrap_membership_is_handed_back(self):
        """Only the usable edge this run granted, and only that one.

        The automatic creator membership is left alone on purpose: its grantor
        is the bootstrap superuser, a member's plain REVOKE of it is a no-op,
        and on a managed provider no customer role can assume that grantor. The
        guards tolerate its exact shape instead. Rolled back.
        """
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:

                    async def edges() -> list[tuple]:
                        rows = await conn.execute(
                            sa.text(
                                "SELECT pg_get_userbyid(membership.grantor), "
                                "membership.admin_option "
                                "FROM pg_auth_members AS membership "
                                "JOIN pg_roles AS granted "
                                "  ON granted.oid = membership.roleid "
                                "JOIN pg_roles AS member "
                                "  ON member.oid = membership.member "
                                "WHERE granted.rolname = :owner "
                                "AND member.rolname = current_user"
                            ),
                            {"owner": PROVISIONER},
                        )
                        return [tuple(row) for row in rows]

                    assert await edges() == []
                    await conn.execute(
                        sa.text(
                            f"GRANT {PROVISIONER} TO current_user "
                            "WITH INHERIT TRUE, SET TRUE"
                        )
                    )
                    assert len(await edges()) == 1

                    await conn.execute(sa.text(RELEASE_PROVISIONER_EDGE_SQL))
                    assert await edges() == []

                    # An ADMIN edge is the creator's, or somebody's decision.
                    # Either way it stays.
                    await conn.execute(
                        sa.text(
                            f"GRANT {PROVISIONER} TO current_user WITH ADMIN OPTION"
                        )
                    )
                    await conn.execute(sa.text(RELEASE_PROVISIONER_EDGE_SQL))
                    assert [admin for _grantor, admin in await edges()] == [True]
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_a_creator_shaped_edge_on_another_login_is_refused(self):
        """fix(#998 codex r44): ADMIN alone can re-arm itself into a usable
        edge, so the creator shape is only safe on the login running adoption.
        The refusal names DROP ROLE, the one remedy a managed platform allows.
        """
        retired = f"w998_retired_{uuid.uuid4().hex[:12]}"
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(sa.text(f"CREATE ROLE {retired} LOGIN"))
                    await conn.execute(
                        sa.text(
                            f"GRANT {TILE} TO {retired} "
                            "WITH ADMIN TRUE, INHERIT FALSE, SET FALSE"
                        )
                    )
                    with pytest.raises(
                        DBAPIError, match="keeps the creator membership"
                    ):
                        await conn.execute(sa.text(CLUSTER_ROLE_VALIDATE_SQL))
                finally:
                    await transaction.rollback()
                await conn.execute(sa.text(f"DROP ROLE IF EXISTS {retired}"))
        finally:
            await engine.dispose()

    async def test_a_foreign_granted_boundary_acl_is_refused(self):
        """fix(#998 codex r44): an EXECUTE entry granted by a third role does
        not re-attribute on owner transfer and a non-grantor's REVOKE is a
        no-op, so repairing over it would silently leave the grant standing.
        """
        grantor = f"w998_grantor_{uuid.uuid4().hex[:12]}"
        grantee = f"w998_grantee_{uuid.uuid4().hex[:12]}"
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(sa.text(f"CREATE ROLE {grantor} NOLOGIN"))
                    await conn.execute(sa.text(f"CREATE ROLE {grantee} NOLOGIN"))
                    name = BOUNDARY_FUNCTIONS[0]
                    await conn.execute(
                        sa.text(f"GRANT USAGE ON SCHEMA catalog TO {grantor}")
                    )
                    await conn.execute(
                        sa.text(
                            f"GRANT EXECUTE ON FUNCTION catalog.{name}(uuid) "
                            f"TO {grantor} WITH GRANT OPTION"
                        )
                    )
                    await conn.execute(sa.text(f"SET LOCAL ROLE {grantor}"))
                    await conn.execute(
                        sa.text(
                            f"GRANT EXECUTE ON FUNCTION catalog.{name}(uuid) "
                            f"TO {grantee}"
                        )
                    )
                    await conn.execute(sa.text("RESET ROLE"))
                    with pytest.raises(DBAPIError, match="granted by"):
                        await secure_boundary_functions(conn)
                finally:
                    await transaction.rollback()
                await conn.execute(sa.text(f"DROP ROLE IF EXISTS {grantee}"))
                await conn.execute(sa.text(f"DROP ROLE IF EXISTS {grantor}"))
        finally:
            await engine.dispose()

    async def test_a_migrator_without_provisioner_privileges_is_told_what_to_run(self):
        migrator = f"w998_mig_{uuid.uuid4().hex[:12]}"
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(
                        sa.text(f"CREATE ROLE {migrator} NOSUPERUSER CREATEROLE")
                    )
                    await conn.execute(
                        sa.text(
                            f"GRANT CREATE, USAGE ON SCHEMA catalog TO {migrator} "
                            "WITH GRANT OPTION"
                        )
                    )
                    for name in BOUNDARY_FUNCTIONS:
                        await conn.execute(
                            sa.text(
                                f"ALTER FUNCTION catalog.{name}(uuid) "
                                f"OWNER TO {migrator}"
                            )
                        )
                    await conn.execute(sa.text(f"SET LOCAL ROLE {migrator}"))

                    with pytest.raises(
                        DBAPIError, match="does not hold the privileges"
                    ):
                        await secure_boundary_functions(conn)
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_a_substituted_function_body_is_refused(self):
        """A `(uuid)` SECURITY DEFINER function is not automatically the one.

        Adoption gives the boundary functions to the provisioner and grants the
        control role execution, so it refuses anything that is not structurally
        what the migrations install. Rolled back either way.
        """
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(
                        sa.text(
                            "CREATE OR REPLACE FUNCTION "
                            "catalog.provision_tenant_data_schema(p_tenant_id uuid) "
                            "RETURNS void LANGUAGE sql SECURITY DEFINER "
                            "SET search_path = pg_catalog AS $$ SELECT NULL::void $$"
                        )
                    )
                    with pytest.raises(RuntimeError, match="not plpgsql"):
                        await secure_boundary_functions(conn)
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_a_direct_execute_grant_outside_the_pair_is_revoked(self):
        """REVOKE … FROM PUBLIC does not touch a grant to a named role."""
        stray = f"w998_stray_{uuid.uuid4().hex[:12]}"
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(sa.text(f"CREATE ROLE {stray} NOLOGIN"))
                    for name in BOUNDARY_FUNCTIONS:
                        await conn.execute(
                            sa.text(
                                f"GRANT EXECUTE ON FUNCTION catalog.{name}(uuid) "
                                f"TO {stray}"
                            )
                        )

                    before = await boundary_function_states(conn)
                    assert all(state.unexpected_grantees == 1 for state in before)
                    assert not any(state.secured for state in before)

                    repaired = await secure_boundary_functions(conn)
                    assert all(state.unexpected_grantees == 0 for state in repaired)
                    assert all(state.secured for state in repaired)
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_a_grantable_execute_for_the_control_role_is_downgraded(self):
        """A re-GRANT does not clear an existing GRANT OPTION."""
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    for name in BOUNDARY_FUNCTIONS:
                        await conn.execute(
                            sa.text(
                                f"GRANT EXECUTE ON FUNCTION catalog.{name}(uuid) "
                                f"TO {CONTROL} WITH GRANT OPTION"
                            )
                        )
                    before = await boundary_function_states(conn)
                    assert all(state.unexpected_grantees == 1 for state in before)
                    assert not any(state.secured for state in before)

                    repaired = await secure_boundary_functions(conn)
                    assert all(state.secured for state in repaired)
                    assert all(state.control_execute for state in repaired)
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_missing_function_refuses_instead_of_installing_one(self):
        """Bodies belong to the migrations; adoption never writes one."""
        from app.core.db.tenant_adoption import secure_boundary_functions

        engine = _make_engine()
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        "ALTER FUNCTION catalog.deprovision_tenant_data_schema(uuid) "
                        "RENAME TO w998_absent_boundary_function"
                    )
                )
                with pytest.raises(RuntimeError, match="alembic upgrade heads"):
                    await secure_boundary_functions(conn)
        finally:
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        "ALTER FUNCTION catalog.w998_absent_boundary_function(uuid) "
                        "RENAME TO deprovision_tenant_data_schema"
                    )
                )
            await _restore_boundary_functions(engine)
            await engine.dispose()


# ---------------------------------------------------------------------------
# D: the boundary is read from the database
# ---------------------------------------------------------------------------


class TestLiveTenantBoundary:
    """D: introspected, never enumerated from a frozen migration constant."""

    async def test_boundary_matches_the_constant_that_drives_rls(self):
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                boundary = await live_tenant_boundary(conn)
        finally:
            await engine.dispose()

        stamped = {table.name for table in boundary if table.has_stamping_trigger}
        assert stamped == set(RLS_TABLES), (
            "The live insert-stamping boundary and app.core.db.rls.RLS_TABLES "
            "have diverged. A table stamped in the database but missing from "
            "RLS_TABLES never gets RLS enabled at boot."
        )
        assert boundary_drift(boundary) == ([], [])

        # 0018's frozen tuple is six tables; the live boundary outgrew it long
        # ago. Anything reading that constant would under-report by three.
        assert len(stamped) > 6

    async def test_a_disabled_stamping_trigger_is_not_a_live_boundary(self):
        """`tgenabled = 'D'` keeps the name and stamps nothing.

        Nothing at boot re-enables it, so an insert on that table lands with no
        `tenant_id` on any path that reaches it.
        """
        engine = _make_engine()
        table = "embed_tokens"
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        f"ALTER TABLE catalog.{table} "
                        "DISABLE TRIGGER trg_stamp_current_tenant_on_insert"
                    )
                )

            async with engine.connect() as conn:
                boundary = await live_tenant_boundary(conn)
            state = next(entry for entry in boundary if entry.name == table)
            assert not state.has_stamping_trigger
            assert state.stamping_trigger_inert

            # It is in RLS_TABLES but no longer stamped, so it reads as drift.
            assert boundary_drift(boundary) == ([], [table])

            report = await run_adoption(engine, apply=False)
            assert not report.ok
            assert "does not stamp" in format_report(report)
        finally:
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        f"ALTER TABLE catalog.{table} "
                        "ENABLE TRIGGER trg_stamp_current_tenant_on_insert"
                    )
                )
            await engine.dispose()

    async def test_a_trigger_on_the_wrong_event_is_not_a_live_boundary(self):
        """The name alone proves nothing about what fires.

        A trigger recreated under the boundary name but wired to the wrong
        timing stamps no ordinary insert, and nothing at boot notices. Rolled
        back, so the worker's schema is unchanged either way.
        """
        engine = _make_engine()
        table = "embed_tokens"
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(
                        sa.text(
                            f"DROP TRIGGER trg_stamp_current_tenant_on_insert "
                            f"ON catalog.{table}"
                        )
                    )
                    await conn.execute(
                        sa.text(
                            "CREATE TRIGGER trg_stamp_current_tenant_on_insert "
                            f"AFTER INSERT ON catalog.{table} FOR EACH ROW "
                            "EXECUTE FUNCTION catalog.stamp_current_tenant_on_insert()"
                        )
                    )

                    boundary = await live_tenant_boundary(conn)
                    state = next(entry for entry in boundary if entry.name == table)
                    assert not state.has_stamping_trigger
                    assert state.stamping_trigger_inert
                    assert boundary_drift(boundary) == ([], [table])
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_a_stubbed_stamping_function_is_reported(self):
        """The trigger can be perfect and still stamp nothing.

        Every table keeps its BEFORE INSERT trigger on the right function; the
        function just stops writing NEW.tenant_id. Rolled back.
        """
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    assert await stamping_function_shape(conn) is None
                    await conn.execute(
                        sa.text(
                            "CREATE OR REPLACE FUNCTION "
                            "catalog.stamp_current_tenant_on_insert() "
                            "RETURNS trigger LANGUAGE plpgsql "
                            "SET search_path = pg_catalog, catalog "
                            "AS $$ BEGIN RETURN NEW; END $$"
                        )
                    )
                    reason = await stamping_function_shape(conn)
                    assert reason is not None
                    assert "stamps nothing" in reason
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_a_conditional_stamping_trigger_is_not_a_live_boundary(self):
        """A WHEN clause leaves the rows it excludes unstamped."""
        engine = _make_engine()
        table = "embed_tokens"
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(
                        sa.text(
                            "DROP TRIGGER trg_stamp_current_tenant_on_insert "
                            f"ON catalog.{table}"
                        )
                    )
                    await conn.execute(
                        sa.text(
                            "CREATE TRIGGER trg_stamp_current_tenant_on_insert "
                            f"BEFORE INSERT ON catalog.{table} FOR EACH ROW "
                            "WHEN (NEW.tenant_id IS NOT NULL) "
                            "EXECUTE FUNCTION catalog.stamp_current_tenant_on_insert()"
                        )
                    )
                    boundary = await live_tenant_boundary(conn)
                    state = next(entry for entry in boundary if entry.name == table)
                    assert not state.has_stamping_trigger
                    assert state.stamping_trigger_inert
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_a_security_definer_stamping_function_is_reported(self):
        """0018 installs it SECURITY INVOKER; it fires on every insert."""
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(
                        sa.text(
                            "ALTER FUNCTION catalog.stamp_current_tenant_on_insert() "
                            "SECURITY DEFINER"
                        )
                    )
                    reason = await stamping_function_shape(conn)
                    assert reason is not None
                    assert "SECURITY DEFINER" in reason
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_an_isolation_policy_narrowed_off_public_is_reported(self):
        """Every role outside a named list takes the implicit RLS deny."""
        engine = _make_engine()
        table = "embed_tokens"
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(
                        sa.text(
                            f"ALTER POLICY tenant_isolation_{table} "
                            f"ON catalog.{table} TO geolens_reader"
                        )
                    )
                    boundary = await live_tenant_boundary(conn)
                    state = next(entry for entry in boundary if entry.name == table)
                    assert not state.isolation_policy_intact
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_a_missing_isolation_policy_is_reported(self):
        """Boot enables RLS; nothing recreates the rule RLS enforces."""
        engine = _make_engine()
        table = "embed_tokens"
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(
                        sa.text(
                            f"DROP POLICY tenant_isolation_{table} ON catalog.{table}"
                        )
                    )
                    boundary = await live_tenant_boundary(conn)
                    state = next(entry for entry in boundary if entry.name == table)
                    assert not state.isolation_policy_intact
                    assert rls_gaps(boundary, tenants_present=False) == [
                        f"{table} (tenant_isolation policy missing or altered)"
                    ]
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_an_altered_isolation_policy_is_reported(self):
        """A permissive rewrite returns every tenant's rows and looks intact."""
        engine = _make_engine()
        table = "embed_tokens"
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(
                        sa.text(
                            f"ALTER POLICY tenant_isolation_{table} "
                            f"ON catalog.{table} USING (true)"
                        )
                    )
                    boundary = await live_tenant_boundary(conn)
                    state = next(entry for entry in boundary if entry.name == table)
                    assert not state.isolation_policy_intact
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_an_extra_restrictive_policy_is_reported(self):
        """Restrictive policies AND: one `USING (false)` denies everything."""
        engine = _make_engine()
        table = "embed_tokens"
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(
                        sa.text(
                            f"CREATE POLICY w998_restrictive ON catalog.{table} "
                            "AS RESTRICTIVE USING (false)"
                        )
                    )
                    boundary = await live_tenant_boundary(conn)
                    state = next(entry for entry in boundary if entry.name == table)
                    assert not state.isolation_policy_intact
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_an_extra_permissive_policy_is_reported(self):
        """Permissive policies OR: one `USING (true)` beside the rule undoes it."""
        engine = _make_engine()
        table = "embed_tokens"
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.execute(
                        sa.text(
                            f"CREATE POLICY w998_extra ON catalog.{table} USING (true)"
                        )
                    )
                    boundary = await live_tenant_boundary(conn)
                    state = next(entry for entry in boundary if entry.name == table)
                    assert not state.isolation_policy_intact
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    async def test_dormant_tenant_id_columns_are_reported_outside_the_boundary(self):
        """0037's ``dataset_refresh_runs.tenant_id`` is deliberately dormant.

        Reporting it as "tenant_id column only" is what lets an accidental
        omission be told apart from this intentional one.
        """
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                boundary = await live_tenant_boundary(conn)
        finally:
            await engine.dispose()

        dormant = {
            table.name
            for table in boundary
            if table.has_tenant_id and not table.has_stamping_trigger
        }
        assert "dataset_refresh_runs" in dormant
        assert dormant.isdisjoint(set(RLS_TABLES))


# ---------------------------------------------------------------------------
# The runbook recipe and the module it invokes
# ---------------------------------------------------------------------------


def test_runbook_documents_the_forward_only_recipe() -> None:
    """A rename that orphans the DR recipe must fail here, not mid-recovery."""
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")

    assert "python -m app.core.db.tenant_adoption --apply" in runbook
    # The destructive downgrade is documented as the thing NOT to reach for,
    # not as the recipe (#998).
    assert "#### Do not reach for `alembic downgrade 0016`" in runbook
    assert "uv run --no-dev alembic downgrade 0016" not in runbook


def test_module_is_runnable_as_documented() -> None:
    import importlib

    module = importlib.import_module("app.core.db.tenant_adoption")

    assert callable(module._main)
    parser = module._build_parser()
    assert parser.parse_args([]).apply is False
    assert parser.parse_args(["--apply"]).apply is True


# ---------------------------------------------------------------------------
# The success predicate covers everything the report surfaces
# ---------------------------------------------------------------------------


def _secured_function(name: str) -> BoundaryFunctionState:
    return BoundaryFunctionState(
        name=name,
        owner=PROVISIONER,
        security_definer=True,
        search_path_pinned=True,
        language="plpgsql",
        returns_void=True,
        body_markers_present=True,
        public_execute=False,
        control_execute=True,
        unexpected_grantees=0,
    )


def _clean_boundary() -> list[BoundaryTableState]:
    return [
        BoundaryTableState(
            name=name,
            has_stamping_trigger=True,
            stamping_trigger_present=True,
            has_tenant_id=True,
            rls_enabled=True,
            rls_forced=True,
            isolation_policy_intact=True,
        )
        for name in RLS_TABLES
    ]


def _adopted_tenant_state() -> TenantOwnershipState:
    return TenantOwnershipState(
        tenant_id="00000000-0000-0000-0000-000000000998",
        schema_name="data_t_00000000_0000_0000_0000_000000000998",
        schema_exists=True,
        schema_owner=PROVISIONER,
        reader_exists=True,
        writer_exists=True,
        relations=1,
        unsafe_routines=0,
        unsafe_types=0,
        unsafe_statistics=0,
        unsafe_collations=0,
        unowned_other_objects=0,
        foreign_grantors=0,
        relations_not_owned_by_writer=0,
        relations_without_reader_select=0,
        relations_with_unsafe_acl=0,
        unexpected_default_acls=0,
        reader_role_secure=True,
        writer_role_secure=True,
        schema_privileges_secure=True,
    )


def _report(**overrides) -> AdoptionReport:
    fields: dict = {
        "applied": False,
        "functions": [_secured_function(name) for name in BOUNDARY_FUNCTIONS],
        "boundary": _clean_boundary(),
        "before": [],
        "after": [],
        "failures": {},
        "cluster_topology": None,
        "stamping_function": None,
        "provisioner_grants_missing": [],
    }
    fields.update(overrides)
    # The report renders `after` against `before`, so a caller that overrides
    # only one of them still gets a coherent report.
    if "before" in overrides and "after" not in overrides:
        fields["after"] = fields["before"]
    return AdoptionReport(**fields)


class TestSuccessPredicate:
    """`ok` is the documented exit code, so it has to see every finding."""

    def test_clean_report_is_ok(self) -> None:
        assert _report().ok

    def test_missing_boundary_function_is_not_ok(self) -> None:
        """An absent function shortens the list; `all(...)` alone passes it."""
        report = _report(functions=[_secured_function(BOUNDARY_FUNCTIONS[0])])
        assert report.missing_functions == [BOUNDARY_FUNCTIONS[1]]
        assert not report.ok
        assert "MISSING" in format_report(report)

    def test_no_boundary_functions_at_all_is_not_ok(self) -> None:
        assert not _report(functions=[]).ok

    def test_refused_cluster_topology_is_not_ok(self) -> None:
        report = _report(cluster_topology="role geolens_tile_gateway is missing")
        assert not report.ok
        assert "NEEDS ATTENTION" in format_report(report)

    def test_missing_provisioner_grant_is_not_ok(self) -> None:
        report = _report(provisioner_grants_missing=["SELECT on catalog.tenants"])
        assert not report.ok
        assert "SELECT on catalog.tenants" in format_report(report)

    def test_stamped_table_missing_from_rls_tables_is_not_ok(self) -> None:
        """Boot never enables RLS on it, so the post-restore check must fail."""
        boundary = _clean_boundary() + [
            BoundaryTableState(
                name="w998_late_arrival",
                has_stamping_trigger=True,
                stamping_trigger_present=True,
                has_tenant_id=True,
                rls_enabled=True,
                rls_forced=True,
                isolation_policy_intact=True,
            )
        ]
        report = _report(boundary=boundary)
        assert boundary_drift(boundary) == (["w998_late_arrival"], [])
        assert not report.ok

    def test_row_security_off_with_tenants_present_is_not_ok(self) -> None:
        """A tenant-carrying control plane with RLS off has no isolation."""
        boundary = [
            BoundaryTableState(
                name=table.name,
                has_stamping_trigger=True,
                stamping_trigger_present=True,
                has_tenant_id=True,
                rls_enabled=False,
                rls_forced=False,
                isolation_policy_intact=True,
            )
            for table in _clean_boundary()
        ]
        report = _report(boundary=boundary, before=[_adopted_tenant_state()])
        assert report.rls_gaps
        assert not report.ok
        assert "NOT SAFE TO SERVE" in format_report(report)

    def test_row_security_off_with_no_tenants_is_ok(self) -> None:
        """Single-tenant is the default posture; RLS is correctly off there."""
        boundary = [
            BoundaryTableState(
                name=table.name,
                has_stamping_trigger=True,
                stamping_trigger_present=True,
                has_tenant_id=True,
                rls_enabled=False,
                rls_forced=False,
                isolation_policy_intact=True,
            )
            for table in _clean_boundary()
        ]
        report = _report(boundary=boundary)
        assert report.rls_gaps == []
        assert report.ok

    def test_row_security_without_force_is_not_ok(self) -> None:
        """The table owner bypasses a non-FORCEd policy in any mode."""
        boundary = [
            BoundaryTableState(
                name=table.name,
                has_stamping_trigger=True,
                stamping_trigger_present=True,
                has_tenant_id=True,
                rls_enabled=True,
                rls_forced=False,
                isolation_policy_intact=True,
            )
            for table in _clean_boundary()
        ]
        report = _report(boundary=boundary)
        assert report.rls_gaps
        assert not report.ok

    def test_inert_trigger_on_an_undeclared_table_is_not_ok(self) -> None:
        """The one combination neither drift direction can see.

        A newly tenant-scoped table absent from ``RLS_TABLES`` with its stamping
        trigger disabled is in neither ``live_only`` (the trigger does not fire)
        nor ``constant_only`` (the constant never named it), and has no row
        security to be missing. The disabled trigger has to be its own finding.
        """
        boundary = _clean_boundary() + [
            BoundaryTableState(
                name="w998_new_and_undeclared",
                has_stamping_trigger=False,
                stamping_trigger_present=True,
                has_tenant_id=True,
                rls_enabled=False,
                rls_forced=False,
                isolation_policy_intact=True,
            )
        ]
        report = _report(boundary=boundary)
        assert boundary_drift(boundary) == ([], [])
        assert report.rls_gaps == []
        assert report.inert_stamping_triggers == ["w998_new_and_undeclared"]
        assert not report.ok
        assert "does not stamp" in format_report(report)

    def test_declared_table_without_a_stamping_trigger_is_not_ok(self) -> None:
        """The other direction: inserts land with no tenant_id at all."""
        boundary = [table for table in _clean_boundary() if table.name != RLS_TABLES[0]]
        report = _report(boundary=boundary)
        assert boundary_drift(boundary) == ([], [RLS_TABLES[0]])
        assert not report.ok
